"""Tests for app.services.acs.error_taxonomy."""

from __future__ import annotations

import pytest

from app.services.acs.error_taxonomy import (
    ALL_CATEGORIES,
    CLIENT_BUG,
    DONE_DEADLOCK,
    FORCE_KILLED,
    LLM_BAD_REQUEST,
    LLM_CONTEXT_OVERFLOW,
    LLM_DISCONNECT_ENDPOINT_DOWN,
    LLM_DISCONNECT_MID_REQUEST,
    LLM_EMPTY_RESPONSE,
    LLM_PARSE_ERROR,
    LLM_SERVER_ERROR,
    LLM_TIMEOUT,
    ORPHANED,
    STALE_SESSION,
    STUCK_PAUSING,
    TASK_CRASH,
    TASK_SOFT_TIMEOUT,
    UNKNOWN,
    classify_from_text,
    classify_termination,
)


# ── classify_from_text — observed signatures from the live DB ─────────


@pytest.mark.parametrize(
    "text,expected",
    [
        # The dominant signatures from the 49 populated error_log rows
        ("RemoteProtocolError: Server disconnected without sending a response.", LLM_DISCONNECT_MID_REQUEST),
        ("Server disconnected without sending a response.", LLM_DISCONNECT_MID_REQUEST),
        ("3 consecutive errors: Server disconnected without sending a response.", LLM_DISCONNECT_MID_REQUEST),
        ("ReadTimeout: <no message>", LLM_TIMEOUT),
        ("All connection attempts failed", LLM_DISCONNECT_ENDPOINT_DOWN),
        ("ConnectError: [Errno 111] Connection refused", LLM_DISCONNECT_ENDPOINT_DOWN),
        ("Empty LLM response on first turn", LLM_EMPTY_RESPONSE),
        ("LLM context overflow after compaction retry", LLM_CONTEXT_OVERFLOW),
        ("LLMContextOverflowError: too many tokens", LLM_CONTEXT_OVERFLOW),
        # HTTP status codes
        ("Client error '400 Bad Request' for url 'http://10.185.1.8:8686/v1/chat/completions'", LLM_BAD_REQUEST),
        # "LLM returned 400" in any form is the literal prefix the ACS LLM
        # client uses ONLY when re-raising a context-overflow — see the
        # comment in error_taxonomy._PATTERNS.
        ("LLM returned 400: malformed", LLM_CONTEXT_OVERFLOW),
        ("Server error '500 Internal Server Error' for url 'http://10.185.1.8:8686/v1/chat/completions'", LLM_SERVER_ERROR),
        # Code bugs
        ("BackgroundLLMClient.chat_completion() got an unexpected keyword argument 'extra_body'", CLIENT_BUG),
        ("'Settings' object has no attribute 'proxmox_api_url'", CLIENT_BUG),
        ("can't subtract offset-naive and offset-aware datetimes", CLIENT_BUG),
        ("too many values to unpack (expected 2)", CLIENT_BUG),
        # Celery
        ("SoftTimeLimitExceeded()", TASK_SOFT_TIMEOUT),
    ],
)
def test_classify_from_text_known_signatures(text: str, expected: str) -> None:
    assert classify_from_text(text) == expected


def test_classify_from_text_empty_or_none() -> None:
    assert classify_from_text(None) is None
    assert classify_from_text("") is None
    assert classify_from_text("   ") is None


def test_classify_from_text_unmatched_falls_to_unknown() -> None:
    assert classify_from_text("something nobody could anticipate") == UNKNOWN


def test_classify_from_text_disconnect_priority() -> None:
    """Disconnect-mid-request must beat endpoint-down when both phrases appear.

    Some real messages mention 'disconnected' + connection-failed phrasing in
    the same string; we want the more specific 'mid-request' classification."""
    assert classify_from_text(
        "RemoteProtocolError: Server disconnected without sending a response (after retries)"
    ) == LLM_DISCONNECT_MID_REQUEST


# ── classify_termination — combined exc + end_reason resolution ───────


def test_benign_end_reasons_return_none() -> None:
    for reason in ("completed", "timeout", "manual", "conversation", "unknown_historical"):
        assert classify_termination(end_reason=reason) is None
        # Even with garbage error_text, benign end_reason wins.
        assert classify_termination(end_reason=reason, error_text="ReadTimeout") is None


def test_reaper_end_reasons_mirror() -> None:
    for reason, expected in [
        ("stale_session", STALE_SESSION),
        ("stuck_pausing", STUCK_PAUSING),
        ("orphaned", ORPHANED),
        ("done_deadlock", DONE_DEADLOCK),
        ("audit_ceiling", "audit_ceiling"),
        ("force_killed", FORCE_KILLED),
        ("task_crash", TASK_CRASH),
    ]:
        assert classify_termination(end_reason=reason) == expected


def test_error_with_text_classifies() -> None:
    cat = classify_termination(
        end_reason="error",
        error_text="RemoteProtocolError: Server disconnected without sending a response.",
    )
    assert cat == LLM_DISCONNECT_MID_REQUEST


def test_error_with_no_text_falls_to_unknown() -> None:
    assert classify_termination(end_reason="error") == UNKNOWN


def test_exception_class_fast_path() -> None:
    """Exception class should classify even if str(exc) is empty."""

    class FakeReadTimeout(Exception):
        pass

    # Rename so type(exc).__name__ matches what httpx raises in production.
    FakeReadTimeout.__name__ = "ReadTimeout"
    cat = classify_termination(exc=FakeReadTimeout(), end_reason="error")
    assert cat == LLM_TIMEOUT


def test_exception_with_message_falls_through_to_text() -> None:
    """Unknown exception class but recognizable message text still classifies."""

    class WeirdError(Exception):
        pass

    cat = classify_termination(exc=WeirdError("Empty LLM response on first turn"), end_reason="error")
    assert cat == LLM_EMPTY_RESPONSE


def test_no_inputs_returns_none() -> None:
    assert classify_termination() is None


def test_all_returned_values_are_in_known_set() -> None:
    """Every category the classifier emits must be in ALL_CATEGORIES.

    Catches drift: someone adding a new pattern but forgetting to register it.
    """
    samples = [
        "RemoteProtocolError: ...", "ReadTimeout", "All connection attempts failed",
        "Server error '503' for url 'x'", "Client error '422' for url 'x'",
        "Empty LLM response", "LLM context overflow", "JSONDecodeError: x",
        "SoftTimeLimitExceeded()", "AttributeError: 'X' object has no attribute 'y'",
        "ConnectError: refused",
    ]
    for s in samples:
        cat = classify_from_text(s)
        assert cat in ALL_CATEGORIES, f"{s!r} -> {cat!r} not in ALL_CATEGORIES"


# ── parse_error coverage — JSON / tool-call malformations ─────────────


def test_parse_error_json_decode() -> None:
    assert classify_from_text("JSONDecodeError: Expecting value: line 1 column 1") == LLM_PARSE_ERROR


def test_parse_error_tool_call_malformed() -> None:
    assert classify_from_text("tool call response was malformed") == LLM_PARSE_ERROR


# ── Regression: LLMContextOverflowError prefix must beat generic 4xx ──


def test_context_overflow_marker_wins_over_4xx() -> None:
    """The ACS LLM client re-raises 400s caused by context overflow as
    `LLMContextOverflowError`. The more-specific marker must win the
    classifier race against the generic 4xx pattern, otherwise context-
    overflow rows get misclassified as bad_request and we lose visibility
    into the actual failure mode.
    """
    msg = (
        "LLMContextOverflowError: LLM returned 400: "
        "Client error '400 Bad Request' for url 'http://10.185.1.8:8686/v1/chat/completions' "
        "For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400"
    )
    assert classify_from_text(msg) == LLM_CONTEXT_OVERFLOW


def test_plain_4xx_without_overflow_marker_stays_bad_request() -> None:
    """Genuine non-overflow 400s should still classify as llm_bad_request."""
    msg = "Client error '400 Bad Request' for url 'http://example.com/v1/chat/completions'"
    from app.services.acs.error_taxonomy import LLM_BAD_REQUEST as _BR
    assert classify_from_text(msg) == _BR
