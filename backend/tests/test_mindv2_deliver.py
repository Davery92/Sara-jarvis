"""
Tests for the Mind V2 delivery task (SARA_ALIVE_BUILD_PLAN Arc 1.4).

Focused on the feature-flag gate and the staleness check found live: a real
approved candidate composed at 9:14 PM ("...before bed") was still sitting
undelivered at 6:44 AM because its own valid_until (TTL) hadn't passed —
delivery needs its own recency check independent of the candidate's TTL.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.mindv2_deliver import _run_async, _KIND_TO_CATEGORY


class TestFeatureFlagGate:
    @pytest.mark.asyncio
    async def test_flag_off_is_a_clean_noop(self):
        with patch("app.core.feature_flags.is_enabled", return_value=False):
            result = await _run_async()
        assert result == {"skipped": "flag_off"}


class TestKindToCategoryMapping:
    def test_every_candidate_kind_covered(self):
        # say_candidate.kind check constraint values (say_candidate.py _KINDS)
        for kind in ("inform", "followup", "prep", "alert", "retrospective"):
            assert kind in _KIND_TO_CATEGORY


def _row(id_, created_at, kind="inform", source="test", urgency="normal", text="hi", final_text=None):
    row = MagicMock()
    row.id = id_
    row.candidate_id = "cand-1"
    row.final_text = final_text
    row.text = text
    row.urgency = urgency
    row.created_at = created_at
    row.kind = kind
    row.source = source
    return row


class TestStalenessGate:
    @pytest.mark.asyncio
    async def test_stale_row_is_dropped_not_sent(self):
        """A composed_utterance row older than 2h must never reach
        send_notification — this is the literal bug found live (a real
        HRV alert saying 'before bed' still undelivered the next morning)."""
        old_row = _row("row-old", datetime.now(timezone.utc) - timedelta(hours=5))

        mock_db = AsyncMock()
        mock_execute = AsyncMock()
        mock_execute.fetchall = MagicMock(return_value=[old_row])
        mock_db.execute = AsyncMock(return_value=mock_execute)
        mock_db.commit = AsyncMock()

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.feature_flags.is_enabled", return_value=True), \
             patch("app.db.session.get_async_session_factory", return_value=mock_factory), \
             patch("app.services.unified_notification.send_notification", new_callable=AsyncMock) as mock_send:
            result = await _run_async()

        mock_send.assert_not_called()
        assert result["stale"] == 1
        assert result["delivered"] == 0

    @pytest.mark.asyncio
    async def test_fresh_row_is_delivered(self):
        fresh_row = _row("row-fresh", datetime.now(timezone.utc) - timedelta(minutes=5))

        mock_db = AsyncMock()
        mock_execute = AsyncMock()
        mock_execute.fetchall = MagicMock(return_value=[fresh_row])
        mock_db.execute = AsyncMock(return_value=mock_execute)
        mock_db.commit = AsyncMock()

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.feature_flags.is_enabled", return_value=True), \
             patch("app.db.session.get_async_session_factory", return_value=mock_factory), \
             patch("app.services.unified_notification.send_notification", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"sent": True}
            result = await _run_async()

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["_skip_phrasing"] is True
        assert call_kwargs["title"] == "Sara"
        assert result["delivered"] == 1
        assert result["stale"] == 0
