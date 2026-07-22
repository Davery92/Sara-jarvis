"""The Mind — API surface for the workspace (§3.1) and self-model (§3.4).

Powers the webapp's Attention pane workspace strip (§7.1) and the Self page
(§7.4 — "David should never need to re-run this audit by hand"). Read-only.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Body
from pydantic import BaseModel

from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mind", tags=["Mind"])


@router.get("/workspace")
async def get_workspace(current_user=Depends(get_current_user)):
    """What Sara is holding in mind right now — the 7-slot global workspace."""
    from app.db.session import get_async_session_factory
    from app.services.global_workspace import build_workspace
    sf = get_async_session_factory()
    async with sf() as db:
        return await build_workspace(db, str(current_user.id))


@router.get("/anything-i-should-know")
async def anything_i_should_know_route(current_user=Depends(get_current_user)):
    """One-paragraph synthesis of the workspace (the §3.1 scenario)."""
    from app.db.session import get_async_session_factory
    from app.services.global_workspace import anything_i_should_know
    sf = get_async_session_factory()
    async with sf() as db:
        return {"summary": await anything_i_should_know(db, str(current_user.id))}


@router.get("/self")
async def get_self_model(current_user=Depends(get_current_user)):
    """Sara's honest model of herself — health, calibration, capabilities, deploy."""
    from app.db.session import get_async_session_factory
    from app.services.self_model import build_self_model
    sf = get_async_session_factory()
    async with sf() as db:
        return await build_self_model(db, str(current_user.id))


@router.get("/beliefs")
async def get_beliefs(current_user=Depends(get_current_user)):
    """The belief ladder (§7.2): behavioral patterns by promotion status, with
    confidence, evidence, and where each sits on observed→…→automated."""
    from app.db.session import get_async_session_factory
    from sqlalchemy import text
    sf = get_async_session_factory()
    async with sf() as db:
        rows = (await db.execute(text("""
            SELECT id::text, description, confidence, evidence_count, category,
                   ladder_status, times_suggested, times_accepted, times_rejected
            FROM behavioral_pattern
            WHERE user_id = :u AND status = 'active'
            ORDER BY
              CASE ladder_status WHEN 'automated' THEN 0 WHEN 'actionable' THEN 1
                   WHEN 'predictive' THEN 2 WHEN 'believed' THEN 3 ELSE 4 END,
              confidence DESC
            LIMIT 100
        """), {"u": str(current_user.id)})).fetchall()
        beliefs = [{
            "id": r.id, "statement": r.description, "confidence": r.confidence,
            "evidence_count": r.evidence_count, "category": r.category,
            "ladder_status": r.ladder_status, "times_suggested": r.times_suggested,
            "times_accepted": r.times_accepted, "times_rejected": r.times_rejected,
        } for r in rows]
        # Contradiction count (consolidation finds these; surfaced here for §7.2).
        contra = 0
        try:
            contra = (await db.execute(text(
                "SELECT COUNT(*) FROM pkg_contradiction WHERE resolved = FALSE"
            ))).scalar() or 0
        except Exception:
            pass
        by_status: dict = {}
        for b in beliefs:
            by_status[b["ladder_status"]] = by_status.get(b["ladder_status"], 0) + 1
        return {"beliefs": beliefs, "by_status": by_status, "open_contradictions": contra}


@router.get("/why")
async def get_why_traces(limit: int = 15, current_user=Depends(get_current_user)):
    """Why-trace (§3.10): the causal chain behind recent interruption decisions —
    'why did you ping me / why did you hold that?'."""
    from app.db.session import get_async_session_factory
    from app.services.delivery_policy import recent_why_traces
    sf = get_async_session_factory()
    async with sf() as db:
        return {"traces": await recent_why_traces(db, str(current_user.id), limit)}


@router.get("/held")
async def get_held(current_user=Depends(get_current_user)):
    """What the delivery policy held while David slept (§3.6 transparency).

    Seeing the restraint — what she chose NOT to buzz him about overnight —
    is what builds trust in the sleep-gating."""
    from app.db.session import get_async_session_factory
    from sqlalchemy import text
    sf = get_async_session_factory()
    async with sf() as db:
        rows = (await db.execute(text("""
            SELECT id, title, message, category, held_reason, held_at, status, deliver_after
            FROM held_notification
            WHERE user_id = :u
              AND held_at >= NOW() - INTERVAL '48 hours'
            ORDER BY held_at DESC LIMIT 50
        """), {"u": str(current_user.id)})).fetchall()
        return {"held": [
            {"id": r.id, "title": r.title, "message": r.message, "category": r.category,
             "reason": r.held_reason, "held_at": r.held_at.isoformat() if r.held_at else None,
             "status": r.status,
             "deliver_after": r.deliver_after.isoformat() if r.deliver_after else None}
            for r in rows
        ]}


@router.get("/trust")
async def get_trust_matrix(current_user=Depends(get_current_user)):
    """The graduated-autonomy trust matrix (§3.7 / §7.3)."""
    from app.db.session import get_async_session_factory
    from app.services.trust_matrix import get_matrix
    sf = get_async_session_factory()
    async with sf() as db:
        return {"classes": await get_matrix(db)}


class TrustGrantRequest(BaseModel):
    action_class: str
    level: int  # 0-3


@router.post("/trust/grant")
async def grant_trust(req: TrustGrantRequest, current_user=Depends(get_current_user)):
    """David sets the granted trust ceiling for an action class."""
    from app.db.session import get_async_session_factory
    from app.services.trust_matrix import set_granted_level
    sf = get_async_session_factory()
    async with sf() as db:
        return await set_granted_level(db, req.action_class, req.level)
