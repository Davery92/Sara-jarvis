"""
Project Tracker Service

Provides business logic and conversation integration for project tracking.
Used by Sara to answer questions about projects, tasks, and development activity.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
import logging

from app.models.project_tracker import (
    DevProject, TaskItem, GitCommit, GitBranch, PullRequest,
    TaskCommitLink, PRTaskLink
)

logger = logging.getLogger(__name__)


class ProjectTrackerService:
    """Service for project tracking operations and conversation integration."""

    def __init__(self, db: Session):
        self.db = db

    # =========================================================================
    # PROJECT QUERIES
    # =========================================================================

    def get_projects_for_user(self, user_id: str, active_only: bool = True) -> List[DevProject]:
        """Get all projects for a user."""
        query = self.db.query(DevProject).filter(DevProject.user_id == user_id)
        if active_only:
            query = query.filter(DevProject.is_active == True)
        return query.order_by(DevProject.name).all()

    def get_project_by_prefix(self, user_id: str, prefix: str) -> Optional[DevProject]:
        """Get a project by its prefix (e.g., 'RN', 'SARA')."""
        return self.db.query(DevProject).filter(
            DevProject.user_id == user_id,
            DevProject.prefix == prefix.upper(),
            DevProject.is_active == True
        ).first()

    def get_project_by_name(self, user_id: str, name: str) -> Optional[DevProject]:
        """Get a project by name (case-insensitive partial match)."""
        return self.db.query(DevProject).filter(
            DevProject.user_id == user_id,
            DevProject.name.ilike(f"%{name}%"),
            DevProject.is_active == True
        ).first()

    # =========================================================================
    # TASK QUERIES
    # =========================================================================

    def get_task_by_tag(self, user_id: str, tag: str) -> Optional[TaskItem]:
        """
        Get a task by its tag (e.g., 'RN-42').
        Returns None if not found or user doesn't own it.
        """
        parts = tag.upper().split('-')
        if len(parts) != 2:
            return None

        prefix, number_str = parts
        try:
            number = int(number_str)
        except ValueError:
            return None

        # Find project by prefix
        project = self.get_project_by_prefix(user_id, prefix)
        if not project:
            return None

        return self.db.query(TaskItem).filter(
            TaskItem.project_id == project.id,
            TaskItem.task_number == number,
            TaskItem.is_deleted == False
        ).first()

    def get_tasks_by_status(
        self,
        user_id: str,
        project_id: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[TaskItem]:
        """Get tasks filtered by status, optionally for a specific project."""
        query = self.db.query(TaskItem).filter(
            TaskItem.user_id == user_id,
            TaskItem.is_deleted == False
        )

        if project_id:
            query = query.filter(TaskItem.project_id == project_id)

        if status:
            query = query.filter(TaskItem.status == status)

        return query.order_by(TaskItem.created_at.desc()).all()

    def get_open_bugs(self, user_id: str, project_id: Optional[str] = None) -> List[TaskItem]:
        """Get all open bugs (not completed)."""
        query = self.db.query(TaskItem).filter(
            TaskItem.user_id == user_id,
            TaskItem.task_type == "bug",
            TaskItem.status.in_(["backlog", "in_progress", "in_qa"]),
            TaskItem.is_deleted == False
        )

        if project_id:
            query = query.filter(TaskItem.project_id == project_id)

        return query.order_by(TaskItem.created_at.desc()).all()

    def get_in_progress_tasks(self, user_id: str, project_id: Optional[str] = None) -> List[TaskItem]:
        """Get all in-progress tasks."""
        return self.get_tasks_by_status(user_id, project_id, "in_progress")

    def get_backlog_tasks(self, user_id: str, project_id: Optional[str] = None) -> List[TaskItem]:
        """Get all backlog tasks."""
        return self.get_tasks_by_status(user_id, project_id, "backlog")

    def get_qa_tasks(self, user_id: str, project_id: Optional[str] = None) -> List[TaskItem]:
        """Get all tasks in QA."""
        return self.get_tasks_by_status(user_id, project_id, "in_qa")

    # =========================================================================
    # STATISTICS AND METRICS
    # =========================================================================

    def get_project_summary(self, user_id: str, project_id: str) -> Dict[str, Any]:
        """Get a comprehensive summary of a project."""
        project = self.db.query(DevProject).filter(
            DevProject.id == project_id,
            DevProject.user_id == user_id
        ).first()

        if not project:
            return {}

        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        # Task counts by status
        task_counts = {}
        for status in ["backlog", "in_progress", "in_qa", "completed"]:
            count = self.db.query(func.count(TaskItem.id)).filter(
                TaskItem.project_id == project_id,
                TaskItem.status == status,
                TaskItem.is_deleted == False
            ).scalar() or 0
            task_counts[status] = count

        # Open bugs
        open_bugs = self.db.query(func.count(TaskItem.id)).filter(
            TaskItem.project_id == project_id,
            TaskItem.task_type == "bug",
            TaskItem.status.in_(["backlog", "in_progress", "in_qa"]),
            TaskItem.is_deleted == False
        ).scalar() or 0

        # Commits this week
        commits_this_week = self.db.query(func.count(GitCommit.id)).filter(
            GitCommit.project_id == project_id,
            GitCommit.committed_at >= week_ago
        ).scalar() or 0

        # Tasks completed this week
        completed_this_week = self.db.query(func.count(TaskItem.id)).filter(
            TaskItem.project_id == project_id,
            TaskItem.status == "completed",
            TaskItem.completed_at >= week_ago
        ).scalar() or 0

        # Active branches
        active_branches = self.db.query(func.count(GitBranch.id)).filter(
            GitBranch.project_id == project_id,
            GitBranch.is_merged == False,
            GitBranch.is_deleted == False
        ).scalar() or 0

        return {
            "project": {
                "id": project.id,
                "name": project.name,
                "prefix": project.prefix,
                "description": project.description,
                "tech_stack": project.tech_stack
            },
            "task_counts": task_counts,
            "total_tasks": sum(task_counts.values()),
            "open_bugs": open_bugs,
            "commits_this_week": commits_this_week,
            "tasks_completed_this_week": completed_this_week,
            "active_branches": active_branches
        }

    def get_weekly_velocity(self, user_id: str, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Get weekly velocity metrics (commits and completed tasks)."""
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)

        query_filter = []
        if project_id:
            query_filter.append(GitCommit.project_id == project_id)
        query_filter.append(GitCommit.committed_at >= week_ago)

        # Get project IDs for user if not specified
        if not project_id:
            project_ids = [p.id for p in self.get_projects_for_user(user_id)]
            if project_ids:
                query_filter.append(GitCommit.project_id.in_(project_ids))
            else:
                return {"commits": 0, "tasks_completed": 0, "commits_per_day": 0}

        commits_this_week = self.db.query(func.count(GitCommit.id)).filter(
            *query_filter
        ).scalar() or 0

        task_filter = [TaskItem.user_id == user_id]
        if project_id:
            task_filter.append(TaskItem.project_id == project_id)
        task_filter.append(TaskItem.status == "completed")
        task_filter.append(TaskItem.completed_at >= week_ago)

        completed_this_week = self.db.query(func.count(TaskItem.id)).filter(
            *task_filter
        ).scalar() or 0

        return {
            "commits": commits_this_week,
            "tasks_completed": completed_this_week,
            "commits_per_day": round(commits_this_week / 7, 1)
        }

    def get_shipped_this_week(self, user_id: str, project_id: Optional[str] = None) -> List[TaskItem]:
        """Get tasks completed this week."""
        week_ago = datetime.utcnow() - timedelta(days=7)

        query = self.db.query(TaskItem).filter(
            TaskItem.user_id == user_id,
            TaskItem.status == "completed",
            TaskItem.completed_at >= week_ago
        )

        if project_id:
            query = query.filter(TaskItem.project_id == project_id)

        return query.order_by(TaskItem.completed_at.desc()).all()

    def get_recent_commits(
        self,
        user_id: str,
        project_id: Optional[str] = None,
        limit: int = 10
    ) -> List[GitCommit]:
        """Get recent commits."""
        # Get project IDs for user
        if project_id:
            project_ids = [project_id]
        else:
            project_ids = [p.id for p in self.get_projects_for_user(user_id)]

        if not project_ids:
            return []

        return self.db.query(GitCommit).filter(
            GitCommit.project_id.in_(project_ids)
        ).order_by(GitCommit.committed_at.desc()).limit(limit).all()

    def get_unlinked_commits(
        self,
        user_id: str,
        project_id: Optional[str] = None
    ) -> List[GitCommit]:
        """Get commits that haven't been linked to any tasks."""
        # Get project IDs
        if project_id:
            project_ids = [project_id]
        else:
            project_ids = [p.id for p in self.get_projects_for_user(user_id)]

        if not project_ids:
            return []

        # Get IDs of linked commits
        linked_ids = self.db.query(TaskCommitLink.commit_id).distinct()

        return self.db.query(GitCommit).filter(
            GitCommit.project_id.in_(project_ids),
            ~GitCommit.id.in_(linked_ids)
        ).order_by(GitCommit.committed_at.desc()).limit(20).all()

    def get_commits_for_task(self, task_id: str) -> List[GitCommit]:
        """Get all commits linked to a task."""
        return self.db.query(GitCommit).join(TaskCommitLink).filter(
            TaskCommitLink.task_id == task_id
        ).order_by(GitCommit.committed_at.desc()).all()

    # =========================================================================
    # SUGGESTIONS AND RECOMMENDATIONS
    # =========================================================================

    def suggest_next_task(self, user_id: str, project_id: Optional[str] = None) -> Optional[TaskItem]:
        """
        Suggest the next task to work on based on:
        1. Critical/high priority bugs first
        2. High priority features
        3. Oldest backlog items
        """
        # First: Critical/high priority bugs in backlog or in_progress
        query = self.db.query(TaskItem).filter(
            TaskItem.user_id == user_id,
            TaskItem.task_type == "bug",
            TaskItem.status.in_(["backlog", "in_progress"]),
            TaskItem.priority.in_(["critical", "high"]),
            TaskItem.is_deleted == False
        )
        if project_id:
            query = query.filter(TaskItem.project_id == project_id)

        bug = query.order_by(
            func.field(TaskItem.priority, "critical", "high"),
            TaskItem.created_at
        ).first()

        if bug:
            return bug

        # Second: High priority backlog items
        query = self.db.query(TaskItem).filter(
            TaskItem.user_id == user_id,
            TaskItem.status == "backlog",
            TaskItem.priority.in_(["critical", "high"]),
            TaskItem.is_deleted == False
        )
        if project_id:
            query = query.filter(TaskItem.project_id == project_id)

        high_priority = query.order_by(TaskItem.created_at).first()
        if high_priority:
            return high_priority

        # Third: Oldest backlog item
        query = self.db.query(TaskItem).filter(
            TaskItem.user_id == user_id,
            TaskItem.status == "backlog",
            TaskItem.is_deleted == False
        )
        if project_id:
            query = query.filter(TaskItem.project_id == project_id)

        return query.order_by(TaskItem.created_at).first()

    def get_stale_tasks(
        self,
        user_id: str,
        project_id: Optional[str] = None,
        days_threshold: int = 14
    ) -> List[TaskItem]:
        """Get tasks that haven't been updated in a while."""
        threshold = datetime.utcnow() - timedelta(days=days_threshold)

        query = self.db.query(TaskItem).filter(
            TaskItem.user_id == user_id,
            TaskItem.status.in_(["in_progress", "in_qa"]),
            TaskItem.updated_at < threshold,
            TaskItem.is_deleted == False
        )

        if project_id:
            query = query.filter(TaskItem.project_id == project_id)

        return query.order_by(TaskItem.updated_at).all()

    # =========================================================================
    # CONVERSATION HELPERS
    # =========================================================================

    def format_project_state(self, user_id: str, project_name: Optional[str] = None) -> str:
        """
        Format project state for Sara's conversation response.
        Used when user asks "What's the state of [project]?" or similar.
        """
        if project_name:
            project = self.get_project_by_name(user_id, project_name)
            if not project:
                project = self.get_project_by_prefix(user_id, project_name)

            if not project:
                return f"I couldn't find a project matching '{project_name}'."

            summary = self.get_project_summary(user_id, project.id)
        else:
            # Get summary across all projects
            projects = self.get_projects_for_user(user_id)
            if not projects:
                return "You don't have any projects set up yet."

            # Aggregate stats
            total_backlog = 0
            total_in_progress = 0
            total_in_qa = 0
            total_bugs = 0

            for p in projects:
                s = self.get_project_summary(user_id, p.id)
                total_backlog += s.get("task_counts", {}).get("backlog", 0)
                total_in_progress += s.get("task_counts", {}).get("in_progress", 0)
                total_in_qa += s.get("task_counts", {}).get("in_qa", 0)
                total_bugs += s.get("open_bugs", 0)

            summary = {
                "project": {"name": "All Projects"},
                "task_counts": {
                    "backlog": total_backlog,
                    "in_progress": total_in_progress,
                    "in_qa": total_in_qa
                },
                "open_bugs": total_bugs
            }

        # Format response
        name = summary["project"]["name"]
        counts = summary.get("task_counts", {})
        bugs = summary.get("open_bugs", 0)
        commits = summary.get("commits_this_week", 0)
        completed = summary.get("tasks_completed_this_week", 0)

        lines = [f"**{name}**"]

        if counts:
            lines.append(f"- Backlog: {counts.get('backlog', 0)}")
            lines.append(f"- In Progress: {counts.get('in_progress', 0)}")
            lines.append(f"- In QA: {counts.get('in_qa', 0)}")

        if bugs > 0:
            lines.append(f"- Open Bugs: {bugs}")

        if commits > 0 or completed > 0:
            lines.append(f"\nThis week: {commits} commits, {completed} tasks completed")

        return "\n".join(lines)

    def format_task_detail(self, task: TaskItem) -> str:
        """Format a single task for conversation output."""
        project = task.project
        prefix = project.prefix if project else "TASK"
        tag = f"{prefix}-{task.task_number}"

        lines = [
            f"**{tag}: {task.title}**",
            f"Type: {task.task_type} | Status: {task.status.replace('_', ' ')}"
        ]

        if task.priority:
            lines.append(f"Priority: {task.priority}")

        if task.description:
            lines.append(f"\n{task.description[:200]}...")

        # Linked commits
        commits = self.get_commits_for_task(task.id)
        if commits:
            lines.append(f"\n{len(commits)} linked commit(s)")

        return "\n".join(lines)

    def format_task_list(self, tasks: List[TaskItem], title: str = "Tasks") -> str:
        """Format a list of tasks for conversation output."""
        if not tasks:
            return f"No {title.lower()} found."

        lines = [f"**{title}** ({len(tasks)}):"]
        for task in tasks[:10]:  # Limit to 10
            project = task.project
            prefix = project.prefix if project else "TASK"
            tag = f"{prefix}-{task.task_number}"
            lines.append(f"- {tag}: {task.title[:50]}{'...' if len(task.title) > 50 else ''}")

        if len(tasks) > 10:
            lines.append(f"... and {len(tasks) - 10} more")

        return "\n".join(lines)

    def format_commits_list(self, commits: List[GitCommit], title: str = "Recent Commits") -> str:
        """Format a list of commits for conversation output."""
        if not commits:
            return "No commits found."

        lines = [f"**{title}** ({len(commits)}):"]
        for commit in commits[:10]:
            short_sha = commit.sha[:7]
            message = commit.message.split('\n')[0][:60]
            lines.append(f"- `{short_sha}` {message}")

        return "\n".join(lines)
