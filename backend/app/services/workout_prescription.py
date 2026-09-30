"""What the plan actually prescribes for a given day — name, week, and load.

The two-a-day program (docs/fitness/TWO_A_DAY_POWERBUILDING_RECOMP_2026_09_14.md)
carries an 8-week loading table per AM lift, and the importer has nowhere
structured to put it, so it lives in the exercise's `notes` in the same
convention Block 3 used:

    TOP: Wk1 270x2 · Wk2 270x3 · … · Wk8 REP PR 270x5 target
    BACKOFF: Wk1 230 · Wk2 230 · … · Wk8 235

Without this, every "today's workout" reader can name the session but not the
number — Sara says "NewTech Flat Press" when the useful answer is "top set
270×2, then 3×4–6 at 230". These helpers turn the notes back into that line.

Known gap (accepted in the plan): `progressive_overload.py` still computes its
own +5/+10 suggestion for `/weight-suggestion`. For the AM lifts the weekly
table here is what the program prescribes.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# "Wk3 240" / "Wk4 DELOAD 210x5x2" / "Wk8 REP PR 270x5 target"
_WEEK_TOKEN = re.compile(r"^Wk(\d+)\s+(.+)$", re.IGNORECASE)
_SEPARATORS = re.compile(r"\s*[·|]\s*")
# "sets 2-4 = BACKOFF x4-6 @1-2 RIR" — the backoff rep range, which is narrower
# than the exercise's `reps` (that spans the top set too: "2-6").
_BACKOFF_REPS = re.compile(r"BACKOFF\s*x\s*(\d+(?:\s*-\s*\d+)?)", re.IGNORECASE)
# A week token may lead with the week's character: "DELOAD 230x4", "REP PR 270x5".
_MARKER = re.compile(r"^(DELOAD|REP PR)\s+(.*)$", re.IGNORECASE)
# "230" / "280" — a load with no reps attached.
_BARE_LOAD = re.compile(r"^\d+(?:\.\d+)?$")


def _split_marker(token: str) -> tuple:
    """('230x4', 'DELOAD') for 'DELOAD 230x4'; ('270', '') for '270'."""
    m = _MARKER.match(token.strip())
    return (m.group(2).strip(), m.group(1).upper()) if m else (token.strip(), "")


def program_week(db: Session, user_id: str, on_date: date) -> Optional[int]:
    """1-based week index of `on_date` within the active program, or None."""
    row = db.execute(text("""
        SELECT start_date FROM fitness_program
        WHERE user_id = :uid AND is_active = true
        LIMIT 1
    """), {"uid": user_id}).fetchone()
    if not row or not row.start_date:
        return None
    start = row.start_date
    if isinstance(start, str):
        try:
            start = date.fromisoformat(start[:10])
        except ValueError:
            logger.warning("program_week: unparseable start_date %r", start)
            return None
    elif hasattr(start, "date"):
        start = start.date()
    delta = (on_date - start).days
    if delta < 0:
        return None
    return delta // 7 + 1


def _row_for_week(notes: str, label: str, week: int) -> Optional[str]:
    """Pull `Wk<week>`'s entry out of the `LABEL: Wk1 … · Wk2 …` line."""
    for line in (notes or "").splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith(f"{label}:"):
            continue
        body = stripped.split(":", 1)[1]
        for token in _SEPARATORS.split(body):
            m = _WEEK_TOKEN.match(token.strip())
            if m and int(m.group(1)) == week:
                return m.group(2).strip()
    return None


def prescription_for_week(notes: str, week: Optional[int]) -> Dict[str, Optional[str]]:
    """{'top': '270x2', 'backoff': '230'} for `week`, entries absent when not listed."""
    if not week:
        return {}
    out = {}
    for key, label in (("top", "TOP"), ("backoff", "BACKOFF")):
        value = _row_for_week(notes, label, week)
        if value:
            out[key] = value
    return out


def describe_exercise(ex: Dict[str, Any], week: Optional[int] = None) -> str:
    """One line for a template exercise: the week's loads when it carries a
    structured `set_plan` (Part A1/A2) or the notes have a loading table,
    otherwise the plain sets×reps prescription.

    `set_plan` takes priority — it's the structured source of truth the
    engine itself resolves from; the notes-table parser is the fallback for
    exercises that predate it. No hold-rule gating here (no db/last-top-set
    to check against): this describes what the calendar week prescribes, the
    same as a passive readout in the brief — the actual session is where the
    advance rule decides whether that's really what gets lifted.
    """
    from app.services.set_plan import is_plan_driven, resolve_set_plan, describe_resolved

    name = ex.get("name") or "Exercise"
    if is_plan_driven(ex) and week:
        resolved = resolve_set_plan(ex, week, last_top_set=None)
        if resolved["sets"]:
            line = f"{name} — {describe_resolved(name, resolved).split(': ', 1)[1]}"
            label = ((ex["set_plan"]["weeks"].get(str(resolved["effective_week"])) or {}).get("label"))
            return f"{line} [{label}]" if label else line

    sets = ex.get("sets")
    reps = ex.get("reps")
    notes = ex.get("notes") or ""
    p = prescription_for_week(notes, week)

    if p.get("top"):
        top, marker = _split_marker(p["top"])
        parts = [f"top set {top}"]
        if p.get("backoff"):
            backoff, _ = _split_marker(p["backoff"])
            if _BARE_LOAD.match(backoff):
                # A bare load: pair it with the sets and the backoff rep range
                # from the notes (narrower than the exercise's combined `reps`).
                backoffs = max(1, int(sets or 1) - 1)
                m = _BACKOFF_REPS.search(notes)
                backoff_reps = m.group(1).replace(" ", "") if m else reps
                parts.append(f"{backoffs}×{backoff_reps} @{backoff}" if backoff_reps
                             else f"backoff {backoff}")
            else:
                # Deload rows already spell out load×reps×sets ("210x5x2").
                parts.append(f"backoff {backoff}")
        line = f"{name} — {', '.join(parts)}"
        return f"{line} [{marker}]" if marker else line

    if sets and reps:
        return f"{name} {sets}×{reps}"
    return name


def describe_template(template: Dict[str, Any], week: Optional[int] = None) -> str:
    """Short label for a session: a single-lift AM day names the lift and its
    loads; a multi-exercise PM day names the session and its size."""
    name = template.get("name") or "Workout"
    exercises: List[Dict[str, Any]] = template.get("exercises") or []
    if len(exercises) == 1:
        return f"{name} — {describe_exercise(exercises[0], week)}"
    if exercises:
        return f"{name} ({len(exercises)} exercises)"
    return name


def describe_day(templates: List[Dict[str, Any]], week: Optional[int] = None) -> str:
    """The whole day, in plan order: 'AM …  ·  PM …'."""
    return "  ·  ".join(describe_template(t, week) for t in templates)
