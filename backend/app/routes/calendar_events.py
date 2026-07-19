"""Calendar events routes."""
import uuid
import logging
from datetime import datetime
from app.core.timezone import naive_local_now
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.models.user import User
from app.tools.calendar import CalendarEvent, build_rrule  # Use existing model with extend_existing
from app.schemas.calendar import (
    CalendarEventCreate, CalendarEventUpdate, CalendarEventResponse,
    IOSCalendarSyncRequest, IOSCalendarSyncResponse
)
from app.services.calendar_reminders import sync_event_reminders, clear_event_reminders
from app.models.ios_event_block import IOSEventBlock
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["Calendar"])


def _to_naive_local(dt: datetime, tz: ZoneInfo) -> datetime:
    """Convert to naive local time. If already naive, treat as local (no conversion)."""
    if dt.tzinfo is not None:
        return dt.astimezone(tz).replace(tzinfo=None)
    return dt


def _supersede_email_duplicates(db: Session, user_id: str, ios_event: CalendarEvent) -> None:
    """When the iPhone syncs in an event Sara already created from an email
    invite, the iOS copy wins: repoint any linked emails at it and delete the
    email_sync duplicate. Match = similar normalized title, same day, starts
    within 90 minutes."""
    try:
        from datetime import timedelta
        from app.tasks.email_sync import _normalize_meeting_title
        from app.models.email import Email as EmailModel

        day_start = ios_event.start_time.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        candidates = db.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.source == "email_sync",
            CalendarEvent.start_time >= day_start,
            CalendarEvent.start_time < day_end,
        ).all()

        ios_norm = _normalize_meeting_title(ios_event.title)
        for dup in candidates:
            dup_norm = _normalize_meeting_title(dup.title)
            titles_match = (
                dup_norm == ios_norm or dup_norm in ios_norm or ios_norm in dup_norm
            )
            if not titles_match:
                continue
            minutes_apart = abs((dup.start_time - ios_event.start_time).total_seconds()) / 60
            if minutes_apart > 90:
                continue
            db.query(EmailModel).filter(
                EmailModel.calendar_event_id == dup.id
            ).update({"calendar_event_id": ios_event.id})
            db.delete(dup)
            logger.info(
                f"iOS sync superseded email_sync event {dup.id} "
                f"('{dup.title}') with {ios_event.id}"
            )
    except Exception as e:
        logger.warning(f"Cross-source supersede check failed: {e}")


@router.get("/ownership")
async def get_calendar_ownership(current_user: User = Depends(get_current_user)):
    """The calendar→owner mapping used to attribute events to family members."""
    from app.services.calendar_ownership import get_config
    return get_config(force_reload=True)


@router.put("/ownership")
async def update_calendar_ownership(
    overrides: dict,
    current_user: User = Depends(get_current_user),
):
    """Replace the stored ownership overrides (merged over built-in defaults).

    Shape: {"self_name": str, "family_members": {name: relation},
            "calendar_owners": {calendar_name: "self"|"family"|"per_event"|<member name>}}
    """
    from app.services.calendar_ownership import save_config, SETTINGS_KEY
    allowed = {"self_name", "family_members", "calendar_owners", "aliases", "acknowledged_unmapped"}
    unknown = set(overrides) - allowed
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown keys: {sorted(unknown)}")

    # Merge over the currently-stored overrides so a partial PUT (e.g. only
    # calendar_owners from the Settings panel) doesn't wipe aliases /
    # acknowledged_unmapped. save_config replaces the whole app_settings value.
    import json as _json
    from sqlalchemy import text
    from app.db.session import SessionLocal
    stored = {}
    try:
        with SessionLocal() as _db:
            row = _db.execute(text("SELECT value FROM app_settings WHERE key = :k"),
                              {"k": SETTINGS_KEY}).fetchone()
            if row and row[0]:
                stored = _json.loads(row[0])
    except Exception:
        stored = {}
    merged = {**stored, **overrides}
    return save_config(merged)


@router.get("/calendars")
async def list_synced_calendars(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Synced iOS calendars with their event counts and current owner mapping —
    powers the ownership Settings panel (a dropdown per calendar)."""
    from sqlalchemy import text
    from app.services.calendar_ownership import get_config, classify_event
    cfg = get_config(force_reload=True)
    rows = db.execute(text("""
        SELECT ios_calendar_name AS name, count(*) AS n,
               max(owner) AS sample_owner
        FROM calendar_event
        WHERE ios_calendar_name IS NOT NULL AND source = 'ios_calendar'
        GROUP BY ios_calendar_name ORDER BY count(*) DESC
    """)).fetchall()
    out = []
    for r in rows:
        low = (r.name or "").strip().lower()
        mapped = cfg["calendar_owners"].get(low)
        out.append({
            "calendar": r.name,
            "events": int(r.n),
            "mapped_owner": mapped,  # None => unmapped
            "acknowledged": low in {str(c).lower() for c in cfg.get("acknowledged_unmapped", [])},
        })
    return {
        "calendars": out,
        "self_name": cfg["self_name"],
        "family_members": cfg["family_members"],
        "aliases": cfg.get("aliases", {}),
    }


@router.get("/events", response_model=List[CalendarEventResponse])
async def list_calendar_events(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all calendar events."""
    import os
    local_tz = ZoneInfo(os.environ.get("TIMEZONE", "America/New_York"))
    query = db.query(CalendarEvent).filter(CalendarEvent.user_id == current_user.id)

    if start_date:
        try:
            start_dt = _to_naive_local(datetime.fromisoformat(start_date.replace('Z', '+00:00')), local_tz)
            query = query.filter(CalendarEvent.start_time >= start_dt)
        except:
            pass

    if end_date:
        try:
            end_dt = _to_naive_local(datetime.fromisoformat(end_date.replace('Z', '+00:00')), local_tz)
            query = query.filter(CalendarEvent.start_time <= end_dt)
        except:
            pass

    events = query.order_by(CalendarEvent.start_time).all()

    return [
        CalendarEventResponse(
            id=event.id,
            title=event.title,
            description=event.description,
            start_time=event.start_time.isoformat(),
            end_time=event.end_time.isoformat(),
            location=event.location or None,
            all_day=event.all_day,
            reminder_minutes=event.reminder_minutes,
            is_completed=event.is_completed if isinstance(event.is_completed, bool) else event.is_completed == "true",
            rrule=getattr(event, 'rrule', None),
            is_recurring=bool(getattr(event, 'rrule', None)),
            source=getattr(event, 'source', 'sara') or 'sara',
            ios_event_id=getattr(event, 'ios_event_id', None),
            ios_calendar_id=getattr(event, 'ios_calendar_id', None),
            ios_calendar_name=getattr(event, 'ios_calendar_name', None),
            read_only=getattr(event, 'read_only', False) or False,
            created_at=event.created_at.isoformat(),
            updated_at=event.updated_at.isoformat()
        )
        for event in events
    ]


@router.post("/events", response_model=CalendarEventResponse)
async def create_calendar_event(
    event_data: CalendarEventCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a calendar event."""
    import os
    local_tz = ZoneInfo(os.environ.get("TIMEZONE", "America/New_York"))
    # Convert to local time for naive DateTime storage
    start_dt = _to_naive_local(datetime.fromisoformat(event_data.start_time.replace('Z', '+00:00')), local_tz)
    end_dt = _to_naive_local(datetime.fromisoformat(event_data.end_time.replace('Z', '+00:00')), local_tz)

    # Handle recurrence - use provided rrule or build from friendly recurrence value
    rrule = event_data.rrule
    if not rrule and event_data.recurrence:
        freq_map = {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY", "yearly": "YEARLY", "weekdays": "WEEKLY"}
        freq = freq_map.get(event_data.recurrence.lower())
        if freq:
            days = ["MO", "TU", "WE", "TH", "FR"] if event_data.recurrence.lower() == "weekdays" else None
            rrule = build_rrule(frequency=freq, days=days)

    event = CalendarEvent(
        user_id=current_user.id,
        title=event_data.title,
        description=event_data.description or "",
        start_time=start_dt,
        end_time=end_dt,
        location=event_data.location or "",
        all_day=event_data.all_day or False,
        reminder_minutes=event_data.reminder_minutes,
        rrule=rrule
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    if event.reminder_minutes is not None:
        sync_event_reminders(db, event)
        db.commit()

    return CalendarEventResponse(
        id=event.id,
        title=event.title,
        description=event.description,
        start_time=event.start_time.isoformat(),
        end_time=event.end_time.isoformat(),
        location=event.location or None,
        all_day=event.all_day,
        reminder_minutes=event.reminder_minutes,
        is_completed=event.is_completed if isinstance(event.is_completed, bool) else event.is_completed == "true",
        rrule=event.rrule,
        is_recurring=bool(event.rrule),
        source=getattr(event, 'source', 'sara') or 'sara',
        ios_event_id=getattr(event, 'ios_event_id', None),
        ios_calendar_id=getattr(event, 'ios_calendar_id', None),
        ios_calendar_name=getattr(event, 'ios_calendar_name', None),
        read_only=getattr(event, 'read_only', False) or False,
        created_at=event.created_at.isoformat(),
        updated_at=event.updated_at.isoformat()
    )


@router.put("/events/{event_id}", response_model=CalendarEventResponse)
async def update_calendar_event(
    event_id: str,
    event_data: CalendarEventUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a calendar event."""
    event = db.query(CalendarEvent).filter(
        CalendarEvent.id == event_id,
        CalendarEvent.user_id == current_user.id
    ).first()

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if event_data.title is not None:
        event.title = event_data.title
    if event_data.description is not None:
        event.description = event_data.description
    if event_data.start_time is not None:
        import os
        local_tz = ZoneInfo(os.environ.get("TIMEZONE", "America/New_York"))
        event.start_time = _to_naive_local(datetime.fromisoformat(event_data.start_time.replace('Z', '+00:00')), local_tz)
    if event_data.end_time is not None:
        import os
        local_tz = ZoneInfo(os.environ.get("TIMEZONE", "America/New_York"))
        event.end_time = _to_naive_local(datetime.fromisoformat(event_data.end_time.replace('Z', '+00:00')), local_tz)
    if event_data.location is not None:
        event.location = event_data.location
    if event_data.all_day is not None:
        event.all_day = event_data.all_day
    if event_data.reminder_minutes is not None:
        event.reminder_minutes = event_data.reminder_minutes
    if event_data.is_completed is not None:
        event.is_completed = event_data.is_completed

    # Handle recurrence update
    if event_data.rrule is not None:
        event.rrule = event_data.rrule if event_data.rrule else None  # Empty string clears recurrence
    elif event_data.recurrence is not None:
        if event_data.recurrence:  # Non-empty recurrence value
            freq_map = {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY", "yearly": "YEARLY", "weekdays": "WEEKLY"}
            freq = freq_map.get(event_data.recurrence.lower())
            if freq:
                days = ["MO", "TU", "WE", "TH", "FR"] if event_data.recurrence.lower() == "weekdays" else None
                event.rrule = build_rrule(frequency=freq, days=days)
        else:
            event.rrule = None  # Empty string clears recurrence

    event.updated_at = naive_local_now()
    db.commit()
    db.refresh(event)

    sync_event_reminders(db, event)
    db.commit()

    return CalendarEventResponse(
        id=event.id,
        title=event.title,
        description=event.description,
        start_time=event.start_time.isoformat(),
        end_time=event.end_time.isoformat(),
        location=event.location or None,
        all_day=event.all_day,
        reminder_minutes=event.reminder_minutes,
        is_completed=event.is_completed if isinstance(event.is_completed, bool) else event.is_completed == "true",
        rrule=event.rrule,
        is_recurring=bool(event.rrule),
        source=getattr(event, 'source', 'sara') or 'sara',
        ios_event_id=getattr(event, 'ios_event_id', None),
        ios_calendar_id=getattr(event, 'ios_calendar_id', None),
        ios_calendar_name=getattr(event, 'ios_calendar_name', None),
        read_only=getattr(event, 'read_only', False) or False,
        created_at=event.created_at.isoformat(),
        updated_at=event.updated_at.isoformat()
    )


@router.delete("/events/{event_id}")
async def delete_calendar_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a calendar event."""
    event = db.query(CalendarEvent).filter(
        CalendarEvent.id == event_id,
        CalendarEvent.user_id == current_user.id
    ).first()

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # For iOS-synced events, also record a blocklist row so the next iOS sync
    # doesn't immediately resurrect the event. The event stays on iPhone.
    if event.source == "ios_calendar" and event.ios_event_id:
        existing_block = db.query(IOSEventBlock).filter(
            IOSEventBlock.user_id == current_user.id,
            IOSEventBlock.ios_event_id == event.ios_event_id,
        ).first()
        if not existing_block:
            db.add(IOSEventBlock(
                user_id=current_user.id,
                ios_event_id=event.ios_event_id,
                ios_calendar_id=event.ios_calendar_id,
                title=event.title,
            ))

    db.delete(event)
    db.commit()

    return {"message": "Event deleted successfully"}


# iOS Calendar Sync endpoints
@router.post("/ios-sync", response_model=IOSCalendarSyncResponse)
async def sync_ios_calendar_events(
    sync_request: IOSCalendarSyncRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Sync events from iOS calendar to Sara."""
    import os
    local_tz = ZoneInfo(os.environ.get("TIMEZONE", "America/New_York"))

    synced = 0
    errors = 0
    deleted = 0
    processed_keys = set()
    payload_event_ids = set()

    # Load the user's iOS event blocklist once — any events the user has removed
    # from Sara should be skipped (but still tracked in payload_event_ids so the
    # reconciliation step doesn't try to "delete" the already-absent rows).
    blocked_ios_event_ids = {
        row.ios_event_id
        for row in db.query(IOSEventBlock.ios_event_id).filter(
            IOSEventBlock.user_id == current_user.id
        ).all()
    }

    for event_data in sync_request.events:
        payload_event_ids.add(event_data.ios_event_id)
        if event_data.ios_event_id in blocked_ios_event_ids:
            continue
        try:
            # Parse UTC times and convert to local timezone for storage
            # (DB columns are naive DateTime, so we store local times)
            start_utc = datetime.fromisoformat(event_data.start_time.replace('Z', '+00:00'))
            end_utc = datetime.fromisoformat(event_data.end_time.replace('Z', '+00:00'))
            start_time = _to_naive_local(start_utc, local_tz)
            end_time = _to_naive_local(end_utc, local_tz)

            event_key = f"{event_data.ios_event_id}_{start_time.isoformat()}"

            if event_key in processed_keys:
                continue
            processed_keys.add(event_key)

            existing_event = db.query(CalendarEvent).filter(
                CalendarEvent.user_id == current_user.id,
                CalendarEvent.ios_event_id == event_data.ios_event_id,
                CalendarEvent.start_time == start_time
            ).first()

            attendees_list = [a.dict() for a in (event_data.attendees or [])]

            # Classify ownership once, at sync time, so every downstream consumer
            # (brief, day-replay, monitors, PKG, chat tool) gets it for free.
            try:
                from app.services.calendar_ownership import classify_event
                _own = classify_event(event_data.title, event_data.ios_calendar_name,
                                      source="ios_calendar")
                _owner, _owner_rel = _own.owner, _own.relation
            except Exception:
                _owner, _owner_rel = None, None

            if existing_event:
                existing_event.title = event_data.title
                existing_event.description = event_data.description or ""
                existing_event.end_time = end_time
                existing_event.location = event_data.location or ""
                existing_event.all_day = event_data.all_day
                existing_event.ios_calendar_id = event_data.ios_calendar_id
                existing_event.ios_calendar_name = event_data.ios_calendar_name
                existing_event.attendees = attendees_list
                existing_event.organizer = event_data.organizer
                existing_event.owner = _owner
                existing_event.owner_relation = _owner_rel
                existing_event.updated_at = naive_local_now()
                db.flush()
                event_for_linkage = existing_event
            else:
                new_event = CalendarEvent(
                    id=str(uuid.uuid4()),
                    user_id=current_user.id,
                    title=event_data.title,
                    description=event_data.description or "",
                    start_time=start_time,
                    end_time=end_time,
                    location=event_data.location or "",
                    all_day=event_data.all_day,
                    source="ios_calendar",
                    ios_event_id=event_data.ios_event_id,
                    ios_calendar_id=event_data.ios_calendar_id,
                    ios_calendar_name=event_data.ios_calendar_name,
                    attendees=attendees_list,
                    organizer=event_data.organizer,
                    owner=_owner,
                    owner_relation=_owner_rel,
                    read_only=True,
                    is_completed=False
                )
                db.add(new_event)
                db.flush()
                _supersede_email_duplicates(db, current_user.id, new_event)
                event_for_linkage = new_event

            if attendees_list:
                try:
                    from app.services.person_service_sync import link_attendees_to_people
                    link_attendees_to_people(db, current_user.id, attendees_list, event_for_linkage.start_time)
                except Exception as e:
                    logger.warning(f"Attendee person-linkage failed for event {event_data.ios_event_id}: {e}")

            synced += 1
        except Exception as e:
            logger.error(f"Error syncing iOS event {event_data.ios_event_id}: {e}")
            db.rollback()
            errors += 1

    # Reconcile deletions: any iOS-sourced events inside the sync window from
    # the synced calendars that are NOT in the payload were deleted on iOS.
    if sync_request.window_start and sync_request.window_end:
        try:
            window_start = _to_naive_local(
                datetime.fromisoformat(sync_request.window_start.replace('Z', '+00:00')),
                local_tz,
            )
            window_end = _to_naive_local(
                datetime.fromisoformat(sync_request.window_end.replace('Z', '+00:00')),
                local_tz,
            )

            stale_query = db.query(CalendarEvent).filter(
                CalendarEvent.user_id == current_user.id,
                CalendarEvent.source == "ios_calendar",
                CalendarEvent.start_time >= window_start,
                CalendarEvent.start_time <= window_end,
            )
            if sync_request.calendar_ids:
                stale_query = stale_query.filter(
                    CalendarEvent.ios_calendar_id.in_(sync_request.calendar_ids)
                )
            if payload_event_ids:
                stale_query = stale_query.filter(
                    ~CalendarEvent.ios_event_id.in_(payload_event_ids)
                )

            stale_events = stale_query.all()
            for stale in stale_events:
                db.delete(stale)
            deleted = len(stale_events)
        except Exception as e:
            logger.error(f"Error reconciling iOS calendar deletions: {e}")
            db.rollback()
            deleted = 0

    try:
        db.commit()
    except Exception as e:
        logger.error(f"Error committing iOS calendar sync: {e}")
        db.rollback()
        errors += synced
        synced = 0
        deleted = 0

    return IOSCalendarSyncResponse(synced=synced, errors=errors, deleted=deleted)


@router.delete("/ios-sync")
async def clear_ios_calendar_events(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove all iOS-synced calendar events."""
    deleted = db.query(CalendarEvent).filter(
        CalendarEvent.user_id == current_user.id,
        CalendarEvent.source == "ios_calendar"
    ).delete()

    db.commit()
    return {"message": f"Deleted {deleted} iOS calendar events"}
