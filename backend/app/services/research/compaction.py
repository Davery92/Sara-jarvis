"""Context compaction for the research executor.

A research step is a long tool-calling loop, and every result it collects stays in
`messages` for the rest of the step: `web_search` returns 10 Tavily hits, `read_file`
returns a whole file. Left alone the transcript grows until the request exceeds the
lane's context window and llama.cpp rejects the whole step with
`400 exceed_context_size_error` — which is exactly how every step of every plan was
dying on 2026-08-19.

Raising the window buys headroom but does not bound growth, so this module bounds it:

  * `truncate_tool_result` caps any single tool payload on the way in.
  * `compact_messages` folds the middle of the transcript into a running digest once
    the estimated size crosses a threshold, keeping the step brief and the most recent
    exchanges verbatim.

The digest is produced by the research LLM itself; if that call fails we fall back to
dropping the middle with an explicit marker, because losing some intermediate detail is
always better than losing the entire step.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Rough chars-per-token for this model family. Deliberately a heuristic — an exact
# tokenizer round-trip per turn would cost more than it saves, and every consumer
# here only needs to know "are we approaching the wall".
CHARS_PER_TOKEN = 4

# Any single tool result larger than this is truncated on the way into the
# transcript. Generous enough to hold a substantial page or file section.
MAX_TOOL_RESULT_CHARS = 12000

# How many trailing messages stay verbatim when we compact. The tail is always
# extended backwards so it never begins with an orphaned `tool` message.
KEEP_RECENT_MESSAGES = 6

DIGEST_MARKER = "[Compacted research notes — earlier turns of this step]"

_DIGEST_PROMPT = (
    "You are condensing the middle of a research transcript so the agent can keep "
    "working without exceeding its context window.\n\n"
    "Write a dense digest that PRESERVES:\n"
    "  - every concrete fact, number, date and claim discovered\n"
    "  - every source URL and the claim it supports\n"
    "  - every file path written or read, and what it contains\n"
    "  - contradictions between sources, and open questions still unanswered\n\n"
    "DROP: tool-call mechanics, retries, navigation chatter, and duplicated text.\n"
    "Write plain prose and bullets. Do not invent anything not present below.\n\n"
    "TRANSCRIPT:\n"
)


def estimate_tokens(messages: List[Dict[str, Any]]) -> int:
    """Approximate the token cost of a message list."""
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += len(content)
        elif content is not None:
            total += len(json.dumps(content))
        # tool_calls carry real weight — the arguments are often large JSON
        tool_calls = m.get("tool_calls")
        if tool_calls:
            total += len(json.dumps(tool_calls))
    return total // CHARS_PER_TOKEN


def truncate_tool_result(content: Any, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    """Cap a single tool result, keeping head and tail.

    Tool output is usually front-loaded (the summary, the first search hits) but the
    tail often carries the conclusion, so we keep both ends rather than a prefix.
    """
    if not isinstance(content, str):
        try:
            content = json.dumps(content)
        except (TypeError, ValueError):
            content = str(content)

    if len(content) <= max_chars:
        return content

    head = int(max_chars * 0.7)
    tail = max_chars - head - 100
    omitted = len(content) - head - tail
    return (
        content[:head]
        + f"\n\n... [{omitted} chars omitted by compaction] ...\n\n"
        + content[-tail:]
    )


def _split_head_middle_tail(
    messages: List[Dict[str, Any]],
    keep_recent: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split into (head, middle, tail).

    Head = leading system messages plus the first user message (the step brief),
    which must survive verbatim or the agent forgets its task. Tail = the most recent
    `keep_recent` messages, walked backwards so it never starts on a `tool` message
    orphaned from the assistant turn that called it.
    """
    head_end = 0
    while head_end < len(messages) and messages[head_end].get("role") == "system":
        head_end += 1
    # include the step brief (first user message) if present
    if head_end < len(messages) and messages[head_end].get("role") == "user":
        head_end += 1

    tail_start = max(head_end, len(messages) - keep_recent)
    # never begin the tail on a tool result whose assistant call would be dropped
    while tail_start > head_end and messages[tail_start].get("role") == "tool":
        tail_start -= 1

    return messages[:head_end], messages[head_end:tail_start], messages[tail_start:]


def _render_middle(middle: List[Dict[str, Any]]) -> str:
    """Flatten the middle of the transcript into text for summarisation."""
    parts = []
    for m in middle:
        role = m.get("role", "?")
        if role == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                parts.append(f"[called {fn.get('name')}({str(fn.get('arguments'))[:300]})]")
            if m.get("content"):
                parts.append(f"assistant: {m['content']}")
        elif role == "tool":
            parts.append(f"[result] {str(m.get('content'))[:4000]}")
        else:
            content = m.get("content")
            if content:
                parts.append(f"{role}: {content}")
    return "\n".join(parts)


async def compact_messages(
    messages: List[Dict[str, Any]],
    llm: Any,
    budget_tokens: int,
    keep_recent: int = KEEP_RECENT_MESSAGES,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Fold the middle of `messages` into a digest if it exceeds `budget_tokens`.

    Returns `(messages, compacted)`. The input list is never mutated.
    """
    before = estimate_tokens(messages)
    if before <= budget_tokens:
        return messages, False

    head, middle, tail = _split_head_middle_tail(messages, keep_recent)
    if not middle:
        # Nothing foldable — the head and tail alone are over budget. Shrink the
        # biggest tool results in the tail instead of giving up.
        shrunk = _shrink_tail_tool_results(head + tail, budget_tokens)
        logger.warning(
            "Research compaction: nothing to fold (%d tok), shrank tool results to %d tok",
            before, estimate_tokens(shrunk),
        )
        return shrunk, True

    digest = await _summarise(middle, llm)
    if digest is None:
        digest = (
            f"{len(middle)} earlier messages were dropped to stay within the context "
            "window, and could not be summarised. Re-read any files you wrote for detail."
        )
        logger.warning("Research compaction: digest call failed, dropped middle verbatim")

    compacted = head + [{"role": "user", "content": f"{DIGEST_MARKER}\n{digest}"}] + tail
    after = estimate_tokens(compacted)
    logger.info(
        "Research compaction: %d -> %d tokens (folded %d messages, budget %d)",
        before, after, len(middle), budget_tokens,
    )

    if after > budget_tokens:
        compacted = _shrink_tail_tool_results(compacted, budget_tokens)
        logger.info("Research compaction: tail shrunk to %d tokens", estimate_tokens(compacted))

    return compacted, True


def _shrink_tail_tool_results(
    messages: List[Dict[str, Any]],
    budget_tokens: int,
) -> List[Dict[str, Any]]:
    """Last resort: progressively truncate the largest tool results until we fit."""
    out = [dict(m) for m in messages]
    limit = MAX_TOOL_RESULT_CHARS
    for _ in range(8):
        if estimate_tokens(out) <= budget_tokens:
            break
        limit = max(500, limit // 2)
        for m in out:
            if m.get("role") == "tool" and isinstance(m.get("content"), str):
                m["content"] = truncate_tool_result(m["content"], limit)
    return out


async def _summarise(middle: List[Dict[str, Any]], llm: Any) -> Optional[str]:
    """Ask the research LLM for a digest of the middle. None if the call fails."""
    body = _render_middle(middle)
    # Bound what we hand the summariser too — it has the same context ceiling.
    if len(body) > 60000:
        body = body[:40000] + "\n\n... [middle of transcript elided] ...\n\n" + body[-20000:]

    try:
        response = await llm.chat_completion(
            messages=[{"role": "user", "content": _DIGEST_PROMPT + body}],
            temperature=0.2,
            max_tokens=1500,
        )
        text = (llm.get_message(response) or {}).get("content") or ""
        text = text.strip()
        return text or None
    except Exception as e:
        logger.error("Research compaction digest failed: %s: %s", type(e).__name__, e)
        return None
