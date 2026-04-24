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
