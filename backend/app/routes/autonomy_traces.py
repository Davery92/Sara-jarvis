"""
Autonomy action trace routes — observability for autonomous actions.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.services.autonomy.action_tracer import ActionTracer

router = APIRouter(prefix="/autonomy", tags=["autonomy"])

_tracer = ActionTracer()


@router.get("/traces")
async def get_traces(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    source: Optional[str] = Query(None),
    action_name: Optional[str] = Query(None),
    hours: int = Query(24, ge=1, le=168),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get recent action traces with optional filters."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    traces = await _tracer.get_recent_traces(
        db=db,
        user_id=str(current_user.id),
        limit=limit,
        offset=offset,
        source=source,
        action_name=action_name,
        since=since,
    )
    return {"traces": traces, "count": len(traces)}


@router.get("/traces/stats")
async def get_trace_stats(
    hours: int = Query(24, ge=1, le=168),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregate stats for action traces."""
    stats = await _tracer.get_trace_stats(
        db=db,
        user_id=str(current_user.id),
        hours=hours,
    )
    return stats
