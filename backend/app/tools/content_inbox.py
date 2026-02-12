"""
Content Inbox Tools for Sara's Chat
Allows Sara to search and read items from David's content inbox.
"""
from typing import Dict, Any

from app.tools.base import BaseTool, ToolResult


class InboxSearchTool(BaseTool):
    """Semantic search across David's saved inbox items."""

    @property
    def name(self) -> str:
        return "inbox_search"

    @property
    def description(self) -> str:
        return (
            "Search David's content inbox by topic or keyword. Finds saved URLs, "
            "Reddit posts, PDFs, and text snippets using semantic similarity. "
            "Use when David asks 'what did I save about X' or 'find that article about Y'."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — topic, keyword, or question about saved content"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            from app.services.content_inbox_service import content_inbox_service
            from app.db.session import SessionLocal

            query = kwargs.get("query", "")
            limit = kwargs.get("limit", 5)

            db = SessionLocal()
            try:
                results = await content_inbox_service.search_inbox(
                    db=db, user_id=user_id, query=query, limit=limit
                )
            finally:
                db.close()

            if not results:
                return ToolResult(
                    success=True,
                    message="No matching items found in the inbox.",
                    data={"items": []}
                )

            formatted = []
            for r in results:
                formatted.append(
                    f"- **{r['title']}** ({r['content_type']}) — "
                    f"{r.get('description', '')[:100]}... "
                    f"[{r['status']}] (similarity: {r['similarity']})"
                )

            return ToolResult(
                success=True,
                message=f"Found {len(results)} inbox items matching '{query}'.",
                data={"items": results, "formatted": "\n".join(formatted)}
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Inbox search failed: {str(e)}")


class InboxReadTool(BaseTool):
    """Read the full extracted content of a specific inbox item."""

    @property
    def name(self) -> str:
        return "inbox_read"

    @property
    def description(self) -> str:
        return (
            "Load the full extracted content of a specific inbox item by ID. "
            "Use when Sara needs to read an article, Reddit post, or document "
            "that David previously saved. Returns the full text and metadata."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "The ID of the inbox item to read"
                }
            },
            "required": ["item_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            from app.db.session import SessionLocal
            from app.models.shared_content import SharedContent

            item_id = kwargs.get("item_id", "")
            if not item_id:
                return ToolResult(success=False, message="item_id is required")

            db = SessionLocal()
            try:
                item = db.query(SharedContent).filter(
                    SharedContent.id == item_id,
                    SharedContent.user_id == user_id,
                ).first()

                if not item:
                    return ToolResult(success=False, message="Item not found")

                if item.extraction_status != "extracted":
                    return ToolResult(
                        success=True,
                        message=f"Item exists but extraction is {item.extraction_status}.",
                        data={"title": item.title, "extraction_status": item.extraction_status}
                    )

                # Truncate very long texts for tool context
                text = item.extracted_text or ""
                if len(text) > 8000:
                    text = text[:8000] + "\n\n[... truncated ...]"

                return ToolResult(
                    success=True,
                    message=f"Read inbox item: {item.title}",
                    data={
                        "id": item.id,
                        "title": item.title,
                        "content_type": item.content_type,
                        "original_url": item.original_url,
                        "extracted_text": text,
                        "meta": item.meta or {},
                        "word_count": item.word_count,
                        "status": item.status,
                    }
                )
            finally:
                db.close()

        except Exception as e:
            return ToolResult(success=False, message=f"Failed to read inbox item: {str(e)}")


# Export for registry
CONTENT_INBOX_TOOLS = [
    InboxSearchTool(),
    InboxReadTool(),
]
