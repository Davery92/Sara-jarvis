"""Durable agent dispatch (Phase 4).

Runs the agent tool-use loop inside a Celery worker (a *separate process* from
the backend API) on its own `dispatch` queue. Because Celery is configured
globally with ``task_acks_late`` + ``task_reject_on_worker_lost``:

  - a backend restart (`docker compose up -d backend`) no longer kills in-flight
    agent work — the worker keeps running;
  - a lost dispatch worker requeues the message instead of dropping the task.

The step journal in background_task.task_metadata lets a re-run pick up where it
left off instead of restarting from zero (see agent_dispatch._run_vm_claude_mode).
"""
import asyncio
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.dispatch.execute_dispatch",
    queue="dispatch",
    bind=True,
    max_retries=1,
    # acks_late / reject_on_worker_lost are global; a mid-run worker loss requeues.
)
def execute_dispatch(self, task_id, mission_id, user_id, task_description,
                     skill_context="", fallback_categories=None, mode="vm_claude"):
    from app.services.agent_dispatch import agent_dispatch_service
    attempt = self.request.retries + 1
    logger.info(
        f"[dispatch] execute_dispatch starting task {task_id} "
        f"(attempt {attempt}, mode={mode})"
    )
    try:
        if mode == "internal":
            # Sara's own data (email, notes, reminders, calendar) is reachable
            # only through the internal tool registry — never from the VM shell.
            prompt = task_description
            if skill_context:
                prompt += f"\n\n{skill_context}"
            asyncio.run(agent_dispatch_service._run_internal_mode(
                task_id, mission_id, user_id, prompt,
                categories=fallback_categories or [],
            ))
        else:
            asyncio.run(agent_dispatch_service._run_vm_claude_mode(
                task_id, mission_id, user_id, task_description,
                skill_context=skill_context,
                fallback_categories=fallback_categories or [],
            ))
        return {"task_id": task_id, "status": "executed"}
    except Exception as e:
        logger.error(f"[dispatch] execute_dispatch task {task_id} failed: {e}", exc_info=True)
        # Re-raise so Celery records FAILURE (interoception ledger picks it up).
        raise
