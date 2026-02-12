"""Worker management routes."""

import logging
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Workers"])

# Lazy-init worker coordinator
_worker_coordinator = None
_coordinator_attempted = False


def _get_coordinator():
    global _worker_coordinator, _coordinator_attempted
    if not _coordinator_attempted:
        _coordinator_attempted = True
        try:
            from app.workers.habit_worker_coordinator import HabitWorkerCoordinator
            _worker_coordinator = HabitWorkerCoordinator()
            _worker_coordinator.start_background_tasks()
            logger.info("Habit worker coordinator initialized")
        except Exception as e:
            logger.warning(f"Habit worker coordinator not available: {e}")
    return _worker_coordinator


@router.get("/workers/status")
async def get_worker_status(current_user: User = Depends(get_current_user)):
    """Get status of all habit workers"""
    coordinator = _get_coordinator()
    if not coordinator:
        raise HTTPException(status_code=503, detail="Worker coordinator not available")
    return coordinator.get_status()


@router.post("/workers/run/{task_name}")
async def run_worker_task(
    task_name: str,
    request: Dict[str, Any] = None,
    current_user: User = Depends(get_current_user)
):
    """Manually run a specific worker task"""
    coordinator = _get_coordinator()
    if not coordinator:
        raise HTTPException(status_code=503, detail="Worker coordinator not available")

    kwargs = request or {}
    result = await coordinator.run_manual_task(task_name, **kwargs)
    return result


@router.post("/workers/generate-instances/{user_id}")
async def generate_past_instances(
    user_id: str,
    days_back: int = 7,
    current_user: User = Depends(get_current_user)
):
    """Generate habit instances for past days (retro logging support)"""
    coordinator = _get_coordinator()
    if not coordinator:
        raise HTTPException(status_code=503, detail="Worker coordinator not available")

    if current_user.id != user_id and not getattr(current_user, 'is_admin', False):
        raise HTTPException(status_code=403, detail="Not authorized")

    result = await coordinator.run_manual_task(
        "generate_past_instances",
        user_id=user_id,
        days_back=days_back
    )
    return result


@router.post("/workers/streak-alerts/{user_id}")
async def send_streak_alerts(
    user_id: str,
    current_user: User = Depends(get_current_user)
):
    """Send streak alerts for a specific user"""
    coordinator = _get_coordinator()
    if not coordinator:
        raise HTTPException(status_code=503, detail="Worker coordinator not available")

    if current_user.id != user_id and not getattr(current_user, 'is_admin', False):
        raise HTTPException(status_code=403, detail="Not authorized")

    result = await coordinator.run_manual_task("streak_alerts", user_id=user_id)
    return result
