"""
Code Mode — a persistent chat "/code" mode that drives an autonomous coding
agent on the sara VM (10.185.1.176).

Flow:
    /code start <owner/repo>   bind the conversation to a CodeSession
                               (clone repo + create a working branch on the VM)
    /code <instruction>        run the autonomous coder on that checkout
    <any message>             (while active) → also routed to the coder
    /code stop                 cancel an in-flight run
    /code off                  leave code mode (checkout + branch preserved)
    /code status | branch | projects | help

Design: CODE_MODE_DESIGN.md. Reuses the dispatch LLM loop primitives from
agent_dispatch.py (`_dispatch_llm_call`, `_compact_tool_history`) and the
SSH VMBridge. Disk (a git checkout on the VM) is the source of truth; the
CodeSession transcript/session_log are the compacted reasoning overlay, and a
fresh `git status` header is rebuilt every turn so the model never has to trust
the transcript for repo state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import tempfile
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timezone import now as local_now
from app.models.code_session import CodeSession
from app.models.background_task import BackgroundTask
from app.services.vm_bridge import VMBridge
from app.services.agent_dispatch import (
    _dispatch_llm_call,
    _compact_tool_history,
    _resolve_vm_path,
    _publish_dispatch_event,
)

logger = logging.getLogger(__name__)

# Holds references to detached background coder tasks so they aren't GC'd mid-run.
_BG_TASKS: set = set()

# Dedicated DB engine for code mode. Code-mode sessions are held across long
# `await`s (SSH / LLM) inside detached tasks; using the shared request pool risks
# a corrupted/cancelled connection being returned to it, which then surfaces as
# "another command is already in progress" 500s on unrelated webapp requests.
# NullPool = a fresh connection per session, closed on session.close(), never
# returned to the shared pool — so code mode can never poison request handlers.
_code_engine = None
_CodeSessionLocal = None


def _code_db():
    """Open a DB session on code mode's isolated NullPool engine."""
    global _code_engine, _CodeSessionLocal
    if _CodeSessionLocal is None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import NullPool
        from app.db.base import engine as _shared_engine
        _code_engine = create_engine(_shared_engine.url, poolclass=NullPool, future=True)
        _CodeSessionLocal = sessionmaker(bind=_code_engine, autoflush=False, expire_on_commit=True)
    return _CodeSessionLocal()

# ---------------------------------------------------------------------------
# Layout on the VM
# ---------------------------------------------------------------------------
CODE_ROOT = settings.code_mode_root.rstrip("/")  # e.g. ~/code-projects

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9_./-]+$")

# Heuristic command blocklist (defense-in-depth, not a true sandbox — see design).
_BLOCKED_PATTERNS = [
    (re.compile(r"\bsudo\b"), "sudo is not allowed"),
    (re.compile(r"rm\s+-rf\s+(/|~|\$HOME)(\s|$)"), "refusing to rm -rf a home/root path"),
    (re.compile(r":\(\)\s*\{"), "fork bomb blocked"),
    (re.compile(r"\b(shutdown|reboot|halt|poweroff)\b"), "power commands blocked"),
    (re.compile(r"\bmkfs\b|\bdd\s+if="), "disk commands blocked"),
    (re.compile(r"\.ssh\b"), "access to ~/.ssh is blocked"),
    (re.compile(r"git-credentials|\.config/gh\b"), "access to git credentials is blocked"),
    (re.compile(r"\bsystemctl\b|acs-daemon"), "touching system services / the ACS daemon is blocked"),
]


def _blocked_reason(command: str) -> str | None:
    low = command.lower()
    for pat, reason in _BLOCKED_PATTERNS:
        if pat.search(low):
            return reason
    return None


# ---------------------------------------------------------------------------
# Tool definitions for the coder loop
# ---------------------------------------------------------------------------
def _code_tools(workdir: str) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": (
                    "Run a shell command in the repo checkout. You have bash, git, python, "
                    "node, etc. Use this for `git`, running tests/builds, `ls`, `grep`, `find`. "
                    f"Working directory: {workdir} (commands run there). Writes must stay inside it."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string", "description": "Shell command"}},
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file from the checkout. Path is relative to the repo root.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": (
                    "Edit an existing file by exact search/replace. `old_string` must appear "
                    "verbatim and be unique (include surrounding context to disambiguate), unless "
                    "replace_all is true. Prefer this over write_file for changes to existing files."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_string": {"type": "string"},
                        "new_string": {"type": "string"},
                        "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)"},
                    },
                    "required": ["path", "old_string", "new_string"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Create a NEW file (or fully overwrite) with the given content. For edits to existing files, use edit_file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "report_complete",
                "description": (
                    "Signal this turn is done. Call when you've finished the requested work "
                    "(edited, tested, and committed). Provide a concise summary of what changed."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "success": {"type": "boolean"},
                    },
                    "required": ["summary"],
                },
            },
        },
    ]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------
async def _exec_tool(bridge: VMBridge, name: str, args: dict, workdir: str) -> str:
    try:
        if name == "run_command":
            command = (args.get("command") or "").strip()
            if not command:
                return "Error: empty command"
            reason = _blocked_reason(command)
            if reason:
                return f"BLOCKED: {reason}. Adjust your approach."
            # Docker builds / compose pulls are slow — give them 10 min vs the 180s default.
            low = command.lower()
            cmd_timeout = 600 if ("docker" in low or "compose" in low) else 180
            # workdir left unquoted so ~ expands on the remote shell
            result = await bridge.execute_command(f"cd {workdir} && {command}", timeout=cmd_timeout)
            if result.timed_out:
                return f"Command timed out after {cmd_timeout}s"
            out = result.stdout
            if result.stderr:
                out += f"\nSTDERR: {result.stderr}"
            if result.exit_code != 0:
                out += f"\n(exit code {result.exit_code})"
            return out[:10000] or "(no output)"

        if name == "read_file":
            raw = args.get("path", "")
            if not raw:
                return "Error: no path"
            path = _resolve_vm_path(raw, workdir, bridge.config.username)
            result = await bridge.execute_command(f"cat {shlex.quote(path)}", timeout=30)
            if result.exit_code != 0:
                return f"Error reading file: {result.stderr or '(not found)'}"
            return result.stdout[:15000] or "(empty file)"

        if name == "write_file":
            raw = args.get("path", "")
            content = args.get("content", "")
            if not raw:
                return "Error: no path"
            path = _resolve_vm_path(raw, workdir, bridge.config.username)
            ok, err = await _write_remote_file(bridge, path, content)
            return f"Wrote {len(content)} bytes to {raw}" if ok else f"Error writing file: {err}"

        if name == "edit_file":
            raw = args.get("path", "")
            old = args.get("old_string", "")
            new = args.get("new_string", "")
            replace_all = bool(args.get("replace_all", False))
            if not raw:
                return "Error: no path"
            if old == new:
                return "Error: old_string and new_string are identical"
            path = _resolve_vm_path(raw, workdir, bridge.config.username)
            read = await bridge.execute_command(f"cat {shlex.quote(path)}", timeout=30)
            if read.exit_code != 0:
                return f"Error: cannot read {raw} ({read.stderr or 'not found'}). Use write_file to create it."
            content = read.stdout
            count = content.count(old)
            if count == 0:
                return f"Error: old_string not found in {raw}. Read the file and match exactly."
            if count > 1 and not replace_all:
                return f"Error: old_string appears {count}× in {raw}. Add context to make it unique, or set replace_all."
            updated = content.replace(old, new) if replace_all else content.replace(old, new, 1)
            ok, err = await _write_remote_file(bridge, path, updated)
            if not ok:
                return f"Error writing edit: {err}"
            return f"Edited {raw} ({count if replace_all else 1} replacement(s))"

        if name == "report_complete":
            return "__TASK_COMPLETE__:" + (args.get("summary") or "Done.")

        return f"Unknown tool: {name}"
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"[code_mode] tool {name} failed: {e}", exc_info=True)
        return f"Tool execution error: {e}"


async def _write_remote_file(bridge: VMBridge, path: str, content: str) -> tuple[bool, str]:
    """Write content to an absolute VM path via a quoted heredoc."""
    marker = "SARA_CODE_EOF"
    # Escape only backslashes; the quoted heredoc ('MARKER') suppresses $ and ` expansion.
    body = content.replace("\\", "\\\\")
    cmd = (
        f"mkdir -p $(dirname {shlex.quote(path)}) && "
        f"cat > {shlex.quote(path)} << '{marker}'\n{body}\n{marker}"
    )
    result = await bridge.execute_command(cmd, timeout=45)
    if result.exit_code != 0:
        return False, result.stderr or f"exit {result.exit_code}"
    return True, ""


# ---------------------------------------------------------------------------
# VM git environment setup
# ---------------------------------------------------------------------------
async def _ensure_git_auth(bridge: VMBridge) -> tuple[bool, str]:
    """Configure git identity + a credential store on the VM holding the PAT.

    The PAT is delivered via scp of a local temp file (never as part of a
    command string), so it never lands in command logs.
    """
    pat = settings.github_pat.strip()
    if not pat:
        return False, "GITHUB_PAT is not set on the backend. Add it to the backend environment."

    home = f"/home/{bridge.config.username}"
    cred_line = f"https://x-access-token:{pat}@github.com\n"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".cred") as fh:
            fh.write(cred_line)
            tmp_path = fh.name
        scp = await bridge.scp_to_vm(tmp_path, f"{home}/.git-credentials")
        if scp.exit_code != 0:
            return False, f"failed to install credentials: {scp.stderr}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    cfg = (
        f"chmod 600 {home}/.git-credentials && "
        "git config --global credential.helper store && "
        f"git config --global user.name {shlex.quote(settings.git_author_name)} && "
        f"git config --global user.email {shlex.quote(settings.git_author_email)} && "
        "git config --global init.defaultBranch main && "
        "git config --global --add safe.directory '*'"
    )
    result = await bridge.execute_command(cfg, timeout=30)
    if result.exit_code != 0:
        return False, f"git config failed: {result.stderr}"
    return True, ""


async def _clone_checkout(bridge: VMBridge, owner: str, repo: str, workdir: str, branch: str) -> tuple[bool, str]:
    """Clone the repo into `workdir` and create the working branch."""
    url = f"https://github.com/{owner}/{repo}.git"
    cmd = (
        f"mkdir -p {CODE_ROOT} && "
        f"rm -rf {workdir} && "
        f"git clone {shlex.quote(url)} {workdir} && "
        f"cd {workdir} && git checkout -B {shlex.quote(branch)}"
    )
    result = await bridge.execute_command(cmd, timeout=300)
    if result.exit_code != 0:
        return False, (result.stderr or result.stdout or "clone failed")[:800]
    return True, ""


async def _git_header(bridge: VMBridge, workdir: str) -> str:
    """Ground-truth repo state, rebuilt every turn."""
    cmd = (
        f"cd {workdir} && "
        "echo '### branch' && git rev-parse --abbrev-ref HEAD && "
        "echo '### status (porcelain)' && git status --short && "
        "echo '### recent commits' && git log --oneline -6 2>/dev/null"
    )
    result = await bridge.execute_command(cmd, timeout=30)
    return (result.stdout or "(unavailable)")[:4000]


async def _repo_digest(bridge: VMBridge, workdir: str) -> str:
    cmd = (
        f"cd {workdir} && "
        "echo '### tracked files (first 250)' && git ls-files | head -250 && "
        "echo '### README (head)' && (head -60 README.md 2>/dev/null || head -60 README* 2>/dev/null || true)"
    )
    result = await bridge.execute_command(cmd, timeout=30)
    return (result.stdout or "")[:6000]


async def _commit_and_push(bridge: VMBridge, workdir: str, branch: str, summary: str) -> str:
    """Safety-net commit of any leftovers, then push the branch. Returns a status line."""
    msg = (summary.strip().splitlines() or ["update"])[0][:72]
    # NOTE: do NOT pipe `git push` into `tail` — the pipeline's exit code would
    # be tail's (0), masking a failed push. Capture full output, tail in Python.
    cmd = (
        f"cd {workdir} && "
        "if [ -n \"$(git status --porcelain)\" ]; then "
        f"git add -A && git commit -m {shlex.quote(msg)} >/dev/null 2>&1; fi && "
        f"git push -u origin {shlex.quote(branch)} 2>&1"
    )
    result = await bridge.execute_command(cmd, timeout=120)
    out = (result.stdout or "").strip()
    tail = "\n".join(out.splitlines()[-5:])
    if result.exit_code != 0:
        return f"⚠️ push failed (exit {result.exit_code}): {tail[:400]}"
    return "✅ pushed branch"


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
def _system_prompt(repo: str, branch: str, workdir: str) -> str:
    return (
        "You are Sara's autonomous coding agent, working directly on a real git checkout on a VM.\n\n"
        f"Repository: {repo}\nBranch: {branch}\nWorking directory: {workdir}\n\n"
        "## How you work\n"
        "- You are AUTONOMOUS: plan, edit, run tests/build, and commit on your own. Do not ask for "
        "permission for ordinary edits. Only stop and ask if you are genuinely blocked or the request is ambiguous.\n"
        "- Work in small steps. Read before you edit. Prefer `edit_file` (search/replace) over `write_file` for "
        "existing files; use `write_file` only for new files.\n"
        "- Verify your work: run the project's tests or a quick check via `run_command` when feasible.\n"
        "- Docker & `docker compose` are available on this VM (no sudo needed). You may build images and "
        "run containers to test your changes — Docker commands get a longer (10 min) timeout. ALWAYS clean "
        "up what you start (`docker compose down`, remove containers/images you created) before finishing, "
        "so nothing accumulates on the shared VM.\n"
        "- Commit as you go with clear messages (`git add` + `git commit`). The harness pushes the branch "
        "for you at the end of the turn — you do NOT need to push, and there is no PR step.\n"
        "- All file writes must stay inside the working directory. `sudo`, touching ~/.ssh, the credential "
        "store, or system services is blocked.\n"
        "- This is for small, scoped tasks. Keep changes focused on what was asked.\n\n"
        "## Finishing\n"
        "When the requested work is done (edited, sanity-checked, committed), call `report_complete` with a "
        "concise summary of what changed (files touched, key decisions). That ends your turn and hands control "
        "back to the user, who can send the next instruction.\n"
    )


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------
async def _emit(q: asyncio.Queue, type_: str, **data):
    # The web ChatInterface reads `full_content` for text_chunk; default it to
    # `content` so single-chunk emits render (and never yield undefined there).
    if type_ == "text_chunk" and "full_content" not in data:
        data["full_content"] = data.get("content", "")
    await q.put({"type": type_, "data": data})


async def _finish(q: asyncio.Queue, full_text: str, conversation_id):
    await q.put({
        "type": "final_response",
        "data": {
            "content": full_text,
            "citations": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "conversation_id": conversation_id,
        },
    })
    await q.put({"type": "done"})
    await q.put(None)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------
def get_active_session(db: Session, user_id: str, conversation_id) -> CodeSession | None:
    q = db.query(CodeSession).filter(
        CodeSession.user_id == str(user_id),
        CodeSession.active == True,  # noqa: E712
    )
    if conversation_id:
        q = q.filter(CodeSession.conversation_id == str(conversation_id))
    return q.order_by(CodeSession.last_active_at.desc()).first()


def _short(sid: str) -> str:
    return sid.replace("-", "")[:8]


def parse_code_command(text: str) -> tuple[str, str]:
    """Returns (kind, arg). kind ∈ start|off|stop|status|branch|projects|help|message."""
    t = (text or "").strip()
    if not t.lower().startswith("/code"):
        return ("message", t)
    rest = t[5:].strip()
    if not rest:
        return ("help", "")
    first, _, arg = rest.partition(" ")
    f = first.lower()
    arg = arg.strip()
    if f == "start":
        return ("start", arg)
    if f in ("off", "exit", "end", "leave"):
        return ("off", "")
    if f == "stop":
        return ("stop", "")
    if f == "status":
        return ("status", "")
    if f == "branch":
        return ("branch", arg)
    if f == "preview":
        return ("preview", arg)
    if f == "projects":
        return ("projects", "")
    if f == "help":
        return ("help", "")
    # "/code <freeform instruction>"
    return ("message", rest)


_HELP = (
    "**Code mode** — autonomous coder on the VM.\n\n"
    "- `/code start <owner/repo>` — clone + start a coding session\n"
    "- `/code <instruction>` (or just type, while active) — give the coder a task\n"
    "- `/code stop` — cancel the current run\n"
    "- `/code off` — leave code mode (your branch is kept)\n"
    "- `/code status` — show repo / branch / git status\n"
    "- `/code branch <name>` — start a fresh branch\n"
    "- `/code preview` — build & run the current branch on the VM for 1 hour, returns a URL\n"
)

PREVIEW_TTL_SECONDS = 3600  # how long a /code preview container stays up


# ---------------------------------------------------------------------------
# Entry point — called from /chat/stream
# ---------------------------------------------------------------------------
async def run_code_message(request_db: Session, user_id: str, conversation_id, text: str, q: asyncio.Queue):
    """Drive one code-mode interaction, streaming SSE events into `q`.

    Always terminates by putting a `final_response`, `done`, then `None` sentinel.
    """
    user_id = str(user_id)
    # This runs as a background asyncio task that can outlive the originating
    # HTTP request — whose Depends(get_db) session is closed on client
    # disconnect. So we own a dedicated DB session (isolated NullPool engine).
    db = _code_db()
    try:
        kind, arg = parse_code_command(text)
        session = get_active_session(db, user_id, conversation_id)
        # `/code` commands follow the user across conversations: if this
        # conversation has no bound session, fall back to the user's most-recent
        # active session. (Plain non-/code messages stay conversation-scoped —
        # that routing decision is made in main_simple, not here — so normal
        # chat in other conversations is never hijacked.)
        if session is None:
            session = (
                db.query(CodeSession)
                .filter(CodeSession.user_id == user_id, CodeSession.active == True)  # noqa: E712
                .order_by(CodeSession.last_active_at.desc())
                .first()
            )

        # --- meta commands -------------------------------------------------
        if kind == "help":
            await _emit(q, "text_chunk", content=_HELP)
            await _finish(q, _HELP, conversation_id)
            return

        if kind == "off":
            if session:
                session.active = False
                session.state = "idle"
                db.commit()
                msg = f"Left code mode. Branch `{session.branch}` on `{session.repo_slug}` is preserved on the VM."
            else:
                msg = "You're not in code mode."
            await _emit(q, "text_chunk", content=msg)
            await _finish(q, msg, conversation_id)
            return

        if kind == "stop":
            if session and session.state == "running":
                session.cancel_requested = True
                db.commit()
                msg = "Stopping the current run — it will halt after the in-flight step, commit, and push."
            else:
                msg = "Nothing is running."
            await _emit(q, "text_chunk", content=msg)
            await _finish(q, msg, conversation_id)
            return

        if kind == "status":
            if not session:
                msg = "Not in code mode. `/code start <owner/repo>` to begin."
            else:
                bridge = VMBridge()
                header = await _git_header(bridge, session.workdir)
                msg = (
                    f"**Code mode** — `{session.repo_slug}` on `{session.branch}` (state: {session.state})\n\n"
                    f"```\n{header}\n```"
                )
            await _emit(q, "text_chunk", content=msg)
            await _finish(q, msg, conversation_id)
            return

        if kind == "projects":
            rows = (
                db.query(CodeSession)
                .filter(CodeSession.user_id == user_id)
                .order_by(CodeSession.last_active_at.desc())
                .limit(20)
                .all()
            )
            if not rows:
                msg = "No code sessions yet. `/code start <owner/repo>`."
            else:
                lines = ["**Your code sessions:**"]
                for r in rows:
                    flag = "🟢" if r.active else "⚪"
                    lines.append(f"- {flag} `{r.repo_slug}` · `{r.branch}` · {r.state}")
                msg = "\n".join(lines)
            await _emit(q, "text_chunk", content=msg)
            await _finish(q, msg, conversation_id)
            return

        if kind == "branch":
            if not session:
                msg = "Not in code mode. `/code start <owner/repo>` first."
                await _emit(q, "text_chunk", content=msg)
                await _finish(q, msg, conversation_id)
                return
            new_branch = arg or f"sara/session-{_short(session.id)}-{session.turns + 1}"
            if not _BRANCH_RE.match(new_branch):
                msg = "Invalid branch name."
                await _emit(q, "text_chunk", content=msg)
                await _finish(q, msg, conversation_id)
                return
            bridge = VMBridge()
            res = await bridge.execute_command(
                f"cd {session.workdir} && git checkout -B {shlex.quote(new_branch)}", timeout=30
            )
            if res.exit_code == 0:
                session.branch = new_branch
                db.commit()
                msg = f"Switched to new branch `{new_branch}`."
            else:
                msg = f"Could not switch branch: {res.stderr}"
            await _emit(q, "text_chunk", content=msg)
            await _finish(q, msg, conversation_id)
            return

        if kind == "preview":
            if not session:
                msg = "No active code session to preview. Run a `/code <task>` first (or `/code start <owner/repo>`)."
                await _emit(q, "text_chunk", content=msg)
                await _finish(q, msg, conversation_id)
                return
            await _handle_preview(session, conversation_id, q)
            return

        if kind == "start":
            session = await _ensure_session(db, user_id, conversation_id, arg, q)
            if session:
                header = await _git_header(VMBridge(), session.workdir)
                msg = (
                    f"✅ Code mode on for `{session.repo_slug}` (branch `{session.branch}`).\n"
                    "Tell me what to build — just type `/code <task>` or plain text. "
                    "I'll edit, test, commit, and push the branch each turn. `/code off` to exit.\n\n"
                    f"```\n{header}\n```"
                )
                await _emit(q, "text_chunk", content=msg)
                await _finish(q, msg, conversation_id)
            return

        # --- a coding instruction → runs in the BACKGROUND (chat stays free) ---
        repo = session.repo_slug if session else _resolve_default_repo(db, user_id)
        if not repo:
            msg = "No default repo configured. Start one with `/code start <owner/repo>`.\n\n" + _HELP
            await _emit(q, "text_chunk", content=msg)
            await _finish(q, msg, conversation_id)
            return

        # If a run is already in flight, queue this onto the session for the
        # running task to pick up (queue-as-next-instruction).
        if session and session.state == "running":
            session.queue = list(session.queue or []) + [arg]
            db.commit()
            msg = "⏳ A coder run is already in progress — I queued that as the next instruction."
            await _emit(q, "text_chunk", content=msg)
            await _finish(q, msg, conversation_id)
            return

        # Register a background task and dispatch the coder detached.
        task_id = str(uuid.uuid4())
        bt = BackgroundTask(
            id=task_id,
            user_id=user_id,
            status="running",
            task_type="code_mode",
            original_query=arg,
            task_metadata={
                "mode": "code_mode",
                "repo": repo,
                "conversation_id": str(conversation_id) if conversation_id else None,
                "execution_log": [],
            },
            started_at=local_now(),
        )
        db.add(bt)

        # Mission for the "Agent Tasks" (missions) screen — mirrors agent_dispatch
        # so code tasks are tracked alongside other agent work.
        from app.models.mission import Mission, MissionStep
        mission = Mission(
            user_id=user_id,
            title=f"Code: {repo} — {arg[:60]}",
            description=arg,
            source="code_mode",
            state="running",
            priority="normal",
            total_steps=3,
            completed_steps=0,
            current_step_index=0,
            requires_confirmation=False,
            mission_metadata={"task_id": task_id, "mode": "code_mode", "repo": repo},
            started_at=local_now(),
        )
        db.add(mission)
        db.flush()  # generate mission.id
        mission_id = str(mission.id)
        for i, (act, dsc) in enumerate([
            ("setup", "Prepare repo checkout"),
            ("code", "Edit, test & commit"),
            ("push", "Push branch"),
        ]):
            db.add(MissionStep(mission_id=mission.id, step_index=i, action_name=act, description=dsc, status="pending"))
        bt.task_metadata = {**(bt.task_metadata or {}), "mission_id": mission_id}
        db.commit()

        t = asyncio.create_task(
            _run_background_task(
                task_id, user_id, conversation_id, arg, repo,
                session.id if session else None, mission_id,
            )
        )
        _BG_TASKS.add(t)
        t.add_done_callback(_BG_TASKS.discard)

        ack = (
            f"🛠️ Started in the background on `{repo}`.\n"
            "Watch live progress in the tasks panel — I'll send a push when it's done. "
            "Your chat is free; `/code status` to check in, `/code stop` to cancel."
        )
        await _emit(q, "text_chunk", content=ack)
        await _finish(q, ack, conversation_id)
        return

    except Exception as e:  # pragma: no cover - defensive top-level guard
        logger.error(f"[code_mode] fatal: {e}", exc_info=True)
        err = f"Code mode error: {e}"
        try:
            await _emit(q, "text_chunk", content=err)
            await _finish(q, err, conversation_id)
        except Exception:
            await q.put(None)
    finally:
        db.close()


def _resolve_default_repo(db: Session, user_id: str) -> str | None:
    """Repo to use when `/code <task>` is sent with no active session:
    the user's most recently used repo, else the configured default."""
    last = (
        db.query(CodeSession)
        .filter(CodeSession.user_id == user_id)
        .order_by(CodeSession.last_active_at.desc())
        .first()
    )
    if last and last.repo_slug:
        return last.repo_slug
    return settings.code_mode_default_repo.strip() or None


async def _ensure_session(db: Session, user_id: str, conversation_id, repo_arg: str, q: asyncio.Queue) -> CodeSession | None:
    """Establish (resume or freshly clone) a code session for `repo_arg`.

    Returns the active CodeSession on success WITHOUT finishing the stream, so
    the caller can continue (e.g. immediately run a turn). On error, emits a
    message, finishes the stream, and returns None.
    """
    repo = (repo_arg or "").strip()
    if repo.startswith("https://github.com/"):
        repo = repo[len("https://github.com/"):].rstrip("/").removesuffix(".git")
    if not _REPO_RE.match(repo):
        msg = "Usage: `/code start <owner/repo>` (e.g. `/code start Davery92/sara-sandbox`)."
        await _emit(q, "text_chunk", content=msg)
        await _finish(q, msg, conversation_id)
        return None
    owner, name = repo.split("/", 1)

    existing = (
        db.query(CodeSession)
        .filter(CodeSession.user_id == user_id, CodeSession.repo_owner == owner, CodeSession.repo_name == name)
        .order_by(CodeSession.last_active_at.desc())
        .first()
    )
    # Deactivate any other active session for this user.
    for s in db.query(CodeSession).filter(
        CodeSession.user_id == user_id, CodeSession.active == True  # noqa: E712
    ).all():
        if not existing or s.id != existing.id:
            s.active = False
    db.commit()

    bridge = VMBridge()
    await _emit(q, "text_chunk", content=f"🔌 Connecting to the VM and setting up `{repo}`…\n")

    ok, err = await _ensure_git_auth(bridge)
    if not ok:
        msg = f"❌ {err}"
        await _emit(q, "text_chunk", content=msg)
        await _finish(q, msg, conversation_id)
        return None

    if existing:
        existing.active = True
        existing.state = "idle"
        existing.cancel_requested = False
        existing.conversation_id = str(conversation_id) if conversation_id else existing.conversation_id
        db.commit()
        check = await bridge.execute_command(f"test -d {existing.workdir}/.git && echo ok", timeout=20)
        if "ok" not in (check.stdout or ""):
            cok, cerr = await _clone_checkout(bridge, owner, name, existing.workdir, existing.branch)
            if not cok:
                msg = f"❌ Could not re-clone: {cerr}"
                await _emit(q, "text_chunk", content=msg)
                await _finish(q, msg, conversation_id)
                return None
        return existing

    # Fresh session
    sid = str(uuid.uuid4())
    branch = f"sara/session-{_short(sid)}"
    workdir = f"{CODE_ROOT}/{_short(sid)}"
    cok, cerr = await _clone_checkout(bridge, owner, name, workdir, branch)
    if not cok:
        msg = f"❌ Clone failed: {cerr}"
        await _emit(q, "text_chunk", content=msg)
        await _finish(q, msg, conversation_id)
        return None

    digest = await _repo_digest(bridge, workdir)
    session = CodeSession(
        id=sid,
        user_id=user_id,
        conversation_id=str(conversation_id) if conversation_id else None,
        repo_owner=owner,
        repo_name=name,
        branch=branch,
        workdir=workdir,
        state="idle",
        active=True,
        transcript=[],
        session_log=f"## Repo overview\n{digest}",
        queue=[],
    )
    db.add(session)
    db.commit()
    return session


# ---------------------------------------------------------------------------
# The autonomous turn loop
# ---------------------------------------------------------------------------
async def _handle_preview(session: CodeSession, conversation_id, q: asyncio.Queue):
    """Build & run the session's current branch on the VM for PREVIEW_TTL_SECONDS,
    return a URL, and schedule auto-teardown. Detects compose / Dockerfile / static."""
    bridge = VMBridge()
    wd = session.workdir
    user = bridge.config.username
    host = bridge.config.host
    name = f"sara-preview-{_short(session.id)}"
    home = f"/home/{user}"
    abswd = (home + wd[1:]) if wd.startswith("~") else wd
    parts: list[str] = []

    async def say(t: str):
        parts.append(t)
        await _emit(q, "text_chunk", content=t, full_content="".join(parts))

    await say(f"🚀 Building a preview of `{session.repo_slug}` (`{session.branch}`)…\n")

    # Tear down any prior preview for this session first.
    await bridge.execute_command(
        f"docker rm -f {name} >/dev/null 2>&1; docker compose -p {name} down >/dev/null 2>&1 || true",
        timeout=60,
    )

    # Pick a free host port in 8090–8099.
    portcmd = (
        "for p in 8090 8091 8092 8093 8094 8095 8096 8097 8098 8099; do "
        "if ! docker ps --format '{{.Ports}}' | grep -q \":$p->\" && "
        "! ss -ltn 2>/dev/null | grep -q \":$p \"; then echo $p; break; fi; done"
    )
    pr = await bridge.execute_command(portcmd, timeout=30)
    port = (pr.stdout or "").strip().split("\n")[0].strip()
    if not port.isdigit():
        msg = "❌ No free preview port (8090–8099) on the VM right now."
        await say(msg)
        await _finish(q, "".join(parts), conversation_id)
        return
    url = f"http://{host}:{port}"

    # Detect project type within the worktree.
    det = await bridge.execute_command(
        f"cd {wd} && "
        "if [ -f docker-compose.yml ] || [ -f compose.yaml ] || [ -f compose.yml ]; then echo compose; "
        "elif [ -f Dockerfile ]; then echo dockerfile; "
        "else f=$(find . -maxdepth 3 -name index.html | head -1); "
        "if [ -n \"$f\" ]; then echo \"static:$(dirname \"$f\")\"; else echo none; fi; fi",
        timeout=30,
    )
    kind = (det.stdout or "").strip().split("\n")[-1].strip()

    ok = False
    extra = ""
    if kind.startswith("static:"):
        sub = kind.split("static:", 1)[1].strip().lstrip("./") or ""
        mountdir = f"{abswd}/{sub}" if sub else abswd
        await say(f"📄 Static site detected — serving `{sub or '.'}` via nginx.\n")
        run = await bridge.execute_command(
            f"docker run -d --name {name} -p {port}:80 "
            f"-v {shlex.quote(mountdir)}:/usr/share/nginx/html:ro nginx:alpine",
            timeout=300,
        )
        ok = run.exit_code == 0
        if not ok:
            extra = (run.stderr or run.stdout or "")[:300]

    elif kind == "dockerfile":
        await say("🐳 Dockerfile detected — building image…\n")
        ex = await bridge.execute_command(
            f"cd {wd} && grep -iE '^EXPOSE' Dockerfile | head -1 | awk '{{print $2}}'", timeout=20
        )
        cport = (ex.stdout or "").strip() or "8080"
        build = await bridge.execute_command(f"cd {wd} && docker build -t {name}:preview .", timeout=600)
        if build.exit_code != 0:
            extra = (build.stderr or build.stdout or "")[-400:]
        else:
            await say(f"▶️ Starting container (container port {cport})…\n")
            run = await bridge.execute_command(
                f"docker run -d --name {name} -p {port}:{cport} {name}:preview", timeout=120
            )
            ok = run.exit_code == 0
            if not ok:
                extra = (run.stderr or run.stdout or "")[:300]

    elif kind == "compose":
        await say("🐳 docker compose detected — bringing the stack up…\n")
        up = await bridge.execute_command(f"cd {wd} && docker compose -p {name} up -d --build", timeout=600)
        ok = up.exit_code == 0
        ps = await bridge.execute_command(f"cd {wd} && docker compose -p {name} ps --format '{{{{.Service}}}} {{{{.Ports}}}}'", timeout=30)
        extra = (ps.stdout or "").strip()
        url = None  # compose maps its own ports
    else:
        msg = ("❓ Couldn't auto-detect how to run this project (no compose file, Dockerfile, or index.html). "
               "Ask the coder to add a Dockerfile, then `/code preview` again.")
        await say(msg)
        await _finish(q, "".join(parts), conversation_id)
        return

    if not ok:
        await say(f"❌ Preview failed to start.\n```\n{extra[:500]}\n```")
        await bridge.execute_command(f"docker rm -f {name} >/dev/null 2>&1; docker compose -p {name} down >/dev/null 2>&1 || true", timeout=60)
        await _finish(q, "".join(parts), conversation_id)
        return

    # Confirm it's running.
    status = await bridge.execute_command(f"docker ps --filter name={name} --format '{{{{.Status}}}}' | head -1", timeout=20)
    running = "Up" in (status.stdout or "")

    # Schedule auto-teardown after the TTL (detached on the VM so it survives independently).
    await bridge.execute_command(
        f"nohup sh -c 'sleep {PREVIEW_TTL_SECONDS}; docker rm -f {name} >/dev/null 2>&1; "
        f"docker compose -p {name} down >/dev/null 2>&1' >/dev/null 2>&1 < /dev/null &",
        timeout=10,
    )

    mins = PREVIEW_TTL_SECONDS // 60
    if kind == "compose":
        await say(
            f"✅ Preview stack is up{' (running)' if running else ''} — auto-stops in {mins} min.\n"
            f"Published ports (reach at `{host}:<port>`):\n```\n{extra or '(see compose config)'}\n```"
        )
    else:
        await say(
            f"✅ **Preview live:** {url}\n"
            f"{'🟢 running' if running else '🟡 starting'} · auto-stops in {mins} min · `/code preview` again to rebuild.\n"
        )
    await _finish(q, "".join(parts), conversation_id)


def _arg_preview(name: str, args: dict) -> str:
    if name == "run_command":
        return (args.get("command") or "")[:160]
    if name in ("read_file", "write_file", "edit_file"):
        return args.get("path") or ""
    if name == "report_complete":
        return (args.get("summary") or "")[:160]
    return json.dumps(args)[:160]


async def _run_turn(db: Session, session: CodeSession, instruction: str, conversation_id, q: asyncio.Queue):
    instruction = (instruction or "").strip()
    if not instruction:
        msg = "Tell me what to work on."
        await _emit(q, "text_chunk", content=msg)
        await _finish(q, msg, conversation_id)
        return

    bridge = VMBridge()
    session.state = "running"
    session.cancel_requested = False
    # Bind the active coder to the conversation this task came from, so plain
    # (non-/code) follow-up messages here route to it.
    if conversation_id:
        session.conversation_id = str(conversation_id)
    db.commit()
    sid = session.id
    workdir = session.workdir
    repo = session.repo_slug
    branch = session.branch

    full_parts: list[str] = []

    async def say(text: str):
        full_parts.append(text)
        await _emit(q, "text_chunk", content=text)

    try:
        header = await _git_header(bridge, workdir)
        tools = _code_tools(workdir)
        # IMPORTANT: keep all `system` content in ONE leading message. The MLX
        # chat template 500s on a system message that appears after user/assistant
        # turns, so the fresh git-status header is folded into the final user
        # message instead (it's still the most-salient, last thing the model reads).
        system_content = _system_prompt(repo, branch, workdir)
        if session.session_log:
            system_content += "\n\n" + session.session_log[:6000]
        messages: list[dict] = [{"role": "system", "content": system_content}]
        # Recent verbatim transcript (prior turns)
        messages.extend(session.transcript or [])
        # Fresh ground-truth state + the instruction, in the final user turn.
        messages.append({
            "role": "user",
            "content": (
                f"## Current repository state (ground truth)\n```\n{header}\n```\n\n"
                f"{instruction}"
            ),
        })

        await say(f"🛠️ Working on it in `{repo}` (`{branch}`)…\n")

        summary, success, actions = await _agent_loop(
            db, sid, bridge, workdir, messages, tools, q, say
        )

        # Push the branch (with a safety-net commit) unless we never touched anything.
        push_status = await _commit_and_push(bridge, workdir, branch, summary or instruction)
        compare = f"https://github.com/{repo}/compare/{branch}?expand=1"

        await say(
            f"\n\n**Done.** {summary}\n\n{push_status} → [`{branch}`]({compare}) "
            f"· {actions} action(s)\n"
        )

        # Persist the compacted overlay: append this turn to the transcript.
        transcript = list(session.transcript or [])
        transcript.append({"role": "user", "content": instruction})
        transcript.append({"role": "assistant", "content": summary or "(no summary)"})
        # Keep the last 12 messages verbatim; fold older ones into session_log.
        if len(transcript) > 12:
            overflow = transcript[:-12]
            transcript = transcript[-12:]
            folded = "\n".join(
                f"- {m['role']}: {m['content'][:200]}" for m in overflow if m.get("content")
            )
            session.session_log = ((session.session_log or "") + "\n## Earlier turns\n" + folded)[:8000]
        session.transcript = transcript
        session.turns = (session.turns or 0) + 1

    except Exception as e:
        logger.error(f"[code_mode] turn failed: {e}", exc_info=True)
        await say(f"\n\n❌ Run failed: {e}")
    finally:
        # Reload state flags from DB (a concurrent /code stop may have set them).
        session.state = "idle"
        session.cancel_requested = False
        db.commit()

    full_text = "".join(full_parts)

    # Drain one queued instruction, if any (queue-as-next-instruction).
    # Refresh so we observe messages a concurrent request appended mid-run.
    db.refresh(session)
    pending = list(session.queue or [])
    if pending:
        next_text = pending[0]
        session.queue = pending[1:]
        db.commit()
        await _emit(q, "text_chunk", content="\n\n— picking up your queued instruction —\n")
        # Continue streaming on this same connection.
        await _run_turn(db, session, next_text, conversation_id, q)
        return

    await _finish(q, full_text, conversation_id)


async def _agent_loop(db, sid, bridge, workdir, messages, tools, q, say):
    """Multi-round tool-use loop for a single turn. Returns (summary, success, action_count)."""
    max_rounds = settings.code_mode_max_rounds
    rounds = 0
    actions = 0

    while rounds < max_rounds:
        # Cancellation check (a concurrent /code stop sets this in the DB).
        cancelled = db.query(CodeSession.cancel_requested).filter(CodeSession.id == sid).scalar()
        if cancelled:
            return "Run cancelled by user. Work so far is committed and pushed.", False, actions

        _compact_tool_history(messages)
        result = await _dispatch_llm_call(messages, model=None, tools=tools)
        choices = result.get("choices", [])
        if not choices:
            return "The model returned no response.", False, actions
        msg = choices[0].get("message", {})
        tool_calls = msg.get("tool_calls")
        content = (msg.get("content") or "").strip()

        if not tool_calls:
            # Plain text → treat as the turn's final word.
            return content or "Done.", True, actions

        if content:
            await say(f"\n{content}\n")

        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})

        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            await say(f"🔧 `{name}` {_arg_preview(name, args)}\n")
            output = await _exec_tool(bridge, name, args, workdir)
            actions += 1

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", str(uuid.uuid4())),
                "content": output,
            })

            if output.startswith("__TASK_COMPLETE__:"):
                return output[len("__TASK_COMPLETE__:"):], bool(args.get("success", True)), actions

        rounds += 1

    return "Reached the maximum number of steps for this turn — stopping here.", False, actions


# ---------------------------------------------------------------------------
# Background execution — fire-and-forget coder tied to a BackgroundTask row.
# Live progress is published to Redis `sara:dispatch:live:{task_id}` (the same
# channel the existing tasks panel/drawer subscribes to) and accumulated in
# task_metadata.execution_log; a push notification fires on completion.
# ---------------------------------------------------------------------------
def _update_task(db: Session, task_id: str, status: str | None = None,
                 error: str | None = None, meta_updates: dict | None = None):
    t = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
    if not t:
        return
    if status:
        t.status = status
        if status in ("completed", "failed"):
            t.completed_at = local_now()
    if error:
        t.error_message = error[:2000]
    if meta_updates:
        meta = dict(t.task_metadata or {})
        meta.update(meta_updates)
        t.task_metadata = meta  # reassign so SQLAlchemy flags the JSONB dirty
    db.commit()


def _finish_mission(db: Session, mission_id: str | None, ok: bool,
                    summary: str | None = None, compare_url: str | None = None):
    """Mark the linked Mission (Agent Tasks screen) done/failed and surface the
    result (summary + branch link) so the card is actually useful when expanded."""
    if not mission_id:
        return
    try:
        from app.models.mission import Mission, MissionStep
        m = db.query(Mission).filter(Mission.id == mission_id).first()
        if not m:
            return
        m.state = "done" if ok else "failed"
        m.completed_at = local_now()
        # Replace the description (was the raw instruction) with the OUTCOME.
        if ok:
            m.completed_steps = m.total_steps
            m.current_step_index = max(0, (m.total_steps or 1) - 1)
            desc = (summary or "Done.").strip()
            if compare_url:
                desc += f"\n\n🔗 Branch: {compare_url}"
            m.description = desc[:2000]
        elif summary:
            m.description = f"Failed: {summary[:1500]}"
        steps = db.query(MissionStep).filter(MissionStep.mission_id == mission_id).order_by(MissionStep.step_index).all()
        for s in steps:
            s.status = "completed" if ok else ("failed" if s.status != "completed" else s.status)
        # Make the push step show the branch link.
        if ok and compare_url:
            push = next((s for s in steps if s.action_name == "push"), None)
            if push:
                push.description = "Pushed branch — open to review / PR"
                push.result = {"compare_url": compare_url}
        db.commit()
    except Exception as e:
        logger.warning(f"[code_mode] mission finalize failed: {e}")


async def _notify_done(user_id: str, title: str, message: str, task_id: str, ok: bool = True):
    try:
        from app.services.unified_notification import send_notification
        await send_notification(
            user_id=user_id,
            title=title,
            message=message,
            category="agent_task",
            topic=f"code_mode:{task_id}",
            source="code_mode",
            priority="normal",
            cooldown_hours=0,  # one-shot completion ping — never suppress
        )
    except Exception as e:
        logger.warning(f"[code_mode] completion notify failed: {e}")


async def _bg_agent_loop(db, sid, bridge, workdir, messages, tools, emit, round_offset=0):
    """Like _agent_loop, but emits STRUCTURED events (for the tasks drawer) via
    `emit(entry)` instead of markdown text. Returns (summary, success, actions)."""
    max_rounds = settings.code_mode_max_rounds
    rounds = 0
    actions = 0
    while rounds < max_rounds:
        cancelled = db.query(CodeSession.cancel_requested).filter(CodeSession.id == sid).scalar()
        if cancelled:
            return "Run cancelled by user. Work so far is committed and pushed.", False, actions

        _compact_tool_history(messages)
        result = await _dispatch_llm_call(messages, model=None, tools=tools)
        choices = result.get("choices", [])
        if not choices:
            return "The model returned no response.", False, actions
        msg = choices[0].get("message", {})
        tool_calls = msg.get("tool_calls")
        content = (msg.get("content") or "").strip()

        if not tool_calls:
            if content:
                await emit({"type": "llm_response", "round": round_offset + rounds, "content": content})
            return content or "Done.", True, actions

        if content:
            await emit({"type": "llm_response", "round": round_offset + rounds, "content": content})
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})

        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            t0 = time.monotonic()
            output = await _exec_tool(bridge, name, args, workdir)
            dur = int((time.monotonic() - t0) * 1000)
            actions += 1
            await emit({
                "type": "tool_call", "round": round_offset + rounds,
                "tool": name, "args": args, "result": output[:10000], "duration_ms": dur,
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", str(uuid.uuid4())),
                "content": output,
            })
            if output.startswith("__TASK_COMPLETE__:"):
                return output[len("__TASK_COMPLETE__:"):], bool(args.get("success", True)), actions
        rounds += 1

    return "Reached the maximum number of steps for this turn.", False, actions


def _step_label(entry: dict) -> str | None:
    """A short, human-friendly 'current step' for the Live Activity subtitle."""
    t = entry.get("type")
    if t == "tool_call":
        tool = entry.get("tool", "")
        args = entry.get("args") or {}
        if tool == "write_file":
            return f"writing {args.get('path', 'file')}"
        if tool == "edit_file":
            return f"editing {args.get('path', 'file')}"
        if tool == "read_file":
            return f"reading {args.get('path', 'file')}"
        if tool == "git push":
            return "pushing branch"
        if tool == "report_complete":
            return "wrapping up"
        if tool == "run_command":
            cmd = (args.get("command") or "").strip()
            low = cmd.lower()
            if "git commit" in low:
                return "committing"
            if "pytest" in low or "npm test" in low or " test" in low:
                return "running tests"
            if low.startswith("git "):
                return "running git"
            return f"running: {cmd[:40]}"
        return tool or None
    if t == "llm_response":
        content = entry.get("content") or ""
        if content.startswith("**Task:**"):
            return "starting…"
        return "thinking…"
    return None


async def _run_background_task(task_id, user_id, conversation_id, instruction, repo, session_id, mission_id=None):
    """Detached coder run: resolves/clones the session, runs the instruction (and
    any queued follow-ups), pushes the branch, and pushes a completion notice.
    Owns its own DB session (it outlives the originating HTTP request)."""
    db = _code_db()
    bridge = VMBridge()
    exec_log: list[dict] = []

    async def emit(entry: dict):
        entry.setdefault("ts", local_now().isoformat())
        exec_log.append(entry)
        meta_updates = {"execution_log": exec_log[-300:]}
        label = _step_label(entry)
        if label:
            meta_updates["status_label"] = label  # drives the iOS Live Activity subtitle
        _update_task(db, task_id, meta_updates=meta_updates)
        await _publish_dispatch_event(task_id, entry)

    session = None
    overall_ok = True
    summaries: list[str] = []
    try:
        if session_id:
            session = db.query(CodeSession).filter(CodeSession.id == session_id).first()

        if session is None:
            await emit({"type": "llm_response", "round": 0, "content": f"Setting up `{repo}`…"})
            ok, err = await _ensure_git_auth(bridge)
            if not ok:
                raise RuntimeError(err)
            owner, name = repo.split("/", 1)
            session = (
                db.query(CodeSession)
                .filter(CodeSession.user_id == user_id, CodeSession.repo_owner == owner, CodeSession.repo_name == name)
                .order_by(CodeSession.last_active_at.desc())
                .first()
            )
            if session is None:
                sid = str(uuid.uuid4())
                branch = f"sara/session-{_short(sid)}"
                workdir = f"{CODE_ROOT}/{_short(sid)}"
                cok, cerr = await _clone_checkout(bridge, owner, name, workdir, branch)
                if not cok:
                    raise RuntimeError(f"Clone failed: {cerr}")
                digest = await _repo_digest(bridge, workdir)
                session = CodeSession(
                    id=sid, user_id=user_id,
                    conversation_id=str(conversation_id) if conversation_id else None,
                    repo_owner=owner, repo_name=name, branch=branch, workdir=workdir,
                    state="idle", active=True, transcript=[],
                    session_log=f"## Repo overview\n{digest}", queue=[],
                )
                db.add(session)
                db.commit()
            else:
                chk = await bridge.execute_command(f"test -d {session.workdir}/.git && echo ok", timeout=20)
                if "ok" not in (chk.stdout or ""):
                    cok, cerr = await _clone_checkout(bridge, owner, name, session.workdir, session.branch)
                    if not cok:
                        raise RuntimeError(f"Re-clone failed: {cerr}")

        # Make this the user's single active session, bound to the launching conversation.
        for s in db.query(CodeSession).filter(
            CodeSession.user_id == user_id, CodeSession.active == True  # noqa: E712
        ).all():
            if s.id != session.id:
                s.active = False
        session.active = True
        session.state = "running"
        session.cancel_requested = False
        if conversation_id:
            session.conversation_id = str(conversation_id)
        db.commit()
        sid = session.id
        _update_task(db, task_id, status="running", meta_updates={
            "session_id": sid, "working_directory": session.workdir,
            "mode": "code_mode", "repo": session.repo_slug, "branch": session.branch,
        })

        pending = [instruction]
        round_offset = 0
        while pending:
            instr = pending.pop(0)
            await emit({"type": "llm_response", "round": round_offset, "content": f"**Task:** {instr}"})
            header = await _git_header(bridge, session.workdir)
            tools = _code_tools(session.workdir)
            sysc = _system_prompt(session.repo_slug, session.branch, session.workdir)
            if session.session_log:
                sysc += "\n\n" + session.session_log[:6000]
            messages = [{"role": "system", "content": sysc}]
            messages.extend(session.transcript or [])
            messages.append({
                "role": "user",
                "content": f"## Current repository state (ground truth)\n```\n{header}\n```\n\n{instr}",
            })

            summary, ok, actions = await _bg_agent_loop(
                db, sid, bridge, session.workdir, messages, tools, emit, round_offset
            )
            overall_ok = overall_ok and ok

            push_status = await _commit_and_push(bridge, session.workdir, session.branch, summary or instr)
            compare = f"https://github.com/{session.repo_slug}/compare/{session.branch}?expand=1"
            await emit({
                "type": "tool_call", "round": round_offset, "tool": "git push",
                "args": {"branch": session.branch}, "result": f"{push_status} ({compare})", "duration_ms": 0,
            })
            summaries.append(summary)

            # Persist the compacted transcript overlay.
            transcript = list(session.transcript or [])
            transcript.append({"role": "user", "content": instr})
            transcript.append({"role": "assistant", "content": summary or "(no summary)"})
            if len(transcript) > 12:
                overflow = transcript[:-12]
                transcript = transcript[-12:]
                folded = "\n".join(f"- {m['role']}: {m['content'][:200]}" for m in overflow if m.get("content"))
                session.session_log = ((session.session_log or "") + "\n## Earlier turns\n" + folded)[:8000]
            session.transcript = transcript
            session.turns = (session.turns or 0) + 1
            db.commit()
            round_offset += 1000  # keep per-turn rounds visually separated in the drawer

            db.refresh(session)
            if session.cancel_requested:
                break
            pending = list(session.queue or [])
            session.queue = []
            db.commit()

        final_summary = "\n\n".join(s for s in summaries if s) or "Done."
        compare = f"https://github.com/{session.repo_slug}/compare/{session.branch}?expand=1"
        _update_task(
            db, task_id,
            status="completed" if overall_ok else "failed",
            meta_updates={"output": final_summary, "exit_code": 0 if overall_ok else 1, "compare_url": compare},
        )
        _finish_mission(db, mission_id, overall_ok, summary=final_summary, compare_url=compare)
        await _notify_done(
            user_id,
            f"{'✅' if overall_ok else '⚠️'} Code: {session.repo_slug}",
            f"{final_summary[:280]}\n{compare}",
            task_id, ok=overall_ok,
        )
    except Exception as e:
        logger.error(f"[code_mode] background task {task_id} failed: {e}", exc_info=True)
        _update_task(db, task_id, status="failed", error=str(e), meta_updates={"error": str(e)})
        _finish_mission(db, mission_id, False)
        try:
            await _notify_done(user_id, "⚠️ Code task failed", str(e)[:280], task_id, ok=False)
        except Exception:
            pass
    finally:
        try:
            if session is not None:
                s = db.query(CodeSession).filter(CodeSession.id == session.id).first()
                if s:
                    s.state = "idle"
                    s.cancel_requested = False
                    db.commit()
        except Exception:
            pass
        db.close()
