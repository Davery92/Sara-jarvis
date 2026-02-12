"""
Briefing, Context Mode, Intelligence Reports, Suggestions, and Patterns routes.
Extracted from main_simple.py.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.briefing import DailyBriefing, BriefingSettings
from app.models.context import ContextMode
from app.models import Episode, Note
from app.models.calendar_event import CalendarEvent
from app.models.doc import Document
from app.models.intelligence import IntelligenceReport, ProactiveSuggestion, DetectedPattern

logger = logging.getLogger(__name__)

router = APIRouter()


# ===================== DAILY BRIEFINGS =====================

@router.get("/api/briefings")
async def get_briefings(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get all daily briefings for the user"""
    try:
        user_id = current_user.id
        briefings = db.query(DailyBriefing).filter(
            DailyBriefing.user_id == user_id
        ).order_by(DailyBriefing.briefing_date.desc()).limit(30).all()

        return [{
            "id": b.id,
            "user_id": b.user_id,
            "briefing_type": b.briefing_type,
            "briefing_date": b.briefing_date.isoformat(),
            "content": b.content,
            "delivered": bool(b.delivered),
            "read": bool(b.read),
            "created_at": b.created_at.isoformat()
        } for b in briefings]
    except Exception as e:
        logger.error(f"Error getting briefings: {e}")
        return []


@router.get("/api/briefings/settings")
async def get_briefing_settings(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get briefing settings for the user"""
    try:
        user_id = current_user.id
        settings = db.query(BriefingSettings).filter(BriefingSettings.user_id == user_id).first()

        if not settings:
            # Create default settings
            settings = BriefingSettings(user_id=user_id)
            db.add(settings)
            db.commit()
            db.refresh(settings)

        return {
            "id": settings.id,
            "user_id": settings.user_id,
            "morning_enabled": bool(settings.morning_enabled),
            "morning_time": settings.morning_time,
            "evening_enabled": bool(settings.evening_enabled),
            "evening_time": settings.evening_time,
            "include_recovery": bool(settings.include_recovery),
            "include_schedule": bool(settings.include_schedule),
            "include_goals": bool(settings.include_goals),
            "include_suggestions": bool(settings.include_suggestions),
            "include_workout_rec": bool(settings.include_workout_rec),
            "include_accomplishments": bool(settings.include_accomplishments),
            "include_insights": bool(settings.include_insights),
            "include_reflection": bool(settings.include_reflection)
        }
    except Exception as e:
        logger.error(f"Error getting briefing settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/briefings/settings")
async def update_briefing_settings(settings_data: dict, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Update briefing settings"""
    try:
        user_id = current_user.id
        settings = db.query(BriefingSettings).filter(BriefingSettings.user_id == user_id).first()

        if not settings:
            settings = BriefingSettings(user_id=user_id)
            db.add(settings)

        # Update fields
        for key, value in settings_data.items():
            if hasattr(settings, key) and key != "id" and key != "user_id":
                setattr(settings, key, 1 if value else 0 if key.startswith("include_") or key.endswith("_enabled") else value)

        settings.updated_at = datetime.now()
        db.commit()
        db.refresh(settings)

        return {"success": True, "settings": settings_data}
    except Exception as e:
        logger.error(f"Error updating briefing settings: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/briefings/generate")
async def generate_briefing_route(data: dict, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Generate a new briefing"""
    try:
        # Lazy imports to avoid circular dependency with main_simple
        from app.services.phase4_intelligence import generate_daily_briefing
        from app.main_simple import call_llm_simple

        user_id = current_user.id
        briefing_type = data.get("briefing_type", "morning")

        # Use the intelligence service to generate briefing
        briefing = await generate_daily_briefing(
            db=db,
            user_id=user_id,
            briefing_type=briefing_type,
            llm_call_fn=call_llm_simple,
            Episode=Episode,
            Note=Note,
            CalendarEvent=CalendarEvent,
            DailyBriefing=DailyBriefing,
            BriefingSettings=BriefingSettings
        )

        return briefing
    except Exception as e:
        logger.error(f"Error generating briefing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/briefings/{briefing_id}/read")
async def mark_briefing_read(briefing_id: str, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Mark briefing as read"""
    try:
        user_id = current_user.id
        briefing = db.query(DailyBriefing).filter(
            DailyBriefing.id == briefing_id,
            DailyBriefing.user_id == user_id
        ).first()

        if briefing:
            briefing.read = 1
            db.commit()
            return {"success": True}

        raise HTTPException(status_code=404, detail="Briefing not found")
    except Exception as e:
        logger.error(f"Error marking briefing as read: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ===================== CONTEXT MODE =====================

@router.get("/api/context/mode")
async def get_context_mode_route(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get current context mode"""
    try:
        user_id = current_user.id
        context_mode = db.query(ContextMode).filter(ContextMode.user_id == user_id).first()

        if not context_mode:
            context_mode = ContextMode(user_id=user_id, current_mode="full")
            db.add(context_mode)
            db.commit()
            db.refresh(context_mode)

        return {"mode": context_mode.current_mode}
    except Exception as e:
        logger.error(f"Error getting context mode: {e}")
        return {"mode": "full"}


@router.put("/api/context/mode")
async def set_context_mode_route(data: dict, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Set context mode"""
    try:
        user_id = current_user.id
        new_mode = data.get("mode", "full")

        context_mode = db.query(ContextMode).filter(ContextMode.user_id == user_id).first()

        if not context_mode:
            context_mode = ContextMode(user_id=user_id, current_mode=new_mode)
            db.add(context_mode)
        else:
            context_mode.current_mode = new_mode
            context_mode.updated_at = datetime.now()

        db.commit()
        return {"mode": new_mode}
    except Exception as e:
        logger.error(f"Error setting context mode: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/context/stats")
async def get_context_stats_route(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get context statistics"""
    # Lazy import to avoid circular dependency
    from app.services.phase4_intelligence import get_context_stats

    user_id = current_user.id
    return get_context_stats(db, user_id, Episode, Note, Document, CalendarEvent)


# ===================== INTELLIGENCE REPORTS =====================

@router.get("/api/reports/list")
async def get_reports_list(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get list of intelligence reports"""
    try:
        user_id = current_user.id
        reports = db.query(IntelligenceReport).filter(
            IntelligenceReport.user_id == user_id
        ).order_by(IntelligenceReport.report_date.desc()).limit(20).all()

        return [{
            "id": r.id,
            "user_id": r.user_id,
            "report_type": r.report_type,
            "report_date": r.report_date.isoformat(),
            "title": r.title,
            "summary": r.summary,
            "created_at": r.created_at.isoformat()
        } for r in reports]
    except Exception as e:
        logger.error(f"Error getting reports list: {e}")
        return []


@router.post("/api/reports/generate")
async def generate_report_route(data: dict, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Generate an intelligence report"""
    try:
        # Lazy imports to avoid circular dependency with main_simple
        from app.services.phase4_intelligence import generate_intelligence_report
        from app.main_simple import call_llm_simple

        user_id = current_user.id
        report_type = data.get("report_type", "weekly")

        report = await generate_intelligence_report(
            db=db,
            user_id=user_id,
            report_type=report_type,
            llm_call_fn=call_llm_simple,
            Episode=Episode,
            IntelligenceReport=IntelligenceReport
        )

        return report
    except Exception as e:
        logger.error(f"Error generating intelligence report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================== SUGGESTIONS =====================

@router.get("/api/suggestions")
async def get_suggestions(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get proactive suggestions"""
    try:
        user_id = current_user.id
        suggestions = db.query(ProactiveSuggestion).filter(
            ProactiveSuggestion.user_id == user_id,
            ProactiveSuggestion.status == "pending"
        ).order_by(ProactiveSuggestion.created_at.desc()).limit(10).all()

        return [{
            "id": s.id,
            "title": s.title,
            "description": s.description,
            "category": s.category,
            "priority": s.priority,
            "confidence": s.confidence,
            "status": s.status,
            "created_at": s.created_at.isoformat()
        } for s in suggestions]
    except Exception as e:
        logger.error(f"Error getting suggestions: {e}")
        return []


@router.patch("/api/suggestions/{suggestion_id}")
async def update_suggestion(suggestion_id: str, data: dict, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Update suggestion status"""
    try:
        user_id = current_user.id
        status = data.get("status", "pending")

        suggestion = db.query(ProactiveSuggestion).filter(
            ProactiveSuggestion.id == suggestion_id,
            ProactiveSuggestion.user_id == user_id
        ).first()

        if suggestion:
            suggestion.status = status
            suggestion.actioned_at = datetime.now() if status in ["accepted", "dismissed"] else None
            db.commit()
            return {"id": suggestion_id, "status": status}

        raise HTTPException(status_code=404, detail="Suggestion not found")
    except Exception as e:
        logger.error(f"Error updating suggestion: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ===================== PATTERNS =====================

@router.get("/api/patterns")
async def get_patterns(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get detected patterns"""
    try:
        user_id = current_user.id
        patterns = db.query(DetectedPattern).filter(
            DetectedPattern.user_id == user_id
        ).order_by(DetectedPattern.confidence.desc()).limit(10).all()

        return [{
            "id": p.id,
            "pattern_type": p.pattern_type,
            "title": p.title,
            "description": p.description,
            "confidence": p.confidence,
            "frequency": p.frequency,
            "data_points": p.data_points,
            "first_detected": p.first_detected.isoformat(),
            "created_at": p.created_at.isoformat()
        } for p in patterns]
    except Exception as e:
        logger.error(f"Error getting patterns: {e}")
        return []
