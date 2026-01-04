"""
Health Metrics API Routes

Handles:
- Batch ingestion of granular health metrics from iOS
- Retrieval of recent metrics for display
- Baseline queries for anomaly detection
- Health insights for Sara's conversational context
"""

import uuid
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health", tags=["health"])


# Import get_current_user from main_simple (deferred to avoid circular imports)
def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Get current user from JWT token - delegates to main_simple implementation."""
    from app.main_simple import get_current_user as _get_current_user
    return _get_current_user(request, db)


# ====================
# Request/Response Models
# ====================

class MetricInput(BaseModel):
    """Single health metric from iOS"""
    metric_type: str  # resting_hr, hrv, sleep_hours, steps, active_energy, heart_rate, weight
    value: float
    recorded_at: str  # ISO timestamp
    source: str = "apple_health"
    metadata: Optional[dict] = None


class DailyRecoveryInput(BaseModel):
    """Backward-compatible daily recovery data"""
    hrv: Optional[int] = None
    resting_hr: Optional[int] = None
    sleep_hours: Optional[float] = None


class BatchMetricsRequest(BaseModel):
    """Batch of health metrics from iOS background sync"""
    metrics: List[MetricInput]
    daily_recovery: Optional[DailyRecoveryInput] = None


class BatchMetricsResponse(BaseModel):
    """Response from batch ingestion"""
    success: bool
    inserted_count: int
    duplicate_count: int
    daily_recovery_updated: bool
    message: str


class MetricResponse(BaseModel):
    """Single metric in response"""
    id: str
    metric_type: str
    value: float
    recorded_at: str
    source: str
    metadata: Optional[dict] = None


class BaselineResponse(BaseModel):
    """Baseline data for a metric type"""
    metric_type: str
    period_type: str
    average_value: float
    std_deviation: Optional[float] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    sample_count: int
    calculated_at: str


class HealthInsightResponse(BaseModel):
    """Health insight for Sara's context"""
    id: str
    insight_type: str
    severity: str
    title: str
    content: str
    evidence: Optional[str] = None
    triggered_at: str
    surfaced_count: int


# ====================
# API Endpoints
# ====================

@router.post("/metrics/batch", response_model=BatchMetricsResponse)
async def ingest_metrics_batch(
    request: BatchMetricsRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Batch ingest health metrics from iOS background sync.

    - Deduplicates based on (user_id, metric_type, recorded_at)
    - Also updates daily_recovery_log for backward compatibility
    - Returns count of inserted and duplicate metrics
    """
    user_id = current_user.id
    inserted_count = 0
    duplicate_count = 0

    try:
        for metric in request.metrics:
            metric_id = str(uuid.uuid4())

            # Try to insert, skip duplicates
            metadata_json = json.dumps(metric.metadata) if metric.metadata else None
            result = db.execute(text("""
                INSERT INTO health_metric (id, user_id, metric_type, value, recorded_at, source, metadata)
                VALUES (:id, :user_id, :metric_type, :value, :recorded_at, :source, CAST(:metadata AS jsonb))
                ON CONFLICT (user_id, metric_type, recorded_at) DO NOTHING
                RETURNING id
            """), {
                "id": metric_id,
                "user_id": user_id,
                "metric_type": metric.metric_type,
                "value": metric.value,
                "recorded_at": metric.recorded_at,
                "source": metric.source,
                "metadata": metadata_json,
            })

            if result.fetchone():
                inserted_count += 1
            else:
                duplicate_count += 1

        # Also update daily_recovery_log for backward compatibility
        daily_recovery_updated = False
        if request.daily_recovery:
            daily_recovery_updated = await _update_daily_recovery(
                db, user_id, request.daily_recovery
            )

        db.commit()

        logger.info(f"Health metrics batch: {inserted_count} inserted, {duplicate_count} duplicates for user {user_id}")

        return BatchMetricsResponse(
            success=True,
            inserted_count=inserted_count,
            duplicate_count=duplicate_count,
            daily_recovery_updated=daily_recovery_updated,
            message=f"Ingested {inserted_count} new metrics ({duplicate_count} duplicates)"
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Error ingesting health metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _update_daily_recovery(
    db: Session,
    user_id: str,
    recovery: DailyRecoveryInput
) -> bool:
    """Update daily_recovery_log with the latest data (backward compatibility)."""
    try:
        today = datetime.now().strftime("%Y-%m-%d")

        # Check if row exists for today
        existing = db.execute(text("""
            SELECT id FROM daily_recovery_log
            WHERE user_id = :user_id AND log_date = :log_date
        """), {"user_id": user_id, "log_date": today}).fetchone()

        if existing:
            # Update existing row
            db.execute(text("""
                UPDATE daily_recovery_log
                SET hrv = COALESCE(:hrv, hrv),
                    heart_rate = COALESCE(:resting_hr, heart_rate),
                    sleep_hours = COALESCE(:sleep_hours, sleep_hours),
                    updated_at = NOW()
                WHERE user_id = :user_id AND log_date = :log_date
            """), {
                "user_id": user_id,
                "log_date": today,
                "hrv": recovery.hrv,
                "resting_hr": recovery.resting_hr,
                "sleep_hours": recovery.sleep_hours,
            })
        else:
            # Insert new row
            db.execute(text("""
                INSERT INTO daily_recovery_log (id, user_id, log_date, hrv, heart_rate, sleep_hours)
                VALUES (:id, :user_id, :log_date, :hrv, :resting_hr, :sleep_hours)
            """), {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "log_date": today,
                "hrv": recovery.hrv,
                "resting_hr": recovery.resting_hr,
                "sleep_hours": recovery.sleep_hours,
            })

        return True

    except Exception as e:
        logger.error(f"Error updating daily_recovery_log: {e}")
        return False


@router.get("/metrics/recent")
async def get_recent_metrics(
    metric_type: Optional[str] = None,
    hours: int = 24,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get recent health metrics for display.

    - Can filter by metric_type
    - Default to last 24 hours
    - Ordered by recorded_at DESC
    """
    user_id = current_user.id
    cutoff = datetime.now() - timedelta(hours=hours)

    try:
        if metric_type:
            result = db.execute(text("""
                SELECT id, metric_type, value, recorded_at, source, metadata
                FROM health_metric
                WHERE user_id = :user_id
                  AND metric_type = :metric_type
                  AND recorded_at >= :cutoff
                ORDER BY recorded_at DESC
                LIMIT :limit
            """), {
                "user_id": user_id,
                "metric_type": metric_type,
                "cutoff": cutoff,
                "limit": limit,
            })
        else:
            result = db.execute(text("""
                SELECT id, metric_type, value, recorded_at, source, metadata
                FROM health_metric
                WHERE user_id = :user_id
                  AND recorded_at >= :cutoff
                ORDER BY recorded_at DESC
                LIMIT :limit
            """), {
                "user_id": user_id,
                "cutoff": cutoff,
                "limit": limit,
            })

        metrics = []
        for row in result.fetchall():
            metrics.append({
                "id": row.id,
                "metric_type": row.metric_type,
                "value": float(row.value),
                "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
                "source": row.source,
                "metadata": row.metadata,
            })

        return {"metrics": metrics, "count": len(metrics)}

    except Exception as e:
        logger.error(f"Error getting recent metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/baselines")
async def get_baselines(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get current baselines for all metric types.

    Returns 7-day and 30-day baselines for each metric.
    """
    user_id = current_user.id

    try:
        result = db.execute(text("""
            SELECT metric_type, period_type, average_value, std_deviation,
                   min_value, max_value, sample_count, calculated_at
            FROM health_baseline
            WHERE user_id = :user_id
            ORDER BY metric_type, period_type
        """), {"user_id": user_id})

        baselines = []
        for row in result.fetchall():
            baselines.append({
                "metric_type": row.metric_type,
                "period_type": row.period_type,
                "average_value": float(row.average_value) if row.average_value else None,
                "std_deviation": float(row.std_deviation) if row.std_deviation else None,
                "min_value": float(row.min_value) if row.min_value else None,
                "max_value": float(row.max_value) if row.max_value else None,
                "sample_count": row.sample_count,
                "calculated_at": row.calculated_at.isoformat() if row.calculated_at else None,
            })

        return {"baselines": baselines}

    except Exception as e:
        logger.error(f"Error getting baselines: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/insights")
async def get_health_insights(
    limit: int = 10,
    include_expired: bool = False,
    severity: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get health insights for Sara's conversational context.

    - Returns recent unsurfaced insights by default
    - Can filter by severity (info, caution, warning, urgent)
    - Marks insights as surfaced when retrieved
    """
    user_id = current_user.id

    try:
        # Build query
        query = """
            SELECT id, insight_type, severity, title, content, evidence,
                   triggered_at, surfaced_count, correlation_data
            FROM health_insight
            WHERE user_id = :user_id
        """
        params = {"user_id": user_id, "limit": limit}

        if not include_expired:
            query += " AND (expires_at IS NULL OR expires_at > NOW())"

        if severity:
            query += " AND severity = :severity"
            params["severity"] = severity

        query += " ORDER BY triggered_at DESC LIMIT :limit"

        result = db.execute(text(query), params)

        insights = []
        insight_ids = []
        for row in result.fetchall():
            insights.append({
                "id": row.id,
                "insight_type": row.insight_type,
                "severity": row.severity,
                "title": row.title,
                "content": row.content,
                "evidence": row.evidence,
                "triggered_at": row.triggered_at.isoformat() if row.triggered_at else None,
                "surfaced_count": row.surfaced_count,
                "correlation_data": row.correlation_data,
            })
            insight_ids.append(row.id)

        # Mark as surfaced
        if insight_ids:
            db.execute(text("""
                UPDATE health_insight
                SET surfaced_count = surfaced_count + 1,
                    surfaced_at = COALESCE(surfaced_at, NOW())
                WHERE id = ANY(:ids)
            """), {"ids": insight_ids})
            db.commit()

        return {"insights": insights, "count": len(insights)}

    except Exception as e:
        logger.error(f"Error getting health insights: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_health_summary(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get a comprehensive health summary for Sara.

    Includes:
    - Latest values for each metric type
    - 7-day baselines
    - Comparison to baseline (above/below/normal)
    - Recent alerts
    """
    user_id = current_user.id

    try:
        # Get latest value for each metric type
        latest_metrics = db.execute(text("""
            SELECT DISTINCT ON (metric_type)
                metric_type, value, recorded_at
            FROM health_metric
            WHERE user_id = :user_id
              AND recorded_at >= NOW() - INTERVAL '24 hours'
            ORDER BY metric_type, recorded_at DESC
        """), {"user_id": user_id}).fetchall()

        # Get 7-day baselines
        baselines = db.execute(text("""
            SELECT metric_type, average_value, std_deviation
            FROM health_baseline
            WHERE user_id = :user_id AND period_type = '7_day'
        """), {"user_id": user_id}).fetchall()

        baseline_map = {b.metric_type: b for b in baselines}

        # Build summary
        summary = {}
        for metric in latest_metrics:
            baseline = baseline_map.get(metric.metric_type)
            status = "normal"

            if baseline and baseline.average_value and baseline.std_deviation:
                diff = metric.value - baseline.average_value
                if diff > baseline.std_deviation * 1.5:
                    status = "above_normal"
                elif diff < -baseline.std_deviation * 1.5:
                    status = "below_normal"

            summary[metric.metric_type] = {
                "current_value": float(metric.value),
                "recorded_at": metric.recorded_at.isoformat(),
                "baseline": float(baseline.average_value) if baseline and baseline.average_value else None,
                "status": status,
            }

        # Get recent alerts
        alerts = db.execute(text("""
            SELECT alert_type, severity, message, created_at
            FROM health_alert
            WHERE user_id = :user_id
              AND created_at >= NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC
            LIMIT 5
        """), {"user_id": user_id}).fetchall()

        recent_alerts = [{
            "alert_type": a.alert_type,
            "severity": a.severity,
            "message": a.message,
            "created_at": a.created_at.isoformat(),
        } for a in alerts]

        return {
            "metrics": summary,
            "recent_alerts": recent_alerts,
            "has_alerts": len(recent_alerts) > 0,
        }

    except Exception as e:
        logger.error(f"Error getting health summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/insights/{insight_id}/feedback")
async def submit_insight_feedback(
    insight_id: str,
    feedback: str,  # helpful, not_helpful, dismissed
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Submit feedback on a health insight."""
    user_id = current_user.id

    if feedback not in ["helpful", "not_helpful", "dismissed"]:
        raise HTTPException(status_code=400, detail="Invalid feedback value")

    try:
        result = db.execute(text("""
            UPDATE health_insight
            SET user_feedback = :feedback
            WHERE id = :id AND user_id = :user_id
            RETURNING id
        """), {"id": insight_id, "user_id": user_id, "feedback": feedback})

        if not result.fetchone():
            raise HTTPException(status_code=404, detail="Insight not found")

        db.commit()
        return {"success": True, "message": f"Feedback recorded: {feedback}"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error submitting insight feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))
