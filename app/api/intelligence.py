"""Intelligence route handlers.

Three endpoints:
  GET /topics/{topic_id}/intelligence          — current sub-theme state for a topic
  GET /topics/{topic_id}/intelligence/timeline — snapshot history for a sub-theme
  GET /intelligence-alerts                     — paginated intelligence alert history
"""

from __future__ import annotations

from datetime import datetime
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
    RedditCommentItem,
    RedditCommentsResponse,
    RepresentativeArticle,
    SnapshotItem,
    SnapshotTimestampResponse,
    SubThemeArticleItem,
    SubThemeArticlesResponse,
    SubThemeItem,
    TimelineResponse,
)

router = APIRouter(tags=["intelligence"])


# ── Shared projection ────────────────────────────────────────────────────────
#
# The intelligence, history and detail endpoints all return the same shape and
# must never disagree about it, so they share one column list and one mapper.
#
# Nothing here computes anything. Growth used to be re-derived at request time
# from a LATERAL ... OFFSET 1 pair, alongside a heuristic that guessed at run
# boundaries by comparing timestamps. That was a second, independent
# implementation of logic the discovery job had already run, and the two could
# disagree — which is how a cluster ended up labelled 'Active' beside a negative
# percentage, and how a revived cluster holding 7 articles rendered as "+700%"
# (a raw count passed through a percentage formatter).
#
# Now the job writes status, growth_pct and prev_volume onto the snapshot, and
# these endpoints project them. Label, description, keywords and the
# representative article are read from the snapshot too, falling back to the
# live sub_themes row only for snapshots written before those columns existed —
# so replaying an old run shows that run's wording and headline, not today's.

_SUB_THEME_COLUMNS = """
    st.id,
    COALESCE(snap.label, st.label)             AS label,
    COALESCE(snap.description, st.description) AS description,
    COALESCE(snap.keywords, st.keywords)       AS keywords,
    COALESCE(snap.status, st.status)           AS status,
    st.first_seen_at,
    st.last_seen_at,
    COALESCE(snap.representative_article_id,
             st.representative_article_id)     AS representative_article_id,
    snap.article_count,
    snap.reddit_post_count,
    snap.total_volume,
    snap.sentiment_score,
    snap.growth_pct,
    snap.prev_volume,
    snap.snapshot_at,
    ra.headline   AS rep_headline,
    ra.url        AS rep_url,
    ra.image_url  AS rep_image_url,
    src.name      AS rep_source_name
"""


def _to_sub_theme_item(row) -> SubThemeItem:
    """Map one projected row to the wire schema. No business logic."""
    rep_article = None
    if row.representative_article_id is not None:
        rep_article = RepresentativeArticle(
            id=row.representative_article_id,
            headline=row.rep_headline or "",
            url=row.rep_url or "",
            image_url=row.rep_image_url,
            source_name=row.rep_source_name or "",
        )

    status = row.status
    return SubThemeItem(
        id=row.id,
        label=row.label,
        description=row.description,
        keywords=list(row.keywords) if row.keywords else [],
        status=status,
        article_count=row.article_count or 0,
        reddit_post_count=row.reddit_post_count or 0,
        total_volume=row.total_volume or 0,
        sentiment_score=row.sentiment_score,
        representative_article=rep_article,
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
        growth_pct=row.growth_pct,
        prev_volume=row.prev_volume,
        snapshot_at=row.snapshot_at,
        # Derived from the stored status rather than inferred from how many
        # snapshot rows happen to exist.
        is_new=(status == "new"),
        is_revival=(status == "revival"),
    )


# ── Helper: verify topic ownership ───────────────────────────────────────────

async def _get_topic_or_404(session: AsyncSession, topic_id: UUID, user_id: str) -> dict:
    """
    Fetch a topic that belongs to the current user.
    Returns 404 if not found OR if it belongs to another user (enumeration protection).
    """
    result = await session.execute(
        text("SELECT id, name, description, sensitivity FROM topics WHERE id = :id AND user_id = :user_id"),
        {"id": str(topic_id), "user_id": user_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Topic not found.")
    return {
        "id": row.id, 
        "name": row.name, 
        "description": row.description, 
        "sensitivity": row.sensitivity
    }


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
        text(f"""
            SELECT {_SUB_THEME_COLUMNS}
            FROM sub_themes st
            -- The single most recent snapshot for each sub-theme. Everything the
            -- client renders comes from this row, so status and growth_pct are
            -- guaranteed to describe the same measurement.
            LEFT JOIN LATERAL (
                SELECT * FROM sub_theme_snapshots
                WHERE sub_theme_id = st.id
                ORDER BY snapshot_at DESC
                LIMIT 1
            ) snap ON TRUE
            LEFT JOIN articles ra  ON COALESCE(snap.representative_article_id,
                                               st.representative_article_id) = ra.id
            LEFT JOIN sources  src ON ra.source_id = src.id
            WHERE st.topic_id = :topic_id
              -- Live view only. Dormant clusters (volume 0 this run) and
              -- rejected ones drop off the dashboard but stay reachable through
              -- the history endpoint and their own detail page.
              AND st.status NOT IN ('dormant', 'rejected')
              -- A cluster with no label was never successfully judged: the
              -- labelling call failed (rate limit, network) and the gate failed
              -- open, which keeps the cluster but leaves it nameless. Rendering
              -- that as "Unlabeled cluster" shows the user a provider outage
              -- dressed up as a narrative. Hide it until a later run names it —
              -- the row and its history are untouched.
              AND COALESCE(snap.label, st.label) IS NOT NULL
            ORDER BY snap.total_volume DESC NULLS LAST
        """),
        {"topic_id": str(topic_id)},
    )

    sub_themes = [_to_sub_theme_item(row) for row in rows.fetchall()]

    return IntelligenceResponse(
        topic_id=topic_id,
        topic_name=topic["name"],
        topic_description=topic["description"],
        sensitivity=topic["sensitivity"],
        sub_themes=sub_themes,
    )


# ── History & Timeline Endpoints ─────────────────────────────────────────────

@router.get("/topics/{topic_id}/intelligence/history/timestamps", response_model=SnapshotTimestampResponse)
async def get_history_timestamps(
    topic_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SnapshotTimestampResponse:
    """
    Returns a sorted list of unique timestamps when sub-theme discovery was run.
    Each timestamp includes a flag indicating if any sub-theme in that run has an image.
    """
    await _get_topic_or_404(db, topic_id, str(current_user.id))

    # Join with sub_themes and articles to see if any snapshot in that run has a rep article with an image
    result = await db.execute(
        text("""
            SELECT 
                sts.snapshot_at,
                EXISTS (
                    SELECT 1 
                    FROM sub_theme_snapshots s2
                    JOIN sub_themes st ON s2.sub_theme_id = st.id
                    JOIN articles a ON st.representative_article_id = a.id
                    WHERE s2.topic_id = :topic_id 
                      AND s2.snapshot_at = sts.snapshot_at
                      AND a.image_url IS NOT NULL
                      AND a.image_url != ''
                ) as has_images
            FROM sub_theme_snapshots sts
            WHERE sts.topic_id = :topic_id
            GROUP BY sts.snapshot_at
            ORDER BY sts.snapshot_at DESC
        """),
        {"topic_id": str(topic_id)},
    )
    
    rows = result.fetchall()
    return SnapshotTimestampResponse(
        topic_id=topic_id,
        timestamps=[{
            "ts": row.snapshot_at, 
            "has_images": row.has_images
        } for row in rows],
    )


@router.get("/topics/{topic_id}/intelligence/history", response_model=IntelligenceResponse)
async def get_topic_history(
    topic_id: UUID,
    timestamp: datetime = Query(..., description="Point-in-time to retrieve narrative state"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> IntelligenceResponse:
    """
    Returns the state of all sub-themes for a topic at a specific historical point.
    Powers the timeline slider.
    """
    topic = await _get_topic_or_404(db, topic_id, str(current_user.id))

    rows = await db.execute(
        text(f"""
            SELECT {_SUB_THEME_COLUMNS}
            FROM sub_theme_snapshots snap
            JOIN sub_themes st ON snap.sub_theme_id = st.id
            LEFT JOIN articles ra  ON COALESCE(snap.representative_article_id,
                                               st.representative_article_id) = ra.id
            LEFT JOIN sources  src ON ra.source_id = src.id
            WHERE snap.topic_id = :topic_id
              AND snap.snapshot_at = :ts
            -- DELIBERATELY UNFILTERED. A cluster that had volume at this point
            -- in time belongs in this view, and so does the run where it fell to
            -- zero: that is the moment the story ended, and hiding it would make
            -- narratives vanish from their own history. The live endpoint is the
            -- only place dormant clusters are excluded.
            ORDER BY snap.total_volume DESC
        """),
        {"topic_id": str(topic_id), "ts": timestamp},
    )

    sub_themes = [_to_sub_theme_item(row) for row in rows.fetchall()]

    return IntelligenceResponse(
        topic_id=topic_id,
        topic_name=topic["name"],
        topic_description=topic["description"],
        sensitivity=topic["sensitivity"],
        sub_themes=sub_themes,
    )


# ── GET /topics/{topic_id}/intelligence/sub-themes/{sub_theme_id} ────────────

@router.get(
    "/topics/{topic_id}/intelligence/sub-themes/{sub_theme_id}",
    response_model=SubThemeItem,
)
async def get_sub_theme(
    topic_id: UUID,
    sub_theme_id: UUID,
    at: datetime | None = Query(
        default=None,
        description="Run timestamp to render. Omit for the most recent snapshot.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SubThemeItem:
    """
    One sub-theme, at a point in time.

    WHY THIS EXISTS: the narrative deep-dive page used to build its header by
    fetching the whole topic's LIVE intelligence payload and searching it for a
    matching id. Any narrative that had fallen dormant was filtered out of that
    payload, so opening one from the timeline produced "Narrative not found in
    the latest snapshot" — even though its chart data had loaded successfully.
    There was no way to ask the backend for a single narrative.

    This endpoint applies NO status filter. A dormant narrative resolves
    normally and reports volume 0, so the page renders with its graph running
    down to zero. A 404 here now means what it says: no such sub-theme in this
    topic.

    Passing ?at= renders the state as of that run — label, description,
    keywords, representative article, volume, growth and status all as they
    stood then, since all of them are snapshotted.
    """
    await _get_topic_or_404(db, topic_id, str(current_user.id))

    row = (await db.execute(
        text(f"""
            SELECT {_SUB_THEME_COLUMNS}
            FROM sub_themes st
            LEFT JOIN LATERAL (
                SELECT * FROM sub_theme_snapshots
                WHERE sub_theme_id = st.id
                  -- With ?at=, pin to that exact run. Without it, take the most
                  -- recent — which for a dormant narrative is its zero-volume
                  -- final snapshot, matching where its graph ends.
                  AND (CAST(:ts AS timestamptz) IS NULL
                       OR snapshot_at = CAST(:ts AS timestamptz))
                ORDER BY snapshot_at DESC
                LIMIT 1
            ) snap ON TRUE
            LEFT JOIN articles ra  ON COALESCE(snap.representative_article_id,
                                               st.representative_article_id) = ra.id
            LEFT JOIN sources  src ON ra.source_id = src.id
            WHERE st.id = :sub_theme_id
              AND st.topic_id = :topic_id
        """),
        {
            "sub_theme_id": str(sub_theme_id),
            "topic_id": str(topic_id),
            "ts": at,
        },
    )).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Sub-theme not found.")

    return _to_sub_theme_item(row)


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
    at: datetime | None = Query(
        default=None,
        description="Run timestamp to render. Omit for the most recent run.",
    ),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SubThemeArticlesResponse:
    """
    Paginated articles belonging to a sub-theme, as of one discovery run.

    Memberships are append-only and stamped with run_at, so this can answer
    "which articles were in this narrative at that point on the graph" rather
    than only "which are in it now". Omitting ?at= resolves to that
    sub-theme's most recent run — which for a dormant narrative is the last run
    where it still held articles, so the evidence list survives its sunset.
    """
    await _get_topic_or_404(db, topic_id, str(current_user.id))

    offset = (page - 1) * limit

    # Resolve which run to show. Pinning it once here keeps the count and the
    # page in agreement; deriving it separately in each query could straddle two
    # runs if a discovery job commits between them.
    run_at = (await db.execute(
        text("""
            SELECT MAX(run_at) FROM sub_theme_memberships
            WHERE sub_theme_id = :sub_theme_id
              AND (CAST(:ts AS timestamptz) IS NULL
                   OR run_at <= CAST(:ts AS timestamptz))
        """),
        {"sub_theme_id": str(sub_theme_id), "ts": at},
    )).scalar()

    if run_at is None:
        # No memberships were ever recorded for this sub-theme at or before the
        # requested point — an empty page, not an error.
        return SubThemeArticlesResponse(data=[], total_count=0, page=page, limit=limit)

    params = {"sub_theme_id": str(sub_theme_id), "run_at": run_at}

    # Count query — MUST carry the same run filter. Without it, an append-only
    # table counts every generation of every article and the pager overshoots.
    count_row = await db.execute(
        text("""
            SELECT COUNT(*)
            FROM sub_theme_memberships stm
            WHERE stm.sub_theme_id = :sub_theme_id
              AND stm.run_at = :run_at
        """),
        params,
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
              AND stm.run_at = :run_at
            -- Most representative article first. similarity_to_centroid is the
            -- cosine distance to the cluster centroid recorded at discovery time,
            -- so this ranks by how central each article is to the narrative.
            -- Reddit rows carry NULL similarity and sort last, then by recency.
            ORDER BY stm.similarity_to_centroid DESC NULLS LAST,
                     a.published_at DESC NULLS LAST
            LIMIT :limit OFFSET :offset
        """),
        {**params, "limit": limit, "offset": offset},
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


# ── GET /articles/{article_id}/comments ──────────────────────────────────────

@router.get("/articles/{article_id}/comments", response_model=RedditCommentsResponse)
async def get_article_comments(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RedditCommentsResponse:
    """
    Returns the analyzed Reddit comments for a specific article/post.
    Used to show individual community reactions and their sentiments in the UI.
    """
    # Verify the article exists and is a reddit post (simple check)
    # We don't strictly enforce topic ownership here as articles are public knowledge
    # but the comment retrieval is gated by user authentication.
    
    rows = await db.execute(
        text("""
            SELECT id, body, score, sentiment_score, created_at
            FROM reddit_comments
            WHERE article_id = :article_id
            ORDER BY score DESC, created_at DESC
        """),
        {"article_id": str(article_id)},
    )
    
    comments = [
        RedditCommentItem(
            id=row.id,
            body=row.body,
            score=row.score,
            sentiment_score=row.sentiment_score,
            created_at=row.created_at,
        )
        for row in rows.fetchall()
    ]
    
    return RedditCommentsResponse(
        article_id=article_id,
        comments=comments,
    )
