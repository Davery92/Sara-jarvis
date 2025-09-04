from typing import Any, Dict, Optional, List
from app.tools.base import BaseTool, ToolResult
from app.db.session import SessionLocal
from app.models.fitness import FitnessProfile, FitnessGoal, Workout, FitnessEvent
from app.services.fitness.generator_service import FitnessPlanGenerator
from app.services.fitness.readiness_service import ReadinessEngine
from datetime import datetime, time as dt_time
import uuid
import os
import httpx
from app.core.config import settings


class FitnessSaveProfileTool(BaseTool):
    @property
    def name(self) -> str:
        return "fitness.save_profile"

    @property
    def description(self) -> str:
        return "Validate and persist a user's fitness profile (demographics, equipment, preferences, constraints)."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "profile": {
                    "type": "object",
                    "description": "Profile data including demographics, equipment, preferences, constraints",
                }
            },
            "required": ["profile"],
            "additionalProperties": False,
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            # Optional API-first path when access_token provided
            token: Optional[str] = kwargs.get("access_token")
            if token:
                base = os.getenv("BASE_URL") or settings.backend_url or "http://localhost:8000"
                async with httpx.AsyncClient(base_url=base, timeout=30.0, headers={"Authorization": f"Bearer {token}"}) as client:
                    payload = {"profile": kwargs.get("profile") or {}}
                    r = await client.post("/fitness/profile", json=payload)
                    if r.status_code // 100 == 2:
                        return ToolResult(success=True, message="profile saved (api)")
                    return ToolResult(success=False, message=f"api error: {r.status_code} {r.text}")

            profile_data = kwargs.get("profile") or {}
            db = SessionLocal()
            try:
                # upsert user's profile
                existing = db.query(FitnessProfile).filter(FitnessProfile.user_id == uuid.UUID(user_id)).first()
                if existing:
                    existing.demographics = profile_data.get("demographics")
                    existing.equipment = profile_data.get("equipment")
                    existing.preferences = profile_data.get("preferences")
                    existing.constraints = profile_data.get("constraints")
                else:
                    rec = FitnessProfile(
                        user_id=uuid.UUID(user_id),
                        demographics=profile_data.get("demographics"),
                        equipment=profile_data.get("equipment"),
                        preferences=profile_data.get("preferences"),
                        constraints=profile_data.get("constraints"),
                    )
                    db.add(rec)
                db.commit()
                return ToolResult(success=True, message="profile saved")
            finally:
                db.close()
        except Exception as e:
            return ToolResult(success=False, message=f"save_profile failed: {e}")


class FitnessSaveGoalsTool(BaseTool):
    @property
    def name(self) -> str:
        return "fitness.save_goals"

    @property
    def description(self) -> str:
        return "Persist fitness goals and targets for the user."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goals": {
                    "type": "object",
                    "description": "Goal object with goal_type, targets, timeframe",
                }
            },
            "required": ["goals"],
            "additionalProperties": False,
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            token: Optional[str] = kwargs.get("access_token")
            if token:
                base = os.getenv("BASE_URL") or settings.backend_url or "http://localhost:8000"
                async with httpx.AsyncClient(base_url=base, timeout=30.0, headers={"Authorization": f"Bearer {token}"}) as client:
                    payload = {"goals": kwargs.get("goals") or {}}
                    r = await client.post("/fitness/goals", json=payload)
                    if r.status_code // 100 == 2:
                        return ToolResult(success=True, data=r.json())
                    return ToolResult(success=False, message=f"api error: {r.status_code} {r.text}")

            goals = kwargs.get("goals") or {}
            db = SessionLocal()
            try:
                rec = FitnessGoal(
                    user_id=uuid.UUID(user_id),
                    goal_type=goals.get("goal_type") or "general",
                    targets=goals.get("targets"),
                    timeframe=goals.get("timeframe"),
                    status=goals.get("status") or "active",
                )
                db.add(rec)
                db.commit()
                return ToolResult(success=True, data={"goal_id": str(rec.id)})
            finally:
                db.close()
        except Exception as e:
            return ToolResult(success=False, message=f"save_goals failed: {e}")


class FitnessProposePlanTool(BaseTool):
    @property
    def name(self) -> str:
        return "fitness.propose_plan"

    @property
    def description(self) -> str:
        return "Generate a draft fitness plan from profile, goals, and constraints."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "profile": {"type": "object"},
                "goals": {"type": "object"},
                "constraints": {"type": "object"},
                "equipment": {"type": "array", "items": {"type": "string"}},
                "days_per_week": {"type": "integer", "minimum": 1, "maximum": 7},
                "session_len_min": {"type": "integer", "minimum": 20, "maximum": 180},
                "preferences": {"type": "object"},
            },
            "required": ["profile", "goals"],
            "additionalProperties": False,
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            token: Optional[str] = kwargs.get("access_token")
            if token:
                base = os.getenv("BASE_URL") or settings.backend_url or "http://localhost:8000"
                async with httpx.AsyncClient(base_url=base, timeout=60.0, headers={"Authorization": f"Bearer {token}"}) as client:
                    payload = {
                        "profile": kwargs.get("profile") or {},
                        "goals": kwargs.get("goals") or {},
                        "constraints": kwargs.get("constraints") or {},
                        "equipment": kwargs.get("equipment") or [],
                        "days_per_week": kwargs.get("days_per_week") or 3,
                        "session_len_min": kwargs.get("session_len_min") or 60,
                        "preferences": kwargs.get("preferences") or {},
                    }
                    r = await client.post("/fitness/plan/propose", json=payload)
                    if r.status_code // 100 == 2:
                        return ToolResult(success=True, data=r.json())
                    return ToolResult(success=False, message=f"api error: {r.status_code} {r.text}")

            payload = {
                "profile": kwargs.get("profile") or {},
                "goals": kwargs.get("goals") or {},
                "constraints": kwargs.get("constraints") or {},
                "equipment": kwargs.get("equipment") or [],
                "days_per_week": kwargs.get("days_per_week") or 3,
                "session_len_min": kwargs.get("session_len_min") or 60,
                "preferences": kwargs.get("preferences") or {},
            }
            gen = FitnessPlanGenerator()
            tpl = gen._select_template(payload)
            days = gen._substitute_exercises(tpl.get("days", []), payload.get("equipment"))
            # Apply time cap
            time_capped: List[Dict[str, Any]] = []
            for d in days:
                time_capped.append(gen._apply_time_cap(d, payload.get("session_len_min"), gen._load_catalog()))
            plan_id = str(uuid.uuid4())
            out = {
                "plan_id": plan_id,
                "phases": tpl.get("phases", []),
                "weeks": tpl.get("weeks", 4),
                "days": time_capped,
            }
            return ToolResult(success=True, data=out)
        except Exception as e:
            return ToolResult(success=False, message=f"propose_plan failed: {e}")


class FitnessCommitPlanTool(BaseTool):
    @property
    def name(self) -> str:
        return "fitness.commit_plan"

    @property
    def description(self) -> str:
        return "Commit a draft plan: persist workouts and create calendar events."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string"},
                "edits": {"type": "object"},
            },
            "required": ["plan_id"],
            "additionalProperties": False,
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            token: Optional[str] = kwargs.get("access_token")
            if token:
                base = os.getenv("BASE_URL") or settings.backend_url or "http://localhost:8000"
                async with httpx.AsyncClient(base_url=base, timeout=60.0, headers={"Authorization": f"Bearer {token}"}) as client:
                    payload = {"plan_id": kwargs.get("plan_id"), "edits": kwargs.get("edits") or {}}
                    r = await client.post("/fitness/plan/commit", json=payload)
                    if r.status_code // 100 == 2:
                        return ToolResult(success=True, data=r.json())
                    return ToolResult(success=False, message=f"api error: {r.status_code} {r.text}")

            plan_id = kwargs.get("plan_id")
            edits = kwargs.get("edits") or {}
            schedule = (edits.get("schedule") or {})
            start_date = schedule.get("start_date")  # YYYY-MM-DD
            t_str = schedule.get("time") or "18:00"
            try:
                hh, mm = [int(x) for x in str(t_str).split(":", 1)]
            except Exception:
                hh, mm = 18, 0
            t_pref = dt_time(hour=hh, minute=mm)

            # Expect a plan JSON to commit — for now, require caller to provide 'days' in edits.plan
            plan = edits.get("plan")
            if not plan or not plan.get("days"):
                return ToolResult(success=False, message="commit requires edits.plan.days array")

            db = SessionLocal()
            try:
                # Persist workouts and optional calendar events
                created: List[Dict[str, Any]] = []
                cur_date = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
                for idx, day in enumerate(plan["days"]):
                    title = day.get("title") or f"Workout {idx+1}"
                    duration = day.get("duration_min") or 60
                    w = Workout(
                        user_id=uuid.UUID(user_id),
                        plan_id=None,
                        title=title,
                        phase=None,
                        week=None,
                        day_of_week=None,
                        duration_min=duration,
                        prescription=day.get("blocks") or [],
                        status="scheduled",
                    )
                    db.add(w)
                    db.flush()

                    ev_id = None
                    if cur_date:
                        starts = datetime.combine(cur_date, t_pref, tzinfo=None)
                        ev = FitnessEvent(
                            id=str(uuid.uuid4()),
                            user_id=str(user_id),
                            title=title,
                            starts_at=starts,
                            ends_at=starts + kwargs.get("event_duration", None) or (datetime.min - datetime.min + (datetime.min.replace(hour=0, minute=duration) - datetime.min)),
                            location="",
                            description="",
                            source="fitness",
                            status="scheduled",
                            meta={"workout_id": str(w.id)},
                        )
                        db.add(ev)
                        ev_id = ev.id
                        w.calendar_event_id = ev.id
                        # increment date by 1 day for next workout
                        from datetime import timedelta as _td
                        cur_date = cur_date + _td(days=1)

                    created.append({"workout_id": str(w.id), "calendar_event_id": ev_id})
                db.commit()
                return ToolResult(success=True, data={"created": created})
            finally:
                db.close()
        except Exception as e:
            return ToolResult(success=False, message=f"commit_plan failed: {e}")


class FitnessAdjustTodayTool(BaseTool):
    @property
    def name(self) -> str:
        return "fitness.adjust_today"

    @property
    def description(self) -> str:
        return "Apply morning readiness inputs to adjust today's session (keep/reduce/swap/move)."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "hrv_ms": {"type": "integer"},
                "rhr": {"type": "integer"},
                "sleep_hours": {"type": "number"},
                "energy": {"type": "integer", "minimum": 1, "maximum": 5},
                "soreness": {"type": "integer", "minimum": 1, "maximum": 5},
                "stress": {"type": "integer", "minimum": 1, "maximum": 5},
                "time_available_min": {"type": "integer", "minimum": 10, "maximum": 240},
            },
            "required": ["energy", "soreness", "stress", "time_available_min"],
            "additionalProperties": False,
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            token: Optional[str] = kwargs.get("access_token")
            if token:
                base = os.getenv("BASE_URL") or settings.backend_url or "http://localhost:8000"
                async with httpx.AsyncClient(base_url=base, timeout=30.0, headers={"Authorization": f"Bearer {token}"}) as client:
                    r = await client.post("/fitness/readiness", json=kwargs)
                    if r.status_code // 100 == 2:
                        return ToolResult(success=True, data=r.json())
                    return ToolResult(success=False, message=f"api error: {r.status_code} {r.text}")

            db = SessionLocal()
            try:
                engine = ReadinessEngine()
                result = engine.score_and_adjust(db, uuid.UUID(user_id), kwargs)
                return ToolResult(success=True, data=result)
            finally:
                db.close()
        except Exception as e:
            return ToolResult(success=False, message=f"adjust_today failed: {e}")
