"""
Shell tools — run commands, read files, write files on the local server.

Used by InternalToolAgent so Sara can execute code, manipulate files,
and run system commands without needing a remote VM.
"""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Base directory for agent working directories
AGENT_WORKDIR_BASE = Path("/tmp/sara-agent")

# Commands that are always blocked (catastrophic or fork-bomb patterns)
BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/\s*$",        # rm -rf /
    r"rm\s+-rf\s+/\s+",         # rm -rf / <anything>
    r"rm\s+-rf\s+/\*",          # rm -rf /*
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;",  # fork bomb
    r"mkfs\.",                    # format filesystem
    r"dd\s+.*of=/dev/sd",       # overwrite disk
    r">\s*/dev/sd",              # redirect to disk device
    r"chmod\s+-R\s+777\s+/\s*$",  # chmod 777 /
    r"shutdown",                  # shutdown
    r"reboot",                    # reboot
    r"init\s+[06]",              # init 0/6
    r":(){ :\|:& };:",          # fork bomb literal
]


def _is_blocked_command(command: str) -> bool:
    """Check if a command matches any blocked pattern."""
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command):
            return True
    return False


def _get_working_dir(task_id: str) -> Path:
    """Get or create the working directory for an agent task."""
    work_dir = AGENT_WORKDIR_BASE / task_id
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


class RunCommandTool(BaseTool):
    """Execute a bash command in the agent's working directory."""

    @property
    def name(self) -> str:
        return "run_command"

    @property
    def description(self) -> str:
        return (
            "Execute a bash command on the server. Commands run in a sandboxed "
            "working directory. Use for running scripts, installing packages, "
            "compiling code, system administration, etc. 60 second timeout."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional override for working directory (absolute path)",
                },
            },
            "required": ["command"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        command = kwargs.get("command", "")
        task_id = kwargs.get("_task_id", "default")
        working_dir = kwargs.get("working_dir")

        if not command.strip():
            return ToolResult(success=False, message="No command provided")

        if _is_blocked_command(command):
            return ToolResult(
                success=False,
                message=f"Command blocked for safety: {command[:100]}",
            )

        # Determine working directory
        if working_dir:
            cwd = Path(working_dir)
            cwd.mkdir(parents=True, exist_ok=True)
        else:
            cwd = _get_working_dir(task_id)

        logger.info(f"[shell] Running command in {cwd}: {command[:200]}")

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                env={**os.environ, "HOME": str(cwd)},
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=60.0
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return ToolResult(
                    success=False,
                    message="Command timed out after 60 seconds",
                    data={"exit_code": -1, "stdout": "", "stderr": "Timeout"},
                )

            stdout_str = stdout.decode("utf-8", errors="replace")[:50000]
            stderr_str = stderr.decode("utf-8", errors="replace")[:10000]
            exit_code = proc.returncode

            return ToolResult(
                success=exit_code == 0,
                message=f"Command exited with code {exit_code}",
                data={
                    "exit_code": exit_code,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                },
            )

        except Exception as e:
            logger.error(f"[shell] Command execution failed: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to execute command: {e}",
            )


class ReadFileTool(BaseTool):
    """Read the contents of a file."""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read the contents of a file at any path on the server. "
            "Returns the file contents as text. Use for inspecting config files, "
            "logs, source code, etc."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file to read",
                },
            },
            "required": ["path"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        file_path = kwargs.get("path", "")
        task_id = kwargs.get("_task_id", "default")

        if not file_path:
            return ToolResult(success=False, message="No file path provided")

        # Resolve relative paths against the task working directory
        path = Path(file_path)
        if not path.is_absolute():
            path = _get_working_dir(task_id) / path

        if not path.exists():
            return ToolResult(
                success=False,
                message=f"File not found: {path}",
            )

        if not path.is_file():
            return ToolResult(
                success=False,
                message=f"Path is not a file: {path}",
            )

        try:
            stat = path.stat()
            if stat.st_size > 1_000_000:  # 1MB limit
                return ToolResult(
                    success=False,
                    message=f"File too large ({stat.st_size} bytes). Use run_command with head/tail instead.",
                )

            content = path.read_text(errors="replace")
            return ToolResult(
                success=True,
                message=f"Read {len(content)} characters from {path}",
                data={"content": content, "path": str(path), "size": stat.st_size},
            )

        except PermissionError:
            return ToolResult(
                success=False,
                message=f"Permission denied reading {path}",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to read file: {e}",
            )


class WriteFileTool(BaseTool):
    """Write content to a file in the agent's working directory."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file. By default writes to the agent working "
            "directory. Creates parent directories if needed. Use for creating "
            "scripts, config files, output files, etc."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path (relative to working dir, or absolute)",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
                "append": {
                    "type": "boolean",
                    "description": "If true, append to file instead of overwriting",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        file_path = kwargs.get("path", "")
        content = kwargs.get("content", "")
        append = kwargs.get("append", False)
        task_id = kwargs.get("_task_id", "default")

        if not file_path:
            return ToolResult(success=False, message="No file path provided")

        # Resolve relative paths against the task working directory
        path = Path(file_path)
        if not path.is_absolute():
            path = _get_working_dir(task_id) / path

        try:
            # Create parent directories
            path.parent.mkdir(parents=True, exist_ok=True)

            mode = "a" if append else "w"
            with open(path, mode) as f:
                f.write(content)

            action = "Appended to" if append else "Wrote"
            return ToolResult(
                success=True,
                message=f"{action} {len(content)} characters to {path}",
                data={"path": str(path), "size": len(content)},
            )

        except PermissionError:
            return ToolResult(
                success=False,
                message=f"Permission denied writing to {path}",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to write file: {e}",
            )


SHELL_TOOLS = [RunCommandTool(), ReadFileTool(), WriteFileTool()]
