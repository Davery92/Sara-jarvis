"""The chat tool loop's budgets and exits (harness rebuild Phase 3).

Every case here is a failure that actually reached David on 2026-09-11:

- turn 4 ran 500 seconds (iOS gave up at 180s, Postgres killed the connection
  at 6 minutes, the loop kept calling tools as a zombie);
- turn 3 sent 52,684 prompt tokens into a 49,152-token context, got a 400,
  and emitted the literal tool status string "Found 20 emails" as Sara's reply;
- `get_self_knowledge(capabilities)` returned 23,430 chars, the model saw
  1,403 of them with no way to ask for the rest, and went to `web_search` to
  look up its own capabilities.
"""

import asyncio
import json

import pytest

from app import main_simple as ms


class FakeStream:
    """Stands in for SimpleLLMClient._stream_response.

    Hand it a script of replies; each call pops the next one. A reply is either
    a dict (returned as-is) or an exception (raised).
    """

    def __init__(self, script):
        self.script = list(script)
        self.payloads = []

    async def __call__(self, payload):
        self.payloads.append(payload)
        if not self.script:
            return {"content": "done", "tool_calls": None}
        nxt = self.script.pop(0)
        # BaseException, not Exception: asyncio.CancelledError is not an
        # Exception in 3.8+, and cancellation is exactly what we script here.
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


def tool_call(name, call_id="c1", args="{}"):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": args}}


def make_client(monkeypatch, script, tool_result=None):
    client = ms.SimpleLLMClient()
    stream = FakeStream(script)
    client._stream_response = stream
    client._current_model = "qwen3.8-27b"
    client._current_model_config = {"provider": "openai", "base_url": "x", "api_key": "y"}

    async def _noop(*a, **kw):
        return None

    client.emit_event = _noop
    client.emit_activity = _noop

    stored = {}

    async def _store(messages, content, user_id, conversation_id, **kw):
        stored["content"] = content
        stored["calls"] = stored.get("calls", 0) + 1
        return "episode-1"

    client._store_conversation_with_timeout = _store

    async def _execute_tool(tc, user_id, conversation_id=None, session_cache=None):
        return {
            "role": "tool",
            "tool_call_id": tc["id"],
            "name": tc["function"]["name"],
            "content": tool_result if tool_result is not None
            else json.dumps({"success": True, "message": "Found 20 emails", "data": {}}),
        }

    client.execute_tool = _execute_tool

    # Session cache + registry side effects are not under test here.
    class _Cache:
        def get_session_context_summary(self, cid):
            return {}

        def set(self, *a, **kw):
            return None

    monkeypatch.setattr(
        "app.services.session_cache.SessionToolCache", lambda *a, **kw: _Cache()
    )
    monkeypatch.setattr(ms, "get_redis_sync_bytes", lambda: None, raising=False)
    return client, stream, stored


BANNED = (
    "I've searched through your documents",
    "Tool execution completed successfully.",
)

MESSAGES = [{"role": "user", "content": "download those attachments for me"}]


@pytest.mark.asyncio
class TestDeadline:
    async def test_deadline_forces_a_final_answer_with_no_tools(self, monkeypatch):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 0)  # expired immediately
        script = [
            {"content": "", "tool_calls": [tool_call("email_search")]},
            {"content": "Jim sent three files — the RFP, the quote, and the cert.",
             "tool_calls": None},
        ]
        client, stream, stored = make_client(monkeypatch, script)

        out = await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")

        assert "Jim sent three files" in out
        assert client._turn_ended_by == "deadline"
        # The forced call must carry no tools at all, or the model just calls
        # another one and the deadline means nothing.
        final_payload = stream.payloads[-1]
        assert not final_payload.get("tools")
        assert "tool_choice" not in final_payload
        for banned in BANNED:
            assert banned not in out

    async def test_round_budget_forces_a_final_answer(self, monkeypatch):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 9999)
        monkeypatch.setattr(ms, "CHAT_TOOL_ROUNDS_MAX", 2)
        script = [
            {"content": "", "tool_calls": [tool_call("email_search")]},
            {"content": "", "tool_calls": [tool_call("email_search", "c2")]},
            {"content": "Here's what I found across both searches.", "tool_calls": None},
        ]
        client, stream, stored = make_client(monkeypatch, script)

        out = await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")

        assert client._turn_ended_by == "rounds"
        assert not stream.payloads[-1].get("tools")
        for banned in BANNED:
            assert banned not in out

    async def test_a_normal_turn_is_not_forced(self, monkeypatch):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 9999)
        script = [
            {"content": "", "tool_calls": [tool_call("email_search")]},
            {"content": "Three files from Jim, all PDFs. Want them in the Studio?",
             "tool_calls": None},
        ]
        client, stream, stored = make_client(monkeypatch, script)

        out = await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")

        assert out.startswith("Three files")
        assert client._turn_ended_by == "model"


@pytest.mark.asyncio
class TestNeverEchoATool:
    async def test_a_tool_status_line_is_never_the_reply(self, monkeypatch):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 9999)
        script = [
            {"content": "", "tool_calls": [tool_call("email_search")]},
            # The exact Sept 11 failure: the model parrots the tool's message.
            {"content": "Found 20 emails", "tool_calls": None},
            {"content": "Twenty came back — the three from Jim are the ones you want.",
             "tool_calls": None},
        ]
        client, stream, stored = make_client(monkeypatch, script)

        out = await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")

        assert out != "Found 20 emails"
        assert "Twenty came back" in out

    async def test_a_too_short_reply_after_tools_is_replaced(self, monkeypatch):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 9999)
        script = [
            {"content": "", "tool_calls": [tool_call("email_search")]},
            {"content": "Done!", "tool_calls": None},
            {"content": "Three files, all filed. They're in the Studio tab.",
             "tool_calls": None},
        ]
        client, stream, stored = make_client(monkeypatch, script)

        out = await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")
        assert out != "Done!"
        assert "Studio" in out


@pytest.mark.asyncio
class TestContextOverflow:
    async def test_a_400_is_recovered_by_eviction_not_a_status_string(self, monkeypatch):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 9999)

        class Overflow(Exception):
            def __init__(self):
                super().__init__("400 Bad Request")
                self.response = type(
                    "R", (), {"text": "the request exceeds the available context size. "
                                      "try increasing the context size or enable context shift"}
                )()

        script = [
            {"content": "", "tool_calls": [tool_call("email_search")]},
            Overflow(),
            {"content": "Twenty emails came back; three of them are Jim's.",
             "tool_calls": None},
        ]
        # A result big enough that eviction has something to drop.
        big = json.dumps({"success": True, "message": "Found 20 emails",
                          "data": {"emails": ["x" * 400] * 400}})
        client, stream, stored = make_client(monkeypatch, script, tool_result=big)
        monkeypatch.setattr(ms, "CHAT_CONTEXT_LIMIT", 12000)

        out = await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")

        assert "Jim" in out
        assert out != "Found 20 emails"
        for banned in BANNED:
            assert banned not in out


@pytest.mark.asyncio
class TestCancellation:
    async def test_cancelled_turn_stores_no_assistant_episode(self, monkeypatch):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 9999)
        script = [asyncio.CancelledError()]
        client, stream, stored = make_client(monkeypatch, script)

        with pytest.raises(asyncio.CancelledError):
            await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")

        assert "calls" not in stored
        assert client._turn_ended_by == "cancelled"


class TestTokenEstimate:
    def test_estimate_is_pessimistic_against_the_measured_ratio(self):
        # 2026-09-11 log: 94,123 bytes reported 25,006 prompt tokens (3.76
        # chars/token). The estimator must never UNDER-count, or the pre-flight
        # check lets a payload through that the server then refuses.
        payload = {"messages": [{"role": "user", "content": "x" * 94000}]}
        est = ms._estimate_tokens(payload)
        assert est >= 25006


class TestEviction:
    def _msgs(self, n, size):
        out = [{"role": "system", "content": "sys"}]
        for i in range(n):
            out.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": f"c{i}", "function": {"name": "email_search", "arguments": "{}"}}]})
            out.append({
                "role": "tool", "tool_call_id": f"c{i}", "name": "email_search",
                "content": json.dumps({"success": True, "message": "Found 20 emails",
                                       "reference_id": f"ref{i}", "data": "y" * size}),
            })
        return out

    def test_evicts_oldest_first_until_it_fits(self, monkeypatch):
        monkeypatch.setattr(ms, "CHAT_CONTEXT_LIMIT", 20000)
        msgs = self._msgs(6, 20000)
        evicted = ms._evict_for_context(msgs, {"model": "m"}, 8000)
        assert evicted > 0
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        first = json.loads(tool_msgs[0]["content"])
        last = json.loads(tool_msgs[-1]["content"])
        assert first.get("_evicted") is True
        assert last.get("_evicted") is not True

    def test_an_evicted_result_keeps_its_reference_id(self, monkeypatch):
        monkeypatch.setattr(ms, "CHAT_CONTEXT_LIMIT", 20000)
        msgs = self._msgs(6, 20000)
        ms._evict_for_context(msgs, {"model": "m"}, 8000)
        evicted = [json.loads(m["content"]) for m in msgs if m["role"] == "tool"]
        evicted = [e for e in evicted if e.get("_evicted")]
        assert evicted and all(e["reference_id"].startswith("ref") for e in evicted)

    def test_nothing_is_evicted_when_it_already_fits(self):
        msgs = self._msgs(1, 100)
        assert ms._evict_for_context(msgs, {"model": "m"}, 8000) == 0


@pytest.mark.asyncio
class TestLargeResultsBecomeReferences:
    async def test_a_60k_result_becomes_a_preview_plus_reference(self, monkeypatch):
        stash = {}

        async def _set(key, value, ttl_seconds):
            stash[key] = value
            return True

        async def _get(key):
            return stash.get(key)

        monkeypatch.setattr(
            "app.services.search_service.search_service.cache_set_json", _set
        )
        monkeypatch.setattr(
            "app.services.search_service.search_service.cache_get_json", _get
        )

        full = json.dumps({"success": True, "message": "Read my capabilities",
                           "data": {"text": "z" * 60000}})
        responses = [{"role": "tool", "tool_call_id": "c1",
                      "name": "get_self_knowledge", "content": full}]

        out = await ms._reference_large_tool_results(responses)
        seen = json.loads(out[0]["content"])

        assert len(out[0]["content"]) <= 2100 + 400  # preview + envelope
        assert seen["message"] == "Read my capabilities"
        assert len(seen["preview"]) == ms.TOOL_RESULT_PREVIEW_CHARS
        assert seen["total_chars"] == len(full)
        ref = seen["reference_id"]

        from app.tools.get_tool_result_details import GetToolResultDetailsTool

        rest = await GetToolResultDetailsTool().execute(
            "u1", reference_id=ref, offset=ms.TOOL_RESULT_PREVIEW_CHARS, length=12000
        )
        assert rest.success
        assert rest.data["total_chars"] == len(full)
        assert rest.data["content"] == full[ms.TOOL_RESULT_PREVIEW_CHARS:
                                            ms.TOOL_RESULT_PREVIEW_CHARS + 12000]
        assert rest.data["has_more"] is True

    async def test_a_small_result_is_untouched(self):
        small = json.dumps({"success": True, "message": "ok", "data": {"n": 1}})
        responses = [{"role": "tool", "tool_call_id": "c1", "content": small}]
        out = await ms._reference_large_tool_results(responses)
        assert out[0]["content"] == small

    async def test_a_missing_reference_says_so_rather_than_inventing(self, monkeypatch):
        async def _get(key):
            return None

        monkeypatch.setattr(
            "app.services.search_service.search_service.cache_get_json", _get
        )
        from app.tools.get_tool_result_details import GetToolResultDetailsTool

        r = await GetToolResultDetailsTool().execute("u1", reference_id="nope")
        assert r.success is False
        assert "narrower query" in r.message


@pytest.mark.asyncio
class TestSelfKnowledgeIsPageable:
    async def test_a_big_section_returns_an_index_not_23k_chars(self):
        from app.tools.self_knowledge import GetSelfKnowledgeTool

        r = await GetSelfKnowledgeTool().execute("u1", section="capabilities")
        assert r.success
        assert r.data.get("index_only") is True
        assert len(r.message) < 4000
        assert r.data["headings"]

    async def test_one_category_returns_only_that_block(self):
        from app.tools.self_knowledge import GetSelfKnowledgeTool

        tool = GetSelfKnowledgeTool()
        index = await tool.execute("u1", section="capabilities")
        heading = index.data["headings"][0]
        one = await tool.execute("u1", section="capabilities", category=heading)
        assert one.success
        assert one.data["category"] == heading
        assert one.message.startswith(f"### {heading}")
        # The point of the whole change: one heading, not 23,430 chars.
        assert one.data["length"] < 6000

    async def test_an_unknown_category_lists_the_real_ones(self):
        from app.tools.self_knowledge import GetSelfKnowledgeTool

        r = await GetSelfKnowledgeTool().execute(
            "u1", section="capabilities", category="quantum teleportation"
        )
        assert r.success is False
        assert r.data["headings"]


class TestProviderScaffoldingNeverReachesDavid:
    """MTPLX appends an advisory when the model emits a tool call on a request
    with no tools — which is exactly the shape of the forced final. On the
    first Phase 3 replay this reached David inside Sara's reply."""

    MTPLX = (
        'It\'s running. Let me check on it.[MTPLX: this reply tried to call '
        '"workspace_job_run", but no tools are active on this request, so nothing '
        'was executed — there was no output and no error. This chat cannot read '
        'files or run terminal commands. For file and terminal access, connect a '
        'coding agent (Claude Code, OpenCode, or the Hermes agent in the MTPLX '
        'app) to MTPLX.]'
    )

    def test_the_advisory_is_stripped(self):
        out = ms._strip_provider_scaffolding(self.MTPLX)
        assert out == "It's running. Let me check on it."
        assert "MTPLX" not in out

    def test_ordinary_brackets_survive(self):
        text = "Filed three files [see the Studio tab] for you."
        assert ms._strip_provider_scaffolding(text) == text

    def test_citations_survive(self):
        text = "Jim sent the RFP on Tuesday [CITE:ep-42]."
        assert ms._strip_provider_scaffolding(text) == text

    def test_empty_and_none_are_safe(self):
        assert ms._strip_provider_scaffolding(None) == ""
        assert ms._strip_provider_scaffolding("") == ""


@pytest.mark.asyncio
class TestForcedFinalIsNeverScaffolding:
    async def test_a_scaffolding_only_forced_final_falls_back_honestly(self, monkeypatch):
        monkeypatch.setattr(ms, "CHAT_TURN_DEADLINE_S", 0)
        script = [
            {"content": "", "tool_calls": [tool_call("email_search")]},
            {"content": '[MTPLX: no tools are active on this request.]',
             "tool_calls": None},
        ]
        client, stream, stored = make_client(monkeypatch, script)

        out = await client.chat_with_tools(MESSAGES, [], "u1", "conv-1")

        assert "MTPLX" not in out
        assert len(out) >= 20
        for banned in BANNED:
            assert banned not in out


class TestSummarizeToolResultsIsNotUserFacing:
    def test_it_is_never_called_from_the_chat_loop(self):
        import inspect

        src = inspect.getsource(ms.SimpleLLMClient.chat_with_tools)
        assert "_summarize_tool_results" not in src

    def test_the_canned_document_string_is_gone(self):
        import inspect

        src = inspect.getsource(ms.SimpleLLMClient.chat_with_tools)
        assert "I've searched through your documents" not in src
