from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.routes.reminders import (
    list_timers, create_timer, get_timer, update_timer, delete_timer,
    TimerCreate, TimerResponse, TimerUpdate, TimersListResponse
)

router = APIRouter()

# Re-export timer endpoints from reminders module with correct signatures
@router.get("/", response_model=TimersListResponse)
async def get_timers(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all timers for current user"""
    return await list_timers(page, per_page, status, current_user, db)

@router.post("/", response_model=TimerResponse)
async def create_new_timer(
    timer_data: TimerCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new timer"""
    return await create_timer(timer_data, current_user, db)

@router.get("/{timer_id}", response_model=TimerResponse)  
async def get_timer_by_id(
    timer_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific timer"""
    return await get_timer(timer_id, current_user, db)

@router.put("/{timer_id}", response_model=TimerResponse)
async def update_timer_by_id(
    timer_id: str,
    timer_update: TimerUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a timer"""
    return await update_timer(timer_id, timer_update, current_user, db)

@router.delete("/{timer_id}")
async def delete_timer_by_id(
    timer_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a timer"""
    return await delete_timer(timer_id, current_user, db)