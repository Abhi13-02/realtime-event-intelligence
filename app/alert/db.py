"""
Async DB queries for the alert consumer.

Four operations, each accepting an AsyncSession:
  get_channels       — what channels does this user want for this topic?
  get_article        — fetch article content for alert delivery
  bulk_insert_alerts — create one alert row per channel (single SQL statement)
  mark_alert_sent    — update status to 'sent' after successful delivery
"""
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class ArticleRow:
    id: str
    headline: str
    summary: str | None
    url: str
    source_name: str


async def get_channels(
    session: AsyncSession,
    user_id: str,
    topic_id: str,
) -> list[str]:
    """
    Return the delivery channels configured by this user for this topic.
    Filters is_active=TRUE — if the topic was paused since the pipeline matched it,
    this returns an empty list and the consumer skips the message.
    """
    result = await session.execute(
        text("""
            SELECT tc.channel
            FROM topic_channels tc
            JOIN topics t ON tc.topic_id = t.id
            WHERE t.user_id  = :user_id
              AND tc.topic_id = :topic_id
              AND t.is_active = TRUE
        """),
        {"user_id": user_id, "topic_id": topic_id},
    )
    return [row.channel for row in result.fetchall()]


async def get_article(
    session: AsyncSession,
    article_id: str,
) -> ArticleRow | None:
    """Fetch article content + source name for building alert payloads."""
    result = await session.execute(
        text("""
            SELECT a.id, a.headline, a.summary, a.url, s.name AS source_name
            FROM articles a
            JOIN sources s ON a.source_id = s.id
            WHERE a.id = :article_id
        """),
        {"article_id": article_id},
    )
    row = result.fetchone()
    if not row:
        return None
    return ArticleRow(
        id=str(row.id),
        headline=row.headline,
        summary=row.summary,
        url=row.url,
        source_name=row.source_name,
    )


async def bulk_insert_alerts(
    session: AsyncSession,
    user_id: str,
    article_id: str,
    topic_id: str,
    relevance_score: float,
    channels: list[str],
) -> list[tuple[str, str]]:
    """
    Insert one alert row per channel in a single SQL statement.
    Returns list of (alert_id, channel) tuples for the inserted rows.

    ON CONFLICT DO NOTHING — idempotent against Kafka at-least-once redelivery.
    If the consumer crashes after inserting but before committing the Kafka offset,
    the next replay will hit the conflict and silently skip — no duplicate alerts.
    """
    if not channels:
        return []

    # Build one VALUES row per channel dynamically
    values_parts = []
    params: dict[str, Any] = {
        "user_id": user_id,
        "article_id": article_id,
        "topic_id": topic_id,
        "relevance_score": relevance_score,
        "status": "pending",
    }
    for i, channel in enumerate(channels):
        key = f"channel_{i}"
        values_parts.append(
            f"(:user_id, :article_id, :topic_id, :relevance_score, :{key}, :status)"
        )
        params[key] = channel

    values_sql = ", ".join(values_parts)
    result = await session.execute(
        text(f"""
            INSERT INTO alerts (user_id, article_id, topic_id, relevance_score, channel, status)
            VALUES {values_sql}
            ON CONFLICT (user_id, article_id, topic_id, channel) DO NOTHING
            RETURNING id, channel
        """),
        params,
    )
    await session.commit()
    return [(str(row.id), row.channel) for row in result.fetchall()]


async def mark_alert_sent(session: AsyncSession, alert_id: str) -> None:
    """Mark a single alert row as sent after successful delivery."""
    await session.execute(
        text("UPDATE alerts SET status='sent', sent_at=NOW() WHERE id=:id"),
        {"id": alert_id},
    )
    await session.commit()


async def mark_alert_failed(session: AsyncSession, alert_id: str) -> None:
    """Mark a single alert row as failed after a terminal delivery failure."""
    await session.execute(
        text("UPDATE alerts SET status='failed' WHERE id=:id"),
        {"id": alert_id},
    )
    await session.commit()
