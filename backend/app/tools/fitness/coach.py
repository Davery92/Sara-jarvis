"""Fitness Coach tools: narrow reads, and writes that are the user's own.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 23 / §8.3.

Every tool here delegates to the same services the API and the deterministic
state use. None of them does arithmetic. That is the point of the step: Sara
answering "am I losing weight?" and the Overview showing a weekly rate must
be the same number, and the only way to guarantee that is for there to be one
implementation.

Four conventions these follow, and what each prevents:

1. **`user_id` is never a model-visible parameter.** It is injected by the
   registry. A tool whose schema accepted an owner id would let a model
   address another athlete's data by naming it, and the model has no business
   knowing an id in the first place.
2. **Reads cannot write.** The read tools call only resolvers and loaders.
   `is_mutating_tool` classifies by name, so these are named `_get`/`_search`
   with no mutating token, and a test asserts the classification.
3. **Writes require a user turn.** `requires_user_origin = True` on every
   write, so the autonomous loop cannot log a measurement or decide a
   recommendation on its own. Deciding a coaching change is David's.
4. **A missing field is never invented.** The check-in write sends exactly
   the fields given; the model may not fill in a weight it did not hear.

Consolidated on purpose. `tool_retrieval.MAX_TOOLS_PER_CALL = 35` caps the
per-turn menu, and one `fitness_analytics_get` with a `section` parameter
costs one slot where seven per-section tools would cost seven — slots that
would come out of the rest of Sara's capability on a fitness turn.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

#: Hard page cap for every list this module returns. A model asking for
#: "all my measurements" would otherwise pull a year of rows into the turn's
#: context and push the conversation out of it.
MAX_ROWS = 100

#: The longest window a single analytics call may ask for. A multi-year
#: window is the request shape that takes a shared database down, and no
#: coaching question needs one.
MAX_SPAN_DAYS = 400

ANALYTICS_SECTIONS = (
    "weight", "nutrition", "sleep", "training", "recovery", "pain",
    "measurements", "quality",
)


def _session():
    from app.db.session import SessionLocal
    return SessionLocal()


def _parse_date(value: Any, field: str) -> Optional[date]:
    """A date, or a clear error. Never a guess.

    A model writing "last Tuesday" into a date field is a real occurrence,
    and silently coercing it to today would attribute data to the wrong day.
    """
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        raise ValueError(
            f"{field} must be an ISO date (YYYY-MM-DD); got {value!r}"
        )


def _athlete_today(db, user_id: str) -> date:
    from app.services.fitness.consumers import athlete_local_today
    return athlete_local_today(db, user_id)


def _bounded_window(
    db, user_id: str, start: Any, end: Any, *, default_span: int = 7,
) -> tuple[date, date]:
    """A validated half-open window, athlete-local.

    `end` is exclusive everywhere in this subsystem, and the default end is
    the athlete's today — so a default window never includes the partial
    current day.
    """
    today = _athlete_today(db, user_id)
    parsed_end = _parse_date(end, "end_date") or today
    parsed_start = _parse_date(start, "start_date") or (
        parsed_end - timedelta(days=default_span)
    )
    if parsed_end <= parsed_start:
        raise ValueError(
            "end_date is exclusive and must be after start_date"
        )
    if (parsed_end - parsed_start).days > MAX_SPAN_DAYS:
        raise ValueError(
            f"that window is {(parsed_end - parsed_start).days} days; "
            f"{MAX_SPAN_DAYS} is the maximum"
        )
    return parsed_start, parsed_end


# ─────────────────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────────────────

class FitnessProfileGetTool(BaseTool):
    """Who the athlete is, what they are training for, and what hurts."""

    @property
    def name(self) -> str:
        return "fitness_profile_get"

    @property
    def description(self) -> str:
        return (
            "Get the athlete's profile, their current goal and its target "
            "rate, today's nutrition/sleep targets, and any limitations they "
            "have reported (sore shoulder, excluded exercises). Use this "
            "before suggesting training or food so the suggestion fits the "
            "goal and works around what hurts. Read only."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "on_date": {
                    "type": "string",
                    "description": (
                        "ISO date (YYYY-MM-DD) to resolve goals and targets "
                        "for. Defaults to the athlete's today. Use a past "
                        "date to answer what the targets WERE then — they "
                        "may differ from today's."
                    ),
                },
            },
            "additionalProperties": False,
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        db = _session()
        try:
            on_date = _parse_date(kwargs.get("on_date"), "on_date") \
                or _athlete_today(db, user_id)

            from app.services.fitness.profile import (
                get_athlete_profile, get_goals, get_limitations,
            )
            from app.services.fitness.targets import resolve_day_type, resolve_targets

            goals = get_goals(db, user_id, on_date)
            limitations = get_limitations(db, user_id, on_date)
            targets = resolve_targets(db, user_id, on_date)
            day_type = resolve_day_type(db, user_id, on_date)

            try:
                profile = get_athlete_profile(db, user_id)
                profile_payload = {
                    "height_cm": profile.height_cm,
                    "training_level": profile.training_level.value,
                    "training_experience_years": profile.training_experience_years,
                    "timezone": profile.timezone,
                    "available_days": profile.available_days,
                    "preferred_duration_minutes": profile.preferred_duration_minutes,
                    "equipment": profile.equipment,
                    "dietary_restrictions": profile.dietary_restrictions,
                    "dietary_preferences": profile.dietary_preferences,
                    "excluded_exercise_ids": profile.excluded_exercise_ids,
                    "coaching_style": profile.coaching_style.value,
                }
            except Exception as exc:
                logger.debug("profile unavailable: %s", exc)
                profile_payload = None

            primary = next((g for g in goals if g.is_primary), None)
            data = {
                "on_date": on_date.isoformat(),
                "day_type": day_type.value,
                "profile": profile_payload,
                "primary_goal": {
                    "kind": primary.kind.value,
                    "rate_basis": primary.rate_basis.value,
                    "target_rate_kg_week": primary.target_rate_kg_week,
                    "target_rate_percent_week": primary.target_rate_percent_week,
                    "target_weight_kg": primary.target_weight_kg,
                    "valid_from": primary.valid_from.isoformat(),
                    "rationale": primary.rationale,
                } if primary else None,
                "other_goals": [
                    {"kind": g.kind.value, "priority": g.priority}
                    for g in goals if not g.is_primary
                ],
                "targets": {
                    "calories": targets.values.calories,
                    "protein_g": targets.values.protein_g,
                    "carbs_g": targets.values.carbs_g,
                    "fat_g": targets.values.fat_g,
                    "sleep_hours": targets.values.sleep_hours,
                    "steps": targets.values.steps,
                    # Said out loud: legacy provenance means these came from a
                    # mutable column and cannot answer what the target was
                    # last month.
                    "provenance": targets.provenance.value,
                    "history_unknown": targets.history_unknown,
                },
                "limitations": [
                    {
                        "area": limitation.area,
                        "severity_flag": limitation.severity_flag,
                        "description": limitation.description,
                        "excluded_exercise_ids": limitation.excluded_exercise_ids,
                        "effective_from": limitation.effective_from.isoformat(),
                    }
                    for limitation in limitations
                ],
            }

            parts = []
            if primary:
                parts.append(f"goal: {primary.kind.value}")
            if targets.values.calories:
                parts.append(f"{targets.values.calories} kcal today")
            if limitations:
                parts.append(
                    f"working around {len(limitations)} reported limitation(s)"
                )
            return ToolResult(
                success=True, data=data,
                message="; ".join(parts) or "no goal or targets recorded",
            )
        except ValueError as exc:
            return ToolResult(success=False, message=str(exc))
        except Exception as exc:
            logger.warning(
                "fitness_profile_get failed (%s): %s", type(exc).__name__, exc,
            )
            return ToolResult(
                success=False,
                message=f"Could not read the athlete profile: {exc}",
            )
        finally:
            db.close()


class FitnessAnalyticsGetTool(BaseTool):
    """One section of the deterministic analytics, over a bounded window."""

    @property
    def name(self) -> str:
        return "fitness_analytics_get"

    @property
    def description(self) -> str:
        return (
            "Get computed fitness metrics for one area over a date range: "
            "weight (latest, means, weekly rate), nutrition (intake means, "
            "adherence, logged-day counts), sleep, training (sessions, "
            "volume, adherence), recovery (energy/soreness/stress means), "
            "pain (reported patterns by session) or quality (how much data "
            "there is). Every metric states how many days it is built from, "
            "and a metric with no value says WHY instead of returning zero. "
            "Use this instead of computing anything yourself. Read only."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": list(ANALYTICS_SECTIONS),
                    "description": "Which area of metrics to return.",
                },
                "start_date": {
                    "type": "string",
                    "description": "ISO date. Defaults to 7 days before end_date.",
                },
                "end_date": {
                    "type": "string",
                    "description": (
                        "ISO date, EXCLUSIVE. Defaults to the athlete's "
                        "today, so the partial current day is not averaged in."
                    ),
                },
                "exercise_id": {
                    "type": "string",
                    "description": (
                        "Optional canonical exercise id, for the training "
                        "section's strength trend. Use fitness_analytics_get "
                        "with section=training first to see which exercises "
                        "have enough data."
                    ),
                },
            },
            "required": ["section"],
            "additionalProperties": False,
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        db = _session()
        try:
            section = str(kwargs.get("section") or "").strip().lower()
            if section not in ANALYTICS_SECTIONS:
                return ToolResult(
                    success=False,
                    message=(
                        f"{section!r} is not a section. Choose one of: "
                        + ", ".join(ANALYTICS_SECTIONS)
                    ),
                )
            start, end = _bounded_window(
                db, user_id, kwargs.get("start_date"), kwargs.get("end_date"),
            )

            from app.schemas.fitness_coach import StateSection
            from app.services.fitness.state import build_fitness_state

            state = build_fitness_state(
                db, user_id, period_end=end, span=(end - start).days,
                sections=[StateSection(section)] if section != "quality" else None,
                fresh=False, redis_client=_cache(),
            )

            if section == "quality":
                data: Dict[str, Any] = {
                    "period": {"start": start.isoformat(), "end": end.isoformat()},
                    "quality": state.quality.model_dump(mode="json"),
                    "freshness": state.freshness.value,
                    "degraded_dependencies": state.degraded_dependencies,
                }
                message = (
                    f"{state.quality.observed_weight_days or 0} weigh-ins, "
                    f"{state.quality.nutrition_complete_days} fully logged "
                    f"food days, {state.quality.sleep_nights or 0} nights"
                )
            else:
                group = state.sections.get(StateSection(section))
                if group is None:
                    return ToolResult(
                        success=False,
                        message=(
                            f"the {section} section could not be computed; "
                            f"this is a fault on our side, not an empty log"
                        ),
                    )
                metrics = {
                    key: metric.model_dump(mode="json")
                    for key, metric in group.metrics.items()
                }
                data = {
                    "period": {"start": start.isoformat(), "end": end.isoformat()},
                    "section": section,
                    "metrics": metrics,
                    "items": group.items[:MAX_ROWS],
                    "limitations": group.limitations,
                    "freshness": state.freshness.value,
                }
                if section == "training" and kwargs.get("exercise_id"):
                    data["strength_trend"] = _strength_trend(
                        db, user_id, str(kwargs["exercise_id"]), start, end,
                    )
                available = sum(
                    1 for m in group.metrics.values() if m.value is not None
                )
                message = (
                    f"{section}: {available} of {len(group.metrics)} metrics "
                    f"available for {start} to {end}"
                )

            if state.freshness.value == "degraded":
                # Said in the message, not only in the payload: a model that
                # skims will otherwise read a partial state as the whole one.
                message += (
                    " — WARNING: some data could not be read, so this is "
                    "incomplete rather than all there is"
                )
            return ToolResult(success=True, data=data, message=message)
        except ValueError as exc:
            return ToolResult(success=False, message=str(exc))
        except Exception as exc:
            logger.warning(
                "fitness_analytics_get failed (%s): %s", type(exc).__name__, exc,
            )
            return ToolResult(
                success=False, message=f"Could not compute that: {exc}",
            )
        finally:
            db.close()


def _cache():
    try:
        from app.core.redis import get_redis_sync
        return get_redis_sync()
    except Exception:
        return None


def _strength_trend(db, user_id: str, exercise_id: str, start: date, end: date):
    from app.services.fitness import analytics
    from app.services.fitness.consumers import athlete_timezone
    from app.services.fitness.data_access import load_sets
    from app.services.fitness.exercises import effective_load_for, get_exercise

    ref = get_exercise(db, user_id, exercise_id)
    if ref is None:
        return {"unavailable_reason": "no such exercise for this athlete"}
    rows = load_sets(
        db, user_id, start, end,
        timezone_name=athlete_timezone(db, user_id),
        exercise_library_id=exercise_id,
    )
    records = []
    for row in rows:
        load, _reason = effective_load_for(ref, row.load)
        records.append(analytics.SetRecord(
            set_id=row.id,
            day=row.session_date or (row.logged_at.date() if row.logged_at else start),
            exercise_id=exercise_id, exercise_name=ref.name,
            occurrence_id=row.exercise_performance_id,
            session_key=row.active_session_id or row.session_id,
            reps=row.reps, load=load, load_unit=row.load_unit,
            set_kind=row.set_kind, set_role=row.set_role,
            counts_toward_target=row.counts_toward_target,
            voided=row.voided_at is not None, skipped=row.skipped,
            load_comparable=ref.load_is_comparable,
        ))
    trend = analytics.strength_trend(records, end, exercise_id=exercise_id)
    return {
        "exercise": ref.name,
        "load_convention": ref.load_convention,
        "comparable": ref.load_is_comparable,
        "metrics": {k: v.model_dump(mode="json") for k, v in trend.items()},
    }


class FitnessMeasurementsGetTool(BaseTool):
    """Tape measurements, with their protocol and what is comparable."""

    @property
    def name(self) -> str:
        return "fitness_measurements_get"

    @property
    def description(self) -> str:
        return (
            "Get the athlete's tape measurements (waist, arm, chest and any "
            "custom types they defined), with the protocol each was taken "
            "under. A change figure is only given when two readings are "
            "actually comparable — same type, site, side, protocol and unit. "
            "Read only."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "type_code": {
                    "type": "string",
                    "description": (
                        "Measurement type code, e.g. waist_circumference. "
                        "Omit to list what types exist."
                    ),
                },
                "start_date": {"type": "string", "description": "ISO date."},
                "end_date": {
                    "type": "string",
                    "description": "ISO date, exclusive.",
                },
                "limit": {
                    "type": "integer", "minimum": 1, "maximum": MAX_ROWS,
                    "description": f"Readings to return, at most {MAX_ROWS}.",
                },
            },
            "additionalProperties": False,
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        db = _session()
        try:
            from app.services.fitness.observations import (
                list_measurement_types, list_measurements, measurement_change,
            )

            type_code = kwargs.get("type_code") or None
            limit = min(int(kwargs.get("limit") or 50), MAX_ROWS)
            start = _parse_date(kwargs.get("start_date"), "start_date")
            end = _parse_date(kwargs.get("end_date"), "end_date")

            types = list_measurement_types(db, user_id)
            if not type_code:
                return ToolResult(
                    success=True,
                    data={"types": [
                        {
                            "code": t.code, "label": t.label,
                            "unit": t.canonical_unit.value,
                            "allows_side": t.allows_side,
                            "protocol_guidance": t.protocol_guidance,
                            "custom": t.owner_user_id is not None,
                        }
                        for t in types
                    ]},
                    message=f"{len(types)} measurement types available",
                )

            readings = list_measurements(
                db, user_id, type_code=type_code,
                start_date=start, end_date=end, limit=limit,
            )
            change = measurement_change(db, user_id, type_code)
            return ToolResult(
                success=True,
                data={
                    "type_code": type_code,
                    "readings": [
                        {
                            "value": r.value, "unit": r.unit.value,
                            "logical_date": r.logical_date.isoformat(),
                            "site": r.site, "side": r.side.value,
                            "protocol": r.protocol,
                            "superseded": r.superseded_by_id is not None,
                        }
                        for r in readings
                    ],
                    "latest_change": change.model_dump(mode="json"),
                },
                message=(
                    f"{len(readings)} {type_code} reading(s); "
                    + (
                        f"latest change {change.value} {change.unit.value}"
                        if change.value is not None
                        else f"no comparable change ({change.unavailable_reason.value if change.unavailable_reason else 'unknown'})"
                    )
                ),
            )
        except LookupError:
            return ToolResult(
                success=False, message="No such measurement type for this athlete.",
            )
        except ValueError as exc:
            return ToolResult(success=False, message=str(exc))
        except Exception as exc:
            logger.warning(
                "fitness_measurements_get failed (%s): %s",
                type(exc).__name__, exc,
            )
            return ToolResult(
                success=False, message=f"Could not read measurements: {exc}",
            )
        finally:
            db.close()


class FitnessCoachReviewGetTool(BaseTool):
    """An existing review. Never generates one."""

    @property
    def name(self) -> str:
        return "fitness_coach_review_get"

    @property
    def description(self) -> str:
        return (
            "Read an existing weekly coach review: its summary, what it "
            "noticed, what it could not tell, and the recommendations it "
            "proposed with their decision status. This does NOT generate a "
            "review — use fitness_coach_review_request for that, and only "
            "when the athlete asks. Read only."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "review_id": {
                    "type": "string",
                    "description": "A specific review. Omit for the latest.",
                },
                "period_end": {
                    "type": "string",
                    "description": (
                        "ISO date (exclusive) of the period's end, to find "
                        "the review covering a particular week."
                    ),
                },
            },
            "additionalProperties": False,
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        db = _session()
        try:
            from app.services.fitness.review_audit import get_review, list_reviews

            review_id = kwargs.get("review_id")
            if not review_id:
                period_end = _parse_date(kwargs.get("period_end"), "period_end")
                reviews = list_reviews(db, user_id, limit=20)
                if period_end:
                    reviews = [r for r in reviews if r.period.end == period_end]
                if not reviews:
                    return ToolResult(
                        success=True, data={"review": None},
                        message=(
                            "No review exists for that period. Nothing has "
                            "been generated — ask the athlete whether they "
                            "want one."
                        ),
                    )
                review_id = reviews[0].id

            detail = get_review(db, user_id, review_id)
            data = {
                "id": detail.id,
                "period": {
                    "start": detail.period.start.isoformat(),
                    "end": detail.period.end.isoformat(),
                },
                "status": detail.status.value,
                "summary": detail.summary,
                "model_actual": detail.model_actual,
                "error_category": (
                    detail.error_category.value if detail.error_category else None
                ),
                "output": detail.output.model_dump(mode="json")
                if detail.output else None,
                "recommendations": [
                    {
                        "id": rec.id, "category": rec.category.value,
                        "title": rec.title, "rationale": rec.rationale,
                        "confidence": rec.confidence.value,
                        "confidence_basis": rec.confidence_basis,
                        "action": rec.action.value,
                        "decision_status": rec.decision_status.value,
                        "expires_at": (
                            rec.expires_at.isoformat() if rec.expires_at else None
                        ),
                    }
                    for rec in detail.recommendations
                ],
            }
            open_count = sum(
                1 for rec in detail.recommendations
                if rec.decision_status.value == "proposed"
            )
            return ToolResult(
                success=True, data=data,
                message=(
                    f"review {detail.period.start} to {detail.period.end}: "
                    f"{detail.status.value}, {open_count} proposal(s) awaiting "
                    f"a decision"
                ),
            )
        except LookupError:
            return ToolResult(success=False, message="No such review.")
        except ValueError as exc:
            return ToolResult(success=False, message=str(exc))
        except Exception as exc:
            logger.warning(
                "fitness_coach_review_get failed (%s): %s",
                type(exc).__name__, exc,
            )
            return ToolResult(
                success=False, message=f"Could not read the review: {exc}",
            )
        finally:
            db.close()


# ─────────────────────────────────────────────────────────────────────────
# Writes — all user-origin
# ─────────────────────────────────────────────────────────────────────────

class FitnessCheckinUpdateTool(BaseTool):
    """Record what the athlete said about their day. Only what they said."""

    requires_user_origin = True

    @property
    def name(self) -> str:
        return "fitness_checkin_update"

    @property
    def description(self) -> str:
        return (
            "Record the athlete's own daily check-in answers: energy, "
            "fatigue, soreness, stress, motivation (all 1-10), sleep quality, "
            "bedtime/wake times, HRV, resting heart rate, sleep hours, body "
            "weight, or whether their food log is complete for the day. Send "
            "ONLY the fields they actually told you. Never fill in a value "
            "you did not hear — an invented number becomes a recorded "
            "observation and every later average is built on it."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "log_date": {
                    "type": "string",
                    "description": (
                        "ISO date the check-in is about. Defaults to the "
                        "athlete's today."
                    ),
                },
                "energy": {"type": "integer", "minimum": 1, "maximum": 10},
                "fatigue": {"type": "integer", "minimum": 1, "maximum": 10},
                "soreness_level": {"type": "integer", "minimum": 1, "maximum": 10},
                "stress": {"type": "integer", "minimum": 1, "maximum": 10},
                "motivation": {"type": "integer", "minimum": 1, "maximum": 10},
                "sleep_quality": {"type": "integer", "minimum": 1, "maximum": 10},
                "sleep_hours": {"type": "number", "minimum": 0, "maximum": 24},
                "hrv": {"type": "number", "minimum": 0},
                "heart_rate": {"type": "number", "minimum": 0},
                "body_weight": {
                    "type": "number", "minimum": 0,
                    "description": (
                        "In the athlete's own weight unit. Goes to the "
                        "canonical observation store, not onto this row."
                    ),
                },
                "nutrition_status": {
                    "type": "string",
                    "enum": ["unknown", "partial", "complete"],
                    "description": (
                        "Only 'complete' when they confirmed the day is "
                        "fully logged. Never inferred from how many meals "
                        "are in the log."
                    ),
                },
                "notes": {"type": "string", "maxLength": 2000},
                "expected_version": {
                    "type": "integer",
                    "description": (
                        "The row version from a previous read, to detect a "
                        "concurrent edit from another device."
                    ),
                },
            },
            "additionalProperties": False,
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        db = _session()
        try:
            from app.schemas.fitness_coach import CheckInPatch
            from app.services.fitness.observations import (
                CheckInConflict, patch_check_in,
            )

            log_date = _parse_date(kwargs.pop("log_date", None), "log_date") \
                or _athlete_today(db, user_id)
            # Exactly the keys the model sent. `present_fields` on the schema
            # distinguishes omitted from explicit null, and building the
            # patch from a full dict would turn every untouched field into an
            # assertion.
            payload = {
                key: value for key, value in kwargs.items()
                if key not in ("idempotency_key",)
            }
            if not payload:
                return ToolResult(
                    success=False,
                    message=(
                        "Nothing to record. Send only the fields the athlete "
                        "actually told you."
                    ),
                )
            patch = CheckInPatch(**payload)
            result = patch_check_in(db, user_id, log_date, patch, source="chat")
            recorded = sorted(k for k in payload if k != "expected_version")
            return ToolResult(
                success=True,
                data={
                    "log_date": log_date.isoformat(),
                    "recorded_fields": recorded,
                    "row_version": result.row_version,
                    "readiness": (
                        result.subjective_readiness
                        if hasattr(result, "subjective_readiness") else None
                    ),
                },
                message=f"Recorded {', '.join(recorded)} for {log_date}.",
            )
        except CheckInConflict as exc:
            return ToolResult(
                success=False,
                message=(
                    f"Someone else changed that day's check-in while you were "
                    f"working (current version {exc.current_version}). Read it "
                    f"again before writing."
                ),
            )
        except ValueError as exc:
            # Includes Pydantic validation: an out-of-range scale or an
            # unknown field is refused rather than coerced.
            return ToolResult(success=False, message=str(exc))
        except Exception as exc:
            logger.warning(
                "fitness_checkin_update failed (%s): %s", type(exc).__name__, exc,
            )
            db.rollback()
            return ToolResult(
                success=False, message=f"Could not record the check-in: {exc}",
            )
        finally:
            db.close()


class FitnessMeasurementLogTool(BaseTool):
    """One tape reading the athlete reported."""

    requires_user_origin = True

    @property
    def name(self) -> str:
        return "fitness_measurement_log"

    @property
    def description(self) -> str:
        return (
            "Record one tape measurement the athlete reported (waist, arm, "
            "chest, or a custom type they defined). Include the protocol if "
            "they said how they measured — a waist at the navel and one at "
            "the narrowest point differ by centimetres, and without the "
            "protocol the two cannot be compared later."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "type_code": {
                    "type": "string",
                    "description": (
                        "Measurement type code. Call fitness_measurements_get "
                        "with no arguments to see what exists."
                    ),
                },
                "value": {"type": "number", "exclusiveMinimum": 0},
                "unit": {
                    "type": "string",
                    "enum": ["cm", "in", "kg", "lb", "%"],
                },
                "measured_at": {
                    "type": "string",
                    "description": (
                        "ISO timestamp of when it was MEASURED, not when it "
                        "was mentioned. Defaults to now."
                    ),
                },
                "site": {
                    "type": "string",
                    "description": "Where on the body, if the type allows sites.",
                },
                "side": {
                    "type": "string", "enum": ["none", "left", "right"],
                },
                "protocol": {
                    "type": "string", "maxLength": 200,
                    "description": "How it was measured, in their words.",
                },
                "idempotency_key": {
                    "type": "string",
                    "description": (
                        "A stable key for this reading, so a retried turn "
                        "does not record it twice."
                    ),
                },
            },
            "required": ["type_code", "value", "unit"],
            "additionalProperties": False,
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        db = _session()
        try:
            from app.core.timezone import now as local_now
            from app.schemas.fitness_coach import MeasurementIn, Side, Unit
            from app.services.fitness.observations import log_measurement

            measured_at = kwargs.get("measured_at")
            if measured_at:
                try:
                    stamp = datetime.fromisoformat(
                        str(measured_at).replace("Z", "+00:00")
                    )
                except Exception:
                    raise ValueError(
                        "measured_at must be an ISO timestamp"
                    )
                if stamp.tzinfo is None:
                    # A naive stamp cannot be placed on a calendar day
                    # without guessing a zone, and guessing moves the
                    # reading to the wrong day.
                    raise ValueError(
                        "measured_at needs a timezone offset; without one the "
                        "reading cannot be placed on a calendar day"
                    )
            else:
                stamp = local_now()

            payload = MeasurementIn(
                type_code=str(kwargs["type_code"]),
                value=float(kwargs["value"]),
                unit=Unit(str(kwargs["unit"])),
                measured_at=stamp,
                site=kwargs.get("site"),
                side=Side(str(kwargs.get("side") or "none")),
                protocol=kwargs.get("protocol"),
                idempotency_key=kwargs.get("idempotency_key"),
            )
            out = log_measurement(db, user_id, payload)
            return ToolResult(
                success=True,
                data={
                    "id": out.id, "type_code": out.type_code,
                    "value": out.value, "unit": out.unit.value,
                    "logical_date": out.logical_date.isoformat(),
                    "protocol": out.protocol,
                },
                message=(
                    f"Recorded {out.value} {out.unit.value} "
                    f"{out.label.lower()} on {out.logical_date}."
                ),
            )
        except LookupError:
            return ToolResult(
                success=False,
                message=(
                    "No such measurement type. Call fitness_measurements_get "
                    "with no arguments to see what exists."
                ),
            )
        except ValueError as exc:
            return ToolResult(success=False, message=str(exc))
        except Exception as exc:
            logger.warning(
                "fitness_measurement_log failed (%s): %s", type(exc).__name__, exc,
            )
            db.rollback()
            return ToolResult(
                success=False, message=f"Could not record that: {exc}",
            )
        finally:
            db.close()


class FitnessCoachReviewRequestTool(BaseTool):
    """Ask for a review. Queues a job; changes no target."""

    requires_user_origin = True

    @property
    def name(self) -> str:
        return "fitness_coach_review_request"

    @property
    def description(self) -> str:
        return (
            "Queue a weekly coach review when the athlete asks for one. It "
            "reads their logged data and proposes changes for them to accept "
            "or reject; it changes nothing by itself and takes about a "
            "minute. Only call this when they asked — a review is a minute of "
            "local GPU time and an unprompted one is a notification they did "
            "not want. Use fitness_coach_review_get to read the result."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "period_end": {
                    "type": "string",
                    "description": (
                        "ISO date (EXCLUSIVE) for the end of the week to "
                        "review. Defaults to the athlete's today, so the "
                        "last seven complete days."
                    ),
                },
                "force": {
                    "type": "boolean",
                    "description": (
                        "Only when a review of this period exists and the "
                        "data has changed since. Produces a linked revision "
                        "and keeps the old review."
                    ),
                },
                "idempotency_key": {
                    "type": "string",
                    "description": "A stable key for this request.",
                },
            },
            "additionalProperties": False,
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        db = _session()
        try:
            from app.schemas.fitness_coach import Period, RequestedBy, ReviewKind
            from app.services.fitness import reviews as review_service
            from app.services.fitness.review_audit import ReviewConflict

            period_end = _parse_date(kwargs.get("period_end"), "period_end")
            period = None
            if period_end:
                period = Period(
                    start=period_end - timedelta(days=7), end=period_end,
                )

            review = review_service.request_review(
                db, user_id, kind=ReviewKind.WEEKLY, period=period,
                requested_by=RequestedBy.USER,
                force=bool(kwargs.get("force")),
            )
            _dispatch(user_id, review.id)
            return ToolResult(
                success=True,
                data={
                    "review_id": review.id,
                    "status": review.status.value,
                    "period": {
                        "start": review.period.start.isoformat(),
                        "end": review.period.end.isoformat(),
                    },
                },
                message=(
                    f"Queued a review of {review.period.start} to "
                    f"{review.period.end}. It takes about a minute and "
                    f"changes nothing on its own."
                ),
            )
        except ReviewConflict as exc:
            return ToolResult(
                success=False,
                data={"review_id": exc.review_id, "status": exc.status.value},
                message=(
                    f"{exc} Read the existing one with "
                    f"fitness_coach_review_get, or ask the athlete whether to "
                    f"run it again on the current data."
                ),
            )
        except ValueError as exc:
            return ToolResult(success=False, message=str(exc))
        except Exception as exc:
            logger.warning(
                "fitness_coach_review_request failed (%s): %s",
                type(exc).__name__, exc,
            )
            db.rollback()
            return ToolResult(
                success=False, message=f"Could not queue a review: {exc}",
            )
        finally:
            db.close()


def _dispatch(user_id: str, review_id: str) -> None:
    """Hand the review to the worker. A dispatch failure loses no data.

    The row is already committed as `pending`, so this logs rather than
    raising — raising would lose the only durable record that the athlete
    asked.
    """
    try:
        from app.celery_app import celery_app
        celery_app.send_task(
            "app.tasks.fitness_coach.generate_review",
            kwargs={"user_id": user_id, "review_id": review_id},
            queue="health",
        )
    except Exception as exc:
        logger.warning(
            "review %s queued but not dispatched (%s)", review_id,
            type(exc).__name__,
        )


class FitnessRecommendationDecideTool(BaseTool):
    """Accept or reject a coaching proposal. The athlete's decision only."""

    requires_user_origin = True

    @property
    def name(self) -> str:
        return "fitness_recommendation_decide"

    @property
    def description(self) -> str:
        return (
            "Record the athlete's decision on a specific coach "
            "recommendation. Accepting applies the exact proposed change — "
            "read it back to them with its numbers and get an unambiguous "
            "yes first. Never call this on your own judgement that a "
            "recommendation is sensible, and never on a vague agreement: "
            "this changes the targets they eat and train against."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "recommendation_id": {
                    "type": "string",
                    "description": (
                        "From fitness_coach_review_get. Must be one the "
                        "athlete has been shown."
                    ),
                },
                "decision": {"type": "string", "enum": ["accept", "reject"]},
                "note": {
                    "type": "string", "maxLength": 1000,
                    "description": "The athlete's own words, if they gave a reason.",
                },
                "idempotency_key": {
                    "type": "string",
                    "description": "A stable key for this decision.",
                },
            },
            "required": ["recommendation_id", "decision"],
            "additionalProperties": False,
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        db = _session()
        try:
            from app.services.fitness import recommendations as service
            from app.services.fitness.data_access import FitnessDataError
            from app.services.fitness.recommendations import (
                RecommendationStale, RecommendationUnsupported,
            )

            recommendation_id = str(kwargs.get("recommendation_id") or "").strip()
            decision = str(kwargs.get("decision") or "").strip().lower()
            if not recommendation_id:
                return ToolResult(
                    success=False, message="recommendation_id is required.",
                )
            if decision not in ("accept", "reject"):
                return ToolResult(
                    success=False,
                    message="decision must be 'accept' or 'reject'.",
                )

            if decision == "reject":
                rec = service.reject(
                    db, user_id, recommendation_id, note=kwargs.get("note"),
                )
                return ToolResult(
                    success=True,
                    data={"recommendation_id": rec.id, "decision": "rejected"},
                    message="Recorded as rejected. Nothing changed.",
                )

            result = service.accept(
                db, user_id, recommendation_id, note=kwargs.get("note"),
            )
            return ToolResult(
                success=True,
                data={
                    "recommendation_id": result.recommendation.id,
                    "decision": "accepted",
                    "action_receipt_id": result.action_receipt_id,
                    "applied_revision_id": result.applied_revision_id,
                    "duplicate": result.duplicate,
                },
                # The committed outcome, not the intent. A message composed
                # from the proposal would describe a change that may not have
                # landed.
                message=result.message,
            )
        except LookupError:
            return ToolResult(
                success=False,
                message="No such recommendation for this athlete.",
            )
        except (RecommendationStale, RecommendationUnsupported,
                FitnessDataError) as exc:
            # The expected refusals: a stale or expired proposal, an action
            # this path cannot perform, or a bound the proposal no longer
            # passes. Each is a message for the athlete, not an error.
            return ToolResult(success=False, message=str(exc))
        except Exception as exc:
            logger.warning(
                "fitness_recommendation_decide failed (%s): %s",
                type(exc).__name__, exc,
            )
            db.rollback()
            return ToolResult(
                success=False, message=f"Could not record that decision: {exc}",
            )
        finally:
            db.close()


class FitnessScienceSearchTool(BaseTool):
    """Accepted evidence from the athlete's curated library.

    Step 28.5. Read-only, and it cannot reach an unreviewed paper: the
    service filters on `status = 'accepted'` in SQL. The distinction
    matters to this tool specifically, because a model asked "what does the
    research say" will happily cite whatever comes back — so what comes
    back has to be only what somebody accepted.

    The hits carry population and limitations deliberately. A snippet with
    no population is how "trained men gained more from higher volume"
    becomes advice for a 52-year-old beginner.
    """

    @property
    def name(self) -> str:
        return "fitness_science_search"

    @property
    def description(self) -> str:
        return (
            "Search the athlete's curated exercise-science library for "
            "accepted evidence on a training, nutrition, sleep or recovery "
            "question. Returns passages with their source, population and "
            "limitations. Only papers the athlete has reviewed and accepted "
            "are searchable — if this returns nothing, say the library has "
            "no accepted evidence on it rather than answering from general "
            "knowledge and implying it came from here. Read only."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The question, in words. 'training frequency for "
                        "hypertrophy', not keywords."
                    ),
                },
                "topics": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "hypertrophy", "strength", "nutrition", "sleep",
                            "recovery", "cardio", "injury", "supplements",
                        ],
                    },
                    "description": "Optional topic filter.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Passages to return (1-10, default 5).",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        db = _session()
        try:
            from app.schemas.fitness_coach import ScienceTopic
            from app.services.fitness import science

            query = (kwargs.get("query") or "").strip()
            if len(query) < 3:
                return ToolResult(
                    success=False,
                    message="A search needs at least three characters.",
                )

            topics = []
            for slug in kwargs.get("topics") or []:
                try:
                    topics.append(ScienceTopic(str(slug).strip().lower()))
                except ValueError:
                    return ToolResult(
                        success=False,
                        message=(
                            f"{slug!r} is not a topic. Known: "
                            f"{', '.join(t.value for t in ScienceTopic)}."
                        ),
                    )

            limit = kwargs.get("limit") or 5
            try:
                limit = max(1, min(int(limit), 10))
            except (TypeError, ValueError):
                limit = 5

            hits = await science.search(
                db, user_id, query, topics=topics or None,
                athlete=_science_athlete(db, user_id), limit=limit,
            )
            library = science.coverage(db, user_id)

            if not hits:
                # The two reasons for an empty result are different answers,
                # and collapsing them is how "no evidence found" becomes
                # "the research is unclear".
                if library["accepted_total"] == 0:
                    message = (
                        "The science library has no accepted papers at all "
                        "yet, so there is nothing to search. Say that "
                        "plainly — do not answer from general knowledge as "
                        "though it came from the library."
                    )
                else:
                    message = (
                        f"Nothing in the {library['accepted_total']} accepted "
                        f"papers matches that. Topics with no accepted "
                        f"evidence: "
                        f"{', '.join(library['topics_with_no_evidence']) or 'none'}."
                    )
                return ToolResult(
                    success=True, data={"hits": [], "library": library},
                    message=message,
                )

            data = {
                "hits": [hit.model_dump(mode="json") for hit in hits],
                "library": library,
                "ranking_policy_version": science.SCIENCE_RANKING_POLICY_VERSION,
            }
            notes = [
                f"{hit.title[:60]}"
                + (f" ({hit.publication_year})" if hit.publication_year else "")
                + (f" — {hit.applicability_note}" if hit.applicability_note else "")
                for hit in hits
            ]
            return ToolResult(
                success=True, data=data,
                message=(
                    f"{len(hits)} passage(s) from accepted sources: "
                    + "; ".join(notes)
                    + ". Cite the source by title; the population and "
                      "limitations are in the data and belong in the answer "
                      "when they bear on it."
                ),
            )
        except Exception as exc:
            logger.warning(
                "fitness_science_search failed (%s): %s",
                type(exc).__name__, exc,
            )
            return ToolResult(
                success=False,
                message=f"Could not search the library: {exc}",
            )
        finally:
            db.close()


def _science_athlete(db, user_id: str):
    """Applicability context from the profile.

    Shared by the tool and the route rather than duplicated: an
    applicability comparison that reads different fields in two places
    would rank the same paper differently depending on who asked.
    """
    from sqlalchemy import text

    from app.services.fitness.science import AthleteContext

    row = db.execute(text("""
        SELECT training_level, calculation_sex, date_of_birth
        FROM fitness_athlete_profile WHERE user_id = :u
    """), {"u": user_id}).fetchone()
    if row is None:
        return AthleteContext()
    age = None
    if row.date_of_birth:
        from app.core.timezone import now as local_now
        today = local_now().date()
        born = row.date_of_birth
        age = today.year - born.year - (
            (today.month, today.day) < (born.month, born.day)
        )
    sex = row.calculation_sex
    if sex in ("unknown", "prefer_not_to_say"):
        sex = None
    level = row.training_level if row.training_level != "unknown" else None
    return AthleteContext(training_level=level, sex=sex, age=age)
