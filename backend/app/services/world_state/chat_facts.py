"""The compact, always-current "world state core" for chat (living-world-
context plan §7, "preserve a compact current-state core").

Reads the CONTINUOUSLY MAINTAINED projections (WorldThread, via the
writer/coordinator/reducer pipeline) rather than reconstructing state from
source records on demand — a workout started or finished while every
client was closed still updates WorldThread the moment its event is
processed, so the next chat turn reads the already-current answer instead
of re-deriving it from `active_workout_session`/`workout_log`.

Deliberately compact and domain-scoped rather than a dump: this is the
small, non-negotiable anchor fed into `allocate_live_context_sections` as
`world_state_core`, sized to survive allocation even under pressure — see
`context_budget.LIVE_CONTEXT_SECTION_ALLOTMENTS`. The prose World Brief
remains the place for a fuller, browsable account.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.timezone import render_relative, render_when
from app.models.world_model import WorldFact, WorldThread

_ACTIVE_THREAD_STATUSES = ("proposed", "open", "waiting", "blocked")

# Plan §4: health measurements have no freshness-aging behavior of their
# own (point-in-time facts, not a "current state" that goes stale) — a
# sync from hours ago is still exactly as true as it was. This bounds how
# long the compact core keeps mentioning it as recent chatter rather than
# something for the fuller World Brief/page to carry instead.
_HEALTH_SYNC_RECENT_WINDOW = timedelta(hours=6)

# How long a resolved/cancelled workout thread still counts as "recent
# enough to mention" once nothing is active. Past this, it's history for
# the World Brief / World Context page, not part of the compact core.
_RECENT_TERMINAL_WINDOW = timedelta(hours=12)

# Plan §4 freshness contract, location row: "mark location last-known after
# 15 minutes without a new observation, subject to the actual feed cadence
# and accuracy. Never infer 'home' from silence."
_LOCATION_LAST_KNOWN_AFTER = timedelta(minutes=15)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _workout_line(db: Session, user_id: str) -> Optional[str]:
    open_thread = db.execute(
        select(WorldThread)
        .where(
            WorldThread.user_id == str(user_id),
            WorldThread.thread_key.like("workout:%"),
            WorldThread.status == "open",
        )
        .order_by(WorldThread.updated_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if open_thread is not None:
        started = render_relative(open_thread.created_at)
        return f"Workout in progress: {open_thread.title} (started {started})."

    terminal = db.execute(
        select(WorldThread)
        .where(
            WorldThread.user_id == str(user_id),
            WorldThread.thread_key.like("workout:%"),
            WorldThread.status.in_(("resolved", "cancelled")),
        )
        .order_by(WorldThread.resolved_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if terminal is None or terminal.resolved_at is None:
        return None
    if _now() - terminal.resolved_at > _RECENT_TERMINAL_WINDOW:
        return None
    verb = "completed" if terminal.status == "resolved" else "abandoned"
    when = render_relative(terminal.resolved_at)
    return f"Last workout: {terminal.title} — {verb} {when}."


def _location_line(db: Session, user_id: str) -> Optional[str]:
    """The most recent location transition, across every known place —
    reducer.py keys each place's fact separately (`location:{place_id}
    :latest`), so "current location" is whichever of those is newest, not
    a single fixed key. Never infers "home" from the absence of a more
    recent event: an exit with nothing after it says "left, unknown since",
    not "still home"."""
    latest = db.execute(
        select(WorldFact)
        .where(
            WorldFact.user_id == str(user_id),
            WorldFact.fact_key.like("location:%:latest"),
            WorldFact.status == "active",
        )
        .order_by(WorldFact.observed_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is None:
        return None
    value = latest.value or {}
    label = value.get("label") or "an unknown place"
    when = render_relative(latest.observed_at)
    age = _now() - latest.observed_at

    if value.get("kind") == "location.exited":
        return f"David left {label} {when}; current location not observed since."

    # "location.entered" (or an older/unrecognized kind — treat as arrival,
    # the conservative reading rather than silently dropping the line).
    if age <= _LOCATION_LAST_KNOWN_AFTER:
        return f"David is at {label} (arrived {when})."
    return f"David was last known at {label}, as of {when} — may have moved since."


def _calendar_line(db: Session, user_id: str) -> Optional[str]:
    """A calendar item currently underway — reducer.py's calendar branch
    stores a single evolving fact per event (`calendar:{id}:schedule`) with
    a `status` field that moves scheduled -> started -> ended/cancelled as
    calendar.* events land, so "in a meeting right now" is just: the most
    recently observed calendar fact whose status is still 'started'."""
    candidates = db.execute(
        select(WorldFact)
        .where(
            WorldFact.user_id == str(user_id),
            WorldFact.fact_key.like("calendar:%:schedule"),
            WorldFact.status == "active",
        )
        .order_by(WorldFact.observed_at.desc())
        .limit(10)
    ).scalars().all()
    for fact in candidates:
        value = fact.value or {}
        if value.get("status") != "started":
            continue
        title = value.get("title") or "an event"
        since = render_relative(fact.observed_at)
        return f"Currently in progress: {title} (started {since})."
    return None


def _commitment_line(db: Session, user_id: str) -> Optional[str]:
    """The soonest-due open commitment across reminders/goals/tasks —
    reducer.py's `elif spec.domain in {"tasks","reminders","goals"}` branch
    keys each one's thread as `{domain}:{id}` with a real due_at (only ever
    set from a trusted producer or an explicit user-stated datetime — see
    `_deterministic_due_at`, never a model's guess)."""
    thread = db.execute(
        select(WorldThread)
        .where(
            WorldThread.user_id == str(user_id),
            WorldThread.status.in_(_ACTIVE_THREAD_STATUSES),
            WorldThread.due_at.is_not(None),
            or_(
                WorldThread.thread_key.like("reminders:%"),
                WorldThread.thread_key.like("goals:%"),
                WorldThread.thread_key.like("tasks:%"),
            ),
        )
        .order_by(WorldThread.due_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    if thread is None:
        return None
    when = render_when(thread.due_at)
    return f"Next due: {thread.title} — {when}."


def _email_line(db: Session, user_id: str) -> Optional[str]:
    """How many email threads are still waiting on David — reducer.py's
    email branch only opens a follow_up thread when the analyzer actually
    flagged action_required, so this is never every unread message, only
    ones something specific asked of him."""
    open_threads = db.execute(
        select(WorldThread)
        .where(
            WorldThread.user_id == str(user_id),
            WorldThread.status.in_(_ACTIVE_THREAD_STATUSES),
            WorldThread.kind == "follow_up",
            or_(
                WorldThread.thread_key.like("email:%"),
                WorldThread.thread_key.like("email-action:%"),
            ),
        )
    ).scalars().all()
    if not open_threads:
        return None
    if len(open_threads) == 1:
        return f"1 email needs a reply: {open_threads[0].title}."
    newest = max(open_threads, key=lambda t: t.updated_at)
    return f"{len(open_threads)} emails need a reply, most recent: {newest.title}."


def _health_line(db: Session, user_id: str) -> Optional[str]:
    """The most recent health sync, if recent enough to still be 'news'
    rather than settled history — see health.sync_completed's producer in
    routes/health_metrics.py for what's actually in this fact's value."""
    fact = db.execute(
        select(WorldFact)
        .where(
            WorldFact.user_id == str(user_id),
            WorldFact.fact_key.like("health:%:state"),
            WorldFact.status == "active",
        )
        .order_by(WorldFact.observed_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if fact is None or _now() - fact.observed_at > _HEALTH_SYNC_RECENT_WINDOW:
        return None
    value = fact.value or {}
    metric_type = value.get("latest_metric_type")
    metric_value = value.get("latest_value")
    when = render_relative(fact.observed_at)
    if metric_type is not None and metric_value is not None:
        return f"Health data synced {when}: latest {metric_type} {metric_value}."
    return f"Health data synced {when}."


def render_world_state_core(
    db: Session, user_id: str, conversation_mode: Optional[str] = None,
) -> str:
    """Compact current-state lines, one per wired domain. Empty string when
    there's nothing to say — an empty "world state" section is worse than
    none (same principle as dialogue_state.render_dialogue_state_block).

    Extend by adding another `_<domain>_line(db, user_id)` helper and
    appending its result below; each domain reads its own maintained
    projection the same way `_workout_line` does.

    `conversation_mode` (personal-conversation remediation plan, step 2):
    when it's one of `context_router.AMBIENT_SUPPRESS_MODES` ("social",
    "personal_vulnerable"), the commitment/email/health lines are dropped —
    exactly the "propose email, SSL, and ACORD work" and unsolicited HRV
    failures the plan's evidence table names. workout/location/calendar
    stay: they read as situational awareness, not a task or health readout,
    and a greeting is allowed "at most one relevant personal callback."
    `None` (the default) preserves the prior unconditional behavior for any
    caller that hasn't been updated to pass a mode yet.
    """
    lines: List[str] = []
    try:
        workout = _workout_line(db, user_id)
    except Exception:
        workout = None
    if workout:
        lines.append(workout)

    try:
        location = _location_line(db, user_id)
    except Exception:
        location = None
    if location:
        lines.append(location)

    try:
        calendar = _calendar_line(db, user_id)
    except Exception:
        calendar = None
    if calendar:
        lines.append(calendar)

    from app.services.context_router import AMBIENT_SUPPRESS_MODES
    _suppress_ambient = conversation_mode in AMBIENT_SUPPRESS_MODES

    if not _suppress_ambient:
        try:
            commitment = _commitment_line(db, user_id)
        except Exception:
            commitment = None
        if commitment:
            lines.append(commitment)

        try:
            email = _email_line(db, user_id)
        except Exception:
            email = None
        if email:
            lines.append(email)

        try:
            health = _health_line(db, user_id)
        except Exception:
            health = None
        if health:
            lines.append(health)

    if not lines:
        return ""
    return "## What's true right now\n" + "\n".join(lines)
