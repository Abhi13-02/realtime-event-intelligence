"""intelligence layer — reddit_comments, sub_themes, sub_theme_memberships,
sub_theme_snapshots, intelligence_alerts

Revision ID: 003
Revises: 002
Create Date: 2026-04-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Shared updated_at trigger function ─────────────────────────────────
    # A generic version of the per-table function used by topics. Defined once
    # here and reused by sub_themes trigger so we don't duplicate boilerplate.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    # ── reddit_comments ────────────────────────────────────────────────────
    # Populated by the sub-theme discovery job AFTER Reddit posts have been
    # assigned to cluster centroids — not at crawl time. Only comments for
    # posts that actually land in a sub-theme are fetched, avoiding wasted
    # PRAW API calls for posts that never match any cluster.
    op.create_table(
        "reddit_comments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "score",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("idx_reddit_comments_article_id", "reddit_comments", ["article_id"])

    # ── sub_themes ─────────────────────────────────────────────────────────
    # One row per discovered sub-theme within a topic. Created by the
    # run_subtheme_discovery Celery task (runs every SUBTHEME_DISCOVERY_INTERVAL_HOURS).
    #
    # centroid is added via raw SQL — pgvector's VECTOR type cannot be
    # expressed through op.create_table()'s type system (same pattern as
    # articles.embedding in migration 001).
    #
    # keywords is a TEXT[] array of top headline terms fed to the LLM
    # labeling prompt as concrete signal.
    op.create_table(
        "sub_themes",
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
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("keywords", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "representative_article_id",
            postgresql.UUID(as_uuid=True),
            # ON DELETE SET NULL: the sub-theme survives if the article is removed.
            sa.ForeignKey("articles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("label_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'emerging'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('emerging', 'active', 'declining', 'inactive')",
            name="ck_sub_themes_status",
        ),
    )

    # centroid: mean embedding of the GDELT articles that formed this cluster.
    # Stored so Reddit posts can be assigned to their nearest sub-theme via
    # pgvector ANN search without re-clustering on every discovery run.
    op.execute("ALTER TABLE sub_themes ADD COLUMN centroid vector(384)")

    # updated_at trigger — reuses the generic function defined above.
    op.execute(
        """
        CREATE TRIGGER sub_themes_updated_at
        BEFORE UPDATE ON sub_themes
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at()
        """
    )

    op.create_index("idx_sub_themes_topic_id", "sub_themes", ["topic_id"])
    op.create_index("idx_sub_themes_status", "sub_themes", ["status"])

    # IVFFlat index for nearest-centroid lookup when assigning Reddit posts.
    # lists=10: appropriate for tens of sub-themes per topic (not thousands).
    # Lower lists = faster build, sufficient recall at this scale.
    # NOTE: requires at least one row to exist before it will be useful;
    # creating here is safe because the table starts empty and the index
    # builds with no data gracefully.
    op.execute(
        """
        CREATE INDEX idx_sub_themes_centroid ON sub_themes
        USING ivfflat (centroid vector_cosine_ops) WITH (lists = 10)
        """
    )

    # ── sub_theme_memberships ──────────────────────────────────────────────
    # Current-state-only table. On each discovery run for a topic, all rows
    # for that topic's sub-themes are deleted and replaced with fresh results.
    # Historical counts are preserved in sub_theme_snapshots — not here.
    op.create_table(
        "sub_theme_memberships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column(
            "sub_theme_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sub_themes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("membership_type", sa.Text(), nullable=False),
        sa.Column("similarity_to_centroid", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "sub_theme_id", "article_id", name="uq_stm_sub_theme_article"
        ),
        sa.CheckConstraint(
            "membership_type IN ('news', 'reddit')",
            name="ck_stm_membership_type",
        ),
        sa.CheckConstraint(
            "similarity_to_centroid BETWEEN -1 AND 1",
            name="ck_stm_similarity",
        ),
    )
    op.create_index("idx_stm_sub_theme_id", "sub_theme_memberships", ["sub_theme_id"])
    op.create_index("idx_stm_article_id", "sub_theme_memberships", ["article_id"])

    # ── sub_theme_snapshots ────────────────────────────────────────────────
    # Time-series table. One row per sub-theme per discovery run.
    # Serves three purposes:
    #   1. Evolution detection — current vs previous snapshot
    #   2. Sentiment baseline — rolling average from history
    #   3. Timeline API — GET /topics/{id}/intelligence/timeline
    op.create_table(
        "sub_theme_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column(
            "sub_theme_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sub_themes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "reddit_post_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_volume",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("sentiment_label", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "snapshot_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sentiment_score BETWEEN -1 AND 1",
            name="ck_sts_sentiment_score",
        ),
        sa.CheckConstraint(
            "sentiment_label IN ('positive', 'neutral', 'negative')",
            name="ck_sts_sentiment_label",
        ),
        sa.CheckConstraint(
            "status IN ('emerging', 'active', 'declining', 'inactive')",
            name="ck_sts_status",
        ),
    )
    op.create_index("idx_sts_sub_theme_id", "sub_theme_snapshots", ["sub_theme_id"])
    op.create_index("idx_sts_topic_id", "sub_theme_snapshots", ["topic_id"])
    op.create_index("idx_sts_snapshot_at", "sub_theme_snapshots", ["snapshot_at"])

    # Composite index: primary query is "last N snapshots for this sub-theme,
    # ordered by recency." Used by both evolution detection and the timeline
    # API. One index scan satisfies both the WHERE and ORDER BY.
    op.create_index(
        "idx_sts_sub_theme_snapshot_at",
        "sub_theme_snapshots",
        ["sub_theme_id", "snapshot_at"],
    )

    # ── intelligence_alerts ────────────────────────────────────────────────
    # Separate from the alerts table — intelligence alerts are triggered by
    # sub-theme state changes, not by individual articles. Mixing them into
    # alerts would require making article_id nullable, breaking the FK
    # integrity of the existing table.
    #
    # Idempotency: UNIQUE(user_id, sub_theme_snapshot_id, alert_type, channel)
    # means a replayed sub-theme-events Kafka message hits ON CONFLICT DO NOTHING
    # — identical guard as the alerts table.
    op.create_table(
        "intelligence_alerts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sub_theme_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sub_themes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sub_theme_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sub_theme_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alert_type", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id",
            "sub_theme_snapshot_id",
            "alert_type",
            "channel",
            name="uq_ia_user_snapshot_type_channel",
        ),
        sa.CheckConstraint(
            "alert_type IN ("
            "'sub_theme_emerging', "
            "'sub_theme_growing', "
            "'sub_theme_disappearing', "
            "'sub_theme_sentiment_shift'"
            ")",
            name="ck_ia_alert_type",
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'sms', 'websocket')",
            name="ck_ia_channel",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="ck_ia_status",
        ),
    )
    op.create_index(
        "idx_ia_user_id_created_at", "intelligence_alerts", ["user_id", "created_at"]
    )
    op.create_index("idx_ia_status", "intelligence_alerts", ["status"])
    op.create_index("idx_ia_sub_theme_id", "intelligence_alerts", ["sub_theme_id"])


def downgrade() -> None:
    op.drop_table("intelligence_alerts")
    op.drop_table("sub_theme_snapshots")
    op.drop_table("sub_theme_memberships")
    op.execute("DROP TRIGGER IF EXISTS sub_themes_updated_at ON sub_themes")
    op.drop_table("sub_themes")
    op.drop_table("reddit_comments")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at()")
