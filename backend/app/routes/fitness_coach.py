"""`/api/fitness/coach` — the Fitness Coach API.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 6, §6, §17. Routes are thin: they
authenticate, validate, delegate to a service, and translate service
exceptions into status codes. No SQL, no policy, no arithmetic.

Two things are deliberate about the error mapping:

* A foreign or missing id is **404, never 403**. A 403 confirms the row
  exists to someone who does not own it.
* A concurrency conflict is **409 with the current version**, so a client
  can reconcile rather than guess. A bare 409 forces a blind retry, which is
  how a second device's edit gets silently discarded.

This router is registered OUTSIDE any try/except in `main_simple.py` (gotcha
3): a swallowed import error there silently drops an entire router, and the
failure mode is "the feature quietly does not exist".
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.fitness_coach import (
    AthleteGoalIn,
    CheckInOut,
    CheckInPatch,
    MeasurementIn,
    MeasurementOut,
    MeasurementPeriodIn,
    MeasurementPeriodOut,
    MeasurementTypeIn,
    MeasurementTypeOut,
    Metric,
    AthleteGoalOut,
    AthleteLimitationIn,
    AthleteLimitationOut,
    AthleteProfileOut,
    AthleteProfilePatch,
    DataQuality,
    DayType,
    FitnessStateV1,
    MetricGroup,
    StateSection,
    ResolvedTargets,
    TargetRevisionIn,
    TargetRevisionOut,
    TargetScope,
)
from app.services.fitness import observations as observation_service
from app.services.fitness import profile as profile_service
from app.services.fitness import state as state_service
from app.services.fitness import targets as target_service
from app.services.fitness.data_access import FitnessDataError

logger = logging.getLogger(__name__)
router = APIRouter()


def current_athlete(current_user: User = Depends(get_current_user)) -> str:
    """The authenticated requester's id.

    Named for what it is. There is no device-token-free variant here and no
    default owner: every route in this module is owner-scoped, and Step 2
    exists because a fitness route once had a default.
    """
    return current_user.id


def _conflict(exc: profile_service.ConcurrencyConflict) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "version_conflict",
            "message": "Someone else changed this while you were editing it.",
            "current_version": exc.current_version,
        },
    )


def _target_conflict(exc: target_service.TargetConflict) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "target_conflict",
            "message": str(exc),
            "current_revision_id": exc.current_revision_id,
        },
    )


# ─────────────────────────────────────────────────────────────────────────
# Profile
# ─────────────────────────────────────────────────────────────────────────

@router.get("/profile", response_model=AthleteProfileOut)
async def get_profile(
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> AthleteProfileOut:
    """The athlete's profile. Creates nothing.

    An athlete who has never opened Settings gets an all-unknown profile
    rather than a row of defaults, so "never configured" stays
    distinguishable from "configured to those values".
    """
    return profile_service.get_athlete_profile(db, user_id)


@router.patch("/profile", response_model=AthleteProfileOut)
async def patch_profile(
    patch: AthleteProfilePatch,
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> AthleteProfileOut:
    """Update only the fields the request mentions.

    An omitted field is untouched; an explicit `null` clears it. Those are
    different requests and the DTO keeps them different.
    """
    try:
        return profile_service.patch_athlete_profile(db, user_id, patch)
    except profile_service.ConcurrencyConflict as exc:
        raise _conflict(exc)
    except FitnessDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/today")
async def get_today(
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """The athlete's own calendar date and timezone.

    Exists because the browser's local date is not authoritative: a
    travelling athlete's device and their configured timezone disagree, and
    the server has to decide which day a check-in belongs to.
    """
    tz = profile_service.profile_timezone(db, user_id)
    today = profile_service.athlete_today(db, user_id)
    return {"athlete_local_date": today.isoformat(), "timezone": tz}


# ─────────────────────────────────────────────────────────────────────────
# Goals
# ─────────────────────────────────────────────────────────────────────────

@router.get("/goals", response_model=List[AthleteGoalOut])
async def list_goals(
    on_date: Optional[date] = Query(
        None, description="athlete-local date; defaults to the athlete's today"
    ),
    history: bool = Query(False, description="return every goal ever recorded"),
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> List[AthleteGoalOut]:
    return profile_service.get_goals(db, user_id, on_date, include_history=history)


@router.post("/goals", response_model=AthleteGoalOut, status_code=201)
async def create_goal(
    payload: AthleteGoalIn,
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> AthleteGoalOut:
    """Record a goal.

    A new primary goal closes the open one it supersedes rather than being
    rejected — "I'm cutting now" should end the bulk. A goal that would
    contradict an already-closed interval is a 409: that is history being
    overwritten, not continued.
    """
    try:
        return profile_service.create_goal(db, user_id, payload)
    except profile_service.GoalOverlap as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "goal_overlap", "message": str(exc)},
        )
    except FitnessDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


class CloseGoalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valid_until: date


@router.post("/goals/{goal_id}/close", response_model=AthleteGoalOut)
async def close_goal(
    goal_id: str,
    payload: CloseGoalRequest,
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> AthleteGoalOut:
    """End a goal's interval. The goal itself is retained."""
    try:
        return profile_service.close_goal(db, user_id, goal_id, payload.valid_until)
    except LookupError:
        raise HTTPException(status_code=404, detail="Goal not found")
    except FitnessDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────
# Limitations
# ─────────────────────────────────────────────────────────────────────────

@router.get("/limitations", response_model=List[AthleteLimitationOut])
async def list_limitations(
    on_date: Optional[date] = Query(None),
    history: bool = Query(False),
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> List[AthleteLimitationOut]:
    return profile_service.get_limitations(db, user_id, on_date, include_history=history)


@router.post("/limitations", response_model=AthleteLimitationOut, status_code=201)
async def create_limitation(
    payload: AthleteLimitationIn,
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> AthleteLimitationOut:
    """Record a user-reported constraint.

    There is no diagnosis field, by design: "right shoulder hurts overhead"
    is data; naming a condition is a clinical conclusion this system does
    not draw.
    """
    return profile_service.create_limitation(db, user_id, payload)


class ResolveLimitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_until: Optional[date] = None


@router.post("/limitations/{limitation_id}/resolve",
             response_model=AthleteLimitationOut)
async def resolve_limitation(
    limitation_id: str,
    payload: ResolveLimitationRequest,
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> AthleteLimitationOut:
    try:
        return profile_service.resolve_limitation(
            db, user_id, limitation_id, effective_until=payload.effective_until
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Limitation not found")


# ─────────────────────────────────────────────────────────────────────────
# Targets
# ─────────────────────────────────────────────────────────────────────────

@router.get("/targets", response_model=ResolvedTargets)
async def resolve_targets(
    on_date: Optional[date] = Query(
        None, description="athlete-local date; defaults to the athlete's today"
    ),
    day_type: Optional[DayType] = Query(
        None, description="override the resolved training/rest day type"
    ),
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> ResolvedTargets:
    """The targets that applied on a date, with their provenance.

    The response always says *where* the numbers came from
    (`approved_revision` | `legacy_phase` | `legacy_default` | `unknown`) and
    whether the date precedes recorded history. A caller rendering a trend
    needs that: comparing intake against targets that were never set is not
    adherence.
    """
    d = on_date or profile_service.athlete_today(db, user_id)
    return target_service.resolve_targets(db, user_id, d, day_type)


@router.get("/targets/history", response_model=List[TargetRevisionOut])
async def list_target_revisions(
    scope: Optional[TargetScope] = Query(None),
    phase_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> List[TargetRevisionOut]:
    return target_service.list_revisions(
        db, user_id, scope=scope, phase_id=phase_id, limit=limit
    )


class CreateTargetRevisionRequest(TargetRevisionIn):
    """A revision plus the optimistic-concurrency token.

    `expected_revision` is what makes accepting a coach recommendation safe:
    the proposal was computed against one current revision, and if that has
    moved the acceptance is stale and must be refused rather than applied to
    a different baseline.
    """
    expected_revision: Optional[str] = Field(
        default=None,
        description="id of the revision this edit expects to be current",
    )


@router.post("/targets", response_model=TargetRevisionOut, status_code=201)
async def create_target_revision(
    payload: CreateTargetRevisionRequest,
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> TargetRevisionOut:
    """Append an approved target revision.

    The previous revision is closed, not replaced — its values stay
    queryable so a review that cited them stays verifiable. The legacy
    `fitness_phase`/`fitness_goals` projection is updated in the same
    transaction, but only when this revision is the current one: a backdated
    correction must not change what today's dashboard shows.
    """
    revision = TargetRevisionIn(
        scope=payload.scope,
        phase_id=payload.phase_id,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        training=payload.training,
        rest=payload.rest,
        source=payload.source,
        review_recommendation_id=payload.review_recommendation_id,
    )
    try:
        return target_service.create_target_revision(
            db, user_id, revision, expected_revision=payload.expected_revision
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Phase not found")
    except target_service.TargetConflict as exc:
        raise _target_conflict(exc)
    except FitnessDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────
# Daily check-ins
# ─────────────────────────────────────────────────────────────────────────

@router.get("/check-ins/{log_date}", response_model=CheckInOut)
async def get_check_in(
    log_date: date,
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> CheckInOut:
    """One athlete-local day.

    Subjective answers come from the daily row; weight, sleep, steps, water,
    HRV and resting heart rate are resolved from `health_metric` through the
    selection rules, each as a `Metric` that can say why it has no value.

    `computed_readiness` is absent — not zero, and not 100 — when nothing
    eligible was recorded. `recovery_score.compute_readiness({})` returns
    100/"Excellent", which is correct arithmetic on no information and has
    been shown to someone who logged nothing.
    """
    return observation_service.get_check_in(db, user_id, log_date)


@router.patch("/check-ins/{log_date}", response_model=CheckInOut)
async def patch_check_in(
    log_date: date,
    patch: CheckInPatch,
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> CheckInOut:
    """Update part of a day.

    An omitted field is left alone; an explicit `null` clears exactly that
    field. A PATCH sending only `energy` must not erase the HRV HealthKit
    wrote this morning, which is why the two cases are distinguishable at the
    DTO level rather than being collapsed into `Optional[int] = None`.

    Marking nutrition complete is explicit. It is never inferred from how
    many meals were logged or from the calorie total looking plausible —
    complete days are the denominator for every nutrition average, so
    guessing one inflates the sample.
    """
    try:
        return observation_service.patch_check_in(db, user_id, log_date, patch)
    except observation_service.CheckInConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "version_conflict",
                "message": "This day was updated somewhere else while you were editing.",
                "current_version": exc.current_version,
            },
        )
    except FitnessDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────
# Measurements
# ─────────────────────────────────────────────────────────────────────────

@router.get("/measurement-types", response_model=List[MeasurementTypeOut])
async def list_measurement_types(
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> List[MeasurementTypeOut]:
    """Global seeds plus this athlete's own definitions.

    Another athlete's custom code is not listed and cannot be logged
    against: its label is something they wrote.
    """
    return observation_service.list_measurement_types(db, user_id)


@router.post("/measurement-types", response_model=MeasurementTypeOut, status_code=201)
async def create_measurement_type(
    payload: MeasurementTypeIn,
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> MeasurementTypeOut:
    """Add a private measurement definition.

    No migration needed, which is the point of the descriptor table: a
    column per circumference cannot hold "forearm at the widest point,
    standing" without a deploy.
    """
    try:
        return observation_service.create_measurement_type(db, user_id, payload)
    except FitnessDataError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/measurement-periods", response_model=List[MeasurementPeriodOut])
async def list_measurement_periods(
    limit: int = Query(50, ge=1, le=200),
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> List[MeasurementPeriodOut]:
    return observation_service.list_measurement_periods(db, user_id, limit=limit)


@router.post("/measurement-periods", response_model=MeasurementPeriodOut,
             status_code=201)
async def create_measurement_period(
    payload: MeasurementPeriodIn,
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> MeasurementPeriodOut:
    """Group one tape session or photo set.

    So "waist 81.5, chest 104, arm 38.5" reads as one sitting rather than
    three unrelated points.
    """
    return observation_service.create_measurement_period(db, user_id, payload)


@router.get("/measurements", response_model=List[MeasurementOut])
async def list_measurements(
    type_code: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None, description="exclusive"),
    limit: int = Query(100, ge=1, le=500),
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> List[MeasurementOut]:
    try:
        return observation_service.list_measurements(
            db, user_id, type_code=type_code, start_date=start_date,
            end_date=end_date, limit=limit,
        )
    except FitnessDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/measurements", response_model=MeasurementOut, status_code=201)
async def log_measurement(
    payload: MeasurementIn,
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> MeasurementOut:
    """Record one tape reading.

    Stored as a canonical observation in `health_metric` — there is no
    separate measurement value table, because body observations have one
    authority and a second numeric store could immediately disagree with it.
    """
    try:
        return observation_service.log_measurement(db, user_id, payload)
    except LookupError:
        raise HTTPException(status_code=404, detail="Measurement type not found")
    except FitnessDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/measurements/{type_code}/change", response_model=Metric)
async def measurement_change(
    type_code: str,
    site: Optional[str] = Query(None),
    side: str = Query("none"),
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> Metric:
    """The difference between the two most recent *comparable* readings.

    Comparable means same type, site, side, protocol and unit. A waist
    measured at the navel and one at the narrowest point differ by
    centimetres, and that difference is not a change in the athlete — so
    those return `not_comparable` rather than a number.
    """
    return observation_service.measurement_change(
        db, user_id, type_code, site=site, side=side
    )


# ─────────────────────────────────────────────────────────────────────────
# State and analytics (Step 17)
# ─────────────────────────────────────────────────────────────────────────

def _state_cache():
    """A shared blocking Redis client, or None.

    None is a supported answer, not a failure: the state is computed from
    records and the cache only saves the computation. Note the `redis<5.0.0`
    pin — the async client here has `.close()`, not `.aclose()`.
    """
    try:
        from app.core.redis import get_redis_sync
        return get_redis_sync()
    except Exception as exc:
        logger.debug("fitness state cache unavailable (%s)", type(exc).__name__)
        return None


@router.get("/state", response_model=FitnessStateV1)
async def get_fitness_state(
    period_end: Optional[date] = Query(
        None,
        description="Exclusive, athlete-local. Defaults to the athlete's "
                    "today, so a partial current day is never averaged in.",
    ),
    span: int = Query(7, ge=1, le=90),
    sections: Optional[str] = Query(
        None, description="Comma-separated section names. Narrowing changes "
                          "which sections are present, never what one says.",
    ),
    fresh: bool = Query(False, description="Bypass the cache."),
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> FitnessStateV1:
    """The athlete's deterministic state — the one projection every surface reads.

    `freshness` is `degraded` when a dependency failed, and
    `degraded_dependencies` names which. That is deliberately not the same
    as returning fewer metrics: a smaller state is indistinguishable from
    the athlete having less data, and a reader would then draw conclusions
    from an absence that is really an outage.
    """
    wanted = None
    if sections:
        try:
            wanted = [
                StateSection(name.strip())
                for name in sections.split(",") if name.strip()
            ]
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown section: {exc}. Valid: "
                       + ", ".join(s.value for s in StateSection),
            )
    try:
        return state_service.build_fitness_state(
            db, user_id,
            period_end=period_end, sections=wanted, span=span, fresh=fresh,
            redis_client=_state_cache(),
        )
    except FitnessDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/capsule")
async def get_fitness_capsule(
    char_budget: int = Query(1500, ge=200, le=8000),
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """The same state, rendered for a prompt within a character budget.

    Exposed so the chat capsule and the UI cannot drift: both render from
    one state, and if this endpoint's text is wrong the dashboard above it
    is wrong in the same way, which is how such a bug gets noticed.
    """
    state = state_service.build_fitness_state(
        db, user_id, redis_client=_state_cache(),
    )
    capsule = state_service.render_fitness_capsule(state, char_budget)
    return {
        "capsule": capsule,
        "chars": len(capsule),
        "char_budget": char_budget,
        "freshness": state.freshness.value,
        "athlete_local_date": state.athlete_local_date.isoformat(),
        "data_revision": state.data_revision,
    }


@router.get("/analytics/{section}", response_model=MetricGroup)
async def get_section_analytics(
    section: StateSection,
    period_end: Optional[date] = Query(None),
    span: int = Query(7, ge=1, le=90),
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> MetricGroup:
    """One section's metrics, bounded by `span`.

    The bound is a real limit, not a default: an unbounded window over a
    multi-year history is the shape of request that takes a shared database
    down, and a coach never needs one to answer a question about this week.
    """
    state = state_service.build_fitness_state(
        db, user_id, period_end=period_end, sections=[section], span=span,
        redis_client=_state_cache(),
    )
    group = state.sections.get(section)
    if group is None:
        raise HTTPException(
            status_code=404,
            detail=f"Section {section.value} has no computed analytics",
        )
    return group


@router.get("/quality", response_model=DataQuality)
async def get_data_quality(
    period_end: Optional[date] = Query(None),
    span: int = Query(7, ge=1, le=90),
    user_id: str = Depends(current_athlete),
    db: Session = Depends(get_db),
) -> DataQuality:
    """Coverage, kept separate from any confidence in an interpretation.

    Folding the two together is how a confident conclusion drawn from two
    days of data stops being visible as such.
    """
    state = state_service.build_fitness_state(
        db, user_id, period_end=period_end, span=span,
        redis_client=_state_cache(),
    )
    return state.quality
