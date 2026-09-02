"""
Agent Dispatch Service — Task execution via Claude Code on the VM.

All background agent tasks are dispatched to the VM (sara@10.185.1.176)
where Claude Code runs with Qwen3.5-122B. The VM has shell access, PDF
reading, multimodal vision, and web research capabilities.

Falls back to InternalToolAgent if the VM is unreachable.
"""

import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from app.core.redis import get_redis
from sqlalchemy.orm import Session

import shlex

from app.core.timezone import now as local_now
from app.services.event_bus import event_bus, EventType, Event
from app.services.note_provenance import SARA_GENERATED_TAG
from app.services.vm_bridge import VMBridge, VMConfig, VMConnectionStatus, get_vm_config_from_settings

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DISPATCH_LIVE_CHANNEL = "sara:dispatch:live:{task_id}"


async def _publish_dispatch_event(task_id: str, entry: dict):
    """Publish a live execution event to the dispatch SSE channel."""
    try:
        r = await get_redis()
        channel = DISPATCH_LIVE_CHANNEL.format(task_id=task_id)
        payload = json.dumps(entry, default=str)
        await r.publish(channel, payload)
    except Exception as e:
        logger.warning(f"[dispatch] Redis publish failed: {e}")

# Working directory on the sandbox VM
DISPATCH_WORKING_DIR = "~/sandbox"

# Playwright runner for the `browse` tool. Lives on the VM at
# ~/.sara-browse/browse.js and is (re)written on demand so the capability
# self-heals across VM resets. Drives the snap-bundled Chromium directly
# (executablePath) so NO root/system libraries are needed — the snap ships its
# own libs. Args: <url> [screenshot_path] [wait_for_selector]; prints JSON.
BROWSE_DIR = "~/.sara-browse"
BROWSE_CHROME = "/snap/chromium/current/usr/lib/chromium-browser/chrome"
BROWSE_JS = r'''const { chromium } = require('playwright');
(async () => {
  const url = process.argv[2];
  const shot = process.argv[3] || '';
  const waitFor = process.argv[4] || '';
  const out = { url };
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath: '__CHROME__', args: ['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage'] });
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    if (waitFor) { try { await page.waitForSelector(waitFor, { timeout: 10000 }); } catch (e) {} }
    await page.waitForTimeout(800);
    out.title = await page.title();
    out.text = (await page.evaluate(() => document.body ? document.body.innerText : '')).slice(0, 8000);
    out.links = await page.evaluate(() =>
      Array.from(document.querySelectorAll('a')).slice(0, 40)
        .map(a => ({ text: (a.innerText||'').trim().slice(0,80), href: a.href }))
        .filter(l => l.href && l.text));
    if (shot) { await page.screenshot({ path: shot, fullPage: false }); out.screenshot = shot; }
    out.ok = true;
  } catch (e) {
    out.ok = false; out.error = String(e).slice(0, 500);
  } finally {
    if (browser) await browser.close();
  }
  process.stdout.write(JSON.stringify(out));
})();
'''.replace("__CHROME__", BROWSE_CHROME)


BROWSE_SHOTS_DIR = os.path.abspath(os.environ.get("BROWSE_SHOTS_DIR", "/app/uploads/browse"))


async def _pull_browse_screenshot(bridge: VMBridge, vm_rel_path: str) -> str | None:
    """scp a browse screenshot off the VM and return a servable URL, or None.

    `vm_rel_path` is relative to ~/.sara-browse (e.g. 'shots/abc.png').
    """
    try:
        os.makedirs(BROWSE_SHOTS_DIR, exist_ok=True)
        name = f"{uuid.uuid4().hex}.png"
        local_path = os.path.join(BROWSE_SHOTS_DIR, name)
        home = f"/home/{bridge.config.username}"
        remote = f"{home}/.sara-browse/{vm_rel_path}"
        res = await bridge.scp_from_vm(remote, local_path)
        if getattr(res, "exit_code", 1) != 0 or not os.path.isfile(local_path):
            logger.warning(f"[browse] scp screenshot failed: {getattr(res, 'stderr', '')[:200]}")
            return None
        # Must match the host the CLIENT app uses to reach the API — NOT
        # settings.backend_url (that points at the frontend domain and returns
        # HTML). Dev: the LAN backend; prod: set BROWSE_SHOTS_BASE_URL=https://sara-api.avery.cloud
        base = os.environ.get("BROWSE_SHOTS_BASE_URL", "http://10.185.1.180:8000").rstrip("/")
        return f"{base}/api/browse-shots/{name}"
    except Exception as e:
        logger.warning(f"[browse] screenshot pull error: {e}")
        return None


async def _ensure_browse_runner(bridge: VMBridge) -> None:
    """Write ~/.sara-browse/browse.js on the VM if it's missing (idempotent)."""
    check = await bridge.execute_command(
        f"test -f {BROWSE_DIR}/browse.js && echo yes || echo no", timeout=20,
    )
    if "yes" in check.stdout:
        return
    marker = "SARA_BROWSE_EOF"
    escaped = BROWSE_JS.replace("\\", "\\\\")
    cmd = (
        f"mkdir -p {BROWSE_DIR}/shots && cat > {BROWSE_DIR}/browse.js << '{marker}'\n"
        f"{escaped}\n{marker}"
    )
    await bridge.execute_command(cmd, timeout=30)


def _resolve_vm_path(path: str, working_dir: str, username: str = "sara") -> str:
    """Resolve a path argument from the dispatch LLM into a concrete VM path.

    The dispatch tools (write_file, read_file) used to do
    `if not path.startswith("/"): path = f"{working_dir}/{path}"`
    which combined with `shlex.quote` produced literal `~/sandbox/~/sandbox/...`
    paths whenever the LLM passed a tilde-prefixed path. SSH single-quotes
    suppress shell tilde expansion, so the file got written to the wrong place
    on the VM.

    This helper normalizes once, before quoting:
      - `~/foo`        → `/home/{username}/foo`
      - `~`            → `/home/{username}`
      - `/abs/path`    → unchanged
      - `relative`     → `{resolved working_dir}/relative`

    `working_dir` itself is also resolved if it's tilde-prefixed.
    """
    home = f"/home/{username}"
    if path == "~":
        return home
    if path.startswith("~/"):
        return home + path[1:]
    if path.startswith("/"):
        return path
    # Relative — anchor against the (possibly tilde-prefixed) working dir
    base = working_dir or ""
    if base == "~":
        base = home
    elif base.startswith("~/"):
        base = home + base[1:]
    return f"{base.rstrip('/')}/{path}" if base else path

# Tool definitions for the dispatch LLM loop (same pattern as ACS session_manager)
DISPATCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Execute a shell command on the sandbox VM. You have full access "
                "to bash, Python, git, Docker, curl, etc. "
                f"Working directory: {DISPATCH_WORKING_DIR}/"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Seconds to allow before killing (default 120). Raise it "
                                       "for long builds/installs — up to 3600.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file on the sandbox VM",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            f"File path (relative to {DISPATCH_WORKING_DIR}/ or absolute)"
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "File content to write",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the sandbox VM",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to read",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web using SearXNG. Use this to look up documentation, "
                "troubleshoot errors, find API references, or research how to do things. "
                "Returns top results with titles, URLs, and snippets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return (default 5)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_code_task",
            "description": (
                "Hand off a CODING task to Sara's dedicated autonomous coder (the same engine "
                "as the /code chat mode). It clones the GitHub repo on the VM, edits, runs tests, "
                "commits, and pushes a branch — all in the background. Use this when the work is "
                "real software changes against a git repo, rather than ad-hoc shell. Returns once "
                "the coder is dispatched; it finishes asynchronously and notifies the user."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Clear description of the code change to make.",
                    },
                    "repo": {
                        "type": "string",
                        "description": "Optional GitHub repo as 'owner/name'. Omit to use the most-recent/default repo.",
                    },
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse",
            "description": (
                "Open a web page in a real headless browser (Playwright/Chromium) on the "
                "sandbox VM and get back the page title, visible text, links, and a "
                "screenshot. Use this to TEST or INSPECT a web app/page, verify a deploy "
                "rendered, read JS-heavy sites that web_search can't, or check a UI."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to open (http/https)."},
                    "wait_for": {
                        "type": "string",
                        "description": "Optional CSS selector to wait for before reading (e.g. '#app', '.results').",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_complete",
            "description": (
                "Signal that the task is complete. Call this when you have finished "
                "all steps of the task. Provide a summary of what was accomplished."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Summary of what was done and the result",
                    },
                    "success": {
                        "type": "boolean",
                        "description": "Whether the task completed successfully",
                    },
                },
                "required": ["summary"],
            },
        },
    },
]


async def _execute_dispatch_tool(
    bridge: VMBridge, name: str, args: dict, working_dir: str, user_id: str | None = None,
) -> str:
    """Execute a dispatch tool call via VMBridge."""
    try:
        if name == "run_command":
            command = args.get("command", "")
            if not command.strip():
                return "Error: empty command"
            # Timeout is agent-adjustable (Phase 4): default 120s, but a real
            # build/install on a managed host can request up to 1h.
            try:
                timeout = int(args.get("timeout") or 120)
            except (TypeError, ValueError):
                timeout = 120
            timeout = max(5, min(timeout, 3600))
            result = await bridge.execute_command(
                f"cd {working_dir} && {command}", timeout=timeout,
            )
            if result.timed_out:
                return (f"Command timed out after {timeout}s. If this was a long "
                        f"build/install, retry with a larger `timeout` (up to 3600).")
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            if result.exit_code != 0:
                output += f"\n(exit code {result.exit_code})"
            return output[:10000] or "(no output)"

        elif name == "write_file":
            raw_path = args.get("path", "")
            content = args.get("content", "")
            if not raw_path:
                return "Error: no path provided"
            path = _resolve_vm_path(raw_path, working_dir, bridge.config.username)
            marker = "SARA_EOF_MARKER"
            escaped_content = content.replace("\\", "\\\\")
            cmd = (
                f"mkdir -p $(dirname {shlex.quote(path)}) && "
                f"cat > {shlex.quote(path)} << '{marker}'\n{escaped_content}\n{marker}"
            )
            result = await bridge.execute_command(cmd, timeout=30)
            if result.exit_code != 0:
                return f"Error writing file: {result.stderr}"
            return f"Wrote {len(content)} bytes to {path}"

        elif name == "read_file":
            raw_path = args.get("path", "")
            if not raw_path:
                return "Error: no path provided"
            path = _resolve_vm_path(raw_path, working_dir, bridge.config.username)
            result = await bridge.execute_command(
                f"cat {shlex.quote(path)}", timeout=30,
            )
            if result.exit_code != 0:
                return f"Error reading file: {result.stderr}"
            return result.stdout[:10000] or "(empty file)"

        elif name == "web_search":
            query = args.get("query", "")
            if not query:
                return "Error: no query provided"
            max_results = int(args.get("max_results", 5))
            try:
                from app.services.search_service import search_service
                result = await search_service.web_search(
                    query=query, max_results=max_results,
                )
                results = result.get("results", [])
                lines = [f"Web search: '{query}' — {len(results)} results\n"]
                for i, r in enumerate(results[:max_results], 1):
                    title = r.get("title", "")
                    url = r.get("url", "")
                    snippet = r.get("snippet", "")[:300]
                    lines.append(f"{i}. {title}\n   {url}\n   {snippet}\n")
                return "\n".join(lines) or "No results found"
            except Exception as e:
                return f"Web search error: {e}"

        elif name == "start_code_task":
            if not user_id:
                return "Error: start_code_task is unavailable in this context (no user)."
            task = (args.get("task") or "").strip()
            if not task:
                return "Error: no task provided"
            repo = (args.get("repo") or "").strip()
            try:
                from app.services import code_mode
                acks: list[str] = []

                async def _drain(text: str):
                    q: asyncio.Queue = asyncio.Queue()
                    await code_mode.run_code_message(None, user_id, None, text, q)
                    while True:
                        ev = await q.get()
                        if ev is None:
                            break
                        if ev.get("type") == "text_chunk":
                            acks.append(ev.get("data", {}).get("content", ""))

                # Bind a specific repo first if requested, then dispatch the task.
                if repo:
                    await _drain(f"/code start {repo}")
                await _drain(f"/code {task}")
                msg = (acks[-1] if acks else "Coder dispatched.").strip()
                return f"Code task handed off to the autonomous coder.\n{msg}"
            except Exception as e:
                logger.error(f"[dispatch] start_code_task failed: {e}", exc_info=True)
                return f"Failed to start code task: {e}"

        elif name == "browse":
            url = (args.get("url") or "").strip()
            if not url:
                return "Error: no url provided"
            if not re.match(r"^https?://", url):
                url = "https://" + url
            wait_for = (args.get("wait_for") or "").strip()
            await _ensure_browse_runner(bridge)
            shot = f"shots/{uuid.uuid4().hex[:12]}.png"
            cmd = (
                f"cd {BROWSE_DIR} && node browse.js {shlex.quote(url)} "
                f"{shlex.quote(shot)} {shlex.quote(wait_for)} 2>/dev/null"
            )
            result = await bridge.execute_command(cmd, timeout=90)
            raw = result.stdout.strip()
            try:
                data = json.loads(raw)
            except Exception:
                combined = result.stdout + result.stderr
                hint = ""
                if "Cannot find module 'playwright'" in combined:
                    hint = " (playwright npm missing on VM — `cd ~/.sara-browse && npm i playwright`)"
                elif "shared libraries" in combined or "libatk" in combined:
                    hint = " (browser libs missing — falls back from snap chromium; check executablePath)"
                return f"Browse failed: couldn't parse browser output{hint}. Raw: {raw[:300]}"
            if not data.get("ok"):
                return f"Browse error for {url}: {data.get('error', 'unknown')}"
            lines = [f"# {data.get('title') or '(no title)'}", f"URL: {data.get('url')}"]
            if data.get("screenshot"):
                shot_url = await _pull_browse_screenshot(bridge, data["screenshot"])
                if shot_url:
                    # Embed as a markdown image so the agent can drop it straight
                    # into its report and David sees it inline.
                    lines.append(f"Screenshot (embed in your report): ![screenshot of {url}]({shot_url})")
                else:
                    lines.append(f"Screenshot saved on VM: ~/.sara-browse/{data['screenshot']}")
            text = (data.get("text") or "").strip()
            if text:
                lines.append("\n## Visible text\n" + text[:6000])
            links = data.get("links") or []
            if links:
                lines.append("\n## Links")
                for l in links[:25]:
                    lines.append(f"- [{l.get('text','')}]({l.get('href','')})")
            return "\n".join(lines)[:9000]

        elif name == "report_complete":
            summary = args.get("summary", "Task complete")
            return f"__TASK_COMPLETE__:{summary}"

        else:
            return f"Unknown tool: {name}"

    except Exception as e:
        logger.error(f"[dispatch] Tool execution error ({name}): {e}")
        return f"Tool execution error: {e}"


async def _dispatch_llm_call(
    messages: list[dict],
    model: str | None = None,
    tools: list[dict] | None = None,
    max_retries: int = 3,
) -> dict:
    """Call the background LLM with tool definitions and retry on transient errors."""
    from app.core.llm import BackgroundLLMClient
    import httpx

    client = BackgroundLLMClient()
    extra_body = {
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if tools:
        extra_body["tools"] = tools
        extra_body["tool_choice"] = "auto"

    last_error = None
    for attempt in range(max_retries):
        try:
            return await client.chat_completion(
                messages=messages,
                temperature=0.7,
                # 12K tokens (≈48 KB) — enough for a multi-page research
                # synthesis in one turn. Stays well under the 64K context
                # ceiling we measured on the MLX endpoint at .115:8081.
                max_tokens=12288,
                model=model,
                # 30 min: a research synthesis over a large accumulated context
                # is genuinely slow on the MLX endpoint. A timeout this long only
                # trips on a real stall, not on a job that's still working.
                request_timeout=1800.0,
                allow_during_lesson_generation=True,
                allow_fallback=False,  # primary endpoint only — no failover
                extra_body=extra_body,
            )
        except httpx.TimeoutException as e:
            # A 30-minute read timeout means the endpoint truly stalled. Retrying
            # just re-sends the same large prompt for another 30 min, so treat it
            # as a hard failure rather than burning another hour.
            logger.error(f"[dispatch] LLM call timed out after 30 min — treating as failure, not retrying: {e}")
            raise
        except (httpx.HTTPStatusError, httpx.ConnectError) as e:
            last_error = e
            wait = 10 * (attempt + 1)
            logger.warning(f"[dispatch] LLM call failed (attempt {attempt + 1}/{max_retries}): {e}, retrying in {wait}s")
            await asyncio.sleep(wait)

    raise last_error


async def _dispatch_llm_call_with_heartbeat(
    messages: list[dict],
    model: str | None,
    tools: list[dict],
    task_id: str | None,
    rounds: int,
    heartbeat_secs: float = 15.0,
):
    """Run _dispatch_llm_call while emitting periodic heartbeat events.

    The LLM call can legitimately take many minutes (a large synthesis over the
    MLX endpoint can run up to the 30-min ceiling). With no events during that
    window the live view shows a blank pane and looks hung. This pulses a
    `heartbeat` event every ~15s so the watcher can see the model is still
    working, and surfaces a visible `error` event if the call fails.
    """
    call = asyncio.ensure_future(_dispatch_llm_call(messages, model=model, tools=tools))
    waited = 0
    try:
        while True:
            done, _ = await asyncio.wait({call}, timeout=heartbeat_secs)
            if done:
                return call.result()  # re-raises any exception from the call
            waited += int(heartbeat_secs)
            if task_id:
                await _publish_dispatch_event(task_id, {
                    "type": "heartbeat",
                    "ts": local_now().isoformat(),
                    "round": rounds,
                    "message": f"Waiting on model… ({waited}s)",
                })
    except Exception as e:
        if task_id:
            await _publish_dispatch_event(task_id, {
                "type": "error",
                "ts": local_now().isoformat(),
                "round": rounds,
                "message": f"Model call failed: {type(e).__name__}: {e}",
            })
        raise


# Compaction tuning. Empirically the failure mode is "22 web_searches × ~3-10 KB
# each, then the model can't fit the prompt." `KEEP_RECENT_TOOL_RESULTS` is the
# sliding window of full-fidelity tool results the model sees; older ones are
# replaced with a 1-line marker that preserves message-shape (tool_call_id,
# tool name) but elides the bulky content. 8 is enough that the model can
# cross-reference its most-recent searches without re-running them, and small
# enough that a 30-call task still leaves ~75% of the 64K budget for the
# synthesis turn.
KEEP_RECENT_TOOL_RESULTS = 8


def _compact_tool_history(messages: list[dict], keep_recent: int = KEEP_RECENT_TOOL_RESULTS) -> int:
    """Replace older `tool`-role message contents with a short marker so the
    conversation log doesn't outgrow the LLM's context window on long runs.

    Idempotent: already-compacted entries (content starts with "[compacted:")
    are skipped, so calling this every loop iteration is cheap.

    Returns the number of tool messages compacted on this call.
    """
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    if len(tool_indices) <= keep_recent:
        return 0

    # Tool-call id → tool name lookup so the marker can name the elided call.
    call_id_to_name: dict[str, str] = {}
    for m in messages:
        for tc in (m.get("tool_calls") or []):
            cid = tc.get("id")
            name = (tc.get("function") or {}).get("name")
            if cid and name:
                call_id_to_name[cid] = name

    compacted_now = 0
    for i in tool_indices[:-keep_recent]:
        m = messages[i]
        content = m.get("content") or ""
        if not content or content.startswith("[compacted:"):
            continue
        tool_name = call_id_to_name.get(m.get("tool_call_id", ""), "tool")
        m["content"] = (
            f"[compacted: {tool_name} result ({len(content)} chars elided to save context)]"
        )
        compacted_now += 1
    return compacted_now


_PREAMBLE_TAIL_PHRASES = (
    "let me create", "let me write", "let me build", "let me draft",
    "let me put together", "let me compile", "let me synthesize",
    "let me now", "let me proceed", "let me go ahead",
    "now i'll", "now i will", "i'll now", "i will now",
    "now i can create", "now i can write", "now i can build",
    "i can now create", "i can now write",
    "i have enough", "i now have enough",
    "here it is", "here's the document", "here is the document",
    "here's the final", "here is the final",
)


# The model sometimes writes its tool calls as prose instead of emitting real
# structured tool_calls — e.g. '[Calling tool: browse("https://...")]' or a raw
# <tool_call> block. Those were never executed, so a "final" response containing
# them is an abandoned turn, not a deliverable.
_TEXT_TOOL_CALL_RE = re.compile(
    r"\[calling\s+tool\b"  # any separator: "[Calling tool: x]", "[Calling tool=x]", …
    r"|<tool_call>|\[tool_call\]"
    r"|^\s*\{\s*\"name\"\s*:\s*\"\w+\"\s*,\s*\"arguments\"",
    re.I | re.M,
)


def _contains_text_tool_calls(text: str) -> bool:
    return bool(text and _TEXT_TOOL_CALL_RE.search(text))


# qwen intermittently drops out of its JSON <tool_call> format into an XML-ish
# dialect (`<function=web_search>\n<parameter=query>…</parameter>\n</function>`)
# that the server's parser doesn't recognize — the calls land in `content` and
# nothing executes. Nudging doesn't reliably recover it (observed failing 2/2
# runs on 2026-06-12), so we re-parse that dialect and execute the calls.
_TEXT_FUNC_BLOCK_RE = re.compile(r"<function=([\w.\-]+)>(.*?)</function>", re.S)
_TEXT_PARAM_RE = re.compile(r"<parameter=([\w.\-]+)>\s*(.*?)\s*</parameter>", re.S)


def _parse_text_tool_calls(content: str, valid_names: set) -> list[dict]:
    """Salvage tool calls the model wrote as text. Returns OpenAI-shaped
    tool_call dicts (arguments JSON-encoded), skipping unknown tool names."""
    calls = []
    for m in _TEXT_FUNC_BLOCK_RE.finditer(content or ""):
        name, body = m.group(1), m.group(2)
        if name not in valid_names:
            continue
        args = {k: v for k, v in _TEXT_PARAM_RE.findall(body)}
        calls.append({
            "id": f"salvaged_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        })
    return calls


def _strip_text_tool_calls(content: str) -> str:
    """Remove salvaged text-format call blocks so the model's own malformed
    syntax doesn't stay in history and reinforce the habit next round."""
    cleaned = _TEXT_FUNC_BLOCK_RE.sub("", content or "")
    cleaned = cleaned.replace("<tool_call>", "").replace("</tool_call>", "")
    return cleaned.strip()


# ── Final-report synthesis ───────────────────────────────────────────────────
#
# The tool-use loop is reliable at GATHERING and unreliable at WRITING: after
# many rounds of tool calls the local model tends to end with two sentences
# and a screenshot gallery instead of the asked-for report. Rather than nudge
# a tool-fatigued context into long-form writing, we run one clean no-tools
# completion over a digest of everything the run gathered. That call has one
# job — write the deliverable — and does it far more consistently.

_RESEARCH_TOOLS = {"web_search", "web_fetch", "browse", "search_memory",
                   "search_notes", "read_file"}

_MD_HEADER_RE = re.compile(r"^#{1,3} \S", re.M)


def _is_report_grade(text: str) -> bool:
    """Does the loop's final output already read like a written deliverable?
    Screenshot galleries and bare URLs don't count as substance."""
    if not text:
        return False
    substance = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    substance = re.sub(r"^\s*\*\*https?://\S+\*\*\s*$", "", substance, flags=re.M)
    substance = substance.strip()
    return len(substance) >= 1200 and len(_MD_HEADER_RE.findall(substance)) >= 2


def _digest_execution_log(execution_log: list, cap: int = 60000) -> str:
    """Compact the run's research tool results into one synthesis-ready digest."""
    parts = []
    total = 0
    for e in execution_log or []:
        if e.get("type") != "tool_call" or e.get("tool") not in _RESEARCH_TOOLS:
            continue
        args = json.dumps(e.get("args") or {})[:200]
        result = str(e.get("result") or "")[:6000]
        chunk = f"### {e.get('tool')} {args}\n{result}\n"
        if total + len(chunk) > cap:
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n".join(parts)


async def _synthesize_report(
    task_description: str, execution_log: list, draft: str,
) -> str | None:
    """Dedicated no-tools writing pass. Returns the report markdown (starting
    with a '# ' title line), or None when there's nothing to write from or
    the pass itself produced junk."""
    digest = _digest_execution_log(execution_log)
    if len(digest) < 1500:
        return None
    user_parts = [f"## Task\n{task_description}"]
    if draft and draft.strip():
        user_parts.append(f"## The agent's own closing notes\n{draft.strip()[:3000]}")
    user_parts.append(f"## Gathered material\n{digest}")
    messages = [
        {"role": "system", "content": (
            "You are writing the final deliverable for a completed research "
            "task. You are given the task and the raw material gathered "
            "(search results, page contents). Write the full report now — "
            "comprehensive, well-structured markdown, starting with a single "
            "'# ' title line naming the deliverable (use the title the task "
            "asked for, if it specified one). Use only the gathered material; "
            "if something the task asked for is not in the material, note it "
            "briefly under a 'Gaps' heading instead of inventing it. No "
            "preamble, no meta-commentary — output the report only."
        )},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]
    try:
        result = await _dispatch_llm_call(messages, model=None, tools=None,
                                          max_retries=2)
        content = ((result.get("choices") or [{}])[0]
                   .get("message", {}).get("content") or "").strip()
        if len(content) >= 800 and not _contains_text_tool_calls(content):
            return content
        logger.warning(
            "[dispatch] synthesis pass produced unusable output (%d chars)",
            len(content),
        )
    except Exception as e:
        logger.warning(f"[dispatch] synthesis pass failed: {e}")
    return None


# Returned (success=False) when the model keeps narrating tool calls as text
# after nudging. Listed in the caller's salvage sentinels so empty-handed runs
# fail loudly instead of shipping a transcript as a "report".
FAKE_TOOL_CALL_FAILURE = (
    "The agent kept writing its tool calls as plain text instead of executing "
    "them, so no actual research was performed and no report was produced."
)


def _looks_like_preamble(text: str) -> bool:
    """Detect when an LLM 'final' text response is actually a preamble — the
    model announced what it was about to write, but never wrote it. Symptoms:

      - Trailing colon ("Let me create it:")
      - Future-tense announcement near the end ("now I'll write…", "let me
        synthesize…", "here is the document:")

    When this fires we don't accept the text as final; we nudge the model
    once and let the loop continue.
    """
    if not text:
        return False
    trimmed = text.rstrip().rstrip("*_`")
    if trimmed.endswith(":"):
        return True
    tail = trimmed[-240:].lower()
    return any(phrase in tail for phrase in _PREAMBLE_TAIL_PHRASES)


async def _dispatch_llm_loop(
    messages: list[dict],
    model: str | None,
    tools: list[dict],
    bridge: VMBridge,
    working_dir: str,
    max_rounds: int = 50,
    task_id: str | None = None,
    user_id: str | None = None,
) -> tuple[str, bool, list[dict]]:
    """Multi-round LLM tool-use loop. Returns (output, success, execution_log).

    Stops when:
    - The LLM calls report_complete
    - The LLM returns a text response with no tool calls AND that response
      doesn't look like an interrupted preamble
    - max_rounds is exceeded
    """
    rounds = 0
    execution_log: list[dict] = []
    tools_executed = 0
    # Cap how many times we'll nudge past a preamble — without this, a model
    # stuck in announce-mode could burn the full max_rounds budget on filler.
    preamble_nudges_used = 0
    max_preamble_nudges = 2

    # Let the live view show something the moment the loop starts, before the
    # first (possibly slow) LLM call publishes any tool/response event.
    if task_id:
        await _publish_dispatch_event(task_id, {
            "type": "status",
            "ts": local_now().isoformat(),
            "round": 0,
            "message": "Starting — sending the task to the model…",
        })

    while rounds < max_rounds:
        compacted = _compact_tool_history(messages)
        if compacted:
            logger.info(
                "[dispatch] Compacted %d older tool result(s) before round %d (sliding window keeps %d most-recent)",
                compacted, rounds, KEEP_RECENT_TOOL_RESULTS,
            )

        # Tell the watcher we're calling the model this round, so the pane isn't
        # blank while the call is in flight (heartbeats follow if it runs long).
        if task_id:
            await _publish_dispatch_event(task_id, {
                "type": "status",
                "ts": local_now().isoformat(),
                "round": rounds,
                "message": "Thinking…" if rounds == 0 else f"Thinking… (round {rounds + 1})",
            })

        result = await _dispatch_llm_call_with_heartbeat(
            messages, model=model, tools=tools, task_id=task_id, rounds=rounds,
        )

        choices = result.get("choices", [])
        if not choices:
            return f"LLM returned no choices: {result}", False, execution_log

        choice = choices[0]
        msg = choice.get("message", {})
        tool_calls = msg.get("tool_calls")
        finish_reason = choice.get("finish_reason")

        if not tool_calls:
            salvaged = _parse_text_tool_calls(
                msg.get("content") or "",
                {t["function"]["name"] for t in tools},
            )
            if salvaged:
                logger.warning(
                    "[dispatch] Salvaged %d text-format tool call(s) the server "
                    "didn't parse (round %d)", len(salvaged), rounds,
                )
                # Log every salvage to the interoception ledger so tool-call dialect
                # drift is *seen*, not silently absorbed (Phase 5.2). If salvages
                # start spiking, the constrained-decoding/grammar work is overdue.
                try:
                    from app.services.diagnostics_service import record_system_event
                    await record_system_event(
                        category="qwen_tool_salvage", service="agent_dispatch",
                        level="WARNING",
                        message=f"Salvaged {len(salvaged)} text-format tool call(s) qwen emitted as plain text",
                        meta={"count": len(salvaged), "round": rounds,
                              "tool_names": [s.get("function", {}).get("name") for s in salvaged]},
                    )
                except Exception:
                    pass
                msg["content"] = _strip_text_tool_calls(msg.get("content") or "")
                tool_calls = salvaged

        if not tool_calls:
            content = msg.get("content", "") or msg.get("reasoning_content", "") or ""

            # Three ways the "no tool calls" branch can be a lie:
            #   1. finish_reason="length" — the model was mid-output when
            #      max_tokens cut it off. Treating that as the final answer
            #      ships a truncated deliverable.
            #   2. Content reads as a preamble ("…let me create it:") — the
            #      model announced the deliverable but never produced it.
            #   3. Content contains tool calls written as plain text
            #      ("[Calling tool: browse(...)]") — the model thought it was
            #      calling tools but nothing was executed.
            truncated = finish_reason == "length"
            preamble = _looks_like_preamble(content)
            fake_tool_calls = _contains_text_tool_calls(content)
            # 4. A few-sentence "final" after a long tool session, without ever
            #    calling report_complete — the deliverable never materialized.
            thin_final = tools_executed >= 3 and len((content or "").strip()) < 500
            if (truncated or preamble or fake_tool_calls or thin_final) \
                    and preamble_nudges_used < max_preamble_nudges:
                preamble_nudges_used += 1
                logger.warning(
                    "[dispatch] Rejecting premature finish (round=%s, truncated=%s, "
                    "preamble=%s, fake_tool_calls=%s, thin_final=%s, nudge=%s/%s); tail=%r",
                    rounds, truncated, preamble, fake_tool_calls, thin_final,
                    preamble_nudges_used, max_preamble_nudges,
                    (content or "")[-160:],
                )
                entry = {
                    "type": "llm_response",
                    "ts": local_now().isoformat(),
                    "round": rounds,
                    "content": (content or "")[:10000],
                    "premature_finish": True,
                    "finish_reason": finish_reason,
                }
                execution_log.append(entry)
                if task_id:
                    await _publish_dispatch_event(task_id, entry)

                # Carry the announcement forward so the model sees what it just
                # said, then redirect it to actually deliver.
                messages.append({"role": "assistant", "content": content})
                if truncated:
                    nudge = (
                        "Your previous turn was truncated by the token limit before you "
                        "finished. Continue from where you left off and deliver the full "
                        "result. Use write_file to save long documents, or call "
                        "report_complete with the complete content."
                    )
                elif fake_tool_calls:
                    nudge = (
                        "You wrote your tool calls as plain text in your response — they "
                        "were NOT executed. Nothing happens unless you emit them as real "
                        "function/tool calls. Re-issue them as actual tool calls now, and "
                        "once you have what you need, call report_complete with the full "
                        "report content."
                    )
                elif thin_final:
                    nudge = (
                        f"You've executed {tools_executed} tools but ended with only a few "
                        "sentences and never called report_complete. That is not the "
                        "deliverable. If you are finished, call report_complete NOW with "
                        "the FULL report content as the summary — everything you found, "
                        "fully written out. If you are not finished, continue working "
                        "with real tool calls."
                    )
                else:
                    nudge = (
                        "You announced the deliverable but didn't actually produce it. "
                        "Now produce it: either call write_file to save a long document "
                        "to disk, or call report_complete with the full content as the "
                        "summary. Don't just describe what you're about to do."
                    )
                messages.append({"role": "user", "content": nudge})
                rounds += 1
                continue

            # Final text response — no more tool calls
            final_text = content or "Task completed (no output)"
            entry = {
                "type": "llm_response",
                "ts": local_now().isoformat(),
                "round": rounds,
                "content": final_text[:10000],
            }
            execution_log.append(entry)
            if task_id:
                await _publish_dispatch_event(task_id, entry)
            if fake_tool_calls:
                # Nudges exhausted and the model is still narrating tool calls
                # instead of executing them — there is no deliverable here.
                return FAKE_TOOL_CALL_FAILURE, False, execution_log
            return final_text, True, execution_log

        # Log LLM reasoning/content if present
        llm_content = msg.get("content") or ""
        if llm_content.strip():
            entry = {
                "type": "llm_response",
                "ts": local_now().isoformat(),
                "round": rounds,
                "content": llm_content[:10000],
            }
            execution_log.append(entry)
            if task_id:
                await _publish_dispatch_event(task_id, entry)

        # Append assistant message with tool calls
        assistant_msg = {"role": "assistant", "content": llm_content}
        assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        # Execute each tool call
        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            try:
                tool_args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                # H5 (Brain Alignment): degrade to empty args (never leak the raw
                # parse error) but make the failure observable in the funnel.
                tool_args = {}
                try:
                    from app.services.silent_failure_tracker import Tracker
                    Tracker("dispatch.tool_arg_parse").note(tool_name or "unknown")
                except Exception:
                    pass

            logger.info(f"[dispatch] Tool call: {tool_name}({json.dumps(tool_args)[:200]})")

            tool_start = time.monotonic()
            output = await _execute_dispatch_tool(bridge, tool_name, tool_args, working_dir, user_id=user_id)
            tool_duration_ms = int((time.monotonic() - tool_start) * 1000)
            tools_executed += 1

            # Log tool call
            entry = {
                "type": "tool_call",
                "ts": local_now().isoformat(),
                "round": rounds,
                "tool": tool_name,
                "args": tool_args,
                "result": output[:10000],
                "duration_ms": tool_duration_ms,
            }
            execution_log.append(entry)
            if task_id:
                await _publish_dispatch_event(task_id, entry)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", str(uuid.uuid4())),
                "content": output,
            })

            # Check for report_complete signal
            if output.startswith("__TASK_COMPLETE__:"):
                summary = output[len("__TASK_COMPLETE__:"):]
                success = tool_args.get("success", True)
                return summary, success, execution_log

        rounds += 1

    return "(Maximum tool-call rounds reached)", False, execution_log

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

    def _resolve_bridge(self, db: Session, user_id: str, task) -> tuple[VMBridge, str, Optional[str]]:
        """Pick the SSH transport for a task.

        If task_metadata names a `target_host` (a registered ManagedHost), the
        agent runs on THAT machine. Otherwise it runs on the user's sandbox VM.

        Returns (bridge, label, working_dir_override).
        """
        target = (task.task_metadata or {}).get("target_host") if task else None
        if target:
            from app.services import host_inspector
            host = host_inspector.get_host(db, user_id, target)
            if host:
                # Remote managed hosts have no ~/sandbox scaffold — work from $HOME.
                return host_inspector.bridge_for(host), f"{host.name} ({host.hostname})", "~"
            logger.warning(f"[dispatch] target_host '{target}' not found, using sandbox VM")
        return self._get_bridge(db, user_id), "sandbox VM", None

    async def _classify_task(self, task_description: str) -> tuple[str, str, list]:
        """Classify a task as 'internal' or 'sandbox' using a fast LLM call.

        Returns (mode, reason, categories) tuple.
        """
        from app.core.llm_config import llm_config
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{llm_config.fast_model_url}/chat/completions",
                    json={
                        "model": llm_config.fast_model,
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
                          "personal_knowledge", "home", "fitness", "learning", "inbox",
                          "shell"}
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
        notify_on_complete: bool = False,
        target_host: Optional[str] = None,
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

        # Classify task for metadata (categories help with fallback routing)
        classified_mode = None
        classification_reason = None
        classified_categories = None
        try:
            classified_mode, classification_reason, classified_categories = await self._classify_task(task_description)
            if not classified_categories:
                classified_categories = self._infer_categories(task_description)
            logger.info(
                f"[dispatch] Classified '{task_description[:60]}' "
                f"→ {classified_mode}, categories={classified_categories}"
            )
        except Exception as e:
            logger.warning(f"[dispatch] Classification failed: {e}")
            classified_categories = self._infer_categories(task_description)

        # Route on the classification instead of forcing every task onto the VM.
        # The VM shell agent has no reach into Sara's own data (email, notes,
        # reminders, calendar), so an "internal" task sent there can only flail
        # until it hits the round cap. An explicit caller mode still wins, and a
        # task pinned to a specific host must run on that host regardless.
        requested = (mode or "auto").lower()
        if target_host or working_directory:
            mode = "vm_claude"
        elif requested == "internal":
            mode = "internal"
        elif requested in ("dispatch", "vm_claude", "self_orchestrate"):
            mode = "vm_claude"
        elif classified_mode == "internal":
            mode = "internal"
        else:
            mode = "vm_claude"

        task_type = "internal_agent" if mode == "internal" else "vm_claude_agent"
        logger.info(
            f"[dispatch] Routing task → mode={mode} "
            f"(requested={requested}, classified={classified_mode})"
        )

        # Find relevant skills from past successful tasks
        relevant_skills = self._find_relevant_skills(db, user_id, task_description)
        used_skill_ids = [s["skill_id"] for s in relevant_skills]

        # Create BackgroundTask record
        task_id = str(uuid.uuid4())
        task_metadata = {
            "mode": mode,
            "working_directory": working_directory,
            "created_by": "agent_dispatch",
            "mission_id": None,  # set after mission is created
            "notify_on_complete": notify_on_complete,
            "started_at": local_now().isoformat(),
        }
        # Optional: dispatch the agent to a registered managed host instead of
        # the default sandbox VM. Validated here so a bad name fails fast.
        if target_host:
            from app.services import host_inspector
            _mh = host_inspector.get_host(db, user_id, target_host)
            if not _mh:
                return {
                    "task_id": None,
                    "status": "error",
                    "error": f"No managed host named '{target_host}'. Add it with /host add first.",
                }
            task_metadata["target_host"] = _mh.name
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
        steps = [
            {"action": "connect", "desc": "Connect to agent VM"},
            {"action": "execute", "desc": "Run Claude Code agent"},
            {"action": "report", "desc": "Compile results"},
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

        # Create ACS plan item so Sara's autonomous sessions prioritize David's request
        try:
            from app.models.acs_plan_item import ACSPlanItem
            from datetime import date
            plan_item = ACSPlanItem(
                id=str(uuid.uuid4()),
                user_id=user_id,
                plan_date=date.today(),
                title=task_description[:200],
                description=task_description,
                success_criteria=f"Complete David's request: {task_description[:200]}",
                priority=90,
                source="david_chat",
                source_ref=task_id,
                cognitive_mode="execution",
            )
            db.add(plan_item)
            db.commit()
        except Exception as e:
            logger.debug(f"[dispatch] ACS plan item creation failed (non-critical): {e}")
            try:
                db.rollback()
            except Exception:
                pass

        # Launch execution — VM primary, internal fallback.
        skill_context = task_metadata.get("skill_context", "")

        # Phase 4: run in the Celery `dispatch` worker so a backend restart doesn't
        # kill in-flight agent work (acks_late + reject_on_worker_lost are global).
        launched_via_celery = False
        try:
            from app.core.config import settings as _settings
            if getattr(_settings, "dispatch_via_celery", True):
                from app.tasks.dispatch import execute_dispatch
                execute_dispatch.delay(
                    task_id, mission_id, user_id, task_description,
                    skill_context, classified_categories or [], mode,
                )
                launched_via_celery = True
                logger.info(f"[dispatch] task {task_id} enqueued to Celery dispatch queue")
        except Exception as e:
            logger.error(f"[dispatch] Celery enqueue failed, falling back to in-process: {e}")

        if not launched_via_celery:
            if mode == "internal":
                coro = self._run_internal_mode(
                    task_id, mission_id, user_id,
                    task_description + (f"\n\n{skill_context}" if skill_context else ""),
                    categories=classified_categories,
                )
            else:
                coro = self._run_vm_claude_mode(
                    task_id, mission_id, user_id, task_description,
                    skill_context=skill_context,
                    fallback_categories=classified_categories,
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
            "message": (
                "Task dispatched to internal tools" if mode == "internal"
                else "Task dispatched to VM agent"
            ),
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
        )

        # Link old → new
        if result.get("task_id"):
            task.task_metadata = {**task.task_metadata, "superseded_by": result["task_id"]}
            db.commit()

        result["retried_from"] = task_id
        return result

    async def cancel_task(
        self,
        db: Session,
        task_id: str,
        user_id: str,
    ) -> dict:
        """Cancel a running or pending agent task."""
        from app.models.background_task import BackgroundTask
        from app.models.mission import Mission

        task = db.query(BackgroundTask).filter(
            BackgroundTask.id == task_id,
            BackgroundTask.user_id == user_id,
        ).first()
        if not task:
            return {"error": "Task not found", "task_id": task_id}

        if task.status not in ("running", "pending"):
            return {"error": f"Task is {task.status}, not cancellable", "task_id": task_id}

        # Cancel the asyncio task if it's running
        if task_id in self._running_tasks:
            async_task = self._running_tasks[task_id]
            if not async_task.done():
                async_task.cancel()
                logger.info(f"[dispatch] Cancelled asyncio task for {task_id}")
            self._running_tasks.pop(task_id, None)

        # Update task status
        task.status = "cancelled"
        meta = task.task_metadata or {}
        meta["cancelled_at"] = local_now().isoformat()
        meta["cancel_reason"] = "user_request"
        task.task_metadata = {**meta}

        # Cancel the associated mission
        mission_id = meta.get("mission_id")
        if mission_id:
            mission = db.query(Mission).filter(Mission.id == mission_id).first()
            if mission and mission.state in ("running", "pending"):
                mission.state = "cancelled"
                mission.completed_at = local_now()

        db.commit()

        # Publish cancellation event for SSE
        await _publish_dispatch_event(task_id, {
            "type": "cancelled",
            "ts": local_now().isoformat(),
        })

        logger.info(f"[dispatch] Task {task_id} cancelled by user")
        return {"status": "cancelled", "task_id": task_id}

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
                BackgroundTask.task_type.in_(["vm_agent", "self_orchestrate", "internal_agent", "vm_claude_agent"]),
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
            # error_message is what the task list/detail UIs render — leaving
            # it empty made restart-orphaned tasks look like silent failures.
            task.error_message = "Task interrupted by a backend restart — retry to re-run it"
            meta = task.task_metadata or {}
            meta["error"] = "Task abandoned by server restart"
            meta["recovered_at"] = local_now().isoformat()
            task.task_metadata = {**meta}

            # Also fail the associated mission
            mission_id = meta.get("mission_id")
            if mission_id:
                mission = db.query(Mission).filter(Mission.id == mission_id).first()
                if mission and mission.state in ("running", "pending"):
                    mission.state = "failed"
                    mission.completed_at = local_now()

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
            meta["last_resume_at"] = local_now().isoformat()

            if result["status"] == "needs_clarification":
                task.status = "needs_clarification"
                task.clarification_question = result.get("question", "")[:500]
            elif result["status"] == "completed":
                task.status = "completed"
                task.completed_at = local_now()
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
            timeout=1800,
            working_dir=meta.get("working_directory"),
        )

        # Update metadata with latest output
        meta["last_resume_output"] = result.output[:3000]
        meta["last_resume_at"] = local_now().isoformat()
        task.task_metadata = {**meta}

        if result.success:
            # Check if agent is asking a question
            if self._looks_like_question(result.output):
                task.status = "needs_clarification"
                task.clarification_question = result.output[:500]
            else:
                task.status = "completed"
                task.completed_at = local_now()
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
        notify_on_complete: bool = False,
    ) -> dict:
        """Dispatch a task originating from Sara's deliberation engine.

        Creates a mission linked to the deliberation and dispatches in auto
        mode. MINDV2 Phase 0 / F2/F3: notify_on_complete defaults to False —
        these are tasks Sara assigned herself, not something David asked
        for, and "Background task complete" announcements for self-generated
        homework were the single largest source of payload-free pushes
        (6 of 9 auto-dispatches/week, 0 engaged). Pass True explicitly for
        categories whose output is genuinely worth surfacing.
        """
        result = await self.dispatch_task(
            db=db,
            user_id=user_id,
            task_description=description,
            mode="auto",
            notify_on_complete=notify_on_complete,
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
        cutoff = local_now() - timedelta(hours=4)
        stuck_tasks = (
            db.query(BackgroundTask)
            .filter(
                BackgroundTask.user_id == user_id,
                BackgroundTask.task_type.in_(["vm_agent", "self_orchestrate", "internal_agent", "vm_claude_agent", "code_mode"]),
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
            meta["auto_expired_at"] = local_now().isoformat()
            t.task_metadata = {**meta}
            # Also fail the associated mission
            mission_id = meta.get("mission_id")
            if mission_id:
                mission = db.query(Mission).filter(Mission.id == mission_id).first()
                if mission and mission.state in ("running", "pending"):
                    mission.state = "failed"
                    mission.completed_at = local_now()
        if stuck_tasks:
            db.commit()

        # Reconcile orphaned missions: several terminal task paths historically
        # missed the mission update, leaving missions stuck in running/pending
        # forever (they surface as un-closable "open tasks" in the apps). Mirror
        # the linked task's terminal state; missions with no surviving task that
        # haven't moved in 24h are failed.
        open_missions = (
            db.query(Mission)
            .filter(
                Mission.user_id == user_id,
                Mission.state.in_(["running", "pending"]),
            )
            .all()
        )
        reconciled = 0
        for m in open_missions:
            linked = (
                db.query(BackgroundTask)
                .filter(BackgroundTask.task_metadata["mission_id"].astext == str(m.id))
                .order_by(BackgroundTask.created_at.desc())
                .first()
            )
            if linked and linked.status in ("completed", "failed", "cancelled", "superseded"):
                m.state = "done" if linked.status == "completed" else "failed"
                m.completed_at = m.completed_at or local_now()
                reconciled += 1
            elif not linked and m.updated_at and m.updated_at < cutoff - timedelta(hours=20):
                m.state = "failed"
                m.completed_at = local_now()
                reconciled += 1
        if reconciled:
            db.commit()
            logger.info(f"[dispatch] Reconciled {reconciled} orphaned missions to terminal state")

        tasks = (
            db.query(BackgroundTask)
            .filter(
                BackgroundTask.user_id == user_id,
                BackgroundTask.task_type.in_(["vm_agent", "self_orchestrate", "internal_agent", "vm_claude_agent", "code_mode"]),
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
            if task.started_at is None:
                task.started_at = local_now()
            db.commit()
            await self._emit_progress(user_id, task_id, "running",
                                      summary="Connecting to sandbox VM...")

            status = await bridge.test_connection()
            if status.value != "connected":
                self._update_mission_step(db, mission_id, 0, "failed",
                                          error=f"VM {status.value}")
                self._update_mission_state(db, mission_id, "failed")
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
                self._update_mission_state(db, mission_id, "failed")
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
            task.completed_at = local_now()
            meta["output"] = summary[:5000]
            meta["artifacts"] = artifacts
            task.task_metadata = {**meta}

            # Create result note + pull VM artifacts into notes
            note_id = await self._create_result_note(
                db, user_id, task_description, summary,
                artifacts=artifacts,
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
                    elapsed = (local_now() - start_dt).total_seconds()
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

            await self._deliver_result_to_user(
                db, user_id, task_id, task_description, summary, note_id,
            )
            await self._emit_progress(user_id, task_id, "completed",
                                      summary=summary[:200])
            # NOTE: no generic _notify() here — _deliver_result_to_user already
            # sent the user-facing push (deep-linked to the result note) and an
            # attention-inbox item. A second "Agent Task Update" push would just
            # double-notify without opening the note.
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
                    self._update_mission_state(db, mission_id, "failed")
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
            if task.started_at is None:
                task.started_at = local_now()
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
            # Make internal runs inspectable in the task detail drawer, the same
            # way VM dispatch runs already are.
            meta["execution_log"] = result.get("execution_log", [])

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
                self._update_mission_state(db, mission_id, "failed")
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
            task.completed_at = local_now()
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
                    elapsed = (local_now() - start_dt).total_seconds()
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

            await self._deliver_result_to_user(
                db, user_id, task_id, task_description, summary, note_id,
            )
            await self._emit_progress(user_id, task_id, "completed",
                                      summary=summary[:200])
            # NOTE: no generic _notify() here — _deliver_result_to_user already
            # sent the user-facing push (deep-linked to the result note) and an
            # attention-inbox item. A second "Agent Task Update" push would just
            # double-notify without opening the note.
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
                    self._update_mission_state(db, mission_id, "failed")
                    db.commit()
            except Exception as inner_e:
                logger.error(f"[dispatch] Failed to update task status: {inner_e}")
        finally:
            if db:
                db.close()
            self._running_tasks.pop(task_id, None)

    # ── VM LLM tool-use execution ───────────────────────────────────

    async def _run_vm_claude_mode(
        self,
        task_id: str,
        mission_id: str,
        user_id: str,
        task_description: str,
        skill_context: str = "",
        fallback_categories: list = None,
    ):
        """Execute task on VM via LLM tool-use loop.

        The LLM (Qwen via BackgroundLLMClient) gets tool definitions for shell
        execution, file read/write on the sandbox VM (via VMBridge). Falls back
        to InternalToolAgent if the VM is unreachable.
        """
        from app.main_simple import SessionLocal

        logger.info(f"[dispatch] Starting VM LLM tool-use mode for task {task_id}")
        db = None
        try:
            db = SessionLocal()
            task = self._get_task(db, task_id)
            if not task:
                return

            notify_on_complete = (task.task_metadata or {}).get("notify_on_complete", False)

            # Step 0: Connect to VM
            self._update_mission_step(db, mission_id, 0, "running")
            task.status = "running"
            if task.started_at is None:
                task.started_at = local_now()
            self._update_mission_state(db, mission_id, "running")
            db.commit()
            await self._emit_progress(user_id, task_id, "running",
                                      summary="Connecting to agent VM...")

            bridge, host_label, working_dir_override = self._resolve_bridge(db, user_id, task)
            vm_status = await bridge.test_connection()

            if vm_status != VMConnectionStatus.CONNECTED:
                # A task explicitly targeting a managed host can't fall back to
                # internal tools (those can't reach the host) — fail clearly.
                if working_dir_override is not None:
                    msg = f"Couldn't reach {host_label} over SSH ({vm_status.value})."
                    self._update_mission_step(db, mission_id, 0, "failed",
                                              result_data={"error": msg})
                    task.status = "failed"
                    task.error_message = msg
                    self._update_mission_state(db, mission_id, "failed")
                    db.commit()
                    await self._emit_progress(user_id, task_id, "failed", summary=msg)
                    await self._notify_completion(db, user_id, task_id, "failed", msg)
                    return
                # Fall back to internal mode
                logger.warning(f"[dispatch] VM {vm_status.value}, falling back to internal mode for task {task_id}")
                self._update_mission_step(db, mission_id, 0, "done",
                                          result_data={"note": f"VM {vm_status.value}, using internal fallback"})
                db.commit()
                db.close()
                db = None
                await self._emit_progress(user_id, task_id, "running",
                                          summary="VM unreachable — running with internal tools...")
                categories = list(set((fallback_categories or []) + ["shell", "web"]))
                await self._run_internal_mode(
                    task_id, mission_id, user_id, task_description,
                    categories=categories,
                )
                return

            self._update_mission_step(db, mission_id, 0, "done")
            db.commit()

            # Step 1: Execute via LLM tool-use loop on VM
            self._update_mission_step(db, mission_id, 1, "running")
            await self._emit_progress(user_id, task_id, "running",
                                      summary="Running agent on VM...")

            # Build prompt with optional skill context
            prompt = task_description
            if skill_context:
                prompt += "\n\n" + skill_context

            working_dir = working_dir_override or DISPATCH_WORKING_DIR
            system_prompt = (
                f"You are Sara, an AI assistant with shell access to {host_label}.\n"
                f"Working directory: {working_dir}\n\n"
                f"You have tools to run shell commands, read/write files on this machine.\n"
                f"Complete the task below. When finished, call report_complete with a summary.\n"
                f"If a command fails, try to diagnose and fix the issue.\n"
                f"Do not give up without trying at least a few approaches."
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]

            output, success, execution_log = await _dispatch_llm_loop(
                messages, model=None, tools=DISPATCH_TOOLS,
                bridge=bridge, working_dir=working_dir,
                max_rounds=50,
                task_id=task_id,
                user_id=user_id,
            )

            meta = task.task_metadata or {}
            meta["execution_log"] = execution_log

            if not success:
                # success=False also covers benign endings — the max-rounds cap
                # or report_complete(success=False) — where the agent still
                # produced something usable (a written report, or browser
                # screenshots). Pushing a bald "Agent task failed" in that case
                # throws the real work away and reads as a false alarm. So only
                # treat it as a HARD failure (status=failed + notify) when there
                # is nothing to salvage; otherwise fall through and deliver a
                # PARTIAL result, staying quiet on the failure channel.
                salvage = (output or "").strip()
                sentinels = ("(Maximum tool-call rounds reached)",
                             "LLM returned no choices",
                             FAKE_TOOL_CALL_FAILURE)
                is_sentinel = any(salvage.startswith(s) for s in sentinels)
                gallery = self._collect_browse_screenshots(execution_log)
                has_usable_output = (bool(salvage) and not is_sentinel) or bool(gallery)

                if not has_usable_output:
                    self._update_mission_step(db, mission_id, 1, "failed",
                                              error=output[:500])
                    self._update_mission_state(db, mission_id, "failed")
                    task.status = "failed"
                    meta["error"] = output[:5000]
                    task.task_metadata = {**meta}
                    db.commit()
                    used_skill_ids = meta.get("used_skill_ids", [])
                    self._track_skill_usage(db, used_skill_ids, succeeded=False)
                    await self._emit_progress(user_id, task_id, "failed",
                                              summary=output[:200])
                    await self._notify(user_id, task_id, "failed",
                                       f"Agent task failed: {output[:200]}")
                    return

                # Salvageable — record it as partial and let the completion
                # path below create + deliver the result note as usual.
                logger.info(
                    "[dispatch] task %s ended success=False but has usable output "
                    "(%d chars text, screenshots=%s); delivering as partial result",
                    task_id, len(salvage), bool(gallery),
                )
                meta["partial"] = True
                if is_sentinel or not salvage:
                    output = (
                        "⚠️ The agent stopped before formally wrapping up — "
                        "here's what it gathered before stopping."
                    )

            # Completed
            self._update_mission_step(db, mission_id, 1, "done",
                                      result_data={"summary": output[:1000]})

            # Step 2: Report
            self._update_mission_step(db, mission_id, 2, "running")

            summary = output or "Task completed"

            # Writing pass: if the run gathered research material but the
            # loop's final output isn't already a real report, synthesize the
            # deliverable in a dedicated no-tools call over the gathered
            # material. This is what turns "did the research" into "wrote the
            # report" reliably.
            research_calls = sum(
                1 for e in execution_log
                if e.get("type") == "tool_call" and e.get("tool") in _RESEARCH_TOOLS
            )
            if research_calls >= 3 and not _is_report_grade(summary):
                await self._emit_progress(user_id, task_id, "running",
                                          summary="Writing final report...")
                report = await _synthesize_report(
                    task_description, execution_log, summary,
                )
                if report:
                    logger.info(
                        "[dispatch] synthesized final report (%d chars) for task %s "
                        "— loop output was not report-grade (%d chars)",
                        len(report), task_id, len(summary or ""),
                    )
                    meta["synthesized_report"] = True
                    summary = report

            # Deterministically append any browser screenshots captured during
            # the run — the local model is unreliable about embedding them, so
            # we build the gallery from the execution log regardless.
            gallery = self._collect_browse_screenshots(execution_log)
            if gallery and "/browse-shots/" not in summary:
                summary = f"{summary}\n\n{gallery}"

            task.status = "completed"
            task.completed_at = local_now()
            meta["output"] = summary[:5000]
            task.task_metadata = {**meta}

            # Extract file paths from output for artifact pull
            artifacts = self._extract_file_paths(summary, execution_log)

            # Create result note + pull VM artifacts into notes
            note_id = await self._create_result_note(
                db, user_id, task_description, summary,
                artifacts=artifacts,
            )
            if note_id:
                task.result_note_id = note_id

            if artifacts:
                meta["artifacts"] = artifacts
                task.task_metadata = {**meta}

            self._update_mission_step(db, mission_id, 2, "done")
            self._update_mission_state(db, mission_id, "done")
            db.commit()

            # Track skill usage
            used_skill_ids = meta.get("used_skill_ids", [])
            self._track_skill_usage(db, used_skill_ids, succeeded=True)

            # Extract skill recipe (fire-and-forget)
            started_at = meta.get("started_at")
            elapsed = 0.0
            if started_at:
                try:
                    start_dt = datetime.fromisoformat(started_at)
                    elapsed = (local_now() - start_dt).total_seconds()
                except (ValueError, TypeError):
                    elapsed = 60.0

            asyncio.create_task(self._extract_skill_recipe(
                db=SessionLocal(),
                user_id=user_id,
                task_id=task_id,
                task_description=task_description,
                output=summary,
                mode="vm_claude",
                elapsed_seconds=elapsed,
            ))

            await self._deliver_result_to_user(
                db, user_id, task_id, task_description, summary, note_id,
            )
            await self._emit_progress(user_id, task_id, "completed",
                                      summary=summary[:200])
            # NOTE: no generic _notify() here — _deliver_result_to_user already
            # sent the user-facing push (deep-linked to the result note) and an
            # attention-inbox item. A second "Agent Task Update" push would just
            # double-notify without opening the note.
            await self._notify_completion(user_id, task_id, task_description,
                                          summary, notify_on_complete)

        except Exception as e:
            logger.exception(f"[dispatch] VM claude mode failed for task {task_id}: {e}")
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
                    self._update_mission_state(db, mission_id, "failed")
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
                step.started_at = local_now()
            if status in ("done", "failed"):
                step.completed_at = local_now()
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
                mission.completed_at = local_now()
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
        if any(w in text for w in ["run", "script", "code", "command", "compile", "build",
                                    "install", "execute", "shell", "bash", "python", "write a"]):
            cats.append("shell")
        # Default to web + shell if nothing matched (versatile fallback)
        return cats if cats else ["web", "shell"]

    def _looks_like_question(self, text: str) -> bool:
        """Heuristic: does the agent output look like it's asking a question?"""
        if not text:
            return False
        lines = text.strip().split("\n")
        last_lines = " ".join(lines[-3:]).lower()
        question_indicators = ["?", "please provide", "could you", "what should",
                               "which option", "do you want", "shall i"]
        return any(ind in last_lines for ind in question_indicators)

    # File extensions worth pulling from the VM into notes
    _INLINEABLE_EXTENSIONS = {
        ".md", ".txt", ".py", ".csv", ".json", ".yaml", ".yml",
        ".sh", ".html", ".xml", ".toml", ".cfg", ".ini", ".log",
        ".rs", ".go", ".js", ".ts", ".sql", ".r", ".tex",
    }
    _MAX_INLINE_SIZE = 100_000  # 100 KB per file

    async def _pull_vm_artifacts(
        self, artifacts: List[str], folder_id: Optional[str],
        user_id: str, db: Session,
    ) -> List[str]:
        """Pull text artifacts from the VM and save each as a separate note.

        Returns list of note IDs created.
        """
        if not artifacts:
            return []

        from app.models.note import Note

        bridge = VMBridge()
        try:
            status = await bridge.test_connection()
            if status != VMConnectionStatus.CONNECTED:
                logger.warning("VM not reachable for artifact pull")
                return []
        except Exception:
            return []

        # Resolve tilde-prefixed paths and dedupe — _extract_file_paths can
        # legitimately produce both `~/sandbox/foo.md` and the absolute form
        # for the same file (e.g. when the LLM tried both during recovery).
        resolved: list[str] = []
        seen: set[str] = set()
        for raw in artifacts:
            r = _resolve_vm_path(raw, DISPATCH_WORKING_DIR, bridge.config.username)
            if r not in seen:
                seen.add(r)
                resolved.append(r)

        created_ids = []
        for path in resolved:
            try:
                ext = os.path.splitext(path)[1].lower()
                if ext not in self._INLINEABLE_EXTENSIONS:
                    continue

                # Check file size first
                size_result = await bridge.execute_command(
                    f"stat -c%s {shlex.quote(path)} 2>/dev/null || echo 0",
                    timeout=10,
                )
                size_str = (size_result.stdout if hasattr(size_result, 'stdout')
                            else size_result.output if hasattr(size_result, 'output')
                            else str(size_result)).strip()
                try:
                    size = int(size_str)
                except (ValueError, TypeError):
                    size = 0
                if size == 0 or size > self._MAX_INLINE_SIZE:
                    continue

                # Read file content
                result = await bridge.execute_command(
                    f"cat {shlex.quote(path)}", timeout=30,
                )
                content = (result.stdout if hasattr(result, 'stdout')
                           else result.output if hasattr(result, 'output')
                           else str(result))
                if not content or not content.strip():
                    continue

                # Derive title from filename
                basename = os.path.basename(path)
                title = os.path.splitext(basename)[0].replace("-", " ").replace("_", " ").title()

                # Wrap non-markdown in code block
                if ext != ".md":
                    content = f"```{ext.lstrip('.')}\n{content}\n```"

                note_id = str(uuid.uuid4())
                note = Note(
                    id=note_id,
                    user_id=user_id,
                    title=title,
                    content=content,
                    folder_id=folder_id,
                    tags=[SARA_GENERATED_TAG],
                )
                db.add(note)
                created_ids.append(note_id)
                logger.info(f"Pulled VM artifact into note: {basename} → {note_id[:8]}")

            except Exception as e:
                logger.debug(f"Failed to pull artifact {path}: {e}")

        if created_ids:
            try:
                db.commit()
            except Exception as e:
                logger.warning(f"Failed to commit artifact notes: {e}")
                db.rollback()
                return []

        return created_ids

    @staticmethod
    def _collect_browse_screenshots(execution_log: list) -> str:
        """Build a markdown screenshot gallery from `browse` tool results.

        Each browse result embeds `![…](…/browse-shots/<id>.png)`. We pull those
        out (with the page URL as a label) so screenshots always appear in the
        report even when the model forgets to embed them.
        """
        if not execution_log:
            return ""
        img_re = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+/browse-shots/[^)\s]+)\)")
        seen: set[str] = set()
        items: list[str] = []
        for e in execution_log:
            if e.get("type") != "tool_call" or e.get("tool") != "browse":
                continue
            result = e.get("result") or ""
            m = img_re.search(result)
            if not m:
                continue
            shot_url = m.group(1)
            if shot_url in seen:
                continue
            seen.add(shot_url)
            page = (e.get("args") or {}).get("url") or ""
            label = f"**{page}**\n\n" if page else ""
            items.append(f"{label}![screenshot]({shot_url})")
        if not items:
            return ""
        return "## Screenshots\n\n" + "\n\n".join(items)

    @staticmethod
    def _extract_file_paths(summary: str, execution_log: list = None) -> List[str]:
        """Extract VM file paths from agent output and execution log."""
        paths = set()

        # Common VM paths pattern: ~/sandbox/..., /home/sara/...
        path_pattern = re.compile(
            r'(?:~/sandbox/[\w./_-]+|/home/sara/[\w./_-]+)'
        )

        # Scan summary text
        for match in path_pattern.finditer(summary or ""):
            p = match.group(0)
            # Only include files (must have extension)
            if '.' in os.path.basename(p):
                paths.add(p)

        # Scan execution log for write_file calls
        for entry in (execution_log or []):
            if isinstance(entry, dict):
                tool = entry.get("tool", "")
                args = entry.get("args", {})
                if tool == "write_file" and "path" in args:
                    paths.add(args["path"])
                # Also check command outputs mentioning file creation
                output_text = entry.get("output", "")
                for match in path_pattern.finditer(output_text):
                    p = match.group(0)
                    if '.' in os.path.basename(p):
                        paths.add(p)

        return list(paths)

    async def _create_result_note(
        self, db: Session, user_id: str, task_description: str, output: str,
        artifacts: List[str] = None,
    ) -> Optional[str]:
        """Create a note in the Agent Workspace folder with the task result.

        If the output is a real report (starts with a '# Title' line), the
        note takes that title and leads with the content — the task prompt is
        demoted to a footer. Otherwise falls back to the 'Agent Result:'
        wrapper so thin outputs are still clearly labeled as agent output.
        """
        first_line = (output or "").lstrip().split("\n", 1)[0]
        title_match = re.match(r"^#\s+(\S.{3,150})$", first_line)
        if title_match:
            note_title = title_match.group(1).strip()
            # Drop the title line from the body — the note title carries it.
            body = (output or "").lstrip().split("\n", 1)
            body = body[1].lstrip("\n") if len(body) > 1 else ""
            footer = f"\n\n---\n*Agent task:* {task_description[:500]}"
            return await self._create_result_note_raw(
                db, user_id, note_title, body + footer, artifacts,
            )
        return await self._create_result_note_raw(
            db, user_id,
            f"Agent Result: {task_description[:80]}",
            (
                f"# Agent Task Result\n\n"
                f"**Task:** {task_description}\n\n"
                f"---\n\n"
                f"{output}"
            ),
            artifacts,
        )

    async def _create_result_note_raw(
        self, db: Session, user_id: str, note_title: str, note_body: str,
        artifacts: List[str] = None,
    ) -> Optional[str]:
        """Create a note in the Agent Workspace folder with the task result.

        If artifacts (VM file paths) are provided, pulls readable files from
        the VM and saves them as separate linked notes.
        """
        try:
            from app.services.background_task_service import background_task_service

            folder = await background_task_service._ensure_workspace_folder(db, user_id)
            from app.models.note import Note

            folder_id = folder.id if folder else None

            # Pull VM artifacts into notes
            artifact_note_ids = await self._pull_vm_artifacts(
                artifacts or [], folder_id, user_id, db,
            )

            # Build a prominent header that surfaces produced documents above
            # the LLM's summary. The previous layout buried these wikilinks at
            # the very bottom under a small "Research Documents:" subheading,
            # which made the note feel "lackluster" — users skimmed the summary
            # and missed that the full deliverable was sitting in a linked note.
            files_header = ""
            if artifact_note_ids:
                artifact_notes = db.query(Note).filter(
                    Note.id.in_(artifact_note_ids)
                ).all()
                if artifact_notes:
                    if len(artifact_notes) == 1:
                        files_header = (
                            f"📄 **Full document:** [[{artifact_notes[0].title}]]\n\n"
                        )
                    else:
                        links = "\n".join(f"- [[{n.title}]]" for n in artifact_notes)
                        files_header = f"📄 **Files produced:**\n{links}\n\n"

            note_id = str(uuid.uuid4())
            note = Note(
                id=note_id,
                user_id=user_id,
                title=note_title,
                content=f"{files_header}{note_body}",
                folder_id=folder_id,
                tags=[SARA_GENERATED_TAG],
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
        """Emit an AGENT_TASK_PROGRESS event on the event bus AND bump the task's
        liveness timestamp + step journal so the progress-based watchdog (Phase 4)
        can tell a live task from a hung one, and long tasks can report step N/M."""
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
        # Liveness + journal (best-effort, must not break the run).
        try:
            self._record_progress(task_id, status, summary)
        except Exception as e:
            logger.debug(f"[dispatch] progress liveness bump failed: {e}")

    def _record_progress(self, task_id: str, status: str, summary: str = ""):
        """Bump task.updated_at (liveness for the stall watchdog) and append a
        capped step-journal entry to task_metadata."""
        from app.main_simple import SessionLocal
        from app.models.background_task import BackgroundTask
        db = SessionLocal()
        try:
            task = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
            if not task:
                return
            meta = dict(task.task_metadata or {})
            journal = list(meta.get("step_journal", []))
            journal.append({
                "at": local_now().isoformat(), "status": status,
                "summary": (summary or "")[:300],
            })
            meta["step_journal"] = journal[-50:]  # cap
            meta["last_progress_at"] = local_now().isoformat()
            meta["step_count"] = len(journal)
            task.task_metadata = meta
            # background_task timestamps are naive UTC (DB session tz is UTC, so
            # func.now() stores naive UTC). Match that or the stall watchdog mis-fires.
            from app.core.timezone import naive_utc_now
            task.updated_at = naive_utc_now()
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(task, "task_metadata")
            from app.services.world_state.writer import append_world_event
            _normalized = (status or "").lower()
            if _normalized in {"completed", "complete"}:
                _event_kind = "task.completed"
            elif _normalized in {"failed", "stuck"}:
                _event_kind = "task.failed"
            elif _normalized in {"running", "in_progress"}:
                _event_kind = "task.started" if len(journal) <= 1 else "task.progressed"
            else:
                _event_kind = "task.queued"
            append_world_event(
                db, user_id=str(task.user_id), kind=_event_kind, source="agent_dispatch",
                source_ref=f"background_task:{task.id}", aggregate_type="background_task",
                aggregate_id=str(task.id), actor_type="assistant", actor_id="sara",
                correlation_id=str(task.id),
                dedupe_key=f"task-progress:{task.id}:{len(journal)}:{_normalized}",
                payload={
                    "task_id": str(task.id), "status": _normalized,
                    "status_label": (summary or "")[:300],
                    "title": (task.original_query or "")[:500],
                    "original_query": (task.original_query or "")[:1000],
                    "task_type": task.task_type,
                    "step_count": len(journal),
                    "summary": (summary or "")[:500],
                    "error": (summary or "")[:500] if _event_kind == "task.failed" else None,
                },
            )
            db.commit()
        finally:
            db.close()

    async def _deliver_result_to_user(
        self, db, user_id: str, task_id: str,
        task_description: str, summary: str, note_id: Optional[str],
    ):
        """Push task result to both chat delivery and attention inbox."""
        # Use the real note title when we have one — "Agent: <task echo>" in
        # the push tells David nothing the task prompt didn't.
        note_title = f"Agent: {task_description[:80]}"
        if note_id:
            try:
                from app.models.note import Note
                n = db.query(Note).filter(Note.id == note_id).first()
                if n and n.title:
                    note_title = n.title
            except Exception:
                pass

        # 1. Real-time chat injection / push notification
        try:
            from app.services.task_result_delivery import deliver_task_result
            await deliver_task_result(
                user_id=user_id,
                task_id=task_id,
                task_query=task_description,
                result_note_id=note_id,
                result_note_title=note_title,
                result_summary=summary[:2000],
                db=db,
            )
        except Exception as e:
            logger.warning(f"[dispatch] Chat delivery failed for task {task_id}: {e}")

        # 2. Attention inbox item for async discovery
        try:
            from app.services.autonomy.attention_queue import AttentionQueueService
            attention = AttentionQueueService()
            await attention.create_item(
                db=db,
                user_id=user_id,
                title=f"Agent complete: {task_description[:60]}",
                body=summary[:500],
                category="agent_task",
                priority="normal",
                source="agent_dispatch",
                dedupe_key=f"agent_task:{task_id}",
                payload={
                    "task_id": task_id,
                    "note_id": note_id,
                    "actions": [
                        {"type": "chat", "label": "Discuss",
                         "data": {"prefill": f"Tell me about: {task_description[:60]}"}},
                        {"type": "navigate", "label": "View Note",
                         "data": {"screen": "notes", "note_id": note_id}},
                        {"type": "complete", "label": "Dismiss"},
                    ],
                },
            )
        except Exception as e:
            logger.warning(f"[dispatch] Attention item failed for task {task_id}: {e}")

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
                overlay={"kind": "report", "payload": {"latest": True}},
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
            result["execution_log"] = meta.get("execution_log", [])
            result["error"] = meta.get("error")
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
