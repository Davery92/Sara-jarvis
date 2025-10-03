from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.thread import ConversationThread, EpisodeThreadMapping
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class ThreadCreate(BaseModel):
    title: str
    tags: List[str] = []


class ThreadUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    tags: Optional[List[str]] = None
    archived: Optional[bool] = None


class ThreadResponse(BaseModel):
    id: str
    title: str
    summary: Optional[str]
    auto_generated: bool
    started_at: str
    last_activity: str
    message_count: int
    tags: List[str]
    archived: bool


class ThreadListResponse(BaseModel):
    threads: List[ThreadResponse]
    total: int
    page: int
    per_page: int


@router.post("/", response_model=ThreadResponse, status_code=status.HTTP_201_CREATED)
async def create_thread(
    thread_data: ThreadCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new conversation thread"""

    try:
        thread = ConversationThread(
            user_id=current_user.id,
            title=thread_data.title,
            tags=thread_data.tags
        )

        db.add(thread)
        db.commit()
        db.refresh(thread)

        return ThreadResponse(
            id=str(thread.id),
            title=thread.title,
            summary=thread.summary,
            auto_generated=thread.auto_generated,
            started_at=thread.started_at.isoformat(),
            last_activity=thread.last_activity.isoformat(),
            message_count=thread.message_count,
            tags=thread.tags or [],
            archived=thread.archived
        )
    except Exception as e:
        logger.error(f"Failed to create thread: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create thread")


@router.get("/", response_model=ThreadListResponse)
async def list_threads(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    archived: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List user's conversation threads"""

    try:
        query = db.query(ConversationThread).filter(ConversationThread.user_id == current_user.id)

        # Apply filters
        if archived is not None:
            query = query.filter(ConversationThread.archived == archived)
        else:
            # Default: show only non-archived
            query = query.filter(ConversationThread.archived == False)

        if search:
            search_term = f"%{search}%"
            query = query.filter(
                (ConversationThread.title.ilike(search_term)) |
                (ConversationThread.summary.ilike(search_term))
            )

        # Get total count
        total = query.count()

        # Apply pagination and ordering
        offset = (page - 1) * per_page
        threads = query.order_by(desc(ConversationThread.last_activity)).offset(offset).limit(per_page).all()

        thread_responses = [
            ThreadResponse(
                id=str(thread.id),
                title=thread.title,
                summary=thread.summary,
                auto_generated=thread.auto_generated,
                started_at=thread.started_at.isoformat(),
                last_activity=thread.last_activity.isoformat(),
                message_count=thread.message_count,
                tags=thread.tags or [],
                archived=thread.archived
            )
            for thread in threads
        ]

        return ThreadListResponse(
            threads=thread_responses,
            total=total,
            page=page,
            per_page=per_page
        )
    except Exception as e:
        logger.error(f"Failed to list threads: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve threads")


@router.get("/{thread_id}", response_model=ThreadResponse)
async def get_thread(
    thread_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific thread"""

    thread = db.query(ConversationThread).filter(
        ConversationThread.id == thread_id,
        ConversationThread.user_id == current_user.id
    ).first()

    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thread not found"
        )

    return ThreadResponse(
        id=str(thread.id),
        title=thread.title,
        summary=thread.summary,
        auto_generated=thread.auto_generated,
        started_at=thread.started_at.isoformat(),
        last_activity=thread.last_activity.isoformat(),
        message_count=thread.message_count,
        tags=thread.tags or [],
        archived=thread.archived
    )


@router.put("/{thread_id}", response_model=ThreadResponse)
async def update_thread(
    thread_id: str,
    thread_update: ThreadUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a thread"""

    try:
        thread = db.query(ConversationThread).filter(
            ConversationThread.id == thread_id,
            ConversationThread.user_id == current_user.id
        ).first()

        if not thread:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Thread not found"
            )

        # Update fields
        if thread_update.title is not None:
            thread.title = thread_update.title
        if thread_update.summary is not None:
            thread.summary = thread_update.summary
        if thread_update.tags is not None:
            thread.tags = thread_update.tags
        if thread_update.archived is not None:
            thread.archived = thread_update.archived

        thread.last_activity = datetime.now(timezone.utc)

        db.commit()
        db.refresh(thread)

        return ThreadResponse(
            id=str(thread.id),
            title=thread.title,
            summary=thread.summary,
            auto_generated=thread.auto_generated,
            started_at=thread.started_at.isoformat(),
            last_activity=thread.last_activity.isoformat(),
            message_count=thread.message_count,
            tags=thread.tags or [],
            archived=thread.archived
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update thread: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update thread")


@router.delete("/{thread_id}")
async def delete_thread(
    thread_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete (archive) a thread"""

    try:
        thread = db.query(ConversationThread).filter(
            ConversationThread.id == thread_id,
            ConversationThread.user_id == current_user.id
        ).first()

        if not thread:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Thread not found"
            )

        # Soft delete by archiving
        thread.archived = True
        thread.last_activity = datetime.now(timezone.utc)

        db.commit()

        return {"message": "Thread archived successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete thread: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete thread")


@router.post("/{thread_id}/episodes/{episode_id}")
async def link_episode_to_thread(
    thread_id: str,
    episode_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Link an episode to a thread"""

    try:
        # Verify thread ownership
        thread = db.query(ConversationThread).filter(
            ConversationThread.id == thread_id,
            ConversationThread.user_id == current_user.id
        ).first()

        if not thread:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Thread not found"
            )

        # Create mapping
        mapping = EpisodeThreadMapping(
            episode_id=episode_id,
            thread_id=thread_id
        )

        db.add(mapping)

        # Update thread message count and activity
        thread.message_count = thread.message_count + 1
        thread.last_activity = datetime.now(timezone.utc)

        db.commit()

        return {"message": "Episode linked to thread successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to link episode to thread: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to link episode")
