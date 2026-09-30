"""verify_action — R03 (Sara repair plan 2026-09-25): ground a confirmation
or a challenge in the actual durable record instead of memory of the
conversation or optimistic re-narration.

Before this, "did you actually cancel that reminder?" had no honest answer
available: nothing but the model's own recollection of the conversation
(which is exactly what produced false reminder/research/chess/goal success
in the evidence — a model confidently re-asserting something it believed it
had done, or folding under pressure and confessing to something it never
did either way). `action_receipt_service.record_chat_tool_action` now
writes one durable row per mutating tool call that actually executed; this
tool is how the model reads that record back.
"""
from typing import Any, Dict

from app.tools.base import BaseTool, ToolResult


class VerifyActionTool(BaseTool):
    @property
    def name(self) -> str:
        return "verify_action"

    @property
    def description(self) -> str:
        return (
            "Check the actual durable record of what you did, before confirming or "
            "denying that an action happened. Use this whenever David asks 'did you "
            "actually do that?', challenges a claimed action, or you are about to state "
            "that something was completed and are not certain — never answer from memory "
            "of the conversation alone. Returns the real receipt(s): what ran, when, and "
            "whether it succeeded, failed, or is unverified. An empty result means no "
            "record was found — say so plainly ('I don't have a record of that'), do not "
            "treat it as proof the action never happened (it may have run through a "
            "different path) and do not treat it as proof it succeeded either."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Distinctive words identifying the target (e.g. a title, id, or "
                        "the subject David mentioned). Omit to see the most recent actions."
                    ),
                },
                "tool_name": {
                    "type": "string",
                    "description": "Restrict to one specific action type, e.g. 'reminders_cancel'.",
                },
                "this_conversation_only": {
                    "type": "boolean",
                    "description": (
                        "True (default) to check only this conversation's own actions. "
                        "Set false to check across all of David's conversations — use this "
                        "when he references something from an earlier session."
                    ),
                    "default": True,
                },
            },
        }

    async def execute(self, user_id: str, _conversation_id: str = None, **kwargs) -> ToolResult:
        from app.db.session import get_db
        from app.services.action_receipt_service import find_receipts

        query = kwargs.get("query")
        tool_name = kwargs.get("tool_name")
        this_conversation_only = kwargs.get("this_conversation_only", True)

        db_gen = get_db()
        db = next(db_gen)
        try:
            receipts = find_receipts(
                db,
                user_id=user_id,
                conversation_id=_conversation_id if this_conversation_only else None,
                tool_name=tool_name,
                query=query,
                limit=10,
            )
        finally:
            db.close()

        if not receipts:
            return ToolResult(
                success=True,
                data={"receipts": []},
                message=(
                    "No record found. This does not prove the action never happened — "
                    "only that there's no durable receipt for it matching this search. "
                    "Say plainly that you can't verify it, do not guess."
                ),
            )

        lines = []
        for r in receipts:
            when = r.get("executed_at") or r.get("created_at")
            status = r.get("status")
            undone = " (later undone)" if r.get("undone") else ""
            lines.append(f"- {r.get('action_type')} on {r.get('target')}: {status}{undone} at {when}")
        return ToolResult(
            success=True,
            data={"receipts": receipts},
            message=f"Found {len(receipts)} matching record(s):\n" + "\n".join(lines),
        )


ACTION_VERIFICATION_TOOLS = [VerifyActionTool()]
