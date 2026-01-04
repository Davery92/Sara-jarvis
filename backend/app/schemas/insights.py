"""Autonomous insights and user profile schemas."""
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel


class UserProfileCreate(BaseModel):
    current_mode: Optional[str] = "companion"
    mode_preferences: Optional[Dict[str, Any]] = None
    autonomy_level: Optional[str] = "moderate"  # minimal, moderate, high
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    idle_thresholds: Optional[Dict[str, int]] = None
    ntfy_enabled: Optional[bool] = True
    ntfy_topics: Optional[Dict[str, str]] = None
    sprite_notifications: Optional[bool] = True
    profile_data: Optional[Dict[str, Any]] = None
    communication_style: Optional[str] = "balanced"
    notification_channels: Optional[Dict[str, Any]] = None


class UserProfileResponse(BaseModel):
    id: str
    user_id: str
    current_mode: str
    mode_preferences: Optional[Dict[str, Any]]
    autonomy_level: str  # minimal, moderate, high
    quiet_hours_start: Optional[str]
    quiet_hours_end: Optional[str]
    idle_thresholds: Optional[Dict[str, int]]
    ntfy_enabled: bool
    ntfy_topics: Optional[Dict[str, str]]
    sprite_notifications: bool
    profile_data: Optional[Dict[str, Any]]
    communication_style: str
    notification_channels: Optional[Dict[str, Any]]
    gtky_completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class AutonomousInsightResponse(BaseModel):
    id: str
    user_id: str
    insight_type: str
    sweep_type: str
    priority_score: float
    title: str
    message: str
    action_suggestion: Optional[Dict[str, str]]
    related_data: Optional[Dict[str, Any]]
    surfaced_at: Optional[datetime]
    user_action: Optional[str]
    feedback_score: Optional[int]
    generated_at: datetime
    expires_at: Optional[datetime]


class InsightFeedbackRequest(BaseModel):
    feedback_score: int  # -1, 0, 1
    user_action: str     # dismissed, acted_on, saved, snoozed


class ActivitySessionResponse(BaseModel):
    id: str
    user_id: str
    session_start: datetime
    session_end: Optional[datetime]
    idle_duration: int
    active_view: Optional[str]
    interaction_count: int
    quick_sweep_triggered: bool
    standard_sweep_triggered: bool
    digest_sweep_triggered: bool
    insights_generated: int
    created_at: datetime


class BackgroundSweepResponse(BaseModel):
    id: str
    user_id: str
    sweep_type: str
    triggered_by: str
    execution_time_ms: int
    insights_generated: int
    errors_encountered: Optional[List]
    episodes_analyzed: int
    notes_analyzed: int
    patterns_found: Optional[Dict[str, Any]]
    executed_at: datetime
