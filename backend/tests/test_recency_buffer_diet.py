"""Recency floor sizing (harness rebuild Phase 6).

At 1,200 tokens and 400-char snippets this was the single largest section of
the 2026-09-11 live context — 3,841 chars, 26% of the whole block — and most
of what it carried was already present, verbatim and untruncated, in
`conversation_history` a few hundred tokens further down the same prompt.

Its real job is narrow: knowing what you just tried when those turns are NOT
in this conversation's history (a session boundary, a crashed client, a turn
started on iOS and answered on the web).
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import recency_buffer as rb


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeDB:
    """Captures the bound parameters so the conversation exclusion is
    checkable without a database."""

    def __init__(self, rows):
        self.rows = rows
        self.params = None

    async def execute(self, stmt, params=None):
        self.params = params
        self.sql = str(stmt)
        return FakeResult(self.rows)


def _turn(role, content, source=None):
    return SimpleNamespace(
        role=role, content=content, source=source,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
class TestRecencyFloor:
    async def test_the_conversation_being_answered_is_excluded(self):
        db = FakeDB([_turn("user", "hello there, a real message")])
        await rb.build_recency_floor(db, "u1", exclude_conversation_id="conv-1")
        assert db.params["cid"] == "conv-1"
        assert "IS DISTINCT FROM" in db.sql

    async def test_no_conversation_id_excludes_nothing(self):
        db = FakeDB([_turn("user", "hello there, a real message")])
        await rb.build_recency_floor(db, "u1")
        assert db.params["cid"] is None

    async def test_it_fits_the_token_budget(self):
        db = FakeDB([_turn("assistant", "z" * 4000) for _ in range(rb.RECENCY_MAX_TURNS)])
        out = await rb.build_recency_floor(db, "u1")
        # 450 tokens x 4 chars, plus the header and a little slack.
        assert len(out) <= rb.RECENCY_MAX_TOKENS * 4 + 200, len(out)

    async def test_a_single_huge_turn_still_renders(self):
        """The budget check runs before appending; without the `lines and`
        guard, one over-budget turn would produce an empty section."""
        db = FakeDB([_turn("assistant", "z" * 40_000)])
        out = await rb.build_recency_floor(db, "u1")
        assert out and "Sara" in out

    async def test_turns_are_clipped_and_marked(self):
        db = FakeDB([_turn("user", "y" * 1000)])
        out = await rb.build_recency_floor(db, "u1")
        assert "…" in out
        # +1 for the "y" in "recency" in the header.
        assert out.count("y") == rb.RECENCY_SNIPPET_CHARS + 1

    async def test_errored_turns_stay_visible(self):
        db = FakeDB([_turn("assistant", "that did not work at all, sorry", source="chat_error")])
        out = await rb.build_recency_floor(db, "u1")
        assert "[errored]" in out

    async def test_no_rows_renders_nothing(self):
        assert await rb.build_recency_floor(FakeDB([]), "u1") is None

    async def test_oldest_first(self):
        db = FakeDB([
            _turn("user", "this is the newest message in the buffer"),
            _turn("user", "this is the oldest message in the buffer"),
        ])
        out = await rb.build_recency_floor(db, "u1")
        assert out.index("oldest") < out.index("newest")


class TestRepeatNote:
    def test_it_is_a_nudge_not_a_transcript(self):
        note = rb.repeat_note({
            "minutes_ago": 180,
            "prior_question": "q" * 500,
            "prior_answer": "a" * 900,
            "similarity": 0.99,
        })
        # 660 chars of the 2026-09-11 prompt went here, most of it a verbatim
        # re-presentation of the answer Sara was being told not to repeat.
        assert len(note) < 600, len(note)
        assert note.count("a") <= 200

    def test_it_says_when(self):
        note = rb.repeat_note({
            "minutes_ago": 3, "prior_question": "what's for dinner",
            "prior_answer": None, "similarity": 0.95,
        })
        assert "3 min ago" in note
