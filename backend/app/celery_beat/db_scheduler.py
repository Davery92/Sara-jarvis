"""
Custom Celery beat scheduler that reads its entries from the `scheduled_job`
PostgreSQL table on each tick window. Replaces the static
`celery_app.conf.beat_schedule` dict so the schedule can be edited at runtime
via the settings API/UI without restarting beat.

Design notes
------------
* Subclasses `celery.beat.Scheduler` (NOT `PersistentScheduler`) — we use the
  DB as the source of truth, so the shelve-based persistence isn't needed.
* `setup_schedule()` does the initial load from DB.
* `sync()` reloads from DB if `RELOAD_INTERVAL` seconds have passed. Celery
  calls `sync()` according to `sync_every`; we set both equal so beat polls
  the DB at most once a minute.
* `apply_entry()` is overridden to update `last_run_at` / `last_status` so
  the UI can show "ran 3 minutes ago".
* Cron expressions are stored as standard 5-field crontab strings
  ("minute hour day_of_month month day_of_week"). Per-row timezones are
  honored via `nowfun`.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict

from celery.beat import Scheduler, ScheduleEntry
from celery.schedules import crontab, schedule as interval_schedule

logger = logging.getLogger(__name__)

# How often to re-poll the DB for schedule changes (seconds)
RELOAD_INTERVAL = 60


def _parse_cron(expr: str, tz_name: str):
    """Parse a 5-field crontab string into a celery.schedules.crontab.

    Falls back to celery's app timezone if pytz is unavailable or tz_name is invalid.
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"cron_expr must have 5 fields (got {len(parts)}): {expr!r}")
    minute, hour, dom, month, dow = parts

    nowfun = None
    if tz_name:
        try:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(tz_name)
            except Exception:
                import pytz
                tz = pytz.timezone(tz_name)
            nowfun = lambda: datetime.now(tz)
        except Exception:
            logger.warning("Unknown timezone %r, falling back to app default", tz_name)

    kwargs: Dict[str, Any] = dict(
        minute=minute, hour=hour,
        day_of_month=dom, month_of_year=month, day_of_week=dow,
    )
    if nowfun is not None:
        kwargs["nowfun"] = nowfun
    return crontab(**kwargs)


class DBScheduler(Scheduler):
    """Celery beat scheduler backed by the `scheduled_job` table."""

    # Celery calls sync() at most this often. We use it as our reload trigger.
    sync_every = RELOAD_INTERVAL
    # Don't busy-wait — at most check for due tasks once a second.
    max_interval = 5

    def __init__(self, *args, **kwargs):
        self._schedule: Dict[str, ScheduleEntry] = {}
        self._last_loaded: float = 0.0
        super().__init__(*args, **kwargs)

    # ── Schedule loading ──────────────────────────────────────────
    def setup_schedule(self) -> None:
        self._reload()
        # install_default_entries adds celery.backend_cleanup
        try:
            self.install_default_entries(self._schedule)
        except Exception as e:
            logger.warning("install_default_entries failed: %s", e)

    @property
    def schedule(self) -> Dict[str, ScheduleEntry]:
        return self._schedule

    @schedule.setter
    def schedule(self, value: Dict[str, ScheduleEntry]) -> None:
        # Celery's parent __init__ may try to assign here. Allow it.
        self._schedule = value or {}

    def sync(self) -> None:
        """Called by beat at most every `sync_every` seconds. Reload from DB."""
        try:
            self._reload()
        except Exception as e:
            logger.exception("DBScheduler reload failed: %s", e)

    # ── DB I/O ────────────────────────────────────────────────────
    def _reload(self) -> None:
        # Lazy import — db.base pulls in app config which may not be ready
        # at module-import time when beat boots.
        from app.db.base import SessionLocal
        from app.models.scheduled_job import ScheduledJob

        new_entries: Dict[str, ScheduleEntry] = {}
        with SessionLocal() as db:
            rows = db.query(ScheduledJob).filter(ScheduledJob.enabled.is_(True)).all()
            for row in rows:
                try:
                    entry = self._row_to_entry(row)
                except Exception as e:
                    logger.warning("Skipping scheduled_job %r: %s", row.key, e)
                    continue

                # Preserve last_run_at across reloads. Without this, interval
                # entries get a fresh `last_run_at = now` every reload, so any
                # interval task with `interval_seconds > RELOAD_INTERVAL` is
                # starved (it never reaches its due time before being reset).
                # Source of truth for the timestamp:
                #   1. The in-memory entry from the previous reload, if any
                #      (it has the most recent dispatch time tracked by beat).
                #   2. Otherwise the persisted `last_run_at` from the DB row,
                #      so process restarts also stay sane.
                prev = self._schedule.get(row.key)
                if prev is not None and getattr(prev, "last_run_at", None):
                    entry.last_run_at = prev.last_run_at
                    entry.total_run_count = getattr(prev, "total_run_count", 0)
                elif row.last_run_at is not None:
                    entry.last_run_at = row.last_run_at

                new_entries[row.key] = entry

        # Preserve celery's default entries (e.g. backend_cleanup) if present.
        for k, v in self._schedule.items():
            if k.startswith("celery.") and k not in new_entries:
                new_entries[k] = v

        added = set(new_entries) - set(self._schedule)
        removed = set(self._schedule) - set(new_entries)
        if added or removed:
            logger.info(
                "DBScheduler reloaded: %d entries (+%d -%d)",
                len(new_entries), len(added), len(removed),
            )
        self._schedule = new_entries
        self._last_loaded = time.time()

    def _row_to_entry(self, row) -> ScheduleEntry:
        if row.schedule_kind == "cron":
            if not row.cron_expr:
                raise ValueError("cron_expr is required when schedule_kind='cron'")
            sched = _parse_cron(row.cron_expr, row.timezone or "America/New_York")
        elif row.schedule_kind == "interval":
            if not row.interval_seconds or row.interval_seconds <= 0:
                raise ValueError("interval_seconds must be > 0 when schedule_kind='interval'")
            sched = interval_schedule(run_every=float(row.interval_seconds))
        else:
            raise ValueError(f"unknown schedule_kind: {row.schedule_kind!r}")

        options: Dict[str, Any] = {}
        if row.queue:
            options["queue"] = row.queue
        if row.expires_seconds:
            options["expires"] = row.expires_seconds

        return ScheduleEntry(
            name=row.key,
            task=row.task_name,
            schedule=sched,
            args=tuple(row.args or []),
            kwargs=dict(row.kwargs or {}),
            options=options,
            app=self.app,
        )

    # ── Run tracking ──────────────────────────────────────────────
    def apply_entry(self, entry, producer=None):
        """Override to record last_run_at after successful dispatch.

        Celery's Scheduler.apply_entry signature is `(self, entry, producer=None)`.
        """
        super().apply_entry(entry, producer=producer)
        # Best-effort: write last_run_at. Don't let DB hiccups crash beat.
        try:
            self._record_run(entry.name, success=True, error=None)
        except Exception as e:
            logger.warning("Failed to record last_run_at for %r: %s", entry.name, e)

    def _record_run(self, key: str, success: bool, error: str | None) -> None:
        from app.db.base import SessionLocal
        from app.models.scheduled_job import ScheduledJob
        from datetime import datetime, timezone as dt_tz

        with SessionLocal() as db:
            row = db.query(ScheduledJob).filter(ScheduledJob.key == key).first()
            if not row:
                return
            row.last_run_at = datetime.now(dt_tz.utc)
            row.last_status = "success" if success else "error"
            row.last_error = error
            db.commit()

    # ── Lifecycle ─────────────────────────────────────────────────
    def close(self) -> None:
        # Nothing to flush — DB writes are immediate.
        pass

    @property
    def info(self) -> str:
        return f"    . db -> {len(self._schedule)} entries (reload every {RELOAD_INTERVAL}s)"
