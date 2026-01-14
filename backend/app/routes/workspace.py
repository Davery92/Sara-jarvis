"""
Workspace State API Routes
Manage canvas/workspace state for cross-device sync.
"""
import logging
from typing import Optional, List, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.workspace_state import WorkspaceState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


class WindowPosition(BaseModel):
    x: float
    y: float


class WindowSize(BaseModel):
    width: float
    height: float


class CanvasTransform(BaseModel):
    x: float = 0
    y: float = 0
    scale: float = 1


class WindowState(BaseModel):
    id: str
    type: str
    title: str
    position: WindowPosition
    size: WindowSize
    zIndex: int = 0
    data: Optional[dict] = None


class WorkspaceStateData(BaseModel):
    transform: CanvasTransform
    windows: List[WindowState]


class WorkspaceStateUpdate(BaseModel):
    """Update workspace state"""
    state_data: WorkspaceStateData


class WorkspaceStateResponse(BaseModel):
    id: str
    user_id: str
    state_data: Optional[dict]
    created_at: Optional[str]
    updated_at: Optional[str]


def get_or_create_workspace_state(db: Session, user_id: str) -> WorkspaceState:
    """Get user workspace state, creating default if not exists."""
    stmt = select(WorkspaceState).where(WorkspaceState.user_id == user_id)
    state = db.execute(stmt).scalar_one_or_none()

    if not state:
        import uuid
        state = WorkspaceState(
            id=str(uuid.uuid4()),
            user_id=user_id,
            state_data={
                "transform": {"x": 0, "y": 0, "scale": 1},
                "windows": []
            }
        )
        db.add(state)
        db.commit()
        db.refresh(state)

    return state


@router.get("/state")
async def get_workspace_state(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's workspace state."""
    user_id = current_user.id
    state = get_or_create_workspace_state(db, user_id)
    return state.to_dict()


@router.put("/state")
async def save_workspace_state(
    update: WorkspaceStateUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Save user's workspace state."""
    user_id = current_user.id
    state = get_or_create_workspace_state(db, user_id)

    # Update state data
    state.state_data = update.state_data.model_dump()

    db.commit()
    db.refresh(state)

    logger.info(f"Workspace state saved for user {user_id}: {len(update.state_data.windows)} windows")
    return state.to_dict()


@router.delete("/state")
async def clear_workspace_state(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Clear user's workspace state (reset to default)."""
    user_id = current_user.id
    stmt = select(WorkspaceState).where(WorkspaceState.user_id == user_id)
    state = db.execute(stmt).scalar_one_or_none()

    if state:
        state.state_data = {
            "transform": {"x": 0, "y": 0, "scale": 1},
            "windows": []
        }
        db.commit()
        db.refresh(state)

    logger.info(f"Workspace state cleared for user {user_id}")
    return {"message": "Workspace state cleared", "state_data": state.state_data if state else {}}
