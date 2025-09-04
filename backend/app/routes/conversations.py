from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.episode import Episode
from typing import List, Dict, Any
from sqlalchemy import desc

router = APIRouter()

@router.get("/")
async def get_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user conversations (episodes)"""
    try:
        episodes = db.query(Episode).filter(
            Episode.user_id == current_user.id
        ).order_by(desc(Episode.created_at)).limit(50).all()
        
        conversations = []
        for episode in episodes:
            conversations.append({
                "id": episode.id,
                "content": episode.content,
                "created_at": episode.created_at.isoformat() if episode.created_at else None,
                "importance": getattr(episode, 'importance', 1.0),
                "episode_type": getattr(episode, 'episode_type', 'conversation')
            })
        
        return conversations
        
    except Exception as e:
        return []