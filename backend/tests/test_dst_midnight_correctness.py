"""Living-world-context plan §12 acceptance matrix: 'Local midnight,
timezone offset, DST | Day labels/totals are correct and historical facts
remain historical.'

app.core.timezone already gets this right by using ZoneInfo (not a fixed
UTC offset) and letting Python's naive-field + timedelta arithmetic
re-derive the correct UTC offset for each resulting datetime — that's what
makes a "day" 23, 24, or 25 real hours depending on whether a DST
transition falls inside it. These tests lock that property in as a
regression guard (a naive "just use timedelta(hours=24)" rewrite would
silently break it) rather than proving something newly fixed.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.timezone import (
    local_day_bounds,
    render_relative,
    render_when,
)

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# 2026 US DST transitions: spring forward Mar 8 (2am -> 3am), fall back
# Nov 1 (2am -> 1am).
SPRING_FORWARD_DAY = datetime(2026, 3, 8).date()
FALL_BACK_DAY = datetime(2026, 11, 1).date()
ORDINARY_DAY = datetime(2026, 6, 15).date()


class TestLocalDayBoundsSpansRealElapsedTime:
    def test_an_ordinary_day_is_24_hours(self):
        start, end = local_day_bounds(ORDINARY_DAY)
        assert (end.astimezone(UTC) - start.astimezone(UTC)) == timedelta(hours=24)

    def test_the_fall_back_day_is_25_hours(self):
        start, end = local_day_bounds(FALL_BACK_DAY)
        assert (end.astimezone(UTC) - start.astimezone(UTC)) == timedelta(hours=25)

    def test_the_spring_forward_day_is_23_hours(self):
        start, end = local_day_bounds(SPRING_FORWARD_DAY)
        assert (end.astimezone(UTC) - start.astimezone(UTC)) == timedelta(hours=23)

    def test_bounds_are_still_midnight_to_midnight_in_wall_clock_terms(self):
        """The point of using real day-length elsewhere is that THIS still
        reads as plain midnight-to-midnight — no leftover hour/minute from
        the DST shift leaking into the boundary itself."""
        for day in (ORDINARY_DAY, SPRING_FORWARD_DAY, FALL_BACK_DAY):
            start, end = local_day_bounds(day)
            assert (start.hour, start.minute, start.second) == (0, 0, 0)
            assert (end.hour, end.minute, end.second) == (0, 0, 0)
            assert end.date() == day + timedelta(days=1)


class TestHistoricalFactsStayHistoricalAcrossDST:
    def test_a_fact_from_the_morning_of_fall_back_day_is_not_today_by_the_evening(self):
        """A workout logged at 9am on the fall-back day, checked at 11pm
        the SAME day — still today, despite the day being 25 real hours,
        not 24."""
        morning = datetime(2026, 11, 1, 9, 0, tzinfo=ET)
        evening_same_day = datetime(2026, 11, 1, 23, 0, tzinfo=ET)
        start, end = local_day_bounds(FALL_BACK_DAY)
        assert start <= morning < end
        assert start <= evening_same_day < end

    def test_a_fact_from_the_day_before_fall_back_is_yesterday_not_today(self):
        start, end = local_day_bounds(FALL_BACK_DAY)
        day_before_last_moment = start - timedelta(seconds=1)
        assert not (start <= day_before_last_moment < end)


class TestRenderingSurvivesTheDSTBoundary:
    def test_a_due_time_just_after_the_spring_forward_gap_renders_without_crashing(self):
        # 2:30 AM doesn't exist on spring-forward day (clocks jump 2am->3am);
        # a due_at stored as 3:30 AM ET the same morning must still render.
        due = datetime(2026, 3, 8, 3, 30, tzinfo=ET)
        rendered = render_when(due, now=datetime(2026, 3, 8, 1, 0, tzinfo=ET))
        assert "Mar 8" in rendered or "March 8" in rendered
        assert rendered  # non-empty, no exception

    def test_a_due_time_during_the_fall_back_repeated_hour_renders_without_crashing(self):
        # 1:30 AM happens twice on fall-back day; ZoneInfo resolves the
        # ambiguity via `fold` rather than raising, so this must not crash.
        due = datetime(2026, 11, 1, 1, 30, tzinfo=ET)
        rendered = render_when(due, now=datetime(2026, 11, 1, 0, 0, tzinfo=ET))
        assert rendered

    def test_relative_time_across_the_fall_back_transition_is_not_negative_or_absurd(self):
        """Real timestamps are UTC-disambiguated (timestamptz columns store
        an absolute instant, never an ambiguous local fold) — so this
        compares the way data actually arrives: as UTC instants, not as
        hand-built same-tzinfo-object datetimes sharing a wall-clock time.
        (Two aware datetimes that share the identical tzinfo object compare
        by naive fields only, per the datetime docs — irrelevant here since
        nothing in this codebase compares timestamps that way; DB reads and
        datetime.now(timezone.utc) never produce that shape.)

        A thread resolved at 1:30 AM EDT, checked one real hour later at
        1:30 AM EST (the fall-back repeats that wall-clock hour) — an hour
        really did pass."""
        before_fallback = datetime(2026, 11, 1, 1, 30, tzinfo=ET, fold=0).astimezone(UTC)
        after_fallback = datetime(2026, 11, 1, 1, 30, tzinfo=ET, fold=1).astimezone(UTC)
        assert after_fallback - before_fallback == timedelta(hours=1)  # sanity: real gap

        rendered = render_relative(before_fallback, reference=after_fallback)
        assert "hour" in rendered
        assert "in " not in rendered  # must read as past, not future
