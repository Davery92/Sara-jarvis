"""Single source of truth for "is this date a training day?"

Before this, two places answered the question differently and contradicted
each other:
  - nutrition context only checked for a logged `workout_session` row, and
  - the morning brief only checked the active phase's scheduled templates.
So right after importing a plan (templates scheduled, no sessions logged yet),
the brief said "training day" while the macro targets said "rest day".

Both signals are legitimate, so they're unified here:
  1. An explicit `workout_session` row for the date — you logged or started one,
     or the training-schedule toggle planned it. Authoritative.
  2. An active-phase `fitness_template` whose `scheduled_days` includes the
     date's weekday — the plan's intent, even before a session exists.
It's a training day if EITHER holds; otherwise a rest day.

Note: there's no explicit "this scheduled day is OFF" store, so toggling a
normally-scheduled day to rest isn't expressible yet — a known limitation, not
worse than before.
"""

import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.phase_resolution import get_effective_phase

logger = logging.getLogger(__name__)


def templates_for_day(db: Session, user_id: str, on_date: date,
                      phase: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """Every active-phase template scheduled for `on_date`, in plan order.

    Ordered by `order_in_phase`, which the two-a-day program uses to put the AM
    strength session before the PM hypertrophy one. Callers used to loop the
    templates and `break` on the first weekday match, which silently hid the
    second session of the day from the brief, the suggestions and the chat.

    Each entry: {id, name, order_in_phase, notes, exercises (parsed list)}.
    """
    phase = phase if phase is not None else get_effective_phase(db, user_id, on_date)
    if not phase:
        return []

    weekday = on_date.strftime("%A").lower()
    rows = db.execute(text("""
        SELECT id, name, scheduled_days, exercises, notes, order_in_phase
        FROM fitness_template
        WHERE user_id = :uid AND phase_id = :pid
        ORDER BY order_in_phase ASC NULLS LAST, name ASC
    """), {"uid": user_id, "pid": phase["id"]}).fetchall()

    out: List[Dict[str, Any]] = []
    for t in rows:
        if not t.scheduled_days:
            continue
        try:
            days = [str(d).lower() for d in (
                json.loads(t.scheduled_days) if isinstance(t.scheduled_days, str)
                else (t.scheduled_days or []))]
        except (ValueError, TypeError):
            continue
        if weekday not in days:
            continue
        try:
            exercises = (json.loads(t.exercises) if isinstance(t.exercises, str)
                         else (t.exercises or []))
        except (ValueError, TypeError):
            exercises = []
        out.append({
            "id": t.id,
            "name": t.name,
            "order_in_phase": t.order_in_phase,
            "notes": t.notes or "",
            "exercises": exercises,
        })
    return out


def _with_session_status(db: Session, user_id: str, on_date: date,
                          templates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach today's (ET) `session_status` to each template (A6).

    The most recent session for a template wins if it was somehow started
    twice in one day. `None` means "not started yet" — the phone and the
    Watch catalog both use this to find the next OUTSTANDING session by id
    instead of matching template names against titles.
    """
    if not templates:
        return templates
    ids = [t["id"] for t in templates]
    by_template: Dict[str, Dict[str, Any]] = {}
    try:
        rows = db.execute(text("""
            SELECT template_id, status, completed_at
            FROM active_workout_session
            WHERE user_id = :uid AND template_id = ANY(:tids)
              AND DATE(started_at AT TIME ZONE 'America/New_York') = :d
            ORDER BY started_at DESC
        """), {"uid": user_id, "tids": ids, "d": on_date}).fetchall()
        for r in rows:
            by_template.setdefault(r.template_id, {
                "session_status": r.status,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            })
    except Exception:
        # Postgres-only SQL (ANY(:tids), AT TIME ZONE) — degrade to "unknown"
        # rather than 500 a reader that only wanted the schedule, not status.
        logger.debug("training_day._with_session_status: status lookup failed", exc_info=True)
    for t in templates:
        info = by_template.get(t["id"])
        t["session_status"] = info["session_status"] if info else None
        t["completed_at"] = info["completed_at"] if info else None
    return templates


def is_training_day(db: Session, user_id: str, on_date: date) -> Dict:
    """Resolve training vs rest for `on_date`.

    Returns {is_training_day, reason, template_id, template_name, templates}.
    `reason` is one of: "session_logged", "scheduled", "rest".

    `templates` lists every session scheduled for the day (AM before PM), each
    carrying `session_status` (A6). `template_id`/`template_name` are the next
    OUTSTANDING one — the first whose `session_status` isn't 'completed' or
    'active' elsewhere yet — falling back to the first template once every
    session for the day is done, so callers with no "done for today" state of
    their own still get a real template id rather than null.
    """
    # 0. Explicit day-type override (Phase 10D set_day_type) wins over everything.
    try:
        ov = db.execute(text("""
            SELECT day_type FROM day_type_override
            WHERE user_id = :uid AND override_date = :d
        """), {"uid": user_id, "d": on_date}).fetchone()
        if ov:
            is_tr = ov.day_type == "training"
            return {"is_training_day": is_tr, "reason": "override",
                    "template_id": None, "template_name": None, "templates": []}
    except Exception:
        pass  # table may not exist yet

    # 1. Explicit session row (logged / started / toggled).
    sess = db.execute(text("""
        SELECT id FROM workout_session
        WHERE user_id = :uid AND session_date = :d
        LIMIT 1
    """), {"uid": user_id, "d": on_date}).fetchone()
    if sess:
        # Still resolve the day's templates: with two sessions a date, logging
        # the AM one must not make the PM one disappear from every reader.
        day_templates = _with_session_status(db, user_id, on_date, templates_for_day(db, user_id, on_date))
        next_up = next((t for t in day_templates if t.get("session_status") not in ("completed", "active")),
                        day_templates[0] if day_templates else None)
        return {"is_training_day": True, "reason": "session_logged",
                "template_id": next_up["id"] if next_up else None,
                "template_name": next_up["name"] if next_up else None,
                "templates": day_templates}

    # 2. Effective approved-program phase templates scheduled for this weekday.
    scheduled = _with_session_status(db, user_id, on_date, templates_for_day(db, user_id, on_date))
    if scheduled:
        # The next OUTSTANDING session — the first not yet completed or
        # currently active — falling back to the first template once the day
        # is done, so "today's template" stays a real id (A6).
        next_up = next((t for t in scheduled if t.get("session_status") not in ("completed", "active")),
                        scheduled[0])
        return {"is_training_day": True, "reason": "scheduled",
                "template_id": next_up["id"], "template_name": next_up["name"],
                "templates": [{"id": t["id"], "name": t["name"],
                               "order_in_phase": t["order_in_phase"],
                               "session_status": t.get("session_status"),
                               "completed_at": t.get("completed_at")} for t in scheduled]}

    return {"is_training_day": False, "reason": "rest",
            "template_id": None, "template_name": None, "templates": []}


def set_day_type(db: Session, user_id: str, on_date: date, day_type: str, note: str = "") -> Dict:
    """Override a day as 'rest' or 'training' (Phase 10D). Flips the nutrition
    targets (fitness_context reads calories_rest_day/carbs_rest_day when the day
    resolves to rest). Returns the stored override."""
    if day_type not in ("rest", "training"):
        return {"error": "day_type must be 'rest' or 'training'"}
    from app.core.timezone import now_utc
    db.execute(text("""
        INSERT INTO day_type_override (user_id, override_date, day_type, note, created_at)
        VALUES (:uid, :d, :t, :n, :now)
        ON CONFLICT (user_id, override_date)
        DO UPDATE SET day_type = :t, note = :n, created_at = :now
    """), {"uid": user_id, "d": on_date, "t": day_type, "n": note, "now": now_utc()})
    db.commit()
    return {"date": str(on_date), "day_type": day_type, "note": note}
