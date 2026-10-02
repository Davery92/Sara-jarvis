"""
Fitness Context Provider

Builds a compact context snippet for Sara's main chat with today's nutrition
plan, macros consumed so far, and remaining budget. Enables natural food/meal
conversations without requiring the user to use a separate fitness chat.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 18: the arithmetic moved to
`services/fitness/consumers.nutrition_day`, which is the same code the Coach
API and `FitnessStateV1` use. This module now only renders. The rendered
shape is unchanged — it is a prompt fragment several other behaviours were
tuned against.

What changed underneath, and why it mattered:

* targets come from `resolve_targets`, which knows about dated revisions. The
  phase columns this used to read are mutable and track the *current* target,
  so a question about last month got this month's macros.
* a macro that was never logged now renders as unknown rather than as 0
  remaining-budget arithmetic. Summing NULLs to zero and subtracting told
  Sara the full fat budget was still available on a day where fat simply was
  not recorded.
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


async def get_fitness_context(user_id: str, db: Session) -> Optional[str]:
    """
    Build a compact fitness context string for injection into Sara's system prompt.

    Returns None if nothing is known about the athlete's plan — no targets and
    no meals. A fragment saying only "no data" costs prompt budget and tells
    Sara nothing she cannot see from the absence.
    """
    try:
        from app.services.fitness.consumers import nutrition_day

        day = nutrition_day(db, user_id)
        target = day["target"]
        eaten = day["eaten"]
        remaining = day["remaining"]
        known = day["known_fields"]

        if not any(target.values()) and not day["meal_count"] \
                and not _has_safety_context(db, user_id, day["date"]):
            # Nothing to say. A fragment saying only "no data" costs prompt
            # budget and tells Sara nothing she cannot see from the absence.
            # But a limitation or a live session IS something to say, even
            # with no targets and nothing logged — that is the turn where
            # getting it wrong matters most.
            return None

        lines = ["## David's Nutrition Plan (Today)"]

        if day["phase_name"]:
            day_label = "Training Day" if day["day_type"] == "training" else (
                "Rest Day" if day["day_type"] == "rest" else "Day type unknown"
            )
            lines.append(f"**Phase:** {day['phase_name']} | **Today:** {day_label}")

            # What today actually prescribes. Without this Sara knows the macros
            # but not the sessions, so "what's my workout today?" fell back to a
            # tool call — or to nothing. Two-a-day means both windows, in order.
            try:
                from datetime import date as _date
                from app.services.phase_resolution import get_effective_phase
                from app.services.training_day import templates_for_day
                from app.services.workout_prescription import describe_day, program_week
                today = _date.fromisoformat(day["date"])
                phase_row = get_effective_phase(db, user_id, today)
                sessions = templates_for_day(db, user_id, today, phase=phase_row)
                if sessions:
                    lines.append(
                        f"**Today's sessions:** "
                        f"{describe_day(sessions, program_week(db, user_id, today))}"
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to describe today's sessions ({type(e).__name__}): {e}"
                )

        lines.append(
            f"**Targets:** {_fmt(target['calories'])} cal | "
            f"{_fmt(target['protein'])}g protein | "
            f"{_fmt(target['carbs'])}g carbs | "
            f"{_fmt(target['fat'])}g fat"
        )
        if day["target_provenance"] in ("legacy_phase", "legacy_default"):
            # Said out loud, because these came from a mutable column with no
            # revision behind it: they are today's targets and cannot answer
            # what the targets were last month.
            lines.append(
                "  (targets have no recorded history — they describe today only)"
            )
        elif day["target_provenance"] == "unknown":
            lines.append("  (no target is recorded for today)")

        # Active limitations, ABOVE the intake numbers.
        #
        # §23.2: a safety limitation must not be clipped into irrelevance on a
        # fitness turn. A shoulder that hurts changes what Sara should
        # suggest; a macro remainder does not, so the limitation goes first
        # and survives any truncation of what follows.
        try:
            from datetime import date as _d
            from app.services.fitness.profile import get_limitations
            limitations = get_limitations(db, user_id, _d.fromisoformat(day["date"]))
        except Exception as e:
            logger.warning(
                f"Failed to read limitations ({type(e).__name__}): {e}"
            )
            limitations = []
        if limitations:
            described = "; ".join(
                limitation.area
                + (f" ({limitation.severity_flag})" if limitation.severity_flag else "")
                for limitation in limitations[:4]
            )
            lines.append(f"**Working around:** {described}")
            excluded = [
                eid for limitation in limitations
                for eid in (limitation.excluded_exercise_ids or [])
            ]
            if excluded:
                lines.append(
                    f"  ({len(excluded)} exercise(s) excluded — check before "
                    f"suggesting movements)"
                )

        # A workout happening RIGHT NOW. Without this Sara answers a
        # mid-session question as though David were at his desk, and "what's
        # next" means something different with a bar in his hands.
        live = _active_session_line(db, user_id)
        if live:
            lines.append(live)

        if day["meal_count"] > 0:
            lines.append(
                f"**Eaten so far:** {_fmt(eaten['calories'], known, 'calories')} cal | "
                f"{_fmt(eaten['protein'], known, 'protein')}g protein | "
                f"{_fmt(eaten['carbs'], known, 'carbs')}g carbs | "
                f"{_fmt(eaten['fat'], known, 'fat')}g fat"
            )
            lines.append(
                f"**Remaining:** {_fmt(remaining['calories'], known, 'calories')} cal | "
                f"{_fmt(remaining['protein'], known, 'protein')}g protein | "
                f"{_fmt(remaining['carbs'], known, 'carbs')}g carbs | "
                f"{_fmt(remaining['fat'], known, 'fat')}g fat"
            )
            if day["meals"]:
                lines.append("**Meals today:**")
                for meal in day["meals"]:
                    lines.append(
                        f"  - {meal['meal_type']}: {meal['food']} "
                        f"({_fmt(meal['calories'])} cal, {_fmt(meal['protein'])}p/"
                        f"{_fmt(meal['carbs'])}c/{_fmt(meal['fats'])}f)"
                    )
        else:
            lines.append("**No meals logged yet today.**")

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"Failed to build fitness context: {e}")
        return None


def _has_safety_context(db: Session, user_id: str, on_date: str) -> bool:
    """Whether there is a limitation or a live session worth the budget."""
    try:
        from datetime import date as _d
        from app.services.fitness.profile import get_limitations
        if get_limitations(db, user_id, _d.fromisoformat(on_date)):
            return True
    except Exception:
        pass
    return _active_session_line(db, user_id) is not None


def _active_session_line(db: Session, user_id: str) -> Optional[str]:
    """One line about an in-progress workout, or None.

    Read directly rather than through the state so a mid-session turn costs
    one small query: the deterministic state is a window over completed days
    and deliberately does not know about a session that started ten minutes
    ago.
    """
    try:
        from sqlalchemy import text
        row = db.execute(text("""
            SELECT a.id, a.status, a.total_sets_completed, a.started_at,
                   t.name AS template_name
            FROM active_workout_session a
            LEFT JOIN fitness_template t ON t.id = a.template_id
            WHERE a.user_id = :uid AND a.status IN ('active', 'in_progress')
            ORDER BY a.started_at DESC
            LIMIT 1
        """), {"uid": user_id}).fetchone()
    except Exception as e:
        logger.warning(
            f"Failed to read the active session ({type(e).__name__}): {e}"
        )
        return None
    if row is None:
        return None
    name = row.template_name or "a session"
    return (
        f"**Training right now:** {name}, "
        f"{row.total_sets_completed or 0} sets logged so far."
    )


def _fmt(val, known=None, field: Optional[str] = None) -> str:
    """Format a number, distinguishing "not recorded" from zero.

    When `known` is supplied and the field has no logged values, the answer
    is "?" — a macro nobody logged is unknown, and rendering 0 there makes
    the remaining-budget line a fabrication.
    """
    if known is not None and field is not None and not known.get(field):
        return "?"
    if val is None:
        return "—"
    return str(round(val))
