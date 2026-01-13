"""
Intelligence Reports API Routes
Weekly, monthly, and quarterly intelligence reports
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date, datetime
from pydantic import BaseModel

from app.db.session import get_db
from app.services.temporal_intelligence import get_temporal_intelligence, IntelligenceReport
from app.main_simple import get_current_user

router = APIRouter(prefix="/api/reports", tags=["intelligence"])


class GenerateReportRequest(BaseModel):
    """Request to generate a report"""
    report_type: str  # weekly, monthly, quarterly
    period_start: Optional[date] = None


class ReportResponse(BaseModel):
    """Response with intelligence report"""
    id: int
    report_type: str
    period_start: date
    period_end: date
    report_data: dict
    summary: Optional[str]
    insights: list
    patterns: list
    recommendations: list
    generation_time_ms: Optional[int]
    created_at: datetime
    delivered_at: Optional[datetime]


@router.get("/weekly/{week_start}", response_model=ReportResponse)
async def get_weekly_report(
    week_start: date,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get or generate weekly intelligence report

    Args:
        week_start: Monday of the week (YYYY-MM-DD)
    """
    try:
        engine = get_temporal_intelligence(db)

        # Try to retrieve existing report
        report = await engine.get_report(
            user_id=user.id,
            report_type="weekly",
            period_start=week_start
        )

        # Generate if doesn't exist
        if not report:
            report = await engine.generate_weekly_report(
                user_id=user.id,
                week_start=week_start
            )

        return ReportResponse(
            id=report.id,
            report_type=report.report_type,
            period_start=report.period_start,
            period_end=report.period_end,
            report_data=report.report_data,
            summary=report.summary,
            insights=report.insights,
            patterns=report.patterns,
            recommendations=report.recommendations,
            generation_time_ms=report.generation_time_ms,
            created_at=report.created_at,
            delivered_at=report.delivered_at
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating weekly report: {str(e)}")


@router.get("/monthly/{month_start}", response_model=ReportResponse)
async def get_monthly_report(
    month_start: date,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get or generate monthly intelligence report

    Args:
        month_start: First day of the month (YYYY-MM-DD)
    """
    try:
        engine = get_temporal_intelligence(db)

        # Try to retrieve existing report
        report = await engine.get_report(
            user_id=user.id,
            report_type="monthly",
            period_start=month_start
        )

        # Generate if doesn't exist
        if not report:
            report = await engine.generate_monthly_report(
                user_id=user.id,
                month=month_start
            )

        return ReportResponse(
            id=report.id,
            report_type=report.report_type,
            period_start=report.period_start,
            period_end=report.period_end,
            report_data=report.report_data,
            summary=report.summary,
            insights=report.insights,
            patterns=report.patterns,
            recommendations=report.recommendations,
            generation_time_ms=report.generation_time_ms,
            created_at=report.created_at,
            delivered_at=report.delivered_at
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating monthly report: {str(e)}")


@router.get("/quarterly/{quarter_start}", response_model=ReportResponse)
async def get_quarterly_report(
    quarter_start: date,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get or generate quarterly intelligence report

    Args:
        quarter_start: First day of the quarter (YYYY-MM-DD)
    """
    try:
        engine = get_temporal_intelligence(db)

        # Try to retrieve existing report
        report = await engine.get_report(
            user_id=user.id,
            report_type="quarterly",
            period_start=quarter_start
        )

        # Generate if doesn't exist
        if not report:
            report = await engine.generate_quarterly_report(
                user_id=user.id,
                quarter_start=quarter_start
            )

        return ReportResponse(
            id=report.id,
            report_type=report.report_type,
            period_start=report.period_start,
            period_end=report.period_end,
            report_data=report.report_data,
            summary=report.summary,
            insights=report.insights,
            patterns=report.patterns,
            recommendations=report.recommendations,
            generation_time_ms=report.generation_time_ms,
            created_at=report.created_at,
            delivered_at=report.delivered_at
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating quarterly report: {str(e)}")


@router.post("/generate", response_model=ReportResponse)
async def generate_report(
    request: GenerateReportRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Manually trigger report generation

    Args:
        request: Report type and optional period start
    """
    try:
        engine = get_temporal_intelligence(db)

        if request.report_type == "weekly":
            report = await engine.generate_weekly_report(
                user_id=user.id,
                week_start=request.period_start
            )
        elif request.report_type == "monthly":
            report = await engine.generate_monthly_report(
                user_id=user.id,
                month=request.period_start
            )
        elif request.report_type == "quarterly":
            report = await engine.generate_quarterly_report(
                user_id=user.id,
                quarter_start=request.period_start
            )
        else:
            raise HTTPException(status_code=400, detail="Invalid report_type. Must be: weekly, monthly, or quarterly")

        return ReportResponse(
            id=report.id,
            report_type=report.report_type,
            period_start=report.period_start,
            period_end=report.period_end,
            report_data=report.report_data,
            summary=report.summary,
            insights=report.insights,
            patterns=report.patterns,
            recommendations=report.recommendations,
            generation_time_ms=report.generation_time_ms,
            created_at=report.created_at,
            delivered_at=report.delivered_at
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating report: {str(e)}")


@router.get("/latest/{report_type}", response_model=Optional[ReportResponse])
async def get_latest_report(
    report_type: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get the latest report of a given type

    Args:
        report_type: weekly, monthly, or quarterly
    """
    try:
        from sqlalchemy import text

        query = text("""
            SELECT
                id, user_id, report_type, period_start, period_end,
                report_data, summary, insights, patterns,
                recommendations, generation_time_ms, created_at, delivered_at
            FROM intelligence_report
            WHERE user_id = :user_id
            AND report_type = :report_type
            ORDER BY period_start DESC
            LIMIT 1
        """)

        result = db.execute(query, {
            "user_id": user.id,
            "report_type": report_type
        })

        row = result.fetchone()

        if not row:
            return None

        import json

        return ReportResponse(
            id=row.id,
            report_type=row.report_type,
            period_start=row.period_start,
            period_end=row.period_end,
            report_data=json.loads(row.report_data) if isinstance(row.report_data, str) else row.report_data,
            summary=row.summary,
            insights=json.loads(row.insights) if isinstance(row.insights, str) else row.insights,
            patterns=json.loads(row.patterns) if isinstance(row.patterns, str) else row.patterns,
            recommendations=json.loads(row.recommendations) if isinstance(row.recommendations, str) else row.recommendations,
            generation_time_ms=row.generation_time_ms,
            created_at=row.created_at,
            delivered_at=row.delivered_at
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving latest report: {str(e)}")
