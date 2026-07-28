"""Interest Model API (SARA_MIND_V2 §3.2 D4: "API + web settings page
first"). Backend half of that — GET the current document for a settings
page to render/edit, PUT a full replace (versioned, never silently
overwritten). The web page itself is a follow-up (out of scope here).
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.db.session import get_async_session_factory
from app.services import interest_model as im

logger = logging.getLogger(__name__)
router = APIRouter()


class InterestModelOut(BaseModel):
    content: Dict[str, Any]
    version: int
    rendered: str


class InterestModelUpdate(BaseModel):
    content: Dict[str, Any]
    change_note: Optional[str] = None


@router.get("/interest-model", response_model=InterestModelOut)
async def read_interest_model(current_user=Depends(get_current_user)):
    factory = get_async_session_factory()
    async with factory() as db:
        state = await im.get_interest_model(db, str(current_user.id))
        rendered = im.render_interest_model(state["content"], state["version"])
        return InterestModelOut(content=state["content"], version=state["version"], rendered=rendered)


@router.put("/interest-model", response_model=InterestModelOut)
async def update_interest_model(
    body: InterestModelUpdate,
    current_user=Depends(get_current_user),
):
    factory = get_async_session_factory()
    async with factory() as db:
        try:
            new_version = await im.set_interest_model(
                db, str(current_user.id), body.content,
                changed_by="david_settings", change_note=body.change_note,
            )
        except Exception as e:
            logger.error(f"[interest_model API] update failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to save interest model")
        rendered = im.render_interest_model(body.content, new_version)
        return InterestModelOut(content=body.content, version=new_version, rendered=rendered)


@router.get("/interest-model/versions")
async def list_interest_model_versions(limit: int = 20, current_user=Depends(get_current_user)):
    from sqlalchemy import text
    factory = get_async_session_factory()
    async with factory() as db:
        rows = (await db.execute(text("""
            SELECT version, changed_by, change_note, created_at
            FROM interest_model_version
            WHERE user_id = :uid
            ORDER BY version DESC LIMIT :limit
        """), {"uid": str(current_user.id), "limit": limit})).fetchall()
        return [
            {
                "version": r.version, "changed_by": r.changed_by,
                "change_note": r.change_note,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
