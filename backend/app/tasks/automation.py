"""
Celery tasks for automation system.

Provides:
- automation_watcher: Periodic task that finds and dispatches due automations
- automation_execute: Executes a single step of an automation task
"""
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.celery_app import celery_app
from app.services.automation.constants import AutomationStatus

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async function from a sync Celery task on a fresh loop."""
    from app.db.session import reset_async_session_factory

    reset_async_session_factory()
    return asyncio.run(coro)


@celery_app.task(
    name="app.tasks.automation.automation_watcher",
    bind=True,
    queue="cognitive",
    max_retries=2
)
def automation_watcher(self):
    """
    Periodic watcher that finds automations ready to execute.

    Runs every 30 seconds. Finds tasks where:
    - status = 'active'
    - next_wake_at <= now

    Dispatches automation_execute for each due task.
    """
    logger.debug("Automation watcher running...")

    try:
        result = _run_async(_automation_watcher_async())
        if result.get("dispatched", 0) > 0:
            logger.info(f"Automation watcher: dispatched {result['dispatched']} tasks")
        return result
    except Exception as e:
        logger.error(f"Automation watcher failed: {e}")
        raise self.retry(countdown=30, exc=e)


async def _automation_watcher_async():
    """Async implementation of automation watcher."""
    from sqlalchemy import text
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    dispatched = 0
    expired = 0
    errors = 0

    async with async_session() as db:
        now = datetime.now(timezone.utc)

        # Find tasks that are due
        result = await db.execute(
            text("""
                SELECT id, user_id, name, expires_at, max_executions, execution_count
                FROM automation_task
                WHERE status = :status
                AND next_wake_at <= :now
                ORDER BY next_wake_at ASC
                LIMIT 20
            """),
            {"now": now, "status": AutomationStatus.ACTIVE}
        )
        due_tasks = result.fetchall()

        for task_row in due_tasks:
            task_id, user_id, name, expires_at, max_executions, execution_count = task_row

            # Check expiration
            if expires_at and expires_at <= now:
                await db.execute(
                    text("""
                        UPDATE automation_task
                        SET status = :status,
                            last_error = 'Expired'
                        WHERE id = :task_id
                    """),
                    {"task_id": task_id, "status": AutomationStatus.COMPLETED}
                )
                expired += 1
                logger.info(f"Automation '{name}' ({task_id[:8]}) expired")
                continue

            # Check max executions
            if max_executions and execution_count >= max_executions:
                await db.execute(
                    text("""
                        UPDATE automation_task
                        SET status = :status,
                            last_error = 'Max executions reached'
                        WHERE id = :task_id
                    """),
                    {"task_id": task_id, "status": AutomationStatus.COMPLETED}
                )
                expired += 1
                logger.info(f"Automation '{name}' ({task_id[:8]}) reached max executions")
                continue

            # Dispatch execution
            try:
                automation_execute.delay(task_id)
                dispatched += 1
                logger.debug(f"Dispatched automation '{name}' ({task_id[:8]})")
            except Exception as e:
                logger.error(f"Failed to dispatch automation {task_id}: {e}")
                errors += 1

        await db.commit()

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dispatched": dispatched,
        "expired": expired,
        "errors": errors
    }


@celery_app.task(
    name="app.tasks.automation.automation_execute",
    bind=True,
    queue="cognitive",
    max_retries=1
)
def automation_execute(self, task_id: str):
    """
    Execute the next step of an automation task.

    Steps:
    1. Load task from DB
    2. Check conditions
    3. Execute current step's primitive
    4. Handle result
    5. Update state (current_step, next_wake_at, execution_count)
    6. Log execution
    """
    logger.info(f"Executing automation task: {task_id[:8]}...")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _automation_execute_async(task_id)
        )
        return result
    except RuntimeError:
        result = asyncio.run(_automation_execute_async(task_id))
        return result
    except Exception as e:
        logger.error(f"Automation execution failed for {task_id}: {e}")
        # Don't retry - let the watcher pick it up again
        raise


async def _automation_execute_async(task_id: str):
    """Async implementation of automation execution."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import os
    import json

    from app.services.automation.primitives import execute_primitive, PrimitiveResult
    from app.services.automation.safety import get_safety_validator
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        # Load task
        result = await db.execute(
            text("""
                SELECT id, user_id, name, schedule_definition, actions, conditions,
                       status, next_wake_at, current_step, step_state,
                       consecutive_errors, execution_count
                FROM automation_task
                WHERE id = :task_id
                FOR UPDATE SKIP LOCKED
            """),
            {"task_id": task_id}
        )
        row = result.fetchone()

        if not row:
            logger.warning(f"Automation task {task_id} not found or locked")
            return {"status": "not_found"}

        (
            task_id, user_id, name, schedule_definition, actions, conditions,
            status, next_wake_at, current_step, step_state,
            consecutive_errors, execution_count
        ) = row

        # Verify status is still active
        if status != AutomationStatus.ACTIVE:
            logger.info(f"Automation {task_id[:8]} no longer active (status={status})")
            return {"status": "skipped", "reason": "not_active"}

        # Check conditions before executing
        conditions_met = await _check_conditions(conditions, db)
        if not conditions_met:
            # Set next wake time and skip execution
            next_wake = _calculate_next_wake(schedule_definition)
            if next_wake is None:
                await db.execute(
                    text("""
                        UPDATE automation_task
                        SET status = :status,
                            last_error = 'One-time condition not met',
                            last_executed_at = NOW()
                        WHERE id = :task_id
                    """),
                    {"task_id": task_id, "status": AutomationStatus.COMPLETED}
                )
            else:
                await db.execute(
                    text("""
                        UPDATE automation_task
                        SET next_wake_at = :next_wake
                        WHERE id = :task_id
                    """),
                    {"task_id": task_id, "next_wake": next_wake}
                )
            await db.commit()
            logger.info(
                f"Automation '{name}' conditions not met, "
                + ("completed" if next_wake is None else "rescheduled")
            )
            return {"status": "condition_not_met"}

        # Get current action
        if not actions or current_step >= len(actions):
            # All steps done for this execution cycle
            next_wake = _calculate_next_wake(schedule_definition)
            if next_wake is None:
                await db.execute(
                    text("""
                        UPDATE automation_task
                        SET status = :status,
                            current_step = 0,
                            execution_count = execution_count + 1,
                            next_wake_at = NULL,
                            last_executed_at = NOW(),
                            consecutive_errors = 0
                        WHERE id = :task_id
                    """),
                    {"task_id": task_id, "status": AutomationStatus.COMPLETED}
                )
            else:
                await db.execute(
                    text("""
                        UPDATE automation_task
                        SET current_step = 0,
                            execution_count = execution_count + 1,
                            next_wake_at = :next_wake,
                            last_executed_at = NOW(),
                            consecutive_errors = 0
                        WHERE id = :task_id
                    """),
                    {"task_id": task_id, "next_wake": next_wake}
                )
            await db.commit()
            if next_wake is None:
                logger.info(f"Automation '{name}' completed one-time cycle")
            else:
                logger.info(f"Automation '{name}' completed cycle, rescheduled for {next_wake}")
            return {"status": "cycle_complete", "next_wake": next_wake.isoformat() if next_wake else None}

        action = actions[current_step]
        primitive = action.get("primitive")
        started_at = datetime.now(timezone.utc)

        # Build step state with user_id for notifications
        exec_step_state = step_state or {}
        exec_step_state["user_id"] = user_id

        # Execute the primitive
        exec_result = await execute_primitive(
            primitive=primitive,
            action=action,
            task_id=task_id,
            step_state=exec_step_state,
            db_session=db
        )

        completed_at = datetime.now(timezone.utc)
        exec_duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        # Log execution
        await db.execute(
            text("""
                INSERT INTO automation_execution_log
                (task_id, started_at, completed_at, step_executed, action_primitive, action_details, status, result, error_message)
                VALUES (:task_id, :started_at, :completed_at, :step, :primitive, CAST(:action_details AS jsonb), :status, CAST(:result AS jsonb), :error)
            """),
            {
                "task_id": task_id,
                "started_at": started_at,
                "completed_at": completed_at,
                "step": current_step,
                "primitive": primitive,
                "action_details": json.dumps(action),
                "status": exec_result.status.value,
                "result": json.dumps(exec_result.result) if exec_result.result else None,
                "error": exec_result.error
            }
        )

        # Write action trace (Phase 0 — Cortana Evolution)
        try:
            from app.services.autonomy.action_tracer import ActionTracer
            tracer = ActionTracer()
            await tracer.trace(
                db=db, run_uuid=None, user_id=user_id,
                source="automation", action_name=f"automation:{primitive}",
                action_args={"task_id": task_id, "step": current_step, "action": action},
                result=exec_result.result,
                success=(exec_result.status != PrimitiveResult.FAILED),
                error_message=exec_result.error,
                step_index=current_step,
                duration_ms=exec_duration_ms,
            )
        except Exception as e:
            logger.debug(f"Action trace write failed (non-fatal): {e}")

        # Handle result
        if exec_result.status == PrimitiveResult.FAILED:
            # Increment error count
            new_error_count = consecutive_errors + 1
            safety = get_safety_validator()

            if safety.should_pause_task(new_error_count):
                # Auto-pause due to too many errors
                await db.execute(
                    text("""
                        UPDATE automation_task
                        SET status = :status,
                            consecutive_errors = :errors,
                            last_error = :error
                        WHERE id = :task_id
                    """),
                    {"task_id": task_id, "errors": new_error_count, "error": exec_result.error, "status": AutomationStatus.FAILED}
                )
                await db.commit()
                logger.warning(f"Automation '{name}' auto-paused after {new_error_count} consecutive errors")
                return {"status": "auto_paused", "errors": new_error_count}
            else:
                # Retry later
                next_wake = _calculate_next_wake(schedule_definition)
                if next_wake is None:
                    await db.execute(
                        text("""
                            UPDATE automation_task
                            SET status = :status,
                                consecutive_errors = :errors,
                                last_error = :error,
                                last_executed_at = NOW()
                            WHERE id = :task_id
                        """),
                        {"task_id": task_id, "errors": new_error_count, "error": exec_result.error, "status": AutomationStatus.FAILED}
                    )
                else:
                    await db.execute(
                        text("""
                            UPDATE automation_task
                            SET consecutive_errors = :errors,
                                last_error = :error,
                                next_wake_at = :next_wake
                            WHERE id = :task_id
                        """),
                        {"task_id": task_id, "errors": new_error_count, "error": exec_result.error, "next_wake": next_wake}
                    )
                await db.commit()
                logger.warning(f"Automation '{name}' step {current_step} failed: {exec_result.error}")
                return {"status": "failed", "error": exec_result.error}

        elif exec_result.status == PrimitiveResult.CONDITION_NOT_MET:
            # Condition check failed - skip remaining steps
            next_wake = _calculate_next_wake(schedule_definition)
            if next_wake is None:
                await db.execute(
                    text("""
                        UPDATE automation_task
                        SET status = :status,
                            current_step = 0,
                            next_wake_at = NULL,
                            last_error = 'One-time condition not met',
                            last_executed_at = NOW()
                        WHERE id = :task_id
                    """),
                    {"task_id": task_id, "status": AutomationStatus.COMPLETED}
                )
            else:
                await db.execute(
                    text("""
                        UPDATE automation_task
                        SET current_step = 0,
                            next_wake_at = :next_wake,
                            last_executed_at = NOW()
                        WHERE id = :task_id
                    """),
                    {"task_id": task_id, "next_wake": next_wake}
                )
            await db.commit()
            logger.info(f"Automation '{name}' condition not met at step {current_step}")
            return {"status": "condition_not_met", "step": current_step}

        else:
            # Success - advance to next step
            next_step = current_step + 1

            # Check if there's a delay
            if exec_result.delay_seconds > 0:
                # Set wake time for after the delay
                next_wake = datetime.now(timezone.utc) + timedelta(seconds=exec_result.delay_seconds)
            elif next_step >= len(actions):
                # Completed all steps
                next_wake = _calculate_next_wake(schedule_definition)
                next_step = 0
                if next_wake is None:
                    await db.execute(
                        text("""
                            UPDATE automation_task
                            SET status = :status,
                                current_step = 0,
                                execution_count = execution_count + 1,
                                next_wake_at = NULL,
                                last_executed_at = NOW(),
                                consecutive_errors = 0
                            WHERE id = :task_id
                        """),
                        {"task_id": task_id, "status": AutomationStatus.COMPLETED}
                    )
                else:
                    await db.execute(
                        text("""
                            UPDATE automation_task
                            SET current_step = 0,
                                execution_count = execution_count + 1,
                                next_wake_at = :next_wake,
                                last_executed_at = NOW(),
                                consecutive_errors = 0
                            WHERE id = :task_id
                        """),
                        {"task_id": task_id, "next_wake": next_wake}
                    )
                await db.commit()
                if next_wake is None:
                    logger.info(f"Automation '{name}' completed one-time execution")
                else:
                    logger.info(f"Automation '{name}' completed all steps")
                return {"status": "cycle_complete", "next_wake": next_wake.isoformat() if next_wake else None}
            else:
                # More steps to execute - wake immediately
                next_wake = datetime.now(timezone.utc) + timedelta(seconds=1)

            await db.execute(
                text("""
                    UPDATE automation_task
                    SET current_step = :next_step,
                        next_wake_at = :next_wake,
                        consecutive_errors = 0
                    WHERE id = :task_id
                """),
                {"task_id": task_id, "next_step": next_step, "next_wake": next_wake}
            )
            await db.commit()

            logger.info(f"Automation '{name}' step {current_step} complete, next step {next_step}")
            return {"status": "step_complete", "step": current_step, "next_step": next_step}


async def _check_conditions(conditions: list, db) -> bool:
    """Check if all conditions are met."""
    if not conditions:
        return True

    from datetime import datetime
    import pytz

    now = datetime.now(pytz.timezone("America/New_York"))

    for condition in conditions:
        cond_type = condition.get("type")

        if cond_type == "time_window":
            start_time_str = condition.get("start", "00:00")
            end_time_str = condition.get("end", "23:59")

            start_parts = start_time_str.split(":")
            end_parts = end_time_str.split(":")

            start_hour, start_min = int(start_parts[0]), int(start_parts[1])
            end_hour, end_min = int(end_parts[0]), int(end_parts[1])

            current_minutes = now.hour * 60 + now.minute
            start_minutes = start_hour * 60 + start_min
            end_minutes = end_hour * 60 + end_min

            # Handle overnight windows (e.g., 22:00 - 06:00)
            if start_minutes <= end_minutes:
                # Normal window (same day)
                if not (start_minutes <= current_minutes <= end_minutes):
                    return False
            else:
                # Overnight window
                if not (current_minutes >= start_minutes or current_minutes <= end_minutes):
                    return False

        elif cond_type == "day_of_week":
            allowed_days = condition.get("days", [])  # 0=Monday, 6=Sunday
            if allowed_days and now.weekday() not in allowed_days:
                return False

        elif cond_type == "state_check":
            # Check HA entity state
            from app.services.ha_control_service import ha_control
            entity_id = condition.get("entity_id")
            expected_state = condition.get("state")
            if entity_id:
                try:
                    state = await ha_control.get_state(entity_id)
                    if state.get("state") != expected_state:
                        return False
                except Exception as e:
                    logger.warning(f"Failed to check HA state for condition: {e}")
                    return False

    return True


def _calculate_next_wake(schedule_definition: dict) -> Optional[datetime]:
    """Calculate the next wake time based on schedule."""
    schedule_type = schedule_definition.get("type")
    now = datetime.now(timezone.utc)

    if schedule_type == "interval":
        interval_seconds = schedule_definition.get("interval_seconds", 3600)
        return now + timedelta(seconds=interval_seconds)

    elif schedule_type == "one_time":
        # One-time tasks should schedule their initial run_at, then stop rescheduling.
        run_at_raw = schedule_definition.get("run_at")
        if not run_at_raw:
            return now
        try:
            if isinstance(run_at_raw, str):
                run_at = datetime.fromisoformat(run_at_raw.replace("Z", "+00:00"))
            else:
                run_at = run_at_raw
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=timezone.utc)
            return run_at if run_at > now else None
        except Exception:
            logger.warning(f"Invalid one_time run_at '{run_at_raw}', defaulting to immediate run")
            return now

    elif schedule_type == "cron":
        # Simple cron parsing - for full cron support, use croniter
        cron_expr = schedule_definition.get("cron_expr", "0 * * * *")
        try:
            from croniter import croniter
            cron = croniter(cron_expr, now)
            return cron.get_next(datetime)
        except ImportError:
            logger.warning("croniter not installed, using 1-hour fallback for cron schedule")
            return now + timedelta(hours=1)
        except Exception as e:
            logger.error(f"Failed to parse cron expression '{cron_expr}': {e}")
            return now + timedelta(hours=1)

    elif schedule_type == "state_change":
        # Poll at regular intervals
        poll_interval = schedule_definition.get("poll_interval_seconds", 300)
        return now + timedelta(seconds=poll_interval)

    else:
        # Default fallback
        return now + timedelta(hours=1)
