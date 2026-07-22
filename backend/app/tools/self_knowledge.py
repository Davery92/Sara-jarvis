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


class CheckCurrentStateTool(BaseTool):
    """Live global workspace (§3.1) — what Sara is holding in mind right now."""

    @property
    def name(self) -> str:
        return "check_current_state"

    @property
    def description(self) -> str:
        return """Check what you're currently holding in mind — your live global workspace.

Use this whenever David asks "anything I should know?", "what's going on?",
"what are you working on?", or any open-ended check-in. Returns a synthesis of:
open loops, today's predictions and any that were violated (things off from the
usual), what you're working on in the background, today's plan, David's current
state, and your current concern level. This is REAL current data — prefer it
over guessing or a generic memory search for "what's up right now" questions."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            from app.db.session import get_async_session_factory
            from app.services.global_workspace import build_workspace, anything_i_should_know
            sf = get_async_session_factory()
            async with sf() as db:
                summary = await anything_i_should_know(db, user_id)
                workspace = await build_workspace(db, user_id)
            return ToolResult(success=True, message=summary, data={"workspace": workspace})
        except Exception as e:
            logger.error(f"check_current_state failed: {e}")
            return ToolResult(success=False, message=f"Couldn't read my workspace: {e}")


class SelfDiagnosticsTool(BaseTool):
    """Live self-model (§3.4) — Sara's honest assessment of her own health."""

    @property
    def name(self) -> str:
        return "self_diagnostics"

    @property
    def description(self) -> str:
        return """Check your own current health honestly — the live self-model.

Use this when David asks "how are you doing?", "is everything working?",
"what's broken?", "anything wrong with you?", or when you want to add an honest
caveat (e.g. "my sent-mail sync has been stalled, so I may have missed
something"). Returns: unresolved failures, failed scheduled jobs, stalled data
cursors, prediction calibration (how accurate your confidence actually is),
capabilities, and deploy state. This is real self-inspection — report it
truthfully, including problems. Read-only; you cannot fix these from here."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            from app.db.session import get_async_session_factory
            from app.services.self_model import build_self_model
            sf = get_async_session_factory()
            async with sf() as db:
                model = await build_self_model(db, user_id)
            return ToolResult(success=True, message=model["summary"], data=model)
        except Exception as e:
            logger.error(f"self_diagnostics failed: {e}")
            return ToolResult(success=False, message=f"Couldn't read my self-model: {e}")


class WhyDidYouNotifyTool(BaseTool):
    """Why-trace (§3.10) — the real causal chain behind recent notifications."""

    @property
    def name(self) -> str:
        return "why_did_you_notify"

    @property
    def description(self) -> str:
        return """Explain WHY you recently notified David (or held something back).

Use this when David asks "why did you ping me?", "why did you tell me that?",
"why didn't you tell me sooner?", or "why did you hold that until morning?".
Returns the actual decision chain for recent notifications: category, priority,
whether it was delivered/held/dropped, the reason (e.g. asleep, security-exempt),
David's sensed state, and the value-model's opinion. Report the REAL chain — do
not confabulate a plausible-sounding reason."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "How many recent decisions (default 10)"}
        }}

    async def execute(self, user_id: str, limit: int = 10, **kwargs) -> ToolResult:
        try:
            from app.db.session import get_async_session_factory
            from app.services.delivery_policy import recent_why_traces
            sf = get_async_session_factory()
            async with sf() as db:
                traces = await recent_why_traces(db, user_id, min(int(limit or 10), 25))
            if not traces:
                return ToolResult(success=True, message="No recent notification decisions on record.")
            lines = []
            for t in traces:
                chain = t.get("chain") or {}
                extra = []
                if chain.get("sleep_source"):
                    extra.append(f"state={chain['sleep_source']}")
                if chain.get("ml_p_valuable") is not None:
                    extra.append(f"value={chain['ml_p_valuable']}")
                lines.append(f"- [{t['decision']}] {t.get('category')} via {t.get('source')} — "
                             f"{t.get('reason')}" + (f" ({', '.join(extra)})" if extra else ""))
            return ToolResult(success=True, message="Recent notification decisions:\n" + "\n".join(lines),
                              data={"traces": traces})
        except Exception as e:
            logger.error(f"why_did_you_notify failed: {e}")
            return ToolResult(success=False, message=f"Couldn't read my decision log: {e}")


# Export for registry
SELF_KNOWLEDGE_TOOLS = [
    GetSelfKnowledgeTool(),
    CheckCurrentStateTool(),
    SelfDiagnosticsTool(),
    WhyDidYouNotifyTool(),
]
