"""
Jarvis Inbox API Routes - RESTful API for inbox management
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from datetime import datetime

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.jarvis_inbox import JarvisInbox, InboxKind, InboxStatus
from app.services.jarvis_inbox_service import inbox_service

router = APIRouter(prefix="/inbox", tags=["jarvis-inbox"])


# Pydantic Models
class InboxItemCreate(BaseModel):
    kind: InboxKind
    title: str = Field(..., max_length=255)
    body: Optional[str] = None
    source: Optional[str] = None
    payload: dict = Field(default_factory=dict)
    priority: int = Field(default=5, ge=1, le=10)
    dedupe_key: Optional[str] = None
    immediate: bool = Field(default=False, description="Bypass batching and quiet hours")


class InboxItemResponse(BaseModel):
    id: int
    kind: InboxKind
    title: str
    body: Optional[str]
    source: Optional[str]
    payload: dict
    priority: int
    status: InboxStatus
    dedupe_key: Optional[str]
    batch_id: Optional[str]
    created_at: datetime
    read_at: Optional[datetime]
    archived_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class InboxListResponse(BaseModel):
    items: List[InboxItemResponse]
    total: int
    unread_count: int


class InboxStatsResponse(BaseModel):
    total_items: int
    unread_count: int
    today_count: int
    last_batch_time: Optional[datetime]
    quiet_hours_active: bool


# Routes
@router.post("/", response_model=InboxItemResponse)
async def create_inbox_item(
    item: InboxItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new inbox item
    
    This is typically called by internal services, monitors, and background tasks.
    Users can also create items directly for testing or manual insights.
    """
    
    created_item = inbox_service.create_inbox_item(
        db=db,
        user_id=current_user.id,
        kind=item.kind,
        title=item.title,
        body=item.body,
        source=item.source,
        payload=item.payload,
        priority=item.priority,
        dedupe_key=item.dedupe_key,
        immediate=item.immediate
    )
    
    if not created_item:
        # Item was batched or filtered out
        raise HTTPException(status_code=202, detail="Item queued for batching")
    
    return created_item


@router.get("/", response_model=InboxListResponse)
async def get_inbox_items(
    status: Optional[InboxStatus] = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Items to skip"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get inbox items with optional filtering and pagination
    """
    
    items = inbox_service.get_inbox_items(
        db=db,
        user_id=current_user.id,
        status=status,
        limit=limit,
        offset=offset
    )
    
    # Get total count for pagination
    total = len(inbox_service.get_inbox_items(
        db=db, 
        user_id=current_user.id, 
        status=status,
        limit=1000,  # Large limit to get total
        offset=0
    ))
    
    unread_count = inbox_service.get_unread_count(db=db, user_id=current_user.id)
    
    return InboxListResponse(
        items=items,
        total=total,
        unread_count=unread_count
    )


@router.post("/{item_id}/read")
async def mark_item_read(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark an inbox item as read"""
    
    success = inbox_service.mark_read(db=db, item_id=item_id, user_id=current_user.id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    
    return {"status": "read"}


@router.post("/{item_id}/archive")
async def archive_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Archive an inbox item"""
    
    success = inbox_service.archive(db=db, item_id=item_id, user_id=current_user.id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    
    return {"status": "archived"}


@router.post("/mark-all-read")
async def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark all unread items as read"""
    
    # Get all unread items
    unread_items = inbox_service.get_inbox_items(
        db=db,
        user_id=current_user.id,
        status=InboxStatus.NEW,
        limit=1000,
        offset=0
    )
    
    # Mark each as read
    count = 0
    for item in unread_items:
        if inbox_service.mark_read(db=db, item_id=item.id, user_id=current_user.id):
            count += 1
    
    return {"marked_read": count}


@router.get("/stats", response_model=InboxStatsResponse)
async def get_inbox_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get inbox statistics and system status"""
    
    from datetime import date, timedelta
    
    # Total items
    all_items = inbox_service.get_inbox_items(
        db=db,
        user_id=current_user.id,
        limit=1000,
        offset=0
    )
    total_items = len(all_items)
    
    # Unread count
    unread_count = inbox_service.get_unread_count(db=db, user_id=current_user.id)
    
    # Today's count
    today = date.today()
    today_items = [item for item in all_items if item.created_at.date() == today]
    today_count = len(today_items)
    
    # System status
    quiet_hours_active = inbox_service.policy.is_quiet_hours()
    
    return InboxStatsResponse(
        total_items=total_items,
        unread_count=unread_count,
        today_count=today_count,
        last_batch_time=inbox_service._last_batch_time,
        quiet_hours_active=quiet_hours_active
    )


@router.delete("/{item_id}")
async def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete an inbox item (admin use)"""
    
    item = db.query(JarvisInbox).filter(
        JarvisInbox.id == item_id,
        JarvisInbox.user_id == current_user.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    
    db.delete(item)
    db.commit()
    
    return {"status": "deleted"}