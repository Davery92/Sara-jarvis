"""Pending-proposal service for the chat mutation gate (Sara repair plan
R01, review remediation rounds 2026-09-25 and 2026-09-26). See
app/models/chat_pending_proposal.py for the full rationale.

Two operations only:
  propose(...)  — record that a mutating call was refused for lack of
                  action evidence AND that Sara's own reply for that turn
                  actually told the user about it, so a later EXPLICIT
                  confirmation can re-authorize exactly that call (not
                  "any mutating tool").
  consume(...)  — atomically claim the one pending, unexpired proposal for
                  (user, conversation, tool_name), or return None. A
                  consumed or expired proposal can never be claimed twice.

Round 2 correction (2026-09-26 review): the first version called
propose() synchronously from inside execute_tool(), at the moment a
mutating call was refused — BEFORE the model's own final reply text for
that turn even existed. That means a proposal could be recorded, and later
CONFIRMED, even if Sara's actual reply to the user never mentioned the
action at all (a swallowed exception, an unrelated reply, a truncated
generation) — "the user actually saw it" was never verified, only "the
tool call was attempted." `propose()` now REQUIRES `presented_summary` —
the model's own real, final response text for that turn — as a mandatory
argument. Its only caller is main_simple.py's `_store_conversation_with_
timeout`, the single choke point EVERY turn-exit path funnels through
before a reply is shown/stored (see that method's own docstring: "every
caller must use the finalized content it gets back"), called AFTER
`_finalize_response_content` — so `presented_summary` is always the exact
text that was actually shown. `execute_tool` no longer writes to this
table directly; it only stashes a proposal candidate in
`self._turn_unpresented_proposals` (pure in-memory), and a candidate with
no accompanying substantive final reply is never persisted at all — there
is no DB row to confirm against.

Deliberately synchronous (matches the sync `Session` used throughout
app/tools/*.py and the mutation-gate call site in main_simple.py) and
best-effort: a DB error here degrades to "no proposal recorded" /
"nothing to consume," never to a hard failure of the chat turn itself —
the pre-existing action-intent/continuation checks remain the primary
authorization path regardless of whether this table is reachable.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 900  # 15 minutes — long enough for a real back-and-forth, short enough that a stale proposal can't resurface days later.

# A reply this short cannot plausibly have told the user anything specific
# about a proposed action — same threshold main_simple.py's own
# `_guard_against_tool_echo` already uses for "too short to be a real
# answer." Below this, no proposal is recorded at all.
MIN_PRESENTED_SUMMARY_CHARS = 20


def propose(
    db: Session, *, user_id: str, conversation_id: str, tool_name: str,
    arguments_json: str, presented_summary: str, source_message: str = "",
    summary: str = "", ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> bool:
    """Record that `tool_name(arguments_json)` was attempted but refused
    for lack of action evidence, AND that Sara's own final reply for this
    turn (`presented_summary`) is what the user actually saw. Supersedes
    any existing pending proposal for the same (user, conversation) —
    exactly one live proposal per conversation at a time, so a bare "yes"
    later has no ambiguity about which proposal it's confirming.

    Returns False (and writes nothing) if `presented_summary` is too short
    to plausibly have told the user anything — there is then no evidence
    the user was ever informed, so nothing should be confirmable later.

    `source_message` is the human's own turn message that prompted the
    refusal — stored so a later consume() can still check recurring-scope
    evidence (or any other message-derived authorization condition)
    against the message that could actually carry it; the confirming
    "yes" never will. See consume()'s docstring.
    """
    if not presented_summary or len(presented_summary.strip()) < MIN_PRESENTED_SUMMARY_CHARS:
        logger.info(
            f"[chat_proposal_service] not proposing '{tool_name}' — no substantive "
            f"reply was actually shown to the user this turn"
        )
        return False

    # R01 review remediation round 4 (2026-09-27): "a sufficiently long
    # reply containing a domain noun does not prove the user saw the
    # proposed operation, target, parameters, and recurring scope."
    # Replaces the length-only gate above with a structural check: the
    # presented text must actually reference something specific to THIS
    # call's own arguments (not just the domain in general), must not be
    # a flat denial with no invitation to confirm, and — for a tool that
    # installs standing/recurring authority — must itself have framed the
    # proposal as recurring. See proposal_presentation.py.
    try:
        import json as _json
        from app.services.proposal_presentation import presented_summary_matches_proposal
        from app.services.tool_mutation import RECURRING_ESTABLISHING_TOOLS
        try:
            _args_for_check = _json.loads(arguments_json) if arguments_json else {}
        except Exception:
            _args_for_check = {}
        if not presented_summary_matches_proposal(
            tool_name, _args_for_check, presented_summary,
            require_recurring=tool_name in RECURRING_ESTABLISHING_TOOLS,
        ):
            logger.info(
                f"[chat_proposal_service] not proposing '{tool_name}' — presented "
                f"summary does not structurally match the proposed operation "
                f"(denial, unrelated discussion, or missing recurring framing)"
            )
            return False
    except Exception as e:
        logger.warning(f"[chat_proposal_service] structural presentation check failed, refusing to propose: {e}")
        return False

    try:
        import uuid
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        db.execute(text("""
            UPDATE chat_pending_proposal
            SET status = 'superseded'
            WHERE user_id = :user_id AND conversation_id = :conversation_id AND status = 'pending'
        """), {"user_id": user_id, "conversation_id": conversation_id})
        db.execute(text("""
            INSERT INTO chat_pending_proposal
                (id, user_id, conversation_id, tool_name, arguments_json, summary,
                 source_message, presented_summary, status, expires_at)
            VALUES
                (:id, :user_id, :conversation_id, :tool_name, :arguments_json, :summary,
                 :source_message, :presented_summary, 'pending', :expires_at)
        """), {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "tool_name": tool_name,
            "arguments_json": arguments_json,
            "summary": summary,
            "source_message": source_message,
            "presented_summary": presented_summary,
            "expires_at": expires_at,
        })
        db.commit()
        return True
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.debug(f"[chat_proposal_service] propose failed (non-fatal): {e}")
        return False


class ConsumedProposal:
    __slots__ = ("arguments_json", "source_message", "presented_summary")

    def __init__(self, arguments_json: str, source_message: str, presented_summary: str):
        self.arguments_json = arguments_json
        self.source_message = source_message
        self.presented_summary = presented_summary


def consume(
    db: Session, *, user_id: str, conversation_id: str, tool_name: str,
) -> Optional[ConsumedProposal]:
    """Atomically claim the one pending, unexpired proposal matching
    (user, conversation, tool_name). Returns a ConsumedProposal (with the
    original `arguments_json`, `source_message`, AND `presented_summary` —
    what Sara's reply actually told the user) on success, or None if there
    is no such proposal (never proposed, already consumed, superseded by a
    newer proposal, or expired — an expired row is marked so explicitly
    here rather than left ambiguous). A row this call didn't match is
    never touched.

    Callers MUST verify the returned `presented_summary` actually concerns
    the action being confirmed (e.g. mentions the tool's domain) before
    treating the confirmation as valid — a proposal existing at all
    already proves Sara said SOMETHING substantive, but not necessarily
    something ABOUT this specific action; see main_simple.py's consume
    call site for the domain-consistency check. Callers that gate a
    RECURRING_ESTABLISHING_TOOL (or any other message-content-derived
    authorization condition) MUST check it against the returned
    `source_message`/`presented_summary`, not the confirming turn's own
    message alone — consuming a proposal must never become a back door
    around a check the original refusal never actually passed.
    """
    try:
        now = datetime.now(timezone.utc)
        # Row-locked read-then-conditional-update, same shape as
        # NotesEditTool's optimistic concurrency: the UPDATE's own WHERE
        # clause is the atomicity guarantee (status='pending' at the time
        # of the UPDATE, not merely at an earlier SELECT), so two
        # concurrent confirmations can't both consume the same proposal.
        result = db.execute(text("""
            SELECT id, arguments_json, source_message, presented_summary, expires_at
            FROM chat_pending_proposal
            WHERE user_id = :user_id AND conversation_id = :conversation_id
              AND tool_name = :tool_name AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT 1
        """), {"user_id": user_id, "conversation_id": conversation_id, "tool_name": tool_name}).fetchone()

        if not result:
            return None

        if result.expires_at and result.expires_at.replace(tzinfo=timezone.utc) < now:
            db.execute(text("""
                UPDATE chat_pending_proposal SET status = 'expired' WHERE id = :id AND status = 'pending'
            """), {"id": result.id})
            db.commit()
            return None

        updated = db.execute(text("""
            UPDATE chat_pending_proposal
            SET status = 'consumed', consumed_at = NOW()
            WHERE id = :id AND status = 'pending'
        """), {"id": result.id})
        db.commit()

        if updated.rowcount == 0:
            return None  # lost a race with another consumer — nothing claimed

        return ConsumedProposal(
            result.arguments_json, result.source_message or "", result.presented_summary or "",
        )
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.debug(f"[chat_proposal_service] consume failed (non-fatal): {e}")
        return None
