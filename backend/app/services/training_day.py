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
from typing import Dict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.phase_resolution import get_effective_phase

logger = logging.getLogger(__name__)


def is_training_day(db: Session, user_id: str, on_date: date) -> Dict:
    """Resolve training vs rest for `on_date`.

    Returns {is_training_day: bool, reason: str, template_id, template_name}.
    `reason` is one of: "session_logged", "scheduled", "rest".
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
                    "template_id": None, "template_name": None}
    except Exception:
        pass  # table may not exist yet

    # 1. Explicit session row (logged / started / toggled).
    sess = db.execute(text("""
        SELECT id FROM workout_session
        WHERE user_id = :uid AND session_date = :d
        LIMIT 1
    """), {"uid": user_id, "d": on_date}).fetchone()
    if sess:
        return {"is_training_day": True, "reason": "session_logged",
                "template_id": None, "template_name": None}

    # 2. Effective approved-program phase template scheduled for this weekday.
    weekday = on_date.strftime("%A").lower()
    active_phase = get_effective_phase(db, user_id, on_date)

    if active_phase:
        templates = db.execute(text("""
            SELECT id, name, scheduled_days
            FROM fitness_template
            WHERE user_id = :uid AND phase_id = :pid
        """), {"uid": user_id, "pid": active_phase["id"]}).fetchall()
        for t in templates:
            if not t.scheduled_days:
                continue
            try:
                days = [str(d).lower() for d in json.loads(t.scheduled_days or "[]")]
            except (ValueError, TypeError):
                days = []
            if weekday in days:
                return {"is_training_day": True, "reason": "scheduled",
                        "template_id": t.id, "template_name": t.name}

    return {"is_training_day": False, "reason": "rest",
            "template_id": None, "template_name": None}


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
