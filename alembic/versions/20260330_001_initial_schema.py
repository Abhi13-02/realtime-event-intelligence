"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── PostgreSQL extensions ──────────────────────────────────────────────
    # uuid-ossp: provides uuid_generate_v4() used as server_default for PKs.
    # vector: pgvector extension for 384-dim embeddings (dedup + topic match).
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── users ──────────────────────────────────────────────────────────────
    # google_sub: stable subject ID from Google OAuth — unique identifier
    # for the user across sessions. NULL until user first authenticates.
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("google_sub", sa.Text(), nullable=True),
        sa.Column("phone_number", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("google_sub", name="uq_users_google_sub"),
    )
    op.create_index("idx_users_email", "users", ["email"])

    # ── sources ────────────────────────────────────────────────────────────
    # Admin-managed list of RSS feeds, Reddit, and Hacker News sources.
    op.create_table(
        "sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column(
            "credibility_score",
            sa.Float(),
            server_default=sa.text("0.5"),
            nullable=False,
        ),
        sa.Column(
            "poll_interval",
            sa.Integer(),
            server_default=sa.text("600"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("TRUE"),
            nullable=False,
        ),
        sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("url", name="uq_sources_url"),
        sa.CheckConstraint(
            "credibility_score BETWEEN 0 AND 1", name="ck_sources_credibility"
        ),
    )

    # ── topics ─────────────────────────────────────────────────────────────
    # User-defined monitoring topics. The embedding column is added via raw
    # SQL because pgvector's VECTOR type is not a standard SQLAlchemy type —
    # Alembic cannot express it through the op.create_table() API.
    op.create_table(
        "topics",
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
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("expanded_description", sa.Text(), nullable=True),
        sa.Column(
            "sensitivity",
            sa.Text(),
            server_default=sa.text("'balanced'"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("TRUE"),
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
            "sensitivity IN ('broad', 'balanced', 'high')", name="ck_topics_sensitivity"
        ),
    )
    op.create_index("idx_topics_user_id", "topics", ["user_id"])

    # Add embedding column using raw SQL — pgvector syntax not expressible via op.
    op.execute("ALTER TABLE topics ADD COLUMN embedding vector(384)")

    # updated_at trigger: automatically sets updated_at = NOW() on every UPDATE.
    # This cannot be expressed as a server_default alone (server_default only
    # fires on INSERT). A trigger is the correct tool here.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_topics_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER topics_updated_at
        BEFORE UPDATE ON topics
        FOR EACH ROW
        EXECUTE FUNCTION update_topics_updated_at()
        """
    )

    # ── topic_channels ─────────────────────────────────────────────────────
    # One row per delivery channel per topic. Separated from topics to avoid
    # array columns and allow per-channel indexing.
    op.create_table(
        "topic_channels",
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
        sa.Column("channel", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "topic_id", "channel", name="uq_topic_channels_topic_channel"
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'sms', 'websocket')", name="ck_topic_channels_channel"
        ),
    )
    op.create_index("idx_topic_channels_topic_id", "topic_channels", ["topic_id"])

    # ── articles ───────────────────────────────────────────────────────────
    # Post-deduplication articles. Summary is NULL until Stage 5 (Gemini)
    # completes — generated once and reused for all matching users.
    op.create_table(
        "articles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "pipeline_status",
            sa.Text(),
            server_default=sa.text("'passed_dedup'"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "crawled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("url", name="uq_articles_url"),
        sa.CheckConstraint(
            "pipeline_status IN ('passed_dedup', 'processed')",
            name="ck_articles_pipeline_status",
        ),
    )
    op.execute("ALTER TABLE articles ADD COLUMN embedding vector(384)")
    op.create_index("idx_articles_url", "articles", ["url"])
    op.create_index("idx_articles_source_id", "articles", ["source_id"])
    op.create_index("idx_articles_crawled_at", "articles", ["crawled_at"])

    # NOTE: The IVFFlat index on articles.embedding is intentionally excluded.
    # IVFFlat requires the table to have data first (lists=100 needs ~10k rows
    # to be useful). Create it in a separate migration after initial data load:
    #   CREATE INDEX idx_articles_embedding ON articles
    #   USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

    # ── article_topic_matches ──────────────────────────────────────────────
    # Many-to-many junction produced by the pipeline. Credibility score is
    # copied from sources at match time so downstream reads avoid a join.
    op.create_table(
        "article_topic_matches",
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
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("credibility_score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("article_id", "topic_id", name="uq_atm_article_topic"),
        sa.CheckConstraint(
            "relevance_score BETWEEN -1 AND 1", name="ck_atm_relevance"
        ),
        sa.CheckConstraint(
            "credibility_score BETWEEN 0 AND 1", name="ck_atm_credibility"
        ),
    )
    op.create_index("idx_atm_article_id", "article_topic_matches", ["article_id"])
    op.create_index("idx_atm_topic_id", "article_topic_matches", ["topic_id"])

    # ── alerts ─────────────────────────────────────────────────────────────
    # Delivery history. One row per user × article × topic × channel.
    # The composite unique constraint is the idempotency guard — prevents
    # duplicate alert rows if the matched-articles Kafka message is redelivered.
    op.create_table(
        "alerts",
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
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id",
            "article_id",
            "topic_id",
            "channel",
            name="uq_alerts_user_article_topic_channel",
        ),
        sa.CheckConstraint(
            "relevance_score BETWEEN -1 AND 1", name="ck_alerts_relevance"
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'sms', 'websocket')", name="ck_alerts_channel"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')", name="ck_alerts_status"
        ),
    )
    op.create_index(
        "idx_alerts_user_id_created_at", "alerts", ["user_id", "created_at"]
    )
    op.create_index("idx_alerts_status", "alerts", ["status"])


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_table("article_topic_matches")
    op.drop_table("articles")
    op.drop_table("topic_channels")
    op.execute("DROP TRIGGER IF EXISTS topics_updated_at ON topics")
    op.execute("DROP FUNCTION IF EXISTS update_topics_updated_at()")
    op.drop_table("topics")
    op.drop_table("sources")
    op.drop_table("users")
