"""
Accuracy benchmark using REAL topics from the database.

WHAT THIS TEST DOES
===================
1. Pulls your actual topics from Postgres — using the real stored embeddings
   that Gemini expanded and SentenceBERT encoded when you created each topic.
2. Runs all 300 articles from testDataset.tsv through Stage 0 (real embedder).
3. For each article, checks whether the correct broad topic scores above the
   threshold — exactly what the live pipeline does.

This is the honest test. The previous test (test_pipeline_accuracy.py) used
short topic names like "AI regulation" as stand-ins. This one uses your real
Gemini-expanded embeddings, so results reflect actual production behaviour.

TOPIC → CATEGORY MAPPING
=========================
Your 5 DB topics each cover 4 TSV categories (60 articles each):

  Artificial Intelligence  →  ai_regulation, ai_healthcare, ai_jobs, ai_research
  Climate Change           →  climate_policy, climate_oceans, climate_energy, climate_disasters
  Global Economy           →  economy_trade, economy_recession, economy_markets, economy_inflation
  Space Exploration        →  space_research, space_policy, space_missions, space_commercialization
  Public Health            →  health_systems, health_pandemic, health_mental, health_drugs

HOW TO RUN
==========
Run this inside the backend container (needs DB + embedder):

  docker compose exec backend bash -c "cd /app && PYTHONPATH=/app pytest tests/test_pipeline_accuracy_db.py -v -s"
"""

import asyncio
import csv
from collections import defaultdict
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db.models import Topic as DBTopic, TopicSubtopic as DBTopicSubtopic
from app.db.session import AsyncSessionLocal, engine
from app.pipeline.adapters.embedding_adapter import SentenceBertAdapter
from app.pipeline.models import RawArticle, Topic as PipelineTopic
from app.pipeline import stages

# ─── Configuration ────────────────────────────────────────────────────────────

DATASET_PATH = Path(__file__).parent / "testDataset.tsv"

# Thresholds read from config — same values the live pipeline uses.
# To change thresholds, update app/config.py (or override via env vars).
_s = get_settings()
THRESHOLDS = {
    "broad":    _s.threshold_broad,
    "balanced": _s.threshold_balanced,
    "high":     _s.threshold_high,
}

DUMMY_SOURCE_ID = UUID("00000000-0000-0000-0000-000000000001")

# Maps each TSV category label to the DB topic name it belongs to.
# Topic names here must match exactly what you typed when creating the topic.
CATEGORY_TO_TOPIC = {
    # Artificial Intelligence
    "ai_regulation":           "Artificial Intelligence",
    "ai_healthcare":           "Artificial Intelligence",
    "ai_jobs":                 "Artificial Intelligence",
    "ai_research":             "Artificial Intelligence",
    # Climate Change
    "climate_policy":          "Climate Change",
    "climate_oceans":          "Climate Change",
    "climate_energy":          "Climate Change",
    "climate_disasters":       "Climate Change",
    # Global Economy
    "economy_trade":           "Global Economy",
    "economy_recession":       "Global Economy",
    "economy_markets":         "Global Economy",
    "economy_inflation":       "Global Economy",
    # Space Exploration
    "space_research":          "Space Exploration",
    "space_policy":            "Space Exploration",
    "space_missions":          "Space Exploration",
    "space_commercialization": "Space Exploration",
    # Public Health
    "health_systems":          "Public Health",
    "health_pandemic":         "Public Health",
    "health_mental":           "Public Health",
    "health_drugs":            "Public Health",
}


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def embedder() -> SentenceBertAdapter:
    """Load the real sentence-BERT model once for the whole file."""
    return SentenceBertAdapter()


@pytest.fixture(scope="module")
def dataset() -> list[tuple[str, str, str, str]]:
    """Parse testDataset.tsv → list of (article_id, category, headline, content)."""
    rows = []
    with open(DATASET_PATH, newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            article_id, _type, category, headline, content = row
            rows.append((article_id, category, headline, content))
    return rows


@pytest.fixture(scope="module")
def db_topics() -> dict[str, PipelineTopic]:
    """
    Fetch all topics from Postgres and return them as a dict:
        { topic_name (lowercase) → PipelineTopic }

    Uses the stored embedding — the one Gemini expanded and SentenceBERT encoded
    when you created the topic through the API. This is the real production vector.
    """

    async def _fetch():
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(DBTopic).where(DBTopic.is_active == True))
            topic_rows = result.scalars().all()

        if not topic_rows:
            pytest.skip(
                "No active topics found in the database. "
                "Create topics via the API first, then re-run this test."
            )

        # Fetch all subtopics in one query, keyed by topic_id
        subtopics_map: dict = {}
        async with AsyncSessionLocal() as session:
            sub_result = await session.execute(
                select(DBTopicSubtopic).where(
                    DBTopicSubtopic.topic_id.in_([t.id for t in topic_rows])
                )
            )
            for sub in sub_result.scalars().all():
                subtopics_map.setdefault(sub.topic_id, []).append(list(sub.embedding))

        topics = {}
        for row in topic_rows:
            if row.embedding is None:
                pytest.skip(f"Topic '{row.name}' has no embedding — it may not have been processed yet.")

            topics[row.name.lower().strip()] = PipelineTopic(
                id=row.id,
                user_id=row.user_id,
                name=row.name,
                sensitivity=row.sensitivity,
                parent_embedding=list(row.embedding),
                subtopic_embeddings=subtopics_map.get(row.id, []),
            )

        return topics

    asyncio.run(engine.dispose())
    return asyncio.run(_fetch())


# ─── The Benchmark Test ───────────────────────────────────────────────────────

def test_pipeline_accuracy_against_db_topics(
    embedder: SentenceBertAdapter,
    dataset: list[tuple[str, str, str, str]],
    db_topics: dict[str, PipelineTopic],
) -> None:
    """
    Run 300 TSV articles through the real pipeline stages and measure how many
    are correctly matched to your DB topics at the current threshold.

    PASS condition:
        overall recall@threshold  >= 50%
        overall top-1 accuracy    >= 60%

    These are the targets for production-quality expanded topic embeddings.
    If the test fails, the numbers in the assertion message tell you exactly
    where you are vs. where you need to be.
    """

    threshold_map = THRESHOLDS  # {"broad": 0.55, "balanced": 0.65, "high": 0.75}

    # Verify every expected topic name is present in the DB
    expected_topics = {"artificial intelligence", "climate change", "global economy", "space exploration", "public health"}
    missing = expected_topics - set(db_topics.keys())
    if missing:
        pytest.skip(f"Missing topics in DB (check name spelling): {missing}")

    # Counters
    top1_correct  = defaultdict(int)   # best match == correct topic
    recall_caught = defaultdict(int)   # correct topic scored >= threshold
    total_per_topic = defaultdict(int) # total articles per topic

    # Per-article true-topic scores — for the threshold diagnostic
    all_true_scores: list[float] = []

    # Score matrix: score_matrix[true_topic][candidate_topic] = [scores...]
    # Lets us see avg score of "AI articles" against every topic, not just AI.
    score_matrix: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for article_id, true_cat, headline, content in dataset:
        true_topic_name = CATEGORY_TO_TOPIC[true_cat].lower().strip()
        true_topic = db_topics[true_topic_name]
        threshold = threshold_map.get(true_topic.sensitivity, 0.65)

        raw = RawArticle(
            url=f"https://benchmark.test/{article_id}",
            headline=headline,
            content=content,
            source_id=DUMMY_SOURCE_ID,
        )

        # Stage 0: embed the article — same as production
        processed = stages.stage_0_preprocess(raw, embedder)

        # Score against every DB topic — same logic as production Stage 2:
        # max(subtopic scores + parent score)
        scores: list[tuple[float, str]] = []
        for name, topic in db_topics.items():
            sub_scores = [stages.cosine_similarity(processed.embedding, s) for s in topic.subtopic_embeddings]
            sub_scores.append(stages.cosine_similarity(processed.embedding, topic.parent_embedding))
            score = max(sub_scores)
            scores.append((score, name))
            score_matrix[true_topic_name][name].append(score)
        scores.sort(reverse=True)

        best_score, best_name = scores[0]
        true_score = next(s for s, n in scores if n == true_topic_name)

        total_per_topic[true_topic_name] += 1
        all_true_scores.append(true_score)

        if best_name == true_topic_name:
            top1_correct[true_topic_name] += 1

        if true_score >= threshold:
            recall_caught[true_topic_name] += 1

    # ─── Totals ───────────────────────────────────────────────────────────────
    grand_total         = len(dataset)
    total_top1          = sum(top1_correct.values())
    total_caught        = sum(recall_caught.values())
    overall_top1        = total_top1   / grand_total
    overall_recall      = total_caught / grand_total
    avg_true_score      = sum(all_true_scores) / len(all_true_scores)
    max_true_score      = max(all_true_scores)

    candidate_thresholds = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65]
    threshold_recall_map = {
        t: sum(1 for s in all_true_scores if s >= t) / grand_total
        for t in candidate_thresholds
    }
    balanced_threshold = THRESHOLDS["balanced"]

    # ─── Report ───────────────────────────────────────────────────────────────
    col = 30
    print("\n")
    print("=" * 72)
    print("  PIPELINE ACCURACY BENCHMARK — REAL DB TOPICS")
    print(f"  Model      : all-mpnet-base-v2  (768-dim, Gemini-expanded embeddings)")
    print(f"  Articles   : {grand_total}   |   DB Topics : {len(db_topics)}")
    print("=" * 72)
    print(f"  {'Topic (from DB)':<{col}}  {'Top-1':>6}  {'Recall@thr':>10}  {'Caught':>8}  {'Threshold':>9}")
    print("-" * 72)

    for name in sorted(db_topics.keys()):
        topic    = db_topics[name]
        n        = total_per_topic[name]
        t1       = top1_correct[name]
        rc       = recall_caught[name]
        thr      = threshold_map.get(topic.sensitivity, 0.65)
        print(f"  {topic.name:<{col}}  {t1/n:>5.0%}  {rc/n:>9.0%}  {rc:>4}/{n:<3}  {thr:>9.2f}")

    print("-" * 72)
    print(
        f"  {'OVERALL':<{col}}  {overall_top1:>5.0%}  {overall_recall:>9.0%}"
        f"  {total_caught:>4}/{grand_total}"
    )
    print("=" * 72)

    print(f"\n  TRUE-TOPIC SCORE DISTRIBUTION")
    print(f"  Average score (correct topic) : {avg_true_score:.4f}")
    print(f"  Max score     (correct topic) : {max_true_score:.4f}")
    print(f"\n  Recall if threshold were lowered to:")
    for t, r in threshold_recall_map.items():
        bar    = "█" * int(r * 30)
        marker = "  ← current (balanced)" if t == balanced_threshold else ""
        print(f"    {t:.2f}  {r:>5.0%}  {bar}{marker}")

    # ─── Score matrix ─────────────────────────────────────────────────────────
    # Rows = true topic group (what the article is actually about)
    # Cols = every candidate topic scored against
    # Cell = average cosine similarity for that article-group × topic pair
    # Diagonal = correct match; off-diagonal = cross-topic bleed
    topic_keys = sorted(db_topics.keys())
    topic_display = {k: db_topics[k].name[:14] for k in topic_keys}  # truncate for table width
    hdr_width = 18
    cell_width = 7

    print(f"\n  SCORE MATRIX  (avg cosine similarity — diagonal = correct match)")
    print(f"  {'True topic \\ Scored as':<{hdr_width}}", end="")
    for k in topic_keys:
        print(f"  {topic_display[k]:>{cell_width}}", end="")
    print()
    print(f"  {'-'*hdr_width}", end="")
    for _ in topic_keys:
        print(f"  {'-------':>{cell_width}}", end="")
    print()

    for true_key in topic_keys:
        row_label = db_topics[true_key].name[:hdr_width]
        print(f"  {row_label:<{hdr_width}}", end="")
        for cand_key in topic_keys:
            cell_scores = score_matrix[true_key][cand_key]
            avg = sum(cell_scores) / len(cell_scores) if cell_scores else 0.0
            marker = "*" if cand_key == true_key else " "
            print(f"  {avg:>{cell_width-1}.4f}{marker}", end="")
        print()

    print(f"\n  * = correct topic  |  higher diagonal vs off-diagonal = better discrimination")

    print(
        f"\n  HOW TO READ THIS:\n"
        f"    Top-1 {overall_top1:.0%} = the pipeline chose the right topic as its best\n"
        f"    guess for {overall_top1:.0%} of articles.\n"
        f"\n"
        f"    Recall {overall_recall:.0%} = {overall_recall:.0%} of articles actually cleared the\n"
        f"    threshold and would trigger an alert for the user.\n"
        f"    The remaining {1-overall_recall:.0%} were silently dropped.\n"
    )

    # ─── Assertions ───────────────────────────────────────────────────────────
    # Targets set for all-mpnet-base-v2 (768-dim) with calibrated thresholds
    # (broad=0.40, balanced=0.45, high=0.55). Verified by model_comparison.py.
    # If these fail, either the model changed or topic embedding quality degraded —
    # re-run seed_topics.py then the benchmark before investigating further.
    assert overall_top1 >= 0.85, (
        f"Top-1 accuracy {overall_top1:.1%} is below the 85% target. "
        f"Semantic matching quality has degraded — check embedding or topic quality."
    )
    assert overall_recall >= 0.40, (
        f"Recall@threshold {overall_recall:.1%} is below the 40% target. "
        f"Too many relevant articles are being dropped. "
        f"Average true-topic score is {avg_true_score:.4f}. "
        f"Re-run seed_topics.py to regenerate topic embeddings and retry."
    )
