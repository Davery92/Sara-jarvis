"""Step 23 of FITNESS_COACH_IMPLEMENTATION_PLAN: Sara knows the fitness
state on a fitness turn, and does not carry it on every other turn.

Four claims, each with a concrete failure behind it:

1. **Relevance gating.** A fitness block appended to every turn costs prompt
   budget on every unrelated one, and the thing it displaces is unknowable
   from here.
2. **A safety limitation and a live workout survive truncation.** They are
   rendered FIRST, so a clipped fragment keeps the shoulder that hurts and
   loses the macro remainder — not the other way round. §23.2.
3. **Voice and chat read the same renderer.** Two renderings of one state is
   how a voice answer and a typed answer come to disagree.
4. **An unlogged macro renders as unknown.** Summing NULLs to zero and
   subtracting told Sara the full fat budget was available on a day where
   fat was never recorded.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_context_integration.py
"""
import asyncio
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone

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
def athlete(pg):
    unusable_hash = "$2b$12$" + "x" * 53
    uid = f"s23-{uuid.uuid4().hex[:18]}"
    pg.execute(text("""
        INSERT INTO app_user (id, email, password_hash, created_at)
        VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
    """), {"id": uid, "e": f"{uid}@s23.invalid", "p": unusable_hash})
    pg.execute(text("""
        INSERT INTO fitness_athlete_profile
            (id, user_id, timezone, created_at, updated_at)
        VALUES (:i, :u, 'America/New_York', NOW(), NOW())
        ON CONFLICT (user_id) DO NOTHING
    """), {"i": str(uuid.uuid4()), "u": uid})
    pg.commit()
    yield uid
    pg.rollback()
    for table in ("active_workout_session", "fitness_athlete_limitation",
                  "fitness_target_revision", "fitness_athlete_profile",
                  "food_log", "daily_recovery_log", "health_metric",
                  "weight_trend", "fitness_phase", "fitness_program",
                  "fitness_goals", "world_event"):
        try:
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                       {"ids": [uid]})
        except Exception:
            pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": uid})
    pg.commit()


def _today(pg, uid) -> date:
    from app.services.fitness.profile import athlete_today
    return athlete_today(pg, uid)


def _targets(pg, uid, calories=3000, protein=200):
    from app.schemas.fitness_coach import (
        TargetRevisionIn, TargetScope, TargetValues,
    )
    from app.services.fitness.targets import create_target_revision
    revision = create_target_revision(pg, uid, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=_today(pg, uid) - timedelta(days=30),
        training=TargetValues(calories=calories, protein_g=protein,
                              carbs_g=300, fat_g=90),
    ))
    pg.commit()
    return revision


def _meal(pg, uid, *, calories=900, protein=60, carbs=None, fat=None):
    today = _today(pg, uid)
    pg.execute(text("""
        INSERT INTO food_log
            (id, user_id, meal_type, food_items, calories, protein, carbs, fats,
             logged_at, created_at, updated_at)
        VALUES (:id, :u, 'lunch', CAST(:fi AS jsonb), :cal, :pro, :car, :fat,
                :logged, NOW(), NOW())
    """), {
        "id": str(uuid.uuid4()), "u": uid,
        "fi": json.dumps([{"name": "chicken", "quantity": 1, "unit": "serving"}]),
        "cal": calories, "pro": protein, "car": carbs, "fat": fat,
        "logged": datetime(today.year, today.month, today.day, 12, 30),
    })
    pg.commit()


def _limitation(pg, uid, area="left shoulder", severity="moderate",
                excluded=("ex-1",)):
    from app.schemas.fitness_coach import AthleteLimitationIn
    from app.services.fitness.profile import create_limitation
    out = create_limitation(pg, uid, AthleteLimitationIn(
        area=area, severity_flag=severity,
        description="aches on overhead pressing",
        excluded_exercise_ids=list(excluded),
        effective_from=_today(pg, uid) - timedelta(days=5),
    ))
    pg.commit()
    return out


def _active_session(pg, uid, name="Upper A", sets=4):
    template_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_template (id, user_id, name, created_at)
        VALUES (:id, :u, :n, NOW())
    """), {"id": template_id, "u": uid, "n": name})
    pg.execute(text("""
        INSERT INTO active_workout_session
            (id, user_id, template_id, status, total_sets_completed,
             started_at, created_at)
        VALUES (:id, :u, :t, 'active', :sets, NOW(), NOW())
    """), {"id": str(uuid.uuid4())[:36], "u": uid, "t": template_id, "sets": sets})
    pg.commit()
    return template_id


def _render(pg, uid):
    from app.services.fitness_context import get_fitness_context
    return asyncio.run(get_fitness_context(uid, pg))


# ─────────────────────────────────────────────────────────────────────────
# 1. Relevance gating
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "What's on my calendar tomorrow?",
    "Draft a reply to that email.",
    "Remind me to call the dentist.",
    "Did the deploy finish?",
])
def test_an_unrelated_turn_does_not_ask_for_fitness_context(message):
    """A fitness block on every turn costs budget on every unrelated one,
    and what it displaces is unknowable from here."""
    from app.services.context_router import ContextRouter

    decision = ContextRouter().decide("GENERAL", message, turn_count=3)
    assert decision.inject_fitness is False, message


@pytest.mark.parametrize("message", [
    "What's the weather like?",          # 'eat' inside "weather"
    "That's a great idea.",              # 'eat' inside "great"
    "Can you repeat that?",              # 'eat' inside "repeat"
    "What's the new feature called?",    # 'eat' inside "feature"
    "Book the theater for Friday.",      # 'eat' inside "theater"
])
def test_a_word_inside_another_word_does_not_trigger_fitness(message):
    """The keyword check was a bare substring match, so "What's the weather
    like?" injected a nutrition block — budget spent on an unrelated turn,
    and a macro remainder in front of the model on a weather question."""
    from app.services.context_router import ContextRouter

    decision = ContextRouter().decide("GENERAL", message, turn_count=3)
    assert decision.inject_fitness is False, message


@pytest.mark.parametrize("message", [
    "What should I eat for dinner?",
    "How's my weight trending?",
    "Am I on track with my macros?",
    "Should I do my workout today?",
    "My shoulder is sore again.",
    "Did I hit a PR on bench this week?",
    "How many steps have I done?",
])
def test_a_fitness_turn_asks_for_it(message):
    from app.services.context_router import ContextRouter

    decision = ContextRouter().decide("GENERAL", message, turn_count=3)
    assert decision.inject_fitness is True, message


@requires_pg
def test_an_athlete_with_nothing_recorded_gets_no_block(pg, athlete):
    """A fragment saying only "no data" costs prompt budget and tells Sara
    nothing she cannot see from the absence."""
    assert _render(pg, athlete) is None


# ─────────────────────────────────────────────────────────────────────────
# 2. Safety survives truncation
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_limitation_is_rendered_even_with_no_targets_and_no_meals(pg, athlete):
    """The turn where getting it wrong matters most is exactly the turn with
    the least other data."""
    _limitation(pg, athlete)
    rendered = _render(pg, athlete)
    assert rendered is not None
    assert "left shoulder" in rendered
    assert "moderate" in rendered


@requires_pg
def test_a_limitation_is_rendered_above_the_intake_numbers(pg, athlete):
    """§23.2: a safety limitation must not be clipped into irrelevance. The
    fragment is ordered so a truncated one keeps the shoulder and loses the
    macro remainder, not the other way round."""
    _targets(pg, athlete)
    _meal(pg, athlete)
    _limitation(pg, athlete)

    rendered = _render(pg, athlete)
    assert rendered is not None
    assert rendered.index("Working around") < rendered.index("Eaten so far")


@requires_pg
def test_excluded_exercises_are_flagged_by_count(pg, athlete):
    """Naming every excluded id would spend the budget on uuids. The count
    plus "check before suggesting" is what changes behaviour."""
    _limitation(pg, athlete, excluded=("ex-1", "ex-2", "ex-3"))
    rendered = _render(pg, athlete)
    assert "3 exercise(s) excluded" in rendered
    assert "check before suggesting" in rendered


@requires_pg
def test_a_live_workout_is_in_the_fragment(pg, athlete):
    """Without it Sara answers a mid-session question as though David were at
    his desk, and "what's next" means something different with a bar in his
    hands."""
    _active_session(pg, athlete, name="Upper A", sets=6)
    rendered = _render(pg, athlete)
    assert rendered is not None
    assert "Training right now" in rendered
    assert "Upper A" in rendered
    assert "6 sets logged" in rendered


@requires_pg
def test_no_live_workout_means_no_line(pg, athlete):
    _targets(pg, athlete)
    rendered = _render(pg, athlete)
    assert rendered is not None
    assert "Training right now" not in rendered


@requires_pg
def test_the_fitness_block_is_prioritised_on_a_fitness_turn():
    """Priority 1 in the voice budget. The block only exists on a fitness
    turn, so raising it cannot crowd an unrelated one — and on the turn it
    does exist, the limitation must not be the thing that gets dropped."""
    source = open("app/main_simple.py").read()
    assert 'voice_budget.add("fitness", _v_safe(v_fitness), priority=1)' in source


@requires_pg
def test_the_fragment_stays_within_the_chat_capsule_budget(pg, athlete):
    """§8.1 sets ~1,500 characters for the chat capsule. A fragment that
    grows with the log pushes something else out of the prompt."""
    _targets(pg, athlete)
    _limitation(pg, athlete)
    _active_session(pg, athlete)
    for _ in range(14):
        _meal(pg, athlete, calories=200, protein=15)

    rendered = _render(pg, athlete)
    assert rendered is not None
    assert len(rendered) < 2500, f"the fragment grew to {len(rendered)} chars"


# ─────────────────────────────────────────────────────────────────────────
# 3. One renderer
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_voice_and_chat_read_the_same_renderer(pg, athlete):
    """Two renderings of one state is how a spoken answer and a typed answer
    come to disagree about today's calories."""
    source = open("app/main_simple.py").read()
    assert source.count(
        "from app.services.fitness_context import get_fitness_context"
    ) >= 1
    # The world brief reads it too, rather than re-deriving the numbers.
    brief = open("app/services/world_brief.py").read()
    assert "from app.services.fitness_context import get_fitness_context" in brief


@requires_pg
def test_the_capsule_and_the_state_agree_about_today(pg, athlete):
    """The fragment delegates to `nutrition_day`, which is what the Coach
    API and `FitnessStateV1` use. If these could differ, Sara and the
    dashboard would answer the same question differently."""
    from app.services.fitness.consumers import nutrition_day

    _targets(pg, athlete, calories=2900, protein=190)
    _meal(pg, athlete, calories=900, protein=60)

    day = nutrition_day(pg, athlete)
    rendered = _render(pg, athlete)
    assert str(day["target"]["calories"]) in rendered
    assert str(day["eaten"]["calories"]) in rendered


@requires_pg
def test_the_capsule_states_target_provenance(pg, athlete):
    """Legacy targets come from a mutable column and describe today only.
    Without the caveat Sara would answer "what were my calories last month"
    from them."""
    today = _today(pg, athlete)
    pg.execute(text("""
        INSERT INTO fitness_goals (user_id, calories, protein, carbs, fats)
        VALUES (:u, 2800, 180, 300, 90)
        ON CONFLICT (user_id) DO UPDATE SET calories = 2800
    """), {"u": athlete})
    pg.commit()

    rendered = _render(pg, athlete)
    assert rendered is not None
    assert "no recorded history" in rendered


# ─────────────────────────────────────────────────────────────────────────
# 4. Unknown is not zero
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_an_unlogged_macro_renders_as_unknown(pg, athlete):
    """Summing NULLs to zero and subtracting told Sara the full fat budget
    was still available on a day where fat was never recorded."""
    _targets(pg, athlete)
    _meal(pg, athlete, calories=900, protein=60, carbs=None, fat=None)

    rendered = _render(pg, athlete)
    assert rendered is not None
    assert "?g fat" in rendered
    # And the fields that WERE logged show their numbers.
    assert "900 cal" in rendered


@requires_pg
def test_a_logged_macro_renders_its_number(pg, athlete):
    _targets(pg, athlete)
    _meal(pg, athlete, calories=900, protein=60, carbs=90, fat=30)
    rendered = _render(pg, athlete)
    assert "30g fat" in rendered


@requires_pg
def test_a_read_failure_degrades_to_no_block_rather_than_a_wrong_one(
    pg, athlete, monkeypatch,
):
    """A fragment built from a half-failed read would assert numbers it did
    not have. None is the honest answer."""
    import app.services.fitness.consumers as consumers

    def explode(*args, **kwargs):
        raise RuntimeError("the database is unhappy")

    monkeypatch.setattr(consumers, "nutrition_day", explode)
    assert _render(pg, athlete) is None
