"""
Location Service — classification, transition detection, and location-triggered
reminders/standing-orders. The single brain behind the /api/location routes.

Two geofence sources feed this:
  - iOS significant-location-change reports (periodic, coarse) -> process_report()
  - iOS native CLRegion monitoring (enter/exit, exact) -> handle_geofence_event()

process_report() also does a lightweight distance check against ad-hoc
(unsaved) trigger geofences so location-triggered reminders still fire even
if the OS-level region monitor hasn't caught up yet.
"""
import logging
import math
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.timezone import now as local_now
from app.models.location import KnownPlace, LocationTrigger, LocationEvent
from app.models.reminder import Reminder

logger = logging.getLogger(__name__)

_LAST_PLACE_KEY = "sara:location:last_place:{user_id}"
_ADHOC_INSIDE_KEY = "sara:location:trigger_inside:{trigger_id}"
_STATE_TTL_SECONDS = 60 * 60 * 24 * 7  # a week — cheap to recompute if it expires


async def _get_redis():
    from app.services.unified_context import _get_redis as _shared_get_redis
    return await _shared_get_redis()


async def seed_adhoc_trigger_inside_state(trigger_id: str, inside: bool = True) -> None:
    """Seed the enter/exit baseline for a freshly-created ad-hoc trigger.

    Ad-hoc triggers are always created at the user's current coordinates
    (see _resolve_place in tools/location.py), so the user is "inside" at
    creation time. Without this, _check_adhoc_geofences has no prior state to
    diff against and silently misses the very first exit."""
    r = await _get_redis()
    await r.set(_ADHOC_INSIDE_KEY.format(trigger_id=trigger_id), "1" if inside else "0", ex=_STATE_TTL_SECONDS)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in meters between two lat/lon points."""
    R = 6371000
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def classify(db: Session, user_id: str, lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """Find the nearest active known_place within its radius. Postgres haversine — cheap, no PostGIS needed."""
    row = db.execute(text("""
        SELECT id, name, place_type, latitude, longitude, radius_m,
               2 * 6371000 * asin(sqrt(
                   sin(radians((:lat - latitude) / 2)) ^ 2 +
                   cos(radians(latitude)) * cos(radians(:lat)) *
                   sin(radians((:lon - longitude) / 2)) ^ 2
               )) AS dist_m
        FROM known_place
        WHERE user_id = :user_id AND is_active = TRUE
        ORDER BY dist_m ASC
        LIMIT 1
    """), {"user_id": user_id, "lat": lat, "lon": lon}).fetchone()

    if row and row.dist_m <= row.radius_m:
        return {
            "id": row.id,
            "name": row.name,
            "place_type": row.place_type,
            "latitude": row.latitude,
            "longitude": row.longitude,
            "radius_m": row.radius_m,
        }

    # Fallback: classify against PKG_Place nodes in Neo4j (pre-existing behavior)
    try:
        from app.services.personal_knowledge_graph import personal_kg
        if personal_kg._ensure_driver():
            with personal_kg.driver.session() as session:
                result = session.run("""
                    MATCH (p:PKG_Place)
                    WHERE p.latitude IS NOT NULL AND p.longitude IS NOT NULL
                    WITH p,
                         point.distance(
                             point({latitude: $lat, longitude: $lon}),
                             point({latitude: p.latitude, longitude: p.longitude})
                         ) AS dist
                    WHERE dist < 500
                    RETURN p.name AS name, p.type AS place_type, dist
                    ORDER BY dist ASC
                    LIMIT 1
                """, {"lat": lat, "lon": lon})
                pkg_row = result.single()
                if pkg_row and pkg_row["name"]:
                    return {
                        "id": None,
                        "name": pkg_row["name"],
                        "place_type": pkg_row["place_type"] or "other",
                        "latitude": lat,
                        "longitude": lon,
                        "radius_m": 500,
                    }
    except Exception as e:
        logger.debug(f"PKG place classification failed: {e}")

    return None


async def process_report(db: Session, user_id: str, lat: float, lon: float,
                          accuracy: Optional[float], source: str) -> Dict[str, Any]:
    """Handle a periodic location report from the phone."""
    place = classify(db, user_id, lat, lon)

    event = LocationEvent(
        user_id=user_id,
        latitude=lat,
        longitude=lon,
        accuracy=accuracy,
        place_id=place["id"] if place else None,
        event_type="report",
        source=source,
    )
    db.add(event)

    r = await _get_redis()
    last_place_id = await r.get(_LAST_PLACE_KEY.format(user_id=user_id))
    new_place_id = place["id"] if place else None

    if (last_place_id or None) != (new_place_id or None):
        if last_place_id:
            old_place = _fetch_place(db, last_place_id)
            if old_place:
                await _handle_transition(db, user_id, "exit", old_place, lat, lon)
        if place:
            await _handle_transition(db, user_id, "enter", place, lat, lon)

        if new_place_id:
            await r.set(_LAST_PLACE_KEY.format(user_id=user_id), new_place_id, ex=_STATE_TTL_SECONDS)
        else:
            await r.delete(_LAST_PLACE_KEY.format(user_id=user_id))

    if place and place.get("id"):
        db.execute(text("""
            UPDATE known_place SET visit_count = visit_count + 1, last_seen_at = NOW()
            WHERE id = :id
        """), {"id": place["id"]})

    db.commit()

    await _check_adhoc_geofences(db, user_id, lat, lon)
    await _update_context(user_id, place, lat, lon)

    return {"classified_place": place["name"] if place else None}


async def handle_geofence_event(db: Session, user_id: str, region_id: str,
                                 event_type: str, lat: float, lon: float,
                                 event_time: Optional[str] = None) -> Dict[str, Any]:
    """Handle a trusted native geofence transition from iOS. region_id is either a
    known_place.id or a location_trigger.id (see geofence_payload).

    ``event_time`` (ISO8601) is set when the phone replays an event it queued while
    the backend was unreachable (Phase 10A-fix); a stale replay (>1h old) is
    recorded but skips presence-state changes so we don't mis-set 'David is here'
    hours after the fact.
    """
    stale_replay = False
    if event_time:
        try:
            from datetime import datetime, timezone
            et = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
            if et.tzinfo is None:
                et = et.replace(tzinfo=timezone.utc)
            stale_replay = (datetime.now(timezone.utc) - et).total_seconds() > 3600
        except Exception:
            stale_replay = False
    if stale_replay:
        return {"handled": True, "kind": "late_replay", "stale": True, "region_id": region_id}

    place = _fetch_place(db, region_id)
    if place:
        r = await _get_redis()
        last_place_id = await r.get(_LAST_PLACE_KEY.format(user_id=user_id))

        # State guard: resyncGeofences() re-registers regions on every app
        # foreground, and iOS fires an initial "enter" for any region the
        # device is already inside — plus occasional duplicate enter/exit
        # pairs seconds apart. If this event doesn't actually change presence
        # state, swallow it: no location_event row, no emission, no triggers.
        if event_type == "enter" and last_place_id == place["id"]:
            return {"handled": True, "kind": "place", "deduped": "already_present"}
        if event_type == "exit" and last_place_id != place["id"]:
            return {"handled": True, "kind": "place", "deduped": "not_present"}

        # Cheap raw dedup: an identical (place_id, event_type) row landed in
        # the last 120s (e.g. two near-simultaneous OS callbacks).
        recent = db.execute(text("""
            SELECT 1 FROM location_event
            WHERE user_id = :user_id AND place_id = :place_id AND event_type = :event_type
                  AND created_at >= NOW() - INTERVAL '120 seconds'
            LIMIT 1
        """), {"user_id": user_id, "place_id": place["id"], "event_type": event_type}).fetchone()
        if recent:
            return {"handled": True, "kind": "place", "deduped": "recent_duplicate"}

        db.add(LocationEvent(
            user_id=user_id, latitude=lat, longitude=lon, place_id=place["id"],
            event_type=event_type, source="ios_geofence",
        ))
        if event_type == "enter":
            await r.set(_LAST_PLACE_KEY.format(user_id=user_id), place["id"], ex=_STATE_TTL_SECONDS)
            # Native geofence enters bypass process_report()'s visit_count bump —
            # a real (state-changing) enter should still count as a visit.
            db.execute(text("""
                UPDATE known_place SET visit_count = visit_count + 1, last_seen_at = NOW()
                WHERE id = :id
            """), {"id": place["id"]})
        else:
            await r.delete(_LAST_PLACE_KEY.format(user_id=user_id))
        db.commit()
        await _handle_transition(db, user_id, event_type, place, lat, lon)
        await _update_context(user_id, place if event_type == "enter" else None, lat, lon)
        return {"handled": True, "kind": "place"}

    trigger = db.execute(text("""
        SELECT * FROM location_trigger WHERE id = :id AND user_id = :user_id
    """), {"id": region_id, "user_id": user_id}).fetchone()
    if trigger and trigger.trigger_on == event_type:
        db.add(LocationEvent(
            user_id=user_id, latitude=lat, longitude=lon, place_id=None,
            event_type=event_type, source="ios_geofence",
        ))
        db.commit()
        await _fire_trigger(db, trigger)
        return {"handled": True, "kind": "trigger"}

    return {"handled": False}


def _fetch_place(db: Session, place_id: str) -> Optional[Dict[str, Any]]:
    row = db.execute(text("""
        SELECT id, name, place_type, latitude, longitude, radius_m
        FROM known_place WHERE id = :id
    """), {"id": place_id}).fetchone()
    if not row:
        return None
    return {
        "id": row.id, "name": row.name, "place_type": row.place_type,
        "latitude": row.latitude, "longitude": row.longitude, "radius_m": row.radius_m,
    }


async def _handle_transition(db: Session, user_id: str, event_type: str,
                              place: Dict[str, Any], lat: float, lon: float) -> None:
    label = place["name"]
    place_type = place.get("place_type") or "other"
    logger.info(f"Location transition: {event_type} '{label}' ({place_type})")

    try:
        from app.services.event_bus import emit_event, EventType
        await emit_event(
            EventType.LOCATION_PLACE_ENTERED if event_type == "enter" else EventType.LOCATION_PLACE_EXITED,
            user_id,
            payload={"place_id": place.get("id"), "label": label, "place_type": place_type,
                     "latitude": lat, "longitude": lon},
            source="location_service",
        )
    except Exception as e:
        logger.debug(f"Failed to emit location event: {e}")

    try:
        from app.services.activity_state_machine import activity_state_machine, ActivitySignal
        if place_type == "home":
            value = "home_arrival" if event_type == "enter" else "left_home"
        elif place_type == "gym":
            value = "gym_arrival" if event_type == "enter" else None
        else:
            value = None
        if value:
            activity_state_machine.process_signal(ActivitySignal(
                signal_type="device", source="ios_location", value=value,
                metadata={"place": label},
            ))
    except Exception as e:
        logger.debug(f"Activity state machine signal failed: {e}")

    if place_type == "home":
        try:
            from app.services.standing_order_service import standing_order_service
            await standing_order_service.evaluate_trigger(
                trigger_type="presence",
                context={"presence_state": "home" if event_type == "enter" else "away"},
                db=db,
            )
        except Exception as e:
            logger.debug(f"Standing order presence eval failed: {e}")

    if place.get("id"):
        await _fire_place_triggers(db, user_id, event_type, place)


async def _fire_place_triggers(db: Session, user_id: str, event_type: str, place: Dict[str, Any]) -> None:
    rows = db.execute(text("""
        SELECT * FROM location_trigger
        WHERE user_id = :user_id AND status = 'armed' AND trigger_on = :trigger_on AND place_id = :place_id
    """), {"user_id": user_id, "trigger_on": event_type, "place_id": place["id"]}).fetchall()
    for row in rows:
        await _fire_trigger(db, row)


async def _check_adhoc_geofences(db: Session, user_id: str, lat: float, lon: float) -> None:
    """Backup distance-based geofence check for ad-hoc (unsaved-place) triggers."""
    rows = db.execute(text("""
        SELECT * FROM location_trigger
        WHERE user_id = :user_id AND status = 'armed' AND place_id IS NULL
              AND latitude IS NOT NULL AND longitude IS NOT NULL
    """), {"user_id": user_id}).fetchall()
    if not rows:
        return

    r = await _get_redis()
    for row in rows:
        dist = haversine_m(lat, lon, row.latitude, row.longitude)
        inside = dist <= (row.radius_m or 150)
        state_key = _ADHOC_INSIDE_KEY.format(trigger_id=row.id)
        was_inside = (await r.get(state_key)) == "1"

        await r.set(state_key, "1" if inside else "0", ex=_STATE_TTL_SECONDS)

        if inside == was_inside:
            continue
        if (inside and row.trigger_on == "enter") or (not inside and row.trigger_on == "exit"):
            await _fire_trigger(db, row)


async def _fire_trigger(db: Session, trigger_row) -> None:
    """Create a reminder + push for a matched, armed location_trigger row."""
    now = local_now()

    if trigger_row.last_fired_at:
        last_fired = trigger_row.last_fired_at
        if last_fired.tzinfo is None:
            from datetime import timezone as _tz
            last_fired = last_fired.replace(tzinfo=_tz.utc)
        minutes_since = (now - last_fired).total_seconds() / 60
        if minutes_since < (trigger_row.cooldown_minutes or 60):
            return

    reminder = Reminder(
        user_id=trigger_row.user_id,
        title=trigger_row.reminder_title,
        description=trigger_row.reminder_description or "",
        reminder_time=now,
        is_completed=False,
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)

    try:
        from app.routes.push_tokens import send_push_to_user
        await send_push_to_user(
            user_id=trigger_row.user_id,
            title=f"Reminder: {trigger_row.reminder_title}",
            body=trigger_row.reminder_description or f"You just {'arrived at' if trigger_row.trigger_on == 'enter' else 'left'} {trigger_row.label}",
            notification_data={
                "type": "location_reminder",
                "reminder_id": reminder.id,
                "location_trigger_id": trigger_row.id,
            },
        )
    except Exception as e:
        logger.warning(f"Location trigger push failed for #{trigger_row.id}: {e}")

    if trigger_row.recurring:
        db.execute(text("""
            UPDATE location_trigger SET last_fired_at = NOW() WHERE id = :id
        """), {"id": trigger_row.id})
    else:
        db.execute(text("""
            UPDATE location_trigger SET status = 'fired', last_fired_at = NOW() WHERE id = :id
        """), {"id": trigger_row.id})
    db.commit()

    logger.info(f"Location trigger #{trigger_row.id} fired: '{trigger_row.reminder_title}' ({trigger_row.trigger_on} {trigger_row.label})")


async def _update_context(user_id: str, place: Optional[Dict[str, Any]], lat: float, lon: float) -> None:
    from app.services.context_writer import update_fields
    from app.services.unified_context import read_snapshot

    fields = {
        "location_latitude": lat,
        "location_longitude": lon,
        "last_location_at": local_now().isoformat(),
    }
    if place:
        try:
            snap = await read_snapshot(user_id)
            if snap.current_place != place["name"]:
                fields["at_place_since"] = local_now().isoformat()
        except Exception:
            fields["at_place_since"] = local_now().isoformat()
        fields["current_place"] = place["name"]
        fields["current_place_type"] = place.get("place_type") or "other"
    else:
        fields["current_place"] = "unknown"
        fields["current_place_type"] = ""
        fields["at_place_since"] = local_now().isoformat()

    await update_fields(user_id, source="location", **fields)


def geofence_payload(db: Session, user_id: str, max_regions: int = 18) -> List[Dict[str, Any]]:
    """Regions the phone should register for native CLRegion monitoring.
    Prioritizes armed ad-hoc triggers, then home, then places with armed triggers,
    then most-visited places, capped at max_regions (iOS hard limit is 20)."""
    regions: List[Dict[str, Any]] = []

    adhoc = db.execute(text("""
        SELECT id, latitude, longitude, radius_m, trigger_on
        FROM location_trigger
        WHERE user_id = :user_id AND status = 'armed' AND place_id IS NULL
              AND latitude IS NOT NULL AND longitude IS NOT NULL
        ORDER BY created_at DESC
    """), {"user_id": user_id}).fetchall()
    for row in adhoc:
        regions.append({
            "identifier": row.id, "kind": "trigger",
            "latitude": row.latitude, "longitude": row.longitude,
            "radius_m": row.radius_m or 150,
            "notify_on_entry": row.trigger_on == "enter",
            "notify_on_exit": row.trigger_on == "exit",
        })

    places = db.execute(text("""
        SELECT kp.id, kp.name, kp.place_type, kp.latitude, kp.longitude, kp.radius_m,
               EXISTS(SELECT 1 FROM location_trigger lt WHERE lt.place_id = kp.id AND lt.status = 'armed') AS has_trigger
        FROM known_place kp
        WHERE kp.user_id = :user_id AND kp.is_active = TRUE
        ORDER BY (kp.place_type = 'home') DESC, has_trigger DESC, kp.visit_count DESC
    """), {"user_id": user_id}).fetchall()
    for row in places:
        if len(regions) >= max_regions:
            break
        regions.append({
            "identifier": row.id, "kind": "place",
            "latitude": row.latitude, "longitude": row.longitude,
            "radius_m": row.radius_m,
            "notify_on_entry": True,
            "notify_on_exit": True,
            # Whether an armed location_trigger rides on this place — the phone uses
            # this to decide whether a failed geofence POST is worth a local "couldn't
            # reach the server" notice (Phase 10A-fix). A plain presence place isn't.
            "has_trigger": bool(row.has_trigger),
        })

    return regions[:max_regions]


# ── Place discovery ──────────────────────────────────────────────────────
# Groups recent location_event rows into ~100m grid cells; any cell visited
# on enough distinct days, and not already near a saved/suggested place,
# gets staged as a suggestion (status='suggested', is_active=False) for the
# webapp to show. Deliberately doesn't push a notification for this — it's a
# passive suggestion, not something worth interrupting for.

_DISCOVERY_LOOKBACK_DAYS = 30
_DISCOVERY_MIN_VISIT_DAYS = 3
_DISCOVERY_MAX_SUGGESTIONS_PER_RUN = 3
_DISCOVERY_MIN_DISTANCE_FROM_EXISTING_M = 250


async def discover_and_stage_places(db: Session, user_id: str) -> List[Dict[str, Any]]:
    """Find frequently-visited spots with no saved place nearby and stage them
    as suggestions. Returns the newly-created suggestion rows."""
    clusters = db.execute(text("""
        SELECT
            round(latitude::numeric, 3) AS grid_lat,
            round(longitude::numeric, 3) AS grid_lon,
            avg(latitude) AS centroid_lat,
            avg(longitude) AS centroid_lon,
            count(DISTINCT created_at::date) AS visit_days,
            count(*) AS visit_count
        FROM location_event
        WHERE user_id = :user_id
              AND created_at >= NOW() - make_interval(days => :lookback_days)
        GROUP BY grid_lat, grid_lon
        HAVING count(DISTINCT created_at::date) >= :min_days
        ORDER BY visit_days DESC, visit_count DESC
    """), {
        "user_id": user_id,
        "lookback_days": _DISCOVERY_LOOKBACK_DAYS,
        "min_days": _DISCOVERY_MIN_VISIT_DAYS,
    }).fetchall()

    if not clusters:
        return []

    existing = db.execute(text("""
        SELECT latitude, longitude FROM known_place
        WHERE user_id = :user_id AND status IN ('active', 'suggested')
    """), {"user_id": user_id}).fetchall()

    created: List[Dict[str, Any]] = []
    for cluster in clusters:
        if len(created) >= _DISCOVERY_MAX_SUGGESTIONS_PER_RUN:
            break

        too_close = any(
            haversine_m(cluster.centroid_lat, cluster.centroid_lon, e.latitude, e.longitude)
            < _DISCOVERY_MIN_DISTANCE_FROM_EXISTING_M
            for e in existing
        )
        if too_close:
            continue

        label = await _reverse_geocode_label(cluster.centroid_lat, cluster.centroid_lon)
        place = KnownPlace(
            user_id=user_id,
            name=label or f"Unnamed place ({int(cluster.visit_days)} visits)",
            place_type="other",
            latitude=cluster.centroid_lat,
            longitude=cluster.centroid_lon,
            radius_m=150,
            source="learned",
            status="suggested",
            is_active=False,
            visit_count=int(cluster.visit_count),
        )
        db.add(place)
        existing.append(place)  # avoid suggesting two clusters right next to each other in the same run
        created.append({"name": place.name, "latitude": place.latitude, "longitude": place.longitude, "visit_days": int(cluster.visit_days)})

    if created:
        db.commit()
        logger.info(f"Place discovery: staged {len(created)} suggestion(s) for user {user_id}")

    return created


async def _reverse_geocode_label(lat: float, lon: float) -> Optional[str]:
    """Best-effort human-readable label for a discovered cluster centroid."""
    try:
        import httpx
        from app.services.travel_nudge import USER_AGENT
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lon, "format": "json"},
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()
            addr = data.get("address", {})
            road = addr.get("road")
            house = addr.get("house_number")
            city = addr.get("city") or addr.get("town") or addr.get("village")
            if road and city:
                return f"{house + ' ' if house else ''}{road}, {city}"
            return data.get("display_name", "").split(",")[0] or None
    except Exception as e:
        logger.debug(f"Reverse geocode failed for discovery label: {e}")
        return None
