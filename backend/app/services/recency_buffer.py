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
# Harness rebuild Phase 6. At 1200 tokens / 400-char snippets this was the
# single largest section of the 2026-09-11 live block — 3,841 chars, 26% of it
# — and most of what it carried was already in `conversation_history` a few
# hundred tokens further down the same prompt. Its actual job is narrow: know
# what you just tried when the turns are NOT in this conversation's history
# (a session boundary, a crashed client, a turn from the iOS app answered on
# the web). Turns from the live conversation are now excluded outright, and
# what remains is capped at a third of the old width.
RECENCY_MAX_TOKENS = 450
RECENCY_MAX_TURNS = 10
RECENCY_SNIPPET_CHARS = 220
REPEAT_SIMILARITY_THRESHOLD = 0.92
_CHARS_PER_TOKEN = 4


async def build_recency_floor(
    db: AsyncSession, user_id: str, exclude_conversation_id: Optional[str] = None
) -> Optional[str]:
    """Formatted last-2h conversation turns, capped, for a non-evictable
    context section. Includes errored/system turns so failures aren't invisible.

    `exclude_conversation_id` drops turns from the conversation being answered:
    those are already in `conversation_history` in the same prompt, verbatim
    and untruncated, and repeating a clipped copy of them costs tokens and
    invites the model to treat the clipped version as the real one.
    """
    rows = (await db.execute(text("""
        SELECT role, content, created_at, source
        FROM episode
        WHERE user_id = :uid
          AND created_at > NOW() - INTERVAL ':hours hours'::interval
          AND role IN ('user', 'assistant', 'system')
          AND (:cid::text IS NULL OR conversation_id IS DISTINCT FROM :cid)
        ORDER BY created_at DESC
        LIMIT :limit
    """.replace(":hours", str(int(RECENCY_HOURS)))),
        {"uid": user_id, "limit": RECENCY_MAX_TURNS,
         "cid": exclude_conversation_id})).fetchall()
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
        snippet = content[:RECENCY_SNIPPET_CHARS]
        if len(content) > RECENCY_SNIPPET_CHARS:
            snippet += "…"
        line = f"{speaker}{tag}: {snippet}"
        # Check the budget BEFORE appending, or a full-width turn always
        # overshoots it by its own length.
        cost = len(line) // _CHARS_PER_TOKEN
        if lines and used + cost > RECENCY_MAX_TOKENS:
            break
        used += cost
        lines.append(line)

    if not lines:
        return None
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
            # Short. The point of this note is "you've said this already",
            # not a transcript: quoting 400 chars of the prior answer cost
            # 660 chars of the 2026-09-11 prompt and invited a re-run of it.
            "prior_question": (row.content or "")[:140],
            "prior_answer": (answer.content[:180] if answer and answer.content else None),
            "similarity": round(float(row.similarity), 3),
        }
    except Exception as e:
        logger.debug(f"repeat-question detection skipped: {e}")
        return None


def repeat_note(repeat: Dict[str, Any]) -> str:
    """Prompt note instructing Sara to acknowledge the repeat and add value."""
    mins = repeat["minutes_ago"]
    when = "just now" if mins < 1 else (f"{mins} min ago" if mins < 90 else f"{round(mins/60)}h ago")
    # Clip here as well as at the query — this note is a nudge, and any caller
    # handing it a long answer would otherwise re-present the very reply Sara
    # is being told not to repeat.
    q = (repeat.get("prior_question") or "")[:140]
    a = (repeat.get("prior_answer") or "")[:180]
    ans = f" You started: \"{a}…\"." if a else ""
    return (
        "## You've been asked this before\n"
        f"David asked essentially the same thing {when} (\"{q}\").{ans}\n"
        "Acknowledge you're revisiting it — don't re-answer verbatim. Add something new, "
        "ask what changed, or note if nothing has."
    )
