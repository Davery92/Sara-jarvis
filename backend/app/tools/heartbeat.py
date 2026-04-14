"""
Heartbeat tools — read-only access to Sara's heartbeat checklist.

Deprecated CRUD tools (AddHeartbeatItemTool, RemoveHeartbeatItemTool,
UpdateHeartbeatItemTool, UpdateHeartbeatFileTool) have been removed.
Use standing orders or automation system for heartbeat management.
"""
from typing import Dict, Any
from app.tools.base import BaseTool, ToolResult
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


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


# Export tools — only read-only tools remain
HEARTBEAT_TOOLS = [
    ListHeartbeatItemsTool(),
    ReadHeartbeatFileTool(),
]
