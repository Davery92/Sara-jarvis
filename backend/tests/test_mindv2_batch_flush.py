"""
Tests for the Arc 1.5 follow-up batch-flush task (found + fixed 2026-07-29):
judged_batch was a documented, permanent dead end (candidate_states.py's own
comment: "batch delivery isn't wired yet; SHADOW MODE", and it sat in
TERMINAL_STATUSES) — nothing ever promoted a batched candidate onward, so
real judge-approved-for-later messages never reached David. This task
promotes matching judged_batch rows to judged_send on a tick that falls
inside the labeled slot's delivery window, or via the expiry safety net
regardless of window, and expires anything whose valid_until has already
passed.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.mindv2_batch_flush import _run_async


def _row(id_, valid_until):
    r = MagicMock()
    r.id = id_
    r.valid_until = valid_until
    return r


def _mock_db_ctx(rows):
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[
        MagicMock(fetchall=MagicMock(return_value=rows)),  # SELECT
    ] + [MagicMock()] * len(rows))  # one UPDATE per row
    mock_db.commit = AsyncMock()
    mock_db_ctx = MagicMock()
    mock_db_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_db_ctx, mock_db


class TestOutsideDeliveryWindows:
    @pytest.mark.asyncio
    async def test_no_candidates_outside_windows_is_a_clean_noop(self):
        mock_ctx, mock_db = _mock_db_ctx([])
        with patch("app.core.timezone.now", return_value=datetime(2026, 7, 29, 13, 0)), \
             patch("app.db.session.get_async_session_factory", return_value=lambda: mock_ctx):
            result = await _run_async()
        assert result == {"skipped": "no_candidates", "slot": None}

    @pytest.mark.asyncio
    async def test_expiry_safety_net_still_applies_outside_windows(self):
        rows = [_row("cand-almost-expired", datetime.now(timezone.utc) + timedelta(minutes=30))]
        mock_ctx, mock_db = _mock_db_ctx(rows)
        with patch("app.core.timezone.now", return_value=datetime(2026, 7, 29, 13, 0)), \
             patch("app.db.session.get_async_session_factory", return_value=lambda: mock_ctx):
            result = await _run_async()
        assert result == {"slot": None, "promoted": 1, "expired": 0}


class TestMorningWindow:
    @pytest.mark.asyncio
    async def test_promotes_matching_morning_candidates(self):
        rows = [_row("cand-1", datetime.now(timezone.utc) + timedelta(hours=5))]
        mock_ctx, mock_db = _mock_db_ctx(rows)
        with patch("app.core.timezone.now", return_value=datetime(2026, 7, 29, 9, 0)), \
             patch("app.db.session.get_async_session_factory", return_value=lambda: mock_ctx):
            result = await _run_async()
        assert result == {"slot": "morning", "promoted": 1, "expired": 0}

    @pytest.mark.asyncio
    async def test_expires_stale_candidates_instead_of_promoting(self):
        rows = [_row("cand-stale", datetime.now(timezone.utc) - timedelta(hours=2))]
        mock_ctx, mock_db = _mock_db_ctx(rows)
        with patch("app.core.timezone.now", return_value=datetime(2026, 7, 29, 9, 0)), \
             patch("app.db.session.get_async_session_factory", return_value=lambda: mock_ctx):
            result = await _run_async()
        assert result == {"slot": "morning", "promoted": 0, "expired": 1}
        update_call = mock_db.execute.call_args_list[1]
        assert update_call[0][1]["status"] == "expired"

    @pytest.mark.asyncio
    async def test_no_candidates_is_a_clean_noop(self):
        mock_ctx, mock_db = _mock_db_ctx([])
        with patch("app.core.timezone.now", return_value=datetime(2026, 7, 29, 9, 0)), \
             patch("app.db.session.get_async_session_factory", return_value=lambda: mock_ctx):
            result = await _run_async()
        assert result == {"skipped": "no_candidates", "slot": "morning"}


class TestEveningWindow:
    @pytest.mark.asyncio
    async def test_queries_evening_slot_prefix(self):
        mock_ctx, mock_db = _mock_db_ctx([])
        with patch("app.core.timezone.now", return_value=datetime(2026, 7, 29, 18, 0)), \
             patch("app.db.session.get_async_session_factory", return_value=lambda: mock_ctx):
            result = await _run_async()
        assert result["slot"] == "evening"
        query_params = mock_db.execute.call_args_list[0][0][1]
        assert query_params["slot_prefix"] == "[slot=evening]%"


class TestExpirySafetyNetInsideWindow:
    @pytest.mark.asyncio
    async def test_expiry_cutoff_included_alongside_slot_match(self):
        mock_ctx, mock_db = _mock_db_ctx([])
        with patch("app.core.timezone.now", return_value=datetime(2026, 7, 29, 9, 0)), \
             patch("app.db.session.get_async_session_factory", return_value=lambda: mock_ctx):
            await _run_async()
        query_params = mock_db.execute.call_args_list[0][0][1]
        assert "cutoff" in query_params
