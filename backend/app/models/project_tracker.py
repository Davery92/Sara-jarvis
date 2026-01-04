"""
Project Development Tracker Models

Models for tracking software development projects with GitHub integration,
task management, commit history, and branch/PR tracking.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import enum
import uuid


class TaskType(str, enum.Enum):
    """Type of task/work item"""
    FEATURE = "feature"
    BUG = "bug"
    TASK = "task"
    CHORE = "chore"


class TaskStatus(str, enum.Enum):
    """Kanban column status"""
    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    IN_QA = "in_qa"
    COMPLETED = "completed"


class TaskPriority(str, enum.Enum):
    """Task priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PRStatus(str, enum.Enum):
    """Pull request status"""
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


class DevProject(Base):
    """
    Software development project with GitHub integration.
    Each project has its own task board, commit history, and branch tracking.
    """
    __tablename__ = "dev_project"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    prefix = Column(String(10), nullable=False)  # e.g., "RN", "SARA" for task tags
    description = Column(Text, nullable=True)
    tech_stack = Column(String(500), nullable=True)
    business_context = Column(String(500), nullable=True)

    # GitHub integration
    github_repo_owner = Column(String(255), nullable=True)
    github_repo_name = Column(String(255), nullable=True)
    github_installation_id = Column(String(255), nullable=True)

    # Status
    is_active = Column(Boolean, nullable=False, default=True)

    # Counter for task numbering (auto-incremented per project)
    next_task_number = Column(Integer, nullable=False, default=1)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    tasks = relationship("TaskItem", back_populates="project", cascade="all, delete-orphan")
    commits = relationship("GitCommit", back_populates="project", cascade="all, delete-orphan")
    branches = relationship("GitBranch", back_populates="project", cascade="all, delete-orphan")
    pull_requests = relationship("PullRequest", back_populates="project", cascade="all, delete-orphan")
    qa_checklist_items = relationship("QAChecklistItem", back_populates="project", cascade="all, delete-orphan")
    qa_results = relationship("QACommitResult", back_populates="project", cascade="all, delete-orphan")
    folders = relationship("ProjectFolder", back_populates="project", cascade="all, delete-orphan")
    files = relationship("ProjectFile", back_populates="project", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<DevProject(id={self.id}, name='{self.name}', prefix='{self.prefix}')>"

    @property
    def github_repo_url(self) -> str | None:
        """Get the GitHub repository URL if configured"""
        if self.github_repo_owner and self.github_repo_name:
            return f"https://github.com/{self.github_repo_owner}/{self.github_repo_name}"
        return None

    def get_next_task_number(self) -> int:
        """Get and increment the next task number"""
        current = self.next_task_number
        self.next_task_number = current + 1
        return current


class TaskItem(Base):
    """
    Individual task/work item within a project.
    Uses Kanban-style status workflow: backlog -> in_progress -> in_qa -> completed
    """
    __tablename__ = "task_item"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("dev_project.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    task_number = Column(Integer, nullable=False)  # Auto-incremented per project
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)

    # Type and status
    task_type = Column(String(20), nullable=False, default="task")
    status = Column(String(20), nullable=False, default="backlog")
    priority = Column(String(20), nullable=True)

    # Tags for categorization
    tags = Column(ARRAY(String), nullable=True)

    # Ordering within status column
    sort_order = Column(Integer, nullable=False, default=0)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Soft delete
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships
    project = relationship("DevProject", back_populates="tasks")
    commit_links = relationship("TaskCommitLink", back_populates="task", cascade="all, delete-orphan")
    pr_links = relationship("PRTaskLink", back_populates="task", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<TaskItem(id={self.id}, number={self.task_number}, title='{self.title[:30]}')>"

    @property
    def tag(self) -> str:
        """Get the task tag (e.g., 'RN-42')"""
        if self.project:
            return f"{self.project.prefix}-{self.task_number}"
        return f"TASK-{self.task_number}"

    @property
    def linked_commits(self):
        """Get all commits linked to this task"""
        return [link.commit for link in self.commit_links]


class GitCommit(Base):
    """
    Git commit record from GitHub webhooks.
    Automatically linked to tasks based on commit message parsing.
    """
    __tablename__ = "git_commit"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("dev_project.id", ondelete="CASCADE"), nullable=False)
    sha = Column(String(40), nullable=False)
    message = Column(Text, nullable=False)
    author_name = Column(String(255), nullable=True)
    author_email = Column(String(255), nullable=True)
    committed_at = Column(DateTime(timezone=True), nullable=False)
    branch = Column(String(255), nullable=True)

    # File changes
    files_changed = Column(JSONB, nullable=True)  # Array of filenames
    additions = Column(Integer, nullable=True)
    deletions = Column(Integer, nullable=True)

    # Raw webhook payload for reference
    raw_payload = Column(JSONB, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("DevProject", back_populates="commits")
    task_links = relationship("TaskCommitLink", back_populates="commit", cascade="all, delete-orphan")
    qa_result = relationship("QACommitResult", back_populates="commit", uselist=False)

    def __repr__(self):
        return f"<GitCommit(sha={self.sha[:8]}, message='{self.message[:30]}')>"

    @property
    def short_sha(self) -> str:
        """Get the short SHA (first 7 characters)"""
        return self.sha[:7]

    @property
    def linked_tasks(self):
        """Get all tasks linked to this commit"""
        return [link.task for link in self.task_links]


class TaskCommitLink(Base):
    """
    Many-to-many link between tasks and commits.
    Tracks whether the link was auto-generated or manually created.
    """
    __tablename__ = "task_commit_link"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, ForeignKey("task_item.id", ondelete="CASCADE"), nullable=False)
    commit_id = Column(String, ForeignKey("git_commit.id", ondelete="CASCADE"), nullable=False)
    auto_linked = Column(Boolean, nullable=False, default=True)  # vs manual linking
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    task = relationship("TaskItem", back_populates="commit_links")
    commit = relationship("GitCommit", back_populates="task_links")

    def __repr__(self):
        return f"<TaskCommitLink(task={self.task_id}, commit={self.commit_id})>"


class GitBranch(Base):
    """
    Git branch tracking from GitHub webhooks.
    """
    __tablename__ = "git_branch"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("dev_project.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    last_commit_sha = Column(String(40), nullable=True)
    last_activity_at = Column(DateTime(timezone=True), nullable=True)
    is_default = Column(Boolean, nullable=False, default=False)
    is_merged = Column(Boolean, nullable=False, default=False)
    merged_at = Column(DateTime(timezone=True), nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    project = relationship("DevProject", back_populates="branches")

    def __repr__(self):
        return f"<GitBranch(name='{self.name}', project={self.project_id})>"


class PullRequest(Base):
    """
    Pull request tracking from GitHub webhooks.
    """
    __tablename__ = "pull_request"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("dev_project.id", ondelete="CASCADE"), nullable=False)
    pr_number = Column(Integer, nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)

    # Status: open, closed, merged
    status = Column(String(20), nullable=False, default="open")

    # Branches
    source_branch = Column(String(255), nullable=True)
    target_branch = Column(String(255), nullable=True)

    # Author
    author = Column(String(255), nullable=True)

    # Timestamps
    opened_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    merged_at = Column(DateTime(timezone=True), nullable=True)

    # Raw webhook payload
    raw_payload = Column(JSONB, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    project = relationship("DevProject", back_populates="pull_requests")
    task_links = relationship("PRTaskLink", back_populates="pull_request", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<PullRequest(#{self.pr_number}, title='{self.title[:30]}')>"

    @property
    def linked_tasks(self):
        """Get all tasks linked to this PR"""
        return [link.task for link in self.task_links]


class PRTaskLink(Base):
    """
    Many-to-many link between pull requests and tasks.
    """
    __tablename__ = "pr_task_link"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pr_id = Column(String, ForeignKey("pull_request.id", ondelete="CASCADE"), nullable=False)
    task_id = Column(String, ForeignKey("task_item.id", ondelete="CASCADE"), nullable=False)
    auto_linked = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    pull_request = relationship("PullRequest", back_populates="task_links")
    task = relationship("TaskItem", back_populates="pr_links")

    def __repr__(self):
        return f"<PRTaskLink(pr={self.pr_id}, task={self.task_id})>"


# ============================================================================
# QA CHECKLIST MODELS
# ============================================================================

class QAChecklistItem(Base):
    """
    Per-project QA checklist items.
    These are the test items that users configure for each project.
    """
    __tablename__ = "qa_checklist_item"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("dev_project.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    label = Column(String(255), nullable=False)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("DevProject", back_populates="qa_checklist_items")

    def __repr__(self):
        return f"<QAChecklistItem(label='{self.label}')>"


class QACommitResult(Base):
    """
    Stores QA results for each commit.
    Records which checklist items were checked, any notes, and the overall status.
    """
    __tablename__ = "qa_commit_result"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    commit_id = Column(String, ForeignKey("git_commit.id", ondelete="CASCADE"), nullable=False, unique=True)
    project_id = Column(String, ForeignKey("dev_project.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    checked_items = Column(JSONB, default=list)  # List of checked item IDs
    notes = Column(Text, nullable=True)
    status = Column(String(20), default='pending')  # pending, passed, failed, skipped
    tested_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("DevProject", back_populates="qa_results")
    commit = relationship("GitCommit", back_populates="qa_result")

    def __repr__(self):
        return f"<QACommitResult(commit={self.commit_id[:8]}, status='{self.status}')>"

    @property
    def checklist_completion(self):
        """Calculate completion percentage if we have total items"""
        return len(self.checked_items) if self.checked_items else 0


# ============================================================================
# PROJECT FILES MODELS
# ============================================================================

class ProjectFolder(Base):
    """
    Folder structure for organizing project files.
    Supports nested hierarchy via parent_id self-reference.
    """
    __tablename__ = "project_folder"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("dev_project.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    parent_id = Column(String, ForeignKey("project_folder.id", ondelete="CASCADE"), nullable=True)  # null = root

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    project = relationship("DevProject", back_populates="folders")
    parent = relationship("ProjectFolder", remote_side=[id], backref="children")
    files = relationship("ProjectFile", back_populates="folder", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ProjectFolder(name='{self.name}', project={self.project_id})>"

    @property
    def path(self) -> str:
        """Get the full path of this folder (e.g., 'specs/v1')"""
        if self.parent:
            return f"{self.parent.path}/{self.name}"
        return self.name


class ProjectFile(Base):
    """
    File metadata stored in database with actual file content in MinIO.
    """
    __tablename__ = "project_file"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("dev_project.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    folder_id = Column(String, ForeignKey("project_folder.id", ondelete="SET NULL"), nullable=True)  # null = root
    filename = Column(String(500), nullable=False)  # Original filename
    storage_key = Column(String(1000), nullable=False, unique=True)  # MinIO object key
    mime_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=False)  # Size in bytes
    description = Column(Text, nullable=True)  # Optional description

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    project = relationship("DevProject", back_populates="files")
    folder = relationship("ProjectFolder", back_populates="files")

    def __repr__(self):
        return f"<ProjectFile(filename='{self.filename}', project={self.project_id})>"

    @property
    def file_size_formatted(self) -> str:
        """Get human-readable file size"""
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
