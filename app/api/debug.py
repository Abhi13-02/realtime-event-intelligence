"""Debug routes — internal use only, not for frontend."""

import asyncio
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.db.session import get_db
from app.celery_app import celery_app
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/sources")
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


@router.get("/pipeline")
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


@router.get("/subthemes")
async def subtheme_stats(db: AsyncSession = Depends(get_db)):
    """Sub-themes per topic with keywords, representative article, and latest snapshot stats."""
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
            snap.sentiment_label
        FROM topics t
        JOIN sub_themes st ON st.topic_id = t.id
        LEFT JOIN articles a ON a.id = st.representative_article_id
        LEFT JOIN LATERAL (
            SELECT article_count, reddit_post_count, total_volume, sentiment_label
            FROM sub_theme_snapshots
            WHERE sub_theme_id = st.id
            ORDER BY snapshot_at DESC
            LIMIT 1
        ) snap ON TRUE
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
            "sentiment":         r[9],
        }
        for r in rows
    ]


@router.post("/subthemes/trigger")
async def trigger_discovery(db: AsyncSession = Depends(get_db)):
    """
    Trigger sub-theme discovery synchronously and return results when done.
    Blocks until the Celery task completes (max 3 minutes).
    Debug use only.
    """
    task = celery_app.send_task("app.tasks.subtheme_discovery.run_subtheme_discovery")

    try:
        # Wait for the task to finish in a thread so we don't block the event loop
        await asyncio.to_thread(task.get, timeout=180)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Discovery task failed: {exc}")

    # Return the same sub-themes view as GET /debug/subthemes
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
            snap.sentiment_label
        FROM topics t
        JOIN sub_themes st ON st.topic_id = t.id
        LEFT JOIN articles a ON a.id = st.representative_article_id
        LEFT JOIN LATERAL (
            SELECT article_count, reddit_post_count, total_volume, sentiment_label
            FROM sub_theme_snapshots
            WHERE sub_theme_id = st.id
            ORDER BY snapshot_at DESC
            LIMIT 1
        ) snap ON TRUE
        ORDER BY t.name, snap.total_volume DESC NULLS LAST
    """))
    rows = result.fetchall()

    # Group sub-themes by topic so topic_description appears once
    topics: dict = {}
    for r in rows:
        topic_name = r[0]
        if topic_name not in topics:
            topics[topic_name] = {
                "topic":             topic_name,
                "topic_description": r[1],
                "subtheme_count":    0,
                "sub_themes":        [],
            }
        topics[topic_name]["subtheme_count"] = topics[topic_name].get("subtheme_count", 0) + 1
        topics[topic_name]["sub_themes"].append({
            "label":             r[2],
            "status":            r[3],
            "keywords":          r[4],
            "centroid_article":  r[5],
            "article_count":     r[6],
            "reddit_post_count": r[7],
            "total_volume":      r[8],
            "sentiment":         r[9],
        })

    return {
        "task_id": task.id,
        "topics":  list(topics.values()),
    }


@router.get("/articles")
async def list_articles_debug(db: AsyncSession = Depends(get_db)):
    """List all articles (excluding heavy embedding column) for debugging."""
    count_result = await db.execute(text("SELECT COUNT(*) FROM articles"))
    total_count = count_result.scalar()

    result = await db.execute(text("""
        SELECT 
            id, source_id, url, headline, content, summary, 
            pipeline_status, published_at, crawled_at 
        FROM articles 
        ORDER BY crawled_at DESC
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
            }
            for r in rows
        ]
    }


@router.delete("/articles")
async def delete_all_articles(db: AsyncSession = Depends(get_db)):
    """Wipe all articles (and cascaded data). Simple no-guard delete."""
    result = await db.execute(text("DELETE FROM articles"))
    await db.commit()
    
    return {
        "message": "All articles deleted successfully.",
        "deleted_count": result.rowcount
    }
