"""Reminders and timers routes."""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.timezone import now as local_now, to_local
from app.db.session import get_db
from app.models.user import User
from app.models.reminder import Reminder, Timer
from app.schemas.reminders import (
    ReminderCreate, ReminderUpdate, ReminderResponse,
    TimerCreate, TimerResponse
)
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Reminders"])


@router.get("/reminders", response_model=List[ReminderResponse])
async def list_reminders(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all active reminders for the current user."""
    reminders = db.query(Reminder).filter(
        Reminder.user_id == current_user.id,
        Reminder.is_completed == False
    ).order_by(Reminder.reminder_time).limit(20).all()

    return [
        ReminderResponse(
            id=reminder.id,
            title=reminder.title,
            description=reminder.description,
            reminder_time=reminder.reminder_time.isoformat(),
            is_completed=reminder.is_completed == "true" if isinstance(reminder.is_completed, str) else bool(reminder.is_completed),
            created_at=reminder.created_at.isoformat(),
            updated_at=reminder.updated_at.isoformat()
        )
        for reminder in reminders
    ]


@router.post("/reminders", response_model=ReminderResponse)
async def create_reminder(
    reminder_data: ReminderCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new reminder."""
    reminder_dt = datetime.fromisoformat(reminder_data.reminder_time.replace('Z', '+00:00'))

    reminder = Reminder(
        user_id=current_user.id,
        title=reminder_data.title,
        description=reminder_data.description,
        reminder_time=reminder_dt
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)

    return ReminderResponse(
        id=reminder.id,
        title=reminder.title,
        description=reminder.description,
        reminder_time=reminder.reminder_time.isoformat(),
        is_completed=reminder.is_completed == "true" if isinstance(reminder.is_completed, str) else bool(reminder.is_completed),
        created_at=reminder.created_at.isoformat(),
        updated_at=reminder.updated_at.isoformat()
    )


@router.put("/reminders/{reminder_id}", response_model=ReminderResponse)
async def update_reminder(
    reminder_id: str,
    reminder_data: ReminderUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a reminder."""
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id,
        Reminder.user_id == current_user.id
    ).first()

    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    if reminder_data.title is not None:
        reminder.title = reminder_data.title
    if reminder_data.description is not None:
        reminder.description = reminder_data.description
    if reminder_data.reminder_time is not None:
        reminder.reminder_time = datetime.fromisoformat(reminder_data.reminder_time.replace('Z', '+00:00'))
    if reminder_data.is_completed is not None:
        reminder.is_completed = reminder_data.is_completed

    reminder.updated_at = local_now()
    db.commit()
    db.refresh(reminder)

    return ReminderResponse(
        id=reminder.id,
        title=reminder.title,
        description=reminder.description,
        reminder_time=reminder.reminder_time.isoformat(),
        is_completed=reminder.is_completed == "true" if isinstance(reminder.is_completed, str) else bool(reminder.is_completed),
        created_at=reminder.created_at.isoformat(),
        updated_at=reminder.updated_at.isoformat()
    )


@router.delete("/reminders/{reminder_id}")
async def delete_reminder(
    reminder_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a reminder."""
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id,
        Reminder.user_id == current_user.id
    ).first()

    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    db.delete(reminder)
    db.commit()

    return {"message": "Reminder deleted successfully"}


@router.patch("/reminders/{reminder_id}/complete")
async def complete_reminder(
    reminder_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark a reminder as completed."""
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id,
        Reminder.user_id == current_user.id
    ).first()

    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    reminder.is_completed = True
    reminder.updated_at = local_now()
    db.commit()

    return {"message": f"Marked reminder '{reminder.title}' as completed"}


@router.post("/reminders/{reminder_id}/notify")
async def send_reminder_notification(
    reminder_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Send NTFY notification for a due reminder."""
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id,
        Reminder.user_id == current_user.id
    ).first()

    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    try:
        # Import ntfy_service from main_simple where it's instantiated
        from app.main_simple import ntfy_service
        reminder_time = reminder.reminder_time.strftime("%I:%M %p")
        success = await ntfy_service.send_reminder_notification(
            reminder.title,
            reminder_time,
            reminder_id,
            reminder.description,
            current_user.id
        )

        if success:
            return {"message": f"Notification sent for reminder '{reminder.title}'"}
        else:
            return {"message": f"Failed to send notification for reminder '{reminder.title}'"}
    except ImportError:
        logger.warning("NTFY service not available")
        return {"message": f"Notification service not available for reminder '{reminder.title}'"}


# Timer endpoints

@router.get("/timers", response_model=List[TimerResponse])
async def list_timers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all active timers for the current user."""
    timers = db.query(Timer).filter(
        Timer.user_id == current_user.id,
        Timer.is_active == True
    ).order_by(Timer.created_at.desc()).limit(20).all()

    results = [
        TimerResponse(
            id=timer.id,
            title=timer.title,
            duration_minutes=timer.duration_minutes,
            start_time=to_local(timer.start_time).isoformat(),
            end_time=to_local(timer.end_time).isoformat(),
            is_active=timer.is_active,
            is_completed=timer.is_completed == "true",
            created_at=to_local(timer.created_at).isoformat()
        )
        for timer in timers
    ]

    for timer_response in results:
        logger.info(f"API returning timer: {timer_response.title} - Start: {timer_response.start_time}, End: {timer_response.end_time}, Duration: {timer_response.duration_minutes}m")

    return results


@router.post("/timers", response_model=TimerResponse)
async def start_timer(
    timer_data: TimerCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start a new timer."""
    from datetime import timedelta

    logger.info(f"Creating timer: title={timer_data.title}, duration_minutes={timer_data.duration_minutes}, duration_seconds={timer_data.duration_seconds}")
    start_time = local_now()

    # Support both duration_seconds and duration_minutes for backward compatibility
    if timer_data.duration_seconds is not None:
        duration_minutes = timer_data.duration_seconds / 60  # Store as fractional minutes
        end_time = start_time + timedelta(seconds=timer_data.duration_seconds)
    elif timer_data.duration_minutes is not None:
        duration_minutes = timer_data.duration_minutes
        end_time = start_time + timedelta(minutes=timer_data.duration_minutes)
    else:
        raise HTTPException(status_code=400, detail="Must provide either duration_minutes or duration_seconds")

    timer = Timer(
        user_id=current_user.id,
        title=timer_data.title,
        duration_minutes=int(duration_minutes),  # Store as int minutes (legacy field)
        start_time=start_time,
        end_time=end_time,
        is_active=True
    )
    db.add(timer)
    db.commit()
    db.refresh(timer)

    logger.info(f"Timer created: {timer.id} - {timer.title}, Duration: {timer.duration_minutes}m, Start: {timer.start_time}, End: {timer.end_time}")

    return TimerResponse(
        id=timer.id,
        title=timer.title,
        duration_minutes=timer.duration_minutes,
        start_time=to_local(timer.start_time).isoformat(),
        end_time=to_local(timer.end_time).isoformat(),
        is_active=timer.is_active,
        is_completed=timer.is_completed == "true",
        created_at=to_local(timer.created_at).isoformat()
    )


@router.delete("/timers/{timer_id}")
async def cancel_timer(
    timer_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel a timer."""
    timer = db.query(Timer).filter(
        Timer.id == timer_id,
        Timer.user_id == current_user.id
    ).first()

    if not timer:
        raise HTTPException(status_code=404, detail="Timer not found")

    timer.is_active = False
    db.commit()

    return {"message": f"Timer '{timer.title}' cancelled"}


@router.patch("/timers/{timer_id}/stop")
async def stop_timer(
    timer_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Stop an active timer."""
    timer = db.query(Timer).filter(
        Timer.id == timer_id,
        Timer.user_id == current_user.id,
        Timer.is_active == True
    ).first()

    if not timer:
        raise HTTPException(status_code=404, detail="Active timer not found")

    timer.is_active = False
    timer.is_completed = True
    db.commit()

    # Send notification for stopped timer
    try:
        from app.main_simple import ntfy_service
        now = local_now()
        timer_end_time = to_local(timer.end_time)

        if timer_end_time > now:
            # Timer was stopped early, send immediate notification
            duration_str = f"{timer.duration_minutes}min"
            await ntfy_service.send_timer_notification(timer.title, duration_str, timer_id, current_user.id)
    except ImportError:
        logger.warning("NTFY service not available for timer notification")

    return {"message": f"Stopped timer '{timer.title}'"}
