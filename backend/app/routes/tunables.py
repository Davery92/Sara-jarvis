"""
Settings → Tunables API.

Read/edit rows in `tunable_setting`. Edits invalidate the in-process cache
so subsystems pick up the new value within their normal lookup path.
"""
import logging
from datetime import datetime, timezone as dt_tz
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.tunable_setting import TunableSetting
from app.services.tunables import invalidate_cache

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Settings"])


class TunableOut(BaseModel):
    key: str
    display_name: str
    description: Optional[str] = None
    category: str
    value_type: str
    value: Any
    default_value: Any
    min_value: Any = None
    max_value: Any = None
    unit: Optional[str] = None
    editable: bool

    @classmethod
    def from_row(cls, row: TunableSetting) -> "TunableOut":
        return cls(
            key=row.key,
            display_name=row.display_name,
            description=row.description,
            category=row.category,
            value_type=row.value_type,
            value=row.value,
            default_value=row.default_value,
            min_value=row.min_value,
            max_value=row.max_value,
            unit=row.unit,
            editable=row.editable,
        )


class TunablePatch(BaseModel):
    value: Any


def _coerce_and_validate(row: TunableSetting, raw: Any) -> Any:
    """Coerce the incoming value to the row's declared type and validate bounds."""
    t = row.value_type
    try:
        if t == "int":
            v = int(raw)
        elif t == "float":
            v = float(raw)
        elif t == "bool":
            v = bool(raw)
        elif t == "string":
            v = str(raw)
        elif t == "json":
            v = raw  # accept anything JSON-encodable
        else:
            raise HTTPException(status_code=500, detail=f"unknown value_type {t!r}")
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"value cannot be coerced to {t}: {e}")

    if t in ("int", "float"):
        if row.min_value is not None and v < row.min_value:
            raise HTTPException(status_code=400, detail=f"value {v} below min {row.min_value}")
        if row.max_value is not None and v > row.max_value:
            raise HTTPException(status_code=400, detail=f"value {v} above max {row.max_value}")
    return v


@router.get("/api/settings/tunables", response_model=List[TunableOut])
def list_tunables(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.query(TunableSetting).order_by(TunableSetting.category, TunableSetting.key).all()
    return [TunableOut.from_row(r) for r in rows]


@router.patch("/api/settings/tunables/{key}", response_model=TunableOut)
def patch_tunable(
    key: str,
    patch: TunablePatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.query(TunableSetting).filter(TunableSetting.key == key).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"tunable {key!r} not found")
    if not row.editable:
        raise HTTPException(status_code=403, detail=f"tunable {key!r} is not editable")

    coerced = _coerce_and_validate(row, patch.value)
    row.value = coerced
    row.updated_at = datetime.now(dt_tz.utc)
    db.commit()
    db.refresh(row)
    invalidate_cache()
    logger.info("tunable %s updated by %s → %r", key, current_user.id, coerced)
    return TunableOut.from_row(row)


@router.post("/api/settings/tunables/{key}/reset", response_model=TunableOut)
def reset_tunable(
    key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reset to default_value."""
    row = db.query(TunableSetting).filter(TunableSetting.key == key).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"tunable {key!r} not found")
    row.value = row.default_value
    row.updated_at = datetime.now(dt_tz.utc)
    db.commit()
    db.refresh(row)
    invalidate_cache()
    logger.info("tunable %s reset to default by %s", key, current_user.id)
    return TunableOut.from_row(row)
