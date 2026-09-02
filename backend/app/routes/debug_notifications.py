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
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_USER_ID = get_owner_id()


@router.get("/debug/cognition-cost")
async def cognition_cost(
    days: int = 7,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """What Sara's thinking costs, per job, per day.

    Ground-truth plan, Phase 8 §5. Background model calls used to log a line and
    nothing else, so ~140 deliberations a day — plus appraisal, judge, compose,
    review, interpretation and the two nightly fold-forward documents — were
    invisible while chat's per-call token count was measurable. Every background
    call now records its job name as `operation_type`; this reads it back.

    The target this exists to check: 30–40 deliberations a day, not 140.
    """
    rows = db.execute(text("""
        SELECT operation_type,
               COUNT(*)                             AS calls,
               SUM(prompt_tokens)                   AS prompt_tokens,
               SUM(completion_tokens)               AS completion_tokens,
               SUM(total_tokens)                    AS total_tokens,
               ROUND(AVG(prompt_tokens))            AS avg_prompt_tokens,
               ROUND(COUNT(*)::numeric / :days, 1)  AS calls_per_day
          FROM token_usage
         WHERE created_at > NOW() - (:days || ' days')::interval
         GROUP BY operation_type
         ORDER BY SUM(total_tokens) DESC
    """), {"days": days}).mappings().all()

    jobs = [dict(r) for r in rows]
    return {
        "period_days": days,
        "jobs": jobs,
        "total_tokens": sum(int(j["total_tokens"] or 0) for j in jobs),
        "total_calls": sum(int(j["calls"] or 0) for j in jobs),
        "deliberations_per_day": next(
            (float(j["calls_per_day"]) for j in jobs if j["operation_type"] == "deliberation"),
            0.0,
        ),
        "deliberation_target_per_day": "30-40",
    }


@router.get("/debug/voice-register")
async def voice_register(
    days: int = 7,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Style-contract linter over the last N days of sent notifications
    (ONE_MIND Phase 3 acceptance: "one register"). Reports a register_score
    (fraction of items that read as Sara's one voice) and the specific leaks —
    shouts, template tells, monologue scaffolding, robotic status lines."""
    from app.services.voice_linter import lint_rows

    rows = db.execute(text("""
        SELECT title, message, category, source
        FROM notification_log
        WHERE sent = true
          AND sent_at > NOW() - (:days || ' days')::interval
        ORDER BY sent_at DESC
        LIMIT 2000
    """), {"days": days}).mappings().all()

    report = lint_rows([dict(r) for r in rows])
    report["period_days"] = days
    return report


@router.get("/debug/notification-funnel")
async def notification_funnel(
    hours: int = 24,
    days: int = 7,
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
        "period_days": days,
        "since": since_iso,
        "observations": {},
        "deliberations": {},
        "notifications": {},
        "home_actions": {},
        "attention_queue": {},
        "daily_breakdown": {},
        "recent_deliberations": [],
        "recent_notifications": [],
        "ban_summary": {},
    }

    # 1. Observations from Redis
    try:
        from app.core.redis import get_redis
        r = await get_redis()
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
            FROM outbox_item
            WHERE user_id = :user_id
              AND created_at >= :since
            GROUP BY status
        """), {"user_id": user_id, "since": since_iso}).fetchall()

        funnel["attention_queue"] = {
            row.status: row.count for row in attn_stats
        }
    except Exception as e:
        funnel["attention_queue"] = {"error": str(e)}

    # 5. Proposal rate over trailing 7 days (SARA_UNLEASHED Phase C.5) — this
    # metric alone would have caught R5 (0 proposals across 36h despite a
    # 31-email backlog) automatically instead of requiring a manual DB audit.
    try:
        since_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        rate_row = db.execute(text("""
            SELECT
                COUNT(*) AS runs,
                COUNT(*) FILTER (
                    WHERE COALESCE((actions_taken->>'notifications_sent')::int, 0) > 0
                       OR COALESCE((actions_taken->>'notifications_blocked')::int, 0) > 0
                       OR COALESCE((actions_taken->>'tasks_dispatched')::int, 0) > 0
                       OR COALESCE((actions_taken->>'tasks_proposed')::int, 0) > 0
                ) AS runs_with_proposal
            FROM agent_run_log
            WHERE source = 'deliberation' AND run_at >= :since
        """), {"since": since_7d}).fetchone()
        runs = rate_row.runs or 0
        with_proposal = rate_row.runs_with_proposal or 0
        funnel["proposal_rate_7d"] = {
            "runs": runs,
            "runs_with_a_proposal": with_proposal,
            "rate": round(with_proposal / runs, 3) if runs else None,
        }
    except Exception as e:
        funnel["proposal_rate_7d"] = {"error": str(e)}

    # 5b. Daily created -> suppressed(by reason) -> inboxed-only -> pushed
    # breakdown (NOTIFICATION_DELIVERY_FIX_PLAN_2026_08_17 Phase 5). Two
    # populations, both keyed by ET day:
    #   - attention-queue-routed items (outbox_item rows), LEFT JOINed to
    #     their notification_log outcome (if any) via outbox_item_id — this
    #     gives created/pushed/inboxed_only/no_push_attempt per day. Before
    #     Phase 5, budget/buzz_declined outcomes wrote nothing at all, so
    #     "inboxed-only" was invisible; no_push_attempt should trend to ~0
    #     now and is a canary if some path still skips the log.
    #   - pre-inbox suppressions (banned_topic, dedup, held_asleep,
    #     attention_cooldown, dedupe_key_surfaced, push_failed) — these
    #     never got an outbox_item at all, so they're read straight off
    #     notification_log rows with no outbox_item_id, grouped by reason.
    try:
        since_days = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()

        outcome_rows = db.execute(text("""
            SELECT
                (oi.created_at AT TIME ZONE 'America/New_York')::date AS day,
                COUNT(DISTINCT oi.id) AS created,
                COUNT(DISTINCT oi.id) FILTER (WHERE nl.sent = TRUE) AS pushed,
                COUNT(DISTINCT oi.id) FILTER (WHERE nl.sent = FALSE AND nl.id IS NOT NULL) AS inboxed_only,
                COUNT(DISTINCT oi.id) FILTER (WHERE nl.id IS NULL) AS no_push_attempt
            FROM outbox_item oi
            LEFT JOIN notification_log nl ON nl.outbox_item_id = oi.id
            WHERE oi.user_id = :user_id AND oi.created_at >= :since
            GROUP BY 1
            ORDER BY 1 DESC
        """), {"user_id": user_id, "since": since_days}).fetchall()

        suppressed_rows = db.execute(text("""
            SELECT
                (sent_at AT TIME ZONE 'America/New_York')::date AS day,
                COALESCE(suppress_reason, 'unknown') AS reason,
                COUNT(*) AS count
            FROM notification_log
            WHERE user_id = :user_id AND sent_at >= :since
              AND sent = FALSE AND outbox_item_id IS NULL
            GROUP BY 1, 2
            ORDER BY 1 DESC, 3 DESC
        """), {"user_id": user_id, "since": since_days}).fetchall()

        by_day = {}
        for row in outcome_rows:
            day_key = row.day.isoformat()
            by_day.setdefault(day_key, {
                "created": 0, "pushed": 0, "inboxed_only": 0,
                "no_push_attempt": 0, "suppressed": {},
            })
            by_day[day_key]["created"] = row.created
            by_day[day_key]["pushed"] = row.pushed
            by_day[day_key]["inboxed_only"] = row.inboxed_only
            by_day[day_key]["no_push_attempt"] = row.no_push_attempt

        for row in suppressed_rows:
            day_key = row.day.isoformat()
            by_day.setdefault(day_key, {
                "created": 0, "pushed": 0, "inboxed_only": 0,
                "no_push_attempt": 0, "suppressed": {},
            })
            by_day[day_key]["suppressed"][row.reason] = row.count

        for day_key, d in by_day.items():
            d["suppressed_total"] = sum(d["suppressed"].values())

        funnel["daily_breakdown"] = dict(sorted(by_day.items(), reverse=True))
    except Exception as e:
        funnel["daily_breakdown"] = {"error": str(e)}

    # 6. Build the funnel summary
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
