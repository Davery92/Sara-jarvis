"""The Mind — API surface for the workspace (§3.1) and self-model (§3.4).

Powers the webapp's Attention pane workspace strip (§7.1) and the Self page
(§7.4 — "David should never need to re-run this audit by hand"). Read-only.
"""
import logging

from fastapi import APIRouter, Depends

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
