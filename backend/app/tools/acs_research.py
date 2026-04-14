"""
Tool for queuing research topics for Sara's autonomous exploration (ACS).

When David says "look into X in your free time" or similar, Sara calls this
tool to create a high-fascination interest node marked as a David request,
ensuring it gets prioritized in the next exploration session.
"""

import logging
from typing import Any, Dict

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class QueueResearchTopicTool(BaseTool):
    """Queue a topic for Sara to explore during autonomous time."""

    @property
    def name(self) -> str:
        return "queue_research_topic"

    @property
    def description(self) -> str:
        return (
            "Queue a topic for Sara to research during her autonomous free time (ACS). "
            "Use when David asks Sara to look into something later, explore a topic in "
            "her free time, or investigate something when she has a chance. Creates a "
            "high-priority interest node that Sara will pick up in her next exploration session."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Short label for the topic (e.g. 'Rust async runtimes')",
                },
                "description": {
                    "type": "string",
                    "description": "What specifically to explore — context, angles, what David is curious about",
                },
                "depth_hint": {
                    "type": "string",
                    "enum": ["surface", "moderate", "deep"],
                    "description": "How deep David wants the exploration (default: moderate)",
                },
            },
            "required": ["topic", "description"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        topic = kwargs.get("topic", "").strip()
        description = kwargs.get("description", "").strip()
        depth_hint = kwargs.get("depth_hint", "moderate")

        if not topic:
            return ToolResult(success=False, message="Topic is required")
        if not description:
            return ToolResult(success=False, message="Description is required")

        try:
            from app.services.acs.interest_graph import InterestGraph

            graph = InterestGraph()

            # David-requested topics get high fascination so they're prioritized
            fascination = {"surface": 0.7, "moderate": 0.85, "deep": 0.95}.get(depth_hint, 0.85)

            source_detail = f"David asked Sara to explore this (depth: {depth_hint})"

            result = await graph.add_node(
                user_id=user_id,
                label=topic,
                description=description,
                source="david_request",
                fascination=fascination,
                source_detail=source_detail,
            )

            if not result:
                return ToolResult(
                    success=False,
                    message="Failed to create interest node",
                )

            merged = result.get("merged", False)
            node_id = result.get("id")

            if merged:
                message = (
                    f"Boosted existing interest in '{result.get('label', topic)}' — "
                    f"I'll prioritize this in my next exploration session."
                )
            else:
                message = (
                    f"Queued '{topic}' for autonomous exploration ({depth_hint} depth). "
                    f"I'll dig into this next time I have free time."
                )

            return ToolResult(
                success=True,
                data={
                    "node_id": node_id,
                    "topic": result.get("label", topic),
                    "fascination": result.get("fascination", fascination),
                    "depth_hint": depth_hint,
                    "merged": merged,
                },
                message=message,
            )

        except Exception as e:
            logger.error(f"Failed to queue research topic: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to queue research topic: {e}",
            )


ACS_RESEARCH_TOOLS = [QueueResearchTopicTool()]
