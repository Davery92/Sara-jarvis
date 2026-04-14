"""
Sara's tool to create and manage research plans.

When David asks Sara to research something, she uses this tool to create
a structured plan and hand it off to the research executor agent.
"""

import json
import logging
import uuid
from typing import Any, Dict, List

from app.tools.base import BaseTool, ToolResult
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _get_db():
    from app.db.session import get_db
    return next(get_db())


class CreateResearchPlanTool(BaseTool):
    """Create a research plan and optionally start execution."""

    @property
    def name(self) -> str:
        return "create_research_plan"

    @property
    def description(self) -> str:
        return (
            "Create a structured research plan with ordered steps, then hand it off "
            "to the dedicated research agent for execution. Use this when David asks "
            "you to research something in depth. Break the topic into clear, "
            "sequential steps that can each be researched independently. "
            "The research agent will use web search, file I/O, and shell tools "
            "to execute each step and report findings."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title for the research plan",
                },
                "objective": {
                    "type": "string",
                    "description": "What we're trying to learn — the overall research goal",
                },
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Step title"},
                            "description": {
                                "type": "string",
                                "description": "What to research in this step",
                            },
                            "instructions": {
                                "type": "string",
                                "description": "Detailed instructions for the research agent",
                            },
                        },
                        "required": ["title", "description"],
                    },
                    "description": "Ordered list of research steps",
                },
                "auto_start": {
                    "type": "boolean",
                    "description": "Start execution immediately (default: true)",
                    "default": True,
                },
            },
            "required": ["title", "objective", "steps"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        title = kwargs.get("title", "")
        objective = kwargs.get("objective", "")
        steps_raw = kwargs.get("steps", [])
        auto_start = kwargs.get("auto_start", True)

        if not title or not objective or not steps_raw:
            return ToolResult(
                success=False,
                message="Missing required fields: title, objective, and steps",
            )

        db = _get_db()
        try:
            plan_id = str(uuid.uuid4())

            steps = [
                {
                    "title": s.get("title", f"Step {i+1}"),
                    "description": s.get("description", ""),
                    "instructions": s.get("instructions", s.get("description", "")),
                    "status": "pending",
                    "findings": {},
                }
                for i, s in enumerate(steps_raw)
            ]

            db.execute(
                text("""
                    INSERT INTO research_plan
                    (id, user_id, title, objective, steps, model_id, created_by, status)
                    VALUES (:id, :user_id, :title, :objective, CAST(:steps AS jsonb),
                            'Qwen3.5-27B', 'sara', :status)
                """),
                {
                    "id": plan_id,
                    "user_id": user_id,
                    "title": title,
                    "objective": objective,
                    "steps": json.dumps(steps),
                    "status": "draft",
                },
            )
            db.commit()

            # Auto-start if requested
            if auto_start:
                from app.tasks.research import run_research_plan
                run_research_plan.delay(plan_id, user_id)
                status_msg = "created and started"
            else:
                status_msg = "created (draft — start manually)"

            step_list = "\n".join(
                f"  {i+1}. {s['title']}" for i, s in enumerate(steps)
            )

            return ToolResult(
                success=True,
                data={
                    "plan_id": plan_id,
                    "title": title,
                    "steps_count": len(steps),
                    "status": "running" if auto_start else "draft",
                },
                message=(
                    f"Research plan {status_msg}: **{title}**\n"
                    f"Objective: {objective}\n"
                    f"Steps:\n{step_list}\n\n"
                    f"Plan ID: `{plan_id}`"
                ),
            )

        except Exception as e:
            db.rollback()
            logger.error("Failed to create research plan: %s", e, exc_info=True)
            return ToolResult(success=False, message=f"Failed to create plan: {e}")
        finally:
            db.close()


class ResearchPlanStatusTool(BaseTool):
    """Check the status of a research plan."""

    @property
    def name(self) -> str:
        return "research_plan_status"

    @property
    def description(self) -> str:
        return (
            "Check the current status of a research plan, including progress, "
            "findings, and any pending questions from the research agent."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "string",
                    "description": "The research plan ID to check",
                },
            },
            "required": ["plan_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        plan_id = kwargs.get("plan_id", "")
        if not plan_id:
            return ToolResult(success=False, message="Missing plan_id")

        db = _get_db()
        try:
            result = db.execute(
                text("SELECT * FROM research_plan WHERE id = :id AND user_id = :user_id"),
                {"id": plan_id, "user_id": user_id},
            )
            row = result.fetchone()
            if not row:
                return ToolResult(success=False, message="Plan not found")

            plan = dict(row._mapping)
            steps = plan.get("steps", [])
            if isinstance(steps, str):
                steps = json.loads(steps)

            completed = sum(1 for s in steps if s.get("status") == "complete")
            running = sum(1 for s in steps if s.get("status") == "running")
            stuck = sum(1 for s in steps if s.get("status") == "stuck")

            # Check for pending questions
            msg_result = db.execute(
                text("""
                    SELECT content, step_index FROM research_message
                    WHERE plan_id = :plan_id AND direction = 'agent_to_sara' AND status = 'pending'
                    ORDER BY created_at ASC
                """),
                {"plan_id": plan_id},
            )
            pending_questions = [
                {"question": m.content, "step": m.step_index}
                for m in msg_result.fetchall()
            ]

            status_msg = (
                f"**{plan.get('title', 'Untitled')}** — {plan.get('status', 'unknown')}\n"
                f"Progress: {completed}/{len(steps)} steps complete"
            )
            if running:
                status_msg += f", {running} running"
            if stuck:
                status_msg += f", {stuck} stuck"
            status_msg += f"\nTokens used: {plan.get('total_tokens_used', 0)}"

            if pending_questions:
                status_msg += "\n\n**Pending questions from agent:**"
                for pq in pending_questions:
                    status_msg += f"\n- Step {pq['step']}: {pq['question'][:200]}"

            if plan.get("findings_summary"):
                status_msg += f"\n\n**Summary:**\n{plan['findings_summary'][:500]}"

            # Step details
            step_details = []
            for i, s in enumerate(steps):
                detail = {
                    "index": i,
                    "title": s.get("title"),
                    "status": s.get("status"),
                }
                if s.get("findings", {}).get("summary"):
                    detail["summary"] = s["findings"]["summary"][:200]
                step_details.append(detail)

            return ToolResult(
                success=True,
                data={
                    "plan_id": plan_id,
                    "status": plan.get("status"),
                    "progress": f"{completed}/{len(steps)}",
                    "steps": step_details,
                    "pending_questions": pending_questions,
                    "findings_summary": plan.get("findings_summary"),
                    "tokens_used": plan.get("total_tokens_used", 0),
                },
                message=status_msg,
            )

        except Exception as e:
            return ToolResult(success=False, message=f"Error: {e}")
        finally:
            db.close()
