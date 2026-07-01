"""
Simple personal lists — grocery by default, but any named list works
(packing, gift ideas, hardware store, ...). Plain DB-backed; deliberately NOT
wired to Home Assistant or anything external.
"""

import logging
from typing import Any, Dict, List

from sqlalchemy import text

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_LIST = "grocery"


def _db():
    from app.db.session import get_db
    return next(get_db())


def _norm(name: str) -> str:
    return (name or DEFAULT_LIST).strip().lower() or DEFAULT_LIST


class ListAddTool(BaseTool):
    @property
    def name(self) -> str:
        return "list_add"

    @property
    def description(self) -> str:
        return (
            "Add one or more items to a personal list (defaults to the grocery list). "
            "Use for 'add milk to my grocery list', 'put eggs and bread on the list', "
            "'add a tent to my packing list'. Items can include a quantity in the text "
            "(e.g. '2 gallons of milk')."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Items to add, e.g. ['milk', 'a dozen eggs', 'bread'].",
                },
                "list": {
                    "type": "string",
                    "description": "List name (default 'grocery'). E.g. 'packing', 'gifts'.",
                },
            },
            "required": ["items"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        items: List[str] = kwargs.get("items") or []
        items = [i.strip() for i in items if i and i.strip()]
        if not items:
            return ToolResult(success=False, message="No items to add.")
        list_name = _norm(kwargs.get("list"))
        db = _db()
        try:
            added = []
            for item in items:
                # De-dupe against unchecked items already on the list (case-insensitive).
                exists = db.execute(text("""
                    SELECT 1 FROM list_item
                    WHERE user_id = :uid AND list_name = :ln
                      AND checked = false AND lower(item) = lower(:item)
                    LIMIT 1
                """), {"uid": user_id, "ln": list_name, "item": item}).fetchone()
                if exists:
                    continue
                db.execute(text("""
                    INSERT INTO list_item (user_id, list_name, item)
                    VALUES (:uid, :ln, :item)
                """), {"uid": user_id, "ln": list_name, "item": item})
                added.append(item)
            db.commit()
            if not added:
                return ToolResult(success=True, message=f"Already on the {list_name} list — nothing new added.")
            return ToolResult(
                success=True,
                data={"list": list_name, "added": added},
                message=f"Added to the {list_name} list: {', '.join(added)}.",
            )
        except Exception as e:
            db.rollback()
            logger.error("list_add failed: %s", e, exc_info=True)
            return ToolResult(success=False, message=f"Couldn't add to the list: {e}")
        finally:
            db.close()


class ListViewTool(BaseTool):
    @property
    def name(self) -> str:
        return "list_view"

    @property
    def description(self) -> str:
        return (
            "Show the items on a personal list (defaults to the grocery list). "
            "Use for 'what's on my grocery list', 'show my packing list'."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "list": {"type": "string", "description": "List name (default 'grocery')."},
                "include_checked": {
                    "type": "boolean",
                    "description": "Include already-checked-off items (default false).",
                    "default": False,
                },
            },
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        list_name = _norm(kwargs.get("list"))
        include_checked = bool(kwargs.get("include_checked", False))
        db = _db()
        try:
            rows = db.execute(text("""
                SELECT id, item, quantity, checked
                FROM list_item
                WHERE user_id = :uid AND list_name = :ln
                  AND (:all OR checked = false)
                ORDER BY checked ASC, created_at ASC
            """), {"uid": user_id, "ln": list_name, "all": include_checked}).mappings().all()
            if not rows:
                return ToolResult(success=True, data={"list": list_name, "items": []},
                                  message=f"The {list_name} list is empty.")
            lines = []
            for r in rows:
                mark = "✓ " if r["checked"] else "• "
                qty = f"{r['quantity']} " if r["quantity"] else ""
                lines.append(f"{mark}{qty}{r['item']}")
            return ToolResult(
                success=True,
                data={"list": list_name, "items": [dict(r) for r in rows]},
                message=f"{list_name.capitalize()} list:\n" + "\n".join(lines),
            )
        finally:
            db.close()


class ListCheckTool(BaseTool):
    @property
    def name(self) -> str:
        return "list_check"

    @property
    def description(self) -> str:
        return (
            "Check off (mark as got/done) items on a personal list, by item text. "
            "Use for 'got the milk', 'check off eggs and bread'."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Items to check off (matched case-insensitively).",
                },
                "list": {"type": "string", "description": "List name (default 'grocery')."},
            },
            "required": ["items"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        items = [i.strip() for i in (kwargs.get("items") or []) if i and i.strip()]
        if not items:
            return ToolResult(success=False, message="No items to check off.")
        list_name = _norm(kwargs.get("list"))
        db = _db()
        try:
            done = []
            for item in items:
                res = db.execute(text("""
                    UPDATE list_item SET checked = true, checked_at = now()
                    WHERE user_id = :uid AND list_name = :ln
                      AND checked = false AND lower(item) = lower(:item)
                """), {"uid": user_id, "ln": list_name, "item": item})
                if res.rowcount:
                    done.append(item)
            db.commit()
            if not done:
                return ToolResult(success=True, message=f"Didn't find those on the {list_name} list.")
            return ToolResult(success=True, data={"list": list_name, "checked": done},
                              message=f"Checked off: {', '.join(done)}.")
        finally:
            db.close()


class ListRemoveTool(BaseTool):
    @property
    def name(self) -> str:
        return "list_remove"

    @property
    def description(self) -> str:
        return (
            "Remove items from a personal list, or clear the list entirely. "
            "Use for 'take milk off the list', 'clear my grocery list', "
            "'remove the checked-off items'."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific items to remove (matched case-insensitively).",
                },
                "list": {"type": "string", "description": "List name (default 'grocery')."},
                "clear": {
                    "type": "string",
                    "enum": ["checked", "all"],
                    "description": "Clear the whole list: 'checked' removes only checked-off items, 'all' empties it. Ignored if 'items' is given.",
                },
            },
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        list_name = _norm(kwargs.get("list"))
        items = [i.strip() for i in (kwargs.get("items") or []) if i and i.strip()]
        clear = kwargs.get("clear")
        db = _db()
        try:
            if items:
                removed = []
                for item in items:
                    res = db.execute(text("""
                        DELETE FROM list_item
                        WHERE user_id = :uid AND list_name = :ln AND lower(item) = lower(:item)
                    """), {"uid": user_id, "ln": list_name, "item": item})
                    if res.rowcount:
                        removed.append(item)
                db.commit()
                if not removed:
                    return ToolResult(success=True, message=f"Didn't find those on the {list_name} list.")
                return ToolResult(success=True, message=f"Removed from the {list_name} list: {', '.join(removed)}.")
            if clear == "all":
                res = db.execute(text("DELETE FROM list_item WHERE user_id = :uid AND list_name = :ln"),
                                 {"uid": user_id, "ln": list_name})
                db.commit()
                return ToolResult(success=True, message=f"Cleared the {list_name} list ({res.rowcount} item(s)).")
            if clear == "checked":
                res = db.execute(text("DELETE FROM list_item WHERE user_id = :uid AND list_name = :ln AND checked = true"),
                                 {"uid": user_id, "ln": list_name})
                db.commit()
                return ToolResult(success=True, message=f"Removed {res.rowcount} checked-off item(s) from the {list_name} list.")
            return ToolResult(success=False, message="Specify items to remove, or clear='checked'|'all'.")
        finally:
            db.close()


LIST_TOOLS = [ListAddTool(), ListViewTool(), ListCheckTool(), ListRemoveTool()]
