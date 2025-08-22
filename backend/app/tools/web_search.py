from typing import Any, Dict
from app.tools.base import BaseTool, ToolResult
from app.services.search_service import search_service


class WebSearchTool(BaseTool):
    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web using SearXNG and return compact, reranked results with title, URL, snippet, source, and published date."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "recency": {
                    "type": "string",
                    "enum": ["any", "day", "week", "month"],
                    "description": "Result freshness preference",
                    "default": "any",
                },
                "sites": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional site filters (e.g., 'docs.python.org')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return",
                    "default": 8,
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["query"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        query = kwargs.get("query")
        recency = kwargs.get("recency")
        if recency == "any":
            recency = None
        sites = kwargs.get("sites")
        max_results = kwargs.get("max_results", 8)

        if not query:
            return ToolResult(success=False, message="Query is required")

        try:
            result = await search_service.web_search(
                query=query, recency=recency, sites=sites, max_results=max_results
            )
            return ToolResult(
                success=True,
                data=result,
                message=f"Found {len(result.get('results', []))} results for '{query}'",
                citations=[r.get("url") for r in result.get("results", [])[:5] if r.get("url")],
            )
        except Exception as e:
            return ToolResult(success=False, message=f"web_search failed: {e}")

