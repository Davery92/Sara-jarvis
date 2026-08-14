"""Interest Model (SARA_MIND_V2_PLAN §3.2) — "what David cares about right
now", as a literally-readable, versioned, editable document. Read by the
appraisal loop, judge, and compose calls (once those exist) so relevance is
judged against topics David has actually shown interest in, not just a
notification category.

Storage: `interest_model` (current row per user) + `interest_model_version`
(append-only — nightly diff proposals and David's own edits are both
recoverable, never silently overwritten).

Content shape (JSON, rendered to the markdown-ish form in §3.2):
{
  "top_of_mind": [{"rank": 1, "text": "...", "people": ["Jim", ...]}, ...],
  "people": [{"name": "Jim Kowalski", "role": "client", "priority": "high"}, ...],
  "standing_rules": ["No generic check-ins without a concrete payload. Ever.", ...],
  "cooling_off": [{"topic": "ActivityPub", "reason": "permanent veto"}, ...],
}
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = get_owner_id()

_EMPTY_CONTENT: Dict[str, Any] = {
    "top_of_mind": [],
    "people": [],
    "standing_rules": [],
    "cooling_off": [],
}


async def get_interest_model(db, user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    row = (await db.execute(text("""
        SELECT content, version, updated_at FROM interest_model WHERE user_id = :uid
    """), {"uid": user_id})).first()
    if not row:
        return {"content": dict(_EMPTY_CONTENT), "version": 0, "updated_at": None}
    content = {**_EMPTY_CONTENT, **(row.content or {})}
    return {"content": content, "version": row.version, "updated_at": row.updated_at}


async def set_interest_model(
    db,
    user_id: str,
    content: Dict[str, Any],
    changed_by: str,
    change_note: Optional[str] = None,
) -> int:
    """Full replace, versioned. Returns the new version number. Used by the
    seed script, the nightly diff proposal (auto-applied rank shifts /
    queued rule additions), and the settings-page edit API."""
    current = await get_interest_model(db, user_id)
    new_version = current["version"] + 1
    content_json = json.dumps(content)

    await db.execute(text("""
        INSERT INTO interest_model (user_id, content, version, updated_at)
        VALUES (:uid, CAST(:content AS jsonb), :version, NOW())
        ON CONFLICT (user_id) DO UPDATE
        SET content = CAST(:content AS jsonb), version = :version, updated_at = NOW()
    """), {"uid": user_id, "content": content_json, "version": new_version})

    await db.execute(text("""
        INSERT INTO interest_model_version (user_id, version, content, changed_by, change_note)
        VALUES (:uid, :version, CAST(:content AS jsonb), :changed_by, :change_note)
    """), {
        "uid": user_id, "version": new_version, "content": content_json,
        "changed_by": changed_by, "change_note": change_note,
    })
    await db.commit()
    return new_version


def render_interest_model(content: Dict[str, Any], version: int = 0) -> str:
    """Render for prompt injection — the exact document shape from §3.2."""
    lines = [f"# What David cares about right now (v{version})"]

    top = content.get("top_of_mind") or []
    if top:
        lines.append("## Top of mind (ranked)")
        for i, item in enumerate(top, 1):
            text_line = item.get("text", "") if isinstance(item, dict) else str(item)
            lines.append(f"{i}. {text_line}")

    people = content.get("people") or []
    if people:
        lines.append("## People who matter")
        parts = []
        for p in people:
            if isinstance(p, dict):
                bit = p.get("name", "")
                extra = ", ".join(x for x in (p.get("role"), p.get("priority")) if x)
                parts.append(f"{bit} ({extra})" if extra else bit)
            else:
                parts.append(str(p))
        lines.append(", ".join(parts))

    rules = content.get("standing_rules") or []
    if rules:
        lines.append("## Standing rules (learned + explicit)")
        for r in rules:
            lines.append(f"- {r}")

    cooling = content.get("cooling_off") or []
    if cooling:
        lines.append("## Cooling off / vetoed")
        for c in cooling:
            if isinstance(c, dict):
                reason = f" ({c['reason']})" if c.get("reason") else ""
                lines.append(f"- {c.get('topic', '')}{reason}")
            else:
                lines.append(f"- {c}")

    if len(lines) == 1:
        lines.append("(empty — not yet seeded)")
    return "\n".join(lines)


async def get_rendered_interest_model(db, user_id: str = DEFAULT_USER_ID) -> str:
    state = await get_interest_model(db, user_id)
    return render_interest_model(state["content"], state["version"])


# ── Chat verbs (§3.2: "stop pinging me about X" / "I care about Y now") ───
#
# Intercepted the same way ui_intent/web_investigation/chess commands are —
# a cheap regex detector before the LLM call, immediate edit + a one-line
# ack, no round trip through deliberation.

_STOP_PATTERNS = [
    re.compile(r"^(?:stop|quit)\s+(?:pinging|notifying|texting|bugging)\s+me\s+about\s+(.+)$", re.I),
    re.compile(r"^(?:stop|quit)\s+(?:mentioning|bringing up)\s+(.+)$", re.I),
    re.compile(r"^i\s+don'?t\s+care\s+about\s+(.+)\s+anymore$", re.I),
]
_CARE_PATTERNS = [
    re.compile(r"^i\s+care\s+about\s+(.+)\s+now$", re.I),
    re.compile(r"^(?:i'?m|i\s+am)\s+(?:now\s+)?(?:really\s+)?interested\s+in\s+(.+)$", re.I),
]


def detect_chat_verb(message: str) -> Optional[Dict[str, str]]:
    """Returns {'verb': 'stop'|'care', 'topic': str} or None."""
    msg = (message or "").strip().rstrip(".!")
    if not msg:
        return None
    for pat in _STOP_PATTERNS:
        m = pat.match(msg)
        if m:
            return {"verb": "stop", "topic": m.group(1).strip()}
    for pat in _CARE_PATTERNS:
        m = pat.match(msg)
        if m:
            return {"verb": "care", "topic": m.group(1).strip()}
    return None


async def apply_chat_verb(db, user_id: str, message: str) -> Optional[str]:
    """Detect and apply an interest-model chat verb. Returns the ack string
    to show David, or None if the message didn't match a verb (caller
    should fall through to the normal chat/LLM path in that case)."""
    verb = detect_chat_verb(message)
    if not verb:
        return None

    state = await get_interest_model(db, user_id)
    content = state["content"]
    topic = verb["topic"]

    if verb["verb"] == "stop":
        cooling = content.setdefault("cooling_off", [])
        if not any((c.get("topic") if isinstance(c, dict) else c) == topic for c in cooling):
            cooling.insert(0, {"topic": topic, "reason": "David asked me to stop, via chat"})
        await set_interest_model(db, user_id, content, changed_by="david_chat",
                                  change_note=f"stop: {topic}")
        return f"Got it — I'll stop bringing up {topic}."

    # verb == "care"
    top = content.setdefault("top_of_mind", [])
    if not any((t.get("text") if isinstance(t, dict) else t) == topic for t in top):
        top.insert(0, {"text": topic})
    await set_interest_model(db, user_id, content, changed_by="david_chat",
                              change_note=f"care: {topic}")
    return f"Noted — {topic} is on my radar now."
