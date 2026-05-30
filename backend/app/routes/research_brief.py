"""Research Brief API routes — read, stream, regenerate.

Mirrors the morning-brief route shape so the iOS BriefingsScreen can use the
same patterns. Registered under /api/research-brief in main_simple.py.
"""
from datetime import date, datetime, timezone
from pathlib import Path
import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


class BriefSummary(BaseModel):
    brief_date: str
    paper_count: Optional[int]
    audio_duration_seconds: Optional[float]
    has_audio: bool
    generated_at: Optional[str]


class BriefDetail(BaseModel):
    brief_date: str
    full_text: Optional[str]
    paper_count: Optional[int]
    audio_duration_seconds: Optional[float]
    has_audio: bool
    sources: Optional[list]
    generated_at: Optional[str]


@router.get("/today", response_model=BriefDetail)
async def get_today_brief(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = date.today().strftime("%Y-%m-%d")
    row = db.execute(
        text(
            """
            SELECT brief_date, full_text, paper_count, audio_duration_seconds,
                   audio_path, sources, generated_at
            FROM research_brief
            WHERE user_id = :uid AND brief_date = :d
            """
        ),
        {"uid": str(current_user.id), "d": today},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No research brief generated yet today")
    return BriefDetail(
        brief_date=row.brief_date,
        full_text=row.full_text,
        paper_count=row.paper_count,
        audio_duration_seconds=row.audio_duration_seconds,
        has_audio=bool(row.audio_path) and Path(row.audio_path).exists(),
        sources=row.sources,
        generated_at=row.generated_at.isoformat() if row.generated_at else None,
    )


@router.get("/history", response_model=List[BriefSummary])
async def get_history(
    limit: int = 14,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text(
            """
            SELECT brief_date, paper_count, audio_duration_seconds, audio_path, generated_at
            FROM research_brief
            WHERE user_id = :uid
            ORDER BY brief_date DESC
            LIMIT :lim
            """
        ),
        {"uid": str(current_user.id), "lim": max(1, min(60, limit))},
    ).fetchall()
    out: List[BriefSummary] = []
    for r in rows:
        out.append(
            BriefSummary(
                brief_date=r.brief_date,
                paper_count=r.paper_count,
                audio_duration_seconds=r.audio_duration_seconds,
                has_audio=bool(r.audio_path) and Path(r.audio_path).exists(),
                generated_at=r.generated_at.isoformat() if r.generated_at else None,
            )
        )
    return out


@router.get("/{brief_date}", response_model=BriefDetail)
async def get_brief_by_date(
    brief_date: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.execute(
        text(
            """
            SELECT brief_date, full_text, paper_count, audio_duration_seconds,
                   audio_path, sources, generated_at
            FROM research_brief
            WHERE user_id = :uid AND brief_date = :d
            """
        ),
        {"uid": str(current_user.id), "d": brief_date},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No research brief for that date")
    return BriefDetail(
        brief_date=row.brief_date,
        full_text=row.full_text,
        paper_count=row.paper_count,
        audio_duration_seconds=row.audio_duration_seconds,
        has_audio=bool(row.audio_path) and Path(row.audio_path).exists(),
        sources=row.sources,
        generated_at=row.generated_at.isoformat() if row.generated_at else None,
    )


@router.get("/{brief_date}/audio")
async def get_brief_audio(
    brief_date: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.execute(
        text(
            """
            SELECT audio_path FROM research_brief
            WHERE user_id = :uid AND brief_date = :d
            """
        ),
        {"uid": str(current_user.id), "d": brief_date},
    ).fetchone()
    if not row or not row.audio_path:
        raise HTTPException(status_code=404, detail="No audio for this brief")
    p = Path(row.audio_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Audio file missing")
    return FileResponse(p, media_type="audio/mpeg", filename=f"research_brief_{brief_date}.mp3")


@router.post("/generate")
async def trigger_generate(
    current_user: User = Depends(get_current_user),
):
    """Enqueue a fresh generation. Returns immediately; brief lands when the task finishes (~3 min)."""
    from app.celery_app import celery_app

    r = celery_app.send_task(
        "app.tasks.research_brief.generate_research_brief",
        queue="cognitive",
    )
    return {"task_id": r.id, "status": "queued"}
