"""
Agent Dispatch Tools — LLM tools for dispatching tasks to VM agents.

Tools:
- dispatch_agent_task: Send a task to the sandbox agent
- dispatch_and_monitor: Dispatch + auto-notify David on completion
- get_agent_status: Check status of VM agent tasks
- resume_agent_session: Send follow-up to an agent session
- submit_candidate_skill: Propose a new skill for review
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class DispatchAgentTaskTool(BaseTool):
    """Dispatch a task to the sandbox agent."""

    @property
    def name(self) -> str:
        return "dispatch_agent_task"

    @property
    def description(self) -> str:
        return (
            "Dispatch a task to an agent for autonomous execution. USE THIS for ANY task "
            "involving David's data: searching emails, reading emails, finding attachments, "
            "checking calendar, searching notes, querying memory, home control, fitness data, "
            "or any multi-step work with Sara's internal systems. Also use for code execution "
            "and system admin tasks in the sandbox agent. "
            "In 'auto' mode (default), the system routes automatically: internal data tasks "
            "use Sara's tools directly; code/system tasks use the sandbox agent. "
            "ALWAYS use this tool for email, calendar, notes, and memory tasks. "
            "For chat-initiated 'research X' or 'look into X' tasks, use create_research_plan instead."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Clear description of the task for the agent to perform.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["auto", "dispatch", "sandbox", "internal"],
                    "description": "auto = intelligently route (default); dispatch/sandbox = sandbox agent; internal = Sara's internal tools",
                    "default": "auto",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Working directory for sandbox execution (optional, e.g. ~/projects/myapp)",
                },
                "target_host": {
                    "type": "string",
                    "description": (
                        "Optional name of a registered managed host (see /host list) to run the "
                        "agent ON instead of the default sandbox VM. Use for tasks like "
                        "'free up disk on gpu-box' or 'restart the service on web-01'."
                    ),
                },
            },
            "required": ["task_description"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        task_description = kwargs.get("task_description", "")
        mode = kwargs.get("mode", "auto")
        working_directory = kwargs.get("working_directory")
        target_host = kwargs.get("target_host")

        if not task_description:
            return ToolResult(success=False, message="No task description provided")

        try:
            from app.main_simple import SessionLocal
            from app.services.kernel import focused_turn

            db = SessionLocal()
            try:
                # SINGULAR_SARA_MASTER_PLAN §C7 — real focused-state entry.
                # Wraps dispatch_task unchanged; publishes kernel state
                # ENGAGED->FOCUSED (visible in Interior) around the call.
                result = await focused_turn(
                    db, str(user_id),
                    task_description=task_description,
                    mode=mode,
                    working_directory=working_directory,
                    target_host=target_host,
                )
                if result.get("status") == "error":
                    return ToolResult(success=False, message=result.get("error", "Dispatch failed"))
                _where = f" on {target_host}" if target_host else ""
                return ToolResult(
                    success=True,
                    message=f"Task dispatched ({mode} mode){_where}. Task ID: {result['task_id']}",
                    data=result,
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error dispatching agent task: {e}")
            return ToolResult(success=False, message=f"Failed to dispatch: {str(e)}")


class GetAgentStatusTool(BaseTool):
    """Check status of VM agent tasks."""

    @property
    def name(self) -> str:
        return "get_agent_status"

    @property
    def description(self) -> str:
        return (
            "Check the status of tasks dispatched to VM agents. "
            "Shows active and recent agent tasks. Optionally pass a task_id "
            "for details on a specific task."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Specific task ID to check (optional — omit to list all)",
                },
            },
            "required": [],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        task_id = kwargs.get("task_id")

        try:
            from app.main_simple import SessionLocal
            from app.services.agent_dispatch import agent_dispatch_service

            db = SessionLocal()
            try:
                if task_id:
                    detail = await agent_dispatch_service.get_task_detail(
                        db=db,
                        task_id=task_id,
                        user_id=str(user_id),
                    )
                    if not detail:
                        return ToolResult(success=False, message=f"Task {task_id} not found")
                    return ToolResult(
                        success=True,
                        message=f"Task {task_id}: {detail['status']}",
                        data=detail,
                    )
                else:
                    tasks = await agent_dispatch_service.get_agent_tasks(
                        db, str(user_id),
                    )
                    active = [t for t in tasks if t["status"] in ("pending", "running", "needs_clarification")]
                    return ToolResult(
                        success=True,
                        message=f"{len(active)} active, {len(tasks)} total agent tasks",
                        data={"tasks": tasks, "active_count": len(active)},
                    )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error getting agent status: {e}")
            return ToolResult(success=False, message=f"Failed: {str(e)}")


class ResumeAgentSessionTool(BaseTool):
    """Resume an agent session with a follow-up instruction."""

    @property
    def name(self) -> str:
        return "resume_agent_session"

    @property
    def description(self) -> str:
        return (
            "Send a follow-up instruction to a running agent session. "
            "Use this to answer an agent's question, provide clarification, "
            "or give additional instructions to a task that's in progress or "
            "waiting for input."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID to resume",
                },
                "instruction": {
                    "type": "string",
                    "description": "Follow-up instruction or answer to the agent's question",
                },
            },
            "required": ["task_id", "instruction"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        task_id = kwargs.get("task_id", "")
        instruction = kwargs.get("instruction", "")

        if not task_id or not instruction:
            return ToolResult(success=False, message="task_id and instruction are required")

        try:
            from app.main_simple import SessionLocal
            from app.services.agent_dispatch import agent_dispatch_service

            db = SessionLocal()
            try:
                result = await agent_dispatch_service.resume_task(
                    db=db,
                    task_id=task_id,
                    user_id=str(user_id),
                    instruction=instruction,
                )
                if "error" in result:
                    return ToolResult(success=False, message=result["error"])
                return ToolResult(
                    success=result.get("success", False),
                    message=f"Session resumed. Status: {result.get('status')}",
                    data=result,
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error resuming agent session: {e}")
            return ToolResult(success=False, message=f"Failed: {str(e)}")


class SubmitCandidateSkillTool(BaseTool):
    """Propose a new skill from agent experimentation."""

    @property
    def name(self) -> str:
        return "submit_candidate_skill"

    @property
    def description(self) -> str:
        return (
            "Propose a new skill for review. After an agent successfully completes "
            "a task, use this to capture the approach as a reusable skill that can "
            "be promoted to a permanent SKILL.md file."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name (kebab-case, e.g. 'docker-monitoring')",
                },
                "description": {
                    "type": "string",
                    "description": "Short description of what this skill does",
                },
                "instructions": {
                    "type": "string",
                    "description": "Full skill instructions in markdown",
                },
                "contexts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Contexts where this skill applies (e.g. ['heartbeat', 'chat'])",
                },
                "source_task_id": {
                    "type": "string",
                    "description": "Task ID that produced this skill (optional)",
                },
            },
            "required": ["name", "description", "instructions"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        name = kwargs.get("name", "")
        description = kwargs.get("description", "")
        instructions = kwargs.get("instructions", "")
        contexts = kwargs.get("contexts", [])
        source_task_id = kwargs.get("source_task_id")

        if not name or not instructions:
            return ToolResult(success=False, message="name and instructions are required")

        try:
            from app.main_simple import SessionLocal
            from app.models.candidate_skill import CandidateSkill

            db = SessionLocal()
            try:
                skill = CandidateSkill(
                    id=str(uuid.uuid4()),
                    user_id=str(user_id),
                    name=name,
                    description=description,
                    instructions=instructions,
                    contexts=contexts,
                    source_task_id=source_task_id,
                    status="pending",
                )
                db.add(skill)
                db.commit()

                return ToolResult(
                    success=True,
                    message=f"Candidate skill '{name}' submitted for review",
                    data={"skill_id": skill.id, "name": name, "status": "pending"},
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error submitting candidate skill: {e}")
            return ToolResult(success=False, message=f"Failed: {str(e)}")


class DispatchAndMonitorTool(BaseTool):
    """Dispatch a task and automatically notify David when it completes."""

    @property
    def name(self) -> str:
        return "dispatch_and_monitor"

    @property
    def description(self) -> str:
        return (
            "Dispatch a background task and automatically notify David when it's done. "
            "Use this when David asks you to research something, look into something, "
            "find out about something, set something up, or handle any task that will "
            "take time. The task runs in the background and David gets a notification "
            "with the results. Prefer this over dispatch_agent_task for most requests."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": (
                        "Clear, detailed description of what to do. Include all relevant "
                        "context from the conversation so the background agent has full picture."
                    ),
                },
                "mode": {
                    "type": "string",
                    "enum": ["auto", "dispatch", "sandbox", "internal"],
                    "description": "auto = intelligently route (default); dispatch/sandbox = sandbox agent; internal = Sara's internal tools",
                    "default": "auto",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Working directory for sandbox execution (optional, for code tasks)",
                },
            },
            "required": ["task_description"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        task_description = kwargs.get("task_description", "")
        mode = kwargs.get("mode", "auto")
        working_directory = kwargs.get("working_directory")

        if not task_description:
            return ToolResult(success=False, message="No task description provided")

        try:
            from app.main_simple import SessionLocal
            from app.services.kernel import focused_turn

            db = SessionLocal()
            try:
                result = await focused_turn(
                    db, str(user_id),
                    task_description=task_description,
                    mode=mode,
                    working_directory=working_directory,
                    notify_on_complete=True,
                )
                await self._record_commitment(user_id, task_description, result.get("task_id"))
                return ToolResult(
                    success=True,
                    message=(
                        f"Task dispatched and monitoring. Task ID: {result['task_id']}. "
                        f"David will be notified when it's done."
                    ),
                    data=result,
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error dispatching monitored task: {e}")
            return ToolResult(success=False, message=f"Failed to dispatch: {str(e)}")

    async def _record_commitment(self, user_id: str, task_description: str, task_id: Optional[str]) -> None:
        """Mind V2 rewire plan Workstream D.3 — this tool's whole contract IS
        an explicit promise to report back ("David gets a notification with
        the results"), so every dispatch through it opens a sara_commitment.
        task_result_delivery closes it when the completion notice actually
        delivers — verified live that a chat-dispatched task can complete
        with only a bookkeeping ledger row and no channel David actually
        saw (SSE delivery isn't recorded in notification_log at all), so
        this ledger is the only place the promise-vs-delivery gap becomes
        visible. Best-effort: a ledger failure must never block dispatch."""
        if not task_id:
            return
        try:
            from app.services.commitment_service import create_commitment
            from app.db.session import get_async_session_factory

            factory = get_async_session_factory()
            async with factory() as db:
                await create_commitment(
                    db, user_id=str(user_id),
                    text_=f"Report back on: {task_description[:200]}",
                    created_from="chat",
                    trigger_description=f"task:{task_id}",
                )
        except Exception as e:
            logger.warning(f"[commitment] dispatch-time record failed for task {task_id}: {e}")


class CancelAgentTaskTool(BaseTool):
    """Cancel a running or pending agent task."""

    @property
    def name(self) -> str:
        return "cancel_agent_task"

    @property
    def description(self) -> str:
        return (
            "Cancel a running or pending background agent task. Use this when David "
            "asks to stop/cancel/abort a background task, or when you determine a task "
            "is stuck, redundant, or no longer needed."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID to cancel. Use get_agent_status to find task IDs.",
                },
            },
            "required": ["task_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        task_id = kwargs.get("task_id", "")

        if not task_id:
            return ToolResult(success=False, message="task_id is required")

        try:
            from app.main_simple import SessionLocal
            from app.services.agent_dispatch import agent_dispatch_service

            db = SessionLocal()
            try:
                result = await agent_dispatch_service.cancel_task(
                    db=db,
                    task_id=task_id,
                    user_id=str(user_id),
                )
                if "error" in result:
                    return ToolResult(success=False, message=result["error"])
                return ToolResult(
                    success=True,
                    message=f"Task {task_id} cancelled.",
                    data=result,
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error cancelling agent task: {e}")
            return ToolResult(success=False, message=f"Failed: {str(e)}")


# Export list for registry
AGENT_DISPATCH_TOOLS = [
    DispatchAgentTaskTool(),
    DispatchAndMonitorTool(),
    GetAgentStatusTool(),
    ResumeAgentSessionTool(),
    SubmitCandidateSkillTool(),
    CancelAgentTaskTool(),
]
