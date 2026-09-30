"""The read-only calendar-availability tool adapter — harness/thinking/
personality plan Phase 4. Exercises the ACTUAL execute() path (DB query,
recurrence expansion, interval_calc call), not a reimplementation of it.
"""
from datetime import datetime, timedelta
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.tools.calendar import CalendarEvent
from app.tools.calendar_availability import CalendarAvailabilityTool

USER_ID = "test-user"


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    # Another module (app.models.calendar_event) maps additional JSONB
    # columns onto this same table via extend_existing=True; SQLite can't
    # compile JSONB, so coerce for the duration of the test — same pattern
    # as test_ground_truth_phase2.py's `db` fixture.
    from sqlalchemy import Text
    for column in CalendarEvent.__table__.columns:
        if type(column.type).__name__ == "JSONB":
            column.type = Text()
            column.default = None  # the JSONB default (a Python list) can't bind on sqlite3
            column.nullable = True
    CalendarEvent.__table__.create(engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def tool(monkeypatch, db_session):
    import app.tools.calendar_availability as mod

    def _fake_get_db():
        yield db_session

    monkeypatch.setattr(mod, "get_db", _fake_get_db)
    return CalendarAvailabilityTool()


def _add_event(db_session, title, start, end, rrule=None):
    ev = CalendarEvent(id=str(uuid.uuid4()), user_id=USER_ID, title=title,
                        start_time=start, end_time=end, rrule=rrule)
    db_session.add(ev)
    db_session.commit()
    return ev


class TestCalendarAvailabilityTool:
    @pytest.mark.asyncio
    async def test_earliest_slot_honors_the_buffer_the_real_fixture(self, tool, db_session):
        """The same fixture that found the real bug this phase fixes:
        Standup 09:15-09:45, Design review 10:00-10:50, need 30 minutes
        with a 10-minute buffer each side — ground truth 11:00."""
        d = "2026-09-22"
        _add_event(db_session, "Standup",
                   datetime(2026, 9, 22, 9, 15), datetime(2026, 9, 22, 9, 45))
        _add_event(db_session, "Design review",
                   datetime(2026, 9, 22, 10, 0), datetime(2026, 9, 22, 10, 50))

        result = await tool.execute(
            USER_ID, date=d, window_start_time="09:00", window_end_time="12:00",
            duration_minutes=30, buffer_before_minutes=10, buffer_after_minutes=10,
        )
        assert result.success is True
        assert result.data["slots"][0]["start"].startswith("2026-09-22T11:00:00")

    @pytest.mark.asyncio
    async def test_no_events_means_the_whole_window_qualifies(self, tool):
        result = await tool.execute(USER_ID, date="2026-09-22",
                                     window_start_time="09:00", window_end_time="12:00",
                                     duration_minutes=30)
        assert result.success is True
        assert result.data["slots"][0]["start"].startswith("2026-09-22T09:00:00")

    @pytest.mark.asyncio
    async def test_fully_booked_window_reports_no_slot_honestly(self, tool, db_session):
        _add_event(db_session, "All day meeting",
                   datetime(2026, 9, 22, 8, 0), datetime(2026, 9, 22, 18, 0))
        result = await tool.execute(USER_ID, date="2026-09-22",
                                     window_start_time="09:00", window_end_time="12:00",
                                     duration_minutes=30)
        assert result.success is True
        assert result.data["slots"] == []
        assert "no slot" in result.message.lower()

    @pytest.mark.asyncio
    async def test_all_slots_returns_more_than_one(self, tool, db_session):
        _add_event(db_session, "Mid-morning block",
                   datetime(2026, 9, 22, 10, 0), datetime(2026, 9, 22, 10, 30))
        result = await tool.execute(USER_ID, date="2026-09-22",
                                     window_start_time="09:00", window_end_time="12:00",
                                     duration_minutes=15, all_slots=True)
        assert result.success is True
        assert len(result.data["slots"]) == 2

    @pytest.mark.asyncio
    async def test_recurring_weekly_event_is_expanded_into_the_window(self, tool, db_session):
        """A weekly Tuesday standup anchored on an early date must still
        block time on a LATER Tuesday inside the query window, even though
        the stored row's own start_time is weeks earlier."""
        _add_event(db_session, "Weekly standup",
                   datetime(2026, 9, 1, 9, 0), datetime(2026, 9, 1, 9, 30),
                   rrule="FREQ=WEEKLY;BYDAY=TU")
        # 2026-09-22 is a Tuesday.
        result = await tool.execute(USER_ID, date="2026-09-22",
                                     window_start_time="09:00", window_end_time="10:00",
                                     duration_minutes=30)
        assert result.success is True
        assert result.data["slots"][0]["start"].startswith("2026-09-22T09:30:00")

    @pytest.mark.asyncio
    async def test_a_malformed_rrule_does_not_hide_other_events(self, tool, db_session):
        """A bad recurrence row must not take down the whole query."""
        _add_event(db_session, "Broken recurrence",
                   datetime(2026, 9, 1, 9, 0), datetime(2026, 9, 1, 9, 30),
                   rrule="NOT;A;VALID;RRULE")
        _add_event(db_session, "Ordinary meeting",
                   datetime(2026, 9, 22, 10, 0), datetime(2026, 9, 22, 10, 30))
        result = await tool.execute(USER_ID, date="2026-09-22",
                                     window_start_time="09:00", window_end_time="12:00",
                                     duration_minutes=15, all_slots=True)
        assert result.success is True
        # The ordinary meeting still blocks 10:00-10:30 — proves the query
        # didn't blow up on the malformed row.
        starts = [s["start"] for s in result.data["slots"]]
        assert not any(s.startswith("2026-09-22T10:00:00") for s in starts)

    @pytest.mark.asyncio
    async def test_invalid_date_is_rejected_not_guessed(self, tool):
        result = await tool.execute(USER_ID, date="not-a-date")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_ambiguous_fall_back_time_is_refused_not_guessed(self, tool):
        result = await tool.execute(USER_ID, date="2026-11-01", window_start_time="01:30")
        assert result.success is False
        assert "ambiguous" in result.message.lower()

    @pytest.mark.asyncio
    async def test_nonexistent_spring_forward_time_is_refused_not_guessed(self, tool):
        result = await tool.execute(USER_ID, date="2026-03-08", window_start_time="02:30")
        assert result.success is False
        assert "does not exist" in result.message.lower()

    @pytest.mark.asyncio
    async def test_never_registered_as_a_write_tool(self):
        from app.tools.mutating import is_write_tool
        assert is_write_tool("calendar_find_availability") is False
