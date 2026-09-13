"""The vocabulary of world_thread kinds, and what the interpreter is allowed
to invent.

Ground-truth invariant 3 is "everything open has a closer and an expiry." A
thread kind that nothing can close is a nag generator: the three Laura
Weippert threads were `commitment` and `follow_up` and no code path could
resolve either, and on 2026-09-11 the interpreter opened five threads whose
kinds — `feature_gap`, `feature_request`, `action_item` — it made up on the
spot from David's own chat turns. Nothing could ever close those, so the
weekly wiring check reported them as permanent findings.

The prompt listed the legal kinds in prose only; `interpreter.py` and
`reducer.py` accepted any string up to 32 chars. This module is the single
source of truth both doors clamp against.

Trusted producers (calendar, commitment_service, the conversation tracker)
are NOT clamped — they legitimately open `plan`, `prep`, `meeting` and
`active_conversation`. Only LLM-interpreted threads pass through
`coerce_interpreted_kind`.
"""

# Each kind names how it gets closed; a live kind with no entry here fails
# the weekly wiring check rather than quietly joining the nag pile.
THREAD_KIND_CLOSERS = {
    "active_conversation": "conversation.closed",
    "follow_up": "thread.resolved (sent reply / David / ack / expiry)",
    "commitment": "thread.resolved (commitment_service / David / expiry)",
    "plan": "task.completed / task.cancelled",
    "decision": "thread.resolved (David / expiry)",
    "dependency": "thread.resolved (David / expiry)",
    "prep": "calendar.ended",
    "meeting": "calendar.ended",
    "support_ticket": "thread.resolved (sent reply / David)",
}

# What the LLM interpreter may open. A strict subset of THREAD_KIND_CLOSERS:
# every one of these has a closer that does not depend on an external system
# (a calendar event ending, a conversation closing) that an interpreted thread
# has no link to.
INTERPRETED_THREAD_KINDS = ("follow_up", "commitment", "decision", "dependency")
DEFAULT_INTERPRETED_KIND = "follow_up"


def coerce_interpreted_kind(raw) -> str:
    """Clamp an LLM-proposed thread kind to one the system can close.

    Anything unrecognised becomes `follow_up` rather than being dropped: the
    interpreter noticed something, and a closeable follow-up is a better
    outcome than either an uncloseable invented kind or a silently lost item.
    """
    kind = str(raw or "").strip().lower().replace("-", "_")[:32]
    return kind if kind in INTERPRETED_THREAD_KINDS else DEFAULT_INTERPRETED_KIND
