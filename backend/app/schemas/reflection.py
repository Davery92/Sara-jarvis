"""Pydantic schemas for nightly reflection endpoints."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ReflectionStartRequest(BaseModel):
    reflection_date: Optional[str] = None


class ReflectionStartResponse(BaseModel):
    status: str
    reflection_id: Optional[str] = None
    message: Optional[str] = None
    reflection_date: Optional[str] = None
    current_question_index: Optional[int] = None
    total_questions: Optional[int] = None
    question: Optional[Dict[str, Any]] = None
    progress: Optional[str] = None
    estimated_time: Optional[str] = None
    responses: Optional[Dict[str, Any]] = None
    insights_generated: Optional[Dict[str, Any]] = None
    mood_score: Optional[int] = None
    can_update: Optional[bool] = None


class ReflectionRespondRequest(BaseModel):
    question_id: str
    response: Any
    question_index: int


# Alias for backward compatibility
ReflectionResponseRequest = ReflectionRespondRequest


class ReflectionResponseReply(BaseModel):
    status: str
    question: Optional[Dict[str, Any]] = None
    follow_up: Optional[str] = None
    progress: Optional[str] = None
    current_question_index: Optional[int] = None
    message: Optional[str] = None
    insights: Optional[Dict[str, Any]] = None
    reflection_summary: Optional[str] = None
    mood_score: Optional[int] = None
    next_steps: Optional[List[str]] = None


class ReflectionHistoryResponse(BaseModel):
    history: List[Dict[str, Any]]
    total_count: int
    current_streak: int
    pagination: Dict[str, Any]


class ReflectionInsightsResponse(BaseModel):
    reflection_id: str
    reflection_date: str
    insights: Dict[str, Any]
    responses: Dict[str, Any]
    mood_score: Optional[int] = None
    summary: str


class ReflectionSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    preferred_time: Optional[str] = None
    timezone: Optional[str] = None
    quiet_hours: Optional[Dict[str, Any]] = None
    reminder_channels: Optional[Dict[str, Any]] = None
