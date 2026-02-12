"""
Heartbeat tools.

These tools allow Sara and David to manage Sara's heartbeat checklist - the dynamic
watchlist of things to monitor, check, and track.
"""
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from app.tools.base import BaseTool, ToolResult
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import text
import json
import logging

logger = logging.getLogger(__name__)


class AddHeartbeatItemTool(BaseTool):
    """DEPRECATED: Tool for adding items to the heartbeat checklist.
    Use standing orders or automation system instead."""

    @property
    def name(self) -> str:
        return "add_heartbeat_item"

    @property
    def description(self) -> str:
        return """Add an item to Sara's heartbeat checklist. Use when:
- David asks to be reminded about something periodically
- David wants Sara to monitor a condition
- Sara identifies something worth tracking proactively

Item types:
- monitor: Persistent check that runs every heartbeat cycle (e.g., background task completion)
- time_bound: Expires after a date, then auto-removes (e.g., "check deploy status by Friday")
- conditional: Only triggers when condition is met (e.g., "alert if HRV < 40")

Check logic types:
- background_tasks: Check for completed background tasks
- meal_logging: Check if meals logged today (after specified time)
- home_assistant: Query Home Assistant entity state with optional auto-action
    Config for home_assistant:
    - entity_id: HA entity to monitor (e.g., "light.living_room")
    - expected_state: Expected state value (e.g., "off")
    - check_after_time: Only check after this time (e.g., "23:00" for 11 PM)
    - action_on_mismatch: Optional auto-action when state doesn't match
        - type: "turn_off", "turn_on", or "toggle"
    - require_confirmation: If true (default), generate nudge asking for confirmation
                           If false, execute action automatically
    Example: {"entity_id": "light.living_room", "expected_state": "off",
              "check_after_time": "23:00", "action_on_mismatch": {"type": "turn_off"},
              "require_confirmation": false}
- reminder: Simple reminder to surface to user
- hrv_threshold: Compare HRV to threshold
- conversation_gap: Hours since last conversation
- email_check: Check for new/important/action-required emails (config: check_type, from_sender, since_hours)
- custom: Sara figures it out from description"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "item_type": {
                    "type": "string",
                    "enum": ["monitor", "time_bound", "conditional"],
                    "description": "Type of heartbeat item"
                },
                "description": {
                    "type": "string",
                    "description": "Human-readable description of what to check"
                },
                "check_logic": {
                    "type": "string",
                    "enum": ["background_tasks", "meal_logging", "home_assistant", "reminder", "hrv_threshold", "conversation_gap", "email_check", "custom"],
                    "description": "How to evaluate this item"
                },
                "expires_at": {
                    "type": "string",
                    "description": "ISO datetime for time_bound items (e.g., '2026-02-10T23:59:59')"
                },
                "condition": {
                    "type": "string",
                    "description": "For conditional items: the trigger condition (e.g., 'hrv < 40', 'hours_since_conversation > 8')"
                },
                "config": {
                    "type": "object",
                    "description": "Additional configuration (e.g., entity_id for home_assistant, threshold values)"
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "Notification priority. High = push notification, low = context only"
                },
                "source_context": {
                    "type": "string",
                    "description": "What conversation or observation spawned this item"
                }
            },
            "required": ["item_type", "description", "check_logic"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Add a heartbeat item"""
        logger.warning("DEPRECATED: AddHeartbeatItemTool invoked — use standing orders or automation system instead")

        item_type = kwargs.get("item_type")
        description = kwargs.get("description")
        check_logic = kwargs.get("check_logic")
        expires_at = kwargs.get("expires_at")
        condition = kwargs.get("condition")
        config = kwargs.get("config", {})
        priority = kwargs.get("priority", "normal")
        source_context = kwargs.get("source_context")

        if not item_type or not description or not check_logic:
            return ToolResult(
                success=False,
                message="item_type, description, and check_logic are required"
            )

        # Validate time_bound items have expires_at
        if item_type == "time_bound" and not expires_at:
            return ToolResult(
                success=False,
                message="time_bound items require an expires_at datetime"
            )

        # Validate conditional items have condition
        if item_type == "conditional" and not condition:
            return ToolResult(
                success=False,
                message="conditional items require a condition"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Parse expires_at if provided
            expires_at_dt = None
            if expires_at:
                try:
                    expires_at_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                except ValueError:
                    return ToolResult(
                        success=False,
                        message=f"Invalid expires_at format: {expires_at}. Use ISO format."
                    )

            result = db.execute(text("""
                INSERT INTO heartbeat_items (
                    user_id, item_type, description, check_logic,
                    expires_at, condition, config, priority,
                    created_by, source_context, is_active
                )
                VALUES (
                    :user_id, :item_type, :description, :check_logic,
                    :expires_at, :condition, :config, :priority,
                    'sara', :source_context, true
                )
                RETURNING id
            """), {
                "user_id": user_id,
                "item_type": item_type,
                "description": description,
                "check_logic": check_logic,
                "expires_at": expires_at_dt,
                "condition": condition,
                "config": json.dumps(config) if config else "{}",
                "priority": priority,
                "source_context": source_context
            })

            item_id = result.fetchone()[0]
            db.commit()

            return ToolResult(
                success=True,
                data={
                    "id": item_id,
                    "item_type": item_type,
                    "description": description,
                    "check_logic": check_logic,
                    "expires_at": expires_at,
                    "condition": condition,
                    "priority": priority
                },
                message=f"Added heartbeat item: {description[:50]}..."
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to add heartbeat item: {str(e)}"
            )
        finally:
            db.close()


class ListHeartbeatItemsTool(BaseTool):
    """Tool for listing heartbeat items"""

    @property
    def name(self) -> str:
        return "list_heartbeat_items"

    @property
    def description(self) -> str:
        return "View current heartbeat checklist items. Shows what Sara is actively monitoring."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "item_type": {
                    "type": "string",
                    "enum": ["all", "monitor", "time_bound", "conditional"],
                    "description": "Filter by item type"
                },
                "include_inactive": {
                    "type": "boolean",
                    "description": "Include expired/removed items"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """List heartbeat items"""

        item_type = kwargs.get("item_type", "all")
        include_inactive = kwargs.get("include_inactive", False)

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            query = """
                SELECT id, item_type, description, check_logic,
                       expires_at, condition, config, priority,
                       created_at, created_by, source_context,
                       last_checked_at, last_triggered_at,
                       times_checked, times_triggered, is_active
                FROM heartbeat_items
                WHERE user_id = :user_id
            """

            params = {"user_id": user_id}

            if item_type != "all":
                query += " AND item_type = :item_type"
                params["item_type"] = item_type

            if not include_inactive:
                query += " AND is_active = true"

            query += " ORDER BY priority DESC, created_at DESC"

            result = db.execute(text(query), params).fetchall()

            items = {
                "monitors": [],
                "time_bound": [],
                "conditional": []
            }

            for row in result:
                item = {
                    "id": row.id,
                    "description": row.description,
                    "check_logic": row.check_logic,
                    "priority": row.priority,
                    "created_by": row.created_by,
                    "is_active": row.is_active,
                    "times_checked": row.times_checked,
                    "times_triggered": row.times_triggered,
                    "last_checked_at": row.last_checked_at.isoformat() if row.last_checked_at else None,
                    "last_triggered_at": row.last_triggered_at.isoformat() if row.last_triggered_at else None
                }

                if row.item_type == "time_bound":
                    item["expires_at"] = row.expires_at.isoformat() if row.expires_at else None
                    items["time_bound"].append(item)
                elif row.item_type == "conditional":
                    item["condition"] = row.condition
                    items["conditional"].append(item)
                else:
                    items["monitors"].append(item)

            total = len(items["monitors"]) + len(items["time_bound"]) + len(items["conditional"])

            return ToolResult(
                success=True,
                data=items,
                message=f"Found {total} heartbeat items ({len(items['monitors'])} monitors, {len(items['time_bound'])} time-bound, {len(items['conditional'])} conditional)"
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to list heartbeat items: {str(e)}"
            )
        finally:
            db.close()


class RemoveHeartbeatItemTool(BaseTool):
    """DEPRECATED: Tool for removing heartbeat items.
    Use standing orders or automation system instead."""

    @property
    def name(self) -> str:
        return "remove_heartbeat_item"

    @property
    def description(self) -> str:
        return "Remove an item from the heartbeat checklist. Use when an item is no longer needed."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "integer",
                    "description": "ID of the heartbeat item to remove"
                },
                "reason": {
                    "type": "string",
                    "description": "Why it's being removed (for logging)"
                }
            },
            "required": ["item_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Remove a heartbeat item"""
        logger.warning("DEPRECATED: RemoveHeartbeatItemTool invoked — use standing orders or automation system instead")

        item_id = kwargs.get("item_id")
        reason = kwargs.get("reason", "No reason provided")

        if not item_id:
            return ToolResult(
                success=False,
                message="item_id is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Verify the item exists and belongs to this user
            item = db.execute(text("""
                SELECT id, description FROM heartbeat_items
                WHERE id = :item_id AND user_id = :user_id
            """), {"item_id": item_id, "user_id": user_id}).fetchone()

            if not item:
                return ToolResult(
                    success=False,
                    message=f"Heartbeat item {item_id} not found"
                )

            # Soft delete by setting is_active = false
            db.execute(text("""
                UPDATE heartbeat_items
                SET is_active = false
                WHERE id = :item_id
            """), {"item_id": item_id})

            db.commit()

            return ToolResult(
                success=True,
                data={"id": item_id, "description": item.description, "reason": reason},
                message=f"Removed heartbeat item: {item.description[:50]}..."
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to remove heartbeat item: {str(e)}"
            )
        finally:
            db.close()


class UpdateHeartbeatItemTool(BaseTool):
    """DEPRECATED: Tool for updating heartbeat items.
    Use standing orders or automation system instead."""

    @property
    def name(self) -> str:
        return "update_heartbeat_item"

    @property
    def description(self) -> str:
        return "Modify an existing heartbeat item. Use to change description, condition, priority, or expiration."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "integer",
                    "description": "ID of the heartbeat item to update"
                },
                "description": {
                    "type": "string",
                    "description": "New description"
                },
                "condition": {
                    "type": "string",
                    "description": "New condition (for conditional items)"
                },
                "expires_at": {
                    "type": "string",
                    "description": "New expiration date (ISO format)"
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "New priority"
                },
                "is_active": {
                    "type": "boolean",
                    "description": "Reactivate or deactivate the item"
                }
            },
            "required": ["item_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Update a heartbeat item"""
        logger.warning("DEPRECATED: UpdateHeartbeatItemTool invoked — use standing orders or automation system instead")

        item_id = kwargs.get("item_id")

        if not item_id:
            return ToolResult(
                success=False,
                message="item_id is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Verify the item exists and belongs to this user
            item = db.execute(text("""
                SELECT id, description FROM heartbeat_items
                WHERE id = :item_id AND user_id = :user_id
            """), {"item_id": item_id, "user_id": user_id}).fetchone()

            if not item:
                return ToolResult(
                    success=False,
                    message=f"Heartbeat item {item_id} not found"
                )

            # Build update query dynamically
            updates = []
            params = {"item_id": item_id}

            if "description" in kwargs and kwargs["description"]:
                updates.append("description = :description")
                params["description"] = kwargs["description"]

            if "condition" in kwargs:
                updates.append("condition = :condition")
                params["condition"] = kwargs["condition"]

            if "expires_at" in kwargs and kwargs["expires_at"]:
                try:
                    expires_dt = datetime.fromisoformat(kwargs["expires_at"].replace('Z', '+00:00'))
                    updates.append("expires_at = :expires_at")
                    params["expires_at"] = expires_dt
                except ValueError:
                    return ToolResult(
                        success=False,
                        message=f"Invalid expires_at format"
                    )

            if "priority" in kwargs and kwargs["priority"]:
                updates.append("priority = :priority")
                params["priority"] = kwargs["priority"]

            if "is_active" in kwargs:
                updates.append("is_active = :is_active")
                params["is_active"] = kwargs["is_active"]

            if not updates:
                return ToolResult(
                    success=False,
                    message="No updates provided"
                )

            query = f"UPDATE heartbeat_items SET {', '.join(updates)} WHERE id = :item_id"
            db.execute(text(query), params)
            db.commit()

            return ToolResult(
                success=True,
                data={"id": item_id, "updates": list(params.keys())},
                message=f"Updated heartbeat item {item_id}"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to update heartbeat item: {str(e)}"
            )
        finally:
            db.close()


class ReadHeartbeatFileTool(BaseTool):
    """Tool for reading the HEARTBEAT.md file"""

    @property
    def name(self) -> str:
        return "read_heartbeat_file"

    @property
    def description(self) -> str:
        return """Read Sara's heartbeat checklist file (HEARTBEAT.md).
This file contains natural language rules that Sara evaluates every 30 minutes.
Use this to see what automatic checks and actions are configured."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {}
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Read the HEARTBEAT.md file"""
        from pathlib import Path

        heartbeat_path = Path(__file__).parent.parent.parent / "data" / "HEARTBEAT.md"

        try:
            if not heartbeat_path.exists():
                return ToolResult(
                    success=False,
                    message="HEARTBEAT.md file not found"
                )

            content = heartbeat_path.read_text()
            return ToolResult(
                success=True,
                data={"content": content, "path": str(heartbeat_path)},
                message=f"Read HEARTBEAT.md ({len(content)} characters)"
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to read HEARTBEAT.md: {str(e)}"
            )


class UpdateHeartbeatFileTool(BaseTool):
    """DEPRECATED: Tool for updating the HEARTBEAT.md file.
    Use standing orders or automation system instead."""

    @property
    def name(self) -> str:
        return "update_heartbeat_file"

    @property
    def description(self) -> str:
        return """Update Sara's heartbeat checklist file (HEARTBEAT.md).
Use this to add, modify, or remove rules that Sara evaluates every 30 minutes.
The file uses Markdown format with sections for different time periods.

Example format:
## After 11 PM (Late Night Checks)
- Check if living room lights are on. If so, turn them off.

## Always (Every Heartbeat)
- Check for action-required emails older than 4 hours."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The new content for HEARTBEAT.md"
                },
                "append_section": {
                    "type": "string",
                    "description": "If provided, append this as a new section instead of replacing entire file"
                },
                "remove_section": {
                    "type": "string",
                    "description": "If provided, remove the section with this heading"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Update the HEARTBEAT.md file"""
        logger.warning("DEPRECATED: UpdateHeartbeatFileTool invoked — use standing orders or automation system instead")
        from pathlib import Path
        import re

        heartbeat_path = Path(__file__).parent.parent.parent / "data" / "HEARTBEAT.md"
        content = kwargs.get("content")
        append_section = kwargs.get("append_section")
        remove_section = kwargs.get("remove_section")

        try:
            # Read existing content
            existing_content = ""
            if heartbeat_path.exists():
                existing_content = heartbeat_path.read_text()

            if content:
                # Replace entire file
                new_content = content
            elif append_section:
                # Append a new section
                new_content = existing_content.rstrip() + "\n\n" + append_section + "\n"
            elif remove_section:
                # Remove a section by heading
                # Find the section and remove it (from ## heading to next ## or end)
                pattern = rf'(^|\n)(## {re.escape(remove_section)}.*?)(?=\n## |\Z)'
                new_content = re.sub(pattern, '', existing_content, flags=re.DOTALL)
                new_content = new_content.strip() + "\n"
            else:
                return ToolResult(
                    success=False,
                    message="Must provide content, append_section, or remove_section"
                )

            # Write the file
            heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            heartbeat_path.write_text(new_content)

            return ToolResult(
                success=True,
                data={"path": str(heartbeat_path), "length": len(new_content)},
                message=f"Updated HEARTBEAT.md ({len(new_content)} characters)"
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to update HEARTBEAT.md: {str(e)}"
            )


# Export tools
HEARTBEAT_TOOLS = [
    AddHeartbeatItemTool(),
    ListHeartbeatItemsTool(),
    RemoveHeartbeatItemTool(),
    UpdateHeartbeatItemTool(),
    ReadHeartbeatFileTool(),
    UpdateHeartbeatFileTool(),
]
