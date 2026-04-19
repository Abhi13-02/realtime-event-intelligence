"""Debug routes — internal use only, not for frontend."""

import asyncio
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.db.session import get_db
from app.celery_app import celery_app
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/users")
async def list_all_users(db: AsyncSession = Depends(get_db)):
    """All users in the DB. No auth, debug only."""
    result = await db.execute(text("""
        SELECT id, name, email, created_at
        FROM users
        ORDER BY created_at DESC
    """))
    rows = result.fetchall()
    return {
        "total_users": len(rows),
        "users": [
            {
                "id":         str(r[0]),
                "name":       r[1],
                "email":      r[2],
                "created_at": r[3].isoformat() if r[3] else None,
            }
            for r in rows
        ],
    }


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
    """Sub-themes per topic with keywords, representative article, latest snapshot stats, and member articles."""
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
            arts.articles_json
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
            snap.sentiment_score,
            arts.articles_json
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
            "sentiment_score":   r[9],
            "articles":          r[10] or [],
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


@router.get("/topics/articles")
async def list_articles_by_topic(db: AsyncSession = Depends(get_db)):
    """
    For every topic in the DB, list its matched articles ordered by crawled_at DESC.
    Each topic block leads with its article_count. Global (no auth, no user filter).
    """
    result = await db.execute(text("""
        SELECT
            t.id           AS topic_id,
            t.name         AS topic_name,
            t.user_id      AS user_id,
            a.id           AS article_id,
            a.headline     AS headline,
            a.url          AS url,
            a.summary      AS summary,
            a.pipeline_status AS pipeline_status,
            a.published_at AS published_at,
            a.crawled_at   AS crawled_at,
            atm.relevance_score AS relevance_score
        FROM topics t
        LEFT JOIN article_topic_matches atm ON atm.topic_id = t.id
        LEFT JOIN articles a                ON a.id = atm.article_id
        ORDER BY t.name ASC, a.crawled_at DESC NULLS LAST
    """))
    rows = result.fetchall()

    topics: dict = {}
    for r in rows:
        tid = str(r.topic_id)
        if tid not in topics:
            topics[tid] = {
                "topic_id": tid,
                "topic_name": r.topic_name,
                "user_id": str(r.user_id),
                "article_count": 0,
                "articles": [],
            }
        if r.article_id is None:
            continue
        topics[tid]["article_count"] += 1
        topics[tid]["articles"].append({
            "id": str(r.article_id),
            "headline": r.headline,
            "url": r.url,
            "summary": r.summary,
            "pipeline_status": r.pipeline_status,
            "relevance_score": float(r.relevance_score) if r.relevance_score is not None else None,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "crawled_at": r.crawled_at.isoformat() if r.crawled_at else None,
        })

    return {
        "total_topics": len(topics),
        "topics": list(topics.values()),
    }


@router.get("/topics/alerts")
async def list_alerts_by_topic(db: AsyncSession = Depends(get_db)):
    """
    For every topic in the DB, list every alert ever generated across all users.
    Each topic block leads with its alert_count. Global (no auth, no user filter).
    """
    result = await db.execute(text("""
        SELECT
            t.id           AS topic_id,
            t.name         AS topic_name,
            al.id          AS alert_id,
            al.user_id     AS user_id,
            al.article_id  AS article_id,
            ar.headline    AS headline,
            ar.url         AS url,
            ar.summary     AS summary,
            al.channel     AS channel,
            al.status      AS status,
            al.relevance_score AS relevance_score,
            al.sent_at     AS sent_at,
            al.created_at  AS created_at
        FROM topics t
        LEFT JOIN alerts al   ON al.topic_id = t.id
        LEFT JOIN articles ar ON ar.id = al.article_id
        ORDER BY t.name ASC, al.created_at DESC NULLS LAST
    """))
    rows = result.fetchall()

    topics: dict = {}
    for r in rows:
        tid = str(r.topic_id)
        if tid not in topics:
            topics[tid] = {
                "topic_id": tid,
                "topic_name": r.topic_name,
                "alert_count": 0,
                "alerts": [],
            }
        if r.alert_id is None:
            continue
        topics[tid]["alert_count"] += 1
        topics[tid]["alerts"].append({
            "id": str(r.alert_id),
            "user_id": str(r.user_id),
            "article_id": str(r.article_id),
            "headline": r.headline,
            "url": r.url,
            "summary": r.summary,
            "channel": r.channel,
            "status": r.status,
            "relevance_score": float(r.relevance_score) if r.relevance_score is not None else None,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {
        "total_topics": len(topics),
        "topics": list(topics.values()),
    }


@router.get("/topics/subtopics")
async def list_all_topics_with_subtopics(db: AsyncSession = Depends(get_db)):
    """All topics across all users with their subtopics. No auth, debug only."""
    result = await db.execute(text("""
        SELECT
            t.id            AS topic_id,
            t.name          AS topic_name,
            t.description   AS topic_description,
            t.user_id       AS user_id,
            ts.id           AS subtopic_id,
            ts.description  AS subtopic_description,
            ts.created_at   AS subtopic_created_at
        FROM topics t
        LEFT JOIN topic_subtopics ts ON ts.topic_id = t.id
        ORDER BY t.name ASC, ts.created_at ASC
    """))
    rows = result.fetchall()

    topics: dict = {}
    for r in rows:
        tid = str(r.topic_id)
        if tid not in topics:
            topics[tid] = {
                "topic_id":          tid,
                "topic_name":        r.topic_name,
                "topic_description": r.topic_description,
                "user_id":           str(r.user_id),
                "subtopic_count":    0,
                "subtopics":         [],
            }
        if r.subtopic_id is None:
            continue
        topics[tid]["subtopic_count"] += 1
        topics[tid]["subtopics"].append({
            "id":          str(r.subtopic_id),
            "description": r.subtopic_description,
            "created_at":  r.subtopic_created_at.isoformat() if r.subtopic_created_at else None,
        })

    return {
        "total_topics": len(topics),
        "topics": list(topics.values()),
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


@router.delete("/subthemes")
async def delete_all_subthemes(db: AsyncSession = Depends(get_db)):
    """
    Wipe ALL sub_themes rows for every topic.
    Cascades automatically to:
      - sub_theme_memberships  (ON DELETE CASCADE)
      - sub_theme_snapshots    (ON DELETE CASCADE)
      - intelligence_alerts    (ON DELETE CASCADE)
    The next discovery run will re-cluster from scratch and treat all
    clusters as brand-new, firing sub_theme_emerging events again.
    Debug use only.
    """
    # Count snapshots and memberships before deleting so we can report them
    snap_result = await db.execute(text("SELECT COUNT(*) FROM sub_theme_snapshots"))
    snap_count = snap_result.scalar()

    mem_result = await db.execute(text("SELECT COUNT(*) FROM sub_theme_memberships"))
    mem_count = mem_result.scalar()

    alert_result = await db.execute(text("SELECT COUNT(*) FROM intelligence_alerts"))
    alert_count = alert_result.scalar()

    # Deleting sub_themes cascades to everything else automatically
    st_result = await db.execute(text("DELETE FROM sub_themes"))
    await db.commit()

    return {
        "message": "All sub-themes and their cascaded data deleted successfully.",
        "deleted": {
            "sub_themes":           st_result.rowcount,
            "sub_theme_snapshots":  snap_count,
            "sub_theme_memberships": mem_count,
            "intelligence_alerts":  alert_count,
        },
        "note": "Next discovery run will re-cluster from scratch. All clusters will fire sub_theme_emerging."
    }
