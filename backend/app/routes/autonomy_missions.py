"""
Autonomy mission routes — persistent multi-step tasks.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

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
    db: Session = Depends(get_db),
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
    db.commit()
    if not mission_id:
        raise HTTPException(status_code=500, detail="Failed to create mission")
    return {"id": mission_id, "status": "created"}


@router.get("/missions")
async def list_missions(
    state: Optional[str] = None,
    limit: int = 20,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
):
    """Cancel a mission."""
    success = await mission_engine.cancel_mission(db=db, mission_id=mission_id, user_id=str(current_user.id))
    db.commit()
    return {"success": success}


@router.post("/missions/{mission_id}/retry")
async def retry_mission(
    mission_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retry a failed agent_dispatch mission by creating a new task+mission."""
    from app.services.agent_dispatch import agent_dispatch_service

    result = await agent_dispatch_service.retry_mission(
        db=db,
        mission_id=mission_id,
        user_id=str(current_user.id),
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/missions/{mission_id}/confirm")
async def confirm_mission(
    mission_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Confirm a mission that's awaiting confirmation."""
    success = await mission_engine.confirm_mission(db=db, mission_id=mission_id, user_id=str(current_user.id))
    db.commit()
    return {"success": success}


class MissionActionRequest(BaseModel):
    action: str  # "clarify"
    message: Optional[str] = None


@router.post("/missions/{mission_id}/action")
async def mission_action(
    mission_id: str,
    request: MissionActionRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Perform an action on a mission (e.g. provide clarification)."""
    user_id = str(current_user.id)

    # Get mission and verify ownership
    mission = await mission_engine.get_mission(db=db, mission_id=mission_id)
    if not mission or mission.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Mission not found")

    if request.action == "clarify":
        if not request.message:
            raise HTTPException(status_code=400, detail="Message required for clarification")

        # Find the linked background task and provide clarification
        task_id = (mission.get("mission_metadata") or {}).get("task_id")
        if not task_id:
            raise HTTPException(status_code=400, detail="No linked task found for this mission")

        from app.services.agent_dispatch import agent_dispatch_service
        result = await agent_dispatch_service.resume_task(
            db=db,
            task_id=task_id,
            user_id=user_id,
            instruction=request.message,
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        db.commit()
        return {"success": True, "task_status": result.get("status", "running")}

    raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}")
