"""Moment cards API (SARA_ALIVE §5.8/§5.9, 2026-07-31)."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/moment-cards", tags=["Moment Cards"])


class MomentCardOut(BaseModel):
    id: str
    kind: str
    title: str
    body: str
    source_ref: Optional[str] = None
    source_kind: Optional[str] = None
    created_at: datetime


@router.get("", response_model=List[MomentCardOut])
def list_moment_cards(
    include_seen: bool = False,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Active cards, newest first. Default: unseen and not dismissed only —
    this is meant to surface as a small, rare stack, not an archive."""
    where = "user_id = :uid AND dismissed_at IS NULL"
    if not include_seen:
        where += " AND seen_at IS NULL"
    rows = db.execute(text(f"""
        SELECT id::text AS id, kind, title, body, source_ref, source_kind, created_at
        FROM moment_card
        WHERE {where}
        ORDER BY created_at DESC
        LIMIT :limit
    """), {"uid": str(current_user.id), "limit": limit}).mappings().fetchall()
    return [dict(r) for r in rows]


@router.post("/{card_id}/seen", response_model=MomentCardOut)
def mark_seen(
    card_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The "unwrap" interaction — viewing the card is what marks it seen."""
    db.execute(text("""
        UPDATE moment_card SET seen_at = NOW()
        WHERE id = :id AND user_id = :uid AND seen_at IS NULL
    """), {"id": card_id, "uid": str(current_user.id)})
    db.commit()
    row = db.execute(text("""
        SELECT id::text AS id, kind, title, body, source_ref, source_kind, created_at
        FROM moment_card WHERE id = :id AND user_id = :uid
    """), {"id": card_id, "uid": str(current_user.id)}).mappings().first()
    return dict(row)


@router.post("/{card_id}/dismiss")
def dismiss(
    card_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db.execute(text("""
        UPDATE moment_card SET dismissed_at = NOW(), seen_at = COALESCE(seen_at, NOW())
        WHERE id = :id AND user_id = :uid
    """), {"id": card_id, "uid": str(current_user.id)})
    db.commit()
    return {"success": True}
