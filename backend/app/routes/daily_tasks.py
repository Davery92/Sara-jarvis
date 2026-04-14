"""Daily tasks routes — per-day task management."""
import logging
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.models.user import User
from app.models.daily_task import DailyTask
from app.schemas.daily_tasks import DailyTaskCreate, DailyTaskUpdate, DailyTaskResponse
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/daily-tasks", tags=["Daily Tasks"])


def _task_to_response(task: DailyTask) -> DailyTaskResponse:
    return DailyTaskResponse(
        id=task.id,
        title=task.title,
        description=task.description,
        task_date=str(task.task_date),
        priority=task.priority or "normal",
        is_completed=bool(task.is_completed),
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        created_at=task.created_at.isoformat() if task.created_at else "",
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
    )


@router.get("", response_model=List[DailyTaskResponse])
async def list_tasks(
    date_str: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List tasks for a given date (default: today)."""
    target_date = date.today()
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")

    tasks = (
        db.query(DailyTask)
        .filter(DailyTask.user_id == current_user.id, DailyTask.task_date == target_date)
        .order_by(
            DailyTask.is_completed,
            # high > normal > low
            DailyTask.priority.desc(),
            DailyTask.created_at,
        )
        .all()
    )
    return [_task_to_response(t) for t in tasks]


@router.post("", response_model=DailyTaskResponse, status_code=201)
async def create_task(
    body: DailyTaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new daily task."""
    task_date = date.today()
    if body.task_date:
        try:
            task_date = date.fromisoformat(body.task_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")

    if body.priority not in ("low", "normal", "high"):
        raise HTTPException(status_code=400, detail="Priority must be low, normal, or high")

    task = DailyTask(
        user_id=current_user.id,
        title=body.title,
        description=body.description,
        task_date=task_date,
        priority=body.priority,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return _task_to_response(task)


@router.patch("/{task_id}", response_model=DailyTaskResponse)
async def update_task(
    task_id: str,
    body: DailyTaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a task (title, description, priority, or completion)."""
    task = db.query(DailyTask).filter(
        DailyTask.id == task_id, DailyTask.user_id == current_user.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if body.title is not None:
        task.title = body.title
    if body.description is not None:
        task.description = body.description
    if body.priority is not None:
        if body.priority not in ("low", "normal", "high"):
            raise HTTPException(status_code=400, detail="Priority must be low, normal, or high")
        task.priority = body.priority
    if body.is_completed is not None:
        task.is_completed = body.is_completed
        task.completed_at = datetime.now(timezone.utc) if body.is_completed else None

    db.commit()
    db.refresh(task)
    return _task_to_response(task)


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a task."""
    task = db.query(DailyTask).filter(
        DailyTask.id == task_id, DailyTask.user_id == current_user.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()


@router.patch("/{task_id}/toggle", response_model=DailyTaskResponse)
async def toggle_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Toggle task completion status."""
    task = db.query(DailyTask).filter(
        DailyTask.id == task_id, DailyTask.user_id == current_user.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.is_completed = not task.is_completed
    task.completed_at = datetime.now(timezone.utc) if task.is_completed else None
    db.commit()
    db.refresh(task)
    return _task_to_response(task)


@router.post("/carry-over", response_model=List[DailyTaskResponse])
async def carry_over_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Move yesterday's incomplete tasks to today."""
    from datetime import timedelta

    yesterday = date.today() - timedelta(days=1)
    today = date.today()

    incomplete = (
        db.query(DailyTask)
        .filter(
            DailyTask.user_id == current_user.id,
            DailyTask.task_date == yesterday,
            DailyTask.is_completed == False,
        )
        .all()
    )

    carried = []
    for old_task in incomplete:
        # Check for duplicate (same title already exists today)
        exists = db.query(DailyTask).filter(
            DailyTask.user_id == current_user.id,
            DailyTask.task_date == today,
            DailyTask.title == old_task.title,
        ).first()
        if exists:
            continue

        new_task = DailyTask(
            user_id=current_user.id,
            title=old_task.title,
            description=old_task.description,
            task_date=today,
            priority=old_task.priority,
        )
        db.add(new_task)
        carried.append(new_task)

    if carried:
        db.commit()
        for t in carried:
            db.refresh(t)

    return [_task_to_response(t) for t in carried]
