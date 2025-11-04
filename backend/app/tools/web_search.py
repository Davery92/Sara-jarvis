from typing import Any, Dict
import json
import uuid
from app.tools.base import BaseTool, ToolResult
from app.services.search_service import search_service


class WebSearchTool(BaseTool):
    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web using SearXNG. Returns a compact summary with top 5 results (title, URL, 200-char snippet). "
            "This summary is usually sufficient to answer most questions. Full details are stored temporarily if needed later."
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
        # Convert max_results to int if it's a string (LLM sometimes sends "8" instead of 8)
        if isinstance(max_results, str):
            max_results = int(max_results)

        if not query:
            return ToolResult(success=False, message="Query is required")

        try:
            # Get full search results
            result = await search_service.web_search(
                query=query, recency=recency, sites=sites, max_results=max_results
            )

            # Generate reference ID for storage
            reference_id = str(uuid.uuid4())

            # Store full results in Redis with 5 minute TTL
            if search_service.redis:
                cache_key = f"websearch_details:{reference_id}"
                await search_service.redis.set(
                    cache_key,
                    json.dumps(result),
                    ex=300  # 5 minutes
                )

            # Create compact summary with top 3-5 results
            results = result.get("results", [])
            top_results = results[:5]  # Top 5 for summary

            # Build compact data payload
            compact_data = {
                "query": query,
                "recency": recency,
                "result_count": len(results),
                "reference_id": reference_id,
                "results_summary": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("snippet", "")[:200]  # Truncate snippet to 200 chars
                    }
                    for r in top_results
                ],
                "note": "Full details available via get_web_search_details tool with reference_id"
            }

            return ToolResult(
                success=True,
                data=compact_data,
                message=f"Found {len(results)} results for '{query}' (showing top {len(top_results)} summaries, full details stored: {reference_id})",
                citations=[r.get("url") for r in top_results if r.get("url")],
            )
        except Exception as e:
            return ToolResult(success=False, message=f"web_search failed: {e}")

