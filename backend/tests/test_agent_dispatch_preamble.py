"""Tests for the preamble-detection guard in agent_dispatch.

Motivation: a research task once produced a note whose body ended with
"Now I have enough research to build the comprehensive document. Let me
create it:" — the dispatch loop accepted the LLM's announcement as the
final deliverable. `_looks_like_preamble` is the cheap regex-y guard the
loop now consults before exiting on a text-only response.
"""

from __future__ import annotations

import pytest

from app.services.agent_dispatch import _looks_like_preamble


# ── Should be flagged as preamble ─────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "Now I have enough research to build the comprehensive document. Let me create it:",
        "Let me now synthesize the findings.",
        "I have enough information. I'll now write the full report.",
        "Here is the document:",
        "Okay, now I can create the morning routine document.",
        "Now I will draft the deliverable.",
        # Trailing colon alone is enough — classic announce-and-stop tell.
        "Plan complete. Drafting now:",
        # Markdown emphasis shouldn't hide the colon.
        "**Now writing the final document:**",
    ],
)
def test_preamble_strings_are_flagged(text: str) -> None:
    assert _looks_like_preamble(text) is True


# ── Should NOT be flagged ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Task completed successfully. The morning routine is saved at /home/sara/sandbox/routine.md.",
        "I checked the calendar; there are three meetings tomorrow.",
        "Final answer: 42.",  # Trailing punctuation isn't a colon.
        "The optimal wake time is 6:00 AM based on circadian science.",  # Colon mid-sentence is fine.
    ],
)
def test_completed_responses_are_not_flagged(text: str) -> None:
    assert _looks_like_preamble(text) is False
