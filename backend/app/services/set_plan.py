"""Resolve a template exercise's structured `set_plan` (top/backoff loading
table) into the ordered list of per-set targets for one session.

TWO_A_DAY_AM_SETS_AND_FOOD_REPEAT_PLAN_2026_09_18 Part A2. The data itself is
written onto `fitness_template.exercises[i].set_plan` by
`backend/scripts/plans/add_set_plan_two_a_day.py` — see that file for the
shape (`kind: "top_backoff"`, `warmup: [...]`, `weeks: {"1": {...}, ...}`,
keyed by *program* week, not phase week).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def is_plan_driven(spec: Dict[str, Any]) -> bool:
    plan = spec.get("set_plan")
    return bool(plan and plan.get("kind") == "top_backoff" and plan.get("weeks"))


def _min_reps(reps: Any) -> Optional[int]:
    """Lower end of a rep target ("2-4" -> 2, "4+" -> 4, "3" -> 3)."""
    if reps in (None, ""):
        return None
    s = str(reps).strip().rstrip("+")
    if "-" in s:
        s = s.split("-", 1)[0]
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def resolve_set_plan(
    spec: Dict[str, Any],
    week: Optional[int],
    last_top_set: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve `spec["set_plan"]` for program `week`.

    `last_top_set`, when known, is the most recently logged working set with
    `flags.role == 'top'` for this lift: {"rpe": float|None, "reps": int|None,
    "plan_week": int|None}. Its absence — or a missing `plan_week` on it —
    means "no prior plan-tracked performance to gate on" (first session for
    this lift, or a set logged before this feature existed), so the planned
    week is used untouched. The advance rule (spec: "advance only when the
    top set is clean and <= RPE 8, else repeat the previous week") only fires
    once there is something to check.

    Returns {"sets": [...], "effective_week", "requested_week", "held",
    "note", "working_set_count"}. `sets` is empty when this exercise carries
    no usable set_plan for `week`.
    """
    empty = {"sets": [], "effective_week": None, "requested_week": None,
              "held": False, "note": None, "working_set_count": 0}
    if not is_plan_driven(spec) or not week:
        return empty

    weeks: Dict[str, Any] = spec["set_plan"]["weeks"]
    if str(week) in weeks:
        requested_week = week
    else:
        # Past the end of a defined table (program continues beyond week 8):
        # hold at the last defined week rather than produce nothing.
        available = [int(w) for w in weeks if int(w) <= week]
        requested_week = max(available) if available else None
    if requested_week is None:
        return empty

    requested_row = weeks[str(requested_week)]
    effective_week = requested_week
    held = False
    note: Optional[str] = None

    # Calendar-fixed weeks (deload / rep-PR) are authoritative regardless of
    # how the prior top set went — nothing to gate.
    if not requested_row.get("label") and last_top_set and last_top_set.get("plan_week"):
        last_week = int(last_top_set["plan_week"])
        last_row = weeks.get(str(last_week))
        if last_row and not last_row.get("label"):
            low = _min_reps((last_row.get("top") or {}).get("reps"))
            rpe = last_top_set.get("rpe")
            reps = last_top_set.get("reps")
            dirty = (rpe is not None and rpe > 8) or (
                low is not None and reps is not None and reps < low)
            if dirty:
                held = True
                effective_week = max(1, last_week)
                rpe_txt = f"RPE {rpe:g}" if rpe is not None else "under the rep target"
                note = f"Holding week {effective_week} loads — last top set was {rpe_txt}"

    row = weeks.get(str(effective_week)) or requested_row
    top = row.get("top") or {}
    backoff = row.get("backoff") or {}
    warmups = spec["set_plan"].get("warmup") or []

    resolved: List[Dict[str, Any]] = []
    for w in warmups:
        resolved.append({
            "index": len(resolved), "kind": "warmup",
            "weight": w.get("weight"), "reps": str(w.get("reps")),
        })

    resolved.append({
        "index": len(resolved), "kind": "top",
        "weight": top.get("weight"), "reps": str(top.get("reps")),
        **({"rpe_cap": top.get("rpe_cap")} if top.get("rpe_cap") is not None else {}),
    })

    backoff_sets = int(backoff.get("sets") or 0)
    for _ in range(backoff_sets):
        resolved.append({
            "index": len(resolved), "kind": "backoff",
            "weight": backoff.get("weight"), "reps": str(backoff.get("reps")),
            **({"rir": backoff.get("rir")} if backoff.get("rir") else {}),
        })

    if not note and row.get("label"):
        note = row["label"]

    return {
        "sets": resolved,
        "effective_week": effective_week,
        "requested_week": requested_week,
        "held": held,
        "note": note,
        "working_set_count": 1 + backoff_sets,
    }


def next_entry(
    resolved_sets: List[Dict[str, Any]], completed_warmup: int, completed_working: int,
    requested_kind: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Which resolved entry is up next.

    Warm-ups and working sets (top + backoff) are tracked as two independent
    sequences, not one flat cursor — `completed_working` alone decides which
    top/backoff entry is next, regardless of how many warm-ups happened.

    `requested_kind` picks which sequence to resolve:
      - omitted (display/prefill use — what to show before a kind is chosen):
        warm-ups first, then working sets, the natural default order.
      - "warmup": the next warm-up entry, or None once they're all logged.
      - "working": the next top/backoff entry — this is what makes "Skip
        warm-ups" actually skip: logging a working set resolves against the
        working sequence directly, never blocked on warm-ups being unlogged.
    """
    warmups = [s for s in resolved_sets if s.get("kind") == "warmup"]
    working = [s for s in resolved_sets if s.get("kind") != "warmup"]
    if requested_kind == "warmup":
        return warmups[completed_warmup] if completed_warmup < len(warmups) else None
    if requested_kind == "working":
        return working[completed_working] if completed_working < len(working) else None
    if completed_warmup < len(warmups):
        return warmups[completed_warmup]
    if completed_working < len(working):
        return working[completed_working]
    return None


def describe_resolved(exercise_name: str, resolved: Dict[str, Any]) -> str:
    """Human line for the resolved plan: 'Week 1: top 225x2-4, then 3x4-6 @200'."""
    sets = resolved.get("sets") or []
    top = next((s for s in sets if s["kind"] == "top"), None)
    backoffs = [s for s in sets if s["kind"] == "backoff"]
    if not top:
        return exercise_name
    week = resolved.get("effective_week")
    label = f"Week {week}" if week else "This week"
    parts = [f"top {top['weight']}x{top['reps']}"]
    if backoffs:
        b = backoffs[0]
        parts.append(f"then {len(backoffs)}x{b['reps']} @{b['weight']}")
    return f"{label}: {', '.join(parts)}"
