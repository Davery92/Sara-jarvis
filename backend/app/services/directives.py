"""Directives — behavioral law David authors through conversation (Phase 12B).

Different from the scratchpad (temporal context) and life facts (schedule data):
directives are RULES, always injected into every chat, deliberation, and agent
prompt. Small (tens of tokens each), capped, curated, reviewable/editable.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy import text

from app.core.timezone import now_utc
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = get_owner_id()
_MAX_DIRECTIVES = 40  # curated, capped


async def add_directive(directive_text: str, category: str = "general",
                        user_id: str = DEFAULT_USER_ID) -> dict:
    directive_text = (directive_text or "").strip()
    if not directive_text:
        return {"error": "empty directive"}
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        # De-dupe on near-identical text.
        existing = (await db.execute(text(
            "SELECT id FROM directive WHERE user_id = :uid AND active = true AND lower(text) = lower(:t)"),
            {"uid": user_id, "t": directive_text})).first()
        if existing:
            return {"id": existing[0], "text": directive_text, "duplicate": True}
        count = (await db.execute(text(
            "SELECT count(*) FROM directive WHERE user_id = :uid AND active = true"),
            {"uid": user_id})).scalar() or 0
        if count >= _MAX_DIRECTIVES:
            return {"error": f"directive cap reached ({_MAX_DIRECTIVES}) — remove one first"}
        row = (await db.execute(text("""
            INSERT INTO directive (user_id, text, category, active, created_at)
            VALUES (:uid, :t, :c, true, :now) RETURNING id
        """), {"uid": user_id, "t": directive_text[:1000], "c": category, "now": now_utc()})).first()
        await db.commit()
    return {"id": row[0], "text": directive_text, "category": category}


async def list_directives(user_id: str = DEFAULT_USER_ID) -> List[dict]:
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        rows = (await db.execute(text(
            "SELECT id, text, category, created_at FROM directive WHERE user_id = :uid AND active = true ORDER BY created_at"),
            {"uid": user_id})).mappings().all()
    return [dict(r) for r in rows]


async def remove_directive(directive_id: int, user_id: str = DEFAULT_USER_ID) -> int:
    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        r = await db.execute(text(
            "UPDATE directive SET active = false, updated_at = :now WHERE id = :id AND user_id = :uid"),
            {"id": directive_id, "uid": user_id, "now": now_utc()})
        await db.commit()
        return r.rowcount or 0


async def get_directives_for_context(user_id: str = DEFAULT_USER_ID) -> Optional[str]:
    """The always-injected directive block. None if David hasn't set any."""
    directives = await list_directives(user_id)
    if not directives:
        return None
    lines = ["## Standing directives (David's rules — always follow these):"]
    for d in directives:
        lines.append(f"- {d['text']}")
    return "\n".join(lines)
