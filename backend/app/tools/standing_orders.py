"""
Standing Order Tools — Allow Sara to manage standing orders via chat.
"""

import json
import logging
from typing import Dict, Any

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class StandingOrderListTool(BaseTool):
    @property
    def name(self) -> str:
        return "standing_order_list"

    @property
    def description(self) -> str:
        return (
            "List David's active standing orders — pre-authorized autonomous actions "
            "Sara can execute without asking. Shows trigger, action, and execution count."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status",
                    "enum": ["active", "paused", "all"],
                },
            },
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            from app.services.standing_order_service import standing_order_service
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                status = kwargs.get("status", "active")
                if status == "all":
                    active = await standing_order_service.list_orders(db, user_id, "active")
                    paused = await standing_order_service.list_orders(db, user_id, "paused")
                    orders = active + paused
                else:
                    orders = await standing_order_service.list_orders(db, user_id, status)

                if not orders:
                    return ToolResult(success=True, data=[], message="No standing orders. Create them by saying things like 'always lock doors at midnight'.")
                return ToolResult(success=True, data=orders, message=f"{len(orders)} standing orders found")
            finally:
                db.close()
        except Exception as e:
            return ToolResult(success=False, message=str(e))


class StandingOrderCreateTool(BaseTool):
    @property
    def name(self) -> str:
        return "standing_order_create"

    @property
    def description(self) -> str:
        return (
            "Create a new standing order — a pre-authorized action Sara can execute autonomously. "
            "Use when David says 'always lock doors at midnight' or 'turn off lights when I leave'. "
            "Supports an optional CONDITION that must hold at fire time, which turns a mechanical "
            "trigger into a contextual one — e.g. 'wake me at 6 unless I slept badly' or 'remind me "
            "only if I'm not in a meeting'. See the condition parameter."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Human-readable description",
                },
                "trigger_type": {
                    "type": "string",
                    "enum": ["time", "climate", "presence", "state", "timer"],
                },
                "trigger_config": {
                    "type": "object",
                    "description": "For 'time': {hour, minute, days}. For 'climate': {temperature_below or temperature_above}. For 'presence': {state: 'away'|'home'}. For 'timer': {timer_title, one_shot: true} — fires when a timer with matching title completes; one_shot auto-deletes after execution.",
                },
                "action_type": {
                    "type": "string",
                    "enum": ["home_control", "notification", "all_lights_off", "lock_all"],
                },
                "action_config": {
                    "type": "object",
                    "description": "For 'home_control': {service, entity_id}. For 'notification': {title, message, urgency}. For bulk actions: {}.",
                },
                "condition": {
                    "type": "object",
                    "description": (
                        "OPTIONAL gate the trigger must satisfy to actually fire. Omit for an "
                        "unconditional order. A single clause, or a list of clauses (ALL must pass). "
                        "Clause types: "
                        "{type:'sleep_quality', min_hours:6} — only if David slept at least min_hours "
                        "last night (use for 'wake me UNLESS I slept badly'); "
                        "{type:'activity_state', not_in:['focused_work','in_meeting']} — only if his "
                        "current activity isn't in the list (also supports in:[...] / equals:'...'); "
                        "{type:'interruptibility', min:0.5} — only if he's interruptible enough. "
                        "Missing sensor data fails open (the action still fires)."
                    ),
                },
            },
            "required": ["description", "trigger_type", "trigger_config", "action_type", "action_config"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            from app.services.standing_order_service import standing_order_service
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                # Check for conflicts before creating
                conflicts = await standing_order_service.check_conflicts(
                    db=db,
                    description=kwargs["description"],
                    trigger_type=kwargs["trigger_type"],
                    action_type=kwargs["action_type"],
                    action_config=kwargs.get("action_config", {}),
                    trigger_config=kwargs.get("trigger_config", {}),
                )

                result = await standing_order_service.create_order(
                    db=db, user_id=user_id,
                    description=kwargs["description"],
                    trigger_type=kwargs["trigger_type"],
                    trigger_config=kwargs.get("trigger_config", {}),
                    action_type=kwargs["action_type"],
                    action_config=kwargs.get("action_config", {}),
                    source="user",
                    condition=kwargs.get("condition"),
                )

                msg = f"Standing order created: {kwargs['description']}"
                if conflicts:
                    result["warnings"] = conflicts
                    msg += f" (warnings: {'; '.join(conflicts)})"

                return ToolResult(success=True, data=result, message=msg)
            finally:
                db.close()
        except Exception as e:
            return ToolResult(success=False, message=str(e))


class StandingOrderModifyTool(BaseTool):
    @property
    def name(self) -> str:
        return "standing_order_modify"

    @property
    def description(self) -> str:
        return "Pause, resume, or delete a standing order by ID."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer", "description": "Standing order ID"},
                "action": {
                    "type": "string",
                    "enum": ["pause", "resume", "delete"],
                },
            },
            "required": ["order_id", "action"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            from app.services.standing_order_service import standing_order_service
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                order_id = kwargs["order_id"]
                action = kwargs["action"]
                if action == "pause":
                    await standing_order_service.pause_order(db, order_id)
                elif action == "resume":
                    await standing_order_service.resume_order(db, order_id)
                elif action == "delete":
                    await standing_order_service.delete_order(db, order_id)
                return ToolResult(success=True, message=f"Standing order #{order_id} {action}d")
            finally:
                db.close()
        except Exception as e:
            return ToolResult(success=False, message=str(e))


class ActionLedgerRecentTool(BaseTool):
    @property
    def name(self) -> str:
        return "action_ledger_recent"

    @property
    def description(self) -> str:
        return "Show recent autonomous actions Sara has taken. Shows what, when, and undo availability."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of recent actions", "default": 10},
            },
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            from sqlalchemy import text
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                limit = kwargs.get("limit", 10)
                result = db.execute(text("""
                    SELECT al.id, al.action_type, al.success, al.executed_at,
                           al.undo_available, al.undone, so.description
                    FROM action_ledger al
                    LEFT JOIN standing_order so ON al.standing_order_id = so.id
                    WHERE al.user_id = :user_id
                    ORDER BY al.executed_at DESC LIMIT :limit
                """), {"user_id": user_id, "limit": limit})
                actions = [
                    {
                        "id": r.id,
                        "description": r.description,
                        "action_type": r.action_type,
                        "success": r.success,
                        "executed_at": r.executed_at.isoformat() if r.executed_at else None,
                        "undo_available": r.undo_available and not r.undone,
                        "undone": r.undone,
                    }
                    for r in result.fetchall()
                ]
                return ToolResult(success=True, data=actions, message=f"{len(actions)} recent actions")
            finally:
                db.close()
        except Exception as e:
            return ToolResult(success=False, message=str(e))


class ActionUndoTool(BaseTool):
    @property
    def name(self) -> str:
        return "action_undo"

    @property
    def description(self) -> str:
        return "Undo a recent autonomous action by ledger ID. Only within the 5-minute undo window."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ledger_id": {"type": "integer", "description": "Action ledger ID to undo"},
            },
            "required": ["ledger_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            from app.services.standing_order_service import standing_order_service
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                result = await standing_order_service.undo_action(db, kwargs["ledger_id"])
                if result.get("success"):
                    return ToolResult(success=True, message="Action undone successfully")
                return ToolResult(success=False, message=result.get("reason", "Undo failed"))
            finally:
                db.close()
        except Exception as e:
            return ToolResult(success=False, message=str(e))


# Export for registry
STANDING_ORDER_TOOLS = [
    StandingOrderListTool(),
    StandingOrderCreateTool(),
    StandingOrderModifyTool(),
    ActionLedgerRecentTool(),
    ActionUndoTool(),
]
