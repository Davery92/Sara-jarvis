from typing import Dict, Any, Optional
import logging
from app.tools.base import BaseTool, ToolResult
from app.models.note import Note
from app.models.folder import Folder
from app.services.embeddings import get_embedding
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import text
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _resolve_folder(
    db: Session,
    user_id: str,
    folder_id: Optional[str] = None,
    folder_name: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve a folder reference to a folder_id.

    Returns (folder_id, error_message). If both are None, the note belongs at root.
    Accepts either an explicit folder_id or a case-insensitive folder name.
    """
    if folder_id:
        folder = db.query(Folder).filter(
            Folder.id == folder_id,
            Folder.user_id == user_id,
        ).first()
        if not folder:
            return None, f"No folder found with id '{folder_id}'"
        return folder.id, None

    if folder_name:
        name = folder_name.strip().lstrip("/")
        matches = db.query(Folder).filter(
            Folder.user_id == user_id,
            Folder.name.ilike(name),
        ).all()
        if not matches:
            return None, (
                f"No folder named '{folder_name}' exists. "
                "Use notes_create_folder to make one, or notes_list_folders to see existing folders."
            )
        if len(matches) > 1:
            ids = ", ".join(m.id for m in matches)
            return None, (
                f"Multiple folders named '{folder_name}' exist ({ids}). "
                "Pass an explicit folder_id to disambiguate."
            )
        return matches[0].id, None

    return None, None


class NotesCreateTool(BaseTool):
    """Tool for creating new notes"""
    
    @property
    def name(self) -> str:
        return "notes_create"
    
    @property
    def description(self) -> str:
        return "Create a new note with optional title and content. The note will be automatically embedded for semantic search."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Optional title for the note"
                },
                "content": {
                    "type": "string",
                    "description": "The note content"
                },
                "folder_name": {
                    "type": "string",
                    "description": "Optional folder name to file the note under (e.g. 'Recipes'). The folder must already exist; use notes_create_folder first if needed."
                },
                "folder_id": {
                    "type": "string",
                    "description": "Optional explicit folder ID. Prefer folder_name unless disambiguating duplicates."
                }
            },
            "required": ["content"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Create a new note"""

        title = kwargs.get("title", "")
        content = kwargs.get("content")
        folder_id_arg = kwargs.get("folder_id")
        folder_name_arg = kwargs.get("folder_name")

        if not content:
            return ToolResult(
                success=False,
                message="Note content is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Resolve target folder (by id or name) if one was requested
            resolved_folder_id, folder_err = _resolve_folder(
                db, user_id, folder_id_arg, folder_name_arg
            )
            if folder_err:
                return ToolResult(success=False, message=folder_err)

            # Get embedding for the note
            full_text = f"{title}\n{content}" if title else content
            embedding = await get_embedding(full_text)

            # Create note
            note = Note(
                user_id=user_id,
                title=title,
                content=content,
                folder_id=resolved_folder_id,
                embedding=embedding
            )

            db.add(note)
            db.commit()
            db.refresh(note)

            # Detect connections (wiki links + semantic neighbors)
            try:
                from app.services.note_connector import process_note_connections_sync
                await process_note_connections_sync(
                    str(note.id), user_id, title, content, db
                )
            except Exception as conn_err:
                logger.warning(f"Connection detection failed for new note: {conn_err}")

            return ToolResult(
                success=True,
                data={
                    "note_id": str(note.id),
                    "title": note.title,
                    "content": note.content,
                    "folder_id": note.folder_id,
                    "created_at": note.created_at.isoformat()
                },
                message=(
                    f"Created note: {title or 'Untitled'}"
                    + (f" (in folder {folder_name_arg or resolved_folder_id})" if resolved_folder_id else "")
                )
            )
            
        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to create note: {str(e)}"
            )
        finally:
            db.close()


class NotesSearchTool(BaseTool):
    """Tool for searching notes"""
    
    @property
    def name(self) -> str:
        return "notes_search"
    
    @property
    def description(self) -> str:
        return "Search through notes using keywords or semantic similarity."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for finding notes"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of notes to return (default: 10)",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Search notes using text matching (title/content) with vector similarity as secondary"""

        query = kwargs.get("query")
        limit = kwargs.get("limit", 10)

        if not query:
            return ToolResult(
                success=False,
                message="Search query is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            notes = []
            citations = []
            seen_ids = set()

            # Normalize query for fuzzy matching (remove spaces)
            normalized_query = query.replace(" ", "")

            # FIRST: Text-based search on title and content (works even without embeddings)
            text_sql = text("""
                SELECT id, title, content, created_at, updated_at, 1.0 as similarity
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
                LIMIT :limit
            """)

            text_result = db.execute(text_sql, {
                "user_id": user_id,
                "query_pattern": f"%{query}%",
                "normalized_pattern": f"%{normalized_query}%",
                "limit": limit
            })

            for row in text_result.fetchall():
                if str(row.id) not in seen_ids:
                    seen_ids.add(str(row.id))
                    notes.append({
                        "note_id": str(row.id),
                        "title": row.title,
                        "content": row.content,
                        "similarity": 1.0,  # Text match = high relevance
                        "created_at": row.created_at.isoformat(),
                        "updated_at": row.updated_at.isoformat()
                    })
                    citations.append(f"note:{row.id}")

            # SECOND: If we need more results, add vector similarity search
            if len(notes) < limit:
                try:
                    query_embedding = await get_embedding(query)

                    vector_sql = text("""
                        SELECT
                            id, title, content, created_at, updated_at,
                            (1 - (embedding <=> :query_embedding)) as similarity
                        FROM note
                        WHERE user_id = :user_id AND embedding IS NOT NULL
                        ORDER BY (embedding <=> :query_embedding)
                        LIMIT :limit
                    """)

                    vector_result = db.execute(vector_sql, {
                        "query_embedding": str(query_embedding),
                        "user_id": user_id,
                        "limit": limit
                    })

                    for row in vector_result.fetchall():
                        if str(row.id) not in seen_ids and len(notes) < limit:
                            seen_ids.add(str(row.id))
                            notes.append({
                                "note_id": str(row.id),
                                "title": row.title,
                                "content": row.content,
                                "similarity": round(row.similarity, 3),
                                "created_at": row.created_at.isoformat(),
                                "updated_at": row.updated_at.isoformat()
                            })
                            citations.append(f"note:{row.id}")
                except Exception as embed_error:
                    # Vector search failed, but text search may have worked
                    pass

            return ToolResult(
                success=True,
                data={
                    "notes": notes,
                    "query": query,
                    "total_found": len(notes)
                },
                message=f"Found {len(notes)} notes matching '{query}'",
                citations=citations
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Note search failed: {str(e)}"
            )
        finally:
            db.close()


class NotesEditTool(BaseTool):
    """Tool for editing existing notes"""
    
    @property
    def name(self) -> str:
        return "notes_edit"
    
    @property
    def description(self) -> str:
        return "Edit an existing note's title or content. The note will be re-embedded after editing."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "The ID of the note to edit"
                },
                "title": {
                    "type": "string",
                    "description": "New title for the note"
                },
                "content": {
                    "type": "string",
                    "description": "New content for the note"
                },
                "folder_name": {
                    "type": "string",
                    "description": "Optional: move the note into this folder (by name). The folder must already exist."
                },
                "folder_id": {
                    "type": "string",
                    "description": "Optional: move the note into this folder (by explicit ID). Pass 'root' to move the note out of any folder."
                }
            },
            "required": ["note_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Edit an existing note"""

        note_id = kwargs.get("note_id")
        new_title = kwargs.get("title")
        new_content = kwargs.get("content")
        folder_id_arg = kwargs.get("folder_id")
        folder_name_arg = kwargs.get("folder_name")

        if not note_id:
            return ToolResult(
                success=False,
                message="Note ID is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Find the note
            note = db.query(Note).filter(
                Note.id == note_id,
                Note.user_id == user_id
            ).first()

            if not note:
                return ToolResult(
                    success=False,
                    message="Note not found"
                )

            # Update fields
            updated = False
            if new_title is not None:
                note.title = new_title
                updated = True
            if new_content is not None:
                note.content = new_content
                updated = True

            # Optional folder move
            if folder_id_arg is not None and folder_id_arg.lower() in ("root", "none", ""):
                note.folder_id = None
                updated = True
            elif folder_id_arg or folder_name_arg:
                resolved_folder_id, folder_err = _resolve_folder(
                    db, user_id, folder_id_arg, folder_name_arg
                )
                if folder_err:
                    return ToolResult(success=False, message=folder_err)
                note.folder_id = resolved_folder_id
                updated = True

            if not updated:
                return ToolResult(
                    success=False,
                    message="No changes provided"
                )
            
            # Re-embed the note
            full_text = f"{note.title}\n{note.content}" if note.title else note.content
            note.embedding = await get_embedding(full_text)
            note.updated_at = datetime.now(timezone.utc)
            
            db.commit()

            # Re-detect connections after edit
            try:
                from app.services.note_connector import process_note_connections_sync
                await process_note_connections_sync(
                    str(note.id), user_id, note.title or "", note.content or "", db
                )
            except Exception as conn_err:
                logger.warning(f"Connection detection failed for edited note: {conn_err}")

            return ToolResult(
                success=True,
                data={
                    "note_id": str(note.id),
                    "title": note.title,
                    "content": note.content,
                    "updated_at": note.updated_at.isoformat()
                },
                message=f"Updated note: {note.title or 'Untitled'}"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to edit note: {str(e)}"
            )
        finally:
            db.close()


class NotesDeleteTool(BaseTool):
    """Tool for deleting notes"""

    @property
    def name(self) -> str:
        return "notes_delete"

    @property
    def description(self) -> str:
        return "Delete a note by its ID. This action cannot be undone."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "The ID of the note to delete"
                }
            },
            "required": ["note_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Delete a note"""

        note_id = kwargs.get("note_id")

        if not note_id:
            return ToolResult(
                success=False,
                message="Note ID is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Find the note
            note = db.query(Note).filter(
                Note.id == note_id,
                Note.user_id == user_id
            ).first()

            if not note:
                return ToolResult(
                    success=False,
                    message="Note not found"
                )

            # Store title for response message
            note_title = note.title or "Untitled"

            # Delete the note
            db.delete(note)
            db.commit()

            return ToolResult(
                success=True,
                data={
                    "note_id": note_id,
                    "deleted_title": note_title
                },
                message=f"Deleted note: {note_title}"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to delete note: {str(e)}"
            )
        finally:
            db.close()


class NotesListTool(BaseTool):
    """Tool for listing all notes"""

    @property
    def name(self) -> str:
        return "notes_list"

    @property
    def description(self) -> str:
        return "List all notes for the user, optionally filtered by folder. Returns note IDs, titles, and preview of content."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "folder_id": {
                    "type": "string",
                    "description": "Optional folder ID to filter notes by folder"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of notes to return (default: 20)",
                    "default": 20
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """List all notes"""

        folder_id = kwargs.get("folder_id")
        limit = kwargs.get("limit", 20)

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Build query
            query = db.query(Note).filter(Note.user_id == user_id)

            if folder_id:
                query = query.filter(Note.folder_id == folder_id)

            # Order by most recent first
            query = query.order_by(Note.updated_at.desc()).limit(limit)

            notes = query.all()

            # Format results
            notes_list = []
            citations = []
            for note in notes:
                # Preview first 100 chars of content
                content_preview = note.content[:100] + "..." if len(note.content) > 100 else note.content

                notes_list.append({
                    "note_id": str(note.id),
                    "title": note.title or "Untitled",
                    "content_preview": content_preview,
                    "folder_id": note.folder_id,
                    "created_at": note.created_at.isoformat(),
                    "updated_at": note.updated_at.isoformat()
                })
                citations.append(f"note:{note.id}")

            return ToolResult(
                success=True,
                data={
                    "notes": notes_list,
                    "total": len(notes_list),
                    "folder_id": folder_id
                },
                message=f"Found {len(notes_list)} note(s)",
                citations=citations
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to list notes: {str(e)}"
            )
        finally:
            db.close()


class NotesFindSimilarTool(BaseTool):
    """Tool for finding semantically similar notes."""

    @property
    def name(self) -> str:
        return "find_similar_notes"

    @property
    def description(self) -> str:
        return (
            "Find notes that are semantically similar, useful for discovering "
            "redundancy or connections. Excludes journal entries."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "Optional: find notes similar to this specific note",
                },
                "threshold": {
                    "type": "number",
                    "description": "Minimum similarity (0.0-1.0, default 0.78)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 10)",
                },
            },
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        note_id = kwargs.get("note_id")
        threshold = kwargs.get("threshold", 0.78)
        limit = kwargs.get("limit", 10)

        db = next(get_db())
        try:
            if note_id:
                result = db.execute(
                    text("""
                        SELECT n2.id, n2.title, LEFT(n2.content, 200) AS preview,
                               1 - (n1.embedding <=> n2.embedding) AS similarity
                        FROM note n1
                        JOIN note n2 ON n2.user_id = n1.user_id
                            AND n2.id != n1.id
                            AND n2.embedding IS NOT NULL
                            AND n2.title NOT LIKE 'Sara''s Journal%%'
                        WHERE n1.id = :nid AND n1.embedding IS NOT NULL
                          AND 1 - (n1.embedding <=> n2.embedding) > :threshold
                        ORDER BY similarity DESC
                        LIMIT :lim
                    """),
                    {"nid": note_id, "threshold": threshold, "lim": limit},
                )
                notes = [
                    {
                        "note_id": str(r[0]),
                        "title": r[1],
                        "content_preview": r[2],
                        "similarity": round(float(r[3]), 3),
                    }
                    for r in result.fetchall()
                ]
            else:
                result = db.execute(
                    text("""
                        SELECT n1.id, n1.title, LEFT(n1.content, 200),
                               n2.id, n2.title, LEFT(n2.content, 200),
                               1 - (n1.embedding <=> n2.embedding) AS similarity
                        FROM note n1
                        JOIN note n2 ON n2.user_id = n1.user_id
                            AND n2.id > n1.id
                            AND n2.embedding IS NOT NULL
                            AND n2.title NOT LIKE 'Sara''s Journal%%'
                        WHERE n1.user_id = :uid
                          AND n1.embedding IS NOT NULL
                          AND n1.title NOT LIKE 'Sara''s Journal%%'
                          AND 1 - (n1.embedding <=> n2.embedding) > :threshold
                        ORDER BY similarity DESC
                        LIMIT :lim
                    """),
                    {"uid": user_id, "threshold": threshold, "lim": limit},
                )
                notes = [
                    {
                        "note_a": {"note_id": str(r[0]), "title": r[1], "preview": r[2]},
                        "note_b": {"note_id": str(r[3]), "title": r[4], "preview": r[5]},
                        "similarity": round(float(r[6]), 3),
                    }
                    for r in result.fetchall()
                ]

            return ToolResult(
                success=True,
                data={"results": notes, "total": len(notes)},
                message=f"Found {len(notes)} similar note{'s' if len(notes) != 1 else ''} (threshold={threshold})",
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to find similar notes: {e}")
        finally:
            db.close()


class NotesMergeTool(BaseTool):
    """Tool for merging two overlapping notes into one."""

    @property
    def name(self) -> str:
        return "merge_notes"

    @property
    def description(self) -> str:
        return (
            "Merge two overlapping notes. Transfers connections from source to target, "
            "deletes source, updates target with synthesized content."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target_note_id": {
                    "type": "string",
                    "description": "The note to keep (updated with merged content)",
                },
                "source_note_id": {
                    "type": "string",
                    "description": "The note to merge in and delete",
                },
                "merged_title": {
                    "type": "string",
                    "description": "Optional new title for the merged note",
                },
                "merged_content": {
                    "type": "string",
                    "description": "Synthesized content combining both notes",
                },
            },
            "required": ["target_note_id", "source_note_id", "merged_content"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        target_id = kwargs.get("target_note_id", "")
        source_id = kwargs.get("source_note_id", "")
        merged_title = kwargs.get("merged_title")
        merged_content = kwargs.get("merged_content", "")

        if not target_id or not source_id or not merged_content:
            return ToolResult(
                success=False,
                message="target_note_id, source_note_id, and merged_content are required",
            )

        db = next(get_db())
        try:
            # Verify both notes exist
            target = db.query(Note).filter(Note.id == target_id, Note.user_id == user_id).first()
            source = db.query(Note).filter(Note.id == source_id, Note.user_id == user_id).first()
            if not target:
                return ToolResult(success=False, message=f"Target note {target_id} not found")
            if not source:
                # Source already deleted (likely merged in a previous call) — skip gracefully
                return ToolResult(
                    success=True,
                    message=f"Source note {source_id} already deleted or merged — nothing to do. Move on to the next pair.",
                )

            source_title = source.title

            # Transfer connections from source to target
            db.execute(
                text("""
                    UPDATE note_connection
                    SET source_note_id = :tid, updated_at = NOW()
                    WHERE source_note_id = :sid AND user_id = :uid
                      AND target_note_id != :tid
                      AND NOT EXISTS (
                          SELECT 1 FROM note_connection nc2
                          WHERE nc2.source_note_id = :tid
                            AND nc2.target_note_id = note_connection.target_note_id
                            AND nc2.connection_type = note_connection.connection_type
                      )
                """),
                {"tid": target_id, "sid": source_id, "uid": user_id},
            )
            db.execute(
                text("""
                    UPDATE note_connection
                    SET target_note_id = :tid, updated_at = NOW()
                    WHERE target_note_id = :sid AND user_id = :uid
                      AND source_note_id != :tid
                      AND NOT EXISTS (
                          SELECT 1 FROM note_connection nc2
                          WHERE nc2.target_note_id = :tid
                            AND nc2.source_note_id = note_connection.source_note_id
                            AND nc2.connection_type = note_connection.connection_type
                      )
                """),
                {"tid": target_id, "sid": source_id, "uid": user_id},
            )

            # Delete source note
            db.delete(source)

            # Update target
            if merged_title:
                target.title = merged_title
            target.content = merged_content
            target.updated_at = datetime.now(timezone.utc)

            # Re-embed
            full_text = f"{target.title}\n{merged_content}" if target.title else merged_content
            target.embedding = await get_embedding(full_text)

            db.commit()

            # Detect new connections
            try:
                from app.services.note_connector import process_note_connections_sync
                await process_note_connections_sync(
                    target_id, user_id, target.title or "", merged_content, db
                )
            except Exception as e:
                logger.warning(f"Connection detection after merge failed: {e}")

            return ToolResult(
                success=True,
                data={
                    "merged_note_id": target_id,
                    "title": target.title,
                    "deleted_source": source_title,
                },
                message=f"Merged '{source_title}' into '{target.title}'",
            )
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to merge notes: {e}")
        finally:
            db.close()


class NotesListFoldersTool(BaseTool):
    """Tool for listing the user's note folders."""

    @property
    def name(self) -> str:
        return "notes_list_folders"

    @property
    def description(self) -> str:
        return (
            "List the folders in the knowledge garden, with their IDs, full paths, "
            "and note counts. Use this to discover folder IDs before filing or listing "
            "notes in a folder."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            folders = db.query(Folder).filter(
                Folder.user_id == user_id
            ).order_by(Folder.name).all()

            # Build id->name map for path resolution
            by_id = {f.id: f for f in folders}

            def full_path(folder: Folder) -> str:
                parts = [folder.name]
                seen = {folder.id}
                parent_id = folder.parent_id
                while parent_id and parent_id in by_id and parent_id not in seen:
                    seen.add(parent_id)
                    parent = by_id[parent_id]
                    parts.append(parent.name)
                    parent_id = parent.parent_id
                return "/" + "/".join(reversed(parts))

            folder_list = []
            for f in folders:
                note_count = db.query(Note).filter(Note.folder_id == f.id).count()
                folder_list.append({
                    "folder_id": f.id,
                    "name": f.name,
                    "path": full_path(f),
                    "parent_id": f.parent_id,
                    "notes_count": note_count,
                })

            return ToolResult(
                success=True,
                data={"folders": folder_list, "total": len(folder_list)},
                message=(
                    f"Found {len(folder_list)} folder(s)"
                    if folder_list else
                    "No folders yet — the knowledge garden has no folders. Use notes_create_folder to make one."
                ),
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to list folders: {e}")
        finally:
            db.close()


class NotesCreateFolderTool(BaseTool):
    """Tool for creating a note folder."""

    @property
    def name(self) -> str:
        return "notes_create_folder"

    @property
    def description(self) -> str:
        return (
            "Create a new folder in the knowledge garden. Optionally nest it under an "
            "existing parent folder. Returns the new folder's ID so notes can be filed into it. "
            "If a folder with the same name already exists under the same parent, the existing "
            "one is returned instead of creating a duplicate."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the new folder",
                },
                "parent_folder_name": {
                    "type": "string",
                    "description": "Optional name of an existing folder to nest this one under",
                },
                "parent_folder_id": {
                    "type": "string",
                    "description": "Optional explicit parent folder ID (prefer parent_folder_name)",
                },
            },
            "required": ["name"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        name = (kwargs.get("name") or "").strip()
        parent_id_arg = kwargs.get("parent_folder_id")
        parent_name_arg = kwargs.get("parent_folder_name")

        if not name:
            return ToolResult(success=False, message="Folder name is required")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            # Resolve parent folder if requested
            parent_id, parent_err = _resolve_folder(
                db, user_id, parent_id_arg, parent_name_arg
            )
            if parent_err:
                return ToolResult(success=False, message=parent_err)

            # Dedupe: same name under same parent → return existing
            existing = db.query(Folder).filter(
                Folder.user_id == user_id,
                Folder.name.ilike(name),
                Folder.parent_id == parent_id,
            ).first()
            if existing:
                return ToolResult(
                    success=True,
                    data={
                        "folder_id": existing.id,
                        "name": existing.name,
                        "parent_id": existing.parent_id,
                        "already_existed": True,
                    },
                    message=f"Folder '{name}' already exists — using it.",
                )

            folder = Folder(name=name, parent_id=parent_id, user_id=user_id)
            db.add(folder)
            db.commit()
            db.refresh(folder)

            return ToolResult(
                success=True,
                data={
                    "folder_id": folder.id,
                    "name": folder.name,
                    "parent_id": folder.parent_id,
                    "already_existed": False,
                },
                message=f"Created folder: {name}",
            )
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to create folder: {e}")
        finally:
            db.close()