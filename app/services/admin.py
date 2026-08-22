"""Admin domain logic — every SQL statement behind the /v1/admin routes.

Extracted from app/api/admin.py, which had grown to 669 lines of route handlers
with multi-table SQL, JSON seeding and dynamic UPDATE construction inlined in
them.

Authentication stays in the router: require_admin is an HTTP concern. What
lives here is everything that touches the database.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.exceptions import OperationFailed, ResourceNotFound


async def _update_by_id(
    session: AsyncSession,
    table: str,
    row_id: uuid.UUID,
    update_data: dict,
    not_found: str,
) -> None:
    """
    Apply a partial UPDATE built from a Pydantic model_dump(exclude_unset=True).

    The column names are interpolated into the SQL rather than bound, which is
    unavoidable for a dynamic SET clause. It is safe here because the keys can
    only ever be field names declared on the request model — a caller cannot
    introduce a key that Pydantic did not define. `table` is likewise a literal
    supplied by this module, never by the request.
    """
    set_clause = ", ".join(f"{k} = :{k}" for k in update_data)
    result = await session.execute(
        text(f"UPDATE {table} SET {set_clause} WHERE id = :id"),
        {**update_data, "id": row_id},
    )
    await session.commit()

    if result.rowcount == 0:
        raise ResourceNotFound(not_found)


# ── Users ────────────────────────────────────────────────────────────────────

async def list_users(session: AsyncSession) -> dict:
    """All users with their topic counts."""
    result = await session.execute(text("""
        SELECT
            u.id, u.name, u.email, u.created_at,
            COUNT(t.id) as topic_count
        FROM users u
        LEFT JOIN topics t ON t.user_id = u.id
        GROUP BY u.id
        ORDER BY u.created_at DESC
    """))
    rows = result.fetchall()
    return {
        "total_users": len(rows),
        "users": [
            {
                "id": str(r[0]),
                "name": r[1],
                "email": r[2],
                "created_at": r[3].isoformat() if r[3] else None,
                "topic_count": r[4],
            }
            for r in rows
        ],
    }


async def delete_user(session: AsyncSession, user_id: uuid.UUID) -> dict:
    """
    Delete a user and all their associated data (topics, alerts, etc.).
    Cascading deletes are handled at the DB level via ondelete="CASCADE".
    """
    result = await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    await session.commit()

    if result.rowcount == 0:
        raise ResourceNotFound("User not found")

    return {"message": "User and all associated data deleted successfully"}


async def list_user_topics(session: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    """All topics for a specific user."""
    result = await session.execute(text("""
        SELECT id, name, description, expanded_description, sensitivity, is_active, created_at
        FROM topics
        WHERE user_id = :user_id
        ORDER BY created_at DESC
    """), {"user_id": user_id})
    return [
        {
            "id": str(r[0]),
            "name": r[1],
            "description": r[2],
            "expanded_description": r[3],
            "sensitivity": r[4],
            "is_active": r[5],
            "created_at": r[6].isoformat() if r[6] else None,
        }
        for r in result.fetchall()
    ]


# ── System stats ─────────────────────────────────────────────────────────────

async def source_stats(session: AsyncSession) -> list[dict]:
    """Articles per source — total, last 24h, last 1h."""
    result = await session.execute(text("""
        SELECT
            s.name,
            s.type,
            COUNT(a.id)                                                      AS total,
            COUNT(a.id) FILTER (WHERE a.crawled_at >= NOW() - INTERVAL '24 hours') AS last_24h,
            COUNT(a.id) FILTER (WHERE a.crawled_at >= NOW() - INTERVAL '1 hour')   AS last_1h,
            MAX(a.crawled_at)                                                AS last_seen
        FROM sources s
        LEFT JOIN articles a ON a.source_id = s.id
        GROUP BY s.name, s.type
        ORDER BY total DESC
    """))
    return [
        {
            "source":    r[0],
            "type":      r[1],
            "total":     r[2],
            "last_24h":  r[3],
            "last_1h":   r[4],
            "last_seen": r[5].isoformat() if r[5] else None,
        }
        for r in result.fetchall()
    ]


async def pipeline_stats(session: AsyncSession) -> list[dict]:
    """Article counts by pipeline_status and summary presence."""
    result = await session.execute(text("""
        SELECT
            pipeline_status,
            COUNT(*)                                    AS total,
            COUNT(*) FILTER (WHERE summary IS NULL)     AS missing_summary,
            COUNT(*) FILTER (WHERE summary IS NOT NULL) AS has_summary
        FROM articles
        GROUP BY pipeline_status
        ORDER BY total DESC
    """))
    return [
        {
            "status":          r[0],
            "total":           r[1],
            "missing_summary": r[2],
            "has_summary":     r[3],
        }
        for r in result.fetchall()
    ]


# ── Sub-themes ───────────────────────────────────────────────────────────────

async def subtheme_stats(session: AsyncSession) -> list[dict]:
    """All sub-themes across all users, with their latest snapshot and members."""
    result = await session.execute(text("""
        SELECT
            t.name                          AS topic,
            t.expanded_description          AS topic_description,
            st.label,
            st.status,
            st.keywords,
            a.headline                      AS centroid_article,
            snap.article_count,
            snap.reddit_post_count,
            snap.total_volume,
            snap.sentiment_score,
            arts.articles_json,
            st.id                           AS sub_theme_id
        FROM topics t
        JOIN sub_themes st ON st.topic_id = t.id
        LEFT JOIN articles a ON a.id = st.representative_article_id
        LEFT JOIN LATERAL (
            SELECT article_count, reddit_post_count, total_volume, sentiment_score
            FROM sub_theme_snapshots
            WHERE sub_theme_id = st.id
            ORDER BY snapshot_at DESC
            LIMIT 1
        ) snap ON TRUE
        LEFT JOIN LATERAL (
            SELECT json_agg(
                json_build_object(
                    'id',       a2.id,
                    'headline', a2.headline,
                    'summary',  a2.summary
                ) ORDER BY stm.created_at
            ) AS articles_json
            FROM sub_theme_memberships stm
            JOIN articles a2 ON a2.id = stm.article_id
            WHERE stm.sub_theme_id = st.id
        ) arts ON TRUE
        ORDER BY t.name, snap.total_volume DESC NULLS LAST
    """))
    return [
        {
            "topic":             r[0],
            "topic_description": r[1],
            "label":             r[2],
            "status":            r[3],
            "keywords":          r[4],
            "centroid_article":  r[5],
            "article_count":     r[6],
            "reddit_post_count": r[7],
            "total_volume":      r[8],
            "sentiment_score":   r[9],
            "articles":          r[10] or [],
            "id":                str(r[11]),
        }
        for r in result.fetchall()
    ]


async def list_topic_subthemes(session: AsyncSession, topic_id: uuid.UUID) -> list[dict]:
    """Sub-themes for a specific topic, with their latest snapshot figures."""
    result = await session.execute(text("""
        SELECT
            st.id,
            st.label,
            st.status,
            st.description,
            st.keywords,
            snap.article_count,
            snap.reddit_post_count,
            snap.total_volume,
            snap.sentiment_score
        FROM sub_themes st
        LEFT JOIN LATERAL (
            SELECT article_count, reddit_post_count, total_volume, sentiment_score
            FROM sub_theme_snapshots
            WHERE sub_theme_id = st.id
            ORDER BY snapshot_at DESC
            LIMIT 1
        ) snap ON TRUE
        WHERE st.topic_id = :topic_id
        ORDER BY snap.total_volume DESC NULLS LAST
    """), {"topic_id": topic_id})
    return [
        {
            "id": str(r[0]),
            "label": r[1],
            "status": r[2],
            "description": r[3],
            "keywords": r[4],
            "article_count": r[5],
            "reddit_post_count": r[6],
            "total_volume": r[7],
            "sentiment_score": r[8],
        }
        for r in result.fetchall()
    ]


async def delete_subtheme(session: AsyncSession, subtheme_id: uuid.UUID) -> dict:
    """Delete one sub-theme."""
    result = await session.execute(
        text("DELETE FROM sub_themes WHERE id = :id"), {"id": subtheme_id}
    )
    await session.commit()

    if result.rowcount == 0:
        raise ResourceNotFound("Sub-theme not found")

    return {"message": "Sub-theme deleted successfully"}


async def delete_topic_subthemes(session: AsyncSession, topic_id: uuid.UUID) -> dict:
    """Delete every sub-theme belonging to one topic."""
    result = await session.execute(
        text("DELETE FROM sub_themes WHERE topic_id = :topic_id"), {"topic_id": topic_id}
    )
    await session.commit()

    return {
        "message": f"Deleted {result.rowcount} sub-themes for topic {topic_id}",
        "deleted_count": result.rowcount,
    }


async def delete_all_subthemes(session: AsyncSession) -> dict:
    """
    Wipe ALL sub_themes rows.

    The three counts are read before the delete because the cascade removes
    those rows too — counting afterwards would report zero.
    """
    snap_count = (await session.execute(
        text("SELECT COUNT(*) FROM sub_theme_snapshots")
    )).scalar()
    mem_count = (await session.execute(
        text("SELECT COUNT(*) FROM sub_theme_memberships")
    )).scalar()
    alert_count = (await session.execute(
        text("SELECT COUNT(*) FROM intelligence_alerts")
    )).scalar()

    st_result = await session.execute(text("DELETE FROM sub_themes"))
    await session.commit()

    return {
        "message": "All sub-themes and their cascaded data deleted successfully.",
        "deleted": {
            "sub_themes":            st_result.rowcount,
            "sub_theme_snapshots":   snap_count,
            "sub_theme_memberships": mem_count,
            "intelligence_alerts":   alert_count,
        },
    }


# ── Articles ─────────────────────────────────────────────────────────────────

async def list_articles(
    session: AsyncSession, *, include_dropped: bool, limit: int
) -> dict:
    """
    Articles for debugging.

    Articles with pipeline_status='dropped' are excluded by default. They are
    retained only so the pipeline can recognise a URL it has already embedded,
    and they outnumber real articles by roughly 100 to 1 — returning them would
    swamp this endpoint.
    """
    status_filter = "" if include_dropped else "WHERE a.pipeline_status <> 'dropped'"

    total_count = (await session.execute(
        text(f"SELECT COUNT(*) FROM articles a {status_filter}")
    )).scalar()

    result = await session.execute(text(f"""
        SELECT
            a.id, a.source_id, a.url, a.headline, a.content, a.summary,
            a.pipeline_status, a.published_at, a.crawled_at,
            s.name as source_name,
            COALESCE(json_agg(t.name) FILTER (WHERE t.name IS NOT NULL), '[]') as topic_names
        FROM articles a
        JOIN sources s ON a.source_id = s.id
        LEFT JOIN article_topic_matches atm ON a.id = atm.article_id
        LEFT JOIN topics t ON atm.topic_id = t.id
        {status_filter}
        GROUP BY a.id, s.name
        ORDER BY a.crawled_at DESC
        LIMIT :limit
    """), {"limit": limit})

    return {
        "total_count": total_count,
        "articles": [
            {
                "id": str(r[0]),
                "source_id": str(r[1]),
                "url": r[2],
                "headline": r[3],
                "content": r[4],
                "summary": r[5],
                "pipeline_status": r[6],
                "published_at": r[7].isoformat() if r[7] else None,
                "crawled_at": r[8].isoformat() if r[8] else None,
                "source_name": r[9],
                "topics": r[10],
            }
            for r in result.fetchall()
        ],
    }


async def delete_all_articles(session: AsyncSession) -> dict:
    """Wipe all articles (and cascaded data)."""
    result = await session.execute(text("DELETE FROM articles"))
    await session.commit()

    return {
        "message": "All articles deleted successfully.",
        "deleted_count": result.rowcount,
    }


# ── Ingestion control ────────────────────────────────────────────────────────

async def list_sources(session: AsyncSession) -> list[dict]:
    """All sources with their current config and status."""
    result = await session.execute(text("""
        SELECT id, name, type, is_active, poll_interval, articles_per_crawl, last_crawled_at
        FROM sources
        ORDER BY name
    """))
    return [
        {
            "id": str(r[0]),
            "name": r[1],
            "type": r[2],
            "is_active": r[3],
            "poll_interval": r[4],
            "articles_per_crawl": r[5],
            "last_crawled_at": r[6].isoformat() if r[6] else None,
        }
        for r in result.fetchall()
    ]


async def update_source(
    session: AsyncSession, source_id: uuid.UUID, update_data: dict
) -> dict:
    """Update source-level config (toggle active, interval, etc.)."""
    if not update_data:
        return {"message": "No changes provided"}

    await _update_by_id(session, "sources", source_id, update_data, "Source not found")
    return {"message": "Source updated successfully"}


async def list_source_feeds(session: AsyncSession, source_id: uuid.UUID) -> list[dict]:
    """All RSS feeds for a specific source."""
    result = await session.execute(text("""
        SELECT id, feed_url, feed_label, is_active, articles_per_crawl
        FROM rss_feed_configs
        WHERE source_id = :source_id
        ORDER BY feed_label
    """), {"source_id": source_id})
    return [
        {
            "id": str(r[0]),
            "feed_url": r[1],
            "feed_label": r[2],
            "is_active": r[3],
            "articles_per_crawl": r[4],
        }
        for r in result.fetchall()
    ]


async def update_feed(
    session: AsyncSession, feed_id: uuid.UUID, update_data: dict
) -> dict:
    """Update feed-level config (toggle active, limit)."""
    if not update_data:
        return {"message": "No changes provided"}

    await _update_by_id(session, "rss_feed_configs", feed_id, update_data, "Feed not found")
    return {"message": "Feed updated successfully"}


async def list_reddit_subreddits(session: AsyncSession) -> list[dict]:
    """All subreddits being monitored."""
    result = await session.execute(text(
        "SELECT id, name, limit_per_crawl, sort, is_active FROM reddit_subreddits ORDER BY name"
    ))
    return [
        {
            "id": str(r[0]),
            "name": r[1],
            "limit_per_crawl": r[2],
            "sort": r[3],
            "is_active": r[4],
        }
        for r in result.fetchall()
    ]


async def add_reddit_subreddit(session: AsyncSession, subreddit: dict) -> dict:
    """Add a new subreddit to monitor."""
    try:
        await session.execute(text("""
            INSERT INTO reddit_subreddits (name, limit_per_crawl, sort)
            VALUES (:name, :limit_per_crawl, :sort)
        """), subreddit)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise OperationFailed(str(exc)) from exc

    return {"message": f"Subreddit r/{subreddit['name']} added"}


async def update_reddit_subreddit(
    session: AsyncSession, subreddit_id: uuid.UUID, update_data: dict
) -> dict:
    """Edit subreddit settings or toggle active state."""
    if not update_data:
        return {"message": "No changes provided"}

    await _update_by_id(
        session, "reddit_subreddits", subreddit_id, update_data, "Subreddit not found"
    )
    return {"message": "Subreddit updated successfully"}


async def delete_reddit_subreddit(session: AsyncSession, subreddit_id: uuid.UUID) -> dict:
    """Stop monitoring a subreddit."""
    result = await session.execute(
        text("DELETE FROM reddit_subreddits WHERE id = :id"), {"id": subreddit_id}
    )
    await session.commit()

    if result.rowcount == 0:
        raise ResourceNotFound("Subreddit not found")

    return {"message": "Subreddit removed"}


# ── System settings ──────────────────────────────────────────────────────────

def _setting_seeds() -> list[dict]:
    """
    Defaults written into system_settings the first time the console is opened.

    Seeded here rather than left to the discovery task so they appear in the
    console immediately — the task only seeds them on its next run, which is up
    to 24 hours away.
    """
    settings = get_settings()
    return [
        {
            "key": "subtheme_window_days",
            "value": settings.subtheme_window_days,
            "desc": "Rolling window size (days) for discovery.",
        },
        {
            "key": "subtheme_min_cluster_size",
            "value": settings.subtheme_min_cluster_size,
            "desc": "Min articles required to form a sub-theme.",
        },
        {
            "key": "subtheme_min_samples",
            "value": settings.subtheme_min_samples,
            "desc": "Noise control. Lower = more granular, but more noise.",
        },
        {
            "key": "subtheme_cluster_selection_method",
            "value": settings.subtheme_cluster_selection_method,
            "desc": "Strategy: 'eom' (broad) or 'leaf' (specific).",
        },
        {
            "key": "subtheme_reddit_assign_threshold",
            "value": settings.subtheme_reddit_assign_threshold,
            "desc": "Similarity threshold for Reddit -> News mapping (0.0 to 1.0).",
        },
        {
            "key": "subtheme_discovery_interval_hours",
            "value": settings.subtheme_discovery_interval_hours,
            "desc": "Global interval (hours) between discovery runs.",
        },
        {
            "key": "subtheme_umap_n_components",
            "value": settings.subtheme_umap_n_components,
            "desc": "UMAP dimensions before HDBSCAN (10 recommended for 768-dim embeddings).",
        },
        {
            "key": "subtheme_centroid_match_threshold",
            "value": settings.subtheme_centroid_match_threshold,
            "desc": "Min cosine similarity for a cluster to inherit an existing sub-theme identity (0.85 recommended).",
        },
        {
            "key": "subtheme_relabel_volume_change_threshold",
            "value": settings.subtheme_relabel_volume_change_threshold,
            "desc": "Volume growth vs last label time to trigger AI relabeling (0.50 = 50%).",
        },
        # Kill switches.
        {
            "key": "subtheme_umap_enabled",
            "value": settings.subtheme_umap_enabled,
            "desc": "UMAP reduction before HDBSCAN. OFF clusters normalised 768-dim vectors directly: far faster and deterministic, but leaves more articles unassigned.",
        },
        {
            "key": "subtheme_llm_gate_enabled",
            "value": settings.subtheme_llm_gate_enabled,
            "desc": "LLM relevance gate. OFF keeps every cluster and re-admits previously rejected ones. Labels are still generated either way.",
        },
    ]


async def list_settings(session: AsyncSession) -> list[dict]:
    """List all system settings, seeding any that are missing."""
    for seed in _setting_seeds():
        check = await session.execute(
            text("SELECT 1 FROM system_settings WHERE key = :key"), {"key": seed["key"]}
        )
        if not check.fetchone():
            await session.execute(
                text("INSERT INTO system_settings (key, value, description) VALUES (:key, :value, :desc)"),
                {
                    "key": seed["key"],
                    "value": json.dumps(seed["value"]),
                    "desc": seed["desc"],
                },
            )
    await session.commit()

    result = await session.execute(
        text("SELECT key, value, description FROM system_settings ORDER BY key")
    )
    return [{"key": r[0], "value": r[1], "description": r[2]} for r in result.fetchall()]


async def update_setting(session: AsyncSession, key: str, value: Any) -> dict:
    """Update one system setting. Serialised so the column is treated as JSONB."""
    result = await session.execute(
        text("UPDATE system_settings SET value = :value, updated_at = NOW() WHERE key = :key"),
        {"key": key, "value": json.dumps(value)},
    )
    await session.commit()

    if result.rowcount == 0:
        raise ResourceNotFound("Setting not found")

    return {"message": f"Setting {key} updated"}
