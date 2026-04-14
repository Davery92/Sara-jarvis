"""Debug endpoint for notification pipeline observability.

Shows the full funnel: events → observations → deliberations → proposals → delivery.
"""

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


@router.get("/debug/notification-funnel")
async def notification_funnel(
    hours: int = 24,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Notification pipeline funnel for the last N hours.

    Shows: events received → observations logged → deliberations triggered →
    notifications proposed → notifications delivered.
    """
    user_id = current_user.id
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    since_iso = since.isoformat()

    funnel = {
        "period_hours": hours,
        "since": since_iso,
        "observations": {},
        "deliberations": {},
        "notifications": {},
        "home_actions": {},
        "attention_queue": {},
        "recent_deliberations": [],
        "recent_notifications": [],
        "ban_summary": {},
    }

    # 1. Observations from Redis
    try:
        import redis.asyncio as aioredis
        import os
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        r = await aioredis.from_url(redis_url, decode_responses=True)
        try:
            obs_key = f"sara:observations:{user_id}"
            detail_key = f"sara:observation_details:{user_id}"
            pending_count = await r.zcard(obs_key)
            accumulated_salience = 0.0
            top_obs = await r.zrevrange(obs_key, 0, 9, withscores=True)
            if top_obs:
                accumulated_salience = sum(s for _, s in top_obs)

            # Count observations by category from details
            all_details = await r.hgetall(detail_key)
            category_counts = {}
            import json
            for _, detail_json in all_details.items():
                try:
                    d = json.loads(detail_json)
                    cat = d.get("category", "unknown")
                    category_counts[cat] = category_counts.get(cat, 0) + 1
                except Exception:
                    pass

            funnel["observations"] = {
                "pending_count": pending_count,
                "accumulated_salience": round(accumulated_salience, 2),
                "by_category": category_counts,
                "top_pending": [
                    {"id": obs_id, "salience": round(score, 2)}
                    for obs_id, score in (top_obs or [])[:5]
                ],
            }
        finally:
            await r.aclose()
    except Exception as e:
        funnel["observations"] = {"error": str(e)}

    # 2. Deliberations from agent_run_log
    try:
        delib_rows = db.execute(text("""
            SELECT id, run_at, context_summary AS thought, run_duration_ms AS duration_ms,
                   actions_taken->>'notifications_sent' as notifs_sent,
                   actions_taken->>'notifications_blocked' as notifs_blocked,
                   actions_taken->>'home_actions_executed' as actions_exec,
                   actions_taken->>'home_actions_blocked' as actions_blocked,
                   actions_taken->>'tasks_dispatched' as tasks_dispatched,
                   actions_taken->>'tasks_proposed' as tasks_proposed,
                   actions_taken->>'observations_consumed' as obs_consumed,
                   actions_taken->>'journal_written' as journal_written,
                   watching_for, handoff_note AS handoff
            FROM agent_run_log
            WHERE source = 'deliberation'
              AND run_at >= :since
            ORDER BY run_at DESC
            LIMIT 20
        """), {"since": since_iso}).fetchall()

        total_delibs = len(delib_rows)
        total_notifs_proposed = 0
        total_notifs_sent = 0
        total_notifs_blocked = 0
        total_actions_exec = 0
        total_obs_consumed = 0

        recent = []
        for row in delib_rows:
            sent = _safe_int(row.notifs_sent)
            blocked = _safe_int(row.notifs_blocked)
            total_notifs_sent += sent
            total_notifs_blocked += blocked
            total_notifs_proposed += sent + blocked
            total_actions_exec += _safe_int(row.actions_exec)
            total_obs_consumed += _safe_int(row.obs_consumed)

            recent.append({
                "id": row.id,
                "at": row.run_at.isoformat() if row.run_at else None,
                "thought": (row.thought or "")[:120],
                "duration_ms": row.duration_ms,
                "notifs_sent": sent,
                "notifs_blocked": blocked,
                "actions_exec": _safe_int(row.actions_exec),
                "tasks": _safe_int(row.tasks_dispatched) + _safe_int(row.tasks_proposed),
                "obs_consumed": _safe_int(row.obs_consumed),
                "watching_for": (row.watching_for or "")[:80],
            })

        funnel["deliberations"] = {
            "count": total_delibs,
            "total_notifications_proposed": total_notifs_proposed,
            "total_notifications_sent": total_notifs_sent,
            "total_notifications_blocked": total_notifs_blocked,
            "total_home_actions_executed": total_actions_exec,
            "total_observations_consumed": total_obs_consumed,
        }
        funnel["recent_deliberations"] = recent[:10]

    except Exception as e:
        funnel["deliberations"] = {"error": str(e)}

    # 3. Notification delivery from notification_log
    try:
        notif_summary = db.execute(text("""
            SELECT
                category,
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE sent = true AND dedup_blocked = false) as delivered,
                COUNT(*) FILTER (WHERE dedup_blocked = true) as dedup_blocked,
                COUNT(*) FILTER (WHERE sent = false AND dedup_blocked = false) as other_blocked
            FROM notification_log
            WHERE user_id = :user_id
              AND sent_at >= :since
            GROUP BY category
            ORDER BY total DESC
        """), {"user_id": user_id, "since": since_iso}).fetchall()

        total_attempted = 0
        total_delivered = 0
        total_deduped = 0
        by_category = {}
        for row in notif_summary:
            total_attempted += row.total
            total_delivered += row.delivered
            total_deduped += row.dedup_blocked
            by_category[row.category or "unknown"] = {
                "total": row.total,
                "delivered": row.delivered,
                "dedup_blocked": row.dedup_blocked,
                "other_blocked": row.other_blocked,
            }

        funnel["notifications"] = {
            "total_attempted": total_attempted,
            "total_delivered": total_delivered,
            "total_dedup_blocked": total_deduped,
            "total_other_blocked": total_attempted - total_delivered - total_deduped,
            "by_category": by_category,
        }

        # Recent notifications
        recent_notifs = db.execute(text("""
            SELECT id, category, title, priority, sent, dedup_blocked, sent_at, source
            FROM notification_log
            WHERE user_id = :user_id
              AND sent_at >= :since
            ORDER BY sent_at DESC
            LIMIT 15
        """), {"user_id": user_id, "since": since_iso}).fetchall()

        funnel["recent_notifications"] = [
            {
                "id": r.id,
                "category": r.category,
                "title": (r.title or "")[:80],
                "priority": r.priority,
                "sent": r.sent,
                "dedup_blocked": r.dedup_blocked,
                "at": r.sent_at.isoformat() if r.sent_at else None,
                "source": r.source,
            }
            for r in recent_notifs
        ]

    except Exception as e:
        funnel["notifications"] = {"error": str(e)}

    # 4. Attention queue stats (if enabled)
    try:
        attn_stats = db.execute(text("""
            SELECT
                status,
                COUNT(*) as count
            FROM attention_item
            WHERE user_id = :user_id
              AND created_at >= :since
            GROUP BY status
        """), {"user_id": user_id, "since": since_iso}).fetchall()

        funnel["attention_queue"] = {
            row.status: row.count for row in attn_stats
        }
    except Exception as e:
        funnel["attention_queue"] = {"error": str(e)}

    # 5. Build the funnel summary
    obs_count = funnel.get("observations", {}).get("pending_count", 0)
    delib_count = funnel.get("deliberations", {}).get("count", 0)
    proposed = funnel.get("deliberations", {}).get("total_notifications_proposed", 0)
    delivered = funnel.get("notifications", {}).get("total_delivered", 0)

    funnel["funnel_summary"] = {
        "observations_pending": obs_count,
        "deliberations_triggered": delib_count,
        "notifications_proposed": proposed,
        "notifications_delivered": delivered,
        "drop_rate": f"{(1 - delivered / max(proposed, 1)) * 100:.0f}%" if proposed > 0 else "N/A",
    }

    return funnel


def _safe_int(val) -> int:
    """Safely convert a value to int, defaulting to 0."""
    if val is None:
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0
