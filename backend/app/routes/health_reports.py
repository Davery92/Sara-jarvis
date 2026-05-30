"""Routes for weekly health consolidation reports."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_current_user

router = APIRouter(prefix="/api/reports/health", tags=["health_reports"])


def _row_to_dict(row, *, include_body: bool = False) -> Dict[str, Any]:
    out = {
        "id": row.id,
        "user_id": row.user_id,
        "week_start": row.week_start.isoformat() if row.week_start else None,
        "week_end": row.week_end.isoformat() if row.week_end else None,
        "headline": row.headline,
        "status": row.status,
        "model_used": row.model_used,
        "push_sent_at": row.push_sent_at.isoformat() if row.push_sent_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if include_body:
        out["full_markdown"] = row.full_markdown
        out["recovery_json"] = row.recovery_json
        out["activity_json"] = row.activity_json
        out["stats_json"] = row.stats_json
        out["error"] = row.error
    return out


@router.get("")
async def list_reports(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
):
    rows = db.execute(
        text("""
            SELECT id, user_id, week_start, week_end, headline, status, model_used,
                   push_sent_at, created_at, full_markdown, recovery_json, activity_json,
                   stats_json, error
            FROM health_weekly_report
            WHERE user_id = :u
            ORDER BY week_start DESC
            LIMIT :lim
        """),
        {"u": current_user.id, "lim": limit},
    ).all()
    return {"reports": [_row_to_dict(r) for r in rows]}


@router.get("/{report_id}")
async def get_report(
    report_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = db.execute(
        text("""
            SELECT id, user_id, week_start, week_end, headline, status, model_used,
                   push_sent_at, created_at, full_markdown, recovery_json, activity_json,
                   stats_json, error
            FROM health_weekly_report
            WHERE id = :id AND user_id = :u
        """),
        {"id": report_id, "u": current_user.id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return _row_to_dict(row, include_body=True)
