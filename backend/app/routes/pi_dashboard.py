"""Pi-dashboard endpoints — extracted from main_simple.py.

These routes power the headless Pi display. They support both cookie auth
and device-token auth (``X-Device-Token``) so the Pi can authenticate
without a human session.

Scope:
  * /api/pi-dashboard/devices/register — cookie-auth, creates a device token
  * /api/devices/bootstrap             — email-based bootstrap (P0 auth gap)
  * /api/pi-dashboard/state            — combined dashboard state
  * /api/pi-dashboard/nudges/{id}/acknowledge
  * /api/pi-dashboard/timers           — active timers overlay

The voice endpoints (/api/pi-dashboard/voice/*) stay in main_simple.py for
now — they pull heavily on the LLM/STT/TTS surface and belong with the
upcoming chat extraction.
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.device_auth import get_device_user
from app.core.timezone import now as local_now
from app.db.session import get_db

# get_current_user and Timer/User live in main_simple.py until Phase 3
# extraction progresses further. Import is top-level because main_simple
# registers this router after defining them.
from app.main_simple import Timer, User, get_current_user  # noqa: E402

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/pi-dashboard/devices/register")
async def register_device(
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Legacy Pi dashboard registration — authenticated via cookie."""
    device_name = data.get("device_name", "Unknown Device")
    device_type = data.get("device_type", "pi_dashboard")

    device_token = secrets.token_urlsafe(32)
    device_id = str(uuid.uuid4())

    db.execute(
        text(
            """
            INSERT INTO device_registration
                (id, user_id, device_name, device_token, device_type, last_seen, created_at)
            VALUES (:id, :user_id, :device_name, :device_token, :device_type, NOW(), NOW())
            """
        ),
        {
            "id": device_id,
            "user_id": current_user.id,
            "device_name": device_name,
            "device_token": device_token,
            "device_type": device_type,
        },
    )
    db.commit()

    return {
        "device_id": device_id,
        "device_token": device_token,
        "message": "Device registered. Store this token securely.",
    }


@router.post("/api/devices/bootstrap")
async def bootstrap_device(data: dict, db: Session = Depends(get_db)):
    """Bootstrap a device registration using email — for headless Pi setup.

    ⚠ Known P0 gap (flagged in audit): unauthenticated and takes email,
    so it doubles as a user-enumeration vector. Single-user deployment
    only; do not expose on a shared network without adding a rate limit
    or a provisioning secret.
    """
    email = data.get("email")
    device_name = data.get("device_name", "pi-dashboard")
    device_type = data.get("device_type", "pi_dashboard")

    if not email:
        raise HTTPException(status_code=400, detail="Email required")

    result = db.execute(
        text("SELECT id FROM app_user WHERE email = :email"),
        {"email": email},
    ).fetchone()
    if not result:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = result[0]

    existing = db.execute(
        text(
            """
            SELECT device_token FROM device_registration
            WHERE user_id = :user_id AND device_name = :device_name
            """
        ),
        {"user_id": user_id, "device_name": device_name},
    ).fetchone()
    if existing:
        return {
            "device_token": existing[0],
            "message": "Device already registered. Returning existing token.",
        }

    device_token = secrets.token_urlsafe(32)
    device_id = str(uuid.uuid4())

    db.execute(
        text(
            """
            INSERT INTO device_registration
                (id, user_id, device_name, device_token, device_type, last_seen, created_at)
            VALUES (:id, :user_id, :device_name, :device_token, :device_type, NOW(), NOW())
            """
        ),
        {
            "id": device_id,
            "user_id": user_id,
            "device_name": device_name,
            "device_token": device_token,
            "device_type": device_type,
        },
    )
    db.commit()

    return {
        "device_id": device_id,
        "device_token": device_token,
        "message": "Device registered. Store this token in localStorage as 'device_token'.",
    }


@router.get("/api/pi-dashboard/state")
async def get_pi_dashboard_state(request: Request, db: Session = Depends(get_db)):
    """Combined dashboard state — subconscious, nudges, workers, calendar, notes."""
    user_id = await get_device_user(request, db)
    if not user_id:
        # Cookie auth fallback. get_current_user is sync in main_simple,
        # so call it directly rather than via await.
        try:
            current_user = get_current_user(request, db)
            user_id = current_user.id
        except Exception as auth_err:
            logger.debug(f"Authentication failed for pi-dashboard/state: {auth_err}")
            raise HTTPException(
                status_code=401,
                detail="Not authenticated. Use device token or login.",
            )

    # Subconscious state (JSON columns in text form need parsing before return)
    state_result = db.execute(
        text("SELECT * FROM subconscious_state WHERE user_id = :user_id"),
        {"user_id": user_id},
    ).fetchone()

    state = None
    if state_result:
        state = dict(state_result._mapping)
        # Arc 0.8: no writer for last_meal_type/last_meal_at/hours_since_meal/
        # typical_meal_windows anywhere in the codebase — stale since a
        # one-time seed. /api/sara/status computes hours-since-meal live from
        # the food log instead; drop the dead fields here rather than surface
        # two disagreeing answers.
        for dead_field in ("last_meal_type", "last_meal_at", "hours_since_meal", "typical_meal_windows"):
            state.pop(dead_field, None)
        json_fields = (
            "current_focus_areas",
            "active_threads",
            "docker_health",
            "service_health",
        )
        for field in json_fields:
            if state.get(field) and isinstance(state[field], str):
                try:
                    state[field] = json.loads(state[field])
                except (json.JSONDecodeError, TypeError) as e:
                    logger.debug(f"Failed to parse JSON field {field}: {e}")
        ts_fields = ("last_presence_at", "updated_at", "created_at")
        for field in ts_fields:
            if state.get(field):
                state[field] = (
                    state[field].isoformat()
                    if hasattr(state[field], "isoformat")
                    else str(state[field])
                )

    # Pending nudges (urgent first, then gentle, then recent)
    nudges_result = db.execute(
        text(
            """
            SELECT id, nudge_type, severity, title, message, action_suggestion,
                   delivery_channel, created_at, expires_at
            FROM subconscious_nudge
            WHERE user_id = :user_id
              AND status IN ('pending', 'delivered')
              AND expires_at > NOW()
            ORDER BY
                CASE severity WHEN 'urgent' THEN 1 WHEN 'gentle' THEN 2 ELSE 3 END,
                created_at DESC
            LIMIT 10
            """
        ),
        {"user_id": user_id},
    ).fetchall()

    nudges = []
    for r in nudges_result:
        nudge = dict(r._mapping)
        nudge["created_at"] = (
            nudge["created_at"].isoformat() if nudge.get("created_at") else None
        )
        nudge["expires_at"] = (
            nudge["expires_at"].isoformat() if nudge.get("expires_at") else None
        )
        nudges.append(nudge)

    # Worker status — next-run estimates from last snapshot + known interval.
    worker_status: dict = {}
    try:
        subconscious_log = db.execute(
            text(
                """
                SELECT snapshot_at FROM subconscious_log
                WHERE user_id = :user_id
                ORDER BY snapshot_at DESC LIMIT 1
                """
            ),
            {"user_id": user_id},
        ).fetchone()
        if subconscious_log:
            last_run = subconscious_log.snapshot_at
            next_run = last_run + timedelta(minutes=30) if last_run else None
            worker_status["subconscious"] = {
                "last_run": last_run.isoformat() if last_run else None,
                "next_run": next_run.isoformat() if next_run else None,
                "interval_mins": 30,
            }
    except Exception as e:
        logger.warning(f"Failed to get subconscious worker status: {e}")

    try:
        orchestrator_task = db.execute(
            text(
                """
                SELECT completed_at FROM background_task
                WHERE task_type = 'orchestrator'
                ORDER BY completed_at DESC LIMIT 1
                """
            )
        ).fetchone()
        if orchestrator_task and orchestrator_task.completed_at:
            last_run = orchestrator_task.completed_at
            next_run = last_run + timedelta(minutes=5)
            worker_status["orchestrator"] = {
                "last_run": last_run.isoformat(),
                "next_run": next_run.isoformat(),
                "interval_mins": 5,
            }
    except Exception:
        pass  # background_task table might not exist in all deployments

    # Today's calendar
    calendar_events: list = []
    try:
        today_start = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        events_result = db.execute(
            text(
                """
                SELECT id, title, start_time, end_time, location, ios_calendar_name
                FROM calendar_event
                WHERE user_id = :user_id
                  AND start_time >= :today_start
                  AND start_time < :today_end
                ORDER BY start_time
                LIMIT 10
                """
            ),
            {"user_id": user_id, "today_start": today_start, "today_end": today_end},
        ).fetchall()
        for e in events_result:
            calendar_events.append(
                {
                    "id": e.id,
                    "title": e.title,
                    "start": e.start_time.isoformat() if e.start_time else None,
                    "end": e.end_time.isoformat() if e.end_time else None,
                    "location": e.location,
                    "calendar_name": e.ios_calendar_name,
                }
            )
    except Exception as ex:
        logger.warning(f"Failed to get calendar events: {ex}")

    # Recent notes
    recent_notes: list = []
    try:
        notes_result = db.execute(
            text(
                """
                SELECT id, title, updated_at, created_at
                FROM note
                WHERE user_id = :user_id
                ORDER BY updated_at DESC
                LIMIT 10
                """
            ),
            {"user_id": user_id},
        ).fetchall()
        for n in notes_result:
            recent_notes.append(
                {
                    "id": n.id,
                    "title": n.title,
                    "updated_at": n.updated_at.isoformat() if n.updated_at else None,
                    "created_at": n.created_at.isoformat() if n.created_at else None,
                }
            )
    except Exception as ex:
        logger.warning(f"Failed to get notes: {ex}")

    return {
        "state": state,
        "nudges": nudges,
        "worker_status": worker_status,
        "calendar_events": calendar_events,
        "recent_notes": recent_notes,
        "timestamp": local_now().isoformat(),
    }


@router.post("/api/pi-dashboard/nudges/{nudge_id}/acknowledge")
async def pi_dashboard_acknowledge_nudge(
    nudge_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Acknowledge a nudge via Pi dashboard (supports device token auth)."""
    user_id = await get_device_user(request, db)
    if not user_id:
        try:
            current_user = get_current_user(request, db)
            user_id = current_user.id
        except Exception as auth_err:
            logger.debug(f"Authentication failed: {auth_err}")
            raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        result = db.execute(
            text(
                """
                UPDATE subconscious_nudge
                SET acknowledged_at = NOW(), status = 'acknowledged'
                WHERE id = :nudge_id
                  AND user_id = :user_id
                  AND status IN ('pending', 'delivered')
                """
            ),
            {"nudge_id": nudge_id, "user_id": user_id},
        )
        db.commit()

        if result.rowcount > 0:
            logger.info(f"[Pi Dashboard] Nudge {nudge_id} acknowledged by user {user_id}")
            return {"success": True, "nudge_id": nudge_id}
        raise HTTPException(
            status_code=404, detail="Nudge not found or already acknowledged"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error acknowledging nudge: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/pi-dashboard/timers")
async def get_pi_dashboard_timers(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get active timers for the Pi dashboard overlay.

    Expired timers are swept (marked completed) and emit a standing-order
    trigger + TIMER_COMPLETED event before being dropped from the response.
    """
    user_id = current_user.id
    try:
        now = datetime.now(timezone.utc)

        timers = (
            db.query(Timer)
            .filter(Timer.user_id == user_id, Timer.is_active == True)  # noqa: E712
            .order_by(Timer.end_time.asc())
            .all()
        )

        timer_list: list = []
        for timer in timers:
            end_time = timer.end_time
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
            remaining_seconds = (end_time - now).total_seconds()

            if remaining_seconds <= 0:
                timer.is_active = False
                timer.is_completed = True
                db.commit()
                # Standing-order evaluation — a completed timer may be the
                # trigger for automated downstream actions.
                try:
                    from app.services.standing_order_service import standing_order_service
                    executed = await standing_order_service.evaluate_trigger(
                        trigger_type="timer",
                        context={
                            "timer_id": str(timer.id),
                            "timer_title": timer.title or "",
                            "duration_minutes": timer.duration_minutes,
                        },
                        db=db,
                    )
                    if executed:
                        logger.info(
                            f"Timer '{timer.title}' triggered {len(executed)} standing order(s)"
                        )
                except Exception as e:
                    logger.warning(f"Timer standing order eval failed: {e}")

                # Event-bus emit so reactive subscribers see the completion.
                try:
                    from app.services.event_bus import emit_event, EventType
                    await emit_event(
                        event_type=EventType.TIMER_COMPLETED,
                        user_id=str(timer.user_id),
                        payload={
                            "timer_id": str(timer.id),
                            "timer_title": timer.title or "",
                            "duration_minutes": timer.duration_minutes,
                        },
                        source="timer_expiry",
                    )
                except Exception as e:
                    logger.debug(f"Timer event emit failed: {e}")
                continue

            timer_list.append(
                {
                    "id": timer.id,
                    "title": timer.title,
                    "duration_minutes": timer.duration_minutes,
                    "end_time": end_time.isoformat(),
                    "remaining_seconds": int(remaining_seconds),
                    "remaining_minutes": int(remaining_seconds / 60),
                    "remaining_display": (
                        f"{int(remaining_seconds // 60)}:"
                        f"{int(remaining_seconds % 60):02d}"
                    ),
                }
            )

        return {"timers": timer_list, "count": len(timer_list)}
    except Exception as e:
        logger.error(f"Error getting timers: {e}")
        raise HTTPException(status_code=500, detail=str(e))
