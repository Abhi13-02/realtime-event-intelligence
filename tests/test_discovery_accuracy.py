"""
Discovery Accuracy Benchmark — sub-theme clustering quality.

WHAT THIS TEST DOES
===================
Uses the 300-article labeled TSV dataset as synthetic ground truth.
Each of the 5 topics has 4 sub-categories (15 articles each) — these are
exactly the kinds of sub-themes the discovery worker should find.

For each topic:
  1. Embeds its 60 articles with the real production model (all-mpnet-base-v2)
  2. Runs clustering (HDBSCAN or BERTopic — selectable via --method flag)
  3. Compares cluster assignments to the TSV sub-category labels

HOW TO RUN
==========
  # Default (HDBSCAN, production method):
  docker compose exec backend bash -c "cd /app && PYTHONPATH=/app python tests/test_discovery_accuracy.py"

  # BERTopic comparison:
  docker compose exec backend bash -c "cd /app && PYTHONPATH=/app python tests/test_discovery_accuracy.py --method bertopic"

  # Tune HDBSCAN params:
  docker compose exec backend bash -c "cd /app && PYTHONPATH=/app python tests/test_discovery_accuracy.py --min-cluster-size 3 --min-samples 2"
"""

import csv
import re
import uuid
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
import argparse as _argparse

import numpy as np
from sklearn.metrics import silhouette_score

from app.pipeline.adapters.embedding_adapter import SentenceBertAdapter
from app.tasks.discovery.subtheme_discovery import (
    _ArticleRow,
    _cosine_similarity,
    _step1_cluster,
)

# ─── CLI args ─────────────────────────────────────────────────────────────────

_p = _argparse.ArgumentParser(add_help=False)
_p.add_argument("--method", choices=["hdbscan", "bertopic"], default="hdbscan")
_p.add_argument("--min-cluster-size", type=int, default=2)
_p.add_argument("--min-samples", type=int, default=1)
_args, _ = _p.parse_known_args()

METHOD = _args.method

# ─── Config ───────────────────────────────────────────────────────────────────

DATASET_PATH = Path(__file__).parent / "testDataset.tsv"

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

CLUSTERING_SETTINGS = SimpleNamespace(
    subtheme_min_cluster_size=_args.min_cluster_size,
    subtheme_min_samples=_args.min_samples,
    subtheme_window_days=3,
    subtheme_reddit_assign_threshold=0.55,
    subtheme_centroid_match_threshold=0.80,
    subtheme_growing_threshold=0.50,
    subtheme_disappearing_threshold=0.20,
    subtheme_sentiment_shift_threshold=0.20,
    subtheme_baseline_days=7,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def strip_html(text: str) -> str:
    return re.sub(r"<[^>]*>", "", text)


def load_dataset() -> list[tuple[str, str, str, str]]:
    """Return list of (article_id, sub_category, headline, content)."""
    rows = []
    with open(DATASET_PATH, newline="", encoding="utf-8") as f:
        for row in csv.reader(f, delimiter="\t"):
            article_id, _type, sub_category, headline, content = row
            rows.append((article_id, sub_category, headline, content))
    return rows


def avg_pairwise_cosine(embeddings: list[np.ndarray]) -> float:
    """Average cosine similarity between all pairs in a list."""
    if len(embeddings) < 2:
        return 1.0
    sims = []
    for i in range(len(embeddings)):
        for j in range(i + 1, len(embeddings)):
            sims.append(_cosine_similarity(embeddings[i], embeddings[j]))
    return float(np.mean(sims))


# ─── Clustering methods ───────────────────────────────────────────────────────

def cluster_hdbscan(
    vecs: np.ndarray,
    headlines: list[str],
) -> tuple[np.ndarray, dict[int, list[str]]]:
    """
    Run production HDBSCAN+UMAP clustering.
    Returns (labels array, {cluster_idx: [keywords]}).
    Label -1 = noise.
    """
    article_rows = [
        _ArticleRow(id=str(uuid.uuid4()), embedding=vecs[i], headline=headlines[i])
        for i in range(len(vecs))
    ]
    sub_themes = _step1_cluster(article_rows, CLUSTERING_SETTINGS)

    article_id_to_idx = {row.id: i for i, row in enumerate(article_rows)}
    labels = np.full(len(vecs), -1, dtype=int)
    cluster_keywords: dict[int, list[str]] = {}

    for cluster_idx, st in enumerate(sub_themes):
        cluster_keywords[cluster_idx] = st.keywords[:5]
        for member in st.members:
            labels[article_id_to_idx[member.id]] = cluster_idx

    return labels, cluster_keywords


def cluster_bertopic(
    vecs: np.ndarray,
    texts: list[str],
) -> tuple[np.ndarray, dict[int, list[str]]]:
    """
    Run BERTopic clustering using pre-computed embeddings.
    Returns (labels array, {cluster_idx: [keywords]}).
    Label -1 = noise/outliers.
    """
    try:
        from bertopic import BERTopic
    except ImportError:
        raise RuntimeError("BERTopic not installed. Run: pip install bertopic")

    # Pass pre-computed embeddings — skip BERTopic's internal embedding step
    # nr_topics="auto" lets BERTopic decide the number of topics
    topic_model = BERTopic(
        embedding_model=None,          # we supply embeddings directly
        min_topic_size=2,
        nr_topics="auto",
        verbose=False,
        calculate_probabilities=False,
    )
    raw_topics, _ = topic_model.fit_transform(texts, embeddings=vecs)
    labels = np.array(raw_topics, dtype=int)

    # BERTopic uses -1 for outliers (same convention as HDBSCAN)
    # Re-index so valid topics start at 0
    unique_valid = sorted(set(l for l in labels if l != -1))
    remap = {old: new for new, old in enumerate(unique_valid)}
    remapped = np.array([remap[l] if l != -1 else -1 for l in labels], dtype=int)

    # Extract top keywords per topic from BERTopic
    cluster_keywords: dict[int, list[str]] = {}
    for old_label, new_label in remap.items():
        try:
            words_scores = topic_model.get_topic(old_label)
            cluster_keywords[new_label] = [w for w, _ in words_scores[:5]]
        except Exception:
            cluster_keywords[new_label] = []

    return remapped, cluster_keywords


# ─── Per-topic benchmark ──────────────────────────────────────────────────────

def run_topic(
    topic_name: str,
    articles: list[tuple[str, str, str, str]],  # (article_id, sub_cat, headline, content)
    embedder: SentenceBertAdapter,
) -> dict:
    """Embed articles, cluster with selected method, score, return metrics dict."""

    texts = [f"{headline}. {strip_html(content)[:2000]}" for _, _, headline, content in articles]
    headlines = [headline for _, _, headline, _ in articles]
    vecs = embedder.model.encode(texts, batch_size=32, show_progress_bar=False)

    if METHOD == "bertopic":
        labels, cluster_keywords = cluster_bertopic(vecs, texts)
    else:
        labels, cluster_keywords = cluster_hdbscan(vecs, headlines)

    n_clusters = len(set(labels[labels != -1]))

    # Ground truth: article index → sub-category
    sub_cats = [sub_cat for _, sub_cat, _, _ in articles]
    unique_sub_cats = sorted(set(sub_cats))

    # ── Noise ratio ───────────────────────────────────────────────────────────
    noise_count = int(np.sum(labels == -1))
    noise_ratio = noise_count / len(articles)

    # ── Cluster purity ────────────────────────────────────────────────────────
    cluster_purities = []
    cluster_dominant_sub_cats = {}

    for cluster_idx in sorted(set(labels[labels != -1])):
        member_idxs = [i for i, l in enumerate(labels) if l == cluster_idx]
        member_sub_cats = [sub_cats[i] for i in member_idxs]
        counts = defaultdict(int)
        for sc in member_sub_cats:
            counts[sc] += 1
        dominant_sc = max(counts, key=counts.__getitem__)
        dominant_count = counts[dominant_sc]
        purity = dominant_count / len(member_idxs)
        cluster_purities.append(purity)
        cluster_dominant_sub_cats[cluster_idx] = (dominant_sc, dominant_count, len(member_idxs))

    avg_purity = float(np.mean(cluster_purities)) if cluster_purities else 0.0

    # ── Sub-category recall ───────────────────────────────────────────────────
    # A sub-category is "recalled" if it dominates at least one cluster (>50%)
    recalled_sub_cats = set()
    for cluster_idx, (dominant_sc, dominant_count, cluster_size) in cluster_dominant_sub_cats.items():
        if dominant_count / cluster_size > 0.5:
            recalled_sub_cats.add(dominant_sc)
    recall = len(recalled_sub_cats) / len(unique_sub_cats)

    # ── Silhouette score ──────────────────────────────────────────────────────
    non_noise_mask = labels != -1
    silhouette = None
    if non_noise_mask.sum() > 1 and len(set(labels[non_noise_mask])) > 1:
        try:
            silhouette = float(silhouette_score(vecs[non_noise_mask], labels[non_noise_mask], metric="cosine"))
        except Exception:
            silhouette = None

    # ── Intra-cluster similarity (cohesion) ───────────────────────────────────
    intra_sims = []
    for cluster_idx in sorted(set(labels[labels != -1])):
        member_vecs = [vecs[i] for i, l in enumerate(labels) if l == cluster_idx]
        intra_sims.append(avg_pairwise_cosine(member_vecs))
    avg_intra = float(np.mean(intra_sims)) if intra_sims else 0.0

    # ── Inter-cluster similarity (separation) ─────────────────────────────────
    inter_sim = None
    centroids = []
    for cluster_idx in sorted(set(labels[labels != -1])):
        member_vecs = np.array([vecs[i] for i, l in enumerate(labels) if l == cluster_idx])
        centroids.append(member_vecs.mean(axis=0))
    if len(centroids) > 1:
        inter_sims = []
        for i in range(len(centroids)):
            for j in range(i + 1, len(centroids)):
                inter_sims.append(_cosine_similarity(centroids[i], centroids[j]))
        inter_sim = float(np.mean(inter_sims))

    # ── Sub-category → cluster mapping ───────────────────────────────────────
    sc_to_cluster: dict[str, dict] = {}
    for sc in unique_sub_cats:
        sc_article_idxs = [i for i, s in enumerate(sub_cats) if s == sc]
        sc_cluster_counts: dict[int, int] = defaultdict(int)
        for idx in sc_article_idxs:
            sc_cluster_counts[labels[idx]] += 1
        best_cluster = max(sc_cluster_counts, key=sc_cluster_counts.__getitem__)
        best_count = sc_cluster_counts[best_cluster]
        sc_to_cluster[sc] = {
            "best_cluster": best_cluster,
            "count_in_best": best_count,
            "total": len(sc_article_idxs),
            "recalled": sc in recalled_sub_cats,
            "keywords": cluster_keywords.get(best_cluster, []),
        }

    return {
        "topic": topic_name,
        "n_articles": len(articles),
        "n_clusters": n_clusters,
        "noise_count": noise_count,
        "noise_ratio": noise_ratio,
        "avg_purity": avg_purity,
        "recall": recall,
        "silhouette": silhouette,
        "avg_intra_sim": avg_intra,
        "inter_cluster_sim": inter_sim,
        "sc_to_cluster": sc_to_cluster,
        "cluster_dominant": cluster_dominant_sub_cats,
        "cluster_keywords": cluster_keywords,
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\nLoading dataset ...", flush=True)
    dataset = load_dataset()
    print(f"  {len(dataset)} articles loaded.")

    # Group by topic
    topic_articles: dict[str, list] = defaultdict(list)
    for article_id, sub_cat, headline, content in dataset:
        topic_name = CATEGORY_TO_TOPIC[sub_cat]
        topic_articles[topic_name].append((article_id, sub_cat, headline, content))

    print("\nLoading embedding model ...", flush=True)
    embedder = SentenceBertAdapter()
    print("  Model loaded.")

    results = []
    for topic_name in sorted(topic_articles.keys()):
        articles = topic_articles[topic_name]
        print(f"\n  Clustering: {topic_name} ({len(articles)} articles) ...", flush=True)
        r = run_topic(topic_name, articles, embedder)
        results.append(r)
        sil_str = f"{r['silhouette']:.3f}" if r['silhouette'] is not None else "N/A"
        print(
            f"    Clusters={r['n_clusters']}  Noise={r['noise_ratio']:.0%}  "
            f"Purity={r['avg_purity']:.0%}  Recall={r['recall']:.0%}  "
            f"Silhouette={sil_str}"
        )

    # ── Summary table ─────────────────────────────────────────────────────────
    col = 26
    print(f"\n\n{'='*78}")
    print("  DISCOVERY ACCURACY BENCHMARK")
    print(f"  Model    : all-mpnet-base-v2 (768-dim)")
    print(f"  Dataset  : {len(dataset)} articles  |  5 topics  |  4 sub-categories × 15 articles")
    method_str = "BERTopic (nr_topics=auto, min_topic_size=2)" if METHOD == "bertopic" \
        else f"HDBSCAN+UMAP (min_cluster_size={CLUSTERING_SETTINGS.subtheme_min_cluster_size}, min_samples={CLUSTERING_SETTINGS.subtheme_min_samples})"
    print(f"  Method   : {method_str}")
    print(f"{'='*78}")
    print(f"  {'Topic':<{col}}  {'Clusters':>8}  {'Noise':>6}  {'Purity':>7}  {'Recall':>7}  {'Silhouette':>10}  {'Intra':>6}  {'Inter':>6}")
    print(f"  {'-'*col}  {'--------':>8}  {'------':>6}  {'-------':>7}  {'-------':>7}  {'----------':>10}  {'------':>6}  {'------':>6}")

    total_noise = 0
    total_articles = 0
    all_purities = []
    all_recalls = []
    all_silhouettes = []

    for r in results:
        sil = f"{r['silhouette']:.3f}" if r['silhouette'] is not None else "  N/A  "
        inter = f"{r['inter_cluster_sim']:.3f}" if r['inter_cluster_sim'] is not None else "  N/A"
        print(
            f"  {r['topic']:<{col}}  {r['n_clusters']:>8}  {r['noise_ratio']:>5.0%}  "
            f"{r['avg_purity']:>6.0%}  {r['recall']:>6.0%}  {sil:>10}  "
            f"{r['avg_intra_sim']:>6.3f}  {inter:>6}"
        )
        total_noise += r['noise_count']
        total_articles += r['n_articles']
        all_purities.append(r['avg_purity'])
        all_recalls.append(r['recall'])
        if r['silhouette'] is not None:
            all_silhouettes.append(r['silhouette'])

    overall_noise = total_noise / total_articles
    overall_purity = float(np.mean(all_purities))
    overall_recall = float(np.mean(all_recalls))
    overall_sil = f"{np.mean(all_silhouettes):.3f}" if all_silhouettes else "N/A"

    print(f"  {'-'*col}  {'--------':>8}  {'------':>6}  {'-------':>7}  {'-------':>7}  {'----------':>10}  {'------':>6}  {'------':>6}")
    print(f"  {'OVERALL':<{col}}  {'':>8}  {overall_noise:>5.0%}  {overall_purity:>6.0%}  {overall_recall:>6.0%}  {overall_sil:>10}")
    print(f"{'='*78}")

    # ── Sub-category → cluster mapping ────────────────────────────────────────
    print(f"\n\n  SUB-CATEGORY → CLUSTER MAPPING")
    print(f"  (shows where each sub-category's articles ended up)")

    for r in results:
        print(f"\n  {'─'*60}")
        print(f"  {r['topic']}")
        print(f"  {'─'*60}")
        print(f"  {'Sub-category':<28}  {'Members':>8}  {'Recalled':>9}  Keywords")
        print(f"  {'-'*28}  {'--------':>8}  {'---------':>9}  --------")
        for sc, info in sorted(r['sc_to_cluster'].items()):
            cluster_label = info['best_cluster']
            cluster_str = "noise" if cluster_label == -1 else f"C{cluster_label}"
            recalled_str = "✓" if info['recalled'] else "✗ (missed)"
            kw_str = ", ".join(info['keywords']) if info['keywords'] else "—"
            print(
                f"  {sc:<28}  {info['count_in_best']:>3}/{info['total']:<4}  "
                f"{recalled_str:>9}  [{cluster_str}] {kw_str}"
            )

    # ── All clusters detail ───────────────────────────────────────────────────
    print(f"\n\n  ALL CLUSTERS DETAIL")
    print(f"  (every cluster found, its dominant sub-category, size, and keywords)")

    for r in results:
        print(f"\n  {'─'*70}")
        print(f"  {r['topic']}  —  {r['n_clusters']} clusters found")
        print(f"  {'─'*70}")
        print(f"  {'Cluster':<10}  {'Dominant sub-category':<30}  {'Members':>8}  {'Purity':>7}  Keywords")
        print(f"  {'-'*10}  {'-'*30}  {'--------':>8}  {'-------':>7}  --------")

        sub_cats_list = [sub_cat for _, sub_cat, _, _ in topic_articles[r['topic']]]
        vecs_for_topic = None  # we only need cluster_dominant here

        for cluster_idx in sorted(r['cluster_dominant'].keys()):
            dominant_sc, dominant_count, cluster_size = r['cluster_dominant'][cluster_idx]
            purity = dominant_count / cluster_size
            keywords = r['cluster_keywords'].get(cluster_idx, [])
            kw_str = ", ".join(keywords) if keywords else "—"
            print(
                f"  C{cluster_idx:<9}  {dominant_sc:<30}  {dominant_count:>3}/{cluster_size:<4}  "
                f"{purity:>6.0%}  {kw_str}"
            )

    # ── Metrics glossary ──────────────────────────────────────────────────────
    print(f"\n\n  HOW TO READ THIS:")
    print(f"    Clusters   : how many sub-themes HDBSCAN found (4 expected per topic)")
    print(f"    Noise      : % of articles HDBSCAN couldn't assign to any cluster")
    print(f"    Purity     : avg % of articles in each cluster sharing the same sub-category")
    print(f"    Recall     : % of sub-categories that dominate at least one cluster (>50%)")
    print(f"    Silhouette : cluster quality [-1,1]. >0.3 = reasonable, >0.5 = strong")
    print(f"    Intra sim  : avg cosine similarity within clusters (higher = tighter)")
    print(f"    Inter sim  : avg cosine similarity between cluster centroids (lower = better separation)")
    print()


if __name__ == "__main__":
    main()
