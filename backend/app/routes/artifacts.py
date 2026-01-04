"""
Artifacts API Routes
CRUD operations for canvas artifacts
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid
import logging

from sqlalchemy.orm import Session
from app.models.artifact import Artifact
from app.main_simple import get_db, get_current_user

router = APIRouter(tags=["artifacts"])
logger = logging.getLogger(__name__)


# ============================================================================
# Request/Response Models
# ============================================================================

class ArtifactCreate(BaseModel):
    """Create a new artifact"""
    artifact_type: str  # code, diagram, document, canvas, table
    title: str
    content: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None
    conversation_id: Optional[str] = None
    episode_id: Optional[str] = None


class ArtifactUpdate(BaseModel):
    """Update an artifact"""
    title: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    is_pinned: Optional[bool] = None


class ArtifactResponse(BaseModel):
    """Artifact response"""
    id: str
    user_id: str
    artifact_type: str
    title: str
    content: Dict[str, Any]
    metadata: Optional[Dict[str, Any]]
    conversation_id: Optional[str]
    episode_id: Optional[str]
    is_pinned: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ============================================================================
# Routes
# ============================================================================

@router.post("", response_model=ArtifactResponse)
async def create_artifact(
    request: ArtifactCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Create a new artifact"""
    try:
        artifact = Artifact(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            artifact_type=request.artifact_type,
            title=request.title,
            content=request.content,
            artifact_metadata=request.metadata or {},
            conversation_id=request.conversation_id,
            episode_id=request.episode_id,
            is_pinned=False
        )

        db.add(artifact)
        db.commit()
        db.refresh(artifact)

        logger.info(f"Created artifact: {artifact.id} ({artifact.artifact_type})")

        return ArtifactResponse(
            id=artifact.id,
            user_id=artifact.user_id,
            artifact_type=artifact.artifact_type,
            title=artifact.title,
            content=artifact.content,
            metadata=artifact.artifact_metadata,
            conversation_id=artifact.conversation_id,
            episode_id=artifact.episode_id,
            is_pinned=artifact.is_pinned,
            created_at=artifact.created_at.isoformat(),
            updated_at=artifact.updated_at.isoformat()
        )

    except Exception as e:
        logger.error(f"Error creating artifact: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get an artifact by ID"""
    artifact = db.query(Artifact).filter(
        Artifact.id == artifact_id,
        Artifact.user_id == current_user.id
    ).first()

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return ArtifactResponse(
        id=artifact.id,
        user_id=artifact.user_id,
        artifact_type=artifact.artifact_type,
        title=artifact.title,
        content=artifact.content,
        metadata=artifact.artifact_metadata,
        conversation_id=artifact.conversation_id,
        episode_id=artifact.episode_id,
        is_pinned=artifact.is_pinned,
        created_at=artifact.created_at.isoformat(),
        updated_at=artifact.updated_at.isoformat()
    )


@router.put("/{artifact_id}", response_model=ArtifactResponse)
async def update_artifact(
    artifact_id: str,
    request: ArtifactUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Update an artifact"""
    artifact = db.query(Artifact).filter(
        Artifact.id == artifact_id,
        Artifact.user_id == current_user.id
    ).first()

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if request.title is not None:
        artifact.title = request.title
    if request.content is not None:
        artifact.content = request.content
    if request.metadata is not None:
        artifact.artifact_metadata = request.metadata
    if request.is_pinned is not None:
        artifact.is_pinned = request.is_pinned

    db.commit()
    db.refresh(artifact)

    logger.info(f"Updated artifact: {artifact.id}")

    return ArtifactResponse(
        id=artifact.id,
        user_id=artifact.user_id,
        artifact_type=artifact.artifact_type,
        title=artifact.title,
        content=artifact.content,
        metadata=artifact.artifact_metadata,
        conversation_id=artifact.conversation_id,
        episode_id=artifact.episode_id,
        is_pinned=artifact.is_pinned,
        created_at=artifact.created_at.isoformat(),
        updated_at=artifact.updated_at.isoformat()
    )


@router.delete("/{artifact_id}")
async def delete_artifact(
    artifact_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Delete an artifact"""
    artifact = db.query(Artifact).filter(
        Artifact.id == artifact_id,
        Artifact.user_id == current_user.id
    ).first()

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    db.delete(artifact)
    db.commit()

    logger.info(f"Deleted artifact: {artifact_id}")

    return {"status": "deleted", "id": artifact_id}


@router.get("", response_model=List[ArtifactResponse])
async def list_artifacts(
    artifact_type: Optional[str] = None,
    conversation_id: Optional[str] = None,
    pinned_only: bool = False,
    limit: int = Query(default=50, le=100),
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """List artifacts with optional filters"""
    query = db.query(Artifact).filter(Artifact.user_id == current_user.id)

    if artifact_type:
        query = query.filter(Artifact.artifact_type == artifact_type)

    if conversation_id:
        query = query.filter(Artifact.conversation_id == conversation_id)

    if pinned_only:
        query = query.filter(Artifact.is_pinned == True)

    artifacts = query.order_by(Artifact.updated_at.desc()).offset(offset).limit(limit).all()

    return [
        ArtifactResponse(
            id=a.id,
            user_id=a.user_id,
            artifact_type=a.artifact_type,
            title=a.title,
            content=a.content,
            metadata=a.artifact_metadata,
            conversation_id=a.conversation_id,
            episode_id=a.episode_id,
            is_pinned=a.is_pinned,
            created_at=a.created_at.isoformat(),
            updated_at=a.updated_at.isoformat()
        )
        for a in artifacts
    ]


@router.get("/conversation/{conversation_id}", response_model=List[ArtifactResponse])
async def get_conversation_artifacts(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get all artifacts for a specific conversation"""
    artifacts = db.query(Artifact).filter(
        Artifact.user_id == current_user.id,
        Artifact.conversation_id == conversation_id
    ).order_by(Artifact.created_at).all()

    return [
        ArtifactResponse(
            id=a.id,
            user_id=a.user_id,
            artifact_type=a.artifact_type,
            title=a.title,
            content=a.content,
            metadata=a.artifact_metadata,
            conversation_id=a.conversation_id,
            episode_id=a.episode_id,
            is_pinned=a.is_pinned,
            created_at=a.created_at.isoformat(),
            updated_at=a.updated_at.isoformat()
        )
        for a in artifacts
    ]
