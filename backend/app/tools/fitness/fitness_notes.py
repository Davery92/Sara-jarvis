"""
Fitness Notes Tools
Tools for creating, searching, and managing fitness-specific notes
"""
from typing import Dict, Any
from app.tools.base import BaseTool, ToolResult
from sqlalchemy import create_engine, Column, String, DateTime, Text, select, text
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import uuid
import os

try:
    from pgvector.sqlalchemy import Vector
    PGVECTOR_AVAILABLE = True
except ImportError:
    PGVECTOR_AVAILABLE = False

# Import embedding service
try:
    from app.services.embeddings import get_embedding
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False


def get_fitness_db():
    """Get database session"""
    from app.db.session import get_db
    return next(get_db())


class FitnessNoteCreateTool(BaseTool):
    """Create fitness-specific notes with category tagging"""

    @property
    def name(self) -> str:
        return "fitness_note_create"

    @property
    def description(self) -> str:
        return "Create a fitness note with title, content, and category. Categories: nutrition, workout, goal, progress, general. Notes are automatically embedded for semantic search."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title for the note"
                },
                "content": {
                    "type": "string",
                    "description": "The note content"
                },
                "category": {
                    "type": "string",
                    "description": "Note category",
                    "enum": ["nutrition", "workout", "goal", "progress", "general"]
                }
            },
            "required": ["content", "category"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Create a new fitness note"""
        title = kwargs.get("title", "")
        content = kwargs.get("content")
        category = kwargs.get("category", "general")

        if not content:
            return ToolResult(
                success=False,
                message="Note content is required"
            )

        db = get_fitness_db()

        try:
            # Get embedding if available
            embedding = None
            if EMBEDDINGS_AVAILABLE:
                full_text = f"{title}\n{content}" if title else content
                embedding = await get_embedding(full_text)

            # Create note
            note_id = str(uuid.uuid4())
            stmt = text("""
                INSERT INTO fitness_note (id, user_id, title, content, category, embedding, created_at, updated_at)
                VALUES (:id, :user_id, :title, :content, :category, :embedding, NOW(), NOW())
                RETURNING id, created_at
            """)

            result = db.execute(stmt, {
                "id": note_id,
                "user_id": user_id,
                "title": title,
                "content": content,
                "category": category,
                "embedding": str(embedding) if embedding else None
            })
            db.commit()

            row = result.fetchone()

            return ToolResult(
                success=True,
                data={
                    "note_id": note_id,
                    "title": title,
                    "content": content,
                    "category": category,
                    "created_at": row.created_at.isoformat() if row.created_at else None
                },
                message=f"Created fitness note: {title or 'Untitled'} ({category})"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to create fitness note: {str(e)}"
            )
        finally:
            db.close()


class FitnessNoteSearchTool(BaseTool):
    """Search fitness notes by query and category"""

    @property
    def name(self) -> str:
        return "fitness_note_search"

    @property
    def description(self) -> str:
        return "Search through fitness notes using keywords or semantic similarity. Optionally filter by category."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category",
                    "enum": ["nutrition", "workout", "goal", "progress", "general", "all"]
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default: 10)",
                    "default": 10
                }
            },
            "required": ["query"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Search fitness notes"""
        query = kwargs.get("query")
        category = kwargs.get("category", "all")
        limit = kwargs.get("limit", 10)

        if not query:
            return ToolResult(
                success=False,
                message="Search query is required"
            )

        db = get_fitness_db()

        try:
            if EMBEDDINGS_AVAILABLE and PGVECTOR_AVAILABLE:
                # Semantic search with embeddings
                query_embedding = await get_embedding(query)

                category_filter = ""
                if category != "all":
                    category_filter = "AND category = :category"

                sql = text(f"""
                    SELECT
                        id, title, content, category, created_at, updated_at,
                        (1 - (embedding <=> :query_embedding)) as similarity
                    FROM fitness_note
                    WHERE user_id = :user_id AND embedding IS NOT NULL {category_filter}
                    ORDER BY (embedding <=> :query_embedding)
                    LIMIT :limit
                """)

                params = {
                    "query_embedding": str(query_embedding),
                    "user_id": user_id,
                    "limit": limit
                }
                if category != "all":
                    params["category"] = category

                result = db.execute(sql, params)
            else:
                # Fallback to text search
                category_filter = ""
                if category != "all":
                    category_filter = "AND category = :category"

                sql = text(f"""
                    SELECT id, title, content, category, created_at, updated_at, 0.5 as similarity
                    FROM fitness_note
                    WHERE user_id = :user_id
                    AND (title ILIKE :query OR content ILIKE :query) {category_filter}
                    ORDER BY created_at DESC
                    LIMIT :limit
                """)

                params = {
                    "query": f"%{query}%",
                    "user_id": user_id,
                    "limit": limit
                }
                if category != "all":
                    params["category"] = category

                result = db.execute(sql, params)

            notes = []
            citations = []
            for row in result.fetchall():
                notes.append({
                    "note_id": row.id,
                    "title": row.title,
                    "content": row.content,
                    "category": row.category,
                    "similarity": round(row.similarity, 3) if hasattr(row, 'similarity') else 0.5,
                    "created_at": row.created_at.isoformat() if row.created_at else None
                })
                citations.append(f"fitness_note:{row.id}")

            return ToolResult(
                success=True,
                data={
                    "notes": notes,
                    "query": query,
                    "category": category,
                    "total_found": len(notes)
                },
                message=f"Found {len(notes)} fitness note(s) matching '{query}'",
                citations=citations
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Fitness note search failed: {str(e)}"
            )
        finally:
            db.close()


class FitnessNoteEditTool(BaseTool):
    """Edit existing fitness notes"""

    @property
    def name(self) -> str:
        return "fitness_note_edit"

    @property
    def description(self) -> str:
        return "Edit an existing fitness note's title, content, or category. The note will be re-embedded after editing."

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
                    "description": "New title"
                },
                "content": {
                    "type": "string",
                    "description": "New content"
                },
                "category": {
                    "type": "string",
                    "description": "New category",
                    "enum": ["nutrition", "workout", "goal", "progress", "general"]
                }
            },
            "required": ["note_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Edit an existing fitness note"""
        note_id = kwargs.get("note_id")
        new_title = kwargs.get("title")
        new_content = kwargs.get("content")
        new_category = kwargs.get("category")

        if not note_id:
            return ToolResult(
                success=False,
                message="Note ID is required"
            )

        db = get_fitness_db()

        try:
            # Get current note
            get_stmt = text("""
                SELECT id, title, content, category
                FROM fitness_note
                WHERE id = :note_id AND user_id = :user_id
            """)
            result = db.execute(get_stmt, {"note_id": note_id, "user_id": user_id})
            note = result.fetchone()

            if not note:
                return ToolResult(
                    success=False,
                    message="Fitness note not found"
                )

            # Build update statement
            updates = []
            params = {"note_id": note_id, "user_id": user_id}

            if new_title is not None:
                updates.append("title = :title")
                params["title"] = new_title
            else:
                new_title = note.title

            if new_content is not None:
                updates.append("content = :content")
                params["content"] = new_content
            else:
                new_content = note.content

            if new_category is not None:
                updates.append("category = :category")
                params["category"] = new_category
            else:
                new_category = note.category

            if not updates:
                return ToolResult(
                    success=False,
                    message="No changes provided"
                )

            # Re-embed if content or title changed
            if EMBEDDINGS_AVAILABLE and (new_title != note.title or new_content != note.content):
                full_text = f"{new_title}\n{new_content}" if new_title else new_content
                embedding = await get_embedding(full_text)
                updates.append("embedding = :embedding")
                params["embedding"] = str(embedding)

            updates.append("updated_at = NOW()")

            update_stmt = text(f"""
                UPDATE fitness_note
                SET {', '.join(updates)}
                WHERE id = :note_id AND user_id = :user_id
                RETURNING updated_at
            """)

            result = db.execute(update_stmt, params)
            db.commit()
            row = result.fetchone()

            return ToolResult(
                success=True,
                data={
                    "note_id": note_id,
                    "title": new_title,
                    "content": new_content,
                    "category": new_category,
                    "updated_at": row.updated_at.isoformat() if row and row.updated_at else None
                },
                message=f"Updated fitness note: {new_title or 'Untitled'}"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to edit fitness note: {str(e)}"
            )
        finally:
            db.close()
