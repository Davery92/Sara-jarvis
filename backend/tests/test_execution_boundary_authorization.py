"""Execution-boundary authorization — Milestone-A review, 2026-09-22.

Proves, against a REAL disposable database (not a mock of the query), that
a removal tool's execute() is scoped to the authenticated user_id, cannot
be redirected by a model-supplied argument, and handles a stale/already-
gone target honestly rather than silently no-op'ing. Uses
app.tools.reminders.RemindersCancelTool directly — the actual production
tool, not a reimplementation of its authorization logic.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.reminder import Reminder
from app.tools.reminders import RemindersCancelTool

USER_A = "user-a"
USER_B = "user-b"


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Reminder.__table__.create(engine, checkfirst=True)
    return sessionmaker(bind=engine)


@pytest.fixture()
def db_session(session_factory):
    # A throwaway session used only to seed/inspect fixture rows. The tool
    # under test gets its OWN session per call (see `tool` fixture below) and
    # closes it itself in a `finally`, exactly like the real get_db()
    # dependency — sharing one session between test and tool would raise
    # "not persistent" once the tool's `finally: db.close()` runs.
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def tool(monkeypatch, session_factory):
    import app.tools.reminders as mod

    def _fake_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(mod, "get_db", _fake_get_db)
    # WORLD_EVENTS_ENABLED defaults off under pytest (see conftest); leave
    # it that way so append_world_event() short-circuits without needing
    # the world_event tables in this disposable schema.
    return RemindersCancelTool()


def _reminder(db_session, user_id, title="Call the bank", completed=False):
    r = Reminder(
        id=str(uuid.uuid4()), user_id=user_id, title=title,
        reminder_time=datetime.now(timezone.utc), is_completed=completed,
    )
    db_session.add(r)
    db_session.commit()
    reminder_id = r.id
    db_session.expunge(r)
    return reminder_id


def _fetch(session_factory, reminder_id):
    session = session_factory()
    try:
        return session.query(Reminder).filter(Reminder.id == reminder_id).first()
    finally:
        session.close()


class TestExecutionBoundaryAuthorization:
    @pytest.mark.asyncio
    async def test_the_owning_user_can_cancel_their_own_reminder(self, tool, db_session, session_factory):
        rid = _reminder(db_session, USER_A)
        result = await tool.execute(USER_A, reminder_id=rid)
        assert result.success is True
        assert _fetch(session_factory, rid).is_completed is True

    @pytest.mark.asyncio
    async def test_a_cross_user_target_is_refused_not_cancelled(self, tool, db_session, session_factory):
        """The exact property this pass was asked to verify with real
        evidence: user B's authenticated session cannot cancel user A's
        reminder by ID, even though the ID itself is valid and exists."""
        rid = _reminder(db_session, USER_A)
        result = await tool.execute(USER_B, reminder_id=rid)
        assert result.success is False
        assert "not found" in result.message.lower()
        assert _fetch(session_factory, rid).is_completed is False  # untouched

    @pytest.mark.asyncio
    async def test_a_stale_nonexistent_target_is_refused_honestly(self, tool, db_session):
        result = await tool.execute(USER_A, reminder_id="does-not-exist")
        assert result.success is False
        assert "not found" in result.message.lower()

    @pytest.mark.asyncio
    async def test_an_already_completed_target_is_not_silently_recompleted(self, tool, db_session):
        """Idempotency at the tool layer: a repeated-delivery cancel on an
        already-cancelled reminder must say so honestly, not report a
        fresh success as if it just happened again."""
        rid = _reminder(db_session, USER_A, completed=True)
        result = await tool.execute(USER_A, reminder_id=rid)
        assert result.success is False
        assert "already" in result.message.lower()

    @pytest.mark.asyncio
    async def test_a_model_supplied_user_id_argument_cannot_override_the_authenticated_one(
        self, tool, db_session, session_factory
    ):
        """A model including `user_id` among its OWN tool-call arguments
        (whether malicious, confused, or copy-pasted from a bad example)
        must not be able to act as a different user — the authenticated
        user_id is passed positionally by the dispatcher
        (`tool.execute(user_id, **parameters)`), so a colliding keyword
        raises loudly instead of silently switching identity."""
        rid = _reminder(db_session, USER_A)
        with pytest.raises(TypeError):
            await tool.execute(USER_B, reminder_id=rid, user_id=USER_A)
        assert _fetch(session_factory, rid).is_completed is False  # the call never reached the query at all

    @pytest.mark.asyncio
    async def test_missing_reminder_id_is_refused_not_guessed(self, tool):
        result = await tool.execute(USER_A)
        assert result.success is False
        assert "required" in result.message.lower()


class TestUnknownToolsAreRefusedConservatively:
    """"Handle unknown tools conservatively" — verified against the actual
    registry dispatch path, not a reimplementation of it."""

    def test_the_registry_refuses_an_unregistered_tool_name(self):
        from app.tools.registry import tool_registry
        assert tool_registry.get_tool("this_tool_does_not_exist_anywhere") is None

    @pytest.mark.asyncio
    async def test_execute_tool_on_an_unknown_name_fails_safely(self):
        from app.tools.registry import tool_registry
        result = await tool_registry.execute_tool(
            name="this_tool_does_not_exist_anywhere", user_id=USER_A, parameters={},
        )
        assert result.success is False
        assert "not found" in result.message.lower()

    def test_is_write_tool_treats_unrecognized_names_as_droppable_reads(self):
        """`is_write_tool` answers a narrower question than tool-execution
        authorization: whether a call must survive the turn deadline. Its
        documented, deliberate choice is that an unrecognized name answers
        False there — losing it just costs a re-ask, never a silent
        double-write (see mutating.py's module docstring). The actual
        execution-authorization boundary for unknown tools is the registry
        dispatch path, covered by
        test_execute_tool_on_an_unknown_name_fails_safely above."""
        from app.tools.mutating import is_write_tool
        assert is_write_tool("some_tool_nobody_has_registered_yet") is False
