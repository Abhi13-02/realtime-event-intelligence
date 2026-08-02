"""
End-to-end delivery latency, measured from production data.

The requirement is "< 5 minutes from crawl to alert". Every hop between those
two points is already timestamped, so the number can be read straight out of
Postgres rather than instrumented:

    articles.crawled_at   -- ingestion task wrote the raw article
    alerts.created_at     -- alert service persisted the user-facing alert

The gap covers Kafka publish + consume, the full 8-stage pipeline (including the
LLM summarisation call), the second Kafka hop, and the alert fan-out.

Also reports the ingestion-lag: published_at -> crawled_at, i.e. how stale an
article already is when the crawler first sees it. That bound is set by the
2-minute dispatch cadence and by how promptly each source's feed updates, and it
is not something the pipeline can win back.

Usage (inside the backend container):
    python tests/benchmark_e2e_latency.py
"""

import os

import psycopg2

PERCENTILE_SQL = """
SELECT
    count(*)                                                      AS n,
    min(seconds)                                                  AS min_s,
    percentile_disc(0.50) WITHIN GROUP (ORDER BY seconds)         AS p50_s,
    percentile_disc(0.90) WITHIN GROUP (ORDER BY seconds)         AS p90_s,
    percentile_disc(0.99) WITHIN GROUP (ORDER BY seconds)         AS p99_s,
    max(seconds)                                                  AS max_s,
    avg(seconds)                                                  AS avg_s
FROM ({inner}) t
"""

PIPELINE_INNER = """
SELECT EXTRACT(EPOCH FROM (al.created_at - ar.crawled_at)) AS seconds
FROM alerts al
JOIN articles ar ON ar.id = al.article_id
WHERE al.created_at >= ar.crawled_at
"""

INGEST_INNER = """
SELECT EXTRACT(EPOCH FROM (ar.crawled_at - ar.published_at)) AS seconds
FROM articles ar
WHERE ar.published_at IS NOT NULL
  AND ar.crawled_at >= ar.published_at
"""


def connect():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://"):
        if dsn.startswith(prefix):
            dsn = dsn.replace(prefix, "postgresql://", 1)
    return psycopg2.connect(dsn)


def fmt(seconds) -> str:
    if seconds is None:
        return "-"
    seconds = float(seconds)
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{seconds / 60:.1f}m"


def report(cur, label: str, inner: str, budget_s: float | None = None) -> None:
    cur.execute(PERCENTILE_SQL.format(inner=inner))
    n, lo, p50, p90, p99, hi, avg = cur.fetchone()
    print(f"=== {label} ===")
    if not n:
        print("  no rows\n")
        return
    print(f"  samples : {n}")
    print(f"  min/p50 : {fmt(lo)} / {fmt(p50)}")
    print(f"  p90/p99 : {fmt(p90)} / {fmt(p99)}")
    print(f"  max/avg : {fmt(hi)} / {fmt(avg)}")
    if budget_s is not None:
        cur.execute(
            f"SELECT count(*) FILTER (WHERE seconds <= {budget_s}), count(*) FROM ({inner}) t"
        )
        within, total = cur.fetchone()
        print(f"  within {fmt(budget_s)} budget: {within}/{total} ({within / total:.0%})")
    print()


def main() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM articles")
        articles = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM alerts")
        alerts = cur.fetchone()[0]
        print(f"corpus: {articles} articles, {alerts} alerts\n")

        report(cur, "crawl -> alert (pipeline end-to-end)", PIPELINE_INNER, budget_s=300)
        report(cur, "publish -> crawl (source/ingestion lag)", INGEST_INNER)

        # Per-stage split is not separately timestamped; the closest available
        # breakdown is how many articles never reached summarisation.
        cur.execute(
            "SELECT pipeline_status, count(*) FROM articles GROUP BY 1 ORDER BY 2 DESC"
        )
        print("=== pipeline_status distribution ===")
        for status, count in cur.fetchall():
            print(f"  {status:<16} {count}")


if __name__ == "__main__":
    main()
