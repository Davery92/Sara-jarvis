from typing import Any, Dict
from app.tools.base import BaseTool, ToolResult
from app.services.search_service import search_service


class OpenPageTool(BaseTool):
    @property
    def name(self) -> str:
        return "open_page"

    @property
    def description(self) -> str:
        return (
            "Open a web page and return a clean, readable view with extracted title, plain text, and readable HTML."
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
            data = await search_service.open_page(url)
            return ToolResult(success=True, data=data, message=f"Opened page: {data.get('title') or url}")
        except Exception as e:
            return ToolResult(success=False, message=f"open_page failed: {e}")

