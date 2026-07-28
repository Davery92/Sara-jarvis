"""Canonical resolver for the phase in effect on a given local date.

An active program is an approved schedule. Its dated child phases become
effective by date; a stale ``fitness_phase.status`` must not keep an expired
block active or require each surface to invent its own rollover behavior.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.timezone import today as local_today


def get_active_program(db: Session, user_id: str) -> Optional[Dict[str, Any]]:
    row = db.execute(text("""
        SELECT id, name, goal, start_date, end_date, is_active, notes,
               plan_markdown, created_at, updated_at
        FROM fitness_program
        WHERE user_id = :uid AND is_active = true
        ORDER BY updated_at DESC NULLS LAST, created_at DESC
        LIMIT 1
    """), {"uid": user_id}).fetchone()
    return dict(row._mapping) if row else None


def get_effective_phase(
    db: Session,
    user_id: str,
    on_date: Optional[date] = None,
) -> Optional[Dict[str, Any]]:
    """Return the approved program phase whose dates contain ``on_date``.

    The active program is authoritative. Status is only a lifecycle cache and
    is intentionally absent from the selection predicate. Legacy standalone
    active phases remain supported when the user has no active program.
    """
    target_date = on_date or local_today()
    program = get_active_program(db, user_id)

    if program:
        row = db.execute(text("""
            SELECT p.*
            FROM fitness_phase p
            WHERE p.user_id = :uid
              AND p.program_id = :program_id
              AND (p.start_date IS NOT NULL OR p.end_date IS NOT NULL)
              AND (p.start_date IS NULL OR p.start_date <= :d)
              AND (p.end_date IS NULL OR p.end_date >= :d)
            ORDER BY
              CASE WHEN p.start_date IS NULL THEN 1 ELSE 0 END,
              p.start_date DESC NULLS LAST,
              p.order_index DESC NULLS LAST,
              p.created_at DESC
            LIMIT 1
        """), {"uid": user_id, "program_id": program["id"], "d": target_date}).fetchone()
        if row:
            phase = dict(row._mapping)
            phase["program_name"] = program["name"]
            return phase

        # Preserve undated legacy phases inside an active program, but never
        # revive an expired dated phase merely because its status is stale.
        row = db.execute(text("""
            SELECT p.*
            FROM fitness_phase p
            WHERE p.user_id = :uid
              AND p.program_id = :program_id
              AND p.status = 'active'
              AND p.start_date IS NULL
              AND p.end_date IS NULL
            ORDER BY p.order_index ASC NULLS LAST, p.created_at DESC
            LIMIT 1
        """), {"uid": user_id, "program_id": program["id"]}).fetchone()
        if row:
            phase = dict(row._mapping)
            phase["program_name"] = program["name"]
            return phase
        return None

    row = db.execute(text("""
        SELECT p.*
        FROM fitness_phase p
        WHERE p.user_id = :uid
          AND p.status = 'active'
          AND (p.start_date IS NULL OR p.start_date <= :d)
          AND (p.end_date IS NULL OR p.end_date >= :d)
        ORDER BY p.start_date DESC NULLS LAST, p.created_at DESC
        LIMIT 1
    """), {"uid": user_id, "d": target_date}).fetchone()
    return dict(row._mapping) if row else None


def reconcile_active_program_phase_statuses(
    db: Session,
    user_id: str,
    on_date: Optional[date] = None,
) -> Optional[Dict[str, Any]]:
    """Advance lifecycle status through an already-approved dated program.

    Only status metadata changes. Templates, exercises, targets, and dates are
    never modified. Callers decide when to commit the surrounding transaction.
    """
    target_date = on_date or local_today()
    program = get_active_program(db, user_id)
    phase = get_effective_phase(db, user_id, target_date)
    if not program or not phase or phase.get("program_id") != program["id"]:
        return phase

    db.execute(text("""
        UPDATE fitness_phase
        SET status = CASE
                WHEN id = :phase_id THEN 'active'
                WHEN end_date IS NOT NULL AND end_date < :d THEN 'completed'
                WHEN start_date IS NOT NULL AND start_date > :d THEN 'planned'
                ELSE status
            END,
            updated_at = CASE
                WHEN status IS DISTINCT FROM CASE
                    WHEN id = :phase_id THEN 'active'
                    WHEN end_date IS NOT NULL AND end_date < :d THEN 'completed'
                    WHEN start_date IS NOT NULL AND start_date > :d THEN 'planned'
                    ELSE status
                END
                THEN CURRENT_TIMESTAMP
                ELSE updated_at
            END
        WHERE user_id = :uid
          AND program_id = :program_id
          AND (
            id = :phase_id
            OR status = 'active'
            OR (status = 'planned' AND end_date IS NOT NULL AND end_date < :d)
          )
    """), {
        "uid": user_id,
        "program_id": program["id"],
        "phase_id": phase["id"],
        "d": target_date,
    })
    phase["status"] = "active"
    return phase


def annotate_effective_statuses(
    phases: Iterable[Dict[str, Any]],
    effective_phase_id: Optional[str],
    on_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Return response dictionaries with date-derived lifecycle status."""
    target_date = on_date or local_today()
    annotated: List[Dict[str, Any]] = []
    for original in phases:
        phase = dict(original)
        if phase.get("id") == effective_phase_id:
            phase["status"] = "active"
        elif phase.get("end_date") and phase["end_date"] < target_date:
            phase["status"] = "completed"
        elif phase.get("start_date") and phase["start_date"] > target_date:
            phase["status"] = "planned"
        annotated.append(phase)
    return annotated
