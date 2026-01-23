"""
Self-Knowledge Tool for Sara

Provides Sara with access to her own architecture, capabilities, and limitations documentation.
This enables accurate self-awareness when reasoning about what she can do.
"""

import os
import logging
from typing import Dict, Any, Literal
from pathlib import Path

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Path to self-model documents (relative to project root)
SELF_MODEL_DIR = Path(__file__).parent.parent.parent.parent / "docs"

SELF_KNOWLEDGE_SECTIONS = {
    "architecture": "sara_self_model_architecture.md",
    "capabilities": "sara_self_model_capabilities.md",
    "autonomous": "sara_self_model_autonomous.md",
    "limitations": "sara_self_model_limitations.md",
}


class GetSelfKnowledgeTool(BaseTool):
    """Tool for retrieving Sara's self-knowledge documentation."""

    @property
    def name(self) -> str:
        return "get_self_knowledge"

    @property
    def description(self) -> str:
        return """Retrieve detailed self-knowledge about Sara's systems.

Use this when you need to:
- Check what tools or capabilities you have
- Understand how your memory or architecture works
- Verify what you can or cannot do
- Explain your systems to David

Available sections:
- "architecture": Memory system, databases, processing pipeline, composite scoring
- "capabilities": Tools organized by category, what actions you can perform
- "autonomous": Background services, scheduled jobs, nightly dream sequence
- "limitations": What you can't do, failure modes, system dependencies"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": ["architecture", "capabilities", "autonomous", "limitations"],
                    "description": "Which knowledge section to retrieve"
                }
            },
            "required": ["section"]
        }

    async def execute(
        self,
        user_id: str,
        section: Literal["architecture", "capabilities", "autonomous", "limitations"],
        **kwargs
    ) -> ToolResult:
        """Retrieve the requested self-knowledge section."""
        try:
            filename = SELF_KNOWLEDGE_SECTIONS.get(section)
            if not filename:
                return ToolResult(
                    success=False,
                    message=f"Unknown section: {section}. Available: {list(SELF_KNOWLEDGE_SECTIONS.keys())}"
                )

            filepath = SELF_MODEL_DIR / filename

            if not filepath.exists():
                logger.error(f"Self-knowledge file not found: {filepath}")
                return ToolResult(
                    success=False,
                    message=f"Self-knowledge file not found: {filename}"
                )

            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            logger.info(f"Retrieved self-knowledge section: {section} ({len(content)} chars)")

            return ToolResult(
                success=True,
                message=content,
                data={
                    "section": section,
                    "filename": filename,
                    "length": len(content)
                }
            )

        except Exception as e:
            logger.error(f"Error retrieving self-knowledge section '{section}': {e}")
            return ToolResult(
                success=False,
                message=f"Error retrieving self-knowledge: {str(e)}"
            )


# Export for registry
SELF_KNOWLEDGE_TOOLS = [
    GetSelfKnowledgeTool(),
]
