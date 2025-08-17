from fastapi import APIRouter, Depends, HTTPException, status, Query, Form
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.memory_service import MemoryService
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class MemorySearchRequest(BaseModel):
    query: str
    scopes: List[str] = ["episodes", "notes", "docs", "summaries"]
    limit: int = 10


class MemorySearchResult(BaseModel):
    type: str  # episode, note, document, summary
    score: float
    text: str
    metadata: Dict[str, Any]


class MemorySearchResponse(BaseModel):
    results: List[MemorySearchResult]
    query: str
    total_results: int


class EpisodeResponse(BaseModel):
    id: str
    source: str
    role: str
    content: str
    importance: float
    meta: Dict[str, Any]
    created_at: str


class EpisodesListResponse(BaseModel):
    episodes: List[EpisodeResponse]
    total: int
    page: int
    per_page: int


class SummaryResponse(BaseModel):
    id: str
    scope: str
    content: str
    meta: Dict[str, Any]
    created_at: str


class SummariesListResponse(BaseModel):
    summaries: List[SummaryResponse]
    total: int
    page: int
    per_page: int


@router.post("/search", response_model=MemorySearchResponse)
async def search_memory(
    request: MemorySearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Search across all memory types using semantic similarity"""
    
    try:
        memory_service = MemoryService(db)
        
        # Validate scopes
        valid_scopes = ["episodes", "notes", "docs", "summaries"]
        invalid_scopes = [scope for scope in request.scopes if scope not in valid_scopes]
        if invalid_scopes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid scopes: {invalid_scopes}. Valid scopes: {valid_scopes}"
            )
        
        # Perform memory search
        results = await memory_service.search_memory(
            user_id=str(current_user.id),
            query=request.query,
            scopes=request.scopes,
            limit=request.limit
        )
        
        # Format results
        formatted_results = []
        for result in results:
            metadata = {
                "id": result.get("episode_id") or result.get("note_id") or result.get("doc_id") or result.get("summary_id"),
                "created_at": result.get("created_at", "").isoformat() if result.get("created_at") else None
            }
            
            # Add type-specific metadata
            if result["type"] == "episode":
                metadata.update({
                    "source": result.get("source"),
                    "role": result.get("role"),
                    "importance": result.get("importance")
                })
            elif result["type"] == "note":
                metadata.update({
                    "title": result.get("title")
                })
            elif result["type"] == "document":
                metadata.update({
                    "doc_title": result.get("doc_title"),
                    "chunk_idx": result.get("chunk_idx"),
                    "breadcrumb": result.get("breadcrumb")
                })
            elif result["type"] == "summary":
                metadata.update({
                    "scope": result.get("scope")
                })
            
            formatted_results.append(MemorySearchResult(
                type=result["type"],
                score=result["score"],
                text=result["text"],
                metadata=metadata
            ))
        
        return MemorySearchResponse(
            results=formatted_results,
            query=request.query,
            total_results=len(formatted_results)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to search memory: {e}")
        raise HTTPException(status_code=500, detail="Failed to search memory")


@router.get("/search", response_model=MemorySearchResponse)
async def search_memory_get(
    q: str = Query(..., description="Search query"),
    scopes: str = Query("episodes,notes,docs,summaries", description="Comma-separated list of scopes"),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Search memory via GET request (for simple queries)"""
    
    try:
        # Parse scopes
        scope_list = [scope.strip() for scope in scopes.split(",") if scope.strip()]
        
        request = MemorySearchRequest(
            query=q,
            scopes=scope_list,
            limit=limit
        )
        
        return await search_memory(request, current_user, db)
        
    except Exception as e:
        logger.error(f"Failed to search memory via GET: {e}")
        raise HTTPException(status_code=500, detail="Failed to search memory")


@router.get("/episodes", response_model=EpisodesListResponse)
async def list_episodes(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    source: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    min_importance: Optional[float] = Query(None, ge=0.0, le=1.0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List user's episodes with filtering"""
    
    try:
        from app.models.episode import Episode
        from sqlalchemy import desc
        
        query = db.query(Episode).filter(Episode.user_id == str(current_user.id))
        
        # Apply filters
        if source:
            query = query.filter(Episode.source == source)
        if role:
            query = query.filter(Episode.role == role)
        if min_importance is not None:
            query = query.filter(Episode.importance >= min_importance)
        
        # Get total count
        total = query.count()
        
        # Apply pagination and ordering
        offset = (page - 1) * per_page
        episodes = query.order_by(desc(Episode.created_at)).offset(offset).limit(per_page).all()
        
        episode_responses = [
            EpisodeResponse(
                id=str(episode.id),
                source=episode.source,
                role=episode.role,
                content=episode.content,
                importance=episode.importance,
                meta=episode.meta,
                created_at=episode.created_at.isoformat()
            )
            for episode in episodes
        ]
        
        return EpisodesListResponse(
            episodes=episode_responses,
            total=total,
            page=page,
            per_page=per_page
        )
        
    except Exception as e:
        logger.error(f"Failed to list episodes: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve episodes")


@router.get("/summaries", response_model=SummariesListResponse)
async def list_summaries(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    scope: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List user's semantic summaries"""
    
    try:
        from app.models.memory import SemanticSummary
        from sqlalchemy import desc
        
        query = db.query(SemanticSummary).filter(SemanticSummary.user_id == str(current_user.id))
        
        # Apply scope filter
        if scope:
            query = query.filter(SemanticSummary.scope == scope)
        
        # Get total count
        total = query.count()
        
        # Apply pagination and ordering
        offset = (page - 1) * per_page
        summaries = query.order_by(desc(SemanticSummary.created_at)).offset(offset).limit(per_page).all()
        
        summary_responses = [
            SummaryResponse(
                id=str(summary.id),
                scope=summary.scope,
                content=summary.content,
                meta=summary.meta,
                created_at=summary.created_at.isoformat()
            )
            for summary in summaries
        ]
        
        return SummariesListResponse(
            summaries=summary_responses,
            total=total,
            page=page,
            per_page=per_page
        )
        
    except Exception as e:
        logger.error(f"Failed to list summaries: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve summaries")


@router.post("/episodes/{episode_id}/importance")
async def update_episode_importance(
    episode_id: str,
    importance: float = Form(..., ge=0.0, le=1.0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update the importance score of an episode"""
    
    try:
        from app.models.episode import Episode
        
        episode = db.query(Episode).filter(
            Episode.id == episode_id,
            Episode.user_id == str(current_user.id)
        ).first()
        
        if not episode:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Episode not found"
            )
        
        episode.importance = importance
        db.commit()
        
        return {"message": "Episode importance updated successfully", "new_importance": importance}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update episode importance: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update episode importance")


@router.delete("/episodes/{episode_id}")
async def delete_episode(
    episode_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an episode"""
    
    try:
        from app.models.episode import Episode
        
        episode = db.query(Episode).filter(
            Episode.id == episode_id,
            Episode.user_id == str(current_user.id)
        ).first()
        
        if not episode:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Episode not found"
            )
        
        db.delete(episode)
        db.commit()
        
        return {"message": "Episode deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete episode: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete episode")


@router.post("/summaries/generate")
async def generate_summary(
    scope: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Generate a new summary for a specific scope"""
    
    try:
        memory_service = MemoryService(db)
        
        # Validate scope
        valid_scopes = ["chat", "notes", "documents", "daily", "weekly", "monthly"]
        if scope not in valid_scopes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid scope. Valid scopes: {valid_scopes}"
            )
        
        # Generate summary based on scope
        if scope in ["daily", "weekly", "monthly"]:
            # Time-based summaries
            from datetime import datetime, timedelta, timezone
            
            now = datetime.now(timezone.utc)
            if scope == "daily":
                start_time = now - timedelta(days=1)
            elif scope == "weekly":
                start_time = now - timedelta(weeks=1)
            else:  # monthly
                start_time = now - timedelta(days=30)
            
            from app.models.episode import Episode
            episodes = db.query(Episode).filter(
                Episode.user_id == str(current_user.id),
                Episode.created_at >= start_time
            ).order_by(Episode.importance.desc()).limit(50).all()
            
            if episodes:
                summary = await memory_service.create_time_summary(
                    user_id=str(current_user.id),
                    scope=scope,
                    episodes=episodes
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No episodes found for {scope} summary"
                )
        else:
            # Content-based summaries
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=f"Summary generation for scope '{scope}' not yet implemented"
            )
        
        return {
            "message": f"Summary generated successfully for scope '{scope}'",
            "summary_id": str(summary.id)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate summary")


@router.get("/stats")
async def get_memory_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get memory statistics for the user"""
    
    try:
        from app.models.episode import Episode
        from app.models.memory import SemanticSummary
        from app.models.note import Note
        from app.models.doc import Document, DocChunk
        from sqlalchemy import func
        
        # Get counts
        episodes_count = db.query(Episode).filter(Episode.user_id == str(current_user.id)).count()
        summaries_count = db.query(SemanticSummary).filter(SemanticSummary.user_id == str(current_user.id)).count()
        notes_count = db.query(Note).filter(Note.user_id == current_user.id).count()
        documents_count = db.query(Document).filter(Document.user_id == current_user.id).count()
        chunks_count = db.query(DocChunk).join(Document).filter(Document.user_id == current_user.id).count()
        
        # Get importance distribution
        importance_stats = db.query(
            func.avg(Episode.importance).label('avg_importance'),
            func.min(Episode.importance).label('min_importance'),
            func.max(Episode.importance).label('max_importance')
        ).filter(Episode.user_id == str(current_user.id)).first()
        
        # Get recent activity (last 7 days)
        from datetime import datetime, timedelta, timezone
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        recent_episodes = db.query(Episode).filter(
            Episode.user_id == str(current_user.id),
            Episode.created_at >= week_ago
        ).count()
        
        return {
            "episodes": episodes_count,
            "summaries": summaries_count,
            "notes": notes_count,
            "documents": documents_count,
            "document_chunks": chunks_count,
            "importance_stats": {
                "average": float(importance_stats.avg_importance or 0),
                "minimum": float(importance_stats.min_importance or 0),
                "maximum": float(importance_stats.max_importance or 0)
            },
            "recent_activity": {
                "episodes_last_7_days": recent_episodes
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get memory stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve memory statistics")