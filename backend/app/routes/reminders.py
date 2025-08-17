from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_
from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.reminder import Reminder, Timer
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class ReminderCreate(BaseModel):
    text: str
    due_at: datetime


class ReminderUpdate(BaseModel):
    text: Optional[str] = None
    due_at: Optional[datetime] = None
    status: Optional[str] = None


class ReminderResponse(BaseModel):
    id: str
    text: str
    due_at: str
    status: str
    created_at: str


class TimerCreate(BaseModel):
    label: Optional[str] = None
    ends_at: datetime


class TimerUpdate(BaseModel):
    label: Optional[str] = None
    status: Optional[str] = None


class TimerResponse(BaseModel):
    id: str
    label: Optional[str]
    ends_at: str
    status: str
    created_at: str


class RemindersListResponse(BaseModel):
    reminders: List[ReminderResponse]
    total: int
    page: int
    per_page: int


class TimersListResponse(BaseModel):
    timers: List[TimerResponse]
    total: int
    page: int
    per_page: int


# Reminder endpoints
@router.get("/", response_model=RemindersListResponse)
async def list_reminders(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    upcoming: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List user's reminders with pagination and filtering"""
    
    try:
        query = db.query(Reminder).filter(Reminder.user_id == current_user.id)
        
        # Apply status filter
        if status:
            query = query.filter(Reminder.status == status)
        
        # Apply upcoming filter (due within next 7 days)
        if upcoming:
            from datetime import timedelta
            upcoming_threshold = datetime.now(timezone.utc) + timedelta(days=7)
            query = query.filter(
                and_(
                    Reminder.due_at <= upcoming_threshold,
                    Reminder.status == "scheduled"
                )
            )
        
        # Get total count
        total = query.count()
        
        # Apply pagination and ordering
        offset = (page - 1) * per_page
        reminders = query.order_by(Reminder.due_at).offset(offset).limit(per_page).all()
        
        reminder_responses = [
            ReminderResponse(
                id=str(reminder.id),
                text=reminder.text,
                due_at=reminder.due_at.isoformat(),
                status=reminder.status,
                created_at=reminder.created_at.isoformat()
            )
            for reminder in reminders
        ]
        
        return RemindersListResponse(
            reminders=reminder_responses,
            total=total,
            page=page,
            per_page=per_page
        )
        
    except Exception as e:
        logger.error(f"Failed to list reminders: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve reminders")


@router.post("/", response_model=ReminderResponse, status_code=status.HTTP_201_CREATED)
async def create_reminder(
    reminder_data: ReminderCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new reminder"""
    
    try:
        # Ensure due_at is timezone-aware
        if reminder_data.due_at.tzinfo is None:
            reminder_data.due_at = reminder_data.due_at.replace(tzinfo=timezone.utc)
        
        reminder = Reminder(
            user_id=current_user.id,
            text=reminder_data.text,
            due_at=reminder_data.due_at,
            status="scheduled"
        )
        
        db.add(reminder)
        db.commit()
        db.refresh(reminder)
        
        return ReminderResponse(
            id=str(reminder.id),
            text=reminder.text,
            due_at=reminder.due_at.isoformat(),
            status=reminder.status,
            created_at=reminder.created_at.isoformat()
        )
        
    except Exception as e:
        logger.error(f"Failed to create reminder: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create reminder")


@router.get("/{reminder_id}", response_model=ReminderResponse)
async def get_reminder(
    reminder_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific reminder"""
    
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id,
        Reminder.user_id == current_user.id
    ).first()
    
    if not reminder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reminder not found"
        )
    
    return ReminderResponse(
        id=str(reminder.id),
        text=reminder.text,
        due_at=reminder.due_at.isoformat(),
        status=reminder.status,
        created_at=reminder.created_at.isoformat()
    )


@router.patch("/{reminder_id}", response_model=ReminderResponse)
async def update_reminder(
    reminder_id: UUID,
    reminder_update: ReminderUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a reminder"""
    
    try:
        reminder = db.query(Reminder).filter(
            Reminder.id == reminder_id,
            Reminder.user_id == current_user.id
        ).first()
        
        if not reminder:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reminder not found"
            )
        
        # Update fields
        if reminder_update.text is not None:
            reminder.text = reminder_update.text
            
        if reminder_update.due_at is not None:
            # Ensure timezone-aware
            if reminder_update.due_at.tzinfo is None:
                reminder_update.due_at = reminder_update.due_at.replace(tzinfo=timezone.utc)
            reminder.due_at = reminder_update.due_at
            
        if reminder_update.status is not None:
            if reminder_update.status not in ["scheduled", "completed", "cancelled"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid status. Must be 'scheduled', 'completed', or 'cancelled'"
                )
            reminder.status = reminder_update.status
        
        db.commit()
        db.refresh(reminder)
        
        return ReminderResponse(
            id=str(reminder.id),
            text=reminder.text,
            due_at=reminder.due_at.isoformat(),
            status=reminder.status,
            created_at=reminder.created_at.isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update reminder: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update reminder")


@router.delete("/{reminder_id}")
async def delete_reminder(
    reminder_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a reminder"""
    
    try:
        reminder = db.query(Reminder).filter(
            Reminder.id == reminder_id,
            Reminder.user_id == current_user.id
        ).first()
        
        if not reminder:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reminder not found"
            )
        
        db.delete(reminder)
        db.commit()
        
        return {"message": "Reminder deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete reminder: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete reminder")


# Timer endpoints
@router.get("/timers/", response_model=TimersListResponse)
async def list_timers(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List user's timers with pagination and filtering"""
    
    try:
        query = db.query(Timer).filter(Timer.user_id == current_user.id)
        
        # Apply status filter
        if status:
            query = query.filter(Timer.status == status)
        
        # Get total count
        total = query.count()
        
        # Apply pagination and ordering
        offset = (page - 1) * per_page
        timers = query.order_by(desc(Timer.created_at)).offset(offset).limit(per_page).all()
        
        timer_responses = [
            TimerResponse(
                id=str(timer.id),
                label=timer.label,
                ends_at=timer.ends_at.isoformat(),
                status=timer.status,
                created_at=timer.created_at.isoformat()
            )
            for timer in timers
        ]
        
        return TimersListResponse(
            timers=timer_responses,
            total=total,
            page=page,
            per_page=per_page
        )
        
    except Exception as e:
        logger.error(f"Failed to list timers: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve timers")


@router.post("/timers/", response_model=TimerResponse, status_code=status.HTTP_201_CREATED)
async def create_timer(
    timer_data: TimerCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new timer"""
    
    try:
        # Ensure ends_at is timezone-aware
        if timer_data.ends_at.tzinfo is None:
            timer_data.ends_at = timer_data.ends_at.replace(tzinfo=timezone.utc)
        
        timer = Timer(
            user_id=current_user.id,
            label=timer_data.label,
            ends_at=timer_data.ends_at,
            status="running"
        )
        
        db.add(timer)
        db.commit()
        db.refresh(timer)
        
        return TimerResponse(
            id=str(timer.id),
            label=timer.label,
            ends_at=timer.ends_at.isoformat(),
            status=timer.status,
            created_at=timer.created_at.isoformat()
        )
        
    except Exception as e:
        logger.error(f"Failed to create timer: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create timer")


@router.get("/timers/{timer_id}", response_model=TimerResponse)
async def get_timer(
    timer_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific timer"""
    
    timer = db.query(Timer).filter(
        Timer.id == timer_id,
        Timer.user_id == current_user.id
    ).first()
    
    if not timer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Timer not found"
        )
    
    return TimerResponse(
        id=str(timer.id),
        label=timer.label,
        ends_at=timer.ends_at.isoformat(),
        status=timer.status,
        created_at=timer.created_at.isoformat()
    )


@router.patch("/timers/{timer_id}", response_model=TimerResponse)
async def update_timer(
    timer_id: UUID,
    timer_update: TimerUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a timer"""
    
    try:
        timer = db.query(Timer).filter(
            Timer.id == timer_id,
            Timer.user_id == current_user.id
        ).first()
        
        if not timer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Timer not found"
            )
        
        # Update fields
        if timer_update.label is not None:
            timer.label = timer_update.label
            
        if timer_update.status is not None:
            if timer_update.status not in ["running", "completed", "cancelled"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid status. Must be 'running', 'completed', or 'cancelled'"
                )
            timer.status = timer_update.status
        
        db.commit()
        db.refresh(timer)
        
        return TimerResponse(
            id=str(timer.id),
            label=timer.label,
            ends_at=timer.ends_at.isoformat(),
            status=timer.status,
            created_at=timer.created_at.isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update timer: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update timer")


@router.delete("/timers/{timer_id}")
async def delete_timer(
    timer_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a timer"""
    
    try:
        timer = db.query(Timer).filter(
            Timer.id == timer_id,
            Timer.user_id == current_user.id
        ).first()
        
        if not timer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Timer not found"
            )
        
        db.delete(timer)
        db.commit()
        
        return {"message": "Timer deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete timer: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete timer")