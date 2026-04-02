from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from pgvector.sqlalchemy import Vector

Base = declarative_base()


# Registered users of the platform.
# google_sub is the stable subject ID issued by Google — used to identify
# the user across sessions without storing a password.
class User(Base):
    __tablename__ = "users"

    id = Column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    name = Column(Text, nullable=False)
    email = Column(Text, nullable=False, unique=True)
    google_sub = Column(Text, nullable=True, unique=True)
    phone_number = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )

    __table_args__ = (Index("idx_users_email", "email"),)


# Curated list of RSS feeds, Reddit, and Hacker News sources.
# Admin-managed — not user-configurable in v1.
class Source(Base):
    __tablename__ = "sources"

    id = Column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    name = Column(Text, nullable=False)
    url = Column(Text, nullable=False, unique=True)
    type = Column(Text, nullable=False)
    credibility_score = Column(
        Float,
        CheckConstraint("credibility_score BETWEEN 0 AND 1"),
        nullable=False,
        server_default=text("0.5"),
    )
    poll_interval = Column(Integer, nullable=False, server_default=text("600"))
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))
    last_crawled_at = Column(DateTime(timezone=True), nullable=True)


# User-defined topics to monitor. Embedding is derived from the
# Gemini-expanded description via Sentence-BERT; sensitivity controls
# the relevance threshold used during pipeline matching.
class Topic(Base):
    __tablename__ = "topics"

    id = Column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    user_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    expanded_description = Column(Text, nullable=True)
    embedding = Column(Vector(384), nullable=True)
    sensitivity = Column(
        Text,
        CheckConstraint("sensitivity IN ('broad', 'balanced', 'high')"),
        nullable=False,
        server_default=text("'balanced'"),
    )
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
    # The topics_updated_at trigger that keeps this in sync is added
    # in the Alembic migration — not expressible as a server_default alone.
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )

    __table_args__ = (Index("idx_topics_user_id", "user_id"),)


# Delivery channels subscribed per topic. Separated from topics to
# support multiple channels per topic without array columns.
class TopicChannel(Base):
    __tablename__ = "topic_channels"

    id = Column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    topic_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel = Column(
        Text,
        CheckConstraint("channel IN ('email', 'sms', 'websocket')"),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("topic_id", "channel", name="uq_topic_channels_topic_channel"),
        Index("idx_topic_channels_topic_id", "topic_id"),
    )


# Articles that survived deduplication. Kafka 7-day retention on
# raw-articles serves as raw storage; only post-dedup rows land here.
# The summarization LLM generates one summary per article and all
# matching users reuse that stored result.
class Article(Base):
    __tablename__ = "articles"

    id = Column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    source_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("sources.id"),
        nullable=False,
    )
    url = Column(Text, nullable=False, unique=True)
    headline = Column(Text, nullable=False)
    content = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)  # NULL until stage 5 summarization completes
    embedding = Column(Vector(384), nullable=True)
    pipeline_status = Column(
        Text,
        CheckConstraint("pipeline_status IN ('passed_dedup', 'processed')"),
        nullable=False,
        server_default=text("'passed_dedup'"),
    )
    published_at = Column(DateTime(timezone=True), nullable=True)
    crawled_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )

    # idx_articles_embedding (IVFFlat) is intentionally excluded here.
    # It requires the table to already contain data (lists = 100) and will
    # be created in a separate Alembic migration after initial data load.
    __table_args__ = (
        Index("idx_articles_url", "url"),
        Index("idx_articles_source_id", "source_id"),
        Index("idx_articles_crawled_at", "crawled_at"),
    )


# Many-to-many junction between articles and topics produced by the
# pipeline. Credibility score is copied from sources at match time.
class ArticleTopicMatch(Base):
    __tablename__ = "article_topic_matches"

    id = Column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    article_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    topic_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False,
    )
    relevance_score = Column(
        Float,
        CheckConstraint("relevance_score BETWEEN -1 AND 1"),
        nullable=False,
    )
    credibility_score = Column(
        Float,
        CheckConstraint("credibility_score BETWEEN 0 AND 1"),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )

    __table_args__ = (
        UniqueConstraint("article_id", "topic_id", name="uq_atm_article_topic"),
        Index("idx_atm_article_id", "article_id"),
        Index("idx_atm_topic_id", "topic_id"),
    )


# Alert delivery history. One row per user × article × topic × channel.
# topic_id is intentionally denormalized (also derivable via
# article_topic_matches) to avoid joins on every dashboard read.
# The composite unique constraint is the idempotency guard against
# Kafka at-least-once redelivery of matched-articles messages.
class Alert(Base):
    __tablename__ = "alerts"

    id = Column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    user_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    article_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    topic_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False,
    )
    relevance_score = Column(
        Float,
        CheckConstraint("relevance_score BETWEEN -1 AND 1"),
        nullable=False,
    )
    channel = Column(
        Text,
        CheckConstraint("channel IN ('email', 'sms', 'websocket')"),
        nullable=False,
    )
    status = Column(
        Text,
        CheckConstraint("status IN ('pending', 'sent', 'failed')"),
        nullable=False,
        server_default=text("'pending'"),
    )
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )

    __table_args__ = (
        # Idempotency guard: duplicate INSERT on Kafka replay is silently rejected.
        UniqueConstraint(
            "user_id", "article_id", "topic_id", "channel",
            name="uq_alerts_user_article_topic_channel",
        ),
        # Covers the primary dashboard query: filter by user_id, sort by recency.
        # A single composite index satisfies both the WHERE and ORDER BY clauses.
        Index("idx_alerts_user_id_created_at", "user_id", "created_at"),
        Index("idx_alerts_status", "status"),
    )
