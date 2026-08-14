"""
Agent Memory — cross-agent memory and situation briefs.

Wraps agent_run_log with a higher-level API so any agent can:
- Record what it did
- Record what it noticed
- Set cross-agent watches
- Ask "what happened since my last run?"
- Get a pre-digested situation brief

No LLM calls — pure DB query + template formatting.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = get_owner_id()


async def record_action(
    db: AsyncSession,
    user_id: str,
    source: str,
    action_type: str,
    summary: str,
    details: Optional[Dict] = None,
) -> Optional[int]:
    """
    Record an action taken by any agent.
    Returns the agent_run_log ID or None on failure.
    """
    try:
        result = await db.execute(text("""
            INSERT INTO agent_run_log
            (user_id, run_at, context_summary, actions_taken, source)
            VALUES
            (:uid, NOW(), :summary, CAST(:actions AS jsonb), :source)
            RETURNING id
        """), {
            "uid": user_id,
            "summary": summary,
            "actions": json.dumps([{"type": action_type, "details": details or {}}]),
            "source": source,
        })
        row = result.fetchone()
        await db.commit()
        return row.id if row else None
    except Exception as e:
        logger.warning(f"[AgentMemory] record_action failed: {e}")
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def record_observation(
    db: AsyncSession,
    user_id: str,
    source: str,
    observation: str,
    tags: Optional[List[str]] = None,
) -> Optional[int]:
    """Record an observation (not an action) from any agent."""
    try:
        result = await db.execute(text("""
            INSERT INTO agent_run_log
            (user_id, run_at, observations, source,
             actions_taken, conversation_flags)
            VALUES
            (:uid, NOW(), :obs, :source,
             '[]'::jsonb, CAST(:tags AS jsonb))
            RETURNING id
        """), {
            "uid": user_id,
            "obs": observation,
            "source": source,
            "tags": json.dumps(tags or []),
        })
        row = result.fetchone()
        await db.commit()
        return row.id if row else None
    except Exception as e:
        logger.warning(f"[AgentMemory] record_observation failed: {e}")
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def set_watch(
    db: AsyncSession,
    user_id: str,
    source: str,
    what: str,
    until: Optional[datetime] = None,
) -> None:
    """Set a cross-agent watch (visible to all agents via get_active_watches)."""
    try:
        expires = until.isoformat() if until else None
        await db.execute(text("""
            INSERT INTO agent_run_log
            (user_id, run_at, watching_for, source,
             actions_taken, context_summary)
            VALUES
            (:uid, NOW(), :watch, :source,
             '[]'::jsonb, :ctx)
        """), {
            "uid": user_id,
            "watch": what,
            "source": source,
            "ctx": f"Watch set: {what}" + (f" (until {expires})" if expires else ""),
        })
        await db.commit()
    except Exception as e:
        logger.warning(f"[AgentMemory] set_watch failed: {e}")
        try:
            await db.rollback()
        except Exception:
            pass


async def get_active_watches(
    db: AsyncSession,
    user_id: str,
) -> List[Dict[str, Any]]:
    """Get all active watches from all agents (set in last 24 hours)."""
    try:
        result = await db.execute(text("""
            SELECT source, watching_for, run_at
            FROM agent_run_log
            WHERE user_id = :uid
              AND watching_for IS NOT NULL
              AND watching_for != ''
              AND run_at >= NOW() - INTERVAL '24 hours'
            ORDER BY run_at DESC
            LIMIT 10
        """), {"uid": user_id})
        rows = result.fetchall()
        return [
            {"source": r.source, "watching_for": r.watching_for, "set_at": r.run_at.isoformat()}
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"[AgentMemory] get_active_watches failed: {e}")
        return []


async def get_recent_actions(
    db: AsyncSession,
    user_id: str,
    since_hours: float = 4.0,
    sources: Optional[List[str]] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Get recent actions from specific or all agents."""
    try:
        query = """
            SELECT id, source, run_at, context_summary, actions_taken,
                   notifications_sent, observations, handoff_note, watching_for
            FROM agent_run_log
            WHERE user_id = :uid
              AND run_at >= NOW() - :interval * INTERVAL '1 hour'
        """
        params: Dict[str, Any] = {"uid": user_id, "interval": since_hours}

        if sources:
            query += " AND source = ANY(:sources)"
            params["sources"] = sources

        query += " ORDER BY run_at DESC LIMIT :lim"
        params["lim"] = limit

        result = await db.execute(text(query), params)
        rows = result.fetchall()

        actions = []
        for r in rows:
            entry: Dict[str, Any] = {
                "id": r.id,
                "source": r.source,
                "at": r.run_at.isoformat(),
                "summary": r.context_summary,
            }
            if r.actions_taken:
                acts = r.actions_taken if isinstance(r.actions_taken, list) else json.loads(r.actions_taken)
                if acts:
                    entry["actions"] = acts
            if r.observations:
                entry["observations"] = r.observations
            if r.handoff_note:
                entry["handoff"] = r.handoff_note
            if r.watching_for:
                entry["watching_for"] = r.watching_for
            actions.append(entry)

        return actions
    except Exception as e:
        logger.warning(f"[AgentMemory] get_recent_actions failed: {e}")
        return []


async def build_situation_brief(
    db: AsyncSession,
    user_id: str,
    requesting_agent: str,
    max_tokens: int = 500,
) -> str:
    """
    Build a pre-digested brief for any agent about recent cross-agent activity.

    Example output:
    "Since your last run: anticipation prepared 3 items, subconscious detected
    FOCUSED_WORK, no notifications sent. Active watches: [gymnastics at 7pm].
    Changes since David's last chat (2.3h ago): 2 emails arrived, temp dropped to 28F."
    """
    parts = []

    # 1. Recent actions from other agents
    try:
        actions = await get_recent_actions(db, user_id, since_hours=2.0, limit=15)
        other_actions = [a for a in actions if a["source"] != requesting_agent]

        if other_actions:
            summaries = []
            for a in other_actions[:8]:  # Cap at 8 entries
                src = a["source"]
                summary = a.get("summary", "")
                if summary:
                    summaries.append(f"  - [{src}] {summary[:120]}")
                elif a.get("observations"):
                    summaries.append(f"  - [{src}] Observed: {a['observations'][:100]}")
            if summaries:
                parts.append("Recent agent activity:\n" + "\n".join(summaries))
        else:
            parts.append("No other agent activity in the last 2 hours.")
    except Exception:
        pass

    # 2. Active watches
    try:
        watches = await get_active_watches(db, user_id)
        if watches:
            watch_strs = [f"{w['watching_for']} (set by {w['source']})" for w in watches[:5]]
            parts.append(f"Active watches: {'; '.join(watch_strs)}")
    except Exception:
        pass

    # 3. Changes since last chat (from unified context snapshot)
    try:
        from app.services.unified_context import read_snapshot, read_changes
        snapshot = await read_snapshot(user_id)
        changes = await read_changes(user_id)

        if snapshot.hours_since_last_chat:
            parts.append(f"Hours since David's last chat: {snapshot.hours_since_last_chat:.1f}")
        if changes:
            parts.append(f"Changes since last chat ({len(changes)}):\n  " +
                         "\n  ".join(changes[-5:]))
    except Exception:
        pass

    # 4. Notification count
    try:
        from app.services.unified_context import read_snapshot
        snapshot = await read_snapshot(user_id)
        parts.append(f"Notifications sent today: {snapshot.notifications_sent_today}")
    except Exception:
        pass

    brief = "\n".join(parts)
    # Rough token cap (4 chars ≈ 1 token)
    if len(brief) > max_tokens * 4:
        brief = brief[:max_tokens * 4] + "..."

    return brief
