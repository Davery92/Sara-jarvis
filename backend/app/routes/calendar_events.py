"""Calendar events routes."""
import uuid
import logging
from datetime import datetime
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
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["Calendar"])


def _to_naive_local(dt: datetime, tz: ZoneInfo) -> datetime:
    """Convert to naive local time. If already naive, treat as local (no conversion)."""
    if dt.tzinfo is not None:
        return dt.astimezone(tz).replace(tzinfo=None)
    return dt


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

    event.updated_at = datetime.now()
    db.commit()
    db.refresh(event)

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

    for event_data in sync_request.events:
        payload_event_ids.add(event_data.ios_event_id)
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

            if existing_event:
                existing_event.title = event_data.title
                existing_event.description = event_data.description or ""
                existing_event.end_time = end_time
                existing_event.location = event_data.location or ""
                existing_event.all_day = event_data.all_day
                existing_event.ios_calendar_id = event_data.ios_calendar_id
                existing_event.ios_calendar_name = event_data.ios_calendar_name
                existing_event.updated_at = datetime.now()
                db.flush()
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
                    read_only=True,
                    is_completed=False
                )
                db.add(new_event)
                db.flush()

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
