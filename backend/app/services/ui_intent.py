"""UI intent — "bring up my morning brief" → overlay command on the webapp.

Jarvis-style chat-driven UI: short imperative phrases asking Sara to *show*
something are intercepted before the LLM and answered with a `ui_command`
SSE event the frontend turns into an overlay, plus a one-line ack.

Deliberately conservative: the message must start with a display verb
("bring up", "pull up", "show me", "open", "display") and the remainder must
name a known surface. "Show me how to write a regex" does not match because
"how to write a regex" is not a surface.
"""

import logging
import re
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# "hey sara, can you bring up ..." → capture what comes after the verb
_VERB_RE = re.compile(
    r"^(?:hey\s+sara[,!]?\s+|sara[,!]?\s+)?"
    r"(?:can\s+you\s+|could\s+you\s+|please\s+)?"
    r"(?:bring\s+up|pull\s+up|open(?:\s+up)?|show(?:\s+me)?|display)\s+"
    r"(?:my\s+|the\s+|today'?s\s+)?"
    r"(?P<target>.+?)[\s.!?]*$",
    re.IGNORECASE,
)

# Surface name → overlay kind
_SURFACES = {
    "brief": ("morning brief", "daily brief", "brief", "briefing", "morning briefing"),
    "nutrition": ("nutrition", "daily nutrition", "macros", "food log", "food diary", "calories"),
    "calendar": ("calendar", "schedule", "agenda", "day", "events"),
    "tasks": ("tasks", "task list", "background tasks", "agent tasks", "missions"),
}

# Screen name → app screen (iOS navigation targets; only recognized when the
# client can navigate, i.e. allow_screens=True). Emitted as a `navigate`
# action, which the webapp overlay host ignores by design.
_SCREENS = {
    "inbox": ("inbox", "my inbox", "attention inbox", "assistant inbox"),
    "notifications": ("notifications", "notification", "alerts", "notification history"),
    "email": ("email", "emails", "mail", "mailbox"),
    "documents": ("documents", "docs", "files", "my documents"),
    "recipes": ("recipes", "recipe book", "cookbook", "my recipes"),
    "settings": ("settings", "preferences", "options"),
    "health": ("health", "health data", "health metrics", "health dashboard"),
    "learning": ("learning", "learning topics", "study", "studies"),
    "projects": ("projects", "my projects", "project tracker"),
    "automations": ("automations", "standing orders", "schedules"),
    "knowledge": ("knowledge graph", "knowledge", "graph", "connections"),
    "fitness": ("fitness", "workouts", "workout log", "gym", "training"),
    "notes": ("notes", "my notes", "knowledge garden", "note list"),
    "chat": ("chat", "the chat", "full chat", "conversation"),
}

# Notes go by many names — agent results land as "...report", briefs as
# "...brief". "Open the PolicyMount report" should resolve exactly like
# "open my note about PolicyMount" instead of falling through to the LLM.
_NOTE_NOUN = r"(?P<noun>note|report|brief|summary|write-?up)s?"
_NOTE_RE = re.compile(
    rf"^(?:a\s+)?{_NOTE_NOUN}(?:\s+(?:about|on|called|named|titled|for)\s+(?P<query>.+))?$",
    re.IGNORECASE,
)
# "bring up my server inventory note" / "open the policymount report"
_TRAILING_NOTE_RE = re.compile(rf"^(?P<query>.+?)\s+{_NOTE_NOUN}$", re.IGNORECASE)

MAX_WORDS = 12


def parse_ui_intent(message: str, allow_screens: bool = False) -> Optional[Dict[str, Any]]:
    """Return {'overlay': kind, 'query': str|None}, {'screen': name}, or None.

    allow_screens=True (iOS) also recognizes app-screen targets ("open my
    inbox") and returns {'screen': name} for them.
    """
    msg = (message or "").strip()
    if not msg or len(msg.split()) > MAX_WORDS:
        return None

    m = _VERB_RE.match(msg)
    if not m:
        return None
    target = m.group("target").strip().lower()

    for kind, names in _SURFACES.items():
        if target in names:
            return {"overlay": kind, "query": None}

    if allow_screens:
        for screen, names in _SCREENS.items():
            if target in names:
                return {"screen": screen}

    nm = _NOTE_RE.match(target)
    if nm:
        query = (nm.group("query") or "").strip() or None
        noun = (nm.group("noun") or "note").lower()
        if not query and noun != "note":
            # "open the report" → most recent note titled like a report
            query = noun
        return {"overlay": "note", "query": query}
    tm = _TRAILING_NOTE_RE.match(target)
    if tm:
        return {"overlay": "note", "query": tm.group("query").strip()}

    return None


_SCREEN_ACKS = {
    "inbox": "Opening your inbox.",
    "notifications": "Here are your notifications.",
    "email": "Opening your email.",
    "documents": "Opening your documents.",
    "recipes": "Opening your recipes.",
    "settings": "Opening settings.",
    "health": "Opening your health dashboard.",
    "learning": "Opening your learning topics.",
    "projects": "Opening your projects.",
    "automations": "Opening your automations.",
    "knowledge": "Opening the knowledge graph.",
    "fitness": "Opening fitness.",
    "notes": "Opening your notes.",
    "chat": "Opening chat.",
}


def resolve_ui_intent(db: Session, user_id: str, intent: Dict[str, Any]) -> Dict[str, Any]:
    """Build the ui_command payload + spoken ack for a parsed intent."""
    if "screen" in intent:
        screen = intent["screen"]
        return {
            "command": {"action": "navigate", "screen": screen, "payload": {}},
            "ack": _SCREEN_ACKS.get(screen, "Here you go."),
        }

    kind = intent["overlay"]

    if kind == "note":
        query = intent.get("query")
        if not query:
            return {
                "command": None,
                "ack": "Which note? Try \"bring up my note about <topic>\".",
            }
        # Match every word independently ("server build" finds "Build notes:
        # home server") — title first, then content.
        words = [w for w in re.split(r"\s+", query) if w][:6]
        params: Dict[str, Any] = {"uid": user_id}
        clauses = []
        for i, w in enumerate(words):
            params[f"w{i}"] = f"%{w}%"
            clauses.append(f"title ILIKE :w{i}")
        title_where = " AND ".join(clauses) or "TRUE"
        rows = db.execute(
            text(f"""
                SELECT id, title FROM note
                WHERE user_id = :uid AND {title_where}
                ORDER BY updated_at DESC NULLS LAST
                LIMIT 5
            """),
            params,
        ).fetchall()
        if not rows:
            content_where = title_where.replace("title ILIKE", "content ILIKE")
            rows = db.execute(
                text(f"""
                    SELECT id, title FROM note
                    WHERE user_id = :uid AND {content_where}
                    ORDER BY updated_at DESC NULLS LAST
                    LIMIT 5
                """),
                params,
            ).fetchall()
        if not rows:
            return {
                "command": None,
                "ack": f"I couldn't find a note matching \"{query}\".",
            }
        best = rows[0]
        alternates = [{"id": str(r.id), "title": r.title} for r in rows[1:]]
        return {
            "command": {
                "action": "open_overlay",
                "overlay": "note",
                "payload": {"note_id": str(best.id), "title": best.title, "alternates": alternates},
            },
            "ack": f"Bringing up **{best.title}**.",
        }

    acks = {
        "brief": "Here's your morning brief.",
        "nutrition": "Here's today's nutrition.",
        "calendar": "Here's your schedule.",
        "tasks": "Here's what I'm working on.",
    }
    return {
        "command": {"action": "open_overlay", "overlay": kind, "payload": {}},
        "ack": acks.get(kind, "Here you go."),
    }
