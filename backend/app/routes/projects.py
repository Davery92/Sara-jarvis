"""
Project Development Tracker Routes
API endpoints for projects, tasks, commits, branches, and GitHub webhooks
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from io import BytesIO
import uuid
import mimetypes
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import re
import hmac
import hashlib
import logging
import os
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from app.db.session import get_db
from app.models.project_tracker import (
    DevProject, TaskItem, GitCommit, GitBranch, PullRequest,
    TaskCommitLink, PRTaskLink, TaskStatus, TaskType, TaskPriority,
    QAChecklistItem, QACommitResult, ProjectFolder, ProjectFile
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

# --- Project Models ---

class ProjectCreate(BaseModel):
    name: str
    prefix: str
    description: Optional[str] = None
    tech_stack: Optional[str] = None
    business_context: Optional[str] = None
    github_repo_url: Optional[str] = None  # Will parse owner/name


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    prefix: Optional[str] = None
    description: Optional[str] = None
    tech_stack: Optional[str] = None
    business_context: Optional[str] = None
    github_repo_url: Optional[str] = None
    is_active: Optional[bool] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    prefix: str
    description: Optional[str]
    tech_stack: Optional[str]
    business_context: Optional[str]
    github_repo_owner: Optional[str]
    github_repo_name: Optional[str]
    github_repo_url: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str
    task_counts: Optional[Dict[str, int]] = None


class ProjectListResponse(BaseModel):
    projects: List[ProjectResponse]
    total: int


# --- Task Models ---

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    task_type: str = "task"  # feature, bug, task, chore
    priority: Optional[str] = None  # low, medium, high, critical
    tags: Optional[List[str]] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    task_type: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[List[str]] = None
    sort_order: Optional[int] = None


class TaskResponse(BaseModel):
    id: str
    project_id: str
    task_number: int
    tag: str  # e.g., "RN-42"
    title: str
    description: Optional[str]
    task_type: str
    status: str
    priority: Optional[str]
    tags: Optional[List[str]]
    sort_order: int
    created_at: str
    updated_at: str
    completed_at: Optional[str]
    commit_count: int = 0


class TaskListResponse(BaseModel):
    tasks: List[TaskResponse]
    total: int
    by_status: Dict[str, int]


class TaskBoardResponse(BaseModel):
    """Full Kanban board data"""
    backlog: List[TaskResponse]
    in_progress: List[TaskResponse]
    in_qa: List[TaskResponse]
    completed: List[TaskResponse]
    total: int


# --- Commit Models ---

class CommitResponse(BaseModel):
    id: str
    sha: str
    short_sha: str
    message: str
    author_name: Optional[str]
    author_email: Optional[str]
    committed_at: str
    branch: Optional[str]
    additions: Optional[int]
    deletions: Optional[int]
    linked_tasks: List[str]  # Task tags


class CommitListResponse(BaseModel):
    commits: List[CommitResponse]
    total: int
    page: int
    per_page: int


class CommitLinkRequest(BaseModel):
    task_id: str


# --- Activity Models ---

class ActivityItem(BaseModel):
    id: str
    type: str  # commit, task_created, task_status_change, pr_opened, pr_merged
    title: str
    description: Optional[str]
    timestamp: str
    metadata: Dict[str, Any]


class ActivityFeed(BaseModel):
    items: List[ActivityItem]
    total: int


# --- Stats Models ---

class ProjectStats(BaseModel):
    task_counts: Dict[str, int]
    commits_this_week: int
    tasks_completed_this_week: int
    open_bugs: int
    active_branches: int
    velocity: Dict[str, Any]


# --- QA Models ---

class QAChecklistItemCreate(BaseModel):
    label: str
    sort_order: Optional[int] = None


class QAChecklistItemUpdate(BaseModel):
    label: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class QAChecklistItemResponse(BaseModel):
    id: str
    label: str
    sort_order: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class QAChecklistResponse(BaseModel):
    items: List[QAChecklistItemResponse]
    total: int


class QAResultCreate(BaseModel):
    checked_items: List[str]  # List of checklist item IDs
    notes: Optional[str] = None
    status: str  # passed, failed, skipped


class QAResultResponse(BaseModel):
    id: str
    commit_id: str
    checked_items: List[str]
    notes: Optional[str]
    status: str
    tested_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class QAPendingCommit(BaseModel):
    id: str
    sha: str
    message: str
    author_name: Optional[str]
    committed_at: datetime
    qa_status: Optional[str]  # None = never tested, or status from qa_commit_result


class QAPendingTask(BaseModel):
    task_id: str
    task_tag: str
    task_title: str
    commits: List[QAPendingCommit]


class QAPendingResponse(BaseModel):
    tasks: List[QAPendingTask]
    total_commits: int


# --- Project Files Models ---

class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[str] = None


class FolderUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[str] = None  # For moving folders


class FolderResponse(BaseModel):
    id: str
    name: str
    parent_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FolderTreeItem(BaseModel):
    id: str
    name: str
    parent_id: Optional[str]
    children: List['FolderTreeItem'] = []


class FolderListResponse(BaseModel):
    folders: List[FolderResponse]
    total: int


class FolderTreeResponse(BaseModel):
    tree: List[FolderTreeItem]
    total: int


class FileResponse(BaseModel):
    id: str
    filename: str
    folder_id: Optional[str]
    mime_type: Optional[str]
    file_size: int
    file_size_formatted: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FileUpdate(BaseModel):
    filename: Optional[str] = None
    folder_id: Optional[str] = None  # For moving files
    description: Optional[str] = None


class FileListResponse(BaseModel):
    files: List[FileResponse]
    folders: List[FolderResponse]  # Subfolders in current directory
    total_files: int
    total_folders: int
    current_folder_id: Optional[str]
    breadcrumb: List[FolderResponse]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def get_current_user_id(request: Request, db: Session = Depends(get_db)) -> str:
    """Get current user ID from JWT token (cookie or Authorization header)"""
    from jose import jwt, JWTError
    from app.core.config import settings

    # Try to get token from cookie first (for web UI)
    access_token = request.cookies.get("access_token")

    # If no cookie, try Authorization header (for programmatic access like iOS app)
    if not access_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            access_token = auth_header[7:]

    if not access_token:
        # Fall back to SOLO_USER_ID for unauthenticated requests
        solo_user_id = os.getenv("SOLO_USER_ID")
        if solo_user_id:
            return solo_user_id
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(access_token, settings.jwt_secret, algorithms=["HS256"])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def parse_github_url(url: str) -> tuple[str, str] | None:
    """Parse GitHub repo URL to extract owner and name"""
    if not url:
        return None

    # Handle various GitHub URL formats
    patterns = [
        r'github\.com[/:]([^/]+)/([^/.]+)',  # https or ssh
        r'^([^/]+)/([^/]+)$',  # owner/repo shorthand
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            owner = match.group(1)
            name = match.group(2)
            # Remove .git suffix if present
            if name.endswith('.git'):
                name = name[:-4]
            return owner, name

    return None


def parse_task_tags(text: str) -> List[tuple[str, int]]:
    """
    Parse task tags from commit message or PR description.
    Returns list of (prefix, number) tuples.
    Example: "Fix bug RN-42 and SARA-17" -> [("RN", 42), ("SARA", 17)]
    """
    pattern = r'\b([A-Z]+)-(\d+)\b'
    matches = re.findall(pattern, text)
    return [(prefix, int(num)) for prefix, num in matches]


def parse_status_keywords(text: str) -> Dict[str, List[tuple[str, int]]]:
    """
    Parse status-change keywords from commit message.
    Returns dict mapping status to list of task tags.
    Example: "closes RN-42, qa SARA-17" -> {"completed": [("RN", 42)], "in_qa": [("SARA", 17)]}
    """
    result = {
        "completed": [],
        "in_qa": []
    }

    # Patterns for auto-completing tasks
    close_patterns = [
        r'\b(?:closes?|fixes?|resolved?)\s+([A-Z]+-\d+)',
    ]

    # Patterns for moving to QA
    qa_patterns = [
        r'\b(?:qa|testing)\s+([A-Z]+-\d+)',
    ]

    for pattern in close_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            parts = match.split('-')
            if len(parts) == 2:
                result["completed"].append((parts[0].upper(), int(parts[1])))

    for pattern in qa_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            parts = match.split('-')
            if len(parts) == 2:
                result["in_qa"].append((parts[0].upper(), int(parts[1])))

    return result


def task_to_response(task: TaskItem, include_commit_count: bool = True) -> TaskResponse:
    """Convert TaskItem model to response"""
    # Get the project prefix for the tag
    prefix = task.project.prefix if task.project else "TASK"

    return TaskResponse(
        id=task.id,
        project_id=task.project_id,
        task_number=task.task_number,
        tag=f"{prefix}-{task.task_number}",
        title=task.title,
        description=task.description,
        task_type=task.task_type,
        status=task.status,
        priority=task.priority,
        tags=task.tags,
        sort_order=task.sort_order,
        created_at=task.created_at.isoformat() if task.created_at else "",
        updated_at=task.updated_at.isoformat() if task.updated_at else "",
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        commit_count=len(task.commit_links) if include_commit_count else 0
    )


def project_to_response(project: DevProject, include_counts: bool = True, db: Session = None) -> ProjectResponse:
    """Convert DevProject model to response"""
    task_counts = None

    if include_counts and db:
        # Count tasks by status
        counts = db.query(
            TaskItem.status,
            func.count(TaskItem.id)
        ).filter(
            TaskItem.project_id == project.id,
            TaskItem.is_deleted == False
        ).group_by(TaskItem.status).all()

        task_counts = {status: count for status, count in counts}

    return ProjectResponse(
        id=project.id,
        name=project.name,
        prefix=project.prefix,
        description=project.description,
        tech_stack=project.tech_stack,
        business_context=project.business_context,
        github_repo_owner=project.github_repo_owner,
        github_repo_name=project.github_repo_name,
        github_repo_url=project.github_repo_url,
        is_active=project.is_active,
        created_at=project.created_at.isoformat() if project.created_at else "",
        updated_at=project.updated_at.isoformat() if project.updated_at else "",
        task_counts=task_counts
    )


# ============================================================================
# PROJECT ENDPOINTS
# ============================================================================

@router.get("", response_model=ProjectListResponse)
async def list_projects(
    request: Request,
    active_only: bool = Query(True, description="Only return active projects"),
    db: Session = Depends(get_db)
):
    """List all projects for the current user"""
    user_id = await get_current_user_id(request, db)

    try:
        query = db.query(DevProject).filter(DevProject.user_id == user_id)

        if active_only:
            query = query.filter(DevProject.is_active == True)

        projects = query.order_by(DevProject.name).all()

        return ProjectListResponse(
            projects=[project_to_response(p, include_counts=True, db=db) for p in projects],
            total=len(projects)
        )
    except Exception as e:
        logger.error(f"Failed to list projects: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve projects")


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    request: Request,
    project_data: ProjectCreate,
    db: Session = Depends(get_db)
):
    """Create a new project"""
    user_id = await get_current_user_id(request, db)

    try:
        # Check for duplicate prefix
        existing = db.query(DevProject).filter(
            DevProject.user_id == user_id,
            DevProject.prefix == project_data.prefix.upper()
        ).first()

        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Project with prefix '{project_data.prefix}' already exists"
            )

        # Parse GitHub URL if provided
        github_owner = None
        github_name = None
        if project_data.github_repo_url:
            parsed = parse_github_url(project_data.github_repo_url)
            if parsed:
                github_owner, github_name = parsed

        project = DevProject(
            user_id=user_id,
            name=project_data.name,
            prefix=project_data.prefix.upper(),
            description=project_data.description,
            tech_stack=project_data.tech_stack,
            business_context=project_data.business_context,
            github_repo_owner=github_owner,
            github_repo_name=github_name
        )

        db.add(project)
        db.commit()
        db.refresh(project)

        logger.info(f"Created project: {project.name} ({project.prefix})")
        return project_to_response(project, include_counts=False)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create project: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create project")


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    request: Request,
    project_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific project by ID"""
    user_id = await get_current_user_id(request, db)

    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return project_to_response(project, include_counts=True, db=db)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    request: Request,
    project_id: str,
    project_data: ProjectUpdate,
    db: Session = Depends(get_db)
):
    """Update a project"""
    user_id = await get_current_user_id(request, db)

    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        # Update fields if provided
        if project_data.name is not None:
            project.name = project_data.name
        if project_data.prefix is not None:
            # Check for duplicate prefix
            existing = db.query(DevProject).filter(
                DevProject.user_id == user_id,
                DevProject.prefix == project_data.prefix.upper(),
                DevProject.id != project_id
            ).first()
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Project with prefix '{project_data.prefix}' already exists"
                )
            project.prefix = project_data.prefix.upper()
        if project_data.description is not None:
            project.description = project_data.description
        if project_data.tech_stack is not None:
            project.tech_stack = project_data.tech_stack
        if project_data.business_context is not None:
            project.business_context = project_data.business_context
        if project_data.is_active is not None:
            project.is_active = project_data.is_active
        if project_data.github_repo_url is not None:
            parsed = parse_github_url(project_data.github_repo_url)
            if parsed:
                project.github_repo_owner, project.github_repo_name = parsed
            else:
                project.github_repo_owner = None
                project.github_repo_name = None

        db.commit()
        db.refresh(project)

        return project_to_response(project, include_counts=True, db=db)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update project: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update project")


@router.delete("/{project_id}")
async def delete_project(
    request: Request,
    project_id: str,
    db: Session = Depends(get_db)
):
    """Soft delete a project (set is_active=False)"""
    user_id = await get_current_user_id(request, db)

    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        project.is_active = False
        db.commit()

        return {"message": "Project archived successfully"}

    except Exception as e:
        logger.error(f"Failed to delete project: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to archive project")


@router.get("/{project_id}/stats", response_model=ProjectStats)
async def get_project_stats(
    request: Request,
    project_id: str,
    db: Session = Depends(get_db)
):
    """Get statistics for a project"""
    user_id = await get_current_user_id(request, db)

    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        from datetime import timedelta
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)

        # Task counts by status
        task_counts_query = db.query(
            TaskItem.status,
            func.count(TaskItem.id)
        ).filter(
            TaskItem.project_id == project_id,
            TaskItem.is_deleted == False
        ).group_by(TaskItem.status).all()

        task_counts = {status: count for status, count in task_counts_query}

        # Commits this week
        commits_this_week = db.query(func.count(GitCommit.id)).filter(
            GitCommit.project_id == project_id,
            GitCommit.committed_at >= week_ago
        ).scalar() or 0

        # Tasks completed this week
        tasks_completed_this_week = db.query(func.count(TaskItem.id)).filter(
            TaskItem.project_id == project_id,
            TaskItem.status == "completed",
            TaskItem.completed_at >= week_ago
        ).scalar() or 0

        # Open bugs
        open_bugs = db.query(func.count(TaskItem.id)).filter(
            TaskItem.project_id == project_id,
            TaskItem.task_type == "bug",
            TaskItem.status.in_(["backlog", "in_progress", "in_qa"]),
            TaskItem.is_deleted == False
        ).scalar() or 0

        # Active branches (non-merged, non-deleted)
        active_branches = db.query(func.count(GitBranch.id)).filter(
            GitBranch.project_id == project_id,
            GitBranch.is_merged == False,
            GitBranch.is_deleted == False
        ).scalar() or 0

        return ProjectStats(
            task_counts=task_counts,
            commits_this_week=commits_this_week,
            tasks_completed_this_week=tasks_completed_this_week,
            open_bugs=open_bugs,
            active_branches=active_branches,
            velocity={
                "commits_per_day": round(commits_this_week / 7, 1),
                "tasks_per_week": tasks_completed_this_week
            }
        )

    except Exception as e:
        logger.error(f"Failed to get project stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve stats")


# ============================================================================
# TASK ENDPOINTS
# ============================================================================

@router.get("/{project_id}/tasks", response_model=TaskListResponse)
async def list_tasks(
    request: Request,
    project_id: str,
    status: Optional[str] = Query(None, description="Filter by status"),
    task_type: Optional[str] = Query(None, description="Filter by type"),
    include_deleted: bool = Query(False, description="Include deleted tasks"),
    db: Session = Depends(get_db)
):
    """List tasks for a project"""
    user_id = await get_current_user_id(request, db)

    # Verify project access
    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        query = db.query(TaskItem).filter(TaskItem.project_id == project_id)

        if not include_deleted:
            query = query.filter(TaskItem.is_deleted == False)

        if status:
            query = query.filter(TaskItem.status == status)

        if task_type:
            query = query.filter(TaskItem.task_type == task_type)

        tasks = query.order_by(TaskItem.sort_order, TaskItem.created_at.desc()).all()

        # Count by status
        status_counts = {}
        for task in tasks:
            status_counts[task.status] = status_counts.get(task.status, 0) + 1

        return TaskListResponse(
            tasks=[task_to_response(t) for t in tasks],
            total=len(tasks),
            by_status=status_counts
        )

    except Exception as e:
        logger.error(f"Failed to list tasks: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve tasks")


@router.get("/{project_id}/board", response_model=TaskBoardResponse)
async def get_task_board(
    request: Request,
    project_id: str,
    db: Session = Depends(get_db)
):
    """Get full Kanban board data for a project"""
    user_id = await get_current_user_id(request, db)

    # Verify project access
    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        tasks = db.query(TaskItem).filter(
            TaskItem.project_id == project_id,
            TaskItem.is_deleted == False
        ).order_by(TaskItem.sort_order, TaskItem.created_at.desc()).all()

        # Group by status
        board = {
            "backlog": [],
            "in_progress": [],
            "in_qa": [],
            "completed": []
        }

        for task in tasks:
            task_response = task_to_response(task)
            if task.status in board:
                board[task.status].append(task_response)

        return TaskBoardResponse(
            backlog=board["backlog"],
            in_progress=board["in_progress"],
            in_qa=board["in_qa"],
            completed=board["completed"],
            total=len(tasks)
        )

    except Exception as e:
        logger.error(f"Failed to get task board: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve board")


@router.post("/{project_id}/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    request: Request,
    project_id: str,
    task_data: TaskCreate,
    db: Session = Depends(get_db)
):
    """Create a new task"""
    user_id = await get_current_user_id(request, db)

    # Verify project access
    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        # Get next task number
        task_number = project.next_task_number
        project.next_task_number = task_number + 1

        task = TaskItem(
            project_id=project_id,
            user_id=user_id,
            task_number=task_number,
            title=task_data.title,
            description=task_data.description,
            task_type=task_data.task_type,
            priority=task_data.priority,
            tags=task_data.tags,
            status="backlog",
            sort_order=0
        )

        db.add(task)
        db.commit()
        db.refresh(task)

        logger.info(f"Created task: {project.prefix}-{task_number} - {task.title}")
        return task_to_response(task)

    except Exception as e:
        logger.error(f"Failed to create task: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create task")


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    request: Request,
    task_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific task by ID"""
    user_id = await get_current_user_id(request, db)

    task = db.query(TaskItem).filter(
        TaskItem.id == task_id,
        TaskItem.user_id == user_id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task_to_response(task)


@router.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    request: Request,
    task_id: str,
    task_data: TaskUpdate,
    db: Session = Depends(get_db)
):
    """Update a task"""
    user_id = await get_current_user_id(request, db)

    task = db.query(TaskItem).filter(
        TaskItem.id == task_id,
        TaskItem.user_id == user_id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        if task_data.title is not None:
            task.title = task_data.title
        if task_data.description is not None:
            task.description = task_data.description
        if task_data.task_type is not None:
            task.task_type = task_data.task_type
        if task_data.status is not None:
            old_status = task.status
            task.status = task_data.status
            # Set completed_at if moving to completed
            if task_data.status == "completed" and old_status != "completed":
                task.completed_at = datetime.utcnow()
            elif task_data.status != "completed":
                task.completed_at = None
        if task_data.priority is not None:
            task.priority = task_data.priority
        if task_data.tags is not None:
            task.tags = task_data.tags
        if task_data.sort_order is not None:
            task.sort_order = task_data.sort_order

        db.commit()
        db.refresh(task)

        return task_to_response(task)

    except Exception as e:
        logger.error(f"Failed to update task: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update task")


@router.patch("/tasks/{task_id}/status", response_model=TaskResponse)
async def update_task_status(
    request: Request,
    task_id: str,
    status: str = Query(..., description="New status"),
    db: Session = Depends(get_db)
):
    """Quick status change for a task"""
    user_id = await get_current_user_id(request, db)

    task = db.query(TaskItem).filter(
        TaskItem.id == task_id,
        TaskItem.user_id == user_id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    valid_statuses = ["backlog", "in_progress", "in_qa", "completed"]
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )

    try:
        old_status = task.status
        task.status = status

        if status == "completed" and old_status != "completed":
            task.completed_at = datetime.utcnow()
        elif status != "completed":
            task.completed_at = None

        db.commit()
        db.refresh(task)

        return task_to_response(task)

    except Exception as e:
        logger.error(f"Failed to update task status: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update status")


@router.delete("/tasks/{task_id}")
async def delete_task(
    request: Request,
    task_id: str,
    hard_delete: bool = Query(False, description="Permanently delete"),
    db: Session = Depends(get_db)
):
    """Delete a task (soft delete by default)"""
    user_id = await get_current_user_id(request, db)

    task = db.query(TaskItem).filter(
        TaskItem.id == task_id,
        TaskItem.user_id == user_id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        if hard_delete:
            db.delete(task)
        else:
            task.is_deleted = True

        db.commit()

        return {"message": "Task deleted successfully"}

    except Exception as e:
        logger.error(f"Failed to delete task: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete task")


@router.get("/tasks/{task_id}/commits", response_model=CommitListResponse)
async def get_task_commits(
    request: Request,
    task_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get commits linked to a task"""
    user_id = await get_current_user_id(request, db)

    task = db.query(TaskItem).filter(
        TaskItem.id == task_id,
        TaskItem.user_id == user_id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        # Get linked commits
        query = db.query(GitCommit).join(TaskCommitLink).filter(
            TaskCommitLink.task_id == task_id
        ).order_by(GitCommit.committed_at.desc())

        total = query.count()
        offset = (page - 1) * per_page
        commits = query.offset(offset).limit(per_page).all()

        return CommitListResponse(
            commits=[
                CommitResponse(
                    id=c.id,
                    sha=c.sha,
                    short_sha=c.sha[:7],
                    message=c.message,
                    author_name=c.author_name,
                    author_email=c.author_email,
                    committed_at=c.committed_at.isoformat() if c.committed_at else "",
                    branch=c.branch,
                    additions=c.additions,
                    deletions=c.deletions,
                    linked_tasks=[task.tag]
                )
                for c in commits
            ],
            total=total,
            page=page,
            per_page=per_page
        )

    except Exception as e:
        logger.error(f"Failed to get task commits: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve commits")


# ============================================================================
# COMMIT ENDPOINTS
# ============================================================================

@router.get("/{project_id}/commits", response_model=CommitListResponse)
async def list_commits(
    request: Request,
    project_id: str,
    branch: Optional[str] = Query(None, description="Filter by branch"),
    unlinked_only: bool = Query(False, description="Only unlinked commits"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """List commits for a project"""
    user_id = await get_current_user_id(request, db)

    # Verify project access
    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        query = db.query(GitCommit).filter(GitCommit.project_id == project_id)

        if branch:
            query = query.filter(GitCommit.branch == branch)

        if unlinked_only:
            # Get commits without any task links
            linked_commit_ids = db.query(TaskCommitLink.commit_id).distinct()
            query = query.filter(~GitCommit.id.in_(linked_commit_ids))

        total = query.count()
        offset = (page - 1) * per_page
        commits = query.order_by(GitCommit.committed_at.desc()).offset(offset).limit(per_page).all()

        # Build response with linked task info
        commit_responses = []
        for commit in commits:
            linked_task_tags = []
            for link in commit.task_links:
                if link.task and link.task.project:
                    linked_task_tags.append(f"{link.task.project.prefix}-{link.task.task_number}")

            commit_responses.append(CommitResponse(
                id=commit.id,
                sha=commit.sha,
                short_sha=commit.sha[:7],
                message=commit.message,
                author_name=commit.author_name,
                author_email=commit.author_email,
                committed_at=commit.committed_at.isoformat() if commit.committed_at else "",
                branch=commit.branch,
                additions=commit.additions,
                deletions=commit.deletions,
                linked_tasks=linked_task_tags
            ))

        return CommitListResponse(
            commits=commit_responses,
            total=total,
            page=page,
            per_page=per_page
        )

    except Exception as e:
        logger.error(f"Failed to list commits: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve commits")


@router.post("/commits/{commit_id}/link", response_model=CommitResponse)
async def link_commit_to_task(
    request: Request,
    commit_id: str,
    link_data: CommitLinkRequest,
    db: Session = Depends(get_db)
):
    """Manually link a commit to a task"""
    user_id = await get_current_user_id(request, db)

    # Get the commit and verify access through project
    commit = db.query(GitCommit).filter(GitCommit.id == commit_id).first()
    if not commit:
        raise HTTPException(status_code=404, detail="Commit not found")

    project = db.query(DevProject).filter(
        DevProject.id == commit.project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get the task and verify it belongs to user
    task = db.query(TaskItem).filter(
        TaskItem.id == link_data.task_id,
        TaskItem.user_id == user_id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        # Check if link already exists
        existing = db.query(TaskCommitLink).filter(
            TaskCommitLink.task_id == link_data.task_id,
            TaskCommitLink.commit_id == commit_id
        ).first()

        if existing:
            raise HTTPException(status_code=400, detail="Link already exists")

        # Create manual link
        link = TaskCommitLink(
            task_id=link_data.task_id,
            commit_id=commit_id,
            auto_linked=False
        )

        db.add(link)
        db.commit()
        db.refresh(commit)

        # Build response
        linked_task_tags = []
        for link in commit.task_links:
            if link.task and link.task.project:
                linked_task_tags.append(f"{link.task.project.prefix}-{link.task.task_number}")

        return CommitResponse(
            id=commit.id,
            sha=commit.sha,
            short_sha=commit.sha[:7],
            message=commit.message,
            author_name=commit.author_name,
            author_email=commit.author_email,
            committed_at=commit.committed_at.isoformat() if commit.committed_at else "",
            branch=commit.branch,
            additions=commit.additions,
            deletions=commit.deletions,
            linked_tasks=linked_task_tags
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to link commit: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to link commit")


# ============================================================================
# ACTIVITY FEED
# ============================================================================

@router.get("/{project_id}/activity", response_model=ActivityFeed)
async def get_activity_feed(
    request: Request,
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Get recent activity feed for a project"""
    user_id = await get_current_user_id(request, db)

    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        activities = []

        # Recent commits
        commits = db.query(GitCommit).filter(
            GitCommit.project_id == project_id
        ).order_by(GitCommit.committed_at.desc()).limit(limit // 2).all()

        for commit in commits:
            linked_tags = []
            for link in commit.task_links:
                if link.task and link.task.project:
                    linked_tags.append(f"{link.task.project.prefix}-{link.task.task_number}")

            activities.append(ActivityItem(
                id=commit.id,
                type="commit",
                title=f"Commit {commit.sha[:7]}",
                description=commit.message[:100],
                timestamp=commit.committed_at.isoformat() if commit.committed_at else "",
                metadata={
                    "sha": commit.sha,
                    "branch": commit.branch,
                    "author": commit.author_name,
                    "linked_tasks": linked_tags
                }
            ))

        # Recently completed tasks
        completed_tasks = db.query(TaskItem).filter(
            TaskItem.project_id == project_id,
            TaskItem.status == "completed",
            TaskItem.completed_at.isnot(None)
        ).order_by(TaskItem.completed_at.desc()).limit(limit // 4).all()

        for task in completed_tasks:
            activities.append(ActivityItem(
                id=task.id,
                type="task_completed",
                title=f"{project.prefix}-{task.task_number} completed",
                description=task.title,
                timestamp=task.completed_at.isoformat() if task.completed_at else "",
                metadata={
                    "task_id": task.id,
                    "task_type": task.task_type
                }
            ))

        # Recently created tasks
        new_tasks = db.query(TaskItem).filter(
            TaskItem.project_id == project_id,
            TaskItem.is_deleted == False
        ).order_by(TaskItem.created_at.desc()).limit(limit // 4).all()

        for task in new_tasks:
            activities.append(ActivityItem(
                id=task.id,
                type="task_created",
                title=f"{project.prefix}-{task.task_number} created",
                description=task.title,
                timestamp=task.created_at.isoformat() if task.created_at else "",
                metadata={
                    "task_id": task.id,
                    "task_type": task.task_type,
                    "status": task.status
                }
            ))

        # Sort all activities by timestamp
        activities.sort(key=lambda x: x.timestamp, reverse=True)
        activities = activities[:limit]

        return ActivityFeed(
            items=activities,
            total=len(activities)
        )

    except Exception as e:
        logger.error(f"Failed to get activity feed: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve activity")


# ============================================================================
# GITHUB WEBHOOK
# ============================================================================

@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle GitHub webhooks for commit and PR tracking.
    Requires GITHUB_WEBHOOK_SECRET environment variable.
    """
    webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET")

    # Get the raw body for signature verification
    body = await request.body()

    # Verify signature if secret is configured
    if webhook_secret:
        signature = request.headers.get("X-Hub-Signature-256")
        if not signature:
            raise HTTPException(status_code=401, detail="Missing signature")

        expected = "sha256=" + hmac.new(
            webhook_secret.encode(),
            body,
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        import json
        payload = json.loads(body)
        event_type = request.headers.get("X-GitHub-Event")

        logger.info(f"Received GitHub webhook: {event_type}")

        # Get repository info
        repo = payload.get("repository", {})
        repo_owner = repo.get("owner", {}).get("login")
        repo_name = repo.get("name")

        if not repo_owner or not repo_name:
            logger.warning("Webhook missing repository info")
            return {"status": "ignored", "reason": "missing repository info"}

        # Find matching project
        project = db.query(DevProject).filter(
            DevProject.github_repo_owner == repo_owner,
            DevProject.github_repo_name == repo_name,
            DevProject.is_active == True
        ).first()

        if not project:
            logger.info(f"No matching project for {repo_owner}/{repo_name}")
            return {"status": "ignored", "reason": "no matching project"}

        # Handle different event types
        if event_type == "push":
            return await handle_push_event(payload, project, db)
        elif event_type == "pull_request":
            return await handle_pr_event(payload, project, db)
        elif event_type == "create":
            return await handle_create_event(payload, project, db)
        elif event_type == "delete":
            return await handle_delete_event(payload, project, db)
        else:
            logger.info(f"Unhandled event type: {event_type}")
            return {"status": "ignored", "reason": f"unhandled event: {event_type}"}

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")


async def handle_push_event(payload: dict, project: DevProject, db: Session) -> dict:
    """Process push event - store commits and link to tasks"""
    commits_data = payload.get("commits", [])
    ref = payload.get("ref", "")
    branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref

    processed = 0
    linked = 0

    for commit_data in commits_data:
        sha = commit_data.get("id")

        # Check if commit already exists
        existing = db.query(GitCommit).filter(
            GitCommit.project_id == project.id,
            GitCommit.sha == sha
        ).first()

        if existing:
            continue

        # Create commit record
        commit = GitCommit(
            project_id=project.id,
            sha=sha,
            message=commit_data.get("message", ""),
            author_name=commit_data.get("author", {}).get("name"),
            author_email=commit_data.get("author", {}).get("email"),
            committed_at=datetime.fromisoformat(
                commit_data.get("timestamp", "").replace("Z", "+00:00")
            ),
            branch=branch,
            files_changed=commit_data.get("added", []) +
                         commit_data.get("modified", []) +
                         commit_data.get("removed", []),
            raw_payload=commit_data
        )

        db.add(commit)
        db.flush()  # Get the ID
        processed += 1

        # Parse task tags from commit message
        message = commit_data.get("message", "")
        task_tags = parse_task_tags(message)
        status_changes = parse_status_keywords(message)

        # Link to tasks
        for prefix, number in task_tags:
            if prefix == project.prefix:
                task = db.query(TaskItem).filter(
                    TaskItem.project_id == project.id,
                    TaskItem.task_number == number
                ).first()

                if task:
                    # Create link
                    link = TaskCommitLink(
                        task_id=task.id,
                        commit_id=commit.id,
                        auto_linked=True
                    )
                    db.add(link)
                    linked += 1

                    # Check for status-change keywords
                    for new_status, tags in status_changes.items():
                        if (prefix, number) in tags:
                            task.status = new_status
                            if new_status == "completed":
                                task.completed_at = datetime.utcnow()
                            logger.info(f"Auto-updated {prefix}-{number} to {new_status}")

        # Update branch last activity
        git_branch = db.query(GitBranch).filter(
            GitBranch.project_id == project.id,
            GitBranch.name == branch
        ).first()

        if git_branch:
            git_branch.last_commit_sha = sha
            git_branch.last_activity_at = commit.committed_at

    db.commit()

    logger.info(f"Processed {processed} commits, linked {linked} to tasks")
    return {
        "status": "success",
        "commits_processed": processed,
        "tasks_linked": linked
    }


async def handle_pr_event(payload: dict, project: DevProject, db: Session) -> dict:
    """Process pull request event"""
    action = payload.get("action")
    pr_data = payload.get("pull_request", {})
    pr_number = pr_data.get("number")

    # Find or create PR record
    pr = db.query(PullRequest).filter(
        PullRequest.project_id == project.id,
        PullRequest.pr_number == pr_number
    ).first()

    if not pr:
        pr = PullRequest(
            project_id=project.id,
            pr_number=pr_number,
            title=pr_data.get("title", ""),
            description=pr_data.get("body"),
            source_branch=pr_data.get("head", {}).get("ref"),
            target_branch=pr_data.get("base", {}).get("ref"),
            author=pr_data.get("user", {}).get("login"),
            opened_at=datetime.fromisoformat(
                pr_data.get("created_at", "").replace("Z", "+00:00")
            ) if pr_data.get("created_at") else None,
            raw_payload=pr_data
        )
        db.add(pr)

    # Update status based on action
    if action in ["opened", "reopened"]:
        pr.status = "open"
    elif action == "closed":
        if pr_data.get("merged"):
            pr.status = "merged"
            pr.merged_at = datetime.fromisoformat(
                pr_data.get("merged_at", "").replace("Z", "+00:00")
            ) if pr_data.get("merged_at") else datetime.utcnow()
        else:
            pr.status = "closed"
            pr.closed_at = datetime.utcnow()

    # Update title/description if changed
    pr.title = pr_data.get("title", pr.title)
    pr.description = pr_data.get("body", pr.description)

    # Link to tasks based on title and description
    text_to_parse = f"{pr.title} {pr.description or ''}"
    task_tags = parse_task_tags(text_to_parse)

    for prefix, number in task_tags:
        if prefix == project.prefix:
            task = db.query(TaskItem).filter(
                TaskItem.project_id == project.id,
                TaskItem.task_number == number
            ).first()

            if task:
                # Check if link exists
                existing_link = db.query(PRTaskLink).filter(
                    PRTaskLink.pr_id == pr.id,
                    PRTaskLink.task_id == task.id
                ).first()

                if not existing_link:
                    link = PRTaskLink(
                        pr_id=pr.id,
                        task_id=task.id,
                        auto_linked=True
                    )
                    db.add(link)

    db.commit()

    logger.info(f"Processed PR #{pr_number} ({action})")
    return {"status": "success", "action": action, "pr_number": pr_number}


async def handle_create_event(payload: dict, project: DevProject, db: Session) -> dict:
    """Process create event (branch/tag created)"""
    ref_type = payload.get("ref_type")
    ref_name = payload.get("ref")

    if ref_type != "branch":
        return {"status": "ignored", "reason": "not a branch"}

    # Check if branch exists
    existing = db.query(GitBranch).filter(
        GitBranch.project_id == project.id,
        GitBranch.name == ref_name
    ).first()

    if existing:
        # Undelete if it was deleted
        existing.is_deleted = False
        existing.is_merged = False
        existing.merged_at = None
    else:
        branch = GitBranch(
            project_id=project.id,
            name=ref_name,
            is_default=ref_name in ["main", "master"]
        )
        db.add(branch)

    db.commit()

    logger.info(f"Created branch: {ref_name}")
    return {"status": "success", "branch": ref_name}


async def handle_delete_event(payload: dict, project: DevProject, db: Session) -> dict:
    """Process delete event (branch/tag deleted)"""
    ref_type = payload.get("ref_type")
    ref_name = payload.get("ref")

    if ref_type != "branch":
        return {"status": "ignored", "reason": "not a branch"}

    branch = db.query(GitBranch).filter(
        GitBranch.project_id == project.id,
        GitBranch.name == ref_name
    ).first()

    if branch:
        branch.is_deleted = True
        db.commit()

    logger.info(f"Deleted branch: {ref_name}")
    return {"status": "success", "branch": ref_name}


# ============================================================================
# QA CHECKLIST ENDPOINTS
# ============================================================================

@router.get("/{project_id}/qa/checklist", response_model=QAChecklistResponse)
async def get_qa_checklist(
    request: Request,
    project_id: str,
    include_inactive: bool = Query(False, description="Include inactive items"),
    db: Session = Depends(get_db)
):
    """Get QA checklist items for a project"""
    user_id = await get_current_user_id(request, db)

    # Verify project access
    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    query = db.query(QAChecklistItem).filter(
        QAChecklistItem.project_id == project_id
    )

    if not include_inactive:
        query = query.filter(QAChecklistItem.is_active == True)

    items = query.order_by(QAChecklistItem.sort_order).all()

    return QAChecklistResponse(
        items=[QAChecklistItemResponse(
            id=item.id,
            label=item.label,
            sort_order=item.sort_order or 0,
            is_active=item.is_active,
            created_at=item.created_at
        ) for item in items],
        total=len(items)
    )


@router.post("/{project_id}/qa/checklist", response_model=QAChecklistItemResponse, status_code=201)
async def create_qa_checklist_item(
    request: Request,
    project_id: str,
    item_data: QAChecklistItemCreate,
    db: Session = Depends(get_db)
):
    """Add a new item to the QA checklist"""
    user_id = await get_current_user_id(request, db)

    # Verify project access
    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get next sort order if not specified
    if item_data.sort_order is None:
        max_order = db.query(func.max(QAChecklistItem.sort_order)).filter(
            QAChecklistItem.project_id == project_id
        ).scalar() or 0
        sort_order = max_order + 1
    else:
        sort_order = item_data.sort_order

    item = QAChecklistItem(
        project_id=project_id,
        user_id=user_id,
        label=item_data.label,
        sort_order=sort_order
    )

    db.add(item)
    db.commit()
    db.refresh(item)

    logger.info(f"Created QA checklist item: {item.label} for project {project.prefix}")

    return QAChecklistItemResponse(
        id=item.id,
        label=item.label,
        sort_order=item.sort_order or 0,
        is_active=item.is_active,
        created_at=item.created_at
    )


@router.put("/{project_id}/qa/checklist/{item_id}", response_model=QAChecklistItemResponse)
async def update_qa_checklist_item(
    request: Request,
    project_id: str,
    item_id: str,
    item_data: QAChecklistItemUpdate,
    db: Session = Depends(get_db)
):
    """Update a QA checklist item"""
    user_id = await get_current_user_id(request, db)

    item = db.query(QAChecklistItem).filter(
        QAChecklistItem.id == item_id,
        QAChecklistItem.project_id == project_id
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="Checklist item not found")

    # Verify ownership
    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if item_data.label is not None:
        item.label = item_data.label
    if item_data.sort_order is not None:
        item.sort_order = item_data.sort_order
    if item_data.is_active is not None:
        item.is_active = item_data.is_active

    db.commit()
    db.refresh(item)

    return QAChecklistItemResponse(
        id=item.id,
        label=item.label,
        sort_order=item.sort_order or 0,
        is_active=item.is_active,
        created_at=item.created_at
    )


@router.delete("/{project_id}/qa/checklist/{item_id}")
async def delete_qa_checklist_item(
    request: Request,
    project_id: str,
    item_id: str,
    db: Session = Depends(get_db)
):
    """Delete (soft-delete) a QA checklist item"""
    user_id = await get_current_user_id(request, db)

    item = db.query(QAChecklistItem).filter(
        QAChecklistItem.id == item_id,
        QAChecklistItem.project_id == project_id
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="Checklist item not found")

    # Verify ownership
    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Soft delete
    item.is_active = False
    db.commit()

    return {"status": "deleted", "id": item_id}


@router.put("/{project_id}/qa/checklist/reorder")
async def reorder_qa_checklist(
    request: Request,
    project_id: str,
    item_ids: List[str],
    db: Session = Depends(get_db)
):
    """Reorder QA checklist items"""
    user_id = await get_current_user_id(request, db)

    # Verify project access
    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Update sort orders
    for index, item_id in enumerate(item_ids):
        db.query(QAChecklistItem).filter(
            QAChecklistItem.id == item_id,
            QAChecklistItem.project_id == project_id
        ).update({"sort_order": index})

    db.commit()

    return {"status": "reordered", "count": len(item_ids)}


# ============================================================================
# QA PENDING / RESULTS ENDPOINTS
# ============================================================================

@router.get("/{project_id}/qa/pending", response_model=QAPendingResponse)
async def get_qa_pending(
    request: Request,
    project_id: str,
    db: Session = Depends(get_db)
):
    """
    Get the latest commit per task for QA.
    Only shows one commit per task (the most recent one), whether it's been QA'd or not.
    """
    user_id = await get_current_user_id(request, db)

    # Verify project access
    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get all commits linked to tasks, with their QA status
    # Ordered by committed_at desc so we can pick the latest per task
    commits_with_tasks = db.query(
        GitCommit,
        TaskItem,
        QACommitResult
    ).join(
        TaskCommitLink, TaskCommitLink.commit_id == GitCommit.id
    ).join(
        TaskItem, TaskItem.id == TaskCommitLink.task_id
    ).outerjoin(
        QACommitResult, QACommitResult.commit_id == GitCommit.id
    ).filter(
        GitCommit.project_id == project_id
    ).order_by(
        TaskItem.task_number,
        GitCommit.committed_at.desc()
    ).all()

    # Group by task, but only keep the latest commit per task
    tasks_dict: Dict[str, QAPendingTask] = {}
    seen_tasks: set = set()
    total_commits = 0

    for commit, task, qa_result in commits_with_tasks:
        # Skip if we've already added a commit for this task (we only want the latest)
        if task.id in seen_tasks:
            continue

        seen_tasks.add(task.id)
        task_tag = f"{project.prefix}-{task.task_number}"

        tasks_dict[task.id] = QAPendingTask(
            task_id=task.id,
            task_tag=task_tag,
            task_title=task.title,
            commits=[QAPendingCommit(
                id=commit.id,
                sha=commit.sha,
                message=commit.message,
                author_name=commit.author_name,
                committed_at=commit.committed_at,
                qa_status=qa_result.status if qa_result else None
            )]
        )
        total_commits += 1

    return QAPendingResponse(
        tasks=list(tasks_dict.values()),
        total_commits=total_commits
    )


@router.post("/commits/{commit_id}/qa", response_model=QAResultResponse)
async def save_qa_result(
    request: Request,
    commit_id: str,
    result_data: QAResultCreate,
    db: Session = Depends(get_db)
):
    """Save QA result for a commit"""
    user_id = await get_current_user_id(request, db)

    # Get the commit
    commit = db.query(GitCommit).filter(GitCommit.id == commit_id).first()
    if not commit:
        raise HTTPException(status_code=404, detail="Commit not found")

    # Verify project access
    project = db.query(DevProject).filter(
        DevProject.id == commit.project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate status
    if result_data.status not in ['passed', 'failed', 'skipped']:
        raise HTTPException(status_code=400, detail="Invalid status. Must be: passed, failed, skipped")

    # Check if result already exists
    existing = db.query(QACommitResult).filter(
        QACommitResult.commit_id == commit_id
    ).first()

    if existing:
        # Update existing
        existing.checked_items = result_data.checked_items
        existing.notes = result_data.notes
        existing.status = result_data.status
        existing.tested_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        result = existing
    else:
        # Create new
        result = QACommitResult(
            commit_id=commit_id,
            project_id=commit.project_id,
            user_id=user_id,
            checked_items=result_data.checked_items,
            notes=result_data.notes,
            status=result_data.status,
            tested_at=datetime.utcnow()
        )
        db.add(result)
        db.commit()
        db.refresh(result)

    logger.info(f"Saved QA result for commit {commit.sha[:7]}: {result_data.status}")

    return QAResultResponse(
        id=result.id,
        commit_id=result.commit_id,
        checked_items=result.checked_items or [],
        notes=result.notes,
        status=result.status,
        tested_at=result.tested_at,
        created_at=result.created_at
    )


@router.get("/commits/{commit_id}/qa", response_model=Optional[QAResultResponse])
async def get_qa_result(
    request: Request,
    commit_id: str,
    db: Session = Depends(get_db)
):
    """Get QA result for a commit"""
    user_id = await get_current_user_id(request, db)

    # Get the commit
    commit = db.query(GitCommit).filter(GitCommit.id == commit_id).first()
    if not commit:
        raise HTTPException(status_code=404, detail="Commit not found")

    # Verify project access
    project = db.query(DevProject).filter(
        DevProject.id == commit.project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    result = db.query(QACommitResult).filter(
        QACommitResult.commit_id == commit_id
    ).first()

    if not result:
        return None

    return QAResultResponse(
        id=result.id,
        commit_id=result.commit_id,
        checked_items=result.checked_items or [],
        notes=result.notes,
        status=result.status,
        tested_at=result.tested_at,
        created_at=result.created_at
    )


# ============================================================================
# PROJECT FILES ENDPOINTS
# ============================================================================

def get_minio_client():
    """Get MinIO client instance"""
    from minio import Minio
    from app.core.config import settings

    return Minio(
        settings.minio_url.replace("http://", "").replace("https://", ""),
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False
    )


def get_folder_breadcrumb(folder: ProjectFolder, db: Session) -> List[FolderResponse]:
    """Build breadcrumb path for a folder"""
    breadcrumb = []
    current = folder
    while current:
        breadcrumb.insert(0, FolderResponse(
            id=current.id,
            name=current.name,
            parent_id=current.parent_id,
            created_at=current.created_at,
            updated_at=current.updated_at
        ))
        if current.parent_id:
            current = db.query(ProjectFolder).filter(
                ProjectFolder.id == current.parent_id
            ).first()
        else:
            current = None
    return breadcrumb


def file_to_response(file: ProjectFile) -> FileResponse:
    """Convert ProjectFile to FileResponse"""
    return FileResponse(
        id=file.id,
        filename=file.filename,
        folder_id=file.folder_id,
        mime_type=file.mime_type,
        file_size=file.file_size,
        file_size_formatted=file.file_size_formatted,
        description=file.description,
        created_at=file.created_at,
        updated_at=file.updated_at
    )


def folder_to_response(folder: ProjectFolder) -> FolderResponse:
    """Convert ProjectFolder to FolderResponse"""
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        created_at=folder.created_at,
        updated_at=folder.updated_at
    )


# --- Folder Endpoints ---

@router.get("/{project_id}/files/folders", response_model=FolderTreeResponse)
async def list_folders(
    request: Request,
    project_id: str,
    db: Session = Depends(get_db)
):
    """Get all folders for a project as a tree structure"""
    user_id = await get_current_user_id(request, db)

    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get all folders
    folders = db.query(ProjectFolder).filter(
        ProjectFolder.project_id == project_id
    ).order_by(ProjectFolder.name).all()

    # Build tree structure
    folder_dict = {f.id: FolderTreeItem(id=f.id, name=f.name, parent_id=f.parent_id, children=[]) for f in folders}
    tree = []

    for folder in folders:
        if folder.parent_id and folder.parent_id in folder_dict:
            folder_dict[folder.parent_id].children.append(folder_dict[folder.id])
        elif folder.parent_id is None:
            tree.append(folder_dict[folder.id])

    return FolderTreeResponse(tree=tree, total=len(folders))


@router.post("/{project_id}/files/folders", response_model=FolderResponse, status_code=201)
async def create_folder(
    request: Request,
    project_id: str,
    folder_data: FolderCreate,
    db: Session = Depends(get_db)
):
    """Create a new folder"""
    user_id = await get_current_user_id(request, db)

    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate parent folder if specified
    if folder_data.parent_id:
        parent = db.query(ProjectFolder).filter(
            ProjectFolder.id == folder_data.parent_id,
            ProjectFolder.project_id == project_id
        ).first()
        if not parent:
            raise HTTPException(status_code=400, detail="Parent folder not found")

    # Check for duplicate name in same parent
    existing = db.query(ProjectFolder).filter(
        ProjectFolder.project_id == project_id,
        ProjectFolder.parent_id == folder_data.parent_id,
        ProjectFolder.name == folder_data.name
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Folder with this name already exists")

    folder = ProjectFolder(
        project_id=project_id,
        user_id=user_id,
        name=folder_data.name,
        parent_id=folder_data.parent_id
    )

    db.add(folder)
    db.commit()
    db.refresh(folder)

    logger.info(f"Created folder: {folder.name} in project {project.prefix}")
    return folder_to_response(folder)


@router.put("/{project_id}/files/folders/{folder_id}", response_model=FolderResponse)
async def update_folder(
    request: Request,
    project_id: str,
    folder_id: str,
    folder_data: FolderUpdate,
    db: Session = Depends(get_db)
):
    """Update folder (rename or move)"""
    user_id = await get_current_user_id(request, db)

    folder = db.query(ProjectFolder).filter(
        ProjectFolder.id == folder_id,
        ProjectFolder.project_id == project_id
    ).first()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Verify project access
    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if folder_data.name is not None:
        # Check for duplicate name in same parent
        existing = db.query(ProjectFolder).filter(
            ProjectFolder.project_id == project_id,
            ProjectFolder.parent_id == folder.parent_id,
            ProjectFolder.name == folder_data.name,
            ProjectFolder.id != folder_id
        ).first()

        if existing:
            raise HTTPException(status_code=400, detail="Folder with this name already exists")

        folder.name = folder_data.name

    if folder_data.parent_id is not None:
        # Prevent moving to itself or its children
        if folder_data.parent_id == folder_id:
            raise HTTPException(status_code=400, detail="Cannot move folder into itself")

        # Validate new parent exists
        if folder_data.parent_id:
            new_parent = db.query(ProjectFolder).filter(
                ProjectFolder.id == folder_data.parent_id,
                ProjectFolder.project_id == project_id
            ).first()
            if not new_parent:
                raise HTTPException(status_code=400, detail="Target folder not found")

        folder.parent_id = folder_data.parent_id if folder_data.parent_id else None

    db.commit()
    db.refresh(folder)

    return folder_to_response(folder)


@router.delete("/{project_id}/files/folders/{folder_id}")
async def delete_folder(
    request: Request,
    project_id: str,
    folder_id: str,
    db: Session = Depends(get_db)
):
    """Delete a folder and all its contents"""
    user_id = await get_current_user_id(request, db)

    folder = db.query(ProjectFolder).filter(
        ProjectFolder.id == folder_id,
        ProjectFolder.project_id == project_id
    ).first()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Verify project access
    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        # Delete files in this folder from MinIO
        from app.core.config import settings
        minio_client = get_minio_client()

        files_to_delete = db.query(ProjectFile).filter(
            ProjectFile.folder_id == folder_id
        ).all()

        for file in files_to_delete:
            try:
                minio_client.remove_object(settings.minio_bucket, file.storage_key)
            except Exception as e:
                logger.warning(f"Failed to delete file from MinIO: {file.storage_key} - {e}")

        # Cascade will delete files and subfolders from DB
        db.delete(folder)
        db.commit()

        return {"status": "deleted", "folder_id": folder_id}

    except Exception as e:
        logger.error(f"Failed to delete folder: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete folder")


# --- File Endpoints ---

@router.get("/{project_id}/files", response_model=FileListResponse)
async def list_files(
    request: Request,
    project_id: str,
    folder_id: Optional[str] = Query(None, description="Folder ID (null for root)"),
    db: Session = Depends(get_db)
):
    """List files and subfolders in a folder"""
    user_id = await get_current_user_id(request, db)

    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get current folder and breadcrumb
    breadcrumb = []
    if folder_id:
        current_folder = db.query(ProjectFolder).filter(
            ProjectFolder.id == folder_id,
            ProjectFolder.project_id == project_id
        ).first()
        if not current_folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        breadcrumb = get_folder_breadcrumb(current_folder, db)

    # Get subfolders
    subfolders = db.query(ProjectFolder).filter(
        ProjectFolder.project_id == project_id,
        ProjectFolder.parent_id == folder_id
    ).order_by(ProjectFolder.name).all()

    # Get files in this folder
    files = db.query(ProjectFile).filter(
        ProjectFile.project_id == project_id,
        ProjectFile.folder_id == folder_id
    ).order_by(ProjectFile.filename).all()

    return FileListResponse(
        files=[file_to_response(f) for f in files],
        folders=[folder_to_response(f) for f in subfolders],
        total_files=len(files),
        total_folders=len(subfolders),
        current_folder_id=folder_id,
        breadcrumb=breadcrumb
    )


@router.post("/{project_id}/files/upload", response_model=FileResponse)
async def upload_file(
    request: Request,
    project_id: str,
    file: UploadFile = File(...),
    folder_id: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Upload a file to the project"""
    user_id = await get_current_user_id(request, db)

    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate folder if specified
    if folder_id:
        folder = db.query(ProjectFolder).filter(
            ProjectFolder.id == folder_id,
            ProjectFolder.project_id == project_id
        ).first()
        if not folder:
            raise HTTPException(status_code=400, detail="Folder not found")

    try:
        from app.core.config import settings
        minio_client = get_minio_client()

        # Ensure bucket exists
        if not minio_client.bucket_exists(settings.minio_bucket):
            minio_client.make_bucket(settings.minio_bucket)

        # Read file content
        content = await file.read()
        file_size = len(content)

        # Generate unique storage key
        file_uuid = str(uuid.uuid4())
        # Clean filename for storage
        safe_filename = file.filename.replace("/", "_").replace("\\", "_")
        storage_key = f"projects/{project_id}/{file_uuid}_{safe_filename}"

        # Determine MIME type
        mime_type = file.content_type
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(file.filename)

        # Upload to MinIO
        minio_client.put_object(
            settings.minio_bucket,
            storage_key,
            BytesIO(content),
            length=file_size,
            content_type=mime_type
        )

        # Create database record
        db_file = ProjectFile(
            project_id=project_id,
            user_id=user_id,
            folder_id=folder_id,
            filename=file.filename,
            storage_key=storage_key,
            mime_type=mime_type,
            file_size=file_size,
            description=description
        )

        db.add(db_file)
        db.commit()
        db.refresh(db_file)

        logger.info(f"Uploaded file: {file.filename} to project {project.prefix}")
        return file_to_response(db_file)

    except Exception as e:
        logger.error(f"Failed to upload file: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")


@router.put("/{project_id}/files/{file_id}", response_model=FileResponse)
async def update_file(
    request: Request,
    project_id: str,
    file_id: str,
    file_data: FileUpdate,
    db: Session = Depends(get_db)
):
    """Update file metadata or move file"""
    user_id = await get_current_user_id(request, db)

    file = db.query(ProjectFile).filter(
        ProjectFile.id == file_id,
        ProjectFile.project_id == project_id
    ).first()

    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    # Verify project access
    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if file_data.filename is not None:
        file.filename = file_data.filename

    if file_data.folder_id is not None:
        # Validate new folder
        if file_data.folder_id:
            new_folder = db.query(ProjectFolder).filter(
                ProjectFolder.id == file_data.folder_id,
                ProjectFolder.project_id == project_id
            ).first()
            if not new_folder:
                raise HTTPException(status_code=400, detail="Target folder not found")
        file.folder_id = file_data.folder_id if file_data.folder_id else None

    if file_data.description is not None:
        file.description = file_data.description

    db.commit()
    db.refresh(file)

    return file_to_response(file)


@router.delete("/{project_id}/files/{file_id}")
async def delete_file(
    request: Request,
    project_id: str,
    file_id: str,
    db: Session = Depends(get_db)
):
    """Delete a file"""
    user_id = await get_current_user_id(request, db)

    file = db.query(ProjectFile).filter(
        ProjectFile.id == file_id,
        ProjectFile.project_id == project_id
    ).first()

    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    # Verify project access
    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        from app.core.config import settings
        minio_client = get_minio_client()

        # Delete from MinIO
        try:
            minio_client.remove_object(settings.minio_bucket, file.storage_key)
        except Exception as e:
            logger.warning(f"Failed to delete file from MinIO: {file.storage_key} - {e}")

        # Delete from database
        db.delete(file)
        db.commit()

        return {"status": "deleted", "file_id": file_id}

    except Exception as e:
        logger.error(f"Failed to delete file: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete file")


@router.get("/{project_id}/files/{file_id}/download")
async def download_file(
    request: Request,
    project_id: str,
    file_id: str,
    db: Session = Depends(get_db)
):
    """Download a file"""
    user_id = await get_current_user_id(request, db)

    file = db.query(ProjectFile).filter(
        ProjectFile.id == file_id,
        ProjectFile.project_id == project_id
    ).first()

    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    # Verify project access
    project = db.query(DevProject).filter(
        DevProject.id == project_id,
        DevProject.user_id == user_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        from app.core.config import settings
        minio_client = get_minio_client()

        # Get file from MinIO
        response = minio_client.get_object(settings.minio_bucket, file.storage_key)
        content = response.read()
        response.close()
        response.release_conn()

        return StreamingResponse(
            BytesIO(content),
            media_type=file.mime_type or "application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{file.filename}"'
            }
        )

    except Exception as e:
        logger.error(f"Failed to download file: {e}")
        raise HTTPException(status_code=500, detail="Failed to download file")
