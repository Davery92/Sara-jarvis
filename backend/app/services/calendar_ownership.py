"""Calendar ownership — who an event actually belongs to.

The iOS sync mirrors every calendar on David's phone: his own, Everett's
school calendar, the shared family ones. Sara must not treat "Everett:
dentist" as David's appointment, so every calendar consumer (brief, prep
notifications, working memory) classifies events through this service.

The mapping lives in app_settings under key 'calendar_ownership' as JSON and
is merged over DEFAULT_CONFIG, so it can be edited via the API without a
deploy. Calendars marked "per_event" (e.g. a shared "Doctors Appts"
calendar) get their owner from family-member names in the event title.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

SETTINGS_KEY = "calendar_ownership"
_CACHE_TTL_SECONDS = 300
_cache: dict = {"loaded_at": 0.0, "config": None}

DEFAULT_CONFIG = {
    "self_name": "David",
    # Family member name -> relation. Used both for calendar names and for
    # detecting whose appointment a per-event calendar entry is.
    "family_members": {"Amanda": "partner", "Everett": "son"},
    # Calendar name (lowercased) -> owner:
    #   "self"      David's own events
    #   "<name>"    that family member's events
    #   "family"    shared/household events
    #   "per_event" owner determined from the event title per entry
    "calendar_owners": {
        "everett": "Everett",
        "school": "Everett",
        "work": "self",
        "pay day": "self",
        "doggos": "family",
        "family": "family",
        "family calendar": "family",
        "fun!": "family",
        "doctors appts": "per_event",
    },
}


@dataclass
class EventOwnership:
    owner: str        # "self", a family member name, or "family"
    is_self: bool
    relation: str     # "", "partner", "son", "household"
    label: str        # display prefix: "" for self, else e.g. "Everett"


def get_config(force_reload: bool = False) -> dict:
    """Load the ownership config (defaults merged with app_settings JSON)."""
    now = time.monotonic()
    if (
        not force_reload
        and _cache["config"] is not None
        and now - _cache["loaded_at"] < _CACHE_TTL_SECONDS
    ):
        return _cache["config"]

    config = {
        "self_name": DEFAULT_CONFIG["self_name"],
        "family_members": dict(DEFAULT_CONFIG["family_members"]),
        "calendar_owners": dict(DEFAULT_CONFIG["calendar_owners"]),
    }
    try:
        from sqlalchemy import text
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            row = db.execute(
                text("SELECT value FROM app_settings WHERE key = :k"),
                {"k": SETTINGS_KEY},
            ).fetchone()
        if row and row[0]:
            stored = json.loads(row[0])
            if isinstance(stored.get("self_name"), str):
                config["self_name"] = stored["self_name"]
            if isinstance(stored.get("family_members"), dict):
                config["family_members"].update(stored["family_members"])
            if isinstance(stored.get("calendar_owners"), dict):
                config["calendar_owners"].update(
                    {str(k).lower(): v for k, v in stored["calendar_owners"].items()}
                )
    except Exception as e:
        logger.warning(f"calendar_ownership: falling back to defaults ({e})")

    _cache["config"] = config
    _cache["loaded_at"] = now
    return config


def save_config(overrides: dict) -> dict:
    """Persist override JSON to app_settings and refresh the cache."""
    from sqlalchemy import text
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        db.execute(
            text("""
                INSERT INTO app_settings (key, value, updated_at, updated_by)
                VALUES (:k, :v, NOW(), 'calendar_ownership_api')
                ON CONFLICT (key)
                DO UPDATE SET value = :v, updated_at = NOW(),
                              updated_by = 'calendar_ownership_api'
            """),
            {"k": SETTINGS_KEY, "v": json.dumps(overrides)},
        )
        db.commit()
    return get_config(force_reload=True)


def _member_in_title(title: str, family_members: dict) -> Optional[str]:
    for name in family_members:
        if re.search(rf"\b{re.escape(name)}\b", title, re.IGNORECASE):
            return name
    return None


def classify_event(
    title: Optional[str],
    calendar_name: Optional[str],
    config: Optional[dict] = None,
) -> EventOwnership:
    """Classify a calendar event's owner from its source calendar and title."""
    config = config or get_config()
    family = config["family_members"]
    title = title or ""

    owner: Optional[str] = None
    if calendar_name:
        owner = config["calendar_owners"].get(calendar_name.strip().lower())
        # Unmapped calendar named after a family member belongs to them
        if owner is None:
            for name in family:
                if name.lower() == calendar_name.strip().lower():
                    owner = name
                    break

    if owner in ("per_event", "family", None):
        titled = _member_in_title(title, family)
        if titled:
            # A family member named in the title owns the event, even on a
            # shared calendar ("Everett soccer" on Family Calendar → Everett)
            owner = titled
        elif owner in ("per_event", "family"):
            # Shared calendar, no name in the title — household, not David's
            owner = "family"
        else:
            # Unmapped calendar / Sara-created / email-extracted: David's
            owner = "self"

    if owner == "self":
        return EventOwnership(owner="self", is_self=True, relation="", label="")
    if owner == "family":
        return EventOwnership(owner="family", is_self=False, relation="household", label="Family")
    return EventOwnership(
        owner=owner,
        is_self=False,
        relation=family.get(owner, ""),
        label=owner,
    )


def ownership_prefix(ownership: EventOwnership) -> str:
    """Display prefix for event listings: 'Everett: ' or ''."""
    return f"{ownership.label}: " if not ownership.is_self else ""


@dataclass
class AttendanceRole:
    role: str          # "organizer" | "attendee" | "declined" | "unknown"
    is_organizer: bool
    declined: bool
    attendee_count: int
    is_broadcast: bool  # large invite list David didn't organize — low-relevance FYI
    weight: float       # 0-1, how much this event is actually "David's" to prep for


_BROADCAST_ATTENDEE_THRESHOLD = 8


def attendance_role(
    organizer: Optional[str],
    attendees: Optional[list],
    config: Optional[dict] = None,
) -> AttendanceRole:
    """David's relationship to a meeting he's on the calendar for — was he the
    organizer, an invited attendee, or someone who declined? Distinguishes
    "David's meeting" from a broadcast invite he's just CC'd on, so prep
    notifications and brief prioritization don't treat a 40-person all-hands
    the same as a 1:1 he's running."""
    config = config or get_config()
    self_name = (config.get("self_name") or "David").lower()
    attendees = attendees or []
    attendee_count = len(attendees)

    is_organizer = bool(organizer) and self_name in organizer.lower()

    declined = False
    self_found = False
    for a in attendees:
        name = (a.get("name") or "") if isinstance(a, dict) else ""
        email = (a.get("email") or "") if isinstance(a, dict) else ""
        status = (a.get("status") or "") if isinstance(a, dict) else ""
        if self_name in name.lower() or self_name in email.lower():
            self_found = True
            if status.lower() == "declined":
                declined = True
            break

    is_broadcast = (not is_organizer) and attendee_count >= _BROADCAST_ATTENDEE_THRESHOLD

    if declined:
        role, weight = "declined", 0.0
    elif is_organizer:
        role, weight = "organizer", 1.0
    elif is_broadcast:
        role, weight = "attendee", 0.3
    elif self_found or attendee_count > 0:
        role, weight = "attendee", 0.8
    else:
        role, weight = "unknown", 0.8  # no attendee data at all — assume it's David's

    return AttendanceRole(
        role=role, is_organizer=is_organizer, declined=declined,
        attendee_count=attendee_count, is_broadcast=is_broadcast, weight=weight,
    )
