"""
Tests for the sara_interest lifecycle status (migration 123) and its
David-facing decision endpoints — approve/reject/defer/discuss — plus the
initial_status rule in upsert_interest.

SARA_PROACTIVENESS_IMPLEMENTATION_PLAN_2026_07_25 P5.1: self-noticed
interests (source='reflection', the daemon's default) start at 'noticed' and
need an explicit David decision before mind.py's VM-tool gate will honor
them; interests David creates himself or that come from a real external
event are pre-approved since creating/reporting them IS the approval.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routes import acs_interests as routes


def _mock_async_session(row: dict | None):
    """Build a fake `async with get_async_session_factory()() as db:` chain
    where db.execute(...).mappings().first() returns `row`."""
    db = AsyncMock()
    mappings_result = MagicMock()
    mappings_result.first.return_value = row
    exec_result = MagicMock()
    exec_result.mappings.return_value = mappings_result
    db.execute = AsyncMock(return_value=exec_result)
    db.commit = AsyncMock()

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return db, ctx


def _row(status: str, interest_id: str = "aaaa1111-0000-0000-0000-000000000000") -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": interest_id, "topic": "topic", "display_name": "Display",
        "why": None, "weight": 1.0, "last_acted_at": None,
        "last_updated_at": now, "source": "reflection", "created_at": now,
        "blocked": False, "status": status,
    }


class TestDecisionEndpoints:
    @pytest.mark.asyncio
    async def test_approve_sets_status_approved(self):
        db, ctx = _mock_async_session(_row("approved"))
        with patch("app.routes.acs_interests.get_async_session_factory", return_value=lambda: ctx):
            result = await routes.approve_interest("aaaa1111", current_user=MagicMock())
        assert result.status == "approved"
        params = db.execute.await_args.args[1]
        assert params["status"] == "approved"

    @pytest.mark.asyncio
    async def test_reject_sets_status_rejected(self):
        db, ctx = _mock_async_session(_row("rejected"))
        with patch("app.routes.acs_interests.get_async_session_factory", return_value=lambda: ctx):
            result = await routes.reject_interest("aaaa1111", current_user=MagicMock())
        assert result.status == "rejected"

    @pytest.mark.asyncio
    async def test_defer_sets_status_deferred(self):
        db, ctx = _mock_async_session(_row("deferred"))
        with patch("app.routes.acs_interests.get_async_session_factory", return_value=lambda: ctx):
            result = await routes.defer_interest("aaaa1111", current_user=MagicMock())
        assert result.status == "deferred"

    @pytest.mark.asyncio
    async def test_discuss_sets_status_discussing(self):
        db, ctx = _mock_async_session(_row("discussing"))
        with patch("app.routes.acs_interests.get_async_session_factory", return_value=lambda: ctx):
            result = await routes.discuss_interest("aaaa1111", current_user=MagicMock())
        assert result.status == "discussing"

    @pytest.mark.asyncio
    async def test_approve_missing_interest_404s(self):
        db, ctx = _mock_async_session(None)
        with patch("app.routes.acs_interests.get_async_session_factory", return_value=lambda: ctx):
            with pytest.raises(Exception) as exc_info:
                await routes.approve_interest("ffffffff", current_user=MagicMock())
        assert getattr(exc_info.value, "status_code", None) == 404


class TestTouchInterestActivation:
    @pytest.mark.asyncio
    async def test_touch_sql_promotes_approved_to_active(self):
        """Regression guard: the approved -> active transition lives in
        touch_interest's SQL CASE clause, not in approve_interest itself —
        approval alone must not flip status to 'active'."""
        db, ctx = _mock_async_session(_row("active"))
        with patch("app.routes.acs_interests.get_async_session_factory", return_value=lambda: ctx):
            await routes.touch_interest("aaaa1111")
        sql = str(db.execute.await_args.args[0])
        assert "WHEN status = 'approved' THEN 'active'" in sql


class TestInitialStatusOnUpsert:
    @pytest.mark.parametrize("source,expected_status", [
        ("reflection", "noticed"),
        ("manual", "approved"),
        ("external_event", "approved"),
    ])
    @pytest.mark.asyncio
    async def test_new_interest_initial_status_by_source(self, source, expected_status):
        db, ctx = _mock_async_session(None)  # no existing row -> insert path
        insert_row = _row(expected_status)
        # First execute(): exact-topic lookup -> None. Second (only if no
        # embedding match attempted, since embeddings raise below): INSERT.
        insert_result = MagicMock()
        insert_result.mappings.return_value.first.return_value = insert_row
        no_match_result = MagicMock()
        no_match_result.mappings.return_value.first.return_value = None
        db.execute = AsyncMock(side_effect=[no_match_result, insert_result])

        payload = routes.InterestUpsertIn(
            display_name="A brand new thing", why=None,
            weight_delta=1.0, source=source,
        )
        with patch("app.routes.acs_interests.get_async_session_factory", return_value=lambda: ctx), \
             patch("app.services.embeddings.get_embedding", new=AsyncMock(side_effect=RuntimeError("no embed"))):
            result = await routes.upsert_interest(payload)

        assert result.interest.status == expected_status
        insert_params = db.execute.await_args_list[-1].args[1]
        assert insert_params["status"] == expected_status
