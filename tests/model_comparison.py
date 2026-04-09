"""
Model comparison — find which embedding model clears the 0.65 threshold.

Fetches topic TEXT from Postgres (expanded_description + subtopic descriptions),
re-embeds everything with each candidate model in-memory, scores all 300 TSV
articles, and prints a side-by-side comparison table.

NO schema changes. NO DB writes. Safe to run against production topics.

Run inside the backend container:
    docker compose exec backend bash -c "cd /app && PYTHONPATH=/app python tests/model_comparison.py"
"""

import asyncio
import csv
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer
from sqlalchemy import select

from app.db.models import Topic as DBTopic, TopicSubtopic as DBTopicSubtopic
from app.db.session import AsyncSessionLocal, engine

# ─── Config ───────────────────────────────────────────────────────────────────

DATASET_PATH = Path(__file__).parent / "testDataset.tsv"
THRESHOLD = 0.65

# TSV category → broad topic name (must match DB spelling exactly)
CATEGORY_TO_TOPIC = {
    "ai_regulation":           "Artificial Intelligence",
    "ai_healthcare":           "Artificial Intelligence",
    "ai_jobs":                 "Artificial Intelligence",
    "ai_research":             "Artificial Intelligence",
    "climate_policy":          "Climate Change",
    "climate_oceans":          "Climate Change",
    "climate_energy":          "Climate Change",
    "climate_disasters":       "Climate Change",
    "economy_trade":           "Global Economy",
    "economy_recession":       "Global Economy",
    "economy_markets":         "Global Economy",
    "economy_inflation":       "Global Economy",
    "space_research":          "Space Exploration",
    "space_policy":            "Space Exploration",
    "space_missions":          "Space Exploration",
    "space_commercialization": "Space Exploration",
    "health_systems":          "Public Health",
    "health_pandemic":         "Public Health",
    "health_mental":           "Public Health",
    "health_drugs":            "Public Health",
}

# Models to compare — loaded and unloaded one at a time to avoid OOM.
# All are symmetric cosine-similarity models; bigger dim = more expressive.
CANDIDATE_MODELS = [
    ("all-MiniLM-L6-v2",             384, "original baseline"),
    ("multi-qa-MiniLM-L6-cos-v1",    384, "384-dim, search-tuned"),
    ("all-mpnet-base-v2",            768, "general, high quality"),
    ("multi-qa-mpnet-base-cos-v1",   768, "search-tuned, 768-dim"),
    ("msmarco-distilbert-base-v4",   768, "MS MARCO retrieval"),
]

# ─── Helpers ──────────────────────────────────────────────────────────────────

def strip_html(text: str) -> str:
    return re.sub(r"<[^>]*>", "", text)


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 1e-9 else 0.0


# ─── DB fetch ─────────────────────────────────────────────────────────────────

async def _fetch_topic_texts() -> list[dict]:
    """Return list of {name, parent_text, subtopic_texts} dicts from Postgres."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DBTopic).where(DBTopic.is_active == True)
        )
        topic_rows = result.scalars().all()

    if not topic_rows:
        print("ERROR: No active topics found. Create topics via seed_topics.py first.")
        sys.exit(1)

    # Check we have expanded_description text
    missing_text = [t.name for t in topic_rows if not t.expanded_description]
    if missing_text:
        print(f"ERROR: Topics missing expanded_description: {missing_text}")
        sys.exit(1)

    topic_ids = [t.id for t in topic_rows]
    async with AsyncSessionLocal() as session:
        sub_result = await session.execute(
            select(DBTopicSubtopic).where(DBTopicSubtopic.topic_id.in_(topic_ids))
        )
        sub_rows = sub_result.scalars().all()

    subtopics_map: dict = defaultdict(list)
    for sub in sub_rows:
        subtopics_map[sub.topic_id].append(sub.description)

    return [
        {
            "name": row.name,
            "key": row.name.lower().strip(),
            "parent_text": row.expanded_description,
            "subtopic_texts": subtopics_map[row.id],
        }
        for row in topic_rows
    ]


def fetch_topic_texts() -> list[dict]:
    asyncio.run(engine.dispose())
    return asyncio.run(_fetch_topic_texts())


# ─── Dataset ──────────────────────────────────────────────────────────────────

def load_dataset() -> list[tuple[str, str, str, str]]:
    rows = []
    with open(DATASET_PATH, newline="", encoding="utf-8") as f:
        for row in csv.reader(f, delimiter="\t"):
            article_id, _type, category, headline, content = row
            rows.append((article_id, category, headline, content))
    return rows


# ─── Per-model benchmark ──────────────────────────────────────────────────────

def run_one_model(
    model_name: str,
    topic_data: list[dict],
    dataset: list[tuple[str, str, str, str]],
) -> dict | None:
    """Load model, embed everything, score, return metrics dict."""
    t_start = time.perf_counter()

    try:
        print(f"  Loading {model_name} ...", flush=True)
        t_load_start = time.perf_counter()
        model = SentenceTransformer(model_name)
        load_secs = time.perf_counter() - t_load_start
        print(f"  Loaded in {load_secs:.1f}s", flush=True)
    except Exception as exc:
        print(f"  SKIP: {model_name} — failed to load: {exc}")
        return None

    # ── Embed topics (batch per topic for subtopics) ──────────────────────────
    topics_embedded: dict[str, dict] = {}
    for t in topic_data:
        all_texts = [t["parent_text"]] + t["subtopic_texts"]
        vecs = model.encode(all_texts, batch_size=32, show_progress_bar=False)
        topics_embedded[t["key"]] = {
            "parent": vecs[0],
            "subtopics": vecs[1:],
        }

    # ── Embed all articles at once (much faster than one-by-one) ─────────────
    article_texts = [
        f"{headline}. {strip_html(content)[:2000]}"
        for _, _, headline, content in dataset
    ]
    print(f"  Encoding {len(article_texts)} articles ...", flush=True)
    t_encode_start = time.perf_counter()
    article_vecs = model.encode(article_texts, batch_size=64, show_progress_bar=False)
    encode_secs = time.perf_counter() - t_encode_start
    print(f"  Encoded in {encode_secs:.1f}s", flush=True)

    # ── Score ─────────────────────────────────────────────────────────────────
    top1_correct  = defaultdict(int)
    recall_caught = defaultdict(int)
    total_per     = defaultdict(int)
    all_true_scores: list[float] = []
    score_matrix: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for i, (article_id, true_cat, headline, _) in enumerate(dataset):
        true_key = CATEGORY_TO_TOPIC[true_cat].lower().strip()
        article_vec = article_vecs[i]

        scores: list[tuple[float, str]] = []
        for key, t in topics_embedded.items():
            sub_sims = [cosine_sim(article_vec, s) for s in t["subtopics"]]
            sub_sims.append(cosine_sim(article_vec, t["parent"]))
            score = max(sub_sims)
            scores.append((score, key))
            score_matrix[true_key][key].append(score)
        scores.sort(reverse=True)

        best_score, best_key = scores[0]
        true_score = next(s for s, k in scores if k == true_key)

        total_per[true_key] += 1
        all_true_scores.append(true_score)
        if best_key == true_key:
            top1_correct[true_key] += 1
        if true_score >= THRESHOLD:
            recall_caught[true_key] += 1

    n = len(dataset)
    avg = float(np.mean(all_true_scores))
    p50 = float(np.percentile(all_true_scores, 50))
    p75 = float(np.percentile(all_true_scores, 75))
    p90 = float(np.percentile(all_true_scores, 90))
    total_secs = time.perf_counter() - t_start

    return {
        "model": model_name,
        "top1":   sum(top1_correct.values())  / n,
        "recall": sum(recall_caught.values()) / n,
        "avg":    avg,
        "p50":    p50,
        "p75":    p75,
        "p90":    p90,
        "per_topic_top1":   dict(top1_correct),
        "per_topic_recall": dict(recall_caught),
        "per_topic_total":  dict(total_per),
        "score_matrix":     {k: dict(v) for k, v in score_matrix.items()},
        "load_secs":        load_secs,
        "encode_secs":      encode_secs,
        "total_secs":       total_secs,
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\nFetching topic text from Postgres ...", flush=True)
    topic_data = fetch_topic_texts()
    print(f"  Loaded {len(topic_data)} topics.")
    for t in topic_data:
        print(f"    {t['name']}  ({len(t['subtopic_texts'])} subtopics)")

    print("\nLoading dataset ...", flush=True)
    dataset = load_dataset()
    print(f"  {len(dataset)} articles loaded.")

    # Verify all expected topics are present
    expected = {v.lower().strip() for v in CATEGORY_TO_TOPIC.values()}
    present  = {t["key"] for t in topic_data}
    missing  = expected - present
    if missing:
        print(f"\nERROR: Missing topics (check spelling in DB): {missing}")
        sys.exit(1)

    results: list[dict] = []

    for model_name, dim, note in CANDIDATE_MODELS:
        print(f"\n{'─'*60}")
        print(f"  Model : {model_name}  ({dim}-dim)  — {note}")
        print(f"{'─'*60}")
        r = run_one_model(model_name, topic_data, dataset)
        if r:
            results.append(r)
            print(
                f"  Top-1={r['top1']:.1%}  Recall@{THRESHOLD}={r['recall']:.1%}  "
                f"avg={r['avg']:.4f}  p50={r['p50']:.4f}  p75={r['p75']:.4f}  p90={r['p90']:.4f}"
            )

    # ── Summary table ─────────────────────────────────────────────────────────
    col = 34
    print(f"\n\n{'='*80}")
    print("  MODEL COMPARISON SUMMARY")
    print(f"  Threshold : {THRESHOLD}  |  Articles : {len(dataset)}")
    print(f"{'='*80}")
    print(f"  {'Model':<{col}}  {'Top-1':>6}  {'Recall':>7}  {'Avg':>7}  {'p50':>7}  {'p75':>7}  {'p90':>7}  {'Load':>6}  {'Encode':>7}  {'Total':>6}")
    print(f"  {'-'*col}  {'------':>6}  {'-------':>7}  {'-------':>7}  {'-------':>7}  {'-------':>7}  {'-------':>7}  {'------':>6}  {'-------':>7}  {'------':>6}")
    best_recall = max(r["recall"] for r in results) if results else 0
    best_top1   = max(r["top1"]   for r in results) if results else 0
    for r in results:
        recall_mark = " ◄ best recall" if r["recall"] == best_recall else ""
        top1_mark   = " ◄ best top-1"  if r["top1"]   == best_top1 and r["recall"] != best_recall else ""
        print(
            f"  {r['model']:<{col}}  {r['top1']:>5.1%}  {r['recall']:>6.1%}  "
            f"{r['avg']:>7.4f}  {r['p50']:>7.4f}  {r['p75']:>7.4f}  {r['p90']:>7.4f}  "
            f"{r['load_secs']:>5.1f}s  {r['encode_secs']:>6.1f}s  {r['total_secs']:>5.1f}s"
            f"{recall_mark}{top1_mark}"
        )
    print(f"{'='*80}")

    # ── Per-topic breakdown + score matrix — printed for EVERY model ──────────
    for r in results:
        topic_keys = sorted(r["score_matrix"].keys())
        hdr = 22
        cw  = 8

        print(f"\n\n{'─'*72}")
        print(f"  DETAIL — {r['model']}")
        print(f"{'─'*72}")

        # Per-topic breakdown
        print(f"  {'Topic':<26}  {'Top-1':>6}  {'Recall':>7}  {'Caught':>8}")
        print(f"  {'-'*26}  {'------':>6}  {'-------':>7}  {'--------':>8}")
        for t in topic_data:
            k = t["key"]
            n = r["per_topic_total"].get(k, 0)
            if n == 0:
                continue
            t1 = r["per_topic_top1"].get(k, 0)
            rc = r["per_topic_recall"].get(k, 0)
            print(f"  {t['name']:<26}  {t1/n:>5.0%}  {rc/n:>6.0%}  {rc:>4}/{n:<4}")

        # Score matrix
        topic_labels = {k: k[:12] for k in topic_keys}
        print(f"\n  SCORE MATRIX  (avg cosine — * = correct match)")
        print(f"  {'True group \\ Scored as':<{hdr}}", end="")
        for k in topic_keys:
            print(f"  {topic_labels[k]:>{cw}}", end="")
        print()
        print(f"  {'-'*hdr}", end="")
        for _ in topic_keys:
            print(f"  {'--------':>{cw}}", end="")
        print()
        for true_key in topic_keys:
            row = r["score_matrix"].get(true_key, {})
            print(f"  {true_key:<{hdr}}", end="")
            for cand_key in topic_keys:
                vals = row.get(cand_key, [])
                avg  = sum(vals) / len(vals) if vals else 0.0
                mark = "*" if cand_key == true_key else " "
                print(f"  {avg:>{cw-1}.4f}{mark}", end="")
            print()
        print(f"  * = correct match  |  diagonal >> off-diagonal = good discrimination")

    print()


if __name__ == "__main__":
    main()
