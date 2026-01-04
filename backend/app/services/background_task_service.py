"""
Background Task Service - Manages agent task lifecycle independent of client connections

This service:
- Creates and persists background tasks to database
- Runs orchestration server-side (not tied to WebSocket)
- Creates agent workspace folders and result notes
- Triggers notifications on task completion
- Handles clarification requests
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from .orchestrator_service import OrchestratorService

logger = logging.getLogger(__name__)

# Agent workspace folder name
AGENT_WORKSPACE_FOLDER_NAME = "📁 Agent Workspace"


class BackgroundTaskService:
    """Manages background agent tasks"""

    def __init__(self):
        # Track running tasks by ID (for potential cancellation)
        self._running_tasks: Dict[str, asyncio.Task] = {}

    def _create_orchestrator(
        self,
        db: Session = None,
        user_id: str = None,
        workspace_folder_id: str = None
    ) -> OrchestratorService:
        """
        Create an orchestrator with the appropriate tools.

        If db/user_id provided, uses REAL tools (web search, URL reading, Sara data).
        Otherwise uses mock tools (for testing).
        """
        return OrchestratorService(
            db=db,
            user_id=user_id,
            workspace_folder_id=workspace_folder_id
        )

    async def create_task(
        self,
        db: Session,
        user_id: str,
        query: str,
        task_type: str = "research"
    ) -> "BackgroundTask":
        """
        Create a new background task and persist to database.

        Args:
            db: Database session
            user_id: User who initiated the task
            query: The original query/request
            task_type: Type of task (research, analysis, etc.)

        Returns:
            The created BackgroundTask model
        """
        from ..main_simple import BackgroundTask, Folder

        # Ensure agent workspace folder exists
        workspace_folder = await self._ensure_workspace_folder(db, user_id)

        # Create task record
        task = BackgroundTask(
            id=str(uuid.uuid4()),
            user_id=user_id,
            status="pending",
            task_type=task_type,
            original_query=query,
            workspace_folder_id=workspace_folder.id if workspace_folder else None,
            task_metadata={
                "created_by": "background_task_service",
                "worker_count": 0,
                "progress_events": []
            }
        )

        db.add(task)
        db.commit()
        db.refresh(task)

        logger.info(f"Created background task {task.id} for user {user_id}: {query[:50]}...")

        return task

    async def _ensure_workspace_folder(self, db: Session, user_id: str) -> Optional["Folder"]:
        """Ensure agent workspace folder exists for user, create if needed."""
        from ..main_simple import Folder

        # Look for existing workspace folder
        workspace = db.query(Folder).filter(
            Folder.user_id == user_id,
            Folder.name == AGENT_WORKSPACE_FOLDER_NAME
        ).first()

        if workspace:
            return workspace

        # Create workspace folder
        workspace = Folder(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=AGENT_WORKSPACE_FOLDER_NAME,
            parent_id=None,  # Top-level folder
            sort_order=999  # Put at end
        )

        db.add(workspace)
        db.commit()
        db.refresh(workspace)

        logger.info(f"Created agent workspace folder for user {user_id}")

        return workspace

    async def run_task(
        self,
        db: Session,
        task_id: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None
    ) -> Dict[str, Any]:
        """
        Run a background task using the orchestrator.

        This method:
        1. Updates task status to 'running'
        2. Runs orchestration
        3. Creates result note in workspace
        4. Updates task status to 'completed' or 'failed'
        5. Triggers notification

        Args:
            db: Database session
            task_id: ID of the task to run
            progress_callback: Optional callback for progress events

        Returns:
            Result dict with status and note_id
        """
        from ..main_simple import BackgroundTask, Note

        # Load task
        task = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
        if not task:
            logger.error(f"Task {task_id} not found")
            return {"error": "Task not found"}

        # Update status to running
        task.status = "running"
        task.started_at = datetime.utcnow()
        task.task_metadata = {
            **(task.task_metadata or {}),
            "started_at_utc": datetime.utcnow().isoformat()
        }
        db.commit()

        logger.info(f"Starting background task {task_id}: {task.original_query[:50]}...")

        # Create orchestrator with REAL tools (db, user_id, workspace_folder_id)
        orchestrator = self._create_orchestrator(
            db=db,
            user_id=task.user_id,
            workspace_folder_id=task.workspace_folder_id
        )

        # Collect progress events
        progress_events = []
        worker_results = []

        async def collect_events(event: Dict[str, Any]):
            """Collect events and optionally forward to callback"""
            progress_events.append(event)

            # Track worker results
            if event.get("phase") == "worker_complete":
                worker_results.append({
                    "worker_id": event.get("worker_id"),
                    "task": event.get("task"),
                    "result_preview": event.get("result_preview", "")[:500]
                })

            # Update metadata periodically
            if event.get("phase") in ["spawning_workers", "workers_complete", "complete"]:
                task.task_metadata = {
                    **(task.task_metadata or {}),
                    "last_phase": event.get("phase"),
                    "worker_count": len(worker_results),
                    "progress_events_count": len(progress_events)
                }
                db.commit()

            # Forward to external callback if provided
            if progress_callback:
                try:
                    await progress_callback(event)
                except Exception as e:
                    logger.warning(f"Progress callback error: {e}")

        try:
            # Run orchestration with real tools
            result = await orchestrator.run_task(
                task.original_query,
                collect_events
            )

            if "error" in result:
                # Task failed
                task.status = "failed"
                task.error_message = result.get("error", "Unknown error")
                task.completed_at = datetime.utcnow()
                db.commit()

                logger.error(f"Background task {task_id} failed: {task.error_message}")

                # Still create a note with the error
                note = await self._create_result_note(
                    db,
                    task,
                    f"# Task Failed\n\n**Error:** {task.error_message}\n\n**Original Query:** {task.original_query}",
                    is_error=True
                )

                return {
                    "status": "failed",
                    "error": task.error_message,
                    "note_id": note.id if note else None
                }

            # Task completed successfully
            final_response = result.get("response", "No response generated")

            # Create result note
            note = await self._create_result_note(
                db,
                task,
                final_response,
                worker_results=worker_results
            )

            # Update task as completed
            task.status = "completed"
            task.result_note_id = note.id if note else None
            task.completed_at = datetime.utcnow()
            task.task_metadata = {
                **(task.task_metadata or {}),
                "completed_at_utc": datetime.utcnow().isoformat(),
                "total_duration_ms": result.get("total_duration_ms"),
                "iterations": result.get("iterations"),
                "worker_count": len(worker_results),
                "final_response_length": len(final_response)
            }
            db.commit()

            logger.info(f"Background task {task_id} completed successfully")

            # Trigger notification (async, don't block)
            # Extract data before async to avoid session issues
            task_data = {
                "id": task.id,
                "user_id": task.user_id,
                "status": task.status,
                "original_query": task.original_query,
                "result_note_id": task.result_note_id
            }
            asyncio.create_task(
                self._notify_task_complete(task_data)
            )

            return {
                "status": "completed",
                "note_id": note.id if note else None,
                "response_preview": final_response[:500] + "..." if len(final_response) > 500 else final_response
            }

        except Exception as e:
            logger.exception(f"Background task {task_id} exception")

            task.status = "failed"
            task.error_message = str(e)
            task.completed_at = datetime.utcnow()
            db.commit()

            return {
                "status": "failed",
                "error": str(e)
            }

    async def _create_result_note(
        self,
        db: Session,
        task: "BackgroundTask",
        content: str,
        worker_results: List[Dict] = None,
        is_error: bool = False
    ) -> Optional["Note"]:
        """Create a note in the agent workspace with task results."""
        from ..main_simple import Note

        # Build note title
        query_preview = task.original_query[:50]
        if len(task.original_query) > 50:
            query_preview += "..."

        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        title = f"{'❌' if is_error else '✅'} Agent Report: {query_preview} ({timestamp})"

        # Build note content with metadata
        note_content = f"""# Agent Research Report

**Query:** {task.original_query}
**Status:** {"Failed" if is_error else "Completed"}
**Task Type:** {task.task_type}
**Created:** {task.created_at}
**Completed:** {datetime.utcnow()}

---

{content}
"""

        # Add worker summary if available
        if worker_results and not is_error:
            note_content += "\n\n---\n\n## Worker Summary\n\n"
            for wr in worker_results:
                note_content += f"### Worker {wr.get('worker_id')}: {wr.get('task', 'Unknown')}\n"
                note_content += f"{wr.get('result_preview', 'No preview')}\n\n"

        # Create note
        note = Note(
            id=str(uuid.uuid4()),
            user_id=task.user_id,
            folder_id=task.workspace_folder_id,
            title=title,
            content=note_content
        )

        db.add(note)
        db.commit()
        db.refresh(note)

        logger.info(f"Created result note {note.id} for task {task.id}")

        return note

    async def _notify_task_complete(self, task_data: Dict[str, Any]):
        """
        Send notification that task is complete.

        Args:
            task_data: Dict with keys: id, user_id, status, original_query, result_note_id
        """
        try:
            # Import notification config from main_simple
            from ..main_simple import (
                NTFY_SERVER_URL, NTFY_ENABLED, NTFY_SYSTEM_TOPIC,
                PushToken, SessionLocal
            )
            import httpx

            task_id = task_data["id"]
            user_id = task_data["user_id"]
            status = task_data["status"]
            original_query = task_data["original_query"]
            result_note_id = task_data.get("result_note_id")

            status_emoji = "✅" if status == "completed" else "❌"
            query_preview = original_query[:50]
            if len(original_query) > 50:
                query_preview += "..."

            title = f"{status_emoji} Background Task Complete"
            body = f"Your agents finished: {query_preview}"

            # NTFY notifications disabled - webapp has its own notification banner

            # Send Expo push notification to all user's devices
            try:
                # Create a new session for the push token query
                db = SessionLocal()
                try:
                    push_tokens = db.query(PushToken).filter(
                        PushToken.user_id == user_id,
                        PushToken.is_active == True
                    ).all()

                    if push_tokens:
                        # Build messages for Expo push API
                        messages = []
                        for token in push_tokens:
                            messages.append({
                                "to": token.token,
                                "sound": "default",
                                "title": title,
                                "body": body,
                                "data": {
                                    "type": "background_task",
                                    "task_id": task_id,
                                    "status": status,
                                    "note_id": result_note_id
                                }
                            })

                        # Send to Expo push notification service
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            response = await client.post(
                                "https://exp.host/--/api/v2/push/send",
                                json=messages,
                                headers={
                                    "Accept": "application/json",
                                    "Accept-Encoding": "gzip, deflate",
                                    "Content-Type": "application/json",
                                }
                            )
                            if response.status_code == 200:
                                logger.info(f"Sent push notifications to {len(push_tokens)} devices for task {task_id}")
                            else:
                                logger.warning(f"Expo push returned {response.status_code}: {response.text}")
                finally:
                    db.close()

            except Exception as e:
                logger.warning(f"Failed to send push notifications: {e}")

        except Exception as e:
            logger.exception(f"Error sending task complete notification: {e}")

    async def get_active_tasks(self, db: Session, user_id: str) -> List["BackgroundTask"]:
        """Get all active (pending/running) tasks for a user."""
        from ..main_simple import BackgroundTask

        return db.query(BackgroundTask).filter(
            BackgroundTask.user_id == user_id,
            BackgroundTask.status.in_(["pending", "running", "needs_clarification"])
        ).order_by(BackgroundTask.created_at.desc()).all()

    async def get_recent_tasks(
        self,
        db: Session,
        user_id: str,
        limit: int = 10,
        include_active: bool = True
    ) -> List["BackgroundTask"]:
        """Get recent tasks for a user (active + recently completed)."""
        from ..main_simple import BackgroundTask

        query = db.query(BackgroundTask).filter(
            BackgroundTask.user_id == user_id
        )

        if not include_active:
            query = query.filter(
                BackgroundTask.status.in_(["completed", "failed"])
            )

        return query.order_by(BackgroundTask.created_at.desc()).limit(limit).all()

    async def get_task_status(self, db: Session, task_id: str) -> Optional["BackgroundTask"]:
        """Get a specific task by ID."""
        from ..main_simple import BackgroundTask

        return db.query(BackgroundTask).filter(
            BackgroundTask.id == task_id
        ).first()

    async def request_clarification(
        self,
        db: Session,
        task_id: str,
        question: str
    ) -> bool:
        """
        Request clarification from user (called by orchestrator).
        Updates task status and triggers notification.
        """
        from ..main_simple import BackgroundTask

        task = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
        if not task:
            return False

        task.status = "needs_clarification"
        task.clarification_question = question
        task.task_metadata = {
            **(task.task_metadata or {}),
            "clarification_requested_at": datetime.utcnow().isoformat()
        }
        db.commit()

        # Trigger notification for clarification
        # Extract data before async to avoid session issues
        task_data = {
            "id": task.id,
            "user_id": task.user_id
        }
        asyncio.create_task(
            self._notify_clarification_needed(task_data, question)
        )

        logger.info(f"Task {task_id} needs clarification: {question[:50]}...")

        return True

    async def _notify_clarification_needed(
        self,
        task_data: Dict[str, Any],
        question: str
    ):
        """Send notification that task needs clarification."""
        try:
            from ..main_simple import (
                NTFY_SERVER_URL, NTFY_ENABLED, NTFY_SYSTEM_TOPIC,
                PushToken, SessionLocal
            )
            import httpx

            task_id = task_data["id"]
            user_id = task_data["user_id"]

            title = "🤔 Agent Needs Your Input"
            body = f"Question: {question[:100]}"

            # NTFY notifications disabled - webapp has MiniChatOverlay

            # Send push notifications with a new session
            db = SessionLocal()
            try:
                push_tokens = db.query(PushToken).filter(
                    PushToken.user_id == user_id,
                    PushToken.is_active == True
                ).all()

                if push_tokens:
                    messages = []
                    for token in push_tokens:
                        messages.append({
                            "to": token.token,
                            "sound": "default",
                            "title": title,
                            "body": body,
                            "data": {
                                "type": "background_task_clarification",
                                "task_id": task_id,
                                "question": question
                            }
                        })

                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.post(
                            "https://exp.host/--/api/v2/push/send",
                            json=messages,
                            headers={
                                "Accept": "application/json",
                                "Content-Type": "application/json",
                            }
                        )
                        if response.status_code == 200:
                            logger.info(f"Sent push notifications for clarification on task {task_id}")
            finally:
                db.close()

        except Exception as e:
            logger.exception(f"Error sending clarification notification: {e}")

    async def provide_clarification(
        self,
        db: Session,
        task_id: str,
        response: str
    ) -> bool:
        """
        Provide clarification response and resume task.
        """
        from ..main_simple import BackgroundTask

        task = db.query(BackgroundTask).filter(
            BackgroundTask.id == task_id,
            BackgroundTask.status == "needs_clarification"
        ).first()

        if not task:
            return False

        task.clarification_response = response
        task.status = "running"
        task.task_metadata = {
            **(task.task_metadata or {}),
            "clarification_provided_at": datetime.utcnow().isoformat()
        }
        db.commit()

        logger.info(f"Clarification provided for task {task_id}, resuming...")

        # Resume task (would need to implement continuation logic)
        # For now, we'll need to restart with context
        # This is a TODO for later - orchestrator needs to support continuation

        return True


# Singleton instance
background_task_service = BackgroundTaskService()


def get_background_task_service() -> BackgroundTaskService:
    """Get the background task service singleton."""
    return background_task_service
