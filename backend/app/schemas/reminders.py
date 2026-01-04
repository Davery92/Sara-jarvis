"""Reminders and timers schemas."""
from typing import Optional
from pydantic import BaseModel


class ReminderCreate(BaseModel):
    title: str
    description: str = ""
    reminder_time: str  # ISO format datetime string


class ReminderUpdate(BaseModel):
    title: str = None
    description: str = None
    reminder_time: str = None
    is_completed: bool = None


class ReminderResponse(BaseModel):
    id: str
    title: str
    description: str
    reminder_time: str
    is_completed: bool
    created_at: str
    updated_at: str


class TimerCreate(BaseModel):
    title: str
    duration_minutes: int = None  # Optional for backward compatibility
    duration_seconds: int = None  # New field for seconds precision


class TimerResponse(BaseModel):
    id: str
    title: str
    duration_minutes: int
    start_time: str
    end_time: str
    is_active: bool
    is_completed: bool
    created_at: str
