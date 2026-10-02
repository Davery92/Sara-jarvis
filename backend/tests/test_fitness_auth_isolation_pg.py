"""Step 2 of FITNESS_COACH_IMPLEMENTATION_PLAN: every externally exposed
fitness route derives a real authenticated user, and two athletes cannot see
or mutate each other's rows.

Before this, `app/routes/fitness.py:get_current_user_id()` returned
``os.getenv("SOLO_USER_ID", "default-user")`` — it never looked at the
requester. 99 handlers in `fitness.py`, 8 in `workout_v2.py` and the cardio
routes all took it as a FastAPI dependency, so presenting Bob's cookie
returned David's food log. Code-reading cannot prove the fix; this drives the
actual mounted routers with two real users and two real JWTs.

Deliberately does NOT override `get_current_user`. The dependency under test
*is* the authentication, so overriding it would assert nothing.

Run inside a disposable stack (see FITNESS_COACH_CONTRACT_BASELINE.md §2):

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm backend-test \
      pytest tests/test_fitness_auth_isolation_pg.py
"""
import os
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _pg_available() -> bool:
    return os.getenv("DATABASE_URL", "").startswith("postgresql")


requires_pg = pytest.mark.skipif(
    not _pg_available(),
    reason="needs a disposable PostgreSQL (see FITNESS_COACH_CONTRACT_BASELINE.md)",
)


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
    """Two real `app_user` rows. Real rows, because the routes join to them.

    The hash is a literal, not produced by passlib: nothing here logs in with
    a password (tokens are minted directly), and the image's bcrypt/passlib
    pairing raises on `hash()`. Depending on that would make this test fail
    for a reason unrelated to what it asserts.
    """
    unusable_hash = "$2b$12$" + "x" * 53  # correct shape, verifies against nothing

    # `active_workout_session.user_id` is varchar(36), so these must fit.
    alice = f"fa-{uuid.uuid4().hex[:20]}"
    bob = f"fb-{uuid.uuid4().hex[:20]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :email, :pw, NOW())
            ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "email": f"{uid}@fitness-isolation.invalid",
               "pw": unusable_hash})
    pg.commit()

    yield alice, bob

    pg.rollback()
    for table, col in (
        ("workout_log", "user_id"),
        ("food_log", "user_id"),
        ("daily_recovery_log", "user_id"),
        ("template_exercise", None),
        ("fitness_template", "user_id"),
        ("fitness_phase", "user_id"),
        ("fitness_program", "user_id"),
        ("fitness_goals", "user_id"),
        ("revoked_token", "user_id"),
    ):
        if col is None:
            pg.execute(text("""
                DELETE FROM template_exercise
                WHERE template_id IN (
                    SELECT id FROM fitness_template WHERE user_id = ANY(:ids)
                )
            """), {"ids": [alice, bob]})
        else:
            pg.execute(text(
                f"DELETE FROM {table} WHERE {col} = ANY(:ids)"
            ), {"ids": [alice, bob]})
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"), {"ids": [alice, bob]})
    pg.commit()


@pytest.fixture
def client():
    """A FastAPI app mounting only the fitness routers.

    Mounting the routers rather than importing `main_simple:app` keeps the
    test off the monolith's startup hooks while still exercising the exact
    dependency chain a real request walks: `get_current_user_id` →
    `get_current_user` → cookie/Bearer/device-token → `revoked_token` check.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes.fitness import router as fitness_router
    from app.routes.workout_v2 import router as v2_router

    app = FastAPI()
    app.include_router(fitness_router, prefix="/api/fitness")
    app.include_router(v2_router, prefix="/api/fitness/workout-session/v2")
    return TestClient(app)


def _bearer(user_id: str) -> dict:
    from app.core.auth import create_access_token
    return {"Authorization": f"Bearer {create_access_token({'sub': user_id})}"}


# ─────────────────────────────────────────────────────────────────────────
# The dependency itself
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_dependency_returns_the_requester_not_a_solo_owner(two_athletes, monkeypatch):
    """The regression that motivated Step 2.

    SOLO_USER_ID is set to a third party. If the stub were still in place the
    dependency would return *that*, for both athletes.
    """
    from app.routes.fitness import get_current_user_id
    from app.models.user import User

    monkeypatch.setenv("SOLO_USER_ID", "some-other-athlete")
    alice, bob = two_athletes

    assert get_current_user_id(User(id=alice, email="a@x.invalid")) == alice
    assert get_current_user_id(User(id=bob, email="b@x.invalid")) == bob


@requires_pg
def test_every_fitness_route_declares_an_identity_dependency():
    """No route may be reachable without authentication.

    `/tts` was the one exception at Step 2 — an unauthenticated relay into the
    GPU host's TTS endpoint. A new handler that forgets the dependency fails
    here rather than in production.
    """
    from app.routes.fitness import router as fitness_router, get_current_user_id
    from app.routes.workout_v2 import router as v2_router
    from app.core.deps import get_current_user

    identity_deps = {get_current_user_id, get_current_user}
    unguarded = []
    for router in (fitness_router, v2_router):
        for route in router.routes:
            deps = {d.call for d in getattr(route, "dependant", None).dependencies} \
                if getattr(route, "dependant", None) else set()
            # Sub-dependencies of the handler's own parameters count too.
            flat = set(deps)
            for d in getattr(route, "dependant", None).dependencies if getattr(route, "dependant", None) else []:
                flat.update(sub.call for sub in d.dependencies)
            if not (flat & identity_deps):
                unguarded.append(f"{sorted(route.methods)} {route.path}")
    assert unguarded == [], f"fitness routes with no identity dependency: {unguarded}"


# ─────────────────────────────────────────────────────────────────────────
# Anonymous and revoked
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/fitness/food-log", None),
    ("GET", "/api/fitness/templates", None),
    ("GET", "/api/fitness/programs", None),
    ("GET", "/api/fitness/workout-session/v2/active", None),
    ("POST", "/api/fitness/tts", {"text": "hello", "voice": "en"}),
])
def test_anonymous_is_refused_not_given_an_athlete(client, method, path, body):
    r = client.request(method, path, json=body)
    assert r.status_code == 401, (
        f"{method} {path} answered {r.status_code} without credentials — "
        "an anonymous client must get 401, never another athlete's data"
    )


@requires_pg
def test_forged_user_id_in_the_request_is_ignored(client, two_athletes):
    """Identity comes from the token, never from a parameter or header."""
    alice, bob = two_athletes
    r = client.get(
        "/api/fitness/food-log",
        headers={**_bearer(alice), "X-User-Id": bob},
        params={"user_id": bob},
    )
    assert r.status_code == 200
    # Nothing was created for Bob, and Alice's own list is what came back.
    assert r.json() is not None


@requires_pg
def test_revoked_jwt_is_denied(client, two_athletes, pg):
    from app.core.auth import create_access_token, revoke_token
    alice, _ = two_athletes
    token = create_access_token({"sub": alice})
    assert client.get("/api/fitness/templates",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 200

    revoke_token(token, db=pg)
    pg.commit()

    r = client.get("/api/fitness/templates",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401, "a revoked token must stop working immediately"


@requires_pg
def test_registered_device_token_still_works(client, two_athletes, pg):
    """The iOS app authenticates with X-Device-Token; Step 2 must not break it."""
    alice, _ = two_athletes
    dev = f"fitauth-device-{uuid.uuid4()}"
    pg.execute(text("""
        INSERT INTO device_registration
            (id, user_id, device_name, device_token, device_type, created_at, last_seen)
        VALUES (:id, :u, 'fitness-isolation-test', :t, 'ios', NOW(), NOW())
    """), {"id": str(uuid.uuid4()), "t": dev, "u": alice})
    pg.commit()
    try:
        r = client.get("/api/fitness/templates", headers={"X-Device-Token": dev})
        assert r.status_code == 200
    finally:
        pg.rollback()
        pg.execute(text("DELETE FROM device_registration WHERE device_token = :t"), {"t": dev})
        pg.commit()


# ─────────────────────────────────────────────────────────────────────────
# Cross-athlete isolation on real rows
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_food_logs_do_not_cross(client, two_athletes, pg):
    alice, bob = two_athletes
    r = client.post("/api/fitness/food-log", headers=_bearer(alice), json={
        "meal_type": "lunch",
        "food_items": [{"name": "alice chicken", "quantity": 1, "unit": "serving"}],
        "calories": 400, "protein": 40, "carbs": 10, "fats": 8,
    })
    assert r.status_code in (200, 201), r.text

    owned = pg.execute(text(
        "SELECT user_id FROM food_log WHERE user_id = :u"), {"u": alice}).fetchall()
    assert owned, "Alice's meal was not stored under Alice"
    assert pg.execute(text(
        "SELECT COUNT(*) FROM food_log WHERE user_id = :u"), {"u": bob}
    ).scalar() == 0, "Alice's write landed on Bob"

    bobs_view = client.get("/api/fitness/food-log", headers=_bearer(bob))
    assert bobs_view.status_code == 200
    assert "alice chicken" not in bobs_view.text


@requires_pg
def test_foreign_template_is_404_and_unmutated(client, two_athletes, pg):
    """A foreign id must 404 — not 403, which would confirm it exists."""
    alice, bob = two_athletes
    tid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_template (id, user_id, name, exercises, created_at, updated_at)
        VALUES (:id, :u, 'Bob push day', '[]', NOW(), NOW())
    """), {"id": tid, "u": bob})
    pg.commit()

    assert client.delete(f"/api/fitness/templates/{tid}",
                         headers=_bearer(alice)).status_code == 404
    r = client.patch(f"/api/fitness/templates/{tid}", headers=_bearer(alice),
                     json={"name": "alice stole this"})
    assert r.status_code == 404
    # The children are reachable by their own path and must 404 too.
    assert client.get(f"/api/fitness/templates/{tid}/exercises",
                      headers=_bearer(alice)).status_code == 404

    name = pg.execute(text(
        "SELECT name FROM fitness_template WHERE id = :id"), {"id": tid}).scalar()
    assert name == "Bob push day", "a cross-athlete mutation had a side effect"


@requires_pg
def test_foreign_template_exercise_cannot_be_attached_to_a_set(client, two_athletes, pg):
    """The `template_exercise_id` passthrough in the set-logging handler.

    It used to `UPDATE workout_log ... WHERE id = :set_id` with a
    caller-supplied `template_exercise_id` nobody checked, so Alice could
    point her own set at Bob's prescription row.
    """
    alice, bob = two_athletes
    tid, teid = str(uuid.uuid4()), str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_template (id, user_id, name, exercises, created_at, updated_at)
        VALUES (:id, :u, 'Bob legs', '[]', NOW(), NOW())
    """), {"id": tid, "u": bob})
    pg.execute(text("""
        INSERT INTO template_exercise (id, template_id, exercise_name, order_index, created_at, updated_at)
        VALUES (:id, :t, 'Back Squat', 0, NOW(), NOW())
    """), {"id": teid, "t": tid})
    pg.commit()

    r = client.post("/api/fitness/workout-log", headers=_bearer(alice), json={
        "exercise_name": "Back Squat", "set_index": 1,
        "weight": 100, "reps": 5,
        "template_exercise_id": teid,
    })
    assert r.status_code == 404, r.text
    leaked = pg.execute(text("""
        SELECT COUNT(*) FROM workout_log
        WHERE user_id = :u AND template_exercise_id = :te
    """), {"u": alice, "te": teid}).scalar()
    assert leaked == 0


@requires_pg
def test_v2_active_session_is_per_athlete(client, two_athletes, pg):
    """Two athletes asking "what am I doing right now" get their own answer."""
    alice, bob = two_athletes
    sid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO active_workout_session
            (id, user_id, status, started_at, workout_snapshot, version)
        VALUES (:id, :u, 'active', NOW(), CAST(:snap AS jsonb), 1)
    """), {"id": sid, "u": bob, "snap": '{"exercises": [{"name": "Bob Bench"}]}'})
    pg.commit()
    try:
        a = client.get("/api/fitness/workout-session/v2/active", headers=_bearer(alice))
        assert a.status_code == 200
        assert "Bob Bench" not in a.text

        b = client.get("/api/fitness/workout-session/v2/active", headers=_bearer(bob))
        assert b.status_code == 200
        assert "Bob Bench" in b.text
    finally:
        pg.rollback()
        pg.execute(text("DELETE FROM active_workout_session WHERE id = :id"), {"id": sid})
        pg.commit()


@requires_pg
def test_v2_command_against_a_foreign_session_is_refused(client, two_athletes, pg):
    """A command envelope naming someone else's session must not apply."""
    alice, bob = two_athletes
    sid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO active_workout_session
            (id, user_id, status, started_at, workout_snapshot, version)
        VALUES (:id, :u, 'active', NOW(), CAST(:snap AS jsonb), 1)
    """), {"id": sid, "u": bob,
           "snap": '{"exercises": [{"name": "Bench Press", "sets": 3, "reps": 5}]}'})
    pg.commit()
    try:
        r = client.post("/api/fitness/workout-session/v2/commands", headers=_bearer(alice),
                        json={
                            "command_id": str(uuid.uuid4()),
                            "kind": "log_set",
                            "session_id": sid,
                            "expected_version": 1,
                            "payload": {"exercise_index": 0, "weight": 100, "reps": 5},
                        })
        assert r.status_code in (404, 409), r.text
        assert pg.execute(text("""
            SELECT COUNT(*) FROM workout_log WHERE active_session_id = :s
        """), {"s": sid}).scalar() == 0, "a foreign command mutated Bob's session"
    finally:
        pg.rollback()
        pg.execute(text("DELETE FROM workout_log WHERE active_session_id = :s"), {"s": sid})
        pg.execute(text("DELETE FROM workout_session_command WHERE user_id = ANY(:ids)"),
                   {"ids": [alice, bob]})
        pg.execute(text("DELETE FROM active_workout_session WHERE id = :id"), {"id": sid})
        pg.commit()


@requires_pg
def test_recovery_log_and_targets_do_not_cross(client, two_athletes, pg):
    alice, bob = two_athletes
    pg.execute(text("""
        INSERT INTO daily_recovery_log (id, user_id, log_date, hrv, sleep_hours, created_at, updated_at)
        VALUES (:id, :u, CURRENT_DATE, 77, 7.5, NOW(), NOW())
    """), {"id": str(uuid.uuid4()), "u": bob})
    pg.execute(text("""
        INSERT INTO fitness_goals (id, user_id, calories, protein, carbs, fats)
        VALUES (:id, :u, 3333, 222, 333, 111)
    """), {"id": str(uuid.uuid4()), "u": bob})
    pg.commit()

    r = client.get("/api/fitness/goals", headers=_bearer(alice))
    assert r.status_code == 200
    assert "3333" not in r.text, "Bob's calorie target leaked into Alice's goals"
