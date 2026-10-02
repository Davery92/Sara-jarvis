"""Step 5 of FITNESS_COACH_IMPLEMENTATION_PLAN: athlete profile, dated goals
and limitations hold real history with real constraints.

These run against PostgreSQL because every claim here is a PostgreSQL claim.
SQLite ignores CHECK semantics this work depends on, has no JSONB, and has no
exclusion constraints at all — the "no two overlapping primary goals" rule is
unprovable without a real `gist` index. A passing SQLite suite would be
evidence of nothing.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_athlete_models_pg.py
"""
import os
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

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
    alice = f"m1a-{uuid.uuid4().hex[:18]}"
    bob = f"m1b-{uuid.uuid4().hex[:18]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@m1.invalid", "p": unusable_hash})
    pg.commit()
    yield alice, bob
    pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"), {"ids": [alice, bob]})
    pg.commit()


def _goal(pg, user_id, *, kind="hypertrophy", primary=True, valid_from, valid_until=None,
          rate_basis="none", kg_week=None, pct_week=None, priority=1):
    gid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_athlete_goal
            (id, user_id, kind, is_primary, priority, rate_basis,
             target_rate_kg_week, target_rate_percent_week, valid_from, valid_until)
        VALUES (:id, :u, :k, :p, :prio, :rb, :kg, :pct, :vf, :vu)
    """), {"id": gid, "u": user_id, "k": kind, "p": primary, "prio": priority,
           "rb": rate_basis, "kg": kg_week, "pct": pct_week,
           "vf": valid_from, "vu": valid_until})
    return gid


# ─────────────────────────────────────────────────────────────────────────
# Profile
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_profile_is_unique_per_athlete(pg, two_athletes):
    alice, _ = two_athletes
    pg.execute(text("""
        INSERT INTO fitness_athlete_profile (id, user_id) VALUES (:id, :u)
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()
    with pytest.raises(IntegrityError):
        pg.execute(text("""
            INSERT INTO fitness_athlete_profile (id, user_id) VALUES (:id, :u)
        """), {"id": str(uuid.uuid4()), "u": alice})
        pg.commit()
    pg.rollback()


@requires_pg
def test_an_empty_profile_assumes_nothing(pg, two_athletes):
    """No default beginner, no default age, no default sex, no stored weight.

    This is the whole point of Step 5's "preserve optional DOB/sex unknown;
    no default beginner/age/weight assumption and no permanent current-weight
    column".
    """
    alice, _ = two_athletes
    pg.execute(text("""
        INSERT INTO fitness_athlete_profile (id, user_id) VALUES (:id, :u)
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    row = pg.execute(text("""
        SELECT height_cm, date_of_birth, calculation_sex, training_level,
               training_experience_years, timezone, monitoring_consent, row_version
        FROM fitness_athlete_profile WHERE user_id = :u
    """), {"u": alice}).fetchone()

    assert row.height_cm is None
    assert row.date_of_birth is None
    assert row.calculation_sex == "unknown"
    assert row.training_level == "unknown", "no athlete is assumed to be a novice"
    assert row.training_experience_years is None
    assert row.timezone == "America/New_York", "defaults to Sara's existing ET"
    assert row.monitoring_consent is False, "consent is never on by default"
    assert row.row_version == 1

    columns = {r[0] for r in pg.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'fitness_athlete_profile'
    """)).fetchall()}
    assert "current_weight" not in columns and "weight_kg" not in columns, (
        "bodyweight is an observation in health_metric; a copied 'current' "
        "column would diverge from it after any backdated correction"
    )


@requires_pg
def test_prefer_not_to_say_is_distinct_from_unknown(pg, two_athletes):
    """A refusal and "nobody asked" are different states.

    Both skip any formula that needs the input, but only one of them should
    ever be re-asked.
    """
    alice, bob = two_athletes
    for uid, value in ((alice, "prefer_not_to_say"), (bob, "unknown")):
        pg.execute(text("""
            INSERT INTO fitness_athlete_profile (id, user_id, calculation_sex)
            VALUES (:id, :u, :s)
        """), {"id": str(uuid.uuid4()), "u": uid, "s": value})
    pg.commit()
    stored = dict(pg.execute(text("""
        SELECT user_id, calculation_sex FROM fitness_athlete_profile
        WHERE user_id = ANY(:ids)
    """), {"ids": [alice, bob]}).fetchall())
    assert stored[alice] == "prefer_not_to_say"
    assert stored[bob] == "unknown"


@requires_pg
@pytest.mark.parametrize("column,value", [
    ("calculation_sex", "male-ish"),
    ("training_level", "elite"),
    ("height_cm", 12),
    ("height_cm", 400),
    ("training_experience_years", 150),
    ("row_version", 0),
])
def test_profile_constraints_reject_nonsense(pg, two_athletes, column, value):
    alice, _ = two_athletes
    with pytest.raises(IntegrityError):
        pg.execute(text(f"""
            INSERT INTO fitness_athlete_profile (id, user_id, {column})
            VALUES (:id, :u, :v)
        """), {"id": str(uuid.uuid4()), "u": alice, "v": value})
        pg.commit()
    pg.rollback()


@requires_pg
def test_profile_change_audit_records_a_material_edit(pg, two_athletes):
    alice, _ = two_athletes
    pg.execute(text("""
        INSERT INTO fitness_athlete_profile (id, user_id, height_cm) VALUES (:id, :u, 180)
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.execute(text("""
        INSERT INTO fitness_athlete_profile_change
            (id, user_id, field, old_value, new_value, from_version, to_version)
        VALUES (:id, :u, 'height_cm', '180'::jsonb, '181.5'::jsonb, 1, 2)
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()
    row = pg.execute(text("""
        SELECT field, old_value, new_value, from_version, to_version
        FROM fitness_athlete_profile_change WHERE user_id = :u
    """), {"u": alice}).fetchone()
    assert row.field == "height_cm"
    assert (row.from_version, row.to_version) == (1, 2)


@requires_pg
def test_profile_cascades_with_its_athlete(pg, two_athletes):
    """Deleting an account removes its fitness profile; that is the privacy
    deletion path, so the FK has to actually cascade."""
    alice, _ = two_athletes
    pg.execute(text("""
        INSERT INTO fitness_athlete_profile (id, user_id) VALUES (:id, :u)
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()
    pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": alice})
    pg.commit()
    assert pg.execute(text(
        "SELECT COUNT(*) FROM fitness_athlete_profile WHERE user_id = :u"), {"u": alice}
    ).scalar() == 0


# ─────────────────────────────────────────────────────────────────────────
# Goals: valid time
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_two_overlapping_primary_goals_are_rejected(pg, two_athletes):
    """The database-level rule.

    One primary goal is in force on any given day. Without this, "what was I
    training for on the 14th" has two answers and the review that cites it is
    arbitrary.
    """
    alice, _ = two_athletes
    _goal(pg, alice, valid_from=date(2026, 1, 1), valid_until=date(2026, 3, 1))
    pg.commit()

    with pytest.raises(IntegrityError) as e:
        _goal(pg, alice, kind="cut", valid_from=date(2026, 2, 1),
              valid_until=date(2026, 4, 1))
        pg.commit()
    assert "no_overlap" in str(e.value) or "exclusion" in str(e.value).lower()
    pg.rollback()


@requires_pg
def test_goal_intervals_are_half_open_so_handover_days_do_not_overlap(pg, two_athletes):
    """`[Jan 1, Mar 1)` then `[Mar 1, ...)` is contiguous, not overlapping.

    `fitness_phase.end_date` is inclusive, which would make the same pair a
    conflict. Mixing the conventions is exactly the bug the half-open rule
    exists to prevent.
    """
    alice, _ = two_athletes
    _goal(pg, alice, valid_from=date(2026, 1, 1), valid_until=date(2026, 3, 1))
    _goal(pg, alice, kind="cut", valid_from=date(2026, 3, 1), valid_until=None)
    pg.commit()
    assert pg.execute(text(
        "SELECT COUNT(*) FROM fitness_athlete_goal WHERE user_id = :u"), {"u": alice}
    ).scalar() == 2


@requires_pg
def test_an_open_ended_primary_goal_blocks_a_later_overlapping_one(pg, two_athletes):
    """An unbounded `valid_until` means "still current", and `daterange` with
    a NULL upper bound models that — so a goal starting next month overlaps
    it and must be refused until the current one is closed."""
    alice, _ = two_athletes
    _goal(pg, alice, valid_from=date(2026, 1, 1), valid_until=None)
    pg.commit()
    with pytest.raises(IntegrityError):
        _goal(pg, alice, kind="cut", valid_from=date(2026, 6, 1))
        pg.commit()
    pg.rollback()


@requires_pg
def test_rollover_closes_the_old_goal_and_preserves_it(pg, two_athletes):
    """Superseding is not deleting.

    A review from March reasoned about March's goal; removing it makes that
    review's rationale unverifiable.
    """
    alice, _ = two_athletes
    old = _goal(pg, alice, valid_from=date(2026, 1, 1), valid_until=None)
    pg.commit()

    pg.execute(text("""
        UPDATE fitness_athlete_goal SET valid_until = :d WHERE id = :id
    """), {"d": date(2026, 3, 1), "id": old})
    new = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_athlete_goal
            (id, user_id, kind, is_primary, rate_basis, target_rate_kg_week,
             valid_from, supersedes_id)
        VALUES (:id, :u, 'cut', TRUE, 'absolute', -0.35, :d, :old)
    """), {"id": new, "u": alice, "d": date(2026, 3, 1), "old": old})
    pg.commit()

    rows = pg.execute(text("""
        SELECT id, kind, valid_from, valid_until, supersedes_id
        FROM fitness_athlete_goal WHERE user_id = :u ORDER BY valid_from
    """), {"u": alice}).fetchall()
    assert len(rows) == 2, "the superseded interval must survive"
    assert rows[0].valid_until == date(2026, 3, 1)
    assert rows[1].supersedes_id == rows[0].id

    # As-of resolution: a date inside the old interval resolves to the old goal.
    on_feb = pg.execute(text("""
        SELECT kind FROM fitness_athlete_goal
        WHERE user_id = :u AND is_primary
          AND valid_from <= :d AND (valid_until IS NULL OR valid_until > :d)
    """), {"u": alice, "d": date(2026, 2, 14)}).scalar()
    assert on_feb == "hypertrophy", "history is queryable without replaying memory"

    on_apr = pg.execute(text("""
        SELECT kind FROM fitness_athlete_goal
        WHERE user_id = :u AND is_primary
          AND valid_from <= :d AND (valid_until IS NULL OR valid_until > :d)
    """), {"u": alice, "d": date(2026, 4, 1)}).scalar()
    assert on_apr == "cut"


@requires_pg
def test_several_non_primary_goals_may_coexist(pg, two_athletes):
    """"Gain strength" and "keep the waist under 34in" are not in conflict."""
    alice, _ = two_athletes
    _goal(pg, alice, valid_from=date(2026, 1, 1))
    _goal(pg, alice, kind="strength", primary=False, priority=2,
          valid_from=date(2026, 1, 1))
    _goal(pg, alice, kind="recomp", primary=False, priority=3,
          valid_from=date(2026, 1, 1))
    pg.commit()
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_athlete_goal WHERE user_id = :u AND NOT is_primary
    """), {"u": alice}).scalar() == 2


@requires_pg
def test_overlap_rule_is_per_athlete(pg, two_athletes):
    """Bob's goal must not collide with Alice's."""
    alice, bob = two_athletes
    _goal(pg, alice, valid_from=date(2026, 1, 1))
    _goal(pg, bob, valid_from=date(2026, 1, 1))
    pg.commit()
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_athlete_goal WHERE user_id = ANY(:ids)
    """), {"ids": [alice, bob]}).scalar() == 2


# ─────────────────────────────────────────────────────────────────────────
# Goals: coherence
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_cut_cannot_prescribe_gaining(pg, two_athletes):
    alice, _ = two_athletes
    with pytest.raises(IntegrityError):
        _goal(pg, alice, kind="cut", rate_basis="absolute", kg_week=0.3,
              valid_from=date(2026, 1, 1))
        pg.commit()
    pg.rollback()


@requires_pg
def test_a_gain_cannot_prescribe_losing(pg, two_athletes):
    alice, _ = two_athletes
    with pytest.raises(IntegrityError):
        _goal(pg, alice, kind="gain", rate_basis="percent", pct_week=-0.4,
              valid_from=date(2026, 1, 1))
        pg.commit()
    pg.rollback()


@requires_pg
def test_rate_basis_must_match_the_populated_field(pg, two_athletes):
    """Both rate fields populated makes the athlete's actual choice unknowable."""
    alice, _ = two_athletes
    for basis, kg, pct in (
        ("absolute", None, None),      # claims absolute, supplies nothing
        ("percent", 0.25, None),       # claims percent, supplies absolute
        ("none", 0.25, None),          # claims neither, supplies one
        ("absolute", 0.25, 0.3),       # supplies both
    ):
        with pytest.raises(IntegrityError):
            _goal(pg, alice, kind="gain", rate_basis=basis, kg_week=kg,
                  pct_week=pct, valid_from=date(2026, 1, 1))
            pg.commit()
        pg.rollback()


@requires_pg
def test_backwards_interval_and_zero_length_interval_rejected(pg, two_athletes):
    alice, _ = two_athletes
    for vf, vu in ((date(2026, 3, 1), date(2026, 1, 1)),
                   (date(2026, 3, 1), date(2026, 3, 1))):
        with pytest.raises(IntegrityError):
            _goal(pg, alice, valid_from=vf, valid_until=vu)
            pg.commit()
        pg.rollback()


@requires_pg
def test_absurd_target_weight_rejected(pg, two_athletes):
    alice, _ = two_athletes
    for w in (0, -5, 900):
        with pytest.raises(IntegrityError):
            pg.execute(text("""
                INSERT INTO fitness_athlete_goal
                    (id, user_id, kind, valid_from, target_weight_kg)
                VALUES (:id, :u, 'cut', :d, :w)
            """), {"id": str(uuid.uuid4()), "u": alice, "d": date(2026, 1, 1), "w": w})
            pg.commit()
        pg.rollback()


@requires_pg
def test_strength_targets_are_jsonb_not_text(pg, two_athletes):
    """JSONB so a target can be queried by lift without parsing in Python."""
    alice, _ = two_athletes
    pg.execute(text("""
        INSERT INTO fitness_athlete_goal
            (id, user_id, kind, valid_from, strength_targets)
        VALUES (:id, :u, 'strength', :d, '{"back_squat_kg": 180, "bench_kg": 125}'::jsonb)
    """), {"id": str(uuid.uuid4()), "u": alice, "d": date(2026, 1, 1)})
    pg.commit()
    squat = pg.execute(text("""
        SELECT (strength_targets->>'back_squat_kg')::numeric
        FROM fitness_athlete_goal WHERE user_id = :u
    """), {"u": alice}).scalar()
    assert float(squat) == 180


# ─────────────────────────────────────────────────────────────────────────
# Limitations
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_limitation_has_no_diagnosis_column(pg):
    """Pain is a report, not a finding.

    A `diagnosis` column would invite exactly the clinical conclusion §13
    forbids, and once stored it would be cited as fact by every downstream
    reader.
    """
    columns = {r[0] for r in pg.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'fitness_athlete_limitation'
    """)).fetchall()}
    for forbidden in ("diagnosis", "condition", "icd_code", "injury_type"):
        assert forbidden not in columns, f"{forbidden} is a clinical conclusion"
    assert "severity_flag" in columns and "description" in columns


@requires_pg
def test_resolved_limitations_are_retained_and_queryable_as_of_a_date(pg, two_athletes):
    alice, _ = two_athletes
    pg.execute(text("""
        INSERT INTO fitness_athlete_limitation
            (id, user_id, area, effective_from, effective_until, status, severity_flag)
        VALUES (:id, :u, 'right shoulder', :f, :t, 'resolved', 'moderate')
    """), {"id": str(uuid.uuid4()), "u": alice,
           "f": date(2026, 1, 10), "t": date(2026, 2, 20)})
    pg.execute(text("""
        INSERT INTO fitness_athlete_limitation
            (id, user_id, area, effective_from, status)
        VALUES (:id, :u, 'left knee', :f, 'active')
    """), {"id": str(uuid.uuid4()), "u": alice, "f": date(2026, 3, 1)})
    pg.commit()

    active_in_jan = pg.execute(text("""
        SELECT area FROM fitness_athlete_limitation
        WHERE user_id = :u AND effective_from <= :d
          AND (effective_until IS NULL OR effective_until > :d)
    """), {"u": alice, "d": date(2026, 1, 20)}).scalars().all()
    assert active_in_jan == ["right shoulder"], (
        "a review from January reasoned under January's constraints"
    )

    active_now = pg.execute(text("""
        SELECT area FROM fitness_athlete_limitation
        WHERE user_id = :u AND status = 'active'
    """), {"u": alice}).scalars().all()
    assert active_now == ["left knee"]


@requires_pg
def test_limitation_status_and_severity_are_constrained(pg, two_athletes):
    alice, _ = two_athletes
    for col, bad in (("status", "kinda-hurts"), ("severity_flag", "catastrophic")):
        with pytest.raises(IntegrityError):
            pg.execute(text(f"""
                INSERT INTO fitness_athlete_limitation
                    (id, user_id, area, effective_from, {col})
                VALUES (:id, :u, 'elbow', :d, :v)
            """), {"id": str(uuid.uuid4()), "u": alice, "d": date(2026, 1, 1), "v": bad})
            pg.commit()
        pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Migration shape
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_m1_did_not_touch_existing_fitness_records(pg, two_athletes):
    """Additive means additive.

    An existing phase with its own macros must read back byte-identical after
    the athlete tables land — those columns are still the current projection
    until Step 6's resolver takes over.
    """
    alice, _ = two_athletes
    pid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_phase
            (id, user_id, name, start_date, end_date, status,
             calories_target, protein_target, carbs_target, fat_target,
             calories_training_day, calories_rest_day, created_at, updated_at)
        VALUES (:id, :u, 'Pre-existing block', :s, :e, 'active',
                2900, 195, 320, 85, 3100, 2700, NOW(), NOW())
    """), {"id": pid, "u": alice, "s": date(2026, 1, 1), "e": date(2026, 2, 28)})
    pg.commit()
    try:
        row = pg.execute(text("""
            SELECT calories_target, protein_target, calories_training_day,
                   calories_rest_day, end_date
            FROM fitness_phase WHERE id = :id
        """), {"id": pid}).fetchone()
        assert row.calories_target == 2900
        assert row.protein_target == 195
        assert row.calories_training_day == 3100
        assert row.calories_rest_day == 2700
        assert row.end_date == date(2026, 2, 28), (
            "phase end_date is still INCLUSIVE; the resolver converts, the "
            "migration does not rewrite"
        )
    finally:
        pg.rollback()
        pg.execute(text("DELETE FROM fitness_phase WHERE id = :id"), {"id": pid})
        pg.commit()


@requires_pg
def test_indexes_support_as_of_date_resolution(pg):
    present = {r[0] for r in pg.execute(text(
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")).fetchall()}
    assert {
        "ix_athlete_goal_user_from",
        "ix_athlete_goal_user_primary",
        "ix_athlete_limitation_user_status",
        "ix_athlete_limitation_user_dates",
        "ix_athlete_profile_change_user_time",
    } <= present


@requires_pg
def test_orm_models_map_on_the_modular_base_not_the_monolith(pg):
    """Both bases exist in this process (gotcha 4).

    These tables must be registered on `app.db.base.Base` — the one
    `app/models/*` uses — and must NOT need `extend_existing`, because none
    of them maps a table something else already registered.
    """
    from app.db.base import Base as ModularBase
    from app.models import fitness_coach as fc

    for model in (fc.AthleteProfile, fc.AthleteGoal, fc.AthleteLimitation,
                  fc.TargetRevision, fc.AthleteProfileChange):
        assert model.metadata is ModularBase.metadata, (
            f"{model.__name__} is registered on the wrong declarative base"
        )
        assert not model.__table__.kwargs.get("extend_existing"), (
            f"{model.__name__} should not need extend_existing: it is a new table"
        )

    for name in ("fitness_athlete_profile", "fitness_athlete_goal",
                 "fitness_athlete_limitation", "fitness_target_revision"):
        assert name in ModularBase.metadata.tables


@requires_pg
def test_roundtrip_through_the_orm(pg, two_athletes):
    """The classes are usable for real reads, not decoration."""
    from app.models.fitness_coach import AthleteGoal, AthleteProfile

    alice, _ = two_athletes
    pg.add(AthleteProfile(user_id=alice, height_cm=182.5, training_level="advanced",
                          equipment=["barbell", "dumbbells", "cable"],
                          excluded_exercise_ids=[]))
    pg.add(AthleteGoal(user_id=alice, kind="powerbuilding", is_primary=True,
                       rate_basis="absolute", target_rate_kg_week=0.15,
                       valid_from=date(2026, 10, 1),
                       strength_targets={"back_squat_kg": 200}))
    pg.commit()

    profile = pg.query(AthleteProfile).filter_by(user_id=alice).one()
    assert float(profile.height_cm) == 182.5
    assert profile.equipment == ["barbell", "dumbbells", "cable"]
    assert profile.row_version == 1

    goal = pg.query(AthleteGoal).filter_by(user_id=alice).one()
    assert goal.kind == "powerbuilding"
    assert float(goal.target_rate_kg_week) == 0.15
    assert goal.strength_targets["back_squat_kg"] == 200
    assert goal.valid_until is None
