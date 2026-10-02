"""Step 25 of FITNESS_COACH_IMPLEMENTATION_PLAN end to end: the daily and
weekly loops, against a real database.

What this file proves that the unit tests cannot:

* **Duplicate producers and retries yield one candidate.** The dedup key is
  shared, and `say_candidate.create_candidate` refuses the second — so two
  sources that both notice a missing weigh-in produce one question.
* **A job completed but its notification suppressed is distinguishable from
  a job that failed.** Both are terminal; only one means something went
  wrong, and the ledger says which.
* **The requested artifact survives a suppressed push.** A stored review is
  readable in the Coach tab whatever the gates decided.
* **Nothing in the loop mutates a program or a target.** Asserted by
  counting rows before and after a whole cadence run.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_daily_loop_pg.py
"""
import asyncio
import json
import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
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
    alice = f"s25a-{uuid.uuid4().hex[:17]}"
    bob = f"s25b-{uuid.uuid4().hex[:17]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@s25.invalid", "p": unusable_hash})
        pg.execute(text("""
            INSERT INTO fitness_athlete_profile
                (id, user_id, timezone, created_at, updated_at)
            VALUES (:i, :u, 'America/New_York', NOW(), NOW())
            ON CONFLICT (user_id) DO NOTHING
        """), {"i": str(uuid.uuid4()), "u": uid})
    pg.commit()
    yield alice, bob
    pg.rollback()
    for table in ("say_candidate", "fitness_coaching_job_run",
                  "fitness_coaching_schedule", "fitness_coach_recommendation",
                  "fitness_coach_review", "fitness_target_revision",
                  "fitness_athlete_profile", "health_metric", "food_log",
                  "daily_recovery_log", "weight_trend", "fitness_phase",
                  "fitness_program", "fitness_goals", "world_event"):
        try:
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                       {"ids": [alice, bob]})
        except Exception:
            pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"),
               {"ids": [alice, bob]})
    pg.commit()


@pytest.fixture(autouse=True)
def flags_on(monkeypatch):
    """Both gates on: these tests are about the loop, and one test turns
    `FITNESS_COACH_PROACTIVE` back off to prove it gates."""
    from app.core import feature_flags
    monkeypatch.setattr(
        feature_flags, "is_enabled",
        lambda flag: feature_flags._flag_name(flag) in (
            "FITNESS_COACH_REVIEW", "FITNESS_COACH_PROACTIVE",
        ),
    )


@pytest.fixture(autouse=True)
def gates_open(monkeypatch):
    """Quiet mode off and no notification ban, unless a test says otherwise."""
    import app.services.quiet_mode as quiet_mode
    import app.services.unified_notification as notifications

    async def no_ban(**kwargs):
        return None

    monkeypatch.setattr(quiet_mode, "is_quiet", lambda: False)
    monkeypatch.setattr(notifications, "_check_notification_ban", no_ban)


def _weigh_in(pg, uid, day: date, kg: float):
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import ingest_observation
    ingest_observation(
        pg, uid, metric_type="weight", value=kg, unit=Unit.KG,
        recorded_at=datetime(day.year, day.month, day.day, 7, 0, tzinfo=ET),
        source="manual", timezone_name="America/New_York",
    )
    pg.commit()


def _enable(pg, uid, kind, **kwargs):
    from app.services.fitness.coaching_jobs import set_schedule
    schedule = set_schedule(
        pg, uid, kind, enabled=True, consented=True, **kwargs,
    )
    pg.commit()
    return schedule


def _claim(pg, schedule):
    from app.services.fitness.coaching_jobs import claim_occurrence
    due = datetime.now(UTC) - timedelta(minutes=5)
    pg.execute(text("""
        UPDATE fitness_coaching_schedule SET next_due_at = :due WHERE id = :id
    """), {"due": due, "id": schedule.id})
    pg.commit()
    schedule.next_due_at = due
    occurrence = claim_occurrence(pg, schedule)
    pg.commit()
    return occurrence


def _deliver(pg, uid):
    from app.services.fitness import proactive
    return asyncio.run(proactive.deliver_gap_question(pg, uid))


def _candidates(pg, uid):
    return pg.execute(text("""
        SELECT id, source, summary, topic_entities, status, valid_until
        FROM say_candidate WHERE user_id = :u ORDER BY created_at
    """), {"u": uid}).fetchall()


# ─────────────────────────────────────────────────────────────────────────
# One candidate, whatever produced it
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_missing_weigh_in_produces_one_candidate(pg, two_athletes):
    alice, _ = two_athletes
    _weigh_in(pg, alice, date.today() - timedelta(days=2), 81.0)

    outcome = _deliver(pg, alice)
    assert outcome.delivered is True, outcome.suppressed_reason
    rows = _candidates(pg, alice)
    assert len(rows) == 1
    assert rows[0].source == "fitness_coach"
    assert "weigh in" in rows[0].summary
    # The coverage travels with the question, so it reads as a reason rather
    # than as nagging.
    assert "three is the minimum" in rows[0].summary


@requires_pg
def test_two_producers_of_the_same_question_yield_one_candidate(pg, two_athletes):
    """The shared dedup key. A key with the source in it would let the
    morning brief and the check-in cadence each deliver their own copy —
    the nag-storm shape this subsystem keeps closing."""
    from app.db.session import get_async_session_factory
    from app.services.say_candidate import create_candidate

    alice, _ = two_athletes
    _weigh_in(pg, alice, date.today() - timedelta(days=2), 81.0)

    first = _deliver(pg, alice)
    assert first.delivered is True

    # A different source noticing the same gap, with the same key.
    async def other_producer():
        factory = get_async_session_factory()
        async with factory() as db:
            result = await create_candidate(
                db, alice, source="morning_brief", kind="inform",
                summary="Did you weigh in this morning?",
                dedupe_key=first.question.key,
            )
            await db.commit()
            return result

    assert asyncio.run(other_producer()) is None
    assert len(_candidates(pg, alice)) == 1


@requires_pg
def test_a_retry_of_the_same_occurrence_yields_one_candidate(pg, two_athletes):
    alice, _ = two_athletes
    _weigh_in(pg, alice, date.today() - timedelta(days=2), 81.0)

    first = _deliver(pg, alice)
    assert first.delivered is True
    # The worker retried. The cooldown catches it first; the dedup key would
    # catch it anyway.
    second = _deliver(pg, alice)
    assert second.delivered is False
    assert len(_candidates(pg, alice)) == 1


@requires_pg
def test_two_athletes_each_get_their_own_question(pg, two_athletes):
    alice, bob = two_athletes
    _weigh_in(pg, alice, date.today() - timedelta(days=2), 81.0)
    _weigh_in(pg, bob, date.today() - timedelta(days=2), 65.0)

    assert _deliver(pg, alice).delivered is True
    assert _deliver(pg, bob).delivered is True
    assert len(_candidates(pg, alice)) == 1
    assert len(_candidates(pg, bob)) == 1


@requires_pg
def test_a_second_fitness_question_the_same_morning_is_suppressed(pg, two_athletes):
    """Two different metrics are the same notification category, so the
    per-category cooldown passes both and David gets two fitness questions
    in one morning."""
    alice, _ = two_athletes
    _weigh_in(pg, alice, date.today() - timedelta(days=2), 81.0)

    assert _deliver(pg, alice).delivered is True
    # Now he weighs in, so the next gap is nutrition — a different metric
    # and therefore a different dedup key.
    for offset in (1, 2, 3):
        _weigh_in(pg, alice, date.today() - timedelta(days=offset), 81.0)

    second = _deliver(pg, alice)
    assert second.delivered is False
    assert second.suppressed_reason.startswith("asked_recently:")
    assert len(_candidates(pg, alice)) == 1


@requires_pg
def test_a_candidate_expires_rather_than_accumulating(pg, two_athletes):
    """Tomorrow's question is a new occurrence. A stale one surviving is the
    harping shape."""
    alice, _ = two_athletes
    _weigh_in(pg, alice, date.today() - timedelta(days=2), 81.0)
    _deliver(pg, alice)

    row = _candidates(pg, alice)[0]
    assert row.valid_until is not None
    assert row.valid_until <= datetime.now(row.valid_until.tzinfo) + timedelta(days=1)


# ─────────────────────────────────────────────────────────────────────────
# Suppression is recorded, and distinguishable from failure
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_quiet_mode_records_a_noop_not_a_failure(pg, two_athletes, monkeypatch):
    """Both are terminal; only one means something went wrong, and the
    ledger says which."""
    import app.services.quiet_mode as quiet_mode

    alice, _ = two_athletes
    _weigh_in(pg, alice, date.today() - timedelta(days=2), 81.0)
    schedule = _enable(pg, alice, "daily_checkin")
    occurrence = _claim(pg, schedule)

    monkeypatch.setattr(quiet_mode, "is_quiet", lambda: True)
    from app.tasks.fitness_coach import run_daily_checkin
    result = run_daily_checkin.run(user_id=alice, run_id=occurrence.run_id)

    assert result["status"] == "noop"
    row = pg.execute(text("""
        SELECT status, noop_reason, error_category
        FROM fitness_coaching_job_run WHERE id = :id
    """), {"id": occurrence.run_id}).fetchone()
    assert row.status == "noop"
    assert row.noop_reason == "quiet_mode"
    assert row.error_category is None, "a suppression is not an error"
    assert _candidates(pg, alice) == []


@requires_pg
def test_a_complete_week_records_nothing_missing(pg, two_athletes):
    """Distinct from a suppression: there was nothing to say, which is not
    the same as having been silenced."""
    alice, _ = two_athletes
    today = date.today()
    for offset in range(1, 8):
        _weigh_in(pg, alice, today - timedelta(days=offset), 81.0)
        pg.execute(text("""
            INSERT INTO food_log
                (id, user_id, meal_type, food_items, calories, protein,
                 logged_at, created_at, updated_at)
            VALUES (:id, :u, 'dinner', CAST(:fi AS jsonb), 3000, 200,
                    :logged, NOW(), NOW())
        """), {
            "id": str(uuid.uuid4()), "u": alice,
            "fi": json.dumps([{"name": "x", "quantity": 1, "unit": "serving"}]),
            "logged": datetime.combine(
                today - timedelta(days=offset), time(18, 0),
            ),
        })
        pg.execute(text("""
            INSERT INTO daily_recovery_log
                (id, user_id, log_date, nutrition_status,
                 nutrition_completed_at, sleep_hours, created_at, updated_at)
            VALUES (:i, :u, :d, 'complete', NOW(), 7.5, NOW(), NOW())
            ON CONFLICT (user_id, log_date) DO UPDATE
            SET nutrition_status = 'complete', sleep_hours = 7.5
        """), {"i": str(uuid.uuid4()), "u": alice,
               "d": today - timedelta(days=offset)})
    pg.commit()

    schedule = _enable(pg, alice, "daily_checkin")
    occurrence = _claim(pg, schedule)
    from app.tasks.fitness_coach import run_daily_checkin
    result = run_daily_checkin.run(user_id=alice, run_id=occurrence.run_id)

    assert result["status"] == "noop", result
    reason = pg.execute(text("""
        SELECT noop_reason FROM fitness_coaching_job_run WHERE id = :id
    """), {"id": occurrence.run_id}).scalar()
    assert reason == "nothing_missing"


@requires_pg
def test_the_proactive_flag_gates_the_loop(pg, two_athletes, monkeypatch):
    """"Stop bringing this up on your own" must not also mean "refuse when
    asked", so the proactive flag is separate from the review flag."""
    from app.core import feature_flags

    alice, _ = two_athletes
    _weigh_in(pg, alice, date.today() - timedelta(days=2), 81.0)
    schedule = _enable(pg, alice, "daily_checkin")
    occurrence = _claim(pg, schedule)

    monkeypatch.setattr(
        feature_flags, "is_enabled",
        lambda flag: feature_flags._flag_name(flag) == "FITNESS_COACH_REVIEW",
    )
    from app.tasks.fitness_coach import run_daily_checkin
    result = run_daily_checkin.run(user_id=alice, run_id=occurrence.run_id)

    assert result["reason"] == "proactive_disabled"
    assert _candidates(pg, alice) == []
    # And an on-demand review still works, because that flag is still on.
    from app.core.feature_flags import Flag, is_enabled
    assert is_enabled(Flag.FITNESS_COACH_REVIEW) is True


@requires_pg
def test_a_delivered_question_completes_the_run_with_its_candidate(
    pg, two_athletes,
):
    alice, _ = two_athletes
    _weigh_in(pg, alice, date.today() - timedelta(days=2), 81.0)
    schedule = _enable(pg, alice, "daily_checkin")
    occurrence = _claim(pg, schedule)

    from app.tasks.fitness_coach import run_daily_checkin
    result = run_daily_checkin.run(user_id=alice, run_id=occurrence.run_id)

    assert result["status"] == "completed"
    assert result["asked_about"] == "weight"
    assert result["deep_link"] == "/fitness/today?ask=weight"
    row = pg.execute(text("""
        SELECT status, candidate_id FROM fitness_coaching_job_run
        WHERE id = :id
    """), {"id": occurrence.run_id}).fetchone()
    assert row.status == "completed"
    assert row.candidate_id


@requires_pg
def test_a_preference_switched_off_after_the_claim_delivers_nothing(
    pg, two_athletes,
):
    """An occurrence claimed at 06:58 must not ask at 07:00 if the cadence
    was switched off at 06:59."""
    from app.services.fitness.coaching_jobs import set_schedule

    alice, _ = two_athletes
    _weigh_in(pg, alice, date.today() - timedelta(days=2), 81.0)
    schedule = _enable(pg, alice, "daily_checkin")
    occurrence = _claim(pg, schedule)

    set_schedule(pg, alice, "daily_checkin", enabled=False)
    pg.commit()

    from app.tasks.fitness_coach import run_daily_checkin
    result = run_daily_checkin.run(user_id=alice, run_id=occurrence.run_id)
    assert result["status"] == "noop"
    assert _candidates(pg, alice) == []
    reason = pg.execute(text("""
        SELECT noop_reason FROM fitness_coaching_job_run WHERE id = :id
    """), {"id": occurrence.run_id}).scalar()
    assert reason == "cadence_disabled_since_claim"


# ─────────────────────────────────────────────────────────────────────────
# The artifact survives a suppressed push
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_review_stays_readable_when_its_notice_is_suppressed(
    pg, two_athletes, monkeypatch,
):
    """Suppressing a notification is not suppressing the work. Conflating
    them is how a push preference silently becomes a "do not coach me"
    setting."""
    import app.services.quiet_mode as quiet_mode

    from app.schemas.fitness_coach import ReviewKind
    from app.services.fitness import proactive, review_audit

    alice, _ = two_athletes
    today = date.today()
    for offset in range(1, 16):
        _weigh_in(pg, alice, today - timedelta(days=offset), 81.0 + offset * 0.05)

    from app.services.fitness import reviews as review_service
    review = review_service.request_review(pg, alice, kind=ReviewKind.WEEKLY)
    review_audit.mark_running(pg, alice, review.id, model_actual="qwen3.8-27b")
    from tests.test_fitness_reviews_pg import _model_output  # reuse the fixture
    from app.schemas.fitness_coach import CoachReviewOutputV1
    output = CoachReviewOutputV1.model_validate(_model_output())
    review_audit.mark_complete(pg, alice, review.id, output=output)
    pg.commit()

    monkeypatch.setattr(quiet_mode, "is_quiet", lambda: True)
    detail = review_audit.get_review(pg, alice, review.id)
    notice = asyncio.run(
        proactive.deliver_review_notice(pg, alice, detail)
    )
    assert notice.delivered is False
    assert notice.suppressed_reason == "quiet_mode"
    assert _candidates(pg, alice) == []

    # And the review is still there, complete, with its output.
    reread = review_audit.get_review(pg, alice, review.id)
    assert reread.status.value == "complete"
    assert reread.output is not None
    assert reread.summary


@requires_pg
def test_a_review_notice_is_delivered_when_the_gates_are_open(pg, two_athletes):
    from app.schemas.fitness_coach import CoachReviewOutputV1, ReviewKind
    from app.services.fitness import proactive, review_audit
    from app.services.fitness import reviews as review_service
    from tests.test_fitness_reviews_pg import _model_output

    alice, _ = two_athletes
    today = date.today()
    for offset in range(1, 16):
        _weigh_in(pg, alice, today - timedelta(days=offset), 81.0)

    review = review_service.request_review(pg, alice, kind=ReviewKind.WEEKLY)
    review_audit.mark_running(pg, alice, review.id)
    review_audit.mark_complete(
        pg, alice, review.id,
        output=CoachReviewOutputV1.model_validate(_model_output()),
    )
    pg.commit()

    detail = review_audit.get_review(pg, alice, review.id)
    notice = asyncio.run(proactive.deliver_review_notice(pg, alice, detail))
    assert notice.delivered is True
    rows = _candidates(pg, alice)
    assert len(rows) == 1
    assert "review" in rows[0].summary.lower()


# ─────────────────────────────────────────────────────────────────────────
# The loop changes nothing
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_whole_cadence_run_mutates_no_plan_or_target(pg, two_athletes):
    """The completion criterion, asserted by counting."""
    alice, _ = two_athletes
    _weigh_in(pg, alice, date.today() - timedelta(days=2), 81.0)

    def counts():
        return {
            table: pg.execute(text(
                f"SELECT COUNT(*) FROM {table} WHERE user_id = :u"
            ), {"u": alice}).scalar()
            for table in ("fitness_target_revision", "fitness_phase",
                          "fitness_program", "fitness_goals", "workout_log",
                          "health_metric")
        }

    before = counts()
    schedule = _enable(pg, alice, "daily_checkin")
    occurrence = _claim(pg, schedule)
    from app.tasks.fitness_coach import run_daily_checkin
    run_daily_checkin.run(user_id=alice, run_id=occurrence.run_id)

    assert counts() == before, "the daily loop mutated a plan or a record"


@requires_pg
def test_one_athlete_cannot_run_anothers_occurrence(pg, two_athletes):
    alice, bob = two_athletes
    _weigh_in(pg, alice, date.today() - timedelta(days=2), 81.0)
    schedule = _enable(pg, alice, "daily_checkin")
    occurrence = _claim(pg, schedule)

    from app.tasks.fitness_coach import run_daily_checkin
    with pytest.raises(LookupError):
        run_daily_checkin.run(user_id=bob, run_id=occurrence.run_id)
    assert _candidates(pg, bob) == []


@requires_pg
def test_the_task_refuses_a_missing_owner(pg, two_athletes):
    from app.tasks.fitness_coach import run_daily_checkin

    for bad in ("", "   "):
        with pytest.raises(ValueError):
            run_daily_checkin.run(user_id=bad, run_id="whatever")
