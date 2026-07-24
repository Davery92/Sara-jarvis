"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C0 feature flags and legacy-vs-target
path counters, plus the concrete kernel/autonomy wiring that uses them.
"""

from types import SimpleNamespace

import fakeredis.aioredis
import pytest


# ==========================================
# Feature flags
# ==========================================

class _FakeSettingsSession:
    """Emulates the sync `app_settings(key, value)` table just enough for
    feature_flags._read_flags / set_flag (SELECT ... WHERE key = ANY(:keys),
    INSERT ... ON CONFLICT DO UPDATE)."""

    def __init__(self, store: dict):
        self._store = store

    def execute(self, stmt, params=None):
        params = params or {}
        sql = str(stmt).strip().upper()
        if sql.startswith("SELECT"):
            keys = params.get("keys", [])
            rows = [(k, v) for k, v in self._store.items() if k in keys]
            return SimpleNamespace(fetchall=lambda: rows)
        if sql.startswith("INSERT"):
            self._store[params["key"]] = params["value"]
            return SimpleNamespace(fetchall=lambda: [])
        return SimpleNamespace(fetchall=lambda: [])

    def commit(self):
        pass

    def close(self):
        pass


@pytest.fixture
def fake_app_settings(monkeypatch):
    """Patches app.db.session.SessionLocal so feature_flags reads/writes an
    in-memory dict instead of Postgres."""
    import app.db.session as db_session

    store: dict = {}
    monkeypatch.setattr(db_session, "SessionLocal", lambda: _FakeSettingsSession(store))
    return store


class TestFeatureFlags:
    def test_unknown_flags_default_off(self, fake_app_settings):
        from app.core.feature_flags import Flag, is_enabled

        assert is_enabled(Flag.SINGULAR_KERNEL) is False

    def test_set_flag_then_is_enabled(self, fake_app_settings):
        from app.core.feature_flags import Flag, is_enabled, set_flag

        set_flag(Flag.SINGULAR_KERNEL, True, updated_by="test")
        assert is_enabled(Flag.SINGULAR_KERNEL) is True

        set_flag(Flag.SINGULAR_KERNEL, False, updated_by="test")
        assert is_enabled(Flag.SINGULAR_KERNEL) is False

    def test_is_enabled_accepts_plain_string(self, fake_app_settings):
        from app.core.feature_flags import is_enabled, set_flag

        set_flag("SINGULAR_ATTENTION", True)
        assert is_enabled("SINGULAR_ATTENTION") is True

    def test_unknown_flag_name_raises(self, fake_app_settings):
        from app.core.feature_flags import is_enabled

        with pytest.raises(ValueError):
            is_enabled("NOT_A_REAL_FLAG")

    def test_all_flags_reports_every_known_flag(self, fake_app_settings):
        from app.core.feature_flags import ALL_FLAGS, all_flags, set_flag

        set_flag("SINGULAR_ACTIONS", True)
        snapshot = all_flags()

        assert set(snapshot.keys()) == set(ALL_FLAGS)
        assert snapshot["SINGULAR_ACTIONS"] is True
        assert snapshot["SINGULAR_KERNEL"] is False  # untouched -> default off

    def test_read_failure_fails_closed(self, monkeypatch):
        import app.db.session as db_session
        from app.core.feature_flags import Flag, is_enabled

        def _broken():
            raise ConnectionError("db down")

        monkeypatch.setattr(db_session, "SessionLocal", _broken)
        assert is_enabled(Flag.SINGULAR_CONTEXT) is False


# ==========================================
# Legacy-vs-target path counters
# ==========================================

class TestLegacyPathCounters:
    @pytest.fixture
    def fake_redis(self, monkeypatch):
        import app.services.legacy_path_counters as counters

        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

        async def _fake_get_redis():
            return fake

        monkeypatch.setattr(counters, "_get_redis", _fake_get_redis)
        return fake

    @pytest.mark.asyncio
    async def test_record_and_get_counts(self, fake_redis):
        from app.services.legacy_path_counters import (
            get_counts, record_legacy_path, record_target_path,
        )

        await record_target_path("ambient_cognition")
        await record_target_path("ambient_cognition")
        await record_legacy_path("ambient_cognition")

        counts = await get_counts("ambient_cognition", days=1)
        assert counts["target"] == 2
        assert counts["legacy"] == 1
        assert counts["path_name"] == "ambient_cognition"

    @pytest.mark.asyncio
    async def test_paths_are_independent(self, fake_redis):
        from app.services.legacy_path_counters import get_counts, record_target_path

        await record_target_path("ambient_cognition")

        other = await get_counts("some_other_path", days=1)
        assert other["target"] == 0
        assert other["legacy"] == 0

    @pytest.mark.asyncio
    async def test_invalid_lane_rejected(self, fake_redis):
        from app.services.legacy_path_counters import _record

        with pytest.raises(ValueError):
            await _record("ambient_cognition", "sideways")


# ==========================================
# Real wiring: kernel target-path, autonomy legacy-path
# ==========================================

class TestPathCounterWiring:
    @pytest.mark.asyncio
    async def test_ambient_turn_records_target_path_before_short_circuiting(self, monkeypatch):
        """ambient_turn should count itself as the target path even when the
        exclusive-group lock is busy and it returns early — the count is about
        *reaching the kernel*, not about completing a full deliberation."""
        from app.services import kernel
        import app.services.autonomy.coordination as coordination
        import app.services.legacy_path_counters as counters

        fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

        async def _fake_get_redis():
            return fake

        monkeypatch.setattr(counters, "_get_redis", _fake_get_redis)

        class _BusyCoordinator:
            async def acquire_exclusive(self, *a, **kw):
                return False

            async def release_exclusive(self, *a, **kw):
                pass

        monkeypatch.setattr(coordination, "get_coordinator", lambda: _BusyCoordinator())

        result = await kernel.ambient_turn("user-1")

        assert result["skipped"] == "exclusive_group_busy"
        counts = await counters.get_counts("ambient_cognition", days=1)
        assert counts["target"] == 1
        assert counts["legacy"] == 0
