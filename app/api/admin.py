"""
Admin-only routes for system management and multi-user oversight.
Protected by X-Admin-Key header.
"""

import asyncio
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Any


class SystemSettingUpdate(BaseModel):
    value: Any

from app.config import get_settings
from app.db.session import get_db
from app.celery_app import celery_app

settings = get_settings()

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_admin(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    """Dependency to ensure the request has a valid admin secret key."""
    if not x_admin_key or x_admin_key != settings.admin_secret_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin secret key"
        )


@router.get("/users", dependencies=[Depends(require_admin)])
async def list_users_admin(db: AsyncSession = Depends(get_db)):
    """List all users in the system with their topic counts."""
    result = await db.execute(text("""
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
                "topic_count": r[4]
            }
            for r in rows
        ]
    }


@router.delete("/users/{user_id}", dependencies=[Depends(require_admin)])
async def delete_user_admin(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """
    Delete a user and all their associated data (topics, alerts, etc.).
    Cascading deletes are handled at the DB level via ondelete="CASCADE".
    """
    result = await db.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {"message": "User and all associated data deleted successfully"}


@router.get("/users/{user_id}/topics", dependencies=[Depends(require_admin)])
async def list_user_topics_admin(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List all topics for a specific user."""
    result = await db.execute(text("""
        SELECT id, name, description, expanded_description, sensitivity, is_active, created_at
        FROM topics
        WHERE user_id = :user_id
        ORDER BY created_at DESC
    """), {"user_id": user_id})
    rows = result.fetchall()
    return [
        {
            "id": str(r[0]),
            "name": r[1],
            "description": r[2],
            "expanded_description": r[3],
            "sensitivity": r[4],
            "is_active": r[5],
            "created_at": r[6].isoformat() if r[6] else None
        }
        for r in rows
    ]


@router.post("/users/{user_id}/topics/{topic_id}/discover", dependencies=[Depends(require_admin)])
async def discover_topic_admin(user_id: uuid.UUID, topic_id: uuid.UUID):
    """Trigger sub-theme discovery for a specific topic."""
    task = celery_app.send_task(
        "app.tasks.subtheme_discovery.run_subtheme_discovery_for_topic",
        args=[str(topic_id)]
    )
    return {"task_id": task.id, "status": "queued"}


@router.post("/discover/all", dependencies=[Depends(require_admin)])
async def discover_all_admin():
    """Trigger sub-theme discovery for all topics globally."""
    task = celery_app.send_task("app.tasks.subtheme_discovery.run_subtheme_discovery")
    return {"task_id": task.id, "status": "queued"}


@router.get("/sources", dependencies=[Depends(require_admin)])
async def source_stats(db: AsyncSession = Depends(get_db)):
    """Articles per source — total, last 24h, last 1h."""
    result = await db.execute(text("""
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
    rows = result.fetchall()
    return [
        {
            "source":    r[0],
            "type":      r[1],
            "total":     r[2],
            "last_24h":  r[3],
            "last_1h":   r[4],
            "last_seen": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]


@router.get("/pipeline", dependencies=[Depends(require_admin)])
async def pipeline_stats(db: AsyncSession = Depends(get_db)):
    """Article counts by pipeline_status and summary presence."""
    result = await db.execute(text("""
        SELECT
            pipeline_status,
            COUNT(*)                                    AS total,
            COUNT(*) FILTER (WHERE summary IS NULL)     AS missing_summary,
            COUNT(*) FILTER (WHERE summary IS NOT NULL) AS has_summary
        FROM articles
        GROUP BY pipeline_status
        ORDER BY total DESC
    """))
    rows = result.fetchall()
    return [
        {
            "status":          r[0],
            "total":           r[1],
            "missing_summary": r[2],
            "has_summary":     r[3],
        }
        for r in rows
    ]


@router.get("/subthemes", dependencies=[Depends(require_admin)])
async def subtheme_stats(db: AsyncSession = Depends(get_db)):
    """All sub-themes across all users."""
    result = await db.execute(text("""
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
    rows = result.fetchall()
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
        for r in rows
    ]


@router.get("/users/{user_id}/topics/{topic_id}/subthemes", dependencies=[Depends(require_admin)])
async def list_topic_subthemes_admin(user_id: uuid.UUID, topic_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List sub-themes for a specific topic."""
    result = await db.execute(text("""
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
    rows = result.fetchall()
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
        for r in rows
    ]


@router.delete("/subthemes/{subtheme_id}", dependencies=[Depends(require_admin)])
async def delete_subtheme_admin(subtheme_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete a specific sub-theme."""
    result = await db.execute(text("DELETE FROM sub_themes WHERE id = :id"), {"id": subtheme_id})
    await db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Sub-theme not found")
        
    return {"message": "Sub-theme deleted successfully"}


@router.delete("/users/{user_id}/topics/{topic_id}/subthemes", dependencies=[Depends(require_admin)])
async def delete_topic_subthemes_admin(user_id: uuid.UUID, topic_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete all sub-themes for a specific topic."""
    result = await db.execute(text("DELETE FROM sub_themes WHERE topic_id = :topic_id"), {"topic_id": topic_id})
    await db.commit()
    
    return {
        "message": f"Deleted {result.rowcount} sub-themes for topic {topic_id}",
        "deleted_count": result.rowcount
    }


@router.get("/articles", dependencies=[Depends(require_admin)])
async def list_articles_admin(db: AsyncSession = Depends(get_db)):
    """List all articles for debugging."""
    count_result = await db.execute(text("SELECT COUNT(*) FROM articles"))
    total_count = count_result.scalar()

    result = await db.execute(text("""
        SELECT 
            a.id, a.source_id, a.url, a.headline, a.content, a.summary, 
            a.pipeline_status, a.published_at, a.crawled_at,
            s.name as source_name,
            COALESCE(json_agg(t.name) FILTER (WHERE t.name IS NOT NULL), '[]') as topic_names
        FROM articles a
        JOIN sources s ON a.source_id = s.id
        LEFT JOIN article_topic_matches atm ON a.id = atm.article_id
        LEFT JOIN topics t ON atm.topic_id = t.id
        GROUP BY a.id, s.name
        ORDER BY a.crawled_at DESC
    """))
    rows = result.fetchall()
    
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
                "topics": r[10]
            }
            for r in rows
        ]
    }


@router.delete("/articles", dependencies=[Depends(require_admin)])
async def delete_all_articles_admin(db: AsyncSession = Depends(get_db)):
    """Wipe all articles (and cascaded data)."""
    result = await db.execute(text("DELETE FROM articles"))
    await db.commit()
    
    return {
        "message": "All articles deleted successfully.",
        "deleted_count": result.rowcount
    }


@router.delete("/subthemes", dependencies=[Depends(require_admin)])
async def delete_all_subthemes_admin(db: AsyncSession = Depends(get_db)):
    """Wipe ALL sub_themes rows."""
    snap_result = await db.execute(text("SELECT COUNT(*) FROM sub_theme_snapshots"))
    snap_count = snap_result.scalar()

    mem_result = await db.execute(text("SELECT COUNT(*) FROM sub_theme_memberships"))
    mem_count = mem_result.scalar()

    alert_result = await db.execute(text("SELECT COUNT(*) FROM intelligence_alerts"))
    alert_count = alert_result.scalar()

    st_result = await db.execute(text("DELETE FROM sub_themes"))
    await db.commit()

    return {
        "message": "All sub-themes and their cascaded data deleted successfully.",
        "deleted": {
            "sub_themes":           st_result.rowcount,
            "sub_theme_snapshots":  snap_count,
            "sub_theme_memberships": mem_count,
            "intelligence_alerts":  alert_count,
        }
    }


# ── Ingestion Control ──────────────────────────────────────────────────────────

class SourceUpdate(BaseModel):
    is_active: Optional[bool] = None
    poll_interval: Optional[int] = None
    articles_per_crawl: Optional[int] = None

class FeedUpdate(BaseModel):
    is_active: Optional[bool] = None
    articles_per_crawl: Optional[int] = None

class RedditSubredditCreate(BaseModel):
    name: str
    limit_per_crawl: int = 10
    sort: str = "new"

class RedditSubredditUpdate(BaseModel):
    is_active: Optional[bool] = None
    limit_per_crawl: Optional[int] = None
    sort: Optional[str] = None


@router.get("/ingestion/sources", dependencies=[Depends(require_admin)])
async def list_sources_admin(db: AsyncSession = Depends(get_db)):
    """List all sources with their current config and status."""
    result = await db.execute(text("""
        SELECT id, name, type, is_active, poll_interval, articles_per_crawl, last_crawled_at
        FROM sources
        ORDER BY name
    """))
    rows = result.fetchall()
    return [
        {
            "id": str(r[0]),
            "name": r[1],
            "type": r[2],
            "is_active": r[3],
            "poll_interval": r[4],
            "articles_per_crawl": r[5],
            "last_crawled_at": r[6].isoformat() if r[6] else None
        }
        for r in rows
    ]


@router.patch("/ingestion/sources/{source_id}", dependencies=[Depends(require_admin)])
async def update_source_admin(source_id: uuid.UUID, update: SourceUpdate, db: AsyncSession = Depends(get_db)):
    """Update source-level config (toggle active, interval, etc.)."""
    update_data = update.model_dump(exclude_unset=True)
    if not update_data:
        return {"message": "No changes provided"}

    set_clause = ", ".join([f"{k} = :{k}" for k in update_data.keys()])
    params = {**update_data, "id": source_id}

    result = await db.execute(text(f"UPDATE sources SET {set_clause} WHERE id = :id"), params)
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Source not found")
    
    return {"message": "Source updated successfully"}


@router.get("/ingestion/sources/{source_id}/feeds", dependencies=[Depends(require_admin)])
async def list_source_feeds_admin(source_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List all RSS feeds for a specific source."""
    result = await db.execute(text("""
        SELECT id, feed_url, feed_label, is_active, articles_per_crawl
        FROM rss_feed_configs
        WHERE source_id = :source_id
        ORDER BY feed_label
    """), {"source_id": source_id})
    rows = result.fetchall()
    return [
        {
            "id": str(r[0]),
            "feed_url": r[1],
            "feed_label": r[2],
            "is_active": r[3],
            "articles_per_crawl": r[4]
        }
        for r in rows
    ]


@router.patch("/ingestion/feeds/{feed_id}", dependencies=[Depends(require_admin)])
async def update_feed_admin(feed_id: uuid.UUID, update: FeedUpdate, db: AsyncSession = Depends(get_db)):
    """Update feed-level config (toggle active, limit)."""
    update_data = update.model_dump(exclude_unset=True)
    if not update_data:
        return {"message": "No changes provided"}

    set_clause = ", ".join([f"{k} = :{k}" for k in update_data.keys()])
    params = {**update_data, "id": feed_id}

    result = await db.execute(text(f"UPDATE rss_feed_configs SET {set_clause} WHERE id = :id"), params)
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Feed not found")
    
    return {"message": "Feed updated successfully"}


@router.get("/ingestion/reddit/subreddits", dependencies=[Depends(require_admin)])
async def list_reddit_subreddits_admin(db: AsyncSession = Depends(get_db)):
    """List all subreddits being monitored."""
    result = await db.execute(text("SELECT id, name, limit_per_crawl, sort, is_active FROM reddit_subreddits ORDER BY name"))
    rows = result.fetchall()
    return [
        {
            "id": str(r[0]),
            "name": r[1],
            "limit_per_crawl": r[2],
            "sort": r[3],
            "is_active": r[4]
        }
        for r in rows
    ]


@router.post("/ingestion/reddit/subreddits", dependencies=[Depends(require_admin)])
async def add_reddit_subreddit_admin(subreddit: RedditSubredditCreate, db: AsyncSession = Depends(get_db)):
    """Add a new subreddit to monitor."""
    try:
        await db.execute(text("""
            INSERT INTO reddit_subreddits (name, limit_per_crawl, sort)
            VALUES (:name, :limit_per_crawl, :sort)
        """), subreddit.model_dump())
        await db.commit()
        return {"message": f"Subreddit r/{subreddit.name} added"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/ingestion/reddit/subreddits/{id}", dependencies=[Depends(require_admin)])
async def update_reddit_subreddit_admin(id: uuid.UUID, update: RedditSubredditUpdate, db: AsyncSession = Depends(get_db)):
    """Edit subreddit settings or toggle active state."""
    update_data = update.model_dump(exclude_unset=True)
    if not update_data:
        return {"message": "No changes provided"}

    set_clause = ", ".join([f"{k} = :{k}" for k in update_data.keys()])
    params = {**update_data, "id": id}

    result = await db.execute(text(f"UPDATE reddit_subreddits SET {set_clause} WHERE id = :id"), params)
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Subreddit not found")
    
    return {"message": "Subreddit updated successfully"}


@router.delete("/ingestion/reddit/subreddits/{id}", dependencies=[Depends(require_admin)])
async def delete_reddit_subreddit_admin(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Stop monitoring a subreddit."""
    result = await db.execute(text("DELETE FROM reddit_subreddits WHERE id = :id"), {"id": id})
    await db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Subreddit not found")
        
    return {"message": "Subreddit removed"}


@router.get("/settings", dependencies=[Depends(require_admin)])
async def list_settings_admin(db: AsyncSession = Depends(get_db)):
    """List all system settings. Seeds subtheme_window_days if missing."""
    import json
    from app.config import get_settings
    
    # ── Self-Healing: Seed subtheme settings if missing ──
    settings = get_settings()
    seeds = [
        {
            "key": "subtheme_window_days",
            "value": settings.subtheme_window_days,
            "desc": "Rolling window size (days) for discovery."
        },
        {
            "key": "subtheme_min_cluster_size",
            "value": settings.subtheme_min_cluster_size,
            "desc": "Min articles required to form a sub-theme."
        },
        {
            "key": "subtheme_min_samples",
            "value": settings.subtheme_min_samples,
            "desc": "Noise control. Lower = more granular, but more noise."
        },
        {
            "key": "subtheme_cluster_selection_method",
            "value": settings.subtheme_cluster_selection_method,
            "desc": "Strategy: 'eom' (broad) or 'leaf' (specific)."
        },
        {
            "key": "subtheme_reddit_assign_threshold",
            "value": settings.subtheme_reddit_assign_threshold,
            "desc": "Similarity threshold for Reddit -> News mapping (0.0 to 1.0)."
        },
        {
            "key": "subtheme_discovery_interval_hours",
            "value": settings.subtheme_discovery_interval_hours,
            "desc": "Global interval (hours) between discovery runs."
        },
        {
            "key": "subtheme_umap_n_components",
            "value": settings.subtheme_umap_n_components,
            "desc": "UMAP dimensions before HDBSCAN (10 recommended for 768-dim embeddings)."
        },
        {
            "key": "subtheme_centroid_match_threshold",
            "value": settings.subtheme_centroid_match_threshold,
            "desc": "Min cosine similarity for a cluster to inherit an existing sub-theme identity (0.85 recommended)."
        },
        {
            "key": "subtheme_relabel_volume_change_threshold",
            "value": settings.subtheme_relabel_volume_change_threshold,
            "desc": "Volume growth vs last label time to trigger AI relabeling (0.50 = 50%)."
        }

    ]

    for seed in seeds:
        check = await db.execute(text("SELECT 1 FROM system_settings WHERE key = :key"), {"key": seed["key"]})
        if not check.fetchone():
            await db.execute(
                text("INSERT INTO system_settings (key, value, description) VALUES (:key, :value, :desc)"),
                {
                    "key": seed["key"],
                    "value": json.dumps(seed["value"]),
                    "desc": seed["desc"]
                }
            )
    await db.commit()

    result = await db.execute(text("SELECT key, value, description FROM system_settings ORDER BY key"))
    rows = result.fetchall()
    return [{"key": r[0], "value": r[1], "description": r[2]} for r in rows]


@router.patch("/settings/{key}", dependencies=[Depends(require_admin)])
async def update_setting_admin(key: str, update: SystemSettingUpdate, db: AsyncSession = Depends(get_db)):
    """Update a specific system setting."""
    import json
    # Ensure value is treated as JSONB by passing it as a JSON string
    result = await db.execute(
        text("UPDATE system_settings SET value = :value, updated_at = NOW() WHERE key = :key"), 
        {"key": key, "value": json.dumps(update.value)}
    )
    await db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Setting not found")
        
    return {"message": f"Setting {key} updated"}
