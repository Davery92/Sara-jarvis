"""
Automation REST API routes.

Provides endpoints for:
- Listing user's automations
- Getting automation details
- Execution history
- Pause/Resume/Cancel controls
- WebSocket stream for real-time updates
"""
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import json
import logging
import asyncio

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/automation", tags=["automation"])


# Pydantic models
class AutomationTaskResponse(BaseModel):
    id: str
    name: str
    original_intent: str
    description: Optional[str]
    status: str
    schedule_type: str
    next_wake_at: Optional[datetime]
    execution_count: int
    max_executions: Optional[int]
    expires_at: Optional[datetime]
    last_executed_at: Optional[datetime]
    created_at: datetime
    consecutive_errors: int
    last_error: Optional[str]

    class Config:
        from_attributes = True


class AutomationDetailResponse(AutomationTaskResponse):
    schedule_definition: Dict[str, Any]
    actions: List[Dict[str, Any]]
    conditions: List[Dict[str, Any]]
    current_step: int


class ExecutionLogResponse(BaseModel):
    id: int
    started_at: datetime
    completed_at: Optional[datetime]
    step_executed: int
    action_primitive: str
    status: str
    result: Optional[Dict[str, Any]]
    error_message: Optional[str]

    class Config:
        from_attributes = True


class AutomationCreateRequest(BaseModel):
    name: str = Field(..., max_length=255)
    original_intent: str
    description: Optional[str] = None
    schedule_definition: Dict[str, Any]
    actions: List[Dict[str, Any]]
    conditions: Optional[List[Dict[str, Any]]] = []
    expires_at: Optional[datetime] = None
    max_executions: Optional[int] = None


class AutomationConfirmResponse(BaseModel):
    id: str
    name: str
    status: str
    next_wake_at: Optional[datetime]
    message: str


class AutomationTestRequest(BaseModel):
    intent: str = Field(..., min_length=5, max_length=1000)
    model: Optional[str] = None  # Optional custom model for parsing


class AutomationTestResponse(BaseModel):
    success: bool
    name: str
    description: str
    schedule_type: str
    schedule_definition: Dict[str, Any]
    actions: List[Dict[str, Any]]
    conditions: List[Dict[str, Any]]
    expires_at: Optional[datetime]
    max_executions: Optional[int]
    confirmation_summary: str
    human_readable_summary: str
    parse_confidence: float
    warnings: List[str]
    validation_errors: List[str]


@router.post("/test", response_model=AutomationTestResponse)
async def test_automation_intent(
    request: AutomationTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Test an automation intent without creating it.

    This endpoint parses a natural language automation request and returns
    what the system would do, without actually creating or executing anything.

    Use this to preview automations before confirming them.
    """
    from app.services.automation.intent_parser import (
        parse_automation_intent,
        generate_confirmation_message,
        validate_and_enhance_intent
    )
    from app.services.automation.safety import AutomationSafetyValidator
    from app.services.ha_control_service import ha_control

    try:
        # Fetch real HA entities FIRST so LLM can use correct entity names
        available_entities = []
        available_entity_ids = []
        ha_connected = False
        try:
            states = await ha_control.get_states()
            # Build rich entity list with friendly names for the LLM
            available_entities = [
                {
                    "entity_id": s["entity_id"],
                    "friendly_name": s.get("attributes", {}).get("friendly_name", s["entity_id"]),
                    "state": s.get("state")
                }
                for s in states
            ]
            available_entity_ids = [s["entity_id"] for s in states]
            ha_connected = True
            logger.info(f"Fetched {len(available_entities)} entities from Home Assistant for LLM context")
        except Exception as ha_error:
            logger.warning(f"Could not connect to Home Assistant: {ha_error}")

        # Parse the intent with optional custom model AND available entities
        parsed = await parse_automation_intent(
            request.intent,
            model=request.model,
            available_entities=available_entities if ha_connected else None
        )

        # Validate and get warnings (pass entity IDs for validation)
        parsed, warnings = await validate_and_enhance_intent(parsed, available_entity_ids if ha_connected else None)

        # Add HA connection status to warnings
        if not ha_connected:
            warnings.append("Could not connect to Home Assistant - entity validation skipped")

        # Run safety validation
        validator = AutomationSafetyValidator()
        validation_errors = []

        # Validate the full task
        task_definition = {
            "schedule_definition": parsed.schedule_definition,
            "actions": parsed.actions,
            "conditions": parsed.conditions,
            "expires_at": parsed.expires_at.isoformat() if parsed.expires_at else None
        }
        is_valid, errors = validator.validate_task(task_definition)
        validation_errors.extend(errors)

        # Generate human-readable summary
        human_readable = generate_confirmation_message(parsed)

        return AutomationTestResponse(
            success=parsed.parse_confidence > 0.3 and len(validation_errors) == 0,
            name=parsed.name,
            description=parsed.description,
            schedule_type=parsed.schedule_definition.get("type", "unknown"),
            schedule_definition=parsed.schedule_definition,
            actions=parsed.actions,
            conditions=parsed.conditions,
            expires_at=parsed.expires_at,
            max_executions=parsed.max_executions,
            confirmation_summary=parsed.confirmation_summary,
            human_readable_summary=human_readable,
            parse_confidence=parsed.parse_confidence,
            warnings=warnings,
            validation_errors=validation_errors
        )

    except Exception as e:
        logger.exception(f"Error testing automation intent: {e}")
        return AutomationTestResponse(
            success=False,
            name="Error",
            description=str(e),
            schedule_type="error",
            schedule_definition={},
            actions=[],
            conditions=[],
            expires_at=None,
            max_executions=None,
            confirmation_summary="Failed to parse intent",
            human_readable_summary=f"Error: {str(e)}",
            parse_confidence=0.0,
            warnings=[],
            validation_errors=[str(e)]
        )


@router.get("/tasks", response_model=List[AutomationTaskResponse])
async def list_automations(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List all automation tasks for the current user.

    Optional filter by status: pending_confirmation, active, paused, completed, failed, cancelled
    """
    try:
        user_id = current_user.id

        query = """
            SELECT id, name, original_intent, description, status,
                   schedule_definition->>'type' as schedule_type,
                   next_wake_at, execution_count, max_executions,
                   expires_at, last_executed_at, created_at,
                   consecutive_errors, last_error
            FROM automation_task
            WHERE user_id = :user_id
        """

        if status:
            query += " AND status = :status"
            query += " ORDER BY created_at DESC"
            result = db.execute(text(query), {"user_id": user_id, "status": status})
        else:
            query += " ORDER BY created_at DESC"
            result = db.execute(text(query), {"user_id": user_id})

        tasks = []
        for row in result.fetchall():
            tasks.append(AutomationTaskResponse(
                id=row[0],
                name=row[1],
                original_intent=row[2],
                description=row[3],
                status=row[4],
                schedule_type=row[5] or "unknown",
                next_wake_at=row[6],
                execution_count=row[7] or 0,
                max_executions=row[8],
                expires_at=row[9],
                last_executed_at=row[10],
                created_at=row[11],
                consecutive_errors=row[12] or 0,
                last_error=row[13]
            ))

        return tasks

    except Exception as e:
        logger.error(f"Error listing automations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}", response_model=AutomationDetailResponse)
async def get_automation(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get detailed information about a specific automation."""
    try:
        user_id = current_user.id

        result = db.execute(
            text("""
                SELECT id, name, original_intent, description, status,
                       schedule_definition, actions, conditions,
                       schedule_definition->>'type' as schedule_type,
                       next_wake_at, execution_count, max_executions,
                       expires_at, last_executed_at, created_at,
                       consecutive_errors, last_error, current_step
                FROM automation_task
                WHERE id = :task_id AND user_id = :user_id
            """),
            {"task_id": task_id, "user_id": user_id}
        )
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Automation not found")

        return AutomationDetailResponse(
            id=row[0],
            name=row[1],
            original_intent=row[2],
            description=row[3],
            status=row[4],
            schedule_definition=row[5],
            actions=row[6],
            conditions=row[7] or [],
            schedule_type=row[8] or "unknown",
            next_wake_at=row[9],
            execution_count=row[10] or 0,
            max_executions=row[11],
            expires_at=row[12],
            last_executed_at=row[13],
            created_at=row[14],
            consecutive_errors=row[15] or 0,
            last_error=row[16],
            current_step=row[17] or 0
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting automation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}/logs", response_model=List[ExecutionLogResponse])
async def get_execution_logs(
    task_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get execution history for an automation."""
    try:
        user_id = current_user.id

        # Verify ownership
        result = db.execute(
            text("SELECT 1 FROM automation_task WHERE id = :task_id AND user_id = :user_id"),
            {"task_id": task_id, "user_id": user_id}
        )
        if not result.fetchone():
            raise HTTPException(status_code=404, detail="Automation not found")

        result = db.execute(
            text("""
                SELECT id, started_at, completed_at, step_executed,
                       action_primitive, status, result, error_message
                FROM automation_execution_log
                WHERE task_id = :task_id
                ORDER BY started_at DESC
                LIMIT :limit
            """),
            {"task_id": task_id, "limit": limit}
        )

        logs = []
        for row in result.fetchall():
            logs.append(ExecutionLogResponse(
                id=row[0],
                started_at=row[1],
                completed_at=row[2],
                step_executed=row[3],
                action_primitive=row[4],
                status=row[5],
                result=row[6],
                error_message=row[7]
            ))

        return logs

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting execution logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/pause")
async def pause_automation(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Pause an active automation."""
    try:
        user_id = current_user.id

        result = db.execute(
            text("""
                UPDATE automation_task
                SET status = 'paused'
                WHERE id = :task_id AND user_id = :user_id AND status = 'active'
                RETURNING name
            """),
            {"task_id": task_id, "user_id": user_id}
        )
        row = result.fetchone()
        db.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Automation not found or not active")

        return {"success": True, "message": f"Automation '{row[0]}' paused"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error pausing automation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/resume")
async def resume_automation(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Resume a paused or failed automation."""
    try:
        user_id = current_user.id
        now = datetime.now(timezone.utc)

        result = db.execute(
            text("""
                UPDATE automation_task
                SET status = 'active',
                    next_wake_at = :now,
                    consecutive_errors = 0
                WHERE id = :task_id AND user_id = :user_id AND status IN ('paused', 'failed')
                RETURNING name
            """),
            {"task_id": task_id, "user_id": user_id, "now": now}
        )
        row = result.fetchone()
        db.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Automation not found or not paused/failed")

        return {"success": True, "message": f"Automation '{row[0]}' resumed"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error resuming automation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/cancel")
async def cancel_automation(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cancel an automation."""
    try:
        user_id = current_user.id

        result = db.execute(
            text("""
                UPDATE automation_task
                SET status = 'cancelled'
                WHERE id = :task_id AND user_id = :user_id
                AND status NOT IN ('completed', 'cancelled')
                RETURNING name
            """),
            {"task_id": task_id, "user_id": user_id}
        )
        row = result.fetchone()
        db.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Automation not found or already completed/cancelled")

        return {"success": True, "message": f"Automation '{row[0]}' cancelled"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error cancelling automation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_automation_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get automation statistics for the current user."""
    try:
        user_id = current_user.id

        result = db.execute(
            text("""
                SELECT status, COUNT(*)
                FROM automation_task
                WHERE user_id = :user_id
                GROUP BY status
            """),
            {"user_id": user_id}
        )
        status_counts = dict(result.fetchall())

        result = db.execute(
            text("""
                SELECT COUNT(*)
                FROM automation_execution_log l
                JOIN automation_task t ON l.task_id = t.id
                WHERE t.user_id = :user_id
                AND l.started_at > NOW() - INTERVAL '24 hours'
            """),
            {"user_id": user_id}
        )
        executions_24h = result.scalar() or 0

        return {
            "status_counts": status_counts,
            "total_tasks": sum(status_counts.values()),
            "active_count": status_counts.get("active", 0),
            "executions_24h": executions_24h
        }

    except Exception as e:
        logger.error(f"Error getting automation stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# WebSocket for real-time updates
active_connections: Dict[str, List[WebSocket]] = {}


@router.websocket("/stream")
async def automation_stream(websocket: WebSocket, db: Session = Depends(get_db)):
    """
    WebSocket endpoint for real-time automation execution events.

    Clients can subscribe to receive:
    - Execution started/completed events
    - Status changes
    - Error notifications
    """
    await websocket.accept()

    # TODO: Add proper auth for WebSocket
    user_id = "default"

    if user_id not in active_connections:
        active_connections[user_id] = []
    active_connections[user_id].append(websocket)

    try:
        while True:
            # Keep connection alive and listen for messages
            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                data = json.loads(message)

                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

            except asyncio.TimeoutError:
                # Send keepalive
                await websocket.send_json({"type": "keepalive"})

    except WebSocketDisconnect:
        active_connections[user_id].remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if websocket in active_connections.get(user_id, []):
            active_connections[user_id].remove(websocket)


async def broadcast_automation_event(user_id: str, event: Dict[str, Any]):
    """Broadcast an automation event to all connected clients for a user."""
    if user_id in active_connections:
        for connection in active_connections[user_id]:
            try:
                await connection.send_json(event)
            except Exception as e:
                logger.error(f"Failed to send WebSocket event: {e}")
