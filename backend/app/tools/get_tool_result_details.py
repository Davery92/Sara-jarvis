"""`get_tool_result_details` — paged access to a tool result too big to inline.

Phase 3 of SARA_CHAT_HARNESS_REBUILD_PLAN_2026_09_11. The old
`_budget_tool_responses` truncated big results in place: on 2026-09-11
`get_self_knowledge(capabilities)` returned 23,430 chars and the model was
handed 1,403 of them with no way to ask for the rest, so it went to
`web_search` to look up its own capabilities. Now oversized results are parked
in Redis and the model gets a preview plus a reference it can page through.
"""

from typing import Any, Dict

from app.tools.base import BaseTool, ToolResult
from app.services.search_service import search_service

# Shared with main_simple.py's tool-result budgeter.
CACHE_PREFIX = "tool_result:"
CACHE_TTL_SECONDS = 1800
DEFAULT_LENGTH = 6000
MAX_LENGTH = 12000


class GetToolResultDetailsTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_tool_result_details"

    @property
    def description(self) -> str:
        return (
            "Read more of a tool result that was too large to show in full. Pass the "
            "`reference_id` from that result, plus `offset` (characters already read) "
            "and `length`. Use it when the preview cut off something you actually need "
            "— not reflexively; the preview is usually enough."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reference_id": {
                    "type": "string",
                    "description": "The reference_id carried by the truncated tool result.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Character offset to start from (default 0).",
                },
                "length": {
                    "type": "integer",
                    "description": f"How many characters to read (default {DEFAULT_LENGTH}).",
                },
            },
            "required": ["reference_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        reference_id = (kwargs.get("reference_id") or "").strip()
        if not reference_id:
            return ToolResult(success=False, message="reference_id is required.")

        try:
            offset = max(0, int(kwargs.get("offset") or 0))
        except (TypeError, ValueError):
            offset = 0
        try:
            length = int(kwargs.get("length") or DEFAULT_LENGTH)
        except (TypeError, ValueError):
            length = DEFAULT_LENGTH
        length = max(200, min(length, MAX_LENGTH))

        payload = await search_service.cache_get_json(CACHE_PREFIX + reference_id)
        if payload is None:
            return ToolResult(
                success=False,
                message=(
                    f"No stored result for reference_id {reference_id} (they expire after "
                    "30 minutes). Re-run the original tool with a narrower query."
                ),
            )

        text = payload if isinstance(payload, str) else str(payload)
        total = len(text)
        chunk = text[offset: offset + length]
        next_offset = offset + len(chunk)
        more = next_offset < total

        return ToolResult(
            success=True,
            data={
                "reference_id": reference_id,
                "offset": offset,
                "next_offset": next_offset if more else None,
                "total_chars": total,
                "has_more": more,
                "content": chunk,
            },
            message=(
                f"Read {len(chunk)} of {total} chars"
                + (f"; call again with offset={next_offset} for more." if more else " (end of result).")
            ),
        )


GET_TOOL_RESULT_DETAILS_TOOLS = [GetToolResultDetailsTool()]
