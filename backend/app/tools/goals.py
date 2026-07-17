"""
manage_goal — chat-side goal tool (PHENOMENAL_ASSISTANT_PLAN.md Phase 3.2).

sara_goal already has the right shape (plan/progress jsonb, last_progress_at)
and the ACS daemon already reads/writes it over its token-protected HTTP API
(app/routes/acs_daemon_tools.py). This gives David the same create/progress/
complete actions from a normal chat turn ("let's make X a goal"), using the
same DB shape so the daemon and chat are working the same list.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import text

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_GOAL_COLS = """id, title, why, created_by, status, plan, progress, artifacts,
                outcome, created_at, last_progress_at"""


def _goal_dict(row) -> dict:
    return {
        "id": str(row["id"]), "title": row["title"], "why": row["why"],
        "status": row["status"], "created_by": row["created_by"],
        "plan": row["plan"] or [], "progress": row["progress"] or [],
        "last_progress_at": row["last_progress_at"].isoformat() if row["last_progress_at"] else None,
    }


class ManageGoalTool(BaseTool):
    @property
    def name(self) -> str:
        return "manage_goal"

    @property
    def description(self) -> str:
        return (
            "Create, advance, or complete a persistent goal (survives across days, not just "
            "this conversation). Use when David says 'let's make X a goal', wants to track "
            "progress on something bigger than one sitting, or wants to mark a goal done/"
            "abandoned. action='create' needs title; action='progress' needs id + note; "
            "action='complete' needs id + outcome (and optionally status='abandoned' instead "
            "of the default 'done'). action='list' shows open goals."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "progress", "complete", "list"]},
                "id": {"type": "string", "description": "Goal id (required for progress/complete)."},
                "title": {"type": "string", "description": "Goal title (required for create)."},
                "why": {"type": "string", "description": "Why this matters (optional, for create)."},
                "note": {"type": "string", "description": "What moved (for progress)."},
                "outcome": {"type": "string", "description": "What came of it (required for complete)."},
                "status": {"type": "string", "enum": ["done", "abandoned"],
                          "description": "For complete; default 'done'."},
            },
            "required": ["action"],
        }

    async def execute(self, user_id: str, action: str, **kwargs) -> ToolResult:
        from app.db.session import get_async_session_factory
        session_factory = get_async_session_factory()
        async with session_factory() as db:
            try:
                if action == "list":
                    rows = (await db.execute(text(f"""
                        SELECT {_GOAL_COLS} FROM sara_goal WHERE status = 'open'
                        ORDER BY last_progress_at DESC NULLS LAST, created_at DESC LIMIT 25
                    """))).mappings().all()
                    return ToolResult(success=True, data={"goals": [_goal_dict(r) for r in rows]},
                                      message=f"{len(rows)} open goal(s)")

                if action == "create":
                    title = (kwargs.get("title") or "").strip()
                    if not title:
                        return ToolResult(success=False, message="Need a title to create a goal.")
                    open_count = (await db.execute(
                        text("SELECT COUNT(*) FROM sara_goal WHERE status = 'open'")
                    )).scalar() or 0
                    if open_count >= 5:
                        return ToolResult(success=False,
                            message="5 goals are already open — complete or abandon one before adding more.")
                    row = (await db.execute(text(f"""
                        INSERT INTO sara_goal (title, why, created_by, last_progress_at)
                        VALUES (:title, :why, 'david', NOW())
                        RETURNING {_GOAL_COLS}
                    """), {"title": title[:300], "why": (kwargs.get("why") or None)})).mappings().first()
                    await db.commit()
                    return ToolResult(success=True, data=_goal_dict(row), message=f"Goal created: {title}")

                if action in ("progress", "complete"):
                    goal_id = kwargs.get("id")
                    if not goal_id:
                        return ToolResult(success=False, message="Need the goal id.")
                    row = (await db.execute(
                        text(f"SELECT {_GOAL_COLS} FROM sara_goal WHERE id = :id"), {"id": goal_id}
                    )).mappings().first()
                    if not row:
                        return ToolResult(success=False, message=f"No goal found with id {goal_id}.")
                    if row["status"] != "open":
                        return ToolResult(success=False, message=f"That goal is already {row['status']}.")

                    progress = list(row["progress"] or [])
                    status_update = None
                    outcome = row["outcome"]

                    if action == "progress":
                        note = (kwargs.get("note") or "").strip()
                        if not note:
                            return ToolResult(success=False, message="Need a progress note.")
                        progress.append({"at": datetime.now(timezone.utc).isoformat(), "note": note})
                    else:  # complete
                        outcome_text = (kwargs.get("outcome") or "").strip()
                        if not outcome_text:
                            return ToolResult(success=False,
                                message="Closing a goal needs an outcome — what came of it?")
                        outcome = outcome_text
                        status_update = kwargs.get("status") or "done"

                    updated = (await db.execute(text(f"""
                        UPDATE sara_goal SET
                            progress = CAST(:progress AS jsonb),
                            status = COALESCE(:status, status),
                            outcome = COALESCE(:outcome, outcome),
                            last_progress_at = NOW(),
                            completed_at = CASE WHEN :status IS NOT NULL THEN NOW() ELSE completed_at END
                        WHERE id = :id
                        RETURNING {_GOAL_COLS}
                    """), {"id": goal_id, "progress": json.dumps(progress),
                           "status": status_update, "outcome": outcome})).mappings().first()
                    await db.commit()
                    verb = "closed" if status_update else "updated"
                    return ToolResult(success=True, data=_goal_dict(updated), message=f"Goal {verb}.")

                return ToolResult(success=False, message=f"Unknown action '{action}'.")
            except Exception as e:
                logger.warning(f"[manage_goal] {action} failed: {e}")
                return ToolResult(success=False, message=f"Goal action failed: {e}")
