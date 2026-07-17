"""Overlay data endpoints — surfaces that don't already have a dedicated API.

Backs the standalone /overlay/:kind webapp routes (Desktop Jarvis Overhaul
A2) for the one kind that has no single existing source: `report`, which
spans research briefs, periodic intelligence reports, weekly health
reports, and finished background-task results.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/overlay", tags=["Overlay"])


def _latest_research_brief(db: Session, user_id: str) -> Optional[Dict[str, Any]]:
    row = db.execute(
        text(
            """
            SELECT brief_date, full_text, generated_at
            FROM research_brief
            WHERE user_id = :uid
            ORDER BY brief_date DESC
            LIMIT 1
            """
        ),
        {"uid": user_id},
    ).fetchone()
    if not row:
        return None
    return {
        "report_type": "research_brief",
        "title": f"Research Brief — {row.brief_date}",
        "content_markdown": row.full_text or "*No content.*",
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
    }


def _latest_intelligence_report(db: Session, user_id: str) -> Optional[Dict[str, Any]]:
    row = db.execute(
        text(
            """
            SELECT title, summary, full_content, created_at
            FROM intelligence_reports
            WHERE user_id = :uid
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"uid": user_id},
    ).fetchone()
    if not row:
        return None
    return {
        "report_type": "intelligence",
        "title": row.title,
        "content_markdown": row.full_content or row.summary or "*No content.*",
        "generated_at": row.created_at.isoformat() if row.created_at else None,
    }


def _latest_health_report(db: Session, user_id: str) -> Optional[Dict[str, Any]]:
    row = db.execute(
        text(
            """
            SELECT week_start, week_end, headline, full_markdown, created_at
            FROM health_weekly_report
            WHERE user_id = :uid AND status = 'complete'
            ORDER BY week_end DESC
            LIMIT 1
            """
        ),
        {"uid": user_id},
    ).fetchone()
    if not row:
        return None
    return {
        "report_type": "health",
        "title": row.headline or f"Health Report — week of {row.week_start}",
        "content_markdown": row.full_markdown or "*No content.*",
        "generated_at": row.created_at.isoformat() if row.created_at else None,
    }


def _latest_task_result(db: Session, user_id: str) -> Optional[Dict[str, Any]]:
    row = db.execute(
        text(
            """
            SELECT original_query, result_note_id, completed_at
            FROM background_task
            WHERE user_id = :uid AND status = 'completed' AND result_note_id IS NOT NULL
            ORDER BY completed_at DESC
            LIMIT 1
            """
        ),
        {"uid": user_id},
    ).fetchone()
    if not row:
        return None
    return {
        "report_type": "task",
        "title": row.original_query,
        "note_id": row.result_note_id,
        "generated_at": row.completed_at.isoformat() if row.completed_at else None,
    }


_RESOLVERS = {
    "research_brief": _latest_research_brief,
    "intelligence": _latest_intelligence_report,
    "health": _latest_health_report,
    "task": _latest_task_result,
}


@router.get("/report/latest")
async def get_latest_report(
    type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the single most recent report, optionally scoped to `type`.

    `type` one of: research_brief, intelligence, health, task. Omit to get
    the freshest report of any type ("the report you just ran").
    """
    user_id = str(current_user.id)

    if type:
        resolver = _RESOLVERS.get(type)
        if not resolver:
            raise HTTPException(status_code=400, detail=f"Unknown report type: {type}")
        result = resolver(db, user_id)
        if not result:
            raise HTTPException(status_code=404, detail=f"No {type} report found")
        return result

    candidates = [r(db, user_id) for r in _RESOLVERS.values()]
    candidates = [c for c in candidates if c and c.get("generated_at")]
    if not candidates:
        raise HTTPException(status_code=404, detail="No reports found")
    candidates.sort(key=lambda c: c["generated_at"], reverse=True)
    return candidates[0]
