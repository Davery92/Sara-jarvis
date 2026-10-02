"""Step 12 of FITNESS_COACH_IMPLEMENTATION_PLAN: aliases group the same
variant without merging different movements or different athletes.

What is at stake is PR history. If "Barbell Bench" and "BB Bench" are two
lifts, neither has a complete record. If "Bench Press" and "Smith Machine
Bench Press" are one lift, the record belongs to whichever was easier. Both
failures are silent, and both corrupt the number the athlete cares most
about.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_exercise_normalization_pg.py
"""
import os
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
)

UTC = timezone.utc


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
    alice = f"m6a-{uuid.uuid4().hex[:18]}"
    bob = f"m6b-{uuid.uuid4().hex[:18]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@m6.invalid", "p": unusable_hash})
    pg.commit()
    yield alice, bob
    pg.rollback()
    pg.execute(text("DELETE FROM exercise_pr WHERE user_id = ANY(:ids)"),
               {"ids": [alice, bob]})
    pg.execute(text("DELETE FROM workout_log WHERE user_id = ANY(:ids)"),
               {"ids": [alice, bob]})
    pg.execute(text("DELETE FROM workout WHERE user_id = ANY(:ids)"),
               {"ids": [alice, bob]})
    pg.execute(text("""
        DELETE FROM fitness_exercise_alias
        WHERE owner_user_id = ANY(:ids)
           OR exercise_library_id IN (
               SELECT id FROM exercise_library WHERE name LIKE 'M6TEST %'
           )
    """), {"ids": [alice, bob]})
    pg.execute(text("DELETE FROM exercise_library WHERE name LIKE 'M6TEST %'"))
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"), {"ids": [alice, bob]})
    pg.commit()


def _exercise(pg, name, *, convention="total", parent=None, variation=None,
              unilateral=False, primary=None, owner=None, visibility=None):
    """A global exercise plus its self-name alias, as the migration seeds."""
    import json
    from app.schemas.fitness_coach import normalize_code

    eid = str(uuid.uuid4())
    norm = normalize_code(name)
    vis = visibility or ("private" if owner else "unscoped")
    pg.execute(text("""
        INSERT INTO exercise_library
            (id, name, normalized_name, movement_pattern, load_convention,
             parent_exercise_id, variation_code, is_unilateral, primary_muscles,
             owner_user_id, visibility, created_at, updated_at)
        VALUES (:id, :name, :norm, 'push', :conv, :parent, :var, :uni,
                CAST(:primary AS jsonb), :owner, :vis, NOW(), NOW())
    """), {"id": eid, "name": name, "norm": norm, "conv": convention,
           "parent": parent, "var": variation, "uni": unilateral,
           "primary": json.dumps(list(primary or [])), "owner": owner, "vis": vis})
    pg.execute(text("""
        INSERT INTO fitness_exercise_alias
            (id, normalized_alias, display_alias, exercise_library_id,
             owner_user_id, locale, review_status, source, reviewed_at)
        VALUES (:aid, :norm, :name, :eid, :owner, 'en', 'reviewed', 'self_name', NOW())
    """), {"aid": str(uuid.uuid4()), "norm": norm, "name": name, "eid": eid,
           "owner": owner})
    return eid


def _workout(pg, user_id) -> str:
    wid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO workout (id, user_id, title, status, created_at, updated_at)
        VALUES (:id, :u, 'M6 fixture', 'completed', NOW(), NOW())
    """), {"id": wid, "u": user_id})
    return wid


def _set(pg, user_id, workout_id, exercise_name, *, canonical=None,
         weight=100, reps=5):
    sid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO workout_log
            (id, workout_id, user_id, exercise_id, exercise_library_id,
             set_index, weight, reps, set_kind, session_date, created_at)
        VALUES (:id, :w, :u, :ex, :canon, 1, :wt, :reps, 'working',
                CURRENT_DATE, NOW())
    """), {"id": sid, "w": workout_id, "u": user_id, "ex": exercise_name,
           "canon": canonical, "wt": weight, "reps": reps})
    return sid


# ─────────────────────────────────────────────────────────────────────────
# Normalization
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_spelling_variants_resolve_to_one_exercise(pg, two_athletes):
    """The point of normalization.

    These are one lift. Treating them as four means none has a complete
    record.
    """
    from app.services.fitness.exercises import add_alias, resolve_exercise

    alice, _ = two_athletes
    bench = _exercise(pg, "M6TEST Barbell Bench Press", convention="total")
    for alias in ("BB Bench", "Barbell Bench", "bench press flat"):
        add_alias(pg, alice, alias, bench, source="test")

    for query in (
        "M6TEST Barbell Bench Press",
        "m6test barbell bench press",
        "M6TEST  Barbell-Bench_Press!",
        "BB Bench",
        "bb  bench",
        "BB-BENCH",
        "Barbell Bench",
        "bench press flat",
    ):
        resolved = resolve_exercise(pg, alice, query)
        assert resolved is not None, f"{query!r} did not resolve"
        assert resolved.id == bench, f"{query!r} resolved to the wrong lift"


@requires_pg
def test_an_unknown_name_resolves_to_nothing_rather_than_a_guess(pg, two_athletes):
    from app.services.fitness.exercises import resolve_exercise
    alice, _ = two_athletes
    _exercise(pg, "M6TEST Barbell Bench Press")
    assert resolve_exercise(pg, alice, "Zercher Hack Squat Machine") is None
    assert resolve_exercise(pg, alice, "") is None
    assert resolve_exercise(pg, alice, "!!!") is None


@requires_pg
def test_every_exercise_has_its_own_name_as_an_alias_in_its_own_scope(pg):
    """So `resolve("Bench Press")` needs no separate name-matching path.

    The alias is scoped the way the exercise is: a GLOBAL exercise gets a
    global alias (migration 165 seeded those), and a PRIVATE one gets an
    alias owned by its athlete — which is the point of
    `create_custom_exercise`, because the name is something the athlete
    wrote.

    An earlier version of this test sampled any five rows and demanded a
    global alias for each. It passed only because another test leaked
    private exercises into the table; with those cleaned up, the disposable
    stack's schema fixture seeds no exercise catalogue at all, so there was
    nothing to sample. It now checks the invariant per scope and says so
    when the catalogue is empty.
    """
    rows = pg.execute(text("""
        SELECT e.id, e.name, e.normalized_name, e.owner_user_id
        FROM exercise_library e
        WHERE e.normalized_name IS NOT NULL AND e.normalized_name <> ''
          AND (SELECT COUNT(*) FROM exercise_library d
               WHERE d.normalized_name = e.normalized_name) = 1
        LIMIT 10
    """)).fetchall()
    if not rows:
        pytest.skip(
            "this stack seeds no exercise catalogue; the resolve-by-own-name "
            "path is covered by the tests below, which create their own"
        )
    for row in rows:
        alias = pg.execute(text("""
            SELECT exercise_library_id FROM fitness_exercise_alias
            WHERE normalized_alias = :n
              AND owner_user_id IS NOT DISTINCT FROM :owner
        """), {"n": row.normalized_name, "owner": row.owner_user_id}).scalar()
        assert alias == row.id, (
            f"{row.name!r} has no self-alias in its own scope "
            f"(owner={row.owner_user_id})"
        )


@requires_pg
def test_a_privately_created_exercise_resolves_by_its_own_name(pg, two_athletes):
    """The invariant that matters at runtime, with a row this test owns.

    `create_custom_exercise` writes the self-alias; without it the athlete
    would have to resolve their own exercise by id, which nothing in a
    conversation has.
    """
    from app.services.fitness.exercises import create_custom_exercise, resolve_exercise

    alice, _ = two_athletes
    created = create_custom_exercise(pg, alice, "Zercher Carry Thing")
    pg.commit()

    resolved = resolve_exercise(pg, alice, "zercher carry thing")
    assert resolved is not None
    assert resolved.id == created.id
    # Private: the name is something the athlete wrote.
    owner = pg.execute(text("""
        SELECT owner_user_id FROM fitness_exercise_alias
        WHERE exercise_library_id = :id
    """), {"id": created.id}).scalar()
    assert owner == alice


# ─────────────────────────────────────────────────────────────────────────
# Ambiguity
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_two_exercises_sharing_a_name_are_ambiguous_not_silently_merged(
    pg, two_athletes,
):
    """The real ambiguity case, and the one the migration leaves unaliased.

    Migration 165 deliberately skips seeding a self-alias for a name two rows
    share — picking one would be the silent merge this module exists to
    prevent. Resolution surfaces the candidates instead of returning None,
    so the caller can ask rather than being left with nothing.
    """
    import uuid as _uuid
    from app.services.fitness.exercises import AmbiguousExercise, resolve_exercise

    alice, _ = two_athletes
    # Two rows, same normalized name, neither aliased — exactly the shape the
    # migration refuses to disambiguate.
    first, second = str(_uuid.uuid4()), str(_uuid.uuid4())
    for eid, convention in ((first, "total"), (second, "per_hand")):
        pg.execute(text("""
            INSERT INTO exercise_library
                (id, name, normalized_name, movement_pattern, load_convention,
                 created_at, updated_at)
            VALUES (:id, 'M6TEST Bench', 'm6test_bench', 'push', :conv, NOW(), NOW())
        """), {"id": eid, "conv": convention})
    pg.commit()

    with pytest.raises(AmbiguousExercise) as e:
        resolve_exercise(pg, alice, "M6TEST Bench")
    assert len(e.value.candidates) == 2
    assert {c.id for c in e.value.candidates} == {first, second}
    assert "could mean" in str(e.value)


@requires_pg
def test_the_alias_index_makes_same_scope_ambiguity_impossible(pg, two_athletes):
    """Why the raise above comes from name collision, not from aliases.

    `uq_exercise_alias_scope` is a partial unique index over
    `(owner, locale, normalized_alias)` for reviewed rows, so two reviewed
    aliases for one string in one scope cannot exist. Across scopes,
    own-beats-global settles it. That is the design: ambiguity is prevented
    at the write, not resolved at the read.
    """
    alice, _ = two_athletes
    a = _exercise(pg, "M6TEST Lift One")
    b = _exercise(pg, "M6TEST Lift Two")
    pg.commit()

    pg.execute(text("""
        INSERT INTO fitness_exercise_alias
            (id, normalized_alias, display_alias, exercise_library_id,
             owner_user_id, locale, review_status, source, reviewed_at)
        VALUES (:id, 'm6test_collide', 'Collide', :eid, NULL, 'en',
                'reviewed', 'test', NOW())
    """), {"id": str(uuid.uuid4()), "eid": a})
    pg.commit()

    with pytest.raises(IntegrityError):
        pg.execute(text("""
            INSERT INTO fitness_exercise_alias
                (id, normalized_alias, display_alias, exercise_library_id,
                 owner_user_id, locale, review_status, source, reviewed_at)
            VALUES (:id, 'm6test_collide', 'Collide', :eid, NULL, 'en',
                    'reviewed', 'test', NOW())
        """), {"id": str(uuid.uuid4()), "eid": b})
        pg.commit()
    pg.rollback()


@requires_pg
def test_the_athletes_own_alias_outranks_a_global_one(pg, two_athletes):
    """They chose that mapping for themselves."""
    from app.services.fitness.exercises import add_alias, resolve_exercise

    alice, _ = two_athletes
    barbell = _exercise(pg, "M6TEST Barbell Bench Press")
    dumbbell = _exercise(pg, "M6TEST Dumbbell Bench Press", convention="per_hand")

    pg.execute(text("""
        INSERT INTO fitness_exercise_alias
            (id, normalized_alias, display_alias, exercise_library_id,
             owner_user_id, locale, review_status, source, reviewed_at)
        VALUES (:id, 'bench', 'Bench', :eid, NULL, 'en', 'reviewed', 'test', NOW())
    """), {"id": str(uuid.uuid4()), "eid": barbell})
    pg.commit()
    add_alias(pg, alice, "Bench", dumbbell, source="test")

    assert resolve_exercise(pg, alice, "Bench").id == dumbbell


@requires_pg
def test_adding_a_conflicting_alias_is_refused(pg, two_athletes):
    """Replacing a mapping would retroactively move every set logged under it."""
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.exercises import add_alias

    alice, _ = two_athletes
    barbell = _exercise(pg, "M6TEST Barbell Bench Press")
    dumbbell = _exercise(pg, "M6TEST Dumbbell Bench Press", convention="per_hand")
    add_alias(pg, alice, "Bench", barbell, source="test")

    with pytest.raises(FitnessDataError) as e:
        add_alias(pg, alice, "Bench", dumbbell, source="test")
    assert "already means something else" in str(e.value)
    pg.rollback()


@requires_pg
def test_re_adding_the_same_alias_is_idempotent(pg, two_athletes):
    from app.services.fitness.exercises import add_alias
    alice, _ = two_athletes
    bench = _exercise(pg, "M6TEST Barbell Bench Press")
    first = add_alias(pg, alice, "BB Bench", bench, source="test")
    second = add_alias(pg, alice, "bb  bench", bench, source="test")
    assert first == second


@requires_pg
def test_the_unique_index_refuses_a_duplicate_reviewed_alias(pg, two_athletes):
    """The service refuses, and so does the database."""
    alice, _ = two_athletes
    a = _exercise(pg, "M6TEST Lift A")
    b = _exercise(pg, "M6TEST Lift B")
    pg.commit()
    with pytest.raises(IntegrityError):
        for eid in (a, b):
            pg.execute(text("""
                INSERT INTO fitness_exercise_alias
                    (id, normalized_alias, display_alias, exercise_library_id,
                     owner_user_id, locale, review_status, source)
                VALUES (:id, 'm6test_dupe', 'Dupe', :eid, :u, 'en', 'reviewed', 'test')
            """), {"id": str(uuid.uuid4()), "eid": eid, "u": alice})
        pg.commit()
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Fuzzy matching is a suggestion, never a resolution
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_fuzzy_match_suggests_but_never_resolves(pg, two_athletes):
    """A guess that silently becomes a set's identity misattributes a PR."""
    from app.services.fitness.exercises import resolve_exercise, suggest_exercises

    alice, _ = two_athletes
    incline = _exercise(pg, "M6TEST Incline Barbell Bench Press")
    pg.commit()

    assert resolve_exercise(pg, alice, "incline bench") is None, (
        "a partial name must not resolve"
    )
    suggestions = suggest_exercises(pg, alice, "incline bench")
    assert incline in [s.id for s in suggestions] or any(
        s.id == incline for s in suggestions
    )


@requires_pg
def test_an_inferred_alias_is_never_used_for_resolution(pg, two_athletes):
    """Excluded by the index's WHERE clause, not by convention.

    An automated suggestion becoming an athlete's exercise identity is
    exactly what the review status prevents.
    """
    from app.services.fitness.exercises import (
        record_inferred_alias, resolve_exercise,
    )

    alice, _ = two_athletes
    bench = _exercise(pg, "M6TEST Barbell Bench Press")
    record_inferred_alias(pg, alice, "Chest Day Main Lift", bench)
    pg.commit()

    assert resolve_exercise(pg, alice, "Chest Day Main Lift") is None
    stored = pg.execute(text("""
        SELECT review_status FROM fitness_exercise_alias
        WHERE normalized_alias = 'chest_day_main_lift'
    """)).scalar()
    assert stored == "inferred"


# ─────────────────────────────────────────────────────────────────────────
# Variants keep separate histories
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_equipment_variants_share_a_parent_but_not_an_identity(pg, two_athletes):
    """Barbell and dumbbell bench are one movement and two records.

    Sharing a record would credit the dumbbell PR to the barbell.
    """
    from app.services.fitness.exercises import (
        get_exercise, resolve_exercise, share_comparison_identity,
    )

    alice, _ = two_athletes
    parent = _exercise(pg, "M6TEST Horizontal Press")
    barbell = _exercise(pg, "M6TEST Barbell Bench Press", parent=parent,
                        variation="barbell", convention="total")
    dumbbell = _exercise(pg, "M6TEST Dumbbell Bench Press", parent=parent,
                         variation="dumbbell", convention="per_hand")
    pg.commit()

    bb = get_exercise(pg, alice, barbell)
    db_ = get_exercise(pg, alice, dumbbell)
    assert bb.parent_exercise_id == db_.parent_exercise_id == parent
    assert bb.id != db_.id
    assert not share_comparison_identity(bb, db_), (
        "a shared parent must not mean a shared PR"
    )
    assert share_comparison_identity(bb, bb)


@requires_pg
def test_a_machine_variant_is_a_separate_exercise(pg, two_athletes):
    from app.services.fitness.exercises import resolve_exercise

    alice, _ = two_athletes
    free = _exercise(pg, "M6TEST Barbell Bench Press", convention="total")
    smith = _exercise(pg, "M6TEST Smith Machine Bench Press", convention="stack")
    pg.commit()

    assert resolve_exercise(pg, alice, "M6TEST Barbell Bench Press").id == free
    assert resolve_exercise(pg, alice, "M6TEST Smith Machine Bench Press").id == smith
    assert free != smith


@requires_pg
def test_an_exercise_cannot_be_its_own_parent(pg, two_athletes):
    alice, _ = two_athletes
    eid = _exercise(pg, "M6TEST Self Parent")
    pg.commit()
    with pytest.raises(IntegrityError):
        pg.execute(text("""
            UPDATE exercise_library SET parent_exercise_id = id WHERE id = :id
        """), {"id": eid})
        pg.commit()
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Load conventions
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_per_hand_load_doubles_and_other_conventions_refuse(pg, two_athletes):
    """40 kg per hand is 80 kg moved; 40 kg of assistance is not 40 kg lifted."""
    from app.services.fitness.exercises import effective_load_for, get_exercise

    alice, _ = two_athletes
    total = _exercise(pg, "M6TEST Total Load Lift", convention="total")
    per_hand = _exercise(pg, "M6TEST Per Hand Lift", convention="per_hand")
    assisted = _exercise(pg, "M6TEST Assisted Lift", convention="assisted")
    bodyweight = _exercise(pg, "M6TEST Bodyweight Lift", convention="bodyweight")
    stack = _exercise(pg, "M6TEST Stack Lift", convention="stack")
    unknown = _exercise(pg, "M6TEST Unknown Convention", convention=None)
    pg.commit()

    assert effective_load_for(get_exercise(pg, alice, total), 100.0) == (100.0, None)
    assert effective_load_for(get_exercise(pg, alice, per_hand), 40.0) == (80.0, None)

    value, reason = effective_load_for(get_exercise(pg, alice, assisted), 40.0)
    assert value is None and "more help is less work" in reason

    value, reason = effective_load_for(get_exercise(pg, alice, bodyweight), 0.0)
    assert value is None and "no external load" in reason

    value, reason = effective_load_for(get_exercise(pg, alice, stack), 40.0)
    assert value is None and "not comparable to free weight" in reason

    # An unrecorded convention is refused, not assumed to be `total`.
    value, reason = effective_load_for(get_exercise(pg, alice, unknown), 100.0)
    assert value is None and "never recorded" in reason

    assert effective_load_for(None, 100.0)[0] is None


@requires_pg
def test_only_comparable_conventions_may_enter_a_volume_figure(pg, two_athletes):
    from app.services.fitness.exercises import get_exercise

    alice, _ = two_athletes
    cases = {
        "total": True, "per_hand": True,
        "assisted": False, "bodyweight": False, "stack": False,
    }
    for convention, comparable in cases.items():
        eid = _exercise(pg, f"M6TEST {convention} Case", convention=convention)
        pg.commit()
        ref = get_exercise(pg, alice, eid)
        assert ref.load_is_comparable is comparable, convention

    unknown = _exercise(pg, "M6TEST No Convention Case", convention=None)
    pg.commit()
    assert get_exercise(pg, alice, unknown).load_is_comparable is False


@requires_pg
def test_an_invalid_load_convention_is_refused_by_the_constraint(pg, two_athletes):
    alice, _ = two_athletes
    with pytest.raises(IntegrityError):
        pg.execute(text("""
            INSERT INTO exercise_library
                (id, name, movement_pattern, load_convention, created_at, updated_at)
            VALUES (:id, 'M6TEST Bad Convention', 'push', 'vibes', NOW(), NOW())
        """), {"id": str(uuid.uuid4())})
        pg.commit()
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Private custom exercises
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_custom_exercise_is_private_to_its_creator(pg, two_athletes):
    """Its name is something the athlete wrote."""
    from app.services.fitness.exercises import (
        create_custom_exercise, get_exercise, list_exercises, resolve_exercise,
    )

    alice, bob = two_athletes
    created = create_custom_exercise(
        pg, alice, "M6TEST Alices Cable Thing", load_convention="stack",
    )
    assert created.visibility == "private"
    assert created.owner_user_id == alice

    assert resolve_exercise(pg, alice, "M6TEST Alices Cable Thing").id == created.id
    assert resolve_exercise(pg, bob, "M6TEST Alices Cable Thing") is None
    assert get_exercise(pg, bob, created.id) is None

    bobs_catalog = {e.id for e in list_exercises(pg, bob)}
    assert created.id not in bobs_catalog


@requires_pg
def test_a_custom_exercise_refuses_an_invalid_convention(pg, two_athletes):
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.exercises import create_custom_exercise

    alice, _ = two_athletes
    with pytest.raises(FitnessDataError) as e:
        create_custom_exercise(pg, alice, "M6TEST Bad", load_convention="vibes")
    assert "not a load convention" in str(e.value)
    pg.rollback()


@requires_pg
def test_a_custom_exercise_cannot_shadow_a_name_the_athlete_can_resolve(
    pg, two_athletes,
):
    """The new row would be unreachable by name."""
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.exercises import create_custom_exercise

    alice, _ = two_athletes
    _exercise(pg, "M6TEST Barbell Bench Press")
    pg.commit()
    with pytest.raises(FitnessDataError) as e:
        create_custom_exercise(pg, alice, "M6TEST Barbell Bench Press")
    assert "already resolves" in str(e.value)
    pg.rollback()


@requires_pg
def test_two_athletes_may_each_have_a_private_exercise_with_the_same_name(
    pg, two_athletes,
):
    from app.services.fitness.exercises import create_custom_exercise, resolve_exercise

    alice, bob = two_athletes
    a = create_custom_exercise(pg, alice, "M6TEST My Weird Lift")
    b = create_custom_exercise(pg, bob, "M6TEST My Weird Lift")
    assert a.id != b.id
    assert resolve_exercise(pg, alice, "M6TEST My Weird Lift").id == a.id
    assert resolve_exercise(pg, bob, "M6TEST My Weird Lift").id == b.id


@requires_pg
def test_an_alias_cannot_point_at_another_athletes_private_exercise(pg, two_athletes):
    from app.services.fitness.exercises import add_alias, create_custom_exercise

    alice, bob = two_athletes
    alices = create_custom_exercise(pg, alice, "M6TEST Alices Private Lift")
    with pytest.raises(LookupError):
        add_alias(pg, bob, "Bobs Name For It", alices.id, source="test")
    pg.rollback()


@requires_pg
def test_a_global_alias_cannot_point_at_a_private_exercise(pg, two_athletes):
    """Publishing a global alias for a private row would expose its name."""
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.exercises import add_alias, create_custom_exercise

    alice, _ = two_athletes
    private = create_custom_exercise(pg, alice, "M6TEST Private Thing")
    with pytest.raises(FitnessDataError) as e:
        add_alias(pg, alice, "Everyones Name", private.id, scope_global=True)
    assert "private exercise" in str(e.value)
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Visibility classification
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_visibility_classification_is_dry_run_by_default(pg, two_athletes):
    from app.services.fitness.exercises import classify_visibility

    alice, _ = two_athletes
    unused = _exercise(pg, "M6TEST Nobody Uses This")
    used_by_one = _exercise(pg, "M6TEST Only Alice Uses This")
    workout = _workout(pg, alice)
    _set(pg, alice, workout, "M6TEST Only Alice Uses This", canonical=used_by_one)
    pg.commit()

    report = classify_visibility(pg, dry_run=True)
    assert report["dry_run"] is True
    assert report["global"] >= 1
    assert report["private"] >= 1
    assert "not consent to publish" in report["note"]

    # Nothing moved.
    for eid in (unused, used_by_one):
        assert pg.execute(text(
            "SELECT visibility FROM exercise_library WHERE id = :id"), {"id": eid}
        ).scalar() == "unscoped"


@requires_pg
def test_classification_makes_a_single_user_exercise_private_not_global(
    pg, two_athletes,
):
    """Publishing it would expose a user-created exercise name."""
    from app.services.fitness.exercises import classify_visibility

    alice, _ = two_athletes
    mine = _exercise(pg, "M6TEST Only Alice Uses This")
    workout = _workout(pg, alice)
    _set(pg, alice, workout, "M6TEST Only Alice Uses This", canonical=mine)
    pg.commit()

    classify_visibility(pg, dry_run=False)
    pg.commit()

    row = pg.execute(text("""
        SELECT visibility, owner_user_id FROM exercise_library WHERE id = :id
    """), {"id": mine}).fetchone()
    assert row.visibility == "private"
    assert row.owner_user_id == alice


@requires_pg
def test_classification_makes_a_multi_user_exercise_shared_not_public(pg, two_athletes):
    """Two people using a name is not consent to publish it."""
    from app.services.fitness.exercises import classify_visibility

    alice, bob = two_athletes
    shared = _exercise(pg, "M6TEST Both Use This")
    for uid in (alice, bob):
        workout = _workout(pg, uid)
        _set(pg, uid, workout, "M6TEST Both Use This", canonical=shared)
    pg.commit()

    classify_visibility(pg, dry_run=False)
    pg.commit()

    row = pg.execute(text("""
        SELECT visibility, owner_user_id FROM exercise_library WHERE id = :id
    """), {"id": shared}).fetchone()
    assert row.visibility == "shared", "shared is restricted, not global"
    assert row.owner_user_id is None


@requires_pg
def test_classification_reports_counts_never_private_names(pg, two_athletes):
    import json
    from app.services.fitness.exercises import classify_visibility

    alice, _ = two_athletes
    mine = _exercise(pg, "M6TEST Alices Very Personal Lift Name")
    workout = _workout(pg, alice)
    _set(pg, alice, workout, "M6TEST Alices Very Personal Lift Name", canonical=mine)
    pg.commit()

    report = classify_visibility(pg, dry_run=True)
    assert "Alices Very Personal Lift Name" not in json.dumps(report)


# ─────────────────────────────────────────────────────────────────────────
# Backfill
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_backfill_is_dry_run_first_and_writes_only_exact_matches(pg, two_athletes):
    from app.services.fitness.exercises import add_alias, backfill_canonical_ids

    alice, _ = two_athletes
    bench = _exercise(pg, "M6TEST Barbell Bench Press")
    add_alias(pg, alice, "BB Bench", bench, source="test")

    workout = _workout(pg, alice)
    resolvable = _set(pg, alice, workout, "BB Bench")
    unresolvable = _set(pg, alice, workout, "M6TEST Some Lift Nobody Named")
    pg.commit()

    plan = backfill_canonical_ids(pg, alice, dry_run=True)
    assert plan.dry_run is True
    assert plan.resolved == 1
    assert plan.unresolved == 1
    assert "M6TEST Some Lift Nobody Named" in plan.unresolved_names
    # Nothing written.
    assert pg.execute(text(
        "SELECT exercise_library_id FROM workout_log WHERE id = :id"),
        {"id": resolvable}).scalar() is None

    applied = backfill_canonical_ids(pg, alice, dry_run=False)
    assert applied.resolved == 1
    assert pg.execute(text(
        "SELECT exercise_library_id FROM workout_log WHERE id = :id"),
        {"id": resolvable}).scalar() == bench
    # The unresolvable one stays unresolved rather than being guessed.
    assert pg.execute(text(
        "SELECT exercise_library_id FROM workout_log WHERE id = :id"),
        {"id": unresolvable}).scalar() is None

    again = backfill_canonical_ids(pg, alice, dry_run=False)
    assert again.resolved == 0, "a re-run must be a no-op"


@requires_pg
def test_backfill_preserves_the_legacy_name_and_display(pg, two_athletes):
    from app.services.fitness.exercises import add_alias, backfill_canonical_ids

    alice, _ = two_athletes
    bench = _exercise(pg, "M6TEST Barbell Bench Press")
    add_alias(pg, alice, "BB Bench", bench, source="test")
    workout = _workout(pg, alice)
    sid = _set(pg, alice, workout, "BB Bench", weight=225, reps=5)
    pg.commit()

    backfill_canonical_ids(pg, alice, dry_run=False)
    row = pg.execute(text("""
        SELECT exercise_id, exercise_library_id, weight, reps
        FROM workout_log WHERE id = :id
    """), {"id": sid}).fetchone()
    assert row.exercise_id == "BB Bench", (
        "the name the athlete typed is preserved as the fallback identity"
    )
    assert row.exercise_library_id == bench
    assert (row.weight, row.reps) == (225, 5)


@requires_pg
def test_backfill_leaves_an_ambiguous_name_alone(pg, two_athletes):
    """Guessing would attribute sets to a movement never performed.

    And the mistake would be invisible: the set still shows the name the
    athlete typed, while the PR and progression comparisons use a different
    lift's history.
    """
    import uuid as _uuid
    from app.services.fitness.exercises import backfill_canonical_ids

    alice, _ = two_athletes
    for convention in ("total", "per_hand"):
        pg.execute(text("""
            INSERT INTO exercise_library
                (id, name, normalized_name, movement_pattern, load_convention,
                 created_at, updated_at)
            VALUES (:id, 'M6TEST Bench', 'm6test_bench', 'push', :conv, NOW(), NOW())
        """), {"id": str(_uuid.uuid4()), "conv": convention})
    workout = _workout(pg, alice)
    sid = _set(pg, alice, workout, "M6TEST Bench")
    pg.commit()

    report = backfill_canonical_ids(pg, alice, dry_run=False)
    assert report.ambiguous >= 1
    assert "M6TEST Bench" in report.ambiguous_names
    assert pg.execute(text(
        "SELECT exercise_library_id FROM workout_log WHERE id = :id"),
        {"id": sid}).scalar() is None, "an ambiguous name must not be guessed"


@requires_pg
def test_backfill_only_touches_the_requested_athletes_sets(pg, two_athletes):
    from app.services.fitness.exercises import add_alias, backfill_canonical_ids

    alice, bob = two_athletes
    bench = _exercise(pg, "M6TEST Barbell Bench Press")
    pg.execute(text("""
        INSERT INTO fitness_exercise_alias
            (id, normalized_alias, display_alias, exercise_library_id,
             owner_user_id, locale, review_status, source, reviewed_at)
        VALUES (:id, 'bb_bench', 'BB Bench', :eid, NULL, 'en', 'reviewed', 'test', NOW())
    """), {"id": str(uuid.uuid4()), "eid": bench})

    alices_set = _set(pg, alice, _workout(pg, alice), "BB Bench")
    bobs_set = _set(pg, bob, _workout(pg, bob), "BB Bench")
    pg.commit()

    backfill_canonical_ids(pg, alice, dry_run=False)
    assert pg.execute(text(
        "SELECT exercise_library_id FROM workout_log WHERE id = :id"),
        {"id": alices_set}).scalar() == bench
    assert pg.execute(text(
        "SELECT exercise_library_id FROM workout_log WHERE id = :id"),
        {"id": bobs_set}).scalar() is None


# ─────────────────────────────────────────────────────────────────────────
# PR identity
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_prs_gained_a_canonical_identity_and_a_withdrawal(pg, two_athletes):
    """A PR whose source set is corrected has to be retractable.

    Before, there was no column to record that, so the record silently stood
    on a set that no longer existed.
    """
    alice, _ = two_athletes
    bench = _exercise(pg, "M6TEST Barbell Bench Press")
    workout = _workout(pg, alice)
    sid = _set(pg, alice, workout, "M6TEST Barbell Bench Press", weight=225, reps=5)
    pr_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO exercise_pr
            (id, user_id, exercise_name, exercise_library_id, pr_kind,
             weight, reps, estimated_1rm, formula_version, load_unit,
             achieved_at, workout_set_id, created_at)
        VALUES (:id, :u, 'M6TEST Barbell Bench Press', :eid, 'estimated_1rm',
                225, 5, 262.5, 'epley_v1', 'lb', CURRENT_DATE, :sid, NOW())
    """), {"id": pr_id, "u": alice, "eid": bench, "sid": sid})
    pg.commit()

    row = pg.execute(text("""
        SELECT exercise_library_id, pr_kind, formula_version, load_unit,
               withdrawn_at, workout_set_id
        FROM exercise_pr WHERE id = :id
    """), {"id": pr_id}).fetchone()
    assert row.exercise_library_id == bench
    assert row.pr_kind == "estimated_1rm"
    assert row.formula_version == "epley_v1"
    assert row.load_unit == "lb"
    assert row.withdrawn_at is None
    assert row.workout_set_id == sid

    pg.execute(text("""
        UPDATE exercise_pr
        SET withdrawn_at = NOW(), withdrawn_reason = 'source set voided'
        WHERE id = :id
    """), {"id": pr_id})
    pg.commit()
    withdrawn = pg.execute(text("""
        SELECT withdrawn_at, withdrawn_reason FROM exercise_pr WHERE id = :id
    """), {"id": pr_id}).fetchone()
    assert withdrawn.withdrawn_at is not None
    assert withdrawn.withdrawn_reason == "source set voided"


@requires_pg
def test_an_invalid_pr_kind_is_refused(pg, two_athletes):
    alice, _ = two_athletes
    with pytest.raises(IntegrityError):
        pg.execute(text("""
            INSERT INTO exercise_pr
                (id, user_id, exercise_name, pr_kind, weight, reps,
                 estimated_1rm, achieved_at, created_at)
            VALUES (:id, :u, 'M6TEST Lift', 'vibes_pr', 100, 5, 115,
                    CURRENT_DATE, NOW())
        """), {"id": str(uuid.uuid4()), "u": alice})
        pg.commit()
    pg.rollback()


@requires_pg
def test_legacy_pr_rows_with_only_a_text_name_still_read(pg, two_athletes):
    """Additive means the old shape keeps working."""
    alice, _ = two_athletes
    pr_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO exercise_pr
            (id, user_id, exercise_name, weight, reps, estimated_1rm,
             achieved_at, created_at)
        VALUES (:id, :u, 'M6TEST Legacy Named Lift', 200, 3, 220,
                CURRENT_DATE, NOW())
    """), {"id": pr_id, "u": alice})
    pg.commit()
    row = pg.execute(text("""
        SELECT exercise_name, exercise_library_id, pr_kind, withdrawn_at
        FROM exercise_pr WHERE id = :id
    """), {"id": pr_id}).fetchone()
    assert row.exercise_name == "M6TEST Legacy Named Lift"
    assert row.exercise_library_id is None
    assert row.pr_kind is None
    assert row.withdrawn_at is None


# ─────────────────────────────────────────────────────────────────────────
# Muscle roles
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_muscle_roles_are_typed_beside_the_untouched_legacy_json(pg, two_athletes):
    """Direct volume counts primaries; secondary involvement is separate.

    The existing `muscle_groups` JSON is left exactly as it is for the
    readers that already use it.
    """
    import json
    from app.services.fitness.exercises import get_exercise

    alice, _ = two_athletes
    eid = _exercise(pg, "M6TEST Barbell Bench Press",
                    primary=["chest"])
    pg.execute(text("""
        UPDATE exercise_library
        SET secondary_muscles = CAST(:sec AS jsonb),
            muscle_groups = CAST(:legacy AS json)
        WHERE id = :id
    """), {"sec": json.dumps(["front_delt", "triceps"]),
           "legacy": json.dumps(["chest", "shoulders", "triceps"]),
           "id": eid})
    pg.commit()

    ref = get_exercise(pg, alice, eid)
    assert ref.primary_muscles == ("chest",)
    assert ref.secondary_muscles == ("front_delt", "triceps")

    legacy = pg.execute(text(
        "SELECT muscle_groups FROM exercise_library WHERE id = :id"), {"id": eid}
    ).scalar()
    assert legacy == ["chest", "shoulders", "triceps"], (
        "the legacy JSON column must be untouched"
    )
