from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.routes import sara_status
from app.routes.sara_status import (
    _hours_since_naive_local,
    _local_day_bounds_naive,
    _resolve_daily_calorie_goal,
)


class _GoalDb:
    def __init__(self, calories=None):
        self.calories = calories

    def execute(self, *_args, **_kwargs):
        row = None if self.calories is None else SimpleNamespace(calories=self.calories)
        return SimpleNamespace(fetchone=lambda: row)


def test_hours_since_meal_treats_naive_timestamp_as_eastern_daylight_time(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "America/New_York")

    now_utc = datetime(2026, 8, 3, 16, 14, tzinfo=timezone.utc)
    logged_at = datetime(2026, 8, 3, 11, 11)

    assert _hours_since_naive_local(logged_at, now_utc) == 1.1


def test_hours_since_meal_uses_winter_offset(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "America/New_York")

    now_utc = datetime(2026, 1, 3, 18, 30, tzinfo=timezone.utc)
    logged_at = datetime(2026, 1, 3, 12, 0)

    assert _hours_since_naive_local(logged_at, now_utc) == 1.5


def test_hours_since_meal_does_not_show_negative_age(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "America/New_York")

    now_utc = datetime(2026, 8, 3, 16, 0, tzinfo=timezone.utc)
    logged_at = datetime(2026, 8, 3, 12, 5)

    assert _hours_since_naive_local(logged_at, now_utc) == 0.0


def test_food_day_bounds_match_naive_local_storage(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "America/New_York")

    now_utc = datetime(2026, 8, 4, 2, 0, tzinfo=timezone.utc)

    assert _local_day_bounds_naive(now_utc) == (
        datetime(2026, 8, 3, 0, 0),
        datetime(2026, 8, 4, 0, 0),
    )


def test_dashboard_calorie_goal_uses_training_day_phase_target(monkeypatch):
    monkeypatch.setattr(sara_status, "get_effective_phase", lambda *_: {
        "calories_target": 2300,
        "calories_training_day": 2550,
        "calories_rest_day": 2050,
    })
    monkeypatch.setattr(
        sara_status,
        "is_training_day",
        lambda *_: {"is_training_day": True},
    )

    assert _resolve_daily_calorie_goal(
        _GoalDb(1900), "user-1", date(2026, 8, 6)
    ) == 2550


def test_dashboard_calorie_goal_uses_manual_goal_without_active_phase(monkeypatch):
    monkeypatch.setattr(sara_status, "get_effective_phase", lambda *_: None)

    assert _resolve_daily_calorie_goal(
        _GoalDb(1875), "user-1", date(2026, 8, 6)
    ) == 1875
