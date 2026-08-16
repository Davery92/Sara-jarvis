"""Presence logging routes."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.core.timezone import now_utc, today as local_today
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Presence"])

# --- Redis-backed client state helpers ---

_CLIENT_STATE_PREFIX = "sara:client_state"
_CLIENT_STATE_TTL = 60  # seconds
_HEARTBEAT_SECONDS = 30  # nominal client heartbeat cadence (used for dwell rollup)
_VIEW_CHANGE_DWELL_SECONDS = 120  # min dwell before APP_VIEW_CHANGED fires
_ACTIVITY_REFRESH_SECONDS = 120  # min gap between cheap last_app_activity_at refreshes
_VIEWS_TODAY_PREFIX = "sara:app_views_today"
_VIEWS_TODAY_TTL = 48 * 60 * 60  # seconds


def _client_key(user_id: str, client_id: str) -> str:
    return f"{_CLIENT_STATE_PREFIX}:{user_id}:{client_id}"


def get_active_clients(user_id: str) -> List[dict]:
    """Return all active client states for a user (keys with unexpired TTL)."""
    try:
        from app.core.redis import get_redis_sync
        r = get_redis_sync()
        pattern = f"{_CLIENT_STATE_PREFIX}:{user_id}:*"
        clients = []
        for key in r.scan_iter(match=pattern, count=50):
            raw = r.get(key)
            if raw:
                clients.append(json.loads(raw))
        return clients
    except Exception as e:
        logger.error(f"Failed to get active clients: {e}")
        return []


def is_user_in_chat(user_id: str) -> Tuple[bool, Optional[str]]:
    """
    Check whether any active client for this user is on the chat view.
    Returns (in_chat, platform) — platform of the first client in chat, or None.
    """
    for client in get_active_clients(user_id):
        view = client.get("current_view", "")
        if view in ("chat", "sara", "Sara"):
            return True, client.get("platform")
    return False, None


# --- Legacy presence log ---

async def log_presence(user_id: str, activity_type: str, platform: str = None, db: Session = None):
    """
    Log a presence/activity event for the user.
    Called from various endpoints to track when the user is active.
    """
    try:
        if db is None:
            from app.db.session import SessionLocal
            db = SessionLocal()
            close_db = True
        else:
            close_db = False

        try:
            db.execute(text("""
                INSERT INTO presence_log (id, user_id, activity_type, platform, created_at)
                VALUES (:id, :user_id, :activity_type, :platform, NOW())
            """), {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "activity_type": activity_type,
                "platform": platform
            })
            db.commit()
            logger.debug(f"Logged presence: {user_id} - {activity_type} ({platform})")
        finally:
            if close_db:
                db.close()

    except Exception as e:
        logger.error(f"Error logging presence: {e}")


@router.post("/api/presence")
async def log_presence_endpoint(
    data: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Log user presence/activity. Call this when app opens, resumes, or on significant actions.
    """
    activity_type = data.get("activity_type", "app_open")
    platform = data.get("platform", "unknown")

    await log_presence(current_user.id, activity_type, platform, db)

    return {"success": True, "message": "Presence logged"}


def _increment_view_dwell(r, user_id: str, view: str, seconds: int) -> None:
    """Accumulate per-view dwell minutes in a date-keyed Redis hash.

    Stored in seconds; rendered to the app_views_today string by the derived
    refresher. Date-keyed key + 48h TTL means it resets naturally each day.
    """
    try:
        key = f"{_VIEWS_TODAY_PREFIX}:{user_id}:{local_today().isoformat()}"
        r.hincrby(key, view, seconds)
        r.expire(key, _VIEWS_TODAY_TTL)
    except Exception as e:
        logger.debug(f"view dwell increment failed: {e}")


@router.post("/api/presence/heartbeat")
async def presence_heartbeat(
    data: dict,
    current_user=Depends(get_current_user)
):
    """
    Periodic heartbeat from web/iOS clients.

    Accepts:
      platform:     "web" | "ios"
      client_id:    stable per-session identifier
      current_view: "chat" | "notes" | "dashboard" | "fitness" | ...
      visible:      true if the app/tab is in the foreground
    """
    client_id = data.get("client_id", "unknown")
    platform = data.get("platform", "unknown")
    current_view = data.get("current_view", "unknown")
    visible = bool(data.get("visible", True))
    now = now_utc()
    now_iso = now.isoformat()

    prev_state: Optional[dict] = None
    view_changed = True
    view_since = now_iso
    view_change_emitted = False
    emit_view_changed = False

    try:
        from app.core.redis import get_redis_sync
        r = get_redis_sync()
        key = _client_key(current_user.id, client_id)

        raw_prev = r.get(key)
        if raw_prev:
            try:
                prev_state = json.loads(raw_prev)
            except (ValueError, TypeError):
                prev_state = None

        # Track dwell in the current view (carry view_since forward while unchanged)
        if prev_state and prev_state.get("current_view") == current_view:
            view_changed = False
            view_since = prev_state.get("view_since", now_iso)
            view_change_emitted = bool(prev_state.get("view_change_emitted", False))

        # Fire APP_VIEW_CHANGED only once the new view has been dwelt in >=2 min,
        # so tab-flipping doesn't spam the observation log.
        if visible and not view_changed and not view_change_emitted:
            try:
                since_dt = datetime.fromisoformat(view_since)
                if since_dt.tzinfo is None:
                    since_dt = since_dt.replace(tzinfo=timezone.utc)
                if (now - since_dt).total_seconds() >= _VIEW_CHANGE_DWELL_SECONDS:
                    emit_view_changed = True
                    view_change_emitted = True
            except (ValueError, TypeError):
                pass

        state = {
            "platform": platform,
            "client_id": client_id,
            "current_view": current_view,
            "visible": visible,
            "user_id": current_user.id,
            "view_since": view_since,
            "view_change_emitted": view_change_emitted,
            "last_seen": now_iso,
        }
        r.setex(key, _CLIENT_STATE_TTL, json.dumps(state))

        # Dwell rollup — only count foreground time in a real view
        if visible and current_view not in ("", "unknown"):
            _increment_view_dwell(r, current_user.id, current_view, _HEARTBEAT_SECONDS)
    except Exception as e:
        logger.error(f"Failed to store heartbeat: {e}")

    # Working-memory + event processing is fire-and-forget: a Redis pub/sub
    # hiccup must never fail a heartbeat.
    try:
        asyncio.ensure_future(_apply_app_presence(
            user_id=current_user.id,
            platform=platform,
            current_view=current_view,
            visible=visible,
            view_changed=view_changed,
            view_since=view_since,
            now_iso=now_iso,
            prev_visible=bool(prev_state.get("visible", False)) if prev_state else False,
            emit_view_changed=emit_view_changed,
        ))
    except Exception as e:
        logger.debug(f"app presence dispatch failed: {e}")

    return {"ok": True}


async def _apply_app_presence(
    user_id: str,
    platform: str,
    current_view: str,
    visible: bool,
    view_changed: bool,
    view_since: str,
    now_iso: str,
    prev_visible: bool,
    emit_view_changed: bool,
) -> None:
    """
    Translate a heartbeat into working-memory app-presence fields + ambient
    events. App presence is *contact*, not conversation — these events are
    observation-only and never trigger deliberation on their own.
    """
    try:
        from app.services.working_memory import read_memory, update_memory
        from app.services.event_bus import emit_event, EventType
        from app.services.unified_context import _get_redis

        memory = await read_memory(user_id)
        was_active = bool(memory.app_active)

        if not visible:
            # A background/hidden heartbeat is not "contact" — don't refresh
            # last_app_activity_at, but if this client going hidden coincides
            # with the app having been active, let the reaper handle session end.
            return

        session_started = not was_active

        # Decide whether to write working memory or just cheaply refresh activity.
        significant = (
            session_started
            or view_changed
            or (memory.app_current_view != current_view)
            or (not prev_visible)
        )

        if significant:
            fields = {
                "app_active": True,
                "app_platform": platform,
                "app_current_view": current_view,
                "last_app_activity_at": now_iso,
            }
            # Only stamp view_since when the view actually changed
            if view_changed or memory.app_current_view != current_view:
                fields["app_view_since"] = view_since
            await update_memory(user_id, source="app_presence", **fields)
        else:
            # Debounced cheap refresh — at most once per 2 min when nothing changed.
            should_refresh = True
            if memory.last_app_activity_at:
                try:
                    last_dt = datetime.fromisoformat(memory.last_app_activity_at)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    now_dt = datetime.fromisoformat(now_iso)
                    if (now_dt - last_dt).total_seconds() < _ACTIVITY_REFRESH_SECONDS:
                        should_refresh = False
                except (ValueError, TypeError):
                    pass
            if should_refresh:
                await update_memory(
                    user_id, source="app_presence", last_app_activity_at=now_iso
                )

        # ── Ambient events (observation-only) ──
        if session_started:
            first_today = False
            try:
                r = await _get_redis()
                dedup = f"sara:app_session_started_today:{user_id}:{local_today().isoformat()}"
                first_today = bool(await r.set(dedup, "1", ex=_VIEWS_TODAY_TTL, nx=True))
                # Session-start marker for the reaper to compute duration on end.
                await r.set(f"sara:app_session_start:{user_id}", now_iso, ex=_VIEWS_TODAY_TTL)
            except Exception:
                pass
            await emit_event(
                EventType.APP_SESSION_STARTED,
                user_id,
                payload={
                    "platform": platform,
                    "view": current_view,
                    "first_of_day": first_today,
                },
                source="app_presence",
            )

        if emit_view_changed:
            await emit_event(
                EventType.APP_VIEW_CHANGED,
                user_id,
                payload={"platform": platform, "view": current_view},
                source="app_presence",
            )
    except Exception as e:
        logger.debug(f"[AppPresence] apply failed: {e}")


def render_app_views_today(user_id: str) -> Optional[str]:
    """Render the per-view dwell hash into 'fitness 41m, recipes 12m'."""
    try:
        from app.core.redis import get_redis_sync
        r = get_redis_sync()
        key = f"{_VIEWS_TODAY_PREFIX}:{user_id}:{local_today().isoformat()}"
        raw = r.hgetall(key)
        if not raw:
            return None
        pairs = []
        for view, secs in raw.items():
            try:
                minutes = round(int(secs) / 60)
            except (ValueError, TypeError):
                continue
            if minutes >= 1:
                pairs.append((view, minutes))
        pairs.sort(key=lambda p: p[1], reverse=True)
        if not pairs:
            return None
        return ", ".join(f"{v} {m}m" for v, m in pairs)
    except Exception as e:
        logger.debug(f"render app_views_today failed: {e}")
        return None


async def reap_app_presence(user_id: str) -> dict:
    """
    Session-end reaper + app-activity freshness recompute. Called from the
    5-min derived-signal refresher.

    - If all client TTLs have expired but working memory still says app_active,
      flip it off, clear the current view, and emit one APP_SESSION_ENDED
      carrying session duration + views visited.
    - Always recompute hours_since_app_activity and re-render app_views_today.
    """
    from app.services.working_memory import read_memory, update_memory
    from app.services.event_bus import emit_event, EventType
    from app.services.unified_context import _get_redis

    result = {}
    memory = await read_memory(user_id)
    now = now_utc()

    active_clients = get_active_clients(user_id)
    any_visible = any(c.get("visible") for c in active_clients)

    # Session-end detection — no client is foregrounded anymore
    if memory.app_active and not any_visible:
        duration_min = None
        views = render_app_views_today(user_id)
        try:
            r = await _get_redis()
            start_iso = await r.get(f"sara:app_session_start:{user_id}")
            if start_iso:
                start_dt = datetime.fromisoformat(start_iso)
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
                duration_min = int((now - start_dt).total_seconds() / 60)
            await r.delete(f"sara:app_session_start:{user_id}")
        except Exception:
            pass

        await update_memory(
            user_id,
            source="app_presence_reaper",
            app_active=False,
            app_current_view=None,
            app_view_since=None,
        )
        await emit_event(
            EventType.APP_SESSION_ENDED,
            user_id,
            payload={
                "duration_minutes": duration_min,
                "views_today": views,
            },
            source="app_presence",
        )
        result["app_session_ended"] = duration_min

    # Freshness recompute (same pattern as hours_since_last_chat)
    if memory.last_app_activity_at:
        try:
            last_dt = datetime.fromisoformat(memory.last_app_activity_at)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            hours = (now - last_dt).total_seconds() / 3600
            await update_memory(
                user_id,
                source="app_presence_reaper",
                hours_since_app_activity=round(hours, 1),
                app_views_today=render_app_views_today(user_id),
            )
            result["hours_since_app_activity"] = round(hours, 1)
        except (ValueError, TypeError):
            pass

    return result


@router.post("/desktop-activity")
async def report_desktop_activity(
    data: Dict,
    current_user=Depends(get_current_user),
):
    """
    Report desktop active window for activity state inference.

    Expected payload:
        app: str        — active app name (e.g. "VSCode", "Zoom")
        window_title: str — window title (optional)
        idle_seconds: int — seconds since last input (optional)
    """
    app = data.get("app", "")
    window_title = data.get("window_title", "")
    idle_seconds = data.get("idle_seconds", 0)

    # Feed into activity state machine
    try:
        from app.services.activity_state_machine import activity_state_machine, ActivitySignal
        activity_state_machine.process_signal(ActivitySignal(
            signal_type="desktop",
            source="desktop_agent",
            value=app,
            metadata={
                "window_title": window_title,
                "idle_seconds": idle_seconds,
            },
        ))
    except Exception as e:
        logger.warning(f"Desktop activity signal failed: {e}")

    # Store in unified context
    try:
        from app.services.context_writer import update_fields
        import asyncio
        asyncio.ensure_future(update_fields(str(current_user.id), source="desktop_agent", **{
            "desktop_active_app": app,
            "desktop_active_window": window_title[:100] if window_title else "",
            "desktop_idle_seconds": idle_seconds,
        }))
    except Exception:
        pass

    return {"ok": True}


class LocationUpdate(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None
    label: Optional[str] = None  # iOS may provide a label
    observed_at: Optional[datetime] = None


@router.post("/location")
async def report_location(
    data: LocationUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Legacy significant-location-change endpoint. New iOS builds should use
    POST /api/location/report instead — kept here so old app builds keep working.
    """
    from app.services.location_service import process_report
    result = await process_report(
        db, current_user.id, data.latitude, data.longitude, data.accuracy,
        "ios_significant", observed_at=data.observed_at,
    )
    return {"ok": True, "classified_place": result.get("classified_place") or data.label or "unknown"}
