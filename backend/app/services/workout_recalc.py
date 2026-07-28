"""One deterministic derivation of workout state from its performed sets.

SARA_WORKOUT_RELIABILITY_AND_FLEXIBLE_SETS_PLAN_2026_07_27 §6.4.

Before this, `log_set` incremented counters as it went: `total_sets_completed +
1`, `total_volume + weight*reps`. That works exactly as long as sets only ever
arrive, one at a time, in order. Add-set, drop segments, revise and void break
all three assumptions at once, and the plan is explicit that five command
handlers must not each invent their own arithmetic.

So state is *derived*, never patched. After any mutation the caller runs
`recalculate_session`, which re-reads the live rows and writes back:

  - completed working sets per exercise (and the cursor that follows from them)
  - whether the workout is finished
  - total sets and total volume
  - the PR ledger for sets that no longer stand

Two rules the whole file rests on (§4.4):

  - only a non-voided `working` set consumes a prescribed set slot;
  - every non-voided set of any kind contributes volume.

A drop segment is real work at a deliberately lower weight, so it must add
volume without advancing the working-set cursor and without ever reading as a
regression. A warm-up is the same shape. A voided set contributes nothing to
anything — which is what makes Undo trustworthy enough to use mid-workout.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Every read that drives progress, volume, PRs or progression carries this.
# Written once here so a new call site cannot quietly forget the voided check.
LIVE_SET_PREDICATE = "voided_at IS NULL"
WORKING_SET_PREDICATE = "voided_at IS NULL AND counts_toward_target = true"


def effective_name(exercise: Dict[str, Any]) -> str:
    """The identity a set is logged under — the variant if one is recorded.

    Same rule as `workout_session_service._effective_name`; duplicated rather
    than imported to keep this module free of that import cycle.
    """
    variant = (exercise.get("variant") or "").strip()
    return variant or exercise.get("name") or ""


def target_sets_for(exercise: Dict[str, Any]) -> int:
    """Effective working-set target for this workout.

    `sets` is the prescription copied from the template at start. `sets_added`
    is what David added *during this workout only* — it is deliberately a
    separate field so the prescription stays visible and the honest
    "4 sets (3 prescribed)" line the UI shows is derivable (§7.1).
    """
    base = exercise.get("sets") or 0
    try:
        base = int(base)
    except (TypeError, ValueError):
        base = 0
    try:
        added = int(exercise.get("sets_added") or 0)
    except (TypeError, ValueError):
        added = 0
    return max(0, base + added)


def prescribed_sets_for(exercise: Dict[str, Any]) -> int:
    """The set count this workout was created with. Never changes in-session.

    Deliberately `sets` and not `sets_original`: on a deload week the workout
    genuinely prescribes the reduced number, and telling David he is two sets
    short of a plan the program itself backed off would be a lie in the other
    direction.
    """
    try:
        return max(0, int(exercise.get("sets") or 0))
    except (TypeError, ValueError):
        return 0


# ────────────────────────────────────────────────────────────────────────
# Reading performed sets
# ────────────────────────────────────────────────────────────────────────

def load_session_sets(db: Session, session_id: str, *, include_voided: bool = False) -> List[Dict[str, Any]]:
    """Every set logged in this session, oldest first.

    Voided rows are returned only when explicitly asked for: the phone's
    View/Edit list wants to show that a set was struck, every counting query
    does not.
    """
    sql = """
        SELECT id, exercise_id, set_index, weight, reps, rpe, notes, is_pr,
               set_kind, parent_set_id, set_group_id, group_sequence,
               counts_toward_target, voided_at, void_reason, revised_from_set_id,
               session_time, created_at
        FROM workout_log
        WHERE active_session_id = :sid
    """
    if not include_voided:
        sql += f" AND {LIVE_SET_PREDICATE}"
    sql += " ORDER BY created_at ASC, group_sequence ASC"
    rows = db.execute(text(sql), {"sid": session_id}).fetchall()
    return [_row_to_set(r) for r in rows]


def _row_to_set(row) -> Dict[str, Any]:
    return {
        "id": row.id,
        "exercise": row.exercise_id,
        "set_index": row.set_index,
        "weight": float(row.weight) if row.weight is not None else None,
        "reps": row.reps,
        "rpe": row.rpe,
        "notes": row.notes,
        "is_pr": bool(row.is_pr),
        "set_kind": row.set_kind or "working",
        "parent_set_id": row.parent_set_id,
        "set_group_id": row.set_group_id,
        "group_sequence": row.group_sequence or 0,
        "counts_toward_target": bool(row.counts_toward_target),
        "voided": row.voided_at is not None,
        "void_reason": row.void_reason,
        "revised_from_set_id": row.revised_from_set_id,
        "logged_at": row.session_time.isoformat() if row.session_time else (
            row.created_at.isoformat() if row.created_at else None
        ),
    }


def working_counts(db: Session, session_id: str) -> Dict[str, int]:
    """Live working sets per exercise name — the completion arithmetic.

    Drop segments and warm-ups are excluded by `counts_toward_target`, so
    three drops after a working set still read as one set done (§4.4).
    """
    rows = db.execute(text(f"""
        SELECT exercise_id, COUNT(*) AS c FROM workout_log
        WHERE active_session_id = :sid AND {WORKING_SET_PREDICATE}
        GROUP BY exercise_id
    """), {"sid": session_id}).fetchall()
    return {r.exercise_id: int(r.c) for r in rows}


def drop_counts(db: Session, session_id: str) -> Dict[str, int]:
    rows = db.execute(text(f"""
        SELECT exercise_id, COUNT(*) AS c FROM workout_log
        WHERE active_session_id = :sid AND {LIVE_SET_PREDICATE} AND set_kind = 'drop'
        GROUP BY exercise_id
    """), {"sid": session_id}).fetchall()
    return {r.exercise_id: int(r.c) for r in rows}


def completed_for(exercises: List[Dict[str, Any]], counts: Dict[str, int], idx: int) -> int:
    """Completed working sets for one exercise, capped at its effective target."""
    if idx < 0 or idx >= len(exercises):
        return 0
    ex = exercises[idx]
    return min(counts.get(effective_name(ex), 0), target_sets_for(ex))


def next_incomplete_index(
    exercises: List[Dict[str, Any]], counts: Dict[str, int], from_idx: int
) -> Optional[int]:
    """Next exercise with working sets still owed, searching forward and wrapping.

    Wrapping is what lets a skipped machine be picked up later — and what makes
    Add Set on an already-finished exercise reopen it rather than strand the
    cursor at the end of the workout.
    """
    n = len(exercises)
    if n == 0:
        return None
    for step in range(1, n + 1):
        j = (from_idx + step) % n
        if completed_for(exercises, counts, j) < target_sets_for(exercises[j]):
            return j
    return None


# ────────────────────────────────────────────────────────────────────────
# The derivation
# ────────────────────────────────────────────────────────────────────────

def recalculate_session(
    db: Session,
    session_id: str,
    *,
    snapshot: Optional[Dict[str, Any]] = None,
    prefer_exercise_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Re-derive the whole session from its live sets and write it back.

    Never commits — the caller owns the transaction, exactly as every other
    mutation in `workout_command_service` does.

    `prefer_exercise_index` keeps the cursor where the user just acted when
    that exercise still has work left: after logging set 2 of 3 the cursor
    should stay, and only move on when the exercise is genuinely finished.
    """
    row = db.execute(text("""
        SELECT id, workout_snapshot, current_exercise_index
        FROM active_workout_session WHERE id = :sid
    """), {"sid": session_id}).fetchone()
    if not row:
        raise ValueError(f"Session {session_id} not found")

    snap = snapshot
    if snap is None:
        raw = row.workout_snapshot
        if isinstance(raw, str):
            import json
            snap = json.loads(raw) if raw else {}
        else:
            snap = raw or {}
    exercises: List[Dict[str, Any]] = snap.get("exercises") or []

    counts = working_counts(db, session_id)
    totals = db.execute(text(f"""
        SELECT
            COUNT(*) FILTER (WHERE counts_toward_target = true) AS working_sets,
            COUNT(*) AS all_sets,
            COALESCE(SUM(COALESCE(weight, 0) * COALESCE(reps, 0)), 0) AS volume
        FROM workout_log
        WHERE active_session_id = :sid AND {LIVE_SET_PREDICATE}
    """), {"sid": session_id}).fetchone()

    completed_working = int(totals.working_sets or 0)
    total_volume = Decimal(str(totals.volume or 0))

    # Cursor. Stay on the exercise the user is working through; move only when
    # it has actually hit its (possibly increased) target.
    base_idx = prefer_exercise_index
    if base_idx is None:
        base_idx = row.current_exercise_index or 0
    if base_idx < 0 or base_idx >= len(exercises):
        base_idx = 0

    workout_complete = False
    cursor_idx = base_idx
    if exercises:
        if completed_for(exercises, counts, base_idx) < target_sets_for(exercises[base_idx]):
            cursor_idx = base_idx
        else:
            nxt = next_incomplete_index(exercises, counts, base_idx)
            if nxt is None:
                workout_complete = True
                cursor_idx = base_idx
            else:
                cursor_idx = nxt
    set_idx = completed_for(exercises, counts, cursor_idx)

    db.execute(text("""
        UPDATE active_workout_session
        SET current_exercise_index = :ei,
            current_set_index = :si,
            total_sets_completed = :done,
            total_volume = :vol
        WHERE id = :sid
    """), {
        "ei": cursor_idx, "si": set_idx, "done": completed_working,
        "vol": total_volume, "sid": session_id,
    })

    return {
        "cursor_exercise_index": cursor_idx,
        "cursor_set_index": set_idx,
        "completed_working_sets": completed_working,
        "total_logged_sets": int(totals.all_sets or 0),
        "total_volume": float(total_volume),
        "workout_complete": workout_complete,
        "counts": counts,
    }


def total_target_sets(exercises: List[Dict[str, Any]]) -> int:
    """Workout-level set target using *effective* per-exercise targets (§6.2)."""
    return sum(target_sets_for(e) for e in exercises)


# ────────────────────────────────────────────────────────────────────────
# PR ledger
# ────────────────────────────────────────────────────────────────────────

def withdraw_prs_for_set(db: Session, user_id: str, set_id: str) -> int:
    """Remove PR records a set no longer supports.

    A PR is a claim about a set that happened. Void or correct the set and the
    claim has to go with it, or Sara congratulates David for a lift he told her
    he did not do (§4.4, §12.7).
    """
    result = db.execute(text("""
        DELETE FROM exercise_pr WHERE user_id = :uid AND workout_set_id = :sid
    """), {"uid": user_id, "sid": set_id})
    db.execute(text("UPDATE workout_log SET is_pr = false WHERE id = :sid"), {"sid": set_id})
    return int(result.rowcount or 0)
