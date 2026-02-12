"""
Autonomy control routes — quiet mode, digest config, etc.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.services.context_writer import update_fields
from app.services.unified_context import read_snapshot

router = APIRouter(prefix="/autonomy", tags=["autonomy"])


class QuietModeRequest(BaseModel):
    until: Optional[str] = None  # ISO timestamp, None = indefinite


@router.post("/quiet-mode")
async def enable_quiet_mode(
    request: QuietModeRequest,
    current_user=Depends(get_current_user),
):
    """Enable quiet mode — suppresses non-safety notifications and most standing orders."""
    user_id = str(current_user.id)
    await update_fields(
        user_id,
        source="user_control",
        quiet_mode=True,
        quiet_mode_until=request.until or "",
    )
    return {
        "status": "enabled",
        "quiet_mode": True,
        "until": request.until,
    }


@router.delete("/quiet-mode")
async def disable_quiet_mode(
    current_user=Depends(get_current_user),
):
    """Disable quiet mode — resume normal autonomous behavior."""
    user_id = str(current_user.id)
    await update_fields(
        user_id,
        source="user_control",
        quiet_mode=False,
        quiet_mode_until="",
    )
    return {"status": "disabled", "quiet_mode": False}


@router.get("/quiet-mode")
async def get_quiet_mode_status(
    current_user=Depends(get_current_user),
):
    """Check current quiet mode status."""
    user_id = str(current_user.id)
    snapshot = await read_snapshot(user_id)

    # Auto-expire if until time has passed
    is_active = snapshot.quiet_mode
    if is_active and snapshot.quiet_mode_until:
        try:
            until = datetime.fromisoformat(snapshot.quiet_mode_until).replace(tzinfo=None)
            if datetime.utcnow() > until:
                is_active = False
                await update_fields(
                    user_id, source="auto_expire",
                    quiet_mode=False, quiet_mode_until="",
                )
        except (ValueError, TypeError):
            pass

    return {
        "quiet_mode": is_active,
        "until": snapshot.quiet_mode_until if is_active else None,
    }
