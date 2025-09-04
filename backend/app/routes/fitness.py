from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Any, Dict
from uuid import UUID
from app.core.deps import get_current_user
from app.db.session import get_db
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.fitness import FitnessPlan, Workout, FitnessEvent
from app.models.fitness_onboarding import FitnessOnboardingSession
from app.services.fitness.generator_service import FitnessPlanGenerator
from app.services.fitness.readiness_service import ReadinessEngine
from app.services.fitness.onboarding_service import FitnessOnboardingService
from app.services.fitness.onboarding_orchestrator import OnboardingOrchestrator
from app.services.fitness.healthkit_service import HealthKitService
from app.services.fitness.manual_entry_service import ManualEntryService
from app.services.fitness.baseline_learning import BaselineLearningEngine
from app.services.fitness.adjustment_service import WorkoutAdjustmentService
from app.services.fitness.notification_service import FitnessNotificationService
from datetime import datetime, timedelta, date, time, timezone
import uuid
import json as _json
import os as _os

# Simple Redis session store (fallback to in-memory if Redis unavailable)
_redis_client = None
_inproc_sessions: dict[str, str] = {}


def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis  # type: ignore

        url = _os.getenv("REDIS_URL", "redis://redis:6379/0")
        _redis_client = redis.from_url(url, decode_responses=True)
        return _redis_client
    except Exception:
        _redis_client = None
        return None


def _sess_key(user_id: uuid.UUID, workout_id: uuid.UUID) -> str:
    return f"fitness:session:{user_id}:{workout_id}"


def _sess_get(user_id: uuid.UUID, workout_id: uuid.UUID) -> dict:
    key = _sess_key(user_id, workout_id)
    r = _get_redis()
    if r:
        raw = r.get(key)
    else:
        raw = _inproc_sessions.get(key)
    return _json.loads(raw) if raw else {}


def _sess_set(user_id: uuid.UUID, workout_id: uuid.UUID, data: dict, ttl_sec: int = 6 * 3600):
    key = _sess_key(user_id, workout_id)
    payload = _json.dumps(data)
    r = _get_redis()
    if r:
        r.set(key, payload, ex=ttl_sec)
    else:
        _inproc_sessions[key] = payload


def _compute_next_set(workout: Workout, session: dict) -> dict | None:
    blocks = workout.prescription or []
    if not blocks:
        return None
    bi = int(session.get("current_block", 0))
    si = int(session.get("current_set", 0))
    # Ensure within bounds
    if bi >= len(blocks):
        return None
    block = blocks[bi]
    total_sets = int(block.get("sets", 0) or 0)
    if si >= total_sets:
        # advance to next block
        bi += 1
        si = 0
        if bi >= len(blocks):
            return None
        block = blocks[bi]
        total_sets = int(block.get("sets", 0) or 0)
    return {
        "block_index": bi,
        "set_index": si + 1,  # 1-based for UI
        "total_sets": total_sets,
        "exercises": block.get("exercises", []),
        "prescription": {
            "reps": block.get("reps"),
            "rpe": block.get("rpe"),
            "intensity": block.get("intensity"),
            "rest": block.get("rest", 60),
        },
    }


# --------- Reflow helpers ---------

def _load_catalog():
    from app.services.fitness.generator import CATALOG_PATH
    with CATALOG_PATH.open("r") as f:
        return _json.load(f)


def _workout_primary_pattern(wk: Workout) -> str | None:
    catalog = _load_catalog()
    blocks = wk.prescription or []
    # Prefer first block containing a main_lift
    for b in blocks:
        for ex in b.get("exercises", []):
            meta = catalog.get(ex)
            if meta and meta.get("main_lift"):
                return meta.get("pattern")
    # Fallback to first block's first exercise
    if blocks and blocks[0].get("exercises"):
        ex = blocks[0]["exercises"][0]
        meta = catalog.get(ex)
        if meta:
            return meta.get("pattern")
    return None


def _parse_time(s: str) -> time:
    hh, mm = [int(x) for x in s.split(":", 1)]
    return time(hour=hh, minute=mm, tzinfo=timezone.utc)


def _in_no_go(dow: int, t: time, constraints: dict | None) -> bool:
    if not constraints:
        return False
    windows = constraints.get("no_go") or []
    for w in windows:
        try:
            if int(w.get("dow")) != dow:
                continue
            st = _parse_time(w.get("start"))
            en = _parse_time(w.get("end"))
            if st <= t <= en:
                return True
        except Exception:
            continue
    return False


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return (a_start < b_end) and (a_end > b_start)


def _has_conflict(db: Session, user_id: uuid.UUID, start: datetime, end: datetime) -> bool:
    # Any event overlapping window
    q = db.query(FitnessEvent).filter(
        FitnessEvent.user_id == user_id,
        FitnessEvent.starts_at < end,
        FitnessEvent.ends_at > start,
    )
    return db.query(q.exists()).scalar()


def _same_pattern_within(db: Session, user_id: uuid.UUID, pattern: str | None, start: datetime, window_hours: int = 24) -> bool:
    if not pattern:
        return False
    from datetime import timedelta as _td
    lo = start - _td(hours=window_hours)
    hi = start + _td(hours=window_hours)
    events = db.query(FitnessEvent).filter(
        FitnessEvent.user_id == user_id,
        FitnessEvent.source == "fitness",
        FitnessEvent.starts_at >= lo,
        FitnessEvent.starts_at <= hi,
    ).all()
    for ev in events:
        try:
            wid = ev.meta.get("workout_id") if ev.meta else None
            if not wid:
                continue
            wid = uuid.UUID(str(wid))
            owk = db.query(Workout).filter(Workout.id == wid).first()
            if owk and _workout_primary_pattern(owk) == pattern:
                return True
        except Exception:
            continue
    return False


def _propose_slot(db: Session, user_id: uuid.UUID, base_dt: datetime, duration_min: int, pattern: str | None, constraints: dict | None, seed_time: Optional[time] = None) -> Optional[datetime]:
    times: List[time] = []
    if constraints and constraints.get("preferred_times"):
        try:
            times = [_parse_time(t) for t in constraints["preferred_times"]]
        except Exception:
            times = []
    if not times:
        times = [seed_time] if seed_time else []
    if not times:
        times = [_parse_time("18:00")]

    # search next 7 days including today
    for day_offset in range(0, 7):
        target_date = (base_dt + timedelta(days=day_offset)).date()
        dow = target_date.weekday()
        for t in times:
            if _in_no_go(dow, t, constraints):
                continue
            start = datetime(target_date.year, target_date.month, target_date.day, t.hour, t.minute, tzinfo=timezone.utc)
            # ensure we don't go backward relative to base
            if start <= base_dt:
                continue
            end = start + timedelta(minutes=duration_min or 60)
            if _has_conflict(db, user_id, start, end):
                continue
            if _same_pattern_within(db, user_id, pattern, start, 24):
                continue
            return start
    return None

router = APIRouter()


# ----- Schemas (contracts only, no logic) -----

class PlanWorkoutBlock(BaseModel):
    exercises: List[str]
    sets: Optional[int] = None
    reps: Optional[str] = None
    intensity: Optional[str] = None
    rpe: Optional[str] = None
    rest: Optional[int] = None


class PlanWorkout(BaseModel):
    title: str
    duration_min: Optional[int] = None
    blocks: List[PlanWorkoutBlock] = Field(default_factory=list)


class PlanDraftRequest(BaseModel):
    profile: Dict[str, Any]
    goals: Dict[str, Any]
    constraints: Optional[Dict[str, Any]] = None
    equipment: Optional[List[str]] = None
    days_per_week: int
    session_len_min: int
    preferences: Optional[Dict[str, Any]] = None


class PlanDraftResponse(BaseModel):
    plan_id: str
    phases: List[str]
    weeks: int
    days: List[PlanWorkout]


class PlanCommitRequest(BaseModel):
    plan_id: str
    edits: Optional[Dict[str, Any]] = None


class PlanCommitResponse(BaseModel):
    workouts_created: int
    events_created: int
    summary: str


class MilestoneNotificationRequest(BaseModel):
    milestone_type: str = Field(..., description="Type of milestone reached")
    details: Dict[str, Any] = Field(default_factory=dict, description="Milestone details")


class ReadinessRequest(BaseModel):
    hrv_ms: Optional[int] = None
    rhr: Optional[int] = None
    sleep_hours: Optional[int] = None
    energy: int
    soreness: int
    stress: int
    time_available_min: int


class Adjustment(BaseModel):
    action: Literal['drop_sets', 'change_load', 'swap_block', 'trim_accessories', 'move_session']
    details: Dict[str, Any]


class ReadinessResponse(BaseModel):
    score: int
    recommendation: Literal['keep', 'reduce', 'swap', 'move']
    adjustments: List[Adjustment]
    message: str


class SetLogRequest(BaseModel):
    workout_id: UUID
    exercise_id: Optional[str]
    set_index: int
    weight: Optional[int]
    reps: Optional[int]
    rpe: Optional[int]
    notes: Optional[str]
    flags: Optional[Dict[str, Any]]


class SetLogResponse(BaseModel):
    accepted: bool
    autoreg_suggestion: Optional[Dict[str, Any]] = None
    next_set: Optional[Dict[str, Any]] = None


class PushSkipRequest(BaseModel):
    reason: str
    constraints: Optional[Dict[str, Any]] = None


class PushSkipResponse(BaseModel):
    proposed_slot: Optional[str] = None
    status: Literal['scheduled', 'floating', 'skipped']


# ----- Endpoints (stubs) -----


@router.post("/plan/propose", response_model=PlanDraftResponse)
async def propose_plan(
    payload: PlanDraftRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    gen = FitnessPlanGenerator()
    draft = gen.propose_plan(payload.dict())
    # Persist draft plan metadata
    plan = FitnessPlan(
        id=uuid.uuid4(),
        user_id=current_user.id,
        meta={
            "phases": draft["phases"],
            "weeks": draft["weeks"],
            "days": [d for d in draft["days"]],
        },
        status="draft",
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    return PlanDraftResponse(
        plan_id=str(plan.id),
        phases=draft["phases"],
        weeks=draft["weeks"],
        days=[PlanWorkout(**d) for d in draft["days"]],
    )


@router.post("/plan/commit", response_model=PlanCommitResponse)
async def commit_plan(
    payload: PlanCommitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Load plan
    plan: FitnessPlan | None = db.query(FitnessPlan).filter(
        FitnessPlan.id == uuid.UUID(payload.plan_id),
        FitnessPlan.user_id == current_user.id,
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    meta = plan.meta or {}
    days = meta.get("days", [])
    weeks = int(meta.get("weeks", 4))

    # Scheduling edits: start_date (YYYY-MM-DD), time (HH:MM, 24h)
    edits = payload.edits or {}
    sched = edits.get("schedule", {})
    start_date_str = sched.get("start_date")
    time_str = sched.get("time", "18:00")

    workouts_created = 0
    events_created = 0

    # Helper to parse time
    def parse_time(t: str) -> time:
        hh, mm = [int(x) for x in t.split(":", 1)]
        return time(hour=hh, minute=mm, tzinfo=timezone.utc)

    default_time = parse_time(time_str)

    # Commit workouts (and optionally events if schedule provided)
    for w in range(weeks):
        for day in days:
            dow = int(day.get("dow", 0))
            title = day.get("title", "Workout")
            duration_min = int(day.get("duration_min", 60))
            prescription = day.get("blocks", [])

            workout = Workout(
                id=uuid.uuid4(),
                user_id=current_user.id,
                plan_id=plan.id,
                title=title,
                phase=meta.get("phases", ["Base"])[0] if w < (weeks - 1) else meta.get("phases", ["Deload"])[-1],
                week=w + 1,
                day_of_week=dow,
                duration_min=duration_min,
                prescription=prescription,
                status="scheduled",
            )
            db.add(workout)
            workouts_created += 1

            # If schedule provided, create calendar event
            if start_date_str:
                start_dt = datetime.fromisoformat(start_date_str)
                # Align to week w and desired dow (0=Mon)
                # Calculate Monday of week 0
                start_monday = start_dt - timedelta(days=start_dt.weekday())
                target_date = start_monday + timedelta(weeks=w, days=dow)
                starts_at = datetime(
                    target_date.year, target_date.month, target_date.day,
                    default_time.hour, default_time.minute, tzinfo=timezone.utc
                )
                ends_at = starts_at + timedelta(minutes=duration_min)

                event = FitnessEvent(
                    id=uuid.uuid4(),
                    user_id=current_user.id,
                    title=title,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    description=f"Workout: {title}",
                    source="fitness",
                    status="planned",
                    meta={"workout_id": None},
                )
                db.add(event)
                db.flush()  # assign event.id
                workout.calendar_event_id = event.id
                event.meta = {"workout_id": str(workout.id)}
                events_created += 1

    plan.status = "active"
    db.commit()

    return PlanCommitResponse(
        workouts_created=workouts_created,
        events_created=events_created,
        summary=f"Committed plan {plan.id} with {workouts_created} workouts, {events_created} events",
    )


@router.post("/readiness", response_model=ReadinessResponse)
async def morning_readiness(
    payload: ReadinessRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engine = ReadinessEngine()
    result = await engine.score_and_adjust(db, current_user.id, payload.dict())
    # Persist entry
    from app.models.fitness import MorningReadiness
    entry = MorningReadiness(
        user_id=current_user.id,
        hrv_ms=payload.hrv_ms,
        rhr=payload.rhr,
        sleep_hours=payload.sleep_hours,
        energy=payload.energy,
        soreness=payload.soreness,
        stress=payload.stress,
        time_available_min=payload.time_available_min,
        score=result["score"],
        recommendation=result["recommendation"],
        adjustments=result.get("adjustments", []),
        message=result.get("message", ""),
    )
    db.add(entry)
    db.commit()
    return ReadinessResponse(**result)


@router.post("/workouts/{workout_id}/start")
async def start_workout(
    workout_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wk = db.query(Workout).filter(Workout.id == workout_id, Workout.user_id == current_user.id).first()
    if not wk:
        raise HTTPException(status_code=404, detail="Workout not found")
    session = {
        "state": "warmup",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "current_block": 0,
        "current_set": 0,
        "rest": {"active": False, "ends_at": None},
        "subs": {},
    }
    _sess_set(current_user.id, wk.id, session)
    return {"status": "started", "state": session["state"], "next": _compute_next_set(wk, session)}


@router.post("/workouts/{workout_id}/set", response_model=SetLogResponse)
async def log_set(
    workout_id: UUID,
    payload: SetLogRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wk = db.query(Workout).filter(Workout.id == workout_id, Workout.user_id == current_user.id).first()
    if not wk:
        raise HTTPException(status_code=404, detail="Workout not found")
    # Persist set log
    from app.models.fitness import WorkoutLog as WLog

    log = WLog(
        workout_id=wk.id,
        user_id=current_user.id,
        exercise_id=payload.exercise_id,
        set_index=payload.set_index,
        weight=payload.weight,
        reps=payload.reps,
        rpe=payload.rpe,
        notes=payload.notes or "",
        flags=payload.flags or {},
    )
    db.add(log)
    db.commit()

    # Advance session counters
    sess = _sess_get(current_user.id, wk.id)
    if not sess:
        sess = {"current_block": 0, "current_set": 0, "state": "working_set", "rest": {"active": False, "ends_at": None}, "subs": {}}
    else:
        sess["state"] = "working_set"
    blocks = wk.prescription or []
    bi = int(sess.get("current_block", 0))
    si = int(sess.get("current_set", 0)) + 1
    # Determine sets in current block
    total_sets = 0
    if bi < len(blocks):
        total_sets = int(blocks[bi].get("sets", 0) or 0)
    if si >= total_sets:
        # move to next block
        bi += 1
        si = 0
        if bi >= len(blocks):
            sess["state"] = "summary"
    sess["current_block"] = bi
    sess["current_set"] = si
    _sess_set(current_user.id, wk.id, sess)

    next_set = _compute_next_set(wk, sess)
    return SetLogResponse(accepted=True, autoreg_suggestion=None, next_set=next_set)


@router.post("/workouts/{workout_id}/rest/{action}")
async def rest_control(
    workout_id: UUID,
    action: Literal['start', 'end'],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wk = db.query(Workout).filter(Workout.id == workout_id, Workout.user_id == current_user.id).first()
    if not wk:
        raise HTTPException(status_code=404, detail="Workout not found")
    sess = _sess_get(current_user.id, wk.id)
    if not sess:
        sess = {"current_block": 0, "current_set": 0, "state": "working_set", "rest": {"active": False, "ends_at": None}, "subs": {}}
    if action == 'start':
        # derive rest from current block
        blocks = wk.prescription or []
        bi = int(sess.get("current_block", 0))
        rest_sec = 60
        if bi < len(blocks):
            rest_sec = int(blocks[bi].get("rest", 60) or 60)
        ends = datetime.now(timezone.utc) + timedelta(seconds=rest_sec)
        sess["state"] = "resting"
        sess["rest"] = {"active": True, "ends_at": ends.isoformat()}
        _sess_set(current_user.id, wk.id, sess)
        return {"status": "resting", "ends_at": ends.isoformat()}
    else:
        sess["state"] = "working_set"
        sess["rest"] = {"active": False, "ends_at": None}
        _sess_set(current_user.id, wk.id, sess)
        return {"status": "resumed"}


@router.post("/workouts/{workout_id}/substitute")
async def substitute_block(
    workout_id: UUID,
    payload: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wk = db.query(Workout).filter(Workout.id == workout_id, Workout.user_id == current_user.id).first()
    if not wk:
        raise HTTPException(status_code=404, detail="Workout not found")
    bi = int(payload.get("block_index", 0))
    from_ex = payload.get("from")
    to_ex = payload.get("to")
    if wk.prescription and 0 <= bi < len(wk.prescription) and from_ex and to_ex:
        block = wk.prescription[bi]
        exs = [str(x) for x in block.get("exercises", [])]
        block["exercises"] = [to_ex if e == from_ex else e for e in exs]
        db.add(wk)
        db.commit()
    # reflect in session subs map
    sess = _sess_get(current_user.id, wk.id) or {}
    subs = sess.get("subs", {})
    if from_ex and to_ex:
        subs[from_ex] = to_ex
    sess["subs"] = subs
    _sess_set(current_user.id, wk.id, sess)
    return {"status": "ok"}


@router.post("/workouts/{workout_id}/complete")
async def complete_workout(
    workout_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wk = db.query(Workout).filter(Workout.id == workout_id, Workout.user_id == current_user.id).first()
    if not wk:
        raise HTTPException(status_code=404, detail="Workout not found")
    # Set status
    wk.status = "completed"
    # Complete linked event if present
    if wk.calendar_event_id:
        ev = db.query(FitnessEvent).filter(FitnessEvent.id == wk.calendar_event_id, FitnessEvent.user_id == current_user.id).first()
        if ev:
            ev.status = "completed"
            db.add(ev)
    db.add(wk)
    db.commit()
    # Summary
    from app.models.fitness import WorkoutLog as WLog
    total_logs = db.query(WLog).filter(WLog.workout_id == wk.id, WLog.user_id == current_user.id).count()
    planned_sets = sum(int(b.get("sets", 0) or 0) for b in (wk.prescription or []))
    return {"status": "completed", "logged_sets": int(total_logs), "planned_sets": int(planned_sets)}


@router.post("/workouts/{workout_id}/push", response_model=PushSkipResponse)
async def push_workout(
    workout_id: UUID,
    payload: PushSkipRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wk = db.query(Workout).filter(Workout.id == workout_id, Workout.user_id == current_user.id).first()
    if not wk:
        raise HTTPException(status_code=404, detail="Workout not found")
    ev = None
    if wk.calendar_event_id:
        ev = db.query(FitnessEvent).filter(FitnessEvent.id == wk.calendar_event_id, FitnessEvent.user_id == current_user.id).first()
    base_dt = ev.starts_at if ev else datetime.now(timezone.utc)
    seed_time = base_dt.timetz() if ev else _parse_time("18:00")
    pattern = _workout_primary_pattern(wk)
    constraints = payload.constraints or {}
    proposed = _propose_slot(db, current_user.id, base_dt, wk.duration_min or 60, pattern, constraints, seed_time=seed_time)
    if not proposed:
        wk.status = "floating"
        if ev:
            ev.status = "cancelled"
            db.add(ev)
        db.add(wk)
        db.commit()
        return PushSkipResponse(proposed_slot=None, status="floating")
    # Move event (create if missing)
    if not ev:
        ev = FitnessEvent(
            id=uuid.uuid4(),
            user_id=current_user.id,
            title=wk.title,
            starts_at=proposed,
            ends_at=proposed + timedelta(minutes=wk.duration_min or 60),
            description=f"Workout: {wk.title}",
            source="fitness",
            status="planned",
            meta={"workout_id": str(wk.id)},
        )
        db.add(ev)
        db.flush()
        wk.calendar_event_id = ev.id
    else:
        ev.starts_at = proposed
        ev.ends_at = proposed + timedelta(minutes=wk.duration_min or 60)
        ev.status = "planned"
        if not ev.meta:
            ev.meta = {}
        ev.meta["workout_id"] = str(wk.id)
        db.add(ev)
    wk.status = "scheduled"
    db.add(wk)
    db.commit()
    return PushSkipResponse(proposed_slot=proposed.isoformat(), status="scheduled")


@router.post("/workouts/{workout_id}/skip", response_model=PushSkipResponse)
async def skip_workout(
    workout_id: UUID,
    payload: PushSkipRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    wk = db.query(Workout).filter(Workout.id == workout_id, Workout.user_id == current_user.id).first()
    if not wk:
        raise HTTPException(status_code=404, detail="Workout not found")
    ev = None
    if wk.calendar_event_id:
        ev = db.query(FitnessEvent).filter(FitnessEvent.id == wk.calendar_event_id, FitnessEvent.user_id == current_user.id).first()
        if ev:
            ev.status = "cancelled"
            db.add(ev)
    wk.status = "skipped"
    db.add(wk)
    db.commit()

    # Propose a reflow slot in next 7 days, using original time if any
    base_dt = datetime.now(timezone.utc)
    seed_time = ev.starts_at.timetz() if ev else _parse_time("18:00")
    pattern = _workout_primary_pattern(wk)
    constraints = payload.constraints or {}
    proposed = _propose_slot(db, current_user.id, base_dt, wk.duration_min or 60, pattern, constraints, seed_time=seed_time)
    if not proposed:
        return PushSkipResponse(proposed_slot=None, status="floating")
    # Create a new planned event for proposed slot but do not change workout until user confirms via push
    return PushSkipResponse(proposed_slot=proposed.isoformat(), status="skipped")


# ---------------- Privacy & Controls -----------------

class ExportFormat(str):
    json = "json"
    csv = "csv"


@router.get("/export")
async def export_fitness_data(
    fmt: str = "json",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.fitness import FitnessProfile, FitnessGoal, FitnessPlan, Workout, WorkoutLog, MorningReadiness

    profiles = db.query(FitnessProfile).filter(FitnessProfile.user_id == current_user.id).all()
    goals = db.query(FitnessGoal).filter(FitnessGoal.user_id == current_user.id).all()
    plans = db.query(FitnessPlan).filter(FitnessPlan.user_id == current_user.id).all()
    workouts = db.query(Workout).filter(Workout.user_id == current_user.id).all()
    logs = db.query(WorkoutLog).filter(WorkoutLog.user_id == current_user.id).all()
    readiness = db.query(MorningReadiness).filter(MorningReadiness.user_id == current_user.id).all()
    events = db.query(FitnessEvent).filter(FitnessEvent.user_id == current_user.id, FitnessEvent.source == 'fitness').all()

    def serialize(row):
        out = {}
        for k, v in row.__dict__.items():
            if k.startswith("_"):
                continue
            try:
                out[k] = str(v) if isinstance(v, uuid.UUID) else v
            except Exception:
                out[k] = None
        return out

    if fmt == ExportFormat.csv:
        import csv
        from io import StringIO
        tables = {
            "profiles": profiles,
            "goals": goals,
            "plans": plans,
            "workouts": workouts,
            "workout_logs": logs,
            "morning_readiness": readiness,
            "events": events,
        }
        csv_bundle = {}
        for name, rows in tables.items():
            if not rows:
                csv_bundle[name] = ""
                continue
            buf = StringIO()
            dicts = [serialize(r) for r in rows]
            fieldnames = sorted({k for d in dicts for k in d.keys()})
            w = csv.DictWriter(buf, fieldnames=fieldnames)
            w.writeheader()
            for d in dicts:
                w.writerow(d)
            csv_bundle[name] = buf.getvalue()
        return {"format": "csv", "tables": csv_bundle}

    # Default JSON export
    return {
        "format": "json",
        "profiles": [serialize(r) for r in profiles],
        "goals": [serialize(r) for r in goals],
        "plans": [serialize(r) for r in plans],
        "workouts": [serialize(r) for r in workouts],
        "workout_logs": [serialize(r) for r in logs],
        "morning_readiness": [serialize(r) for r in readiness],
        "events": [serialize(r) for r in events],
    }


@router.delete("/plan/{plan_id}")
async def delete_plan(
    plan_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = db.query(FitnessPlan).filter(FitnessPlan.id == plan_id, FitnessPlan.user_id == current_user.id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    # Gather workouts and delete linked events
    ws = db.query(Workout).filter(Workout.plan_id == plan.id, Workout.user_id == current_user.id).all()
    wids = {str(w.id) for w in ws}
    if wids:
        evs = db.query(FitnessEvent).filter(FitnessEvent.user_id == current_user.id, FitnessEvent.source == 'fitness').all()
        for ev in evs:
            wid = (ev.meta or {}).get("workout_id")
            if wid in wids:
                db.delete(ev)
        for w in ws:
            db.delete(w)
    db.delete(plan)
    db.commit()
    return {"status": "deleted", "plan_id": str(plan_id), "workouts_removed": len(ws)}


@router.post("/onboarding/reset")
async def reset_onboarding(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Clear any in-flight onboarding state in Redis
    try:
        r = _get_redis()
        if r:
            r.delete(f"fitness:onboarding:{current_user.id}")
    except Exception:
        pass
    # Optionally archive draft plans
    db.query(FitnessPlan).filter(FitnessPlan.user_id == current_user.id, FitnessPlan.status == 'draft').update({FitnessPlan.status: 'archived'})
    db.commit()
    return {"status": "reset"}


@router.post("/health/disconnect")
async def disconnect_health(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.profile import PrivacySettings
    settings = db.query(PrivacySettings).filter(PrivacySettings.user_id == str(current_user.id)).first()
    if not settings:
        settings = PrivacySettings(user_id=str(current_user.id))
        db.add(settings)
        db.flush()
    # Update data_categories to disable health
    cats = settings.data_categories or {}
    cats["health"] = False
    settings.data_categories = cats
    db.add(settings)
    db.commit()
    return {"status": "disconnected"}


# ----- Onboarding Endpoints -----

class OnboardingStartRequest(BaseModel):
    flow_type: str = "new_journey"

class OnboardingResponse(BaseModel):
    session_id: str
    step: str
    type: str
    message: str
    options: Optional[List[str]] = None
    fields: Optional[List[Dict[str, Any]]] = None
    progress: float
    can_go_back: bool

class OnboardingContinueRequest(BaseModel):
    response: Dict[str, Any]

class ChatOnboardingStartRequest(BaseModel):
    flow_type: str = "chat_onboarding"
    context: Optional[Dict[str, Any]] = None

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"] 
    content: str
    timestamp: Optional[str] = None

class ChatOnboardingResponse(BaseModel):
    session_id: str
    stage: str
    message: str
    progress: float
    can_go_back: bool = True
    completed: bool = False
    plan_draft_id: Optional[str] = None
    conversation_history: List[ChatMessage] = Field(default_factory=list)

class ChatContinueRequest(BaseModel):
    message: str
    context: Optional[Dict[str, Any]] = None

@router.post("/onboarding/start", response_model=OnboardingResponse)
async def start_fitness_onboarding(
    request: OnboardingStartRequest,
    current_user: User = Depends(get_current_user),
):
    """Start fitness onboarding flow"""
    try:
        onboarding_service = FitnessOnboardingService()
        result = onboarding_service.start_onboarding(
            user_id=str(current_user.id),
            flow_type=request.flow_type
        )
        return OnboardingResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start onboarding: {str(e)}"
        )

@router.post("/onboarding/{session_id}/continue", response_model=OnboardingResponse)
async def continue_fitness_onboarding(
    session_id: str,
    request: OnboardingContinueRequest,
    current_user: User = Depends(get_current_user),
):
    """Continue fitness onboarding with user response"""
    try:
        onboarding_service = FitnessOnboardingService()
        result = onboarding_service.continue_onboarding(
            session_id=session_id,
            response=request.response
        )
        
        if "error" in result:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )
        
        return OnboardingResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to continue onboarding: {str(e)}"
        )

@router.get("/onboarding/{session_id}/status")
async def get_onboarding_status(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    """Get current onboarding session status"""
    try:
        onboarding_service = FitnessOnboardingService()
        result = onboarding_service.get_session_status(session_id)
        
        if "error" in result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result["error"]
            )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get onboarding status: {str(e)}"
        )

@router.post("/onboarding/{session_id}/complete")
async def complete_fitness_onboarding(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    """Complete onboarding and save profile/goals to database"""
    try:
        onboarding_service = FitnessOnboardingService()
        result = onboarding_service.complete_onboarding(session_id)
        
        if "error" in result:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to complete onboarding: {str(e)}"
        )


# ----- Conversational Onboarding Endpoints -----

@router.post("/onboarding/chat/start", response_model=ChatOnboardingResponse)
async def start_chat_onboarding(
    request: ChatOnboardingStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start conversational fitness onboarding"""
    try:
        orchestrator = OnboardingOrchestrator(db)
        result = await orchestrator.start_conversation(
            user_id=current_user.id,
            flow_type=request.flow_type,
            context=request.context
        )
        
        if "error" in result:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )
        
        return ChatOnboardingResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start chat onboarding: {str(e)}"
        )

@router.post("/onboarding/chat/{session_id}/continue", response_model=ChatOnboardingResponse)
async def continue_chat_onboarding(
    session_id: str,
    request: ChatContinueRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Continue conversational fitness onboarding with user message"""
    try:
        orchestrator = OnboardingOrchestrator(db)
        result = await orchestrator.process_message(
            session_id=session_id,
            user_message=request.message,
            user_id=current_user.id,
            context=request.context
        )
        
        if "error" in result:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )
        
        return ChatOnboardingResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to continue chat onboarding: {str(e)}"
        )

@router.get("/onboarding/chat/{session_id}/status")
async def get_chat_onboarding_status(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current conversational onboarding session status"""
    try:
        orchestrator = OnboardingOrchestrator(db)
        result = await orchestrator.get_session_status(session_id, current_user.id)
        
        if "error" in result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result["error"]
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get chat onboarding status: {str(e)}"
        )

@router.post("/onboarding/chat/{session_id}/back")
async def go_back_chat_onboarding(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Go back to previous stage in conversational onboarding"""
    try:
        orchestrator = OnboardingOrchestrator(db)
        result = await orchestrator.go_back(session_id, current_user.id)
        
        if "error" in result:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )
        
        return ChatOnboardingResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to go back in chat onboarding: {str(e)}"
        )

@router.post("/onboarding/chat/{session_id}/complete", response_model=Dict[str, Any])
async def complete_chat_onboarding(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Complete conversational onboarding and save profile/goals"""
    try:
        orchestrator = OnboardingOrchestrator(db)
        result = await orchestrator.complete_onboarding(session_id, current_user.id)
        
        if "error" in result:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to complete chat onboarding: {str(e)}"
        )


# ----- Daily Readiness Endpoints -----

class ReadinessIntakeRequest(BaseModel):
    hrv_ms: Optional[int] = None
    rhr: Optional[int] = None
    sleep_hours: Optional[float] = None
    energy: int = Field(..., ge=1, le=5, description="Energy level 1-5")
    soreness: int = Field(..., ge=1, le=5, description="Muscle soreness 1-5") 
    stress: int = Field(..., ge=1, le=5, description="Stress level 1-5")
    time_available_min: int = Field(..., ge=10, le=240, description="Available workout time")
    notes: Optional[str] = None

class ReadinessResponse(BaseModel):
    readiness_id: str
    score: int
    recommendation: Literal["keep", "reduce", "swap", "move"]
    message: str
    adjustments: List[Dict[str, Any]]
    baseline_confidence: float
    today_workout: Optional[Dict[str, Any]] = None

class ReadinessHistoryResponse(BaseModel):
    readiness_entries: List[Dict[str, Any]]
    baseline_stats: Dict[str, Any]
    trends: Dict[str, Any]

@router.post("/readiness/daily", response_model=ReadinessResponse)
async def submit_daily_readiness(
    request: ReadinessIntakeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit daily readiness assessment and get workout adjustments"""
    try:
        readiness_engine = ReadinessEngine()
        
        # Convert request to dict for the engine
        readiness_input = {
            "hrv_ms": request.hrv_ms,
            "rhr": request.rhr, 
            "sleep_hours": request.sleep_hours,
            "energy": request.energy,
            "soreness": request.soreness,
            "stress": request.stress,
            "time_available_min": request.time_available_min
        }
        
        # Process readiness and get adjustments
        result = await readiness_engine.score_and_adjust(db, str(current_user.id), readiness_input)
        
        # Find today's workout if any
        today_workout = _find_todays_workout(db, str(current_user.id))
        if today_workout:
            result["today_workout"] = {
                "id": str(today_workout.id),
                "title": today_workout.title,
                "duration_min": today_workout.duration_min,
                "status": today_workout.status
            }
            
            # Generate workout adjustments based on readiness
            adjustment_service = WorkoutAdjustmentService()
            adjustments = await adjustment_service.generate_adjustments(
                db=db,
                user_id=str(current_user.id),
                readiness_score=result["score"],
                time_available_min=request.time_available_min,
                today_workout=today_workout
            )
            
            result["workout_adjustments"] = adjustments
        
        return ReadinessResponse(**result)
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process readiness: {str(e)}"
        )

@router.get("/readiness/history", response_model=ReadinessHistoryResponse)
async def get_readiness_history(
    days: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get readiness history and trends"""
    try:
        from app.models.fitness import MorningReadiness, ReadinessBaseline
        from sqlalchemy import desc
        
        # Get recent readiness entries
        readiness_entries = db.query(MorningReadiness).filter(
            MorningReadiness.user_id == str(current_user.id)
        ).order_by(desc(MorningReadiness.created_at)).limit(days).all()
        
        # Get baseline stats
        baseline = db.query(ReadinessBaseline).filter(
            ReadinessBaseline.user_id == str(current_user.id)
        ).first()
        
        # Format response
        entries_data = []
        for entry in readiness_entries:
            entries_data.append({
                "id": entry.id,
                "date": entry.created_at.date().isoformat(),
                "score": entry.score,
                "recommendation": entry.recommendation,
                "hrv_ms": entry.hrv_ms,
                "rhr": entry.rhr,
                "sleep_hours": entry.sleep_hours,
                "energy": entry.energy,
                "soreness": entry.soreness,
                "stress": entry.stress,
                "message": entry.message
            })
        
        baseline_stats = {}
        if baseline:
            baseline_stats = {
                "hrv_baseline": baseline.hrv_baseline,
                "rhr_baseline": baseline.rhr_baseline,
                "sleep_baseline": baseline.sleep_baseline,
                "sample_count": baseline.sample_count,
                "confidence": baseline.sample_count / 14 if baseline.sample_count < 14 else 1.0
            }
        
        # Calculate trends (simple implementation)
        trends = _calculate_readiness_trends(entries_data)
        
        return ReadinessHistoryResponse(
            readiness_entries=entries_data,
            baseline_stats=baseline_stats,
            trends=trends
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get readiness history: {str(e)}"
        )

@router.get("/readiness/today")
async def get_todays_readiness(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check if user has submitted today's readiness"""
    try:
        from app.models.fitness import MorningReadiness
        from sqlalchemy import func
        
        today = datetime.utcnow().date()
        
        todays_entry = db.query(MorningReadiness).filter(
            MorningReadiness.user_id == str(current_user.id),
            func.date(MorningReadiness.created_at) == today
        ).first()
        
        if todays_entry:
            return {
                "submitted": True,
                "readiness_id": todays_entry.id,
                "score": todays_entry.score,
                "recommendation": todays_entry.recommendation,
                "message": todays_entry.message
            }
        else:
            return {
                "submitted": False,
                "message": "Ready to assess your readiness for today?"
            }
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check today's readiness: {str(e)}"
        )

def _find_todays_workout(db: Session, user_id: str) -> Optional[Workout]:
    """Find today's scheduled workout"""
    today = datetime.utcnow().date()
    
    # Look for scheduled workouts for today
    workout = db.query(Workout).filter(
        Workout.user_id == user_id,
        Workout.status == "scheduled"
    ).first()  # Simplified - would need proper date filtering in real implementation
    
    return workout

def _calculate_readiness_trends(entries_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate readiness trends from recent entries"""
    if len(entries_data) < 3:
        return {"trend": "insufficient_data"}
    
    # Simple trend calculation - last 7 days vs previous 7 days
    recent_scores = [entry["score"] for entry in entries_data[:7]]
    previous_scores = [entry["score"] for entry in entries_data[7:14]] if len(entries_data) >= 14 else []
    
    recent_avg = sum(recent_scores) / len(recent_scores) if recent_scores else 0
    previous_avg = sum(previous_scores) / len(previous_scores) if previous_scores else recent_avg
    
    if recent_avg > previous_avg + 5:
        trend = "improving"
    elif recent_avg < previous_avg - 5:
        trend = "declining"
    else:
        trend = "stable"
    
    return {
        "trend": trend,
        "recent_avg": round(recent_avg, 1),
        "previous_avg": round(previous_avg, 1) if previous_scores else None,
        "green_days": len([s for s in recent_scores if s >= 80]),
        "yellow_days": len([s for s in recent_scores if 60 <= s < 80]), 
        "red_days": len([s for s in recent_scores if s < 60])
    }


# ----- HealthKit Integration Endpoints -----

class HealthKitDataRequest(BaseModel):
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    metrics: Dict[str, Any] = Field(..., description="Health metrics from HealthKit")
    samples: Optional[List[Dict[str, Any]]] = Field(default=None, description="Detailed HealthKit samples")

class HealthKitConfigResponse(BaseModel):
    required_permissions: List[Dict[str, Any]]
    optional_permissions: List[Dict[str, Any]]
    collection_settings: Dict[str, Any]
    data_quality: Dict[str, Any]

@router.post("/healthkit/data")
async def submit_healthkit_data(
    request: HealthKitDataRequest,
    current_user: User = Depends(get_current_user),
):
    """Accept HealthKit data from iOS app"""
    try:
        healthkit_service = HealthKitService()
        
        # Validate data first
        validation = await healthkit_service.validate_healthkit_data(request.dict())
        if not validation["valid"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid HealthKit data: {', '.join(validation['errors'])}"
            )
        
        # Process the data
        result = await healthkit_service.process_healthkit_data(
            user_id=str(current_user.id),
            healthkit_data=request.dict()
        )
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to process HealthKit data: {result.get('error', 'Unknown error')}"
            )
        
        response_data = {
            "success": True,
            "message": f"Processed {len(result.get('metrics_processed', []))} metrics for {result.get('date')}",
            "processed": result
        }
        
        # Include warnings if any
        if validation["warnings"]:
            response_data["warnings"] = validation["warnings"]
            
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"HealthKit data submission failed: {str(e)}"
        )

@router.get("/healthkit/config", response_model=HealthKitConfigResponse)
async def get_healthkit_config(
    current_user: User = Depends(get_current_user),
):
    """Get HealthKit configuration for iOS app setup"""
    try:
        healthkit_service = HealthKitService()
        config = await healthkit_service.get_healthkit_config(str(current_user.id))
        return HealthKitConfigResponse(**config)
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get HealthKit config: {str(e)}"
        )

@router.post("/healthkit/validate")
async def validate_healthkit_data(
    request: HealthKitDataRequest,
    current_user: User = Depends(get_current_user),
):
    """Validate HealthKit data before submission (optional pre-check)"""
    try:
        healthkit_service = HealthKitService()
        validation = await healthkit_service.validate_healthkit_data(request.dict())
        return validation
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"HealthKit data validation failed: {str(e)}"
        )

@router.get("/healthkit/sync-status")
async def get_healthkit_sync_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check HealthKit sync status and data recency"""
    try:
        from app.models.fitness import ReadinessBaseline
        from sqlalchemy import desc, func
        
        # Get most recent HealthKit data
        latest_baseline = db.query(ReadinessBaseline).filter(
            ReadinessBaseline.user_id == str(current_user.id),
            ReadinessBaseline.data_source == "healthkit"
        ).order_by(desc(ReadinessBaseline.date)).first()
        
        if not latest_baseline:
            return {
                "connected": False,
                "last_sync": None,
                "status": "no_data",
                "message": "No HealthKit data found. Please sync your iOS Health app."
            }
        
        days_ago = (datetime.utcnow().date() - latest_baseline.date).days
        
        if days_ago == 0:
            status = "current"
            message = "HealthKit data is up to date"
        elif days_ago == 1:
            status = "recent" 
            message = "HealthKit data from yesterday - consider syncing"
        elif days_ago <= 3:
            status = "stale"
            message = f"HealthKit data is {days_ago} days old - sync recommended"
        else:
            status = "outdated"
            message = f"HealthKit data is {days_ago} days old - manual entry may be needed"
        
        # Count total HealthKit entries
        total_entries = db.query(func.count(ReadinessBaseline.id)).filter(
            ReadinessBaseline.user_id == str(current_user.id),
            ReadinessBaseline.data_source == "healthkit"
        ).scalar()
        
        return {
            "connected": True,
            "last_sync": latest_baseline.date.isoformat(),
            "status": status,
            "message": message,
            "days_ago": days_ago,
            "total_entries": total_entries,
            "metrics_available": {
                "hrv": latest_baseline.hrv_ms is not None,
                "rhr": latest_baseline.rhr is not None,
                "sleep": latest_baseline.sleep_hours is not None
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check HealthKit sync status: {str(e)}"
        )


# ----- Manual Entry Endpoints -----

class ManualEntryRequest(BaseModel):
    entry_type: Literal["readiness", "health_metrics"] = Field(..., description="Type of entry to create")
    data: Dict[str, Any] = Field(..., description="Entry data based on template")

class ManualEntryResponse(BaseModel):
    success: bool
    message: str
    entry_id: Optional[str] = None
    baseline_updated: Optional[bool] = None
    action: Optional[str] = None

@router.post("/manual-entry", response_model=ManualEntryResponse)
async def create_manual_entry(
    request: ManualEntryRequest,
    current_user: User = Depends(get_current_user),
):
    """Create manual health/readiness entry for web and Android users"""
    try:
        manual_service = ManualEntryService()
        
        result = await manual_service.create_manual_entry(
            user_id=str(current_user.id),
            entry_type=request.entry_type,
            data=request.data
        )
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )
        
        return ManualEntryResponse(
            success=True,
            message=result["message"],
            entry_id=result.get("readiness_id") or result.get("baseline_id"),
            baseline_updated=result.get("baseline_updated"),
            action=result.get("action")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Manual entry creation failed: {str(e)}"
        )

@router.get("/manual-entry/template/{entry_type}")
async def get_manual_entry_template(
    entry_type: Literal["readiness", "health_metrics"],
    current_user: User = Depends(get_current_user),
):
    """Get form template for manual entry"""
    try:
        manual_service = ManualEntryService()
        template = await manual_service.get_manual_entry_template(entry_type)
        
        if "error" in template:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=template["error"]
            )
        
        return template
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get entry template: {str(e)}"
        )

@router.get("/manual-entry/history/{entry_type}")
async def get_manual_entry_history(
    entry_type: Literal["readiness", "health_metrics"],
    days: int = 30,
    current_user: User = Depends(get_current_user),
):
    """Get history of manual entries"""
    try:
        manual_service = ManualEntryService()
        history = await manual_service.get_entry_history(
            user_id=str(current_user.id),
            entry_type=entry_type,
            days=days
        )
        
        if "error" in history:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=history["error"]
            )
        
        return history
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get entry history: {str(e)}"
        )

@router.get("/data-sources/status")
async def get_data_sources_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get status of all data sources (HealthKit, manual, etc.)"""
    try:
        from app.models.fitness import ReadinessBaseline, MorningReadiness
        from sqlalchemy import func, desc
        
        # Check HealthKit status
        healthkit_data = db.query(ReadinessBaseline).filter(
            ReadinessBaseline.user_id == str(current_user.id),
            ReadinessBaseline.data_source == "healthkit"
        ).order_by(desc(ReadinessBaseline.date)).first()
        
        # Check manual entries
        manual_readiness_count = db.query(func.count(MorningReadiness.id)).filter(
            MorningReadiness.user_id == str(current_user.id),
            MorningReadiness.data_source == "manual"
        ).scalar()
        
        manual_baseline_count = db.query(func.count(ReadinessBaseline.id)).filter(
            ReadinessBaseline.user_id == str(current_user.id),
            ReadinessBaseline.data_source == "manual"
        ).scalar()
        
        # Get most recent entries
        latest_readiness = db.query(MorningReadiness).filter(
            MorningReadiness.user_id == str(current_user.id)
        ).order_by(desc(MorningReadiness.created_at)).first()
        
        return {
            "healthkit": {
                "connected": healthkit_data is not None,
                "last_sync": healthkit_data.date.isoformat() if healthkit_data else None,
                "total_entries": db.query(func.count(ReadinessBaseline.id)).filter(
                    ReadinessBaseline.user_id == str(current_user.id),
                    ReadinessBaseline.data_source == "healthkit"
                ).scalar()
            },
            "manual": {
                "readiness_entries": manual_readiness_count,
                "health_metrics_entries": manual_baseline_count,
                "last_entry": latest_readiness.created_at.date().isoformat() if latest_readiness else None
            },
            "recommendations": {
                "primary_source": "healthkit" if healthkit_data else "manual",
                "setup_needed": not healthkit_data and manual_readiness_count == 0,
                "message": self._get_setup_recommendation(healthkit_data, manual_readiness_count)
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get data sources status: {str(e)}"
        )

def _get_setup_recommendation(healthkit_data, manual_count: int) -> str:
    """Get setup recommendation based on current data sources"""
    if healthkit_data:
        if manual_count > 0:
            return "You have both HealthKit and manual entries. HealthKit provides more accurate baseline tracking."
        return "HealthKit is connected and providing health data automatically."
    elif manual_count > 0:
        return f"You have {manual_count} manual entries. Consider connecting HealthKit for automatic data sync."
    else:
        return "No health data found. Set up HealthKit (iOS) or use manual entry to start tracking readiness."


# ----- Baseline Learning Endpoints -----

@router.get("/baselines/status")
async def get_baseline_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current baseline learning status and recommendations"""
    try:
        baseline_engine = BaselineLearningEngine()
        status = await baseline_engine.get_baseline_status(db, str(current_user.id))
        return status
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get baseline status: {str(e)}"
        )

@router.post("/baselines/update")
async def manual_baseline_update(
    metrics: Dict[str, Any],
    target_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually trigger baseline update with specific metrics"""
    try:
        baseline_engine = BaselineLearningEngine()
        
        # Parse target date or use today
        if target_date:
            update_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        else:
            update_date = datetime.utcnow().date()
        
        result = await baseline_engine.update_user_baselines(
            db, str(current_user.id), update_date, metrics
        )
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )
        
        db.commit()
        return {
            "success": True,
            "message": "Baseline updated successfully",
            "updates": result["updates"],
            "confidence": result["confidence"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Manual baseline update failed: {str(e)}"
        )

@router.post("/baselines/reset")
async def reset_baselines(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reset user's baselines to start fresh learning"""
    try:
        from app.models.fitness import ReadinessBaseline
        
        # Delete existing baselines
        db.query(ReadinessBaseline).filter(
            ReadinessBaseline.user_id == str(current_user.id)
        ).delete()
        
        db.commit()
        
        return {
            "success": True,
            "message": "Baselines reset successfully. Start logging health data to establish new baselines."
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset baselines: {str(e)}"
        )

@router.get("/baselines/history")
async def get_baseline_history(
    days: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get baseline learning history and trends"""
    try:
        from app.models.fitness import ReadinessBaseline
        from sqlalchemy import desc
        
        baselines = db.query(ReadinessBaseline).filter(
            ReadinessBaseline.user_id == str(current_user.id)
        ).order_by(desc(ReadinessBaseline.date)).limit(days).all()
        
        baseline_data = []
        for baseline in baselines:
            baseline_data.append({
                "date": baseline.date.isoformat(),
                "hrv_baseline": baseline.hrv_baseline,
                "rhr_baseline": baseline.rhr_baseline, 
                "sleep_baseline": baseline.sleep_baseline,
                "sample_count": baseline.sample_count,
                "confidence_score": baseline.confidence_score,
                "data_source": baseline.data_source,
                "last_updated": baseline.last_updated.isoformat() if baseline.last_updated else None
            })
        
        # Calculate trends if we have enough data
        trends = {}
        if len(baseline_data) >= 7:
            # Simple trend calculation over recent data
            recent_data = baseline_data[:7]
            older_data = baseline_data[7:14] if len(baseline_data) >= 14 else []
            
            for metric in ['hrv_baseline', 'rhr_baseline', 'sleep_baseline']:
                recent_values = [b[metric] for b in recent_data if b[metric] is not None]
                older_values = [b[metric] for b in older_data if b[metric] is not None]
                
                if recent_values and older_values:
                    recent_avg = sum(recent_values) / len(recent_values)
                    older_avg = sum(older_values) / len(older_values)
                    
                    if metric == 'rhr_baseline':
                        # For RHR, lower is better
                        trend = "improving" if recent_avg < older_avg else "declining"
                    else:
                        # For HRV and sleep, higher is better
                        trend = "improving" if recent_avg > older_avg else "declining"
                    
                    trends[metric] = {
                        "trend": trend,
                        "recent_avg": round(recent_avg, 2),
                        "older_avg": round(older_avg, 2)
                    }
        
        return {
            "baselines": baseline_data,
            "trends": trends,
            "total_count": len(baseline_data)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get baseline history: {str(e)}"
        )


# ----- Workout Adjustment Endpoints -----

class AdjustmentApprovalRequest(BaseModel):
    adjustment_id: str = Field(..., description="ID of the adjustment to apply")
    approved: bool = Field(..., description="Whether user approves the adjustment")
    custom_modifications: Optional[Dict[str, Any]] = Field(default=None, description="User's custom modifications")

@router.get("/adjustments/{workout_id}")
async def get_workout_adjustments(
    workout_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get available adjustments for a specific workout"""
    try:
        from app.models.fitness import ReadinessAdjustment
        
        # Get all adjustments for this workout
        adjustments = db.query(ReadinessAdjustment).filter(
            ReadinessAdjustment.workout_id == workout_id,
            ReadinessAdjustment.user_id == str(current_user.id)
        ).order_by(desc(ReadinessAdjustment.created_at)).all()
        
        adjustment_data = []
        for adj in adjustments:
            adjustment_data.append({
                "id": str(adj.id),
                "strategy": adj.strategy,
                "readiness_score": adj.readiness_score,
                "adjustments": adj.proposed_adjustments,
                "status": adj.status,
                "created_at": adj.created_at.isoformat(),
                "applied_at": adj.applied_at.isoformat() if adj.applied_at else None,
                "user_confirmed": adj.user_confirmed
            })
        
        return {
            "workout_id": workout_id,
            "adjustments": adjustment_data,
            "total_count": len(adjustment_data)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get workout adjustments: {str(e)}"
        )

@router.post("/adjustments/apply")
async def apply_workout_adjustment(
    request: AdjustmentApprovalRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Apply approved workout adjustments"""
    try:
        adjustment_service = WorkoutAdjustmentService()
        
        if request.approved:
            result = await adjustment_service.apply_adjustments(
                db=db,
                adjustment_id=request.adjustment_id,
                user_confirmation=True
            )
            
            if not result["success"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=result["error"]
                )
            
            return {
                "success": True,
                "message": "Adjustments applied successfully",
                "changes": result["changes_applied"],
                "adjustment_id": request.adjustment_id
            }
        else:
            # User declined adjustments - mark as declined
            from app.models.fitness import ReadinessAdjustment
            
            adjustment = db.query(ReadinessAdjustment).filter(
                ReadinessAdjustment.id == request.adjustment_id
            ).first()
            
            if adjustment:
                adjustment.status = "declined"
                adjustment.user_confirmed = False
                db.add(adjustment)
                db.commit()
            
            return {
                "success": True,
                "message": "Adjustments declined - proceeding with original workout",
                "adjustment_id": request.adjustment_id
            }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to apply adjustment: {str(e)}"
        )

@router.post("/adjustments/generate/{workout_id}")
async def generate_manual_adjustments(
    workout_id: str,
    readiness_score: int = Query(..., ge=0, le=100, description="Manual readiness score"),
    time_available_min: int = Query(..., ge=10, le=240, description="Available time for workout"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually generate adjustments for a workout (not based on daily readiness)"""
    try:
        # Get the workout
        workout = db.query(Workout).filter(
            Workout.id == workout_id,
            Workout.user_id == str(current_user.id)
        ).first()
        
        if not workout:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workout not found"
            )
        
        adjustment_service = WorkoutAdjustmentService()
        adjustments = await adjustment_service.generate_adjustments(
            db=db,
            user_id=str(current_user.id),
            readiness_score=readiness_score,
            time_available_min=time_available_min,
            today_workout=workout
        )
        
        db.commit()
        return adjustments
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate adjustments: {str(e)}"
        )

@router.get("/adjustments/history")
async def get_adjustment_history(
    days: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get history of workout adjustments"""
    try:
        from app.models.fitness import ReadinessAdjustment
        
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        adjustments = db.query(ReadinessAdjustment).filter(
            ReadinessAdjustment.user_id == str(current_user.id),
            ReadinessAdjustment.created_at >= cutoff_date
        ).order_by(desc(ReadinessAdjustment.created_at)).all()
        
        # Group by strategy for analytics
        strategy_counts = {}
        total_applied = 0
        
        adjustment_data = []
        for adj in adjustments:
            strategy = adj.strategy
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
            
            if adj.status == "applied":
                total_applied += 1
                
            adjustment_data.append({
                "id": str(adj.id),
                "workout_id": str(adj.workout_id),
                "strategy": strategy,
                "readiness_score": adj.readiness_score,
                "status": adj.status,
                "created_at": adj.created_at.date().isoformat(),
                "applied": adj.status == "applied",
                "user_confirmed": adj.user_confirmed
            })
        
        return {
            "adjustments": adjustment_data,
            "analytics": {
                "total_adjustments": len(adjustment_data),
                "applied_count": total_applied,
                "strategy_breakdown": strategy_counts,
                "application_rate": round(total_applied / len(adjustment_data) * 100, 1) if adjustment_data else 0
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get adjustment history: {str(e)}"
        )


# ----- Notification Endpoints -----

@router.post("/notifications/setup")
async def setup_fitness_notifications(
    device_info: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(get_current_user),
):
    """Set up fitness notifications for the user"""
    try:
        notification_service = FitnessNotificationService()
        result = await notification_service.subscribe_user_to_fitness_notifications(
            user_id=str(current_user.id),
            device_info=device_info
        )
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to set up notifications: {str(e)}"
        )

@router.post("/notifications/test/{notification_type}")
async def test_fitness_notification(
    notification_type: Literal["readiness_reminder", "adjustment_alert", "workout_reminder", "baseline_milestone"],
    message: Optional[str] = "Test notification from Sara Fitness",
    current_user: User = Depends(get_current_user),
):
    """Send a test notification to verify setup"""
    try:
        notification_service = FitnessNotificationService()
        result = await notification_service.send_notification(
            user_id=str(current_user.id),
            notification_type=notification_type,
            message=message,
            data={"test": True, "timestamp": datetime.utcnow().isoformat()}
        )
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send test notification: {str(e)}"
        )

@router.post("/notifications/run-checks")
async def run_notification_checks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually trigger notification checks (admin/testing)"""
    try:
        # Only allow this for testing/admin purposes
        # In production, this would be run by a scheduled task
        
        notification_service = FitnessNotificationService()
        results = await notification_service.run_notification_checks(db)
        
        return {
            "success": True,
            "message": "Notification checks completed",
            "results": results
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to run notification checks: {str(e)}"
        )

@router.post("/notifications/milestone")
async def send_baseline_milestone(
    request: MilestoneNotificationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a baseline milestone notification"""
    try:
        notification_service = FitnessNotificationService()
        result = await notification_service.send_baseline_milestone(
            db=db,
            user_id=str(current_user.id),
            milestone_type=request.milestone_type,
            details=request.details
        )
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send milestone notification: {str(e)}"
        )

@router.get("/notifications/schedule")
async def get_notification_schedule(
    current_user: User = Depends(get_current_user),
):
    """Get the current notification schedule and preferences"""
    try:
        notification_service = FitnessNotificationService()
        
        schedule = {
            "readiness_reminder": {
                "time": "8:00 AM",
                "frequency": "daily",
                "condition": "if workout scheduled",
                "description": "Reminder to submit daily readiness assessment"
            },
            "workout_reminder": {
                "time": "5:00 PM",
                "frequency": "day before workout",
                "condition": "if workout scheduled next day",
                "description": "Reminder about tomorrow's workout"
            },
            "adjustment_alert": {
                "time": "immediate",
                "frequency": "as needed",
                "condition": "after readiness submission with adjustments",
                "description": "Alert about recommended workout adjustments"
            },
            "baseline_milestone": {
                "time": "variable",
                "frequency": "weekly/milestone-based",
                "condition": "when baseline learning milestones reached",
                "description": "Updates on baseline learning progress"
            }
        }
        
        return {
            "user_id": str(current_user.id),
            "schedule": schedule,
            "topic": f"{notification_service.fitness_topic}_{current_user.id}",
            "setup_instructions": {
                "mobile": "Install NTFY app and subscribe to your fitness topic",
                "web": "Visit ntfy.sh and subscribe to your fitness topic",
                "topic_url": f"{notification_service.ntfy_base_url}/{notification_service.fitness_topic}_{current_user.id}"
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get notification schedule: {str(e)}"
        )
