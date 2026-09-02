"""Register and retire ActivityKit update tokens."""

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.live_activity import LiveActivityRegistration

router = APIRouter(prefix="/api/live-activities", tags=["live-activities"])


class RegistrationIn(BaseModel):
    activity_id: str = Field(min_length=1, max_length=255)
    logical_id: str = Field(min_length=1, max_length=255)
    kind: Literal["task", "workout", "presence"]
    push_token: str = Field(min_length=16, max_length=1024)
    device_name: Optional[str] = Field(default=None, max_length=255)
    environment: Literal["production", "sandbox"] = "production"


@router.post("/register")
def register(body: RegistrationIn, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    uid = str(current_user.id)
    row = db.execute(select(LiveActivityRegistration).where(
        LiveActivityRegistration.user_id == uid,
        LiveActivityRegistration.activity_id == body.activity_id,
    )).scalar_one_or_none()
    if row is None:
        row = LiveActivityRegistration(user_id=uid, **body.model_dump())
        db.add(row)
    else:
        row.logical_id = body.logical_id
        row.kind = body.kind
        row.push_token = body.push_token
        row.device_name = body.device_name
        row.environment = body.environment
        row.is_active = True
        row.ended_at = None
        row.updated_at = datetime.now(timezone.utc)
    # A restarted activity supersedes older tokens for the same logical item.
    for old in db.execute(select(LiveActivityRegistration).where(
        LiveActivityRegistration.user_id == uid,
        LiveActivityRegistration.logical_id == body.logical_id,
        LiveActivityRegistration.activity_id != body.activity_id,
        LiveActivityRegistration.is_active.is_(True),
    )).scalars().all():
        old.is_active = False
        old.ended_at = datetime.now(timezone.utc)
    db.commit()
    return {"success": True, "registration_id": row.id}


@router.delete("/{activity_id}")
def unregister(activity_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    row = db.execute(select(LiveActivityRegistration).where(
        LiveActivityRegistration.user_id == str(current_user.id),
        LiveActivityRegistration.activity_id == activity_id,
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Live Activity registration not found")
    row.is_active = False
    row.ended_at = datetime.now(timezone.utc)
    db.commit()
    return {"success": True}
