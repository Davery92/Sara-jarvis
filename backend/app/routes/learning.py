"""
Learning Routes
API endpoints for the Sara Learning System: topics, sources, chat, research
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import logging
import re
import asyncio
import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.learning import (
    LearningTopic, TopicSource, SourceChunk, LearningSession,
    LearningProgress, TopicScratchpad, ResearchReport, ResearchJob, LearningArtifact,
    TopicConnection
)
from app.prompts.learning_system_prompt import get_learning_system_prompt

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class TopicCreate(BaseModel):
    title: str
    description: Optional[str] = None
    parent_id: Optional[str] = None
    priority: Optional[int] = 5


class TopicUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    mastery_level: Optional[float] = None
    priority: Optional[int] = None
    parent_id: Optional[str] = None


class TopicResponse(BaseModel):
    id: str
    user_id: str
    parent_id: Optional[str]
    title: str
    description: Optional[str]
    status: str
    mastery_level: float
    priority: int
    created_at: str
    updated_at: str


class SourceCreate(BaseModel):
    topic_id: str
    source_type: str  # web, pdf, document, note
    url: Optional[str] = None
    title: Optional[str] = None


class SourceResponse(BaseModel):
    id: str
    topic_id: str
    source_type: str
    url: Optional[str]
    title: Optional[str]
    quality_score: float
    fetch_status: str
    created_at: str


class ScratchpadUpdate(BaseModel):
    content: str


class ScratchpadResponse(BaseModel):
    id: str
    topic_id: str
    content: str
    version: int
    updated_at: str


class ArtifactCreate(BaseModel):
    topic_id: Optional[str] = None
    artifact_type: str  # concept_map, mind_map, flowchart, comparison
    title: Optional[str] = None
    content: Dict[str, Any]  # React Flow nodes/edges


class ArtifactUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[Dict[str, Any]] = None


class ArtifactResponse(BaseModel):
    id: str
    topic_id: Optional[str]
    artifact_type: str
    title: Optional[str]
    content: Dict[str, Any]
    version: int
    created_at: str
    updated_at: str


class LearningChatRequest(BaseModel):
    message: str
    topic_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = {}


class ResearchQuickRequest(BaseModel):
    question: str
    topic_id: Optional[str] = None


class ResearchDeepRequest(BaseModel):
    question: str
    topic_id: Optional[str] = None


class ConnectionCreate(BaseModel):
    source_topic_id: str
    target_topic_id: str
    connection_type: str  # prerequisite, related, builds_on, contrasts, applies_to
    description: Optional[str] = None
    strength: float = 0.5


class ConnectionResponse(BaseModel):
    id: str
    source_topic_id: str
    target_topic_id: str
    connection_type: str
    strength: float
    description: Optional[str]
    auto_generated: bool
    confirmed: bool
    created_at: str


class QuizRequest(BaseModel):
    question_count: int = 5
    question_type: Optional[str] = None  # recall, comprehension, application, synthesis
    difficulty: Optional[str] = None  # easy, medium, hard


class FlashcardRequest(BaseModel):
    card_count: int = 10


class QuizAnswerSubmit(BaseModel):
    question_id: str
    user_answer: str
    correct_answer: str


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def get_current_user_id(request: Request, db: Session = Depends(get_db)) -> str:
    """Get current user ID from JWT token (cookie or Authorization header)"""
    from jose import jwt, JWTError
    from app.core.config import settings

    # Try to get token from cookie first (for web UI)
    access_token = request.cookies.get("access_token")

    # If no cookie, try Authorization header (for programmatic access like iOS app)
    if not access_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            access_token = auth_header[7:]  # Remove "Bearer " prefix

    if not access_token:
        # Fall back to SOLO_USER_ID for unauthenticated requests
        import os
        solo_user_id = os.getenv("SOLO_USER_ID")
        if solo_user_id:
            return solo_user_id
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(access_token, settings.jwt_secret, algorithms=["HS256"])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


# Simple message class for SimpleLLMClient compatibility
class SimpleMessage:
    """Simple message object compatible with SimpleLLMClient"""
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content


# ============================================================================
# TOPIC ENDPOINTS
# ============================================================================

@router.get("/topics", response_model=List[TopicResponse])
async def list_topics(
    status: Optional[str] = None,
    parent_id: Optional[str] = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """List all learning topics for the user"""
    try:
        logger.info(f"📚 list_topics called with user_id={user_id}, status={status}, parent_id={parent_id}")
        query = db.query(LearningTopic).filter(LearningTopic.user_id == user_id)

        if status:
            query = query.filter(LearningTopic.status == status)
        if parent_id:
            query = query.filter(LearningTopic.parent_id == parent_id)
        else:
            # Default to root topics
            query = query.filter(LearningTopic.parent_id.is_(None))

        topics = query.order_by(LearningTopic.priority.desc(), LearningTopic.created_at.desc()).all()
        logger.info(f"📚 Found {len(topics)} topics for user {user_id}")

        return [
            TopicResponse(
                id=t.id,
                user_id=t.user_id,
                parent_id=t.parent_id,
                title=t.title,
                description=t.description,
                status=t.status,
                mastery_level=t.mastery_level or 0.0,
                priority=t.priority or 5,
                created_at=t.created_at.isoformat() if t.created_at else "",
                updated_at=t.updated_at.isoformat() if t.updated_at else ""
            )
            for t in topics
        ]
    except Exception as e:
        logger.error(f"Error listing topics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/topics", response_model=TopicResponse)
async def create_topic(
    topic: TopicCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Create a new learning topic"""
    try:
        new_topic = LearningTopic(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=topic.title,
            description=topic.description,
            parent_id=topic.parent_id,
            priority=topic.priority or 5,
            status="active"
        )
        db.add(new_topic)
        db.commit()
        db.refresh(new_topic)

        return TopicResponse(
            id=new_topic.id,
            user_id=new_topic.user_id,
            parent_id=new_topic.parent_id,
            title=new_topic.title,
            description=new_topic.description,
            status=new_topic.status,
            mastery_level=new_topic.mastery_level or 0.0,
            priority=new_topic.priority or 5,
            created_at=new_topic.created_at.isoformat() if new_topic.created_at else "",
            updated_at=new_topic.updated_at.isoformat() if new_topic.updated_at else ""
        )
    except Exception as e:
        logger.error(f"Error creating topic: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/topics/{topic_id}", response_model=TopicResponse)
async def get_topic(
    topic_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get a specific topic with its details"""
    try:
        topic = db.query(LearningTopic).filter(
            LearningTopic.id == topic_id,
            LearningTopic.user_id == user_id
        ).first()

        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")

        return TopicResponse(
            id=topic.id,
            user_id=topic.user_id,
            parent_id=topic.parent_id,
            title=topic.title,
            description=topic.description,
            status=topic.status,
            mastery_level=topic.mastery_level or 0.0,
            priority=topic.priority or 5,
            created_at=topic.created_at.isoformat() if topic.created_at else "",
            updated_at=topic.updated_at.isoformat() if topic.updated_at else ""
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting topic: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/topics/{topic_id}", response_model=TopicResponse)
async def update_topic(
    topic_id: str,
    topic_update: TopicUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Update a learning topic"""
    try:
        topic = db.query(LearningTopic).filter(
            LearningTopic.id == topic_id,
            LearningTopic.user_id == user_id
        ).first()

        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")

        if topic_update.title is not None:
            topic.title = topic_update.title
        if topic_update.description is not None:
            topic.description = topic_update.description
        if topic_update.status is not None:
            topic.status = topic_update.status
        if topic_update.mastery_level is not None:
            topic.mastery_level = topic_update.mastery_level
        if topic_update.priority is not None:
            topic.priority = topic_update.priority
        if topic_update.parent_id is not None:
            topic.parent_id = topic_update.parent_id

        db.commit()
        db.refresh(topic)

        return TopicResponse(
            id=topic.id,
            user_id=topic.user_id,
            parent_id=topic.parent_id,
            title=topic.title,
            description=topic.description,
            status=topic.status,
            mastery_level=topic.mastery_level or 0.0,
            priority=topic.priority or 5,
            created_at=topic.created_at.isoformat() if topic.created_at else "",
            updated_at=topic.updated_at.isoformat() if topic.updated_at else ""
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating topic: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/topics/{topic_id}")
async def delete_topic(
    topic_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Delete a learning topic"""
    try:
        topic = db.query(LearningTopic).filter(
            LearningTopic.id == topic_id,
            LearningTopic.user_id == user_id
        ).first()

        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")

        db.delete(topic)
        db.commit()

        return {"status": "deleted", "topic_id": topic_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting topic: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/topics/{topic_id}/children", response_model=List[TopicResponse])
async def get_topic_children(
    topic_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get child topics of a parent topic"""
    try:
        children = db.query(LearningTopic).filter(
            LearningTopic.parent_id == topic_id,
            LearningTopic.user_id == user_id
        ).order_by(LearningTopic.priority.desc(), LearningTopic.created_at.desc()).all()

        return [
            TopicResponse(
                id=t.id,
                user_id=t.user_id,
                parent_id=t.parent_id,
                title=t.title,
                description=t.description,
                status=t.status,
                mastery_level=t.mastery_level or 0.0,
                priority=t.priority or 5,
                created_at=t.created_at.isoformat() if t.created_at else "",
                updated_at=t.updated_at.isoformat() if t.updated_at else ""
            )
            for t in children
        ]
    except Exception as e:
        logger.error(f"Error getting topic children: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# SOURCE ENDPOINTS
# ============================================================================

@router.get("/topics/{topic_id}/sources", response_model=List[SourceResponse])
async def list_topic_sources(
    topic_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """List all sources for a topic"""
    try:
        sources = db.query(TopicSource).filter(
            TopicSource.topic_id == topic_id,
            TopicSource.user_id == user_id
        ).order_by(TopicSource.quality_score.desc(), TopicSource.created_at.desc()).all()

        return [
            SourceResponse(
                id=s.id,
                topic_id=s.topic_id,
                source_type=s.source_type,
                url=s.url,
                title=s.title,
                quality_score=s.quality_score or 0.5,
                fetch_status=s.fetch_status or "pending",
                created_at=s.created_at.isoformat() if s.created_at else ""
            )
            for s in sources
        ]
    except Exception as e:
        logger.error(f"Error listing sources: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sources", response_model=SourceResponse)
async def add_source(
    source: SourceCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Add a source to a topic"""
    try:
        # Verify topic exists and belongs to user
        topic = db.query(LearningTopic).filter(
            LearningTopic.id == source.topic_id,
            LearningTopic.user_id == user_id
        ).first()

        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")

        new_source = TopicSource(
            id=str(uuid.uuid4()),
            topic_id=source.topic_id,
            user_id=user_id,
            source_type=source.source_type,
            url=source.url,
            title=source.title,
            fetch_status="pending"
        )
        db.add(new_source)
        db.commit()
        db.refresh(new_source)

        return SourceResponse(
            id=new_source.id,
            topic_id=new_source.topic_id,
            source_type=new_source.source_type,
            url=new_source.url,
            title=new_source.title,
            quality_score=new_source.quality_score or 0.5,
            fetch_status=new_source.fetch_status or "pending",
            created_at=new_source.created_at.isoformat() if new_source.created_at else ""
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding source: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sources/{source_id}/fetch")
async def fetch_source(
    source_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Fetch and process a source (extract content, chunk, embed)"""
    try:
        from app.services.learning_source_service import learning_source_service

        source = db.query(TopicSource).filter(
            TopicSource.id == source_id,
            TopicSource.user_id == user_id
        ).first()

        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        # Process the source (fetch, extract, chunk, embed)
        result = await learning_source_service.fetch_and_process_source(source, db)

        if result["status"] == "success":
            return {
                "status": "success",
                "source_id": source_id,
                "chunk_count": result.get("chunk_count", 0),
                "content_length": result.get("content_length", 0),
                "title": result.get("title"),
                "message": f"Source processed successfully with {result.get('chunk_count', 0)} chunks"
            }
        else:
            return {
                "status": "failed",
                "source_id": source_id,
                "error": result.get("error", "Unknown error"),
                "message": "Source processing failed"
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching source: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Delete a source"""
    try:
        source = db.query(TopicSource).filter(
            TopicSource.id == source_id,
            TopicSource.user_id == user_id
        ).first()

        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        db.delete(source)
        db.commit()

        return {"status": "deleted", "source_id": source_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting source: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# SCRATCHPAD ENDPOINTS
# ============================================================================

@router.get("/topics/{topic_id}/scratchpad", response_model=ScratchpadResponse)
async def get_scratchpad(
    topic_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get scratchpad for a topic"""
    try:
        scratchpad = db.query(TopicScratchpad).filter(
            TopicScratchpad.topic_id == topic_id,
            TopicScratchpad.user_id == user_id
        ).first()

        if not scratchpad:
            # Create empty scratchpad
            scratchpad = TopicScratchpad(
                id=str(uuid.uuid4()),
                topic_id=topic_id,
                user_id=user_id,
                content=""
            )
            db.add(scratchpad)
            db.commit()
            db.refresh(scratchpad)

        return ScratchpadResponse(
            id=scratchpad.id,
            topic_id=scratchpad.topic_id,
            content=scratchpad.content or "",
            version=scratchpad.version or 1,
            updated_at=scratchpad.updated_at.isoformat() if scratchpad.updated_at else ""
        )
    except Exception as e:
        logger.error(f"Error getting scratchpad: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/topics/{topic_id}/scratchpad", response_model=ScratchpadResponse)
async def update_scratchpad(
    topic_id: str,
    update: ScratchpadUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Update scratchpad for a topic"""
    try:
        scratchpad = db.query(TopicScratchpad).filter(
            TopicScratchpad.topic_id == topic_id,
            TopicScratchpad.user_id == user_id
        ).first()

        if not scratchpad:
            # Create new scratchpad
            scratchpad = TopicScratchpad(
                id=str(uuid.uuid4()),
                topic_id=topic_id,
                user_id=user_id,
                content=update.content
            )
            db.add(scratchpad)
        else:
            scratchpad.content = update.content
            scratchpad.version = (scratchpad.version or 1) + 1

        db.commit()
        db.refresh(scratchpad)

        return ScratchpadResponse(
            id=scratchpad.id,
            topic_id=scratchpad.topic_id,
            content=scratchpad.content or "",
            version=scratchpad.version or 1,
            updated_at=scratchpad.updated_at.isoformat() if scratchpad.updated_at else ""
        )
    except Exception as e:
        logger.error(f"Error updating scratchpad: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ARTIFACT ENDPOINTS
# ============================================================================

@router.get("/artifacts", response_model=List[ArtifactResponse])
async def list_artifacts(
    topic_id: Optional[str] = None,
    artifact_type: Optional[str] = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """List all artifacts for the user"""
    try:
        query = db.query(LearningArtifact).filter(LearningArtifact.user_id == user_id)

        if topic_id:
            query = query.filter(LearningArtifact.topic_id == topic_id)
        if artifact_type:
            query = query.filter(LearningArtifact.artifact_type == artifact_type)

        artifacts = query.order_by(LearningArtifact.updated_at.desc()).all()

        return [
            ArtifactResponse(
                id=a.id,
                topic_id=a.topic_id,
                artifact_type=a.artifact_type,
                title=a.title,
                content=a.content or {},
                version=a.version or 1,
                created_at=a.created_at.isoformat() if a.created_at else "",
                updated_at=a.updated_at.isoformat() if a.updated_at else ""
            )
            for a in artifacts
        ]
    except Exception as e:
        logger.error(f"Error listing artifacts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/artifacts", response_model=ArtifactResponse)
async def create_artifact(
    artifact: ArtifactCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Create a new artifact"""
    try:
        new_artifact = LearningArtifact(
            id=str(uuid.uuid4()),
            user_id=user_id,
            topic_id=artifact.topic_id,
            artifact_type=artifact.artifact_type,
            title=artifact.title,
            content=artifact.content
        )
        db.add(new_artifact)
        db.commit()
        db.refresh(new_artifact)

        return ArtifactResponse(
            id=new_artifact.id,
            topic_id=new_artifact.topic_id,
            artifact_type=new_artifact.artifact_type,
            title=new_artifact.title,
            content=new_artifact.content or {},
            version=new_artifact.version or 1,
            created_at=new_artifact.created_at.isoformat() if new_artifact.created_at else "",
            updated_at=new_artifact.updated_at.isoformat() if new_artifact.updated_at else ""
        )
    except Exception as e:
        logger.error(f"Error creating artifact: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get a specific artifact"""
    try:
        artifact = db.query(LearningArtifact).filter(
            LearningArtifact.id == artifact_id,
            LearningArtifact.user_id == user_id
        ).first()

        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

        return ArtifactResponse(
            id=artifact.id,
            topic_id=artifact.topic_id,
            artifact_type=artifact.artifact_type,
            title=artifact.title,
            content=artifact.content or {},
            version=artifact.version or 1,
            created_at=artifact.created_at.isoformat() if artifact.created_at else "",
            updated_at=artifact.updated_at.isoformat() if artifact.updated_at else ""
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting artifact: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def update_artifact(
    artifact_id: str,
    update: ArtifactUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Update an artifact"""
    try:
        artifact = db.query(LearningArtifact).filter(
            LearningArtifact.id == artifact_id,
            LearningArtifact.user_id == user_id
        ).first()

        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

        if update.title is not None:
            artifact.title = update.title
        if update.content is not None:
            artifact.content = update.content
            artifact.version = (artifact.version or 1) + 1

        db.commit()
        db.refresh(artifact)

        return ArtifactResponse(
            id=artifact.id,
            topic_id=artifact.topic_id,
            artifact_type=artifact.artifact_type,
            title=artifact.title,
            content=artifact.content or {},
            version=artifact.version or 1,
            created_at=artifact.created_at.isoformat() if artifact.created_at else "",
            updated_at=artifact.updated_at.isoformat() if artifact.updated_at else ""
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating artifact: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/artifacts/{artifact_id}")
async def delete_artifact(
    artifact_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Delete an artifact"""
    try:
        artifact = db.query(LearningArtifact).filter(
            LearningArtifact.id == artifact_id,
            LearningArtifact.user_id == user_id
        ).first()

        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

        db.delete(artifact)
        db.commit()

        return {"status": "deleted", "artifact_id": artifact_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting artifact: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CHAT ENDPOINT (STREAMING)
# ============================================================================

@router.post("/chat/stream")
async def learning_chat_stream(
    request: LearningChatRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Streaming learning chat endpoint with Socratic tutoring"""
    try:
        from app.main_simple import SimpleLLMClient
        from app.core.config import settings
        from app.services.learning_source_service import learning_source_service
        import logging

        logger = logging.getLogger("app.main_simple")
        logger.info(f"📚 Learning chat: user_id={user_id}, topic_id={request.topic_id}")

        OPENAI_MODEL = settings.openai_model
        ASSISTANT_NAME = settings.assistant_name

        # Get topic context if topic_id provided
        topic_context = ""
        scratchpad_content = ""
        rag_context = ""

        if request.topic_id:
            topic = db.query(LearningTopic).filter(
                LearningTopic.id == request.topic_id,
                LearningTopic.user_id == user_id
            ).first()

            if topic:
                topic_context = f"**Current Topic:** {topic.title}"
                if topic.description:
                    topic_context += f"\n{topic.description}"

                # Get sources summary
                sources = db.query(TopicSource).filter(
                    TopicSource.topic_id == request.topic_id
                ).limit(5).all()

                if sources:
                    topic_context += "\n\n**Available Sources:**"
                    for s in sources:
                        topic_context += f"\n- {s.title or s.url} ({s.source_type})"

                # RAG: Search for relevant chunks based on user's message
                try:
                    relevant_chunks = await learning_source_service.search_chunks(
                        topic_id=request.topic_id,
                        query=request.message,
                        db=db,
                        limit=5
                    )

                    if relevant_chunks:
                        rag_context = "\n\n**Relevant Source Content:**\n"
                        for chunk in relevant_chunks:
                            source_info = f"[{chunk.get('source_title', 'Source')}]"
                            if chunk.get('breadcrumb'):
                                source_info += f" > {chunk['breadcrumb']}"
                            rag_context += f"\n{source_info}:\n{chunk['text']}\n"
                        logger.info(f"📖 RAG: Found {len(relevant_chunks)} relevant chunks")
                except Exception as e:
                    logger.warning(f"RAG search failed: {e}")

            # Get scratchpad
            scratchpad = db.query(TopicScratchpad).filter(
                TopicScratchpad.topic_id == request.topic_id,
                TopicScratchpad.user_id == user_id
            ).first()

            if scratchpad and scratchpad.content:
                scratchpad_content = scratchpad.content

        # Build context prompt (include RAG context)
        full_topic_context = topic_context + rag_context
        context_prompt = get_learning_system_prompt(full_topic_context, scratchpad_content)

        # Get conversation history (from learning_chat episodes)
        history_result = db.execute(text("""
            SELECT role, content
            FROM episode
            WHERE user_id = :user_id AND source = 'learning_chat'
            ORDER BY created_at DESC
            LIMIT 20
        """), {"user_id": user_id})

        conversation_history = []
        for row in reversed(list(history_result.fetchall())):
            conversation_history.append({"role": row.role, "content": row.content})

        # Build messages
        messages = [{"role": "system", "content": context_prompt}]
        messages.extend(conversation_history[-10:])
        messages.append({"role": "user", "content": request.message})

        # Save user message to episodes
        user_episode_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO episode (id, user_id, source, role, content, importance, created_at, meta)
            VALUES (:id, :user_id, :source, :role, :content, :importance, :created_at, :meta)
        """), {
            "id": user_episode_id,
            "user_id": user_id,
            "source": "learning_chat",
            "role": "user",
            "content": request.message,
            "importance": 0.7,
            "created_at": datetime.utcnow(),
            "meta": json.dumps({"topic_id": request.topic_id} if request.topic_id else {})
        })
        db.commit()

        # Get learning-relevant tools from the registry
        from app.tools.registry import tool_registry

        # Learning chat gets: web search, learning tools, notes
        learning_tool_categories = ['web', 'learning', 'notes', 'memory']
        tools_schemas = tool_registry.get_tools_by_categories(learning_tool_categories)

        async def generate_events():
            try:
                # Create event queue for streaming
                event_queue = asyncio.Queue()

                # Set up streaming LLM client
                streaming_client = SimpleLLMClient()
                streaming_client.set_event_queue(event_queue)

                # Convert messages to SimpleMessage objects
                message_objects = [SimpleMessage(msg["role"], msg["content"]) for msg in messages]

                # Start LLM processing in background task
                async def process_chat():
                    response_content = await streaming_client.chat_with_tools(
                        messages=message_objects,
                        tools=tools_schemas,
                        user_id=user_id,
                        conversation_id=f"learning_{user_id}"
                    )

                    # Clean up XML tags
                    response_content = re.sub(r'<tool_call>.*?</tool_call>', '', response_content, flags=re.DOTALL).strip()
                    response_content = re.sub(r'<[^>]+>', '', response_content).strip()

                    # Save Sara's response to memory
                    db.execute(text("""
                        INSERT INTO episode (id, user_id, source, role, content, importance, created_at, meta)
                        VALUES (:id, :user_id, :source, :role, :content, :importance, :created_at, :meta)
                    """), {
                        "id": str(uuid.uuid4()),
                        "user_id": user_id,
                        "source": "learning_chat",
                        "role": "assistant",
                        "content": response_content,
                        "importance": 0.7,
                        "created_at": datetime.utcnow(),
                        "meta": json.dumps({"topic_id": request.topic_id} if request.topic_id else {})
                    })
                    db.commit()

                    await event_queue.put({
                        "type": "final_response",
                        "data": {
                            "content": response_content,
                            "timestamp": datetime.utcnow().isoformat()
                        }
                    })
                    await event_queue.put({"type": "done"})

                # Start processing
                task = asyncio.create_task(process_chat())

                # Stream events as they come in
                while True:
                    try:
                        event = await asyncio.wait_for(event_queue.get(), timeout=1.0)

                        if event.get("type") == "done":
                            break

                        # Format as Server-Sent Event
                        event_data = json.dumps(event)
                        yield f"data: {event_data}\n\n"

                    except asyncio.TimeoutError:
                        # Send heartbeat to keep connection alive
                        yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
                    except Exception as e:
                        logger.error(f"Error in event stream: {e}")
                        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                        break

                # Ensure task is cleaned up
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            except Exception as e:
                logger.error(f"Error in learning chat stream: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        return StreamingResponse(
            generate_events(),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive"
            }
        )

    except Exception as e:
        logger.error(f"Learning chat stream error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RESEARCH ENDPOINTS
# ============================================================================

@router.post("/topics/{topic_id}/auto-research")
async def auto_research_topic(
    topic_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Auto-discover and add sources for a topic based on its title and description.
    Called when creating a topic with 'research mode' enabled."""
    try:
        from app.services.search_service import search_service
        from app.services.learning_source_service import learning_source_service

        # Get the topic
        topic = db.query(LearningTopic).filter(
            LearningTopic.id == topic_id,
            LearningTopic.user_id == user_id
        ).first()

        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")

        # Build search queries based on topic
        search_queries = [
            f"{topic.title} tutorial",
            f"{topic.title} guide",
            f"{topic.title} explained"
        ]

        if topic.description:
            # Add a query based on the description
            search_queries.append(f"{topic.title} {topic.description[:50]}")

        # Search and add sources
        added_sources = []
        existing_urls = set()

        for query in search_queries[:3]:  # Limit to 3 queries
            try:
                search_result = await search_service.web_search(
                    query=query,
                    max_results=3
                )

                for result in search_result.get("results", [])[:2]:  # Top 2 per query
                    url = result.get("url")
                    if not url or url in existing_urls:
                        continue

                    title = result.get("title", url)

                    source = TopicSource(
                        id=str(uuid.uuid4()),
                        topic_id=topic_id,
                        user_id=user_id,
                        source_type="web",
                        url=url,
                        title=title,
                        fetch_status="pending"
                    )
                    db.add(source)
                    existing_urls.add(url)
                    added_sources.append({
                        "source_id": source.id,
                        "url": url,
                        "title": title
                    })

                    if len(added_sources) >= 5:  # Max 5 sources
                        break

            except Exception as e:
                logger.warning(f"Search query failed: {e}")
                continue

            if len(added_sources) >= 5:
                break

        db.commit()

        # Fetch and process sources in background (first 3)
        fetched_count = 0
        for source_info in added_sources[:3]:
            source = db.query(TopicSource).filter(
                TopicSource.id == source_info["source_id"]
            ).first()
            if source:
                try:
                    result = await learning_source_service.fetch_and_process_source(source, db)
                    if result.get("status") == "success":
                        fetched_count += 1
                        source_info["fetched"] = True
                        source_info["chunk_count"] = result.get("chunk_count", 0)
                except Exception as e:
                    logger.warning(f"Failed to fetch source: {e}")

        return {
            "topic_id": topic_id,
            "topic_title": topic.title,
            "sources_added": len(added_sources),
            "sources_fetched": fetched_count,
            "sources": added_sources,
            "message": f"Auto-discovered {len(added_sources)} sources for '{topic.title}'. {fetched_count} ready for learning."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auto-research failed: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/research/quick")
async def research_quick(
    request: ResearchQuickRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Quick feasibility check on a research question (sync)"""
    try:
        from app.services.search_service import search_service
        from app.core.llm import llm_client

        # Create research report record
        report = ResearchReport(
            id=str(uuid.uuid4()),
            user_id=user_id,
            topic_id=request.topic_id,
            question=request.question,
            report_type="quick",
            status="in_progress"
        )
        db.add(report)
        db.commit()

        # Check existing sources if topic_id provided
        existing_context = ""
        existing_sources = []
        if request.topic_id:
            from app.services.learning_source_service import learning_source_service
            try:
                chunks = await learning_source_service.search_chunks(
                    topic_id=request.topic_id,
                    query=request.question,
                    db=db,
                    limit=3
                )
                if chunks:
                    existing_context = "\n\n**From Your Existing Sources:**\n"
                    for chunk in chunks:
                        existing_context += f"- [{chunk.get('source_title', 'Source')}]: {chunk['text'][:200]}...\n"
                        existing_sources.append({
                            "title": chunk.get("source_title"),
                            "url": chunk.get("source_url"),
                            "relevance": chunk.get("similarity", 0)
                        })
            except Exception as e:
                logger.warning(f"Failed to search existing sources: {e}")

        # Perform web search
        web_results = []
        web_context = ""
        try:
            search_result = await search_service.web_search(
                query=request.question,
                max_results=5
            )
            web_results = search_result.get("results", [])
            if web_results:
                web_context = "\n\n**Web Search Results:**\n"
                for r in web_results[:5]:
                    web_context += f"- [{r.get('title', 'Untitled')}]({r.get('url', '')}): {r.get('snippet', '')[:150]}...\n"
        except Exception as e:
            logger.warning(f"Web search failed: {e}")

        # Generate quick analysis with LLM
        analysis_prompt = f"""You are a research assistant. Analyze this question and provide a quick feasibility assessment.

Question: {request.question}

{existing_context}
{web_context}

Provide a brief analysis (2-3 sentences) covering:
1. Whether this question can be answered with available information
2. Key insights from the sources
3. Whether deeper research would be beneficial

Keep the response concise and actionable."""

        try:
            analysis = await llm_client.generate(
                prompt=analysis_prompt,
                max_tokens=300
            )
            summary = analysis.strip() if analysis else "Unable to generate analysis."
        except Exception as e:
            logger.warning(f"LLM analysis failed: {e}")
            summary = "Quick analysis unavailable. Web search found {} results.".format(len(web_results))

        # Determine feasibility and confidence
        has_sources = len(existing_sources) > 0 or len(web_results) > 0
        confidence = 0.3
        if existing_sources:
            confidence += 0.3
        if web_results:
            confidence += 0.2
        if len(web_results) >= 3:
            confidence += 0.1

        # Update report
        report.status = "completed"
        report.summary = summary
        report.confidence = min(confidence, 1.0)
        report.sources_used = [
            {"url": r.get("url"), "title": r.get("title"), "contribution": "web_search"}
            for r in web_results[:5]
        ]
        report.completed_at = datetime.utcnow()
        db.commit()

        return {
            "report_id": report.id,
            "question": request.question,
            "feasible": has_sources,
            "confidence": report.confidence,
            "summary": summary,
            "suggested_approach": "Deep research recommended" if confidence < 0.6 else "Sufficient information available",
            "existing_sources": existing_sources,
            "web_results": [
                {"title": r.get("title"), "url": r.get("url"), "snippet": r.get("snippet", "")[:200]}
                for r in web_results[:5]
            ]
        }
    except Exception as e:
        logger.error(f"Error in quick research: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/research/deep")
async def research_deep(
    request: ResearchDeepRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Start a deep research job (async)"""
    try:
        # Create research report record
        report = ResearchReport(
            id=str(uuid.uuid4()),
            user_id=user_id,
            topic_id=request.topic_id,
            question=request.question,
            report_type="deep",
            status="pending"
        )
        db.add(report)

        # Create research job
        job = ResearchJob(
            id=str(uuid.uuid4()),
            user_id=user_id,
            report_id=report.id,
            status="queued"
        )
        db.add(job)
        db.commit()

        return {
            "job_id": job.id,
            "report_id": report.id,
            "question": request.question,
            "status": "queued",
            "message": "Deep research job queued. Check status with /learn/research/{job_id}"
        }
    except Exception as e:
        logger.error(f"Error starting deep research: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/research/{job_id}")
async def get_research_status(
    job_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get status of a research job"""
    try:
        job = db.query(ResearchJob).filter(
            ResearchJob.id == job_id,
            ResearchJob.user_id == user_id
        ).first()

        if not job:
            raise HTTPException(status_code=404, detail="Research job not found")

        result = {
            "job_id": job.id,
            "status": job.status,
            "progress": job.progress,
            "current_step": job.current_step,
            "sources_found": job.sources_found,
            "created_at": job.created_at.isoformat() if job.created_at else None
        }

        # Include report if completed
        if job.status == "completed" and job.report_id:
            report = db.query(ResearchReport).filter(
                ResearchReport.id == job.report_id
            ).first()
            if report:
                result["report"] = report.to_dict()

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting research status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# REVIEW QUEUE ENDPOINT
# ============================================================================

@router.get("/review-queue")
async def get_review_queue(
    limit: int = 10,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get concepts due for spaced repetition review"""
    try:
        now = datetime.utcnow()

        due_items = db.query(LearningProgress).filter(
            LearningProgress.user_id == user_id,
            LearningProgress.next_review_at <= now
        ).order_by(
            LearningProgress.next_review_at
        ).limit(limit).all()

        return {
            "due_count": len(due_items),
            "items": [item.to_dict() for item in due_items]
        }
    except Exception as e:
        logger.error(f"Error getting review queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# SESSION ENDPOINTS
# ============================================================================

@router.post("/sessions/start")
async def start_session(
    topic_id: Optional[str] = None,
    session_type: str = "study",
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Start a new learning session"""
    try:
        session = LearningSession(
            id=str(uuid.uuid4()),
            user_id=user_id,
            topic_id=topic_id,
            session_type=session_type,
            started_at=datetime.utcnow()
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        return session.to_dict()
    except Exception as e:
        logger.error(f"Error starting session: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/end")
async def end_session(
    session_id: str,
    notes: Optional[str] = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """End a learning session"""
    try:
        session = db.query(LearningSession).filter(
            LearningSession.id == session_id,
            LearningSession.user_id == user_id
        ).first()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session.ended_at = datetime.utcnow()
        if session.started_at:
            duration = (session.ended_at - session.started_at).total_seconds() / 60
            session.duration_minutes = int(duration)
        if notes:
            session.notes = notes

        db.commit()
        db.refresh(session)

        return session.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error ending session: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# LEARNING PATH ENDPOINTS
# ============================================================================

@router.get("/path")
async def get_learning_path(
    focus_topic_id: Optional[str] = None,
    max_steps: int = 5,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get a personalized learning path based on topics, mastery levels, and knowledge gaps.
    Returns prioritized study recommendations using spaced repetition principles.
    """
    try:
        from app.services.learning_path_service import learning_path_service

        result = await learning_path_service.generate_learning_path(
            user_id=user_id,
            db=db,
            focus_topic_id=focus_topic_id,
            max_steps=max_steps
        )

        return result

    except Exception as e:
        logger.error(f"Failed to generate learning path: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/path/next-session")
async def get_next_study_session(
    duration_minutes: int = 30,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get a recommended study session based on available time.
    Returns the highest priority topic and specific actions to take.
    """
    try:
        from app.services.learning_path_service import learning_path_service

        result = await learning_path_service.get_next_study_session(
            user_id=user_id,
            db=db,
            duration_minutes=duration_minutes
        )

        return result

    except Exception as e:
        logger.error(f"Failed to get next session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# TOPIC CONNECTION ENDPOINTS
# ============================================================================

@router.post("/connections", response_model=dict)
async def create_connection(
    connection: ConnectionCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Create a connection between two topics"""
    try:
        from app.services.topic_connection_service import topic_connection_service

        result = await topic_connection_service.create_connection(
            user_id=user_id,
            source_topic_id=connection.source_topic_id,
            target_topic_id=connection.target_topic_id,
            connection_type=connection.connection_type,
            db=db,
            description=connection.description,
            strength=connection.strength,
            auto_generated=False
        )

        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("error"))

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating connection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/topics/{topic_id}/connections")
async def get_topic_connections(
    topic_id: str,
    include_unconfirmed: bool = False,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get all connections for a topic"""
    try:
        from app.services.topic_connection_service import topic_connection_service

        result = await topic_connection_service.get_connections(
            user_id=user_id,
            topic_id=topic_id,
            db=db,
            include_unconfirmed=include_unconfirmed
        )

        return result

    except Exception as e:
        logger.error(f"Error getting connections: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/topics/{topic_id}/discover-connections")
async def discover_topic_connections(
    topic_id: str,
    auto_create: bool = False,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Discover potential connections for a topic using semantic similarity.
    Optionally auto-create strong connections.
    """
    try:
        from app.services.topic_connection_service import topic_connection_service

        result = await topic_connection_service.discover_connections(
            user_id=user_id,
            topic_id=topic_id,
            db=db,
            auto_create=auto_create
        )

        return result

    except Exception as e:
        logger.error(f"Error discovering connections: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connections/{connection_id}/confirm")
async def confirm_connection(
    connection_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Confirm an auto-generated connection"""
    try:
        from app.services.topic_connection_service import topic_connection_service

        result = await topic_connection_service.confirm_connection(
            user_id=user_id,
            connection_id=connection_id,
            db=db
        )

        if result.get("status") == "error":
            raise HTTPException(status_code=404, detail=result.get("error"))

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error confirming connection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/connections/{connection_id}")
async def delete_connection(
    connection_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Delete a topic connection"""
    try:
        from app.services.topic_connection_service import topic_connection_service

        result = await topic_connection_service.delete_connection(
            user_id=user_id,
            connection_id=connection_id,
            db=db
        )

        if result.get("status") == "error":
            raise HTTPException(status_code=404, detail=result.get("error"))

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting connection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph")
async def get_topic_graph(
    include_unconfirmed: bool = False,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get all topics and connections as a graph structure for visualization.
    Returns nodes (topics) and edges (connections).
    """
    try:
        from app.services.topic_connection_service import topic_connection_service

        result = await topic_connection_service.get_topic_graph(
            user_id=user_id,
            db=db,
            include_unconfirmed=include_unconfirmed
        )

        return result

    except Exception as e:
        logger.error(f"Error getting topic graph: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# QUIZ/FLASHCARD ENDPOINTS
# ============================================================================

@router.post("/topics/{topic_id}/quiz")
async def generate_quiz(
    topic_id: str,
    request: QuizRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Generate quiz questions from a topic's sources.
    Uses LLM to create varied questions based on source content.
    """
    try:
        from app.services.quiz_service import quiz_service

        result = await quiz_service.generate_questions(
            topic_id=topic_id,
            user_id=user_id,
            db=db,
            question_count=request.question_count,
            question_type=request.question_type,
            difficulty=request.difficulty
        )

        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("error"))

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating quiz: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/topics/{topic_id}/flashcards")
async def generate_flashcards(
    topic_id: str,
    request: FlashcardRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Generate flashcards from a topic's sources.
    Creates front/back cards with optional hints.
    """
    try:
        from app.services.quiz_service import quiz_service

        result = await quiz_service.generate_flashcards(
            topic_id=topic_id,
            user_id=user_id,
            db=db,
            card_count=request.card_count
        )

        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("error"))

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating flashcards: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/topics/{topic_id}/quiz/submit")
async def submit_quiz_answer(
    topic_id: str,
    answer: QuizAnswerSubmit,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Submit a quiz answer and update spaced repetition progress.
    Updates mastery level based on performance.
    """
    try:
        from app.services.quiz_service import quiz_service

        result = await quiz_service.submit_quiz_answer(
            topic_id=topic_id,
            question_id=answer.question_id,
            user_answer=answer.user_answer,
            correct_answer=answer.correct_answer,
            user_id=user_id,
            db=db
        )

        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("error"))

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting quiz answer: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flashcards/review")
async def get_review_flashcards(
    topic_id: Optional[str] = None,
    limit: int = 20,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get flashcards due for spaced repetition review.
    Returns cards from topics that need review based on SM-2 algorithm.
    """
    try:
        from app.services.quiz_service import quiz_service

        result = await quiz_service.get_review_flashcards(
            user_id=user_id,
            db=db,
            topic_id=topic_id,
            limit=limit
        )

        return result

    except Exception as e:
        logger.error(f"Error getting review flashcards: {e}")
        raise HTTPException(status_code=500, detail=str(e))
