"""
Pattern Correlation API Routes

Endpoints for querying and managing cross-domain patterns.
"""

import logging
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models import User
from app.services.pattern_correlation_service import pattern_correlation_service
from app.services.temporal_bin_service import temporal_bin_service
from app.services.cross_domain_analyzer import cross_domain_analyzer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/patterns", tags=["patterns"])


# ==================== Request/Response Models ====================

class PatternResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    narrative: Optional[str]
    category: str
    metric_a: str
    metric_b: str
    correlation: float
    confidence: float
    sample_size: int
    p_value: Optional[float]
    status: str
    lag_hours: Optional[int]
    threshold: Optional[float]
    threshold_direction: Optional[str]
    validations: int
    invalidations: int
    first_detected: Optional[str]
    last_validated: Optional[str]
    surfaced_count: int


class TimeSeriesPoint(BaseModel):
    date: str
    value: Optional[float]
    day_of_week: Optional[int]
    is_weekend: Optional[bool]


class TimeSeriesResponse(BaseModel):
    metrics: dict  # metric_name -> list of TimeSeriesPoint


class CorrelationMatrixResponse(BaseModel):
    metrics: List[str]
    matrix: dict  # metric_a -> {metric_b -> correlation}


class DiscoveryResponse(BaseModel):
    run_id: str
    status: str
    bins_created: int
    bins_updated: int
    patterns_discovered: int
    patterns_validated: int
    patterns_invalidated: int
    duration_seconds: Optional[float]


class FeedbackRequest(BaseModel):
    feedback: str  # 'helpful', 'not_helpful', 'dismissed'
    notes: Optional[str] = None


class BinResponse(BaseModel):
    bin_date: str
    git: Optional[dict]
    health: Optional[dict]
    food: Optional[dict]
    home: Optional[dict]
    mood: Optional[dict]
    day_of_week: int
    is_weekend: bool


# ==================== Time Series Endpoints ====================

@router.get("/timeseries")
async def get_timeseries(
    metrics: str = Query(..., description="Comma-separated metrics like 'health.sleep_hours,git.commit_count'"),
    days: int = Query(30, ge=7, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get time series data for specified metrics."""
    metric_list = [m.strip() for m in metrics.split(',')]

    series = await temporal_bin_service.get_time_series(
        db, current_user.id, metric_list, days
    )

    # Count total data points
    data_points = sum(
        len([p for p in points if p.get('value') is not None])
        for points in series.values()
    )

    return {"series": series, "days": days, "data_points": data_points}


@router.get("/bins")
async def get_temporal_bins(
    days: int = Query(30, ge=7, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get raw temporal bin data."""
    start_date = date.today() - timedelta(days=days)

    result = db.execute(text("""
        SELECT bin_date, git_metrics, health_metrics, food_metrics,
               home_metrics, mood_metrics, day_of_week, is_weekend
        FROM temporal_bin
        WHERE user_id = :user_id
          AND bin_date >= :start_date
          AND bin_type = 'daily'
        ORDER BY bin_date DESC
    """), {"user_id": current_user.id, "start_date": start_date}).fetchall()

    bins = []
    for row in result:
        bins.append({
            "bin_date": row.bin_date.isoformat(),
            "git": row.git_metrics,
            "health": row.health_metrics,
            "food": row.food_metrics,
            "home": row.home_metrics,
            "mood": row.mood_metrics,
            "day_of_week": row.day_of_week,
            "is_weekend": row.is_weekend
        })

    return {"bins": bins, "count": len(bins)}


# ==================== Correlation Endpoints ====================

@router.get("/correlations")
async def get_correlation_matrix(
    days: int = Query(30, ge=14, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get correlation matrix for all metric pairs."""
    matrix = await pattern_correlation_service.get_correlation_matrix(
        db, current_user.id, days
    )

    # Get list of metrics
    metrics = list(matrix.keys())

    return {
        "metrics": metrics,
        "matrix": matrix,
        "days_analyzed": days
    }


@router.get("/correlations/analyze")
async def analyze_correlation(
    metric_a: str = Query(..., description="First metric (e.g., health.sleep_hours)"),
    metric_b: str = Query(..., description="Second metric (e.g., git.commit_count)"),
    lag_days: int = Query(0, ge=0, le=7),
    days: int = Query(30, ge=14, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Analyze correlation between two specific metrics."""
    result = await cross_domain_analyzer.analyze_correlation(
        db, current_user.id, metric_a, metric_b, days, lag_days
    )

    if not result:
        raise HTTPException(
            status_code=400,
            detail="Insufficient data for correlation analysis"
        )

    return {
        "metric_a": result.metric_a,
        "metric_b": result.metric_b,
        "correlation_coefficient": result.correlation_coefficient,
        "sample_size": result.sample_size,
        "p_value": result.p_value,
        "effect_size": result.effect_size,
        "lag_days": result.lag_days,
        "is_significant": result.is_significant,
        "interpretation": result.interpretation
    }


# ==================== Discovery Endpoints ====================

@router.post("/discover", response_model=DiscoveryResponse)
async def trigger_discovery(
    days: int = Query(30, ge=14, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually trigger pattern discovery."""
    result = await pattern_correlation_service.run_discovery(
        db, current_user.id, lookback_days=days
    )
    return result


@router.get("/discovery-status")
async def get_discovery_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get status of recent discovery runs."""
    result = db.execute(text("""
        SELECT id, run_type, started_at, completed_at, status,
               bins_created, bins_updated, patterns_discovered,
               patterns_validated, patterns_invalidated, error_message
        FROM pattern_discovery_log
        WHERE user_id = :user_id
        ORDER BY started_at DESC
        LIMIT 5
    """), {"user_id": current_user.id}).fetchall()

    runs = []
    for row in result:
        runs.append({
            "run_id": str(row.id),
            "run_type": row.run_type,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "status": row.status,
            "bins_created": row.bins_created,
            "bins_updated": row.bins_updated,
            "patterns_discovered": row.patterns_discovered,
            "patterns_validated": row.patterns_validated,
            "patterns_invalidated": row.patterns_invalidated,
            "error": row.error_message
        })

    return {"runs": runs}


@router.post("/backfill")
async def backfill_bins(
    days: int = Query(30, ge=7, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Backfill temporal bins for specified number of days."""
    result = await temporal_bin_service.backfill_bins(
        db, current_user.id, days
    )
    return {
        "status": "ok",
        "bins_created": result.get("created", 0),
        "bins_updated": result.get("updated", 0)
    }


# ==================== Relevant Patterns for Context ====================

@router.post("/relevant")
async def get_relevant_patterns(
    context: Optional[str] = None,
    limit: int = Query(3, ge=1, le=10),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get patterns relevant to the current conversation context."""
    patterns = await pattern_correlation_service.get_relevant_patterns(
        db, current_user.id, context, limit
    )
    return {"patterns": patterns}


# ==================== Pattern Endpoints (must be LAST due to {pattern_id} wildcard) ====================

@router.get("", response_model=List[PatternResponse])
async def get_patterns(
    include_emerging: bool = Query(False, description="Include emerging patterns"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all confirmed patterns for the user."""
    patterns = await pattern_correlation_service.get_all_patterns(
        db, current_user.id, include_emerging=include_emerging
    )
    return patterns


@router.get("/{pattern_id}", response_model=PatternResponse)
async def get_pattern(
    pattern_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific pattern by ID."""
    result = db.execute(text("""
        SELECT
            id, title, description, narrative, pattern_category,
            metric_a, metric_b, correlation_coefficient,
            confidence, sample_size, p_value,
            status, temporal_lag_hours,
            threshold_a, threshold_direction,
            validation_count, invalidation_count,
            first_detected_at, last_validated_at, surfaced_count
        FROM correlation_pattern
        WHERE id = :pattern_id AND user_id = :user_id
    """), {"pattern_id": pattern_id, "user_id": current_user.id}).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Pattern not found")

    return {
        "id": str(result.id),
        "title": result.title,
        "description": result.description,
        "narrative": result.narrative,
        "category": result.pattern_category,
        "metric_a": result.metric_a,
        "metric_b": result.metric_b,
        "correlation": result.correlation_coefficient,
        "confidence": result.confidence,
        "sample_size": result.sample_size,
        "p_value": result.p_value,
        "status": result.status,
        "lag_hours": result.temporal_lag_hours,
        "threshold": result.threshold_a,
        "threshold_direction": result.threshold_direction,
        "validations": result.validation_count,
        "invalidations": result.invalidation_count,
        "first_detected": result.first_detected_at.isoformat() if result.first_detected_at else None,
        "last_validated": result.last_validated_at.isoformat() if result.last_validated_at else None,
        "surfaced_count": result.surfaced_count
    }


@router.post("/{pattern_id}/feedback")
async def submit_pattern_feedback(
    pattern_id: str,
    request: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Submit feedback on a pattern."""
    # Update pattern with feedback
    result = db.execute(text("""
        UPDATE correlation_pattern
        SET user_feedback = :feedback,
            surfaced_count = surfaced_count + 1,
            last_surfaced_at = NOW(),
            updated_at = NOW()
        WHERE id = :pattern_id AND user_id = :user_id
        RETURNING id
    """), {
        "pattern_id": pattern_id,
        "user_id": current_user.id,
        "feedback": request.feedback
    })
    db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Pattern not found")

    return {"status": "ok", "message": "Feedback recorded"}
