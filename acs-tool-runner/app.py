"""ACS tool runner — sandbox sidecar for Sara's user-defined tools.

Backend (`acs_user_tools.invoke`) POSTs here with `{invocation_id, code, args}`.
We spawn a Python subprocess per call, pipe the harness on stdin, enforce
resource limits inside the child, wait with a wall-clock timeout, return
`{result?, error?, duration_ms}`.

Threat model: the daemon is trusted to author code with reasonable intent.
The risk is buggy or runaway tools, not adversarial escape attempts. So we
get away with subprocess + setrlimit + wall-clock timeout instead of full
container isolation. If the threat model changes, swap `_spawn` for an
ephemeral docker exec without touching the API.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("acs_tool_runner")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="ACS Tool Runner")

DAEMON_TOKEN = os.environ.get("ACS_DAEMON_TOKEN", "")
WALL_CLOCK_TIMEOUT_SEC = float(os.environ.get("ACS_TOOL_TIMEOUT_SEC", "30"))
MEMORY_LIMIT_BYTES = int(os.environ.get("ACS_TOOL_MEMORY_BYTES", str(256 * 1024 * 1024)))
CPU_LIMIT_SEC = int(os.environ.get("ACS_TOOL_CPU_SEC", "30"))
NOFILE_LIMIT = int(os.environ.get("ACS_TOOL_NOFILE", "256"))
MAX_RESULT_BYTES = int(os.environ.get("ACS_TOOL_MAX_RESULT_BYTES", str(1 * 1024 * 1024)))


# Harness runs inside the child. It reads {code, args} from stdin, sets
# rlimits, exec's the code in a fresh namespace, calls run(args), prints a
# single-line JSON response on stdout. All limits must be enforced *inside*
# the child because asyncio.create_subprocess_exec doesn't take preexec_fn.
HARNESS = r"""
import json, sys, resource, traceback

raw = sys.stdin.read()
payload = json.loads(raw)
code = payload["code"]
args = payload.get("args") or {}

mem = int(payload["_mem"])
cpu = int(payload["_cpu"])
nofile = int(payload["_nofile"])

try:
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    resource.setrlimit(resource.RLIMIT_DATA, (mem, mem))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
    resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
except (ValueError, OSError):
    # Hard limit may be lower than what we want; best-effort.
    pass

ns = {"__name__": "__sara_tool__", "__file__": "<sara_tool>"}
out = {}
try:
    exec(compile(code, "<sara_tool>", "exec"), ns)
    fn = ns.get("run")
    if not callable(fn):
        out = {"error": "tool defined no callable run()"}
    else:
        result = fn(args)
        try:
            json.dumps(result, default=str)
        except (TypeError, ValueError) as je:
            out = {"error": f"result not JSON-serializable: {je}"}
        else:
            out = {"result": result}
except MemoryError:
    out = {"error": "MemoryError: tool exceeded memory limit"}
except Exception as e:
    tb = traceback.format_exc()
    out = {
        "error": f"{type(e).__name__}: {e}",
        "traceback": tb[-1500:],
    }

sys.stdout.write(json.dumps(out, default=str))
sys.stdout.flush()
"""


class RunIn(BaseModel):
    invocation_id: str = Field(..., min_length=1, max_length=64)
    code: str = Field(..., min_length=1, max_length=64 * 1024)
    args: dict[str, Any] = Field(default_factory=dict)


class RunOut(BaseModel):
    result: Any = None
    error: str | None = None
    traceback: str | None = None
    duration_ms: int


def _verify_token(x_daemon_token: str | None) -> None:
    if not DAEMON_TOKEN:
        raise HTTPException(status_code=503, detail="ACS_DAEMON_TOKEN not set on runner")
    if not x_daemon_token or x_daemon_token != DAEMON_TOKEN:
        raise HTTPException(status_code=401, detail="invalid daemon token")


async def _spawn(code: str, args: dict[str, Any], scratch_dir: str) -> tuple[bytes, bytes, int]:
    proc = await asyncio.create_subprocess_exec(
        "python3", "-u", "-I", "-c", HARNESS,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=scratch_dir,
        env={
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "HOME": scratch_dir,
            "TMPDIR": scratch_dir,
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    stdin_payload = json.dumps({
        "code": code,
        "args": args,
        "_mem": MEMORY_LIMIT_BYTES,
        "_cpu": CPU_LIMIT_SEC,
        "_nofile": NOFILE_LIMIT,
    }).encode("utf-8")
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(stdin_payload),
            timeout=WALL_CLOCK_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
        raise
    return stdout, stderr, proc.returncode if proc.returncode is not None else -1


@app.post("/run", response_model=RunOut)
async def run_tool(payload: RunIn, x_daemon_token: str | None = Header(None)) -> RunOut:
    _verify_token(x_daemon_token)
    scratch_dir = tempfile.mkdtemp(prefix=f"sara_tool_{payload.invocation_id[:8]}_")
    try:
        os.chmod(scratch_dir, 0o700)
        t0 = time.monotonic()
        try:
            stdout, stderr, rc = await _spawn(payload.code, payload.args, scratch_dir)
        except asyncio.TimeoutError:
            duration_ms = int((time.monotonic() - t0) * 1000)
            return RunOut(
                error=f"tool exceeded {WALL_CLOCK_TIMEOUT_SEC:.0f}s wall-clock timeout",
                duration_ms=duration_ms,
            )
        duration_ms = int((time.monotonic() - t0) * 1000)

        if rc != 0:
            err_text = stderr.decode("utf-8", errors="replace")[:1000]
            # rc -9 / -15 = killed by SIGKILL/SIGTERM (likely OOM or timeout).
            # rc -24 = SIGXCPU (CPU limit hit).
            hint = ""
            if rc in (-9, -15):
                hint = " (process killed — likely memory or kill timeout)"
            elif rc == -24:
                hint = " (CPU time limit exceeded)"
            return RunOut(
                error=f"runner subprocess exited rc={rc}{hint}: {err_text}",
                duration_ms=duration_ms,
            )

        if len(stdout) > MAX_RESULT_BYTES:
            return RunOut(
                error=f"result exceeded max size {MAX_RESULT_BYTES} bytes",
                duration_ms=duration_ms,
            )

        try:
            body = json.loads(stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            return RunOut(
                error=f"runner output not valid JSON: {e}",
                duration_ms=duration_ms,
            )
        return RunOut(
            result=body.get("result"),
            error=body.get("error"),
            traceback=body.get("traceback"),
            duration_ms=duration_ms,
        )
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "limits": {
            "wall_clock_sec": WALL_CLOCK_TIMEOUT_SEC,
            "memory_bytes": MEMORY_LIMIT_BYTES,
            "cpu_sec": CPU_LIMIT_SEC,
            "nofile": NOFILE_LIMIT,
        },
    }
