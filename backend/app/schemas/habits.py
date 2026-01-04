"""Habit tracking schemas."""
from typing import Optional, List
from pydantic import BaseModel


class HabitCreate(BaseModel):
    title: str
    type: str  # binary, quantitative, checklist, time
    target_numeric: Optional[float] = None
    unit: Optional[str] = None
    rrule: str = "FREQ=DAILY"  # Default to daily
    weekly_minimum: Optional[int] = None
    monthly_minimum: Optional[int] = None
    windows: Optional[str] = None  # JSON string
    checklist_mode: Optional[str] = "all"  # all, percent
    checklist_threshold: Optional[float] = 1.0
    grace_days: int = 0
    retro_hours: int = 24
    notes: Optional[str] = None


class HabitResponse(BaseModel):
    id: str
    title: str
    type: str
    target_numeric: Optional[float] = None
    unit: Optional[str] = None
    rrule: str
    weekly_minimum: Optional[int] = None
    monthly_minimum: Optional[int] = None
    windows: Optional[str] = None
    checklist_mode: Optional[str] = None
    checklist_threshold: Optional[float] = None
    grace_days: int
    retro_hours: int
    paused: bool
    pause_from: Optional[str] = None
    pause_to: Optional[str] = None
    notes: Optional[str] = None
    created_at: str
    updated_at: str


class HabitItemCreate(BaseModel):
    label: str
    sort_order: int = 0


class HabitItemResponse(BaseModel):
    id: str
    habit_id: str
    label: str
    sort_order: int
    created_at: str


class HabitInstanceResponse(BaseModel):
    id: str
    habit_id: str
    date: str
    window: Optional[str] = None
    expected: bool
    status: str  # pending, complete, skipped
    progress: float
    total_amount: Optional[float] = None
    target: Optional[float] = None
    # Include habit details for Today view
    title: str
    type: str
    unit: Optional[str] = None


class HabitTodayStats(BaseModel):
    total: int
    completed: int
    in_progress: int
    completion_rate: float


class HabitTodayResponse(BaseModel):
    date: str
    habits: List[HabitInstanceResponse]
    stats: HabitTodayStats


class HabitInsightsOverview(BaseModel):
    total_habits: int
    active_habits: int
    total_completions: int
    average_completion_rate: float
    current_streaks: int
    longest_streak: int


class HabitInsightsWeeklyStats(BaseModel):
    this_week: dict
    last_week: dict
    trend: str


class HabitInsightsPerformance(BaseModel):
    habit_id: str
    title: str
    type: str
    completion_rate: float
    current_streak: int
    best_streak: int
    total_completions: int


class HabitInsightsPatterns(BaseModel):
    best_day_of_week: str
    best_time_of_day: str
    most_consistent_habit: str
    improvement_suggestions: List[str]


class HabitInsightsResponse(BaseModel):
    overview: HabitInsightsOverview
    weekly_stats: HabitInsightsWeeklyStats
    habit_performance: List[HabitInsightsPerformance]
    patterns: HabitInsightsPatterns


class HabitLogCreate(BaseModel):
    amount: Optional[float] = None
    source: str = "manual"
    payload: Optional[str] = None  # JSON string


class HabitLogResponse(BaseModel):
    id: str
    habit_id: str
    instance_id: Optional[str] = None
    ts: str
    source: str
    payload: Optional[str] = None
    created_at: str


class HabitStreakResponse(BaseModel):
    habit_id: str
    current_streak: int
    best_streak: int
    last_completed: Optional[str] = None


class HabitLinkCreate(BaseModel):
    target_type: str  # note, concept, document
    target_id: str
    meta: Optional[str] = None  # JSON string


class HabitLinkResponse(BaseModel):
    id: str
    habit_id: str
    target_type: str
    target_id: str
    meta: Optional[str] = None
    created_at: str


class HabitPauseRequest(BaseModel):
    pause_from: str  # ISO datetime
    pause_to: str    # ISO datetime
