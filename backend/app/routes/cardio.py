"""
Cardio Routes
API for the cardio tracker — the strength tracker's sibling, but cardio-shaped
(minutes / distance / HR / zone instead of sets & reps).

Mounted at /api/fitness/cardio. Single-user (SOLO_USER_ID) like the rest of fitness.

Endpoints:
  GET    /logs                 list cardio sessions (default: current week)
  POST   /log                  create a cardio session
  PATCH  /log/{id}             edit a session
  DELETE /log/{id}             delete a session
  GET    /stats                weekly dose vs target + by-activity + steps floor + 8-week trend
  GET    /settings             weekly target + steps floor + the density-engine menu
  PUT    /settings             update settings
  GET    /tabata-presets       saved interval timers (seeds built-ins on first load)
  POST   /tabata-presets       create a custom interval timer
  PATCH  /tabata-presets/{id}  edit a preset
  DELETE /tabata-presets/{id}  delete a preset
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
import asyncio
import uuid
import json
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.timezone import now as local_now, today as local_today
from app.routes.fitness import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_ACTIVITIES = {
    "walk", "ruck", "kb_swings", "coaching", "commute",
    "run", "row", "bike", "tabata", "hike", "cycle", "other",
}

# The Forge "density engine" menu — seeded per user, editable via PUT /settings.
DEFAULT_MENU: List[Dict[str, Any]] = [
    {"key": "walk", "label": "Fragmented walk", "typical_minutes": 15, "worth_minutes": 15,
     "note": "Pre-9 / lunch / post-5 — fragments count fully."},
    {"key": "ruck", "label": "Ruck / hilly walk", "typical_minutes": 50, "worth_minutes": 50,
     "note": "The gold standard when life allows."},
    {"key": "kb_swings", "label": "KB swings EMOM", "typical_minutes": 12, "worth_minutes": 30,
     "note": "10 swings/min × 12 min ≈ 30 min equivalent — they buy efficiency."},
    {"key": "coaching", "label": "Active coaching", "typical_minutes": 40, "worth_minutes": 40,
     "note": "Early arrival, BP, fungoes — on your feet."},
    {"key": "commute", "label": "Commute buffer", "typical_minutes": 10, "worth_minutes": 10,
     "note": "Park 10 min out, or a 10-min loop before dinner."},
    {"key": "run", "label": "Zone 2 run/row/bike", "typical_minutes": 30, "worth_minutes": 30,
     "note": "Conversational pace — able to talk, not sing."},
]

# Built-in interval timers — seeded once per user, fully editable/deletable after.
DEFAULT_PRESETS: List[Dict[str, Any]] = [
    {"name": "Classic Tabata", "prepare_seconds": 10, "work_seconds": 20, "rest_seconds": 10,
     "rounds": 8, "sets": 1, "rest_between_sets_seconds": 60, "activity_type": "tabata",
     "color": "#ef4444", "sort_order": 0},
    {"name": "KB Swings EMOM", "prepare_seconds": 10, "work_seconds": 40, "rest_seconds": 20,
     "rounds": 12, "sets": 1, "rest_between_sets_seconds": 0, "activity_type": "kb_swings",
     "color": "#f59e0b", "sort_order": 1},
    {"name": "1-Minute Intervals", "prepare_seconds": 10, "work_seconds": 60, "rest_seconds": 60,
     "rounds": 8, "sets": 1, "rest_between_sets_seconds": 0, "activity_type": "tabata",
     "color": "#06b6d4", "sort_order": 2},
    {"name": "HIIT 30/30", "prepare_seconds": 10, "work_seconds": 30, "rest_seconds": 30,
     "rounds": 10, "sets": 1, "rest_between_sets_seconds": 0, "activity_type": "tabata",
     "color": "#8b5cf6", "sort_order": 3},
]


# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #
class CardioLogCreate(BaseModel):
    activity_type: str
    title: Optional[str] = ""
    duration_minutes: float
    distance_miles: Optional[float] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    zone: Optional[str] = None
    calories_burned: Optional[float] = None
    rpe: Optional[int] = None
    source: Optional[str] = "manual"
    tabata_detail: Optional[Dict[str, Any]] = None
    notes: Optional[str] = ""
    session_date: Optional[str] = None   # YYYY-MM-DD, defaults to local today
    logged_at: Optional[str] = None      # ISO, defaults to now


class CardioLogUpdate(BaseModel):
    activity_type: Optional[str] = None
    title: Optional[str] = None
    duration_minutes: Optional[float] = None
    distance_miles: Optional[float] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    zone: Optional[str] = None
    calories_burned: Optional[float] = None
    rpe: Optional[int] = None
    notes: Optional[str] = None
    session_date: Optional[str] = None


class CardioSettingsUpdate(BaseModel):
    weekly_min_minutes: Optional[int] = None
    weekly_max_minutes: Optional[int] = None
    steps_floor: Optional[int] = None
    menu: Optional[List[Dict[str, Any]]] = None


class TabataPresetCreate(BaseModel):
    name: str
    prepare_seconds: int = 10
    work_seconds: int
    rest_seconds: int
    rounds: int
    sets: int = 1
    rest_between_sets_seconds: int = 60
    activity_type: str = "tabata"
    color: Optional[str] = None


class TabataPresetUpdate(BaseModel):
    name: Optional[str] = None
    prepare_seconds: Optional[int] = None
    work_seconds: Optional[int] = None
    rest_seconds: Optional[int] = None
    rounds: Optional[int] = None
    sets: Optional[int] = None
    rest_between_sets_seconds: Optional[int] = None
    activity_type: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date '{s}'. Use YYYY-MM-DD.")


def _week_start(offset: int = 0) -> date:
    """Monday of the ET week, shifted by `offset` weeks (0 = this week)."""
    t = local_today()
    monday = t - timedelta(days=t.weekday())
    return monday + timedelta(weeks=offset)


def _log_to_dict(row) -> Dict[str, Any]:
    m = row._mapping
    td = m["tabata_detail"]
    if isinstance(td, str):
        try:
            td = json.loads(td)
        except (ValueError, TypeError):
            td = None
    return {
        "id": m["id"],
        "activity_type": m["activity_type"],
        "title": m["title"] or "",
        "duration_minutes": float(m["duration_minutes"]) if m["duration_minutes"] is not None else 0,
        "distance_miles": float(m["distance_miles"]) if m["distance_miles"] is not None else None,
        "avg_hr": m["avg_hr"],
        "max_hr": m["max_hr"],
        "zone": m["zone"],
        "calories_burned": float(m["calories_burned"]) if m["calories_burned"] is not None else None,
        "rpe": m["rpe"],
        "source": m["source"],
        "tabata_detail": td,
        "notes": m["notes"] or "",
        "session_date": m["session_date"].isoformat() if m["session_date"] else None,
        "logged_at": m["logged_at"].isoformat() if m["logged_at"] else None,
    }


def _preset_to_dict(row) -> Dict[str, Any]:
    m = row._mapping
    return {
        "id": m["id"],
        "name": m["name"],
        "prepare_seconds": m["prepare_seconds"],
        "work_seconds": m["work_seconds"],
        "rest_seconds": m["rest_seconds"],
        "rounds": m["rounds"],
        "sets": m["sets"],
        "rest_between_sets_seconds": m["rest_between_sets_seconds"],
        "activity_type": m["activity_type"],
        "color": m["color"],
        "is_built_in": m["is_built_in"],
        "sort_order": m["sort_order"],
    }


def _ensure_initialized(db: Session, user_id: str) -> None:
    """Create the user's cardio_settings row + seed built-in presets exactly once."""
    exists = db.execute(
        text("SELECT 1 FROM cardio_settings WHERE user_id = :u"), {"u": user_id}
    ).fetchone()
    if exists:
        return
    db.execute(
        text("""
            INSERT INTO cardio_settings
                (user_id, weekly_min_minutes, weekly_max_minutes, steps_floor, menu, created_at, updated_at)
            VALUES (:u, 90, 120, 8000, :menu, NOW(), NOW())
            ON CONFLICT (user_id) DO NOTHING
        """),
        {"u": user_id, "menu": json.dumps(DEFAULT_MENU)},
    )
    for p in DEFAULT_PRESETS:
        db.execute(
            text("""
                INSERT INTO tabata_preset
                    (id, user_id, name, prepare_seconds, work_seconds, rest_seconds, rounds, sets,
                     rest_between_sets_seconds, activity_type, color, is_built_in, sort_order,
                     created_at, updated_at)
                VALUES (:id, :u, :name, :prep, :work, :rest, :rounds, :sets, :rbs, :act, :color,
                        TRUE, :sort, NOW(), NOW())
            """),
            {
                "id": str(uuid.uuid4()), "u": user_id, "name": p["name"],
                "prep": p["prepare_seconds"], "work": p["work_seconds"], "rest": p["rest_seconds"],
                "rounds": p["rounds"], "sets": p["sets"], "rbs": p["rest_between_sets_seconds"],
                "act": p["activity_type"], "color": p["color"], "sort": p["sort_order"],
            },
        )
    db.commit()


# --------------------------------------------------------------------------- #
# Cardio logs
# --------------------------------------------------------------------------- #
@router.get("/logs")
async def list_cardio_logs(
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 200,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """List cardio sessions. Defaults to the current ET week when no range given."""
    _ensure_initialized(db, user_id)
    start_d = _parse_date(start) or _week_start(0)
    end_d = _parse_date(end) or (start_d + timedelta(days=6))
    rows = db.execute(
        text("""
            SELECT * FROM cardio_log
            WHERE user_id = :u AND session_date BETWEEN :s AND :e
            ORDER BY session_date DESC, logged_at DESC
            LIMIT :lim
        """),
        {"u": user_id, "s": start_d, "e": end_d, "lim": max(1, min(limit, 500))},
    ).fetchall()
    return {"logs": [_log_to_dict(r) for r in rows], "start": start_d.isoformat(), "end": end_d.isoformat()}


@router.post("/log")
async def create_cardio_log(
    payload: CardioLogCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Log a cardio session (manual, menu quick-log, or a finished Tabata run)."""
    _ensure_initialized(db, user_id)
    if payload.activity_type not in VALID_ACTIVITIES:
        # accept but normalize unknowns to "other" rather than reject
        activity = "other"
    else:
        activity = payload.activity_type
    if payload.duration_minutes is None or payload.duration_minutes <= 0:
        raise HTTPException(status_code=400, detail="duration_minutes must be > 0")

    session_d = _parse_date(payload.session_date) or local_today()
    logged_at = local_now()
    if payload.logged_at:
        try:
            logged_at = datetime.fromisoformat(payload.logged_at.replace("Z", "+00:00"))
        except ValueError:
            pass

    new_id = str(uuid.uuid4())
    row = db.execute(
        text("""
            INSERT INTO cardio_log
                (id, user_id, activity_type, title, duration_minutes, distance_miles, avg_hr, max_hr,
                 zone, calories_burned, rpe, source, tabata_detail, notes, session_date, logged_at,
                 created_at, updated_at)
            VALUES
                (:id, :u, :act, :title, :dur, :dist, :ahr, :mhr, :zone, :cal, :rpe, :src, :td, :notes,
                 :sd, :la, NOW(), NOW())
            RETURNING *
        """),
        {
            "id": new_id, "u": user_id, "act": activity, "title": payload.title or "",
            "dur": payload.duration_minutes, "dist": payload.distance_miles,
            "ahr": payload.avg_hr, "mhr": payload.max_hr, "zone": payload.zone,
            "cal": payload.calories_burned, "rpe": payload.rpe, "src": payload.source or "manual",
            "td": json.dumps(payload.tabata_detail) if payload.tabata_detail else None,
            "notes": payload.notes or "", "sd": session_d, "la": logged_at,
        },
    ).fetchone()
    db.commit()

    # Tell Sara's cognitive system a cardio session was completed (contact +
    # domain action). Cardio counts as a WORKOUT_COMPLETED with modality=cardio.
    try:
        from app.services.event_bus import emit_event, EventType
        asyncio.ensure_future(emit_event(
            EventType.WORKOUT_COMPLETED, user_id,
            payload={
                "type": activity,
                "modality": "cardio",
                "duration_minutes": payload.duration_minutes,
            },
            source="cardio_route",
        ))
    except Exception as e:
        logger.debug(f"cardio WORKOUT_COMPLETED emit failed: {e}")

    return _log_to_dict(row)


@router.patch("/log/{log_id}")
async def update_cardio_log(
    log_id: str,
    payload: CardioLogUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "activity_type" in fields and fields["activity_type"] not in VALID_ACTIVITIES:
        fields["activity_type"] = "other"
    if "session_date" in fields:
        fields["session_date"] = _parse_date(fields["session_date"])

    sets = ", ".join(f"{k} = :{k}" for k in fields)
    params = {**fields, "id": log_id, "u": user_id}
    row = db.execute(
        text(f"UPDATE cardio_log SET {sets}, updated_at = NOW() "
             f"WHERE id = :id AND user_id = :u RETURNING *"),
        params,
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Cardio log not found")
    db.commit()
    return _log_to_dict(row)


@router.delete("/log/{log_id}")
async def delete_cardio_log(
    log_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    res = db.execute(
        text("DELETE FROM cardio_log WHERE id = :id AND user_id = :u"),
        {"id": log_id, "u": user_id},
    )
    db.commit()
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="Cardio log not found")
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Stats — the weekly dose gauge
# --------------------------------------------------------------------------- #
@router.get("/stats")
async def cardio_stats(
    week_offset: int = 0,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _ensure_initialized(db, user_id)
    ws = _week_start(week_offset)
    we = ws + timedelta(days=6)

    settings = db.execute(
        text("SELECT weekly_min_minutes, weekly_max_minutes, steps_floor FROM cardio_settings WHERE user_id = :u"),
        {"u": user_id},
    ).fetchone()
    target_min = settings._mapping["weekly_min_minutes"] if settings else 90
    target_max = settings._mapping["weekly_max_minutes"] if settings else 120
    steps_floor = settings._mapping["steps_floor"] if settings else 8000

    total = db.execute(
        text("""SELECT COALESCE(SUM(duration_minutes), 0) AS m, COUNT(*) AS c
                FROM cardio_log WHERE user_id = :u AND session_date BETWEEN :s AND :e"""),
        {"u": user_id, "s": ws, "e": we},
    ).fetchone()
    total_minutes = float(total._mapping["m"] or 0)
    session_count = int(total._mapping["c"] or 0)

    by_activity = db.execute(
        text("""SELECT activity_type, SUM(duration_minutes) AS m, COUNT(*) AS c
                FROM cardio_log WHERE user_id = :u AND session_date BETWEEN :s AND :e
                GROUP BY activity_type ORDER BY m DESC"""),
        {"u": user_id, "s": ws, "e": we},
    ).fetchall()

    # Steps today — cumulative snapshots, so MAX per day (ET); only meaningful for this week.
    steps_today = None
    if week_offset == 0:
        srow = db.execute(
            text("""SELECT MAX(value) AS v FROM health_metric
                    WHERE user_id = :u AND metric_type = 'steps'
                      AND (recorded_at AT TIME ZONE 'America/New_York')::date = :today"""),
            {"u": user_id, "today": local_today()},
        ).fetchone()
        steps_today = int(srow._mapping["v"]) if srow and srow._mapping["v"] is not None else 0

    # 8-week trend of total minutes
    trend = []
    for off in range(-7, 1):
        tws = _week_start(week_offset + off)
        twe = tws + timedelta(days=6)
        r = db.execute(
            text("""SELECT COALESCE(SUM(duration_minutes), 0) AS m FROM cardio_log
                    WHERE user_id = :u AND session_date BETWEEN :s AND :e"""),
            {"u": user_id, "s": tws, "e": twe},
        ).fetchone()
        trend.append({"week_start": tws.isoformat(), "minutes": float(r._mapping["m"] or 0)})

    pct = round(min(total_minutes / target_min, 1.0) * 100) if target_min else 0
    return {
        "week_start": ws.isoformat(),
        "week_end": we.isoformat(),
        "target_min": target_min,
        "target_max": target_max,
        "total_minutes": total_minutes,
        "pct_of_min": pct,
        "session_count": session_count,
        "steps_today": steps_today,
        "steps_floor": steps_floor,
        "by_activity": [
            {"activity_type": r._mapping["activity_type"],
             "minutes": float(r._mapping["m"] or 0),
             "count": int(r._mapping["c"] or 0)}
            for r in by_activity
        ],
        "trend": trend,
    }


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@router.get("/settings")
async def get_cardio_settings(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _ensure_initialized(db, user_id)
    row = db.execute(
        text("SELECT * FROM cardio_settings WHERE user_id = :u"), {"u": user_id}
    ).fetchone()
    m = row._mapping
    menu = m["menu"]
    if isinstance(menu, str):
        menu = json.loads(menu)
    return {
        "weekly_min_minutes": m["weekly_min_minutes"],
        "weekly_max_minutes": m["weekly_max_minutes"],
        "steps_floor": m["steps_floor"],
        "menu": menu or DEFAULT_MENU,
    }


@router.put("/settings")
async def update_cardio_settings(
    payload: CardioSettingsUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _ensure_initialized(db, user_id)
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "menu" in fields:
        fields["menu"] = json.dumps(fields["menu"])
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    db.execute(
        text(f"UPDATE cardio_settings SET {sets}, updated_at = NOW() WHERE user_id = :u"),
        {**fields, "u": user_id},
    )
    db.commit()
    return await get_cardio_settings(user_id=user_id, db=db)


# --------------------------------------------------------------------------- #
# Tabata presets
# --------------------------------------------------------------------------- #
@router.get("/tabata-presets")
async def list_presets(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _ensure_initialized(db, user_id)
    rows = db.execute(
        text("SELECT * FROM tabata_preset WHERE user_id = :u ORDER BY sort_order, created_at"),
        {"u": user_id},
    ).fetchall()
    return {"presets": [_preset_to_dict(r) for r in rows]}


@router.post("/tabata-presets")
async def create_preset(
    payload: TabataPresetCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _ensure_initialized(db, user_id)
    if payload.work_seconds <= 0 or payload.rest_seconds < 0 or payload.rounds <= 0 or payload.sets <= 0:
        raise HTTPException(status_code=400, detail="work/rounds/sets must be > 0 and rest >= 0")
    max_sort = db.execute(
        text("SELECT COALESCE(MAX(sort_order), 0) AS s FROM tabata_preset WHERE user_id = :u"),
        {"u": user_id},
    ).fetchone()._mapping["s"]
    new_id = str(uuid.uuid4())
    row = db.execute(
        text("""
            INSERT INTO tabata_preset
                (id, user_id, name, prepare_seconds, work_seconds, rest_seconds, rounds, sets,
                 rest_between_sets_seconds, activity_type, color, is_built_in, sort_order,
                 created_at, updated_at)
            VALUES (:id, :u, :name, :prep, :work, :rest, :rounds, :sets, :rbs, :act, :color, FALSE, :sort,
                    NOW(), NOW())
            RETURNING *
        """),
        {
            "id": new_id, "u": user_id, "name": payload.name, "prep": payload.prepare_seconds,
            "work": payload.work_seconds, "rest": payload.rest_seconds, "rounds": payload.rounds,
            "sets": payload.sets, "rbs": payload.rest_between_sets_seconds,
            "act": payload.activity_type, "color": payload.color, "sort": int(max_sort) + 1,
        },
    ).fetchone()
    db.commit()
    return _preset_to_dict(row)


@router.patch("/tabata-presets/{preset_id}")
async def update_preset(
    preset_id: str,
    payload: TabataPresetUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    row = db.execute(
        text(f"UPDATE tabata_preset SET {sets}, updated_at = NOW() "
             f"WHERE id = :id AND user_id = :u RETURNING *"),
        {**fields, "id": preset_id, "u": user_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Preset not found")
    db.commit()
    return _preset_to_dict(row)


@router.delete("/tabata-presets/{preset_id}")
async def delete_preset(
    preset_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    res = db.execute(
        text("DELETE FROM tabata_preset WHERE id = :id AND user_id = :u"),
        {"id": preset_id, "u": user_id},
    )
    db.commit()
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"ok": True}
