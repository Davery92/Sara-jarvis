"""Standing-context scratchpad (Phase 10C).

Free-text context David dictates that Sara keeps pinned in front of her every
time she thinks — the difference between "Sara remembers if the retriever
happens to surface it" and "Sara *knows*". Budget-capped, expires by
active_until (default end of week), and the scratchpad wins over inferred
patterns ("smoothie every morning" silences the pre-gym-meal nudge).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy import text

from app.core.timezone import now_utc

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"
_MAX_CHARS = 900  # ~300 tokens, budget-capped for injection
_CATEGORIES = {"meals", "schedule", "errands", "other"}


def _end_of_week():
    """Sunday 23:59 UTC-ish — a sane default expiry for weekly standing context."""
    from datetime import timedelta
    now = now_utc()
    days_to_sunday = (6 - now.weekday()) % 7
    return (now + timedelta(days=days_to_sunday)).replace(hour=23, minute=59, second=0, microsecond=0)


async def write_scratchpad(content: str, category: str = "other",
                           active_until=None, created_from: str = "chat",
                           user_id: str = DEFAULT_USER_ID) -> dict:
    content = (content or "").strip()
    if not content:
        return {"error": "empty content"}
    if category not in _CATEGORIES:
        category = "other"
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        row = (await db.execute(text("""
            INSERT INTO scratchpad_entry (user_id, content, category, active_until, created_from, created_at, cleared)
            VALUES (:uid, :c, :cat, :until, :src, :now, false)
            RETURNING id
        """), {"uid": user_id, "c": content[:2000], "cat": category,
               "until": active_until or _end_of_week(), "src": created_from, "now": now_utc()})).first()
        await db.commit()
    return {"id": row[0], "content": content, "category": category}


async def read_scratchpad(user_id: str = DEFAULT_USER_ID) -> List[dict]:
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        rows = (await db.execute(text("""
            SELECT id, content, category, active_until, created_at
            FROM scratchpad_entry
            WHERE user_id = :uid AND cleared = false
              AND (active_until IS NULL OR active_until > NOW())
            ORDER BY created_at DESC
        """), {"uid": user_id})).mappings().all()
    return [dict(r) for r in rows]


async def clear_scratchpad(entry_id: Optional[int] = None, user_id: str = DEFAULT_USER_ID) -> int:
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        if entry_id is not None:
            r = await db.execute(text(
                "UPDATE scratchpad_entry SET cleared = true WHERE id = :id AND user_id = :uid"),
                {"id": entry_id, "uid": user_id})
        else:
            r = await db.execute(text(
                "UPDATE scratchpad_entry SET cleared = true WHERE user_id = :uid AND cleared = false"),
                {"uid": user_id})
        await db.commit()
        return r.rowcount or 0


async def get_scratchpad_for_context(user_id: str = DEFAULT_USER_ID) -> Optional[str]:
    """Budget-capped block for chat + deliberation injection. None if empty."""
    entries = await read_scratchpad(user_id)
    if not entries:
        return None
    lines = ["## Standing context (David told me):"]
    used = len(lines[0])
    for e in entries:
        line = f"- {e['content']}"
        if used + len(line) > _MAX_CHARS:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)
