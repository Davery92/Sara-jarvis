"""
Background Tasks API Routes

Endpoints for creating, monitoring, and managing background agent tasks.
"""

import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/background-tasks", tags=["background-tasks"])


# Pydantic models for API
class CreateTaskRequest(BaseModel):
    query: str
    task_type: str = "research"


class ClarificationResponse(BaseModel):
    response: str


class TaskResponse(BaseModel):
    id: str
    status: str
    task_type: str
    original_query: str
    result_note_id: Optional[str] = None
    workspace_folder_id: Optional[str] = None
    clarification_question: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    tasks: List[TaskResponse]
    active_count: int
    total_count: int


def _task_to_response(task) -> TaskResponse:
    """Convert BackgroundTask model to response."""
    return TaskResponse(
        id=task.id,
        status=task.status,
        task_type=task.task_type,
        original_query=task.original_query,
        result_note_id=task.result_note_id,
        workspace_folder_id=task.workspace_folder_id,
        clarification_question=task.clarification_question,
        error_message=task.error_message,
        created_at=task.created_at.isoformat() if task.created_at else None,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        updated_at=task.updated_at.isoformat() if getattr(task, 'updated_at', None) else None
    )


@router.post("", response_model=TaskResponse)
async def create_task(
    request: CreateTaskRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(lambda: _get_db()),
    current_user = Depends(lambda: _get_current_user())
):
    """
    Create a new background task and start it running.

    The task will run asynchronously and you can poll for status
    or receive push notifications when complete.
    """
    from ..services.background_task_service import get_background_task_service

    service = get_background_task_service()

    # Create task record
    task = await service.create_task(
        db=db,
        user_id=current_user.id,
        query=request.query,
        task_type=request.task_type
    )

    # Start task in background (doesn't block response)
    async def run_task_background():
        # Need a new session for background task
        from ..main_simple import SessionLocal
        async_db = SessionLocal()
        try:
            await service.run_task(async_db, task.id)
        finally:
            async_db.close()

    # Schedule as asyncio task
    asyncio.create_task(run_task_background())

    logger.info(f"Created and started background task {task.id}")

    return _task_to_response(task)


@router.get("/active", response_model=TaskListResponse)
async def get_active_tasks(
    db: Session = Depends(lambda: _get_db()),
    current_user = Depends(lambda: _get_current_user())
):
    """Get all active (pending/running) tasks for current user."""
    from ..services.background_task_service import get_background_task_service

    service = get_background_task_service()
    tasks = await service.get_active_tasks(db, current_user.id)

    return TaskListResponse(
        tasks=[_task_to_response(t) for t in tasks],
        active_count=len(tasks),
        total_count=len(tasks)
    )


@router.get("/recent", response_model=TaskListResponse)
async def get_recent_tasks(
    limit: int = 10,
    include_active: bool = True,
    db: Session = Depends(lambda: _get_db()),
    current_user = Depends(lambda: _get_current_user())
):
    """Get recent tasks for current user."""
    from ..services.background_task_service import get_background_task_service

    service = get_background_task_service()
    tasks = await service.get_recent_tasks(
        db, current_user.id, limit=limit, include_active=include_active
    )

    active_count = len([t for t in tasks if t.status in ["pending", "running", "needs_clarification"]])

    return TaskListResponse(
        tasks=[_task_to_response(t) for t in tasks],
        active_count=active_count,
        total_count=len(tasks)
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task_status(
    task_id: str,
    db: Session = Depends(lambda: _get_db()),
    current_user = Depends(lambda: _get_current_user())
):
    """Get status of a specific task."""
    from ..services.background_task_service import get_background_task_service
    from ..main_simple import BackgroundTask

    service = get_background_task_service()
    task = await service.get_task_status(db, task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Ensure user owns this task
    if task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return _task_to_response(task)


@router.post("/{task_id}/clarify", response_model=TaskResponse)
async def provide_clarification(
    task_id: str,
    request: ClarificationResponse,
    db: Session = Depends(lambda: _get_db()),
    current_user = Depends(lambda: _get_current_user())
):
    """
    Provide clarification response for a stuck task.

    Only works for tasks with status 'needs_clarification'.
    """
    from ..services.background_task_service import get_background_task_service

    service = get_background_task_service()

    # Verify task exists and user owns it
    task = await service.get_task_status(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if task.status != "needs_clarification":
        raise HTTPException(
            status_code=400,
            detail=f"Task is not waiting for clarification (status: {task.status})"
        )

    # Provide clarification
    success = await service.provide_clarification(db, task_id, request.response)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to provide clarification")

    # Refresh task
    task = await service.get_task_status(db, task_id)
    return _task_to_response(task)


# Dependency injection helpers (will be replaced with actual imports)
def _get_db():
    """Get database session - imported at runtime to avoid circular imports."""
    from ..main_simple import get_db
    return next(get_db())


def _get_current_user():
    """Get current user - imported at runtime to avoid circular imports."""
    # This will need to be properly integrated with the auth system
    # For now, return a mock or integrate later
    raise NotImplementedError("Integrate with actual auth system")


# Alternative: Export setup function to be called from main_simple.py
def setup_routes(app, get_db_func, get_user_func):
    """
    Setup routes with proper dependency injection.

    Call this from main_simple.py after app is created:
        from app.routes.background_tasks import setup_routes, router as bg_tasks_router
        setup_routes(app, get_db, get_current_user)
        app.include_router(bg_tasks_router)
    """
    global _get_db, _get_current_user

    def _get_db():
        return next(get_db_func())

    # For current_user, we need the request context
    # This will be handled differently - see integration below


# For cleaner integration, here's a function that returns properly configured routes
def get_configured_router(get_db, get_current_user):
    """
    Returns a router with properly configured dependencies.

    Usage in main_simple.py:
        from app.routes.background_tasks import get_configured_router
        bg_router = get_configured_router(get_db, get_current_user)
        app.include_router(bg_router)
    """
    from fastapi import Depends, Request

    configured_router = APIRouter(prefix="/api/background-tasks", tags=["background-tasks"])

    @configured_router.post("")
    async def create_task(
        request_body: CreateTaskRequest,
        request: Request,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db),
        current_user = Depends(get_current_user)
    ):
        from ..services.background_task_service import get_background_task_service

        service = get_background_task_service()

        task = await service.create_task(
            db=db,
            user_id=current_user.id,
            query=request_body.query,
            task_type=request_body.task_type
        )

        async def run_task_background():
            from ..main_simple import SessionLocal
            async_db = SessionLocal()
            try:
                await service.run_task(async_db, task.id)
            finally:
                async_db.close()

        asyncio.create_task(run_task_background())

        return _task_to_response(task)

    @configured_router.get("/active")
    async def get_active(
        db: Session = Depends(get_db),
        current_user = Depends(get_current_user)
    ):
        from ..services.background_task_service import get_background_task_service
        service = get_background_task_service()
        tasks = await service.get_active_tasks(db, current_user.id)
        return TaskListResponse(
            tasks=[_task_to_response(t) for t in tasks],
            active_count=len(tasks),
            total_count=len(tasks)
        )

    @configured_router.get("/recent")
    async def get_recent(
        limit: int = 10,
        include_active: bool = True,
        db: Session = Depends(get_db),
        current_user = Depends(get_current_user)
    ):
        from ..services.background_task_service import get_background_task_service
        service = get_background_task_service()
        tasks = await service.get_recent_tasks(db, current_user.id, limit=limit, include_active=include_active)
        active_count = len([t for t in tasks if t.status in ["pending", "running", "needs_clarification"]])
        return TaskListResponse(
            tasks=[_task_to_response(t) for t in tasks],
            active_count=active_count,
            total_count=len(tasks)
        )

    @configured_router.get("/{task_id}")
    async def get_status(
        task_id: str,
        db: Session = Depends(get_db),
        current_user = Depends(get_current_user)
    ):
        from ..services.background_task_service import get_background_task_service
        service = get_background_task_service()
        task = await service.get_task_status(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized")
        return _task_to_response(task)

    @configured_router.post("/{task_id}/clarify")
    async def clarify(
        task_id: str,
        request_body: ClarificationResponse,
        db: Session = Depends(get_db),
        current_user = Depends(get_current_user)
    ):
        from ..services.background_task_service import get_background_task_service
        service = get_background_task_service()
        task = await service.get_task_status(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized")
        if task.status != "needs_clarification":
            raise HTTPException(status_code=400, detail=f"Task status is {task.status}")

        await service.provide_clarification(db, task_id, request_body.response)
        task = await service.get_task_status(db, task_id)
        return _task_to_response(task)

    return configured_router
