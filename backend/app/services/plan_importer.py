"""
Plan Importer
=============
Turns a free-form training/nutrition plan document into structured fitness data
and applies it to the DB the same way a manual rebuild would:

  - one fitness_program (new, activated; the old active one is kept as history)
  - N fitness_phase rows (block periodization), dates computed deterministically
  - the weekly workout templates copied under each phase (exercises JSON)
  - per-phase nutrition (incl. training-vs-rest-day carb cycling)
  - a structured nutrition_guide stored on the program (drives the Nutrition tab)

Parsing is done by the in-house Qwen model (enable_thinking=False, like the
other background JSON tasks). Nothing is written during parse — the route layer
shows the result as a preview and only calls apply_imported_plan() on confirm.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

VALID_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_DAY_INDEX = {d: i for i, d in enumerate(VALID_DAYS)}


# ──────────────────────────────────────────────────────────────────────────
# LLM extraction
# ──────────────────────────────────────────────────────────────────────────

_SCHEMA_PROMPT = """You convert a fitness/training plan document into STRICT JSON.

Output ONLY a single JSON object — no markdown fences, no commentary. Shape:

{
  "program": {
    "name": "string (the plan title)",
    "goal": "recomp|hypertrophy|strength|cut|maintenance",
    "duration_weeks": 8,
    "notes": "any program-wide guidance not captured elsewhere: priorities, injury/knee rules, cardio plan, guardrails. Plain prose."
  },
  "phases": [
    {
      "name": "Accumulate (Weeks 1-3)",
      "goal": "recomp",
      "order_index": 0,
      "duration_weeks": 3,
      "deload_week": null,
      "notes": "what changes in this block (RPE, volume, load)",
      "nutrition": {
        "calories_target": 2630, "protein_target": 240,
        "carbs_target": 290, "fat_target": 70,
        "calories_training_day": 2800, "calories_rest_day": 2400,
        "carbs_training_day": 290, "carbs_rest_day": 150,
        "fat_training_day": 70, "fat_rest_day": 95,
        "training_days_per_week": 4
      }
    }
  ],
  "templates": [
    {
      "name": "Upper A — Heavy Press",
      "scheduled_days": ["monday"],
      "order_in_phase": 0,
      "notes": "short day summary",
      "exercises": [
        {"name": "Barbell Bench Press", "sets": 4, "reps": "5",
         "rpe_target": 7, "rest_seconds": 180, "is_per_side": false,
         "metric_type": "reps", "notes": "home option / cues"}
      ]
    }
  ],
  "nutrition_guide": {
    "goal": "one-line goal",
    "how_it_works": "one or two sentences",
    "weekly_average": "e.g. ~2,630 cal/day — around maintenance",
    "macros": [
      {"label": "Calories", "training": "~2,800", "rest": "~2,400"},
      {"label": "Protein", "training": "~240g", "rest": "~240g"}
    ],
    "rules": [{"title": "short rule", "body": "explanation"}],
    "carb_timing": {"days": "Mon/Thu", "pre": "oats or rice", "post": "rice-heavy meal", "note": "why"},
    "staples": {"carbs": "rice, oats", "protein": "chicken, beef", "watch_out": "caveat"},
    "self_check": ["question 1", "question 2"]
  }
}

Rules:
- "templates" is the WEEKLY set of workouts (one entry per training day). Do NOT
  repeat them per phase — the same workouts run across every phase.
- scheduled_days must be lowercase day names from: monday..sunday.
- reps is always a STRING ("5", "8-10", "12"). sets is an integer.
- Set is_per_side=true for per-leg / per-arm movements. metric_type is "reps"
  unless the exercise is a timed hold, then "time_seconds".
- Put any "home option" / substitution and coaching cue into the exercise "notes".
- If the document carb-cycles, fill the *_training_day / *_rest_day fields; the
  base calories_target should be the weekly average.
- Omit nutrition_guide ONLY if the document has no nutrition content.
- Do NOT invent calendar dates. Dates are computed downstream from duration_weeks.
"""


def _extract_json(content: str) -> Dict[str, Any]:
    """Pull a JSON object out of an LLM response that may include fences/prose."""
    s = content.strip()
    if s.startswith("```"):
        # strip ```json ... ``` fences
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model output")
    return json.loads(s[start : end + 1])


async def parse_plan_document(source_text: str) -> Dict[str, Any]:
    """Call the background LLM to extract the structured plan. Read-only."""
    if not source_text or not source_text.strip():
        raise ValueError("Empty document")

    base_url = settings.bg_llm_primary_url
    model = settings.bg_llm_primary_model
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SCHEMA_PROMPT},
            {"role": "user", "content": f"Plan document:\n\n{source_text.strip()[:20000]}"},
        ],
        "temperature": 0.1,
        "stream": False,
        "max_tokens": 8000,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    async with httpx.AsyncClient(timeout=settings.bg_llm_request_timeout) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key or 'dummy'}",
                     "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

    parsed = _extract_json(content)
    return _normalize(parsed)


# ──────────────────────────────────────────────────────────────────────────
# Normalization / validation (defensive — the LLM output is untrusted)
# ──────────────────────────────────────────────────────────────────────────

def _as_int(v, default=None):
    try:
        if v is None or v == "":
            return default
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


def _normalize_exercise(ex: Dict[str, Any]) -> Dict[str, Any]:
    reps = ex.get("reps")
    reps = str(reps) if reps is not None else ""
    low = _as_int(ex.get("rep_range_low"))
    high = _as_int(ex.get("rep_range_high"))
    if low is None and reps.isdigit():
        low = high = int(reps)
    rpe = ex.get("rpe_target")
    try:
        rpe = float(rpe) if rpe not in (None, "") else None
    except (TypeError, ValueError):
        rpe = None
    return {
        "name": str(ex.get("name", "")).strip() or "Exercise",
        "reps": reps,
        "sets": _as_int(ex.get("sets"), 3),
        "notes": str(ex.get("notes", "") or ""),
        "rpe_target": rpe,
        "is_per_side": bool(ex.get("is_per_side", False)),
        "metric_type": ex.get("metric_type") if ex.get("metric_type") in ("reps", "time_seconds") else "reps",
        "rest_seconds": _as_int(ex.get("rest_seconds")),
        "rep_range_low": low,
        "set_technique": ex.get("set_technique"),
        "rep_range_high": high,
        "superset_group": ex.get("superset_group"),
        "progression_rule": ex.get("progression_rule") or "LINEAR",
    }


def _normalize(parsed: Dict[str, Any]) -> Dict[str, Any]:
    prog = parsed.get("program") or {}
    program = {
        "name": str(prog.get("name") or "Imported Plan").strip(),
        "goal": str(prog.get("goal") or "recomp").strip().lower(),
        "duration_weeks": _as_int(prog.get("duration_weeks")),
        "notes": str(prog.get("notes") or ""),
    }

    phases: List[Dict[str, Any]] = []
    for i, ph in enumerate(parsed.get("phases") or []):
        nut = ph.get("nutrition") or {}
        phases.append({
            "name": str(ph.get("name") or f"Phase {i + 1}").strip(),
            "goal": str(ph.get("goal") or program["goal"]).strip().lower(),
            "order_index": _as_int(ph.get("order_index"), i),
            "duration_weeks": _as_int(ph.get("duration_weeks"), 4) or 4,
            "deload_week": _as_int(ph.get("deload_week")),
            "notes": str(ph.get("notes") or ""),
            "nutrition": {k: _as_int(nut.get(k)) for k in (
                "calories_target", "protein_target", "carbs_target", "fat_target",
                "calories_training_day", "calories_rest_day",
                "carbs_training_day", "carbs_rest_day",
                "fat_training_day", "fat_rest_day", "training_days_per_week",
            )},
        })
    phases.sort(key=lambda p: p["order_index"])
    for i, p in enumerate(phases):
        p["order_index"] = i

    templates: List[Dict[str, Any]] = []
    for i, t in enumerate(parsed.get("templates") or []):
        days = [str(d).strip().lower() for d in (t.get("scheduled_days") or []) if str(d).strip().lower() in VALID_DAYS]
        templates.append({
            "name": str(t.get("name") or f"Day {i + 1}").strip(),
            "scheduled_days": days,
            "order_in_phase": _as_int(t.get("order_in_phase"), i),
            "notes": str(t.get("notes") or ""),
            "exercises": [_normalize_exercise(e) for e in (t.get("exercises") or []) if e.get("name")],
        })
    # order templates by first scheduled weekday, then declared order
    templates.sort(key=lambda t: (
        min((_DAY_INDEX[d] for d in t["scheduled_days"]), default=99), t["order_in_phase"]))
    for i, t in enumerate(templates):
        t["order_in_phase"] = i

    guide = parsed.get("nutrition_guide")
    if guide and not isinstance(guide, dict):
        guide = None

    return {"program": program, "phases": phases, "templates": templates, "nutrition_guide": guide}


def validate_parsed(parsed: Dict[str, Any]) -> List[str]:
    """Return human-readable warnings (not hard errors) for the preview screen."""
    warnings: List[str] = []
    if not parsed.get("phases"):
        warnings.append("No training phases were detected.")
    if not parsed.get("templates"):
        warnings.append("No workouts/templates were detected.")
    for t in parsed.get("templates", []):
        if not t["scheduled_days"]:
            warnings.append(f"Workout “{t['name']}” has no scheduled day.")
        if not t["exercises"]:
            warnings.append(f"Workout “{t['name']}” has no exercises.")
    if not parsed.get("nutrition_guide"):
        warnings.append("No nutrition guide content was detected (the Nutrition tab will keep its current content).")
    return warnings


# ──────────────────────────────────────────────────────────────────────────
# Apply (atomic write)
# ──────────────────────────────────────────────────────────────────────────

def _next_monday(from_date: date) -> date:
    """Upcoming Monday; if today is Monday, use today."""
    return from_date + timedelta(days=(0 - from_date.weekday()) % 7)


def apply_imported_plan(db: Session, user_id: str, parsed: Dict[str, Any],
                        source_text: str = "", start_date: Optional[str] = None) -> Dict[str, Any]:
    """Create + activate a new program from the parsed plan. Atomic."""
    program = parsed["program"]
    phases = parsed["phases"]
    templates = parsed["templates"]
    guide = parsed.get("nutrition_guide")

    if not phases:
        raise ValueError("Cannot apply a plan with no phases.")
    if not templates:
        raise ValueError("Cannot apply a plan with no workouts.")

    # Anchor start date
    anchor: Optional[date] = None
    if start_date:
        try:
            anchor = date.fromisoformat(start_date)
        except ValueError:
            anchor = None
    if anchor is None:
        anchor = _next_monday(local_now().date())

    total_weeks = sum(p["duration_weeks"] for p in phases) or program.get("duration_weeks") or 8
    program_id = str(uuid.uuid4())
    program_end = anchor + timedelta(weeks=total_weeks) - timedelta(days=1)

    try:
        # 1) deactivate any currently-active program (kept as history)
        db.execute(text(
            "UPDATE fitness_program SET is_active=false, updated_at=now() "
            "WHERE user_id=:uid AND is_active=true"), {"uid": user_id})

        # 2) new active program
        db.execute(text("""
            INSERT INTO fitness_program (id, user_id, name, goal, start_date, end_date,
                                         is_active, notes, plan_markdown, nutrition_guide,
                                         created_at, updated_at)
            VALUES (:id, :uid, :name, :goal, :start, :end, true, :notes, :md, :guide, now(), now())
        """), {
            "id": program_id, "uid": user_id, "name": program["name"], "goal": program["goal"],
            "start": anchor, "end": program_end, "notes": program["notes"],
            "md": source_text or "", "guide": json.dumps(guide) if guide else None,
        })

        # 3) phases (dates sequenced from the anchor) + their template copies
        cursor = anchor
        applied_phases = []
        for idx, ph in enumerate(phases):
            p_start = cursor
            p_end = p_start + timedelta(weeks=ph["duration_weeks"]) - timedelta(days=1)
            cursor = p_end + timedelta(days=1)
            phase_id = str(uuid.uuid4())
            nut = ph["nutrition"]
            db.execute(text("""
                INSERT INTO fitness_phase (id, user_id, program_id, name, goal, order_index,
                    duration_weeks, start_date, end_date, status, deload_week, notes,
                    calories_target, protein_target, carbs_target, fat_target,
                    training_days_per_week, calories_training_day, calories_rest_day,
                    carbs_training_day, carbs_rest_day, fat_training_day, fat_rest_day,
                    created_at, updated_at)
                VALUES (:id, :uid, :pid, :name, :goal, :oi, :dw, :start, :end,
                    :status, :deload, :notes,
                    :cal, :pro, :carb, :fat, :tdpw, :cal_t, :cal_r, :carb_t, :carb_r,
                    :fat_t, :fat_r, now(), now())
            """), {
                "id": phase_id, "uid": user_id, "pid": program_id, "name": ph["name"],
                "goal": ph["goal"], "oi": idx, "dw": ph["duration_weeks"],
                "start": p_start, "end": p_end,
                "status": "active" if idx == 0 else "planned",
                "deload": ph["deload_week"], "notes": ph["notes"],
                "cal": nut.get("calories_target"), "pro": nut.get("protein_target"),
                "carb": nut.get("carbs_target"), "fat": nut.get("fat_target"),
                "tdpw": nut.get("training_days_per_week"),
                "cal_t": nut.get("calories_training_day"), "cal_r": nut.get("calories_rest_day"),
                "carb_t": nut.get("carbs_training_day"), "carb_r": nut.get("carbs_rest_day"),
                "fat_t": nut.get("fat_training_day"), "fat_r": nut.get("fat_rest_day"),
            })
            # the weekly workouts run in every phase → copy each template under it
            for t in templates:
                db.execute(text("""
                    INSERT INTO fitness_template (id, user_id, phase_id, name, scheduled_days,
                        exercises, order_in_phase, notes, created_at, updated_at)
                    VALUES (:id, :uid, :pid, :name, :days, :ex, :oi, :notes, now(), now())
                """), {
                    "id": str(uuid.uuid4()), "uid": user_id, "pid": phase_id, "name": t["name"],
                    "days": json.dumps(t["scheduled_days"]), "ex": json.dumps(t["exercises"]),
                    "oi": t["order_in_phase"], "notes": t["notes"],
                })
            applied_phases.append({
                "name": ph["name"], "start": p_start.isoformat(), "end": p_end.isoformat(),
                "duration_weeks": ph["duration_weeks"], "status": "active" if idx == 0 else "planned",
            })

        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "program_id": program_id,
        "name": program["name"],
        "start_date": anchor.isoformat(),
        "end_date": program_end.isoformat(),
        "phases": applied_phases,
        "workouts": [{"name": t["name"], "days": t["scheduled_days"],
                      "exercises": len(t["exercises"])} for t in templates],
        "nutrition_guide_updated": bool(guide),
    }
