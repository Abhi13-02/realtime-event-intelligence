"""topic_subtopics — multi-vector topic matching

Each topic now generates 3-15 focused subtopic descriptions via Gemini.
Each subtopic is embedded separately and stored here. Stage 2 of the pipeline
matches articles against all subtopics (plus the parent embedding) and takes
the max score, replacing the previous single-vector cosine comparison.

Revision ID: 005
Revises: 004
Create Date: 2026-04-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the table without the embedding column first — pgvector's VECTOR
    # type cannot be expressed through op.create_table()'s type system.
    # Same pattern used for articles.embedding and sub_themes.centroid.
    op.create_table(
        "topic_subtopics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    # Add the vector column via raw SQL (pgvector type, NOT NULL).
    # Table is empty at migration time so NOT NULL is safe.
    op.execute("ALTER TABLE topic_subtopics ADD COLUMN embedding vector(384) NOT NULL")

    # Index for the primary access pattern: load all subtopics for a topic.
    op.create_index("idx_topic_subtopics_topic_id", "topic_subtopics", ["topic_id"])


def downgrade() -> None:
    op.drop_table("topic_subtopics")
