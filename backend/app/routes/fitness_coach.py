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
    AthleteGoalOut,
    AthleteLimitationIn,
    AthleteLimitationOut,
    AthleteProfileOut,
    AthleteProfilePatch,
    DayType,
    ResolvedTargets,
    TargetRevisionIn,
    TargetRevisionOut,
    TargetScope,
)
from app.services.fitness import profile as profile_service
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
