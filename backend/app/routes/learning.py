"""
Learning Routes
API endpoints for the Sara Learning System: topics, sources, chat, research
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from app.core.timezone import now as local_now
import uuid
import logging
import re
import asyncio
import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db
from app.models.learning import (
    LearningTopic, TopicSource, SourceChunk, LearningSession,
    LearningProgress, TopicScratchpad, ResearchReport, ResearchJob, LearningGuideJob, LearningArtifact,
    TopicConnection, LearningBlueprint
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
    auto_research: Optional[bool] = True  # Auto-discover sources on creation


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


class BlueprintParseRequest(BaseModel):
    text: str
    source_format: Optional[str] = "markdown"  # text, markdown, pdf
    parse_mode: Optional[str] = "balanced"  # fast, balanced, deep
    pace_mode: Optional[str] = "self_directed"
    title_override: Optional[str] = None


class BlueprintMaterializeRequest(BaseModel):
    mode: Optional[str] = "adaptive"
    create_sources: Optional[bool] = True
    create_connections: Optional[bool] = True
    create_curriculum: Optional[bool] = True
    seed_reviews: Optional[bool] = True
    replace_existing: Optional[bool] = False
    parent_topic_id: Optional[str] = None


class BlueprintGuideGenerateRequest(BaseModel):
    force_regenerate: Optional[bool] = False
    module_limit: Optional[int] = None
    model: Optional[str] = None
    num_ctx: Optional[int] = 16384


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
    include_all: bool = Query(False),
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
        elif not include_all:
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


@router.post("/topics")
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

        # Generate anchor points from known domains
        try:
            from app.services.anchor_service import anchor_service
            await anchor_service.generate_anchors(new_topic.id, user_id, db)
            logger.info(f"Generated anchors for new topic: {new_topic.title}")
        except Exception as e:
            logger.debug(f"Anchor generation on create failed (non-critical): {e}")

        # Check prerequisite chain depth — warn if overly deep
        prereq_warning = None
        try:
            from app.models.learning import TopicConnection
            from app.models.tangent_queue import TangentQueue

            # Walk prerequisite chain from this topic
            def _get_prereq_depth(tid, visited=None, depth=0):
                if visited is None:
                    visited = set()
                if tid in visited or depth > 10:
                    return depth
                visited.add(tid)
                prereqs = db.query(TopicConnection).filter(
                    TopicConnection.target_topic_id == tid,
                    TopicConnection.connection_type == "prerequisite"
                ).all()
                if not prereqs:
                    return depth
                return max(_get_prereq_depth(p.source_topic_id, visited, depth + 1) for p in prereqs)

            chain_depth = _get_prereq_depth(new_topic.id)
            prereq_branches = db.query(TopicConnection).filter(
                TopicConnection.target_topic_id == new_topic.id,
                TopicConnection.connection_type == "prerequisite"
            ).count()

            if chain_depth > 3 or prereq_branches > 5:
                # Queue excess prerequisites as tangent items
                prereq_conns = db.query(TopicConnection).filter(
                    TopicConnection.target_topic_id == new_topic.id,
                    TopicConnection.connection_type == "prerequisite"
                ).offset(2).all()  # Keep first 2 as direct prereqs, queue the rest
                for conn in prereq_conns:
                    prereq_topic = db.query(LearningTopic).filter(
                        LearningTopic.id == conn.source_topic_id
                    ).first()
                    if prereq_topic:
                        tangent = TangentQueue(
                            id=str(uuid.uuid4()),
                            user_id=user_id,
                            parent_topic_id=new_topic.id,
                            tangent_description=f"Prerequisite: {prereq_topic.title}",
                            source_context=f"Auto-queued from deep prerequisite chain (depth {chain_depth})",
                            priority=4,
                            is_prerequisite=True,
                            status="queued"
                        )
                        db.add(tangent)
                db.commit()
                prereq_warning = f"Deep prerequisite chain detected (depth {chain_depth}, {prereq_branches} branches). Excess prerequisites queued as tangent items — focus on the core 2 first."
        except Exception as e:
            logger.debug(f"Prereq chain check failed (non-critical): {e}")

        # Auto-research: dispatch background task to discover and fetch sources
        if topic.auto_research:
            try:
                from app.tasks.learning import auto_research_topic_task
                auto_research_topic_task.delay(user_id, new_topic.id)
                logger.info(f"Dispatched auto-research for new topic: {new_topic.title}")
            except Exception as e:
                logger.warning(f"Failed to dispatch auto-research (non-critical): {e}")

        result = TopicResponse(
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

        # If there's a prerequisite warning, return it alongside the topic
        if prereq_warning:
            return {
                **result.dict(),
                "prerequisite_warning": prereq_warning,
            }
        return result
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


@router.get("/blueprints/{blueprint_id}/sources")
async def list_blueprint_sources(
    blueprint_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """List all sources across all topics in a blueprint (including ancestor topics), with chunk counts."""
    from sqlalchemy import func as sa_func, text as sa_text

    blueprint = db.query(LearningBlueprint).filter(
        LearningBlueprint.id == blueprint_id,
        LearningBlueprint.user_id == user_id
    ).first()
    if not blueprint:
        raise HTTPException(status_code=404, detail="Blueprint not found")

    # Get blueprint's own topic IDs
    topic_ids = set(
        t.id for t in db.query(LearningTopic.id).filter(
            LearningTopic.blueprint_id == blueprint_id
        ).all()
    )

    if not topic_ids:
        return {"sources": []}

    # Walk UP the tree from each topic to collect ancestor topic IDs
    all_topic_ids = set(topic_ids)
    frontier = set(topic_ids)
    for _ in range(10):  # max depth
        if not frontier:
            break
        parent_rows = db.execute(sa_text(
            "SELECT DISTINCT parent_id FROM learning_topic WHERE id = ANY(:ids) AND parent_id IS NOT NULL"
        ), {"ids": list(frontier)}).fetchall()
        new_parents = {r.parent_id for r in parent_rows} - all_topic_ids
        if not new_parents:
            break
        all_topic_ids.update(new_parents)
        frontier = new_parents

    rows = db.query(
        TopicSource,
        LearningTopic.title.label("topic_title"),
        sa_func.count(SourceChunk.id).label("chunk_count"),
    ).join(
        LearningTopic, LearningTopic.id == TopicSource.topic_id
    ).outerjoin(
        SourceChunk, SourceChunk.source_id == TopicSource.id
    ).filter(
        TopicSource.topic_id.in_(list(all_topic_ids)),
        TopicSource.user_id == user_id
    ).group_by(
        TopicSource.id, LearningTopic.title
    ).order_by(
        sa_func.count(SourceChunk.id).desc(),
        TopicSource.created_at.desc()
    ).all()

    sources = []
    for source, topic_title, chunk_count in rows:
        has_chapters = bool(source.toc)
        chapter_count = len(source.toc) if source.toc else 0
        sources.append({
            "id": source.id,
            "topic_id": source.topic_id,
            "topic_title": topic_title,
            "source_type": source.source_type,
            "url": source.url,
            "title": source.title,
            "quality_score": float(source.quality_score or 0.5),
            "fetch_status": source.fetch_status or "pending",
            "chunk_count": chunk_count,
            "has_chapters": has_chapters,
            "chapter_count": chapter_count,
            "created_at": source.created_at.isoformat() if source.created_at else "",
        })

    return {"sources": sources}


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


@router.post("/sources/upload")
async def upload_source(
    request: Request,
    topic_id: str = None,
    title: str = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Upload a file as a learning source (PDF, TXT, MD).
    Processes the file directly without fetching - content goes straight to chunking/embedding.
    """
    from fastapi import UploadFile, File, Form
    from app.services.learning_source_service import learning_source_service

    # Parse multipart form data
    content_type = request.headers.get("content-type", "")

    try:
        form = await request.form()
    except Exception as form_err:
        logger.error(f"Failed to parse form data: {form_err}, content-type={content_type}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse multipart form: {form_err}"
        )

    form_keys = list(form.keys())

    file = form.get("file")
    topic_id = form.get("topic_id") or topic_id
    title = form.get("title") or title

    if not file:
        raise HTTPException(
            status_code=400,
            detail=f"No file provided. Received form fields: {form_keys}. Content-Type: {content_type}"
        )

    if not topic_id:
        raise HTTPException(status_code=400, detail="topic_id is required")

    # Verify topic exists and belongs to user
    topic = db.query(LearningTopic).filter(
        LearningTopic.id == topic_id,
        LearningTopic.user_id == user_id
    ).first()

    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    try:
        # Determine type from extension first, then MIME as fallback.
        filename = file.filename if hasattr(file, 'filename') else "uploaded_file"
        content_type = (getattr(file, "content_type", None) or "").lower()
        file_ext = filename.lower().split('.')[-1] if '.' in filename else ''

        allowed_types = {'pdf', 'txt', 'md', 'markdown'}
        mime_fallback_ext = None
        if content_type.startswith("application/pdf"):
            mime_fallback_ext = "pdf"
        elif content_type.startswith("text/plain"):
            mime_fallback_ext = "txt"
        elif content_type.startswith("text/markdown") or content_type.startswith("text/x-markdown"):
            mime_fallback_ext = "md"

        if file_ext not in allowed_types and mime_fallback_ext:
            file_ext = mime_fallback_ext

        # Validate file type
        if file_ext not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported file type. filename='{filename}', content_type='{content_type}'. "
                    f"Allowed: {', '.join(sorted(allowed_types))}"
                )
            )

        # Read file content
        file_content = await file.read() if hasattr(file, 'read') else file.file.read()

        # Determine source type
        if file_ext == 'pdf':
            source_type = 'pdf'
        else:
            source_type = 'document'

        # Extract content based on type
        content = ""
        meta = {"uploaded": True, "filename": filename}

        if file_ext == 'pdf':
            content, extracted_title, pdf_meta = learning_source_service.extract_text_from_pdf_bytes(file_content)
            if extracted_title and not title:
                title = extracted_title
            meta.update(pdf_meta)
            if pdf_meta.get("error"):
                raise HTTPException(status_code=400, detail=f"PDF processing failed: {pdf_meta.get('error')}")
        else:
            # Text files (txt, md, markdown)
            try:
                content = file_content.decode('utf-8')
            except UnicodeDecodeError:
                content = file_content.decode('latin-1')
            meta["content_type"] = "text/plain" if file_ext == 'txt' else "text/markdown"

        if not content or not content.strip():
            if file_ext == "pdf":
                raise HTTPException(
                    status_code=400,
                    detail="Could not extract text from PDF. If this file is scanned/image-only, OCR is not supported yet."
                )
            raise HTTPException(status_code=400, detail="Could not extract any content from the file")

        # Use filename as title if not provided
        if not title:
            title = filename.rsplit('.', 1)[0] if '.' in filename else filename

        # Store raw PDF bytes in meta so the background task can do chapter-aware chunking
        import base64 as _b64
        if file_ext == 'pdf':
            meta["pdf_b64"] = _b64.b64encode(file_content).decode("ascii")

        # Create source record
        source = TopicSource(
            id=str(uuid.uuid4()),
            topic_id=topic_id,
            user_id=user_id,
            source_type=source_type,
            url=None,
            title=title,
            content_text=content,
            fetch_status="processing",
            meta=meta
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        # Dispatch background processing (chunking + embedding + push notification)
        from app.tasks.learning import process_uploaded_source
        process_uploaded_source.delay(source.id, user_id)

        return {
            "status": "processing",
            "source_id": source.id,
            "topic_id": topic_id,
            "title": source.title,
            "message": "File uploaded — processing in the background. You'll get a notification when it's ready.",
        }

    except HTTPException as e:
        logger.warning(
            f"Upload rejected for topic {topic_id} (user={user_id}): {getattr(e, 'detail', str(e))}"
        )
        raise
    except Exception as e:
        logger.error(f"Error uploading source: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sources/upload-b64")
async def upload_source_b64(
    request: Request,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Upload a file as base64 JSON — avoids multipart/FormData issues on mobile.
    Body: { topic_id, filename, content_type, data_b64, title? }
    """
    import base64 as _b64
    from app.services.learning_source_service import learning_source_service

    body = await request.json()
    topic_id = body.get("topic_id")
    filename = body.get("filename", "upload")
    content_type_hint = (body.get("content_type") or "").lower()
    data_b64 = body.get("data_b64", "")
    title = body.get("title")

    if not topic_id:
        raise HTTPException(status_code=400, detail="topic_id is required")
    if not data_b64:
        raise HTTPException(status_code=400, detail="data_b64 is required")

    # Verify topic
    topic = db.query(LearningTopic).filter(
        LearningTopic.id == topic_id,
        LearningTopic.user_id == user_id
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    try:
        file_content = _b64.b64decode(data_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 data")

    # Determine file type
    file_ext = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
    allowed_types = {'pdf', 'txt', 'md', 'markdown'}
    if file_ext not in allowed_types:
        if 'pdf' in content_type_hint:
            file_ext = 'pdf'
        elif 'markdown' in content_type_hint:
            file_ext = 'md'
        elif 'text' in content_type_hint:
            file_ext = 'txt'
    if file_ext not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {filename}")

    try:
        source_type = 'pdf' if file_ext == 'pdf' else 'document'
        meta = {"uploaded": True, "filename": filename}

        if file_ext == 'pdf':
            content, extracted_title, pdf_meta = learning_source_service.extract_text_from_pdf_bytes(file_content)
            if extracted_title and not title:
                title = extracted_title
            meta.update(pdf_meta)
            if pdf_meta.get("error"):
                raise HTTPException(status_code=400, detail=f"PDF processing failed: {pdf_meta['error']}")
            meta["pdf_b64"] = data_b64  # Keep for background chunking
        else:
            try:
                content = file_content.decode('utf-8')
            except UnicodeDecodeError:
                content = file_content.decode('latin-1')

        if not content or not content.strip():
            raise HTTPException(status_code=400, detail="Could not extract any content from the file")

        if not title:
            title = filename.rsplit('.', 1)[0] if '.' in filename else filename

        source = TopicSource(
            id=str(uuid.uuid4()),
            topic_id=topic_id,
            user_id=user_id,
            source_type=source_type,
            url=None,
            title=title,
            content_text=content,
            fetch_status="processing",
            meta=meta
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        from app.tasks.learning import process_uploaded_source
        process_uploaded_source.delay(source.id, user_id)

        return {
            "status": "processing",
            "source_id": source.id,
            "topic_id": topic_id,
            "title": source.title,
            "message": "File uploaded — processing in the background. You'll get a notification when it's ready.",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading source (b64): {e}")
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
        from app.services.learning_session_summarizer import learning_session_summarizer
        from app.services.learning_path_service import learning_path_service
        from datetime import timedelta
        import logging

        logger = logging.getLogger("app.main_simple")
        logger.info(f"📚 Learning chat: user_id={user_id}, topic_id={request.topic_id}")

        now = local_now()

        # Get topic context if topic_id provided
        topic_context = ""
        scratchpad_content = ""
        rag_context = ""
        recent_sources = []
        review_queue_status = None
        learning_recommendations = []
        session_state = None
        scratchpad = None
        topic_title = ""

        if request.topic_id:
            topic = db.query(LearningTopic).filter(
                LearningTopic.id == request.topic_id,
                LearningTopic.user_id == user_id
            ).first()

            if topic:
                topic_title = topic.title
                topic_context = f"**Current Topic:** {topic.title}"
                if topic.description:
                    topic_context += f"\n{topic.description}"

                # Get all sources for the topic
                sources_query = db.query(TopicSource).filter(
                    TopicSource.topic_id == request.topic_id,
                    TopicSource.user_id == user_id
                ).all()

                # Build available sources list
                if sources_query:
                    topic_context += "\n\n**Available Sources:**"
                    for s in sources_query[:5]:
                        topic_context += f"\n- {s.title or s.url} ({s.source_type})"

                # Filter to recently added sources (last 7 days)
                seven_days_ago = now - timedelta(days=7)
                for src in sources_query:
                    if src.created_at and src.created_at >= seven_days_ago:
                        delta = now - src.created_at
                        if delta.days == 0:
                            added_ago = "today"
                        elif delta.days == 1:
                            added_ago = "yesterday"
                        else:
                            added_ago = f"{delta.days} days ago"
                        recent_sources.append({
                            "title": src.title or src.url,
                            "added_ago": added_ago
                        })

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

            # Get scratchpad (includes session_state and last_interaction_at)
            scratchpad = db.query(TopicScratchpad).filter(
                TopicScratchpad.topic_id == request.topic_id,
                TopicScratchpad.user_id == user_id
            ).first()

            if scratchpad:
                scratchpad_content = scratchpad.content or ""

                # Check if we should summarize previous session
                should_summarize = learning_session_summarizer.should_summarize(
                    last_interaction_at=scratchpad.last_interaction_at,
                    is_topic_change=False  # TODO: track topic changes
                )

                if should_summarize and scratchpad.last_interaction_at:
                    # Fetch recent conversation history for summarization
                    history_for_summary = db.execute(text("""
                        SELECT role, content
                        FROM episode
                        WHERE user_id = :user_id
                        AND source = 'learning_chat'
                        AND meta->>'topic_id' = :topic_id
                        ORDER BY created_at DESC
                        LIMIT 20
                    """), {"user_id": user_id, "topic_id": request.topic_id})

                    summary_messages = [
                        {"role": row.role, "content": row.content}
                        for row in reversed(list(history_for_summary.fetchall()))
                    ]

                    if summary_messages:
                        new_session_state = await learning_session_summarizer.summarize_session(
                            conversation_history=summary_messages,
                            topic_title=topic_title
                        )
                        # Store new session state
                        scratchpad.session_state = new_session_state
                        db.commit()
                        logger.info(f"📝 Session summarized: {new_session_state.get('summary', '')[:50]}...")

                # Use existing session state for context
                session_state = scratchpad.session_state if scratchpad.session_state else None

        # Get review queue status
        review_count = db.query(LearningProgress).filter(
            LearningProgress.user_id == user_id,
            LearningProgress.next_review_at <= now
        ).count()
        if review_count > 0:
            review_queue_status = {"due_count": review_count}

        # Get learning path recommendations
        try:
            path_result = await learning_path_service.generate_learning_path(
                user_id=user_id,
                db=db,
                focus_topic_id=request.topic_id,
                max_steps=3
            )
            learning_recommendations = path_result.get("recommendations", [])[:3]
        except Exception as e:
            logger.warning(f"Failed to get learning recommendations: {e}")

        # Extract cognitive state from session state for prompt injection
        cognitive_state = None
        if session_state and session_state.get("cognitive_state"):
            cognitive_state = session_state["cognitive_state"]

        # Query known domains for analogy context
        known_domains_list = None
        try:
            from app.models.known_domain import KnownDomain
            domains = db.query(KnownDomain).filter(
                KnownDomain.user_id == user_id
            ).all()
            if domains:
                known_domains_list = [d.to_dict() for d in domains]
        except Exception as e:
            logger.debug(f"Known domains query failed: {e}")

        # Query active anchors for the current topic
        active_anchors_list = None
        if request.topic_id:
            try:
                from app.services.anchor_service import anchor_service
                active_anchors_list = await anchor_service.get_active_anchors(
                    request.topic_id, user_id, db
                )
            except Exception as e:
                logger.debug(f"Anchors query failed: {e}")

        # Query tangent queue for the current topic
        tangent_queue_list = None
        if request.topic_id:
            try:
                from app.models.tangent_queue import TangentQueue
                tangents = db.query(TangentQueue).filter(
                    TangentQueue.user_id == user_id,
                    TangentQueue.parent_topic_id == request.topic_id,
                    TangentQueue.status == "queued"
                ).order_by(TangentQueue.priority.desc()).limit(5).all()
                if tangents:
                    tangent_queue_list = [t.to_dict() for t in tangents]
            except Exception as e:
                logger.debug(f"Tangent queue query failed: {e}")

        # Load persisted curriculum for chat context
        curriculum_steps = None
        if request.topic_id and scratchpad and scratchpad.curriculum:
            curriculum_steps = scratchpad.curriculum

        # Build context prompt with all injections
        full_topic_context = topic_context + rag_context
        context_prompt = get_learning_system_prompt(
            topic_context=full_topic_context,
            scratchpad_content=scratchpad_content,
            recent_sources=recent_sources if recent_sources else None,
            review_queue_status=review_queue_status,
            learning_recommendations=learning_recommendations if learning_recommendations else None,
            session_state=session_state,
            cognitive_state=cognitive_state,
            known_domains=known_domains_list,
            active_anchors=active_anchors_list if active_anchors_list else None,
            tangent_queue=tangent_queue_list,
            curriculum_steps=curriculum_steps
        )

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
            "created_at": now,
            "meta": json.dumps({"topic_id": request.topic_id} if request.topic_id else {})
        })

        # Update last_interaction_at on scratchpad for session tracking
        if scratchpad:
            scratchpad.last_interaction_at = now
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
                        "created_at": local_now(),
                        "meta": json.dumps({"topic_id": request.topic_id} if request.topic_id else {})
                    })
                    db.commit()

                    # Trigger PKG sync every 5th message in this learning session
                    if request.topic_id:
                        try:
                            msg_count_result = db.execute(text("""
                                SELECT COUNT(*) as cnt FROM episode
                                WHERE user_id = :user_id AND source = 'learning_chat'
                                  AND meta->>'topic_id' = :topic_id
                                  AND created_at >= NOW() - INTERVAL '1 hour'
                            """), {"user_id": user_id, "topic_id": request.topic_id})
                            msg_count = msg_count_result.fetchone()
                            if msg_count and (msg_count.cnt or 0) % 5 == 0:
                                from app.tasks.autonomy import learning_pkg_sync
                                learning_pkg_sync.delay(user_id, request.topic_id)
                                logger.info(f"📚 Triggered learning PKG sync for topic {request.topic_id}")
                        except Exception as pkg_err:
                            logger.debug(f"Learning PKG sync trigger failed: {pkg_err}")

                    await event_queue.put({
                        "type": "final_response",
                        "data": {
                            "content": response_content,
                            "timestamp": local_now().isoformat()
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
                        yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': local_now().isoformat()})}\n\n"
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


class FindMoreSourcesRequest(BaseModel):
    """Optional hints for finding more sources."""
    focus: Optional[str] = None  # e.g. "advanced patterns", "practical examples"
    count: Optional[int] = 8  # how many new sources to find
    fetch_inline: Optional[bool] = False  # fetch immediately vs background


@router.post("/topics/{topic_id}/find-more-sources")
async def find_more_sources(
    topic_id: str,
    request: FindMoreSourcesRequest = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Find additional sources for a topic that already has some.

    Uses LLM to generate smarter queries based on existing sources and gaps,
    skips URLs already in the topic, and optionally accepts a focus hint.
    Can fetch inline or dispatch to background.
    """
    if request is None:
        request = FindMoreSourcesRequest()

    try:
        from app.services.search_service import search_service
        from app.services.learning_source_service import learning_source_service

        topic = db.query(LearningTopic).filter(
            LearningTopic.id == topic_id,
            LearningTopic.user_id == user_id
        ).first()

        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")

        # Gather existing source URLs so we skip duplicates
        existing_sources = db.query(TopicSource).filter(
            TopicSource.topic_id == topic_id,
            TopicSource.user_id == user_id
        ).all()
        existing_urls = {s.url for s in existing_sources if s.url}
        existing_titles = [s.title for s in existing_sources if s.title]

        # Build smarter queries using existing coverage gaps
        base_queries = []
        focus = request.focus or ""

        if focus:
            base_queries.append(f"{topic.title} {focus}")
            base_queries.append(f"{topic.title} {focus} examples")

        # Vary the query angles to find different content
        angles = [
            "deep dive", "advanced", "practical examples",
            "best practices", "common mistakes", "cheat sheet",
            "interview questions", "real world", "comparison",
        ]
        # Pick angles that aren't already covered by existing source titles
        title_text = " ".join(existing_titles).lower()
        for angle in angles:
            if angle not in title_text:
                base_queries.append(f"{topic.title} {angle}")
            if len(base_queries) >= 6:
                break

        # Fallback if we have very few queries
        if len(base_queries) < 3:
            base_queries.extend([
                f"{topic.title} documentation",
                f"{topic.title} in depth",
                f"{topic.title} from scratch",
            ])

        # Search and collect new sources
        max_new = request.count or 8
        added_sources = []

        for query in base_queries:
            if len(added_sources) >= max_new:
                break

            try:
                search_result = await search_service.web_search(
                    query=query, max_results=5
                )
                for r in search_result.get("results", []):
                    url = r.get("url")
                    if not url or url in existing_urls:
                        continue

                    title = r.get("title", url[:60])
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
                        "title": title,
                    })

                    if len(added_sources) >= max_new:
                        break
            except Exception as e:
                logger.warning(f"Search failed for '{query}': {e}")
                continue

        db.commit()

        if not added_sources:
            return {
                "topic_id": topic_id,
                "topic_title": topic.title,
                "sources_added": 0,
                "sources_fetched": 0,
                "existing_count": len(existing_sources),
                "message": f"No new sources found for '{topic.title}'. Try providing a focus hint."
            }

        # Fetch sources
        fetched_count = 0
        if request.fetch_inline:
            # Fetch top 5 inline
            for src_info in added_sources[:5]:
                source_obj = db.query(TopicSource).filter(
                    TopicSource.id == src_info["source_id"]
                ).first()
                if source_obj:
                    try:
                        result = await learning_source_service.fetch_and_process_source(source_obj, db)
                        if result.get("status") == "success":
                            fetched_count += 1
                            src_info["fetched"] = True
                            src_info["chunk_count"] = result.get("chunk_count", 0)
                    except Exception as e:
                        logger.warning(f"Inline fetch failed: {e}")
        else:
            # Dispatch background fetch for all sources
            try:
                from app.tasks.learning import fetch_pending_sources
                fetch_pending_sources.delay(batch_size=len(added_sources))
                logger.info(f"Dispatched background fetch for {len(added_sources)} new sources")
            except Exception as e:
                logger.warning(f"Background fetch dispatch failed: {e}")

        return {
            "topic_id": topic_id,
            "topic_title": topic.title,
            "sources_added": len(added_sources),
            "sources_fetched": fetched_count,
            "existing_count": len(existing_sources),
            "sources": added_sources,
            "message": (
                f"Found {len(added_sources)} new sources for '{topic.title}'. "
                + (f"{fetched_count} fetched inline." if request.fetch_inline
                   else "Fetching in background.")
            )
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Find more sources failed: {e}")
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
        report.completed_at = local_now()
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

        # Dispatch Celery task for immediate processing
        try:
            from app.tasks.learning import deep_research_worker
            deep_research_worker.delay(job.id)
            logger.info(f"Dispatched deep research task for job {job.id}")
        except Exception as e:
            logger.warning(f"Failed to dispatch deep research task (poller will pick it up): {e}")

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
        now = local_now()

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
            started_at=local_now()
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

        session.ended_at = local_now()
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
# CURRICULUM ENDPOINTS
# ============================================================================


class CurriculumStepUpdate(BaseModel):
    status: str  # "completed" or "active"


@router.get("/curriculum/{topic_id}")
async def get_curriculum(
    topic_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get the persisted curriculum for a topic."""
    from app.services.learning_path_service import learning_path_service

    curriculum = await learning_path_service.get_persisted_curriculum(topic_id, user_id, db)
    if not curriculum:
        raise HTTPException(status_code=404, detail="No curriculum found for this topic")
    return curriculum


@router.patch("/curriculum/{topic_id}/steps/{step_index}")
async def update_curriculum_step(
    topic_id: str,
    step_index: int,
    update: CurriculumStepUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Complete or activate a curriculum step. Completing a step auto-advances the next one."""
    from sqlalchemy.orm.attributes import flag_modified

    scratchpad = db.query(TopicScratchpad).filter(
        TopicScratchpad.topic_id == topic_id,
        TopicScratchpad.user_id == user_id
    ).first()

    if not scratchpad or not scratchpad.curriculum:
        raise HTTPException(status_code=404, detail="No curriculum found")

    curriculum = scratchpad.curriculum
    steps = curriculum.get("steps", [])

    if step_index < 0 or step_index >= len(steps):
        raise HTTPException(status_code=400, detail="Invalid step index")

    if update.status == "completed":
        steps[step_index]["status"] = "completed"
        steps[step_index]["completed_at"] = local_now().isoformat()

        # Auto-advance: make the next pending step active
        for s in steps[step_index + 1:]:
            if s["status"] == "pending":
                s["status"] = "active"
                break
    elif update.status == "active":
        steps[step_index]["status"] = "active"
    else:
        raise HTTPException(status_code=400, detail="Status must be 'completed' or 'active'")

    scratchpad.curriculum = curriculum
    flag_modified(scratchpad, "curriculum")
    db.commit()

    return curriculum


@router.post("/curriculum/{topic_id}/regenerate")
async def regenerate_curriculum(
    topic_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Force-regenerate the curriculum for a topic (replaces existing)."""
    from app.services.learning_path_service import learning_path_service

    result = await learning_path_service.generate_learning_path(
        user_id=user_id,
        db=db,
        focus_topic_id=topic_id,
        max_steps=10,
        force_regenerate=True
    )
    return result


# ============================================================================
# BLUEPRINT IMPORT ENDPOINTS
# ============================================================================


@router.post("/blueprints/parse")
async def parse_blueprint(
    request: BlueprintParseRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Parse and persist an imported learning blueprint."""
    try:
        from app.services.learning_blueprint_service import learning_blueprint_service

        parsed, confidence = await learning_blueprint_service.parse_blueprint_text(
            text=request.text,
            source_format=request.source_format or "markdown",
            parse_mode=request.parse_mode or "balanced",
            pace_mode=request.pace_mode or "self_directed",
            title_override=request.title_override,
        )

        blueprint_info = parsed.get("blueprint", {})
        blueprint = LearningBlueprint(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=(blueprint_info.get("title") or request.title_override or "Imported Blueprint")[:255],
            subtitle=(blueprint_info.get("subtitle") or None),
            description=(blueprint_info.get("description") or None),
            source_format=blueprint_info.get("source_format") or request.source_format or "markdown",
            pace_mode=blueprint_info.get("pace_mode") or request.pace_mode or "self_directed",
            status="parsed",
            import_confidence=confidence,
            raw_text=request.text,
            parsed_json=parsed,
            meta={"parse_mode": request.parse_mode or "balanced"},
        )
        db.add(blueprint)
        db.commit()
        db.refresh(blueprint)

        return {
            "blueprint_id": blueprint.id,
            "status": blueprint.status,
            "import_confidence": blueprint.import_confidence,
            "preview": blueprint.parsed_json,
            "warnings": (parsed.get("metadata") or {}).get("warnings", []),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Blueprint parse failed: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blueprints")
async def list_blueprints(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """List previously imported learning blueprints."""
    try:
        rows = db.query(LearningBlueprint).filter(
            LearningBlueprint.user_id == user_id
        ).order_by(LearningBlueprint.created_at.desc()).all()

        return {
            "blueprints": [
                {
                    "id": bp.id,
                    "title": bp.title,
                    "subtitle": bp.subtitle,
                    "description": bp.description,
                    "status": bp.status,
                    "import_confidence": bp.import_confidence,
                    "source_format": bp.source_format,
                    "pace_mode": bp.pace_mode,
                    "materialized_at": bp.materialized_at.isoformat() if bp.materialized_at else None,
                    "created_at": bp.created_at.isoformat() if bp.created_at else None,
                    "updated_at": bp.updated_at.isoformat() if bp.updated_at else None,
                }
                for bp in rows
            ],
            "count": len(rows),
        }
    except Exception as e:
        logger.error(f"Failed to list blueprints: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blueprints/{blueprint_id}")
async def get_blueprint(
    blueprint_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get a full blueprint payload including parsed structure."""
    try:
        blueprint = db.query(LearningBlueprint).filter(
            LearningBlueprint.id == blueprint_id,
            LearningBlueprint.user_id == user_id
        ).first()
        if not blueprint:
            raise HTTPException(status_code=404, detail="Blueprint not found")

        return blueprint.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get blueprint {blueprint_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/blueprints/{blueprint_id}/materialize")
async def materialize_blueprint(
    blueprint_id: str,
    request: BlueprintMaterializeRequest = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Materialize a blueprint into topics, sources, connections, and curricula."""
    if request is None:
        request = BlueprintMaterializeRequest()

    try:
        from app.services.learning_blueprint_service import learning_blueprint_service

        blueprint = db.query(LearningBlueprint).filter(
            LearningBlueprint.id == blueprint_id,
            LearningBlueprint.user_id == user_id
        ).first()
        if not blueprint:
            raise HTTPException(status_code=404, detail="Blueprint not found")

        result = learning_blueprint_service.materialize_blueprint(
            blueprint=blueprint,
            user_id=user_id,
            db=db,
            mode=request.mode or "adaptive",
            create_sources=request.create_sources if request.create_sources is not None else True,
            create_connections=request.create_connections if request.create_connections is not None else True,
            create_curriculum=request.create_curriculum if request.create_curriculum is not None else True,
            seed_reviews=request.seed_reviews if request.seed_reviews is not None else True,
            replace_existing=request.replace_existing if request.replace_existing is not None else False,
            parent_topic_id=request.parent_topic_id,
        )

        # Dispatch background task to discover free versions of resources
        if result.get("status") == "materialized":
            try:
                from app.tasks.learning import discover_blueprint_resources
                discover_blueprint_resources.delay(blueprint_id, user_id)
                logger.info(f"Dispatched resource discovery for blueprint {blueprint_id}")
            except Exception as e:
                logger.warning(f"Failed to dispatch resource discovery: {e}")

        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to materialize blueprint {blueprint_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/blueprints/{blueprint_id}/discover-resources")
async def discover_blueprint_resources_endpoint(
    blueprint_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Trigger background search for free versions of blueprint resources."""
    blueprint = db.query(LearningBlueprint).filter(
        LearningBlueprint.id == blueprint_id,
        LearningBlueprint.user_id == user_id
    ).first()
    if not blueprint:
        raise HTTPException(status_code=404, detail="Blueprint not found")

    from app.tasks.learning import discover_blueprint_resources
    result = discover_blueprint_resources.delay(blueprint_id, user_id)
    return {"status": "dispatched", "task_id": result.id, "blueprint_id": blueprint_id}


@router.get("/blueprints/{blueprint_id}/progress")
async def get_blueprint_progress(
    blueprint_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get learning progress across modules in a blueprint."""
    try:
        from app.services.learning_blueprint_service import learning_blueprint_service

        blueprint = db.query(LearningBlueprint).filter(
            LearningBlueprint.id == blueprint_id,
            LearningBlueprint.user_id == user_id
        ).first()
        if not blueprint:
            raise HTTPException(status_code=404, detail="Blueprint not found")

        return learning_blueprint_service.compute_blueprint_progress(
            blueprint=blueprint,
            user_id=user_id,
            db=db
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to compute blueprint progress {blueprint_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/blueprints/{blueprint_id}/guides/generate")
async def generate_blueprint_guides(
    blueprint_id: str,
    request: BlueprintGuideGenerateRequest = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Queue study-guide generation for all modules in a blueprint."""
    if request is None:
        request = BlueprintGuideGenerateRequest()

    try:
        blueprint = db.query(LearningBlueprint).filter(
            LearningBlueprint.id == blueprint_id,
            LearningBlueprint.user_id == user_id
        ).first()
        if not blueprint:
            raise HTTPException(status_code=404, detail="Blueprint not found")

        default_guide_model = getattr(settings, "bg_llm_primary_model", None) or "Qwen3.5-35B-A3B"
        model = (request.model or default_guide_model).strip() or default_guide_model
        num_ctx = int(request.num_ctx or 16384)
        num_ctx = max(2048, min(num_ctx, 131072))

        job = LearningGuideJob(
            id=str(uuid.uuid4()),
            user_id=user_id,
            blueprint_id=blueprint_id,
            status="queued",
            progress=0,
            current_step="Queued",
            model=model,
            meta={
                "force_regenerate": bool(request.force_regenerate),
                "module_limit": request.module_limit,
                "requested_model": model,
                "num_ctx": num_ctx,
            },
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        try:
            from app.tasks.learning import generate_blueprint_guides_worker
            generate_blueprint_guides_worker.delay(job.id)
        except Exception as dispatch_error:
            logger.warning(f"Failed to dispatch guide worker for job {job.id}: {dispatch_error}")

        return {
            "status": "queued",
            "job_id": job.id,
            "blueprint_id": blueprint_id,
            "model": model,
            "num_ctx": num_ctx,
            "force_regenerate": bool(request.force_regenerate),
            "module_limit": request.module_limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to queue blueprint guides for {blueprint_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blueprints/{blueprint_id}/guides/jobs/{job_id}")
async def get_blueprint_guide_job(
    blueprint_id: str,
    job_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get status/progress for a blueprint guide generation job."""
    try:
        job = db.query(LearningGuideJob).filter(
            LearningGuideJob.id == job_id,
            LearningGuideJob.blueprint_id == blueprint_id,
            LearningGuideJob.user_id == user_id,
        ).first()
        if not job:
            raise HTTPException(status_code=404, detail="Guide job not found")
        return job.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to load guide job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/blueprints/{blueprint_id}/guides/jobs/{job_id}/cancel")
async def cancel_blueprint_guide_job(
    blueprint_id: str,
    job_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Cancel a queued/running guide generation job."""
    try:
        job = db.query(LearningGuideJob).filter(
            LearningGuideJob.id == job_id,
            LearningGuideJob.blueprint_id == blueprint_id,
            LearningGuideJob.user_id == user_id,
        ).first()
        if not job:
            raise HTTPException(status_code=404, detail="Guide job not found")

        if job.status in {"completed", "failed", "cancelled"}:
            return {
                "status": "noop",
                "message": f"Job already {job.status}",
                "job": job.to_dict(),
            }

        now = local_now()
        if job.status == "queued":
            job.status = "cancelled"
            job.current_step = "Cancelled before start"
            job.completed_at = now
        else:
            # running jobs stop cooperatively at safe boundaries,
            # but expose terminal cancelled state to clients immediately.
            job.status = "cancelled"
            job.current_step = "Cancelled (stopping worker at safe boundary)"
            job.completed_at = now

        db.commit()
        db.refresh(job)
        return {
            "status": "ok",
            "message": "Cancellation requested",
            "job": job.to_dict(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel guide job {job_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blueprints/{blueprint_id}/guides/jobs")
async def list_blueprint_guide_jobs(
    blueprint_id: str,
    limit: int = 20,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """List recent guide generation jobs for a blueprint."""
    try:
        rows = db.query(LearningGuideJob).filter(
            LearningGuideJob.blueprint_id == blueprint_id,
            LearningGuideJob.user_id == user_id,
        ).order_by(LearningGuideJob.created_at.desc()).limit(max(1, min(limit, 100))).all()

        return {
            "blueprint_id": blueprint_id,
            "jobs": [row.to_dict() for row in rows],
            "count": len(rows),
        }
    except Exception as e:
        logger.error(f"Failed to list guide jobs for blueprint {blueprint_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blueprints/{blueprint_id}/guides")
async def list_blueprint_guides(
    blueprint_id: str,
    artifact_type: Optional[str] = None,
    limit: int = 200,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """List generated study guides (Pareto + deep) for a blueprint."""
    try:
        blueprint = db.query(LearningBlueprint).filter(
            LearningBlueprint.id == blueprint_id,
            LearningBlueprint.user_id == user_id
        ).first()
        if not blueprint:
            raise HTTPException(status_code=404, detail="Blueprint not found")

        module_topics = db.query(LearningTopic).filter(
            LearningTopic.user_id == user_id,
            LearningTopic.blueprint_id == blueprint_id
        ).all()
        module_topic_ids = {
            topic.id
            for topic in module_topics
            if (topic.meta or {}).get("blueprint_node_type") == "module"
        }

        query = db.query(LearningArtifact).filter(
            LearningArtifact.user_id == user_id
        )
        if artifact_type:
            query = query.filter(LearningArtifact.artifact_type == artifact_type)
        else:
            query = query.filter(
                LearningArtifact.artifact_type.in_(["study_guide_pareto", "study_guide_deep"])
            )

        rows = query.order_by(LearningArtifact.updated_at.desc()).limit(max(1, min(limit, 500))).all()

        filtered = []
        for artifact in rows:
            content = artifact.content or {}
            content_blueprint = str(content.get("blueprint_id") or "")
            if artifact.topic_id in module_topic_ids or content_blueprint == blueprint_id:
                filtered.append({
                    "id": artifact.id,
                    "topic_id": artifact.topic_id,
                    "artifact_type": artifact.artifact_type,
                    "title": artifact.title,
                    "version": artifact.version,
                    "content": content,
                    "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
                    "updated_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
                })

        return {
            "blueprint_id": blueprint_id,
            "guides": filtered,
            "count": len(filtered),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list blueprint guides for {blueprint_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# LESSON GENERATION ENDPOINTS
# ============================================================================


class BlueprintLessonGenerateRequest(BaseModel):
    force_regenerate: Optional[bool] = False
    module_limit: Optional[int] = None
    model: Optional[str] = None
    num_ctx: Optional[int] = 49152


@router.post("/blueprints/{blueprint_id}/lessons/generate")
async def generate_blueprint_lessons(
    blueprint_id: str,
    request: BlueprintLessonGenerateRequest = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Queue lesson generation for all modules in a blueprint."""
    if request is None:
        request = BlueprintLessonGenerateRequest()

    try:
        blueprint = db.query(LearningBlueprint).filter(
            LearningBlueprint.id == blueprint_id,
            LearningBlueprint.user_id == user_id
        ).first()
        if not blueprint:
            raise HTTPException(status_code=404, detail="Blueprint not found")

        default_lesson_model = getattr(settings, "bg_llm_primary_model", None) or "qwen3.8-27b"
        model = (request.model or default_lesson_model).strip() or default_lesson_model
        num_ctx = int(request.num_ctx or 49152)
        # Keep lesson generation under model-stable context limits.
        num_ctx = max(2048, min(num_ctx, 49152))

        job = LearningGuideJob(
            id=str(uuid.uuid4()),
            user_id=user_id,
            blueprint_id=blueprint_id,
            status="queued",
            progress=0,
            current_step="Queued",
            model=model,
            job_type="lesson",
            meta={
                "force_regenerate": bool(request.force_regenerate),
                "module_limit": request.module_limit,
                "requested_model": model,
                "num_ctx": num_ctx,
            },
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        try:
            from app.tasks.learning import generate_blueprint_lessons_worker
            generate_blueprint_lessons_worker.delay(job.id)
        except Exception as dispatch_error:
            logger.warning(f"Failed to dispatch lesson worker for job {job.id}: {dispatch_error}")

        return {
            "status": "queued",
            "job_id": job.id,
            "blueprint_id": blueprint_id,
            "model": model,
            "num_ctx": num_ctx,
            "force_regenerate": bool(request.force_regenerate),
            "module_limit": request.module_limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to queue blueprint lessons for {blueprint_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blueprints/{blueprint_id}/lessons")
async def list_blueprint_lessons(
    blueprint_id: str,
    limit: int = 200,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """List generated lessons for a blueprint."""
    try:
        blueprint = db.query(LearningBlueprint).filter(
            LearningBlueprint.id == blueprint_id,
            LearningBlueprint.user_id == user_id
        ).first()
        if not blueprint:
            raise HTTPException(status_code=404, detail="Blueprint not found")

        module_topics = db.query(LearningTopic).filter(
            LearningTopic.user_id == user_id,
            LearningTopic.blueprint_id == blueprint_id
        ).all()
        module_topic_ids = {
            topic.id
            for topic in module_topics
            if (topic.meta or {}).get("blueprint_node_type") == "module"
        }

        rows = db.query(LearningArtifact).filter(
            LearningArtifact.user_id == user_id,
            LearningArtifact.artifact_type == "lesson",
        ).order_by(LearningArtifact.updated_at.desc()).limit(max(1, min(limit, 500))).all()

        filtered = []
        for artifact in rows:
            content = artifact.content or {}
            content_blueprint = str(content.get("blueprint_id") or "")
            if artifact.topic_id in module_topic_ids or content_blueprint == blueprint_id:
                filtered.append({
                    "id": artifact.id,
                    "topic_id": artifact.topic_id,
                    "artifact_type": artifact.artifact_type,
                    "title": artifact.title,
                    "version": artifact.version,
                    "content": content,
                    "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
                    "updated_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
                })

        return {
            "blueprint_id": blueprint_id,
            "lessons": filtered,
            "count": len(filtered),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list blueprint lessons for {blueprint_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blueprints/{blueprint_id}/lessons/jobs")
async def list_blueprint_lesson_jobs(
    blueprint_id: str,
    limit: int = 20,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """List recent lesson generation jobs for a blueprint."""
    try:
        rows = db.query(LearningGuideJob).filter(
            LearningGuideJob.blueprint_id == blueprint_id,
            LearningGuideJob.user_id == user_id,
            LearningGuideJob.job_type == "lesson",
        ).order_by(LearningGuideJob.created_at.desc()).limit(max(1, min(limit, 100))).all()

        return {
            "blueprint_id": blueprint_id,
            "jobs": [row.to_dict() for row in rows],
            "count": len(rows),
        }
    except Exception as e:
        logger.error(f"Failed to list lesson jobs for blueprint {blueprint_id}: {e}")
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


# ============================================================================
# TANGENT QUEUE ENDPOINTS
# ============================================================================

@router.get("/tangents/{topic_id}")
async def list_tangents(
    topic_id: str,
    status: Optional[str] = "queued",
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """List tangents for a topic"""
    try:
        from app.models.tangent_queue import TangentQueue

        query = db.query(TangentQueue).filter(
            TangentQueue.user_id == user_id,
            TangentQueue.parent_topic_id == topic_id
        )
        if status:
            query = query.filter(TangentQueue.status == status)

        tangents = query.order_by(TangentQueue.priority.desc(), TangentQueue.created_at.desc()).all()
        return {"tangents": [t.to_dict() for t in tangents], "total": len(tangents)}
    except Exception as e:
        logger.error(f"Error listing tangents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class TangentUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[int] = None


@router.put("/tangents/{tangent_id}")
async def update_tangent(
    tangent_id: str,
    update: TangentUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Update a tangent's status or priority"""
    try:
        from app.models.tangent_queue import TangentQueue

        tangent = db.query(TangentQueue).filter(
            TangentQueue.id == tangent_id,
            TangentQueue.user_id == user_id
        ).first()
        if not tangent:
            raise HTTPException(status_code=404, detail="Tangent not found")

        if update.status:
            tangent.status = update.status
        if update.priority is not None:
            tangent.priority = min(max(update.priority, 1), 5)

        db.commit()
        return tangent.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating tangent: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tangents/{tangent_id}/promote")
async def promote_tangent(
    tangent_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Promote a tangent to a full learning topic"""
    try:
        from app.models.tangent_queue import TangentQueue

        tangent = db.query(TangentQueue).filter(
            TangentQueue.id == tangent_id,
            TangentQueue.user_id == user_id
        ).first()
        if not tangent:
            raise HTTPException(status_code=404, detail="Tangent not found")

        # Create new topic from tangent
        new_topic = LearningTopic(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=tangent.tangent_description[:255],
            description=f"Promoted from tangent while studying parent topic. Context: {tangent.source_context or 'N/A'}",
            parent_id=tangent.parent_topic_id,
            priority=tangent.priority + 2,  # Slightly boosted
            status="active"
        )
        db.add(new_topic)

        # Update tangent status
        tangent.status = "promoted_to_topic"
        tangent.promoted_topic_id = new_topic.id

        db.commit()

        # Optionally trigger auto-research
        try:
            from app.tasks.learning import auto_research_topic_task
            auto_research_topic_task.delay(user_id, new_topic.id)
        except Exception:
            pass

        return {
            "status": "promoted",
            "tangent_id": tangent_id,
            "new_topic_id": new_topic.id,
            "new_topic_title": new_topic.title,
            "message": f"Tangent promoted to topic: '{new_topic.title}'"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error promoting tangent: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ANCHOR POINT ENDPOINTS
# ============================================================================

@router.get("/topics/{topic_id}/anchors")
async def get_topic_anchors(
    topic_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """List anchor points for a topic"""
    try:
        from app.services.anchor_service import anchor_service
        anchors = await anchor_service.get_active_anchors(topic_id, user_id, db)
        return {"anchors": anchors, "count": len(anchors)}
    except Exception as e:
        logger.error(f"Error getting anchors: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class AnchorValidation(BaseModel):
    is_valid: bool


@router.put("/anchors/{anchor_id}/validate")
async def validate_anchor(
    anchor_id: str,
    validation: AnchorValidation,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Validate or reject an anchor point"""
    try:
        from app.services.anchor_service import anchor_service
        result = await anchor_service.validate_anchor(anchor_id, user_id, db, validation.is_valid)
        if result is None:
            raise HTTPException(status_code=404, detail="Anchor not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating anchor: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# REVIEW SYSTEM ENDPOINTS
# ============================================================================

class ReviewRequest(BaseModel):
    preferred_mode: Optional[str] = None  # analogy_check, explain_back, build_challenge, connection_map, gap_detection


class ReviewSubmit(BaseModel):
    review_mode: str
    response: str
    concept: str
    quality: Optional[int] = None  # 0-5 SM-2 quality


@router.post("/topics/{topic_id}/review")
async def generate_review(
    topic_id: str,
    request: ReviewRequest = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Generate a review using one of the cognitive review modes"""
    if request is None:
        request = ReviewRequest()
    try:
        from app.services.quiz_service import quiz_service
        result = await quiz_service.generate_review(
            topic_id=topic_id,
            user_id=user_id,
            db=db,
            preferred_mode=request.preferred_mode
        )
        return result
    except Exception as e:
        logger.error(f"Error generating review: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/topics/{topic_id}/review/submit")
async def submit_review(
    topic_id: str,
    submit: ReviewSubmit,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Submit a review response with mode metadata"""
    try:
        from app.services.quiz_service import quiz_service
        result = await quiz_service.submit_review_answer(
            topic_id=topic_id,
            concept=submit.concept,
            review_mode=submit.review_mode,
            response=submit.response,
            quality=submit.quality,
            user_id=user_id,
            db=db
        )
        return result
    except Exception as e:
        logger.error(f"Error submitting review: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ANALOGY TRANSFORM ENDPOINT
# ============================================================================

@router.post("/topics/{topic_id}/transform")
async def transform_topic_chunks(
    topic_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Trigger analogy transformation for a topic's source chunks"""
    try:
        topic = db.query(LearningTopic).filter(
            LearningTopic.id == topic_id,
            LearningTopic.user_id == user_id
        ).first()
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")

        # Dispatch as Celery task
        try:
            from app.tasks.learning import transform_topic_chunks_task
            transform_topic_chunks_task.delay(user_id, topic_id)
            return {
                "status": "queued",
                "topic_id": topic_id,
                "message": f"Analogy transformation queued for '{topic.title}'"
            }
        except Exception as e:
            # Fall back to inline processing
            from app.services.learning_source_service import learning_source_service
            result = await learning_source_service.transform_topic_chunks(topic_id, user_id, db)
            return {
                "status": "completed",
                "topic_id": topic_id,
                "transformed": result.get("transformed", 0),
                "message": f"Transformed {result.get('transformed', 0)} chunks for '{topic.title}'"
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error transforming chunks: {e}")
        raise HTTPException(status_code=500, detail=str(e))
