"""
VM Bridge — SSH bridge to remote sandbox VM for Claude Code agent dispatch.

Provides:
- SSH command execution on remote VM
- Claude Code session management (start + resume)
- File transfer via SCP
"""

import asyncio
import json
import logging
import os
import shlex
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class VMConnectionStatus(str, Enum):
    CONNECTED = "connected"
    UNREACHABLE = "unreachable"
    AUTH_FAILED = "auth_failed"
    ERROR = "error"


@dataclass
class VMConfig:
    host: str = "10.185.1.176"
    username: str = "sara"
    ssh_key_path: str = "~/.ssh/sara_agent"
    connect_timeout: int = 10


@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class AgentSessionResult:
    success: bool
    session_id: Optional[str] = None
    output: str = ""
    raw_json: Optional[dict] = None
    exit_code: int = -1


def get_vm_config_from_settings(preferences: dict) -> VMConfig:
    """Extract VMConfig from UserSettings.preferences JSONB."""
    vm = preferences.get("vm_sandbox", {}) if preferences else {}
    return VMConfig(
        host=vm.get("host", "10.185.1.176"),
        username=vm.get("username", "sara"),
        ssh_key_path=vm.get("ssh_key_path", "~/.ssh/sara_agent"),
    )


class VMBridge:
    """SSH bridge to remote sandbox VM."""

    def __init__(self, config: Optional[VMConfig] = None):
        self.config = config or VMConfig()

    def _ssh_key(self) -> str:
        return os.path.expanduser(self.config.ssh_key_path)

    def _ssh_base_args(self) -> list[str]:
        return [
            "ssh",
            "-i", self._ssh_key(),
            "-o", "StrictHostKeyChecking=no",
            "-o", f"ConnectTimeout={self.config.connect_timeout}",
            "-o", "BatchMode=yes",
            f"{self.config.username}@{self.config.host}",
        ]

    async def test_connection(self) -> VMConnectionStatus:
        """Test SSH connectivity to the VM."""
        try:
            result = await self.execute_command("echo ok", timeout=15)
            if result.timed_out:
                return VMConnectionStatus.UNREACHABLE
            if result.exit_code == 0 and "ok" in result.stdout:
                return VMConnectionStatus.CONNECTED
            if "permission denied" in result.stderr.lower():
                return VMConnectionStatus.AUTH_FAILED
            return VMConnectionStatus.ERROR
        except Exception as e:
            logger.error(f"VM connection test failed: {e}")
            return VMConnectionStatus.ERROR

    async def execute_command(
        self, command: str, timeout: int = 120
    ) -> CommandResult:
        """Execute a command on the remote VM via SSH."""
        args = self._ssh_base_args() + [command]
        logger.info(f"VM exec: {command[:120]}...")

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return CommandResult(
                    exit_code=-1,
                    stdout="",
                    stderr="Command timed out",
                    timed_out=True,
                )

            return CommandResult(
                exit_code=process.returncode or 0,
                stdout=stdout_bytes.decode(errors="replace"),
                stderr=stderr_bytes.decode(errors="replace"),
            )
        except FileNotFoundError:
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr="ssh binary not found",
            )

    async def start_claude_session(
        self,
        task_prompt: str,
        timeout: int = 600,
        working_dir: Optional[str] = None,
    ) -> AgentSessionResult:
        """Start a new Claude Code session on the VM.

        Returns AgentSessionResult with session_id for later resumption.
        """
        escaped_prompt = shlex.quote(task_prompt)

        cd_prefix = f"cd {shlex.quote(working_dir)} && " if working_dir else ""
        remote_cmd = (
            f"{cd_prefix}claude -p --dangerously-skip-permissions "
            f"--output-format json {escaped_prompt}"
        )

        result = await self.execute_command(remote_cmd, timeout=timeout)

        if result.timed_out:
            return AgentSessionResult(
                success=False,
                output="Agent session timed out",
                exit_code=-1,
            )

        return self._parse_claude_output(result)

    async def resume_claude_session(
        self,
        session_id: str,
        instruction: str,
        timeout: int = 600,
        working_dir: Optional[str] = None,
    ) -> AgentSessionResult:
        """Resume an existing Claude Code session with a follow-up instruction."""
        escaped_instruction = shlex.quote(instruction)

        cd_prefix = f"cd {shlex.quote(working_dir)} && " if working_dir else ""
        remote_cmd = (
            f"{cd_prefix}claude -p --dangerously-skip-permissions "
            f"--resume {shlex.quote(session_id)} {escaped_instruction}"
        )

        result = await self.execute_command(remote_cmd, timeout=timeout)

        if result.timed_out:
            return AgentSessionResult(
                success=False,
                session_id=session_id,
                output="Agent session timed out on resume",
                exit_code=-1,
            )

        parsed = self._parse_claude_output(result)
        # Preserve the original session_id on resume
        if not parsed.session_id:
            parsed.session_id = session_id
        return parsed

    def _parse_claude_output(self, result: CommandResult) -> AgentSessionResult:
        """Parse Claude Code JSON output to extract session_id and result."""
        if result.exit_code != 0 and not result.stdout.strip():
            return AgentSessionResult(
                success=False,
                output=result.stderr or "Command failed with no output",
                exit_code=result.exit_code,
            )

        stdout = result.stdout.strip()

        # Claude --output-format json emits a JSON object with:
        # type, subtype, is_error, result, session_id, duration_ms, etc.
        try:
            data = json.loads(stdout)
            session_id = data.get("session_id")
            is_error = data.get("is_error", False)
            output_text = (
                data.get("result", "")
                or data.get("content", "")
                or data.get("message", "")
                or str(data)
            )
            success = not is_error and result.exit_code == 0
            return AgentSessionResult(
                success=success,
                session_id=session_id,
                output=output_text,
                raw_json=data,
                exit_code=result.exit_code,
            )
        except json.JSONDecodeError:
            # Non-JSON output — still might be valid plain text response
            return AgentSessionResult(
                success=result.exit_code == 0,
                output=stdout[:5000],
                exit_code=result.exit_code,
            )

    async def scp_from_vm(self, remote_path: str, local_path: str) -> CommandResult:
        """Copy a file from the VM to local."""
        args = [
            "scp",
            "-i", self._ssh_key(),
            "-o", "StrictHostKeyChecking=no",
            "-o", f"ConnectTimeout={self.config.connect_timeout}",
            f"{self.config.username}@{self.config.host}:{remote_path}",
            local_path,
        ]
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=60
        )
        return CommandResult(
            exit_code=process.returncode or 0,
            stdout=stdout_bytes.decode(errors="replace"),
            stderr=stderr_bytes.decode(errors="replace"),
        )

    async def scp_to_vm(self, local_path: str, remote_path: str) -> CommandResult:
        """Copy a file from local to the VM."""
        args = [
            "scp",
            "-i", self._ssh_key(),
            "-o", "StrictHostKeyChecking=no",
            "-o", f"ConnectTimeout={self.config.connect_timeout}",
            local_path,
            f"{self.config.username}@{self.config.host}:{remote_path}",
        ]
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=60
        )
        return CommandResult(
            exit_code=process.returncode or 0,
            stdout=stdout_bytes.decode(errors="replace"),
            stderr=stderr_bytes.decode(errors="replace"),
        )
