"""Tests for the tool-history compactor in agent_dispatch.

Motivation: a research task once ran 22 `web_search` calls and pushed the
prompt past the LLM's context window when the loop appended a follow-up
nudge. `_compact_tool_history` is the sliding-window compactor that keeps
the most-recent K tool results in full and replaces older ones with a
short marker — preserving message shape (tool_call_id, role) while
elidong the bulky content.
"""

from __future__ import annotations

from app.services.agent_dispatch import (
    KEEP_RECENT_TOOL_RESULTS,
    _compact_tool_history,
)


def _build_history(num_tool_calls: int) -> list[dict]:
    """Build a minimal valid messages history with N assistant→tool pairs."""
    msgs: list[dict] = [
        {"role": "system", "content": "you are an agent"},
        {"role": "user", "content": "do the thing"},
    ]
    for i in range(num_tool_calls):
        tc_id = f"call_{i:03d}"
        msgs.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": tc_id,
                "function": {"name": "web_search", "arguments": "{}"},
            }],
        })
        # A realistic web_search result chunk — a couple KB each.
        msgs.append({
            "role": "tool",
            "tool_call_id": tc_id,
            # 2000-char filler stands in for actual search-result payload.
            "content": f"result body for {tc_id} " + ("x" * 2000),
        })
    return msgs


# ── No-op below the threshold ─────────────────────────────────────────


def test_no_compaction_under_threshold() -> None:
    msgs = _build_history(num_tool_calls=KEEP_RECENT_TOOL_RESULTS)
    compacted = _compact_tool_history(msgs)
    assert compacted == 0
    # Every tool message keeps its original full-length content.
    for m in msgs:
        if m.get("role") == "tool":
            assert not m["content"].startswith("[compacted:")


def test_one_over_threshold_compacts_exactly_one() -> None:
    msgs = _build_history(num_tool_calls=KEEP_RECENT_TOOL_RESULTS + 1)
    compacted = _compact_tool_history(msgs)
    assert compacted == 1
    tool_msgs = [m for m in msgs if m.get("role") == "tool"]
    # Oldest tool result was compacted; the rest are intact.
    assert tool_msgs[0]["content"].startswith("[compacted:")
    for m in tool_msgs[1:]:
        assert not m["content"].startswith("[compacted:")


# ── Long histories — keeps the window honest ──────────────────────────


def test_long_history_keeps_only_recent_window() -> None:
    """22 web_searches (today's failure scenario) — only the last 8 stay full."""
    msgs = _build_history(num_tool_calls=22)
    compacted = _compact_tool_history(msgs)
    assert compacted == 22 - KEEP_RECENT_TOOL_RESULTS
    tool_msgs = [m for m in msgs if m.get("role") == "tool"]
    for m in tool_msgs[:-KEEP_RECENT_TOOL_RESULTS]:
        assert m["content"].startswith("[compacted:")
        # Marker names the tool so the model knows what was elided.
        assert "web_search" in m["content"]
    for m in tool_msgs[-KEEP_RECENT_TOOL_RESULTS:]:
        assert not m["content"].startswith("[compacted:")


def test_compaction_preserves_message_shape() -> None:
    """Compaction must NOT drop messages or alter tool_call_ids — the OpenAI
    chat-completions API requires every `tool` message to reference a
    tool_call_id from a preceding assistant turn, or the request 400s."""
    msgs = _build_history(num_tool_calls=15)
    original_len = len(msgs)
    original_ids = [m["tool_call_id"] for m in msgs if m.get("role") == "tool"]
    _compact_tool_history(msgs)
    assert len(msgs) == original_len
    new_ids = [m["tool_call_id"] for m in msgs if m.get("role") == "tool"]
    assert new_ids == original_ids


# ── Idempotency ───────────────────────────────────────────────────────


def test_compaction_is_idempotent() -> None:
    """Called every loop iteration — re-running on an already-compacted
    history should be a no-op (zero new compactions)."""
    msgs = _build_history(num_tool_calls=20)
    first_pass = _compact_tool_history(msgs)
    second_pass = _compact_tool_history(msgs)
    assert first_pass == 20 - KEEP_RECENT_TOOL_RESULTS
    assert second_pass == 0


def test_compaction_significantly_reduces_size() -> None:
    """Sanity-check the actual byte savings on a realistic long run."""
    msgs = _build_history(num_tool_calls=22)
    before = sum(len(m.get("content") or "") for m in msgs)
    _compact_tool_history(msgs)
    after = sum(len(m.get("content") or "") for m in msgs)
    # 14 of 22 tool results shrunk from ~2KB to ~70 bytes — should drop the
    # total by at least 20 KB. (Conservative bound; actual is much more.)
    assert before - after > 20_000
