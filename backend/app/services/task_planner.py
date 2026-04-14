"""
Task Planner — orchestrates multi-step requests through InternalToolAgent.

Given a MultiStepPlan from the detector, executes steps in dependency order,
passing intermediate results as context to downstream steps.
Reports progress via an async callback for SSE streaming.
"""

import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

from app.services.multi_step_detector import MultiStepPlan, TaskStep
from app.services.internal_tool_agent import InternalToolAgent

logger = logging.getLogger(__name__)


async def execute_plan(
    plan: MultiStepPlan,
    user_id: str,
    db_session,
    on_progress: Optional[Callable[[int, str, str], Coroutine]] = None,
) -> Dict[str, Any]:
    """
    Execute a multi-step plan sequentially, respecting dependencies.

    Args:
        plan: MultiStepPlan from detect_multi_step()
        user_id: User ID for tool context
        db_session: SQLAlchemy session for tool execution
        on_progress: async callback(step_index, status, message) for SSE updates

    Returns:
        {status, summary, step_results: [{step, status, summary}]}
    """
    step_results: List[Dict[str, Any]] = []
    step_summaries: Dict[int, str] = {}  # index -> summary for dependency injection

    for i, step in enumerate(plan.steps):
        # Notify progress
        if on_progress:
            try:
                await on_progress(i, "started", f"Step {i+1}/{len(plan.steps)}: {step.description[:80]}")
            except Exception:
                pass

        # Build task description with context from prior steps
        task_desc = _build_step_prompt(step, i, step_summaries, plan.original_query)

        # Determine which tool categories this step needs
        categories = step.tool_categories or ["memory", "web", "notes", "calendar", "email"]

        try:
            agent = InternalToolAgent(
                db=db_session,
                user_id=user_id,
                active_categories=categories,
                max_iterations=8,
            )
            result = await agent.run(task_desc)

            summary = result.get("summary", "No result")
            step_summaries[i] = summary
            step_results.append({
                "step": i + 1,
                "description": step.description,
                "status": result.get("status", "completed"),
                "summary": summary,
                "found_items": result.get("found_items", []),
            })

            if on_progress:
                try:
                    await on_progress(i, "completed", f"Step {i+1} done: {summary[:100]}")
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"[TaskPlanner] Step {i+1} failed: {e}")
            step_summaries[i] = f"Failed: {e}"
            step_results.append({
                "step": i + 1,
                "description": step.description,
                "status": "error",
                "summary": f"Failed: {e}",
                "found_items": [],
            })

            if on_progress:
                try:
                    await on_progress(i, "error", f"Step {i+1} failed: {e}")
                except Exception:
                    pass

    # Build final summary
    final_summary = _build_final_summary(plan, step_results)

    return {
        "status": "completed",
        "summary": final_summary,
        "step_results": step_results,
        "total_steps": len(plan.steps),
        "completed_steps": sum(1 for r in step_results if r["status"] == "completed"),
    }


def _build_step_prompt(
    step: TaskStep, index: int, prior_summaries: Dict[int, str], original_query: str
) -> str:
    """Build the task description for a single step, injecting prior step context."""
    parts = [f"You are executing step {index + 1} of a multi-step request."]
    parts.append(f"\nOriginal request: {original_query}")
    parts.append(f"\nCurrent step: {step.description}")

    # Inject results from dependency steps
    if step.depends_on:
        context_parts = []
        for dep_idx in step.depends_on:
            if dep_idx in prior_summaries:
                context_parts.append(f"  Step {dep_idx + 1} result: {prior_summaries[dep_idx]}")
        if context_parts:
            parts.append("\nResults from prior steps:")
            parts.extend(context_parts)
            parts.append("\nUse these results to inform your actions for this step.")

    parts.append("\nComplete this step and call report_complete with your findings.")
    return "\n".join(parts)


def _build_final_summary(plan: MultiStepPlan, step_results: List[Dict]) -> str:
    """Build a combined summary from all step results."""
    completed = [r for r in step_results if r["status"] == "completed"]
    failed = [r for r in step_results if r["status"] == "error"]

    lines = []
    if len(completed) == len(step_results):
        lines.append(f"All {len(step_results)} steps completed successfully.")
    else:
        lines.append(f"Completed {len(completed)}/{len(step_results)} steps.")

    lines.append("")
    for r in step_results:
        icon = "✅" if r["status"] == "completed" else "❌"
        lines.append(f"{icon} **Step {r['step']}**: {r['summary']}")

    return "\n".join(lines)
