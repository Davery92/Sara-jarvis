"""
Sandbox Orchestrator — GLM-based multi-step agent coordinator.

Three-tier system:
1. Sara (qwen3.6-27b) → understands user intent, crafts task prompt, dispatches
2. Orchestrator (qwen3.6-27b) → plans approach, decomposes into steps,
   manages Claude Code agents on the sandbox VM
3. Claude Code (on VM 10.185.1.176) → executes individual steps

Escalation flow: Claude Code → GLM → Sara (notification) → David
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Tool schemas for the GLM orchestrator ────────────────────────────────

ORCHESTRATOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_sandbox_task",
            "description": (
                "Dispatch a task to a Claude Code agent on the sandbox VM. "
                "Use this for substantial work: writing code, building projects, "
                "debugging, research. Returns the agent's output and a session_id "
                "you can use with continue_sandbox_task for follow-ups."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_prompt": {
                        "type": "string",
                        "description": "Clear, detailed prompt for the Claude Code agent",
                    },
                    "working_directory": {
                        "type": "string",
                        "description": "Working directory on the VM (default: inherited from task)",
                    },
                },
                "required": ["task_prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "continue_sandbox_task",
            "description": (
                "Send a follow-up instruction to an existing Claude Code agent session. "
                "Use this to build on previous work, fix issues, or add to what an "
                "agent already did."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "The session_id from a previous run_sandbox_task call",
                    },
                    "instruction": {
                        "type": "string",
                        "description": "Follow-up instruction for the agent",
                    },
                    "working_directory": {
                        "type": "string",
                        "description": "Working directory override (optional)",
                    },
                },
                "required": ["session_id", "instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a quick shell command on the sandbox VM. "
                "Use this for simple checks: ls, cat, curl, grep, df, etc. "
                "NOT for long-running tasks — use run_sandbox_task for those."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute (30s timeout)",
                    },
                },
                "required": ["command"],
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
                "genuinely need human input (e.g., which approach to take, "
                "credentials, project-specific preferences)."
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
    {
        "type": "function",
        "function": {
            "name": "report_complete",
            "description": (
                "Report that the task is complete. Include a clear summary of "
                "what was accomplished and list any important file paths or artifacts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Summary of what was accomplished",
                    },
                    "artifacts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of important file paths or artifacts created",
                    },
                },
                "required": ["summary"],
            },
        },
    },
]

SYSTEM_PROMPT_TEMPLATE = """You are a task orchestrator managing a sandbox Ubuntu VM (10.185.1.176).
Your job is to plan and execute technical tasks by dispatching work to
Claude Code agents running on the VM.

WORKFLOW:
1. Analyze the task and break it into concrete steps
2. For each step, use run_sandbox_task to dispatch work to a Claude Code agent
3. Review the agent's output before proceeding to the next step
4. For quick checks (ls, cat, curl, df), use run_command instead of a full agent
5. When done, use report_complete with a summary

RULES:
- Think step-by-step. Don't try to do everything in one agent call
- Review agent output before moving on — catch errors early
- If you need info from David, use ask_david (but try to solve it yourself first)
- If an agent fails, try to fix the issue before giving up
- Working directory: {working_dir}
- You can use continue_sandbox_task to resume a previous agent session
{skill_section}"""


class SandboxOrchestrator:
    """GLM-based orchestrator that plans and coordinates Claude Code agents."""

    def __init__(
        self,
        vm_bridge,
        task_id: str,
        mission_id: str,
        user_id: str,
        skill_context: str = "",
    ):
        self.bridge = vm_bridge
        self.task_id = task_id
        self.mission_id = mission_id
        self.user_id = user_id
        self.skill_context = skill_context or ""
        from app.core.llm_config import llm_config
        self.llm_url = llm_config.primary_url
        self.model = llm_config.primary_model
        self.max_iterations = 30
        self.active_sessions: Dict[str, str] = {}  # session_id → description
        self._step_counter = 0
        self._should_pause = False
        self._is_complete = False
        self._pause_question: Optional[str] = None
        self._complete_summary: Optional[str] = None
        self._complete_artifacts: List[str] = []

    async def run(
        self,
        task_description: str,
        working_dir: str = "/home/sara/sandbox",
    ) -> dict:
        """Main orchestration loop — returns final result dict."""
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            working_dir=working_dir,
            skill_section=self.skill_context,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Task: {task_description}"},
        ]

        return await self._run_loop(messages, working_dir)

    async def resume(
        self,
        instruction: str,
        prior_messages: List[dict],
    ) -> dict:
        """Resume orchestration after David answers a question."""
        # Reset state
        self._should_pause = False
        self._is_complete = False
        self._pause_question = None

        # Append David's answer to the conversation
        prior_messages.append({
            "role": "user",
            "content": f"David's answer: {instruction}",
        })

        # Extract working_dir from system prompt
        working_dir = "/home/sara/sandbox"
        if prior_messages and prior_messages[0].get("role") == "system":
            content = prior_messages[0]["content"]
            marker = "Working directory: "
            idx = content.find(marker)
            if idx != -1:
                working_dir = content[idx + len(marker):].split("\n")[0].strip()

        return await self._run_loop(prior_messages, working_dir)

    async def _run_loop(
        self,
        messages: List[dict],
        working_dir: str,
    ) -> dict:
        """Core agent loop shared by run() and resume()."""
        for iteration in range(self.max_iterations):
            try:
                response = await self._call_glm(messages)
            except Exception as e:
                logger.error(f"[orchestrator] GLM call failed on iteration {iteration}: {e}")
                return {
                    "status": "failed",
                    "error": f"Orchestrator LLM call failed: {e}",
                    "messages": messages,
                }

            assistant_content = response.get("content") or ""
            tool_calls = response.get("tool_calls")

            # Build assistant message for history
            assistant_msg: Dict[str, Any] = {"role": "assistant"}
            if assistant_content:
                assistant_msg["content"] = assistant_content
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            if not assistant_content and not tool_calls:
                assistant_msg["content"] = ""
            messages.append(assistant_msg)

            if tool_calls:
                for tc in tool_calls:
                    result = await self._execute_tool(tc, working_dir)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })

                    if self._should_pause:
                        return {
                            "status": "needs_clarification",
                            "question": self._pause_question,
                            "messages": messages,
                        }

                    if self._is_complete:
                        return {
                            "status": "completed",
                            "summary": self._complete_summary,
                            "artifacts": self._complete_artifacts,
                            "messages": messages,
                        }

                # Compact messages after iteration 8 to prevent unbounded growth
                if iteration == 7 and len(messages) > 10:
                    messages = self._compact_messages(messages)

                # Inject deadline warning 3 iterations before the limit
                if iteration == self.max_iterations - 3:
                    messages.append({
                        "role": "user",
                        "content": (
                            "IMPORTANT: You are running low on iterations. "
                            "You MUST call report_complete on your NEXT step "
                            "with a thorough summary of everything you've found so far. "
                            "Do NOT start new research — synthesize what you have NOW."
                        ),
                    })
            else:
                # No tool call — GLM thinks it's done
                logger.info("[orchestrator] GLM returned no tool calls — treating as implicit completion")
                return {
                    "status": "completed",
                    "summary": assistant_content or "Task completed (no explicit summary)",
                    "artifacts": [],
                    "messages": messages,
                }

        # Exceeded max iterations — extract best summary from accumulated results
        logger.warning(f"[orchestrator] Hit max iterations ({self.max_iterations}) for task {self.task_id}")
        summary = self._extract_best_summary(messages)
        return {
            "status": "completed",
            "summary": summary,
            "artifacts": [],
            "messages": messages,
        }

    async def _call_glm(self, messages: List[dict]) -> dict:
        """Call the GLM model via OpenAI-compatible API."""
        # Clean messages for the API — strip any keys the API doesn't expect
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

        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{self.llm_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": clean_messages,
                    "tools": ORCHESTRATOR_TOOLS,
                    "tool_choice": "auto",
                    "temperature": 0.5,
                    "max_tokens": 4000,
                    "num_ctx": 32768,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return data["choices"][0]["message"]

    async def _execute_tool(self, tool_call: dict, working_dir: str) -> str:
        """Execute a single tool call and return the result as a string."""
        func = tool_call.get("function", {})
        name = func.get("name", "")
        try:
            args = json.loads(func.get("arguments", "{}"))
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON in tool arguments"})

        logger.info(f"[orchestrator] Tool: {name} args={list(args.keys())}")

        if name == "run_sandbox_task":
            return await self._tool_run_sandbox_task(args, working_dir)
        elif name == "continue_sandbox_task":
            return await self._tool_continue_sandbox_task(args, working_dir)
        elif name == "run_command":
            return await self._tool_run_command(args)
        elif name == "ask_david":
            return self._tool_ask_david(args)
        elif name == "report_complete":
            return self._tool_report_complete(args)
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    async def _tool_run_sandbox_task(self, args: dict, default_working_dir: str) -> str:
        """Dispatch a task to a Claude Code agent on the VM."""
        task_prompt = args.get("task_prompt", "")
        wd = args.get("working_directory", default_working_dir)

        if not task_prompt:
            return json.dumps({"error": "task_prompt is required"})

        # Create a MissionStep for this agent call
        step_desc = f"Agent: {task_prompt[:80]}"
        self._step_counter += 1
        step_index = self._step_counter + 2  # offset by initial connect/execute/report steps
        self._add_mission_step(step_index, step_desc, "running")

        try:
            result = await self.bridge.start_claude_session(
                task_prompt=task_prompt,
                timeout=600,
                working_dir=wd,
            )

            if result.session_id:
                self.active_sessions[result.session_id] = task_prompt[:80]

            output = result.output[:3000] if result.output else ""
            success = result.success

            self._update_step_status(
                step_index,
                "done" if success else "failed",
                error=output[:500] if not success else None,
            )

            return json.dumps({
                "success": success,
                "output": output,
                "session_id": result.session_id,
                "exit_code": result.exit_code,
            })

        except Exception as e:
            self._update_step_status(step_index, "failed", error=str(e))
            return json.dumps({"error": f"Agent execution failed: {e}"})

    async def _tool_continue_sandbox_task(self, args: dict, default_working_dir: str) -> str:
        """Resume an existing Claude Code agent session."""
        session_id = args.get("session_id", "")
        instruction = args.get("instruction", "")
        wd = args.get("working_directory", default_working_dir)

        if not session_id or not instruction:
            return json.dumps({"error": "session_id and instruction are required"})

        step_desc = f"Continue: {instruction[:80]}"
        self._step_counter += 1
        step_index = self._step_counter + 2
        self._add_mission_step(step_index, step_desc, "running")

        try:
            result = await self.bridge.resume_claude_session(
                session_id=session_id,
                instruction=instruction,
                timeout=600,
                working_dir=wd,
            )

            output = result.output[:3000] if result.output else ""
            success = result.success

            self._update_step_status(
                step_index,
                "done" if success else "failed",
                error=output[:500] if not success else None,
            )

            return json.dumps({
                "success": success,
                "output": output,
            })

        except Exception as e:
            self._update_step_status(step_index, "failed", error=str(e))
            return json.dumps({"error": f"Agent resume failed: {e}"})

    async def _tool_run_command(self, args: dict) -> str:
        """Run a quick shell command on the VM."""
        command = args.get("command", "")
        if not command:
            return json.dumps({"error": "command is required"})

        step_desc = f"Command: {command[:80]}"
        self._step_counter += 1
        step_index = self._step_counter + 2
        self._add_mission_step(step_index, step_desc, "running")

        try:
            result = await self.bridge.execute_command(command, timeout=30)

            self._update_step_status(step_index, "done")

            return json.dumps({
                "stdout": result.stdout[:2000],
                "stderr": result.stderr[:500] if result.stderr else "",
                "exit_code": result.exit_code,
            })

        except Exception as e:
            self._update_step_status(step_index, "failed", error=str(e))
            return json.dumps({"error": f"Command failed: {e}"})

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
            "message": "Question sent to David. The orchestrator will resume when he responds.",
        })

    def _tool_report_complete(self, args: dict) -> str:
        """Mark the task as complete."""
        self._is_complete = True
        self._complete_summary = args.get("summary", "Task completed")
        self._complete_artifacts = args.get("artifacts", [])

        return json.dumps({
            "status": "completed",
            "summary": self._complete_summary,
        })

    def _extract_best_summary(self, messages: List[dict]) -> str:
        """Extract the best summary from messages when hitting the iteration limit.

        Walks messages in reverse to find the last substantial tool output
        or assistant synthesis, rather than returning a useless generic string.
        """
        # First: check if the last assistant message has a real summary
        for msg in reversed(messages):
            if msg["role"] == "assistant":
                content = (msg.get("content") or "").strip()
                if content and len(content) > 100:
                    return content[:5000]
                break  # only check the last assistant message

        # Second: find the longest/last tool output that looks like a report
        best_tool_output = ""
        for msg in reversed(messages):
            if msg["role"] == "tool":
                content = msg.get("content", "")
                # Try to parse JSON tool results for stdout
                try:
                    data = json.loads(content)
                    stdout = data.get("stdout", "")
                    if len(stdout) > len(best_tool_output):
                        best_tool_output = stdout
                except (json.JSONDecodeError, TypeError):
                    if len(content) > len(best_tool_output):
                        best_tool_output = content
                if len(best_tool_output) > 500:
                    break  # good enough

        if best_tool_output:
            return best_tool_output[:5000]

        return "Task completed but no summary was produced (iteration limit reached)."

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

    def _add_mission_step(self, step_index: int, description: str, status: str):
        """Add a new MissionStep dynamically."""
        try:
            from app.main_simple import SessionLocal
            from app.models.mission import Mission, MissionStep

            db = SessionLocal()
            try:
                step = MissionStep(
                    mission_id=self.mission_id,
                    step_index=step_index,
                    action_name="orchestrator_step",
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
                    mission.total_steps = total + 1  # +1 for the one we're adding
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[orchestrator] Failed to add mission step: {e}")

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
            logger.warning(f"[orchestrator] Failed to update mission step: {e}")
