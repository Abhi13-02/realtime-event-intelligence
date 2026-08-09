"""Store dropped articles + add the HNSW vector index.

Three changes that only make sense together.

1. pipeline_status gains 'dropped'.
   Until now an article that matched no topic was discarded without a trace,
   so stage_0_url_deduplicate (which looks in `articles`) could never recognise
   it. The same article was re-embedded on every crawl — measured at 7.4x
   redundant work. Storing it under 'dropped' closes that loop.

2. HNSW index on articles.embedding.
   Change 1 grows this table by roughly two orders of magnitude, and
   stage_2_vector_deduplicate touches it for every article. There was no
   vector index at all on the live database (schema.sql declared an ivfflat
   one that never got applied), so that check was a sequential scan. HNSW is
   used here rather than ivfflat: no training step, and recall stays good as
   the table grows.

3. Index on (pipeline_status, crawled_at).
   Supports the retention job that deletes expired 'dropped' rows.

Revision ID: 012_dropped_articles
Revises: 011_volume_at_last_label
Create Date: 2026-08-09
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '012_dropped_articles'
down_revision: Union[str, None] = '011_volume_at_last_label'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Allow pipeline_status = 'dropped' ──────────────────────────────
    op.execute("ALTER TABLE articles DROP CONSTRAINT IF EXISTS ck_articles_pipeline_status")
    op.execute("""
        ALTER TABLE articles ADD CONSTRAINT ck_articles_pipeline_status
            CHECK (pipeline_status IN ('passed_dedup', 'processed', 'dropped'))
    """)

    # ── 2. HNSW index for cosine distance ─────────────────────────────────
    # m=16 / ef_construction=64 are the pgvector defaults: a good build-time
    # vs recall trade-off, and cheap enough to build on a 2-core box.
    op.execute("DROP INDEX IF EXISTS idx_articles_embedding")
    op.execute("""
        CREATE INDEX idx_articles_embedding ON articles
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
    """)

    # ── 3. Retention-job index ────────────────────────────────────────────
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_status_crawled_at
            ON articles (pipeline_status, crawled_at)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_articles_status_crawled_at")
    op.execute("DROP INDEX IF EXISTS idx_articles_embedding")

    # Rows added since the upgrade would violate the narrower constraint.
    op.execute("DELETE FROM articles WHERE pipeline_status = 'dropped'")
    op.execute("ALTER TABLE articles DROP CONSTRAINT IF EXISTS ck_articles_pipeline_status")
    op.execute("""
        ALTER TABLE articles ADD CONSTRAINT ck_articles_pipeline_status
            CHECK (pipeline_status IN ('passed_dedup', 'processed'))
    """)
