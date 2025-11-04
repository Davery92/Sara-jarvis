from typing import Any, Dict
import json
from app.tools.base import BaseTool, ToolResult
from app.services.search_service import search_service


class GetWebSearchDetailsTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_web_search_details"

    @property
    def description(self) -> str:
        return (
            "Retrieve full details of a previous web search using its reference ID. "
            "ONLY use this if the compact summary from web_search was insufficient to answer the user's question. "
            "The summary usually contains enough information - avoid calling this unless truly necessary."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reference_id": {
                    "type": "string",
                    "description": "The reference ID from a previous web_search call"
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
            # Retrieve from Redis
            if not search_service.redis:
                return ToolResult(
                    success=False,
                    message="Redis not available for retrieving search details"
                )

            cache_key = f"websearch_details:{reference_id}"
            cached_data = await search_service.redis.get(cache_key)

            if not cached_data:
                return ToolResult(
                    success=False,
                    message=f"Search results not found or expired for reference_id: {reference_id}. "
                            "Results are stored for 5 minutes after the original search."
                )

            # Parse and return full results
            full_results = json.loads(cached_data)

            return ToolResult(
                success=True,
                data=full_results,
                message=f"Retrieved full search results for reference_id: {reference_id}",
                citations=[r.get("url") for r in full_results.get("results", []) if r.get("url")]
            )

        except json.JSONDecodeError as e:
            return ToolResult(
                success=False,
                message=f"Failed to parse stored search results: {e}"
            )
        except Exception as e:
            return ToolResult(
                success=False,
                message=f"get_web_search_details failed: {e}"
            )
