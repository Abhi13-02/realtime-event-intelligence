"""
Async DB queries for the intelligence alert consumer.

Five operations, each accepting an AsyncSession:
  get_sub_theme              — fetch sub-theme label, description, keywords, sentiment
  get_snapshot               — fetch snapshot volume counts and sentiment
  get_topic_name             — fetch topic name string
  bulk_insert_intelligence_alerts — one row per channel into intelligence_alerts
  mark_intelligence_alert_sent    — UPDATE status='sent' after delivery
  mark_intelligence_alert_failed  — UPDATE status='failed' after permanent failure

Note: get_channels is reused from app.alert.db — same query, same table.
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class SubThemeRow:
    id: str
    label: str | None
    description: str | None
    keywords: list[str]
    status: str


@dataclass
class SnapshotRow:
    id: str
    gdelt_article_count: int
    reddit_post_count: int
    total_volume: int
    sentiment_score: float | None
    sentiment_label: str | None
    snapshot_at: datetime


async def get_sub_theme(
    session: AsyncSession,
    sub_theme_id: str,
) -> SubThemeRow | None:
    """Fetch sub-theme state for building intelligence alert payloads."""
    result = await session.execute(
        text("""
            SELECT id, label, description, keywords, status
            FROM sub_themes
            WHERE id = :sub_theme_id
        """),
        {"sub_theme_id": sub_theme_id},
    )
    row = result.fetchone()
    if not row:
        return None
    return SubThemeRow(
        id=str(row.id),
        label=row.label,
        description=row.description,
        keywords=list(row.keywords) if row.keywords else [],
        status=row.status,
    )


async def get_snapshot(
    session: AsyncSession,
    sub_theme_snapshot_id: str,
) -> SnapshotRow | None:
    """Fetch snapshot volume/sentiment for building intelligence alert payloads."""
    result = await session.execute(
        text("""
            SELECT id, gdelt_article_count, reddit_post_count, total_volume,
                   sentiment_score, sentiment_label, snapshot_at
            FROM sub_theme_snapshots
            WHERE id = :snapshot_id
        """),
        {"snapshot_id": sub_theme_snapshot_id},
    )
    row = result.fetchone()
    if not row:
        return None
    return SnapshotRow(
        id=str(row.id),
        gdelt_article_count=row.gdelt_article_count,
        reddit_post_count=row.reddit_post_count,
        total_volume=row.total_volume,
        sentiment_score=row.sentiment_score,
        sentiment_label=row.sentiment_label,
        snapshot_at=row.snapshot_at,
    )


async def get_topic_name(
    session: AsyncSession,
    topic_id: str,
) -> str | None:
    """Fetch topic name string."""
    result = await session.execute(
        text("SELECT name FROM topics WHERE id = :topic_id"),
        {"topic_id": topic_id},
    )
    row = result.fetchone()
    return row.name if row else None


async def bulk_insert_intelligence_alerts(
    session: AsyncSession,
    user_id: str,
    sub_theme_id: str,
    sub_theme_snapshot_id: str,
    topic_id: str,
    alert_type: str,
    payload: dict,
    channels: list[str],
) -> list[tuple[str, str]]:
    """
    Insert one intelligence_alerts row per channel in a single SQL statement.
    Returns list of (alert_id, channel) tuples for the inserted rows.

    ON CONFLICT DO NOTHING — idempotent against Kafka at-least-once redelivery.
    Unique constraint: (user_id, sub_theme_snapshot_id, alert_type, channel).
    """
    if not channels:
        return []

    payload_json = json.dumps(payload)

    values_parts = []
    params: dict = {
        "user_id": user_id,
        "sub_theme_id": sub_theme_id,
        "sub_theme_snapshot_id": sub_theme_snapshot_id,
        "topic_id": topic_id,
        "alert_type": alert_type,
        "payload": payload_json,
        "status": "pending",
    }

    for i, channel in enumerate(channels):
        key = f"channel_{i}"
        values_parts.append(
            f"(:user_id, :topic_id, :sub_theme_id, :sub_theme_snapshot_id, "
            f":alert_type, :{key}, :status, :payload::jsonb)"
        )
        params[key] = channel

    values_sql = ", ".join(values_parts)
    result = await session.execute(
        text(f"""
            INSERT INTO intelligence_alerts
                (user_id, topic_id, sub_theme_id, sub_theme_snapshot_id,
                 alert_type, channel, status, payload)
            VALUES {values_sql}
            ON CONFLICT (user_id, sub_theme_snapshot_id, alert_type, channel) DO NOTHING
            RETURNING id, channel
        """),
        params,
    )
    await session.commit()
    return [(str(row.id), row.channel) for row in result.fetchall()]


async def mark_intelligence_alert_sent(
    session: AsyncSession,
    alert_id: str,
) -> None:
    """Mark a single intelligence alert as sent after successful delivery."""
    await session.execute(
        text("UPDATE intelligence_alerts SET status='sent', sent_at=NOW() WHERE id=:id"),
        {"id": alert_id},
    )
    await session.commit()


async def mark_intelligence_alert_failed(
    session: AsyncSession,
    alert_id: str,
) -> None:
    """Mark a single intelligence alert as failed after a terminal delivery failure."""
    await session.execute(
        text("UPDATE intelligence_alerts SET status='failed' WHERE id=:id"),
        {"id": alert_id},
    )
    await session.commit()
