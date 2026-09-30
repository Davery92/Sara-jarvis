"""Harness/thinking/personality plan, Phase 1: parse_glm45_tool_calls used
to log up to 100 raw characters of extracted <think> reasoning at DEBUG
level (app/core/text_utils.py). Locks in the fix: the function's return
value is unaffected (reasoning is still stripped from the content), and the
log line reports a length only, never content.
"""
import logging

from app.core.text_utils import parse_glm45_tool_calls


def test_reasoning_is_stripped_from_content_and_never_logged(caplog):
    # parse_glm45_tool_calls only reaches the <think> stripping code when a
    # <tool_call> block is also present (an early return otherwise) — see
    # its own `if not matches: return content, []`.
    raw = (
        "<think>the user's private health detail is X</think>"
        "Here is the answer.<tool_call>notes_search <arg_key>query</arg_key>"
        "<arg_value>test</arg_value></tool_call>"
    )
    with caplog.at_level(logging.DEBUG):
        cleaned, tool_calls = parse_glm45_tool_calls(raw)

    assert "<think>" not in cleaned
    assert "Here is the answer." in cleaned
    assert len(tool_calls) == 1
    for record in caplog.records:
        assert "private health detail" not in record.getMessage()
        assert "the user's" not in record.getMessage()
    assert any("Model reasoning present and stripped" in r.getMessage() for r in caplog.records)


def test_no_reasoning_log_when_no_think_tag():
    cleaned, tool_calls = parse_glm45_tool_calls("Just a plain answer, no tool call.")
    assert cleaned == "Just a plain answer, no tool call."
    assert tool_calls == []
