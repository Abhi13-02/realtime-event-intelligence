"""
Stage 2 (vector deduplication) index benchmark.

Why this exists
---------------
`db_adapter.vector_search_duplicate` asks "does any stored article sit within
0.05 cosine distance of this one?" and expresses it as:

    SELECT 1 FROM articles WHERE embedding <=> $1 <= $2 LIMIT 1

pgvector cannot serve that with an IVFFlat/HNSW index — approximate indexes are
only consulted for `ORDER BY embedding <=> $1 LIMIT n`. A distance predicate in
WHERE forces a sequential scan, so dedup cost grows linearly with the corpus.

The equivalent question can be asked in an index-friendly shape: fetch the single
nearest neighbour, then compare its distance in Python. This script measures what
that rewrite is worth, and what the approximate index costs in accuracy.

The initial migration deliberately skipped the IVFFlat index because it needs
~10k rows to be useful (20260330_001_initial_schema.py). This quantifies the
row count at which creating it starts paying off.

Usage (inside the backend container, which already has numpy + psycopg2):
    python tests/benchmark_vector_dedup.py
    python tests/benchmark_vector_dedup.py --sizes 10000,50000 --queries 50
"""

import argparse
import os
import statistics
import time
from typing import Callable

import numpy as np
import psycopg2

DIM = 768
TABLE = "bench_dedup_vectors"
# Stage 2 treats >= 0.95 cosine similarity as a duplicate, i.e. distance <= 0.05.
DUPLICATE_DISTANCE = 0.05


def connect() -> psycopg2.extensions.connection:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")
    # SQLAlchemy-style driver suffixes are not understood by libpq.
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://"):
        if dsn.startswith(prefix):
            dsn = dsn.replace(prefix, "postgresql://", 1)
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    return conn


def unit_vectors(count: int, rng: np.random.Generator) -> np.ndarray:
    """Random unit-norm vectors — cosine distance is only meaningful normalised."""
    raw = rng.standard_normal((count, DIM)).astype(np.float32)
    return raw / np.linalg.norm(raw, axis=1, keepdims=True)


def as_literal(vec: np.ndarray) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


def load_corpus(conn, size: int, rng: np.random.Generator) -> None:
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {TABLE}")
        cur.execute(f"CREATE TABLE {TABLE} (id serial PRIMARY KEY, embedding vector({DIM}))")
        # Insert in chunks; a single multi-MB statement is slower and can blow
        # past libpq's buffer on the larger corpus sizes.
        chunk = 2000
        for start in range(0, size, chunk):
            batch = unit_vectors(min(chunk, size - start), rng)
            args = ",".join(f"('{as_literal(v)}')" for v in batch)
            cur.execute(f"INSERT INTO {TABLE} (embedding) VALUES {args}")
        cur.execute(f"ANALYZE {TABLE}")


def drop_vector_indexes(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(f"DROP INDEX IF EXISTS {TABLE}_ivfflat")
        cur.execute(f"DROP INDEX IF EXISTS {TABLE}_hnsw")


def time_queries(conn, run: Callable[[np.ndarray], object], probes: np.ndarray) -> dict:
    timings = []
    for probe in probes:
        start = time.perf_counter()
        run(probe)
        timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    return {
        "mean_ms": statistics.mean(timings),
        "p50_ms": timings[len(timings) // 2],
        "p95_ms": timings[int(len(timings) * 0.95) - 1],
    }


def plan_summary(conn, sql: str, params: tuple) -> str:
    with conn.cursor() as cur:
        cur.execute("EXPLAIN " + sql, params)
        rows = [r[0] for r in cur.fetchall()]
    for row in rows:
        stripped = row.strip()
        if stripped.startswith(("Seq Scan", "Index Scan", "Bitmap", "Custom Scan")):
            return stripped.split("  ")[0]
    return rows[0].strip() if rows else "?"


PREDICATE_SQL = f"SELECT 1 FROM {TABLE} WHERE embedding <=> %s::vector <= %s LIMIT 1"
NEAREST_SQL = f"SELECT embedding <=> %s::vector AS d FROM {TABLE} ORDER BY d LIMIT 1"


def exact_nearest(conn, probes: np.ndarray) -> list:
    """Ground truth distances with every approximate index dropped."""
    out = []
    with conn.cursor() as cur:
        for probe in probes:
            cur.execute(NEAREST_SQL, (as_literal(probe),))
            out.append(cur.fetchone()[0])
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default="10000,50000")
    parser.add_argument("--queries", type=int, default=50)
    parser.add_argument("--keep", action="store_true", help="do not drop the bench table")
    args = parser.parse_args()

    rng = np.random.default_rng(42)
    sizes = [int(s) for s in args.sizes.split(",")]
    conn = connect()

    print(f"pgvector dedup benchmark — dim={DIM}, duplicate threshold <= {DUPLICATE_DISTANCE}")
    print(f"queries per configuration: {args.queries}\n")

    for size in sizes:
        print(f"=== corpus: {size:,} vectors ===")
        load_corpus(conn, size, rng)
        drop_vector_indexes(conn)
        probes = unit_vectors(args.queries, rng)

        with conn.cursor() as cur:
            def predicate(probe):
                cur.execute(PREDICATE_SQL, (as_literal(probe), DUPLICATE_DISTANCE))
                return cur.fetchone()

            def nearest(probe):
                cur.execute(NEAREST_SQL, (as_literal(probe),))
                return cur.fetchone()

            results = {}

            results["A. WHERE predicate (production form)"] = {
                **time_queries(conn, predicate, probes),
                "plan": plan_summary(conn, PREDICATE_SQL, (as_literal(probes[0]), DUPLICATE_DISTANCE)),
            }

            results["B. ORDER BY, no index (exact)"] = {
                **time_queries(conn, nearest, probes),
                "plan": plan_summary(conn, NEAREST_SQL, (as_literal(probes[0]),)),
            }
            truth = exact_nearest(conn, probes)

            lists = max(1, min(1000, size // 1000))
            cur.execute(
                f"CREATE INDEX {TABLE}_ivfflat ON {TABLE} "
                f"USING ivfflat (embedding vector_cosine_ops) WITH (lists = {lists})"
            )
            cur.execute(f"ANALYZE {TABLE}")
            results[f"C. ORDER BY + IVFFlat (lists={lists})"] = {
                **time_queries(conn, nearest, probes),
                "plan": plan_summary(conn, NEAREST_SQL, (as_literal(probes[0]),)),
                "recall": recall_at_1(conn, probes, truth),
            }
            cur.execute(f"DROP INDEX {TABLE}_ivfflat")

            cur.execute(
                f"CREATE INDEX {TABLE}_hnsw ON {TABLE} "
                f"USING hnsw (embedding vector_cosine_ops)"
            )
            cur.execute(f"ANALYZE {TABLE}")
            results["D. ORDER BY + HNSW"] = {
                **time_queries(conn, nearest, probes),
                "plan": plan_summary(conn, NEAREST_SQL, (as_literal(probes[0]),)),
                "recall": recall_at_1(conn, probes, truth),
            }

        baseline = results["A. WHERE predicate (production form)"]["mean_ms"]
        print(f"{'configuration':<38} {'mean':>9} {'p50':>9} {'p95':>9} {'speedup':>9}  plan")
        for label, r in results.items():
            speed = baseline / r["mean_ms"]
            extra = f"  recall@1={r['recall']:.0%}" if "recall" in r else ""
            print(
                f"{label:<38} {r['mean_ms']:>7.2f}ms {r['p50_ms']:>7.2f}ms "
                f"{r['p95_ms']:>7.2f}ms {speed:>8.1f}x  {r['plan']}{extra}"
            )
        print()

    if not args.keep:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {TABLE}")
    conn.close()


def recall_at_1(conn, probes: np.ndarray, truth: list) -> float:
    """
    Fraction of probes where the approximate index returned the same nearest
    distance as the exact scan. Below 100% means the index would silently miss
    duplicates that a sequential scan catches.
    """
    hits = 0
    with conn.cursor() as cur:
        for probe, exact in zip(probes, truth):
            cur.execute(NEAREST_SQL, (as_literal(probe),))
            got = cur.fetchone()[0]
            if abs(got - exact) < 1e-6:
                hits += 1
    return hits / len(probes)


if __name__ == "__main__":
    main()
