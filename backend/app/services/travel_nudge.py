"""
Geocoding + travel-time "leave now" nudges.

Two capabilities, deliberately kept together since they're one pipeline:
1. geocode_address() — turn a calendar event's location string into coordinates
   (Nominatim, free/no API key, Redis-cached since personal-use volume is tiny
   and Nominatim's usage policy caps at 1 req/sec).
2. estimate_travel_minutes() — drive time between two points (OSRM public
   routing, haversine/avg-speed fallback if OSRM is unreachable).

check_and_send_leave_now_nudges() ties them together: for upcoming events with
a location, geocode it, compare against David's current reported position, and
nudge once travel time + a buffer eats into the time remaining.
"""
import logging
import math
from datetime import timedelta
from typing import Optional, Tuple

import httpx
from sqlalchemy import text

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "http://router.project-osrm.org/route/v1/driving"
USER_AGENT = "SaraAssistant/1.0 (personal use, github.com/avery)"
GEOCODE_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days — addresses don't move
AVG_FALLBACK_SPEED_MPH = 28  # used only if OSRM is unreachable

# Nudge window: only consider events starting within this range. Wide enough to
# cover long drives, narrow enough that check_and_send_leave_now_nudges (run
# every 15 min) doesn't waste geocode/route calls on far-future events.
LOOKAHEAD_MINUTES = 150
LEAVE_BUFFER_MINUTES = 5  # pad the nudge a few minutes early
ALREADY_THERE_RADIUS_M = 300  # don't nudge if current position is basically the venue


async def _get_redis():
    from app.services.unified_context import _get_redis as _shared_get_redis
    return await _shared_get_redis()


def _cache_key(address: str) -> str:
    return f"sara:geocode:{address.strip().lower()}"


async def geocode_address(address: str) -> Optional[Tuple[float, float]]:
    """Resolve a free-text address to (lat, lon). Redis-cached; returns None on failure."""
    address = (address or "").strip()
    if not address:
        return None

    r = await _get_redis()
    cache_key = _cache_key(address)
    cached = await r.get(cache_key)
    if cached is not None:
        if cached == "":
            return None  # cached negative result
        lat_str, lon_str = cached.split(",")
        return float(lat_str), float(lon_str)

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                NOMINATIM_URL,
                params={"q": address, "format": "json", "limit": 1},
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            results = resp.json()
    except Exception as e:
        logger.debug(f"Geocode failed for '{address}': {e}")
        return None

    if not results:
        await r.set(cache_key, "", ex=GEOCODE_CACHE_TTL_SECONDS)
        return None

    lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
    await r.set(cache_key, f"{lat},{lon}", ex=GEOCODE_CACHE_TTL_SECONDS)
    return lat, lon


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def estimate_travel_minutes(
    origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float
) -> Optional[int]:
    """Drive time in minutes. Tries OSRM's public routing server first, falls
    back to a straight-line-distance / average-speed guess if it's unreachable."""
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            url = f"{OSRM_URL}/{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
            resp = await client.get(url, params={"overview": "false"})
            resp.raise_for_status()
            data = resp.json()
            duration_s = data["routes"][0]["duration"]
            return max(1, round(duration_s / 60))
    except Exception as e:
        logger.debug(f"OSRM route failed, falling back to haversine estimate: {e}")

    dist_m = _haversine_m(origin_lat, origin_lon, dest_lat, dest_lon)
    dist_miles = dist_m / 1609.34
    minutes = (dist_miles / AVG_FALLBACK_SPEED_MPH) * 60
    return max(1, round(minutes))


async def check_and_send_leave_now_nudges(user_id: str) -> dict:
    """Nudge David when it's time to leave for an upcoming event, based on
    real drive time from his current reported position."""
    from app.db.session import get_async_session_factory
    from app.core.timezone import now as local_now
    from app.services.unified_context import read_snapshot

    try:
        from app.services.activity_state_machine import activity_state_machine, ActivityState
        if activity_state_machine.current.state == ActivityState.SLEEPING:
            return {"sent": 0, "reason": "sleeping"}
    except Exception:
        pass

    snap = await read_snapshot(user_id)
    if snap.location_latitude is None or snap.location_longitude is None:
        return {"sent": 0, "reason": "no current location"}

    now = local_now().replace(tzinfo=None)
    window_end = now + timedelta(minutes=LOOKAHEAD_MINUTES)

    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(text("""
            SELECT id, title, start_time, location
            FROM calendar_event
            WHERE user_id = :uid
              AND start_time BETWEEN :start AND :end
              AND location IS NOT NULL AND location != ''
            ORDER BY start_time ASC
            LIMIT 5
        """), {"uid": user_id, "start": now, "end": window_end})
        events = result.fetchall()

    sent = 0
    for event in events:
        event_id, title, start_time, location = event
        topic = f"leave_now:{event_id}"

        dest = await geocode_address(location)
        if not dest:
            continue
        dest_lat, dest_lon = dest

        dist_m = _haversine_m(snap.location_latitude, snap.location_longitude, dest_lat, dest_lon)
        if dist_m <= ALREADY_THERE_RADIUS_M:
            continue  # already there, or the venue and home/office coincide

        travel_min = await estimate_travel_minutes(
            snap.location_latitude, snap.location_longitude, dest_lat, dest_lon
        )
        if travel_min is None:
            continue

        minutes_until_start = (start_time - now).total_seconds() / 60
        minutes_until_leave = minutes_until_start - travel_min - LEAVE_BUFFER_MINUTES

        if minutes_until_leave > 15:
            continue  # not time yet — check again next sweep

        leave_by = (now + timedelta(minutes=max(0, minutes_until_leave))).strftime("%-I:%M %p")
        message = f"About {travel_min} min to {location} — leave by {leave_by} for \"{title}\"."

        # Item 4 / registers=1 closure (2026-07-31): legacy immediate send
        # deleted. Proven end-to-end with a real synthesized leave-now
        # firing (real calendar event + real location snapshot + real
        # geocoding/routing): candidate created -> compose produced a real
        # payload (once the World Brief's calendar sweep had picked up the
        # event -- compose's time-honesty check correctly declined before
        # that) -> review approved -> delivery confirmed, all within
        # single-digit seconds, comfortably inside the <=15min "leave now"
        # buffer this sender needed and well under the 60s target. The
        # urgent lane (single-pass compose->review->deliver, no beat-
        # interval wait) is now the only path — no dual-notify window.
        try:
            from app.core.timezone import to_utc
            from app.services.urgent_lane import deliver_urgent
            urgent_result = await deliver_urgent(
                async_session, user_id, source="travel_nudge", kind="alert",
                summary=message, evidence=[{"event_id": event_id, "travel_minutes": travel_min}],
                topic_entities=[topic], valid_until=to_utc(start_time),
                dedupe_key=f"urgent:{topic}",
                notification_title="Time to head out",
                notification_category="location", notification_priority="high",
            )
            logger.info(f"[urgent_lane] travel_nudge result: {urgent_result}")
            if urgent_result.get("sent"):
                sent += 1
                logger.info(f"Leave-now nudge sent for '{title}' ({travel_min}min drive)")
        except Exception as e:
            logger.warning(f"[urgent_lane] travel_nudge failed: {e}")

    return {"sent": sent, "checked": len(events)}
