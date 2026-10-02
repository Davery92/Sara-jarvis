"""Per-athlete coaching cadence, and the occurrence ledger that dedupes it.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 24.

Four things this is built around, each with a concrete failure behind it:

1. **Opt-in, per kind.** Every preference starts disabled and unconsented,
   and "remind me to weigh in" is a different toggle from "write me a weekly
   review". One switch would make a nudge and a minute of GPU time the same
   decision.

2. **An anchor, not a cron, for multi-day cadences.** A cron's `*/14` in the
   day-of-month field means the 1st, 15th and 29th — so January gives 14
   days, 14 days, then 3. An anchor date plus a day count is the only
   arithmetic that means "every two weeks".

3. **The occurrence ledger absorbs a double dispatch.** `DBScheduler` seeds
   UTC `last_run_at`, which makes a daily ET cron fire twice (see
   `tests/test_db_scheduler_beat_double_fire.py`), and it marks
   `last_status='success'` at DISPATCH time so a green row proves nothing
   about the work. The unique index on `(user_id, kind, occurrence_at)` is
   what makes "retry/restart never produces two reviews per occurrence"
   true rather than hoped for.

4. **A claim that fails to enqueue is reclaimable.** The claim row is
   written first and carries `claimed_at`; if the enqueue then fails, the
   row stays non-terminal and the next sweep picks it up after a timeout.
   Enqueueing first and claiming after would lose the occurrence whenever
   the process died in between.

The athlete never supplies a task name, a queue or kwargs. Their settings
control one row describing their own cadence; the sweep is a single global
`scheduled_job`. A per-athlete scheduled job would put `task_name` behind a
user-facing API, which is arbitrary code execution with extra steps.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.fitness.data_access import (
    FitnessDataError, _require_user, athlete_zone,
)

logger = logging.getLogger(__name__)

#: Cadence kinds. A closed set: the column has a CHECK, and a value outside
#: it is a rejected write rather than a silently inert preference.
CADENCE_KINDS = (
    "daily_checkin", "weekly_review", "biweekly_review", "monthly_review",
    "tape_measurement", "progress_photo",
)

#: Which kinds are driven by an anchor plus a day count rather than weekdays.
ANCHORED_KINDS = frozenset({
    "biweekly_review", "monthly_review", "tape_measurement", "progress_photo",
})

#: Default day counts, used when an athlete enables an anchored kind without
#: naming one.
DEFAULT_CADENCE_DAYS = {
    "biweekly_review": 14,
    "monthly_review": 28,
    "tape_measurement": 14,
    "progress_photo": 28,
}

#: The Celery task each kind enqueues. A MAPPING in code, never a column:
#: a task name in a user-writable row is arbitrary code execution.
KIND_TASKS = {
    "daily_checkin": "app.tasks.fitness_coach.run_daily_checkin",
    "weekly_review": "app.tasks.fitness_coach.run_scheduled_review",
    "biweekly_review": "app.tasks.fitness_coach.run_scheduled_review",
    "monthly_review": "app.tasks.fitness_coach.run_scheduled_review",
    "tape_measurement": "app.tasks.fitness_coach.run_measurement_nudge",
    "progress_photo": "app.tasks.fitness_coach.run_photo_nudge",
}

#: Every coaching task runs on the health lane, which is where the other
#: health rollups live. Also a mapping in code, for the same reason.
KIND_QUEUE = "health"

#: How many occurrences one sweep may claim. Bounded so a backlog after an
#: outage does not enqueue a thousand model calls in one tick.
SWEEP_BATCH_SIZE = 25

#: How long a non-terminal claim may sit before the next sweep reclaims it.
#: Longer than a review takes, so a slow generation is not reclaimed out from
#: under itself.
CLAIM_EXPIRY = timedelta(minutes=30)

#: How late an occurrence may be claimed. Past this it is expired rather than
#: run: a check-in nudge for last Tuesday is not a nudge, it is confusing.
OCCURRENCE_GRACE = timedelta(hours=12)


class CadenceConflict(Exception):
    """A stale `expected_version` on a preference edit."""

    def __init__(self, message: str, current_version: int):
        super().__init__(message)
        self.current_version = current_version


@dataclass
class CoachingSchedule:
    id: str
    user_id: str
    kind: str
    enabled: bool
    consented: bool
    consented_at: Optional[datetime]
    local_time: time
    timezone: str
    weekdays: List[int]
    cadence_days: Optional[int]
    anchor_date: Optional[date]
    next_due_at: Optional[datetime]
    last_evaluated_at: Optional[datetime]
    last_completed_at: Optional[datetime]
    snoozed_until: Optional[datetime]
    version: int

    @property
    def active(self) -> bool:
        """Both switches. `enabled` is "is this on"; `consented` is "may we
        contact you about it" — a cadence that computes and stores without
        delivering is a legitimate state."""
        return self.enabled and self.consented


@dataclass
class ClaimedOccurrence:
    run_id: str
    user_id: str
    kind: str
    occurrence_at: datetime
    schedule_id: str
    schedule_version: int
    task_name: str
    reclaimed: bool = False


# ─────────────────────────────────────────────────────────────────────────
# Preferences
# ─────────────────────────────────────────────────────────────────────────

def list_schedules(db: Session, user_id: str) -> List[CoachingSchedule]:
    """Every cadence for this athlete, including the ones never enabled.

    The disabled ones are returned so a settings screen can show what is
    available rather than only what is on — a toggle nobody can see is a
    feature nobody has.
    """
    uid = _require_user(user_id)
    rows = db.execute(text("""
        SELECT * FROM fitness_coaching_schedule
        WHERE user_id = :uid ORDER BY kind
    """), {"uid": uid}).fetchall()
    existing = {r.kind: _schedule(r) for r in rows}
    return [
        existing.get(kind) or _unset_schedule(uid, kind)
        for kind in CADENCE_KINDS
    ]


def _unset_schedule(user_id: str, kind: str) -> CoachingSchedule:
    """A cadence with no row yet. Not created on read: a read that wrote
    would mean opening a settings screen enrolled the athlete in six
    cadences."""
    return CoachingSchedule(
        id="", user_id=user_id, kind=kind, enabled=False, consented=False,
        consented_at=None, local_time=time(7, 0),
        timezone="America/New_York", weekdays=[],
        cadence_days=DEFAULT_CADENCE_DAYS.get(kind),
        anchor_date=None, next_due_at=None, last_evaluated_at=None,
        last_completed_at=None, snoozed_until=None, version=0,
    )


def get_schedule(
    db: Session, user_id: str, kind: str,
) -> Optional[CoachingSchedule]:
    uid = _require_user(user_id)
    _check_kind(kind)
    row = db.execute(text("""
        SELECT * FROM fitness_coaching_schedule
        WHERE user_id = :uid AND kind = :kind
    """), {"uid": uid, "kind": kind}).fetchone()
    return _schedule(row) if row else None


def set_schedule(
    db: Session,
    user_id: str,
    kind: str,
    *,
    enabled: Optional[bool] = None,
    consented: Optional[bool] = None,
    local_time: Optional[time] = None,
    timezone_name: Optional[str] = None,
    weekdays: Optional[Sequence[int]] = None,
    cadence_days: Optional[int] = None,
    anchor_date: Optional[date] = None,
    expected_version: Optional[int] = None,
) -> CoachingSchedule:
    """Create or update one cadence preference.

    Only the athlete's OWN cadence. There is no parameter here for a task
    name, a queue or an owner — the sweep's task is a mapping in code, and
    the owner is the authenticated requester.

    `version` is bumped on every edit, and a queued job compares it before
    acting: an occurrence claimed at 06:58 must not run at 07:00 if the
    athlete switched the cadence off at 06:59.
    """
    uid = _require_user(user_id)
    _check_kind(kind)

    current = db.execute(text("""
        SELECT * FROM fitness_coaching_schedule
        WHERE user_id = :uid AND kind = :kind
        FOR UPDATE
    """), {"uid": uid, "kind": kind}).fetchone()

    if current is not None and expected_version is not None and \
            int(expected_version) != int(current.version):
        raise CadenceConflict(
            "someone else changed this cadence while you were editing it",
            int(current.version),
        )

    merged = _schedule(current) if current else _unset_schedule(uid, kind)
    if enabled is not None:
        merged.enabled = bool(enabled)
    if local_time is not None:
        merged.local_time = local_time
    if timezone_name is not None:
        # Validated STRICTLY on the write path. `athlete_zone` falls back to
        # ET with a warning, which is right for a read — an existing bad row
        # must not break the state — and wrong here: accepting an unknown
        # zone stores something that silently becomes ET forever, and the
        # athlete sees their 07:00 fire at the wrong time with no
        # explanation.
        try:
            ZoneInfo(timezone_name)
        except Exception:
            raise FitnessDataError(
                f"{timezone_name!r} is not a known timezone"
            )
        merged.timezone = timezone_name
    if weekdays is not None:
        cleaned = sorted({int(d) for d in weekdays})
        if any(d < 1 or d > 7 for d in cleaned):
            raise FitnessDataError("weekdays are ISO numbers 1 (Mon) to 7 (Sun)")
        merged.weekdays = cleaned
    if cadence_days is not None:
        if not 1 <= int(cadence_days) <= 365:
            raise FitnessDataError("cadence_days must be between 1 and 365")
        merged.cadence_days = int(cadence_days)
    if anchor_date is not None:
        merged.anchor_date = anchor_date

    if consented is not None:
        if bool(consented) and not merged.consented:
            merged.consented_at = datetime.now(timezone.utc)
        if not bool(consented):
            # Withdrawing consent keeps the timestamp of the previous grant
            # cleared, so a later row cannot look retroactively consented.
            merged.consented_at = None
        merged.consented = bool(consented)

    if kind in ANCHORED_KINDS and merged.enabled:
        if merged.cadence_days is None:
            merged.cadence_days = DEFAULT_CADENCE_DAYS.get(kind, 14)
        if merged.anchor_date is None:
            # Anchored on the day they turned it on. Any other default
            # ("the 1st") makes the first interval a partial one.
            merged.anchor_date = _local_today(merged.timezone)

    merged.next_due_at = compute_next_due(merged)

    if current is None:
        merged.id = str(uuid.uuid4())
        merged.version = 1
        db.execute(text("""
            INSERT INTO fitness_coaching_schedule (
                id, user_id, kind, enabled, consented, consented_at,
                local_time, timezone, weekdays, cadence_days, anchor_date,
                next_due_at, version
            ) VALUES (
                :id, :uid, :kind, :enabled, :consented, :consented_at,
                :local_time, :tz, CAST(:weekdays AS jsonb), :cadence_days,
                :anchor, :next_due, 1
            )
        """), _params(merged))
    else:
        merged.id = current.id
        merged.version = int(current.version) + 1
        db.execute(text("""
            UPDATE fitness_coaching_schedule
            SET enabled = :enabled, consented = :consented,
                consented_at = :consented_at, local_time = :local_time,
                timezone = :tz, weekdays = CAST(:weekdays AS jsonb),
                cadence_days = :cadence_days, anchor_date = :anchor,
                next_due_at = :next_due, version = version + 1,
                updated_at = NOW()
            WHERE id = :id AND user_id = :uid
        """), _params(merged))
    return merged


def snooze(
    db: Session, user_id: str, kind: str, until: datetime,
) -> CoachingSchedule:
    """Push a cadence out without switching it off.

    A distinct operation because "not this week" and "stop asking" are
    different statements, and collapsing them means an athlete who wanted a
    week's quiet has to re-enable from scratch.
    """
    uid = _require_user(user_id)
    _check_kind(kind)
    if until.tzinfo is None:
        raise FitnessDataError("snooze needs a timezone-aware instant")
    row = db.execute(text("""
        UPDATE fitness_coaching_schedule
        SET snoozed_until = :until, version = version + 1, updated_at = NOW()
        WHERE user_id = :uid AND kind = :kind
        RETURNING *
    """), {"uid": uid, "kind": kind, "until": until}).fetchone()
    if row is None:
        raise LookupError("no such cadence for this athlete")
    return _schedule(row)


def _check_kind(kind: str) -> None:
    if kind not in CADENCE_KINDS:
        raise FitnessDataError(
            f"{kind!r} is not a coaching cadence "
            f"({', '.join(CADENCE_KINDS)})"
        )


def _params(schedule: CoachingSchedule) -> Dict[str, Any]:
    import json
    return {
        "id": schedule.id,
        "uid": schedule.user_id, "kind": schedule.kind,
        "enabled": schedule.enabled, "consented": schedule.consented,
        "consented_at": schedule.consented_at,
        "local_time": schedule.local_time, "tz": schedule.timezone,
        "weekdays": json.dumps(schedule.weekdays),
        "cadence_days": schedule.cadence_days,
        "anchor": schedule.anchor_date,
        "next_due": schedule.next_due_at,
    }


# ─────────────────────────────────────────────────────────────────────────
# Due-time arithmetic
# ─────────────────────────────────────────────────────────────────────────

def _local_today(timezone_name: str) -> date:
    return datetime.now(athlete_zone(timezone_name)).date()


def _local_instant(
    day: date, local_time: time, timezone_name: str,
) -> datetime:
    """A wall-clock time on a local date, as an instant.

    DST is handled by `fold`, deliberately:

    * **A skipped hour** (spring forward, 02:30 on the switch day does not
      exist): `ZoneInfo` resolves it to the equivalent instant rather than
      raising, so a cadence set for 02:30 still fires that day. Skipping the
      day entirely would silently drop one occurrence a year.
    * **A repeated hour** (autumn back, 01:30 happens twice): `fold=0`
      selects the FIRST occurrence. Picking the second would fire an hour
      later than every other day of the year, and firing on both is what the
      occurrence ledger prevents — both resolve through the same
      `occurrence_at`, so the second is a duplicate claim.
    """
    zone = athlete_zone(timezone_name)
    naive = datetime.combine(day, local_time)
    return naive.replace(tzinfo=zone, fold=0)


def compute_next_due(
    schedule: CoachingSchedule, *, after: Optional[datetime] = None,
) -> Optional[datetime]:
    """When this cadence is next due, or None when it is off.

    `after` defaults to now. Returning None for a disabled cadence is what
    keeps the sweep's partial index small: a disabled row has no due time to
    index.
    """
    if not schedule.active:
        return None
    moment = after or datetime.now(timezone.utc)
    zone = athlete_zone(schedule.timezone)
    local_now = moment.astimezone(zone)

    if schedule.kind in ANCHORED_KINDS:
        return _next_anchored(schedule, local_now)
    if schedule.kind == "daily_checkin":
        return _next_daily(schedule, local_now)
    return _next_weekly(schedule, local_now)


def _next_daily(schedule: CoachingSchedule, local_now: datetime):
    today = local_now.date()
    candidate = _local_instant(today, schedule.local_time, schedule.timezone)
    if candidate <= local_now:
        candidate = _local_instant(
            today + timedelta(days=1), schedule.local_time, schedule.timezone,
        )
    return candidate


def _next_weekly(schedule: CoachingSchedule, local_now: datetime):
    """The next configured weekday at the configured local time.

    Defaults to Monday when no weekday was chosen — the week has to end
    somewhere, and a review of "last week" on a Monday is a review of a
    finished week.
    """
    weekdays = schedule.weekdays or [1]
    for offset in range(0, 8):
        day = local_now.date() + timedelta(days=offset)
        if day.isoweekday() not in weekdays:
            continue
        candidate = _local_instant(
            day, schedule.local_time, schedule.timezone,
        )
        if candidate > local_now:
            return candidate
    return None


def _next_anchored(schedule: CoachingSchedule, local_now: datetime):
    """Anchor plus N days, repeatedly, until past now.

    NOT a cron. `*/14` on a day-of-month field means the 1st, 15th and 29th,
    so January would give a 14-day gap, a 14-day gap, then a 3-day gap — and
    "every two weeks" would quietly mean something else every month.
    """
    days = schedule.cadence_days or DEFAULT_CADENCE_DAYS.get(schedule.kind, 14)
    anchor = schedule.anchor_date or local_now.date()
    if days <= 0:
        return None

    elapsed = (local_now.date() - anchor).days
    if elapsed < 0:
        periods = 0
    else:
        periods = elapsed // days
    for step in (periods, periods + 1, periods + 2):
        day = anchor + timedelta(days=days * step)
        candidate = _local_instant(day, schedule.local_time, schedule.timezone)
        if candidate > local_now:
            return candidate
    return None


# ─────────────────────────────────────────────────────────────────────────
# The sweep
# ─────────────────────────────────────────────────────────────────────────

def due_schedules(
    db: Session, *, now: Optional[datetime] = None, limit: int = SWEEP_BATCH_SIZE,
) -> List[CoachingSchedule]:
    """Enabled, consented, un-snoozed cadences whose due time has passed.

    Across ALL athletes — this is the global sweep, and it is the only place
    in the subsystem that reads without an owner, because its job is to find
    out whose turn it is. Everything it then does is per-owner and explicit.
    """
    moment = now or datetime.now(timezone.utc)
    rows = db.execute(text("""
        SELECT * FROM fitness_coaching_schedule
        WHERE enabled AND consented
          AND next_due_at IS NOT NULL
          AND next_due_at <= :now
          AND (snoozed_until IS NULL OR snoozed_until <= :now)
        ORDER BY next_due_at ASC
        LIMIT :lim
    """), {"now": moment, "lim": max(1, min(limit, 200))}).fetchall()
    return [_schedule(r) for r in rows]


def claim_occurrence(
    db: Session,
    schedule: CoachingSchedule,
    *,
    now: Optional[datetime] = None,
) -> Optional[ClaimedOccurrence]:
    """Claim this athlete's due occurrence, or None if somebody already has.

    Claim BEFORE enqueue, deliberately. If the enqueue then fails the row
    stays non-terminal with a `claimed_at`, and the next sweep reclaims it
    after `CLAIM_EXPIRY`. Enqueueing first and claiming after would lose the
    occurrence entirely whenever the process died in between — and nothing
    would ever notice, because there would be no row.

    `occurrence_at` is the DUE time truncated to the minute, not now. Two
    sweeps three seconds apart therefore compute the same value and collide
    on the unique index, which is what absorbs `DBScheduler`'s known
    double-fire into one artifact.
    """
    moment = now or datetime.now(timezone.utc)
    due = schedule.next_due_at
    if due is None:
        return None
    occurrence_at = due.astimezone(timezone.utc).replace(second=0, microsecond=0)

    if moment - due > OCCURRENCE_GRACE:
        # Too late to be useful. Recorded as a noop so the gap is visible,
        # and the schedule is rolled forward so it does not retry forever.
        _record_expired(db, schedule, occurrence_at)
        _advance(db, schedule, now=moment)
        return None

    task_name = KIND_TASKS.get(schedule.kind)
    if task_name is None:  # pragma: no cover - CHECK constraint covers this
        raise FitnessDataError(f"no task is mapped for {schedule.kind!r}")

    run_id = str(uuid.uuid4())
    inserted = db.execute(text("""
        INSERT INTO fitness_coaching_job_run (
            id, user_id, schedule_id, kind, occurrence_at, status,
            schedule_version, claimed_at, attempts
        ) VALUES (
            :id, :uid, :sid, :kind, :occ, 'claimed', :ver, :now, 1
        )
        ON CONFLICT (user_id, kind, occurrence_at) DO NOTHING
        RETURNING id
    """), {
        "id": run_id, "uid": schedule.user_id, "sid": schedule.id,
        "kind": schedule.kind, "occ": occurrence_at,
        "ver": schedule.version, "now": moment,
    }).fetchone()

    if inserted is None:
        # Somebody has this occurrence. Reclaim it only if their claim has
        # gone stale, which is the enqueue-failed-and-died case.
        reclaimed = db.execute(text("""
            UPDATE fitness_coaching_job_run
            SET status = 'claimed', claimed_at = :now,
                attempts = attempts + 1, updated_at = NOW()
            WHERE user_id = :uid AND kind = :kind AND occurrence_at = :occ
              AND status IN ('claimed', 'enqueued')
              AND claimed_at <= :stale
            RETURNING id, attempts
        """), {
            "uid": schedule.user_id, "kind": schedule.kind,
            "occ": occurrence_at, "now": moment,
            "stale": moment - CLAIM_EXPIRY,
        }).fetchone()
        if reclaimed is None:
            # A live claim, or an already-finished occurrence. Roll the
            # schedule forward anyway: leaving `next_due_at` in the past
            # makes every subsequent sweep re-examine it.
            _advance(db, schedule, now=moment)
            return None
        return ClaimedOccurrence(
            run_id=reclaimed.id, user_id=schedule.user_id, kind=schedule.kind,
            occurrence_at=occurrence_at, schedule_id=schedule.id,
            schedule_version=schedule.version, task_name=task_name,
            reclaimed=True,
        )

    _advance(db, schedule, now=moment)
    return ClaimedOccurrence(
        run_id=run_id, user_id=schedule.user_id, kind=schedule.kind,
        occurrence_at=occurrence_at, schedule_id=schedule.id,
        schedule_version=schedule.version, task_name=task_name,
    )


def _advance(db: Session, schedule: CoachingSchedule, *, now: datetime) -> None:
    """Roll `next_due_at` past `now`, and record that we looked.

    `last_evaluated_at` is separate from `last_completed_at` on purpose:
    `DBScheduler` marks a job successful at dispatch, and this subsystem
    refuses to make the same mistake twice. Looking at a cadence and
    completing its work are different events.
    """
    following = compute_next_due(schedule, after=now)
    db.execute(text("""
        UPDATE fitness_coaching_schedule
        SET next_due_at = :next, last_evaluated_at = :now, updated_at = NOW()
        WHERE id = :id
    """), {"next": following, "now": now, "id": schedule.id})
    schedule.next_due_at = following
    schedule.last_evaluated_at = now


def _record_expired(
    db: Session, schedule: CoachingSchedule, occurrence_at: datetime,
) -> None:
    db.execute(text("""
        INSERT INTO fitness_coaching_job_run (
            id, user_id, schedule_id, kind, occurrence_at, status,
            schedule_version, noop_reason, completed_at
        ) VALUES (
            :id, :uid, :sid, :kind, :occ, 'noop', :ver,
            'occurrence_expired', NOW()
        )
        ON CONFLICT (user_id, kind, occurrence_at) DO NOTHING
    """), {
        "id": str(uuid.uuid4()), "uid": schedule.user_id, "sid": schedule.id,
        "kind": schedule.kind, "occ": occurrence_at, "ver": schedule.version,
    })


# ─────────────────────────────────────────────────────────────────────────
# The ledger
# ─────────────────────────────────────────────────────────────────────────

def mark_enqueued(
    db: Session, run_id: str, *, celery_task_id: Optional[str] = None,
) -> None:
    db.execute(text("""
        UPDATE fitness_coaching_job_run
        SET status = 'enqueued', enqueued_at = NOW(),
            celery_task_id = :task, updated_at = NOW()
        WHERE id = :id AND status = 'claimed'
    """), {"id": run_id, "task": celery_task_id})


def begin_run(db: Session, user_id: str, run_id: str) -> Optional[Dict[str, Any]]:
    """Claim a queued occurrence for execution, re-checking the preference.

    Returns None when the occurrence must not run — already terminal, or the
    preference changed since the claim. That second case is the one that
    matters: an occurrence claimed at 06:58 must not run at 07:00 if the
    athlete switched the cadence off at 06:59, and the stored
    `schedule_version` is what detects it.
    """
    uid = _require_user(user_id)
    row = db.execute(text("""
        SELECT r.*, s.enabled, s.consented, s.version AS current_version,
               s.snoozed_until
        FROM fitness_coaching_job_run r
        LEFT JOIN fitness_coaching_schedule s ON s.id = r.schedule_id
        WHERE r.id = :id AND r.user_id = :uid
        FOR UPDATE OF r
    """), {"id": run_id, "uid": uid}).fetchone()
    if row is None:
        raise LookupError("no such coaching run")
    if row.status in ("completed", "failed", "noop"):
        return None

    now = datetime.now(timezone.utc)
    if row.enabled is False or row.consented is False:
        _noop(db, run_id, "cadence_disabled_since_claim")
        return None
    if row.snoozed_until is not None and row.snoozed_until > now:
        _noop(db, run_id, "snoozed_since_claim")
        return None
    if row.current_version is not None and row.schedule_version is not None \
            and int(row.current_version) != int(row.schedule_version):
        # The preference changed. The safe reading is that the athlete's
        # current wishes differ from the ones this occurrence was claimed
        # under, and acting on the stale ones is the nag this avoids.
        _noop(db, run_id, "preference_changed_since_claim")
        return None

    db.execute(text("""
        UPDATE fitness_coaching_job_run
        SET status = 'running', started_at = NOW(), updated_at = NOW()
        WHERE id = :id
    """), {"id": run_id})
    return {
        "run_id": row.id, "kind": row.kind,
        "occurrence_at": row.occurrence_at,
        "schedule_id": row.schedule_id,
    }


def complete_run(
    db: Session,
    user_id: str,
    run_id: str,
    *,
    review_id: Optional[str] = None,
    candidate_id: Optional[str] = None,
) -> None:
    """The work happened. Separate from dispatch, which is the whole point.

    Also stamps the schedule's `last_completed_at`, which is the only field
    that means "this cadence actually produced something".
    """
    uid = _require_user(user_id)
    db.execute(text("""
        UPDATE fitness_coaching_job_run
        SET status = 'completed', completed_at = NOW(),
            review_id = :review, candidate_id = :candidate, updated_at = NOW()
        WHERE id = :id AND user_id = :uid
          AND status NOT IN ('completed', 'failed', 'noop')
    """), {
        "id": run_id, "uid": uid, "review": review_id, "candidate": candidate_id,
    })
    db.execute(text("""
        UPDATE fitness_coaching_schedule
        SET last_completed_at = NOW(), updated_at = NOW()
        WHERE id = (
            SELECT schedule_id FROM fitness_coaching_job_run WHERE id = :id
        )
    """), {"id": run_id})


def fail_run(
    db: Session,
    user_id: str,
    run_id: str,
    *,
    category: str,
    detail: Optional[str] = None,
) -> None:
    uid = _require_user(user_id)
    db.execute(text("""
        UPDATE fitness_coaching_job_run
        SET status = 'failed', completed_at = NOW(),
            error_category = :cat, error_detail = :detail, updated_at = NOW()
        WHERE id = :id AND user_id = :uid
          AND status NOT IN ('completed', 'failed', 'noop')
    """), {
        "id": run_id, "uid": uid, "cat": category[:40],
        "detail": (detail or "")[:500] or None,
    })


def noop_run(db: Session, user_id: str, run_id: str, reason: str) -> None:
    """Nothing was delivered, and WHY is recorded.

    §25.3: a suppression is a recorded result, never a silent bypass. A
    missing row and a suppressed one would otherwise be indistinguishable,
    and "why didn't Sara say anything" would have no answer.
    """
    _require_user(user_id)
    _noop(db, run_id, reason)


def _noop(db: Session, run_id: str, reason: str) -> None:
    db.execute(text("""
        UPDATE fitness_coaching_job_run
        SET status = 'noop', noop_reason = :reason, completed_at = NOW(),
            updated_at = NOW()
        WHERE id = :id AND status NOT IN ('completed', 'failed', 'noop')
    """), {"id": run_id, "reason": reason[:60]})


def recent_runs(
    db: Session, user_id: str, *, kind: Optional[str] = None, limit: int = 20,
) -> List[Dict[str, Any]]:
    uid = _require_user(user_id)
    clauses = ["user_id = :uid"]
    params: Dict[str, Any] = {"uid": uid, "lim": max(1, min(limit, 100))}
    if kind:
        _check_kind(kind)
        clauses.append("kind = :kind")
        params["kind"] = kind
    rows = db.execute(text(f"""
        SELECT id, kind, occurrence_at, status, attempts, review_id,
               candidate_id, error_category, noop_reason, completed_at
        FROM fitness_coaching_job_run
        WHERE {' AND '.join(clauses)}
        ORDER BY occurrence_at DESC
        LIMIT :lim
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


# ─────────────────────────────────────────────────────────────────────────
# Row adapter
# ─────────────────────────────────────────────────────────────────────────

def _schedule(row: Any) -> CoachingSchedule:
    m = dict(row._mapping)
    weekdays = m.get("weekdays")
    if isinstance(weekdays, str):
        import json
        try:
            weekdays = json.loads(weekdays)
        except Exception:
            weekdays = []
    return CoachingSchedule(
        id=m["id"], user_id=m["user_id"], kind=m["kind"],
        enabled=bool(m["enabled"]), consented=bool(m["consented"]),
        consented_at=m.get("consented_at"),
        local_time=m["local_time"], timezone=m["timezone"],
        weekdays=list(weekdays or []),
        cadence_days=m.get("cadence_days"), anchor_date=m.get("anchor_date"),
        next_due_at=m.get("next_due_at"),
        last_evaluated_at=m.get("last_evaluated_at"),
        last_completed_at=m.get("last_completed_at"),
        snoozed_until=m.get("snoozed_until"),
        version=int(m.get("version") or 1),
    )
