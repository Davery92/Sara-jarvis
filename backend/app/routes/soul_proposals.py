"""Soul-change proposal API — Brain Alignment H7.2.

One-tap approve/reject for Sara's proposed identity changes. Identity-level
changes stay consented — David is the only one who moves a proposal to
`approved` (except style-only ones, which auto-approve after 14 days via the
nightly persona job).
"""
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.soul import SoulChangeProposal

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/soul/proposals")
async def list_soul_proposals(
    status: str = "pending",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List soul-change proposals (pending by default) for the inbox card."""
    q = db.query(SoulChangeProposal)
    if status and status != "all":
        q = q.filter(SoulChangeProposal.status == status)
    rows = q.order_by(SoulChangeProposal.proposed_at.desc()).limit(50).all()
    return {
        "proposals": [
            {
                "id": p.id,
                "section": p.section,
                "proposed_content": p.proposed_content,
                "current_content": p.current_content,
                "rationale": p.rationale,
                "kind": p.kind,
                "evidence_count": p.evidence_count,
                "status": p.status,
                "proposed_at": p.proposed_at.isoformat() if p.proposed_at else None,
            }
            for p in rows
        ]
    }


@router.post("/soul/proposals/{proposal_id}/approve")
async def approve_soul_proposal(
    proposal_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.persona_evolution import approve_proposal
    result = approve_proposal(db, proposal_id, resolved_by="david")
    return result


@router.post("/soul/proposals/{proposal_id}/reject")
async def reject_soul_proposal(
    proposal_id: int,
    reason: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.persona_evolution import reject_proposal
    return reject_proposal(db, proposal_id, reason=reason)
