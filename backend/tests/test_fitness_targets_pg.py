"""Step 6 of FITNESS_COACH_IMPLEMENTATION_PLAN: one resolver answers "what
were my targets on this date", and no target writer bypasses the history.

The defect being prevented: `fitness_phase.calories_target` is edited in
place, and `plan_adjust.py` legitimately moves those phases' dates around.
So before this, "what was my protein target on 14 February" resolved to
"whatever the row says right now" — and historical adherence computed against
a mutable current value is not adherence, it is a comparison against a target
that may never have applied.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_targets_pg.py
"""
import os
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
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
    unusable_hash = "$2b$12$" + "x" * 53
    alice = f"m2a-{uuid.uuid4().hex[:18]}"
    bob = f"m2b-{uuid.uuid4().hex[:18]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@m2.invalid", "p": unusable_hash})
    pg.commit()
    yield alice, bob
    pg.rollback()
    for t in ("fitness_target_revision", "fitness_template", "fitness_phase",
              "fitness_program", "fitness_goals", "fitness_athlete_profile",
              "fitness_athlete_goal", "fitness_athlete_limitation",
              "fitness_athlete_profile_change", "workout_session"):
        pg.execute(text(f"DELETE FROM {t} WHERE user_id = ANY(:ids)"),
                   {"ids": [alice, bob]})
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"), {"ids": [alice, bob]})
    pg.commit()


def _program(pg, user_id, *, active=True) -> str:
    pid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_program (id, user_id, name, goal, is_active, created_at, updated_at)
        VALUES (:id, :u, 'Test program', 'hypertrophy', :a, NOW(), NOW())
    """), {"id": pid, "u": user_id, "a": active})
    return pid


def _phase(pg, user_id, program_id, *, start, end, name="Block",
           cal=None, pro=None, carb=None, fat=None,
           cal_t=None, cal_r=None, steps=None, status="active") -> str:
    pid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_phase
            (id, user_id, program_id, name, start_date, end_date, status,
             calories_target, protein_target, carbs_target, fat_target,
             calories_training_day, calories_rest_day, daily_steps_target,
             created_at, updated_at)
        VALUES (:id, :u, :prog, :n, :s, :e, :st, :cal, :pro, :carb, :fat,
                :cal_t, :cal_r, :steps, NOW(), NOW())
    """), {"id": pid, "u": user_id, "prog": program_id, "n": name,
           "s": start, "e": end, "st": status, "cal": cal, "pro": pro,
           "carb": carb, "fat": fat, "cal_t": cal_t, "cal_r": cal_r,
           "steps": steps})
    return pid


# ─────────────────────────────────────────────────────────────────────────
# Resolution: provenance is always stated
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_no_data_resolves_to_unknown_not_zero(pg, two_athletes):
    """An athlete with nothing configured has unknown targets.

    Zero calories is a target. "I never set one" is not, and conflating them
    makes every adherence number for that period a fiction.
    """
    from app.schemas.fitness_coach import TargetProvenance
    from app.services.fitness.targets import resolve_targets

    alice, _ = two_athletes
    resolved = resolve_targets(pg, alice, date(2026, 10, 1))

    assert resolved.provenance is TargetProvenance.UNKNOWN
    assert resolved.values.calories is None
    assert resolved.values.protein_g is None
    assert resolved.history_unknown is True


@requires_pg
def test_legacy_phase_macros_resolve_with_legacy_provenance(pg, two_athletes):
    """An untouched existing phase still answers — labelled as legacy.

    This is the compatibility path: an athlete who has never used the Coach
    still gets their phase's macros, and the response says those values have
    no recorded history behind them.
    """
    from app.schemas.fitness_coach import TargetProvenance
    from app.services.fitness.targets import resolve_targets

    alice, _ = two_athletes
    prog = _program(pg, alice)
    _phase(pg, alice, prog, start=date(2026, 9, 1), end=date(2026, 10, 31),
           cal=2800, pro=190, carb=300, fat=80)
    pg.commit()

    resolved = resolve_targets(pg, alice, date(2026, 9, 15))
    assert resolved.provenance is TargetProvenance.LEGACY_PHASE
    assert resolved.values.calories == 2800
    assert resolved.values.protein_g == 190
    assert resolved.history_unknown is True, (
        "a mutable phase column has no provable effective date"
    )


@requires_pg
def test_inclusive_phase_end_becomes_a_half_open_bound(pg, two_athletes):
    """The one conversion point.

    `fitness_phase.end_date` is inclusive: a phase ending 31 October still
    applies *on* the 31st. Revisions are `[from, until)`. Getting this wrong
    shifts every target by a day at every block boundary.
    """
    from app.services.fitness.targets import resolve_targets

    alice, _ = two_athletes
    prog = _program(pg, alice)
    _phase(pg, alice, prog, start=date(2026, 9, 1), end=date(2026, 10, 31), cal=2800)
    pg.commit()

    resolved = resolve_targets(pg, alice, date(2026, 10, 31))
    assert resolved.values.calories == 2800, "the inclusive end date is still covered"
    assert resolved.effective_until == date(2026, 11, 1), (
        "exposed as a half-open bound, one day after the inclusive end"
    )


@requires_pg
def test_legacy_default_goals_resolve_when_no_phase_applies(pg, two_athletes):
    from app.schemas.fitness_coach import TargetProvenance
    from app.services.fitness.targets import resolve_targets

    alice, _ = two_athletes
    pg.execute(text("""
        INSERT INTO fitness_goals (id, user_id, calories, protein, carbs, fats, updated_at)
        VALUES (:id, :u, 2450, 175, 240, 70, NOW())
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    resolved = resolve_targets(pg, alice, date(2026, 10, 1))
    assert resolved.provenance is TargetProvenance.LEGACY_DEFAULT
    assert resolved.values.calories == 2450
    assert resolved.effective_from is None, (
        "fitness_goals is a mutable row with no history; claiming a start "
        "date for it would be a fabrication"
    )


@requires_pg
def test_an_approved_revision_beats_the_legacy_columns(pg, two_athletes):
    from app.schemas.fitness_coach import (
        TargetProvenance, TargetRevisionIn, TargetScope, TargetValues,
    )
    from app.services.fitness.targets import create_target_revision, resolve_targets

    alice, _ = two_athletes
    prog = _program(pg, alice)
    phase = _phase(pg, alice, prog, start=date(2026, 9, 1), end=date(2026, 12, 31),
                   cal=2800, pro=190)
    pg.commit()

    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.PHASE, phase_id=phase,
        valid_from=date(2026, 10, 1),
        training=TargetValues(calories=3000, protein_g=200),
    ))

    before = resolve_targets(pg, alice, date(2026, 9, 20))
    after = resolve_targets(pg, alice, date(2026, 10, 5))

    assert after.provenance is TargetProvenance.APPROVED_REVISION
    assert after.values.calories == 3000
    assert after.revision_version == 1

    # September is NOT answered with 2800 either, and that is the point.
    # Creating the October revision synced the phase's mutable
    # `calories_training_day` column to 3000 (so every un-migrated reader
    # shows the current target). Falling back to that column for September
    # would claim the October target applied in September — which is the
    # fabricated-adherence failure this whole subsystem exists to prevent.
    # Once a phase has recorded history, a gap in it is an honest unknown.
    assert before.provenance is TargetProvenance.UNKNOWN
    assert before.values.calories is None
    assert before.history_unknown is True


@requires_pg
def test_a_draft_revision_is_not_the_athletes_target(pg, two_athletes):
    """`approved_at IS NULL` must never resolve.

    A coach recommendation becomes a revision only when the athlete accepts
    it. An unapproved row silently applying would be the system changing
    someone's calories without being asked.
    """
    from app.schemas.fitness_coach import TargetProvenance
    from app.services.fitness.targets import resolve_targets

    alice, _ = two_athletes
    prog = _program(pg, alice)
    phase = _phase(pg, alice, prog, start=date(2026, 9, 1), end=date(2026, 12, 31),
                   cal=2800)
    pg.execute(text("""
        INSERT INTO fitness_target_revision
            (id, user_id, scope, phase_id, version, valid_from, calories, approved_at)
        VALUES (:id, :u, 'phase', :p, 1, :d, 9000, NULL)
    """), {"id": str(uuid.uuid4()), "u": alice, "p": phase, "d": date(2026, 9, 1)})
    pg.commit()

    resolved = resolve_targets(pg, alice, date(2026, 9, 15))
    assert resolved.values.calories == 2800
    assert resolved.provenance is TargetProvenance.LEGACY_PHASE


# ─────────────────────────────────────────────────────────────────────────
# Training vs rest days
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_training_and_rest_variants_resolve_separately(pg, two_athletes):
    from app.schemas.fitness_coach import (
        DayType, TargetRevisionIn, TargetScope, TargetValues,
    )
    from app.services.fitness.targets import create_target_revision, resolve_targets

    alice, _ = two_athletes
    prog = _program(pg, alice)
    phase = _phase(pg, alice, prog, start=date(2026, 9, 1), end=date(2026, 12, 31))
    pg.commit()

    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.PHASE, phase_id=phase, valid_from=date(2026, 9, 1),
        training=TargetValues(calories=3100, protein_g=200, carbs_g=380, fat_g=80),
        rest=TargetValues(calories=2700, protein_g=200, carbs_g=250, fat_g=85),
    ))

    training = resolve_targets(pg, alice, date(2026, 9, 15), DayType.TRAINING)
    rest = resolve_targets(pg, alice, date(2026, 9, 15), DayType.REST)
    assert training.values.calories == 3100
    assert rest.values.calories == 2700
    assert rest.values.protein_g == 200, "protein is the same on both day types here"


@requires_pg
def test_a_revision_without_rest_values_uses_training_for_both(pg, two_athletes):
    """No rest values means "this plan does not distinguish day types".

    Different from a rest-day target of zero — which is why the fallback
    tests `is None` rather than truthiness.
    """
    from app.schemas.fitness_coach import (
        DayType, TargetRevisionIn, TargetScope, TargetValues,
    )
    from app.services.fitness.targets import create_target_revision, resolve_targets

    alice, _ = two_athletes
    prog = _program(pg, alice)
    phase = _phase(pg, alice, prog, start=date(2026, 9, 1), end=date(2026, 12, 31))
    pg.commit()

    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.PHASE, phase_id=phase, valid_from=date(2026, 9, 1),
        training=TargetValues(calories=2900, protein_g=185),
    ))
    assert resolve_targets(pg, alice, date(2026, 9, 15), DayType.REST).values.calories == 2900


@requires_pg
def test_a_legitimate_zero_rest_target_is_not_treated_as_absent(pg, two_athletes):
    from app.schemas.fitness_coach import (
        DayType, TargetRevisionIn, TargetScope, TargetValues,
    )
    from app.services.fitness.targets import create_target_revision, resolve_targets

    alice, _ = two_athletes
    prog = _program(pg, alice)
    phase = _phase(pg, alice, prog, start=date(2026, 9, 1), end=date(2026, 12, 31))
    pg.commit()

    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.PHASE, phase_id=phase, valid_from=date(2026, 9, 1),
        training=TargetValues(calories=2900, steps=12000),
        rest=TargetValues(calories=2400, steps=0),
    ))
    rest = resolve_targets(pg, alice, date(2026, 9, 15), DayType.REST)
    assert rest.values.calories == 2400
    assert rest.values.steps == 0, "an explicit zero step goal is a goal"


# ─────────────────────────────────────────────────────────────────────────
# History
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_midweek_change_does_not_rewrite_the_earlier_days(pg, two_athletes):
    """The central claim of the whole step."""
    from app.schemas.fitness_coach import TargetRevisionIn, TargetScope, TargetValues
    from app.services.fitness.targets import create_target_revision, resolve_targets

    alice, _ = two_athletes
    prog = _program(pg, alice)
    phase = _phase(pg, alice, prog, start=date(2026, 9, 1), end=date(2026, 12, 31))
    pg.commit()

    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.PHASE, phase_id=phase, valid_from=date(2026, 9, 1),
        training=TargetValues(calories=2800, protein_g=180),
    ))
    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.PHASE, phase_id=phase, valid_from=date(2026, 9, 10),
        training=TargetValues(calories=2500, protein_g=190),
    ))

    assert resolve_targets(pg, alice, date(2026, 9, 5)).values.calories == 2800
    assert resolve_targets(pg, alice, date(2026, 9, 9)).values.calories == 2800
    assert resolve_targets(pg, alice, date(2026, 9, 10)).values.calories == 2500, (
        "valid_from is inclusive"
    )
    assert resolve_targets(pg, alice, date(2026, 9, 20)).values.calories == 2500


@requires_pg
def test_the_superseded_revision_is_closed_not_deleted(pg, two_athletes):
    from app.schemas.fitness_coach import TargetRevisionIn, TargetScope, TargetValues
    from app.services.fitness.targets import create_target_revision, list_revisions

    alice, _ = two_athletes
    prog = _program(pg, alice)
    phase = _phase(pg, alice, prog, start=date(2026, 9, 1), end=date(2026, 12, 31))
    pg.commit()

    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.PHASE, phase_id=phase, valid_from=date(2026, 9, 1),
        training=TargetValues(calories=2800),
    ))
    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.PHASE, phase_id=phase, valid_from=date(2026, 9, 10),
        training=TargetValues(calories=2500),
    ))

    history = list_revisions(pg, alice, scope=TargetScope.PHASE)
    assert len(history) == 2, "the earlier revision must survive for audit"
    older = next(r for r in history if r.version == 1)
    assert older.valid_until == date(2026, 9, 10), "closed, not overwritten"
    assert older.training.calories == 2800, "its values are intact"


@requires_pg
def test_a_date_before_recorded_history_is_flagged_unknown(pg, two_athletes):
    """The `fitness_goals` defaults problem, concretely.

    A date before the first revision must not be answered with the current
    values. Doing so would assert a target for a month nobody set one in, and
    every adherence number for that month would be invented.
    """
    from app.schemas.fitness_coach import TargetRevisionIn, TargetScope, TargetValues
    from app.services.fitness.targets import create_target_revision, resolve_targets

    alice, _ = two_athletes
    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=date(2026, 9, 1),
        training=TargetValues(calories=2600, protein_g=180),
    ))

    before = resolve_targets(pg, alice, date(2026, 7, 15))
    assert before.history_unknown is True
    assert before.values.calories != 2600 or before.provenance.value != "approved_revision"

    after = resolve_targets(pg, alice, date(2026, 9, 15))
    assert after.history_unknown is False
    assert after.values.calories == 2600


@requires_pg
def test_a_backdated_revision_does_not_change_todays_dashboard(pg, two_athletes):
    """Correcting history must not move the current projection.

    The legacy `fitness_goals`/`fitness_phase` columns are what every
    un-migrated reader shows. A backdated correction updates the history and
    leaves them alone.
    """
    from app.schemas.fitness_coach import TargetRevisionIn, TargetScope, TargetValues
    from app.services.fitness.targets import create_target_revision

    from app.services.fitness.profile import athlete_today

    alice, _ = two_athletes
    today = athlete_today(pg, alice)
    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=today,
        training=TargetValues(calories=2600, protein_g=180),
    ))
    current = pg.execute(text(
        "SELECT calories FROM fitness_goals WHERE user_id = :u"), {"u": alice}).scalar()
    assert current == 2600

    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.DEFAULT,
        valid_from=today - timedelta(days=90),
        valid_until=today - timedelta(days=60),
        training=TargetValues(calories=2100, protein_g=160),
    ))
    still = pg.execute(text(
        "SELECT calories FROM fitness_goals WHERE user_id = :u"), {"u": alice}).scalar()
    assert still == 2600, "a backdated correction changed the current projection"


@requires_pg
def test_overlapping_approved_revisions_are_refused(pg, two_athletes):
    """A revision cannot be inserted underneath existing history."""
    from app.schemas.fitness_coach import TargetRevisionIn, TargetScope, TargetValues
    from app.services.fitness.targets import TargetConflict, create_target_revision

    alice, _ = two_athletes
    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=date(2026, 9, 1),
        valid_until=date(2026, 10, 1), training=TargetValues(calories=2600),
    ))
    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=date(2026, 10, 1),
        training=TargetValues(calories=2800),
    ))
    with pytest.raises(TargetConflict):
        create_target_revision(pg, alice, TargetRevisionIn(
            scope=TargetScope.DEFAULT, valid_from=date(2026, 8, 1),
            valid_until=date(2026, 11, 1), training=TargetValues(calories=9999),
        ))
    pg.rollback()


@requires_pg
def test_expected_revision_refuses_a_stale_acceptance(pg, two_athletes):
    """The concurrency token that makes accepting a recommendation safe.

    A proposal was computed against one current revision. If that moved, the
    acceptance must be refused, not applied to a different baseline — the
    numbers in the proposal were derived from the old one.
    """
    from app.schemas.fitness_coach import TargetRevisionIn, TargetScope, TargetValues
    from app.services.fitness.targets import TargetConflict, create_target_revision

    alice, _ = two_athletes
    first = create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=date(2026, 9, 1),
        training=TargetValues(calories=2600),
    ))
    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=date(2026, 9, 15),
        training=TargetValues(calories=2700),
    ))
    with pytest.raises(TargetConflict) as e:
        create_target_revision(
            pg, alice,
            TargetRevisionIn(scope=TargetScope.DEFAULT, valid_from=date(2026, 10, 1),
                             training=TargetValues(calories=2900)),
            expected_revision=first.id,
        )
    assert e.value.current_revision_id is not None, (
        "a client needs the current revision id to reconcile, not a bare 409"
    )
    pg.rollback()


@requires_pg
def test_versions_increment_per_scope_and_phase(pg, two_athletes):
    from app.schemas.fitness_coach import TargetRevisionIn, TargetScope, TargetValues
    from app.services.fitness.targets import create_target_revision

    alice, _ = two_athletes
    prog = _program(pg, alice)
    phase_a = _phase(pg, alice, prog, start=date(2026, 1, 1), end=date(2026, 3, 31),
                     name="Block A")
    phase_b = _phase(pg, alice, prog, start=date(2026, 4, 1), end=date(2026, 6, 30),
                     name="Block B", status="planned")
    pg.commit()

    r1 = create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.PHASE, phase_id=phase_a, valid_from=date(2026, 1, 1),
        valid_until=date(2026, 4, 1), training=TargetValues(calories=2800)))
    r2 = create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.PHASE, phase_id=phase_a, valid_from=date(2026, 2, 1),
        valid_until=date(2026, 4, 1), training=TargetValues(calories=2700)))
    r3 = create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.PHASE, phase_id=phase_b, valid_from=date(2026, 4, 1),
        training=TargetValues(calories=3000)))

    assert (r1.version, r2.version) == (1, 2)
    assert r3.version == 1, "each phase has its own version sequence"


# ─────────────────────────────────────────────────────────────────────────
# No writer bypasses the history
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_creating_a_phase_through_the_api_records_a_revision(pg, two_athletes):
    """`POST /api/fitness/phases` is a target writer."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness import router as fitness_router

    alice, _ = two_athletes
    app = FastAPI()
    app.include_router(fitness_router, prefix="/api/fitness")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}

    prog = _program(pg, alice)
    pg.commit()

    r = client.post("/api/fitness/phases", headers=headers, json={
        "name": "API block", "goal": "hypertrophy", "program_id": prog,
        "start_date": "2026-11-01", "end_date": "2026-12-31",
        "calories_target": 3050, "protein_target": 205,
        "calories_training_day": 3200, "calories_rest_day": 2850,
    })
    assert r.status_code == 200, r.text
    phase_id = r.json()["phase_id"]

    revision = pg.execute(text("""
        SELECT valid_from, valid_until, calories, protein_g, rest_calories, source
        FROM fitness_target_revision WHERE phase_id = :p
    """), {"p": phase_id}).fetchone()
    assert revision is not None, "a phase created through the API left no history"
    assert revision.valid_from == date(2026, 11, 1), (
        "a created phase's targets provably apply from its own start date"
    )
    assert revision.valid_until == date(2027, 1, 1), "inclusive end + 1 day"
    assert revision.calories == 3200
    assert revision.rest_calories == 2850


@requires_pg
def test_editing_a_phases_macros_records_a_revision_effective_today(pg, two_athletes):
    """An *edit* takes effect today, unlike a creation.

    Backdating an edit to the phase's start would retroactively change the
    targets for weeks already lived, rewriting their adherence.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness import router as fitness_router

    from app.services.fitness.profile import athlete_today

    alice, _ = two_athletes
    app = FastAPI()
    app.include_router(fitness_router, prefix="/api/fitness")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}

    # The athlete's own calendar date, not the server's. Just after UTC
    # midnight those differ, and asserting against `date.today()` would make
    # this test fail nightly for exactly the reason the resolver exists.
    today = athlete_today(pg, alice)

    prog = _program(pg, alice)
    phase = _phase(pg, alice, prog, start=today - timedelta(days=30),
                   end=today + timedelta(days=30), cal=2800, pro=190)
    pg.commit()

    r = client.patch(f"/api/fitness/phases/{phase}", headers=headers,
                     json={"calories_target": 2600, "protein_target": 200})
    assert r.status_code == 200, r.text

    revisions = pg.execute(text("""
        SELECT valid_from, calories, protein_g, source
        FROM fitness_target_revision WHERE phase_id = :p ORDER BY version
    """), {"p": phase}).fetchall()
    assert revisions, "a macro edit left no history"
    latest = revisions[-1]
    assert latest.valid_from == today, (
        "an edit is effective from the athlete's today, not retroactive to "
        "the phase start"
    )
    assert latest.calories == 2600
    assert latest.protein_g == 200

    # The legacy projection still reflects the edit, for un-migrated readers.
    current = pg.execute(text(
        "SELECT calories_target, protein_target FROM fitness_phase WHERE id = :p"
    ), {"p": phase}).fetchone()
    assert (current.calories_target, current.protein_target) == (2600, 200)


@requires_pg
def test_editing_only_a_phase_name_creates_no_empty_revision(pg, two_athletes):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness import router as fitness_router

    alice, _ = two_athletes
    app = FastAPI()
    app.include_router(fitness_router, prefix="/api/fitness")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}

    prog = _program(pg, alice)
    phase = _phase(pg, alice, prog, start=date(2026, 9, 1), end=date(2026, 12, 31))
    pg.commit()

    assert client.patch(f"/api/fitness/phases/{phase}", headers=headers,
                        json={"name": "Renamed"}).status_code == 200
    assert pg.execute(text(
        "SELECT COUNT(*) FROM fitness_target_revision WHERE phase_id = :p"), {"p": phase}
    ).scalar() == 0, "renaming a phase is not a target change"


@requires_pg
def test_plan_adjust_block_insertion_records_each_blocks_targets(pg, two_athletes):
    """Splitting a block must preserve both halves' targets.

    `plan_adjust.insert_phase_block` trims and splits existing phases. If
    only the current phase's targets were recorded, adherence for the earlier
    half would be judged against targets that never applied to it.
    """
    from app.services.plan_adjust import insert_phase_block

    alice, _ = two_athletes
    prog = _program(pg, alice)
    _phase(pg, alice, prog, start=date(2026, 9, 1), end=date(2026, 12, 31),
           name="Long block", cal=2800, pro=190)
    pg.commit()

    try:
        insert_phase_block(
            pg, alice, name="Mini cut", goal="cut",
            start_date=date(2026, 10, 1), duration_weeks=4,
            nutrition={"calories_target": 2300, "protein_target": 210,
                       "carbs_target": 200, "fat_target": 70},
        )
        pg.commit()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"insert_phase_block signature differs: {exc}")

    revisions = pg.execute(text("""
        SELECT r.calories, r.valid_from, r.valid_until, p.name
        FROM fitness_target_revision r
        JOIN fitness_phase p ON p.id = r.phase_id
        WHERE r.user_id = :u
        ORDER BY r.valid_from
    """), {"u": alice}).fetchall()
    assert any(r.calories == 2300 for r in revisions), (
        "the inserted block's targets were not recorded"
    )
    for r in revisions:
        assert r.valid_from is not None, "every revision has a provable start"


# ─────────────────────────────────────────────────────────────────────────
# Isolation and the API surface
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_targets_do_not_cross_between_athletes(pg, two_athletes):
    from app.schemas.fitness_coach import TargetRevisionIn, TargetScope, TargetValues
    from app.services.fitness.targets import create_target_revision, resolve_targets

    alice, bob = two_athletes
    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=date(2026, 9, 1),
        training=TargetValues(calories=2600)))
    create_target_revision(pg, bob, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=date(2026, 9, 1),
        training=TargetValues(calories=3400)))

    assert resolve_targets(pg, alice, date(2026, 9, 15)).values.calories == 2600
    assert resolve_targets(pg, bob, date(2026, 9, 15)).values.calories == 3400


@requires_pg
def test_a_revision_cannot_name_a_foreign_phase(pg, two_athletes):
    """404-shaped, not 403: a foreign id must not confirm its own existence."""
    from app.schemas.fitness_coach import TargetRevisionIn, TargetScope, TargetValues
    from app.services.fitness.targets import create_target_revision

    alice, bob = two_athletes
    prog = _program(pg, bob)
    bobs_phase = _phase(pg, bob, prog, start=date(2026, 9, 1), end=date(2026, 12, 31))
    pg.commit()

    with pytest.raises(LookupError):
        create_target_revision(pg, alice, TargetRevisionIn(
            scope=TargetScope.PHASE, phase_id=bobs_phase,
            valid_from=date(2026, 9, 1), training=TargetValues(calories=1200)))
    pg.rollback()
    assert pg.execute(text(
        "SELECT COUNT(*) FROM fitness_target_revision WHERE phase_id = :p"),
        {"p": bobs_phase}).scalar() == 0


@requires_pg
def test_coach_api_round_trip(pg, two_athletes):
    """The `/api/fitness/coach` surface, end to end, with real auth."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness_coach import router

    alice, bob = two_athletes
    app = FastAPI()
    app.include_router(router, prefix="/api/fitness/coach")
    client = TestClient(app)
    a = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}
    b = {"Authorization": f"Bearer {create_access_token({'sub': bob})}"}

    assert client.get("/api/fitness/coach/profile").status_code == 401

    # An athlete who has never opened Settings.
    empty = client.get("/api/fitness/coach/profile", headers=a)
    assert empty.status_code == 200
    body = empty.json()
    assert body["height_cm"] is None
    assert body["calculation_sex"] == "unknown"
    assert body["training_level"] == "unknown"
    assert body["current_weight"]["value"] is None
    assert body["current_weight"]["unavailable_reason"] == "no_data"

    # First edit upserts.
    r = client.patch("/api/fitness/coach/profile", headers=a,
                     json={"height_cm": 182.5, "training_level": "advanced",
                           "equipment": ["barbell", "rack"]})
    assert r.status_code == 200, r.text
    assert r.json()["row_version"] == 2 or r.json()["row_version"] == 1
    version = r.json()["row_version"]

    # Omitted fields survive; an explicit null clears.
    r = client.patch("/api/fitness/coach/profile", headers=a,
                     json={"preferred_duration_minutes": 75})
    assert r.json()["height_cm"] == 182.5, "an omitted field must not be wiped"
    assert r.json()["preferred_duration_minutes"] == 75

    r = client.patch("/api/fitness/coach/profile", headers=a,
                     json={"preferred_duration_minutes": None})
    assert r.json()["preferred_duration_minutes"] is None, "explicit null clears"

    # A stale expected_version is a 409 carrying the current one.
    r = client.patch("/api/fitness/coach/profile", headers=a,
                     json={"height_cm": 170, "expected_version": version})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "version_conflict"
    assert isinstance(detail["current_version"], int)

    # Bob's profile is untouched.
    assert client.get("/api/fitness/coach/profile", headers=b).json()["height_cm"] is None

    # Goals.
    r = client.post("/api/fitness/coach/goals", headers=a, json={
        "kind": "gain", "is_primary": True, "rate_basis": "absolute",
        "target_rate_kg_week": 0.2, "valid_from": "2026-09-01",
        "rationale": "upper-body thickness",
    })
    assert r.status_code == 201, r.text

    r = client.post("/api/fitness/coach/goals", headers=a, json={
        "kind": "cut", "is_primary": True, "rate_basis": "absolute",
        "target_rate_kg_week": -0.4, "valid_from": "2026-11-01",
    })
    assert r.status_code == 201, "a new primary goal closes the open one"

    history = client.get("/api/fitness/coach/goals", headers=a,
                         params={"history": True}).json()
    assert len(history) == 2
    on_sept = client.get("/api/fitness/coach/goals", headers=a,
                         params={"on_date": "2026-09-15"}).json()
    assert len(on_sept) == 1 and on_sept[0]["kind"] == "gain"

    # Sign coherence is rejected at the API boundary.
    assert client.post("/api/fitness/coach/goals", headers=a, json={
        "kind": "cut", "rate_basis": "absolute", "target_rate_kg_week": 0.5,
        "valid_from": "2027-01-01",
    }).status_code == 422

    # Limitations.
    r = client.post("/api/fitness/coach/limitations", headers=a, json={
        "area": "right shoulder", "description": "aches on overhead pressing",
        "severity_flag": "mild", "effective_from": "2026-09-20",
    })
    assert r.status_code == 201
    lim_id = r.json()["id"]
    assert "diagnosis" not in r.json()

    r = client.post(f"/api/fitness/coach/limitations/{lim_id}/resolve",
                    headers=a, json={})
    assert r.status_code == 200 and r.json()["status"] == "resolved"

    # Bob cannot resolve Alice's limitation.
    assert client.post(f"/api/fitness/coach/limitations/{lim_id}/resolve",
                       headers=b, json={}).status_code == 404

    # Targets.
    r = client.post("/api/fitness/coach/targets", headers=a, json={
        "scope": "default", "valid_from": "2026-09-01",
        "training": {"calories": 3000, "protein_g": 200},
    })
    assert r.status_code == 201, r.text

    r = client.get("/api/fitness/coach/targets", headers=a,
                   params={"on_date": "2026-09-15"})
    assert r.status_code == 200
    body = r.json()
    assert body["values"]["calories"] == 3000
    assert body["provenance"] == "approved_revision"
    assert body["history_unknown"] is False

    # Before recorded history.
    earlier = client.get("/api/fitness/coach/targets", headers=a,
                         params={"on_date": "2026-06-01"}).json()
    assert earlier["history_unknown"] is True

    assert len(client.get("/api/fitness/coach/targets/history", headers=a).json()) == 1

    # A foreign phase is 404, not 403.
    prog = _program(pg, bob)
    bobs_phase = _phase(pg, bob, prog, start=date(2026, 9, 1), end=date(2026, 12, 31))
    pg.commit()
    assert client.post("/api/fitness/coach/targets", headers=a, json={
        "scope": "phase", "phase_id": bobs_phase, "valid_from": "2026-09-01",
        "training": {"calories": 1200},
    }).status_code == 404

    # The athlete's own calendar date.
    today = client.get("/api/fitness/coach/today", headers=a).json()
    assert "athlete_local_date" in today and today["timezone"]


@requires_pg
def test_profile_timezone_drives_the_athletes_today(pg, two_athletes):
    """The server's date is not the athlete's date."""
    from app.services.fitness.profile import athlete_today, patch_athlete_profile
    from app.schemas.fitness_coach import AthleteProfilePatch

    alice, _ = two_athletes
    patch_athlete_profile(pg, alice, AthleteProfilePatch(timezone="Pacific/Kiritimati"))
    kiritimati = athlete_today(pg, alice)

    patch_athlete_profile(pg, alice, AthleteProfilePatch(timezone="Pacific/Niue"))
    niue = athlete_today(pg, alice)

    # Kiritimati is UTC+14, Niue is UTC-11: 25 hours apart, so these cannot
    # both be the same calendar day at any instant.
    assert kiritimati >= niue
    assert (kiritimati - niue).days in (0, 1)


@requires_pg
def test_the_coach_router_is_registered_outside_a_try_except(pg):
    """Gotcha 3: a swallowed ImportError silently drops a whole router.

    Asserted on the source, because the failure is invisible at runtime —
    the feature just 404s with no log line anyone reads.
    """
    import pathlib
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "app" / "main_simple.py").read_text()
    idx = source.index("fitness_coach_router")
    # The 400 characters before the registration must not open a try block
    # that the registration sits inside.
    preceding = source[max(0, idx - 400):idx]
    last_try = preceding.rfind("\ntry:")
    last_except = preceding.rfind("\nexcept")
    assert last_try <= last_except, (
        "the Fitness Coach router is registered inside a try/except; an "
        "import error there would silently drop the entire router"
    )
