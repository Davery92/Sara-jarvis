"""
Autonomy action trace routes — observability for autonomous actions.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.services.autonomy.action_tracer import ActionTracer

router = APIRouter(prefix="/autonomy", tags=["autonomy"])

_tracer = ActionTracer()


@router.get("/traces")
async def get_traces(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    source: Optional[str] = Query(None),
    action_name: Optional[str] = Query(None),
    hours: int = Query(24, ge=1, le=168),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get recent action traces with optional filters."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    traces = await _tracer.get_recent_traces(
        db=db,
        user_id=str(current_user.id),
        limit=limit,
        offset=offset,
        source=source,
        action_name=action_name,
        since=since,
    )
    return {"traces": traces, "count": len(traces)}


@router.get("/traces/stats")
async def get_trace_stats(
    hours: int = Query(24, ge=1, le=168),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregate stats for action traces."""
    stats = await _tracer.get_trace_stats(
        db=db,
        user_id=str(current_user.id),
        hours=hours,
    )
    return stats


@router.get("/rollout/summary")
async def get_rollout_summary(
    hours: int = Query(24, ge=1, le=168),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Rollout-focused observability snapshot for autonomy feature flags.
    Returns:
    - current flag state
    - trace stats
    - decision/risk breakdown
    - structured-plan fallback indicators from agent_run_log
    """
    user_id = str(current_user.id)
    trace_stats = await _tracer.get_trace_stats(db=db, user_id=user_id, hours=hours)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    decisions = []
    risk_tiers = []
    run_log = {
        "total_runs": 0,
        "fallback_runs": 0,
        "fallback_rate": 0.0,
    }
    notification_stats = {
        "sent_total": 0,
        "dedup_blocked_total": 0,
        "attention_linked_sent": 0,
        "direct_sent": 0,
    }
    attention_queue = {
        "new": 0,
        "in_progress": 0,
        "done": 0,
    }
    mission_stats = {
        "total": 0,
        "by_state": [],
    }
    thresholds = {
        "min_runs_for_eval": settings.autonomy_rollout_min_runs_for_eval,
        "max_fallback_rate": settings.autonomy_rollout_max_fallback_rate,
        "max_action_failure_rate": settings.autonomy_rollout_max_action_failure_rate,
        "max_dedup_block_rate": settings.autonomy_rollout_max_dedup_block_rate,
        "max_attention_backlog_ratio": settings.autonomy_rollout_max_attention_backlog_ratio,
        "max_mission_failure_rate": settings.autonomy_rollout_max_mission_failure_rate,
        "max_mission_nonterminal_ratio": settings.autonomy_rollout_max_mission_nonterminal_ratio,
    }

    try:
        decision_rows = await db.execute(text("""
            SELECT decision, COUNT(*)::int
            FROM autonomy_action_trace
            WHERE user_id = :user_id AND created_at >= :since
            GROUP BY decision
            ORDER BY COUNT(*) DESC
        """), {"user_id": user_id, "since": since})
        decisions = [{"decision": row[0], "count": row[1]} for row in decision_rows.fetchall()]

        risk_rows = await db.execute(text("""
            SELECT risk_tier, COUNT(*)::int
            FROM autonomy_action_trace
            WHERE user_id = :user_id AND created_at >= :since
            GROUP BY risk_tier
            ORDER BY risk_tier
        """), {"user_id": user_id, "since": since})
        risk_tiers = [{"risk_tier": row[0], "count": row[1]} for row in risk_rows.fetchall()]
    except Exception:
        # Table might not exist in early migrations; keep graceful fallback payload.
        pass

    async def _column_exists(table_name: str, column_name: str) -> bool:
        exists_row = await db.execute(text("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                  AND column_name = :column_name
            ) AS exists_flag
        """), {"table_name": table_name, "column_name": column_name})
        return bool(exists_row.scalar())

    try:
        total_row = await db.execute(text("""
            SELECT COUNT(*)::int
            FROM agent_run_log
            WHERE user_id = :user_id AND created_at >= :since
        """), {"user_id": user_id, "since": since})
        total_runs = int(total_row.scalar() or 0)
        run_log["total_runs"] = total_runs

        fallback_runs = 0
        if total_runs > 0:
            if await _column_exists("agent_run_log", "plan_summary"):
                fallback_row = await db.execute(text("""
                    SELECT COUNT(*)::int
                    FROM agent_run_log
                    WHERE user_id = :user_id
                      AND created_at >= :since
                      AND COALESCE((plan_summary->>'fallback')::boolean, FALSE) = TRUE
                """), {"user_id": user_id, "since": since})
                fallback_runs = int(fallback_row.scalar() or 0)
            elif await _column_exists("agent_run_log", "run_metadata"):
                fallback_row = await db.execute(text("""
                    SELECT COUNT(*)::int
                    FROM agent_run_log
                    WHERE user_id = :user_id
                      AND created_at >= :since
                      AND (
                        LOWER(COALESCE(run_metadata->>'fallback', '')) IN ('true', 't', '1', 'yes')
                        OR LOWER(COALESCE(run_metadata->>'used_fallback', '')) IN ('true', 't', '1', 'yes')
                        OR LOWER(COALESCE(run_metadata->'plan_summary'->>'fallback', '')) IN ('true', 't', '1', 'yes')
                      )
                """), {"user_id": user_id, "since": since})
                fallback_runs = int(fallback_row.scalar() or 0)

        run_log["fallback_runs"] = fallback_runs
        run_log["fallback_rate"] = (fallback_runs / total_runs) if total_runs else 0.0
    except Exception:
        pass

    try:
        notif_row = await db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE sent = TRUE)::int AS sent_total,
                COUNT(*) FILTER (WHERE dedup_blocked = TRUE)::int AS dedup_blocked_total,
                COUNT(*) FILTER (WHERE sent = TRUE AND outbox_item_id IS NOT NULL)::int AS attention_linked_sent,
                COUNT(*) FILTER (WHERE sent = TRUE AND outbox_item_id IS NULL)::int AS direct_sent
            FROM notification_log
            WHERE user_id = :user_id
              AND sent_at >= :since
        """), {"user_id": user_id, "since": since})
        nr = notif_row.fetchone()
        if nr:
            notification_stats["sent_total"] = nr[0] or 0
            notification_stats["dedup_blocked_total"] = nr[1] or 0
            notification_stats["attention_linked_sent"] = nr[2] or 0
            notification_stats["direct_sent"] = nr[3] or 0
    except Exception:
        pass

    try:
        attention_rows = await db.execute(text("""
            SELECT status, COUNT(*)::int
            FROM autonomy_attention_item
            WHERE user_id = :user_id
              AND created_at >= :since
            GROUP BY status
        """), {"user_id": user_id, "since": since})
        for status_value, count in attention_rows.fetchall():
            status_key = str(status_value or "").lower()
            if status_key in attention_queue:
                attention_queue[status_key] = count or 0
    except Exception:
        pass

    try:
        mission_rows = await db.execute(text("""
            SELECT state, COUNT(*)::int
            FROM autonomy_mission
            WHERE user_id = :user_id
              AND created_at >= :since
            GROUP BY state
            ORDER BY COUNT(*) DESC
        """), {"user_id": user_id, "since": since})
        state_rows = mission_rows.fetchall()
        mission_stats["by_state"] = [{"state": r[0], "count": r[1]} for r in state_rows]
        mission_stats["total"] = sum((r[1] or 0) for r in state_rows)
    except Exception:
        pass

    total_notif_attempts = (
        notification_stats["sent_total"] + notification_stats["dedup_blocked_total"]
    )
    total_attention_items = (
        attention_queue["new"] + attention_queue["in_progress"] + attention_queue["done"]
    )
    mission_state_counts = {
        str(row.get("state")): int(row.get("count") or 0)
        for row in mission_stats["by_state"]
    }
    mission_failed = mission_state_counts.get("failed", 0)
    mission_nonterminal = (
        mission_state_counts.get("pending", 0)
        + mission_state_counts.get("running", 0)
        + mission_state_counts.get("awaiting_confirm", 0)
    )

    rates = {
        "fallback_rate": run_log["fallback_rate"],
        "action_failure_rate": (
            (trace_stats.get("failed", 0) / trace_stats.get("total", 1))
            if trace_stats.get("total", 0) > 0 else 0.0
        ),
        "dedup_block_rate": (
            (notification_stats["dedup_blocked_total"] / total_notif_attempts)
            if total_notif_attempts > 0 else 0.0
        ),
        "attention_backlog_ratio": (
            (attention_queue["new"] / total_attention_items)
            if total_attention_items > 0 else 0.0
        ),
        "mission_failure_rate": (
            (mission_failed / mission_stats["total"])
            if mission_stats["total"] > 0 else 0.0
        ),
        "mission_nonterminal_ratio": (
            (mission_nonterminal / mission_stats["total"])
            if mission_stats["total"] > 0 else 0.0
        ),
    }

    def _evaluation(flag_enabled: bool, checks: list[tuple[str, bool, str]]):
        if not flag_enabled:
            return {
                "status": "flag_off",
                "healthy": None,
                "rollback_recommended": False,
                "reasons": ["flag_disabled"],
            }
        if run_log["total_runs"] < thresholds["min_runs_for_eval"]:
            return {
                "status": "insufficient_data",
                "healthy": None,
                "rollback_recommended": False,
                "reasons": [f"requires_at_least_{thresholds['min_runs_for_eval']}_runs"],
            }

        failing = [reason for _, ok, reason in checks if not ok]
        return {
            "status": "healthy" if not failing else "unhealthy",
            "healthy": len(failing) == 0,
            "rollback_recommended": len(failing) > 0,
            "reasons": failing,
        }

    evaluations = {
        "autonomy_attention_enabled": _evaluation(
            settings.autonomy_attention_enabled,
            [
                (
                    "attention_backlog_ratio",
                    rates["attention_backlog_ratio"] <= thresholds["max_attention_backlog_ratio"],
                    (
                        f"attention_backlog_ratio {rates['attention_backlog_ratio']:.3f} > "
                        f"{thresholds['max_attention_backlog_ratio']:.3f}"
                    ),
                ),
                (
                    "dedup_block_rate",
                    rates["dedup_block_rate"] <= thresholds["max_dedup_block_rate"],
                    (
                        f"dedup_block_rate {rates['dedup_block_rate']:.3f} > "
                        f"{thresholds['max_dedup_block_rate']:.3f}"
                    ),
                ),
            ],
        ),
        "autonomy_structured_plan": _evaluation(
            settings.autonomy_structured_plan,
            [
                (
                    "fallback_rate",
                    rates["fallback_rate"] <= thresholds["max_fallback_rate"],
                    (
                        f"fallback_rate {rates['fallback_rate']:.3f} > "
                        f"{thresholds['max_fallback_rate']:.3f}"
                    ),
                ),
            ],
        ),
        "autonomy_policy_engine": _evaluation(
            settings.autonomy_policy_engine,
            [
                (
                    "action_failure_rate",
                    rates["action_failure_rate"] <= thresholds["max_action_failure_rate"],
                    (
                        f"action_failure_rate {rates['action_failure_rate']:.3f} > "
                        f"{thresholds['max_action_failure_rate']:.3f}"
                    ),
                ),
            ],
        ),
        "autonomy_missions_enabled": _evaluation(
            settings.autonomy_missions_enabled,
            [
                (
                    "mission_failure_rate",
                    rates["mission_failure_rate"] <= thresholds["max_mission_failure_rate"],
                    (
                        f"mission_failure_rate {rates['mission_failure_rate']:.3f} > "
                        f"{thresholds['max_mission_failure_rate']:.3f}"
                    ),
                ),
                (
                    "mission_nonterminal_ratio",
                    rates["mission_nonterminal_ratio"] <= thresholds["max_mission_nonterminal_ratio"],
                    (
                        f"mission_nonterminal_ratio {rates['mission_nonterminal_ratio']:.3f} > "
                        f"{thresholds['max_mission_nonterminal_ratio']:.3f}"
                    ),
                ),
            ],
        ),
        "autonomy_policy_candidates_enabled": _evaluation(
            settings.autonomy_policy_candidates_enabled,
            [
                (
                    "action_failure_rate",
                    rates["action_failure_rate"] <= thresholds["max_action_failure_rate"],
                    (
                        f"action_failure_rate {rates['action_failure_rate']:.3f} > "
                        f"{thresholds['max_action_failure_rate']:.3f}"
                    ),
                ),
            ],
        ),
    }

    rollback_recommendations = [
        {"flag": flag_name, "reasons": eval_result["reasons"]}
        for flag_name, eval_result in evaluations.items()
        if eval_result.get("rollback_recommended")
    ]

    return {
        "window_hours": hours,
        "flags": {
            "autonomy_traces_enabled": settings.autonomy_traces_enabled,
            "autonomy_structured_plan": settings.autonomy_structured_plan,
            "autonomy_policy_engine": settings.autonomy_policy_engine,
            "autonomy_attention_enabled": settings.autonomy_attention_enabled,
            "autonomy_missions_enabled": settings.autonomy_missions_enabled,
            "autonomy_policy_candidates_enabled": settings.autonomy_policy_candidates_enabled,
        },
        "trace_stats": trace_stats,
        "decision_breakdown": decisions,
        "risk_tier_breakdown": risk_tiers,
        "run_log": run_log,
        "notifications": notification_stats,
        "attention_queue": attention_queue,
        "missions": mission_stats,
        "thresholds": thresholds,
        "rates": rates,
        "evaluations": evaluations,
        "rollback_recommendations": rollback_recommendations,
    }


# ── Observation & Deliberation Observability ────────────────────


@router.get("/observations")
async def get_observations(
    min_salience: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user),
):
    """Get pending observations from the salience-scored observation log."""
    try:
        from app.services.observation_log import (
            get_pending_observations,
            get_accumulated_salience,
            get_observation_count,
        )
        user_id = str(current_user.id)
        observations = await get_pending_observations(user_id, min_salience=min_salience, limit=limit)
        accumulated = await get_accumulated_salience(user_id)
        count = await get_observation_count(user_id)
        return {
            "observations": [
                {
                    "id": obs.id,
                    "timestamp": obs.timestamp,
                    "source": obs.source,
                    "description": obs.description,
                    "salience": obs.salience,
                    "category": obs.category,
                }
                for obs in observations
            ],
            "accumulated_salience": accumulated,
            "pending_count": count,
        }
    except Exception as e:
        return {"observations": [], "accumulated_salience": 0.0, "pending_count": 0, "error": str(e)}


@router.get("/working-memory")
async def get_working_memory(
    current_user=Depends(get_current_user),
):
    """Read Sara's current working memory snapshot from Redis."""
    try:
        from app.services.working_memory import read_memory
        user_id = str(current_user.id)
        memory = await read_memory(user_id)
        return {
            "activity_state": memory.activity_state,
            "activity_confidence": memory.activity_confidence,
            "room": memory.room,
            "interruptibility": memory.interruptibility,
            "hours_since_last_chat": memory.hours_since_last_chat,
            "last_chat_at": memory.last_chat_at,
            "hours_since_last_meal": memory.hours_since_last_meal,
            "mood": memory.mood,
            "alertness": memory.alertness,
            "stress_load": memory.stress_load,
            "circadian_phase": memory.circadian_phase,
            "home_occupied": memory.home_occupied,
            "temperature_inside": memory.temperature_inside,
            "temperature_outside": memory.temperature_outside,
            "weather_condition": memory.weather_condition,
            "next_event_title": memory.next_event_title,
            "next_event_minutes_away": memory.next_event_minutes_away,
            "today_habit_status": memory.today_habit_status,
            "recent_notes_summary": memory.recent_notes_summary,
            "notifications_sent_today": memory.notifications_sent_today,
            "sara_focus": memory.sara_focus,
            "sara_emotional_tone": memory.sara_emotional_tone,
            "sara_curiosities": memory.sara_curiosities,
            "sara_last_deliberation_at": memory.sara_last_deliberation_at,
            "sara_deliberation_count_today": memory.sara_deliberation_count_today,
            "observation_count": memory.observation_count,
            "salience_high_water": memory.salience_high_water,
            "last_heartbeat_handoff": memory.last_heartbeat_handoff,
            "last_heartbeat_watching_for": memory.last_heartbeat_watching_for,
            "quiet_mode": memory.quiet_mode,
            "updated_at": memory.updated_at,
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/deliberation-history")
async def get_deliberation_history(
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get recent deliberation and consolidation runs from agent_run_log."""
    user_id = str(current_user.id)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        rows = await db.execute(text("""
            SELECT source, context_summary, handoff_note, watching_for,
                   actions_taken, run_duration_ms, run_at, created_at
            FROM agent_run_log
            WHERE user_id = :uid
              AND source IN ('deliberation', 'consolidation', 'unified_agent', 'morning_anticipation')
              AND created_at >= :since
            ORDER BY created_at DESC
            LIMIT :lim
        """), {"uid": user_id, "since": since, "lim": limit})
        entries = []
        for row in rows.fetchall():
            entries.append({
                "source": row.source,
                "thought": row.context_summary[:500] if row.context_summary else None,
                "handoff_note": row.handoff_note[:300] if row.handoff_note else None,
                "watching_for": row.watching_for[:200] if row.watching_for else None,
                "actions_taken": row.actions_taken,
                "duration_seconds": round(row.run_duration_ms / 1000, 1) if row.run_duration_ms else None,
                "run_at": row.run_at.isoformat() if row.run_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            })
        return {"entries": entries, "count": len(entries)}
    except Exception as e:
        return {"entries": [], "count": 0, "error": str(e)}
