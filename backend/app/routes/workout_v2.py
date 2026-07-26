"""Versioned cross-device workout API.

SARA_APPLE_WATCH_FITNESS_IMPLEMENTATION_PLAN_2026_07_25 §5, §6.5.

Mounted at /api/fitness/workout-session/v2. The legacy
/api/fitness/workout-session/* endpoints stay live and route into the same
command service (§16.2 rollback), so nothing here is a cutover on its own —
these are the endpoints a second controller (the Watch, via the iPhone) needs
and the phone will migrate onto behind WORKOUT_COMMAND_V2_ENABLED.

The shape of every request/response here is the wire contract in §5. Keep it in
step with `WorkoutWireModels.swift` and `ios-app/src/services/workoutContracts.ts`;
`tests/test_workout_wire_contract.py` asserts the three stay aligned.

  POST /v2/start            create / resume / refuse-to-clobber the session
  GET  /v2/active           current projection
  POST /v2/commands         apply one idempotent command envelope
  GET  /v2/sync             projection + coaching events after a version
  POST /v2/healthkit-link   bind the exact HealthKit workout to the session
  GET  /v2/catalog          compact template list the Watch caches
  GET  /v2/proposals        recommendations awaiting David's decision
  GET  /v2/policy           standing bounded approvals
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.routes.fitness import get_current_user_id
from app.services.workout_command_service import (
    SCHEMA_VERSION,
    WorkoutConflict,
    workout_command_service,
)

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_DEVICES = {"phone", "watch", "web", "server"}


def _device(value: Optional[str]) -> str:
    v = (value or "phone").strip().lower()
    return v if v in VALID_DEVICES else "phone"


def _conflict(c: WorkoutConflict) -> HTTPException:
    """Conflicts are data the client acts on, not opaque failures.

    The active projection rides along so the Watch can immediately offer
    Resume / End without a second round trip (§4.2 step 8).
    """
    status = 409 if c.code != "no_active_session" else 404
    return HTTPException(status_code=status, detail={
        "code": c.code,
        "message": c.message,
        "projection": c.projection,
    })


class StartRequest(BaseModel):
    template_id: str
    # Client-generated. A retry through a dropped link replays instead of
    # creating a second workout (§4.3 "persist a start attempt ID").
    start_attempt_id: Optional[str] = None
    origin_device: str = "phone"
    healthkit_started_at: Optional[str] = None
    # Watch-originated Start that finds a different workout running must not
    # silently end it; only an explicit user choice may.
    on_conflict: str = Field(default="error", pattern="^(error|abandon)$")


class CommandEnvelope(BaseModel):
    schema_version: int = SCHEMA_VERSION
    command_id: str
    session_id: Optional[str] = None
    expected_version: Optional[int] = None
    origin_device: str = "phone"
    kind: str
    created_at: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class HealthKitLinkRequest(BaseModel):
    session_id: str
    healthkit_workout_uuid: str
    activity_type: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None


@router.post("/start")
async def v2_start(
    request: StartRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Create, resume, or refuse. Never silently replaces a running workout."""
    try:
        return await workout_command_service.start(
            db, user_id, request.template_id,
            start_attempt_id=request.start_attempt_id,
            origin_device=_device(request.origin_device),
            on_conflict=request.on_conflict,
            healthkit_started_at=request.healthkit_started_at,
        )
    except WorkoutConflict as c:
        raise _conflict(c)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("[workout/v2] start failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active")
async def v2_active(
    compact: bool = False,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Current projection, or null. `compact=true` drops the full exercise
    list for the Watch, which renders from `current_exercise` alone."""
    try:
        result = workout_command_service.sync(db, user_id, compact=compact)
        return {"projection": result["projection"]}
    except Exception as e:
        logger.exception("[workout/v2] active failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/commands")
async def v2_command(
    envelope: CommandEnvelope,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Apply one command exactly once.

    Replaying the same `command_id` returns the original result with
    status="replayed" — that is what makes a double-tapped `Log Set` over bad
    connectivity safe.
    """
    if envelope.schema_version != SCHEMA_VERSION:
        # An older build must be told plainly rather than have its payload
        # guessed at (§5.3 "never crash an active workout").
        raise HTTPException(status_code=400, detail={
            "code": "unsupported_schema_version",
            "message": f"This app build speaks schema {envelope.schema_version}; server speaks {SCHEMA_VERSION}.",
            "server_schema_version": SCHEMA_VERSION,
        })
    try:
        payload = envelope.model_dump()
        payload["origin_device"] = _device(envelope.origin_device)
        return await workout_command_service.execute(db, user_id, payload)
    except WorkoutConflict as c:
        raise _conflict(c)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"[workout/v2] command {envelope.kind} failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync")
async def v2_sync(
    after_version: Optional[int] = None,
    compact: bool = False,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Reconciliation fallback for a device that missed mirrored messages.

    Mirroring is the primary transport (§4.4); this is what a device polls
    after a reconnect or a cold start.
    """
    try:
        return workout_command_service.sync(db, user_id, after_version, compact=compact)
    except Exception as e:
        logger.exception("[workout/v2] sync failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/healthkit-link")
async def v2_healthkit_link(
    request: HealthKitLinkRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Bind the exact HealthKit workout to the Sara session (§6.4).

    Safe to call before the corresponding `external_workout` row has been
    ingested — the UUID lands on the session either way and ingestion picks
    the link up from there.
    """
    try:
        return workout_command_service.link_healthkit(
            db, user_id, request.session_id, request.healthkit_workout_uuid,
            activity_type=request.activity_type,
            started_at=request.started_at,
            ended_at=request.ended_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("[workout/v2] healthkit-link failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog")
async def v2_catalog(
    limit: int = 8,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Compact catalog the Watch caches so it can start without the phone (§7.5)."""
    try:
        return workout_command_service.catalog(db, user_id, limit=max(1, min(limit, 25)))
    except Exception as e:
        logger.exception("[workout/v2] catalog failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/proposals")
async def v2_proposals(
    status: str = "pending",
    limit: int = 50,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Recommendations awaiting a decision — including next-session progression
    David approves outside the gym (§6.8)."""
    try:
        return {"proposals": workout_command_service.list_proposals(
            db, user_id, status=status, limit=max(1, min(limit, 200))
        )}
    except Exception as e:
        logger.exception("[workout/v2] proposals failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/policy")
async def v2_policy(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """The standing bounded approvals Sara may act inside (§6.9).

    Changing them goes through the `set_policy` command so every widening is
    an attributable approval, not a silent config write.
    """
    try:
        return {"policy": workout_command_service.get_policy(db, user_id)}
    except Exception as e:
        logger.exception("[workout/v2] policy failed")
        raise HTTPException(status_code=500, detail=str(e))
