"""Timer naive/aware datetime crash (Sara repair plan R05, evidence
D04_TIMERS_STATUS_CRASHES_NAIVE_AWARE_DATETIME).

Confirmed mechanism: `app/tools/timers.py` defines its OWN local `Timer`
SQLAlchemy model (to avoid a circular import with
`app.models.reminder.Timer`), mapped to the same `timer` table the real
migrations built with `DateTime(timezone=True)` (timestamptz) columns — but
the local model declared plain `DateTime` (no `timezone=True`). SQLAlchemy's
generic `DateTime` type tells the driver to hand back a NAIVE datetime for
an actually-aware timestamptz column, so `timer.end_time` came back naive
while `TimersStatusTool.execute` compares it against
`datetime.now(timezone.utc)` (aware) — "can't subtract offset-naive and
offset-aware datetimes" on every status check, which also blocked cancel
(it depends on status to locate the timer).

Runs against the real disposable Postgres (needed: the naive-vs-aware
behavior is a property of how psycopg/SQLAlchemy interprets an actual
timestamptz column via a DateTime(no tz) Python type — a SQLite fixture
would not reproduce it, since SQLite has no native timestamptz distinction).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.tools.timers import Timer, TimersCancelTool, TimersStatusTool, TimersStartTool


class TestTimerStatusDoesNotCrashOnRealPostgresTimestamptz:
    @pytest.mark.asyncio
    async def test_status_check_on_a_freshly_started_timer_does_not_crash(self, monkeypatch):
        """The exact D04 shape: start a timer, then immediately ask for its
        status. Must not raise 'offset-naive and offset-aware'."""
        tool_start = TimersStartTool()
        started = await tool_start.execute("user-timer-test", label="repro timer", duration_seconds=120)
        assert started.success is True
        timer_id = started.data["timer_id"]

        try:
            tool_status = TimersStatusTool()
            status = await tool_status.execute("user-timer-test")

            assert status.success is True, status.message
            matching = [t for t in status.data["timers"] if t["timer_id"] == timer_id]
            assert matching, "started timer not found in status list"
            assert matching[0]["time_remaining"] is not None
            assert matching[0]["time_remaining"]["total_seconds"] > 0
        finally:
            tool_cancel = TimersCancelTool()
            await tool_cancel.execute("user-timer-test", timer_id=timer_id)

    @pytest.mark.asyncio
    async def test_cancel_after_status_check_works(self):
        tool_start = TimersStartTool()
        started = await tool_start.execute("user-timer-test-2", label="cancel repro", duration_seconds=90)
        timer_id = started.data["timer_id"]

        tool_status = TimersStatusTool()
        status = await tool_status.execute("user-timer-test-2")
        assert status.success is True

        tool_cancel = TimersCancelTool()
        result = await tool_cancel.execute("user-timer-test-2", timer_id=timer_id)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_an_already_expired_timer_is_auto_completed_not_crashed(self):
        """The comparison `timer.end_time - now` must work even when the
        stored end_time is already in the past (the exact arithmetic that
        raised before the fix)."""
        from app.db.session import get_db

        db_gen = get_db()
        db = next(db_gen)
        try:
            expired = Timer(
                user_id="user-timer-test-3",
                title="already expired",
                duration_minutes=1,
                start_time=datetime.now(timezone.utc) - timedelta(minutes=5),
                end_time=datetime.now(timezone.utc) - timedelta(minutes=4),
                is_active=True,
                is_completed=False,
            )
            db.add(expired)
            db.commit()
            db.refresh(expired)
            expired_id = expired.id
        finally:
            db.close()

        tool_status = TimersStatusTool()
        status = await tool_status.execute("user-timer-test-3")
        assert status.success is True
        matching = [t for t in status.data["timers"] if t["timer_id"] == expired_id]
        assert matching
        assert matching[0]["is_expired"] is True
