"""
People tool — query the `person` table (PHENOMENAL_ASSISTANT_PLAN.md Phase 2).

Lets David ask "who am I overdue with?" / "who's new?" and have Sara answer
from the person table (built from email senders + chat mentions), instead
of having no data source for that question at all.
"""

import logging
from typing import Any, Dict

from sqlalchemy import text

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


def _db():
    from app.db.session import get_db
    return next(get_db())


class ListPeopleTool(BaseTool):
    @property
    def name(self) -> str:
        return "list_people"

    @property
    def description(self) -> str:
        return (
            "List people David has interacted with (from email + chat mentions), "
            "optionally filtered. Use for 'who am I overdue with?', 'who's new this week?', "
            "'who have I been talking to?'. filter='overdue' returns people who haven't "
            "been in touch for 2x their usual cadence; 'new' returns people first seen in "
            "the last 7 days; 'recent' returns the most recently interacted-with; omit for "
            "recent by default."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "enum": ["recent", "overdue", "new", "vip"],
                    "description": "Which slice of people to return (default 'recent').",
                },
                "limit": {"type": "integer", "description": "Max results (default 10)."},
            },
        }

    async def execute(self, user_id: str, filter: str = "recent", limit: int = 10, **kwargs) -> ToolResult:
        db = _db()
        limit = max(1, min(int(limit or 10), 50))
        try:
            if filter == "overdue":
                rows = db.execute(text("""
                    SELECT p.canonical_name, p.last_interaction_at, p.interaction_count,
                           EXTRACT(EPOCH FROM (now() - p.last_interaction_at)) / 86400.0 AS days_since
                    FROM person p
                    JOIN signal_baseline sb ON sb.user_id = p.user_id
                        AND sb.domain = 'people' AND sb.signal_key = 'cadence.' || p.id
                    WHERE p.user_id=:u AND p.muted = false AND sb.sample_count >= 2
                      AND EXTRACT(EPOCH FROM (now() - p.last_interaction_at)) / 3600.0 > 2 * sb.ewma
                    ORDER BY days_since DESC LIMIT :lim
                """), {"u": user_id, "lim": limit}).fetchall()
            elif filter == "new":
                rows = db.execute(text("""
                    SELECT canonical_name, last_interaction_at, interaction_count,
                           EXTRACT(EPOCH FROM (now() - first_seen_at)) / 86400.0 AS days_since
                    FROM person WHERE user_id=:u AND first_seen_at > now() - interval '7 days'
                    ORDER BY first_seen_at DESC LIMIT :lim
                """), {"u": user_id, "lim": limit}).fetchall()
            elif filter == "vip":
                rows = db.execute(text("""
                    SELECT canonical_name, last_interaction_at, interaction_count,
                           EXTRACT(EPOCH FROM (now() - last_interaction_at)) / 86400.0 AS days_since
                    FROM person WHERE user_id=:u AND is_vip = true
                    ORDER BY last_interaction_at DESC NULLS LAST LIMIT :lim
                """), {"u": user_id, "lim": limit}).fetchall()
            else:
                rows = db.execute(text("""
                    SELECT canonical_name, last_interaction_at, interaction_count,
                           EXTRACT(EPOCH FROM (now() - last_interaction_at)) / 86400.0 AS days_since
                    FROM person WHERE user_id=:u AND muted = false AND last_interaction_at IS NOT NULL
                    ORDER BY last_interaction_at DESC LIMIT :lim
                """), {"u": user_id, "lim": limit}).fetchall()

            people = [{
                "name": r[0],
                "last_interaction_at": r[1].isoformat() if r[1] else None,
                "interaction_count": int(r[2] or 0),
                "days_since": round(float(r[3]), 1) if r[3] is not None else None,
            } for r in rows]

            return ToolResult(success=True, data={"filter": filter, "people": people},
                              message=f"{len(people)} people ({filter})")
        except Exception as e:
            logger.warning(f"[list_people] query failed: {e}")
            return ToolResult(success=False, message=f"Couldn't look up people: {e}")
        finally:
            db.close()
