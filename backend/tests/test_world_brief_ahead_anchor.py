"""Regression test for a real bug found live 2026-07-30 via an end-to-end
sender-proof test: sweep_brief's AHEAD anchor stored end_time (for
migrate_zones' own transition check) but render_brief displayed that same
`at` field as "time until event starts" — a real prep candidate's correct
"starts in 44 min" got killed at review because the World Brief claimed
"in 1h 26m" (the event's END time, mislabeled as its start).

Fix: `at` = start_time (what render_brief/consumers should see), a separate
`migrate_at` = end_time is used only by migrate_zones for the HAPPENED
transition.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.world_brief import migrate_zones


class TestMigrateZonesUsesMigrateAt:
    @pytest.mark.asyncio
    async def test_item_with_future_end_time_not_migrated_even_if_at_is_past(self):
        """An item whose `at` (start_time) has passed but `migrate_at` (end_time)
        hasn't yet must stay in AHEAD — the exact case that was broken."""
        now = datetime.now(timezone.utc)
        item = {
            "key": "cal:test-event",
            "text": "Ongoing meeting",
            "at": (now - timedelta(minutes=10)).isoformat(),       # started 10 min ago
            "migrate_at": (now + timedelta(minutes=20)).isoformat(),  # ends in 20 min
        }
        with patch("app.services.world_brief.get_brief_row", new=AsyncMock(
            return_value={"sections": {"ahead": [item]}}
        )), patch("app.services.world_brief.brief_patch", new=AsyncMock()) as mock_patch:
            moved = await migrate_zones(MagicMock(), "test-user")
        assert moved == 0
        mock_patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_item_migrates_once_migrate_at_passes(self):
        now = datetime.now(timezone.utc)
        item = {
            "key": "cal:test-event",
            "text": "Finished meeting",
            "at": (now - timedelta(minutes=90)).isoformat(),
            "migrate_at": (now - timedelta(minutes=30)).isoformat(),  # ended 30 min ago
        }
        with patch("app.services.world_brief.get_brief_row", new=AsyncMock(
            return_value={"sections": {"ahead": [item]}}
        )), patch("app.services.world_brief.brief_patch", new=AsyncMock()) as mock_patch:
            moved = await migrate_zones(MagicMock(), "test-user")
        assert moved == 1
        mock_patch.assert_called_once()

    @pytest.mark.asyncio
    async def test_item_without_migrate_at_falls_back_to_at(self):
        """Non-calendar AHEAD items (no end_time concept) keep working as before."""
        now = datetime.now(timezone.utc)
        item = {
            "key": "misc:test-item",
            "text": "Some ahead item",
            "at": (now - timedelta(minutes=5)).isoformat(),
        }
        with patch("app.services.world_brief.get_brief_row", new=AsyncMock(
            return_value={"sections": {"ahead": [item]}}
        )), patch("app.services.world_brief.brief_patch", new=AsyncMock()) as mock_patch:
            moved = await migrate_zones(MagicMock(), "test-user")
        assert moved == 1
        mock_patch.assert_called_once()


class TestSweepBriefCalendarAnchorIsStartTime:
    @pytest.mark.asyncio
    async def test_ahead_at_is_start_time_not_end_time(self):
        """The real bug: `at` must be start_time so render_brief's 'in Xh Ym'
        matches when the event actually starts, not when it ends."""
        from app.services.world_brief import sweep_brief

        start = datetime(2026, 7, 30, 20, 0, 0)   # naive ET wall-clock
        end = datetime(2026, 7, 30, 21, 0, 0)      # 1h duration

        fake_row = MagicMock(id="evt-1", title="Budget review", start_time=start, end_time=end)
        fake_result = MagicMock()
        fake_result.fetchall.return_value = [fake_row]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=fake_result)

        captured = {}

        async def fake_brief_patch(db, user_id, *, op, section, item_key, content, **kwargs):
            if section == "ahead":
                captured["content"] = content

        with patch("app.services.world_brief.migrate_zones", new=AsyncMock(return_value=0)), \
             patch("app.services.world_brief.brief_patch", new=fake_brief_patch), \
             patch("app.services.world_brief.get_brief_row", new=AsyncMock(return_value={"sections": {}})):
            await sweep_brief(db, "test-user")

        assert "content" in captured
        assert captured["content"]["at"] != captured["content"]["migrate_at"]
        # `at` (start) must be earlier than `migrate_at` (end) for a normal event.
        from app.services.world_brief import _parse_iso
        assert _parse_iso(captured["content"]["at"]) < _parse_iso(captured["content"]["migrate_at"])
