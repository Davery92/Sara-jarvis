"""MORNING_NOTIFICATIONS_PLAN_2026_08_18 Phase 5: the deliberation gate's
notification dedup key must survive LLM rephrasing. Greetings/check-ins
collapse to one per day-part (date + slot) regardless of wording; schedule
proposals key on the real calendar event when one can be matched.
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.deliberation import NotificationProposal
from app.services.deliberation_gate import _greeting_slot, _dedup_topic_for, _schedule_dedup_key


def _dt(hour: int, day: int = 18):
    return datetime(2026, 8, day, hour, 0, 0)


class TestGreetingSlot:
    def test_morning_hour_buckets_morning(self):
        p = NotificationProposal(title="Good morning", message="70F and sunny", category="checkin")
        assert _greeting_slot(p, _dt(6)) == "morning"

    def test_afternoon_hour_buckets_afternoon(self):
        p = NotificationProposal(title="Quick check-in", message="how's it going", category="checkin")
        assert _greeting_slot(p, _dt(14)) == "afternoon"

    def test_evening_hour_buckets_evening(self):
        p = NotificationProposal(title="Evening check-in", message="wrapping up?", category="checkin")
        assert _greeting_slot(p, _dt(19)) == "evening"

    def test_arrival_content_overrides_hour(self):
        p = NotificationProposal(title="Glad you're home", message="hope traffic wasn't bad", category="checkin")
        assert _greeting_slot(p, _dt(18)) == "arrival"

    def test_arrival_variant_phrasing_still_matches(self):
        p = NotificationProposal(title="Welcome back!", message="", category="checkin")
        assert _greeting_slot(p, _dt(17)) == "arrival"


class TestDedupTopicForCheckin:
    @pytest.mark.asyncio
    async def test_same_slot_same_day_collapses_regardless_of_wording(self):
        db = AsyncMock()
        p1 = NotificationProposal(title="Good morning!", message="70F, Iron Forums today", category="checkin")
        p2 = NotificationProposal(title="Morning update", message="Sunny and 70, you have Iron Forums", category="checkin")

        t1 = await _dedup_topic_for(db, "u1", p1, "checkin", _dt(6), "hash1")
        t2 = await _dedup_topic_for(db, "u1", p2, "checkin", _dt(6, day=18), "hash2")

        assert t1 == t2 == "checkin:2026-08-18:morning"

    @pytest.mark.asyncio
    async def test_different_day_gets_a_fresh_key(self):
        db = AsyncMock()
        p = NotificationProposal(title="Good morning!", message="", category="checkin")

        t_today = await _dedup_topic_for(db, "u1", p, "checkin", _dt(6, day=18), "hash1")
        t_tomorrow = await _dedup_topic_for(db, "u1", p, "checkin", _dt(6, day=19), "hash1")

        assert t_today != t_tomorrow

    @pytest.mark.asyncio
    async def test_arrival_and_morning_get_distinct_keys_same_day(self):
        db = AsyncMock()
        arrival = NotificationProposal(title="Glad you're home", message="", category="checkin")
        morning = NotificationProposal(title="Good morning", message="", category="checkin")

        t_arrival = await _dedup_topic_for(db, "u1", arrival, "checkin", _dt(18), "h1")
        t_morning = await _dedup_topic_for(db, "u1", morning, "checkin", _dt(6), "h2")

        assert t_arrival == "checkin:2026-08-18:arrival"
        assert t_morning == "checkin:2026-08-18:morning"
        assert t_arrival != t_morning


class TestScheduleDedupKey:
    @pytest.mark.asyncio
    async def test_matches_real_calendar_event_by_title(self):
        row = MagicMock(id=42, title="Iron Forums")
        result = MagicMock()
        result.fetchall.return_value = [row]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        p = NotificationProposal(title="Heads up", message="Iron Forums starts at 1pm", category="schedule")
        key = await _schedule_dedup_key(db, "u1", p, _dt(11), "fallbackhash")

        assert key == "schedule:42:2026-08-18"

    @pytest.mark.asyncio
    async def test_falls_back_to_date_scoped_hash_when_no_event_matches(self):
        result = MagicMock()
        result.fetchall.return_value = []
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        p = NotificationProposal(title="Heads up", message="something is happening today", category="schedule")
        key = await _schedule_dedup_key(db, "u1", p, _dt(11), "fallbackhash")

        assert key == "schedule:2026-08-18:fallbackhash"

    @pytest.mark.asyncio
    async def test_db_error_falls_back_gracefully(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=RuntimeError("db exploded"))

        p = NotificationProposal(title="Heads up", message="something", category="schedule")
        key = await _schedule_dedup_key(db, "u1", p, _dt(11), "fallbackhash")

        assert key == "schedule:2026-08-18:fallbackhash"


class TestDedupTopicForOtherCategories:
    @pytest.mark.asyncio
    async def test_non_checkin_non_schedule_falls_back_to_content_hash(self):
        db = AsyncMock()
        p = NotificationProposal(title="Lights left on", message="the porch light is on", category="home")
        key = await _dedup_topic_for(db, "u1", p, "home", _dt(20), "contenthash")
        assert key == "home:contenthash"
