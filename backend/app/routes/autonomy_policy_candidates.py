"""
Autonomy policy candidate routes — reviewable suggestions from dreams/reflections.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.services.autonomy.policy_candidate import policy_candidate_service

router = APIRouter(prefix="/autonomy", tags=["autonomy"])


@router.get("/policy-candidates")
async def list_policy_candidates(
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List policy candidates."""
    candidates = await policy_candidate_service.list_candidates(
        db=db, user_id=str(current_user.id), status=status, limit=limit,
    )
    return {"candidates": candidates, "count": len(candidates)}


@router.post("/policy-candidates/{candidate_id}/accept")
async def accept_policy_candidate(
    candidate_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept a policy candidate, creating the corresponding standing order or automation."""
    result = await policy_candidate_service.accept_candidate(
        db=db, candidate_id=candidate_id, user_id=str(current_user.id),
    )
    await db.commit()
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to accept"))
    return result


@router.post("/policy-candidates/{candidate_id}/reject")
async def reject_policy_candidate(
    candidate_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reject a policy candidate."""
    success = await policy_candidate_service.reject_candidate(
        db=db, candidate_id=candidate_id, user_id=str(current_user.id),
    )
    await db.commit()
    return {"success": success}
