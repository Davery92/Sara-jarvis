"""Per-turn chat trace — harness rebuild Phase 9.

On 2026-09-11 David asked Sara to download some attachments and then waited.
One of those turns ran for 500 seconds. There was no way for him to see that
she had spent it calling fifteen tools, and reconstructing what happened took a
20-minute docker log window read line by line.

`chat_turn_trace` is that reconstruction, written by the turn itself. The field
to read first is `ended_by`: anything other than `model` means the harness —
a deadline, a round cap, a disconnect, an error — decided when Sara stopped
talking, rather than Sara deciding she was finished.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/debug/chat-turns")
async def chat_turns(
    conversation_id: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    ended_by: Optional[str] = Query(
        default=None,
        description=(
            "Filter to one outcome: model | deadline | rounds | tool_budget | "
            "cancelled | error"
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Recent chat turns, newest first, for the signed-in user."""
    clauses = ["(user_id = :uid OR user_id IS NULL)"]
    params = {"uid": str(current_user.id), "limit": limit}
    if conversation_id:
        clauses.append("conversation_id = :cid")
        params["cid"] = conversation_id
    if ended_by:
        clauses.append("ended_by = :ended")
        params["ended"] = ended_by

    rows = db.execute(text(f"""
        SELECT id, conversation_id, client_message_id, started_at,
               first_token_ms, total_ms, prompt_tokens_first, tool_count,
               rounds, tools_called, ended_by, context_chars, reply_chars
        FROM chat_turn_trace
        WHERE {' AND '.join(clauses)}
        ORDER BY started_at DESC
        LIMIT :limit
    """), params).fetchall()

    return [
        {
            "id": r.id,
            "conversation_id": r.conversation_id,
            "client_message_id": r.client_message_id,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "first_token_s": round(r.first_token_ms / 1000, 2) if r.first_token_ms else None,
            "total_s": round(r.total_ms / 1000, 2) if r.total_ms else None,
            "prompt_tokens_first": r.prompt_tokens_first,
            "tool_count": r.tool_count,
            "rounds": r.rounds,
            "tools_called": r.tools_called or [],
            "ended_by": r.ended_by,
            "context_chars": r.context_chars,
            "reply_chars": r.reply_chars,
        }
        for r in rows
    ]
