"""
Tool for Sara to review her own ACS (Autonomous Cognition System) activity.

Gives conversational Sara visibility into what she's accomplished during
autonomous sessions — sessions, notes, interest graph, discoveries.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from zoneinfo import ZoneInfo

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

DAILY_PLAN_KEY = "sara:acs:daily_plan:{user_id}"


class ACSMyActivityTool(BaseTool):
    """Let Sara review her own autonomous activity."""

    @property
    def name(self) -> str:
        return "get_my_activity"

    @property
    def description(self) -> str:
        return (
            "Review Sara's own autonomous activity — sessions completed, notes created, "
            "topics explored, discoveries made, and interest graph highlights. Use when "
            "David asks what you've been working on, what you did today, or about your "
            "autonomous exploration. Also use to check your daily plan."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "yesterday", "week"],
                    "description": "Time period to review (default: today)",
                },
                "include_interest_graph": {
                    "type": "boolean",
                    "description": "Include top interest graph nodes (default: true)",
                },
            },
            "required": [],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        period = kwargs.get("period", "today")
        include_graph = kwargs.get("include_interest_graph", True)

        try:
            from app.db.session import get_async_session_factory
            from app.models.acs_session import ACSSession
            from app.models.acs_session_log import ACSSessionLog
            from app.models.acs_interest_node import ACSInterestNode
            from app.models.acs_show_david import ACSShowDavid
            from app.models.note import Note
            from sqlalchemy import select, func, and_, desc
            import redis.asyncio as aioredis
            from app.core.config import settings

            session_factory = get_async_session_factory()

            # Determine time window (Eastern time boundaries, stored as UTC)
            eastern = ZoneInfo("America/New_York")
            now_et = datetime.now(eastern)
            if period == "today":
                since = now_et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
                period_label = "today"
            elif period == "yesterday":
                yesterday_et = now_et - timedelta(days=1)
                since = yesterday_et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
                until = now_et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
                period_label = "yesterday"
            else:  # week
                since = (now_et - timedelta(days=7)).astimezone(timezone.utc)
                period_label = "this week"

            parts = []

            async with session_factory() as db:
                # 1. Sessions in period
                sess_q = select(ACSSessionLog).where(
                    and_(
                        ACSSessionLog.user_id == user_id,
                        ACSSessionLog.started_at >= since,
                    )
                )
                if period == "yesterday":
                    sess_q = sess_q.where(ACSSessionLog.started_at < until)
                sess_q = sess_q.order_by(desc(ACSSessionLog.started_at))
                result = await db.execute(sess_q)
                sessions = result.scalars().all()

                if sessions:
                    total_turns = sum(s.turns_completed or 0 for s in sessions)
                    total_notes = sum(s.notes_written or 0 for s in sessions)
                    total_nodes = sum(s.nodes_created or 0 for s in sessions)
                    total_edges = sum(s.edges_created or 0 for s in sessions)
                    total_minutes = sum(s.duration_minutes or 0 for s in sessions)
                    modes = {}
                    for s in sessions:
                        m = s.mode or "unknown"
                        modes[m] = modes.get(m, 0) + 1

                    parts.append(f"## Sessions ({period_label})")
                    parts.append(
                        f"- **{len(sessions)} sessions** totaling {total_minutes:.0f} minutes"
                    )
                    parts.append(f"- {total_turns} turns, {total_notes} notes written")
                    if total_nodes or total_edges:
                        parts.append(
                            f"- {total_nodes} interest nodes created, {total_edges} edges created"
                        )
                    mode_str = ", ".join(f"{m}: {c}" for m, c in sorted(modes.items()))
                    parts.append(f"- Modes: {mode_str}")

                    # Session details
                    parts.append("")
                    for s in sessions[:5]:
                        time_str = s.started_at.replace(tzinfo=timezone.utc).astimezone(eastern).strftime("%I:%M %p") if s.started_at else "?"
                        dur = f"{s.duration_minutes:.0f}m" if s.duration_minutes else "?"
                        summary_str = ""
                        if s.summary:
                            summary_str = f" — {s.summary[:150]}"
                        parts.append(
                            f"- **{time_str}** [{s.mode or '?'}] {dur}, "
                            f"{s.turns_completed or 0} turns, "
                            f"{s.notes_written or 0} notes{summary_str}"
                        )
                    if len(sessions) > 5:
                        parts.append(f"  _(+ {len(sessions) - 5} more sessions)_")
                else:
                    parts.append(f"## Sessions ({period_label})")
                    parts.append("No autonomous sessions in this period.")

                # 2. Notes created in Sara's Notes folder tree during period
                from app.models.folder import Folder
                from sqlalchemy.orm import selectinload

                # Find Sara's Notes root folder
                sara_folder_q = select(Folder).where(
                    and_(
                        Folder.user_id == user_id,
                        Folder.name == "Sara's Notes",
                    )
                )
                sf_result = await db.execute(sara_folder_q)
                sara_folder = sf_result.scalar_one_or_none()

                acs_notes = []
                if sara_folder:
                    # Get all subfolder IDs
                    subfolder_q = select(Folder.id).where(
                        Folder.parent_id == sara_folder.id
                    )
                    sf_ids_result = await db.execute(subfolder_q)
                    all_folder_ids = [sara_folder.id] + [r[0] for r in sf_ids_result.fetchall()]

                    notes_q = (
                        select(Note)
                        .options(selectinload(Note.folder))
                        .where(
                            and_(
                                Note.user_id == user_id,
                                Note.created_at >= since,
                                Note.folder_id.in_(all_folder_ids),
                            )
                        )
                        .order_by(desc(Note.created_at))
                        .limit(15)
                    )
                    if period == "yesterday":
                        notes_q = notes_q.where(Note.created_at < until)
                    result = await db.execute(notes_q)
                    acs_notes = result.scalars().all()

                if acs_notes:
                    parts.append(f"\n## Notes Created ({len(acs_notes)})")
                    for n in acs_notes:
                        folder_str = ""
                        if n.folder and n.folder.name != "Sara's Notes":
                            folder_str = f" [{n.folder.name}]"
                        parts.append(f"- {n.title}{folder_str}")

                # 3. Discoveries (show-david buffer)
                disc_q = select(ACSShowDavid).where(
                    and_(
                        ACSShowDavid.user_id == user_id,
                        ACSShowDavid.created_at >= since,
                    )
                ).order_by(desc(ACSShowDavid.priority)).limit(5)
                if period == "yesterday":
                    disc_q = disc_q.where(ACSShowDavid.created_at < until)
                result = await db.execute(disc_q)
                discoveries = result.scalars().all()

                if discoveries:
                    parts.append(f"\n## Discoveries & Insights")
                    for d in discoveries:
                        shown = " (already shared)" if d.shown else ""
                        parts.append(f"- **{d.title}**{shown}: {d.content[:200]}")

                # 4. Interest graph highlights
                if include_graph:
                    graph_q = select(ACSInterestNode).where(
                        and_(
                            ACSInterestNode.user_id == user_id,
                            ACSInterestNode.status == "active",
                        )
                    ).order_by(desc(ACSInterestNode.fascination)).limit(10)
                    result = await db.execute(graph_q)
                    nodes = result.scalars().all()

                    if nodes:
                        parts.append(f"\n## Interest Graph (top topics)")
                        for n in nodes:
                            engaged = f", engaged {n.times_engaged}x" if n.times_engaged else ""
                            depth_pct = f"{n.depth * 100:.0f}%" if n.depth else "0%"
                            parts.append(
                                f"- **{n.label}** (fascination: {n.fascination:.1f}, "
                                f"depth: {depth_pct}{engaged})"
                            )

            # 5. Daily plan from Redis
            try:
                r = aioredis.from_url(settings.redis_url, decode_responses=True)
                plan_key = DAILY_PLAN_KEY.format(user_id=user_id)
                plan = await r.get(plan_key)
                await r.aclose()
                if plan:
                    parts.append(f"\n## Today's Plan")
                    parts.append(plan)
            except Exception:
                pass

            report = "\n".join(parts) if parts else "No autonomous activity found for this period."

            return ToolResult(
                success=True,
                data={"period": period, "sessions_count": len(sessions) if sessions else 0},
                message=report,
            )

        except Exception as e:
            logger.error(f"Failed to fetch ACS activity: {e}", exc_info=True)
            return ToolResult(
                success=False,
                message=f"Failed to fetch activity: {e}",
            )


ACS_ACTIVITY_TOOLS = [ACSMyActivityTool()]
