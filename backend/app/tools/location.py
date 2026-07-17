import logging
import uuid
from datetime import timedelta
from typing import Dict, Any, Optional

from app.tools.base import BaseTool, ToolResult
from app.models.location import KnownPlace, LocationTrigger
from app.db.session import get_db
from app.core.timezone import now as local_now
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_ONE_SHOT_TTL_HOURS = 24


async def _resolve_place(db: Session, user_id: str, place: str) -> Dict[str, Any]:
    """
    Resolve a chat-provided place string to either a saved KnownPlace or
    the user's current coordinates (for ad-hoc geofences like "this client site").

    Returns dict with either {"known_place": KnownPlace} or
    {"latitude": ..., "longitude": ..., "label": ...}, or {"error": ...}.
    """
    place_lower = (place or "").strip().lower()

    here_phrases = ("here", "this place", "this location", "this client site", "current location", "where i am")
    if not place_lower or place_lower in here_phrases:
        from app.services.unified_context import read_snapshot
        snap = await read_snapshot(user_id)
        if snap.location_latitude is None or snap.location_longitude is None:
            return {"error": "I don't have a current location for you yet — location sharing may not be enabled on your phone."}
        label = place if place and place_lower not in here_phrases else (snap.current_place or "current location")
        return {"latitude": snap.location_latitude, "longitude": snap.location_longitude, "label": label}

    known = db.query(KnownPlace).filter(
        KnownPlace.user_id == user_id, KnownPlace.is_active == True
    ).all()
    for p in known:
        if place_lower == p.name.lower() or place_lower in p.name.lower() or p.name.lower() in place_lower:
            return {"known_place": p}

    from app.services.unified_context import read_snapshot
    snap = await read_snapshot(user_id)
    if snap.location_latitude is not None and snap.location_longitude is not None:
        return {"latitude": snap.location_latitude, "longitude": snap.location_longitude, "label": place}

    return {"error": f"I don't have a saved place called '{place}', and I don't have your current location to use instead."}


class LocationReminderCreateTool(BaseTool):
    """Create a location-triggered reminder."""

    @property
    def name(self) -> str:
        return "location_reminder_create"

    @property
    def description(self) -> str:
        return (
            "Create a reminder that fires when David enters or leaves a place — e.g. "
            "'when I leave this client site, remind me to go to the store' or "
            "'when I get home remind me to call the plumber'. Use place='here' or "
            "'this place'/'this client site' for his current location. One-shot by "
            "default (expires in 24h if the transition never happens); pass "
            "recurring=true for 'every time I get home...' style reminders."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reminder_title": {"type": "string", "description": "What to remind David of"},
                "trigger_on": {"type": "string", "enum": ["enter", "exit"], "description": "Fire on arrival ('enter') or departure ('exit')"},
                "place": {"type": "string", "description": "Place name (e.g. 'home', 'the gym'), or 'here'/'this place' for current location"},
                "description": {"type": "string", "description": "Optional longer description"},
                "recurring": {"type": "boolean", "description": "If true, fires every time (with a cooldown); if false, fires once then expires (default: false)", "default": False},
            },
            "required": ["reminder_title", "trigger_on", "place"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        reminder_title = kwargs.get("reminder_title")
        trigger_on = kwargs.get("trigger_on")
        place = kwargs.get("place")
        description = kwargs.get("description", "")
        recurring = bool(kwargs.get("recurring", False))

        if not reminder_title or not trigger_on or not place:
            return ToolResult(success=False, message="reminder_title, trigger_on, and place are required")
        if trigger_on not in ("enter", "exit"):
            return ToolResult(success=False, message="trigger_on must be 'enter' or 'exit'")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            resolved = await _resolve_place(db, user_id, place)
            if "error" in resolved:
                return ToolResult(success=False, message=resolved["error"])

            trigger = LocationTrigger(
                user_id=user_id,
                trigger_on=trigger_on,
                reminder_title=reminder_title,
                reminder_description=description,
                recurring=recurring,
                status="armed",
                expires_at=None if recurring else (local_now() + timedelta(hours=DEFAULT_ONE_SHOT_TTL_HOURS)),
            )

            is_adhoc = "known_place" not in resolved
            if not is_adhoc:
                kp = resolved["known_place"]
                trigger.place_id = kp.id
                trigger.label = kp.name
            else:
                trigger.latitude = resolved["latitude"]
                trigger.longitude = resolved["longitude"]
                trigger.radius_m = 150
                trigger.label = resolved["label"]

            db.add(trigger)
            db.commit()
            db.refresh(trigger)

            if is_adhoc:
                # Ad-hoc triggers are always created at the user's current
                # location, so seed the enter/exit baseline as "inside" —
                # otherwise the first exit is never detected (no prior state
                # to diff against).
                from app.services.location_service import seed_adhoc_trigger_inside_state
                await seed_adhoc_trigger_inside_state(trigger.id, inside=True)

            verb = "arrive at" if trigger_on == "enter" else "leave"
            return ToolResult(
                success=True,
                data={"trigger_id": trigger.id, "label": trigger.label, "trigger_on": trigger_on, "recurring": recurring},
                message=f"Got it — I'll remind you to \"{reminder_title}\" when you {verb} {trigger.label}."
                + ("" if recurring else " (one-time, expires in 24h if it doesn't fire)"),
            )
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to create location reminder: {str(e)}")
        finally:
            db.close()


class LocationReminderListTool(BaseTool):
    """List armed location-triggered reminders."""

    @property
    def name(self) -> str:
        return "location_reminder_list"

    @property
    def description(self) -> str:
        return "List David's active location-triggered reminders (armed, not yet fired or cancelled)."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            triggers = db.query(LocationTrigger).filter(
                LocationTrigger.user_id == user_id, LocationTrigger.status == "armed"
            ).order_by(LocationTrigger.created_at.desc()).all()

            items = [{
                "trigger_id": t.id,
                "reminder_title": t.reminder_title,
                "trigger_on": t.trigger_on,
                "label": t.label,
                "recurring": t.recurring,
            } for t in triggers]

            return ToolResult(
                success=True,
                data={"triggers": items, "total_found": len(items)},
                message=f"Found {len(items)} active location reminder(s)",
            )
        finally:
            db.close()


class LocationReminderCancelTool(BaseTool):
    """Cancel a location-triggered reminder."""

    @property
    def name(self) -> str:
        return "location_reminder_cancel"

    @property
    def description(self) -> str:
        return "Cancel an armed location-triggered reminder by ID."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {"trigger_id": {"type": "string", "description": "The location trigger ID to cancel"}},
            "required": ["trigger_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        trigger_id = kwargs.get("trigger_id")
        if not trigger_id:
            return ToolResult(success=False, message="trigger_id is required")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            trigger = db.query(LocationTrigger).filter(
                LocationTrigger.id == trigger_id, LocationTrigger.user_id == user_id
            ).first()
            if not trigger:
                return ToolResult(success=False, message="Location reminder not found")

            trigger.status = "cancelled"
            db.commit()
            return ToolResult(success=True, data={"trigger_id": trigger_id}, message=f"Cancelled location reminder: {trigger.reminder_title}")
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to cancel: {str(e)}")
        finally:
            db.close()


class PlacesSaveTool(BaseTool):
    """Save a named place, usually at David's current location."""

    @property
    def name(self) -> str:
        return "places_save"

    @property
    def description(self) -> str:
        return (
            "Save a place using David's actual current GPS coordinates, so Sara can recognize "
            "when he arrives at or leaves it later (geofencing, location-triggered reminders). "
            "This is the correct tool whenever David says 'remember this place as ...', "
            "'save my current location as ...', or names home/work/gym/a client site while he's "
            "there — do NOT use remember_about_david for this, it doesn't capture coordinates."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name for the place"},
                "place_type": {"type": "string", "enum": ["home", "work", "gym", "client_site", "store", "other"], "description": "Category of place (default: other)"},
            },
            "required": ["name"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        name = kwargs.get("name")
        place_type = kwargs.get("place_type", "other")
        if not name:
            return ToolResult(success=False, message="name is required")

        from app.services.unified_context import read_snapshot
        snap = await read_snapshot(user_id)
        if snap.location_latitude is None or snap.location_longitude is None:
            return ToolResult(success=False, message="I don't have your current location yet — location sharing may not be enabled on your phone.")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            place = KnownPlace(
                user_id=user_id, name=name, place_type=place_type,
                latitude=snap.location_latitude, longitude=snap.location_longitude,
                radius_m=150, source="chat",
            )
            db.add(place)
            db.commit()
            db.refresh(place)

            try:
                from app.services.personal_knowledge_graph import personal_kg
                personal_kg.upsert_fact(
                    fact_type="Place",
                    properties={"name": name, "type": place_type, "address": "", "significance": ""},
                    confidence=0.9, source="explicit_statement",
                )
            except Exception as e:
                logger.debug(f"PKG place mirror failed: {e}")

            return ToolResult(success=True, data={"place_id": place.id, "name": name}, message=f"Saved '{name}' as a known place.")
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to save place: {str(e)}")
        finally:
            db.close()


class PlacesListTool(BaseTool):
    """List saved places."""

    @property
    def name(self) -> str:
        return "places_list"

    @property
    def description(self) -> str:
        return "List David's saved places (home, work, gym, client sites, etc)."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            places = db.query(KnownPlace).filter(
                KnownPlace.user_id == user_id, KnownPlace.is_active == True
            ).order_by(KnownPlace.name).all()

            items = [{"place_id": p.id, "name": p.name, "place_type": p.place_type, "visit_count": p.visit_count} for p in places]
            return ToolResult(success=True, data={"places": items, "total_found": len(items)}, message=f"Found {len(items)} saved place(s)")
        finally:
            db.close()


class PlacesDeleteTool(BaseTool):
    """Delete/deactivate a saved place."""

    @property
    def name(self) -> str:
        return "places_delete"

    @property
    def description(self) -> str:
        return "Forget a saved place by name or ID."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {"place": {"type": "string", "description": "Place name or ID to forget"}},
            "required": ["place"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        place_ref = kwargs.get("place")
        if not place_ref:
            return ToolResult(success=False, message="place is required")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            place = db.query(KnownPlace).filter(
                KnownPlace.user_id == user_id, KnownPlace.id == place_ref
            ).first()
            if not place:
                place = db.query(KnownPlace).filter(
                    KnownPlace.user_id == user_id,
                    KnownPlace.is_active == True,
                ).filter(KnownPlace.name.ilike(f"%{place_ref}%")).first()

            if not place:
                return ToolResult(success=False, message=f"No saved place matching '{place_ref}'")

            place.is_active = False
            db.commit()
            return ToolResult(success=True, data={"place_id": place.id}, message=f"Forgot place: {place.name}")
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to delete place: {str(e)}")
        finally:
            db.close()
