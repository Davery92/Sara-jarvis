"""The shared chat assembly boundary (living-world-context plan, Phase 0
item 5 / Phase 2): the pure, testable core of building the local-provider
prompt-cache-split message list — extracted out of the SSE handler in
main_simple.py so it can be exercised directly, with injected inputs,
against its actual return value (the real outgoing `all_messages` payload)
rather than only through a live chat turn.

Side effects (logging, the debug-dump file, streaming_client diagnostics)
stay in main_simple.py, which calls `assemble_local_provider_messages` and
does its own reporting on the result — this module only computes.
"""

from __future__ import annotations

from typing import Any, List, Sequence

from app.schemas.chat import ChatMessage
from app.services.context_budget import allocate_live_context_sections

_LIVE_CTX_OPEN = "<live_context>"
_LIVE_CTX_CLOSE = "</live_context>"

# The exact marker main_simple.py injects the World Brief under — kept here
# too so a caller that already removed it from its own `full_sys` doesn't
# have to duplicate the literal string, and so a test can assert on it.
WORLD_BRIEF_MARKER = "\n\n## What's true in David's world right now\n"

_LIVE_CTX_PREAMBLE = (
    "[Sara — your own live awareness for this moment, placed here by your system, "
    "not typed by David: the time, how you're feeling, what you know about him and "
    "his day. Read it as your own knowing, not as data to consult. Speak from it "
    "naturally — never recite it, quote it, or refer to \"this block\". Every "
    "specific you state about his day must actually appear here, in the "
    "conversation, or in a tool result. David's message follows the closing tag.]\n\n"
)


def replace_world_state_core_in_messages(messages, old_value: str, new_value: str):
    """Living-world-context plan, Turn 3 item 2 ("Updates during long
    turns"): a multi-round tool-calling turn bakes `world_state_core` into
    the message list once, before the round loop starts. A tool call
    earlier in THIS SAME turn (or an external event landing between
    rounds) can move a fact before the model asks again — the workout it
    just logged ends, a reminder fires. Without this, the model's next
    round call still sees the stale value baked into round 1's messages,
    with nothing telling it that value is now wrong.

    Finds `old_value` verbatim inside `messages` (dict entries or objects
    with a `.content` attribute; plain string content or a list of
    `{"type": "text", "text": ...}` parts) and REPLACES it with
    `new_value` in place — never appends a second, conflicting copy
    alongside the stale one. A no-op (returns `changed=False`) when
    `old_value` is empty, unchanged, or not found (it may already have
    been evicted by `_evict_for_context` — nothing to replace is correct,
    not an error).

    Mutates `messages` in place for dict entries (matching how
    `current_messages` is threaded through the round loop elsewhere) and
    returns `(messages, changed)`.
    """
    if not old_value or old_value == new_value:
        return messages, False
    changed = False
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
        if isinstance(content, str):
            if old_value in content:
                new_content = content.replace(old_value, new_value, 1)
                if isinstance(m, dict):
                    m["content"] = new_content
                else:
                    m.content = new_content
                changed = True
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str) and old_value in part["text"]:
                    part["text"] = part["text"].replace(old_value, new_value, 1)
                    changed = True
    return messages, changed


def compose_voice_persona(
    *,
    datetime_line: str,
    persona: str,
    overlay_parts: Sequence[str],
) -> str:
    """Voice's counterpart to text chat's [stable system][datetime+volatile
    system] split — harness/thinking/personality plan Phase 2.

    Voice sends ONE system message (see `assemble_voice_messages`), so there
    is no prompt-cache split to preserve here the way local-provider text
    chat has one; this exists so the composition itself — datetime first,
    then the shared persona, then voice-specific overlay material (canvas
    mode, the per-turn voice context bundle) — is a plain, independently
    testable function instead of a sequence of `system_prompt +=` mutations
    threaded through a 700-line SSE generator with no test coverage of its
    own. `persona` is expected to already be the output of
    `build_chat_system_prompt` — the SAME builder text chat uses — not a
    separate voice-only persona string.
    """
    parts = [datetime_line + "\n\n---", persona]
    parts.extend(p for p in overlay_parts if p)
    return "\n\n".join(parts)


def assemble_voice_messages(
    *,
    system_prompt: str,
    dialogue_block: str,
    world_state_core: str,
    conversation_history: Sequence[dict],
    user_message: str,
) -> List[dict]:
    """The voice-endpoint (`/api/pi-dashboard/voice/chat`) counterpart to
    `assemble_non_local_provider_messages` — same parity gap, third
    independent code path. Unlike text chat, voice's `system_prompt` is
    already fully assembled (persona, tools, its own voice_budget context)
    by the time this is called, and there's no separate datetime_line — the
    datetime is already baked into `system_prompt` by `get_system_prompt`.
    Plain dicts throughout, not ChatMessage objects: voice's
    conversation_history already comes back from the Episode query as
    dicts, and chat_with_tools accepts either shape.

    Returns the actual `llm_messages` list passed to chat_with_tools.
    """
    core_parts = [p for p in (dialogue_block, world_state_core) if p]
    core_block = ("\n\n".join(core_parts) + "\n\n") if core_parts else ""
    return (
        [{"role": "system", "content": core_block + system_prompt}]
        + list(conversation_history)
        + [{"role": "user", "content": user_message}]
    )


def assemble_non_local_provider_messages(
    *,
    full_sys: str,
    dialogue_block: str,
    world_state_core: str,
    datetime_line: str,
    conversation_history: Sequence[ChatMessage],
    merged_request_messages: Sequence[ChatMessage],
) -> dict:
    """The non-local-provider (Claude/Gemini/codex) counterpart to
    `assemble_local_provider_messages` — living-world-context plan, Phase 2
    item 8: "Use the same fact precedence and freshness behavior for local
    and non-local providers." `full_sys` already carries the World Brief
    (injected earlier, unconditionally, before either provider branch) —
    what a non-local turn used to be missing entirely was dialogue_block
    and world_state_core, both built but only ever spliced into the
    local-provider branch's live-context block.

    No prompt-cache split and no tight char budget here: non-local
    providers keep the single system message they expect, and aren't
    billed on a stable-prefix cache hit the way the local lane is, so
    there's no budget this needs to fit under beyond what upstream
    assembly (engaged context, the brief) already enforced.

    Returns {"all_messages"} — same key as the local-provider function's
    return dict, so a caller can treat both uniformly.
    """
    core_parts = [p for p in (dialogue_block, world_state_core) if p]
    core_block = ("\n\n".join(core_parts) + "\n\n") if core_parts else ""
    system_message = ChatMessage(role="system", content=datetime_line + "\n\n" + core_block + full_sys)
    all_messages: List[Any] = [system_message] + list(conversation_history) + list(merged_request_messages)
    return {"all_messages": all_messages}


def assemble_local_provider_messages(
    *,
    full_sys: str,
    stable_system_prompt: str,
    conversation_history: Sequence[ChatMessage],
    merged_request_messages: Sequence[ChatMessage],
    dialogue_block: str,
    world_state_core: str,
    world_brief: str,
    datetime_line: str,
    live_context_char_budget: int,
) -> dict:
    """Build the [stable system][live-context-wrapped last user turn][...]
    message list Qwen's chat template needs for a cacheable prefix.

    `full_sys` is the assembled system message content (persona + whatever
    was appended ahead of this point — engaged context, corrections,
    world brief, attention/notes/re-entry material); `stable_system_prompt`
    is the substring of it that must stay a stable prefix across turns.
    `world_brief` is passed SEPARATELY and REMOVED from `full_sys` if
    present there (via WORLD_BRIEF_MARKER) before allocation, so it is
    allocated its own guaranteed share rather than living inside the
    undifferentiated remainder and competing on equal footing with whatever
    else grew that remainder — see Finding #1 in the plan's evidence table.

    Returns a dict: {"all_messages", "volatile", "volatile_raw_chars"}.
    `all_messages` is the actual outgoing payload; the other two are for
    the caller's own diagnostics/logging.
    """
    split_idx = full_sys.find(stable_system_prompt)
    if split_idx < 0:
        volatile = full_sys.strip()
    else:
        volatile = (full_sys[:split_idx] + full_sys[split_idx + len(stable_system_prompt):]).strip()

    world_brief_for_envelope = ""
    if world_brief and (WORLD_BRIEF_MARKER + world_brief) in volatile:
        volatile = volatile.replace(WORLD_BRIEF_MARKER + world_brief, "", 1)
        world_brief_for_envelope = world_brief
    elif world_brief:
        # Caller passed a brief that isn't (or is no longer) embedded in
        # `full_sys` — still give it its guaranteed share rather than
        # silently dropping it.
        world_brief_for_envelope = world_brief

    volatile, volatile_raw_chars = allocate_live_context_sections(
        dialogue_state=dialogue_block,
        world_state_core=world_state_core,
        world_brief=world_brief_for_envelope,
        rest=volatile,
        max_chars=live_context_char_budget,
    )

    live_block = (
        f"{_LIVE_CTX_OPEN}\n"
        + _LIVE_CTX_PREAMBLE
        + datetime_line + ("\n\n" + volatile if volatile else "") + f"\n{_LIVE_CTX_CLOSE}\n\n"
    )

    all_messages: List[Any] = (
        [ChatMessage(role="system", content=stable_system_prompt)]
        + list(conversation_history) + list(merged_request_messages)
    )
    last_user_idx = max((i for i, m in enumerate(all_messages) if m.role == "user"), default=None)
    if last_user_idx is None:
        # No user turn at all (shouldn't happen) — fall back to a leading system block.
        all_messages.insert(1, ChatMessage(role="system", content=live_block))
    else:
        um = all_messages[last_user_idx]
        if isinstance(um.content, list):
            new_content: Any = [{"type": "text", "text": live_block}] + list(um.content)
        else:
            new_content = live_block + (um.content or "")
        all_messages[last_user_idx] = ChatMessage(role="user", content=new_content)

    assert len(volatile) <= live_context_char_budget, (
        f"live context {len(volatile)} chars exceeds the {live_context_char_budget}-char "
        "budget after clipping — the final-boundary clip did not run"
    )

    return {
        "all_messages": all_messages,
        "volatile": volatile,
        "volatile_raw_chars": volatile_raw_chars,
        "live_block": live_block,
    }
