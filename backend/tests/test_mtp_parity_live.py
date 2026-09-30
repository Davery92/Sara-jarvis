"""AR/MTP parity against the real local chat lane (chat harness repair Phase 7).

David's recommended disposition (2026-09-16): keep production on AR, build
this parity suite, run it before ever flipping LOCAL_GENERATION_MODE to mtp.
gotcha_mtplx_mtp_derails_qwen38_27b.md found MTP corrupting tool-bearing
replies on this exact model/pack; this suite is how that gets re-checked
against the CURRENT server build rather than assumed still true or assumed
fixed.

Real calls to the local model server — slow (a handful of generations per
scenario) and opt-in:

    SARA_MTP_LIVE_TEST=1 pytest tests/test_mtp_parity_live.py -v

Everything runs at temperature=0 so AR and MTP should be IDENTICAL under
the server's own "exact speculative sampling" claim — that's the actual
thing under test, not throughput. A mismatch is either evidence the
derailing bug is still present, or evidence "exact" doesn't mean what the
server's /health claims.

Lives in tests/, not tests/replay/: it needs no database at all, replay or
otherwise, only the model server — and tests/replay/conftest.py skips
everything under that directory unless DATABASE_URL points at sara_replay,
which would make this un-runnable for no reason. The morning-sequence class
below reads the 2026_09_16 fixture's turns.json directly as plain JSON, the
same way test_dialogue_state_2026_09_16_fixture.py does.
"""
import json
import os

import httpx
import pytest

LOCAL_URL = os.getenv("LOCAL_CHAT_LANE_URL", "http://100.104.68.115:8082/v1/chat/completions")
MODEL = os.getenv("LOCAL_CHAT_LANE_MODEL", "qwen3.8-27b")

RUN_LIVE = os.getenv("SARA_MTP_LIVE_TEST") == "1"
requires_live = pytest.mark.skipif(
    not RUN_LIVE, reason="set SARA_MTP_LIVE_TEST=1 to call the live local chat lane"
)

pytestmark = [pytest.mark.asyncio, requires_live]


async def _call(messages, tools=None, mode="ar", depth=0, max_tokens=200, stream=False):
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
        "generation_mode": mode,
        "depth": depth if mode == "mtp" else 0,
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=90.0) as client:
        if not stream:
            resp = await client.post(LOCAL_URL, json=payload)
            resp.raise_for_status()
            return resp.json()

        chunks = []
        async with client.stream("POST", LOCAL_URL, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[len("data: "):]
                if raw.strip() == "[DONE]":
                    break
                chunks.append(json.loads(raw))
        return chunks


def _stats(response: dict) -> dict:
    return response.get("mtplx_stats", {})


def _assert_mtp_actually_engaged(response: dict, expected_depth: int):
    stats = _stats(response)
    assert stats.get("generation_mode") == "mtp"
    assert stats.get("mtp_depth") == expected_depth, stats
    assert stats.get("verify_calls", 0) > 0, "mtp mode ran with zero verify calls — not actually engaged"


def _assert_no_raw_tool_markup(text: str):
    if text is None:
        return
    for marker in ("<tool_call>", "<function=", "</tool_call>"):
        assert marker not in text, f"raw tool markup leaked into content: {text[:200]!r}"


# ---------------------------------------------------------------------------
# Plain conversation
# ---------------------------------------------------------------------------

class TestPlainConversation:
    MESSAGES = [{"role": "user", "content": "In one short sentence, what is the capital of France?"}]

    async def test_ar_and_mtp_produce_identical_content(self):
        ar = await _call(self.MESSAGES, mode="ar")
        mtp = await _call(self.MESSAGES, mode="mtp", depth=3)

        ar_text = ar["choices"][0]["message"]["content"]
        mtp_text = mtp["choices"][0]["message"]["content"]

        _assert_mtp_actually_engaged(mtp, expected_depth=3)
        assert ar_text == mtp_text, (ar_text, mtp_text)
        assert ar["choices"][0]["finish_reason"] == mtp["choices"][0]["finish_reason"]


# ---------------------------------------------------------------------------
# Native tool calls
# ---------------------------------------------------------------------------

_WEATHER_TOOL = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a location.",
        "parameters": {
            "type": "object",
            "properties": {"location": {"type": "string", "description": "City name"}},
            "required": ["location"],
        },
    },
}]


class TestNativeToolCalls:
    MESSAGES = [{"role": "user", "content": "What's the weather like in Boston right now? Use the tool."}]

    async def test_ar_and_mtp_produce_the_same_tool_call(self):
        ar = await _call(self.MESSAGES, tools=_WEATHER_TOOL, mode="ar")
        mtp = await _call(self.MESSAGES, tools=_WEATHER_TOOL, mode="mtp", depth=3)

        ar_msg = ar["choices"][0]["message"]
        mtp_msg = mtp["choices"][0]["message"]

        _assert_mtp_actually_engaged(mtp, expected_depth=3)
        assert ar["choices"][0]["finish_reason"] == "tool_calls"
        assert mtp["choices"][0]["finish_reason"] == "tool_calls"

        ar_call = ar_msg["tool_calls"][0]["function"]
        mtp_call = mtp_msg["tool_calls"][0]["function"]
        assert ar_call["name"] == mtp_call["name"] == "get_weather"
        assert json.loads(ar_call["arguments"]) == json.loads(mtp_call["arguments"])

        _assert_no_raw_tool_markup(ar_msg.get("content"))
        _assert_no_raw_tool_markup(mtp_msg.get("content"))


# ---------------------------------------------------------------------------
# Tool follow-up rounds
# ---------------------------------------------------------------------------

class TestToolFollowUp:
    def _messages(self):
        return [
            {"role": "user", "content": "What's the weather like in Boston right now? Use the tool."},
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_fc0b2436", "type": "function",
                "function": {"name": "get_weather", "arguments": '{"location":"Boston"}'},
            }]},
            {"role": "tool", "tool_call_id": "call_fc0b2436", "content": "62F, partly cloudy, wind 8mph NW"},
        ]

    async def test_ar_and_mtp_produce_identical_final_answer(self):
        ar = await _call(self._messages(), tools=_WEATHER_TOOL, mode="ar")
        mtp = await _call(self._messages(), tools=_WEATHER_TOOL, mode="mtp", depth=3)

        ar_text = ar["choices"][0]["message"]["content"]
        mtp_text = mtp["choices"][0]["message"]["content"]

        _assert_mtp_actually_engaged(mtp, expected_depth=3)
        assert ar["choices"][0]["message"].get("tool_calls") is None
        assert mtp["choices"][0]["message"].get("tool_calls") is None
        assert ar_text == mtp_text, (ar_text, mtp_text)
        _assert_no_raw_tool_markup(mtp_text)


# ---------------------------------------------------------------------------
# Streaming assembly
# ---------------------------------------------------------------------------

class TestStreamingAssembly:
    MESSAGES = [{"role": "user", "content": "In one short sentence, name the largest planet in our solar system."}]

    def _assemble(self, chunks):
        text = ""
        finish_reason = None
        for c in chunks:
            choice = (c.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            text += delta.get("content") or ""
            finish_reason = choice.get("finish_reason") or finish_reason
        return text, finish_reason

    async def test_streamed_assembly_matches_non_streamed_for_both_modes(self):
        for mode, depth in (("ar", 0), ("mtp", 3)):
            non_stream = await _call(self.MESSAGES, mode=mode, depth=depth, stream=False)
            stream_chunks = await _call(self.MESSAGES, mode=mode, depth=depth, stream=True)

            non_stream_text = non_stream["choices"][0]["message"]["content"]
            streamed_text, finish_reason = self._assemble(stream_chunks)

            assert streamed_text == non_stream_text, (mode, streamed_text, non_stream_text)
            assert finish_reason == non_stream["choices"][0]["finish_reason"]
            _assert_no_raw_tool_markup(streamed_text)

    async def test_ar_and_mtp_streamed_text_match(self):
        ar_chunks = await _call(self.MESSAGES, mode="ar", stream=True)
        mtp_chunks = await _call(self.MESSAGES, mode="mtp", depth=3, stream=True)
        ar_text, _ = self._assemble(ar_chunks)
        mtp_text, _ = self._assemble(mtp_chunks)
        assert ar_text == mtp_text, (ar_text, mtp_text)


# ---------------------------------------------------------------------------
# Long context
# ---------------------------------------------------------------------------

class TestLongContext:
    def _messages(self):
        filler = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": f"Turn {i}: just checking in, nothing important — message padding for a long-context test."}
            for i in range(40)
        ]
        return filler + [
            {"role": "user", "content": "Given everything above, in one short sentence: what is 2 + 2?"}
        ]

    async def test_ar_and_mtp_agree_at_longer_context(self):
        messages = self._messages()
        ar = await _call(messages, mode="ar", max_tokens=40)
        mtp = await _call(messages, mode="mtp", depth=3, max_tokens=40)

        assert ar["usage"]["prompt_tokens"] > 300, "context wasn't actually long"
        _assert_mtp_actually_engaged(mtp, expected_depth=3)

        ar_text = ar["choices"][0]["message"]["content"]
        mtp_text = mtp["choices"][0]["message"]["content"]
        assert ar_text == mtp_text, (ar_text, mtp_text)


# ---------------------------------------------------------------------------
# The complete 2026-09-16 morning correction/repetition sequence
# ---------------------------------------------------------------------------

class TestMorningSequenceReplay:
    """Not a check that Sara stops repeating herself under MTP — that's the
    harness/prompt fix (Phase 2-4), unrelated to generation mode. This is
    narrower: replayed as real multi-turn history, does MTP produce the
    same output AR does, and does it stay coherent (no raw tool markup, no
    truncated/garbled text) on the actual sequence that triggered this plan.
    """

    def _turns(self):
        import pathlib
        path = pathlib.Path(__file__).parent / "replay" / "fixtures" / "2026_09_16" / "turns.json"
        return json.loads(path.read_text())

    def _messages_through(self, turns, upto_index):
        msgs = []
        for t in turns[:upto_index]:
            msgs.append({"role": "user", "content": t["user_text"]})
            msgs.append({"role": "assistant", "content": t["observed_assistant_text"]})
        msgs.append({"role": "user", "content": turns[upto_index]["user_text"]})
        return msgs

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "REPRODUCED 2026-09-16 against the live server (build reports "
            "native_draft_head + exact_speculative_sampling, default_generation_mode=ar). "
            "At this exact 6-turn history AR and MTP diverge after 'enjoy the ': AR says "
            "'...enjoy the walk and that zero-cal energy drink.' and stops; MTP says "
            "'...enjoy the win.' and continues into a fresh RingCentral-timing sentence "
            "not present in AR's output. Reproduced twice, deterministically, on both "
            "sides (AR==AR, MTP==MTP, AR!=MTP) — not sampling noise. All 7 shorter/"
            "simpler scenarios in this file (plain conversation, native tool call, tool "
            "follow-up, streaming, a synthetic long-context prompt, and turn 5 of this "
            "same conversation) match exactly, so this is specific to this history shape, "
            "not a blanket MTP failure. This is exactly gotcha_mtplx_mtp_derails_"
            "qwen38_27b.md's finding, still open on the current build — the reason "
            "LOCAL_GENERATION_MODE defaults to ar and MUST NOT be flipped until this "
            "turns green."
        ),
    )
    async def test_final_correction_turn_matches_between_modes(self):
        """Turn 6: 'Shoulders all good that pain I had has gone away' — the
        turn whose observed reply re-asked an already-answered question."""
        turns = self._turns()
        messages = self._messages_through(turns, 6)

        ar = await _call(messages, mode="ar", max_tokens=200)
        mtp = await _call(messages, mode="mtp", depth=3, max_tokens=200)

        ar_text = ar["choices"][0]["message"]["content"]
        mtp_text = mtp["choices"][0]["message"]["content"]

        _assert_mtp_actually_engaged(mtp, expected_depth=3)
        _assert_no_raw_tool_markup(ar_text)
        _assert_no_raw_tool_markup(mtp_text)
        assert ar_text == mtp_text, (ar_text, mtp_text)

    async def test_correction_turn_matches_between_modes(self):
        """Turn 5: 'It was 4 sets of 135x6' — the numeric correction turn."""
        turns = self._turns()
        messages = self._messages_through(turns, 5)

        ar = await _call(messages, mode="ar", max_tokens=200)
        mtp = await _call(messages, mode="mtp", depth=3, max_tokens=200)

        ar_text = ar["choices"][0]["message"]["content"]
        mtp_text = mtp["choices"][0]["message"]["content"]

        _assert_mtp_actually_engaged(mtp, expected_depth=3)
        assert ar_text == mtp_text, (ar_text, mtp_text)
