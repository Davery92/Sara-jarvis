"""Notes management routes."""
import uuid
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.models.user import User
from app.models.note import Note
from app.models.note_connection import NoteConnection
from app.schemas.notes import (
    NoteCreate, NoteResponse,
    NoteConnectionCreate, NoteConnectionResponse
)
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notes", tags=["Notes"])


@router.get("", response_model=List[NoteResponse])
async def list_notes(
    folder_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List notes, optionally filtered by folder.
    - folder_id=null : Return only root-level notes (no folder)
    - folder_id=<uuid> : Return notes in specific folder
    - folder_id not provided : Return all notes (legacy behavior)
    """
    query = db.query(Note).filter(Note.user_id == current_user.id)

    # Handle folder filtering
    if folder_id is not None:
        if folder_id.lower() == "null":
            query = query.filter(Note.folder_id.is_(None))
        else:
            query = query.filter(Note.folder_id == folder_id)

    notes = query.order_by(Note.updated_at.desc()).limit(100).all()

    return [
        NoteResponse(
            id=note.id,
            title=note.title,
            content=note.content,
            folder_id=note.folder_id,
            created_at=note.created_at.isoformat(),
            updated_at=note.updated_at.isoformat()
        )
        for note in notes
    ]


@router.post("", response_model=NoteResponse)
async def create_note(
    note_data: NoteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new note with Neo4j-first approach."""
    note_id = str(uuid.uuid4())

    try:
        from app.services.neo4j_service import neo4j_service
        from app.services.intelligence_pipeline import intelligence_pipeline, ContentType

        if not neo4j_service.driver:
            await neo4j_service.connect()

        await neo4j_service.create_note(
            note_id=note_id,
            user_id=current_user.id,
            title=note_data.title or "Untitled",
            content=note_data.content,
            folder_id=note_data.folder_id
        )

        await intelligence_pipeline.start_workers()

        await intelligence_pipeline.queue_fast_processing(
            content_id=note_id,
            content_type=ContentType.NOTE,
            metadata={
                "user_id": current_user.id,
                "title": note_data.title,
                "folder_id": note_data.folder_id
            }
        )

        logger.info(f"✅ Note {note_id} created in Neo4j and queued for intelligent processing")

    except Exception as neo_error:
        logger.error(f"❌ Neo4j note creation failed: {neo_error}")

    note = Note(
        id=note_id,
        user_id=current_user.id,
        title=note_data.title,
        content=note_data.content,
        folder_id=note_data.folder_id
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    return NoteResponse(
        id=note.id,
        title=note.title,
        content=note.content,
        folder_id=note.folder_id,
        created_at=note.created_at.isoformat(),
        updated_at=note.updated_at.isoformat()
    )


@router.get("/graph-data")
async def get_notes_graph_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all notes and connections for graph visualization."""
    notes = db.query(Note).filter(Note.user_id == current_user.id).all()
    connections = db.query(NoteConnection).filter(NoteConnection.user_id == current_user.id).all()

    return {
        "nodes": [
            {
                "id": note.id,
                "title": note.title,
                "content": note.content[:200] + "..." if len(note.content) > 200 else note.content,
                "type": "note",
                "created_at": note.created_at.isoformat(),
                "updated_at": note.updated_at.isoformat()
            }
            for note in notes
        ],
        "links": [
            {
                "id": conn.id,
                "source": conn.source_note_id,
                "target": conn.target_note_id,
                "type": conn.connection_type,
                "strength": conn.strength / 100.0,
                "auto_generated": conn.auto_generated == "true"
            }
            for conn in connections
        ]
    }


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a single note by ID."""
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    return NoteResponse(
        id=note.id,
        user_id=note.user_id,
        title=note.title,
        content=note.content,
        folder_id=note.folder_id,
        created_at=note.created_at.isoformat(),
        updated_at=note.updated_at.isoformat()
    )


@router.put("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: str,
    note_data: NoteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a note with Neo4j-first approach."""
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        from app.services.neo4j_service import neo4j_service
        from app.services.intelligence_pipeline import intelligence_pipeline, ContentType

        if not neo4j_service.driver:
            await neo4j_service.connect()

        await neo4j_service.create_note(
            note_id=note_id,
            user_id=current_user.id,
            title=note_data.title or "Untitled",
            content=note_data.content,
            folder_id=note_data.folder_id
        )

        await intelligence_pipeline.queue_fast_processing(
            content_id=note_id,
            content_type=ContentType.NOTE,
            metadata={
                "user_id": current_user.id,
                "title": note_data.title,
                "folder_id": note_data.folder_id,
                "is_update": True
            }
        )

        logger.info(f"✅ Note {note_id} updated in Neo4j and re-queued for processing")

    except Exception as neo_error:
        logger.error(f"❌ Neo4j note update failed: {neo_error}")

    note.title = note_data.title
    note.content = note_data.content
    note.folder_id = note_data.folder_id
    note.updated_at = datetime.now()
    db.commit()
    db.refresh(note)

    return NoteResponse(
        id=note.id,
        title=note.title,
        content=note.content,
        folder_id=note.folder_id,
        created_at=note.created_at.isoformat(),
        updated_at=note.updated_at.isoformat()
    )


@router.delete("/{note_id}")
async def delete_note(
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a note."""
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        from app.services.neo4j_service import neo4j_service
        await neo4j_service.delete_note(note_id, current_user.id)
        logger.info(f"✅ Note {note_id} deleted from Neo4j")
    except Exception as e:
        logger.warning(f"Failed to delete note from Neo4j: {e}")

    db.query(NoteConnection).filter(
        (NoteConnection.source_note_id == note_id) | (NoteConnection.target_note_id == note_id),
        NoteConnection.user_id == current_user.id
    ).delete()

    db.delete(note)
    db.commit()

    return {"message": "Note deleted successfully"}


@router.get("/{note_id}/connections", response_model=List[NoteConnectionResponse])
async def get_note_connections(
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all connections for a specific note (both outgoing and incoming)."""
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    connections = db.query(NoteConnection).filter(
        (NoteConnection.source_note_id == note_id) | (NoteConnection.target_note_id == note_id),
        NoteConnection.user_id == current_user.id
    ).all()

    return [
        NoteConnectionResponse(
            id=conn.id,
            source_note_id=conn.source_note_id,
            target_note_id=conn.target_note_id,
            connection_type=conn.connection_type,
            strength=conn.strength,
            auto_generated=conn.auto_generated == "true",
            created_at=conn.created_at.isoformat(),
            updated_at=conn.updated_at.isoformat()
        )
        for conn in connections
    ]


@router.get("/{note_id}/backlinks")
async def get_note_backlinks(
    note_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all notes that link TO this note (backlinks)."""
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    backlinks = db.query(NoteConnection).filter(
        NoteConnection.target_note_id == note_id,
        NoteConnection.user_id == current_user.id
    ).all()

    backlink_notes = []
    for conn in backlinks:
        source_note = db.query(Note).filter(Note.id == conn.source_note_id).first()
        if source_note:
            backlink_notes.append({
                "id": source_note.id,
                "title": source_note.title,
                "connection_type": conn.connection_type,
                "strength": conn.strength,
                "created_at": source_note.created_at.isoformat()
            })

    return backlink_notes


@router.post("/{note_id}/connections", response_model=NoteConnectionResponse)
async def create_note_connection(
    note_id: str,
    connection_data: NoteConnectionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a connection from one note to another."""
    source_note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not source_note:
        raise HTTPException(status_code=404, detail="Source note not found")

    target_note = db.query(Note).filter(
        Note.id == connection_data.target_note_id,
        Note.user_id == current_user.id
    ).first()
    if not target_note:
        raise HTTPException(status_code=404, detail="Target note not found")

    existing = db.query(NoteConnection).filter(
        NoteConnection.source_note_id == note_id,
        NoteConnection.target_note_id == connection_data.target_note_id,
        NoteConnection.user_id == current_user.id
    ).first()

    if existing:
        raise HTTPException(status_code=409, detail="Connection already exists")

    connection = NoteConnection(
        user_id=current_user.id,
        source_note_id=note_id,
        target_note_id=connection_data.target_note_id,
        connection_type=connection_data.connection_type,
        strength=connection_data.strength,
        auto_generated="true" if connection_data.auto_generated else "false"
    )

    db.add(connection)
    db.commit()
    db.refresh(connection)

    return NoteConnectionResponse(
        id=connection.id,
        source_note_id=connection.source_note_id,
        target_note_id=connection.target_note_id,
        connection_type=connection.connection_type,
        strength=connection.strength,
        auto_generated=connection.auto_generated == "true",
        created_at=connection.created_at.isoformat(),
        updated_at=connection.updated_at.isoformat()
    )


@router.delete("/{note_id}/connections/{connection_id}")
async def delete_note_connection(
    note_id: str,
    connection_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a specific note connection."""
    connection = db.query(NoteConnection).filter(
        NoteConnection.id == connection_id,
        (NoteConnection.source_note_id == note_id) | (NoteConnection.target_note_id == note_id),
        NoteConnection.user_id == current_user.id
    ).first()

    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    db.delete(connection)
    db.commit()

    return {"message": "Connection deleted successfully"}
