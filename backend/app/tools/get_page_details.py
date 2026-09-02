from typing import Any, Dict
from app.tools.base import BaseTool, ToolResult
from app.services.search_service import search_service


class GetPageDetailsTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_page_details"

    @property
    def description(self) -> str:
        return (
            "Retrieve full page content from a previous open_page call using its reference ID. "
            "ONLY use this if the 500-char preview from open_page was insufficient to answer the question. "
            "The preview usually contains enough information - avoid calling this unless truly necessary."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reference_id": {
                    "type": "string",
                    "description": "The reference ID from a previous open_page call"
                }
            },
            "required": ["reference_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        reference_id = kwargs.get("reference_id")

        if not reference_id:
            return ToolResult(
                success=False,
                message="reference_id is required"
            )

        try:
            cache_key = f"page_details:{reference_id}"
            full_page_data = await search_service.cache_get_json(cache_key)

            if full_page_data is None:
                return ToolResult(
                    success=False,
                    message=f"Page content not found or expired for reference_id: {reference_id}. "
                            "Page content is stored for 5 minutes after the original fetch."
                )

            # Normalize: ensure 'content' key exists for Sara to use
            if "plain_text" in full_page_data and "content" not in full_page_data:
                full_page_data["content"] = full_page_data["plain_text"]

            # Also ensure text key exists for backwards compat
            if "plain_text" in full_page_data and "text" not in full_page_data:
                full_page_data["text"] = full_page_data["plain_text"]

            # Phase 11B: this is arbitrary fetched web content — frame it untrusted.
            from app.core.untrusted import wrap_untrusted
            _src = f"the web page {full_page_data.get('url', 'a fetched URL')}"
            for _k in ("content", "text", "plain_text"):
                if full_page_data.get(_k):
                    full_page_data[_k] = wrap_untrusted(full_page_data[_k], source=_src)

            return ToolResult(
                success=True,
                data=full_page_data,
                message=f"Retrieved full page content for reference_id: {reference_id} ({len(full_page_data.get('plain_text', ''))} chars)"
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"get_page_details failed: {e}"
            )
