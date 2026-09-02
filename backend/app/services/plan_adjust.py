"""Timeline surgery for the active fitness program.

The phase remains the single unit of nutrition truth (see
docs/plans/FITNESS_PLAN_CONTROL_2026_08_17.md): a "cut" or "bulk" is a dated
phase inserted into the active program, not a new override table. Once a
phase's dates are correct, `phase_resolution.get_effective_phase()` already
resolves it everywhere (today-target, fitness_context, morning brief) with no
resolver changes needed.

`insert_phase_block` inserts a dated block, trimming/splitting/shifting
whatever phases it collides with so dates never overlap two rows on the same
day. `end_phase_block_early` closes a block early and re-opens whatever phase
was pushed/trimmed to start right after it.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.timezone import today as local_today
from app.services.phase_resolution import (
    get_active_program,
    get_effective_phase,
    reconcile_active_program_phase_statuses,
)

logger = logging.getLogger(__name__)

MAX_GUIDE_BYTES = 32 * 1024

_PROVENANCE_PREFIX = "[[plan_adjust:"
_PROVENANCE_SUFFIX = "]]"


def _next_monday(from_date: date) -> date:
    """Upcoming Monday; if from_date is already Monday, use it."""
    return from_date + timedelta(days=(0 - from_date.weekday()) % 7)


def _encode_provenance(data: Dict[str, Any], notes: Optional[str]) -> str:
    body = (notes or "").strip()
    marker = f"{_PROVENANCE_PREFIX}{json.dumps(data)}{_PROVENANCE_SUFFIX}"
    return f"{body}\n\n{marker}" if body else marker


def _decode_provenance(notes: Optional[str]) -> Optional[Dict[str, Any]]:
    if not notes or _PROVENANCE_PREFIX not in notes:
        return None
    start = notes.rfind(_PROVENANCE_PREFIX)
    end = notes.find(_PROVENANCE_SUFFIX, start)
    if end == -1:
        return None
    raw = notes[start + len(_PROVENANCE_PREFIX): end]
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _row_to_dict(row) -> Dict[str, Any]:
    return dict(row._mapping)


def _fetch_dated_phases(db: Session, user_id: str, program_id: str) -> List[Dict[str, Any]]:
    rows = db.execute(text("""
        SELECT id, name, goal, order_index, duration_weeks, start_date, end_date,
               status, notes, deload_week,
               calories_target, protein_target, carbs_target, fat_target,
               calories_training_day, calories_rest_day,
               carbs_training_day, carbs_rest_day,
               fat_training_day, fat_rest_day, daily_steps_target,
               training_days_per_week
        FROM fitness_phase
        WHERE user_id = :uid AND program_id = :pid
          AND start_date IS NOT NULL AND end_date IS NOT NULL
        ORDER BY start_date ASC
    """), {"uid": user_id, "pid": program_id}).fetchall()
    return [_row_to_dict(r) for r in rows]


def _renumber_order_index(db: Session, user_id: str, program_id: str) -> None:
    rows = db.execute(text("""
        SELECT id FROM fitness_phase
        WHERE user_id = :uid AND program_id = :pid
        ORDER BY start_date ASC NULLS LAST, order_index ASC NULLS LAST, created_at ASC
    """), {"uid": user_id, "pid": program_id}).fetchall()
    for i, row in enumerate(rows):
        db.execute(text("UPDATE fitness_phase SET order_index = :oi WHERE id = :id"),
                   {"oi": i, "id": row.id})


def _copy_templates(db: Session, user_id: str, from_phase_id: str, to_phase_id: str) -> int:
    templates = db.execute(text("""
        SELECT name, scheduled_days, exercises, order_in_phase, notes
        FROM fitness_template
        WHERE user_id = :uid AND phase_id = :pid
    """), {"uid": user_id, "pid": from_phase_id}).fetchall()
    for t in templates:
        db.execute(text("""
            INSERT INTO fitness_template (id, user_id, phase_id, name, scheduled_days,
                exercises, order_in_phase, notes, created_at, updated_at)
            VALUES (:id, :uid, :pid, :name, :days, :ex, :oi, :notes, now(), now())
        """), {
            "id": str(uuid.uuid4()), "uid": user_id, "pid": to_phase_id,
            "name": t.name, "days": t.scheduled_days, "ex": t.exercises,
            "oi": t.order_in_phase, "notes": t.notes,
        })
    return len(templates)


def _insert_phase_row(db: Session, user_id: str, program_id: str, *, phase_id: str,
                       name: str, goal: Optional[str], order_index: int,
                       duration_weeks: Optional[int], start: date, end: date,
                       status: str, deload_week: Optional[int], notes: Optional[str],
                       nutrition: Dict[str, Any]) -> None:
    db.execute(text("""
        INSERT INTO fitness_phase (
            id, user_id, program_id, name, goal, order_index, duration_weeks,
            start_date, end_date, status, deload_week, notes,
            calories_target, protein_target, carbs_target, fat_target,
            calories_training_day, calories_rest_day,
            carbs_training_day, carbs_rest_day,
            fat_training_day, fat_rest_day, daily_steps_target,
            training_days_per_week, created_at, updated_at
        ) VALUES (
            :id, :uid, :pid, :name, :goal, :oi, :dw,
            :start, :end, :status, :deload, :notes,
            :cal, :pro, :carb, :fat,
            :cal_t, :cal_r, :carb_t, :carb_r, :fat_t, :fat_r, :steps,
            :tdpw, now(), now()
        )
    """), {
        "id": phase_id, "uid": user_id, "pid": program_id, "name": name, "goal": goal,
        "oi": order_index, "dw": duration_weeks, "start": start, "end": end,
        "status": status, "deload": deload_week, "notes": notes,
        "cal": nutrition.get("calories_target"), "pro": nutrition.get("protein_target"),
        "carb": nutrition.get("carbs_target"), "fat": nutrition.get("fat_target"),
        "cal_t": nutrition.get("calories_training_day"), "cal_r": nutrition.get("calories_rest_day"),
        "carb_t": nutrition.get("carbs_training_day"), "carb_r": nutrition.get("carbs_rest_day"),
        "fat_t": nutrition.get("fat_training_day"), "fat_r": nutrition.get("fat_rest_day"),
        "steps": nutrition.get("daily_steps_target"), "tdpw": nutrition.get("training_days_per_week"),
    })


def insert_phase_block(
    db: Session,
    user_id: str,
    *,
    name: Optional[str] = None,
    goal: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    duration_weeks: Optional[int] = None,
    nutrition: Optional[Dict[str, Any]] = None,
    mode: str = "overlay",
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert a dated block (cut/bulk/maintenance) into the active program.

    `mode="overlay"` (default) trims/splits whatever it collides with so dates
    never overlap. `mode="push"` instead shifts every later phase back by the
    block's length, extending the program.
    """
    if mode not in ("overlay", "push"):
        raise ValueError(f"Unknown mode '{mode}' (expected 'overlay' or 'push')")

    program = get_active_program(db, user_id)
    if not program:
        raise ValueError("No active program — activate or import a program first.")

    block_start = start_date or _next_monday(local_today())
    if end_date:
        block_end = end_date
    elif duration_weeks:
        block_end = block_start + timedelta(weeks=duration_weeks) - timedelta(days=1)
    else:
        raise ValueError("Either end_date or duration_weeks is required.")
    if block_end < block_start:
        raise ValueError("end_date must be on or after start_date.")

    # The stored name always carries goal + dates ("Cut (Aug 18 – Sep 7)") so
    # Sara's chat context and the morning brief (which just print phase.name)
    # read naturally without any resolver/display changes.
    base_name = (name or "").strip() or (goal.strip().capitalize() if goal else "Block")
    name = f"{base_name} ({_fmt_short_date(block_start)}–{_fmt_short_date(block_end)})"

    nutrition = nutrition or {}
    pre_cut = block_start - timedelta(days=1)
    post_cut = block_end + timedelta(days=1)
    push_delta = (block_end - block_start) + timedelta(days=1)

    phases = _fetch_dated_phases(db, user_id, program["id"])

    trimmed: List[Dict[str, Any]] = []
    shifted: List[Dict[str, Any]] = []
    shelved: List[Dict[str, Any]] = []
    split_phase_id: Optional[str] = None
    next_neighbor_id: Optional[str] = None

    for p in phases:
        p_start, p_end = p["start_date"], p["end_date"]
        has_pre = p_start <= pre_cut
        has_post = p_end >= post_cut
        overlaps = not (p_end < block_start or p_start > block_end)

        if mode == "push":
            if p_start >= block_start:
                new_start, new_end = p_start + push_delta, p_end + push_delta
                db.execute(text("""
                    UPDATE fitness_phase SET start_date = :s, end_date = :e, updated_at = now()
                    WHERE id = :id
                """), {"s": new_start, "e": new_end, "id": p["id"]})
                shifted.append({"id": p["id"], "name": p["name"],
                                 "start_date": new_start.isoformat(), "end_date": new_end.isoformat()})
            elif p_end >= block_start:
                db.execute(text("UPDATE fitness_phase SET end_date = :e, updated_at = now() WHERE id = :id"),
                           {"e": pre_cut, "id": p["id"]})
                trimmed.append({"id": p["id"], "name": p["name"], "end_date": pre_cut.isoformat()})
            continue

        # mode == "overlay"
        if not overlaps:
            continue
        if has_pre and has_post:
            # the block lands entirely inside this phase — split it in two
            db.execute(text("UPDATE fitness_phase SET end_date = :e, updated_at = now() WHERE id = :id"),
                       {"e": pre_cut, "id": p["id"]})
            trimmed.append({"id": p["id"], "name": p["name"], "end_date": pre_cut.isoformat()})

            new_id = str(uuid.uuid4())
            _insert_phase_row(
                db, user_id, program["id"], phase_id=new_id, name=p["name"], goal=p["goal"],
                order_index=p["order_index"], duration_weeks=p["duration_weeks"],
                start=post_cut, end=p_end, status="planned", deload_week=p["deload_week"],
                notes=p["notes"], nutrition=p,
            )
            _copy_templates(db, user_id, p["id"], new_id)
            split_phase_id = new_id
        elif has_pre:
            db.execute(text("UPDATE fitness_phase SET end_date = :e, updated_at = now() WHERE id = :id"),
                       {"e": pre_cut, "id": p["id"]})
            trimmed.append({"id": p["id"], "name": p["name"], "end_date": pre_cut.isoformat()})
        elif has_post:
            db.execute(text("UPDATE fitness_phase SET start_date = :s, updated_at = now() WHERE id = :id"),
                       {"s": post_cut, "id": p["id"]})
            trimmed.append({"id": p["id"], "name": p["name"], "start_date": post_cut.isoformat()})
        else:
            # fully inside the block — shelve it. Status alone can't keep it out
            # of the resolver (get_effective_phase intentionally ignores status),
            # so its dates are cleared too; the row and its templates are kept.
            db.execute(text("""
                UPDATE fitness_phase
                SET status = 'completed', start_date = NULL, end_date = NULL, updated_at = now()
                WHERE id = :id
            """), {"id": p["id"]})
            shelved.append({"id": p["id"], "name": p["name"],
                             "original_start": p_start.isoformat(), "original_end": p_end.isoformat()})

    if program.get("end_date"):
        if mode == "push":
            # every later phase shifted by push_delta, so the program runs that much longer
            new_program_end = program["end_date"] + push_delta
        elif program["end_date"] < block_end:
            new_program_end = block_end
        else:
            new_program_end = None
        if new_program_end:
            db.execute(text("UPDATE fitness_program SET end_date = :e, updated_at = now() WHERE id = :id"),
                       {"e": new_program_end, "id": program["id"]})

    # Whichever surviving dated phase now starts right after the block is the
    # "next neighbor" end_phase_block_early re-opens if the block ends early.
    neighbor_row = db.execute(text("""
        SELECT id FROM fitness_phase WHERE user_id = :uid AND program_id = :pid AND start_date = :s
    """), {"uid": user_id, "pid": program["id"], "s": post_cut}).fetchone()
    if neighbor_row:
        next_neighbor_id = neighbor_row.id

    block_id = str(uuid.uuid4())
    provenance = {
        "block": True, "mode": mode, "next_neighbor_id": next_neighbor_id,
        "natural_end_date": block_end.isoformat(),
    }
    _insert_phase_row(
        db, user_id, program["id"], phase_id=block_id, name=name, goal=goal,
        order_index=0, duration_weeks=None, start=block_start, end=block_end,
        status="planned", deload_week=None,
        notes=_encode_provenance(provenance, notes), nutrition=nutrition,
    )

    # The weekly workouts continue through the block unless told otherwise —
    # copy them from whatever phase was effective the day before it starts.
    template_source = get_effective_phase(db, user_id, block_start - timedelta(days=1))
    templates_copied = 0
    if template_source and template_source["id"] != block_id:
        templates_copied = _copy_templates(db, user_id, template_source["id"], block_id)

    _renumber_order_index(db, user_id, program["id"])

    existing_guide = _load_nutrition_guide(db, program["id"])
    new_guide = _regenerate_nutrition_guide(existing_guide, name, nutrition)
    db.execute(text("UPDATE fitness_program SET nutrition_guide = :g, updated_at = now() WHERE id = :id"),
               {"g": json.dumps(new_guide), "id": program["id"]})

    reconcile_active_program_phase_statuses(db, user_id, local_today())

    return {
        "block_phase_id": block_id,
        "name": name,
        "start_date": block_start.isoformat(),
        "end_date": block_end.isoformat(),
        "mode": mode,
        "trimmed_phases": trimmed,
        "shifted_phases": shifted,
        "shelved_phases": shelved,
        "split_phase_id": split_phase_id,
        "templates_copied": templates_copied,
        "nutrition_guide_updated": True,
    }


def end_phase_block_early(db: Session, user_id: str, phase_id: str, on_date: date) -> Dict[str, Any]:
    """End a block early and re-open whatever phase it pushed/trimmed to start after it."""
    row = db.execute(text("""
        SELECT id, name, program_id, start_date, end_date, notes
        FROM fitness_phase WHERE id = :id AND user_id = :uid
    """), {"id": phase_id, "uid": user_id}).fetchone()
    if not row:
        raise ValueError("Phase not found.")
    phase = _row_to_dict(row)
    if not phase["start_date"] or not phase["end_date"]:
        raise ValueError("Phase has no dated range to end early.")
    if on_date < phase["start_date"]:
        raise ValueError("on_date is before the block's start date.")

    natural_end = phase["end_date"]
    db.execute(text("UPDATE fitness_phase SET end_date = :e, status = 'completed', updated_at = now() WHERE id = :id"),
               {"e": on_date, "id": phase_id})

    restored_neighbor = None
    provenance = _decode_provenance(phase["notes"]) or {}
    next_id = provenance.get("next_neighbor_id")
    if next_id and on_date < natural_end:
        neighbor = db.execute(text("""
            SELECT id, name, start_date FROM fitness_phase WHERE id = :id AND user_id = :uid
        """), {"id": next_id, "uid": user_id}).fetchone()
        if neighbor and neighbor.start_date and neighbor.start_date > on_date:
            new_start = on_date + timedelta(days=1)
            db.execute(text("UPDATE fitness_phase SET start_date = :s, updated_at = now() WHERE id = :id"),
                       {"s": new_start, "id": next_id})
            restored_neighbor = {"id": next_id, "name": neighbor.name, "start_date": new_start.isoformat()}

    program_id = phase["program_id"]
    if program_id:
        _renumber_order_index(db, user_id, program_id)
    reconcile_active_program_phase_statuses(db, user_id, local_today())

    return {
        "phase_id": phase_id,
        "name": phase["name"],
        "end_date": on_date.isoformat(),
        "restored_neighbor": restored_neighbor,
    }


# ──────────────────────────────────────────────────────────────────────────
# Nutrition guide
# ──────────────────────────────────────────────────────────────────────────

def _load_nutrition_guide(db: Session, program_id: str) -> Optional[Dict[str, Any]]:
    row = db.execute(text("SELECT nutrition_guide FROM fitness_program WHERE id = :id"),
                      {"id": program_id}).fetchone()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0])
    except (ValueError, TypeError):
        return None


def _fmt_short_date(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def _regenerate_nutrition_guide(
    existing: Optional[Dict[str, Any]],
    block_name: str,
    nutrition: Dict[str, Any],
) -> Dict[str, Any]:
    """Mechanically rebuild the macros table + weekly average + a banner line
    from the new block's numbers. rules/carb_timing/staples/self_check are
    left untouched — no LLM involved."""
    guide: Dict[str, Any] = dict(existing) if existing else {}

    def split(train_key: str, rest_key: str, flat_key: str):
        flat = nutrition.get(flat_key)
        t = nutrition.get(train_key)
        r = nutrition.get(rest_key)
        return (t if t is not None else flat), (r if r is not None else flat)

    cal_t, cal_r = split("calories_training_day", "calories_rest_day", "calories_target")
    carb_t, carb_r = split("carbs_training_day", "carbs_rest_day", "carbs_target")
    fat_t, fat_r = split("fat_training_day", "fat_rest_day", "fat_target")
    protein = nutrition.get("protein_target")

    def cell(v: Optional[int], suffix: str = "") -> str:
        return f"~{v:,}{suffix}" if v is not None else "—"

    guide["macros"] = [
        {"label": "Calories", "training": cell(cal_t), "rest": cell(cal_r)},
        {"label": "Protein", "training": cell(protein, "g"), "rest": cell(protein, "g")},
        {"label": "Carbs", "training": cell(carb_t, "g"), "rest": cell(carb_r, "g")},
        {"label": "Fat", "training": cell(fat_t, "g"), "rest": cell(fat_r, "g")},
    ]

    tdpw = nutrition.get("training_days_per_week")
    if tdpw and cal_t is not None and cal_r is not None and cal_t != cal_r:
        avg = (cal_t * tdpw + cal_r * (7 - tdpw)) / 7
        guide["weekly_average"] = f"~{avg:,.0f} cal/day"
    elif nutrition.get("calories_target") is not None:
        guide["weekly_average"] = f"~{nutrition['calories_target']:,} cal/day"

    # block_name already carries its own date range (see insert_phase_block),
    # so the banner doesn't repeat it.
    banner = f"{block_name} is active."
    prior = str(guide.get("how_it_works") or "").strip()
    guide["how_it_works"] = f"{banner} {prior}".strip() if prior else banner

    return guide


def update_nutrition_guide(db: Session, user_id: str, guide: Dict[str, Any]) -> Dict[str, Any]:
    """Overwrite the active program's nutrition guide (used by the PATCH endpoint / tool)."""
    if not isinstance(guide, dict):
        raise ValueError("guide must be a JSON object.")
    encoded = json.dumps(guide)
    if len(encoded.encode("utf-8")) > MAX_GUIDE_BYTES:
        raise ValueError(f"guide exceeds the {MAX_GUIDE_BYTES // 1024}KB size cap.")

    program = get_active_program(db, user_id)
    if not program:
        raise ValueError("No active program — activate or import a program first.")

    db.execute(text("UPDATE fitness_program SET nutrition_guide = :g, updated_at = now() WHERE id = :id"),
               {"g": encoded, "id": program["id"]})
    return {"program_id": program["id"], "guide": guide}
