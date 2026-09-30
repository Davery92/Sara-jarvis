"""Fail-closed guard against pytest ever touching production Postgres/Redis.

2026-09-22 incident: a full-suite pytest run inside `jarvis-backend-1` used
the container's ambient `DATABASE_URL`/`REDIS_URL`, which pointed at the
live production database and Redis instance (there was no separate test
target configured at all). `_pg.py`-suffixed integration tests are, by
design, meant to run against a real Postgres — but "real" must mean a
disposable one, never THE one. See `docs/plans/incidents/
2026-09-22_test_run_against_live_db.md`.

This module is imported as the FIRST statement in `conftest.py`, before any
`app.*` import (conftest.py used to `from app.main_simple import Base` as
line 1 of its own imports — that alone was already enough to start pulling
in application modules before any safety check ran). It must therefore have
zero dependency on `app.*` or any third-party package beyond the stdlib, so
it can run before those imports and before application startup/import-time
side effects have any chance to fire.

Deliberately lexical, not connective: this NEVER opens a socket. Checking
"is this production" by trying to connect to it would recreate exactly the
risk this guard exists to prevent, and the instruction that prompted this
module is explicit that rejection must be provable without opening a
connection. Everything here is string/env inspection only.

Three independent signals must ALL agree this is the disposable test stack
before a real DATABASE_URL/REDIS_URL is allowed through. Any one missing,
or any one looking production-shaped, fails closed:
  1. An explicit test-environment marker env var (SARA_TEST_ENV).
  2. Credentials distinct from production's.
  3. A hostname on the isolated-stack allowlist — not production's compose
     service name, not its LAN IP, not "localhost" pointing at a forwarded
     production port.

A DATABASE_URL/REDIS_URL that isn't postgres/redis-shaped at all (unset,
or sqlite) is a no-op here — ordinary mocked unit tests must keep working
without needing to set SARA_TEST_ENV for no reason.
"""
import os
import re

REQUIRED_MARKER_VALUE = "disposable"

# Known production identifiers — reject on ANY of these regardless of what
# else is set, even if someone later adds "disposable" markers around a
# genuine production URL by mistake.
_PROD_DB_HOST_MARKERS = frozenset({"10.185.1.180", "jarvis-db-1", "db"})
_PROD_DB_USER = "sara"
_PROD_DB_NAME = "sara_hub"
_PROD_REDIS_HOST_MARKERS = frozenset({"jarvis-redis-1", "redis"})

# Disposable databases whose names predate this guard and cannot carry a "test"
# marker (2026-09-30). `tests/replay/harness.py` hard-requires the database to
# be named exactly `sara_replay` — it refuses to run against anything else, as
# its own protection against replaying over live data. That made the name rule
# below and the replay suite mutually exclusive: `pytest tests/replay` could not
# run on ANY host, which is how it was found.
#
# This exempts the NAME only. All three independent signals still apply to it:
# SARA_TEST_ENV must be "disposable", the host must be on the test allowlist,
# and the user must not be the production credential. Production remains
# rejected three ways over (host `db`/10.185.1.180, user `sara`, name
# `sara_hub`), and so does a replay pointed at the production server — which is
# the real hazard here, since `tests/replay/provision.py` builds `sara_replay`
# on the production Postgres by default.
_KNOWN_DISPOSABLE_DB_NAMES = frozenset({"sara_replay"})

# The isolated test stack's own compose network — see docker-compose.test.yml.
_TEST_DB_HOST_ALLOW = re.compile(r"^(test-db|localhost|127\.0\.0\.1)$")
_TEST_REDIS_HOST_ALLOW = re.compile(r"^(test-redis|localhost|127\.0\.0\.1)$")

_URL_RE = re.compile(
    r"^[a-zA-Z0-9+]+://(?:([^:/@]+)(?::[^@]*)?@)?([^:/]+)(?::(\d+))?/(.*)$"
)


class UnsafeTestEnvironment(RuntimeError):
    """Raised when the configured DATABASE_URL/REDIS_URL is not provably
    the disposable test stack. Never caught — this must abort collection."""


def _parse(url: str):
    m = _URL_RE.match(url or "")
    if not m:
        return None
    user, host, _port, name = m.groups()
    return {"user": user, "host": host, "name": name}


def assert_disposable_test_environment() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    redis_url = os.environ.get("REDIS_URL", "")

    touches_real_db = database_url.startswith("postgresql")
    touches_real_redis = redis_url.startswith("redis")

    if not touches_real_db and not touches_real_redis:
        return  # sqlite / unset — ordinary mocked unit tests, nothing to gate

    problems = []
    marker = os.environ.get("SARA_TEST_ENV", "")
    if marker != REQUIRED_MARKER_VALUE:
        problems.append(
            f"SARA_TEST_ENV must equal {REQUIRED_MARKER_VALUE!r} to run "
            f"tests against a real DATABASE_URL/REDIS_URL; got {marker!r}. "
            "Use docker-compose.test.yml, which sets this."
        )

    if touches_real_db:
        db = _parse(database_url)
        if db is None:
            problems.append(f"DATABASE_URL could not be parsed: {database_url!r}")
        else:
            if (db["host"] or "") in _PROD_DB_HOST_MARKERS:
                problems.append(
                    f"DATABASE_URL host {db['host']!r} matches a known PRODUCTION host."
                )
            elif not _TEST_DB_HOST_ALLOW.match(db["host"] or ""):
                problems.append(
                    f"DATABASE_URL host {db['host']!r} is not on the disposable-test "
                    f"allowlist {_TEST_DB_HOST_ALLOW.pattern!r}."
                )
            if db["user"] == _PROD_DB_USER:
                problems.append(
                    f"DATABASE_URL user {db['user']!r} matches the PRODUCTION credential."
                )
            if db["name"] == _PROD_DB_NAME:
                problems.append(
                    f"DATABASE_URL database name {db['name']!r} matches the PRODUCTION database."
                )
            if db["name"] and "test" not in db["name"] \
                    and db["name"] not in _KNOWN_DISPOSABLE_DB_NAMES:
                problems.append(
                    f"DATABASE_URL database name {db['name']!r} carries no 'test' "
                    f"marker and is not one of the known-disposable names "
                    f"{sorted(_KNOWN_DISPOSABLE_DB_NAMES)}."
                )

    if touches_real_redis:
        rd = _parse(redis_url)
        if rd is None:
            problems.append(f"REDIS_URL could not be parsed: {redis_url!r}")
        else:
            if (rd["host"] or "") in _PROD_REDIS_HOST_MARKERS:
                problems.append(
                    f"REDIS_URL host {rd['host']!r} matches a known PRODUCTION host."
                )
            elif not _TEST_REDIS_HOST_ALLOW.match(rd["host"] or ""):
                problems.append(
                    f"REDIS_URL host {rd['host']!r} is not on the disposable-test "
                    f"allowlist {_TEST_REDIS_HOST_ALLOW.pattern!r}."
                )

    if problems:
        raise UnsafeTestEnvironment(
            "Refusing to collect/run: the configured DATABASE_URL/REDIS_URL "
            "does not provably point at the disposable test stack.\n- "
            + "\n- ".join(problems)
            + "\n\nRun tests via docker-compose.test.yml instead, e.g.:\n"
            "  docker compose -f docker-compose.test.yml up -d --wait test-db test-redis\n"
            "  docker compose -f docker-compose.test.yml run --rm backend-test "
            "pytest tests/\n"
        )
