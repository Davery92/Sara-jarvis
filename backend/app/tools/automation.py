"""
Automation tools for Sara to create and manage automation tasks.

These tools allow Sara to:
- Parse natural language automation requests
- Create pending tasks for user confirmation
- Confirm, pause, resume, and cancel automations
- List and modify existing automations
"""
from app.tools.base import BaseTool, ToolResult
from app.services.automation.constants import AutomationStatus
from typing import Optional
from datetime import datetime, timezone, timedelta
import logging
import json
import uuid

logger = logging.getLogger(__name__)


class AutomationCreateTool(BaseTool):
    """Create a new automation task from natural language."""

    name = "automation_create"
    description = """Create a new automation task from a natural language description.
    Examples:
    - "turn the heat on for an hour every two hours"
    - "alert me if the garage door opens after 10pm"
    - "turn on the office lights at 8am weekdays"
    - "remind me to take a break every 2 hours"

    Returns a task in pending_confirmation status that requires user confirmation via automation_confirm."""

    parameters = {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "description": "The natural language description of what the automation should do"
            },
            "expires_hours": {
                "type": "integer",
                "description": "Hours until automation expires (default 24, max 168 for 1 week)",
                "default": 24
            }
        },
        "required": ["intent"]
    }

    async def execute(self, user_id: str, intent: str, expires_hours: int = 24, **kwargs) -> ToolResult:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import text
        import os

        from app.services.automation.intent_parser import parse_automation_intent, generate_confirmation_message, validate_and_enhance_intent
        from app.services.automation.safety import get_safety_validator
        from app.services.ha_control_service import ha_control

        try:
            # Fetch HA entities first so LLM can use correct entity names
            available_entities = []
            try:
                states = await ha_control.get_states()
                available_entities = [
                    {
                        "entity_id": s["entity_id"],
                        "friendly_name": s.get("attributes", {}).get("friendly_name", s["entity_id"]),
                    }
                    for s in states
                ]
                logger.info(f"Fetched {len(available_entities)} HA entities for automation parsing")
            except Exception as ha_error:
                logger.warning(f"Could not fetch HA entities: {ha_error}")

            # Parse the intent with HA entity context
            parsed = await parse_automation_intent(intent, available_entities=available_entities if available_entities else None)

            if parsed.parse_confidence < 0.3:
                return ToolResult(
                    success=False,
                    message=f"I couldn't understand that automation request. {parsed.description}"
                )

            # Validate
            parsed, warnings = await validate_and_enhance_intent(parsed)

            # Safety validation
            safety = get_safety_validator()
            is_valid, errors = safety.validate_task({
                "schedule_definition": parsed.schedule_definition,
                "actions": parsed.actions,
                "conditions": parsed.conditions,
                "expires_at": parsed.expires_at.isoformat() if parsed.expires_at else None
            })

            if not is_valid:
                return ToolResult(
                    success=False,
                    message=f"This automation has safety issues: {'; '.join(errors)}"
                )

            # Connect to database
            database_url = os.getenv("DATABASE_URL")

            if database_url.startswith("postgresql://"):
                async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
            elif database_url.startswith("postgresql+psycopg://"):
                async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
            else:
                async_url = database_url

            engine = create_async_engine(async_url, echo=False)
            async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

            async with async_session() as db:
                # Check user limits
                can_create, limit_error = await safety.check_user_task_limit(db, user_id)
                if not can_create:
                    return ToolResult(success=False, message=limit_error)

                # Create the task
                task_id = str(uuid.uuid4())
                now = datetime.now(timezone.utc)

                await db.execute(
                    text("""
                        INSERT INTO automation_task
                        (id, user_id, name, original_intent, description, schedule_definition,
                         actions, conditions, status, expires_at, max_executions, created_at)
                        VALUES (:id, :user_id, :name, :intent, :description, CAST(:schedule AS jsonb),
                                CAST(:actions AS jsonb), CAST(:conditions AS jsonb), :status,
                                :expires_at, :max_executions, :created_at)
                    """),
                    {
                        "id": task_id,
                        "user_id": user_id,
                        "name": parsed.name,
                        "intent": intent,
                        "description": parsed.description,
                        "schedule": json.dumps(parsed.schedule_definition),
                        "actions": json.dumps(parsed.actions),
                        "conditions": json.dumps(parsed.conditions),
                        "status": AutomationStatus.PENDING_CONFIRMATION,
                        "expires_at": parsed.expires_at,
                        "max_executions": parsed.max_executions,
                        "created_at": now
                    }
                )
                await db.commit()

            await engine.dispose()

            # Generate confirmation message
            confirmation = generate_confirmation_message(parsed)

            warning_text = ""
            if warnings:
                warning_text = f"\n\nWarnings:\n- " + "\n- ".join(warnings)

            return ToolResult(
                success=True,
                message=f"I've prepared this automation for you:\n\n{confirmation}{warning_text}\n\nTo activate, say 'confirm' or use automation_confirm with task_id '{task_id}'.",
                data={
                    "task_id": task_id,
                    "name": parsed.name,
                    "status": "pending_confirmation",
                    "confidence": parsed.parse_confidence,
                    "warnings": warnings
                }
            )

        except Exception as e:
            logger.error(f"automation_create failed: {e}", exc_info=True)
            return ToolResult(success=False, message=f"Failed to create automation: {e}")


class AutomationConfirmTool(BaseTool):
    """Confirm and activate a pending automation task."""

    name = "automation_confirm"
    description = """Confirm and activate a pending automation task.
    Use this after automation_create to activate the automation.
    If task_id is not provided, confirms the most recent pending automation.
    The task will start executing according to its schedule."""

    parameters = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The ID of the pending automation task to confirm. If not provided, confirms the most recent pending task."
            }
        },
        "required": []
    }

    async def execute(self, user_id: str, task_id: str = None, **kwargs) -> ToolResult:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import text
        import os

        from app.services.automation.safety import get_safety_validator
        from app.tasks.automation import _calculate_next_wake

        try:
            database_url = os.getenv("DATABASE_URL")

            if database_url.startswith("postgresql://"):
                async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
            elif database_url.startswith("postgresql+psycopg://"):
                async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
            else:
                async_url = database_url

            engine = create_async_engine(async_url, echo=False)
            async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

            async with async_session() as db:
                # If no task_id provided, find the most recent pending automation
                if not task_id:
                    result = await db.execute(
                        text("""
                            SELECT id, name, schedule_definition
                            FROM automation_task
                            WHERE user_id = :user_id AND status = :status
                            ORDER BY created_at DESC
                            LIMIT 1
                        """),
                        {"user_id": user_id, "status": AutomationStatus.PENDING_CONFIRMATION}
                    )
                    row = result.fetchone()
                    if not row:
                        return ToolResult(success=False, message="No pending automations found to confirm.")
                    task_id, name, schedule_definition = row
                    status = "pending_confirmation"
                    logger.info(f"Auto-selected most recent pending automation: {task_id} ({name})")
                else:
                    # Get the specified task
                    result = await db.execute(
                        text("""
                            SELECT name, schedule_definition, status
                            FROM automation_task
                            WHERE id = :task_id AND user_id = :user_id
                        """),
                        {"task_id": task_id, "user_id": user_id}
                    )
                    row = result.fetchone()

                    if not row:
                        return ToolResult(success=False, message="Automation task not found.")

                    name, schedule_definition, status = row

                if status != AutomationStatus.PENDING_CONFIRMATION:
                    return ToolResult(
                        success=False,
                        message=f"This automation is already {status}. Only pending automations can be confirmed."
                    )

                # Check global limits
                safety = get_safety_validator()
                can_create, limit_error = await safety.check_global_task_limit(db)
                if not can_create:
                    return ToolResult(success=False, message=limit_error)

                # Calculate first wake time
                next_wake = _calculate_next_wake(schedule_definition)
                now = datetime.now(timezone.utc)
                if next_wake is None and schedule_definition.get("type") == "one_time":
                    next_wake = now

                # Activate the task
                await db.execute(
                    text("""
                        UPDATE automation_task
                        SET status = :status,
                            confirmed_at = :now,
                            next_wake_at = :next_wake
                        WHERE id = :task_id
                    """),
                    {"task_id": task_id, "now": now, "next_wake": next_wake, "status": AutomationStatus.ACTIVE}
                )
                await db.commit()

            await engine.dispose()

            # Convert to EST for display
            from zoneinfo import ZoneInfo
            est = ZoneInfo("America/New_York")
            if next_wake:
                next_wake_est = next_wake.astimezone(est)
                next_wake_str = next_wake_est.strftime("%I:%M %p")
            else:
                next_wake_str = "soon"
            return ToolResult(
                success=True,
                message=f"Automation '{name}' is now active! First execution at {next_wake_str} ET.",
                data={
                    "task_id": task_id,
                    "name": name,
                    "status": "active",
                    "next_wake_at": next_wake.isoformat() if next_wake else None
                }
            )

        except Exception as e:
            logger.error(f"automation_confirm failed: {e}", exc_info=True)
            return ToolResult(success=False, message=f"Failed to confirm automation: {e}")


class AutomationListTool(BaseTool):
    """List all automation tasks for the user."""

    name = "automation_list"
    description = """List all automation tasks for the user.
    Can filter by status: active, paused, pending_confirmation, completed, failed, cancelled."""

    parameters = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Filter by status (active, paused, pending_confirmation, completed, failed, cancelled)",
                "enum": ["active", "paused", "pending_confirmation", "completed", "failed", "cancelled"]
            }
        }
    }

    async def execute(self, user_id: str, status: Optional[str] = None, **kwargs) -> ToolResult:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import text
        import os

        try:
            database_url = os.getenv("DATABASE_URL")

            if database_url.startswith("postgresql://"):
                async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
            elif database_url.startswith("postgresql+psycopg://"):
                async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
            else:
                async_url = database_url

            engine = create_async_engine(async_url, echo=False)
            async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

            async with async_session() as db:
                query = """
                    SELECT id, name, status, schedule_definition->>'type' as schedule_type,
                           next_wake_at, execution_count, last_executed_at, last_error
                    FROM automation_task
                    WHERE user_id = :user_id
                """

                if status:
                    query += " AND status = :status"
                    result = await db.execute(text(query + " ORDER BY created_at DESC"), {"user_id": user_id, "status": status})
                else:
                    result = await db.execute(text(query + " ORDER BY created_at DESC"), {"user_id": user_id})

                rows = result.fetchall()

            await engine.dispose()

            if not rows:
                filter_msg = f" with status '{status}'" if status else ""
                return ToolResult(
                    success=True,
                    message=f"You have no automation tasks{filter_msg}.",
                    data={"tasks": []}
                )

            tasks = []
            for row in rows:
                task_id, name, task_status, schedule_type, next_wake, exec_count, last_exec, last_error = row
                tasks.append({
                    "id": task_id,
                    "name": name,
                    "status": task_status,
                    "schedule_type": schedule_type,
                    "next_wake_at": next_wake.isoformat() if next_wake else None,
                    "execution_count": exec_count or 0,
                    "last_executed_at": last_exec.isoformat() if last_exec else None,
                    "last_error": last_error
                })

            # Format for display
            lines = [f"Your automation tasks ({len(tasks)} total):"]
            for t in tasks:
                status_emoji = {
                    "active": "🟢",
                    "paused": "⏸️",
                    "pending_confirmation": "⏳",
                    "completed": "✅",
                    "failed": "❌",
                    "cancelled": "🚫"
                }.get(t["status"], "❓")
                lines.append(f"{status_emoji} {t['name']} ({t['status']}, {t['execution_count']} runs)")

            return ToolResult(
                success=True,
                message="\n".join(lines),
                data={"tasks": tasks}
            )

        except Exception as e:
            logger.error(f"automation_list failed: {e}", exc_info=True)
            return ToolResult(success=False, message=f"Failed to list automations: {e}")


class AutomationCancelTool(BaseTool):
    """Cancel an automation task."""

    name = "automation_cancel"
    description = """Cancel an automation task by name or ID.
    Cancelled tasks stop executing and cannot be resumed."""

    parameters = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The ID of the automation task to cancel (or use name)"
            },
            "name": {
                "type": "string",
                "description": "The name of the automation task to cancel (if task_id not provided)"
            }
        }
    }

    async def execute(self, user_id: str, task_id: Optional[str] = None, name: Optional[str] = None, **kwargs) -> ToolResult:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import text
        import os

        if not task_id and not name:
            return ToolResult(success=False, message="Please provide either task_id or name to cancel.")

        try:
            database_url = os.getenv("DATABASE_URL")

            if database_url.startswith("postgresql://"):
                async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
            elif database_url.startswith("postgresql+psycopg://"):
                async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
            else:
                async_url = database_url

            engine = create_async_engine(async_url, echo=False)
            async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

            async with async_session() as db:
                if task_id:
                    result = await db.execute(
                        text("""
                            UPDATE automation_task
                            SET status = :new_status
                            WHERE id = :task_id AND user_id = :user_id
                            AND status NOT IN (:s_completed, :s_cancelled)
                            RETURNING name
                        """),
                        {"task_id": task_id, "user_id": user_id, "new_status": AutomationStatus.CANCELLED, "s_completed": AutomationStatus.COMPLETED, "s_cancelled": AutomationStatus.CANCELLED}
                    )
                else:
                    result = await db.execute(
                        text("""
                            UPDATE automation_task
                            SET status = :new_status
                            WHERE LOWER(name) = LOWER(:name) AND user_id = :user_id
                            AND status NOT IN (:s_completed, :s_cancelled)
                            RETURNING name
                        """),
                        {"name": name, "user_id": user_id, "new_status": AutomationStatus.CANCELLED, "s_completed": AutomationStatus.COMPLETED, "s_cancelled": AutomationStatus.CANCELLED}
                    )

                row = result.fetchone()
                await db.commit()

            await engine.dispose()

            if not row:
                return ToolResult(
                    success=False,
                    message="Automation not found or already completed/cancelled."
                )

            return ToolResult(
                success=True,
                message=f"Automation '{row[0]}' has been cancelled.",
                data={"name": row[0], "status": "cancelled"}
            )

        except Exception as e:
            logger.error(f"automation_cancel failed: {e}", exc_info=True)
            return ToolResult(success=False, message=f"Failed to cancel automation: {e}")


class AutomationModifyTool(BaseTool):
    """Modify an existing automation (pause, resume, extend)."""

    name = "automation_modify"
    description = """Modify an existing automation task.
    Actions: pause, resume, extend (add more time before expiration)."""

    parameters = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The ID of the automation task to modify"
            },
            "action": {
                "type": "string",
                "description": "The action to perform: pause, resume, or extend",
                "enum": ["pause", "resume", "extend"]
            },
            "extend_hours": {
                "type": "integer",
                "description": "Hours to extend expiration (only for 'extend' action)",
                "default": 24
            }
        },
        "required": ["task_id", "action"]
    }

    async def execute(self, user_id: str, task_id: str, action: str, extend_hours: int = 24, **kwargs) -> ToolResult:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import text
        import os

        try:
            database_url = os.getenv("DATABASE_URL")

            if database_url.startswith("postgresql://"):
                async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
            elif database_url.startswith("postgresql+psycopg://"):
                async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
            else:
                async_url = database_url

            engine = create_async_engine(async_url, echo=False)
            async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

            async with async_session() as db:
                # Get current task
                result = await db.execute(
                    text("""
                        SELECT name, status, expires_at
                        FROM automation_task
                        WHERE id = :task_id AND user_id = :user_id
                    """),
                    {"task_id": task_id, "user_id": user_id}
                )
                row = result.fetchone()

                if not row:
                    return ToolResult(success=False, message="Automation not found.")

                name, status, expires_at = row

                if action == "pause":
                    if status != AutomationStatus.ACTIVE:
                        return ToolResult(success=False, message=f"Cannot pause - automation is {status}.")

                    await db.execute(
                        text("UPDATE automation_task SET status = :status WHERE id = :task_id"),
                        {"task_id": task_id, "status": AutomationStatus.PAUSED}
                    )
                    await db.commit()
                    await engine.dispose()
                    return ToolResult(
                        success=True,
                        message=f"Automation '{name}' is now paused.",
                        data={"name": name, "status": "paused"}
                    )

                elif action == "resume":
                    if status not in (AutomationStatus.PAUSED, AutomationStatus.FAILED):
                        return ToolResult(success=False, message=f"Cannot resume - automation is {status}.")

                    now = datetime.now(timezone.utc)
                    await db.execute(
                        text("""
                            UPDATE automation_task
                            SET status = :status, next_wake_at = :now, consecutive_errors = 0
                            WHERE id = :task_id
                        """),
                        {"task_id": task_id, "now": now, "status": AutomationStatus.ACTIVE}
                    )
                    await db.commit()
                    await engine.dispose()
                    return ToolResult(
                        success=True,
                        message=f"Automation '{name}' has been resumed.",
                        data={"name": name, "status": "active"}
                    )

                elif action == "extend":
                    new_expires = (expires_at or datetime.now(timezone.utc)) + timedelta(hours=extend_hours)
                    max_expires = datetime.now(timezone.utc) + timedelta(days=7)
                    if new_expires > max_expires:
                        new_expires = max_expires

                    await db.execute(
                        text("UPDATE automation_task SET expires_at = :expires WHERE id = :task_id"),
                        {"task_id": task_id, "expires": new_expires}
                    )
                    await db.commit()
                    await engine.dispose()
                    # Convert to EST for display
                    from zoneinfo import ZoneInfo
                    est = ZoneInfo("America/New_York")
                    new_expires_est = new_expires.astimezone(est)
                    return ToolResult(
                        success=True,
                        message=f"Automation '{name}' extended until {new_expires_est.strftime('%Y-%m-%d %I:%M %p')} ET.",
                        data={"name": name, "expires_at": new_expires.isoformat()}
                    )

                else:
                    return ToolResult(success=False, message=f"Unknown action: {action}")

        except Exception as e:
            logger.error(f"automation_modify failed: {e}", exc_info=True)
            return ToolResult(success=False, message=f"Failed to modify automation: {e}")


# List of automation tools for registration
AUTOMATION_TOOLS = [
    AutomationCreateTool(),
    AutomationConfirmTool(),
    AutomationListTool(),
    AutomationCancelTool(),
    AutomationModifyTool(),
]
