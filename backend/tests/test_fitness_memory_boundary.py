"""Step 23 of FITNESS_COACH_IMPLEMENTATION_PLAN §8.4: structured records and
preference memory do not compete.

The incident this whole boundary exists because of (2026-08-31): the nightly
extractor read Sara's OWN reply out of a transcript, minted
`PKG_Health {metric: "hrv", current_value: "80"}` at confidence 0.99, and
re-injected it into the next turn's context — where it looked exactly like
evidence. 80 was a number Sara had invented; the authoritative table said 54.

Step 23 extends that refusal to TARGETS. The old exemption let "daily calorie
target: 2760" through on the grounds that a chosen number had nowhere else to
live. `fitness_target_revision` and `fitness_athlete_goal` now own them,
dated and revisioned, so a graph copy is a second authority that never
expires and cannot be reconciled against the first.

What must NOT be lost: a qualitative preference. "dislikes lunges", "wants
upper-body thickness", "prefers short sessions" have no numeric home and are
exactly the rationale a structured goal is supposed to preserve. And the
conversations themselves stay — this is about canonical arithmetic, not about
erasing history.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_memory_boundary.py
"""
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.personal_knowledge_graph import (
    OWNED_TARGET_METRICS,
    is_authoritative_health_copy,
    is_intention_metric,
    is_measured_health_metric,
    is_numeric_health_value,
    is_owned_target_metric,
)

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
)


# ─────────────────────────────────────────────────────────────────────────
# Measurements stay refused
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("metric,value", [
    ("hrv", "80"),
    ("resting heart rate", 54),
    ("weight", "225 lbs"),
    ("body fat", "14%"),
    ("sleep hours", "7.5"),
    ("steps", "12,431"),
])
def test_a_measurement_copy_is_still_refused(metric, value):
    """`health_metric` is the authority. A graph copy has no `recorded_at`,
    never expires, and reads as evidence."""
    assert is_authoritative_health_copy(metric, value) is True


def test_a_qualitative_health_attribute_is_still_allowed():
    """"chest historically underdeveloped" is a durable attribute with no
    other home, and refusing it would make the graph useless for the thing
    it is for."""
    assert is_authoritative_health_copy(
        "chest", "historically underdeveloped",
    ) is False
    assert is_authoritative_health_copy(
        "red wine", "gives him migraines",
    ) is False
    assert is_authoritative_health_copy(
        "sleep", "apnea diagnosed years ago",
    ) is False


# ─────────────────────────────────────────────────────────────────────────
# Targets are refused NOW TOO
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("metric,value", [
    ("daily calorie target", "2760"),
    ("calorie target", 2900),
    ("protein target", "200g"),
    ("goal weight", "225 lbs"),
    ("target weight", 102),
    ("sleep target", "8 hours"),
    ("step target", "10,000"),
    ("weekly protein target", "210"),
    ("target rate", "-0.4"),
])
def test_a_numeric_target_copy_is_refused(metric, value):
    """§23.5. These have a dated home now, so a graph copy is a second
    authority that never expires — the 2026-08-31 shape, one table over."""
    assert is_owned_target_metric(metric) is True
    assert is_authoritative_health_copy(metric, value) is True


def test_a_qualitative_goal_is_kept_as_rationale():
    """§8.4: "goals such as thickness become structured once they drive
    programming, preserving the original phrase as rationale." The phrase has
    no numeric home and is the thing a structured goal cites."""
    for metric, value in (
        ("goal", "upper-body thickness"),
        ("training goal", "look like he lifts, not like he runs"),
        ("aim", "get back under the bar without the shoulder complaining"),
        ("goal", "feel strong in the mornings"),
    ):
        assert is_authoritative_health_copy(metric, value) is False, (metric, value)


def test_a_preference_is_never_refused():
    """These are the memory's job. A system that could not remember "dislikes
    lunges" would propose them forever."""
    for metric, value in (
        ("lunges", "dislikes them"),
        ("deadlifts", "enjoys going heavy"),
        ("session length", "prefers short sessions"),
        ("whey", "dislikes it in water"),
        ("training time", "prefers mornings before work"),
    ):
        assert is_authoritative_health_copy(metric, value) is False, metric


def test_the_owned_target_list_names_what_it_owns():
    """Enumerated, not inferred from a token. A token rule would catch
    "goal: upper-body thickness" too, and that one must survive."""
    assert "daily calorie target" in OWNED_TARGET_METRICS
    assert "goal weight" in OWNED_TARGET_METRICS
    assert "protein target" in OWNED_TARGET_METRICS
    # And not a bare "goal", which is where the qualitative ones live.
    assert "goal" not in OWNED_TARGET_METRICS


def test_the_intention_exemption_still_exists_for_everything_else():
    """The exemption was not deleted — only narrowed. A chosen number with no
    owning table is still better in the graph than nowhere."""
    assert is_intention_metric("reading goal") is True
    assert is_authoritative_health_copy("reading goal", "30 books") is False


# ─────────────────────────────────────────────────────────────────────────
# The read path is gated too
# ─────────────────────────────────────────────────────────────────────────

def test_the_context_provider_filters_the_same_way():
    """Minting is one path; a node already in the graph from before the rule
    is another. The read filter is what makes an old copy stop being
    injected."""
    import app.services.pkg_context_provider as provider

    source = open(provider.__file__).read()
    assert "is_authoritative_health_copy" in source


def test_both_mint_sites_apply_the_filter():
    """A second mint path that skipped the check would reintroduce the whole
    failure quietly."""
    import app.services.personal_knowledge_graph as pkg

    source = open(pkg.__file__).read()
    assert source.count("is_authoritative_health_copy(metric, value)") >= 2


# ─────────────────────────────────────────────────────────────────────────
# Structured records win; conversations survive
# ─────────────────────────────────────────────────────────────────────────

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
def athlete(pg):
    unusable_hash = "$2b$12$" + "x" * 53
    uid = f"s23m-{uuid.uuid4().hex[:17]}"
    pg.execute(text("""
        INSERT INTO app_user (id, email, password_hash, created_at)
        VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
    """), {"id": uid, "e": f"{uid}@s23m.invalid", "p": unusable_hash})
    pg.execute(text("""
        INSERT INTO fitness_athlete_profile
            (id, user_id, timezone, created_at, updated_at)
        VALUES (:i, :u, 'America/New_York', NOW(), NOW())
        ON CONFLICT (user_id) DO NOTHING
    """), {"i": str(uuid.uuid4()), "u": uid})
    pg.commit()
    yield uid
    pg.rollback()
    for table in ("fitness_target_revision", "fitness_athlete_profile",
                  "health_metric", "weight_trend", "fitness_goals",
                  "world_event"):
        try:
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                       {"ids": [uid]})
        except Exception:
            pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": uid})
    pg.commit()


@requires_pg
def test_the_resolver_is_the_authority_for_a_target_a_memory_disagrees_with(
    pg, athlete,
):
    """A remembered number is whatever was said in some conversation. The
    dated revision is what the athlete is actually eating against, and the
    tool Sara uses reads the revision."""
    from app.schemas.fitness_coach import (
        TargetRevisionIn, TargetScope, TargetValues,
    )
    from app.services.fitness.targets import create_target_revision, resolve_targets

    today = date(2026, 9, 28)
    create_target_revision(pg, athlete, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=date(2026, 9, 1),
        training=TargetValues(calories=2900, protein_g=200),
    ))
    pg.commit()

    # A memory from an older conversation says 2760. It is not consulted.
    resolved = resolve_targets(pg, athlete, today)
    assert resolved.values.calories == 2900
    assert resolved.provenance.value == "approved_revision"


@requires_pg
def test_the_observation_store_is_the_authority_for_a_weight(pg, athlete):
    """A conversation three weeks ago is not a measurement today."""
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import ingest_observation, latest_metric

    ingest_observation(
        pg, athlete, metric_type="weight", value=81.0, unit=Unit.KG,
        recorded_at=datetime(2026, 9, 27, 7, 0, tzinfo=timezone.utc),
        source="manual", timezone_name="America/New_York",
    )
    pg.commit()

    latest = latest_metric(pg, athlete, "weight")
    assert latest is not None
    assert latest.value is not None


@requires_pg
def test_a_structured_goal_can_carry_the_original_phrase(pg, athlete):
    """§8.4: the structured goal preserves the phrase as rationale, so
    promoting a conversational goal does not destroy how it was said."""
    from app.schemas.fitness_coach import AthleteGoalIn, GoalKind, RateBasis
    from app.services.fitness.profile import create_goal, get_goals

    create_goal(pg, athlete, AthleteGoalIn(
        kind=GoalKind.HYPERTROPHY, rate_basis=RateBasis.NONE,
        rationale="wants upper-body thickness — his words, from 2026-09-14",
        valid_from=date(2026, 9, 14),
    ))
    pg.commit()

    goals = get_goals(pg, athlete, date(2026, 9, 28))
    assert goals
    assert "upper-body thickness" in goals[0].rationale
    assert "his words" in goals[0].rationale


@requires_pg
def test_closing_a_goal_keeps_the_old_one(pg, athlete):
    """"What was I training for in March" has to stay answerable, including
    for a review from March whose rationale cites it."""
    from app.schemas.fitness_coach import AthleteGoalIn, GoalKind, RateBasis
    from app.services.fitness.profile import close_goal, create_goal, get_goals

    first = create_goal(pg, athlete, AthleteGoalIn(
        kind=GoalKind.CUT, rate_basis=RateBasis.ABSOLUTE,
        target_rate_kg_week=-0.4, valid_from=date(2026, 3, 1),
    ))
    close_goal(pg, athlete, first.id, date(2026, 6, 1))
    create_goal(pg, athlete, AthleteGoalIn(
        kind=GoalKind.HYPERTROPHY, rate_basis=RateBasis.NONE,
        valid_from=date(2026, 6, 1),
    ))
    pg.commit()

    march = get_goals(pg, athlete, date(2026, 3, 15))
    assert march and march[0].kind is GoalKind.CUT
    september = get_goals(pg, athlete, date(2026, 9, 1))
    assert september and september[0].kind is GoalKind.HYPERTROPHY


# ─────────────────────────────────────────────────────────────────────────
# The skill tells Sara which side is which
# ─────────────────────────────────────────────────────────────────────────

def test_the_skill_sends_numbers_to_tools_and_not_to_memory():
    """The old skill said to use `search_memory` to find workout logs. A
    remembered number loses to the dated record every time, and asking
    memory for it is how the two came to compete."""
    skill = " ".join(open("skills/fitness-coaching/SKILL.md").read().split())
    assert "Do **not** use `search_memory`" in skill
    assert "fitness_analytics_get" in skill
    assert "Memory holds conversations; the tools hold the records." in skill


def test_the_skill_drops_the_blanket_check_in_question():
    """"How'd you sleep?" every single time, when the sleep is in the data,
    is the shape of nagging David has been explicit about."""
    skill = " ".join(open("skills/fitness-coaching/SKILL.md").read().split())
    assert "not every time" in skill
    assert "already know" in skill
    assert "Don't ask a question the data already answers." in skill


def test_the_skill_drops_the_beginner_and_owner_assumptions():
    skill = " ".join(open("skills/fitness-coaching/SKILL.md").read().split())
    assert "No assumed level, no assumed owner" in skill
    assert "do not assume the athlete is David" in skill


def test_the_skill_forbids_naming_a_condition_and_citing_research():
    # Whitespace-normalised: the markdown wraps, so an assertion against the
    # raw text would be testing the line width.
    skill = " ".join(open("skills/fitness-coaching/SKILL.md").read().split())
    assert "Never name a condition" in skill
    assert "any study, author or year you produce is invented" in skill
    assert "an invented citation reads exactly like a real one" in skill


def test_the_skill_says_coverage_travels_with_every_number():
    skill = " ".join(open("skills/fitness-coaching/SKILL.md").read().split())
    assert "Read the coverage, and say it" in skill
    assert "does not mean nothing changed" in skill


def test_the_skill_is_one_persona_not_a_second_one():
    """§23.3: one Sara with domain guidance. A separate fitness persona is
    how the voice, the memory and the boundaries come to differ by subject."""
    skill = " ".join(open("skills/fitness-coaching/SKILL.md").read().split())
    assert "the same\nSara as everywhere else" in skill or \
        "same Sara as everywhere else" in skill.replace("\n", " ")
    assert "not a separate fitness persona" in skill.replace("\n", " ")
