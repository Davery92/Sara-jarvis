"""
Tests for mission engine idempotency (Phase 2 — Cortana Evolution).

Since MissionEngine uses raw SQL with AsyncSession (PostgreSQL-specific),
these tests mock the DB layer to verify idempotency logic.

Scenarios:
- advance_mission() called twice on same step → second is no-op
- Step already failed → skip
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.autonomy.mission_engine import MissionEngine


@pytest.fixture
def engine():
    return MissionEngine()


def _make_mission_row(state="running", current_idx=0, total_steps=3,
                       requires_confirmation=False, confirmed_at=None):
    """Create a mock mission row tuple."""
    return (
        "mission-123",  # id
        "user-1",       # user_id
        state,
        current_idx,
        total_steps,
        requires_confirmation,
        confirmed_at,
    )


def _make_step_row(status="pending", action_name="check_emails"):
    """Create a mock step row tuple."""
    return (
        "step-456",      # id
        action_name,
        "{}",            # action_args
        status,
    )


class TestAdvanceMissionIdempotency:
    """Test that advance_mission is idempotent."""

    @pytest.mark.asyncio
    async def test_already_executed_step_is_noop(self, engine):
        """If step_status != 'pending', advance_mission returns already_executed."""
        db = AsyncMock()

        # First query: load mission (FOR UPDATE)
        mission_result = MagicMock()
        mission_result.fetchone.return_value = _make_mission_row(state="running", current_idx=0)

        # Second query: load current step — already done
        step_result = MagicMock()
        step_result.fetchone.return_value = _make_step_row(status="done")

        db.execute = AsyncMock(side_effect=[mission_result, step_result])

        result = await engine.advance_mission(db, "mission-123")
        assert result["status"] == "already_executed"
        assert result["step_status"] == "done"
        # No further queries (no update, no execute)
        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_failed_step_is_noop(self, engine):
        """If current step already failed, advance_mission returns already_executed."""
        db = AsyncMock()

        mission_result = MagicMock()
        mission_result.fetchone.return_value = _make_mission_row(state="running", current_idx=1)

        step_result = MagicMock()
        step_result.fetchone.return_value = _make_step_row(status="failed")

        db.execute = AsyncMock(side_effect=[mission_result, step_result])

        result = await engine.advance_mission(db, "mission-123")
        assert result["status"] == "already_executed"
        assert result["step_status"] == "failed"

    @pytest.mark.asyncio
    async def test_running_step_is_noop(self, engine):
        """If current step is already running, advance_mission returns already_executed."""
        db = AsyncMock()

        mission_result = MagicMock()
        mission_result.fetchone.return_value = _make_mission_row(state="running", current_idx=0)

        step_result = MagicMock()
        step_result.fetchone.return_value = _make_step_row(status="running")

        db.execute = AsyncMock(side_effect=[mission_result, step_result])

        result = await engine.advance_mission(db, "mission-123")
        assert result["status"] == "already_executed"
        assert result["step_status"] == "running"

    @pytest.mark.asyncio
    async def test_not_found_mission(self, engine):
        """Non-existent mission returns not_found."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.fetchone.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        result = await engine.advance_mission(db, "nonexistent")
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_terminal_state_not_runnable(self, engine):
        """Mission in done/failed/cancelled state returns not_runnable."""
        for state in ("done", "failed", "cancelled"):
            db = AsyncMock()
            mission_result = MagicMock()
            mission_result.fetchone.return_value = _make_mission_row(state=state)
            db.execute = AsyncMock(return_value=mission_result)

            result = await engine.advance_mission(db, "mission-123")
            assert result["status"] == "not_runnable"
            assert result["state"] == state

    @pytest.mark.asyncio
    async def test_all_steps_done_completes_mission(self, engine):
        """When current_step_index >= total_steps, mission completes."""
        db = AsyncMock()

        mission_result = MagicMock()
        mission_result.fetchone.return_value = _make_mission_row(
            state="running", current_idx=3, total_steps=3
        )

        # UPDATE to set state='done'
        update_result = MagicMock()
        update_result.rowcount = 1

        db.execute = AsyncMock(side_effect=[mission_result, update_result])

        result = await engine.advance_mission(db, "mission-123")
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_step_not_found(self, engine):
        """If the step at current_idx doesn't exist, returns step_not_found."""
        db = AsyncMock()

        mission_result = MagicMock()
        mission_result.fetchone.return_value = _make_mission_row(state="running", current_idx=0)

        step_result = MagicMock()
        step_result.fetchone.return_value = None

        db.execute = AsyncMock(side_effect=[mission_result, step_result])

        result = await engine.advance_mission(db, "mission-123")
        assert result["status"] == "step_not_found"

    @pytest.mark.asyncio
    async def test_awaiting_confirmation(self, engine):
        """Mission requiring confirmation pauses at first step."""
        db = AsyncMock()

        mission_result = MagicMock()
        mission_result.fetchone.return_value = _make_mission_row(
            state="running", current_idx=0, requires_confirmation=True, confirmed_at=None,
        )

        step_result = MagicMock()
        step_result.fetchone.return_value = _make_step_row(status="pending")

        # UPDATE to set state='awaiting_confirm'
        update_result = MagicMock()
        update_result.rowcount = 1

        db.execute = AsyncMock(side_effect=[mission_result, step_result, update_result])

        result = await engine.advance_mission(db, "mission-123")
        assert result["status"] == "awaiting_confirmation"

    @pytest.mark.asyncio
    async def test_db_error_returns_error(self, engine):
        """DB exceptions should be caught and returned as error status."""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("Connection lost"))

        result = await engine.advance_mission(db, "mission-123")
        assert result["status"] == "error"
        assert "Connection lost" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_pending_mission_auto_starts(self, engine):
        """A pending mission should auto-start when advance_mission is called."""
        db = AsyncMock()

        # Load mission — state is 'pending'
        mission_result = MagicMock()
        mission_result.fetchone.return_value = _make_mission_row(
            state="pending", current_idx=0, total_steps=2
        )

        # UPDATE to set state='running' (auto-start)
        start_result = MagicMock()
        start_result.rowcount = 1

        # Load step — pending
        step_result = MagicMock()
        step_result.fetchone.return_value = _make_step_row(status="pending", action_name="check_emails")

        # UPDATE step to running
        step_running = MagicMock()
        step_running.rowcount = 1

        # _execute_step will try imports — mock it
        from unittest.mock import patch
        with patch.object(engine, "_execute_step", return_value={"success": True, "result": "ok"}):
            # UPDATE step to done + UPDATE mission (advance index)
            step_done = MagicMock()
            step_done.rowcount = 1
            mission_advance = MagicMock()
            mission_advance.rowcount = 1

            db.execute = AsyncMock(side_effect=[
                mission_result, start_result, step_result,
                step_running, step_done, mission_advance,
            ])

            result = await engine.advance_mission(db, "mission-123")
            assert result["status"] == "step_completed"
            assert result["step_index"] == 0
