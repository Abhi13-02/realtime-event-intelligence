"""vector_768 — upgrade all embedding columns from 384-dim to 768-dim

Switches the embedding model from all-MiniLM-L6-v2 / multi-qa-MiniLM-L6-cos-v1
(384-dim) to all-mpnet-base-v2 (768-dim). Benchmarking showed all-mpnet-base-v2
achieves 87% Top-1 accuracy vs 82% for the 384-dim baseline at the same threshold.

IMPORTANT — after running this migration you MUST re-seed all topic embeddings:
    docker compose exec backend bash -c "cd /app && PYTHONPATH=/app python tests/seed_topics.py"

All stored embeddings in topics, topic_subtopics, articles, and sub_themes are
invalidated by the dimension change and will be NULL / empty until regenerated.

Revision ID: 006
Revises: 005
Create Date: 2026-04-09
"""
from typing import Sequence, Union

from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Drop the IVFFlat index on sub_themes.centroid before altering the column.
    # IVFFlat indexes are tied to a specific vector dimension and cannot survive
    # a type change. The index is recreated below at 768-dim.
    op.execute("DROP INDEX IF EXISTS idx_sub_themes_centroid")

    # ── topics.embedding (nullable) ───────────────────────────────────────────
    # Drop and re-add. Existing 384-dim embeddings are invalid after model change
    # and are discarded. Re-seeding via seed_topics.py repopulates this column.
    op.execute("ALTER TABLE topics DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE topics ADD COLUMN embedding vector(768)")

    # ── topic_subtopics.embedding (NOT NULL) ──────────────────────────────────
    # Truncate first — all rows contain 384-dim vectors that are now incompatible.
    # seed_topics.py will repopulate this table with 768-dim embeddings.
    op.execute("TRUNCATE TABLE topic_subtopics")
    op.execute("ALTER TABLE topic_subtopics DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE topic_subtopics ADD COLUMN embedding vector(768) NOT NULL")

    # ── articles.embedding (nullable) ─────────────────────────────────────────
    # Existing article embeddings are invalidated. Articles will be re-embedded
    # the next time they pass through Stage 0 of the pipeline.
    op.execute("ALTER TABLE articles DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE articles ADD COLUMN embedding vector(768)")

    # ── sub_themes.centroid (nullable) ────────────────────────────────────────
    op.execute("ALTER TABLE sub_themes DROP COLUMN IF EXISTS centroid")
    op.execute("ALTER TABLE sub_themes ADD COLUMN centroid vector(768)")

    # ── Recreate IVFFlat index for sub_themes.centroid at 768-dim ─────────────
    # lists=10 kept the same — sub_themes table is small (tens of rows per topic).
    # This index is used for nearest-centroid lookup when assigning Reddit posts.
    op.execute(
        """
        CREATE INDEX idx_sub_themes_centroid
        ON sub_themes
        USING ivfflat (centroid vector_cosine_ops)
        WITH (lists = 10)
        """
    )


def downgrade() -> None:
    # Revert to 384-dim. All stored embeddings are again invalidated.
    # Re-seed and re-embed after running downgrade.
    op.execute("DROP INDEX IF EXISTS idx_sub_themes_centroid")

    op.execute("ALTER TABLE topics DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE topics ADD COLUMN embedding vector(384)")

    op.execute("TRUNCATE TABLE topic_subtopics")
    op.execute("ALTER TABLE topic_subtopics DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE topic_subtopics ADD COLUMN embedding vector(384) NOT NULL")

    op.execute("ALTER TABLE articles DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE articles ADD COLUMN embedding vector(384)")

    op.execute("ALTER TABLE sub_themes DROP COLUMN IF EXISTS centroid")
    op.execute("ALTER TABLE sub_themes ADD COLUMN centroid vector(384)")

    op.execute(
        """
        CREATE INDEX idx_sub_themes_centroid
        ON sub_themes
        USING ivfflat (centroid vector_cosine_ops)
        WITH (lists = 10)
        """
    )
