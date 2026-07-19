"""Diagnostics API — read-only vitals for the webapp System view (Phase 2).

Mirrors the chat diagnostics tools over HTTP so the webapp can render a vitals
strip: failing tasks, error counts, queue depths, drift, and version-match.
All read-only; no endpoint mutates Sara's state.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.services import diagnostics_service as diag

router = APIRouter(prefix="/api/diagnostics", tags=["Diagnostics"])


@router.get("/overview")
async def overview(current_user=Depends(get_current_user)):
    return await diag.diagnostics_overview()


@router.get("/failures")
async def failures(hours: int = 24, include_resolved: bool = False,
                   current_user=Depends(get_current_user)):
    return {"failures": await diag.get_failing_tasks(hours=hours, include_resolved=include_resolved)}


@router.get("/events")
async def events(service: Optional[str] = None, level: Optional[str] = None,
                 since_hours: int = 24, query: Optional[str] = None, limit: int = 50,
                 current_user=Depends(get_current_user)):
    return {"events": await diag.search_events(service=service, level=level,
                                               since_hours=since_hours, query=query, limit=limit)}


@router.get("/explain/{event_id}")
async def explain(event_id: str, current_user=Depends(get_current_user)):
    detail = await diag.explain_event(event_id)
    if not detail:
        raise HTTPException(status_code=404, detail="event not found")
    return detail


class ReportIn(BaseModel):
    topic: str = "system health"


@router.post("/report")
async def report(payload: ReportIn, current_user=Depends(get_current_user)):
    md = await diag.build_report(payload.topic)
    return {"topic": payload.topic, "markdown": md}
