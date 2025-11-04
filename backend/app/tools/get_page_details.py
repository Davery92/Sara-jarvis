from typing import Any, Dict
import json
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
            # Retrieve from Redis
            if not search_service.redis:
                return ToolResult(
                    success=False,
                    message="Redis not available for retrieving page details"
                )

            cache_key = f"page_details:{reference_id}"
            cached_data = await search_service.redis.get(cache_key)

            if not cached_data:
                return ToolResult(
                    success=False,
                    message=f"Page content not found or expired for reference_id: {reference_id}. "
                            "Page content is stored for 5 minutes after the original fetch."
                )

            # Parse and return full page data
            full_page_data = json.loads(cached_data)

            return ToolResult(
                success=True,
                data=full_page_data,
                message=f"Retrieved full page content for reference_id: {reference_id}"
            )

        except json.JSONDecodeError as e:
            return ToolResult(
                success=False,
                message=f"Failed to parse stored page content: {e}"
            )
        except Exception as e:
            return ToolResult(
                success=False,
                message=f"get_page_details failed: {e}"
            )
