"""
Action tracing for autonomous actions (Phase 0 — Cortana Evolution).

Every autonomous action (heartbeat tool call, automation primitive execution)
gets a trace record in autonomy_action_trace. Uses idempotency keys to handle
retries safely.

Usage:
    tracer = ActionTracer()
    await tracer.trace(
        db=db, run_uuid=run_uuid, user_id=user_id,
        source="unified_agent", action_name="home_light_control",
        action_args={"entity_id": "light.office", "action": "turn_on"},
        risk_tier=1, decision="allow", result={"success": True},
        success=True, step_index=0, duration_ms=120,
    )
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Risk tier classification for known tools
RISK_TIERS: Dict[str, int] = {
    # Tier 0: Read-only, always allow
    "home_get_devices": 0,
    "home_lock_status": 0,
    "home_climate_status": 0,
    "check_emails": 0,
    "check_reminders": 0,
    "check_calendar": 0,
    "get_weather": 0,
    "check_habits": 0,
    "check_notes": 0,
    "check_recent_activity": 0,
    "check_background_tasks": 0,
    "check_learning_reviews": 0,
    "query_personal_knowledge": 0,
    "save_observation": 0,
    # Tier 1: Reversible
    "home_light_control": 1,
    "home_switch_control": 1,
    "send_notification": 1,
    "flag_conversation": 1,
    "followup_thread": 1,
    # Tier 2: Irreversible (reserved for future tools)
    # "home_lock_control": 2,
    # "calendar_create": 2,
    # "send_message": 2,
}

# Default tier for unknown tools (safety: treat as irreversible)
DEFAULT_RISK_TIER = 2


def get_risk_tier(action_name: str) -> int:
    """Get risk tier for a tool name. Unknown tools default to Tier 2."""
    tier = RISK_TIERS.get(action_name)
    if tier is not None:
        return tier
    # Try stripping common LLM hallucination prefixes
    stripped = action_name
    for prefix in ("tool.", "tool_", "repo_browser.run_code.", "repo_browser."):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
    if stripped != action_name:
        tier = RISK_TIERS.get(stripped)
        if tier is not None:
            return tier
    return DEFAULT_RISK_TIER


class ActionTracer:
    """Records traces for every autonomous action."""

    async def trace(
        self,
        db: AsyncSession,
        run_uuid: Optional[UUID],
        user_id: str,
        source: str,
        action_name: str,
        action_args: Optional[Dict[str, Any]] = None,
        risk_tier: Optional[int] = None,
        decision: str = "allow",
        decision_reason: Optional[str] = None,
        simulation: Optional[Dict[str, Any]] = None,
        result: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        step_index: int = 0,
        duration_ms: Optional[int] = None,
    ) -> Optional[str]:
        """
        Write an action trace record.

        Uses idempotency_key = "{run_uuid}:{action_name}:{step_index}"
        with ON CONFLICT DO NOTHING for retry safety.

        Returns trace ID on success, None on conflict or error.
        """
        if risk_tier is None:
            risk_tier = get_risk_tier(action_name)

        idempotency_key = None
        if run_uuid:
            idempotency_key = f"{run_uuid}:{action_name}:{step_index}"

        try:
            row = await db.execute(text("""
                INSERT INTO autonomy_action_trace
                (run_uuid, user_id, source, action_name, action_args, risk_tier,
                 decision, decision_reason, simulation, result, success,
                 error_message, step_index, idempotency_key, duration_ms)
                VALUES
                (:run_uuid, :user_id, :source, :action_name,
                 CAST(:action_args AS jsonb), :risk_tier,
                 :decision, :decision_reason, CAST(:simulation AS jsonb),
                 CAST(:result AS jsonb), :success,
                 :error_message, :step_index, :idempotency_key, :duration_ms)
                ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
                DO NOTHING
                RETURNING id::text
            """), {
                "run_uuid": str(run_uuid) if run_uuid else None,
                "user_id": user_id,
                "source": source,
                "action_name": action_name,
                "action_args": json.dumps(action_args, default=str) if action_args else None,
                "risk_tier": risk_tier,
                "decision": decision,
                "decision_reason": decision_reason,
                "simulation": json.dumps(simulation, default=str) if simulation else None,
                "result": json.dumps(result, default=str) if result else None,
                "success": success,
                "error_message": error_message,
                "step_index": step_index,
                "idempotency_key": idempotency_key,
                "duration_ms": duration_ms,
            })
            result_row = row.fetchone()
            return result_row[0] if result_row else None
        except Exception as e:
            logger.error(f"Failed to write action trace: {e}")
            try:
                await db.rollback()
            except Exception:
                pass
            return None

    async def backfill_run_id(self, db: AsyncSession, run_uuid: UUID, run_id: int) -> int:
        """
        Backfill run_id on all traces for a given run_uuid.
        Called in RECORD phase after agent_run_log INSERT returns the id.
        Returns count of updated rows.
        """
        try:
            result = await db.execute(text("""
                UPDATE autonomy_action_trace
                SET run_id = :run_id
                WHERE run_uuid = :run_uuid AND run_id IS NULL
            """), {"run_id": run_id, "run_uuid": str(run_uuid)})
            return result.rowcount
        except Exception as e:
            logger.error(f"Failed to backfill run_id: {e}")
            return 0

    async def get_recent_traces(
        self,
        db: AsyncSession,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        source: Optional[str] = None,
        action_name: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent action traces with optional filters."""
        conditions = ["user_id = :user_id"]
        params: Dict[str, Any] = {"user_id": user_id, "limit": limit, "offset": offset}

        if source:
            conditions.append("source = :source")
            params["source"] = source
        if action_name:
            conditions.append("action_name = :action_name")
            params["action_name"] = action_name
        if since:
            conditions.append("created_at >= :since")
            params["since"] = since

        where = " AND ".join(conditions)

        try:
            result = await db.execute(text(f"""
                SELECT id::text, run_uuid::text, run_id, source, action_name,
                       action_args, risk_tier, decision, decision_reason,
                       simulation, result, success, error_message,
                       step_index, duration_ms, created_at
                FROM autonomy_action_trace
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """), params)
            rows = result.fetchall()
            return [
                {
                    "id": r[0], "run_uuid": r[1], "run_id": r[2],
                    "source": r[3], "action_name": r[4], "action_args": r[5],
                    "risk_tier": r[6], "decision": r[7], "decision_reason": r[8],
                    "simulation": r[9], "result": r[10], "success": r[11],
                    "error_message": r[12], "step_index": r[13],
                    "duration_ms": r[14], "created_at": r[15].isoformat() if r[15] else None,
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get recent traces: {e}")
            return []

    async def get_trace_stats(
        self,
        db: AsyncSession,
        user_id: str,
        hours: int = 24,
    ) -> Dict[str, Any]:
        """Get aggregate stats for action traces over a time window."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        try:
            result = await db.execute(text("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE success = TRUE) as succeeded,
                    COUNT(*) FILTER (WHERE success = FALSE) as failed,
                    COUNT(DISTINCT run_uuid) as runs,
                    COUNT(DISTINCT action_name) as unique_actions,
                    AVG(duration_ms) FILTER (WHERE duration_ms IS NOT NULL) as avg_duration_ms
                FROM autonomy_action_trace
                WHERE user_id = :user_id AND created_at >= :since
            """), {"user_id": user_id, "since": since})
            row = result.fetchone()

            # Per-action breakdown
            breakdown_result = await db.execute(text("""
                SELECT
                    action_name,
                    source,
                    risk_tier,
                    COUNT(*) as count,
                    COUNT(*) FILTER (WHERE success = TRUE) as succeeded,
                    COUNT(*) FILTER (WHERE success = FALSE) as failed
                FROM autonomy_action_trace
                WHERE user_id = :user_id AND created_at >= :since
                GROUP BY action_name, source, risk_tier
                ORDER BY count DESC
            """), {"user_id": user_id, "since": since})
            breakdown = [
                {
                    "action_name": r[0], "source": r[1], "risk_tier": r[2],
                    "count": r[3], "succeeded": r[4], "failed": r[5],
                }
                for r in breakdown_result.fetchall()
            ]

            return {
                "hours": hours,
                "total": row[0] if row else 0,
                "succeeded": row[1] if row else 0,
                "failed": row[2] if row else 0,
                "runs": row[3] if row else 0,
                "unique_actions": row[4] if row else 0,
                "avg_duration_ms": round(row[5], 1) if row and row[5] else None,
                "breakdown": breakdown,
            }
        except Exception as e:
            logger.error(f"Failed to get trace stats: {e}")
            return {"hours": hours, "total": 0, "error": str(e)}
