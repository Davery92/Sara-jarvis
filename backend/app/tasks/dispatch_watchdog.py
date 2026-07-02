"""
Dispatch watchdog — proactive version of agent_dispatch's stuck-task expiry
(PHENOMENAL_ASSISTANT_PLAN.md Phase 4.3).

The acute hang bug ("no activity 8+ min") is already fixed elsewhere; this is
the policy-as-code half: agent_dispatch.list_agent_tasks() only auto-expires
stuck tasks (>4h in running/needs_clarification) lazily, when someone happens
to view the task list — so a stuck task can sit silently indefinitely if
nobody looks. This runs the same check on a schedule, then decides whether to
notify: never on a single failure (that's still silent — feedback_no_repetitive_
nags), and never with a bare "failed" if the task produced usable output
(result_note_id set) — only the first time a task_type has failed twice in a
row does anything reach David, and even then it points at the partial output
when one exists.
"""

import logging
import os
from datetime import timedelta

from app.celery_app import celery_app
from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)
DEFAULT_USER_ID = os.getenv("SOLO_USER_ID", "64f37c56-85cb-4590-8de9-adfc17d343ed")
MAX_RUNTIME_HOURS = 4
REPEAT_FAILURE_WINDOW_HOURS = 24


def _run_async(coro):
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(name="app.tasks.dispatch_watchdog.check_stuck_tasks", bind=True, max_retries=0)
def check_stuck_tasks(self):
    """Mark tasks stuck past MAX_RUNTIME_HOURS as failed; notify only on a
    repeated failure for the same task_type, surfacing partial output if any."""
    from app.db.base import SessionLocal
    from app.models.background_task import BackgroundTask

    db = SessionLocal()
    newly_failed = []
    try:
        cutoff = local_now() - timedelta(hours=MAX_RUNTIME_HOURS)
        stuck = (
            db.query(BackgroundTask)
            .filter(
                BackgroundTask.user_id == DEFAULT_USER_ID,
                BackgroundTask.task_type.in_(
                    ["vm_agent", "self_orchestrate", "internal_agent", "vm_claude_agent", "code_mode"]
                ),
                BackgroundTask.status.in_(["needs_clarification", "running"]),
                BackgroundTask.updated_at < cutoff,
            )
            .all()
        )
        for t in stuck:
            logger.info(f"[dispatch_watchdog] Auto-expiring stuck task {t.id} (status={t.status})")
            original_status = t.status
            t.status = "failed"
            meta = t.task_metadata or {}
            meta["error"] = f"Auto-expired by watchdog: stuck in {original_status} for >{MAX_RUNTIME_HOURS}h"
            meta["auto_expired_at"] = local_now().isoformat()
            t.task_metadata = {**meta}
            newly_failed.append(t)
        if newly_failed:
            db.commit()

        notified = 0
        for t in newly_failed:
            recent_failures = (
                db.query(BackgroundTask)
                .filter(
                    BackgroundTask.user_id == DEFAULT_USER_ID,
                    BackgroundTask.task_type == t.task_type,
                    BackgroundTask.status == "failed",
                    BackgroundTask.updated_at > local_now() - timedelta(hours=REPEAT_FAILURE_WINDOW_HOURS),
                )
                .count()
            )
            if recent_failures < 2:
                continue  # single failure — stays silent, matches anti-nag policy

            if t.result_note_id:
                body = f"'{t.original_query[:100]}' didn't finish cleanly, but it got partway — see the note it produced."
            else:
                body = f"'{t.original_query[:100]}' has now stalled {recent_failures} times in a row and auto-failed."

            try:
                _run_async(_notify(t, body))
                notified += 1
            except Exception as e:
                logger.warning(f"[dispatch_watchdog] notify failed for task {t.id}: {e}")

        return {"expired": len(newly_failed), "notified": notified}
    except Exception as e:
        logger.warning(f"[dispatch_watchdog] check failed: {e}")
        return {"error": str(e)}
    finally:
        db.close()


async def _notify(task, body: str) -> None:
    from app.services.unified_notification import send_notification
    await send_notification(
        user_id=DEFAULT_USER_ID,
        title="A background task stalled",
        message=body,
        topic=f"dispatch_watchdog:{task.task_type}",
        priority="normal",
        source="dispatch_watchdog",
    )
