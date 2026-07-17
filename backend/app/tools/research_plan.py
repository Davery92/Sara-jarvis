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


async def _resolve_research_model(base_url: str, fallback: str) -> str:
    """Query the configured LLM endpoint for the actual loaded model name.

    The endpoint may host a different model than what's hardcoded in config; we
    want the row to reflect what actually ran the plan. Falls back to the
    configured `research_llm_model` if discovery fails (offline, schema mismatch, etc.).
    """
    import httpx
    try:
        url = base_url.rstrip("/") + "/models"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        models = data.get("data") or data.get("models") or []
        if models and isinstance(models, list):
            first = models[0]
            if isinstance(first, dict):
                return first.get("id") or first.get("name") or fallback
            if isinstance(first, str):
                return first
    except Exception as e:
        logger.warning("Could not discover research model from %s: %s", base_url, e)
    return fallback


class CreateResearchPlanTool(BaseTool):
    """Create a research plan and optionally start execution."""

    @property
    def name(self) -> str:
        return "create_research_plan"

    @property
    def description(self) -> str:
        return (
            "Hand off a research task to the dedicated research agent. Use this — and only this — "
            "when David asks you to look into, research, dig into, investigate, gain an "
            "understanding of, or explain a topic. Trigger phrases include: 'look into X', "
            "'research X', 'do some research on X', 'dig into X', 'investigate X', "
            "'understand X and explain it', 'put together a brief on X'. "
            "Break the topic into 3–6 ordered, independently-researchable steps. The agent "
            "executes them in the background using web search, file I/O, and shell tools, "
            "then writes a report. "
            "DO NOT use for simple factual lookups (e.g. 'what time does X open', 'who is Y') — "
            "use web_search inline and answer in the same turn instead. "
            "Plans created from chat are marked origin='david_chat' and take precedence "
            "over Sara's autonomous research."
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

            # Resolve the actual model loaded on the research LLM endpoint at create time.
            # Falls back to the configured default if discovery fails.
            from app.core.config import settings
            model_id = await _resolve_research_model(settings.research_llm_url, settings.research_llm_model)

            db.execute(
                text("""
                    INSERT INTO research_plan
                    (id, user_id, title, objective, steps, model_id, created_by, origin, status)
                    VALUES (:id, :user_id, :title, :objective, CAST(:steps AS jsonb),
                            :model_id, 'sara', 'david_chat', :status)
                """),
                {
                    "id": plan_id,
                    "user_id": user_id,
                    "title": title,
                    "objective": objective,
                    "steps": json.dumps(steps),
                    "model_id": model_id,
                    "status": "draft",
                },
            )
            db.commit()

            # Auto-start if requested
            if auto_start:
                from app.tasks.research import run_research_plan
                # Chat-initiated plans run on the david_priority queue so they
                # never share workers with ACS or other cognitive work.
                run_research_plan.apply_async(
                    args=[plan_id, user_id],
                    queue="david_priority",
                )
                status_msg = "created and started"
            else:
                status_msg = "created (draft — start manually)"

            # (Phase 6: old ACS state-machine pause removed; the v2 daemon
            # has its own continuous loop and doesn't need to be preempted.)

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
