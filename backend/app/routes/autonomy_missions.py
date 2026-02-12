"""
Autonomy mission routes — persistent multi-step tasks.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.services.autonomy.mission_engine import mission_engine

router = APIRouter(prefix="/autonomy", tags=["autonomy"])


class MissionStepInput(BaseModel):
    action_name: str
    action_args: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


class CreateMissionRequest(BaseModel):
    title: str
    description: Optional[str] = None
    steps: List[MissionStepInput]
    priority: str = "normal"
    requires_confirmation: bool = False
    metadata: Optional[Dict[str, Any]] = None


@router.post("/missions")
async def create_mission(
    request: CreateMissionRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new mission."""
    steps = [
        {
            "action_name": s.action_name,
            "action_args": s.action_args or {},
            "description": s.description,
        }
        for s in request.steps
    ]
    mission_id = await mission_engine.create_mission(
        db=db,
        user_id=str(current_user.id),
        title=request.title,
        description=request.description,
        steps=steps,
        source="user",
        priority=request.priority,
        requires_confirmation=request.requires_confirmation,
        metadata=request.metadata,
    )
    await db.commit()
    if not mission_id:
        raise HTTPException(status_code=500, detail="Failed to create mission")
    return {"id": mission_id, "status": "created"}


@router.get("/missions")
async def list_missions(
    state: Optional[str] = None,
    limit: int = 20,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List missions."""
    missions = await mission_engine.list_missions(
        db=db, user_id=str(current_user.id), state=state, limit=limit,
    )
    return {"missions": missions, "count": len(missions)}


@router.get("/missions/{mission_id}")
async def get_mission(
    mission_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a mission with its steps."""
    mission = await mission_engine.get_mission(db=db, mission_id=mission_id)
    if not mission or mission.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


@router.post("/missions/{mission_id}/cancel")
async def cancel_mission(
    mission_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a mission."""
    success = await mission_engine.cancel_mission(db=db, mission_id=mission_id, user_id=str(current_user.id))
    await db.commit()
    return {"success": success}


@router.post("/missions/{mission_id}/confirm")
async def confirm_mission(
    mission_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm a mission that's awaiting confirmation."""
    success = await mission_engine.confirm_mission(db=db, mission_id=mission_id, user_id=str(current_user.id))
    await db.commit()
    return {"success": success}
