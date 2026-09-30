"""Reasoning may affect an answer, never its displayed or durable text."""
import json
import re

import httpx
import pytest
from unittest.mock import AsyncMock

from app import main_simple as ms
from app.services.chat_reasoning import ThinkingContentFilter, strip_thinking_content, StreamScaffoldGuard


@pytest.mark.parametrize("width", [1, 2, 3, 6, 8, 1000])
def test_split_reasoning_tags_never_leak(width):
    raw = "<think>private <tool_call>bad</tool_call></think>Answer < 5."
    parser = ThinkingContentFilter()
    answer = "".join(parser.feed(raw[i:i + width]) for i in range(0, len(raw), width))
    assert answer + parser.finish() == "Answer < 5."


@pytest.mark.parametrize("raw,expected", [
    ("<think>unfinished private reasoning", ""),
    ("Answer.<think>unfinished", "Answer."),
    ("<thi", ""),
    ("x <", "x <"),
    ("<think>one</think>A<think>two</think>B", "AB"),
])
def test_truncated_reasoning_and_ordinary_text(raw, expected):
    assert strip_thinking_content(raw) == expected


def test_thinking_request_disables_preserved_history(monkeypatch):
    monkeypatch.setattr(ms, "CHAT_ENABLE_THINKING", True)
    monkeypatch.setattr(ms, "CHAT_REASONING_EFFORT", "low")
    payload = {"presence_penalty": 1.5}
    ms._apply_local_qwen_chat_sampling(payload)
    assert payload["chat_template_kwargs"] == {
        "enable_thinking": True, "preserve_thinking": False,
        "reasoning_effort": "low",
    }
    assert payload["reasoning_effort"] == "low"
    assert payload["presence_penalty"] == 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize("inline", [False, True])
async def test_stream_drops_reasoning_before_display_tools_and_history(inline):
    if inline:
        deltas = [{"content": text} for text in [
            "<thi", "nk>private <tool_call>bad</tool_call></thi", "nk>", "Answer.",
        ]]
    else:
        deltas = [{"reasoning_content": "private"}, {"content": "Answer."}]
    deltas.append({"tool_calls": [{"index": 0, "id": "call-1", "type": "function",
        "function": {"name": "notes_search", "arguments": '{"query":"test"}'}}]})
    chunks = [{"choices": [{"delta": delta}]} for delta in deltas]
    chunks.append({"choices": [], "usage": {
        "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}})
    wire = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"
    client = ms.SimpleLLMClient()
    await client.client.aclose()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text=wire)))
    client._current_model_config = {"provider": "local", "base_url": "http://test/v1", "api_key": "test"}
    client.emit_text_chunk = AsyncMock()
    try:
        message = await client._stream_response({"model": "qwen3.8-27b", "messages": []})
        assert message["content"] == "Answer."
        assert "reasoning_content" not in message
        assert len(message["tool_calls"]) == 1
        assert message["tool_calls"][0]["function"]["name"] == "notes_search"
        visible = "".join(call.args[0] for call in client.emit_text_chunk.call_args_list)
        assert visible == "Answer."

        # The real persistence wrapper must pass only final text to storage.
        client.store_conversation = AsyncMock()
        result, _ = await client._store_conversation_with_timeout([], message["content"], "u", "c")
        assert result == "Answer."
        assert client.store_conversation.call_args.args[1] == "Answer."
    finally:
        await client.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("leak_text,width", [
    # A bare closing </tool_call> — no matching opener in this stream — is
    # what MTPLX actually sent when a model with zero tools declared this
    # turn reflexively tried to call find_tools (harness/thinking/
    # personality plan Phase 0/1 evidence: reproduced live in the prior
    # evaluation's Stage D, case p_repetition_check_2, 2/2 trials).
    ('</tool_call>[MTPLX: this reply tried to call "find_tools", but no '
     'tools are active on this request, so nothing was executed.]', 7),
    # Split at every width so a boundary landing mid-tag/mid-bracket can't
    # accidentally hide the leak.
    ('</tool_call>[MTPLX: this reply tried to call "find_tools", but no '
     'tools are active on this request, so nothing was executed.]', 1),
    ('</tool_call>[MTPLX: this reply tried to call "find_tools", but no '
     'tools are active on this request, so nothing was executed.]', 3),
    # LLAMA.CPP/SERVER are the other two advisory prefixes
    # _strip_provider_scaffolding already knows about for the FINAL text;
    # the streaming guard must recognize the same set.
    ('[LLAMA.CPP: context window exceeded]', 5),
    ('[SERVER: request cancelled upstream]', 4),
])
async def test_stream_never_emits_provider_scaffolding_or_bare_closing_tags(leak_text, width):
    """Harness/thinking/personality plan Phase 1, correcting the prior
    evaluation's overstated finding: `_finalize_response_content` already
    guarantees the STORED/RETURNED final answer is clean (it calls
    `strip_tool_markup`) — but nothing guarantees the LIVE STREAM is, since
    `emit_text_chunk` fires per-delta as chunks arrive, before that final
    cleanup ever runs. The existing holdback regex in `_stream_response`
    (`xml_tag_pattern`) only recognizes the START of an OPENING `<tool_call`
    or `<think` tag — a bare closing `</tool_call>` (no opener) and a
    provider-advisory bracket (`[MTPLX: ...]` etc, which doesn't start with
    `<` at all) match neither, so they stream straight to `emit_text_chunk`
    untouched. This test proves that precisely, split at every chunk
    boundary, rather than asserting it from a single sample."""
    before, after = "Fetched it. ", " More text."
    full_leak_source = before + leak_text + after
    deltas = [{"content": full_leak_source[i:i + width]} for i in range(0, len(full_leak_source), width)]
    chunks = [{"choices": [{"delta": d}]} for d in deltas]
    chunks.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    wire = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"

    client = ms.SimpleLLMClient()
    await client.client.aclose()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text=wire)))
    client._current_model_config = {"provider": "local", "base_url": "http://test/v1", "api_key": "test"}
    client.emit_text_chunk = AsyncMock()
    try:
        await client._stream_response({"model": "qwen3.8-27b", "messages": []})
        visible = "".join(call.args[0] for call in client.emit_text_chunk.call_args_list)
        assert "</tool_call>" not in visible, f"leaked closing tag into the live stream: {visible!r}"
        assert not re.search(r"\[(?:MTPLX|LLAMA\.CPP|SERVER)\s*:", visible), (
            f"leaked provider scaffolding into the live stream: {visible!r}")
    finally:
        await client.client.aclose()


@pytest.mark.asyncio
async def test_stream_resumes_after_a_standalone_advisory_bracket():
    """The fix must not overcorrect into silence: a `[MTPLX: ...]` advisory
    with no adjacent tag marker is a one-off insertion, not a dialect
    switch — legitimate text that follows it in the same turn must still
    reach the user, or a real turn would go visibly silent after any
    advisory instead of just losing the bracket itself."""
    before, after = "Here is what I found: ", " and that's the whole answer."
    full_source = before + "[MTPLX: context window exceeded]" + after
    deltas = [{"content": full_source[i:i + 5]} for i in range(0, len(full_source), 5)]
    chunks = [{"choices": [{"delta": d}]} for d in deltas]
    wire = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"

    client = ms.SimpleLLMClient()
    await client.client.aclose()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text=wire)))
    client._current_model_config = {"provider": "local", "base_url": "http://test/v1", "api_key": "test"}
    client.emit_text_chunk = AsyncMock()
    try:
        await client._stream_response({"model": "qwen3.8-27b", "messages": []})
        visible = "".join(call.args[0] for call in client.emit_text_chunk.call_args_list)
        assert visible == before + after, visible
    finally:
        await client.client.aclose()


@pytest.mark.parametrize("raw,width", [
    # Generation stops mid-tag-marker — the exact bug: finish() used to
    # release these genuine partial prefixes unconditionally.
    ("Fetched it. <tool_", 1), ("Fetched it. <tool_", 3), ("Fetched it. <tool_", 1000),
    ("Fetched it. </tool_ca", 1), ("Fetched it. </tool_ca", 4),
    ("Fetched it. <thi", 1), ("Fetched it. <thi", 2),
    ("Fetched it. </thi", 1),
    # Generation stops mid-bracket-marker (not yet inside the bracket —
    # still matching the marker's own prefix, e.g. "[MTP" of "[MTPLX:").
    ("Fetched it. [MTP", 1), ("Fetched it. [MTP", 2),
    ("Fetched it. [LLAMA.C", 1), ("Fetched it. [LLAMA.C", 5),
    ("Fetched it. [SERV", 1),
])
def test_finish_discards_a_genuine_partial_marker_prefix_at_any_chunk_boundary(raw, width):
    """StreamScaffoldGuard.finish() regression (Milestone A review,
    2026-09-22): everything left in `_pending` when the stream ends,
    aside from a single bare `<`/`[`, is BY CONSTRUCTION a real prefix of
    a control marker — `feed`'s longest-suffix-match holdback put it
    there. The old `finish()` released it unconditionally, leaking
    fragments like `<tool_`, `</tool_ca`, `[MTPLX` at stream end,
    truncation, cancellation, or error. Exercised at every chunk boundary
    so no particular split can hide a regression."""
    guard = StreamScaffoldGuard()
    visible = "".join(guard.feed(raw[i:i + width]) for i in range(0, len(raw), width))
    visible += guard.finish()
    assert "<tool_" not in visible
    assert "</tool_" not in visible
    assert "<thi" not in visible
    assert "[MTP" not in visible
    assert "[LLAMA" not in visible
    assert "[SERV" not in visible
    # And the safe prose that precedes the cut-short marker must still
    # have gone through — the fix must not overcorrect into silence.
    assert visible.startswith("Fetched it. ")


@pytest.mark.parametrize("raw", ["Answer is 5 <", "See item [", "<", "["])
def test_finish_still_releases_a_lone_safe_bracket_or_angle_char(raw):
    """The one deliberate exception, matching
    ThinkingContentFilter.finish()'s existing convention: a single bare
    `<` or `[` at the very end of a turn is ordinary prose (`5 < 10`,
    `see [1]`) that only happens to be a length-1 marker prefix — it must
    still reach the user, not be discarded as if it were a real partial
    marker."""
    guard = StreamScaffoldGuard()
    visible = guard.feed(raw) + guard.finish()
    assert visible == raw


def test_finish_after_suppression_releases_nothing():
    """Once a real tag marker has fired, the turn is suppressed for good
    (see feed()'s docstring) — finish() must not release anything
    afterward even if more text was fed in past the marker."""
    guard = StreamScaffoldGuard()
    guard.feed("before <tool_call>{\"name\": \"x\"}")
    assert guard.finish() == ""


def test_finish_inside_an_unterminated_bracket_releases_nothing():
    """A `[MTPLX: ...]` advisory that never closes before the stream ends
    is exactly the malformed case the bracket holdback exists for —
    finish() must not flush the unterminated advisory body."""
    guard = StreamScaffoldGuard()
    guard.feed("Here: [MTPLX: still talking and the stream just stops")
    assert guard.finish() == ""


@pytest.mark.asyncio
async def test_stream_truncated_mid_marker_never_leaks_the_fragment():
    """Same bug, exercised through the REAL _stream_response path (not
    just the StreamScaffoldGuard class in isolation): a provider stream
    that ends abruptly while mid-way through a control marker — the shape
    of a truncated/cancelled/errored generation — must not leak the
    partial marker into what the user sees or what gets stored."""
    before = "Here is the answer. "
    # No [DONE], no closing tag/bracket — the stream just stops, as it
    # would on truncation, upstream cancellation, or a dropped connection.
    full_source = before + "<tool_ca"
    deltas = [{"content": full_source[i:i + 3]} for i in range(0, len(full_source), 3)]
    chunks = [{"choices": [{"delta": d}]} for d in deltas]
    wire = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks)  # no [DONE] sentinel

    client = ms.SimpleLLMClient()
    await client.client.aclose()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text=wire)))
    client._current_model_config = {"provider": "local", "base_url": "http://test/v1", "api_key": "test"}
    client.emit_text_chunk = AsyncMock()
    try:
        await client._stream_response({"model": "qwen3.8-27b", "messages": []})
        visible = "".join(call.args[0] for call in client.emit_text_chunk.call_args_list)
        assert "<tool_" not in visible, f"leaked a truncated marker fragment: {visible!r}"
        assert visible == before
    finally:
        await client.client.aclose()


@pytest.mark.asyncio
async def test_persistence_rejects_unclosed_reasoning():
    client = ms.SimpleLLMClient()
    client.store_conversation = AsyncMock()
    try:
        result, episode_id = await client._store_conversation_with_timeout(
            [], "<think>private unfinished reasoning", "u", "c")
        assert result == ""
        assert episode_id is None
        assert client.store_conversation.call_args.args[1] == ""
    finally:
        await client.client.aclose()


class TestNoToolsChatReasoningIsolation:
    """Milestone A review, 2026-09-22: voice's no-tools path calls
    `SimpleLLMClient.chat()`, which used to return
    `result["choices"][0]["message"]["content"]` straight off the wire —
    no thinking-mode sampling config, no `<think>`/MLX-channel/tool-markup
    cleanup. These exercise `chat()` itself (what voice actually calls,
    end to end with a mocked provider transport, tools=None) rather than a
    reimplementation of its cleanup logic."""

    def _local_client(self, wire_content):
        client = ms.SimpleLLMClient()
        captured = {}

        def _handler(request):
            captured["payload"] = json.loads(request.content)
            body = json.dumps({"choices": [{"message": {"content": wire_content}}]})
            return httpx.Response(200, text=body)

        client.client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        return client, captured

    @pytest.mark.asyncio
    async def test_inline_think_tags_never_reach_the_returned_content(self, monkeypatch):
        monkeypatch.setattr(ms, "get_model_config", lambda m: {
            "provider": "local", "base_url": "http://test/v1", "api_key": "test"})
        client, _ = self._local_client("<think>private reasoning</think>The bank closes at 5pm.")
        try:
            result = await client.chat([{"role": "user", "content": "when does the bank close"}],
                                        model="qwen3.8-27b")
            assert result == "The bank closes at 5pm."
            assert "<think>" not in result and "private reasoning" not in result
        finally:
            await client.client.aclose()

    @pytest.mark.asyncio
    async def test_mlx_channel_wrapper_never_reaches_the_returned_content(self, monkeypatch):
        monkeypatch.setattr(ms, "get_model_config", lambda m: {
            "provider": "local", "base_url": "http://test/v1", "api_key": "test"})
        wire = ("<|channel|>analysis<|message|>thinking about it<|end|>"
                "<|start|>assistant<|channel|>final<|message|>It's 72 degrees.")
        client, _ = self._local_client(wire)
        try:
            result = await client.chat([{"role": "user", "content": "what's the temperature"}],
                                        model="qwen3.8-27b")
            assert result == "It's 72 degrees."
            assert "<|channel|>" not in result and "thinking about it" not in result
        finally:
            await client.client.aclose()

    @pytest.mark.asyncio
    async def test_a_reflexive_stray_tool_call_marker_never_reaches_the_returned_content(self, monkeypatch):
        """A no-tools turn has nothing to call, but a model can still
        reflexively emit the markup (the same MTPLX find_tools reflex
        StreamScaffoldGuard's docstring documents for the tool-enabled
        path) — voice must not speak or store that fragment either."""
        monkeypatch.setattr(ms, "get_model_config", lambda m: {
            "provider": "local", "base_url": "http://test/v1", "api_key": "test"})
        client, _ = self._local_client('<tool_call>{"name": "find_tools"}</tool_call>The timer is set.')
        try:
            result = await client.chat([{"role": "user", "content": "set a timer"}], model="qwen3.8-27b")
            assert result == "The timer is set."
            assert "tool_call" not in result
        finally:
            await client.client.aclose()

    @pytest.mark.asyncio
    async def test_local_lane_sends_the_shared_thinking_sampling_config(self, monkeypatch):
        """The bug wasn't only leakage — this path also skipped the
        payload-side half of the contract (`_apply_local_qwen_chat_sampling`),
        meaning the server's own thinking-mode default governed a lane the
        rest of the harness always sets explicitly (see
        `_apply_local_qwen_chat_sampling`'s docstring)."""
        monkeypatch.setattr(ms, "get_model_config", lambda m: {
            "provider": "local", "base_url": "http://test/v1", "api_key": "test"})
        monkeypatch.setattr(ms, "CHAT_ENABLE_THINKING", False)
        client, captured = self._local_client("Sure, all set.")
        try:
            await client.chat([{"role": "user", "content": "hi"}], model="qwen3.8-27b")
            assert captured["payload"]["chat_template_kwargs"] == {
                "enable_thinking": False, "preserve_thinking": False,
            }
        finally:
            await client.client.aclose()

    @pytest.mark.asyncio
    async def test_no_tools_and_tool_enabled_voice_paths_both_isolate_reasoning_end_to_end(self, monkeypatch):
        """Direct side-by-side, both against mocked transports, tools=None
        vs tools=[...]: the two voice code paths (`chat()` vs
        `chat_with_tools()`) must produce the same reasoning-isolation
        guarantee for the same raw provider output shape. The tool-enabled
        side reuses `_stream_response`, already covered exhaustively by
        `test_stream_drops_reasoning_before_display_tools_and_history`
        above — this proves the no-tools side now matches it instead of
        returning raw provider content."""
        monkeypatch.setattr(ms, "get_model_config", lambda m: {
            "provider": "local", "base_url": "http://test/v1", "api_key": "test"})
        client, _ = self._local_client("<think>hmm</think>Done.")
        try:
            no_tools_result = await client.chat(
                [{"role": "user", "content": "ok"}], model="qwen3.8-27b")
            assert no_tools_result == "Done."
            assert "<think>" not in no_tools_result
        finally:
            await client.client.aclose()

        # Tool-enabled side: same reasoning shape, via the streaming path.
        deltas = [{"content": c} for c in ["<think>hmm</think>", "Done."]]
        chunks = [{"choices": [{"delta": d}]} for d in deltas]
        chunks.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
        wire = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"
        tool_client = ms.SimpleLLMClient()
        await tool_client.client.aclose()
        tool_client.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=wire)))
        tool_client._current_model_config = {"provider": "local", "base_url": "http://test/v1", "api_key": "test"}
        tool_client.emit_text_chunk = AsyncMock()
        try:
            message = await tool_client._stream_response({"model": "qwen3.8-27b", "messages": []})
            assert message["content"] == "Done."
        finally:
            await tool_client.client.aclose()


def test_get_current_user_is_synchronous_not_a_coroutine_function():
    """2026-09-22: 5 endpoints (including the voice/chat endpoint's cookie-
    auth fallback) did `await get_current_user(request, db)` — but
    get_current_user is a plain `def`, not `async def`, so awaiting its
    return value (a User) raised TypeError on every call, silently
    swallowed into a misleading 401 by each endpoint's own except clause.
    Cookie-based auth for those endpoints never actually worked. This
    guards the fix (removing the erroneous `await`) against regressing —
    if get_current_user is ever made properly async, every call site
    fixed here must be updated to `await` it again."""
    import inspect
    from app import main_simple as ms
    assert not inspect.iscoroutinefunction(ms.get_current_user)
