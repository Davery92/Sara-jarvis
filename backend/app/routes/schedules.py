"""
Settings → Schedules API.

Read/edit/enable/disable the rows in `scheduled_job` that drive the DB-backed
Celery beat scheduler. Edits take effect on the next beat reload (~60s).
"""
import logging
from datetime import datetime, timezone as dt_tz
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.scheduled_job import ScheduledJob

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Settings"])


# ── Schemas ──────────────────────────────────────────────────────────
class ScheduleOut(BaseModel):
    key: str
    display_name: str
    description: Optional[str] = None
    category: str
    task_name: str
    schedule_kind: str
    cron_expr: Optional[str] = None
    interval_seconds: Optional[int] = None
    timezone: str
    args: List[Any]
    kwargs: Dict[str, Any]
    queue: Optional[str] = None
    expires_seconds: Optional[int] = None
    enabled: bool
    editable: bool
    source: str
    visibility: str
    last_run_at: Optional[datetime] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    last_run_duration_ms: Optional[int] = None
    human_readable: str  # "Daily at 6:00 AM" / "Every 5 minutes"

    @classmethod
    def from_row(cls, row: ScheduledJob) -> "ScheduleOut":
        return cls(
            key=row.key,
            display_name=row.display_name,
            description=row.description,
            category=row.category,
            task_name=row.task_name,
            schedule_kind=row.schedule_kind,
            cron_expr=row.cron_expr,
            interval_seconds=row.interval_seconds,
            timezone=row.timezone,
            args=list(row.args or []),
            kwargs=dict(row.kwargs or {}),
            queue=row.queue,
            expires_seconds=row.expires_seconds,
            enabled=row.enabled,
            editable=row.editable,
            source=row.source,
            visibility=row.visibility,
            last_run_at=row.last_run_at,
            last_status=row.last_status,
            last_error=row.last_error,
            last_run_duration_ms=row.last_run_duration_ms,
            human_readable=_humanize(row),
        )


class SchedulePatch(BaseModel):
    schedule_kind: Optional[str] = Field(None, pattern="^(cron|interval)$")
    cron_expr: Optional[str] = None
    interval_seconds: Optional[int] = Field(None, gt=0)
    timezone: Optional[str] = None
    enabled: Optional[bool] = None
    kwargs: Optional[Dict[str, Any]] = None

    @field_validator("cron_expr")
    @classmethod
    def _validate_cron(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        parts = v.strip().split()
        if len(parts) != 5:
            raise ValueError("cron_expr must have 5 fields: 'minute hour day_of_month month day_of_week'")
        # Try to parse via celery.crontab to surface a useful error.
        from celery.schedules import crontab
        try:
            crontab(minute=parts[0], hour=parts[1], day_of_month=parts[2],
                    month_of_year=parts[3], day_of_week=parts[4])
        except Exception as e:
            raise ValueError(f"invalid cron expression: {e}")
        return v.strip()


# ── Helpers ──────────────────────────────────────────────────────────
def _humanize(row: ScheduledJob) -> str:
    if row.schedule_kind == "interval":
        s = row.interval_seconds or 0
        if s < 60:
            return f"Every {s} seconds"
        if s < 3600:
            mins = s // 60
            return f"Every {mins} minute{'s' if mins != 1 else ''}"
        if s < 86400:
            hrs = s / 3600
            return f"Every {hrs:g} hour{'s' if hrs != 1 else ''}"
        days = s / 86400
        return f"Every {days:g} day{'s' if days != 1 else ''}"
    if row.schedule_kind == "cron" and row.cron_expr:
        parts = row.cron_expr.split()
        if len(parts) == 5:
            m, h, dom, mon, dow = parts
            tz = row.timezone or "America/New_York"
            try:
                if m.isdigit() and h.isdigit() and dom == "*" and mon == "*":
                    hh, mm = int(h), int(m)
                    suffix = "AM" if hh < 12 else "PM"
                    h12 = hh % 12 or 12
                    when = f"{h12}:{mm:02d} {suffix}"
                    if dow == "*":
                        return f"Daily at {when} {tz}"
                    return f"{dow} at {when} {tz}"
            except Exception:
                pass
        return f"cron({row.cron_expr}) {row.timezone}"
    return "—"


# ── Routes ───────────────────────────────────────────────────────────
@router.get("/api/settings/schedules", response_model=List[ScheduleOut])
def list_schedules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List every scheduled job, ordered by category then key."""
    rows = db.query(ScheduledJob).order_by(ScheduledJob.category, ScheduledJob.key).all()
    return [ScheduleOut.from_row(r) for r in rows]


@router.get("/api/settings/schedules/{key}", response_model=ScheduleOut)
def get_schedule(
    key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.query(ScheduledJob).filter(ScheduledJob.key == key).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"scheduled job {key!r} not found")
    return ScheduleOut.from_row(row)


@router.patch("/api/settings/schedules/{key}", response_model=ScheduleOut)
def patch_schedule(
    key: str,
    patch: SchedulePatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.query(ScheduledJob).filter(ScheduledJob.key == key).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"scheduled job {key!r} not found")
    if not row.editable:
        raise HTTPException(status_code=403, detail=f"scheduled job {key!r} is not editable")

    data = patch.model_dump(exclude_unset=True)

    # If schedule_kind is changing, the new payload must include the matching field.
    new_kind = data.get("schedule_kind", row.schedule_kind)
    if new_kind == "cron":
        new_cron = data.get("cron_expr", row.cron_expr)
        if not new_cron:
            raise HTTPException(status_code=400, detail="cron_expr is required when schedule_kind='cron'")
        if "schedule_kind" in data:
            row.interval_seconds = None
    elif new_kind == "interval":
        new_interval = data.get("interval_seconds", row.interval_seconds)
        if not new_interval or new_interval <= 0:
            raise HTTPException(status_code=400, detail="interval_seconds must be > 0 when schedule_kind='interval'")
        if "schedule_kind" in data:
            row.cron_expr = None

    for field in ("schedule_kind", "cron_expr", "interval_seconds", "timezone", "enabled", "kwargs"):
        if field in data:
            setattr(row, field, data[field])

    row.updated_at = datetime.now(dt_tz.utc)
    db.commit()
    db.refresh(row)
    logger.info("schedule %s updated by %s: %s", key, current_user.id, data)
    return ScheduleOut.from_row(row)


@router.post("/api/settings/schedules/{key}/run-now")
def run_schedule_now(
    key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dispatch the underlying Celery task immediately, bypassing the schedule."""
    row = db.query(ScheduledJob).filter(ScheduledJob.key == key).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"scheduled job {key!r} not found")

    from app.celery_app import celery_app
    options: Dict[str, Any] = {}
    if row.queue:
        options["queue"] = row.queue
    if row.expires_seconds:
        options["expires"] = row.expires_seconds

    try:
        result = celery_app.send_task(
            row.task_name,
            args=list(row.args or []),
            kwargs=dict(row.kwargs or {}),
            **options,
        )
    except Exception as e:
        logger.exception("run-now dispatch failed for %s", key)
        raise HTTPException(status_code=500, detail=f"dispatch failed: {e}")

    logger.info("schedule %s run-now dispatched by %s (task_id=%s)", key, current_user.id, result.id)
    return {"ok": True, "task_id": result.id, "task_name": row.task_name}
