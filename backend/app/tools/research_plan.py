"""
Sara's tool to create and manage research plans.

For large or explicitly backgrounded research, Sara can use this tool to create
a durable structured plan and hand it off to the research executor agent.
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


def normalize_plan_title(title: str) -> str:
    """Two ways of asking the same question hash to the same plan.

    "Salem MA historical guide", "Salem MA Historical Guide!" and "salem ma
    historical  guide" are one piece of work. Lowercase, strip punctuation,
    collapse whitespace — deliberately crude, because the failure it prevents
    (four concurrent agents against one LLM lane) is far worse than the
    occasional false match, which Sara can resolve by cancelling.
    """
    import re as _re
    return _re.sub(r"\s+", " ", _re.sub(r"[^a-z0-9\s]", " ", (title or "").lower())).strip()


# How long a completed plan counts as "already answered". Long enough that asking
# again the same day gets the existing report; short enough that tomorrow's
# version of the question is genuinely new work.
COMPLETED_PLAN_REUSE_HOURS = 12


def _find_matching_plan(db, user_id: str, title: str):
    """A live or freshly-completed plan for the same question, or None."""
    normalized = normalize_plan_title(title)
    if not normalized:
        return None
    try:
        rows = db.execute(text("""
            SELECT id, title, status, updated_at, created_at
              FROM research_plan
             WHERE user_id = :uid
               AND (status IN ('draft', 'running', 'pending', 'stuck', 'paused', 'stalled')
                    OR (status IN ('complete', 'completed', 'partial')
                        AND COALESCE(updated_at, created_at) >= NOW() - (:hrs * INTERVAL '1 hour')))
             ORDER BY COALESCE(updated_at, created_at) DESC LIMIT 25
        """), {"uid": user_id, "hrs": COMPLETED_PLAN_REUSE_HOURS}).fetchall()
    except Exception as e:
        logger.warning("single-flight title check failed: %s", e)
        return None

    for row in rows:
        if normalize_plan_title(row.title) == normalized:
            return {"id": str(row.id), "title": row.title, "status": row.status}
    return None


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
            "Hand off a large or explicitly backgrounded research task to the dedicated "
            "research agent. Use this only when David asks for a background report, asks "
            "to be notified later, or requests a durable multi-source investigation that "
            "will take several minutes. Phrases such as 'look into', 'research', "
            "'explain', or 'tell me about' do not by themselves justify a handoff: use "
            "web_search/open_page inline and answer in the current conversation. "
            "Break the topic into 3–6 ordered, independently-researchable steps. The agent "
            "executes them in the background using web search, file I/O, and shell tools, "
            "then writes a report. "
            "DO NOT use for normal web questions, URL inspection, comparisons, or explanations "
            "that the chat tool loop can complete now. "
            "Plans created from chat are marked origin='david_chat' and take precedence "
            "over Sara's autonomous research. "
            "If a plan for the same question is already running or finished in the last "
            "12 hours, this returns THAT plan with attached=true — say \"already running "
            "as <id>\" (or point him at the finished result) rather than announcing a new plan."
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
            # Same question, same plan. David asked for the Salem report four
            # times on 2026-09-01 because Sara kept telling him nothing was
            # running; all four plans then completed, producing three duplicate
            # "Completed" notes that went on to dominate her own memory recall.
            # A repeat of a question already answered — or being answered — hands
            # back the existing plan rather than starting a second one.
            attached = _find_matching_plan(db, user_id, title)
            if attached:
                return ToolResult(
                    success=True,
                    data={
                        "plan_id": attached["id"], "title": attached["title"],
                        "status": attached["status"], "attached": True,
                    },
                    message=(
                        f"Already running as `{attached['id']}`: **{attached['title']}** "
                        f"({attached['status']}). Tell David it's the same work, not a new plan."
                        if attached["status"] not in ("complete", "completed")
                        else f"Already done — I finished **{attached['title']}** earlier today "
                             f"(`{attached['id']}`). Point David at that result rather than re-running it."
                    ),
                )

            # Single-flight guard. Two research agents against the same LLM lane
            # is what OOM'd it on 2026-09-01 and destroyed three plans. Refuse
            # at the door and hand back the running plan so Sara can answer
            # "is it running?" truthfully instead of re-dispatching.
            from app.services.agent_activity import active_research_plans

            live = active_research_plans(db, user_id)
            if live:
                existing = live[0]
                steps_total = existing.n_steps or 0
                step_no = min((existing.current_step_index or 0) + 1, steps_total or 1)
                step_title = (existing.current_step_title or "").strip()
                progress = f"step {step_no}/{steps_total}" if steps_total else existing.status
                if step_title:
                    progress += f" — {step_title}"
                mine = existing.origin == "sara_internal"
                whose = (
                    "One of my own background research plans is running"
                    if mine else "A research plan is already running"
                )
                nudge = (
                    "That's my own work, not David's — if this request matters more, "
                    "call cancel_research_plan with that ID and then create the new plan."
                    if mine else
                    "Tell David it's in flight, or call cancel_research_plan with "
                    "that ID first if he wants to replace it."
                )
                return ToolResult(
                    success=False,
                    data={
                        "reason": "already_running",
                        "plan_id": existing.id,
                        "title": existing.title,
                        "status": existing.status,
                        "origin": existing.origin,
                        "progress": progress,
                    },
                    message=(
                        f"{whose}: **{existing.title}** ({progress}). "
                        "Only one research agent may use the LLM lane at a time, so "
                        "I'm not starting a duplicate.\n"
                        f"Plan ID: `{existing.id}`\n{nudge}"
                    ),
                )

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
                async_result = run_research_plan.apply_async(
                    args=[plan_id, user_id],
                    queue="david_priority",
                )
                # Remember the worker so cancel can actually revoke it — a
                # status flip alone leaves it grinding against the LLM lane.
                db.execute(
                    text("UPDATE research_plan SET celery_task_id = :tid WHERE id = :id"),
                    {"tid": async_result.id, "id": plan_id},
                )
                db.commit()
                status_msg = "created and started"
                # "I'll ping you when it's ready" becomes a row, not a sentence.
                # Without this the Salem report finished at 21:28 on 2026-09-01
                # and batched itself into a morning window David had already left
                # for work by — nothing owned the promise to tell him.
                from app.services.commitment_service import create_delivery_commitment
                await create_delivery_commitment(user_id, plan_id, title, origin="david_chat")
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
                    "description": (
                        "The research plan ID to check. An id prefix of 8 or more "
                        "characters is accepted."
                    ),
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
            # Sara quotes 8-char id prefixes in prose and reads them back to
            # herself; an exact match answers "Plan not found" for a plan that
            # is very much running. Resolve prefixes, and on a real miss hand
            # back the recent plans so she self-corrects instead of concluding
            # nothing is happening.
            from app.services.research.cancel import resolve_plan_id, recent_plans_hint

            resolved, reason = resolve_plan_id(db, user_id, plan_id)
            if not resolved:
                recent = recent_plans_hint(db, user_id)
                msg = reason or f"No research plan matching '{plan_id}'."
                if recent:
                    listing = "\n".join(
                        f"- `{p['plan_id']}` — {p['title']} ({p['status']}, {p['progress']})"
                        for p in recent
                    )
                    msg += f"\n\nYour most recent plans:\n{listing}"
                else:
                    msg += " You have no research plans at all."
                return ToolResult(
                    success=False, message=msg, data={"recent_plans": recent}
                )
            plan_id = resolved

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
            logger.error(
                "research_plan_status failed: %s: %s", type(e).__name__, e, exc_info=True
            )
            return ToolResult(success=False, message=f"Error: {type(e).__name__}: {e}")
        finally:
            db.close()


class CancelResearchPlanTool(BaseTool):
    """Kill a running research plan — the explicit replace path."""

    @property
    def name(self) -> str:
        return "cancel_research_plan"

    @property
    def description(self) -> str:
        return (
            "Cancel a running research plan. Only one research plan may run at a "
            "time, so use this when David wants to replace what's in flight with "
            "something else: cancel the old plan, then create the new one. "
            "Accepts a full plan ID or an ID prefix of 8+ characters."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "string",
                    "description": "Plan ID (or an 8+ character prefix) to cancel",
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
            from app.services.research.cancel import cancel_research_plan, recent_plans_hint

            result = cancel_research_plan(db, user_id, plan_id)
            if result.get("cancelled"):
                return ToolResult(
                    success=True,
                    data=result,
                    message=(
                        f"Cancelled research plan **{result.get('title')}** "
                        f"(`{result.get('id')}`). The lane is free for a new plan."
                    ),
                )

            msg = result.get("error") or f"No research plan matching '{plan_id}'."
            recent = recent_plans_hint(db, user_id)
            if recent and not result.get("id"):
                listing = "\n".join(
                    f"- `{p['plan_id']}` — {p['title']} ({p['status']})" for p in recent
                )
                msg += f"\n\nYour most recent plans:\n{listing}"
            return ToolResult(success=False, message=msg, data={"recent_plans": recent})

        except Exception as e:
            db.rollback()
            logger.error(
                "cancel_research_plan failed: %s: %s", type(e).__name__, e, exc_info=True
            )
            return ToolResult(success=False, message=f"Error: {type(e).__name__}: {e}")
        finally:
            db.close()
