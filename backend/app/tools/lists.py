"""
Simple personal lists — grocery by default, but any named list works
(packing, gift ideas, hardware store, ...). Plain DB-backed; deliberately NOT
wired to Home Assistant or anything external.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_LIST = "grocery"


def _db():
    from app.db.session import get_db
    return next(get_db())


def _norm(name: str) -> str:
    return (name or DEFAULT_LIST).strip().lower() or DEFAULT_LIST


# ---------------------------------------------------------------------------
# Canonical list names — reliable-assistant plan Phase F, Tasks/lists/goals:
# "stable IDs and canonical names, no accidental completion, no forked lists."
# ---------------------------------------------------------------------------
#
# Finding 11: "List-name inconsistency causes a false 'actually it never saved'
# correction, forking the user's data across two differently-named lists."
# `_norm` lowercases and trims, which makes "Grocery" and "grocery" the same
# list and leaves "groceries", "grocery list" and "the grocery list" as three
# more. David then adds milk to one and reads back another, and the honest
# answer from the second list ("nothing there") reads as Sara losing his data.
#
# So a requested name is matched against the lists he ALREADY HAS before a new
# one is created. Deliberately conservative: only whitespace, case, a trailing
# "list", and a simple plural differ. "packing" never becomes "grocery".

_TRAILING_LIST_RE = re.compile(r"\s*\blists?\b\s*$", re.IGNORECASE)
_LEADING_ARTICLE_RE = re.compile(r"^\s*(?:the|my|our)\s+", re.IGNORECASE)


def _name_key(name: str) -> str:
    """A key that collapses only the differences that are never meaningful."""
    value = _LEADING_ARTICLE_RE.sub("", (name or "").strip().lower())
    value = _TRAILING_LIST_RE.sub("", value).strip()
    value = re.sub(r"[^a-z0-9]+", "", value)
    if value.endswith("ies") and len(value) > 4:
        value = value[:-3] + "y"
    elif value.endswith("es") and len(value) > 3:
        value = value[:-2]
    elif value.endswith("s") and not value.endswith("ss") and len(value) > 2:
        value = value[:-1]
    return value or _name_key(DEFAULT_LIST)


def existing_list_names(db, user_id: str) -> List[str]:
    rows = db.execute(text(
        "SELECT DISTINCT list_name FROM list_item WHERE user_id = :uid"
    ), {"uid": user_id}).fetchall()
    return [r[0] for r in rows if r[0]]


def resolve_list_name(db, user_id: str, requested: Optional[str]) -> Tuple[str, Optional[str]]:
    """(canonical_name, alias_note).

    `alias_note` is set only when the requested name differed from the list it
    resolved to, so the reply can say which list it actually used rather than
    letting David believe there are two.
    """
    asked = _norm(requested)
    try:
        names = existing_list_names(db, user_id)
    except Exception as exc:  # a read failure must not invent a new list
        logger.warning("list-name resolution skipped: %s", exc)
        return asked, None
    if asked in names:
        return asked, None
    key = _name_key(asked)
    for name in sorted(names):
        if _name_key(name) == key:
            note = None if name == asked else (
                f"(using your existing \"{name}\" list)"
            )
            return name, note
    return asked, None


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
        db = _db()
        try:
            list_name, alias_note = resolve_list_name(db, user_id, kwargs.get("list"))
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
                return ToolResult(
                    success=True,
                    data={"list": list_name, "added": [], "already_present": items},
                    message=(
                        f"Already on the {list_name} list — nothing new added."
                        + (f" {alias_note}" if alias_note else "")
                    ),
                )
            return ToolResult(
                success=True,
                data={"list": list_name, "added": added},
                message=(
                    f"Added to the {list_name} list: {', '.join(added)}."
                    + (f" {alias_note}" if alias_note else "")
                ),
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
        include_checked = bool(kwargs.get("include_checked", False))
        db = _db()
        try:
            list_name, alias_note = resolve_list_name(db, user_id, kwargs.get("list"))
            rows = db.execute(text("""
                SELECT id, item, quantity, checked
                FROM list_item
                WHERE user_id = :uid AND list_name = :ln
                  AND (:all OR checked = false)
                ORDER BY checked ASC, created_at ASC, id ASC
            """), {"uid": user_id, "ln": list_name, "all": include_checked}).mappings().all()
            if not rows:
                # An empty list and a list that does not exist are different
                # answers, and reading one back as the other is how finding 11's
                # false "it never saved" correction happened.
                other = [n for n in existing_list_names(db, user_id) if n != list_name]
                hint = f" Lists you do have: {', '.join(sorted(other))}." if other else ""
                return ToolResult(
                    success=True,
                    data={"list": list_name, "items": [], "other_lists": sorted(other)},
                    message=f"The {list_name} list is empty.{hint}",
                )
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
        db = _db()
        try:
            list_name, alias_note = resolve_list_name(db, user_id, kwargs.get("list"))
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
                # success=False, deliberately: nothing changed. Reporting a
                # no-op as success is what lets a reply say "checked off the
                # milk" when no such item existed — the same false-completion
                # shape as finding 20's unrequested completion, arriving
                # through a truthful-looking tool result.
                present = db.execute(text(
                    "SELECT item FROM list_item WHERE user_id = :uid AND list_name = :ln "
                    "AND checked = false ORDER BY created_at, id"
                ), {"uid": user_id, "ln": list_name}).fetchall()
                names = ", ".join(r[0] for r in present) or "nothing"
                return ToolResult(
                    success=False,
                    data={"list": list_name, "checked": [], "unchecked_items": [r[0] for r in present]},
                    message=(
                        f"Didn't find {', '.join(items)} on the {list_name} list — "
                        f"nothing was checked off. It currently has: {names}."
                    ),
                )
            return ToolResult(success=True, data={"list": list_name, "checked": done},
                              message=f"Checked off: {', '.join(done)}."
                                      + (f" {alias_note}" if alias_note else ""))
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
        items = [i.strip() for i in (kwargs.get("items") or []) if i and i.strip()]
        clear = kwargs.get("clear")
        db = _db()
        try:
            list_name, alias_note = resolve_list_name(db, user_id, kwargs.get("list"))
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
                    return ToolResult(
                        success=False,
                        data={"list": list_name, "removed": []},
                        message=(
                            f"Didn't find {', '.join(items)} on the {list_name} list — "
                            "nothing was removed."
                        ),
                    )
                return ToolResult(
                    success=True,
                    data={"list": list_name, "removed": removed},
                    message=f"Removed from the {list_name} list: {', '.join(removed)}.",
                )
            if clear == "all":
                res = db.execute(text("DELETE FROM list_item WHERE user_id = :uid AND list_name = :ln"),
                                 {"uid": user_id, "ln": list_name})
                db.commit()
                if not res.rowcount:
                    return ToolResult(
                        success=False,
                        message=f"The {list_name} list was already empty — nothing was cleared.",
                    )
                return ToolResult(success=True, data={"list": list_name, "cleared": res.rowcount},
                                  message=f"Cleared the {list_name} list ({res.rowcount} item(s)).")
            if clear == "checked":
                res = db.execute(text("DELETE FROM list_item WHERE user_id = :uid AND list_name = :ln AND checked = true"),
                                 {"uid": user_id, "ln": list_name})
                db.commit()
                if not res.rowcount:
                    return ToolResult(
                        success=False,
                        message=f"Nothing on the {list_name} list was checked off — nothing was removed.",
                    )
                return ToolResult(success=True, data={"list": list_name, "cleared": res.rowcount},
                                  message=f"Removed {res.rowcount} checked-off item(s) from the {list_name} list.")
            return ToolResult(success=False, message="Specify items to remove, or clear='checked'|'all'.")
        finally:
            db.close()


class ListCorrectItemTool(BaseTool):
    """Change what one item on a list SAYS — reliable-assistant plan Phase C4.

    "Expose coherent operations… Do not require the model to improvise coupled
    delete/create sequences." Without this, "make that two gallons of milk, not
    one" had to become remove + add, which is finding 28's shape: the item
    loses its place and its identity, and a half-completed pair leaves David
    with both or neither.
    """

    @property
    def name(self) -> str:
        return "list_correct_item"

    @property
    def description(self) -> str:
        return (
            "Change the wording of an item already on a list — 'make that two gallons "
            "of milk, not one', 'it's sourdough not rye', 'the tent, not the tarp'. "
            "Use this rather than removing and re-adding: the item keeps its place and "
            "its checked state, and there is no window where David has both or neither. "
            "Refuses without changing anything if the old wording isn't on the list."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "old_item": {
                    "type": "string",
                    "description": "The item as it currently reads on the list.",
                },
                "new_item": {
                    "type": "string",
                    "description": "What it should read instead.",
                },
                "list": {"type": "string", "description": "List name (default 'grocery')."},
            },
            "required": ["old_item", "new_item"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        old_item = (kwargs.get("old_item") or "").strip()
        new_item = (kwargs.get("new_item") or "").strip()
        if not old_item or not new_item:
            return ToolResult(
                success=False,
                message="Both old_item and new_item are required.",
            )
        db = _db()
        try:
            list_name, alias_note = resolve_list_name(db, user_id, kwargs.get("list"))
            matches = db.execute(text("""
                SELECT id, item, checked FROM list_item
                WHERE user_id = :uid AND list_name = :ln AND lower(item) = lower(:item)
                ORDER BY created_at, id
            """), {"uid": user_id, "ln": list_name, "item": old_item}).mappings().all()
            if not matches:
                present = db.execute(text(
                    "SELECT item FROM list_item WHERE user_id = :uid AND list_name = :ln "
                    "ORDER BY created_at, id"
                ), {"uid": user_id, "ln": list_name}).fetchall()
                names = ", ".join(r[0] for r in present) or "nothing"
                return ToolResult(
                    success=False,
                    message=(
                        f"\"{old_item}\" isn't on the {list_name} list — nothing changed. "
                        f"It has: {names}."
                    ),
                )
            if len(matches) > 1:
                return ToolResult(
                    success=False,
                    message=(
                        f"\"{old_item}\" is on the {list_name} list {len(matches)} times — "
                        "say which one you mean rather than having me guess."
                    ),
                )
            row = matches[0]
            if old_item.lower() == new_item.lower():
                return ToolResult(
                    success=False,
                    message=f"It already says \"{row['item']}\" — nothing to change.",
                )
            db.execute(text(
                "UPDATE list_item SET item = :new WHERE id = :id AND user_id = :uid"
            ), {"new": new_item, "id": row["id"], "uid": user_id})
            db.commit()
            return ToolResult(
                success=True,
                data={
                    "list": list_name, "item_id": row["id"],
                    "was": row["item"], "now": new_item,
                    "still_checked": bool(row["checked"]),
                },
                message=(
                    f"Changed \"{row['item']}\" to \"{new_item}\" on the {list_name} list."
                    + (f" {alias_note}" if alias_note else "")
                ),
            )
        except Exception as e:
            db.rollback()
            logger.error("list_correct_item failed: %s", e, exc_info=True)
            return ToolResult(success=False, message=f"Couldn't change the item: {e}")
        finally:
            db.close()


LIST_TOOLS = [
    ListAddTool(), ListViewTool(), ListCheckTool(), ListRemoveTool(),
    ListCorrectItemTool(),
]
