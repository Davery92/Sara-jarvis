from typing import Any, Dict
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
            cache_key = f"websearch_details:{reference_id}"
            full_results = await search_service.cache_get_json(cache_key)

            if full_results is None:
                return ToolResult(
                    success=False,
                    message=f"Search results not found or expired for reference_id: {reference_id}. "
                            "Results are stored for 5 minutes after the original search."
                )

            return ToolResult(
                success=True,
                data=full_results,
                message=f"Retrieved full search results for reference_id: {reference_id}",
                citations=[r.get("url") for r in full_results.get("results", []) if r.get("url")]
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"get_web_search_details failed: {e}"
            )
