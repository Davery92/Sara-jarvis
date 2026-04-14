from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone, date, timedelta
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.calendar_event import CalendarEvent
import uuid
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class EventCreate(BaseModel):
    title: str
    starts_at: datetime
    ends_at: datetime
    location: str = ""
    description: str = ""


class EventUpdate(BaseModel):
    title: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    location: Optional[str] = None
    description: Optional[str] = None


class EventResponse(BaseModel):
    id: str
    title: str
    starts_at: str
    ends_at: str
    location: str
    description: str
    created_at: str
    updated_at: str


class EventsListResponse(BaseModel):
    events: List[EventResponse]
    total: int
    page: int
    per_page: int


def _event_to_response(event: CalendarEvent) -> EventResponse:
    """Convert CalendarEvent to EventResponse (maps column names for backward compat)."""
    return EventResponse(
        id=str(event.id),
        title=event.title,
        starts_at=event.start_time.isoformat() if event.start_time else "",
        ends_at=event.end_time.isoformat() if event.end_time else "",
        location=event.location or "",
        description=event.description or "",
        created_at=event.created_at.isoformat() if event.created_at else "",
        updated_at=event.updated_at.isoformat() if event.updated_at else "",
    )


@router.get("/", response_model=EventsListResponse)
async def list_events(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List user's events with pagination and filtering"""
    try:
        query = db.query(CalendarEvent).filter(CalendarEvent.user_id == str(current_user.id))

        if start_date:
            start_datetime = datetime.combine(start_date, datetime.min.time())
            query = query.filter(CalendarEvent.start_time >= start_datetime)

        if end_date:
            end_datetime = datetime.combine(end_date, datetime.max.time())
            query = query.filter(CalendarEvent.start_time <= end_datetime)

        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    CalendarEvent.title.ilike(search_term),
                    CalendarEvent.description.ilike(search_term),
                    CalendarEvent.location.ilike(search_term)
                )
            )

        total = query.count()
        offset = (page - 1) * per_page
        events = query.order_by(CalendarEvent.start_time).offset(offset).limit(per_page).all()

        return EventsListResponse(
            events=[_event_to_response(e) for e in events],
            total=total,
            page=page,
            per_page=per_page
        )
    except Exception as e:
        logger.error(f"Failed to list events: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve events")


@router.post("/", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    event_data: EventCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new calendar event"""
    try:
        if event_data.starts_at >= event_data.ends_at:
            raise HTTPException(status_code=400, detail="Start time must be before end time")

        event = CalendarEvent(
            id=str(uuid.uuid4()),
            user_id=str(current_user.id),
            title=event_data.title,
            start_time=event_data.starts_at,
            end_time=event_data.ends_at,
            location=event_data.location,
            description=event_data.description,
            source="sara",
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return _event_to_response(event)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create event: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create event")


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific event"""
    event = db.query(CalendarEvent).filter(
        CalendarEvent.id == event_id,
        CalendarEvent.user_id == str(current_user.id)
    ).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return _event_to_response(event)


@router.patch("/{event_id}", response_model=EventResponse)
@router.put("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: str,
    event_update: EventUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an event"""
    try:
        event = db.query(CalendarEvent).filter(
            CalendarEvent.id == event_id,
            CalendarEvent.user_id == str(current_user.id)
        ).first()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")

        if event_update.title is not None:
            event.title = event_update.title
        if event_update.starts_at is not None:
            event.start_time = event_update.starts_at
        if event_update.ends_at is not None:
            event.end_time = event_update.ends_at
        if event_update.location is not None:
            event.location = event_update.location
        if event_update.description is not None:
            event.description = event_update.description

        if event.start_time >= event.end_time:
            raise HTTPException(status_code=400, detail="Start time must be before end time")

        db.commit()
        db.refresh(event)
        return _event_to_response(event)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update event: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update event")


@router.delete("/{event_id}")
async def delete_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an event"""
    try:
        event = db.query(CalendarEvent).filter(
            CalendarEvent.id == event_id,
            CalendarEvent.user_id == str(current_user.id)
        ).first()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        db.delete(event)
        db.commit()
        return {"message": "Event deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete event: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete event")


@router.get("/today/", response_model=List[EventResponse])
async def get_today_events(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get today's events"""
    try:
        today = date.today()
        start_of_day = datetime.combine(today, datetime.min.time())
        end_of_day = datetime.combine(today, datetime.max.time())

        events = db.query(CalendarEvent).filter(
            CalendarEvent.user_id == str(current_user.id),
            CalendarEvent.start_time >= start_of_day,
            CalendarEvent.start_time <= end_of_day,
        ).order_by(CalendarEvent.start_time).all()

        return [_event_to_response(e) for e in events]
    except Exception as e:
        logger.error(f"Failed to get today's events: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve today's events")


@router.get("/upcoming/", response_model=List[EventResponse])
async def get_upcoming_events(
    days: int = Query(7, ge=1, le=30),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get upcoming events within the specified number of days"""
    try:
        now = datetime.now(timezone.utc)
        future = now + timedelta(days=days)

        events = db.query(CalendarEvent).filter(
            CalendarEvent.user_id == str(current_user.id),
            CalendarEvent.start_time >= now,
            CalendarEvent.start_time <= future,
        ).order_by(CalendarEvent.start_time).all()

        return [_event_to_response(e) for e in events]
    except Exception as e:
        logger.error(f"Failed to get upcoming events: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve upcoming events")


@router.get("/conflicts/{event_id}", response_model=List[EventResponse])
async def get_conflicting_events(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Find events that conflict with the given event's time"""
    try:
        source = db.query(CalendarEvent).filter(
            CalendarEvent.id == event_id,
            CalendarEvent.user_id == str(current_user.id)
        ).first()
        if not source:
            raise HTTPException(status_code=404, detail="Event not found")

        conflicts = db.query(CalendarEvent).filter(
            CalendarEvent.user_id == str(current_user.id),
            CalendarEvent.id != event_id,
            or_(
                and_(CalendarEvent.start_time >= source.start_time, CalendarEvent.start_time < source.end_time),
                and_(CalendarEvent.end_time > source.start_time, CalendarEvent.end_time <= source.end_time),
                and_(CalendarEvent.start_time <= source.start_time, CalendarEvent.end_time >= source.end_time),
            )
        ).order_by(CalendarEvent.start_time).all()

        return [_event_to_response(e) for e in conflicts]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to find conflicting events: {e}")
        raise HTTPException(status_code=500, detail="Failed to find conflicting events")
