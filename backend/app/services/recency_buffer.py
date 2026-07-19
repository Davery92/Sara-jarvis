"""Recency buffer + repeat detection — Brain Alignment H5.

Two conversation-level guarantees modeled on near-perfect short-term recall:

  1. Recency floor — the last ~2 hours of turns are *always* in context
     (non-evictable), including failed/errored ones, so Sara knows what she
     just tried and can resolve a pronoun ("let's talk about it") against a
     request made minutes ago even across a session boundary.

  2. Repeat detection — before answering, the incoming question is compared
     against the last 24h of David's turns; a near-duplicate gets a context
     note so Sara acknowledges the repeat instead of re-answering verbatim.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

RECENCY_HOURS = 2
RECENCY_MAX_TOKENS = 1200
RECENCY_MAX_TURNS = 16
REPEAT_SIMILARITY_THRESHOLD = 0.92
_CHARS_PER_TOKEN = 4


async def build_recency_floor(db: AsyncSession, user_id: str) -> Optional[str]:
    """Formatted last-2h conversation turns, capped, for a non-evictable
    context section. Includes errored/system turns so failures aren't invisible."""
    rows = (await db.execute(text("""
        SELECT role, content, created_at, source
        FROM episode
        WHERE user_id = :uid
          AND created_at > NOW() - INTERVAL ':hours hours'::interval
          AND role IN ('user', 'assistant', 'system')
        ORDER BY created_at DESC
        LIMIT :limit
    """.replace(":hours", str(int(RECENCY_HOURS)))),
        {"uid": user_id, "limit": RECENCY_MAX_TURNS})).fetchall()
    if not rows:
        return None

    # rows are newest-first; render oldest-first and cap by token budget.
    lines: List[str] = []
    used = 0
    for r in rows:  # newest first — build then reverse
        content = (r.content or "").strip()
        if not content:
            continue
        speaker = "David" if r.role == "user" else ("Sara" if r.role == "assistant" else "System")
        tag = ""
        if r.source and "error" in str(r.source).lower():
            tag = " [errored]"
        snippet = content[:400]
        line = f"{speaker}{tag}: {snippet}"
        used += len(line) // _CHARS_PER_TOKEN
        lines.append(line)
        if used >= RECENCY_MAX_TOKENS:
            break

    lines.reverse()
    return "## Last couple hours (verbatim recency floor)\n" + "\n".join(lines)


async def detect_repeat_question(
    db: AsyncSession,
    user_id: str,
    message: str,
    embedding: Optional[List[float]] = None,
    conversation_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """If `message` closely repeats a question David asked in the last 24h,
    return {minutes_ago, prior_question, prior_answer, similarity}. Else None."""
    if not message or len(message.strip()) < 8:
        return None
    try:
        if embedding is None:
            from app.services.embedding_service import EmbeddingService
            embedding = await EmbeddingService().generate_embedding(message)
        if not embedding:
            return None

        row = (await db.execute(text("""
            SELECT id, conversation_id, content, created_at,
                   1 - (embedding <=> CAST(:qvec AS vector)) AS similarity,
                   EXTRACT(EPOCH FROM (NOW() - created_at)) / 60.0 AS minutes_ago
            FROM episode
            WHERE user_id = :uid
              AND role = 'user'
              AND embedding IS NOT NULL
              AND created_at > NOW() - INTERVAL '24 hours'
              AND created_at < NOW() - INTERVAL '20 seconds'
            ORDER BY embedding <=> CAST(:qvec AS vector) ASC
            LIMIT 1
        """), {"uid": user_id, "qvec": str(embedding)})).fetchone()

        if not row or row.similarity is None or float(row.similarity) < REPEAT_SIMILARITY_THRESHOLD:
            return None

        # Best-effort: Sara's answer is the next assistant turn in that thread.
        answer = (await db.execute(text("""
            SELECT content FROM episode
            WHERE user_id = :uid AND role = 'assistant'
              AND conversation_id = :cid
              AND created_at > :after
            ORDER BY created_at ASC
            LIMIT 1
        """), {"uid": user_id, "cid": row.conversation_id, "after": row.created_at})).fetchone()

        return {
            "minutes_ago": round(float(row.minutes_ago)),
            "prior_question": (row.content or "")[:300],
            "prior_answer": (answer.content[:400] if answer and answer.content else None),
            "similarity": round(float(row.similarity), 3),
        }
    except Exception as e:
        logger.debug(f"repeat-question detection skipped: {e}")
        return None


def repeat_note(repeat: Dict[str, Any]) -> str:
    """Prompt note instructing Sara to acknowledge the repeat and add value."""
    mins = repeat["minutes_ago"]
    when = "just now" if mins < 1 else (f"{mins} min ago" if mins < 90 else f"{round(mins/60)}h ago")
    ans = f" You answered: \"{repeat['prior_answer']}\"." if repeat.get("prior_answer") else ""
    return (
        "## You've been asked this before\n"
        f"David asked essentially the same thing {when} (\"{repeat['prior_question']}\").{ans}\n"
        "Acknowledge you're revisiting it — don't re-answer verbatim. Add something new, "
        "ask what changed, or note if nothing has."
    )
