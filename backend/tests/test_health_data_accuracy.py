"""
Unit tests for HEALTH_DATA_ACCURACY_FIX_PLAN_2026_08_31.

On 2026-08-31 Sara produced a seven-day HRV table in which every value was
invented. Her sleep numbers in the same table were 6/7 correct. The split is
the whole diagnosis: the sleep path returned data, the HRV path returned
nothing, and rather than report an absence she completed the pattern.

These cover the code-level invariants. `scripts/health_accuracy_check.py` is
the live-stack complement (real DB, real graph, real tool output).
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

ET = ZoneInfo("America/New_York")


class TestDayBounds:
    """5.1/D5: a naive ET midnight bound against a `timestamptz` column on a
    UTC session made "today" start at 8 PM ET *yesterday*."""

    def test_local_day_bounds_are_aware_and_et(self):
        from app.core.timezone import local_day_bounds
        start, end = local_day_bounds(date(2026, 8, 31))
        assert start.tzinfo is not None and end.tzinfo is not None
        assert start.isoformat() == "2026-08-31T00:00:00-04:00"
        assert end.isoformat() == "2026-09-01T00:00:00-04:00"

    def test_aware_bound_is_not_the_naive_one_reinterpreted(self):
        """The bug in one assertion: binding the naive value against a
        timestamptz column reads it as UTC, four hours early."""
        from app.core.timezone import local_day_bounds, naive_local_day_bounds
        aware_start, _ = local_day_bounds(date(2026, 8, 31))
        naive_start, _ = naive_local_day_bounds(date(2026, 8, 31))
        misread_as_utc = naive_start.replace(tzinfo=timezone.utc)
        assert misread_as_utc < aware_start
        assert (aware_start - misread_as_utc) == timedelta(hours=4)

    def test_naive_bounds_stay_naive_for_legacy_columns(self):
        from app.core.timezone import naive_local_day_bounds
        start, end = naive_local_day_bounds(date(2026, 8, 31))
        assert start.tzinfo is None and end.tzinfo is None
        assert start == datetime(2026, 8, 31, 0, 0)


class TestMeasurementDetector:
    """0.2: `health_metric` is the only authority for a number about David's
    body, so the graph refuses to hold one."""

    @pytest.mark.parametrize("metric,value", [
        ("hrv", "80"),
        ("hrv", "87"),
        ("HRV (Heart Rate Variability)", "51"),
        ("sleep_duration", "7.5 hours"),
        ("Sleep duration", "Trending down (slept in a bit today)"),
        ("Sleep Quality", "Poor (barely slept)"),
        ("resting_heart_rate", "60 bpm"),
        ("daily_steps", 16679),
        ("weight", "241-242 lbs"),
        ("daily_calorie_intake", "1910 calories"),
    ])
    def test_rejects_measurements(self, metric, value):
        from app.services.personal_knowledge_graph import is_authoritative_health_copy
        assert is_authoritative_health_copy(metric, value) is True

    @pytest.mark.parametrize("metric,value", [
        ("chest development", "chronically underdeveloped relative to back"),
        ("migraine trigger", "red wine"),
        ("caffeine tolerance", "low"),
        ("soreness", "sore quads after squats"),
        ("sleep", "diagnosed with mild apnea"),
        ("recovery", "feels better after two rest days"),
        # A number David chose, not one his body produced.
        ("daily_calorie_target", "2760"),
        ("goal weight", "225 lbs"),
    ])
    def test_keeps_qualitative_and_intentional_facts(self, metric, value):
        from app.services.personal_knowledge_graph import is_authoritative_health_copy
        assert is_authoritative_health_copy(metric, value) is False

    def test_handles_non_string_values(self):
        """Neo4j returns properties in their stored type; an int used to raise."""
        from app.services.personal_knowledge_graph import is_numeric_health_value
        assert is_numeric_health_value(16679) is True
        assert is_numeric_health_value(None) is False


class TestTrendGapDays:
    """1.4/D12: SQL `GROUP BY DATE` only returns days that have rows, so a
    7-day request came back as a tidy 3-day series — which reads as
    continuous."""

    @pytest.mark.asyncio
    async def test_missing_days_are_reported_not_dropped(self):
        from app.services.health_insight_service import health_insight_service
        from app.core.timezone import today as local_today

        today = local_today()
        rows = [
            MagicMock(day=today - timedelta(days=6), avg_value=99.0,
                      min_value=99.0, max_value=99.0, sample_count=1),
            MagicMock(day=today, avg_value=54.0,
                      min_value=54.0, max_value=54.0, sample_count=1),
        ]
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = rows

        result = await health_insight_service.get_trend_analysis(
            "u1", db, "hrv", days=7)

        assert len(result["daily_data"]) == 7
        assert result["days_with_data"] == 2
        assert len(result["missing_days"]) == 5
        # The two real readings survive untouched, in the right slots.
        by_day = {d["day"]: d["avg_value"] for d in result["daily_data"]}
        assert by_day[(today - timedelta(days=6)).isoformat()] == 99.0
        assert by_day[today.isoformat()] == 54.0
        # And nothing was interpolated across the hole between them.
        assert all(by_day[(today - timedelta(days=n)).isoformat()] is None
                   for n in range(1, 6))

    @pytest.mark.asyncio
    async def test_average_is_over_days_with_data_only(self):
        from app.services.health_insight_service import health_insight_service
        from app.core.timezone import today as local_today

        today = local_today()
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [
            MagicMock(day=today, avg_value=54.0, min_value=54.0,
                      max_value=54.0, sample_count=1),
        ]
        result = await health_insight_service.get_trend_analysis("u1", db, "hrv", days=7)
        assert result["overall_avg"] == 54.0


class TestMetricAliasing:
    """The raw `hrv` stream went dark on 2026-05-05 and every reading since
    arrives as `hrv_morning`. The chat path still asked for `hrv`, found
    nothing, and reported an absence that wasn't real."""

    def test_hrv_resolves_to_the_live_stream_first(self):
        from app.services.health_insight_service import alias_chain
        assert alias_chain("hrv")[0] == "hrv_morning"
        assert "hrv" in alias_chain("hrv")

    def test_unaliased_metric_is_itself(self):
        from app.services.health_insight_service import alias_chain
        assert alias_chain("sleep_hours") == ["sleep_hours"]


class TestRecordedAtRendering:
    """2.2/D6: metrics from different days used to render as one undated
    "Current Health Status" block."""

    def test_unknown_timestamp_says_so(self):
        from app.services.health_insight_service import render_recorded_at
        assert render_recorded_at(None) == "at an unknown time"
        assert render_recorded_at("not-a-date") == "at an unknown time"

    def test_today_and_yesterday_are_named(self):
        from app.services.health_insight_service import render_recorded_at
        now = datetime.now(ET)
        assert render_recorded_at(now.isoformat()).startswith("today ")
        assert render_recorded_at(
            (now - timedelta(days=1)).isoformat()).startswith("yesterday ")

    def test_older_readings_carry_a_date(self):
        from app.services.health_insight_service import render_recorded_at
        old = (datetime.now(ET) - timedelta(days=6)).isoformat()
        rendered = render_recorded_at(old)
        assert "today" not in rendered and "yesterday" not in rendered
        assert any(ch.isdigit() for ch in rendered)


class TestHealthTodaySlice:
    """1.1/1.2/D1/D2: a missing metric was omitted rather than reported, and
    confidence was 1.0 whenever *any* row existed."""

    def _slice_for(self, rows):
        from app.services.context_snapshot import get_world_state
        db = MagicMock()

        def execute(stmt, params=None):
            result = MagicMock()
            text = str(stmt)
            if "health_metric" in text:
                result.fetchall.return_value = rows
            else:
                result.fetchall.return_value = []
                result.scalar.return_value = 0
                result.fetchone.return_value = None
            return result

        db.execute.side_effect = execute
        return get_world_state, db

    @pytest.mark.asyncio
    async def test_absent_metric_is_named_not_omitted(self):
        get_world_state, db = self._slice_for([
            MagicMock(metric_type="sleep_hours", value=8.3,
                      recorded_at=datetime.now(timezone.utc)),
        ])
        from unittest.mock import AsyncMock
        with patch("app.services.unified_context.read_snapshot",
                   new=AsyncMock(side_effect=Exception("skip"))):
            world = await get_world_state(db, user_id="u1")

        data = world.health_today.data
        assert "hrv" in data
        assert str(data["hrv"]).startswith("unavailable")
        assert "8.3" in str(data["sleep_hours"])

    @pytest.mark.asyncio
    async def test_confidence_reflects_coverage_not_existence(self):
        get_world_state, db = self._slice_for([
            MagicMock(metric_type="sleep_hours", value=8.3,
                      recorded_at=datetime.now(timezone.utc)),
        ])
        from unittest.mock import AsyncMock
        with patch("app.services.unified_context.read_snapshot",
                   new=AsyncMock(side_effect=Exception("skip"))):
            world = await get_world_state(db, user_id="u1")

        # One of four expected metrics present — emphatically not 1.0.
        assert world.health_today.confidence < 1.0
        assert world.health_today.confidence == pytest.approx(0.25)


class TestPKGHealthSuppression:
    """2.1: raw wins, always. Two numbers for the same metric side by side is
    how the model ends up choosing the wrong one."""

    def test_conflicting_line_is_dropped(self):
        from app.services.context_snapshot import suppress_pkg_health_conflicts
        pkg_text = (
            "## What Sara Knows About David\n"
            "- David's hrv: 80 (high confidence, confirmed 3x)\n"
            "- David likes black coffee (high confidence, confirmed 9x)\n"
        )
        out = suppress_pkg_health_conflicts(pkg_text, {"hrv": "54 (as of 06:12)"})
        assert "80" not in out
        assert "black coffee" in out

    def test_nothing_dropped_when_raw_has_no_reading(self):
        from app.services.context_snapshot import suppress_pkg_health_conflicts
        pkg_text = "- David's hrv: 80 (high confidence, confirmed 3x)\n"
        out = suppress_pkg_health_conflicts(
            pkg_text, {"hrv": "unavailable (not recorded today)"})
        assert "80" in out

    def test_alias_named_metric_is_matched(self):
        from app.services.context_snapshot import suppress_pkg_health_conflicts
        pkg_text = "- David's sleep duration: 7.5 hours (moderate confidence, confirmed 1x)\n"
        out = suppress_pkg_health_conflicts(pkg_text, {"sleep_hours": "8.3 (as of 06:00)"})
        assert "7.5" not in out


class TestRecallSuppressionIsNotBypassed:
    """A suppressed Health fact must not come back through the raw-column
    fallback in memory_recall._fact_text."""

    def test_suppressed_health_fact_yields_no_text(self):
        from app.services.memory_recall import _fact_text
        row = {"type": "Health", "metric": "hrv", "current_value": "80",
               "content_text": "David's hrv: 80"}
        assert _fact_text(row) == ""

    def test_other_types_still_use_the_fallback(self):
        from app.services.memory_recall import _fact_text
        row = {"type": "Routine", "value": "lifts on Tuesdays"}
        assert _fact_text(row) == "lifts on Tuesdays"


class TestWorkoutFallbacksAreNotSilent:
    """4.1/4.3/D8/D10."""

    def test_measured_ttl_constant_is_short(self):
        from app.services.personal_knowledge_graph import MEASURED_HEALTH_TTL_HOURS
        assert MEASURED_HEALTH_TTL_HOURS <= 48

    def test_zero_is_not_missing(self):
        from app.services.morning_brief_service import _measured
        assert _measured(0) == "0"
        assert _measured(0.0) == "0.0"
        assert _measured(None) == "not recorded"
