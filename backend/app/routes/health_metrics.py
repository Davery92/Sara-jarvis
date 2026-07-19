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
from app.core.timezone import naive_local_now
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel, field_validator
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health", tags=["health"])


# Module-level: ensure 400s on this router log enough detail to debug client issues.
# FastAPI's default RequestValidationError handler returns the standard JSON but
# doesn't log the body content; for the metrics/workouts batch routes we want
# server-side visibility when the iOS side sends something unexpected.
async def _log_validation_error(request: Request, exc: RequestValidationError):
    try:
        body = (await request.body()).decode("utf-8", errors="replace")[:1000]
    except Exception:
        body = "<could not read body>"
    logger.warning(
        f"health validation error on {request.method} {request.url.path}: "
        f"errors={exc.errors()[:3]} body_preview={body!r}"
    )
    return JSONResponse(status_code=400, content={"detail": exc.errors()})


# Import get_current_user from main_simple (deferred to avoid circular imports)
def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Get current user from JWT token - delegates to main_simple implementation."""
    from app.main_simple import get_current_user as _get_current_user
    return _get_current_user(request, db)


# ====================
# Request/Response Models
# ====================

class MetricInput(BaseModel):
    """Single health metric from iOS.

    metric_type values currently emitted by the iOS background sync:
      Vitals:         resting_hr, weight, spo2, respiratory_rate, body_temp
      Cardio:         heart_rate, hrv, hrv_morning, vo2_max, walking_hr_avg, hr_recovery_1min
      Sleep:          sleep_hours, sleep_deep_min, sleep_rem_min, sleep_core_min, sleep_awake_min
      Activity:       steps, active_energy, stand_minutes, exercise_minutes,
                      flights_climbed, mindful_minutes
    Workouts go through /api/health/workouts/batch instead.
    """
    metric_type: str
    # Optional so a single NaN/null doesn't 400 the whole batch — we filter at insert time.
    value: Optional[float] = None
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
    skipped_invalid: int = 0
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
    skipped_invalid = 0

    try:
        import math
        for metric in request.metrics:
            # Skip rows with bad value (NaN, None, infinity). These come through
            # when HealthKit returns nullable samples for some types.
            if metric.value is None or not math.isfinite(metric.value):
                skipped_invalid += 1
                continue
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
            skipped_invalid=skipped_invalid,
            daily_recovery_updated=daily_recovery_updated,
            message=(
                f"Ingested {inserted_count} new metrics "
                f"({duplicate_count} dup, {skipped_invalid} invalid)"
            ),
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
        today = naive_local_now().strftime("%Y-%m-%d")

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
    cutoff = naive_local_now() - timedelta(hours=hours)

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


# ====================
# External Workouts (Apple Health / Watch-tracked)
# ====================

class WorkoutInput(BaseModel):
    """Single workout record from HealthKit."""
    external_id: str  # HKWorkout UUID — used for dedup
    activity_type: str  # e.g. "running", "walking", "cycling", "yoga"
    started_at: str
    ended_at: str
    duration_seconds: int
    total_energy_kcal: Optional[float] = None
    total_distance_m: Optional[float] = None
    avg_heart_rate: Optional[int] = None
    max_heart_rate: Optional[int] = None
    min_heart_rate: Optional[int] = None
    hr_zones: Optional[dict] = None  # {"zone_1": minutes, ...}
    workout_metadata: Optional[dict] = None
    source: str = "apple_health"


class BatchWorkoutsRequest(BaseModel):
    workouts: List[WorkoutInput]


class BatchWorkoutsResponse(BaseModel):
    success: bool
    inserted_count: int
    duplicate_count: int


@router.post("/workouts/batch", response_model=BatchWorkoutsResponse)
async def ingest_workouts_batch(
    request: BatchWorkoutsRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Batch-ingest HealthKit workouts. Deduped on (user_id, source, external_id)."""
    user_id = current_user.id
    inserted = 0
    duplicates = 0

    try:
        for w in request.workouts:
            workout_id = str(uuid.uuid4())
            hr_zones_json = json.dumps(w.hr_zones) if w.hr_zones else None
            metadata_json = json.dumps(w.workout_metadata) if w.workout_metadata else None
            result = db.execute(text("""
                INSERT INTO external_workout (
                    id, user_id, source, external_id, activity_type,
                    started_at, ended_at, duration_seconds,
                    total_energy_kcal, total_distance_m,
                    avg_heart_rate, max_heart_rate, min_heart_rate,
                    hr_zones, workout_metadata
                ) VALUES (
                    :id, :user_id, :source, :external_id, :activity_type,
                    :started_at, :ended_at, :duration_seconds,
                    :total_energy_kcal, :total_distance_m,
                    :avg_hr, :max_hr, :min_hr,
                    CAST(:hr_zones AS jsonb), CAST(:meta AS jsonb)
                )
                ON CONFLICT (user_id, source, external_id) DO NOTHING
                RETURNING id
            """), {
                "id": workout_id,
                "user_id": user_id,
                "source": w.source,
                "external_id": w.external_id,
                "activity_type": w.activity_type,
                "started_at": w.started_at,
                "ended_at": w.ended_at,
                "duration_seconds": w.duration_seconds,
                "total_energy_kcal": w.total_energy_kcal,
                "total_distance_m": w.total_distance_m,
                "avg_hr": w.avg_heart_rate,
                "max_hr": w.max_heart_rate,
                "min_hr": w.min_heart_rate,
                "hr_zones": hr_zones_json,
                "meta": metadata_json,
            })
            if result.fetchone():
                inserted += 1
            else:
                duplicates += 1

        db.commit()
        logger.info(f"External workouts: {inserted} inserted, {duplicates} duplicates for user {user_id}")
        return BatchWorkoutsResponse(success=True, inserted_count=inserted, duplicate_count=duplicates)

    except Exception as e:
        db.rollback()
        logger.error(f"Error ingesting workouts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workouts/recent")
async def get_recent_external_workouts(
    days: int = 30,
    activity_type: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List recent external workouts (HealthKit/Watch) for the user."""
    user_id = current_user.id
    cutoff = naive_local_now() - timedelta(days=days)

    query = """
        SELECT id, source, external_id, activity_type, started_at, ended_at,
               duration_seconds, total_energy_kcal, total_distance_m,
               avg_heart_rate, max_heart_rate, min_heart_rate,
               hr_zones, workout_metadata
        FROM external_workout
        WHERE user_id = :user_id AND started_at >= :cutoff
    """
    params = {"user_id": user_id, "cutoff": cutoff, "limit": limit}
    if activity_type:
        query += " AND activity_type = :activity_type"
        params["activity_type"] = activity_type
    query += " ORDER BY started_at DESC LIMIT :limit"

    try:
        result = db.execute(text(query), params)
        workouts = []
        for row in result.fetchall():
            workouts.append({
                "id": row.id,
                "source": row.source,
                "external_id": row.external_id,
                "activity_type": row.activity_type,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "ended_at": row.ended_at.isoformat() if row.ended_at else None,
                "duration_seconds": row.duration_seconds,
                "total_energy_kcal": float(row.total_energy_kcal) if row.total_energy_kcal else None,
                "total_distance_m": float(row.total_distance_m) if row.total_distance_m else None,
                "avg_heart_rate": row.avg_heart_rate,
                "max_heart_rate": row.max_heart_rate,
                "min_heart_rate": row.min_heart_rate,
                "hr_zones": row.hr_zones,
                "workout_metadata": row.workout_metadata,
            })
        return {"workouts": workouts, "count": len(workouts)}
    except Exception as e:
        logger.error(f"Error listing external workouts: {e}")
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
