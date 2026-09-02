"""Regression: POST /api/fitness/food-log 500'd with

    'str' object has no attribute 'isoformat'

once the continuous-world-model plan started publishing a ``food.logged``
event from the create path. ``FoodLogCreate.logged_at`` is typed ``str``
(iOS and web both send an ISO string), so the raw string reached
``logged_at_time.isoformat()`` in the event payload. Every meal logged from
the phone with an explicit timestamp failed.

Also pins the timezone half of the fix: ``food_log.logged_at`` is a naive
``timestamp`` holding ET wall-clock, while ``world_event.occurred_at`` is
``timestamptz`` — handing the naive ET value straight to the envelope would
record the meal 4-5 hours early.
"""

import asyncio
from datetime import datetime

import pytest

from app.routes import fitness as fitness_routes
from app.core.timezone import USER_TIMEZONE


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _StubSession:
    """Enough Session for create_food_log: the INSERT returns a row."""

    def __init__(self):
        self.params = []
        self.committed = False
        self.rolled_back = False

    def execute(self, query, params=None):
        self.params.append(params)
        return _Result(("log-row-id",))

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


@pytest.fixture
def captured_events(monkeypatch):
    """Silence the side effects create_food_log fires after the insert and
    capture the world event instead of writing one."""
    events = []

    def fake_append(db, **kwargs):
        events.append(kwargs)
        return None

    import app.services.world_state.writer as writer

    monkeypatch.setattr(writer, "append_world_event", fake_append)

    async def noop_async(*args, **kwargs):
        return None

    monkeypatch.setattr(fitness_routes, "save_to_episodic_memory", noop_async)
    monkeypatch.setattr(fitness_routes, "update_daily_log", noop_async)
    monkeypatch.setattr(fitness_routes, "_emit_domain_event_safe", lambda *a, **k: None)
    return events


def _payload(logged_at):
    return fitness_routes.FoodLogCreate(
        meal_type="lunch",
        food_items=[{"name": "chicken", "quantity": 6, "unit": "oz"}],
        calories=320,
        protein=60,
        logged_at=logged_at,
    )


class TestFoodLogTimestampCoercion:
    def test_string_logged_at_does_not_500(self, captured_events):
        db = _StubSession()
        result = asyncio.run(
            fitness_routes.create_food_log(_payload("2026-08-28T13:45:00"), "user-1", db)
        )

        assert result["success"] is True
        assert db.committed is True
        assert db.rolled_back is False

        # The column gets naive ET wall-clock, exactly as sent.
        insert_params = db.params[0]
        assert insert_params["logged_at"] == datetime(2026, 8, 28, 13, 45)
        assert insert_params["logged_at"].tzinfo is None

    def test_event_occurred_at_is_offset_aware_et(self, captured_events):
        db = _StubSession()
        asyncio.run(
            fitness_routes.create_food_log(_payload("2026-08-28T13:45:00"), "user-1", db)
        )

        assert len(captured_events) == 1
        event = captured_events[0]
        assert event["kind"] == "food.logged"

        occurred_at = event["occurred_at"]
        assert occurred_at.tzinfo is not None, "timestamptz column needs an aware value"
        assert occurred_at == datetime(2026, 8, 28, 13, 45, tzinfo=USER_TIMEZONE)
        # 13:45 ET, not 13:45 UTC — the meal must not land 4-5 hours early.
        assert occurred_at.utcoffset().total_seconds() != 0

        # The payload copy is the same instant and is self-describing.
        assert datetime.fromisoformat(event["payload"]["logged_at"]) == occurred_at

    def test_offset_and_z_suffixed_timestamps_convert_to_et(self, captured_events):
        for sent in ("2026-08-28T17:45:00Z", "2026-08-28T17:45:00+00:00"):
            db = _StubSession()
            asyncio.run(fitness_routes.create_food_log(_payload(sent), "user-1", db))
            # 17:45 UTC is 13:45 EDT.
            assert db.params[0]["logged_at"] == datetime(2026, 8, 28, 13, 45)

    def test_missing_logged_at_falls_back_to_now(self, captured_events):
        db = _StubSession()
        asyncio.run(fitness_routes.create_food_log(_payload(None), "user-1", db))

        stored = db.params[0]["logged_at"]
        assert stored.tzinfo is None
        assert abs((stored - fitness_routes.naive_local_now()).total_seconds()) < 60

    def test_garbage_timestamp_is_a_400_not_a_500(self, captured_events):
        from fastapi import HTTPException

        db = _StubSession()
        with pytest.raises(HTTPException) as exc:
            asyncio.run(fitness_routes.create_food_log(_payload("not-a-date"), "user-1", db))

        assert exc.value.status_code == 400
        assert captured_events == []


class TestCoerceLoggedAt:
    def test_naive_string_is_treated_as_et_wall_clock(self):
        assert fitness_routes._coerce_logged_at("2026-08-28T13:45:00") == datetime(2026, 8, 28, 13, 45)

    def test_datetime_passthrough_is_normalized_to_naive_et(self):
        aware = datetime(2026, 8, 28, 17, 45, tzinfo=USER_TIMEZONE).astimezone()
        assert fitness_routes._coerce_logged_at(aware).tzinfo is None

    def test_empty_values_are_none(self):
        assert fitness_routes._coerce_logged_at(None) is None
        assert fitness_routes._coerce_logged_at("") is None
