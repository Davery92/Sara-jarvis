"""Conversation routes extracted from main_simple.py."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, distinct
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import get_db
from app.core.deps import get_current_user
from app.core.timezone import format_iso_utc
from app.models.conversation import Conversation, ConversationTurn
from app.models.episode import Episode
from app.models.user import User
from app.models.profile import UserProfile
from app.schemas.memory import (
    ConversationResponse,
    ConversationTurnResponse,
    ConversationSummaryResponse,
    SetActiveConversationRequest,
    EpisodeMessageResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== CONVERSATION ENDPOINTS ====================

@router.get("/conversations", response_model=list[ConversationResponse])
async def get_conversations(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get recent conversations for the current user"""
    conversations = db.query(Conversation).filter(
        Conversation.user_id == current_user.id
    ).order_by(Conversation.updated_at.desc()).limit(limit).all()

    return [
        ConversationResponse(
            id=conv.id,
            title=conv.title or "Conversation",
            summary=conv.summary or "",
            total_messages=conv.total_messages,
            created_at=conv.created_at.isoformat(),
            updated_at=conv.updated_at.isoformat(),
        )
        for conv in conversations
    ]


@router.get("/conversations/{conversation_id}/turns", response_model=list[ConversationTurnResponse])
async def get_conversation_turns(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all turns/messages for a specific conversation"""
    # Verify the conversation belongs to the user
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id,
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    turns = db.query(ConversationTurn).filter(
        ConversationTurn.conversation_id == conversation_id
    ).order_by(ConversationTurn.message_index).all()

    return [
        ConversationTurnResponse(
            id=turn.id,
            conversation_id=turn.conversation_id,
            role=turn.role,
            content=turn.content,
            message_index=turn.message_index,
            created_at=turn.created_at.isoformat(),
        )
        for turn in turns
    ]


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a conversation and all its turns"""
    try:
        logger.info(f"Delete request for conversation {conversation_id} by user {current_user.id}")

        # Verify the conversation belongs to the user
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        ).first()

        if not conversation:
            logger.warning(f"Conversation {conversation_id} not found for user {current_user.id}")
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Delete all conversation turns first (due to foreign key constraints)
        db.query(ConversationTurn).filter(
            ConversationTurn.conversation_id == conversation_id
        ).delete()

        # Delete the conversation
        db.delete(conversation)
        db.commit()

        logger.info(f"Deleted conversation {conversation_id} and its turns for user {current_user.id}")
        return {"message": "Conversation deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation {conversation_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete conversation")


# ==================== EPISODE-BASED CONVERSATION ENDPOINTS ====================

@router.get("/api/conversations/list", response_model=list[ConversationSummaryResponse])
async def list_conversations(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get list of conversations based on Episodes"""
    try:
        # Query for distinct conversation_ids with aggregated data
        conversations = db.query(
            Episode.conversation_id,
            func.min(Episode.content).label('first_message'),
            func.count(Episode.id).label('message_count'),
            func.max(Episode.created_at).label('last_activity'),
            func.min(Episode.created_at).label('created_at'),
        ).filter(
            Episode.user_id == current_user.id,
            Episode.conversation_id.isnot(None),
            Episode.role.in_(['user', 'assistant']),
        ).group_by(
            Episode.conversation_id
        ).order_by(
            func.max(Episode.created_at).desc()
        ).limit(limit).all()

        return [
            ConversationSummaryResponse(
                conversation_id=conv.conversation_id,
                first_message=conv.first_message[:100] if conv.first_message else "",
                message_count=conv.message_count,
                last_activity=conv.last_activity.isoformat(),
                created_at=conv.created_at.isoformat(),
            )
            for conv in conversations
        ]
    except Exception as e:
        logger.error(f"Error fetching conversations list: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch conversations")


def _snippet(content: str, q: str, width: int = 120) -> str:
    """A short excerpt centered on the first match of `q`, for search results."""
    if not content:
        return ""
    idx = content.lower().find(q.lower())
    if idx < 0:
        return content[:width]
    start = max(0, idx - 40)
    prefix = "…" if start > 0 else ""
    suffix = "…" if start + width < len(content) else ""
    return f"{prefix}{content[start:start + width]}{suffix}"


@router.get("/api/conversations/search", response_model=list[ConversationSummaryResponse])
async def search_conversations(
    q: str,
    limit: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Full-text-ish search across the user's past conversations.

    Matches on episode (message) content, then rolls matches up to their
    conversation with a snippet centered on the hit. Backs the web chat's
    history search. Single-user scale, so a simple ILIKE + Python rollup is
    plenty — no need for a tsvector index here.
    """
    q = (q or "").strip()
    if len(q) < 2:
        return []
    try:
        pattern = f"%{q}%"

        # Conversations that contain at least one matching message.
        matching_ids = [
            row[0]
            for row in db.query(Episode.conversation_id)
            .filter(
                Episode.user_id == current_user.id,
                Episode.conversation_id.isnot(None),
                Episode.role.in_(["user", "assistant"]),
                Episode.content.ilike(pattern),
            )
            .distinct()
            .all()
        ]
        if not matching_ids:
            return []

        # Aggregate stats for those conversations.
        rows = (
            db.query(
                Episode.conversation_id,
                func.count(Episode.id).label("message_count"),
                func.max(Episode.created_at).label("last_activity"),
                func.min(Episode.created_at).label("created_at"),
            )
            .filter(
                Episode.user_id == current_user.id,
                Episode.conversation_id.in_(matching_ids),
                Episode.role.in_(["user", "assistant"]),
            )
            .group_by(Episode.conversation_id)
            .order_by(func.max(Episode.created_at).desc())
            .limit(limit)
            .all()
        )

        # Earliest matching message per conversation → snippet.
        snippets: dict[str, str] = {}
        for cid, content in (
            db.query(Episode.conversation_id, Episode.content)
            .filter(
                Episode.user_id == current_user.id,
                Episode.conversation_id.in_(matching_ids),
                Episode.role.in_(["user", "assistant"]),
                Episode.content.ilike(pattern),
            )
            .order_by(Episode.created_at.asc())
            .all()
        ):
            if cid not in snippets:
                snippets[cid] = _snippet(content, q)

        return [
            ConversationSummaryResponse(
                conversation_id=row.conversation_id,
                first_message=snippets.get(row.conversation_id, ""),
                message_count=row.message_count,
                last_activity=row.last_activity.isoformat(),
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Error searching conversations: {e}")
        raise HTTPException(status_code=500, detail="Failed to search conversations")


@router.get("/api/conversations/{conversation_id}/messages", response_model=list[EpisodeMessageResponse])
async def get_conversation_messages(
    conversation_id: str,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get messages for a specific conversation from Episodes"""
    try:
        # Get messages for this conversation
        episodes = db.query(Episode).filter(
            Episode.conversation_id == conversation_id,
            Episode.user_id == current_user.id,
            Episode.role.in_(['user', 'assistant']),
        ).order_by(
            Episode.created_at.asc()
        ).offset(offset).limit(limit).all()

        return [
            EpisodeMessageResponse(
                id=ep.id,
                role=ep.role,
                content=ep.content,
                created_at=format_iso_utc(ep.created_at),
                importance=ep.importance,
            )
            for ep in episodes
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching conversation messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch conversation messages")


@router.post("/api/conversations/active")
async def set_active_conversation(
    request: SetActiveConversationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set the user's current active conversation"""
    try:
        # Get or create user profile
        user_profile = db.query(UserProfile).filter(
            UserProfile.user_id == current_user.id
        ).first()

        if not user_profile:
            user_profile = UserProfile(
                user_id=current_user.id,
                profile_data={},
            )
            db.add(user_profile)

        # Store active conversation_id in profile_data field (JSONB)
        if not user_profile.profile_data:
            user_profile.profile_data = {}

        # Make a copy to ensure SQLAlchemy detects the change
        profile_data_copy = dict(user_profile.profile_data) if user_profile.profile_data else {}
        profile_data_copy['active_conversation_id'] = request.conversation_id
        user_profile.profile_data = profile_data_copy

        # Mark as modified for SQLAlchemy to detect the change
        flag_modified(user_profile, "profile_data")

        db.commit()

        return {"message": "Active conversation set", "conversation_id": request.conversation_id}
    except Exception as e:
        logger.error(f"Error setting active conversation: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to set active conversation")


@router.get("/api/conversations/active")
async def get_active_conversation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the user's current active conversation"""
    try:
        user_profile = db.query(UserProfile).filter(
            UserProfile.user_id == current_user.id
        ).first()

        active_conversation_id = None
        if user_profile and user_profile.profile_data:
            active_conversation_id = user_profile.profile_data.get('active_conversation_id')

        # Validate the stored conversation actually has episodes
        if active_conversation_id:
            has_episodes = db.query(Episode).filter(
                Episode.conversation_id == active_conversation_id,
                Episode.user_id == current_user.id,
            ).first()
            if not has_episodes:
                # Stored conversation has no messages — treat as no active conversation
                active_conversation_id = None

        # If no active conversation, return null — let the frontend show a fresh chat.
        # Don't auto-load an old conversation; "New Chat" explicitly clears this.
        return {
            "conversation_id": active_conversation_id
        }
    except Exception as e:
        logger.error(f"Error getting active conversation: {e}")
        raise HTTPException(status_code=500, detail="Failed to get active conversation")
