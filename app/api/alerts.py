"""Alert route handlers."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.alerts import AlertItem, AlertListResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=AlertListResponse)
async def list_alerts(
    topic_id: UUID | None = Query(default=None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertListResponse:
    """
    List all alerts for the authenticated user, newest first.
    Optionally filter by topic_id (used by the per-topic timeline view).

    Joins alerts → topics → articles → sources to assemble the full response
    shape in one query — no extra round trips needed from the frontend.
    """
    offset = (page - 1) * limit
    params: dict = {"user_id": str(current_user.id), "limit": limit, "offset": offset}

    topic_filter = ""
    if topic_id is not None:
        topic_filter = "AND a.topic_id = :topic_id"
        params["topic_id"] = str(topic_id)

    rows = await db.execute(
        text(f"""
            SELECT
                a.id,
                a.topic_id,
                t.name          AS topic_name,
                a.article_id,
                ar.headline,
                ar.summary,
                ar.url,
                ar.image_url,
                s.name          AS source_name,
                a.relevance_score,
                a.channel,
                a.created_at
            FROM alerts a
            JOIN topics   t  ON a.topic_id   = t.id
            JOIN articles ar ON a.article_id = ar.id
            JOIN sources  s  ON ar.source_id = s.id
            WHERE a.user_id = :user_id
              {topic_filter}
            ORDER BY a.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )

    count_row = await db.execute(
        text(f"""
            SELECT COUNT(*)
            FROM alerts a
            WHERE a.user_id = :user_id
              {topic_filter}
        """),
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    )

    total_count = count_row.scalar() or 0
    data = [AlertItem.model_validate(dict(row._mapping)) for row in rows.fetchall()]

    return AlertListResponse(data=data, total_count=total_count, page=page, limit=limit)


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """
    Delete a single alert from the user's history.
    Returns 404 if not found OR if it belongs to another user (enumeration protection).
    """
    result = await db.execute(
        text("""
            DELETE FROM alerts
            WHERE id = :alert_id AND user_id = :user_id
        """),
        {"alert_id": str(alert_id), "user_id": str(current_user.id)},
    )
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Alert not found.")

    return Response(status_code=status.HTTP_204_NO_CONTENT)
