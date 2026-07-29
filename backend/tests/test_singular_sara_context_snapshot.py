"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C2 canonical context snapshot
(world/self/relationship state) — the remaining three quadrants alongside
the already-tested body-state projection.
"""

from types import SimpleNamespace

import pytest

from app.services import context_snapshot as ctx


def _db_returning(*results):
    """Fake db whose .execute(...).scalar()/.fetchone() yields each result
    in call order."""
    calls = list(results)

    class _Result:
        def __init__(self, value):
            self._value = value

        def scalar(self):
            return self._value

        def fetchone(self):
            return self._value

    db = SimpleNamespace()
    db.execute = lambda *a, **kw: _Result(calls.pop(0))
    return db


class TestWorldState:
    @pytest.mark.asyncio
    async def test_computes_calendar_and_thread_counts(self, monkeypatch):
        # Arc 2.1 added david/home/health_today/work/fleet slices, each its
        # own best-effort db.execute call beyond the original calendar+thread
        # pair this test targets — _db_returning's canned-result queue only
        # covers those two, so later calls raise IndexError, which every
        # later slice already catches internally (per-slice isolation is
        # the point of Arc 2.1). Silence the unrelated unified_context read
        # too so this test stays scoped to calendar_horizon.
        from unittest.mock import AsyncMock
        monkeypatch.setattr(
            "app.services.unified_context.read_snapshot",
            AsyncMock(side_effect=RuntimeError("not under test here")),
        )
        db = _db_returning(3, 5)  # calendar count, then thread count
        state = await ctx.get_world_state(db, "user-1")

        assert state.active_calendar_events == 3
        assert state.open_threads == 5
        assert "3 calendar event(s)" in state.summary
        assert "5 open thread(s)" in state.summary
        assert state.confidence == 1.0

    @pytest.mark.asyncio
    async def test_query_failure_lowers_confidence_but_does_not_raise(self, monkeypatch):
        from unittest.mock import AsyncMock
        monkeypatch.setattr(
            "app.services.unified_context.read_snapshot",
            AsyncMock(side_effect=RuntimeError("not under test here")),
        )
        db = SimpleNamespace()

        def _broken(*a, **kw):
            raise RuntimeError("db down")

        db.execute = _broken
        state = await ctx.get_world_state(db, "user-1")

        assert state.active_calendar_events == 0
        assert state.open_threads == 0
        assert state.confidence < 1.0


class TestSelfState:
    @pytest.mark.asyncio
    async def test_open_concerns_sourced_from_degraded_body_components(self, monkeypatch):
        from app.schemas.contracts import BodyComponentV1, BodyStateV1, ComponentStatus
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        fake_body_state = BodyStateV1(
            as_of=now, healthy=False,
            components=[
                BodyComponentV1(name="database", status=ComponentStatus.OK, source="x", as_of=now),
                BodyComponentV1(name="acs_daemon", status=ComponentStatus.DEGRADED,
                                 impact="background self is offline", source="interoception", as_of=now),
            ],
            degraded_count=1, confidence=0.9,
        )

        async def _fake_get_body_state_projection(user_id):
            return fake_body_state

        async def _fake_kernel_get_state(user_id):
            return {"state": "ambient", "wake_reason": "promoted_event"}

        import app.services.body_state_projection as bsp
        import app.services.kernel as kernel

        monkeypatch.setattr(bsp, "get_body_state_projection", _fake_get_body_state_projection)
        monkeypatch.setattr(kernel, "get_state", _fake_kernel_get_state)

        state = await ctx.get_self_state("user-1")

        assert state.kernel_state == "ambient"
        assert state.wake_reason == "promoted_event"
        assert state.open_concerns == ["background self is offline"]
        assert state.self_story is None  # no db passed — unchanged, backward compatible

    @pytest.mark.asyncio
    async def test_self_story_populates_when_db_passed(self, monkeypatch):
        """Arc 4.2: passing db reads the rolling self-story; omitting it
        (the call above) stays exactly as before — additive, not breaking."""
        from unittest.mock import AsyncMock
        from app.schemas.contracts import BodyStateV1
        from datetime import datetime, timezone

        async def _fake_get_body_state_projection(user_id):
            return BodyStateV1(as_of=datetime.now(timezone.utc), healthy=True, components=[], degraded_count=0, confidence=1.0)

        async def _fake_kernel_get_state(user_id):
            return {"state": "ambient", "wake_reason": None}

        import app.services.body_state_projection as bsp
        import app.services.kernel as kernel
        import app.services.sara_journal_service as sjs

        monkeypatch.setattr(bsp, "get_body_state_projection", _fake_get_body_state_projection)
        monkeypatch.setattr(kernel, "get_state", _fake_kernel_get_state)
        monkeypatch.setattr(
            sjs.sara_journal, "get_self_story",
            AsyncMock(return_value="Yesterday I helped David plan the Risk Ninja pitch."),
        )

        state = await ctx.get_self_state("user-1", db=SimpleNamespace())

        assert state.self_story == "Yesterday I helped David plan the Risk Ninja pitch."

    @pytest.mark.asyncio
    async def test_self_story_read_failure_degrades_silently(self, monkeypatch):
        """A broken journal read must not take down the rest of self_state
        — same slice-isolation discipline as world_state."""
        from unittest.mock import AsyncMock
        from app.schemas.contracts import BodyStateV1
        from datetime import datetime, timezone

        async def _fake_get_body_state_projection(user_id):
            return BodyStateV1(as_of=datetime.now(timezone.utc), healthy=True, components=[], degraded_count=0, confidence=1.0)

        async def _fake_kernel_get_state(user_id):
            return {"state": "ambient", "wake_reason": None}

        import app.services.body_state_projection as bsp
        import app.services.kernel as kernel
        import app.services.sara_journal_service as sjs

        monkeypatch.setattr(bsp, "get_body_state_projection", _fake_get_body_state_projection)
        monkeypatch.setattr(kernel, "get_state", _fake_kernel_get_state)
        monkeypatch.setattr(
            sjs.sara_journal, "get_self_story",
            AsyncMock(side_effect=RuntimeError("db exploded")),
        )

        state = await ctx.get_self_state("user-1", db=SimpleNamespace())

        assert state.self_story is None
        assert state.kernel_state == "ambient"


class TestRelationshipState:
    def test_active_conversation_id_from_latest_conversation(self):
        db = _db_returning((("conv-123",)))
        # fetchone returns a row-like; emulate row[0] access via tuple
        db.execute = lambda *a, **kw: SimpleNamespace(fetchone=lambda: ("conv-123",))
        state = ctx.get_relationship_state(db, "user-1")

        assert state.active_conversation_id == "conv-123"
        assert state.recent_promises == []

    def test_no_conversation_yields_none(self):
        db = SimpleNamespace()
        db.execute = lambda *a, **kw: SimpleNamespace(fetchone=lambda: None)
        state = ctx.get_relationship_state(db, "user-1")

        assert state.active_conversation_id is None

    def test_query_failure_lowers_confidence(self):
        db = SimpleNamespace()

        def _broken(*a, **kw):
            raise RuntimeError("db down")

        db.execute = _broken
        state = ctx.get_relationship_state(db, "user-1")

        assert state.active_conversation_id is None
        assert state.confidence < 0.6


class TestGetContextSnapshot:
    @pytest.mark.asyncio
    async def test_assembles_all_three_quadrants(self, monkeypatch):
        async def _fake_self_state(user_id, db=None):
            from app.schemas.contracts import SelfStateV1
            from datetime import datetime, timezone
            return SelfStateV1(as_of=datetime.now(timezone.utc), kernel_state="ambient")

        monkeypatch.setattr(ctx, "get_self_state", _fake_self_state)

        db = _db_returning(0, 0)
        # get_relationship_state issues its own query after the two world_state
        # queries; extend the fake to also answer a fetchone() call with None.
        calls = [0, 0]

        class _Result:
            def __init__(self, value):
                self._value = value

            def scalar(self):
                return self._value

            def fetchone(self):
                return None

        db.execute = lambda *a, **kw: _Result(calls.pop(0)) if calls else _Result(None)

        result = await ctx.get_context_snapshot(db, "user-1")

        assert set(result.keys()) == {"world_state", "self_state", "relationship_state"}
        assert result["self_state"]["kernel_state"] == "ambient"
