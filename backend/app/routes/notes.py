"""Notes management routes."""
import uuid
import logging
from datetime import datetime
from app.core.timezone import naive_local_now
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


def normalize_note_tags(tags: Optional[List[str]]) -> List[str]:
    """Trim, dedupe, and cap note tags for consistent storage."""
    if not tags:
        return []

    normalized = []
    seen = set()

    for raw_tag in tags:
        if raw_tag is None:
            continue

        tag = str(raw_tag).strip().lower()
        if not tag or tag in seen:
            continue

        seen.add(tag)
        normalized.append(tag[:48])

        if len(normalized) >= 20:
            break

    return normalized


def serialize_note(note: Note, include_user_id: bool = False) -> NoteResponse:
    return NoteResponse(
        id=note.id,
        title=note.title,
        content=note.content,
        folder_id=note.folder_id,
        tags=normalize_note_tags(note.tags),
        starred=bool(note.starred),
        user_id=note.user_id if include_user_id else None,
        created_at=note.created_at.isoformat(),
        updated_at=note.updated_at.isoformat(),
    )


@router.get("", response_model=List[NoteResponse])
async def list_notes(
    folder_id: Optional[str] = None,
    limit: int = Query(500, ge=1, le=500, description="Max notes to return"),
    include_content: bool = Query(
        True,
        description=(
            "Include full note body. Default True for backward compatibility. "
            "Pass false to get only a short excerpt — the vault list view does "
            "this to avoid shipping multi-MB of note bodies on every page load; "
            "full content is fetched lazily via GET /notes/{id} when a note opens."
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List notes, optionally filtered by folder.
    - folder_id=null : Return only root-level notes (no folder)
    - folder_id=<uuid> : Return notes in specific folder
    - folder_id not provided : Return all notes (legacy behavior)

    Explicitly skips the `embedding` column (vector(1024), ~4KB per row) —
    the list response doesn't use it and loading it across 500 rows added
    ~2MB of pgvector overhead per request.

    When include_content=false, `content` is truncated to a short excerpt
    (EXCERPT_CHARS) so previews/search-by-snippet still work while the payload
    drops from ~5MB to a few hundred KB.
    """
    EXCERPT_CHARS = 400

    query = db.query(
        Note.id, Note.user_id, Note.folder_id, Note.title, Note.content,
        Note.tags, Note.starred, Note.created_at, Note.updated_at,
    ).filter(Note.user_id == current_user.id)

    # Handle folder filtering
    if folder_id is not None:
        if folder_id.lower() == "null":
            query = query.filter(Note.folder_id.is_(None))
        else:
            query = query.filter(Note.folder_id == folder_id)

    rows = query.order_by(Note.updated_at.desc()).limit(limit).all()

    def _body(content: Optional[str]) -> str:
        text = content or ""
        if include_content or len(text) <= EXCERPT_CHARS:
            return text
        return text[:EXCERPT_CHARS]

    return [
        NoteResponse(
            id=row.id,
            title=row.title,
            content=_body(row.content),
            folder_id=row.folder_id,
            tags=normalize_note_tags(row.tags),
            starred=bool(row.starred),
            user_id=None,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
        )
        for row in rows
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
        folder_id=note_data.folder_id,
        tags=normalize_note_tags(note_data.tags),
        starred=bool(note_data.starred),
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    return serialize_note(note)


@router.post("/admin/backfill-connections")
async def backfill_note_connections(
    current_user: User = Depends(get_current_user),
):
    """Trigger a backfill of embeddings and connections for all user notes."""
    from app.tasks.notes import backfill_note_connections as backfill_task
    backfill_task.delay(current_user.id)
    return {"message": "Backfill task queued", "user_id": current_user.id}


@router.get("/graph-data")
async def get_notes_graph_data(
    include_nodes: bool = Query(False, description="Include note metadata in response. Default false — current frontend only consumes `links`."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get note connections (and optionally node metadata) for graph viz.

    By default returns connections only — the current Notes UI computes its
    own node set from local state. Pass include_nodes=true to also receive
    note id/title/preview metadata.
    """
    # Connections are the actual payload the frontend consumes.
    conn_rows = (
        db.query(
            NoteConnection.id,
            NoteConnection.source_note_id,
            NoteConnection.target_note_id,
            NoteConnection.connection_type,
            NoteConnection.strength,
            NoteConnection.auto_generated,
        )
        .filter(NoteConnection.user_id == current_user.id)
        .all()
    )

    response: dict = {
        "links": [
            {
                "id": conn.id,
                "source": conn.source_note_id,
                "target": conn.target_note_id,
                "type": conn.connection_type,
                "strength": (conn.strength or 0) / 100.0,
                "auto_generated": conn.auto_generated == "true",
            }
            for conn in conn_rows
        ]
    }

    if include_nodes:
        # Truncate content in SQL — full content is wasted at 200 chars max.
        # Embedding column is excluded by virtue of explicit-column SELECT.
        from sqlalchemy import func, case
        note_rows = (
            db.query(
                Note.id,
                Note.title,
                case(
                    (func.length(Note.content) > 200, func.substr(Note.content, 1, 200) + "..."),
                    else_=Note.content,
                ).label("content_preview"),
                Note.tags,
                Note.starred,
                Note.created_at,
                Note.updated_at,
            )
            .filter(Note.user_id == current_user.id)
            .all()
        )
        response["nodes"] = [
            {
                "id": row.id,
                "title": row.title,
                "content": row.content_preview or "",
                "type": "note",
                "tags": normalize_note_tags(row.tags),
                "starred": bool(row.starred),
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
            for row in note_rows
        ]

    return response


@router.get("/search")
async def search_notes(
    q: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fuzzy title+content search for notes.

    Mirrors `/api/notes/search`. Without this, a `GET /notes/search?q=...`
    matches the `/notes/{note_id}` handler with note_id="search" and 404s.
    iOS clients hit the unprefixed `/notes/search`.
    """
    from sqlalchemy import text
    import json as _json

    normalized_query = q.replace(" ", "")
    rows = db.execute(text(
        """
        SELECT id, title, content, folder_id, tags, starred, created_at, updated_at
        FROM note
        WHERE user_id = :user_id
          AND (
            title ILIKE :query_pattern
            OR REPLACE(title, ' ', '') ILIKE :normalized_pattern
            OR content ILIKE :query_pattern
          )
        ORDER BY
            CASE WHEN title ILIKE :query_pattern THEN 0
                 WHEN REPLACE(title, ' ', '') ILIKE :normalized_pattern THEN 1
                 ELSE 2 END,
            updated_at DESC
        LIMIT 10
        """
    ), {
        "user_id": current_user.id,
        "query_pattern": f"%{q}%",
        "normalized_pattern": f"%{normalized_query}%",
    }).fetchall()

    return [
        {
            "id": str(row.id),
            "title": row.title or "Untitled",
            "content": row.content,
            "folder_id": row.folder_id,
            "tags": (
                row.tags
                if isinstance(row.tags, list)
                else (_json.loads(row.tags) if row.tags else [])
            ),
            "starred": bool(row.starred),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


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

    return serialize_note(note, include_user_id=True)


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
    if note_data.tags is not None:
        note.tags = normalize_note_tags(note_data.tags)
    if note_data.starred is not None:
        note.starred = bool(note_data.starred)
    note.updated_at = naive_local_now()
    db.commit()
    db.refresh(note)

    return serialize_note(note)


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
