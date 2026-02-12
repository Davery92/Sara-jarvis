"""
Sara Observations Endpoint

Returns Sara's ambient observations — things she noticed during
heartbeat cycles, periodic subconscious processing, and journal entries.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import get_db
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sara-observations"])


@router.get("/api/sara/observations")
async def get_observations(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    since: Optional[str] = Query(None, description="ISO datetime to fetch observations since"),
    limit: int = Query(10, ge=1, le=50)
):
    """
    Get Sara's recent ambient observations.
    Merges journal entries (heartbeat/periodic) with agent_run_log observations.
    """
    user_id = str(current_user.id)

    # Parse since parameter or default to 24 hours ago
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
        except ValueError:
            since_dt = datetime.now(timezone.utc) - timedelta(hours=24)
    else:
        since_dt = datetime.now(timezone.utc) - timedelta(hours=24)

    observations = []

    try:
        # Get journal observations (heartbeat + periodic entries)
        journal_entries = db.execute(text("""
            SELECT id, content, emotional_state, entry_type, label, created_at
            FROM sara_journal
            WHERE user_id = :uid
            AND entry_type IN ('heartbeat', 'periodic', 'unified')
            AND created_at >= :since
            ORDER BY created_at DESC
            LIMIT :lim
        """), {"uid": user_id, "since": since_dt, "lim": limit}).fetchall()

        for entry in journal_entries:
            content = entry.content or ""
            # Extract a summary from the content (first meaningful line)
            summary = content.split("\n")[0][:200].strip()
            observations.append({
                "id": str(entry.id),
                "timestamp": entry.created_at.isoformat() if entry.created_at else None,
                "type": entry.entry_type,
                "summary": summary,
                "emotional_state": entry.emotional_state,
                "label": entry.label,
                "source": "journal"
            })

        # Get agent run observations
        agent_runs = db.execute(text("""
            SELECT id, context_summary, actions_taken, created_at
            FROM agent_run_log
            WHERE user_id = :uid
            AND created_at >= :since
            AND context_summary IS NOT NULL
            ORDER BY created_at DESC
            LIMIT :lim
        """), {"uid": user_id, "since": since_dt, "lim": limit}).fetchall()

        for run in agent_runs:
            observations.append({
                "id": str(run.id),
                "timestamp": run.created_at.isoformat() if run.created_at else None,
                "type": "heartbeat_action",
                "summary": (run.context_summary or "")[:200],
                "actions": run.actions_taken,
                "source": "agent_run"
            })

        # Sort by timestamp descending
        observations.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        # Limit to requested count
        observations = observations[:limit]

    except Exception as e:
        logger.error(f"Sara observations endpoint error: {e}")
        return {"observations": [], "error": str(e)}

    return {"observations": observations, "total": len(observations)}
