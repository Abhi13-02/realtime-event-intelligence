"""
Throughput benchmark for the two CPU-bound pipeline stages.

Stage 1 (embedding) and Stage 3 (topic matching) are the only stages whose cost
is paid for every surviving article, so together they set the ceiling on how
many articles/second one pipeline consumer can absorb. Stage 6 (summarisation)
is network-bound and runs on ~10-15 articles per cycle, so it is excluded.

Stage 3 compares each article against every active topic, and each topic carries
a parent embedding plus 3-6 LLM-generated subtopic embeddings. Cost is therefore
O(topics x vectors_per_topic) per article — this measures how that scales, and
whether the current per-topic Python loop holds up as tenants are added.

Usage (inside the backend container):
    python tests/benchmark_pipeline_throughput.py
    python tests/benchmark_pipeline_throughput.py --articles 100
"""

import argparse
import os
import statistics
import time

import numpy as np

DIM = 768
MODEL_NAME = "all-mpnet-base-v2"
# Matches the pipeline: parent description + 3-6 subtopic descriptions.
VECTORS_PER_TOPIC = 5
# Stage 1 truncates article text before encoding.
TRUNCATE_CHARS = 2000


def load_article_texts(limit: int) -> list:
    """Real article text when the database has it, synthetic filler otherwise."""
    dsn = os.environ.get("DATABASE_URL", "")
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://"):
        if dsn.startswith(prefix):
            dsn = dsn.replace(prefix, "postgresql://", 1)

    texts = []
    if dsn:
        try:
            import psycopg2

            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT headline, coalesce(content, '') FROM articles LIMIT %s",
                    (limit,),
                )
                texts = [f"{h}. {c}"[:TRUNCATE_CHARS] for h, c in cur.fetchall()]
        except Exception as exc:  # pragma: no cover - diagnostic path
            print(f"  (could not read articles from DB: {exc})")

    if len(texts) < limit:
        filler = (
            "Global markets reacted sharply as policymakers signalled a shift in "
            "monetary strategy, with analysts warning that the coming quarter "
            "could reshape investment flows across emerging economies. "
        ) * 6
        texts += [filler[:TRUNCATE_CHARS]] * (limit - len(texts))
    return texts[:limit]


def bench_embedding(texts: list) -> dict:
    from sentence_transformers import SentenceTransformer

    print(f"loading {MODEL_NAME} ...")
    model = SentenceTransformer(MODEL_NAME)

    # Warm-up: first encode pays lazy init and would skew the single-article number.
    model.encode(texts[0])

    singles = []
    for text in texts:
        start = time.perf_counter()
        model.encode(text)
        singles.append((time.perf_counter() - start) * 1000)
    singles.sort()

    start = time.perf_counter()
    model.encode(texts, batch_size=32)
    batch_total = time.perf_counter() - start

    return {
        "single_mean_ms": statistics.mean(singles),
        "single_p95_ms": singles[int(len(singles) * 0.95) - 1],
        "single_per_sec": 1000 / statistics.mean(singles),
        "batch_per_article_ms": batch_total * 1000 / len(texts),
        "batch_per_sec": len(texts) / batch_total,
    }


def bench_matching(topic_counts: list, trials: int = 200) -> list:
    """
    Replicates stage_3_topic_matching: for every topic, cosine the article
    against each subtopic embedding plus the parent, then take the max.
    Vectors are unit-norm so cosine reduces to a dot product, exactly as the
    production helper does after normalisation.
    """
    rng = np.random.default_rng(42)
    rows = []

    for count in topic_counts:
        cache = []
        for _ in range(count):
            vecs = rng.standard_normal((VECTORS_PER_TOPIC, DIM)).astype(np.float32)
            vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
            cache.append(vecs)

        article = rng.standard_normal(DIM).astype(np.float32)
        article /= np.linalg.norm(article)

        timings = []
        for _ in range(trials):
            start = time.perf_counter()
            for vecs in cache:
                float(np.max(vecs @ article))
            timings.append((time.perf_counter() - start) * 1000)
        timings.sort()

        rows.append({
            "topics": count,
            "vectors": count * VECTORS_PER_TOPIC,
            "mean_ms": statistics.mean(timings),
            "p95_ms": timings[int(len(timings) * 0.95) - 1],
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--articles", type=int, default=50)
    parser.add_argument("--topics", default="10,100,1000")
    args = parser.parse_args()

    texts = load_article_texts(args.articles)
    print(f"pipeline throughput benchmark — {len(texts)} articles, dim={DIM}\n")

    emb = bench_embedding(texts)
    print("=== Stage 1: embedding (all-mpnet-base-v2, CPU) ===")
    print(f"  single-article : {emb['single_mean_ms']:.1f} ms mean, "
          f"{emb['single_p95_ms']:.1f} ms p95  ->  {emb['single_per_sec']:.1f} articles/sec")
    print(f"  batch-32       : {emb['batch_per_article_ms']:.1f} ms/article"
          f"  ->  {emb['batch_per_sec']:.1f} articles/sec\n")

    counts = [int(c) for c in args.topics.split(",")]
    print("=== Stage 3: topic matching (max cosine over parent + subtopics) ===")
    print(f"{'topics':>8} {'vectors':>9} {'mean':>10} {'p95':>10} {'articles/sec':>14}")
    for row in bench_matching(counts):
        print(f"{row['topics']:>8} {row['vectors']:>9} {row['mean_ms']:>8.3f}ms "
              f"{row['p95_ms']:>8.3f}ms {1000 / row['mean_ms']:>13.0f}")

    print("\n=== combined ceiling (Stage 1 + Stage 3, single consumer) ===")
    for row in bench_matching(counts):
        total = emb["single_mean_ms"] + row["mean_ms"]
        batched = emb["batch_per_article_ms"] + row["mean_ms"]
        print(f"  {row['topics']:>5} topics: {total:.1f} ms/article "
              f"({1000 / total:.1f}/sec)   batched: {batched:.1f} ms/article "
              f"({1000 / batched:.1f}/sec)")


if __name__ == "__main__":
    main()
