"""
Internal Tool Agent — LLM agent loop using Sara's tool registry.

Mirrors SandboxOrchestrator's pattern but executes against Sara's internal
tools (email, calendar, memory, notes, web search, etc.) instead of
dispatching to a VM.

Used by AgentDispatchService when a task is classified as "internal".
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.tools.registry import tool_registry

logger = logging.getLogger(__name__)

# All possible internal categories (used as fallback when classifier doesn't specify)
ALL_INTERNAL_CATEGORIES = [
    "email", "time", "notes", "memory", "web",
    "personal_knowledge", "home", "fitness", "learning", "inbox",
]

# Extra tools added on top of registry tools
EXTRA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "report_complete",
            "description": (
                "Report that the task is complete. Include a clear summary of "
                "what was accomplished and list any key findings. If you found "
                "specific emails, notes, or attachments, include them in found_items "
                "so the user can open them directly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Summary of what was accomplished",
                    },
                    "key_findings": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key findings or results from the task",
                    },
                    "found_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["email", "note", "attachment"],
                                    "description": "Type of item found",
                                },
                                "id": {
                                    "type": "string",
                                    "description": "The item's ID (email ID, note ID, etc.)",
                                },
                                "title": {
                                    "type": "string",
                                    "description": "Display title (email subject, note title, filename)",
                                },
                                "download_url": {
                                    "type": "string",
                                    "description": "API path to download the item (for attachments, e.g. /email/{id}/attachments/{att_id}/download)",
                                },
                            },
                            "required": ["type", "id", "title"],
                        },
                        "description": (
                            "Specific items found during the task. Include emails, "
                            "notes, or attachments so they can be opened individually."
                        ),
                    },
                },
                "required": ["summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_david",
            "description": (
                "Ask David a question when you're stuck or need clarification. "
                "Try to solve problems yourself first. Only use this when you "
                "genuinely need human input."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask David",
                    },
                    "context": {
                        "type": "string",
                        "description": "Brief context about what you've tried so far",
                    },
                },
                "required": ["question"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are Sara's internal agent. You execute tasks using tools.

CRITICAL RULES:
1. DO NOT plan or describe what you would do. START CALLING TOOLS IMMEDIATELY.
2. Your FIRST response must be a tool call, not text. Never reply with just a plan.
3. After gathering information, call report_complete with your findings.
4. You MUST finish by calling report_complete. Never stop without it.

CAPABILITIES:
- You have full shell access via run_command, and can read/write files.
- Use these for any task requiring code execution, file manipulation, or system commands.
- Use email_search, email_read, etc. to access Sara's databases.
- Use web_search and open_page for research tasks.
- If a search returns no results, try different search terms.

SHELL USAGE:
- run_command executes bash in your working directory. Use it to run scripts, install packages, compile code, etc.
- write_file creates files in your working directory. Use for scripts, configs, output.
- read_file reads any file on the server.
- For code tasks: write the code with write_file, then run it with run_command.

EFFICIENCY — avoid redundant calls:
- Call email_search ONCE with broad terms, then email_read each result. Do NOT search repeatedly.
- email_search returns a list with IDs. Use email_read with each ID to get full content and attachments.
- Do NOT call email_search more than 2-3 times total. Search broad, then read specific emails.

FORMATTING ATTACHMENTS:
Include attachment download links in your summary as markdown:
  [filename.pdf](/email/{email_id}/attachments/{attachment_id}/download)

REPORT_COMPLETE:
When done, call report_complete with:
- summary: markdown text with findings and download links
- key_findings: list of key results
- found_items: ALWAYS include every email, note, or attachment you accessed.
  Each item: {"type": "email"|"note"|"attachment", "id": "<the item ID>", "title": "<subject or name>"}
  For attachments, also include "download_url": "/email/{email_id}/attachments/{attachment_id}/download"
  IMPORTANT: Include ALL emails you read in found_items, not just ones matching the search criteria.
  David wants to be able to open and review them directly."""


def _looks_like_junk_output(text: str) -> bool:
    """True when a 'summary' is not actually a deliverable — an unexecuted
    text-format tool call, or too short to carry any finding. Such runs used to
    be recorded as `completed`, which put raw XML in the result note and taught
    the notification tuner that agent results are worthless.
    """
    t = (text or "").strip()
    if len(t) < 40:
        return True
    if "<tool_call>" in t or "<function=" in t:
        return True
    return False


class InternalToolAgent:
    """LLM agent loop that uses Sara's tool registry for internal tasks."""

    def __init__(
        self,
        task_id: str,
        mission_id: str,
        user_id: str,
        categories: list = None,
    ):
        self.task_id = task_id
        self.mission_id = mission_id
        self.user_id = user_id
        from app.core.llm_config import llm_config
        # bg lane (:8081): tool-agent loops are background work, never the chat lane.
        self.llm_url = llm_config.bg_primary_url
        self.model = llm_config.bg_primary_model
        self.max_iterations = 25
        self._step_counter = 0
        self._should_pause = False
        self._is_complete = False
        self._pause_question: Optional[str] = None
        self._complete_summary: Optional[str] = None
        self._complete_findings: List[str] = []
        self._found_items: List[dict] = []
        # Drawer-compatible execution log (same entry shape the VM
        # dispatch loop emits) so internal tasks are inspectable too.
        self._execution_log: List[dict] = []

        # Use classifier-provided categories if available, else fall back to all
        # Note: empty list [] also falls back (classifier returned no categories)
        active_categories = categories if categories else ALL_INTERNAL_CATEGORIES
        # Always include shell + web so the agent can execute commands and research
        for required_cat in ("shell", "web"):
            if required_cat not in active_categories:
                active_categories.append(required_cat)
        logger.info(f"[internal-agent] Loading tools for categories: {active_categories}")

        # Load tool schemas from registry
        self._tool_schemas = tool_registry.get_tools_by_categories(active_categories)
        self._tool_schemas.extend(EXTRA_TOOLS)

        logger.info(f"[internal-agent] Loaded {len(self._tool_schemas)} tools total")

        # Names the model is allowed to call — used to validate salvaged
        # text-format tool calls (see _run_loop).
        self._valid_tool_names = {
            t["function"]["name"]
            for t in self._tool_schemas
            if t.get("function", {}).get("name")
        }

        # Build a set of registry tool names for dispatching
        self._registry_tool_names = set()
        for cat in active_categories:
            cat_info = tool_registry.TOOL_CATEGORIES.get(cat, {})
            self._registry_tool_names.update(cat_info.get("tools", []))

    async def run(self, task_description: str) -> dict:
        """Main agent loop — returns final result dict."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task_description}"},
        ]

        return await self._run_loop(messages)

    async def _run_loop(self, messages: List[dict]) -> dict:
        """Core agent loop."""
        # Track tool results for fallback summary
        tool_results_log: List[dict] = []
        has_called_tools = False
        no_tool_nudges = 0  # how many times we've nudged the LLM to use tools
        warning_iteration = self.max_iterations - 3  # warn 3 iterations before end
        final_iteration = self.max_iterations - 1     # force report_complete on last

        for iteration in range(self.max_iterations):
            # Inject countdown warning when nearing the limit
            if iteration == warning_iteration:
                messages.append({
                    "role": "user",
                    "content": (
                        f"URGENT: You have {self.max_iterations - iteration} iterations left. "
                        "You MUST call report_complete NOW with a summary of everything "
                        "you've found so far. Do NOT make any more search/read calls. "
                        "Summarize your findings and call report_complete immediately."
                    ),
                })

            # On the final iteration, force the model to call report_complete
            force_report = iteration == final_iteration

            try:
                response = await self._call_llm(messages, force_report_complete=force_report)
            except Exception as e:
                logger.error(f"[internal-agent] LLM call failed on iteration {iteration}: {e}")
                # Build fallback summary from what we have
                fallback = self._build_fallback_summary(tool_results_log)
                if not fallback:
                    # Nothing was accomplished — report the failure instead of
                    # dressing the exception string up as a result.
                    return {
                        "status": "failed",
                        "error": f"Internal agent LLM call failed: {e}",
                        "summary": "",
                        "artifacts": [],
                        "found_items": [],
                        "messages": messages,
                        "execution_log": self._execution_log,
                    }
                return {
                    "status": "completed",
                    "summary": fallback,
                    "artifacts": [],
                    "found_items": [],
                    "messages": messages,
                    "execution_log": self._execution_log,
                }

            assistant_content = response.get("content") or ""
            tool_calls = response.get("tool_calls")

            # Qwen intermittently emits tool calls as plain text instead of real
            # tool_calls. The VM dispatch loop already salvages these; without the
            # same treatment here the raw XML fell through to "implicit completion"
            # and got stored as the task's answer.
            if not tool_calls and assistant_content:
                from app.services.agent_dispatch import (
                    _parse_text_tool_calls,
                    _strip_text_tool_calls,
                )
                salvaged = _parse_text_tool_calls(
                    assistant_content, self._valid_tool_names,
                )
                if salvaged:
                    logger.warning(
                        "[internal-agent] Salvaged %d text-format tool call(s) the "
                        "server didn't parse (iteration %d)",
                        len(salvaged), iteration,
                    )
                    tool_calls = salvaged
                    assistant_content = _strip_text_tool_calls(assistant_content)

            # Build assistant message for history
            assistant_msg: Dict[str, Any] = {"role": "assistant"}
            if assistant_content:
                assistant_msg["content"] = assistant_content
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            if not assistant_content and not tool_calls:
                assistant_msg["content"] = ""
            messages.append(assistant_msg)

            if assistant_content.strip():
                self._execution_log.append({
                    "type": "llm_response",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "round": iteration,
                    "content": assistant_content[:10000],
                })

            if tool_calls:
                has_called_tools = True
                for tc in tool_calls:
                    _t0 = time.monotonic()
                    result = await self._execute_tool(tc)
                    _dur_ms = int((time.monotonic() - _t0) * 1000)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })

                    # Log tool results for fallback summary
                    func_name = tc.get("function", {}).get("name", "")
                    tool_results_log.append({
                        "tool": func_name,
                        "result": result[:2000],
                    })
                    try:
                        _args = json.loads(tc.get("function", {}).get("arguments") or "{}")
                    except (json.JSONDecodeError, TypeError):
                        _args = {}
                    self._execution_log.append({
                        "type": "tool_call",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "round": iteration,
                        "tool": func_name,
                        "args": _args,
                        "result": result[:10000],
                        "duration_ms": _dur_ms,
                    })

                    if self._should_pause:
                        return {
                            "status": "needs_clarification",
                            "question": self._pause_question,
                            "messages": messages,
                            "execution_log": self._execution_log,
                        }

                    if self._is_complete:
                        return {
                            "status": "completed",
                            "summary": self._complete_summary,
                            "artifacts": self._complete_findings,
                            "found_items": self._found_items,
                            "messages": messages,
                            "execution_log": self._execution_log,
                        }

                # Compact messages periodically to keep context manageable
                if iteration > 0 and iteration % 10 == 0 and len(messages) > 15:
                    messages = self._compact_messages(messages)
            else:
                # No tool call — but has the agent actually done any work yet?
                if not has_called_tools and no_tool_nudges < 2:
                    # LLM just planned/described instead of acting — nudge it
                    no_tool_nudges += 1
                    logger.info(f"[internal-agent] LLM returned text without tool calls (nudge {no_tool_nudges})")
                    messages.append({
                        "role": "user",
                        "content": (
                            "DO NOT describe what you would do. Call the tools NOW. "
                            "Start by calling the appropriate search tool immediately."
                        ),
                    })
                    continue

                # LLM has done work and now stopped calling tools — implicit completion
                logger.info("[internal-agent] LLM returned no tool calls — implicit completion")
                summary = assistant_content
                if not summary or len(summary) < 50:
                    summary = self._build_fallback_summary(tool_results_log) or summary or "Task completed"
                if _looks_like_junk_output(summary):
                    return {
                        "status": "failed",
                        "error": (
                            "Agent stopped without producing a result "
                            "(no executable tool calls)."
                        ),
                        "summary": "",
                        "artifacts": [],
                        "found_items": [],
                        "messages": messages,
                        "execution_log": self._execution_log,
                    }
                return {
                    "status": "completed",
                    "summary": summary,
                    "artifacts": [],
                    "found_items": [],
                    "messages": messages,
                    "execution_log": self._execution_log,
                }

        # Max iterations reached — build a meaningful summary from tool results
        logger.warning(f"[internal-agent] Hit max iterations ({self.max_iterations}) for task {self.task_id}")
        fallback = self._build_fallback_summary(tool_results_log)
        if not fallback:
            return {
                "status": "failed",
                "error": (
                    f"Agent hit the {self.max_iterations}-iteration limit without "
                    "producing any usable output."
                ),
                "summary": "",
                "artifacts": [],
                "found_items": [],
                "messages": messages,
                "execution_log": self._execution_log,
            }
        return {
            "status": "completed",
            "summary": fallback,
            "artifacts": [],
            "found_items": [],
            "messages": messages,
            "execution_log": self._execution_log,
        }

    async def _call_llm(
        self,
        messages: List[dict],
        force_report_complete: bool = False,
    ) -> dict:
        """Call the LLM via OpenAI-compatible API."""
        clean_messages = []
        for msg in messages:
            clean = {"role": msg["role"]}
            if msg.get("content") is not None:
                clean["content"] = msg["content"]
            if msg.get("tool_calls"):
                clean["tool_calls"] = msg["tool_calls"]
            if msg.get("tool_call_id"):
                clean["tool_call_id"] = msg["tool_call_id"]
            clean_messages.append(clean)

        # Force the model to call report_complete on the final iteration.
        # llama-server IGNORES a named tool_choice (verified against :8081 — ask
        # for report_complete and it happily returns a different tool), so the
        # tool_choice below is only advisory. What actually works is taking every
        # other tool away for this call.
        tools_for_call = self._tool_schemas
        if force_report_complete:
            tool_choice = {
                "type": "function",
                "function": {"name": "report_complete"},
            }
            report_only = [
                t for t in self._tool_schemas
                if t.get("function", {}).get("name") == "report_complete"
            ]
            if report_only:
                tools_for_call = report_only
        else:
            tool_choice = "auto"

        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{self.llm_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": clean_messages,
                    "tools": tools_for_call,
                    "tool_choice": tool_choice,
                    "temperature": 0.5,
                    "max_tokens": 4000,
                    "num_ctx": 131072,
                    # Qwen returns an empty `content` (and often no tool_calls)
                    # when thinking mode is left on for bounded tool-use turns.
                    "enable_thinking": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return data["choices"][0]["message"]

    async def _execute_tool(self, tool_call: dict) -> str:
        """Execute a single tool call and return the result as a string."""
        func = tool_call.get("function", {})
        name = func.get("name", "")
        try:
            args = json.loads(func.get("arguments", "{}"))
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in tool arguments"})

        logger.info(f"[internal-agent] Tool: {name} args={list(args.keys())}")

        # Handle special tools
        if name == "report_complete":
            return self._tool_report_complete(args)
        if name == "ask_david":
            return self._tool_ask_david(args)

        # Handle registry tools
        if name in self._registry_tool_names:
            return await self._execute_registry_tool(name, args)

        return json.dumps({"error": f"Unknown tool: {name}"})

    async def _execute_registry_tool(self, name: str, args: dict) -> str:
        """Execute a tool from Sara's tool registry."""
        # Create a MissionStep for this tool call
        args_summary = ", ".join(f"{k}={repr(v)[:60]}" for k, v in args.items())
        step_desc = f"{name}: {args_summary}"[:120]
        self._step_counter += 1
        step_index = self._step_counter + 2  # offset by initial classify/execute/report steps
        self._add_mission_step(step_index, name, step_desc, "running")

        try:
            result = await tool_registry.execute_tool(
                name, self.user_id, args,
                context={"task_id": self.task_id},
            )

            self._update_step_status(
                step_index,
                "done" if result.success else "failed",
                error=result.message[:500] if not result.success else None,
            )

            # Convert ToolResult to JSON string for LLM consumption
            output = {
                "success": result.success,
                "message": result.message,
            }
            if result.data is not None:
                data = result.data
                # For email_read: truncate body but ALWAYS preserve attachments
                if name == "email_read" and isinstance(data, dict):
                    body = data.get("body") or ""
                    if len(body) > 500:
                        data = {**data, "body": body[:500] + "... [truncated]"}
                output["data"] = self._truncate_tool_data(data)

            return json.dumps(output, default=str)

        except Exception as e:
            self._update_step_status(step_index, "failed", error=str(e)[:500])
            return json.dumps({"error": f"Tool execution failed: {e}"})

    def _tool_report_complete(self, args: dict) -> str:
        """Mark the task as complete."""
        self._is_complete = True
        self._complete_summary = args.get("summary", "Task completed")
        self._complete_findings = args.get("key_findings", [])
        self._found_items = args.get("found_items", [])

        return json.dumps({
            "status": "completed",
            "summary": self._complete_summary,
        })

    def _tool_ask_david(self, args: dict) -> str:
        """Pause the loop and escalate a question to David."""
        question = args.get("question", "")
        context = args.get("context", "")

        self._should_pause = True
        self._pause_question = question
        if context:
            self._pause_question = f"{question}\n\nContext: {context}"

        return json.dumps({
            "status": "paused",
            "message": "Question sent to David. The agent will resume when he responds.",
        })

    @staticmethod
    def _truncate_tool_data(data: Any, max_chars: int = 8000) -> Any:
        """Truncate tool result data to fit in context without breaking IDs.

        For lists (e.g. email search results), limits the number of items
        rather than cutting the JSON string mid-field.
        """
        if data is None:
            return None

        # If data is a dict containing a list, truncate the list
        if isinstance(data, dict):
            truncated = {}
            for key, value in data.items():
                if isinstance(value, list) and len(value) > 10:
                    truncated[key] = value[:10]
                    truncated[f"_{key}_note"] = f"Showing 10 of {len(value)} results"
                else:
                    truncated[key] = value
            data = truncated

        # Final size check
        try:
            serialized = json.dumps(data, default=str)
            if len(serialized) <= max_chars:
                return data
            # If still too large, try fewer items
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, list) and len(value) > 5:
                        data[key] = value[:5]
                        data[f"_{key}_note"] = f"Showing 5 of many results (truncated for context)"
                serialized = json.dumps(data, default=str)
                if len(serialized) <= max_chars:
                    return data
            # Last resort: string truncation at a safe boundary
            return json.loads(serialized[:max_chars - 50].rsplit('},', 1)[0] + '}]}}')
        except Exception:
            return str(data)[:max_chars]

    @staticmethod
    def _build_fallback_summary(tool_results_log: List[dict]) -> Optional[str]:
        """Build a meaningful summary from tool call results when agent didn't call report_complete.

        Extracts key information from email searches, reads, etc. to produce
        a useful summary rather than a generic "task completed" message.
        """
        if not tool_results_log:
            return None

        parts = []
        found_emails = []
        found_items = []

        for entry in tool_results_log:
            tool = entry.get("tool", "")
            result_str = entry.get("result", "")

            try:
                result = json.loads(result_str)
            except (json.JSONDecodeError, TypeError):
                continue

            if not isinstance(result, dict):
                continue

            data = result.get("data", result)

            if tool == "email_search" and result.get("success"):
                emails = data.get("emails") or data.get("results") or []
                if isinstance(emails, list):
                    for email in emails[:5]:
                        if isinstance(email, dict):
                            subj = email.get("subject", "No subject")
                            sender = email.get("from", email.get("sender", ""))
                            date = email.get("date", email.get("received_at", ""))
                            found_emails.append(f"- **{subj}** from {sender} ({date})")

            elif tool == "email_read" and result.get("success"):
                subj = data.get("subject", "")
                body_preview = (data.get("body") or data.get("text") or "")[:200]
                attachments = data.get("attachments", [])
                if subj:
                    parts.append(f"Read email: **{subj}**")
                    if body_preview:
                        parts.append(f"  Preview: {body_preview}...")
                    for att in (attachments or []):
                        if isinstance(att, dict):
                            att_name = att.get("name", att.get("filename", "attachment"))
                            dl_url = att.get("download_url", "")
                            if dl_url:
                                found_items.append(f"  - [{att_name}]({dl_url})")

        summary_parts = []
        if found_emails:
            summary_parts.append("**Emails found:**\n" + "\n".join(found_emails[:10]))
        if parts:
            summary_parts.append("\n".join(parts[:10]))
        if found_items:
            summary_parts.append("**Attachments:**\n" + "\n".join(found_items[:10]))

        if summary_parts:
            return "\n\n".join(summary_parts)
        return None

    def _compact_messages(self, messages: List[dict]) -> List[dict]:
        """Summarize prior tool results to keep context manageable."""
        summaries = []
        for msg in messages[2:]:  # skip system + initial user
            if msg["role"] == "tool":
                content = msg.get("content", "")
                summaries.append(content[:150])
        if not summaries:
            return messages

        compact = "[Prior results: " + "; ".join(summaries) + "]"
        return messages[:2] + [{"role": "user", "content": compact}] + messages[-3:]

    # ── Mission step helpers ──────────────────────────────────────────

    def _add_mission_step(self, step_index: int, action_name: str, description: str, status: str):
        """Add a new MissionStep dynamically."""
        try:
            from app.main_simple import SessionLocal
            from app.models.mission import Mission, MissionStep

            db = SessionLocal()
            try:
                step = MissionStep(
                    mission_id=self.mission_id,
                    step_index=step_index,
                    action_name=action_name,
                    description=description,
                    status=status,
                    started_at=datetime.now(timezone.utc) if status == "running" else None,
                )
                db.add(step)

                # Update mission total_steps
                mission = db.query(Mission).filter(Mission.id == self.mission_id).first()
                if mission:
                    total = db.query(MissionStep).filter(
                        MissionStep.mission_id == self.mission_id,
                    ).count()
                    mission.total_steps = total + 1
                    mission.state = "running"
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[internal-agent] Failed to add mission step: {e}")

    def _update_step_status(
        self,
        step_index: int,
        status: str,
        error: Optional[str] = None,
    ):
        """Update an existing MissionStep status."""
        try:
            from app.main_simple import SessionLocal
            from app.models.mission import Mission, MissionStep

            db = SessionLocal()
            try:
                step = db.query(MissionStep).filter(
                    MissionStep.mission_id == self.mission_id,
                    MissionStep.step_index == step_index,
                ).first()
                if step:
                    step.status = status
                    if status in ("done", "failed"):
                        step.completed_at = datetime.now(timezone.utc)
                    if error:
                        step.error_message = error

                # Update mission completed_steps count
                mission = db.query(Mission).filter(Mission.id == self.mission_id).first()
                if mission:
                    done_count = db.query(MissionStep).filter(
                        MissionStep.mission_id == self.mission_id,
                        MissionStep.status == "done",
                    ).count()
                    mission.completed_steps = done_count
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[internal-agent] Failed to update mission step: {e}")
