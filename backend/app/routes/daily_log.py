"""
Daily Log / Diary routes — DAILY_LOG_DIARY_PLAN_2026_08_25 Phase 4.

Read surface over `day_replay_cache`: the nightly dream cycle writes the prose
into `summary` and the structured facts into `replay_data`; this exposes both,
plus a regenerate endpoint that doubles as the backfill path (every collector
is date-parameterized, so any past date works immediately).

Mounted at /api/daily-log.
"""
import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.timezone import today as local_today
from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/daily-log", tags=["Daily Log"])

MAX_LIMIT = 120


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date '{value}', expected YYYY-MM-DD")


def _require_complete_day(day: date) -> None:
    """Only completed ET days can be logged — today is still happening."""
    today = local_today()
    if day >= today:
        raise HTTPException(
            status_code=400,
            detail=f"{day.isoformat()} is not a completed day (today is {today.isoformat()} ET)",
        )


def _load_replay_data(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _section_counts(replay_data: Dict[str, Any]) -> Dict[str, int]:
    """Per-source event counts, for the list view's at-a-glance chips."""
    summary = replay_data.get("summary") or {}
    by_source = summary.get("by_source") or {}
    if by_source:
        return {k: int(v) for k, v in by_source.items()}
    counts: Dict[str, int] = {}
    for event in replay_data.get("events") or []:
        source = event.get("source") or "unknown"
        counts[source] = counts.get(source, 0) + 1
    return counts


@router.get("")
async def list_daily_logs(
    limit: int = Query(30, ge=1, le=MAX_LIMIT),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Newest-first list of diary entries. Prose + section counts, no event bodies."""
    rows = db.execute(
        text("""
            SELECT replay_date, summary, replay_data, data_sources, created_at
            FROM day_replay_cache
            WHERE user_id = :user_id
            ORDER BY replay_date DESC
            LIMIT :limit
        """),
        {"user_id": current_user.id, "limit": limit},
    ).fetchall()

    entries = []
    for row in rows:
        replay_data = _load_replay_data(row.replay_data)
        entries.append({
            "date": row.replay_date.isoformat(),
            "weekday": row.replay_date.strftime("%A"),
            "diary": row.summary,
            "sections_summary": _section_counts(replay_data),
            "total_events": len(replay_data.get("events") or []),
            "data_sources": list(row.data_sources or []),
            "generated_at": row.created_at.isoformat() if row.created_at else None,
        })

    return {"entries": entries, "count": len(entries)}


@router.get("/{log_date}")
async def get_daily_log(
    log_date: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """One entry: the diary prose plus the structured receipts behind it."""
    day = _parse_date(log_date)

    row = db.execute(
        text("""
            SELECT replay_date, summary, replay_data, data_sources, created_at
            FROM day_replay_cache
            WHERE user_id = :user_id AND replay_date = :replay_date
        """),
        {"user_id": current_user.id, "replay_date": day},
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"No daily log for {day.isoformat()}")

    replay_data = _load_replay_data(row.replay_data)
    events = replay_data.get("events") or []

    # Group the flat event list by source so the UI can render one receipts
    # table per section without re-deriving the grouping client-side.
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for event in events:
        by_source.setdefault(event.get("source") or "unknown", []).append(event)

    return {
        "date": row.replay_date.isoformat(),
        "weekday": row.replay_date.strftime("%A"),
        "diary": row.summary,
        "sections": by_source,
        "sections_summary": _section_counts(replay_data),
        "total_events": len(events),
        "data_sources": list(row.data_sources or []),
        "generated_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/{log_date}/regenerate")
async def regenerate_daily_log(
    log_date: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Re-run the whole pipeline for a date.

    Doubles as backfill: the collectors are date-parameterized, so a date that
    was never processed builds from scratch. Future dates and today are
    rejected — the day has to be over for the log to be true.
    """
    day = _parse_date(log_date)
    _require_complete_day(day)

    from app.services.daily_log_service import daily_log_service

    try:
        result = await daily_log_service.generate(db, current_user.id, day)
    except Exception as e:
        logger.error(f"Daily log regenerate failed for {day}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to regenerate daily log: {e}")

    return result.to_dict()
