"""Health baseline + anomaly tasks.

Two periodic jobs:

1. recompute_health_baselines (nightly @ 2 AM ET) — computes 7-day and 30-day
   rolling avg/std/min/max per (user_id, metric_type) into health_baseline.

2. detect_health_anomalies (hourly) — compares each metric's latest value
   against its 7-day baseline (z-score). Writes health_alert rows; promotes
   warning/urgent alerts to health_insight; sends push notifications for
   urgent severity through the unified_notification path.

Design notes:
 - Cumulative metrics (steps, active_energy, stand_minutes, etc.) are stored
   in health_metric as a running tally with metadata.cumulative=true. We
   aggregate to daily MAX before computing baselines, since AVG of cumulative
   is meaningless.
 - Point-sample metrics (heart_rate, spo2, etc.) get aggregated to daily AVG.
 - Single-row/day metrics (sleep_hours, weight, resting_hr, hrv_morning,
   sleep stage minutes) are used directly.
 - Anomaly direction is metric-specific: low HRV is bad, high RHR is bad,
   etc. ALERT_DIRECTION below encodes this.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


# ─── Metric classification ──────────────────────────────────────────────────

# Cumulative metrics: use daily MAX (the day's running total).
CUMULATIVE_METRICS = {
    "steps", "active_energy",
    "stand_minutes", "exercise_minutes",
    "flights_climbed", "mindful_minutes",
}

# Single-row-per-day metrics: use the value directly (don't aggregate).
SINGLE_DAILY_METRICS = {
    "sleep_hours", "sleep_deep_min", "sleep_rem_min",
    "sleep_core_min", "sleep_awake_min",
    "hrv_morning", "weight",
}

# All other tracked metrics aggregate to daily AVG.
KNOWN_METRICS = (CUMULATIVE_METRICS | SINGLE_DAILY_METRICS | {
    "resting_hr", "heart_rate", "hrv",
    "spo2", "respiratory_rate", "body_temp",
    "vo2_max", "walking_hr_avg", "hr_recovery_1min",
})

# Anomaly direction:
#   "low_bad"   → alert when z is very negative (deficit hurts)
#   "high_bad"  → alert when z is very positive (excess hurts)
#   "any_change"→ alert on either direction
ALERT_DIRECTION: Dict[str, str] = {
    # Low-is-bad
    "hrv": "low_bad",
    "hrv_morning": "low_bad",
    "sleep_hours": "low_bad",
    "sleep_deep_min": "low_bad",
    "sleep_rem_min": "low_bad",
    "spo2": "low_bad",
    "vo2_max": "low_bad",
    "hr_recovery_1min": "low_bad",
    # High-is-bad
    "resting_hr": "high_bad",
    "heart_rate": "high_bad",
    "respiratory_rate": "high_bad",
    "body_temp": "high_bad",
    "sleep_awake_min": "high_bad",
    # Any change is interesting
    "weight": "any_change",
    "walking_hr_avg": "any_change",
}

# Alert thresholds (absolute z-score, after direction check).
SEVERITY_BANDS: List[Tuple[float, str]] = [
    (3.0, "urgent"),
    (2.0, "warning"),
    (1.5, "caution"),
]

# Alert cooldown: don't re-fire same alert_type within this many hours.
ALERT_COOLDOWN_HOURS = 12

# Notification severity floor: only fire push for these.
NOTIFICATION_SEVERITY = {"urgent", "warning"}


# ─── Helpers ────────────────────────────────────────────────────────────────

def _list_users_with_metrics(db: Session, days: int = 30) -> List[str]:
    """Return distinct user_ids that have any health_metric in the window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(text("""
        SELECT DISTINCT user_id FROM health_metric
        WHERE recorded_at >= :cutoff
    """), {"cutoff": cutoff}).fetchall()
    return [r.user_id for r in rows]


def _daily_values_for_metric(
    db: Session, user_id: str, metric_type: str, days: int
) -> List[Tuple[Any, float]]:
    """
    Return [(date, daily_value)] over the past `days`.

    Aggregation depends on metric class:
      cumulative   → MAX(value)  (running tally → end-of-day total)
      single-daily → AVG(value)  (only one row/day; AVG just unwraps it)
      multi-sample → AVG(value)  (point readings averaged across the day)
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    if metric_type in CUMULATIVE_METRICS:
        agg = "MAX(value)"
    else:
        agg = "AVG(value)"

    rows = db.execute(text(f"""
        SELECT DATE(recorded_at AT TIME ZONE 'America/New_York') AS d,
               {agg} AS daily_value
        FROM health_metric
        WHERE user_id = :user_id
          AND metric_type = :metric_type
          AND recorded_at >= :cutoff
        GROUP BY DATE(recorded_at AT TIME ZONE 'America/New_York')
        ORDER BY d ASC
    """), {"user_id": user_id, "metric_type": metric_type, "cutoff": cutoff}).fetchall()
    return [(r.d, float(r.daily_value)) for r in rows if r.daily_value is not None]


def _stats(values: List[float]) -> Optional[Dict[str, float]]:
    """Return {avg, std, min, max, n} or None if not enough data."""
    n = len(values)
    if n == 0:
        return None
    avg = sum(values) / n
    if n >= 2:
        variance = sum((v - avg) ** 2 for v in values) / (n - 1)
        std = variance ** 0.5
    else:
        std = 0.0
    return {"avg": avg, "std": std, "min": min(values), "max": max(values), "n": n}


def _upsert_baseline(
    db: Session, user_id: str, metric_type: str, period_type: str,
    s: Dict[str, float], period_end,
):
    """Upsert a row in health_baseline keyed on (user_id, metric_type, period_type)."""
    db.execute(text("""
        INSERT INTO health_baseline (
            id, user_id, metric_type, period_type,
            average_value, std_deviation, min_value, max_value,
            sample_count, period_end, calculated_at
        ) VALUES (
            :id, :user_id, :metric_type, :period_type,
            :avg, :std, :min, :max,
            :n, :period_end, NOW()
        )
        ON CONFLICT (user_id, metric_type, period_type) DO UPDATE SET
            average_value  = EXCLUDED.average_value,
            std_deviation  = EXCLUDED.std_deviation,
            min_value      = EXCLUDED.min_value,
            max_value      = EXCLUDED.max_value,
            sample_count   = EXCLUDED.sample_count,
            period_end     = EXCLUDED.period_end,
            calculated_at  = EXCLUDED.calculated_at
    """), {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "metric_type": metric_type,
        "period_type": period_type,
        "avg": s["avg"],
        "std": s["std"],
        "min": s["min"],
        "max": s["max"],
        "n": s["n"],
        "period_end": period_end,
    })


# ─── Task 1: nightly baseline recompute ─────────────────────────────────────

@celery_app.task(bind=True, name="app.tasks.health_baselines.recompute_health_baselines")
def recompute_health_baselines(self) -> Dict[str, Any]:
    """Recompute 7-day and 30-day health baselines for all users with recent metrics."""
    from app.db.session import SessionLocal

    summary: Dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "users_processed": 0,
        "baselines_written": 0,
        "errors": [],
    }

    db: Session = SessionLocal()
    try:
        users = _list_users_with_metrics(db, days=30)
        for user_id in users:
            try:
                metrics_with_data = db.execute(text("""
                    SELECT DISTINCT metric_type FROM health_metric
                    WHERE user_id = :user_id
                      AND recorded_at >= NOW() - INTERVAL '30 days'
                """), {"user_id": user_id}).fetchall()

                for row in metrics_with_data:
                    metric_type = row.metric_type
                    if metric_type not in KNOWN_METRICS:
                        continue

                    daily_30 = _daily_values_for_metric(db, user_id, metric_type, 30)
                    if not daily_30:
                        continue

                    period_end = daily_30[-1][0]
                    values_30 = [v for _, v in daily_30]
                    values_7 = [v for d, v in daily_30 if d >= period_end - timedelta(days=7)]

                    s30 = _stats(values_30)
                    s7 = _stats(values_7)

                    if s30:
                        _upsert_baseline(db, user_id, metric_type, "30_day", s30, period_end)
                        summary["baselines_written"] += 1
                    if s7:
                        _upsert_baseline(db, user_id, metric_type, "7_day", s7, period_end)
                        summary["baselines_written"] += 1

                db.commit()
                summary["users_processed"] += 1
            except Exception as e:
                db.rollback()
                logger.exception(f"baseline recompute failed for user {user_id}: {e}")
                summary["errors"].append({"user_id": user_id, "error": str(e)})
    finally:
        db.close()

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(
        f"health baselines: {summary['users_processed']} users, "
        f"{summary['baselines_written']} baselines, {len(summary['errors'])} errors"
    )
    return summary


# ─── Task 2: hourly anomaly detection ───────────────────────────────────────

def _severity_for_z(abs_z: float) -> Optional[str]:
    for threshold, sev in SEVERITY_BANDS:
        if abs_z >= threshold:
            return sev
    return None


def _anomaly_message(metric_type: str, value: float, baseline_avg: float,
                     direction: str, severity: str) -> Tuple[str, str]:
    """Return (alert_type, human-readable message)."""
    pct_diff = ((value - baseline_avg) / baseline_avg * 100) if baseline_avg else 0
    label = metric_type.replace("_", " ")
    direction_word = "above" if value > baseline_avg else "below"
    alert_type = f"{metric_type}_{'spike' if value > baseline_avg else 'drop'}"
    msg = (
        f"{label.capitalize()} is {abs(pct_diff):.0f}% {direction_word} your 7-day average "
        f"({value:.1f} vs {baseline_avg:.1f})."
    )
    return alert_type, msg


def _recent_alert_exists(db: Session, user_id: str, alert_type: str, hours: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    row = db.execute(text("""
        SELECT 1 FROM health_alert
        WHERE user_id = :user_id AND alert_type = :alert_type
          AND created_at >= :cutoff
        LIMIT 1
    """), {"user_id": user_id, "alert_type": alert_type, "cutoff": cutoff}).fetchone()
    return row is not None


@celery_app.task(bind=True, name="app.tasks.health_baselines.detect_health_anomalies")
def detect_health_anomalies(self) -> Dict[str, Any]:
    """Compare latest readings against 7-day baselines, fire alerts on material deviations."""
    from app.db.session import SessionLocal

    summary: Dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "users_processed": 0,
        "alerts_created": 0,
        "insights_created": 0,
        "notifications_sent": 0,
        "skipped_cooldown": 0,
    }

    db: Session = SessionLocal()
    try:
        users = _list_users_with_metrics(db, days=2)
        for user_id in users:
            try:
                # Latest reading per metric (last 24h)
                rows = db.execute(text("""
                    SELECT DISTINCT ON (metric_type)
                        metric_type, value, recorded_at
                    FROM health_metric
                    WHERE user_id = :user_id
                      AND recorded_at >= NOW() - INTERVAL '24 hours'
                    ORDER BY metric_type, recorded_at DESC
                """), {"user_id": user_id}).fetchall()

                # 7-day baselines
                baselines = db.execute(text("""
                    SELECT metric_type, average_value, std_deviation, sample_count
                    FROM health_baseline
                    WHERE user_id = :user_id AND period_type = '7_day'
                """), {"user_id": user_id}).fetchall()
                baseline_map = {b.metric_type: b for b in baselines}

                for r in rows:
                    metric_type = r.metric_type
                    direction = ALERT_DIRECTION.get(metric_type)
                    if direction is None:
                        continue  # untracked metric

                    b = baseline_map.get(metric_type)
                    if not b or not b.std_deviation or float(b.std_deviation) <= 0:
                        continue
                    if (b.sample_count or 0) < 3:
                        continue  # need at least 3 days of history before alerting

                    value = float(r.value)
                    avg = float(b.average_value)
                    std = float(b.std_deviation)
                    z = (value - avg) / std

                    if direction == "low_bad" and z >= 0:
                        continue
                    if direction == "high_bad" and z <= 0:
                        continue

                    severity = _severity_for_z(abs(z))
                    if not severity:
                        continue

                    alert_type, message = _anomaly_message(
                        metric_type, value, avg, direction, severity
                    )

                    if _recent_alert_exists(db, user_id, alert_type, ALERT_COOLDOWN_HOURS):
                        summary["skipped_cooldown"] += 1
                        continue

                    alert_id = str(uuid.uuid4())
                    insight_id = None

                    # Create insight for material findings
                    if severity in NOTIFICATION_SEVERITY:
                        insight_id = str(uuid.uuid4())
                        db.execute(text("""
                            INSERT INTO health_insight (
                                id, user_id, insight_type, severity, title, content,
                                evidence, related_metrics, expires_at
                            ) VALUES (
                                :id, :user_id, 'anomaly', :severity, :title, :content,
                                :evidence, CAST(:related AS jsonb),
                                NOW() + INTERVAL '7 days'
                            )
                        """), {
                            "id": insight_id,
                            "user_id": user_id,
                            "severity": severity,
                            "title": f"{metric_type.replace('_', ' ').title()} anomaly",
                            "content": message,
                            "evidence": (
                                f"Latest: {value:.2f}; 7-day avg: {avg:.2f} ± {std:.2f}; "
                                f"z={z:.2f}; n={b.sample_count}"
                            ),
                            "related": _json_dump([{
                                "metric_type": metric_type,
                                "value": value,
                                "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
                            }]),
                        })
                        summary["insights_created"] += 1

                    db.execute(text("""
                        INSERT INTO health_alert (
                            id, user_id, alert_type, severity, message,
                            metric_data, insight_id
                        ) VALUES (
                            :id, :user_id, :alert_type, :severity, :message,
                            CAST(:metric_data AS jsonb), :insight_id
                        )
                    """), {
                        "id": alert_id,
                        "user_id": user_id,
                        "alert_type": alert_type,
                        "severity": severity,
                        "message": message,
                        "metric_data": _json_dump({
                            "metric_type": metric_type,
                            "value": value,
                            "baseline_avg": avg,
                            "baseline_std": std,
                            "z_score": round(z, 2),
                            "sample_count": b.sample_count,
                        }),
                        "insight_id": insight_id,
                    })
                    summary["alerts_created"] += 1

                    # Fire push notification for warning/urgent
                    if severity in NOTIFICATION_SEVERITY:
                        sent = _fire_push(user_id, alert_type, severity, message)
                        if sent:
                            db.execute(text("""
                                UPDATE health_alert SET notification_sent_at = NOW()
                                WHERE id = :id
                            """), {"id": alert_id})
                            summary["notifications_sent"] += 1

                db.commit()
                summary["users_processed"] += 1
            except Exception as e:
                db.rollback()
                logger.exception(f"anomaly detection failed for user {user_id}: {e}")
    finally:
        db.close()

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(
        f"health anomalies: {summary['users_processed']} users, "
        f"{summary['alerts_created']} alerts, {summary['insights_created']} insights, "
        f"{summary['notifications_sent']} pushes, {summary['skipped_cooldown']} cooldowns"
    )
    return summary


def _json_dump(obj: Any) -> str:
    import json
    return json.dumps(obj, default=str)


def _fire_push(user_id: str, alert_type: str, severity: str, message: str) -> bool:
    """Send push via unified_notification. Returns True on apparent success."""
    import asyncio
    try:
        from app.services.unified_notification import send_notification

        title_prefix = "🚨 Health alert" if severity == "urgent" else "⚠️ Health"
        async def _send():
            return await send_notification(
                user_id=user_id,
                title=title_prefix,
                message=message,
                priority="urgent" if severity == "urgent" else "important",
                category="health_anomaly",
                topic=f"health:{alert_type}",
                source="health_anomaly_detector",
                cooldown_hours=ALERT_COOLDOWN_HOURS,
            )

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule and assume success — task will return before the coroutine
                # finishes, but unified_notification handles its own logging/dedup.
                asyncio.ensure_future(_send())
                return True
            result = loop.run_until_complete(_send())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(_send())
            finally:
                loop.close()
        return bool(result and result.get("sent"))
    except Exception as e:
        logger.warning(f"health push failed: {e}")
        return False
