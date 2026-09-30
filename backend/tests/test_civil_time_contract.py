"""The one timestamp contract — reliable-assistant plan Phase F.

Finding 37: "Calendar and reminder tools use **opposite** conventions for
offset-free timestamps." Finding 16: repeated reminder timezone defects. The
same naive string from the same model in the same turn meant two different
instants four or five hours apart depending on which tool received it.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services.civil_time import (
    AmbiguousTimeError,
    DEFAULT_USER_TZ,
    TIME_PARAMETER_CONTRACT,
    describe_instant,
    parse_user_datetime,
)

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

# 2026 US transitions: forward Mar 8 (2am→3am), back Nov 1 (2am→1am).
SPRING_FORWARD = "2026-03-08"
FALL_BACK = "2026-11-01"


class TestNaiveIsDavidsWallClock:
    def test_a_naive_evening_time_is_that_evening_for_him(self):
        """The finding-16 case: a naive 7pm read as UTC books 3pm ET."""
        result = parse_user_datetime("2026-09-28T19:00:00")
        assert result.had_offset is False
        assert result.local.hour == 19
        assert result.local.tzinfo is not None
        # 19:00 EDT is 23:00 UTC, not 19:00 UTC.
        assert result.instant.astimezone(UTC).hour == 23

    def test_it_says_which_zone_it_assumed(self):
        result = parse_user_datetime("2026-09-28T19:00:00")
        assert "New_York" in (result.assumed_zone or "")

    def test_an_explicit_offset_is_authoritative(self):
        result = parse_user_datetime("2026-09-28T19:00:00+00:00")
        assert result.had_offset is True
        assert result.instant.astimezone(UTC).hour == 19
        assert result.assumed_zone is None

    def test_a_z_suffix_is_utc(self):
        assert parse_user_datetime("2026-09-28T19:00:00Z").instant.astimezone(UTC).hour == 19

    def test_an_aware_datetime_object_passes_through(self):
        dt = datetime(2026, 9, 28, 19, 0, tzinfo=ET)
        assert parse_user_datetime(dt).instant == dt.astimezone(UTC)

    def test_a_naive_datetime_object_follows_the_same_rule_as_a_string(self):
        naive = datetime(2026, 9, 28, 19, 0)
        assert parse_user_datetime(naive).local.hour == 19

    def test_every_result_is_aware_utc(self):
        for value in ("2026-09-28T19:00:00", "2026-09-28T19:00:00Z", "2026-09-28"):
            instant = parse_user_datetime(value).instant
            assert instant.tzinfo is not None
            assert instant.utcoffset().total_seconds() == 0


class TestOneConventionForEveryTool:
    def test_reminders_and_calendar_agree(self):
        """The whole point of finding 37: whatever the convention IS, both
        tools have to share it. Asserted at the parse layer both now use."""
        from app.tools.reminders import RemindersCreateTool
        from app.tools.calendar import CalendarCreateTool

        # Both descriptions must carry the same stated contract, so the model
        # is never told two different things in one turn.
        assert TIME_PARAMETER_CONTRACT in RemindersCreateTool().parameters[
            "properties"]["reminder_time"]["description"]
        cal = CalendarCreateTool().parameters["properties"]
        for field in ("starts_at", "ends_at"):
            assert TIME_PARAMETER_CONTRACT in cal[field]["description"], field


class TestDSTPolicyIsStatedNotAccidental:
    def test_the_repeated_hour_picks_the_first_and_says_so(self):
        result = parse_user_datetime(f"{FALL_BACK}T01:30:00")
        assert result.note, "a time that happens twice must be explained"
        assert "twice" in result.note
        # The first occurrence is still on EDT (-04:00).
        assert result.instant.astimezone(ET).utcoffset().total_seconds() == -4 * 3600

    def test_a_time_in_the_spring_gap_is_moved_forward_and_said_so(self):
        result = parse_user_datetime(f"{SPRING_FORWARD}T02:30:00")
        assert result.note
        assert "doesn't exist" in result.note
        # Whatever it becomes, it must be a real instant that round-trips.
        assert result.local.replace(tzinfo=None) != datetime(2026, 3, 8, 2, 30)

    def test_an_ordinary_time_has_no_note(self):
        assert parse_user_datetime("2026-06-15T14:00:00").note == ""

    def test_a_time_just_outside_the_transition_is_unremarkable(self):
        for value in (f"{FALL_BACK}T05:00:00", f"{SPRING_FORWARD}T06:00:00"):
            assert parse_user_datetime(value).note == ""


class TestBareDates:
    def test_a_bare_date_is_a_morning_reminder_not_midnight(self):
        result = parse_user_datetime("2026-09-28")
        assert result.local.hour == 9
        assert "no time" in result.note

    def test_it_is_local_9am_not_utc_9am(self):
        assert parse_user_datetime("2026-09-28").instant.astimezone(UTC).hour == 13


class TestUnreadableInput:
    @pytest.mark.parametrize("value", ["", None, "next tuesday", "soon", "??"])
    def test_it_raises_rather_than_guess(self, value):
        with pytest.raises(AmbiguousTimeError):
            parse_user_datetime(value)

    def test_the_error_says_what_shape_to_use(self):
        with pytest.raises(AmbiguousTimeError) as exc:
            parse_user_datetime("next tuesday")
        assert "ISO 8601" in str(exc.value)

    @pytest.mark.parametrize("value", [
        "2026-09-28 19:00:00",
        "2026-09-28 19:00:00 UTC",
    ])
    def test_common_near_misses_still_parse(self, value):
        assert parse_user_datetime(value).instant.year == 2026


class TestReadback:
    def test_a_readback_carries_the_local_time_and_zone(self):
        instant = parse_user_datetime("2026-09-28T19:00:00").instant
        spoken = describe_instant(instant)
        assert "7:00 PM" in spoken
        assert "EDT" in spoken

    def test_a_readback_of_a_utc_input_is_still_in_his_zone(self):
        instant = parse_user_datetime("2026-09-28T19:00:00Z").instant
        assert "3:00 PM" in describe_instant(instant)
