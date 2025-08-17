from typing import Dict, Any
from app.tools.base import BaseTool, ToolResult
from app.models.note import Note
from app.services.embeddings import get_embedding
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import text
import uuid
from datetime import datetime, timezone


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
                }
            },
            "required": ["content"]
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Create a new note"""
        
        title = kwargs.get("title", "")
        content = kwargs.get("content")
        
        if not content:
            return ToolResult(
                success=False,
                message="Note content is required"
            )
        
        db_gen = get_db()
        db: Session = next(db_gen)
        
        try:
            # Get embedding for the note
            full_text = f"{title}\n{content}" if title else content
            embedding = await get_embedding(full_text)
            
            # Create note
            note = Note(
                user_id=user_id,
                title=title,
                content=content,
                embedding=embedding
            )
            
            db.add(note)
            db.commit()
            db.refresh(note)
            
            return ToolResult(
                success=True,
                data={
                    "note_id": str(note.id),
                    "title": note.title,
                    "content": note.content,
                    "created_at": note.created_at.isoformat()
                },
                message=f"Created note: {title or 'Untitled'}"
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
        """Search notes"""
        
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
            # Get query embedding
            query_embedding = await get_embedding(query)
            
            # Search using vector similarity
            sql = text("""
                SELECT 
                    id, title, content, created_at, updated_at,
                    (1 - (embedding <=> :query_embedding)) as similarity
                FROM note
                WHERE user_id = :user_id AND embedding IS NOT NULL
                ORDER BY (embedding <=> :query_embedding)
                LIMIT :limit
            """)
            
            result = db.execute(sql, {
                "query_embedding": str(query_embedding),
                "user_id": user_id,
                "limit": limit
            })
            
            notes = []
            citations = []
            for row in result.fetchall():
                notes.append({
                    "note_id": str(row.id),
                    "title": row.title,
                    "content": row.content,
                    "similarity": round(row.similarity, 3),
                    "created_at": row.created_at.isoformat(),
                    "updated_at": row.updated_at.isoformat()
                })
                citations.append(f"note:{row.id}")
            
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
                }
            },
            "required": ["note_id"]
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Edit an existing note"""
        
        note_id = kwargs.get("note_id")
        new_title = kwargs.get("title")
        new_content = kwargs.get("content")
        
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