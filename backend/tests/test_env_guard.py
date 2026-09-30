"""Proves env_guard rejects production-shaped config and accepts the
disposable test stack's config — purely by inspecting the function's
return/raise behavior against monkeypatched environment variables. No
network connection is opened anywhere in this file (env_guard.py itself
never opens one — see its own docstring) — this is the proof requested
after the 2026-09-22 incident that rejection works without connecting."""
import pytest

from tests.env_guard import assert_disposable_test_environment, UnsafeTestEnvironment


def _clear(monkeypatch):
    for key in ("DATABASE_URL", "REDIS_URL", "SARA_TEST_ENV"):
        monkeypatch.delenv(key, raising=False)


class TestNoOpWhenNothingRealConfigured:
    def test_unset_database_and_redis_url_is_a_noop(self, monkeypatch):
        _clear(monkeypatch)
        assert_disposable_test_environment()  # must not raise

    def test_sqlite_database_url_is_a_noop_even_without_the_marker(self, monkeypatch):
        _clear(monkeypatch)
        monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
        assert_disposable_test_environment()  # ordinary unit tests must keep working


class TestRejectsProductionWithoutConnecting:
    """Each case is the EXACT production shape found during the incident
    investigation — asserted to be rejected purely by string inspection."""

    def test_rejects_the_actual_production_database_url_from_the_incident(self, monkeypatch):
        """The password value itself is irrelevant to what env_guard checks
        (host/user/db-name only) — using a placeholder here rather than the
        real one keeps the actual production credential out of source
        control. (The real credential remains on the outstanding
        rotation list — see docs/plans/incidents/2026-09-22_test_run_
        against_live_db.md — not rotated by this change.)"""
        _clear(monkeypatch)
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql+psycopg://sara:REDACTED@10.185.1.180:5432/sara_hub",
        )
        with pytest.raises(UnsafeTestEnvironment) as exc:
            assert_disposable_test_environment()
        assert "PRODUCTION" in str(exc.value)

    def test_rejects_the_compose_internal_production_hostname(self, monkeypatch):
        _clear(monkeypatch)
        monkeypatch.setenv("SARA_TEST_ENV", "disposable")
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql+psycopg://sara_test:x@db:5432/sara_hub_test"
        )
        with pytest.raises(UnsafeTestEnvironment):
            assert_disposable_test_environment()

    def test_rejects_production_credentials_even_on_an_allowlisted_host(self, monkeypatch):
        """A test-shaped host with the production username/db name is
        still refused — credentials are an independent signal, not just
        the hostname."""
        _clear(monkeypatch)
        monkeypatch.setenv("SARA_TEST_ENV", "disposable")
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql+psycopg://sara:x@test-db:5432/sara_hub"
        )
        with pytest.raises(UnsafeTestEnvironment):
            assert_disposable_test_environment()

    def test_rejects_the_production_redis_url(self, monkeypatch):
        _clear(monkeypatch)
        monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
        with pytest.raises(UnsafeTestEnvironment) as exc:
            assert_disposable_test_environment()
        assert "PRODUCTION" in str(exc.value)

    def test_rejects_a_real_target_missing_the_marker_even_if_host_and_creds_look_right(
        self, monkeypatch
    ):
        _clear(monkeypatch)
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql+psycopg://sara_test:x@test-db:5432/sara_hub_test",
        )
        # SARA_TEST_ENV deliberately not set.
        with pytest.raises(UnsafeTestEnvironment) as exc:
            assert_disposable_test_environment()
        assert "SARA_TEST_ENV" in str(exc.value)

    def test_rejects_a_database_name_with_no_test_marker(self, monkeypatch):
        _clear(monkeypatch)
        monkeypatch.setenv("SARA_TEST_ENV", "disposable")
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql+psycopg://sara_test:x@test-db:5432/some_other_db"
        )
        with pytest.raises(UnsafeTestEnvironment):
            assert_disposable_test_environment()


class TestAcceptsTheDisposableTestStack:
    def test_accepts_the_full_disposable_configuration(self, monkeypatch):
        _clear(monkeypatch)
        monkeypatch.setenv("SARA_TEST_ENV", "disposable")
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql+psycopg://sara_test:disposable_test_only_pw@test-db:5432/sara_hub_test",
        )
        monkeypatch.setenv("REDIS_URL", "redis://test-redis:6379/0")
        assert_disposable_test_environment()  # must not raise
