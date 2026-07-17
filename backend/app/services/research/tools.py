"""
Tools available to the research executor agent.

The agent can: search the web, read/write files, run shell commands,
ask Sara for help, and report findings.
"""

import json
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Working directory for research output
RESEARCH_BASE_DIR = os.getenv("RESEARCH_BASE_DIR", "/tmp/sara-research")


def get_work_dir(plan_id: str) -> str:
    """Get or create the working directory for a research plan."""
    work_dir = os.path.join(RESEARCH_BASE_DIR, plan_id)
    os.makedirs(work_dir, exist_ok=True)
    return work_dir


# ─── Tool Definitions (OpenAI function-calling format) ───────────────────────

RESEARCH_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for up-to-date information. Returns search results "
                "with titles, URLs, and snippets. Use this to find current data, "
                "verify facts, or discover sources."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return (default 5, max 10)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Fetch the content of a web page. Returns the text content of the page. "
                "Use this to read articles, documentation, or other web content after "
                "finding URLs via web_search."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch",
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "Max characters to return (default 8000)",
                        "default": 8000,
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write content to a file in the research working directory. "
                "Use this to save findings, notes, code, or any output. "
                "Creates parent directories automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path (e.g., 'findings/topic1.md')",
                    },
                    "content": {
                        "type": "string",
                        "description": "File content to write",
                    },
                    "append": {
                        "type": "boolean",
                        "description": "Append to existing file instead of overwriting",
                        "default": False,
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
            "description": "Read the content of a file in the research working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path to read",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in the research working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path (default: root)",
                        "default": ".",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a shell command in the research working directory. "
                "Useful for data processing, running scripts, or system operations. "
                "Commands are sandboxed to the working directory."
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
                        "description": "Timeout in seconds (default 60, max 300)",
                        "default": 60,
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_sara",
            "description": (
                "Ask Sara (the primary AI) for help when you are stuck, need clarification "
                "on the research objective, or need guidance on how to proceed. "
                "Sara has full context of the research plan and can provide direction. "
                "This will pause execution until Sara responds."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Your question or description of what you need help with",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_findings",
            "description": (
                "Report the findings for the current research step. Call this when you've "
                "completed your research on the current topic. The findings will be stored "
                "and the executor will move to the next step."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Concise summary of what you found",
                    },
                    "details": {
                        "type": "string",
                        "description": "Detailed findings in markdown format",
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of URLs or references used",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence in findings (0.0-1.0)",
                    },
                    "substeps_needed": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                            },
                        },
                        "description": "If the topic needs to be broken into subtopics, list them here",
                    },
                },
                "required": ["summary", "details"],
            },
        },
    },
]


# ─── Blocked command patterns ────────────────────────────────────────────────

BLOCKED_COMMANDS = [
    "rm -rf /",
    "mkfs",
    "dd if=",
    ":(){ :|:& };:",
    "shutdown",
    "reboot",
    "init 0",
    "init 6",
]


# ─── Tool Execution ──────────────────────────────────────────────────────────

async def execute_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    plan_id: str,
) -> str:
    """
    Execute a research tool and return the result as a string.

    The ask_sara and report_findings tools are handled by the executor loop,
    not here — they return a sentinel value.
    """
    work_dir = get_work_dir(plan_id)

    if tool_name == "web_search":
        return await _web_search(arguments)
    elif tool_name == "web_fetch":
        return await _web_fetch(arguments)
    elif tool_name == "write_file":
        return _write_file(work_dir, arguments)
    elif tool_name == "read_file":
        return _read_file(work_dir, arguments)
    elif tool_name == "list_files":
        return _list_files(work_dir, arguments)
    elif tool_name == "run_command":
        return _run_command(work_dir, arguments)
    elif tool_name == "ask_sara":
        return "__ASK_SARA__"  # Sentinel — handled by executor
    elif tool_name == "report_findings":
        return "__REPORT_FINDINGS__"  # Sentinel — handled by executor
    else:
        return f"Unknown tool: {tool_name}"


async def _web_search(args: Dict[str, Any]) -> str:
    """Search the web using the Tavily search service."""
    query = args.get("query", "")
    num_results = min(args.get("num_results", 5), 10)

    if not query:
        return "Error: empty search query"

    try:
        from app.services.search_service import search_service

        result = await search_service.web_search(
            query=query,
            max_results=num_results,
            extract_top_n=min(num_results, 6),
        )

        results = result.get("results", [])
        if not results:
            return f"No results found for: {query}"

        output = []
        for i, r in enumerate(results, 1):
            output.append(
                f"{i}. **{r.get('title', 'No title')}**\n"
                f"   URL: {r.get('url', 'N/A')}\n"
                f"   {r.get('snippet', 'No description')}\n"
            )
        return "\n".join(output)

    except Exception as e:
        logger.error("Web search error: %s", e)
        return f"Search error: {e}"


async def _web_fetch(args: Dict[str, Any]) -> str:
    """Fetch and extract text from a URL."""
    url = args.get("url", "")
    max_length = args.get("max_length", 8000)

    if not url:
        return "Error: empty URL"

    try:
        import httpx
        from html.parser import HTMLParser

        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text_parts = []
                self._skip = False
                self._skip_tags = {"script", "style", "nav", "header", "footer"}

            def handle_starttag(self, tag, attrs):
                if tag in self._skip_tags:
                    self._skip = True

            def handle_endtag(self, tag):
                if tag in self._skip_tags:
                    self._skip = False

            def handle_data(self, data):
                if not self._skip:
                    text = data.strip()
                    if text:
                        self.text_parts.append(text)

        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SaraResearchBot/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")

        if "text/html" in content_type:
            extractor = TextExtractor()
            extractor.feed(resp.text)
            text = "\n".join(extractor.text_parts)
        else:
            text = resp.text

        if len(text) > max_length:
            text = text[:max_length] + "\n\n[... truncated]"

        return text if text.strip() else "Page returned no extractable text content."

    except Exception as e:
        logger.error("Web fetch error for %s: %s", url, e)
        return f"Failed to fetch {url}: {e}"


def _write_file(work_dir: str, args: Dict[str, Any]) -> str:
    """Write a file to the research working directory."""
    rel_path = args.get("path", "")
    content = args.get("content", "")
    append = args.get("append", False)

    if not rel_path:
        return "Error: no file path provided"

    # Prevent path traversal
    full_path = os.path.normpath(os.path.join(work_dir, rel_path))
    if not full_path.startswith(work_dir):
        return "Error: path traversal not allowed"

    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    mode = "a" if append else "w"
    with open(full_path, mode) as f:
        f.write(content)

    action = "Appended to" if append else "Wrote"
    return f"{action} {rel_path} ({len(content)} chars)"


def _read_file(work_dir: str, args: Dict[str, Any]) -> str:
    """Read a file from the research working directory."""
    rel_path = args.get("path", "")
    if not rel_path:
        return "Error: no file path provided"

    full_path = os.path.normpath(os.path.join(work_dir, rel_path))
    if not full_path.startswith(work_dir):
        return "Error: path traversal not allowed"

    if not os.path.exists(full_path):
        return f"File not found: {rel_path}"

    with open(full_path, "r") as f:
        content = f.read()

    if len(content) > 16000:
        content = content[:16000] + "\n\n[... truncated at 16000 chars]"

    return content


def _list_files(work_dir: str, args: Dict[str, Any]) -> str:
    """List files in the research working directory."""
    rel_path = args.get("path", ".")

    full_path = os.path.normpath(os.path.join(work_dir, rel_path))
    if not full_path.startswith(work_dir):
        return "Error: path traversal not allowed"

    if not os.path.exists(full_path):
        return f"Directory not found: {rel_path}"

    entries = []
    for root, dirs, files in os.walk(full_path):
        level = root.replace(work_dir, "").count(os.sep)
        indent = "  " * level
        entries.append(f"{indent}{os.path.basename(root)}/")
        sub_indent = "  " * (level + 1)
        for f in sorted(files):
            size = os.path.getsize(os.path.join(root, f))
            entries.append(f"{sub_indent}{f} ({size} bytes)")

    return "\n".join(entries) if entries else "Empty directory"


def _run_command(work_dir: str, args: Dict[str, Any]) -> str:
    """Run a shell command in the research working directory."""
    command = args.get("command", "")
    timeout = min(args.get("timeout", 60), 300)

    if not command:
        return "Error: no command provided"

    # Safety check
    cmd_lower = command.lower().strip()
    for blocked in BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            return f"Blocked: dangerous command pattern '{blocked}'"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
            env={**os.environ, "HOME": work_dir},
        )

        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"

        if len(output) > 8000:
            output = output[:8000] + "\n[... truncated]"

        return output.strip() or "(no output)"

    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except Exception as e:
        return f"Command error: {e}"
