"""
Daily Brief API Routes - RESTful API for daily briefings
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from datetime import datetime, date

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.daily_brief import DailyBrief
from app.services.daily_brief_service import daily_brief_service

router = APIRouter(prefix="/brief", tags=["daily-brief"])


# Pydantic Models
class BriefSectionItem(BaseModel):
    id: Optional[str] = None
    title: str
    subtitle: Optional[str] = None
    type: str  # reminder, calendar_event, insight, suggestion, etc.
    source_id: Optional[int] = None
    action: Optional[str] = None
    # Additional fields can be added as needed
    
    class Config:
        extra = "allow"  # Allow additional fields


class BriefSection(BaseModel):
    id: str
    title: str
    items: list[BriefSectionItem]


class DailyBriefResponse(BaseModel):
    id: int
    brief_date: date
    sections: list[BriefSection]
    generated_at: datetime
    generation_duration_ms: int
    calendar_events_count: int
    reminders_count: int
    insights_count: int
    dream_highlights_count: int
    viewed_at: Optional[datetime]
    pinned_items: list[str]
    
    # Computed properties
    total_items: int
    is_today: bool
    
    class Config:
        from_attributes = True


class PinItemRequest(BaseModel):
    item_id: str


# Routes
@router.get("/daily", response_model=DailyBriefResponse)
async def get_daily_brief(
    t: Optional[str] = Query(None, description="Date in YYYY-MM-DD format (defaults to today)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get the daily brief for a specific date
    
    The brief is cached for performance and includes:
    - Top priorities from high-priority reminders
    - Calendar overview with first event and conflicts
    - Carry-over tasks from previous day
    - Dream highlights (from overnight processing)
    - Suggested focus areas
    """
    
    # Parse target date
    if t:
        try:
            target_date = date.fromisoformat(t)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    else:
        target_date = date.today()
    
    # Generate brief
    brief = await daily_brief_service.generate_brief(
        db=db,
        user_id=current_user.id,
        target_date=target_date
    )
    
    # Mark as viewed if it's today and hasn't been viewed yet
    if target_date == date.today() and not brief.viewed_at:
        daily_brief_service.mark_viewed(db=db, brief_id=brief.id, user_id=current_user.id)
    
    # Convert to response format
    return DailyBriefResponse(
        id=brief.id,
        brief_date=brief.brief_date,
        sections=[
            BriefSection(
                id=section["id"],
                title=section["title"],
                items=[BriefSectionItem(**item) for item in section["items"]]
            )
            for section in brief.sections
        ],
        generated_at=brief.generated_at,
        generation_duration_ms=brief.generation_duration_ms or 0,
        calendar_events_count=brief.calendar_events_count or 0,
        reminders_count=brief.reminders_count or 0,
        insights_count=brief.insights_count or 0,
        dream_highlights_count=brief.dream_highlights_count or 0,
        viewed_at=brief.viewed_at,
        pinned_items=brief.pinned_items or [],
        total_items=brief.total_items,
        is_today=brief.is_today
    )


@router.post("/daily/{brief_id}/pin")
async def pin_brief_item(
    brief_id: int,
    request: PinItemRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Pin a brief item as a reminder
    
    This creates a new reminder from a brief item that the user wants to track.
    """
    
    success = daily_brief_service.pin_item(
        db=db,
        brief_id=brief_id,
        user_id=current_user.id,
        item_id=request.item_id
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Daily brief not found")
    
    # TODO: In a more advanced implementation, this would actually create
    # a reminder from the pinned item's details
    
    return {"status": "pinned", "item_id": request.item_id}


@router.get("/history")
async def get_brief_history(
    limit: int = Query(7, ge=1, le=30, description="Number of recent briefs"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get history of recent daily briefs
    
    Returns metadata about recent briefs without the full content,
    useful for showing a history/archive view.
    """
    
    briefs = db.query(DailyBrief).filter(
        DailyBrief.user_id == current_user.id
    ).order_by(DailyBrief.brief_date.desc()).limit(limit).all()
    
    brief_summaries = []
    for brief in briefs:
        brief_summaries.append({
            "id": brief.id,
            "brief_date": brief.brief_date,
            "sections_count": len(brief.sections or []),
            "total_items": brief.total_items,
            "generated_at": brief.generated_at,
            "viewed_at": brief.viewed_at,
            "calendar_events_count": brief.calendar_events_count or 0,
            "reminders_count": brief.reminders_count or 0,
            "insights_count": brief.insights_count or 0
        })
    
    return {
        "briefs": brief_summaries,
        "total": len(brief_summaries)
    }


@router.post("/daily/{brief_id}/regenerate")
async def regenerate_brief(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Force regeneration of a daily brief
    
    This bypasses the cache and regenerates the brief with current data.
    Useful when user wants to refresh the brief after making changes.
    """
    
    # Get the existing brief to find the date
    existing_brief = db.query(DailyBrief).filter(
        DailyBrief.id == brief_id,
        DailyBrief.user_id == current_user.id
    ).first()
    
    if not existing_brief:
        raise HTTPException(status_code=404, detail="Daily brief not found")
    
    # Delete the existing brief to force regeneration
    db.delete(existing_brief)
    db.commit()
    
    # Generate new brief
    new_brief = await daily_brief_service.generate_brief(
        db=db,
        user_id=current_user.id,
        target_date=existing_brief.brief_date
    )
    
    return {
        "status": "regenerated",
        "brief_id": new_brief.id,
        "generated_at": new_brief.generated_at
    }


@router.get("/stats")
async def get_brief_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get statistics about daily briefs"""
    
    from sqlalchemy import func
    from datetime import timedelta
    
    # Get recent briefs for statistics
    recent_date = date.today() - timedelta(days=30)
    recent_briefs = db.query(DailyBrief).filter(
        DailyBrief.user_id == current_user.id,
        DailyBrief.brief_date >= recent_date
    ).all()
    
    if not recent_briefs:
        return {
            "total_briefs": 0,
            "avg_generation_time_ms": 0,
            "avg_items_per_brief": 0,
            "most_active_source": None
        }
    
    # Calculate statistics
    total_briefs = len(recent_briefs)
    
    generation_times = [b.generation_duration_ms for b in recent_briefs if b.generation_duration_ms]
    avg_generation_time = sum(generation_times) / len(generation_times) if generation_times else 0
    
    total_items = sum(b.total_items for b in recent_briefs)
    avg_items = total_items / total_briefs if total_briefs > 0 else 0
    
    # Find most active content source
    calendar_total = sum(b.calendar_events_count or 0 for b in recent_briefs)
    reminders_total = sum(b.reminders_count or 0 for b in recent_briefs)
    insights_total = sum(b.insights_count or 0 for b in recent_briefs)
    
    source_counts = {
        "calendar": calendar_total,
        "reminders": reminders_total,
        "insights": insights_total
    }
    most_active_source = max(source_counts, key=source_counts.get) if any(source_counts.values()) else None
    
    return {
        "total_briefs": total_briefs,
        "avg_generation_time_ms": round(avg_generation_time),
        "avg_items_per_brief": round(avg_items, 1),
        "most_active_source": most_active_source,
        "source_breakdown": source_counts
    }