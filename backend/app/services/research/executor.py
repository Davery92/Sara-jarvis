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

from app.services.note_provenance import SARA_GENERATED_TAG
from app.services.research.llm_client import ResearchLLMClient, ResearchLLMOverloaded
from app.services.research.lane_lock import LaneLock
from app.services.research.compaction import (
    compact_messages,
    estimate_tokens,
    truncate_tool_result,
)
from app.services.research.tools import RESEARCH_TOOLS, execute_tool
from app.services.research.context import (
    build_step_context,
    build_sara_answer_context,
)

logger = logging.getLogger(__name__)

# Limits
MAX_TOOL_TURNS_PER_STEP = 30

# Tool list used on a step's final turn. llama-server IGNORES a named
# `tool_choice` (verified against :8081 — asked for report_findings, it returned
# web_search anyway), so the only reliable way to make the agent file its
# findings is to take every other tool away for that turn.
_REPORT_ONLY_TOOLS = [
    t for t in RESEARCH_TOOLS
    if t.get("function", {}).get("name") == "report_findings"
]

# Fraction of the lane's context window the transcript may occupy before we compact.
# The remainder absorbs the RESEARCH_TOOLS schemas, the model's reply, and the slack
# between our chars/4 estimate and the real tokenizer.
CONTEXT_BUDGET_FRACTION = 0.55


def _context_budget_tokens() -> int:
    """Token budget for the step transcript, derived from the configured window.

    Read at call time rather than import time so a settings change (or a lane
    resize) takes effect without a code change.
    """
    from app.core.config import settings
    num_ctx = getattr(settings, "bg_llm_num_ctx", None) or 32768
    return max(8000, int(num_ctx * CONTEXT_BUDGET_FRACTION))
SARA_ANSWER_POLL_INTERVAL = 30  # seconds
SARA_ANSWER_TIMEOUT = 3600  # 1 hour max wait

# How long to wait before retrying a plan parked on a sick LLM lane, and how
# long to wait for the lane lock when another plan already holds it.
STALL_RESUME_DELAY = 900   # 15 min
LANE_BUSY_RETRY_DELAY = 120  # 2 min

# Two consecutive step failures for a reason that isn't the lane means something
# is structurally wrong with the plan. Stop and report honestly instead of
# marching through the remaining steps at machine speed and calling it complete.
MAX_CONSECUTIVE_STEP_ERRORS = 2

# Plan statuses that mean "stop, someone else changed this out from under us".
_EXTERNAL_STOP_STATUSES = ("paused", "failed", "cancelled")


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
        lock = LaneLock(self.user_id, self.plan_id)
        last_error: Optional[str] = None
        consecutive_errors = 0
        plan: Dict[str, Any] = {}

        try:
            # Load the plan
            plan = await self._load_plan(db)
            if not plan:
                logger.error("Research plan %s not found", self.plan_id)
                return

            if plan.get("status") in _EXTERNAL_STOP_STATUSES:
                logger.info(
                    "Research plan %s is %s — not starting", self.plan_id, plan.get("status")
                )
                return

            # One research agent on the lane at a time. A second acquirer waits
            # its turn rather than executing — two agents against the bg lane is
            # what OOM'd it into 507s and destroyed three plans (2026-09-01).
            if not await lock.acquire():
                self._requeue(LANE_BUSY_RETRY_DELAY, reason="lane busy")
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
                self._emit_task_event(
                    db,
                    "task.started" if current_index == 0 else "task.progressed",
                    "running",
                    plan.get("title", "Research"),
                    status_label=(
                        f"Step {current_index + 1} of {len(steps)}"
                        f" — {step.get('title', '')}".rstrip(" —")
                    ),
                    step_count=current_index + 1,
                )

                # Execute the step
                result = await self._execute_step(db, plan, current_index)

                if result["action"] == "lane_down":
                    # The LLM lane is sick, not the plan. Park it exactly where
                    # it is — the current step goes back to pending so the
                    # resume retries it — and schedule one attempt later.
                    step["status"] = "pending"
                    await self._update_plan_steps(db, steps, current_index)
                    last_error = result.get("error")
                    db = self._reopen(db)
                    await self._update_plan_status(db, "stalled", error=last_error)
                    self._emit_task_event(
                        db, "task.failed", "stalled", plan.get("title", "Research"),
                        status_label=f"Paused at step {current_index + 1} — LLM lane unavailable",
                        step_count=current_index + 1, error=last_error,
                    )
                    self._requeue(STALL_RESUME_DELAY, reason="lane down", persist_db=db)
                    logger.error(
                        "Research plan %s stalled at step %d: %s",
                        self.plan_id, current_index + 1, last_error,
                    )
                    await self._send_failure_push(
                        plan, "stalled", current_index + 1, len(steps), last_error
                    )
                    return

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
                    consecutive_errors = 0

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
                    last_error = result.get("error", "Unknown error")
                    await self._update_plan_steps(db, steps, current_index)
                    logger.error("Step failed: %s", last_error)
                    consecutive_errors += 1
                    current_index += 1
                    if consecutive_errors >= MAX_CONSECUTIVE_STEP_ERRORS:
                        logger.error(
                            "Research plan %s: %d consecutive step failures — stopping "
                            "instead of burning the remaining steps",
                            self.plan_id, consecutive_errors,
                        )
                        break

                # Reload plan in case it was modified externally (paused,
                # cancelled from the phone, or hard-failed by the Celery task).
                plan = await self._load_plan(db)
                if not plan or plan["status"] in _EXTERNAL_STOP_STATUSES:
                    logger.info(
                        "Plan %s externally %s — stopping",
                        self.plan_id, (plan or {}).get("status", "removed"),
                    )
                    return

                steps = plan.get("steps", [])

            # Step loop is over — report what actually happened. This used to
            # unconditionally write 'complete', which is how a plan that burned
            # all six steps on instant 507s in 1.3 seconds was filed as a
            # success with zero output and no notification (2026-09-01).
            done = [s for s in steps if s.get("status") == "complete"]
            synthesis_ok = False
            if done:
                synthesis_ok = await self._synthesize_findings(db, plan)

            db = self._reopen(db)

            if steps and len(done) == len(steps) and synthesis_ok:
                terminal = "complete"
            elif done:
                terminal = "partial"
            else:
                terminal = "failed"

            await self._update_plan_status(
                db,
                terminal,
                completed_at=datetime.now(timezone.utc),
                error=(last_error if terminal != "complete" else None),
            )
            logger.info(
                "Research plan %s finished as '%s' (%d/%d steps complete%s)",
                plan.get("title"), terminal, len(done), len(steps),
                "" if synthesis_ok else ", synthesis failed",
            )

            self._emit_task_event(
                db,
                "task.completed" if terminal != "failed" else "task.failed",
                terminal,
                plan.get("title", "Research"),
                status_label=f"{len(done)} of {len(steps)} steps complete",
                step_count=len(steps) + 1,
                error=last_error if terminal == "failed" else None,
            )

            if terminal == "failed":
                await self._send_failure_push(
                    plan, "failed", len(done), len(steps), last_error
                )

        except Exception as e:
            logger.error(
                "Research executor error: %s: %s", type(e).__name__, e, exc_info=True
            )
            # Persist the failure on a guaranteed-fresh session — the working
            # one may be the very thing that broke.
            try:
                db = self._reopen(db)
                await self._update_plan_status(
                    db, "failed", error=f"{type(e).__name__}: {e}"
                )
                self._emit_task_event(
                    db, "task.failed", "failed", plan.get("title", "Research"),
                    status_label="Research failed",
                    step_count=0, error=f"{type(e).__name__}: {e}",
                )
            except Exception as e2:
                logger.error("Could not persist failed status: %s", e2)
            await self._send_failure_push(
                plan, "failed", 0, 0, f"{type(e).__name__}: {e}"
            )
        finally:
            await lock.release()
            await self.llm.close()
            try:
                db.close()
            except Exception:
                pass

    def _emit_task_event(
        self,
        db,
        kind: str,
        status: str,
        title: str,
        status_label: str = "",
        step_count: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """Publish a `task.*` world event for this plan.

        This is what makes a research plan drive the lock-screen Live Activity:
        the world reducer turns task.started/progressed into Sara's presence and
        presence_delivery pushes it to ActivityKit, ending the activity on
        task.completed / task.failed. agent_dispatch already emits exactly these
        for background_task rows — research plans were the one dispatch path
        that stayed dark when the app wasn't foregrounded.
        """
        try:
            from app.services.world_state.writer import append_world_event

            append_world_event(
                db,
                user_id=str(self.user_id),
                kind=kind,
                source="research_executor",
                source_ref=f"research_plan:{self.plan_id}",
                aggregate_type="research_plan",
                aggregate_id=str(self.plan_id),
                actor_type="assistant",
                actor_id="sara",
                correlation_id=str(self.plan_id),
                dedupe_key=f"research-progress:{self.plan_id}:{step_count}:{status}",
                payload={
                    "task_id": str(self.plan_id),
                    "status": status,
                    "status_label": status_label[:300],
                    "title": (title or "")[:500],
                    "original_query": (title or "")[:1000],
                    "task_type": "research_plan",
                    "step_count": step_count,
                    "error": (error or "")[:500] if error else None,
                },
            )
            db.commit()
        except Exception as e:
            # Presence is a nicety; never let it take down a research run.
            logger.warning(
                "Could not emit %s world event for plan %s: %s: %s",
                kind, self.plan_id, type(e).__name__, e,
            )
            try:
                db.rollback()
            except Exception:
                pass

    def _requeue(self, countdown: int, reason: str, persist_db=None) -> None:
        """Re-dispatch this plan after `countdown` seconds and remember the task id.

        Used both when the lane is busy and when a stalled plan gets its one
        scheduled resume attempt.
        """
        try:
            from app.tasks.research import run_research_plan
            async_result = run_research_plan.apply_async(
                args=[self.plan_id, self.user_id],
                queue="david_priority",
                countdown=countdown,
            )
            logger.info(
                "Requeued research plan %s in %ds (%s) as celery task %s",
                self.plan_id, countdown, reason, async_result.id,
            )
            db = persist_db
            owned = False
            if db is None:
                from app.db.session import get_db
                db = next(get_db())
                owned = True
            try:
                db.execute(
                    text("UPDATE research_plan SET celery_task_id = :tid WHERE id = :id"),
                    {"tid": async_result.id, "id": self.plan_id},
                )
                db.commit()
            finally:
                if owned:
                    db.close()
        except Exception as e:
            logger.error(
                "Could not requeue research plan %s (%s): %s: %s",
                self.plan_id, reason, type(e).__name__, e,
            )

    async def _send_failure_push(
        self,
        plan: Dict[str, Any],
        outcome: str,
        step_no: int,
        total_steps: int,
        error: Optional[str],
    ) -> None:
        """Tell David when research dies. Silence is what burned us: three plans
        were marked complete with no output and no notification, so 'completed'
        and 'failed' both have to be loud.

        Only for chat-initiated plans — autonomous research reports through its
        own flow and must not push.
        """
        if (plan or {}).get("origin") != "david_chat":
            return
        try:
            from app.services.unified_notification import send_notification

            title = (plan or {}).get("title") or "Research plan"
            if outcome == "stalled":
                headline = "Research paused"
                body = (
                    f"'{title}' stopped at step {step_no} of {total_steps} — the LLM "
                    f"lane is unavailable. I'll retry in "
                    f"{STALL_RESUME_DELAY // 60} minutes."
                )
            else:
                headline = "Research failed"
                progress = (
                    f"after {step_no} of {total_steps} steps"
                    if total_steps else "before it got anywhere"
                )
                body = f"'{title}' failed {progress}."
            if error:
                body += f" ({str(error)[:120]})"

            # 'high' or above is what actually reaches the phone — the attention
            # queue swallows normal-priority pushes.
            await send_notification(
                user_id=self.user_id,
                title=headline,
                message=body,
                priority="high",
                topic=f"research_failure:{self.plan_id}:{outcome}",
                category="general",
                source="research_executor",
                extra_push_data={
                    "type": "task_failed",
                    "plan_id": self.plan_id,
                    "outcome": outcome,
                },
            )
            logger.info("Sent research %s push for plan %s", outcome, self.plan_id)
        except Exception as e:
            logger.warning(
                "Could not send research %s push: %s: %s", outcome, type(e).__name__, e
            )

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
            {"action": "lane_down", "error": "..."}  — LLM lane unavailable;
                the caller stalls the whole plan rather than failing steps.
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

        # Tool-calling loop.
        # The cap is a runaway guard, but running into it silently used to throw
        # away every turn of real research and persist a confidence-0.3
        # placeholder. Warn before the end and force the agent to file findings
        # on the last turn, the same way InternalToolAgent does.
        warn_turn = max(0, MAX_TOOL_TURNS_PER_STEP - 3)
        final_turn = MAX_TOOL_TURNS_PER_STEP - 1
        query_counts: Dict[str, int] = {}
        consecutive_blocked_turns = 0

        for turn in range(MAX_TOOL_TURNS_PER_STEP):
            # Fold older turns into a digest before they push us over the window.
            # Without this the transcript grows unboundedly (10 search hits and whole
            # files per turn) and the step dies on a 400 part-way through.
            messages, did_compact = await compact_messages(
                messages, self.llm, _context_budget_tokens()
            )
            if did_compact:
                logger.info(
                    "Step %d: compacted context to ~%d tokens",
                    step_index + 1, estimate_tokens(messages),
                )

            if turn == warn_turn:
                messages.append({
                    "role": "user",
                    "content": (
                        f"You have {MAX_TOOL_TURNS_PER_STEP - turn} turns left on this "
                        "step. Stop searching and call report_findings NOW with what you "
                        "already have. A negative result is a valid finding: if the thing "
                        "you were asked to research does not appear to exist, report that "
                        "conclusion and cite what you found instead."
                    ),
                })

            # A model that keeps re-issuing queries the guard already blocked will
            # never break out on its own (observed live: 5 straight turns of the
            # same two blocked queries). Jump to the endgame instead of burning
            # the remaining turns.
            stuck_on_repeats = consecutive_blocked_turns >= 3
            if stuck_on_repeats:
                logger.warning(
                    "Step %d: %d consecutive fully-blocked turns — going to endgame early",
                    step_index + 1, consecutive_blocked_turns,
                )
            force_report = turn == final_turn or stuck_on_repeats
            turn_tools = RESEARCH_TOOLS
            if force_report and _REPORT_ONLY_TOOLS:
                turn_tools = _REPORT_ONLY_TOOLS
                logger.warning(
                    "Step %d: final turn — restricting tools to report_findings",
                    step_index + 1,
                )
                # Without this the model, seeing only one tool, reports "I don't
                # have web search capability" instead of summarizing the searches
                # it already ran.
                messages.append({
                    "role": "user",
                    "content": (
                        "This is your FINAL turn for this step. Call report_findings "
                        "now and summarize everything your earlier searches in this "
                        "step already returned. Do not claim you lack tools — you have "
                        "the results above. If the subject does not appear to exist, "
                        "that conclusion IS the finding; report it with the sources "
                        "that led you there."
                    ),
                })

            try:
                response = await self.llm.chat_completion(
                    messages=messages,
                    tools=turn_tools,
                    temperature=0.7,
                    tool_choice=(
                        {"type": "function", "function": {"name": "report_findings"}}
                        if force_report else None
                    ),
                )
            except ResearchLLMOverloaded as e:
                # The lane is out of memory / down, not the plan's fault. Bubble
                # up so the whole plan parks and resumes later with its
                # completed steps intact.
                logger.error(
                    "Step %d: research lane unavailable (%s)", step_index + 1, e
                )
                return {"action": "lane_down", "error": str(e)}
            except Exception as e:
                # Keep the class and the response body — a bare str(e) on an empty
                # exception used to persist as the useless literal "LLM error: ".
                detail = ""
                resp = getattr(e, "response", None)
                if resp is not None:
                    try:
                        detail = f" | body: {resp.text[:400]}"
                    except Exception:
                        pass
                err = f"LLM error: {type(e).__name__}: {e}{detail}"
                logger.error("Step %d failed: %s", step_index + 1, err)
                return {"action": "error", "error": err}

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
            calls_this_turn = 0
            blocked_this_turn = 0
            for tc in tool_calls:
                calls_this_turn += 1
                func_name = tc["function"]["name"]
                try:
                    func_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    func_args = {}

                logger.info(
                    "Step %d turn %d: %s(%s)",
                    step_index + 1, turn, func_name, json.dumps(func_args)[:200],
                )

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

                # Repetition guard. Steps that research something non-existent
                # (e.g. "FST-2") otherwise re-issue the same query verbatim until
                # the turn cap — 6+ identical searches in one step, observed.
                repeat_query = None
                if func_name == "web_search":
                    q = (func_args.get("query") or "").strip().lower()
                    if q:
                        query_counts[q] = query_counts.get(q, 0) + 1
                        if query_counts[q] >= 3:
                            repeat_query = func_args.get("query")

                if repeat_query is not None:
                    result = (
                        f'You have already searched "{repeat_query}" '
                        f"{query_counts[repeat_query.strip().lower()]} times in this step "
                        "and it returns the same results. Do not repeat it. Either change "
                        "your approach materially, or call report_findings now with what "
                        "you have — including a negative result if the subject does not "
                        "appear to exist."
                    )
                    blocked_this_turn += 1
                    logger.warning(
                        "Step %d turn %d: blocked repeated query %r",
                        step_index + 1, turn, repeat_query,
                    )
                else:
                    # Execute the tool
                    result = await execute_tool(func_name, func_args, self.plan_id)
                    logger.info(
                        "Step %d turn %d: %s -> %d chars | %s",
                        step_index + 1, turn, func_name, len(result or ""),
                        (result or "")[:160].replace("\n", " "),
                    )

                # Append tool result to conversation, capped — a single
                # web_search (10 hits) or read_file (whole file) is otherwise
                # large enough to blow the window on its own.
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": truncate_tool_result(result),
                })

            if calls_this_turn and blocked_this_turn == calls_this_turn:
                consecutive_blocked_turns += 1
            else:
                consecutive_blocked_turns = 0

        # Exhausted turns. With the forced report_findings on the final turn this
        # should now be unreachable in practice; keep it as a genuine last resort
        # (e.g. the model returns something other than the forced call).
        logger.error(
            "Step %d: exhausted all %d turns AND the forced report_findings did not "
            "produce a result", step_index + 1, MAX_TOOL_TURNS_PER_STEP,
        )

        # Last resort: ask for a plain-text summary of the transcript rather than
        # discarding 30 turns of real research behind a placeholder.
        try:
            salvage = await self.llm.chat_completion(
                messages=messages + [{
                    "role": "user",
                    "content": (
                        "Summarize what you established in this step: the key findings "
                        "and the sources they came from. If the subject does not appear "
                        "to exist, say so plainly. Plain prose, no tool calls."
                    ),
                }],
                tools=None,
                temperature=0.3,
            )
            salvaged_text = (self.llm.get_message(salvage).get("content") or "").strip()
        except ResearchLLMOverloaded as e:
            logger.error("Step %d: lane unavailable during salvage (%s)", step_index + 1, e)
            return {"action": "lane_down", "error": str(e)}
        except Exception as e:
            logger.warning(
                "Step %d: salvage summary failed: %s: %s",
                step_index + 1, type(e).__name__, e,
            )
            salvaged_text = ""

        if salvaged_text:
            return {
                "action": "complete",
                "findings": {
                    "summary": salvaged_text[:500],
                    "details": salvaged_text,
                    "sources": [],
                    "confidence": 0.4,
                },
            }

        return {
            "action": "complete",
            "findings": {
                "summary": "Step reached maximum turns without explicit findings report",
                "details": (
                    "The agent used all available turns and did not file findings even "
                    "when forced. Check the step's tool-call log for what it gathered."
                ),
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
            if plan and plan["status"] in _EXTERNAL_STOP_STATUSES:
                return None

        return None

    async def _synthesize_findings(self, db, plan: Dict[str, Any]) -> bool:
        """Use the research LLM to create a final synthesis of all findings.

        Returns True only if the synthesis was written. A swallowed failure here
        used to leave a plan marked `complete` with no report anywhere — the
        caller now downgrades it to `partial` instead.
        """
        steps = plan.get("steps", [])
        completed = [s for s in steps if s.get("status") == "complete" and s.get("findings")]

        if not completed:
            return False

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
            return True

        except ResearchLLMOverloaded as e:
            logger.error("Synthesis skipped — research lane unavailable: %s", e)
            return False
        except Exception as e:
            logger.error(
                "Failed to synthesize findings: %s: %s", type(e).__name__, e, exc_info=True
            )
            return False

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

            note_title = f"Research: {plan['title']}"

            # Ground-truth plan, Phase 6 §4: one note per plan title per day.
            # Four identical Salem plans on 2026-09-01 produced three "Salem MA
            # Historical Guide - Completed" notes, and those duplicates then took
            # four of the top five slots in her own memory recall. A later run
            # appends to the existing note instead of creating a rival copy.
            existing = db.execute(
                text("""
                    SELECT id, content FROM note
                     WHERE user_id = :user_id AND title = :title
                       AND created_at >= NOW() - INTERVAL '24 hours'
                     ORDER BY created_at DESC LIMIT 1
                """),
                {"user_id": self.user_id, "title": note_title},
            ).fetchone()

            if existing:
                run_number = (existing.content or "").count("## Run ") + 2
                db.execute(
                    text("""
                        UPDATE note
                           SET content = content || :addition, updated_at = NOW()
                         WHERE id = :id
                    """),
                    {
                        "id": existing.id,
                        "addition": f"\n\n---\n\n## Run {run_number}\n\n{content}",
                    },
                )
                db.commit()
                note_id = str(existing.id)
                logger.info("Appended run %d to existing note %s", run_number, note_id)
                return note_id

            note_id = str(uuid.uuid4())
            db.execute(
                text("""
                    INSERT INTO note (id, user_id, folder_id, title, content, tags, created_at, updated_at)
                    VALUES (:id, :user_id, :folder_id, :title, :content,
                            CAST(:tags AS jsonb), NOW(), NOW())
                """),
                {
                    "id": note_id,
                    "user_id": self.user_id,
                    "folder_id": folder_id,
                    "title": note_title,
                    "content": content,
                    # Invariant 2: Sara's own output is tagged, so memory_recall
                    # and the PKG extractor never mistake it for evidence.
                    "tags": json.dumps([SARA_GENERATED_TAG]),
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
            # Body = first paragraph of synthesis, trimmed for the lock screen.
            body = (synthesis or "").strip().split("\n\n", 1)[0]
            body = body.replace("# ", "").replace("## ", "").strip()
            if len(body) > 240:
                body = body[:237].rstrip() + "..."
            if not body:
                body = f"Your research on {plan.get('title', 'the topic')} is ready."

            # Arc 1.5 (SARA_ALIVE_BUILD_PLAN): the legacy direct push
            # (notification_service.send_notification — itself a thin
            # wrapper over unified_notification.send_notification) is
            # retired now that Arc 1.4's real delivery path is live — this
            # source speaks through the say_candidate queue only.
            await self._dual_write_candidate(plan, note_id, body, synthesis)
            # The promise made when the plan was created comes due here. The
            # candidate above is the message; this closes the obligation so the
            # World Brief's OPEN LOOPS stops listing it as outstanding.
            from app.services.commitment_service import close_delivery_commitment
            await close_delivery_commitment(
                self.user_id, self.plan_id,
                closure_note=f"{plan.get('title', 'Research')} is ready.",
                origin=plan.get("origin") or "david_chat",
                make_candidate=False,
            )
            logger.info("Queued research_complete candidate for plan %s → note %s", self.plan_id, note_id)
        except Exception as e:
            logger.warning("Failed to queue research completion candidate: %s", e)

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
            from datetime import timedelta
            from app.core.timezone import now as local_now
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

                # Something David asked for in chat is an alert, not an inform:
                # the judge is not allowed to batch it into a window he may have
                # already left the house before (Salem, 2026-09-01).
                origin = plan.get("origin") or ""
                await create_candidate(
                    db, user_id=self.user_id, source="research_executor",
                    kind="alert" if origin == "david_chat" else "inform",
                    summary=summary[:2000],
                    # `title` is what the compose fallback names when the model
                    # declines to write about a finished report (follow-up plan
                    # §6) — `summary` here is the whole report body.
                    evidence=[{"note_id": note_id, "plan_id": self.plan_id,
                               "origin": origin, "title": plan.get("title")}],
                    topic_entities=[f"research:{self.plan_id}"],
                    # An alert's 30-minute default TTL would expire a report
                    # finished at 21:28 long before David saw it.
                    valid_until=valid_until or (local_now() + timedelta(hours=24)),
                    value_guess=0.9 if origin == "david_chat" else None,
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
