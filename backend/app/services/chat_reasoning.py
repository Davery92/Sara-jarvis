"""Discard inline reasoning before streaming, tool parsing, or storage.

Qwen normally uses reasoning_content, which chat ignores. This also handles
servers returning <think> in content, including arbitrarily split tags and
unfinished reasoning. Only a possible tag suffix is buffered, not reasoning.
"""


class ThinkingContentFilter:
    def __init__(self):
        self._pending = ""
        self._thinking = False

    def feed(self, text: str) -> str:
        self._pending += text
        output = []
        while self._pending:
            marker = "</think>" if self._thinking else "<think>"
            index = self._pending.find(marker)
            if index >= 0:
                if not self._thinking:
                    output.append(self._pending[:index])
                self._pending = self._pending[index + len(marker):]
                self._thinking = not self._thinking
                continue
            keep = 0
            for size in range(1, min(len(marker), len(self._pending) + 1)):
                if self._pending.endswith(marker[:size]):
                    keep = size
            resolved = self._pending[:-keep] if keep else self._pending
            if not self._thinking:
                output.append(resolved)
            self._pending = self._pending[-keep:] if keep else ""
            break
        return "".join(output)

    def finish(self) -> str:
        # A lone '<' can be prose. Other partial tags/unfinished reasoning
        # must not become part of the answer when generation is cut short.
        tail = self._pending if not self._thinking and self._pending == "<" else ""
        self._pending = ""
        return tail


def strip_thinking_content(text: str) -> str:
    parser = ThinkingContentFilter()
    return parser.feed(text) + parser.finish()


# Harness/thinking/personality plan, Phase 1. `_finalize_response_content`
# (main_simple.py) already guarantees the STORED/RETURNED final answer is
# clean — it runs `strip_tool_markup` before persistence. Nothing guaranteed
# the LIVE STREAM was: `_stream_response` calls `emit_text_chunk` per delta,
# as chunks arrive, before that final cleanup ever runs. Its old holdback
# check (a regex for an OPENING `<tool_call`/`<think` tag, plus a bare
# `.endswith('<')` guess) let two things through untouched: a bare
# `</tool_call>` closing tag with no opener in the stream (exactly what
# MTPLX sends when a model with zero tools declared still tries to call one
# — reproduced live, Stage D case p_repetition_check_2, 2/2 trials), and any
# `[MTPLX: ...]` / `[LLAMA.CPP: ...]` / `[SERVER: ...]` provider advisory,
# which never starts with `<` at all. See
# tests/test_chat_thinking.py::test_stream_never_emits_provider_scaffolding_or_bare_closing_tags
# for the reproduction.
_TAG_MARKERS = ("<tool_call", "</tool_call>", "<think", "</think>")
_BRACKET_MARKERS = ("[MTPLX:", "[LLAMA.CPP:", "[SERVER:")
_ALL_MARKERS = _TAG_MARKERS + _BRACKET_MARKERS
_MAX_MARKER_LEN = max(len(m) for m in _ALL_MARKERS)


class StreamScaffoldGuard:
    """Holds back a live-streamed chunk until it is provably not the start
    of a tag marker or a provider-scaffolding bracket — never emits a
    partial marker, regardless of where the provider happens to split its
    SSE chunks.

    Two different holdback policies, because they mean different things:
    - A tag marker (`<tool_call`, `</tool_call>`, `<think`, `</think>`)
      means the rest of this delta's text is XML-dialect tool-call/thinking
      markup, parsed as a whole once the stream ends — so once one is seen,
      everything from that point is held back for the rest of the turn
      (matches the pre-existing behavior for `<tool_call`, which relied on
      the caller never calling `feed` again with fresh "safe" content after
      a match; this class makes that explicit instead of implicit).
    - A bracket marker (`[MTPLX: ...]`) is a one-off inference-server
      advisory, not a format change for the rest of the response: held back
      only until its closing `]` (or, if a stream ends without one, for
      good — see `finish()`), then normal emission resumes.

    `feed(text) -> str` returns what is safe to emit now; call `finish()`
    once the stream ends to get anything left over that turned out not to
    be a real marker after all (e.g. a lone trailing `[` that was never
    followed by `MTPLX:`).
    """

    def __init__(self):
        self._pending = ""
        self._suppressed_for_turn = False  # a tag marker fired; never resumes
        self._in_bracket = False  # inside a matched [MTPLX: ...] span

    def feed(self, text: str) -> str:
        self._pending += text
        if self._suppressed_for_turn:
            return ""

        output = []
        while self._pending:
            if self._in_bracket:
                close = self._pending.find("]")
                if close < 0:
                    return "".join(output)  # still inside the advisory; hold everything
                self._pending = self._pending[close + 1:]
                self._in_bracket = False
                continue

            earliest_match = None
            matched_marker = None
            for marker in _ALL_MARKERS:
                pos = self._pending.find(marker)
                if pos >= 0 and (earliest_match is None or pos < earliest_match):
                    earliest_match = pos
                    matched_marker = marker

            if earliest_match is not None:
                output.append(self._pending[:earliest_match])
                if matched_marker in _BRACKET_MARKERS:
                    self._pending = self._pending[earliest_match + len(matched_marker):]
                    self._in_bracket = True
                    continue
                # A tag marker: suppress everything from here on, this turn.
                self._pending = ""
                self._suppressed_for_turn = True
                return "".join(output)

            # No full marker yet — check whether the tail could still grow
            # into one, the same longest-suffix-is-a-prefix technique
            # ThinkingContentFilter uses for <think>/</think>.
            keep = 0
            for marker in _ALL_MARKERS:
                for size in range(1, min(len(marker), len(self._pending)) + 1):
                    if self._pending.endswith(marker[:size]):
                        keep = max(keep, size)
            safe_len = len(self._pending) - keep
            if safe_len > 0:
                output.append(self._pending[:safe_len])
            self._pending = self._pending[len(self._pending) - keep:] if keep else ""
            break
        return "".join(output)

    def finish(self) -> str:
        """End of stream (also called on truncation, cancellation, and
        error — any path that stops feeding chunks). Anything still in
        `self._pending` at this point was put there BY `feed`'s
        longest-suffix-match holdback: it is, by construction, a genuine
        non-empty prefix of some marker in `_ALL_MARKERS` — e.g. `<tool_`,
        `</tool_ca`, `[MTPLX`. Releasing it unconditionally leaked exactly
        that malformed control-markup fragment to the user (confirmed:
        `<tool_`, `</tool_ca`, `[MTPLX`). A matched bracket without its `]`
        is likewise never released — an unterminated advisory is exactly
        the malformed case this guard exists to hold back.

        The one exception, matching `ThinkingContentFilter.finish()`'s
        existing convention: a single bare `<` or `[` is common, legitimate
        prose (`5 < 10`, `see [1]`) that only happens to be a length-1
        prefix of a marker. Anything longer is discarded — it cannot be
        innocent prose and a real marker prefix at once."""
        if self._suppressed_for_turn or self._in_bracket:
            tail = ""
        elif len(self._pending) <= 1:
            tail = self._pending
        else:
            tail = ""
        self._pending = ""
        return tail
