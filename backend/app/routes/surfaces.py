"""
Surfaces API — read surfaces and receive interaction events.

The web `custom` view renders a surface from its spec+state and POSTs events
here as the user interacts. Silent events just patch state; components flagged
notify:true also drop a compact line into Sara's working memory (S2).
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.surface import Surface
from app.main_simple import get_db, get_current_user

router = APIRouter(tags=["surfaces"])
logger = logging.getLogger(__name__)


class SurfaceEvent(BaseModel):
    component_id: str
    event: str  # check | step | submit | click | set
    value: Optional[Dict[str, Any]] = None


def _expired(surface: Surface) -> bool:
    """Lazy expiry — a surface past expires_at is treated as inactive on read,
    so stale surfaces retire without needing a Celery beat."""
    if surface.expires_at is None:
        return False
    exp = surface.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < datetime.now(timezone.utc)


def _find_component(spec: Dict[str, Any], component_id: str) -> Optional[Dict[str, Any]]:
    for comp in (spec or {}).get("components", []):
        if comp.get("id") == component_id:
            return comp
    return None


def _apply_event(state: Dict[str, Any], comp: Dict[str, Any], event: SurfaceEvent) -> None:
    """Patch mutable state for one interaction. State is keyed by component id."""
    cid = event.component_id
    value = event.value or {}
    node = state.setdefault(cid, {})

    if event.event == "check":
        node.setdefault("checked", {})[str(value.get("item_id"))] = bool(value.get("checked"))
    elif event.event == "step":
        node.setdefault("done", {})[str(value.get("step_id"))] = bool(value.get("done"))
    elif event.event == "submit":
        node["values"] = value.get("values", value)
        node["submitted_at"] = datetime.now(timezone.utc).isoformat()
    elif event.event == "click":
        node["clicked"] = value.get("button_id")
        node["clicked_at"] = datetime.now(timezone.utc).isoformat()
    elif event.event == "set":
        node.update(value)
    else:
        # Unknown event kinds are stored raw so nothing is silently dropped.
        node.setdefault("events", []).append({"event": event.event, "value": value})


def _component_notifies(comp: Dict[str, Any], event: SurfaceEvent) -> bool:
    # Buttons carry notify per-button (no component-level flag); only the
    # clicked button's flag counts. Check this before the component-level flag.
    if comp.get("type") == "buttons":
        if event.event != "click":
            return False
        btn_id = (event.value or {}).get("button_id")
        for b in comp.get("buttons", []):
            if b.get("id") == btn_id:
                return bool(b.get("notify"))
        return False
    return bool(comp.get("notify"))


@router.get("")
async def list_surfaces(
    status: Optional[str] = Query(default="active"),
    conversation_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(Surface).filter(Surface.user_id == current_user.id)
    if status:
        q = q.filter(Surface.status == status)
    if conversation_id:
        q = q.filter(Surface.conversation_id == conversation_id)
    surfaces = q.order_by(Surface.updated_at.desc()).limit(limit).all()
    # Lazy-expire on read so a reloaded chat doesn't resurrect stale surfaces.
    fresh = []
    for s in surfaces:
        if s.status == "active" and _expired(s):
            s.status = "expired"
            continue
        fresh.append(s)
    db.commit()
    return [s.to_dict() for s in fresh]


@router.get("/{surface_id}")
async def get_surface(
    surface_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    surface = db.query(Surface).filter(
        Surface.id == surface_id, Surface.user_id == current_user.id
    ).first()
    if not surface:
        raise HTTPException(status_code=404, detail="Surface not found")
    if surface.status == "active" and _expired(surface):
        surface.status = "expired"
        db.commit()
    return surface.to_dict()


@router.post("/{surface_id}/events")
async def post_surface_event(
    surface_id: str,
    event: SurfaceEvent,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    surface = db.query(Surface).filter(
        Surface.id == surface_id, Surface.user_id == current_user.id
    ).first()
    if not surface:
        raise HTTPException(status_code=404, detail="Surface not found")
    if surface.status != "active" or _expired(surface):
        if surface.status == "active":
            surface.status = "expired"
            db.commit()
        raise HTTPException(status_code=409, detail="Surface is no longer active")

    comp = _find_component(surface.spec, event.component_id)
    if not comp:
        raise HTTPException(status_code=400, detail=f"Unknown component '{event.component_id}'")

    state = dict(surface.state or {})
    _apply_event(state, comp, event)
    surface.state = state
    flag_modified(surface, "state")
    db.commit()

    notified = False
    if _component_notifies(comp, event):
        try:
            from app.services.surface_notify import notify_surface_event
            await notify_surface_event(current_user.id, surface, comp, event.model_dump())
            notified = True
        except Exception as e:
            logger.warning(f"surface notify failed: {e}")

    return {"status": "ok", "notified": notified, "state": surface.state}
