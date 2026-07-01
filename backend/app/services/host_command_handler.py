"""
Host command handler — parses `/host` commands and natural "check out <server>"
phrasing, and drives the inspection, streaming results back as SSE events.

Wired into /chat/stream in main_simple.py, mirroring the chess / code-mode
interception. The natural-language path only fires when the named target
resolves to a *registered* host, so it never hijacks ordinary chat like
"check out this idea".
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from sqlalchemy.orm import Session

from app.services import host_inspector

logger = logging.getLogger(__name__)

HOST_HELP = (
    "**Host registry** — machines I can SSH into and inspect.\n\n"
    "- `/host list` — show registered machines\n"
    "- `/host add <name> <user>@<hostname>[:port] [description]` — register a machine\n"
    "- `/host check <name>` — connect and report specs (also: \"check out <name>\")\n"
    "- `/host remove <name>` — unregister\n\n"
    "First add my public key (`~/.ssh/sara_agent.pub`) to the target's "
    "`~/.ssh/authorized_keys`."
)

# "check out gpu-box", "check gpu-box", "look at gpu-box", "what's on gpu-box",
# "status of gpu-box", "how's gpu-box". Captures the candidate host token.
_NL_PATTERNS = [
    re.compile(r"\bcheck(?:\s+out)?\s+(?:the\s+|on\s+|server\s+|host\s+|machine\s+)?([a-z0-9][\w.-]*)", re.I),
    re.compile(r"\blook(?:\s+at|\s+into)?\s+(?:the\s+|server\s+|host\s+|machine\s+)?([a-z0-9][\w.-]*)", re.I),
    re.compile(r"\b(?:status|specs?|resources?)\s+(?:of|on|for)\s+(?:the\s+)?([a-z0-9][\w.-]*)", re.I),
    re.compile(r"\bhow'?s\s+(?:the\s+)?([a-z0-9][\w.-]*)\s+(?:doing|looking)", re.I),
]


def parse_host_command(message: str, db: Session, user_id: str) -> Optional[dict]:
    """Return a parsed command dict, or None if this isn't a host command.

    Shapes: {"action": "help"|"list"|"add"|"remove"|"check", ...}
    """
    if not message:
        return None
    text = message.strip()
    low = text.lower()

    if low == "/host" or low.startswith("/host "):
        return _parse_slash(text[len("/host"):].strip())

    # Natural language — only intercept when the candidate resolves to a host.
    for pat in _NL_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        candidate = m.group(1).strip().lower().rstrip(".,!?")
        if host_inspector.get_host(db, user_id, candidate):
            return {"action": "check", "name": candidate}
    return None


def _parse_slash(rest: str) -> dict:
    if not rest:
        return {"action": "list"}
    parts = rest.split()
    sub = parts[0].lower()

    if sub in ("list", "ls"):
        return {"action": "list"}
    if sub in ("help", "?"):
        return {"action": "help"}
    if sub in ("remove", "rm", "delete"):
        return {"action": "remove", "name": (parts[1].lower() if len(parts) > 1 else None)}
    if sub in ("check", "inspect"):
        return {"action": "check", "name": (parts[1].lower() if len(parts) > 1 else None)}
    if sub == "add":
        return _parse_add(parts[1:])
    # `/host <name>` shorthand → check that name
    return {"action": "check", "name": sub}


def _parse_add(args: list[str]) -> dict:
    # <name> <user>@<hostname>[:port] [description...]
    if len(args) < 2:
        return {"action": "error", "message": "Usage: `/host add <name> <user>@<hostname>[:port] [description]`"}
    name = args[0].lower()
    target = args[1]
    description = " ".join(args[2:]) or None

    username = "sara"
    if "@" in target:
        username, target = target.split("@", 1)
    port = 22
    if ":" in target:
        target, port_s = target.rsplit(":", 1)
        try:
            port = int(port_s)
        except ValueError:
            return {"action": "error", "message": f"Invalid port: {port_s}"}
    return {
        "action": "add", "name": name, "hostname": target,
        "username": username, "port": port, "description": description,
    }


# ---------------------------------------------------------------------------
# Streaming execution
# ---------------------------------------------------------------------------

async def run_host_command(db: Session, user_id: str, cmd: dict) -> AsyncIterator[dict]:
    """Yield SSE event dicts (text_chunk… → final_response → done)."""
    full = {"text": ""}

    def chunk(delta: str) -> dict:
        full["text"] += delta
        return {"type": "text_chunk", "data": {"content": delta, "full_content": full["text"]}}

    action = cmd.get("action")

    if action == "help":
        yield chunk(HOST_HELP)
    elif action == "error":
        yield chunk("⚠️ " + cmd.get("message", "Bad command"))
    elif action == "list":
        yield chunk(_render_list(db, user_id))
    elif action == "add":
        host = host_inspector.add_host(
            db, user_id, name=cmd["name"], hostname=cmd["hostname"],
            username=cmd["username"], port=cmd["port"], description=cmd.get("description"),
        )
        yield chunk(
            f"✅ Registered **{host.name}** → `{host.username}@{host.hostname}:{host.port}`. "
            f"Say \"check out {host.name}\" and I'll connect and report back."
        )
    elif action == "remove":
        name = cmd.get("name")
        ok = host_inspector.remove_host(db, user_id, name) if name else False
        yield chunk(f"🗑️ Removed **{name}**." if ok else f"No host named **{name}**.")
    elif action == "check":
        async for ev in _run_check(db, user_id, cmd.get("name"), chunk):
            yield ev
    else:
        yield chunk("Unknown host command. Try `/host help`.")

    text = full["text"]
    yield {
        "type": "final_response",
        "data": {
            "content": text,
            "citations": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
    yield {"type": "done"}


async def _run_check(db, user_id, name, chunk) -> AsyncIterator[dict]:
    if not name:
        yield chunk("Which host? Try `/host list`.")
        return
    host = host_inspector.get_host(db, user_id, name)
    if not host:
        yield chunk(
            f"I don't have a host named **{name}** registered. "
            f"Add it with `/host add {name} <user>@<hostname>`."
        )
        return

    yield chunk(f"🔍 Connecting to **{host.name}** (`{host.username}@{host.hostname}`)…\n\n")
    try:
        spec = await host_inspector.inspect_host(db, host)
    except Exception as e:
        logger.error(f"[host] inspect failed for {host.name}: {e}", exc_info=True)
        yield chunk(f"❌ Inspection of **{host.name}** errored: {e}")
        return
    yield chunk(host_inspector.render_report(host, spec))


def _render_list(db: Session, user_id: str) -> str:
    hosts = host_inspector.list_hosts(db, user_id)
    if not hosts:
        return (
            "No machines registered yet. Add one with "
            "`/host add <name> <user>@<hostname>` — then I can check it out for you."
        )
    lines = ["**Registered machines:**"]
    for h in hosts:
        status = f" · _{h.last_status}_" if h.last_status else ""
        desc = f" — {h.description}" if h.description else ""
        lines.append(f"- **{h.name}** `{h.username}@{h.hostname}:{h.port}`{status}{desc}")
    lines.append("\n_Say \"check out <name>\" to inspect one._")
    return "\n".join(lines)
