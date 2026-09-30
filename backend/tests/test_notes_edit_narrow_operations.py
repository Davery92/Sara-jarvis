"""Narrow single-item note edits and revision-checked writes (Sara repair
plan R02, evidence J03_trial2_TURN6_FALSE_DIAGNOSIS_CAUSES_REAL_DATA_LOSS,
and the 2026-09-25 review remediation of the first version of this fix).

The confirmed mechanism: `notes_edit` only ever supported whole-content
REPLACEMENT. A request like "remove the rain jacket but keep the other
items" forced the model to reconstruct the entire new content itself; when
its belief about the note's actual current content was wrong, the
reconstructed full content silently dropped an item the user never asked to
remove — real, permanent, unrequested data loss.

The FIRST fix (remove_text/append_text) closed the reproduced case but
still deleted the WHOLE LINE containing a match — wrong for an inline
comma-separated list or a phrase inside a paragraph, where the line also
carries unrelated text. This version removes exactly the matched span (see
`_remove_span`'s docstring for the three shapes it handles), and every
write path — including `content` full replacement, which remained
"unrestricted" in the first version — now goes through a conditional
UPDATE gated on the note's `updated_at` at read time, so a genuinely
concurrent edit is refused rather than silently lost.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.note import Note
from app.tools.notes import NotesEditTool, _remove_span

USER_A = "user-a"
USER_B = "user-b"


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Note.__table__.create(engine, checkfirst=True)
    return sessionmaker(bind=engine)


@pytest.fixture()
def db_session(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def tool(monkeypatch, session_factory):
    import app.tools.notes as mod

    def _fake_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    async def _fake_get_embedding(text):
        return [0.0] * 1024

    monkeypatch.setattr(mod, "get_db", _fake_get_db)
    monkeypatch.setattr(mod, "get_embedding", _fake_get_embedding)

    async def _noop_connections(*a, **kw):
        return None

    import app.services.note_connector as connector_mod
    monkeypatch.setattr(connector_mod, "process_note_connections_sync", _noop_connections, raising=False)

    return NotesEditTool()


def _note(db_session, user_id, content, title="Cedar packing"):
    n = Note(
        id=str(uuid.uuid4()), user_id=user_id, title=title, content=content,
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(n)
    db_session.commit()
    note_id = n.id
    revision = n.updated_at.isoformat()
    db_session.expunge(n)
    return note_id, revision


def _fetch(session_factory, note_id):
    session = session_factory()
    try:
        return session.query(Note).filter(Note.id == note_id).first()
    finally:
        session.close()


# ── _remove_span unit tests: the three cleanup shapes directly ──────────

class TestRemoveSpanShapes:
    def test_whole_line_list_item(self):
        content = "spare cable\ncharger\nnotebook\nrain jacket"
        new_content, err = _remove_span(content, "rain jacket")
        assert err is None
        assert new_content == "spare cable\ncharger\nnotebook"

    def test_inline_comma_list_middle_item(self):
        content = "Bring: spare cable, charger, notebook, rain jacket."
        new_content, err = _remove_span(content, "charger")
        assert err is None
        assert new_content == "Bring: spare cable, notebook, rain jacket."

    def test_inline_comma_list_last_item(self):
        content = "Bring: spare cable, charger, rain jacket"
        new_content, err = _remove_span(content, "rain jacket")
        assert err is None
        assert new_content == "Bring: spare cable, charger"

    def test_inline_comma_list_first_item(self):
        content = "rain jacket, spare cable, charger"
        new_content, err = _remove_span(content, "rain jacket")
        assert err is None
        assert new_content == "spare cable, charger"

    def test_paragraph_prose_removes_only_the_phrase(self):
        content = "Remember to grab the rain jacket before you leave for the trip tomorrow."
        new_content, err = _remove_span(content, "the rain jacket")
        assert err is None
        # Nothing else in the sentence is touched — only the matched phrase
        # and one collapsed double space are affected.
        assert "before you leave for the trip tomorrow" in new_content
        assert "rain jacket" not in new_content
        assert "  " not in new_content  # no leftover double space

    def test_does_not_match_inside_an_unrelated_word(self):
        """'cup' must not match inside 'cupcake' — a real risk of plain
        substring matching that whole-line deletion also had, just
        invisibly (it always over-deleted the whole line anyway)."""
        content = "cupcake recipe\nflour\nsugar"
        new_content, err = _remove_span(content, "cup")
        assert err == "not_found"
        assert new_content is None

    def test_repeated_match_is_ambiguous(self):
        content = "charger for phone\ncharger for laptop\nnotebook"
        new_content, err = _remove_span(content, "charger")
        assert new_content is None
        assert err is not None and err.startswith("ambiguous")

    def test_not_found(self):
        new_content, err = _remove_span("spare cable\ncharger", "rain jacket")
        assert new_content is None
        assert err == "not_found"

    def test_case_insensitive_match(self):
        new_content, err = _remove_span("Spare Cable\nCharger\nNotebook", "charger")
        assert err is None
        assert new_content == "Spare Cable\nNotebook"


# ── Tool-level integration tests ─────────────────────────────────────────

class TestRemoveTextPreservesUnrelatedContent:
    @pytest.mark.asyncio
    async def test_j03_repro_remove_one_item_keeps_the_others_verbatim(self, tool, db_session, session_factory):
        """The exact J03 shape: 4-item packing note, remove ONE item the
        user actually asked to remove, the other three (including the one
        Sara falsely believed was never saved) must survive untouched."""
        nid, _rev = _note(db_session, USER_A, "spare cable\ncharger\nnotebook\nrain jacket")
        result = await tool.execute(USER_A, note_id=nid, remove_text="rain jacket")
        assert result.success is True
        assert _fetch(session_factory, nid).content == "spare cable\ncharger\nnotebook"

    @pytest.mark.asyncio
    async def test_inline_list_removal_preserves_the_other_items_on_the_same_line(
        self, tool, db_session, session_factory,
    ):
        """The review finding this directly addresses: an inline,
        comma-separated list on ONE line must not lose its other items
        when one is removed — the first version of this fix deleted the
        WHOLE LINE, which would have wiped 'spare cable' and 'notebook'
        too."""
        nid, _rev = _note(db_session, USER_A, "Packing list: spare cable, charger, notebook, rain jacket.")
        result = await tool.execute(USER_A, note_id=nid, remove_text="charger")
        assert result.success is True
        content = _fetch(session_factory, nid).content
        assert content == "Packing list: spare cable, notebook, rain jacket."
        assert "spare cable" in content
        assert "notebook" in content
        assert "rain jacket" in content

    @pytest.mark.asyncio
    async def test_paragraph_removal_preserves_the_rest_of_the_sentence(self, tool, db_session, session_factory):
        nid, _rev = _note(
            db_session, USER_A,
            "Meeting notes: discuss Q3 budget, review the rain jacket vendor contract, and plan the offsite.",
        )
        result = await tool.execute(USER_A, note_id=nid, remove_text="the rain jacket vendor contract, ")
        assert result.success is True
        content = _fetch(session_factory, nid).content
        assert "discuss Q3 budget" in content
        assert "plan the offsite" in content
        assert "rain jacket" not in content

    @pytest.mark.asyncio
    async def test_repeated_matches_across_the_whole_note_are_refused(self, tool, db_session, session_factory):
        nid, _rev = _note(db_session, USER_A, "charger for phone\ncharger for laptop\nnotebook")
        result = await tool.execute(USER_A, note_id=nid, remove_text="charger")
        assert result.success is False
        assert "ambiguous" in result.message.lower()
        assert _fetch(session_factory, nid).content == "charger for phone\ncharger for laptop\nnotebook"

    @pytest.mark.asyncio
    async def test_no_match_is_refused_honestly_not_silently_ignored(self, tool, db_session, session_factory):
        nid, _rev = _note(db_session, USER_A, "spare cable\ncharger\nnotebook")
        result = await tool.execute(USER_A, note_id=nid, remove_text="rain jacket")
        assert result.success is False
        assert "didn't find" in result.message.lower()
        assert _fetch(session_factory, nid).content == "spare cable\ncharger\nnotebook"  # untouched

    @pytest.mark.asyncio
    async def test_append_text_preserves_existing_lines(self, tool, db_session, session_factory):
        nid, _rev = _note(db_session, USER_A, "spare cable\ncharger")
        result = await tool.execute(USER_A, note_id=nid, append_text="notebook")
        assert result.success is True
        assert _fetch(session_factory, nid).content == "spare cable\ncharger\nnotebook"

    @pytest.mark.asyncio
    async def test_content_and_remove_text_together_is_refused(self, tool, db_session, session_factory):
        nid, _rev = _note(db_session, USER_A, "spare cable\ncharger\nnotebook")
        result = await tool.execute(USER_A, note_id=nid, content="whatever", remove_text="charger", base_revision=_rev)
        assert result.success is False
        assert _fetch(session_factory, nid).content == "spare cable\ncharger\nnotebook"  # untouched

    @pytest.mark.asyncio
    async def test_cross_user_target_cannot_be_edited(self, tool, db_session, session_factory):
        nid, _rev = _note(db_session, USER_A, "spare cable\ncharger")
        result = await tool.execute(USER_B, note_id=nid, remove_text="charger")
        assert result.success is False
        assert _fetch(session_factory, nid).content == "spare cable\ncharger"


class TestFullContentReplacementRequiresARevision:
    @pytest.mark.asyncio
    async def test_replacing_content_without_base_revision_is_refused(self, tool, db_session, session_factory):
        """The review finding: 'unrestricted stale replacement remains
        possible' — content on a note that already has content must not
        succeed with no revision check at all."""
        nid, _rev = _note(db_session, USER_A, "old content")
        result = await tool.execute(USER_A, note_id=nid, content="brand new content")
        assert result.success is False
        assert "base_revision" in result.message
        assert _fetch(session_factory, nid).content == "old content"  # untouched

    @pytest.mark.asyncio
    async def test_replacing_content_with_the_correct_revision_succeeds(self, tool, db_session, session_factory):
        nid, rev = _note(db_session, USER_A, "old content")
        result = await tool.execute(USER_A, note_id=nid, content="brand new content", base_revision=rev)
        assert result.success is True
        assert _fetch(session_factory, nid).content == "brand new content"

    @pytest.mark.asyncio
    async def test_replacing_content_with_a_stale_revision_is_refused(self, tool, db_session, session_factory):
        nid, stale_rev = _note(db_session, USER_A, "old content")
        # Someone else's edit lands first.
        await tool.execute(USER_A, note_id=nid, append_text="an update from another turn")
        result = await tool.execute(USER_A, note_id=nid, content="brand new content", base_revision=stale_rev)
        assert result.success is False
        assert "changed" in result.message.lower()
        assert "an update from another turn" in _fetch(session_factory, nid).content

    @pytest.mark.asyncio
    async def test_replacing_content_on_an_empty_note_needs_no_revision(self, tool, db_session, session_factory):
        """Nothing to lose — an empty note's first real content doesn't
        need a base_revision to be provided."""
        nid, _rev = _note(db_session, USER_A, "")
        result = await tool.execute(USER_A, note_id=nid, content="first real content")
        assert result.success is True
        assert _fetch(session_factory, nid).content == "first real content"


class TestConcurrentEdits:
    @pytest.mark.asyncio
    async def test_a_stale_writer_is_refused_not_silently_applied(self, tool, db_session, session_factory):
        """Two 'sessions' read the same note. Session A commits first.
        Session B's write, computed from its own now-stale read, must be
        refused — not silently overwrite A's change (a lost update)."""
        nid, rev_at_read = _note(db_session, USER_A, "spare cable\ncharger\nnotebook")

        # Session A: reads the note (rev_at_read), then commits a change.
        result_a = await tool.execute(USER_A, note_id=nid, remove_text="charger")
        assert result_a.success is True
        assert _fetch(session_factory, nid).content == "spare cable\nnotebook"

        # Session B: was ALSO looking at the note as of rev_at_read (before
        # A's edit) and tries to remove "notebook" using content= built
        # from ITS OWN stale view (which still included "charger") —
        # using the STALE revision it actually read at.
        result_b = await tool.execute(
            USER_A, note_id=nid, content="spare cable\ncharger", base_revision=rev_at_read,
        )
        assert result_b.success is False
        assert "changed" in result_b.message.lower()
        # A's edit must survive untouched — B's stale write never applied.
        assert _fetch(session_factory, nid).content == "spare cable\nnotebook"

    @pytest.mark.asyncio
    async def test_two_narrow_edits_in_sequence_both_apply_when_each_rereads(
        self, tool, db_session, session_factory,
    ):
        """The legitimate case: two SEPARATE, correctly-sequenced edits
        (each naturally reading fresh state via the tool itself, as
        remove_text/append_text always do) must both succeed — the
        revision check must not make ordinary sequential editing fail."""
        nid, _rev = _note(db_session, USER_A, "spare cable\ncharger\nnotebook")

        result_1 = await tool.execute(USER_A, note_id=nid, remove_text="charger")
        assert result_1.success is True

        result_2 = await tool.execute(USER_A, note_id=nid, append_text="rain jacket")
        assert result_2.success is True

        assert _fetch(session_factory, nid).content == "spare cable\nnotebook\nrain jacket"

    @pytest.mark.asyncio
    async def test_full_content_replacement_still_works_for_a_genuine_fresh_rewrite(
        self, tool, db_session, session_factory,
    ):
        nid, rev = _note(db_session, USER_A, "old content")
        result = await tool.execute(USER_A, note_id=nid, content="brand new content", base_revision=rev)
        assert result.success is True
        assert _fetch(session_factory, nid).content == "brand new content"
