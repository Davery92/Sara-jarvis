"""
Workspace State API Routes
Manage canvas/workspace state for cross-device sync.
"""
import logging
import json
from datetime import datetime, timezone
from typing import Optional, List, Any, Dict
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select
from redis import Redis

from app.core.deps import get_current_user
from app.core.config import settings
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
    model_config = {"extra": "allow"}

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


class PartnerWorkspaceWindow(BaseModel):
    id: Optional[str] = None
    type: str
    title: Optional[str] = None
    z_index: Optional[int] = None
    data: Optional[Dict[str, Any]] = None


class PartnerRecentAction(BaseModel):
    type: str
    target: Optional[str] = None
    query: Optional[str] = None
    window_type: Optional[str] = None
    at: Optional[str] = None


class PartnerContextUpdate(BaseModel):
    session_id: str
    active: bool
    focused_window_id: Optional[str] = None
    focused_window_type: Optional[str] = None
    active_scene_id: Optional[str] = None
    windows: List[PartnerWorkspaceWindow] = Field(default_factory=list)
    map_count: int = 0
    recent_actions: List[PartnerRecentAction] = Field(default_factory=list)
    transform: Optional[Dict[str, float]] = None
    client_timestamp: Optional[str] = None


PARTNER_CONTEXT_TTL_SECONDS = 900
PARTNER_ACTIVE_MAX_AGE_SECONDS = 60
MAX_RECENT_ACTIONS = 12
MAX_WINDOWS = 24


def _partner_context_key(user_id: str) -> str:
    return f"workspace_partner_context:{user_id}"


def _get_redis() -> Optional[Redis]:
    try:
        from app.core.redis import get_redis_sync
        return get_redis_sync()
    except Exception as e:
        logger.warning(f"Workspace partner Redis unavailable: {e}")
        return None


def _parse_iso_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _build_partner_thoughts(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    thoughts: List[Dict[str, Any]] = []
    windows = ctx.get("windows", []) or []
    focus_type = (ctx.get("focused_window_type") or "").lower()
    map_count = int(ctx.get("map_count") or 0)
    actions = ctx.get("recent_actions", []) or []
    action_queries = [a.get("query", "").strip() for a in actions if isinstance(a, dict) and a.get("query")]
    latest_query = action_queries[-1] if action_queries else ""
    window_types = {str(w.get("type", "")).lower() for w in windows if isinstance(w, dict)}

    def add(text: str, priority: int = 50, action: Optional[Dict[str, Any]] = None):
        if not text:
            return
        if any(t["text"] == text for t in thoughts):
            return
        item = {
            "id": str(uuid.uuid4()),
            "text": text,
            "priority": priority,
            "source": "workspace_context",
        }
        if action:
            item["action"] = action
        thoughts.append(item)

    if not windows:
        add("Your canvas is clear. I can set up a focused layout when you're ready.", priority=60)
    else:
        add(f"I see {len(windows)} workspace windows open. I can help reduce clutter when you want.", priority=20)

    if focus_type == "email":
        if latest_query:
            add(
                f"You're focused on email and searching for '{latest_query}'. I can open matching threads in separate windows.",
                priority=90
            )
        else:
            add("You're in email. I can filter by sender, attachments, or action-required messages.", priority=80)

    if focus_type == "documents":
        if latest_query:
            add(f"You're searching documents for '{latest_query}'. I can pull the strongest matches side-by-side.", priority=90)
        else:
            add("You're in documents. I can search across uploads and open the best matches instantly.", priority=80)

    if "email" in window_types and "documents" in window_types:
        add(
            "Email and documents are both open. I can cross-reference attachments against document matches.",
            priority=88
        )

    if "note" in window_types and "research" in window_types:
        add("Notes and research are open together. I can summarize findings straight into your notes.", priority=84)

    if map_count > 0:
        add(f"You have {map_count} map{'s' if map_count != 1 else ''} visible. I can reorganize nodes for clarity.", priority=70)

    if len(windows) >= 5:
        add(
            "You’re juggling several windows. I can tile or cascade them for a cleaner working view.",
            priority=75,
            action={"label": "Tile windows", "command": {"workspace_command": "arrange_windows", "arrangement": "tile"}}
        )

    thoughts.sort(key=lambda t: int(t.get("priority", 0)), reverse=True)
    return thoughts[:6]


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


@router.post("/partner-context")
async def update_partner_context(
    update: PartnerContextUpdate,
    current_user: User = Depends(get_current_user),
):
    """Store latest workspace context for partner-thought generation."""
    redis = _get_redis()
    if not redis:
        return {"success": False, "active": False, "error": "partner_context_unavailable"}

    user_id = str(current_user.id)
    now = datetime.now(timezone.utc)
    data = update.model_dump()
    data["user_id"] = user_id
    data["server_updated_at"] = now.isoformat()
    data["recent_actions"] = (data.get("recent_actions") or [])[-MAX_RECENT_ACTIONS:]
    data["windows"] = (data.get("windows") or [])[:MAX_WINDOWS]
    if update.active:
        data["last_active_at"] = now.isoformat()

    redis.setex(_partner_context_key(user_id), PARTNER_CONTEXT_TTL_SECONDS, json.dumps(data))
    return {"success": True, "active": bool(update.active), "updated_at": data["server_updated_at"]}


@router.get("/partner-thoughts")
async def get_partner_thoughts(
    current_user: User = Depends(get_current_user),
):
    """
    Return workspace-partner thoughts derived from current canvas context.
    Thoughts are intentionally empty whenever user activity is not currently active.
    """
    redis = _get_redis()
    if not redis:
        return {"active": False, "thoughts": [], "reason": "unavailable"}

    user_id = str(current_user.id)
    raw = redis.get(_partner_context_key(user_id))
    if not raw:
        return {"active": False, "thoughts": [], "reason": "no_context"}

    try:
        ctx = json.loads(raw)
    except Exception:
        return {"active": False, "thoughts": [], "reason": "bad_context"}

    now = datetime.now(timezone.utc)
    last_active_at = _parse_iso_utc(ctx.get("last_active_at"))
    is_fresh = bool(last_active_at and (now - last_active_at).total_seconds() <= PARTNER_ACTIVE_MAX_AGE_SECONDS)
    is_active = bool(ctx.get("active")) and is_fresh

    if not is_active:
        return {"active": False, "thoughts": [], "reason": "inactive"}

    thoughts = _build_partner_thoughts(ctx)
    return {
        "active": True,
        "session_id": ctx.get("session_id"),
        "generated_at": now.isoformat(),
        "thoughts": thoughts,
    }
