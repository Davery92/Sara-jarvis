"""Step 17 of FITNESS_COACH_IMPLEMENTATION_PLAN, against a real database.

The gate this file exists to prove: **the state API and a direct collection
over the same as-of period produce the same numbers.** If they can disagree,
then the dashboard, the chat capsule and a stored review input are three
different answers to one question, which is the condition Step 18 is about
to consolidate away.

Also here, because they can only be shown with real rows:

* the period end is exclusive and athlete-local, so a partial current day is
  never averaged in — and moving the athlete's timezone moves which readings
  fall in the window;
* the `/state` route is owner-scoped end to end, driven with two real JWTs;
* a backdated correction changes the data revision, which is what bounds a
  missed cache invalidation;
* a database failure produces a DEGRADED state, not an empty one.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_state_api_pg.py
"""
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
)

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
TODAY = date(2026, 10, 1)


def lb(kg: float) -> float:
    """The canonical stored unit for `weight` is POUNDS.

    `LEGACY_METRIC_UNITS` pins it there because the iOS app, the dashboard
    and `weight_trend` were all already written against pounds. Ingest
    accepts kg and converts; the state reports the canonical unit. Asserting
    in kg here would be asserting against a conversion this module does not
    do.
    """
    from app.schemas.fitness_coach import Unit, convert
    return convert(kg, Unit.KG, Unit.LB)


@pytest.fixture
def pg():
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def two_athletes(pg):
    unusable_hash = "$2b$12$" + "x" * 53
    alice = f"s7a-{uuid.uuid4().hex[:18]}"
    bob = f"s7b-{uuid.uuid4().hex[:18]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@s17.invalid", "p": unusable_hash})
    pg.commit()
    yield alice, bob
    pg.rollback()
    for table in ("health_metric", "food_log", "daily_recovery_log",
                  "weight_trend", "workout_log", "fitness_athlete_goal",
                  "fitness_athlete_limitation", "fitness_target_revision",
                  "fitness_athlete_profile", "fitness_phase", "fitness_program",
                  "fitness_goals", "world_event"):
        try:
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                       {"ids": [alice, bob]})
        except Exception:
            pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"),
               {"ids": [alice, bob]})
    pg.commit()


@pytest.fixture
def client():
    """Only the coach router, so the monolith's startup hooks stay out of it
    while the real dependency chain (`current_athlete` → `get_current_user` →
    token → `revoked_token`) is still what a request walks."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes.fitness_coach import router

    app = FastAPI()
    app.include_router(router, prefix="/api/fitness/coach")
    return TestClient(app)


def _bearer(user_id: str) -> dict:
    from app.core.auth import create_access_token
    return {"Authorization": f"Bearer {create_access_token({'sub': user_id})}"}


def _weigh_in(pg, user_id, day: date, kg: float, *, hour: int = 7):
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import ingest_observation
    result = ingest_observation(
        pg, user_id, metric_type="weight", value=kg, unit=Unit.KG,
        recorded_at=datetime(day.year, day.month, day.day, hour, 0, tzinfo=ET),
        source="manual", timezone_name="America/New_York",
    )
    pg.commit()
    return result


def _profile(pg, user_id, timezone_name="America/New_York"):
    from app.schemas.fitness_coach import AthleteProfilePatch
    from app.services.fitness.profile import patch_athlete_profile
    return patch_athlete_profile(
        pg, user_id, AthleteProfilePatch(timezone=timezone_name),
    )


# ─────────────────────────────────────────────────────────────────────────
# The gate: the API and a direct collection agree
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_api_and_a_direct_collection_report_the_same_numbers(
    pg, two_athletes, client,
):
    """The Step 17 gate.

    If these can differ, then the dashboard, the capsule and a stored review
    input are three answers to one question — and nothing in the system says
    which is right.
    """
    from app.services.fitness.state import build_fitness_state

    alice, _ = two_athletes
    _profile(pg, alice)
    for offset in range(1, 8):
        _weigh_in(pg, alice, TODAY - timedelta(days=offset), 81.0 + offset * 0.1)

    direct = build_fitness_state(
        pg, alice, period_end=TODAY, span=7, fresh=True, redis_client=None,
    )
    response = client.get(
        "/api/fitness/coach/state",
        params={"period_end": TODAY.isoformat(), "span": 7, "fresh": True},
        headers=_bearer(alice),
    )
    assert response.status_code == 200
    served = response.json()

    assert served["period"]["start"] == direct.period.start.isoformat()
    assert served["period"]["end"] == direct.period.end.isoformat()

    from app.schemas.fitness_coach import StateSection

    api_weight = served["sections"]["weight"]["metrics"]
    for name, metric in direct.sections[StateSection.WEIGHT].metrics.items():
        assert name in api_weight, f"{name} missing from the API's weight section"
        served_metric = api_weight[name]
        if metric.value is None:
            assert served_metric["value"] is None
        else:
            assert served_metric["value"] == pytest.approx(metric.value)
        assert served_metric["observed_days"] == metric.observed_days
        assert served_metric["unavailable_reason"] == (
            metric.unavailable_reason.value if metric.unavailable_reason else None
        )

    assert served["quality"]["observed_weight_days"] == \
        direct.quality.observed_weight_days
    assert served["quality"]["missing_fields"] == direct.quality.missing_fields


@requires_pg
def test_the_analytics_endpoint_matches_the_same_section_of_the_state(
    pg, two_athletes, client,
):
    alice, _ = two_athletes
    _profile(pg, alice)
    for offset in range(1, 8):
        _weigh_in(pg, alice, TODAY - timedelta(days=offset), 81.0)

    whole = client.get(
        "/api/fitness/coach/state",
        params={"period_end": TODAY.isoformat(), "span": 7, "fresh": True},
        headers=_bearer(alice),
    ).json()
    section = client.get(
        "/api/fitness/coach/analytics/weight",
        params={"period_end": TODAY.isoformat(), "span": 7},
        headers=_bearer(alice),
    )
    assert section.status_code == 200
    assert section.json()["metrics"] == whole["sections"]["weight"]["metrics"]


@requires_pg
def test_the_quality_endpoint_matches_the_states_quality(pg, two_athletes, client):
    alice, _ = two_athletes
    _profile(pg, alice)
    _weigh_in(pg, alice, TODAY - timedelta(days=2), 81.0)

    whole = client.get(
        "/api/fitness/coach/state",
        params={"period_end": TODAY.isoformat(), "fresh": True},
        headers=_bearer(alice),
    ).json()
    quality = client.get(
        "/api/fitness/coach/quality",
        params={"period_end": TODAY.isoformat()},
        headers=_bearer(alice),
    )
    assert quality.status_code == 200
    assert quality.json() == whole["quality"]


# ─────────────────────────────────────────────────────────────────────────
# The period is exclusive and athlete-local
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_current_day_is_excluded_from_a_completed_period(pg, two_athletes):
    """A partial day drags an average toward whatever happened before noon.

    The exclusive end is what makes "last week" mean seven finished days.
    """
    from app.schemas.fitness_coach import StateSection, Unit
    from app.services.fitness.state import build_fitness_state

    alice, _ = two_athletes
    _profile(pg, alice)
    for offset in range(1, 8):
        _weigh_in(pg, alice, TODAY - timedelta(days=offset), 81.0)
    _weigh_in(pg, alice, TODAY, 95.0)  # today, and wildly different

    state = build_fitness_state(
        pg, alice, period_end=TODAY, span=7, fresh=True, redis_client=None,
    )
    mean = state.sections[StateSection.WEIGHT].metrics["mean_7d"]
    assert mean.value == pytest.approx(lb(81.0), abs=0.01)
    assert mean.unit is Unit.LB
    assert mean.observed_days == 7


@requires_pg
def test_the_athletes_timezone_decides_which_day_a_reading_belongs_to(
    pg, two_athletes,
):
    """A 22:00 ET reading is the same day in ET and the NEXT day in UTC.

    Resolving the day in the wrong zone silently moves readings across the
    window boundary, which changes both the mean and the coverage count.
    """
    from app.schemas.fitness_coach import StateSection, Unit
    from app.services.fitness.observations import ingest_observation
    from app.services.fitness.state import build_fitness_state

    alice, _ = two_athletes
    _profile(pg, alice, "America/New_York")
    # 2026-09-30 22:30 ET == 2026-10-01 02:30 UTC.
    ingest_observation(
        pg, alice, metric_type="weight", value=81.0, unit=Unit.KG,
        recorded_at=datetime(2026, 9, 30, 22, 30, tzinfo=ET),
        source="manual", timezone_name="America/New_York",
    )
    pg.commit()

    state = build_fitness_state(
        pg, alice, period_end=TODAY, span=7, fresh=True, redis_client=None,
    )
    latest = state.sections[StateSection.WEIGHT].metrics["latest"]
    assert latest.value == pytest.approx(lb(81.0), abs=0.01), (
        "the reading fell outside the window, so its day was resolved in the "
        "wrong timezone"
    )
    assert state.timezone == "America/New_York"


@requires_pg
def test_the_state_defaults_to_the_athletes_today_not_the_servers(pg, two_athletes):
    from app.services.fitness.profile import athlete_today
    from app.services.fitness.state import build_fitness_state

    alice, _ = two_athletes
    _profile(pg, alice, "Pacific/Auckland")
    state = build_fitness_state(pg, alice, fresh=True, redis_client=None)
    assert state.timezone == "Pacific/Auckland"
    assert state.athlete_local_date == athlete_today(pg, alice)


# ─────────────────────────────────────────────────────────────────────────
# Owner scope
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_one_athletes_token_never_returns_anothers_state(pg, two_athletes, client):
    alice, bob = two_athletes
    _profile(pg, alice)
    _profile(pg, bob)
    _weigh_in(pg, alice, TODAY - timedelta(days=1), 81.0)

    served = client.get(
        "/api/fitness/coach/state",
        params={"period_end": TODAY.isoformat(), "fresh": True},
        headers=_bearer(bob),
    ).json()

    assert served["user_id"] == bob
    latest = served["sections"]["weight"]["metrics"]["latest"]
    assert latest["value"] is None, "Bob was served Alice's weight"
    assert latest["unavailable_reason"] == "no_data"


@requires_pg
def test_an_unauthenticated_request_gets_no_state(client):
    for path in ("/api/fitness/coach/state", "/api/fitness/coach/quality",
                 "/api/fitness/coach/capsule",
                 "/api/fitness/coach/analytics/weight"):
        assert client.get(path).status_code in (401, 403), path


@requires_pg
def test_the_cache_is_never_shared_between_two_athletes(pg, two_athletes):
    """Keyed on the owner, and the owner is in the literal key prefix. A
    collision here would hand one athlete another's body numbers."""
    from app.services.fitness.state import build_fitness_state

    class Recorder(dict):
        def __init__(self):
            super().__init__()
            self.keys_written = []

        def get(self, key):
            return super().get(key)

        def setex(self, key, ttl, value):
            self.keys_written.append(key)
            self[key] = value

    alice, bob = two_athletes
    _profile(pg, alice)
    _profile(pg, bob)
    _weigh_in(pg, alice, TODAY - timedelta(days=1), 81.0)
    _weigh_in(pg, bob, TODAY - timedelta(days=1), 65.0)

    cache = Recorder()
    a_state = build_fitness_state(pg, alice, period_end=TODAY,
                                  redis_client=cache)
    b_state = build_fitness_state(pg, bob, period_end=TODAY,
                                  redis_client=cache)

    assert len(set(cache.keys_written)) == 2
    from app.schemas.fitness_coach import StateSection
    assert a_state.sections[StateSection.WEIGHT].metrics["latest"].value \
        == pytest.approx(lb(81.0), abs=0.01)
    assert b_state.sections[StateSection.WEIGHT].metrics["latest"].value \
        == pytest.approx(lb(65.0), abs=0.01)


# ─────────────────────────────────────────────────────────────────────────
# Cache behaviour against real data
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_second_identical_read_is_served_from_the_cache(pg, two_athletes):
    from app.services.fitness.state import build_fitness_state

    class Counting(dict):
        def __init__(self):
            super().__init__()
            self.hits = 0

        def get(self, key):
            value = super().get(key)
            if value is not None:
                self.hits += 1
            return value

        def setex(self, key, ttl, value):
            self[key] = value

    alice, _ = two_athletes
    _profile(pg, alice)
    _weigh_in(pg, alice, TODAY - timedelta(days=1), 81.0)

    cache = Counting()
    first = build_fitness_state(pg, alice, period_end=TODAY, redis_client=cache)
    second = build_fitness_state(pg, alice, period_end=TODAY, redis_client=cache)

    assert cache.hits == 1
    assert first.model_dump_json() == second.model_dump_json()


@requires_pg
def test_fresh_bypasses_the_cache_entirely(pg, two_athletes):
    """A stored review input must be reproducible from records. One
    assembled from a cache could not be."""
    from app.services.fitness.state import build_fitness_state

    class Counting(dict):
        def __init__(self):
            super().__init__()
            self.gets = 0

        def get(self, key):
            self.gets += 1
            return super().get(key)

        def setex(self, key, ttl, value):
            self[key] = value

    alice, _ = two_athletes
    _profile(pg, alice)
    _weigh_in(pg, alice, TODAY - timedelta(days=1), 81.0)

    cache = Counting()
    build_fitness_state(pg, alice, period_end=TODAY, redis_client=cache)
    gets_after_first = cache.gets
    build_fitness_state(pg, alice, period_end=TODAY, redis_client=cache,
                        fresh=True)
    assert cache.gets == gets_after_first, "fresh=True still read the cache"


@requires_pg
def test_a_backdated_correction_changes_the_data_revision(pg, two_athletes):
    """This is what bounds a missed invalidation.

    A correction to last Tuesday changes the fingerprint in the cache key, so
    the stale entry becomes unreachable rather than needing to be found and
    deleted.
    """
    from app.services.fitness.data_access import data_revision
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import ingest_observation

    alice, _ = two_athletes
    _profile(pg, alice)
    first = _weigh_in(pg, alice, TODAY - timedelta(days=5), 81.0)
    before = data_revision(pg, alice)

    ingest_observation(
        pg, alice, metric_type="weight", value=80.4, unit=Unit.KG,
        recorded_at=datetime(2026, 9, 26, 7, 1, tzinfo=ET),
        source="manual", timezone_name="America/New_York",
        corrects_observation_id=first.observation_id,
        correction_reason="misread the scale",
    )
    pg.commit()

    assert data_revision(pg, alice) != before


@requires_pg
def test_a_new_write_makes_the_previous_cache_entry_unreachable(pg, two_athletes):
    from app.services.fitness.state import build_fitness_state

    class Store(dict):
        def get(self, key):
            return super().get(key)

        def setex(self, key, ttl, value):
            self[key] = value

    alice, _ = two_athletes
    _profile(pg, alice)
    _weigh_in(pg, alice, TODAY - timedelta(days=3), 81.0)

    cache = Store()
    build_fitness_state(pg, alice, period_end=TODAY, redis_client=cache)
    assert len(cache) == 1
    first_key = next(iter(cache))

    _weigh_in(pg, alice, TODAY - timedelta(days=1), 80.5)
    fresh = build_fitness_state(pg, alice, period_end=TODAY, redis_client=cache)

    assert len(cache) == 2, "the new write reused the previous cache key"
    from app.schemas.fitness_coach import StateSection
    assert fresh.sections[StateSection.WEIGHT].metrics["latest"].value \
        == pytest.approx(lb(80.5), abs=0.01)
    assert first_key in cache  # stale, but unreachable


@requires_pg
def test_a_redis_outage_does_not_break_the_state(pg, two_athletes, client):
    """A cache failure costs a recompute. It must not surface as a failed
    read of the athlete's own records."""
    alice, _ = two_athletes
    _profile(pg, alice)
    _weigh_in(pg, alice, TODAY - timedelta(days=1), 81.0)

    import app.routes.fitness_coach as route_module

    class Broken:
        def get(self, key):
            raise ConnectionError("redis is down")

        def setex(self, *a, **k):
            raise ConnectionError("redis is down")

    original = route_module._state_cache
    route_module._state_cache = lambda: Broken()
    try:
        response = client.get(
            "/api/fitness/coach/state",
            params={"period_end": TODAY.isoformat()},
            headers=_bearer(alice),
        )
    finally:
        route_module._state_cache = original

    assert response.status_code == 200
    served = response.json()
    assert served["freshness"] == "fresh"
    assert served["sections"]["weight"]["metrics"]["latest"]["value"] \
        == pytest.approx(lb(81.0), abs=0.01)


# ─────────────────────────────────────────────────────────────────────────
# A dependency failure degrades
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_broken_section_query_degrades_rather_than_emptying_the_state(
    pg, two_athletes, monkeypatch,
):
    """"A database failure isn't an empty data set" (§17.5).

    The weight history is still true when the pain query is broken, and the
    pain section's absence must be labelled as an outage rather than read as
    "no pain reported".
    """
    from app.schemas.fitness_coach import Freshness, StateSection
    from app.services.fitness import state as state_module

    alice, _ = two_athletes
    _profile(pg, alice)
    _weigh_in(pg, alice, TODAY - timedelta(days=1), 81.0)

    def broken(*args, **kwargs):
        raise RuntimeError("relation does not exist")

    monkeypatch.setattr(state_module, "_pain_group", broken)
    state = state_module.build_fitness_state(
        pg, alice, period_end=TODAY, fresh=True, redis_client=None,
    )

    assert state.freshness is Freshness.DEGRADED
    assert "pain" in state.degraded_dependencies
    # And the sections that worked are still there and still right.
    assert state.sections[StateSection.WEIGHT].metrics["latest"].value \
        == pytest.approx(lb(81.0), abs=0.01)


@requires_pg
def test_a_degraded_state_is_never_cached(pg, two_athletes, monkeypatch):
    """Caching it would serve an outage as current for the whole TTL."""
    from app.services.fitness import state as state_module

    class Store(dict):
        def get(self, key):
            return super().get(key)

        def setex(self, key, ttl, value):
            self[key] = value

    alice, _ = two_athletes
    _profile(pg, alice)
    monkeypatch.setattr(state_module, "_weight_group",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))

    cache = Store()
    state = state_module.build_fitness_state(
        pg, alice, period_end=TODAY, redis_client=cache,
    )
    assert state.degraded_dependencies == ["weight"]
    assert cache == {}


# ─────────────────────────────────────────────────────────────────────────
# Sections, bounds and the capsule
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_narrowing_sections_changes_what_is_present_not_what_it_says(
    pg, two_athletes,
):
    from app.schemas.fitness_coach import StateSection
    from app.services.fitness.state import build_fitness_state

    alice, _ = two_athletes
    _profile(pg, alice)
    for offset in range(1, 8):
        _weigh_in(pg, alice, TODAY - timedelta(days=offset), 81.0 + offset * 0.1)

    whole = build_fitness_state(pg, alice, period_end=TODAY, fresh=True,
                                redis_client=None)
    narrow = build_fitness_state(pg, alice, period_end=TODAY, fresh=True,
                                 sections=[StateSection.WEIGHT],
                                 redis_client=None)

    assert set(narrow.sections) == {StateSection.WEIGHT}
    assert len(whole.sections) > 1
    assert narrow.sections[StateSection.WEIGHT].metrics["mean_7d"].value == \
        pytest.approx(whole.sections[StateSection.WEIGHT].metrics["mean_7d"].value)


@requires_pg
def test_an_unknown_section_name_is_a_422_not_a_silent_empty_state(
    two_athletes, client,
):
    alice, _ = two_athletes
    response = client.get(
        "/api/fitness/coach/state", params={"sections": "weihgt"},
        headers=_bearer(alice),
    )
    assert response.status_code == 422
    assert "weihgt" in str(response.json()["detail"]) or \
        "Unknown section" in str(response.json()["detail"])


@requires_pg
def test_the_span_is_a_real_bound(two_athletes, client):
    """An unbounded window over a multi-year history is the request shape
    that takes a shared database down."""
    alice, _ = two_athletes
    assert client.get("/api/fitness/coach/state", params={"span": 4000},
                      headers=_bearer(alice)).status_code == 422
    assert client.get("/api/fitness/coach/state", params={"span": 0},
                      headers=_bearer(alice)).status_code == 422
    assert client.get("/api/fitness/coach/state", params={"span": 90},
                      headers=_bearer(alice)).status_code == 200


@requires_pg
def test_the_capsule_endpoint_stays_within_its_budget(pg, two_athletes, client):
    alice, _ = two_athletes
    _profile(pg, alice)
    for offset in range(1, 15):
        _weigh_in(pg, alice, TODAY - timedelta(days=offset), 81.0)

    response = client.get(
        "/api/fitness/coach/capsule", params={"char_budget": 400},
        headers=_bearer(alice),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["chars"] <= 400
    assert len(body["capsule"]) == body["chars"]
    assert body["freshness"] == "fresh"


# ─────────────────────────────────────────────────────────────────────────
# Events and invalidation
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def world_events_on(monkeypatch):
    """The disposable stack ships `WORLD_EVENTS_ENABLED=0`.

    That is right for the stack — most tests should not accumulate event
    rows — but these tests are specifically about the events, so they turn
    it on. `_enabled()` reads the environment per call, so this is enough.
    """
    monkeypatch.setenv("WORLD_EVENTS_ENABLED", "true")


@requires_pg
def test_an_observation_writes_a_thin_event_carrying_no_body_number(
    pg, two_athletes, world_events_on,
):
    """A world fact is a wider surface than an owned fitness row. The event
    says a weight was recorded; the number stays where the health authority
    rules reach it."""
    alice, _ = two_athletes
    _profile(pg, alice)
    result = _weigh_in(pg, alice, TODAY - timedelta(days=1), 81.4)

    row = pg.execute(text("""
        SELECT kind, payload::text AS body, source_ref, sensitivity
        FROM world_event
        WHERE user_id = :uid AND kind = 'fitness.observation_ingested'
    """), {"uid": alice}).fetchone()
    assert row is not None, "no event was appended for the observation"
    assert row.source_ref == result.observation_id
    assert "81.4" not in row.body, "the event carried the body measurement"
    assert "179" not in row.body, "the event carried the converted measurement"
    assert "weight" in row.body
    assert row.sensitivity == "health", (
        "a body observation event must inherit health sensitivity"
    )


@requires_pg
def test_the_observation_event_is_not_sent_to_the_interpreter(world_events_on):
    """The interpreter's job is finding obligations in text. Pointed at body
    numbers it invents a due date nobody set — the Laura failure, in a worse
    place, because a weight reading is not a commitment."""
    from app.services.world_state.catalog import get_spec

    for kind in ("fitness.observation_ingested", "fitness.check_in_logged",
                 "fitness.measurement_logged", "fitness.goal_changed",
                 "fitness.target_changed", "fitness.limitation_changed"):
        spec = get_spec(kind)
        assert spec.interpret is False, f"{kind} is routed to the interpreter"
        assert spec.sensitivity == "health", f"{kind} is not marked health"
        assert spec.slice_name == "fitness_health", f"{kind} lands in {spec.slice_name}"


@requires_pg
def test_a_backdated_correction_says_which_day_moved(pg, two_athletes,
                                                     world_events_on):
    """A consumer has to be able to tell an OLD day changing from a new one
    arriving, and `logical_date` is the only thing that says which."""
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import ingest_observation

    alice, _ = two_athletes
    _profile(pg, alice)
    first = _weigh_in(pg, alice, date(2026, 9, 24), 81.0)

    ingest_observation(
        pg, alice, metric_type="weight", value=80.4, unit=Unit.KG,
        recorded_at=datetime(2026, 9, 24, 7, 1, tzinfo=ET),
        source="manual", timezone_name="America/New_York",
        corrects_observation_id=first.observation_id,
        correction_reason="misread the scale",
    )
    pg.commit()

    rows = pg.execute(text("""
        SELECT payload::text AS body FROM world_event
        WHERE user_id = :uid AND kind = 'fitness.observation_ingested'
        ORDER BY sequence
    """), {"uid": alice}).fetchall()
    assert len(rows) == 2
    assert '"is_correction": true' in rows[1].body.lower()
    assert "2026-09-24" in rows[1].body


@requires_pg
def test_the_event_commits_with_the_record_it_describes(pg, two_athletes,
                                                       world_events_on):
    """An event about a weigh-in that was rolled back would make a consumer
    reason about a reading that does not exist."""
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import ingest_observation

    alice, _ = two_athletes
    ingest_observation(
        pg, alice, metric_type="weight", value=81.0, unit=Unit.KG,
        recorded_at=datetime(2026, 9, 29, 7, 0, tzinfo=ET),
        source="manual", timezone_name="America/New_York",
    )
    pg.rollback()

    assert pg.execute(text("""
        SELECT COUNT(*) FROM world_event
        WHERE user_id = :uid AND kind = 'fitness.observation_ingested'
    """), {"uid": alice}).scalar() == 0
    assert pg.execute(text("""
        SELECT COUNT(*) FROM health_metric WHERE user_id = :uid
    """), {"uid": alice}).scalar() == 0


@requires_pg
def test_a_failed_event_append_does_not_lose_the_observation(
    pg, two_athletes, monkeypatch, world_events_on,
):
    """The record is load-bearing; the bookkeeping row is not.

    The SAVEPOINT in `record_fitness_event` is what keeps a failed append
    from poisoning the transaction and taking the weigh-in down at commit.
    """
    from app.schemas.fitness_coach import Unit
    from app.services.fitness import observations as obs_module
    from app.services.world_state import writer as writer_module

    alice, _ = two_athletes

    def exploding(db, **kwargs):
        # Fails the way a real bad statement does: inside the savepoint
        # `record_fitness_event` opened.
        db.execute(text("SELECT * FROM a_table_that_does_not_exist"))

    monkeypatch.setattr(writer_module, "append_world_event", exploding)
    result = obs_module.ingest_observation(
        pg, alice, metric_type="weight", value=81.0, unit=Unit.KG,
        recorded_at=datetime(2026, 9, 28, 7, 0, tzinfo=ET),
        source="manual", timezone_name="America/New_York",
    )
    pg.commit()

    assert result.stored
    assert pg.execute(text("""
        SELECT COUNT(*) FROM health_metric WHERE id = :id
    """), {"id": result.observation_id}).scalar() == 1


@requires_pg
def test_a_private_value_in_an_event_payload_is_dropped(pg, two_athletes,
                                                        world_events_on):
    """Checked rather than trusted. The cost of a mistake is a body
    measurement in a lower-sensitivity store, which is not something code
    review catches every time."""
    from app.services.fitness.events import record_fitness_event

    alice, _ = two_athletes
    record_fitness_event(
        pg, alice, "fitness.observation_ingested",
        dedupe_key=f"leak-test:{uuid.uuid4().hex}",
        payload={"metric_type": "weight", "value": 81.4, "hrv": 62},
    )
    pg.commit()

    body = pg.execute(text("""
        SELECT payload::text AS body FROM world_event
        WHERE user_id = :uid ORDER BY sequence DESC LIMIT 1
    """), {"uid": alice}).fetchone().body
    assert "81.4" not in body
    assert "62" not in body
    assert "weight" in body


@requires_pg
def test_a_goal_change_is_announced_with_its_basis_and_no_body_numbers(
    pg, two_athletes, world_events_on,
):
    from app.schemas.fitness_coach import AthleteGoalIn, GoalKind, RateBasis
    from app.services.fitness.profile import create_goal

    alice, _ = two_athletes
    goal = create_goal(pg, alice, AthleteGoalIn(
        kind=GoalKind.CUT, rate_basis=RateBasis.ABSOLUTE,
        target_rate_kg_week=-0.4, valid_from=date(2026, 9, 1),
    ))

    row = pg.execute(text("""
        SELECT payload::text AS body, sensitivity FROM world_event
        WHERE user_id = :uid AND kind = 'fitness.goal_changed'
          AND source_ref = :gid
    """), {"uid": alice, "gid": goal.id}).fetchone()
    assert row is not None
    assert "cut" in row.body
    assert "absolute" in row.body
    # The prescribed rate's BASIS travels; the athlete's current weight and
    # their written rationale do not.
    assert "target_weight" not in row.body
    assert "rationale" not in row.body
    assert row.sensitivity == "health"


@requires_pg
def test_a_target_revision_is_announced_without_restating_the_macros(
    pg, two_athletes, world_events_on,
):
    """A consumer resolves the values through the resolver, so there is one
    answer to "what were my calories on the 14th" rather than two."""
    from app.schemas.fitness_coach import TargetRevisionIn, TargetScope, TargetValues
    from app.services.fitness.targets import create_target_revision

    alice, _ = two_athletes
    revision = create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=date(2026, 9, 1),
        training=TargetValues(calories=3000, protein_g=200),
    ))

    row = pg.execute(text("""
        SELECT payload::text AS body, source_ref FROM world_event
        WHERE user_id = :uid AND kind = 'fitness.target_changed'
    """), {"uid": alice}).fetchone()
    assert row is not None
    assert row.source_ref == revision.id
    assert "3000" not in row.body, (
        "the event restated the macro values; a consumer must resolve them"
    )
    assert "default" in row.body


@requires_pg
def test_invalidation_fires_after_the_commit_not_before(pg, two_athletes,
                                                        monkeypatch):
    """Dropping the cache BEFORE the commit lets a concurrent reader
    repopulate it from the pre-commit view — the invalidation fires and
    still leaves a stale entry behind."""
    from app.core import redis as redis_module
    from app.services.fitness import state as state_module
    from app.services.fitness.events import _INVALIDATE_INFO_KEY, queue_invalidation

    alice, _ = two_athletes
    dropped = []
    monkeypatch.setattr(redis_module, "get_redis_sync", lambda: object())
    monkeypatch.setattr(state_module, "invalidate_fitness_state",
                        lambda client, user_id: dropped.append(user_id))

    queue_invalidation(pg, alice)
    assert alice in pg.info[_INVALIDATE_INFO_KEY]
    assert dropped == [], "the cache was dropped before the commit"

    pg.commit()

    assert dropped == [alice]
    assert _INVALIDATE_INFO_KEY not in pg.info


@requires_pg
def test_a_rollback_drops_the_queued_invalidation(pg, two_athletes, monkeypatch):
    """Nothing changed, so nothing needs dropping — and an invalidation for
    a write that never happened is wasted work on every rolled-back
    request."""
    from app.core import redis as redis_module
    from app.services.fitness import state as state_module
    from app.services.fitness.events import _INVALIDATE_INFO_KEY, queue_invalidation

    alice, _ = two_athletes
    dropped = []
    monkeypatch.setattr(redis_module, "get_redis_sync", lambda: object())
    monkeypatch.setattr(state_module, "invalidate_fitness_state",
                        lambda client, user_id: dropped.append(user_id))

    queue_invalidation(pg, alice)
    # A real write, then abandon it. The rollback hook only fires when a
    # transaction was actually open, which is the case for every caller that
    # queued an invalidation because it was about to write something.
    pg.execute(text("UPDATE app_user SET email = :e WHERE id = :uid"),
               {"e": f"{alice}@rolled-back.invalid", "uid": alice})
    pg.rollback()

    assert _INVALIDATE_INFO_KEY not in pg.info
    assert dropped == []


@requires_pg
def test_a_bulk_ingest_queues_one_invalidation_not_thirty(pg, two_athletes):
    from app.services.fitness.events import _INVALIDATE_INFO_KEY, queue_invalidation

    alice, _ = two_athletes
    for _ in range(30):
        queue_invalidation(pg, alice)
    assert pg.info[_INVALIDATE_INFO_KEY] == {alice}
    pg.rollback()


@requires_pg
def test_an_invalidation_failure_never_reaches_the_caller(pg, two_athletes,
                                                          monkeypatch):
    """Redis is expendable. A failed invalidation costs the TTL, because the
    key carries a data-revision fingerprint — so it must not be able to fail
    the athlete's write."""
    from app.core import redis as redis_module
    from app.services.fitness import state as state_module
    from app.services.fitness.events import queue_invalidation

    alice, _ = two_athletes

    def boom():
        raise ConnectionError("redis is down")

    monkeypatch.setattr(redis_module, "get_redis_sync", boom)
    monkeypatch.setattr(state_module, "invalidate_fitness_state", boom)

    queue_invalidation(pg, alice)
    pg.execute(text("SELECT 1"))
    pg.commit()   # must not raise
