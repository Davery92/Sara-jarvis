"""
Agent Dispatch Service — Multi-mode task execution with session tracking.

Modes:
- auto: Classify task and route to internal tools or sandbox VM
- dispatch: SSH to remote VM, run Claude Code agent, track session_id
- internal: Use Sara's internal tool registry (email, calendar, memory, etc.)
- self_orchestrate: Use existing OrchestratorService with SSH context
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from app.services.event_bus import event_bus, EventType, Event
from app.services.vm_bridge import VMBridge, VMConfig, get_vm_config_from_settings

logger = logging.getLogger(__name__)

CLASSIFIER_PROMPT = """Classify this task into one of two execution modes.

INTERNAL — Use when the task needs data from Sara's systems:
- email: Search, read, recent emails
- time: Calendar events, reminders, timers
- notes: Notes and documents
- memory: Episodic recall and memory search
- web: Web search or research
- personal_knowledge: Facts about David
- home: Home status or smart home control
- fitness: Fitness, food, workout data
- learning: Learning topics and study data
- inbox: Saved content, articles, URLs

SANDBOX — Use when the task needs:
- Writing or running code
- File creation or manipulation
- System administration
- Building/compiling software
- Installing packages
- Running scripts or commands
- Anything requiring a terminal

Reply with ONLY a JSON object:
{"mode": "internal" or "sandbox", "categories": ["email", "web", ...]}
Include only the 1-3 most relevant categories from the list above.

Task: """


class AgentDispatchService:
    """Manages agent task dispatch to remote VM or local orchestration."""

    def __init__(self):
        self._running_tasks: Dict[str, asyncio.Task] = {}

    def _get_bridge(self, db: Session, user_id: str) -> VMBridge:
        """Build a VMBridge from the user's saved preferences."""
        from app.models.user_settings import UserSettings

        settings = db.query(UserSettings).filter(
            UserSettings.user_id == user_id
        ).first()
        preferences = settings.preferences if settings else {}
        config = get_vm_config_from_settings(preferences)
        return VMBridge(config)

    async def _classify_task(self, task_description: str) -> tuple[str, str, list]:
        """Classify a task as 'internal' or 'sandbox' using a fast LLM call.

        Returns (mode, reason, categories) tuple.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "http://100.104.68.115:11434/v1/chat/completions",
                    json={
                        "model": "gpt-oss:20b",
                        "messages": [
                            {"role": "user", "content": CLASSIFIER_PROMPT + task_description},
                        ],
                        "temperature": 0.0,
                        "max_tokens": 150,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            content = data["choices"][0]["message"].get("content", "").strip()

            # Parse JSON from response (handle markdown code blocks)
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            parsed = json.loads(content)
            mode = parsed.get("mode", "sandbox")
            reason = parsed.get("reason", "")
            categories = parsed.get("categories", [])

            if mode not in ("internal", "sandbox"):
                mode = "sandbox"

            # Validate categories
            valid_cats = {"email", "time", "notes", "memory", "web",
                          "personal_knowledge", "home", "fitness", "learning", "inbox"}
            categories = [c for c in categories if c in valid_cats]

            logger.info(f"[dispatch] Task classified as '{mode}', categories={categories}: {reason}")
            return mode, reason, categories

        except Exception as e:
            logger.warning(f"[dispatch] Classification failed, defaulting to sandbox: {e}")
            return "sandbox", f"Classification error: {e}", []

    async def dispatch_task(
        self,
        db: Session,
        user_id: str,
        task_description: str,
        mode: str = "auto",
        working_directory: Optional[str] = None,
        timeout: int = 600,
        notify_on_complete: bool = False,
    ) -> dict:
        """Dispatch a task to the appropriate execution mode.

        Modes:
        - auto: Classify and route automatically
        - dispatch: VM sandbox agent
        - internal: Sara's internal tools
        - self_orchestrate: Existing orchestrator

        Returns dict with task_id, status, and initial info.
        """
        from app.models.background_task import BackgroundTask
        from app.models.mission import Mission, MissionStep

        # Auto-classify if needed
        classified_mode = None
        classification_reason = None
        classified_categories = None
        if mode == "auto":
            classified_mode, classification_reason, classified_categories = await self._classify_task(task_description)
            # Map classifier result to execution mode
            mode = "internal" if classified_mode == "internal" else "dispatch"
            # If classification succeeded as internal but returned no categories, infer them
            if mode == "internal" and not classified_categories:
                classified_categories = self._infer_categories(task_description)
            logger.info(f"[dispatch] Auto-classified '{task_description[:60]}' → {mode} categories={classified_categories}")
        elif mode == "internal":
            # Mode forced to internal — still classify to get relevant categories
            # so we don't load all 80+ tools
            _, classification_reason, classified_categories = await self._classify_task(task_description)
            classified_mode = "internal"
            # If classification failed (empty categories), infer from task text
            if not classified_categories:
                classified_categories = self._infer_categories(task_description)
            logger.info(f"[dispatch] Forced internal, classified categories={classified_categories}")

        if mode == "internal":
            task_type = "internal_agent"
        elif mode == "dispatch":
            task_type = "vm_agent"
        else:
            task_type = "self_orchestrate"

        # Find relevant skills from past successful tasks
        relevant_skills = self._find_relevant_skills(db, user_id, task_description)
        used_skill_ids = [s["skill_id"] for s in relevant_skills]

        # Create BackgroundTask record
        task_id = str(uuid.uuid4())
        task_metadata = {
            "mode": mode,
            "working_directory": working_directory,
            "timeout": timeout,
            "created_by": "agent_dispatch",
            "mission_id": None,  # set after mission is created
            "notify_on_complete": notify_on_complete,
            "started_at": datetime.utcnow().isoformat(),
        }
        if used_skill_ids:
            task_metadata["used_skill_ids"] = used_skill_ids
            task_metadata["skill_context"] = self._format_skills_for_prompt(relevant_skills)
        if classified_mode:
            task_metadata["classified_mode"] = classified_mode
            task_metadata["classification_reason"] = classification_reason
            task_metadata["classified_categories"] = classified_categories

        task = BackgroundTask(
            id=task_id,
            user_id=user_id,
            status="pending",
            task_type=task_type,
            original_query=task_description,
            task_metadata=task_metadata,
        )
        db.add(task)

        # Create a Mission for frontend tracking
        if mode == "internal":
            steps = [
                {"action": "classify", "desc": "Determine execution mode"},
                {"action": "execute", "desc": "Run internal tools"},
                {"action": "report", "desc": "Compile results"},
            ]
        else:
            steps = [
                {"action": "connect", "desc": "Connect to sandbox VM"},
                {"action": "execute", "desc": "Run agent task"},
                {"action": "report", "desc": "Collect results"},
            ]

        mission = Mission(
            user_id=user_id,
            title=f"Agent: {task_description[:80]}",
            description=task_description,
            source="agent_dispatch",
            state="pending",
            priority="normal",
            total_steps=len(steps),
            completed_steps=0,
            current_step_index=0,
            requires_confirmation=False,
            mission_metadata={"task_id": task_id, "mode": mode},
        )
        db.add(mission)
        db.flush()  # Generate mission.id
        mission_id = str(mission.id)

        # Store mission_id in task metadata for resume lookups
        task.task_metadata = {**(task.task_metadata or {}), "mission_id": mission_id}

        for i, step in enumerate(steps):
            db.add(MissionStep(
                mission_id=mission.id,
                step_index=i,
                action_name=step["action"],
                description=step["desc"],
                status="pending",
            ))

        db.commit()

        # Launch async execution
        if mode == "internal":
            coro = self._run_internal_mode(
                task_id, mission_id, user_id, task_description, timeout,
                categories=classified_categories,
            )
        elif mode == "dispatch":
            coro = self._run_dispatch_mode(
                task_id, mission_id, user_id, task_description,
                working_directory, timeout,
            )
        else:
            coro = self._run_self_orchestrate_mode(
                task_id, mission_id, user_id, task_description, timeout,
            )

        async_task = asyncio.create_task(coro)
        async_task.add_done_callback(self._task_done_callback)
        self._running_tasks[task_id] = async_task

        # Emit dispatched event
        await self._emit_progress(user_id, task_id, "dispatched",
                                  summary=f"Task dispatched ({mode} mode): {task_description[:100]}")

        return {
            "task_id": task_id,
            "mission_id": mission_id,
            "status": "pending",
            "mode": mode,
            "classified_mode": classified_mode,
            "message": f"Task dispatched ({mode} mode)",
        }

    async def retry_task(
        self,
        db: Session,
        task_id: str,
        user_id: str,
    ) -> dict:
        """Retry a failed agent dispatch task by creating a new task+mission.

        Reuses the original query and settings from the failed task.
        """
        from app.models.background_task import BackgroundTask

        task = db.query(BackgroundTask).filter(
            BackgroundTask.id == task_id,
            BackgroundTask.user_id == user_id,
        ).first()
        if not task:
            return {"error": "Task not found", "task_id": task_id}

        if task.status not in ("failed", "needs_clarification"):
            return {"error": f"Task is {task.status}, not retryable", "task_id": task_id}

        meta = task.task_metadata or {}
        mode = meta.get("mode", "dispatch")
        working_directory = meta.get("working_directory")
        timeout = meta.get("timeout", 600)

        # Mark old task as superseded
        task.status = "superseded"
        meta["superseded_by"] = None  # will be filled after dispatch
        task.task_metadata = {**meta}
        db.commit()

        # Also mark old mission as cancelled
        old_mission_id = meta.get("mission_id")
        if old_mission_id:
            self._update_mission_state(db, old_mission_id, "cancelled")

        # Dispatch a new task with the same parameters
        result = await self.dispatch_task(
            db=db,
            user_id=user_id,
            task_description=task.original_query,
            mode=mode,
            working_directory=working_directory,
            timeout=timeout,
        )

        # Link old → new
        if result.get("task_id"):
            task.task_metadata = {**task.task_metadata, "superseded_by": result["task_id"]}
            db.commit()

        result["retried_from"] = task_id
        return result

    async def retry_mission(
        self,
        db: Session,
        mission_id: str,
        user_id: str,
    ) -> dict:
        """Retry a failed mission by finding its associated agent task and retrying it."""
        from app.models.mission import Mission

        mission = db.query(Mission).filter(
            Mission.id == mission_id,
            Mission.user_id == user_id,
        ).first()
        if not mission:
            return {"error": "Mission not found"}

        if mission.state != "failed":
            return {"error": f"Mission is {mission.state}, not retryable"}

        if mission.source != "agent_dispatch":
            return {"error": "Only agent_dispatch missions can be retried"}

        meta = mission.mission_metadata or {}
        task_id = meta.get("task_id")
        if not task_id:
            return {"error": "No task_id associated with this mission"}

        return await self.retry_task(db, task_id, user_id)

    def recover_orphaned_tasks(self, db: Session) -> int:
        """Mark running agent tasks as failed if their asyncio.Task is gone.

        Called on app startup to clean up tasks abandoned by server restarts.
        Returns count of recovered tasks.
        """
        from app.models.background_task import BackgroundTask
        from app.models.mission import Mission

        orphaned = (
            db.query(BackgroundTask)
            .filter(
                BackgroundTask.task_type.in_(["vm_agent", "self_orchestrate", "internal_agent"]),
                BackgroundTask.status.in_(["running", "pending"]),
            )
            .all()
        )

        recovered = 0
        for task in orphaned:
            # Check if there's an active asyncio.Task for it
            if task.id in self._running_tasks:
                async_task = self._running_tasks[task.id]
                if not async_task.done():
                    continue  # Still running, skip

            task.status = "failed"
            meta = task.task_metadata or {}
            meta["error"] = "Task abandoned by server restart"
            meta["recovered_at"] = datetime.utcnow().isoformat()
            task.task_metadata = {**meta}

            # Also fail the associated mission
            mission_id = meta.get("mission_id")
            if mission_id:
                mission = db.query(Mission).filter(Mission.id == mission_id).first()
                if mission and mission.state in ("running", "pending"):
                    mission.state = "failed"
                    mission.completed_at = datetime.utcnow()

            recovered += 1

        if recovered:
            db.commit()
            logger.info(f"Recovered {recovered} orphaned agent tasks on startup")

        return recovered

    async def resume_task(
        self,
        db: Session,
        task_id: str,
        user_id: str,
        instruction: str,
    ) -> dict:
        """Resume an agent session with a follow-up instruction.

        If the task was using the GLM orchestrator, resumes the orchestrator loop.
        Otherwise falls back to direct Claude session resume (legacy).
        """
        from app.models.background_task import BackgroundTask

        task = db.query(BackgroundTask).filter(
            BackgroundTask.id == task_id,
            BackgroundTask.user_id == user_id,
        ).first()
        if not task:
            return {"error": "Task not found", "task_id": task_id}

        meta = task.task_metadata or {}
        prior_messages = meta.get("orchestrator_messages")
        bridge = self._get_bridge(db, task.user_id)

        # Update task status
        task.status = "running"
        db.commit()
        await self._emit_progress(task.user_id, task_id, "running",
                                  summary="Resuming task with follow-up instruction...")

        if prior_messages:
            # Resume via GLM orchestrator
            from app.services.sandbox_orchestrator import SandboxOrchestrator

            mission_id = meta.get("mission_id") or self._find_mission_id(db, task_id)
            orchestrator = SandboxOrchestrator(
                vm_bridge=bridge,
                task_id=task_id,
                mission_id=mission_id or "",
                user_id=task.user_id,
            )
            # Restore active sessions from prior run
            orchestrator.active_sessions = meta.get("active_sessions", {})

            result = await orchestrator.resume(instruction, prior_messages)

            meta["orchestrator_messages"] = result.get("messages", [])
            meta["active_sessions"] = orchestrator.active_sessions
            meta["last_resume_at"] = datetime.utcnow().isoformat()

            if result["status"] == "needs_clarification":
                task.status = "needs_clarification"
                task.clarification_question = result.get("question", "")[:500]
            elif result["status"] == "completed":
                task.status = "completed"
                task.completed_at = datetime.utcnow()
                meta["output"] = result.get("summary", "")[:5000]
                meta["artifacts"] = result.get("artifacts", [])
                if mission_id:
                    self._update_mission_state(db, mission_id, "done")
            else:
                task.status = "failed"
                meta["error"] = result.get("error", "Unknown error")

            task.task_metadata = {**meta}
            db.commit()

            await self._emit_progress(task.user_id, task_id, task.status,
                                      summary=(result.get("summary") or result.get("question")
                                               or result.get("error", ""))[:200])

            return {
                "task_id": task_id,
                "status": task.status,
                "output": result.get("summary") or result.get("question") or result.get("error", ""),
                "success": task.status == "completed",
            }

        # Fallback: direct Claude session resume (legacy single-session tasks)
        session_id = meta.get("session_id")
        if not session_id:
            return {"error": "No session_id or orchestrator state found — task may not have started yet"}

        result = await bridge.resume_claude_session(
            session_id=session_id,
            instruction=instruction,
            timeout=meta.get("timeout", 600),
            working_dir=meta.get("working_directory"),
        )

        # Update metadata with latest output
        meta["last_resume_output"] = result.output[:3000]
        meta["last_resume_at"] = datetime.utcnow().isoformat()
        task.task_metadata = {**meta}

        if result.success:
            # Check if agent is asking a question
            if self._looks_like_question(result.output):
                task.status = "needs_clarification"
                task.clarification_question = result.output[:500]
            else:
                task.status = "completed"
                task.completed_at = datetime.utcnow()
        else:
            task.status = "failed"

        db.commit()

        await self._emit_progress(task.user_id, task_id, task.status,
                                  summary=result.output[:200])

        return {
            "task_id": task_id,
            "session_id": session_id,
            "status": task.status,
            "output": result.output[:3000],
            "success": result.success,
        }

    async def dispatch_from_deliberation(
        self,
        db: Session,
        user_id: str,
        description: str,
        category: str,
        confidence: float,
        reason: str = "",
    ) -> dict:
        """Dispatch a task originating from Sara's deliberation engine.

        Creates a mission linked to the deliberation, dispatches in auto mode,
        and sets notify_on_complete=True so David sees the result.
        """
        result = await self.dispatch_task(
            db=db,
            user_id=user_id,
            task_description=description,
            mode="auto",
            notify_on_complete=True,
        )

        # Annotate task metadata with deliberation origin
        if result.get("task_id"):
            from app.models.background_task import BackgroundTask
            task = db.query(BackgroundTask).filter(
                BackgroundTask.id == result["task_id"]
            ).first()
            if task:
                meta = task.task_metadata or {}
                meta["origin"] = "deliberation"
                meta["deliberation_category"] = category
                meta["deliberation_confidence"] = confidence
                meta["deliberation_reason"] = reason[:500]
                task.task_metadata = {**meta}
                db.commit()

        result["origin"] = "deliberation"
        result["category"] = category
        return result

    async def get_agent_tasks(
        self,
        db: Session,
        user_id: str,
        limit: int = 20,
    ) -> list:
        """List agent tasks (vm_agent and self_orchestrate types).

        Also auto-fails any tasks stuck in 'needs_clarification' or 'running'
        for more than 4 hours, so stale popups don't haunt the UI.
        """
        from app.models.background_task import BackgroundTask
        from app.models.mission import Mission

        # Auto-expire stuck tasks (> 4 hours in needs_clarification or running)
        cutoff = datetime.utcnow() - timedelta(hours=4)
        stuck_tasks = (
            db.query(BackgroundTask)
            .filter(
                BackgroundTask.user_id == user_id,
                BackgroundTask.task_type.in_(["vm_agent", "self_orchestrate", "internal_agent"]),
                BackgroundTask.status.in_(["needs_clarification", "running"]),
                BackgroundTask.updated_at < cutoff,
            )
            .all()
        )
        for t in stuck_tasks:
            logger.info(f"[dispatch] Auto-expiring stuck task {t.id} (status={t.status}, updated_at={t.updated_at})")
            original_status = t.status
            t.status = "failed"
            meta = t.task_metadata or {}
            meta["error"] = f"Auto-expired: stuck in {original_status} for >4 hours"
            meta["auto_expired_at"] = datetime.utcnow().isoformat()
            t.task_metadata = {**meta}
            # Also fail the associated mission
            mission_id = meta.get("mission_id")
            if mission_id:
                mission = db.query(Mission).filter(Mission.id == mission_id).first()
                if mission and mission.state in ("running", "pending"):
                    mission.state = "failed"
                    mission.completed_at = datetime.utcnow()
        if stuck_tasks:
            db.commit()

        tasks = (
            db.query(BackgroundTask)
            .filter(
                BackgroundTask.user_id == user_id,
                BackgroundTask.task_type.in_(["vm_agent", "self_orchestrate", "internal_agent"]),
            )
            .order_by(BackgroundTask.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._task_to_dict(t) for t in tasks]

    async def get_task_detail(self, db: Session, task_id: str, user_id: str) -> Optional[dict]:
        """Get full task detail including session_id and output."""
        from app.models.background_task import BackgroundTask

        task = db.query(BackgroundTask).filter(
            BackgroundTask.id == task_id,
            BackgroundTask.user_id == user_id,
        ).first()
        if not task:
            return None
        return self._task_to_dict(task, include_output=True)

    # ── Internal execution modes ──────────────────────────────────────

    def _task_done_callback(self, task: asyncio.Task):
        """Log any unhandled exceptions from background agent tasks."""
        if task.cancelled():
            logger.info("Agent task was cancelled")
            return
        exc = task.exception()
        if exc:
            logger.error(f"Agent background task failed with exception: {exc}", exc_info=exc)

    async def _run_dispatch_mode(
        self,
        task_id: str,
        mission_id: str,
        user_id: str,
        task_description: str,
        working_directory: Optional[str],
        timeout: int,
    ):
        """Execute task on VM via GLM orchestrator → Claude Code agents."""
        from app.main_simple import SessionLocal
        from app.services.sandbox_orchestrator import SandboxOrchestrator

        logger.info(f"[dispatch] Starting orchestrated dispatch for task {task_id}")
        db = None
        try:
            db = SessionLocal()
            bridge = self._get_bridge(db, user_id)
            task = self._get_task(db, task_id)
            if not task:
                return

            notify_on_complete = (task.task_metadata or {}).get("notify_on_complete", False)

            # Step 0: Connect to VM
            self._update_mission_step(db, mission_id, 0, "running")
            task.status = "running"
            db.commit()
            await self._emit_progress(user_id, task_id, "running",
                                      summary="Connecting to sandbox VM...")

            status = await bridge.test_connection()
            if status.value != "connected":
                self._update_mission_step(db, mission_id, 0, "failed",
                                          error=f"VM {status.value}")
                task.status = "failed"
                task.task_metadata = {
                    **(task.task_metadata or {}),
                    "error": f"VM connection failed: {status.value}",
                }
                db.commit()
                await self._emit_progress(user_id, task_id, "failed",
                                          summary=f"VM connection failed: {status.value}")
                await self._notify(user_id, task_id, "failed",
                                   f"Agent task failed: VM {status.value}")
                return

            self._update_mission_step(db, mission_id, 0, "done")

            # Step 1: Run orchestrator
            self._update_mission_step(db, mission_id, 1, "running")
            await self._emit_progress(user_id, task_id, "running",
                                      summary="Executing task on sandbox VM...")

            # Inject relevant skills into orchestrator
            skill_context = (task.task_metadata or {}).get("skill_context", "")
            orchestrator = SandboxOrchestrator(
                vm_bridge=bridge,
                task_id=task_id,
                mission_id=mission_id,
                user_id=user_id,
                skill_context=skill_context,
            )
            wd = working_directory or "/home/sara/sandbox"
            result = await orchestrator.run(task_description, wd)

            meta = task.task_metadata or {}
            meta["orchestrator_messages"] = result.get("messages", [])
            meta["active_sessions"] = orchestrator.active_sessions
            meta["orchestrator_model"] = orchestrator.model

            if result["status"] == "needs_clarification":
                self._update_mission_step(db, mission_id, 1, "running")
                task.status = "needs_clarification"
                task.clarification_question = result.get("question", "")[:500]
                task.task_metadata = {**meta}
                db.commit()
                await self._emit_progress(user_id, task_id, "needs_clarification",
                                          summary=result.get("question", "")[:200])
                await self._notify(user_id, task_id, "needs_clarification",
                                   f"Agent needs your input: {result.get('question', '')[:200]}")
                return

            if result["status"] == "failed":
                self._update_mission_step(db, mission_id, 1, "failed",
                                          error=result.get("error", "")[:500])
                task.status = "failed"
                meta["error"] = result.get("error", "Unknown error")
                task.task_metadata = {**meta}
                db.commit()
                # Track skill usage as failed (dispatch mode)
                used_skill_ids = meta.get("used_skill_ids", [])
                self._track_skill_usage(db, used_skill_ids, succeeded=False)
                await self._emit_progress(user_id, task_id, "failed",
                                          summary=result.get("error", "")[:200])
                await self._notify(user_id, task_id, "failed",
                                   f"Agent task failed: {result.get('error', '')[:200]}")
                return

            # Completed
            self._update_mission_step(db, mission_id, 1, "done",
                                      result_data={"summary": result.get("summary", "")[:1000]})

            # Step 2: Report
            self._update_mission_step(db, mission_id, 2, "running")

            summary = result.get("summary", "Task completed")
            artifacts = result.get("artifacts", [])

            task.status = "completed"
            task.completed_at = datetime.utcnow()
            meta["output"] = summary[:5000]
            meta["artifacts"] = artifacts
            task.task_metadata = {**meta}

            # Create result note
            note_content = summary
            if artifacts:
                note_content += "\n\n**Artifacts:**\n" + "\n".join(f"- `{a}`" for a in artifacts)
            note_id = await self._create_result_note(
                db, user_id, task_description, note_content,
            )
            if note_id:
                task.result_note_id = note_id

            self._update_mission_step(db, mission_id, 2, "done")
            self._update_mission_state(db, mission_id, "done")
            db.commit()

            # Track skill usage for skills that were injected as context
            used_skill_ids = meta.get("used_skill_ids", [])
            self._track_skill_usage(db, used_skill_ids, succeeded=True)

            # Extract skill recipe from completed task (fire-and-forget)
            started_at = meta.get("started_at")
            elapsed = 0.0
            if started_at:
                try:
                    start_dt = datetime.fromisoformat(started_at)
                    elapsed = (datetime.utcnow() - start_dt).total_seconds()
                except (ValueError, TypeError):
                    elapsed = 60.0  # assume non-trivial if we can't tell

            asyncio.create_task(self._extract_skill_recipe(
                db=SessionLocal(),  # use a fresh session for async extraction
                user_id=user_id,
                task_id=task_id,
                task_description=task_description,
                output=summary,
                mode="dispatch",
                elapsed_seconds=elapsed,
            ))

            await self._emit_progress(user_id, task_id, "completed",
                                      summary=summary[:200])
            await self._notify(user_id, task_id, "completed",
                               f"Agent task completed: {task_description[:100]}")
            await self._notify_completion(user_id, task_id, task_description,
                                          summary, notify_on_complete)

        except Exception as e:
            logger.exception(f"[dispatch] Dispatch mode failed for task {task_id}: {e}")
            await self._emit_progress(user_id, task_id, "failed",
                                      summary=str(e)[:200])
            try:
                if db:
                    db.rollback()
                    task = self._get_task(db, task_id)
                    if task:
                        task.status = "failed"
                        task.task_metadata = {
                            **(task.task_metadata or {}),
                            "error": str(e),
                        }
                        db.commit()
            except Exception as inner_e:
                logger.error(f"[dispatch] Failed to update task status: {inner_e}")
        finally:
            if db:
                db.close()
            self._running_tasks.pop(task_id, None)

    async def _run_internal_mode(
        self,
        task_id: str,
        mission_id: str,
        user_id: str,
        task_description: str,
        timeout: int,
        categories: list = None,
    ):
        """Execute task using Sara's internal tool registry."""
        from app.main_simple import SessionLocal
        from app.services.internal_tool_agent import InternalToolAgent

        logger.info(f"[dispatch] Starting internal mode for task {task_id}")
        db = None
        try:
            db = SessionLocal()
            task = self._get_task(db, task_id)
            if not task:
                return

            notify_on_complete = (task.task_metadata or {}).get("notify_on_complete", False)

            # Step 0: Classify (already done, mark complete)
            self._update_mission_step(db, mission_id, 0, "done")
            task.status = "running"
            self._update_mission_state(db, mission_id, "running")
            db.commit()
            await self._emit_progress(user_id, task_id, "running",
                                      summary="Running internal tools...")

            # Step 1: Execute with internal tools
            self._update_mission_step(db, mission_id, 1, "running")

            agent = InternalToolAgent(
                task_id=task_id,
                mission_id=mission_id,
                user_id=user_id,
                categories=categories,
            )
            result = await agent.run(task_description)

            meta = task.task_metadata or {}

            if result["status"] == "needs_clarification":
                self._update_mission_step(db, mission_id, 1, "running")
                task.status = "needs_clarification"
                task.clarification_question = result.get("question", "")[:500]
                meta["orchestrator_messages"] = result.get("messages", [])
                task.task_metadata = {**meta}
                db.commit()
                await self._emit_progress(user_id, task_id, "needs_clarification",
                                          summary=result.get("question", "")[:200])
                await self._notify(user_id, task_id, "needs_clarification",
                                   f"Agent needs your input: {result.get('question', '')[:200]}")
                return

            if result["status"] == "failed":
                self._update_mission_step(db, mission_id, 1, "failed",
                                          error=result.get("error", "")[:500])
                task.status = "failed"
                meta["error"] = result.get("error", "Unknown error")
                task.task_metadata = {**meta}
                db.commit()
                # Track skill usage as failed (internal mode)
                used_skill_ids = meta.get("used_skill_ids", [])
                self._track_skill_usage(db, used_skill_ids, succeeded=False)
                await self._emit_progress(user_id, task_id, "failed",
                                          summary=result.get("error", "")[:200])
                await self._notify(user_id, task_id, "failed",
                                   f"Agent task failed: {result.get('error', '')[:200]}")
                return

            # Completed
            self._update_mission_step(db, mission_id, 1, "done",
                                      result_data={"summary": result.get("summary", "")[:1000]})

            # Step 2: Report
            self._update_mission_step(db, mission_id, 2, "running")

            summary = result.get("summary", "Task completed")
            artifacts = result.get("artifacts", [])
            found_items = result.get("found_items", [])

            task.status = "completed"
            task.completed_at = datetime.utcnow()
            meta["output"] = summary[:5000]
            meta["artifacts"] = artifacts
            if found_items:
                meta["found_items"] = found_items[:50]  # cap at 50 items
            task.task_metadata = {**meta}

            # Create result note
            note_content = summary
            if artifacts:
                note_content += "\n\n**Key Findings:**\n" + "\n".join(f"- {a}" for a in artifacts)
            note_id = await self._create_result_note(
                db, user_id, task_description, note_content,
            )
            if note_id:
                task.result_note_id = note_id

            self._update_mission_step(db, mission_id, 2, "done")
            self._update_mission_state(db, mission_id, "done")
            db.commit()

            # Track skill usage for skills that were injected as context
            used_skill_ids = meta.get("used_skill_ids", [])
            self._track_skill_usage(db, used_skill_ids, succeeded=True)

            # Extract skill recipe from completed task (fire-and-forget)
            started_at = meta.get("started_at")
            elapsed = 0.0
            if started_at:
                try:
                    start_dt = datetime.fromisoformat(started_at)
                    elapsed = (datetime.utcnow() - start_dt).total_seconds()
                except (ValueError, TypeError):
                    elapsed = 60.0  # assume non-trivial if we can't tell

            asyncio.create_task(self._extract_skill_recipe(
                db=SessionLocal(),  # use a fresh session for async extraction
                user_id=user_id,
                task_id=task_id,
                task_description=task_description,
                output=summary,
                mode="internal",
                elapsed_seconds=elapsed,
            ))

            await self._emit_progress(user_id, task_id, "completed",
                                      summary=summary[:200])
            await self._notify(user_id, task_id, "completed",
                               f"Agent task completed: {task_description[:100]}")
            await self._notify_completion(user_id, task_id, task_description,
                                          summary, notify_on_complete)

        except Exception as e:
            logger.exception(f"[dispatch] Internal mode failed for task {task_id}: {e}")
            await self._emit_progress(user_id, task_id, "failed",
                                      summary=str(e)[:200])
            try:
                if db:
                    db.rollback()
                    task = self._get_task(db, task_id)
                    if task:
                        task.status = "failed"
                        task.task_metadata = {
                            **(task.task_metadata or {}),
                            "error": str(e),
                        }
                        db.commit()
            except Exception as inner_e:
                logger.error(f"[dispatch] Failed to update task status: {inner_e}")
        finally:
            if db:
                db.close()
            self._running_tasks.pop(task_id, None)

    async def _run_self_orchestrate_mode(
        self,
        task_id: str,
        mission_id: str,
        user_id: str,
        task_description: str,
        timeout: int,
    ):
        """Execute task using the existing OrchestratorService with SSH context."""
        from app.main_simple import SessionLocal
        from app.services.background_task_service import background_task_service

        db = SessionLocal()
        try:
            task = self._get_task(db, task_id)
            if not task:
                return

            task.status = "running"
            db.commit()

            # Delegate to existing background_task_service
            await background_task_service.run_task(db, task_id)

        except Exception as e:
            logger.exception(f"Self-orchestrate mode failed for task {task_id}: {e}")
        finally:
            db.close()
            self._running_tasks.pop(task_id, None)

    # ── Helpers ───────────────────────────────────────────────────────

    def _get_task(self, db: Session, task_id: str):
        from app.models.background_task import BackgroundTask
        return db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()

    def _find_mission_id(self, db: Session, task_id: str) -> Optional[str]:
        """Find the Mission ID associated with a task via mission_metadata."""
        from app.models.mission import Mission
        mission = db.query(Mission).filter(
            Mission.mission_metadata["task_id"].astext == task_id,
        ).first()
        return str(mission.id) if mission else None

    def _update_mission_step(
        self, db: Session, mission_id: str, step_index: int,
        status: str, error: str = None, result_data: dict = None,
    ):
        from app.models.mission import Mission, MissionStep
        step = db.query(MissionStep).filter(
            MissionStep.mission_id == mission_id,
            MissionStep.step_index == step_index,
        ).first()
        if step:
            step.status = status
            if status == "running":
                step.started_at = datetime.utcnow()
            if status in ("done", "failed"):
                step.completed_at = datetime.utcnow()
            if error:
                step.error_message = error
            if result_data:
                step.result = result_data

        # Update mission completed_steps count
        mission = db.query(Mission).filter(Mission.id == mission_id).first()
        if mission:
            done_count = db.query(MissionStep).filter(
                MissionStep.mission_id == mission_id,
                MissionStep.status == "done",
            ).count()
            mission.completed_steps = done_count
            mission.current_step_index = step_index
        db.commit()

    def _update_mission_state(self, db: Session, mission_id: str, state: str):
        from app.models.mission import Mission
        mission = db.query(Mission).filter(Mission.id == mission_id).first()
        if mission:
            mission.state = state
            if state == "done":
                mission.completed_at = datetime.utcnow()
            db.commit()

    @staticmethod
    def _infer_categories(task_description: str) -> list:
        """Infer tool categories from task text when LLM classifier fails."""
        text = task_description.lower()
        cats = []
        if any(w in text for w in ["email", "mail", "inbox", "sender", "attachment", "correspond"]):
            cats.append("email")
        if any(w in text for w in ["calendar", "event", "schedule", "meeting", "reminder", "timer"]):
            cats.append("time")
        if any(w in text for w in ["note", "document", "file"]):
            cats.append("notes")
        if any(w in text for w in ["memory", "remember", "recall", "episode"]):
            cats.append("memory")
        if any(w in text for w in ["search", "web", "look up", "research", "find online"]):
            cats.append("web")
        if any(w in text for w in ["home", "light", "thermostat", "door", "lock"]):
            cats.append("home")
        if any(w in text for w in ["fitness", "workout", "exercise", "food", "meal", "calorie"]):
            cats.append("fitness")
        if any(w in text for w in ["learn", "study", "course", "topic"]):
            cats.append("learning")
        # Default to email if nothing matched (most common agent task)
        return cats if cats else ["email"]

    def _looks_like_question(self, text: str) -> bool:
        """Heuristic: does the agent output look like it's asking a question?"""
        if not text:
            return False
        lines = text.strip().split("\n")
        last_lines = " ".join(lines[-3:]).lower()
        question_indicators = ["?", "please provide", "could you", "what should",
                               "which option", "do you want", "shall i"]
        return any(ind in last_lines for ind in question_indicators)

    async def _create_result_note(
        self, db: Session, user_id: str, task_description: str, output: str,
    ) -> Optional[str]:
        """Create a note in the Agent Workspace folder with the task result."""
        try:
            from app.services.background_task_service import background_task_service

            folder = await background_task_service._ensure_workspace_folder(db, user_id)
            from app.models.note import Note

            note_id = str(uuid.uuid4())
            note = Note(
                id=note_id,
                user_id=user_id,
                title=f"Agent Result: {task_description[:80]}",
                content=f"# Agent Task Result\n\n**Task:** {task_description}\n\n---\n\n{output}",
                folder_id=folder.id if folder else None,
            )
            db.add(note)
            db.commit()
            return note_id
        except Exception as e:
            logger.warning(f"Failed to create result note: {e}")
            return None

    async def _emit_progress(
        self, user_id: str, task_id: str, status: str,
        summary: str = "", extra: dict = None,
    ):
        """Emit an AGENT_TASK_PROGRESS event on the event bus."""
        try:
            payload = {"task_id": task_id, "status": status, "summary": summary}
            if extra:
                payload.update(extra)
            await event_bus.publish(Event(
                event_type=EventType.AGENT_TASK_PROGRESS,
                user_id=user_id,
                payload=payload,
                source="agent_dispatch",
            ))
        except Exception as e:
            logger.debug(f"[dispatch] Failed to emit progress event: {e}")

    async def _notify_completion(
        self, user_id: str, task_id: str, task_description: str,
        output: str, notify_on_complete: bool,
    ):
        """Send a completion notification via unified notification pipeline."""
        if not notify_on_complete:
            return
        try:
            from app.services.unified_notification import send_notification

            # Truncate output for the notification body
            body = output[:500]
            if len(output) > 500:
                body += "..."

            await send_notification(
                user_id=user_id,
                title=f"Done: {task_description[:80]}",
                message=body,
                category="agent_task",
                topic=f"agent_task:{task_id}",
                source="agent_dispatch",
                priority="normal",
            )
        except Exception as e:
            logger.warning(f"[dispatch] Failed to send completion notification: {e}")

    async def _notify(self, user_id: str, task_id: str, status: str, message: str):
        """Send a notification about task status."""
        try:
            from app.services.notification_service import notification_service

            await notification_service.send_notification(
                user_id=user_id,
                title="Agent Task Update",
                message=message,
                data={"task_id": task_id, "status": status},
            )
        except Exception as e:
            logger.warning(f"Failed to send agent task notification: {e}")

    def _task_to_dict(self, task, include_output: bool = False) -> dict:
        meta = task.task_metadata or {}
        result = {
            "id": task.id,
            "status": task.status,
            "task_type": task.task_type,
            "query": task.original_query,
            "mode": meta.get("mode", "unknown"),
            "session_id": meta.get("session_id"),
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "updated_at": task.updated_at.isoformat() if getattr(task, "updated_at", None) else None,
            "result_note_id": getattr(task, "result_note_id", None),
        }
        if task.status == "needs_clarification":
            result["clarification_question"] = getattr(task, "clarification_question", None)
        if include_output:
            result["output"] = meta.get("output", meta.get("last_resume_output", ""))
            result["working_directory"] = meta.get("working_directory")
            result["exit_code"] = meta.get("exit_code")
            result["found_items"] = meta.get("found_items", [])
        return result

    # ── Skill Learning ────────────────────────────────────────────────

    def _find_relevant_skills(
        self, db: Session, user_id: str, task_description: str, limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """Query CandidateSkill table for skills relevant to a task description.

        Uses simple ILIKE text matching with key terms extracted from the task.
        Returns up to `limit` matching skills ordered by times_succeeded desc.
        """
        try:
            from app.models.candidate_skill import CandidateSkill
            from sqlalchemy import or_, func

            # Extract meaningful keywords (3+ chars, skip common words)
            stop_words = {
                "the", "and", "for", "that", "this", "with", "from", "are",
                "was", "were", "been", "have", "has", "had", "not", "but",
                "what", "all", "can", "her", "his", "one", "our", "out",
                "you", "your", "about", "could", "would", "should", "please",
                "need", "want", "like", "into", "also", "just", "than",
                "then", "them", "when", "will", "more", "some", "very",
            }
            words = re.findall(r'\b[a-zA-Z]{3,}\b', task_description.lower())
            keywords = [w for w in words if w not in stop_words][:10]

            if not keywords:
                return []

            # Build ILIKE conditions against name, description, and instructions
            conditions = []
            for kw in keywords:
                pattern = f"%{kw}%"
                conditions.append(CandidateSkill.name.ilike(pattern))
                conditions.append(CandidateSkill.description.ilike(pattern))

            skills = (
                db.query(CandidateSkill)
                .filter(
                    CandidateSkill.user_id == user_id,
                    CandidateSkill.status.in_(["pending", "approved", "accepted"]),
                    or_(*conditions),
                )
                .order_by(CandidateSkill.times_succeeded.desc(), CandidateSkill.created_at.desc())
                .limit(limit)
                .all()
            )

            result = []
            for s in skills:
                result.append({
                    "skill_id": s.id,
                    "name": s.name,
                    "description": s.description or "",
                    "instructions": s.instructions or "",
                    "times_used": s.times_used or 0,
                    "times_succeeded": s.times_succeeded or 0,
                })

            if result:
                logger.info(
                    f"[dispatch] Found {len(result)} relevant skills for task: "
                    f"{[s['name'] for s in result]}"
                )

            return result

        except Exception as e:
            logger.warning(f"[dispatch] Failed to find relevant skills: {e}")
            return []

    async def _extract_skill_recipe(
        self,
        db: Session,
        user_id: str,
        task_id: str,
        task_description: str,
        output: str,
        mode: str,
        elapsed_seconds: float,
    ):
        """Extract a reusable skill recipe from a successfully completed task.

        Fires after task completion. Uses a lightweight LLM call to analyze
        the task + result and extract a structured skill if the work is
        non-trivial and reusable.

        Skipped for tasks that took < 30 seconds (trivial tasks).

        This method owns the provided db session and will close it on exit.
        """
        if elapsed_seconds < 30:
            logger.debug(
                f"[dispatch] Skipping skill extraction for task {task_id}: "
                f"elapsed {elapsed_seconds:.0f}s < 30s threshold"
            )
            db.close()
            return

        try:
            from app.core.llm import get_background_llm_client
            from app.models.candidate_skill import CandidateSkill

            llm = get_background_llm_client()

            prompt = f"""Analyze this completed agent task and extract a reusable skill recipe.

TASK DESCRIPTION:
{task_description[:1000]}

TASK OUTPUT (summary):
{output[:1500]}

EXECUTION MODE: {mode}

If this task represents a reusable pattern (not a one-off personal query), extract a skill recipe.
If the task is too specific/personal to be reusable, respond with {{"skip": true}}.

Respond with ONLY a JSON object:
{{
  "skip": false,
  "name": "kebab-case-skill-name",
  "description": "One-line description of what this skill does",
  "instructions": "Step-by-step markdown instructions for replicating this approach",
  "contexts": ["agent_dispatch", "sandbox"]
}}

Rules:
- name must be kebab-case, 2-5 words
- description must be under 100 characters
- instructions should be concise markdown (under 500 chars)
- contexts: list of where this skill applies (e.g. "agent_dispatch", "sandbox", "internal", "deliberation")
- Skip if the task was just answering a question, looking up a specific fact, or checking status"""

            result = await llm.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=600,
            )

            content = result["choices"][0]["message"].get("content", "").strip()

            # Parse JSON (handle markdown code blocks)
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            parsed = json.loads(content)

            if parsed.get("skip"):
                logger.debug(f"[dispatch] Skill extraction skipped for task {task_id}: LLM deemed not reusable")
                return

            skill_name = parsed.get("name", "")
            if not skill_name or len(skill_name) < 3:
                logger.debug(f"[dispatch] Skill extraction skipped: invalid name '{skill_name}'")
                return

            # Check for duplicate skill names
            existing = db.query(CandidateSkill).filter(
                CandidateSkill.user_id == user_id,
                CandidateSkill.name == skill_name,
            ).first()
            if existing:
                logger.debug(f"[dispatch] Skill '{skill_name}' already exists (id={existing.id}), skipping")
                return

            skill = CandidateSkill(
                id=str(uuid.uuid4()),
                user_id=user_id,
                name=skill_name,
                description=(parsed.get("description") or "")[:500],
                instructions=(parsed.get("instructions") or "")[:2000],
                contexts=parsed.get("contexts", []),
                source_task_id=task_id,
                status="pending",
                times_used=0,
                times_succeeded=0,
            )
            db.add(skill)
            db.commit()

            logger.info(
                f"[dispatch] Extracted skill '{skill_name}' from task {task_id} "
                f"(elapsed={elapsed_seconds:.0f}s)"
            )

        except json.JSONDecodeError as e:
            logger.debug(f"[dispatch] Skill extraction JSON parse failed: {e}")
        except Exception as e:
            logger.warning(f"[dispatch] Skill extraction failed for task {task_id}: {e}")
        finally:
            try:
                db.close()
            except Exception:
                pass

    def _track_skill_usage(
        self,
        db: Session,
        skill_ids: List[str],
        succeeded: bool,
    ):
        """Update usage counters on skills that were used as context for a task.

        Called after task completion to track which skills are actually helpful.
        """
        if not skill_ids:
            return

        try:
            from app.models.candidate_skill import CandidateSkill

            for skill_id in skill_ids:
                skill = db.query(CandidateSkill).filter(
                    CandidateSkill.id == skill_id,
                ).first()
                if skill:
                    skill.times_used = (skill.times_used or 0) + 1
                    if succeeded:
                        skill.times_succeeded = (skill.times_succeeded or 0) + 1

            db.commit()
            logger.debug(
                f"[dispatch] Updated skill usage for {len(skill_ids)} skills "
                f"(succeeded={succeeded})"
            )
        except Exception as e:
            logger.warning(f"[dispatch] Failed to track skill usage: {e}")

    @staticmethod
    def _format_skills_for_prompt(skills: List[Dict[str, Any]]) -> str:
        """Format relevant skills as a prompt section for injection into orchestrator/agent prompts."""
        if not skills:
            return ""

        lines = ["\n## Previous Successful Approaches\n"]
        lines.append("The following skill recipes from past successful tasks may be relevant:\n")
        for i, s in enumerate(skills, 1):
            success_rate = ""
            if s["times_used"] > 0:
                rate = s["times_succeeded"] / s["times_used"] * 100
                success_rate = f" (success rate: {rate:.0f}%, used {s['times_used']}x)"
            lines.append(f"### {i}. {s['name']}{success_rate}")
            if s["description"]:
                lines.append(f"_{s['description']}_\n")
            if s["instructions"]:
                lines.append(s["instructions"])
            lines.append("")

        lines.append(
            "Consider these approaches but adapt as needed for the current task.\n"
        )
        return "\n".join(lines)


# Singleton
agent_dispatch_service = AgentDispatchService()
