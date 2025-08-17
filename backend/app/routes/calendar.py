from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_
from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone, date
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.calendar import Event
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
        query = db.query(Event).filter(Event.user_id == current_user.id)
        
        # Apply date range filter
        if start_date:
            start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            query = query.filter(Event.starts_at >= start_datetime)
            
        if end_date:
            end_datetime = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc)
            query = query.filter(Event.starts_at <= end_datetime)
        
        # Apply search filter
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    Event.title.ilike(search_term),
                    Event.description.ilike(search_term),
                    Event.location.ilike(search_term)
                )
            )
        
        # Get total count
        total = query.count()
        
        # Apply pagination and ordering
        offset = (page - 1) * per_page
        events = query.order_by(Event.starts_at).offset(offset).limit(per_page).all()
        
        event_responses = [
            EventResponse(
                id=str(event.id),
                title=event.title,
                starts_at=event.starts_at.isoformat(),
                ends_at=event.ends_at.isoformat(),
                location=event.location,
                description=event.description,
                created_at=event.created_at.isoformat(),
                updated_at=event.updated_at.isoformat()
            )
            for event in events
        ]
        
        return EventsListResponse(
            events=event_responses,
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
        # Ensure datetime fields are timezone-aware
        if event_data.starts_at.tzinfo is None:
            event_data.starts_at = event_data.starts_at.replace(tzinfo=timezone.utc)
        if event_data.ends_at.tzinfo is None:
            event_data.ends_at = event_data.ends_at.replace(tzinfo=timezone.utc)
        
        # Validate that start time is before end time
        if event_data.starts_at >= event_data.ends_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Start time must be before end time"
            )
        
        event = Event(
            user_id=current_user.id,
            title=event_data.title,
            starts_at=event_data.starts_at,
            ends_at=event_data.ends_at,
            location=event_data.location,
            description=event_data.description
        )
        
        db.add(event)
        db.commit()
        db.refresh(event)
        
        return EventResponse(
            id=str(event.id),
            title=event.title,
            starts_at=event.starts_at.isoformat(),
            ends_at=event.ends_at.isoformat(),
            location=event.location,
            description=event.description,
            created_at=event.created_at.isoformat(),
            updated_at=event.updated_at.isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create event: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create event")


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific event"""
    
    event = db.query(Event).filter(
        Event.id == event_id,
        Event.user_id == current_user.id
    ).first()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    
    return EventResponse(
        id=str(event.id),
        title=event.title,
        starts_at=event.starts_at.isoformat(),
        ends_at=event.ends_at.isoformat(),
        location=event.location,
        description=event.description,
        created_at=event.created_at.isoformat(),
        updated_at=event.updated_at.isoformat()
    )


@router.patch("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: UUID,
    event_update: EventUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an event"""
    
    try:
        event = db.query(Event).filter(
            Event.id == event_id,
            Event.user_id == current_user.id
        ).first()
        
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Event not found"
            )
        
        # Update fields
        if event_update.title is not None:
            event.title = event_update.title
            
        if event_update.starts_at is not None:
            # Ensure timezone-aware
            if event_update.starts_at.tzinfo is None:
                event_update.starts_at = event_update.starts_at.replace(tzinfo=timezone.utc)
            event.starts_at = event_update.starts_at
            
        if event_update.ends_at is not None:
            # Ensure timezone-aware
            if event_update.ends_at.tzinfo is None:
                event_update.ends_at = event_update.ends_at.replace(tzinfo=timezone.utc)
            event.ends_at = event_update.ends_at
            
        if event_update.location is not None:
            event.location = event_update.location
            
        if event_update.description is not None:
            event.description = event_update.description
        
        # Validate that start time is before end time
        if event.starts_at >= event.ends_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Start time must be before end time"
            )
        
        db.commit()
        db.refresh(event)
        
        return EventResponse(
            id=str(event.id),
            title=event.title,
            starts_at=event.starts_at.isoformat(),
            ends_at=event.ends_at.isoformat(),
            location=event.location,
            description=event.description,
            created_at=event.created_at.isoformat(),
            updated_at=event.updated_at.isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update event: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update event")


@router.delete("/{event_id}")
async def delete_event(
    event_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an event"""
    
    try:
        event = db.query(Event).filter(
            Event.id == event_id,
            Event.user_id == current_user.id
        ).first()
        
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Event not found"
            )
        
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
        # Get today's date in user's timezone (assuming UTC for now)
        today = date.today()
        start_of_day = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_of_day = datetime.combine(today, datetime.max.time()).replace(tzinfo=timezone.utc)
        
        events = db.query(Event).filter(
            Event.user_id == current_user.id,
            and_(
                Event.starts_at >= start_of_day,
                Event.starts_at <= end_of_day
            )
        ).order_by(Event.starts_at).all()
        
        return [
            EventResponse(
                id=str(event.id),
                title=event.title,
                starts_at=event.starts_at.isoformat(),
                ends_at=event.ends_at.isoformat(),
                location=event.location,
                description=event.description,
                created_at=event.created_at.isoformat(),
                updated_at=event.updated_at.isoformat()
            )
            for event in events
        ]
        
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
        from datetime import timedelta
        
        now = datetime.now(timezone.utc)
        future_threshold = now + timedelta(days=days)
        
        events = db.query(Event).filter(
            Event.user_id == current_user.id,
            and_(
                Event.starts_at >= now,
                Event.starts_at <= future_threshold
            )
        ).order_by(Event.starts_at).all()
        
        return [
            EventResponse(
                id=str(event.id),
                title=event.title,
                starts_at=event.starts_at.isoformat(),
                ends_at=event.ends_at.isoformat(),
                location=event.location,
                description=event.description,
                created_at=event.created_at.isoformat(),
                updated_at=event.updated_at.isoformat()
            )
            for event in events
        ]
        
    except Exception as e:
        logger.error(f"Failed to get upcoming events: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve upcoming events")


@router.get("/conflicts/{event_id}", response_model=List[EventResponse])
async def get_conflicting_events(
    event_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Find events that conflict with the given event's time"""
    
    try:
        # Get the source event
        source_event = db.query(Event).filter(
            Event.id == event_id,
            Event.user_id == current_user.id
        ).first()
        
        if not source_event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Event not found"
            )
        
        # Find overlapping events
        conflicts = db.query(Event).filter(
            Event.user_id == current_user.id,
            Event.id != event_id,
            or_(
                # Event starts during our event
                and_(
                    Event.starts_at >= source_event.starts_at,
                    Event.starts_at < source_event.ends_at
                ),
                # Event ends during our event
                and_(
                    Event.ends_at > source_event.starts_at,
                    Event.ends_at <= source_event.ends_at
                ),
                # Event completely contains our event
                and_(
                    Event.starts_at <= source_event.starts_at,
                    Event.ends_at >= source_event.ends_at
                )
            )
        ).order_by(Event.starts_at).all()
        
        return [
            EventResponse(
                id=str(event.id),
                title=event.title,
                starts_at=event.starts_at.isoformat(),
                ends_at=event.ends_at.isoformat(),
                location=event.location,
                description=event.description,
                created_at=event.created_at.isoformat(),
                updated_at=event.updated_at.isoformat()
            )
            for event in conflicts
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to find conflicting events: {e}")
        raise HTTPException(status_code=500, detail="Failed to find conflicting events")