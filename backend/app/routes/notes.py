from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, or_
from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.note import Note
from app.services.embeddings import get_embedding
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class NoteCreate(BaseModel):
    title: str = ""
    content: str


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


class NoteResponse(BaseModel):
    id: str
    title: str
    content: str
    created_at: str
    updated_at: str


class NotesListResponse(BaseModel):
    notes: List[NoteResponse]
    total: int
    page: int
    per_page: int


@router.get("/", response_model=NotesListResponse)
async def list_notes(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List user's notes with pagination and search"""
    
    try:
        query = db.query(Note).filter(Note.user_id == current_user.id)
        
        # Apply search filter
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    Note.title.ilike(search_term),
                    Note.content.ilike(search_term)
                )
            )
        
        # Get total count
        total = query.count()
        
        # Apply pagination and ordering
        offset = (page - 1) * per_page
        notes = query.order_by(desc(Note.updated_at)).offset(offset).limit(per_page).all()
        
        note_responses = [
            NoteResponse(
                id=str(note.id),
                title=note.title,
                content=note.content,
                created_at=note.created_at.isoformat(),
                updated_at=note.updated_at.isoformat()
            )
            for note in notes
        ]
        
        return NotesListResponse(
            notes=note_responses,
            total=total,
            page=page,
            per_page=per_page
        )
        
    except Exception as e:
        logger.error(f"Failed to list notes: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve notes")


@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(
    note_data: NoteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new note with embedding"""
    
    try:
        # Generate embedding for the note content
        content_for_embedding = f"{note_data.title} {note_data.content}".strip()
        embedding = await get_embedding(content_for_embedding)
        
        # Create note
        note = Note(
            user_id=current_user.id,
            title=note_data.title,
            content=note_data.content,
            embedding=embedding
        )
        
        db.add(note)
        db.commit()
        db.refresh(note)
        
        return NoteResponse(
            id=str(note.id),
            title=note.title,
            content=note.content,
            created_at=note.created_at.isoformat(),
            updated_at=note.updated_at.isoformat()
        )
        
    except Exception as e:
        logger.error(f"Failed to create note: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create note")


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific note"""
    
    note = db.query(Note).filter(
        Note.id == note_id,
        Note.user_id == current_user.id
    ).first()
    
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found"
        )
    
    return NoteResponse(
        id=str(note.id),
        title=note.title,
        content=note.content,
        created_at=note.created_at.isoformat(),
        updated_at=note.updated_at.isoformat()
    )


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: UUID,
    note_update: NoteUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a note and regenerate embedding if content changed"""
    
    try:
        note = db.query(Note).filter(
            Note.id == note_id,
            Note.user_id == current_user.id
        ).first()
        
        if not note:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Note not found"
            )
        
        # Track if content changed for embedding update
        content_changed = False
        
        # Update fields
        if note_update.title is not None:
            note.title = note_update.title
            content_changed = True
            
        if note_update.content is not None:
            note.content = note_update.content
            content_changed = True
        
        # Regenerate embedding if content changed
        if content_changed:
            content_for_embedding = f"{note.title} {note.content}".strip()
            note.embedding = await get_embedding(content_for_embedding)
        
        db.commit()
        db.refresh(note)
        
        return NoteResponse(
            id=str(note.id),
            title=note.title,
            content=note.content,
            created_at=note.created_at.isoformat(),
            updated_at=note.updated_at.isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update note: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update note")


@router.delete("/{note_id}")
async def delete_note(
    note_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a note"""
    
    try:
        note = db.query(Note).filter(
            Note.id == note_id,
            Note.user_id == current_user.id
        ).first()
        
        if not note:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Note not found"
            )
        
        db.delete(note)
        db.commit()
        
        return {"message": "Note deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete note: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete note")


@router.get("/{note_id}/similar", response_model=List[NoteResponse])
async def get_similar_notes(
    note_id: UUID,
    limit: int = Query(5, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Find notes similar to the given note using vector similarity"""
    
    try:
        # Get the source note
        source_note = db.query(Note).filter(
            Note.id == note_id,
            Note.user_id == current_user.id
        ).first()
        
        if not source_note or not source_note.embedding:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Note not found or has no embedding"
            )
        
        # Find similar notes using cosine similarity
        sql = """
        SELECT n.*, 1 - (n.embedding <=> :embedding) as similarity
        FROM note n
        WHERE n.user_id = :user_id 
            AND n.id != :note_id
            AND n.embedding IS NOT NULL
        ORDER BY similarity DESC
        LIMIT :limit
        """
        
        result = db.execute(sql, {
            "embedding": source_note.embedding,
            "user_id": str(current_user.id),
            "note_id": str(note_id),
            "limit": limit
        })
        
        similar_notes = []
        for row in result.fetchall():
            similar_notes.append(NoteResponse(
                id=str(row.id),
                title=row.title,
                content=row.content,
                created_at=row.created_at.isoformat(),
                updated_at=row.updated_at.isoformat()
            ))
        
        return similar_notes
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to find similar notes: {e}")
        raise HTTPException(status_code=500, detail="Failed to find similar notes")