from typing import Any, Dict
import uuid
from app.tools.base import BaseTool, ToolResult
from app.services.search_service import search_service


class OpenPageTool(BaseTool):
    @property
    def name(self) -> str:
        return "open_page"

    @property
    def description(self) -> str:
        return (
            "Open a web page and return a compact summary with title and first 500 chars of content. "
            "This preview is usually sufficient for most questions. Full page content is stored if needed later."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to open"}
            },
            "required": ["url"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        url = kwargs.get("url")
        if not url:
            return ToolResult(success=False, message="URL is required")

        try:
            # Get full page data
            data = await search_service.open_page(url)

            # Generate reference ID for storage
            reference_id = str(uuid.uuid4())

            # Best-effort storage: fetching a page still succeeds if Redis is
            # unavailable or its full-detail cache write fails.
            cache_key = f"page_details:{reference_id}"
            details_cached = await search_service.cache_set_json(
                cache_key, data, ttl_seconds=300
            )

            # Create compact summary
            title = data.get("title", "")
            text = data.get("plain_text", "") or data.get("text", "")

            # Truncate text to first 500 characters for summary
            text_preview = text[:500] + "..." if len(text) > 500 else text
            # Phase 11B: fetched web content is untrusted — frame it as data so a
            # crafted page can't inject instructions into Sara's tool-using loop.
            from app.core.untrusted import wrap_untrusted
            text_preview = wrap_untrusted(text_preview, source=f"the web page {url}")

            compact_data = {
                "title": title,
                "url": url,
                "text_preview": text_preview,
                "full_text_length": len(text),
                "reference_id": reference_id,
                "note": (
                    "Full page content available via get_page_details tool with reference_id"
                    if details_cached
                    else "Full-detail cache unavailable; preview remains valid"
                )
            }

            return ToolResult(
                success=True,
                data=compact_data,
                message=(
                    f"Opened page: {title or url} (showing 500 char preview, "
                    f"full content: {len(text)} chars"
                    + (f", stored: {reference_id})" if details_cached else ")")
                ),
                citations=[url]
            )
        except Exception as e:
            return ToolResult(success=False, message=f"open_page failed: {e}")

