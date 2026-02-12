"""Routes for Sara's autonomous insight system.

Handles autonomous insights, background sweeps, user profiles,
and feedback for the contextual intelligence system.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, and_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.insight import AutonomousInsight, BackgroundSweep
from app.models.profile import UserProfile
from app.schemas.insights import (
    UserProfileCreate,
    UserProfileResponse,
    AutonomousInsightResponse,
    InsightFeedbackRequest,
    BackgroundSweepResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/autonomous/insights", response_model=List[AutonomousInsightResponse])
async def get_autonomous_insights(
    limit: int = 20,
    sweep_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get autonomous insights for the current user"""
    query = db.query(AutonomousInsight).filter(AutonomousInsight.user_id == current_user.id)
    if sweep_type:
        query = query.filter(AutonomousInsight.sweep_type == sweep_type)
    insights = query.order_by(desc(AutonomousInsight.generated_at)).limit(limit).all()
    return [
        AutonomousInsightResponse(
            id=insight.id,
            user_id=insight.user_id,
            insight_type=insight.insight_type,
            sweep_type=insight.sweep_type,
            priority_score=insight.priority_score,
            title=insight.title,
            message=insight.message,
            action_suggestion=json.loads(insight.action_suggestion) if insight.action_suggestion else None,
            related_data=json.loads(insight.related_data) if insight.related_data else None,
            surfaced_at=insight.surfaced_at,
            user_action=insight.user_action,
            feedback_score=insight.feedback_score,
            generated_at=insight.generated_at,
            expires_at=insight.expires_at,
        )
        for insight in insights
    ]


@router.post("/autonomous/insights/{insight_id}/feedback")
async def submit_insight_feedback(
    insight_id: str,
    feedback: InsightFeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit feedback for an autonomous insight"""
    insight = db.query(AutonomousInsight).filter(
        and_(AutonomousInsight.id == insight_id, AutonomousInsight.user_id == current_user.id)
    ).first()
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")
    insight.feedback_score = feedback.feedback_score
    insight.user_action = feedback.user_action
    insight.surfaced_at = datetime.now()
    db.commit()
    return {"message": "Feedback recorded", "insight_id": insight_id}


@router.post("/autonomous/sweep/{sweep_type}")
async def trigger_autonomous_sweep(
    sweep_type: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually trigger an autonomous sweep for testing/debugging"""
    if sweep_type not in ['quick_sweep', 'standard_sweep', 'digest_sweep']:
        raise HTTPException(status_code=400, detail="Invalid sweep type")
    try:
        from app.services.autonomous_sweep_service import AutonomousSweepService
        sweep_service = AutonomousSweepService(db)
        raw_insights = await sweep_service.execute_sweep(
            user_id=current_user.id, sweep_type=sweep_type, triggered_by="manual"
        )
        recent_cutoff = datetime.now() - timedelta(hours=6)
        recent_insights = db.query(AutonomousInsight).filter(
            and_(
                AutonomousInsight.user_id == current_user.id,
                AutonomousInsight.generated_at >= recent_cutoff,
            )
        ).all()
        recent_types = {insight.insight_type for insight in recent_insights}
        recent_titles = {insight.title for insight in recent_insights}
        stored_insights = []
        new_insights = []
        for insight_data in raw_insights:
            if sweep_service.scorer.should_surface(insight_data['priority_score'], sweep_type):
                is_new = (
                    insight_data['type'] not in recent_types
                    and insight_data['title'] not in recent_titles
                )
                insight = AutonomousInsight(
                    user_id=current_user.id,
                    insight_type=insight_data['type'],
                    sweep_type=sweep_type,
                    priority_score=insight_data['priority_score'],
                    title=insight_data['title'],
                    message=insight_data['message'],
                    action_suggestion=json.dumps(insight_data.get('action_suggestion')),
                    related_data=json.dumps({
                        **insight_data.get('related_data', {}),
                        **(insight_data.get('memory_context', {})),
                    }),
                    generated_at=datetime.now(),
                )
                db.add(insight)
                stored_insights.append(insight)
                if is_new:
                    new_insights.append(insight)
        db.commit()
        return {
            "message": f"{sweep_type} completed successfully",
            "insights_generated": len(raw_insights),
            "insights_stored": len(stored_insights),
            "new_insights": len(new_insights),
            "sweep_type": sweep_type,
        }
    except Exception as e:
        logger.error(f"Autonomous sweep error: {e}")
        raise HTTPException(status_code=500, detail=f"Sweep execution failed: {str(e)}")


@router.get("/autonomous/profile", response_model=Optional[UserProfileResponse])
async def get_user_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get user's autonomous system profile"""
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    if not profile:
        return None
    return UserProfileResponse(
        id=profile.id,
        user_id=profile.user_id,
        current_mode=profile.current_mode,
        mode_preferences=json.loads(profile.mode_preferences) if profile.mode_preferences else None,
        autonomy_level=profile.autonomy_level,
        quiet_hours_start=profile.quiet_hours_start,
        quiet_hours_end=profile.quiet_hours_end,
        idle_thresholds=json.loads(profile.idle_thresholds) if profile.idle_thresholds else None,
        ntfy_enabled=profile.ntfy_enabled,
        ntfy_topics=json.loads(profile.ntfy_topics) if profile.ntfy_topics else None,
        sprite_notifications=profile.sprite_notifications,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@router.put("/autonomous/profile")
async def update_user_profile(
    profile_data: UserProfileCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update user's autonomous system profile"""
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    if not profile:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)
    if profile_data.current_mode is not None:
        profile.current_mode = profile_data.current_mode
    if profile_data.mode_preferences is not None:
        profile.mode_preferences = json.dumps(profile_data.mode_preferences)
    if profile_data.autonomy_level is not None:
        profile.autonomy_level = profile_data.autonomy_level
    if profile_data.quiet_hours_start is not None:
        profile.quiet_hours_start = profile_data.quiet_hours_start
    if profile_data.quiet_hours_end is not None:
        profile.quiet_hours_end = profile_data.quiet_hours_end
    if profile_data.idle_thresholds is not None:
        profile.idle_thresholds = json.dumps(profile_data.idle_thresholds)
    if profile_data.ntfy_enabled is not None:
        profile.ntfy_enabled = profile_data.ntfy_enabled
    if profile_data.ntfy_topics is not None:
        profile.ntfy_topics = json.dumps(profile_data.ntfy_topics)
    if profile_data.sprite_notifications is not None:
        profile.sprite_notifications = profile_data.sprite_notifications
    profile.updated_at = datetime.now()
    db.commit()
    return {"message": "Profile updated successfully", "profile_id": profile.id}


@router.get("/autonomous/sweeps", response_model=List[BackgroundSweepResponse])
async def get_background_sweeps(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get background sweep execution history"""
    sweeps = db.query(BackgroundSweep).filter(
        BackgroundSweep.user_id == current_user.id
    ).order_by(desc(BackgroundSweep.executed_at)).limit(limit).all()
    return [
        BackgroundSweepResponse(
            id=sweep.id,
            user_id=sweep.user_id,
            sweep_type=sweep.sweep_type,
            triggered_by=sweep.triggered_by,
            execution_time_ms=sweep.execution_time_ms,
            insights_generated=sweep.insights_generated,
            errors_encountered=json.loads(sweep.errors_encountered) if sweep.errors_encountered else None,
            episodes_analyzed=sweep.episodes_analyzed,
            notes_analyzed=sweep.notes_analyzed,
            patterns_found=json.loads(sweep.patterns_found) if sweep.patterns_found else None,
            executed_at=sweep.executed_at,
        )
        for sweep in sweeps
    ]
