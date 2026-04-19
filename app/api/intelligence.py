"""Intelligence route handlers.

Three endpoints:
  GET /topics/{topic_id}/intelligence          — current sub-theme state for a topic
  GET /topics/{topic_id}/intelligence/timeline — snapshot history for a sub-theme
  GET /intelligence-alerts                     — paginated intelligence alert history
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.intelligence import (
    IntelligenceAlertItem,
    IntelligenceAlertListResponse,
    IntelligenceResponse,
    RepresentativeArticle,
    SnapshotItem,
    SubThemeArticleItem,
    SubThemeArticlesResponse,
    SubThemeItem,
    TimelineResponse,
)

router = APIRouter(tags=["intelligence"])


# ── Helper: verify topic ownership ───────────────────────────────────────────

async def _get_topic_or_404(session: AsyncSession, topic_id: UUID, user_id: str) -> dict:
    """
    Fetch a topic that belongs to the current user.
    Returns 404 if not found OR if it belongs to another user (enumeration protection).
    """
    result = await session.execute(
        text("SELECT id, name, sensitivity FROM topics WHERE id = :id AND user_id = :user_id"),
        {"id": str(topic_id), "user_id": user_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Topic not found.")
    return {"id": row.id, "name": row.name, "sensitivity": row.sensitivity}


# ── GET /topics/{topic_id}/intelligence ──────────────────────────────────────

@router.get("/topics/{topic_id}/intelligence", response_model=IntelligenceResponse)
async def get_topic_intelligence(
    topic_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> IntelligenceResponse:
    """
    Returns the current state of all sub-themes for a topic — labels, descriptions,
    volume, sentiment, status, and representative article.

    Reads from sub_themes joined with the most recent sub_theme_snapshots row per
    sub-theme (LATERAL subquery) and articles/sources for the representative article.
    All computation was done by the discovery job — this is a pure read query.
    """
    topic = await _get_topic_or_404(db, topic_id, str(current_user.id))

    rows = await db.execute(
        text("""
            SELECT
                st.id,
                st.label,
                st.description,
                st.keywords,
                st.status,
                st.first_seen_at,
                st.last_seen_at,
                st.representative_article_id,
                -- Most recent snapshot values via LATERAL
                snap.article_count,
                snap.reddit_post_count,
                snap.total_volume,
                snap.sentiment_score,
                -- Representative article detail
                ra.headline   AS rep_headline,
                ra.url        AS rep_url,
                ra.image_url  AS rep_image_url,
                src.name      AS rep_source_name
            FROM sub_themes st
            LEFT JOIN LATERAL (
                SELECT article_count, reddit_post_count, total_volume,
                       sentiment_score
                FROM sub_theme_snapshots
                WHERE sub_theme_id = st.id
                ORDER BY snapshot_at DESC
                LIMIT 1
            ) snap ON TRUE
            LEFT JOIN articles ra  ON st.representative_article_id = ra.id
            LEFT JOIN sources  src ON ra.source_id = src.id
            WHERE st.topic_id = :topic_id
              AND st.status  != 'inactive'
            ORDER BY snap.total_volume DESC NULLS LAST
        """),
        {"topic_id": str(topic_id)},
    )

    sub_themes = []
    for row in rows.fetchall():
        rep_article = None
        if row.representative_article_id is not None:
            rep_article = RepresentativeArticle(
                id=row.representative_article_id,
                headline=row.rep_headline or "",
                url=row.rep_url or "",
                image_url=row.rep_image_url,
                source_name=row.rep_source_name or "",
            )

        sub_themes.append(SubThemeItem(
            id=row.id,
            label=row.label,
            description=row.description,
            keywords=list(row.keywords) if row.keywords else [],
            status=row.status,
            article_count=row.article_count or 0,
            reddit_post_count=row.reddit_post_count or 0,
            total_volume=row.total_volume or 0,
            sentiment_score=row.sentiment_score,
            representative_article=rep_article,
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
        ))

    return IntelligenceResponse(
        topic_id=topic_id,
        topic_name=topic["name"],
        sensitivity=topic["sensitivity"],
        sub_themes=sub_themes,
    )


# ── GET /topics/{topic_id}/intelligence/timeline ─────────────────────────────

@router.get("/topics/{topic_id}/intelligence/timeline", response_model=TimelineResponse)
async def get_intelligence_timeline(
    topic_id: UUID,
    sub_theme_id: UUID = Query(..., description="Sub-theme whose snapshot history to return"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TimelineResponse:
    """
    Returns snapshot history for a specific sub-theme within a topic — how its
    volume and sentiment have changed over time. Powers the timeline view.

    Requires ?sub_theme_id=<uuid>. Snapshots are returned newest-first.
    Uses the composite index idx_sts_sub_theme_snapshot_at for a fast single-index scan.
    """
    await _get_topic_or_404(db, topic_id, str(current_user.id))

    # Verify the sub-theme belongs to this topic (enumeration protection)
    st_check = await db.execute(
        text("""
            SELECT id, label FROM sub_themes
            WHERE id = :sub_theme_id AND topic_id = :topic_id
        """),
        {"sub_theme_id": str(sub_theme_id), "topic_id": str(topic_id)},
    )
    st_row = st_check.fetchone()
    if not st_row:
        raise HTTPException(status_code=404, detail="Sub-theme not found.")

    snap_rows = await db.execute(
        text("""
            SELECT snapshot_at, article_count, reddit_post_count,
                   total_volume, sentiment_score, status
            FROM sub_theme_snapshots
            WHERE sub_theme_id = :sub_theme_id
            ORDER BY snapshot_at DESC
            LIMIT :limit
        """),
        {"sub_theme_id": str(sub_theme_id), "limit": limit},
    )

    snapshots = [
        SnapshotItem(
            snapshot_at=row.snapshot_at,
            article_count=row.article_count,
            reddit_post_count=row.reddit_post_count,
            total_volume=row.total_volume,
            sentiment_score=row.sentiment_score,
            status=row.status,
        )
        for row in snap_rows.fetchall()
    ]

    return TimelineResponse(
        sub_theme_id=sub_theme_id,
        sub_theme_label=st_row.label,
        snapshots=snapshots,
    )


# ── GET /intelligence-alerts ─────────────────────────────────────────────────

@router.get("/intelligence-alerts", response_model=IntelligenceAlertListResponse)
async def list_intelligence_alerts(
    topic_id: UUID | None = Query(default=None),
    alert_type: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> IntelligenceAlertListResponse:
    """
    List all intelligence alerts for the authenticated user, newest first.
    Optionally filter by topic_id and/or alert_type.

    The payload field is returned as-is (stored JSONB snapshot) — no extra JOINs
    needed to get label/description/sentiment since it was persisted at alert time.
    """
    offset = (page - 1) * limit
    params: dict = {
        "user_id": str(current_user.id),
        "limit": limit,
        "offset": offset,
    }

    topic_filter = ""
    if topic_id is not None:
        topic_filter += " AND ia.topic_id = :topic_id"
        params["topic_id"] = str(topic_id)

    type_filter = ""
    if alert_type is not None:
        type_filter += " AND ia.alert_type = :alert_type"
        params["alert_type"] = alert_type

    rows = await db.execute(
        text(f"""
            SELECT
                ia.id,
                ia.alert_type,
                ia.topic_id,
                t.name          AS topic_name,
                ia.sub_theme_id,
                ia.channel,
                ia.status,
                ia.payload,
                ia.created_at
            FROM intelligence_alerts ia
            JOIN topics t ON ia.topic_id = t.id
            WHERE ia.user_id = :user_id
              {topic_filter}
              {type_filter}
            ORDER BY ia.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )

    count_row = await db.execute(
        text(f"""
            SELECT COUNT(*)
            FROM intelligence_alerts ia
            WHERE ia.user_id = :user_id
              {topic_filter}
              {type_filter}
        """),
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    )

    total_count = count_row.scalar() or 0

    data = []
    for row in rows.fetchall():
        # payload may be a dict (asyncpg auto-parses JSONB) or a string
        payload = row.payload if isinstance(row.payload, dict) else {}
        data.append(IntelligenceAlertItem(
            id=row.id,
            alert_type=row.alert_type,
            topic_id=row.topic_id,
            topic_name=row.topic_name,
            sub_theme_id=row.sub_theme_id,
            channel=row.channel,
            status=row.status,
            payload=payload,
            created_at=row.created_at,
        ))

    return IntelligenceAlertListResponse(
        data=data,
        total_count=total_count,
        page=page,
        limit=limit,
    )


# ── GET /topics/{topic_id}/intelligence/sub-themes/{sub_theme_id}/articles ──

@router.get("/topics/{topic_id}/intelligence/sub-themes/{sub_theme_id}/articles", response_model=SubThemeArticlesResponse)
async def get_sub_theme_articles(
    topic_id: UUID,
    sub_theme_id: UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SubThemeArticlesResponse:
    """
    Paginated list of articles currently mapped to a given sub-theme.
    """
    await _get_topic_or_404(db, topic_id, str(current_user.id))

    offset = (page - 1) * limit

    # Count query
    count_row = await db.execute(
        text("""
            SELECT COUNT(*)
            FROM sub_theme_memberships stm
            WHERE stm.sub_theme_id = :sub_theme_id
        """),
        {"sub_theme_id": str(sub_theme_id)},
    )
    total_count = count_row.scalar() or 0

    # Data query
    rows = await db.execute(
        text("""
            SELECT
                a.id, a.headline, a.summary, a.url, a.image_url, a.published_at,
                s.name as source_name,
                stm.membership_type, stm.similarity_to_centroid
            FROM sub_theme_memberships stm
            JOIN articles a ON stm.article_id = a.id
            JOIN sources s ON a.source_id = s.id
            WHERE stm.sub_theme_id = :sub_theme_id
            ORDER BY a.published_at DESC NULLS LAST
            LIMIT :limit OFFSET :offset
        """),
        {
            "sub_theme_id": str(sub_theme_id),
            "limit": limit,
            "offset": offset,
        },
    )

    data = []
    for row in rows.fetchall():
        data.append(SubThemeArticleItem(
            id=row.id,
            headline=row.headline,
            url=row.url,
            image_url=row.image_url,
            summary=row.summary,
            published_at=row.published_at,
            source_name=row.source_name,
            membership_type=row.membership_type,
            similarity_to_centroid=row.similarity_to_centroid,
        ))

    return SubThemeArticlesResponse(
        data=data,
        total_count=total_count,
        page=page,
        limit=limit,
    )
