"""
Research Executor — drives the research agent through a plan step by step.

For each step:
1. Build fresh context (system prompt + step instructions + prior findings)
2. Enter tool-calling loop with the research LLM
3. Handle tool calls (web search, file I/O, shell, ask_sara, report_findings)
4. Store findings and advance to next step
5. If agent asks Sara, pause and wait for her answer
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.services.research.llm_client import ResearchLLMClient
from app.services.research.tools import RESEARCH_TOOLS, execute_tool
from app.services.research.context import (
    build_step_context,
    build_sara_answer_context,
)

logger = logging.getLogger(__name__)

# Limits
MAX_TOOL_TURNS_PER_STEP = 30
SARA_ANSWER_POLL_INTERVAL = 30  # seconds
SARA_ANSWER_TIMEOUT = 3600  # 1 hour max wait


class ResearchExecutor:
    """Executes a research plan step by step using the research LLM."""

    def __init__(self, plan_id: str, user_id: str):
        self.plan_id = plan_id
        self.user_id = user_id
        self.llm = ResearchLLMClient()
        self.total_tokens = 0

    async def run(self):
        """Execute the full research plan."""
        from app.db.session import get_db

        db = next(get_db())

        try:
            # Load the plan
            plan = await self._load_plan(db)
            if not plan:
                logger.error("Research plan %s not found", self.plan_id)
                return

            # Update status to running
            await self._update_plan_status(db, "running", started_at=datetime.now(timezone.utc))
            logger.info("Starting research plan: %s (%s)", plan["title"], self.plan_id)

            steps = plan.get("steps", [])
            current_index = plan.get("current_step_index", 0)

            while current_index < len(steps):
                step = steps[current_index]

                # Skip completed steps
                if step.get("status") == "complete":
                    current_index += 1
                    continue

                logger.info(
                    "Executing step %d/%d: %s",
                    current_index + 1,
                    len(steps),
                    step.get("title", "Untitled"),
                )

                # Mark step as running
                step["status"] = "running"
                await self._update_plan_steps(db, steps, current_index)

                # Execute the step
                result = await self._execute_step(db, plan, current_index)

                if result["action"] == "complete":
                    # Store findings in the step
                    step["status"] = "complete"
                    step["findings"] = result.get("findings", {})
                    await self._update_plan_steps(db, steps, current_index + 1)

                    # Handle substeps — insert them after current step
                    substeps = result.get("findings", {}).get("substeps_needed", [])
                    if substeps:
                        new_steps = []
                        for sub in substeps:
                            new_steps.append({
                                "title": sub.get("title", "Subtopic"),
                                "description": sub.get("description", ""),
                                "instructions": sub.get("description", ""),
                                "status": "pending",
                                "findings": {},
                                "parent_step": current_index,
                            })
                        # Insert substeps after current step
                        for i, ns in enumerate(new_steps):
                            steps.insert(current_index + 1 + i, ns)
                        await self._update_plan_steps(db, steps, current_index + 1)
                        logger.info(
                            "Step decomposed into %d substeps", len(new_steps)
                        )

                    current_index += 1

                elif result["action"] == "stuck":
                    # Agent asked Sara — wait for her answer, then retry
                    step["status"] = "stuck"
                    await self._update_plan_steps(db, steps, current_index)
                    await self._update_plan_status(db, "stuck")

                    answer = await self._wait_for_sara_answer(db, result["message_id"])

                    if answer:
                        # Sara answered — retry the step with her guidance
                        step["status"] = "pending"
                        step.setdefault("sara_answers", []).append({
                            "question": result.get("question", ""),
                            "answer": answer,
                        })
                        await self._update_plan_steps(db, steps, current_index)
                        await self._update_plan_status(db, "running")
                        # Don't increment — retry this step
                    else:
                        # Timeout waiting for Sara — mark as stuck and stop
                        logger.warning("Timed out waiting for Sara's answer")
                        await self._update_plan_status(db, "stuck")
                        return

                elif result["action"] == "error":
                    step["status"] = "failed"
                    step["error"] = result.get("error", "Unknown error")
                    await self._update_plan_steps(db, steps, current_index)
                    logger.error("Step failed: %s", result.get("error"))
                    # Continue to next step on error
                    current_index += 1

                # Reload plan in case it was modified externally (e.g., paused)
                plan = await self._load_plan(db)
                if not plan or plan["status"] in ("paused", "failed"):
                    logger.info("Plan was externally paused/stopped")
                    return

                steps = plan.get("steps", [])

            # All steps complete — synthesize findings. _synthesize_findings
            # reopens its own fresh session for its writes; refresh here too so
            # the final status update doesn't ride a connection the long step
            # loop already let go stale.
            await self._synthesize_findings(db, plan)
            db = self._reopen(db)
            await self._update_plan_status(
                db, "complete", completed_at=datetime.now(timezone.utc)
            )
            logger.info("Research plan complete: %s", plan["title"])

        except Exception as e:
            logger.error("Research executor error: %s", e, exc_info=True)
            # Persist the failure on a guaranteed-fresh session — the working
            # one may be the very thing that broke.
            try:
                db = self._reopen(db)
                await self._update_plan_status(db, "failed", error=str(e))
            except Exception as e2:
                logger.error("Could not persist failed status: %s", e2)
        finally:
            await self.llm.close()
            try:
                db.close()
            except Exception:
                pass

    @staticmethod
    def _reopen(db):
        """Close a possibly-stale session and return a fresh one.

        Research runs span many minutes (web search + LLM per step), long
        enough for Postgres to close an idle connection. Any DB write that
        happens after a long no-DB stretch must run on a fresh session.
        """
        from app.db.session import get_db
        try:
            db.close()
        except Exception:
            pass
        return next(get_db())

    async def _execute_step(
        self,
        db,
        plan: Dict[str, Any],
        step_index: int,
    ) -> Dict[str, Any]:
        """
        Execute a single research step using the tool-calling loop.

        Returns:
            {"action": "complete", "findings": {...}}
            {"action": "stuck", "question": "...", "message_id": "..."}
            {"action": "error", "error": "..."}
        """
        # Gather prior findings
        steps = plan.get("steps", [])
        prior_findings = []
        for i in range(step_index):
            s = steps[i]
            if s.get("status") == "complete" and s.get("findings"):
                prior_findings.append({
                    "title": s.get("title", f"Step {i + 1}"),
                    "summary": s["findings"].get("summary", ""),
                })

        # Gather Sara's answers for this step
        sara_answers = steps[step_index].get("sara_answers", [])

        # Build fresh context
        messages = build_step_context(plan, step_index, prior_findings, sara_answers)

        # Tool-calling loop
        for turn in range(MAX_TOOL_TURNS_PER_STEP):
            try:
                response = await self.llm.chat_completion(
                    messages=messages,
                    tools=RESEARCH_TOOLS,
                    temperature=0.7,
                )
            except Exception as e:
                return {"action": "error", "error": f"LLM error: {e}"}

            # Track tokens
            usage = self.llm.get_token_usage(response)
            self.total_tokens += usage.get("total_tokens", 0)

            # Get the assistant's message
            msg = self.llm.get_message(response)
            tool_calls = msg.get("tool_calls", [])

            # Append assistant message to conversation
            messages.append(msg)

            if not tool_calls:
                # No tool calls — the agent is done talking
                text_content = msg.get("content", "")
                if text_content:
                    logger.debug("Agent text (no tools): %s", text_content[:200])
                # If no tool calls and no report_findings, prompt for action
                if turn > 0:
                    return {
                        "action": "complete",
                        "findings": {
                            "summary": text_content[:500] if text_content else "Step completed without explicit findings",
                            "details": text_content or "",
                            "sources": [],
                            "confidence": 0.5,
                        },
                    }
                # First turn with no tools — ask for action
                messages.append({
                    "role": "user",
                    "content": "Please use the available tools to research this topic. Start with web_search to find relevant sources.",
                })
                continue

            # Process tool calls
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                try:
                    func_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    func_args = {}

                logger.info("Tool call: %s(%s)", func_name, json.dumps(func_args)[:200])

                # Handle special sentinel tools
                if func_name == "ask_sara":
                    question = func_args.get("question", "")
                    message_id = await self._create_sara_question(
                        db, step_index, question
                    )
                    return {
                        "action": "stuck",
                        "question": question,
                        "message_id": message_id,
                    }

                if func_name == "report_findings":
                    return {
                        "action": "complete",
                        "findings": {
                            "summary": func_args.get("summary", ""),
                            "details": func_args.get("details", ""),
                            "sources": func_args.get("sources", []),
                            "confidence": func_args.get("confidence", 0.7),
                            "substeps_needed": func_args.get("substeps_needed", []),
                        },
                    }

                # Execute the tool
                result = await execute_tool(func_name, func_args, self.plan_id)

                # Append tool result to conversation
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        # Exhausted turns
        return {
            "action": "complete",
            "findings": {
                "summary": "Step reached maximum turns without explicit findings report",
                "details": "The agent used all available turns. Review files in the working directory for partial results.",
                "sources": [],
                "confidence": 0.3,
            },
        }

    async def _create_sara_question(
        self, db, step_index: int, question: str
    ) -> str:
        """Create a research_message for Sara to answer."""
        msg_id = str(uuid.uuid4())

        db.execute(
            text("""
                INSERT INTO research_message (id, plan_id, direction, content, step_index, status)
                VALUES (:id, :plan_id, 'agent_to_sara', :content, :step_index, 'pending')
            """),
            {
                "id": msg_id,
                "plan_id": self.plan_id,
                "content": question,
                "step_index": step_index,
            },
        )
        db.commit()

        # Immediately dispatch Sara to answer via Celery
        try:
            from app.tasks.research import answer_research_question
            answer_research_question.delay(msg_id, self.plan_id)
        except Exception as e:
            logger.warning("Failed to dispatch Sara answer task: %s", e)

        logger.info("Agent asked Sara: %s", question[:200])
        return msg_id

    async def _wait_for_sara_answer(
        self, db, message_id: str
    ) -> Optional[str]:
        """Poll for Sara's answer to a research message."""
        elapsed = 0

        while elapsed < SARA_ANSWER_TIMEOUT:
            await asyncio.sleep(SARA_ANSWER_POLL_INTERVAL)
            elapsed += SARA_ANSWER_POLL_INTERVAL

            result = db.execute(
                text("""
                    SELECT rm.content, rm.status
                    FROM research_message rm
                    WHERE rm.id = :msg_id
                """),
                {"msg_id": message_id},
            )
            row = result.fetchone()

            if row and row.status == "answered":
                # Find Sara's reply
                reply_result = db.execute(
                    text("""
                        SELECT content FROM research_message
                        WHERE plan_id = :plan_id
                          AND direction = 'sara_to_agent'
                          AND step_index = (
                              SELECT step_index FROM research_message WHERE id = :msg_id
                          )
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {"plan_id": self.plan_id, "msg_id": message_id},
                )
                reply_row = reply_result.fetchone()
                if reply_row:
                    return reply_row.content

            # Also check if plan was paused/cancelled
            plan = await self._load_plan(db)
            if plan and plan["status"] in ("paused", "failed"):
                return None

        return None

    async def _synthesize_findings(self, db, plan: Dict[str, Any]):
        """Use the research LLM to create a final synthesis of all findings."""
        steps = plan.get("steps", [])
        completed = [s for s in steps if s.get("status") == "complete" and s.get("findings")]

        if not completed:
            return

        synthesis_prompt = f"""You just completed a research plan titled "{plan['title']}".

**Objective:** {plan['objective']}

## Findings by Step
"""
        for i, s in enumerate(completed):
            findings = s["findings"]
            synthesis_prompt += f"\n### {s.get('title', f'Step {i+1}')}\n"
            synthesis_prompt += f"{findings.get('summary', 'No summary')}\n"
            if findings.get("sources"):
                synthesis_prompt += "Sources: " + ", ".join(findings["sources"][:5]) + "\n"

        synthesis_prompt += """
---
Please write a comprehensive summary that synthesizes all findings into a cohesive document.
Include key takeaways, connections between topics, and actionable conclusions.
Write in clean markdown format."""

        try:
            response = await self.llm.chat_completion(
                messages=[
                    {"role": "system", "content": "You are a research synthesis agent. Create clear, comprehensive summaries."},
                    {"role": "user", "content": synthesis_prompt},
                ],
                temperature=0.5,
                max_tokens=4096,
            )
            synthesis = self.llm.get_text(response)

            # The step loop + this synthesis call can span many minutes — long
            # enough for Postgres to drop our connection. Reopen a fresh session
            # for the writes so completed research is never lost to a stale
            # connection (the IRMI brief failed at exactly this commit).
            db = self._reopen(db)

            db.execute(
                text("""
                    UPDATE research_plan
                    SET findings_summary = :summary,
                        total_tokens_used = :tokens
                    WHERE id = :plan_id
                """),
                {
                    "plan_id": self.plan_id,
                    "summary": synthesis,
                    "tokens": self.total_tokens,
                },
            )
            db.commit()

            # Also write to file
            from app.services.research.tools import get_work_dir

            work_dir = get_work_dir(self.plan_id)
            with open(f"{work_dir}/SYNTHESIS.md", "w") as f:
                f.write(f"# {plan['title']}\n\n")
                f.write(synthesis)

            # Save as a note in the Research > Agent Reports folder
            await self._save_as_note(db, plan, synthesis, completed)

        except Exception as e:
            logger.error("Failed to synthesize findings: %s", e)

    async def _save_as_note(
        self, db, plan: Dict[str, Any], synthesis: str, completed_steps: list
    ):
        """Save the final research report as a note."""
        try:
            # Find the Agent Reports folder
            result = db.execute(
                text("""
                    SELECT id FROM folder
                    WHERE user_id = :user_id AND name = 'Agent Reports'
                    LIMIT 1
                """),
                {"user_id": self.user_id},
            )
            folder_row = result.fetchone()
            folder_id = folder_row.id if folder_row else None

            # Build note content
            content = f"# {plan['title']}\n\n"
            content += f"**Objective:** {plan['objective']}\n\n"
            content += f"**Model:** {plan.get('model_id', 'Unknown')} | "
            content += f"**Tokens:** {self.total_tokens:,}\n\n"
            content += "---\n\n"
            content += synthesis
            content += "\n\n---\n\n## Step-by-Step Findings\n\n"

            for i, s in enumerate(completed_steps):
                findings = s.get("findings", {})
                content += f"### {s.get('title', f'Step {i+1}')}\n\n"
                content += f"{findings.get('details', findings.get('summary', 'No details'))}\n\n"
                sources = findings.get("sources", [])
                if sources:
                    content += "**Sources:**\n"
                    for src in sources:
                        content += f"- {src}\n"
                    content += "\n"

            note_id = str(uuid.uuid4())
            note_title = f"Research: {plan['title']}"
            db.execute(
                text("""
                    INSERT INTO note (id, user_id, folder_id, title, content, created_at, updated_at)
                    VALUES (:id, :user_id, :folder_id, :title, :content, NOW(), NOW())
                """),
                {
                    "id": note_id,
                    "user_id": self.user_id,
                    "folder_id": folder_id,
                    "title": note_title,
                    "content": content,
                },
            )
            db.commit()
            logger.info("Saved research note %s in Agent Reports folder", note_id)

            # Notify David — only for chat-initiated plans. ACS-internal research
            # is silent because it lands in the autonomous report flow already.
            if plan.get("origin") == "david_chat":
                await self._send_completion_push(plan, note_id, note_title, synthesis)

        except Exception as e:
            logger.error("Failed to save research note: %s", e)

    async def _send_completion_push(
        self, plan: Dict[str, Any], note_id: str, note_title: str, synthesis: str
    ):
        """Push a 'Research ready' notification with deep-link data to the note."""
        try:
            from app.services.notification_service import notification_service, NotificationPriority

            # Body = first paragraph of synthesis, trimmed for the lock screen.
            body = (synthesis or "").strip().split("\n\n", 1)[0]
            body = body.replace("# ", "").replace("## ", "").strip()
            if len(body) > 240:
                body = body[:237].rstrip() + "..."
            if not body:
                body = f"Your research on {plan.get('title', 'the topic')} is ready."

            await notification_service.send_notification(
                user_id=self.user_id,
                title=f"Research ready: {plan.get('title', 'Untitled')}",
                message=body,
                priority=NotificationPriority.NORMAL,
                data={
                    "type": "research_complete",
                    "note_id": note_id,
                    "note_title": note_title,
                    "plan_id": self.plan_id,
                },
                category="research_complete",
                source="research_executor",
            )
            logger.info("Sent research_complete push for plan %s → note %s", self.plan_id, note_id)
            await self._dual_write_candidate(plan, note_id, body, synthesis)
        except Exception as e:
            logger.warning("Failed to send research completion push: %s", e)

    async def _dual_write_candidate(
        self, plan: Dict[str, Any], note_id: str, body: Optional[str], synthesis: str
    ) -> None:
        """Mind V2 rewire plan Workstream B.4 — feed the say_candidate queue
        with the same real content the legacy push above already delivers.
        research_plan has no direct event link, so valid_until is best-
        effort: the nearest upcoming calendar event whose title overlaps
        this research's title (the Phxins/JFK-prep evidence class — research
        done FOR a meeting is worthless after it), else the 'inform' kind's
        default 24h TTL. Wrapped so a candidate-queue failure never breaks
        the legacy push while it's still the delivery path."""
        try:
            from app.services.say_candidate import create_candidate
            from app.db.session import get_async_session_factory

            summary = (body or (synthesis or "").strip().split("\n\n", 1)[0] or
                       f"Research on {plan.get('title', 'the topic')} is ready.")

            factory = get_async_session_factory()
            valid_until = None
            async with factory() as db:
                title_words = {w.lower() for w in (plan.get("title") or "").split() if len(w) > 3}
                if title_words:
                    rows = (await db.execute(text("""
                        SELECT title, start_time FROM calendar_event
                        WHERE user_id = :uid AND start_time BETWEEN NOW() AND NOW() + INTERVAL '7 days'
                          AND COALESCE(all_day, FALSE) = FALSE
                        ORDER BY start_time ASC LIMIT 20
                    """), {"uid": self.user_id})).fetchall()
                    for r in rows:
                        event_words = {w.lower() for w in (r.title or "").split() if len(w) > 3}
                        if title_words & event_words:
                            from app.core.timezone import to_utc
                            valid_until = to_utc(r.start_time)
                            break

                await create_candidate(
                    db, user_id=self.user_id, source="research_executor", kind="inform",
                    summary=summary[:2000],
                    evidence=[{"note_id": note_id, "plan_id": self.plan_id}],
                    topic_entities=[f"research:{self.plan_id}"],
                    valid_until=valid_until,
                    dedupe_key=f"research:{self.plan_id}",
                )
        except Exception as e:
            logger.warning("[say_candidate] research_executor dual-write failed: %s", e)

    async def _load_plan(self, db) -> Optional[Dict[str, Any]]:
        """Load the research plan from DB."""
        result = db.execute(
            text("SELECT * FROM research_plan WHERE id = :id"),
            {"id": self.plan_id},
        )
        row = result.fetchone()
        if not row:
            return None

        plan = dict(row._mapping)

        # Parse JSONB fields that might be strings
        if isinstance(plan.get("steps"), str):
            plan["steps"] = json.loads(plan["steps"])

        return plan

    async def _update_plan_status(
        self,
        db,
        status: str,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        error: Optional[str] = None,
    ):
        """Update plan status and optional timestamps."""
        params: Dict[str, Any] = {
            "plan_id": self.plan_id,
            "status": status,
            "tokens": self.total_tokens,
        }

        set_parts = ["status = :status", "total_tokens_used = :tokens", "updated_at = NOW()"]

        if started_at:
            set_parts.append("started_at = :started_at")
            params["started_at"] = started_at

        if completed_at:
            set_parts.append("completed_at = :completed_at")
            params["completed_at"] = completed_at

        if error:
            set_parts.append("error_log = :error")
            params["error"] = error

        db.execute(
            text(f"UPDATE research_plan SET {', '.join(set_parts)} WHERE id = :plan_id"),
            params,
        )
        db.commit()

    async def _update_plan_steps(
        self, db, steps: List[Dict[str, Any]], current_index: int
    ):
        """Update the plan's steps JSONB and current step index."""
        db.execute(
            text("""
                UPDATE research_plan
                SET steps = CAST(:steps AS jsonb),
                    current_step_index = :idx,
                    updated_at = NOW()
                WHERE id = :plan_id
            """),
            {
                "plan_id": self.plan_id,
                "steps": json.dumps(steps),
                "idx": current_index,
            },
        )
        db.commit()
