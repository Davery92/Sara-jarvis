"""Daily tasks schemas."""
from typing import Optional
from pydantic import BaseModel


class DailyTaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str = "normal"
    task_date: Optional[str] = None  # YYYY-MM-DD, defaults to today


class DailyTaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    is_completed: Optional[bool] = None


class DailyTaskResponse(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    task_date: str
    priority: str
    is_completed: bool
    completed_at: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None
