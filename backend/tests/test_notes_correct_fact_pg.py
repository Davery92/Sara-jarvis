"""Fact correction against a real database — reliable-assistant plan Phase E.

The required workflow, from the plan: *"capture two people, correct one
employer naturally, retain unrelated details, open a new conversation, retrieve
the corrected current employer with accurate history. Repeated correction must
not fork notes or create contradictory current facts."*

What this replaces is measured, not assumed. The 2026-09-27 convention run's
appended-correction strategy left the stored note as

    title    | Priya Raghavan — Globex
    content  | Priya Raghavan is at Globex. …
             | Correction 2026-09-27: Priya Raghavan is now at Initech, not Globex.

— current truth asserted twice, contradictorily, with the stale one in the
title. Every assertion below checks the stored row, not the tool's own message.
"""
import os
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _pg_available() -> bool:
    return os.getenv("DATABASE_URL", "").startswith("postgresql")


requires_pg = pytest.mark.skipif(
    not _pg_available(),
    reason="needs the disposable PostgreSQL database (run inside the test container)",
)


@pytest.fixture
def pg():
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def user_id(pg):
    uid = str(uuid.uuid4())
    pg.execute(text(
        "INSERT INTO app_user (id, email, password_hash) VALUES (:id, :email, 'x')"
    ), {"id": uid, "email": f"correct-fact-{uid}@test.invalid"})
    pg.commit()
    yield uid
    pg.rollback()
    pg.execute(text("DELETE FROM note_connection WHERE user_id = :u"), {"u": uid})
    pg.execute(text("DELETE FROM note WHERE user_id = :u"), {"u": uid})
    pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": uid})
    pg.commit()


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    async def _fake_embedding(text_value):
        return [0.01] * 1024
    monkeypatch.setattr("app.tools.notes.get_embedding", _fake_embedding)


async def create_note(user_id, title, content):
    from app.tools.notes import NotesCreateTool
    result = await NotesCreateTool().execute(
        user_id=user_id, title=title, content=content)
    assert result.success, result.message
    return result.data["note_id"]


async def correct(user_id, note_id, old, new, kind="changed"):
    from app.tools.notes import NotesCorrectFactTool
    return await NotesCorrectFactTool().execute(
        user_id=user_id, note_id=note_id, old_value=old, new_value=new, kind=kind)


def stored(pg, note_id):
    pg.rollback()  # see the other session's committed state
    row = pg.execute(text(
        "SELECT title, content, updated_at, created_at FROM note WHERE id = :i"
    ), {"i": note_id}).fetchone()
    return row


@requires_pg
class TestTheRequiredWorkflow:
    @pytest.mark.asyncio
    async def test_capture_two_people_correct_one_employer_keep_the_rest(self, pg, user_id):
        priya = await create_note(
            user_id, "Priya Raghavan — Globex",
            "Priya Raghavan is at Globex. She leads their migration off Oracle "
            "and runs the whole data platform there.\n"
            "Wants a follow-up about pricing next week.",
        )
        dana = await create_note(
            user_id, "Dana Whitfield — Acme",
            "Dana Whitfield runs Acme's platform team. Email her after the 10th.",
        )

        result = await correct(user_id, priya, "Globex", "Initech")
        assert result.success, result.message

        row = stored(pg, priya)
        # Current truth, everywhere it is asserted — including the title, which
        # the appended-correction strategy left saying Globex forever.
        assert "Globex" not in row.title
        assert "Initech" in row.title
        body = row.content.split("## History")[0]
        assert "Globex" not in body, f"stale fact still asserted as current: {body!r}"
        assert "Initech" in body

        # Unrelated details on the same note are untouched.
        assert "migration off Oracle" in row.content
        assert "runs the whole data platform" in row.content
        assert "follow-up about pricing next week" in row.content

        # Provenance kept, not discarded.
        assert "## History" in row.content
        assert 'was "Globex"' in row.content
        assert 'now "Initech"' in row.content

        # One note, not two — and the other person's note is untouched.
        count = pg.execute(text("SELECT count(*) FROM note WHERE user_id = :u"),
                           {"u": user_id}).scalar()
        assert count == 2
        dana_row = stored(pg, dana)
        assert dana_row.content == "Dana Whitfield runs Acme's platform team. Email her after the 10th."

    @pytest.mark.asyncio
    async def test_a_repeated_correction_does_not_fork_or_contradict(self, pg, user_id):
        note_id = await create_note(
            user_id, "Priya Raghavan — Globex", "Priya Raghavan is at Globex.")

        assert (await correct(user_id, note_id, "Globex", "Initech")).success
        second = await correct(user_id, note_id, "Initech", "Contoso")
        assert second.success, second.message

        row = stored(pg, note_id)
        body = row.content.split("## History")[0]
        # Exactly one current employer, and it is the latest one.
        assert "Contoso" in body
        assert "Initech" not in body
        assert "Globex" not in body
        assert "Contoso" in row.title
        # Both steps are in the history, in order.
        history = row.content.split("## History")[1]
        assert history.index('was "Globex"') < history.index('was "Initech"')
        assert pg.execute(text("SELECT count(*) FROM note WHERE user_id = :u"),
                          {"u": user_id}).scalar() == 1

    @pytest.mark.asyncio
    async def test_a_correction_is_visible_to_a_fresh_read(self, pg, user_id):
        """A new conversation reads the note through the ordinary read path;
        what matters is that the stored row it reads no longer states the stale
        fact as current, so no interpretation of a correction line is needed."""
        from app.tools.notes import NotesListTool

        note_id = await create_note(
            user_id, "Priya Raghavan — Globex", "Priya Raghavan is at Globex.")
        assert (await correct(user_id, note_id, "Globex", "Initech")).success

        listed = await NotesListTool().execute(user_id=user_id, limit=10)
        assert listed.success, listed.message
        titles = " ".join(n.get("title") or "" for n in (listed.data or {}).get("notes", []))
        assert "Initech" in titles
        assert "Globex" not in titles


@requires_pg
class TestHistoryIsNotFalsified:
    @pytest.mark.asyncio
    async def test_a_dated_line_keeps_its_original_wording(self, pg, user_id):
        """Plan E: "Priya moved companies" should not falsify the old meeting
        record. A line that opens with a date is a record of what happened
        then, and stays accurate."""
        note_id = await create_note(
            user_id, "Priya Raghavan — Globex",
            "Priya Raghavan is at Globex, running the data platform.\n"
            "2026-09-20: met Priya at the Globex booth, talked Oracle migration.",
        )
        result = await correct(user_id, note_id, "Globex", "Initech")
        assert result.success, result.message
        assert result.data["historical_left"] == 1

        row = stored(pg, note_id)
        assert "2026-09-20: met Priya at the Globex booth" in row.content
        current = row.content.split("2026-09-20")[0]
        assert "Globex" not in current
        assert "Initech" in current

    @pytest.mark.asyncio
    async def test_a_value_only_in_history_is_not_a_current_fact_to_correct(self, pg, user_id):
        note_id = await create_note(
            user_id, "Priya Raghavan",
            "Priya Raghavan runs the data platform.\n"
            "2026-09-20: met Priya at the Globex booth.",
        )
        result = await correct(user_id, note_id, "Globex", "Initech")
        assert result.success is False
        assert "dated history" in result.message
        row = stored(pg, note_id)
        assert row.content.count("Globex") == 1
        assert row.updated_at == row.created_at or "Initech" not in row.content


@requires_pg
class TestItRefusesRatherThanGuess:
    @pytest.mark.asyncio
    async def test_a_value_that_is_not_in_the_note_changes_nothing(self, pg, user_id):
        note_id = await create_note(user_id, "Dana Whitfield", "Dana runs Acme's platform team.")
        before = stored(pg, note_id).content
        result = await correct(user_id, note_id, "Globex", "Initech")
        assert result.success is False
        assert "Didn't find" in result.message
        assert stored(pg, note_id).content == before

    @pytest.mark.asyncio
    async def test_another_users_note_is_not_touched(self, pg, user_id):
        other = str(uuid.uuid4())
        pg.execute(text(
            "INSERT INTO app_user (id, email, password_hash) VALUES (:id, :email, 'x')"
        ), {"id": other, "email": f"other-{other}@test.invalid"})
        pg.commit()
        try:
            note_id = await create_note(other, "Theirs — Globex", "Someone else at Globex.")
            result = await correct(user_id, note_id, "Globex", "Initech")
            assert result.success is False
            assert "not found" in result.message.lower()
            assert "Globex" in stored(pg, note_id).content
        finally:
            pg.rollback()
            pg.execute(text("DELETE FROM note_connection WHERE user_id = :u"), {"u": other})
            pg.execute(text("DELETE FROM note WHERE user_id = :u"), {"u": other})
            pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": other})
            pg.commit()

    @pytest.mark.asyncio
    async def test_a_no_op_correction_is_refused(self, pg, user_id):
        note_id = await create_note(user_id, "Priya — Initech", "Priya is at Initech.")
        result = await correct(user_id, note_id, "Initech", "initech")
        assert result.success is False
        assert "already says" in result.message


class TestSubstitutionUnit:
    """The pure substitution, so its edge cases are pinned without a database."""

    def test_it_replaces_every_current_mention(self):
        from app.tools.notes import substitute_current_fact
        out, replaced, historical = substitute_current_fact(
            "She is at Globex. Globex is migrating off Oracle.", "Globex", "Initech")
        assert replaced == 2
        assert historical == 0
        assert "Globex" not in out

    def test_it_is_case_insensitive_but_writes_the_given_casing(self):
        from app.tools.notes import substitute_current_fact
        out, replaced, _ = substitute_current_fact("She is at globex.", "Globex", "Initech")
        assert replaced == 1
        assert "Initech" in out

    def test_it_leaves_history_alone(self):
        from app.tools.notes import substitute_current_fact
        out, replaced, historical = substitute_current_fact(
            "At Globex.\n\n## History\n- 2026-01-01: joined Globex.", "Globex", "Initech")
        assert replaced == 1
        assert historical == 1
        assert "joined Globex" in out

    @pytest.mark.parametrize("line", [
        "2026-09-20: met at the Globex booth",
        "- 2026-09-20: met at the Globex booth",
        "9/20: met at the Globex booth",
        "Sep 20 — met at the Globex booth (Globex)",
    ])
    def test_dated_line_shapes_are_recognized(self, line):
        from app.tools.notes import substitute_current_fact
        out, replaced, historical = substitute_current_fact(line, "Globex", "Initech")
        assert replaced == 0
        assert historical >= 1
        assert out == line

    def test_appending_history_creates_the_section_once(self):
        from app.tools.notes import append_history_line
        once = append_history_line("Body.", "- a")
        twice = append_history_line(once, "- b")
        assert twice.count("## History") == 1
        assert twice.index("- a") < twice.index("- b")
