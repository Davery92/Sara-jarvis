"""Step 30 of FITNESS_COACH_IMPLEMENTATION_PLAN: approved automation.

This is where the coach may change something without asking at the time,
and the failure mode is not a crash. It is a calorie target that drifted
400 kcal over a month through fourteen individually reasonable steps, and
an athlete who cannot say when they agreed to that.

So the claims here are all about the narrowness of the permission:

* **Nothing is automated by default**, and no approval implies another.
  §30.2 says it directly: the existing in-workout rest approvals do not
  authorize a calorie or program change.
* **Bounds include a rate.** A single-change ceiling with no frequency
  limit is not a limit.
* **Everything is re-checked immediately before acting** — liveness,
  expiry, bounds, rate, coverage, evidence, pain, revision — inside the
  same transaction as the change.
* **Outside the bounds is a proposal, not a bigger action.**
* **Every applied action has a receipt and an idempotency key**, so a retry
  cannot apply twice and `verify_action` can read back what happened.
* **Any policy can be switched off and future actions stop.**

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_approved_automation_pg.py
"""
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

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
    alice = f"s30a-{uuid.uuid4().hex[:17]}"
    bob = f"s30b-{uuid.uuid4().hex[:17]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@s30.invalid", "p": unusable_hash})
    pg.commit()
    yield alice, bob
    pg.rollback()
    for table in ("fitness_automation_action", "fitness_automation_policy",
                  "fitness_source_adapter", "action_receipt",
                  "fitness_pain_report", "health_metric", "food_log",
                  "workout_log", "workout", "daily_recovery_log",
                  "fitness_target_revision", "fitness_athlete_goal",
                  "fitness_athlete_profile", "fitness_program_revision",
                  "fitness_phase", "fitness_program"):
        try:
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                       {"ids": [alice, bob]})
            pg.commit()
        except Exception:
            pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"),
               {"ids": [alice, bob]})
    pg.commit()


def _policy_in(**over):
    from app.schemas.fitness_coach import AutomationAction, AutomationPolicyIn

    body = {
        "action": AutomationAction.CALORIE_ADJUST,
        "max_change": 150,
        "min_change": 25,
        "max_actions_per_window": 2,
        "window_days": 14,
        "min_coverage_days": 10,
        "coverage_window_days": 14,
        "requires_evidence": False,
        "expires_at": datetime.now(UTC) + timedelta(days=90),
        "notify": True,
        "note": "small weekly nudges only",
    }
    body.update(over)
    return AutomationPolicyIn(**body)


def _request(**over):
    from app.schemas.fitness_coach import AutomationAction
    from app.services.fitness.automation import AutomationRequest

    body = {
        "action": AutomationAction.CALORIE_ADJUST,
        "change": -100.0,
        "idempotency_key": f"test:{uuid.uuid4()}",
        "reason": "loss has stalled for two weeks at a steady intake",
        "evidence_refs": [{"kind": "metric", "value": "weight.velocity_weekly"}],
    }
    body.update(over)
    return AutomationRequest(**body)


def _coverage(pg, user_id, *, days=14):
    """Food logs and weigh-ins on the same days, which is what a calorie
    adjustment's coverage is counted from."""
    for offset in range(days):
        day = date.today() - timedelta(days=offset)
        pg.execute(text("""
            INSERT INTO food_log (
                id, user_id, meal_type, food_items, calories, protein,
                carbs, fats, logged_at, created_at
            ) VALUES (
                :id, :u, 'lunch', '["chicken and rice"]', 700, 55, 70, 18,
                :logged, NOW()
            )
        """), {
            "id": str(uuid.uuid4()), "u": user_id,
            "logged": datetime.combine(day, datetime.min.time())
            + timedelta(hours=13),
        })
        pg.execute(text("""
            INSERT INTO health_metric (
                id, user_id, metric_type, value, unit, recorded_at,
                source, created_at
            ) VALUES (
                :id, :u, 'weight', 82.5, 'kg', :recorded, 'manual', NOW()
            )
        """), {
            "id": str(uuid.uuid4()), "u": user_id,
            "recorded": datetime.combine(day, datetime.min.time()).replace(
                tzinfo=UTC,
            ) + timedelta(hours=7),
        })
    pg.commit()


# ─────────────────────────────────────────────────────────────────────────
# Nothing is automated by default
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_no_policy_means_no_action(pg, two_athletes):
    """§30.2. Nothing is on until somebody turned it on, and no other
    approval implies this one."""
    from app.schemas.fitness_coach import AutomationDenial
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    outcome = automation.execute(pg, alice, _request())
    assert outcome.decision.value == "denied"
    assert outcome.denial is AutomationDenial.NO_POLICY
    assert "no other approval implies this one" in outcome.reason


@requires_pg
def test_a_policy_is_for_one_action_only(pg, two_athletes):
    """§30.2's central rule: approving the in-workout rest automation has
    never authorized a calorie change. The database agrees."""
    from app.schemas.fitness_coach import AutomationAction, AutomationDenial
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(
        pg, alice,
        _policy_in(
            action=AutomationAction.PROGRESSION_APPLY,
            max_change=10, min_change=1,
        ),
        approved_by=alice,
    )
    # A progression policy does not authorize a calorie adjustment.
    outcome = automation.execute(pg, alice, _request())
    assert outcome.denial is AutomationDenial.NO_POLICY

    # And an action row cannot point at a policy for another action.
    policy_id = pg.execute(text("""
        SELECT id FROM fitness_automation_policy
        WHERE user_id = :u AND action = 'progression_apply'
    """), {"u": alice}).scalar()
    with pytest.raises((IntegrityError, DBAPIError)) as excinfo:
        pg.execute(text("""
            INSERT INTO fitness_automation_action (
                id, user_id, policy_id, action, decision, reason,
                applied_change, receipt_id, idempotency_key
            ) VALUES (
                :id, :u, :policy, 'calorie_adjust', 'applied', 'because',
                -100, 'receipt', :key
            )
        """), {
            "id": str(uuid.uuid4()), "u": alice, "policy": policy_id,
            "key": f"bad:{uuid.uuid4()}",
        })
        pg.commit()
    assert "does not authorize" in str(excinfo.value)
    pg.rollback()


@requires_pg
def test_a_model_cannot_approve_a_policy(pg, two_athletes):
    """A permission granted by the thing that uses it is not a
    permission."""
    from app.services.fitness import automation

    alice, _ = two_athletes
    for approver in ("model", "llm", "autonomous", "system"):
        with pytest.raises(automation.AutomationError) as excinfo:
            automation.grant_policy(
                pg, alice, _policy_in(), approved_by=approver,
            )
        assert "is not a" in str(excinfo.value)

    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_automation_policy (
                id, user_id, action, max_change, max_actions_per_window,
                window_days, min_coverage_days, coverage_window_days,
                expires_at, approved_by
            ) VALUES (
                :id, :u, 'calorie_adjust', 100, 1, 7, 5, 7,
                NOW() + INTERVAL '30 days', 'model'
            )
        """), {"id": str(uuid.uuid4()), "u": alice})
        pg.commit()
    pg.rollback()


@requires_pg
def test_a_granted_policy_can_be_disabled_at_grant_time(pg, two_athletes):
    """Granting and enabling are separate. A permission recorded but not
    switched on is a normal state."""
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    policy = automation.grant_policy(
        pg, alice, _policy_in(), approved_by=alice, enabled=False,
    )
    assert policy.enabled is False
    outcome = automation.execute(pg, alice, _request())
    assert outcome.denial.value == "policy_disabled"


# ─────────────────────────────────────────────────────────────────────────
# Bounds, rate and coverage
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_an_in_bounds_change_applies_with_a_receipt(pg, two_athletes):
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)

    outcome = automation.execute(pg, alice, _request(change=-100.0))
    assert outcome.decision.value == "applied_notified"
    assert outcome.applied_change == -100.0
    assert outcome.receipt_id

    receipt = pg.execute(text("""
        SELECT action_type, permission_tier, status, evidence_refs,
               idempotency_key
        FROM action_receipt WHERE action_id = CAST(:id AS uuid)
    """), {"id": outcome.receipt_id}).fetchone()
    assert receipt.action_type == "fitness_automation"
    # Pre-approved does not make it routine: this moved somebody's target
    # without asking at the time.
    assert receipt.permission_tier == "consequential"
    assert receipt.status == "completed"


@requires_pg
def test_an_outside_bound_change_becomes_a_proposal(pg, two_athletes):
    """§30.3: major outside-bound changes remain proposals. This is also
    what makes a narrow bound safe to grant — the answer to "this needs
    300 and you approved 150" is to ask."""
    from app.schemas.fitness_coach import AutomationDenial
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(pg, alice, _policy_in(max_change=150),
                            approved_by=alice)

    outcome = automation.execute(pg, alice, _request(change=-300.0))
    assert outcome.decision.value == "proposed"
    assert outcome.denial is AutomationDenial.OUTSIDE_BOUNDS
    assert outcome.applied_change is None
    assert "becomes a proposal" in outcome.reason
    # And no receipt: nothing happened.
    assert outcome.receipt_id is None


@requires_pg
def test_a_change_below_the_floor_is_not_worth_making(pg, two_athletes):
    """An automation that moves nothing is noise with a receipt."""
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(pg, alice, _policy_in(min_change=25),
                            approved_by=alice)
    outcome = automation.execute(pg, alice, _request(change=-10.0))
    assert outcome.decision.value == "proposed"
    assert "floor" in outcome.reason


@requires_pg
def test_the_rate_limit_caps_repeated_adjustments(pg, two_athletes):
    """The plan's "repeated adjustment cap". Fourteen approved 50-calorie
    steps is a 700-calorie change nobody approved."""
    from app.schemas.fitness_coach import AutomationDenial
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(
        pg, alice, _policy_in(max_actions_per_window=2, window_days=14),
        approved_by=alice,
    )

    first = automation.execute(pg, alice, _request(change=-50.0))
    second = automation.execute(pg, alice, _request(change=-50.0))
    third = automation.execute(pg, alice, _request(change=-50.0))

    assert first.decision.value == "applied_notified"
    assert second.decision.value == "applied_notified"
    assert third.decision.value == "denied"
    assert third.denial is AutomationDenial.RATE_LIMITED
    assert "which is the approved limit" in third.reason

    applied = pg.execute(text("""
        SELECT COUNT(*) FROM fitness_automation_action
        WHERE user_id = :u AND decision IN ('applied', 'applied_notified')
    """), {"u": alice}).scalar()
    assert applied == 2


@requires_pg
def test_the_rate_window_is_counted_from_the_log(pg, two_athletes):
    """From the log rather than a counter: a counter drifts when a
    transaction rolls back after incrementing it, and the drift is in the
    permissive direction."""
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(
        pg, alice, _policy_in(max_actions_per_window=1, window_days=7),
        approved_by=alice,
    )
    automation.execute(pg, alice, _request(change=-50.0))
    assert automation.execute(
        pg, alice, _request(change=-50.0),
    ).denial.value == "rate_limited"

    # Age the applied action past the window.
    pg.execute(text("""
        UPDATE fitness_automation_action
        SET created_at = NOW() - INTERVAL '10 days'
        WHERE user_id = :u AND decision IN ('applied', 'applied_notified')
    """), {"u": alice})
    pg.commit()
    assert automation.execute(
        pg, alice, _request(change=-50.0),
    ).decision.value == "applied_notified"


@requires_pg
def test_sparse_data_stops_the_automation(pg, two_athletes):
    """The plan's "sparse-data stop". An adjustment from two weigh-ins is a
    response to noise, and a confident small change is the wrong answer."""
    from app.schemas.fitness_coach import AutomationDenial
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice, days=3)
    automation.grant_policy(
        pg, alice, _policy_in(min_coverage_days=10, coverage_window_days=14),
        approved_by=alice,
    )
    outcome = automation.execute(pg, alice, _request())
    assert outcome.decision.value == "denied"
    assert outcome.denial is AutomationDenial.INSUFFICIENT_COVERAGE
    assert "response to noise" in outcome.reason


@requires_pg
def test_coverage_needs_both_streams_for_a_calorie_change(pg, two_athletes):
    """A fortnight of weigh-ins cannot authorize a change computed from
    intake, and counting "any fitness row" would let it."""
    from app.services.fitness import automation

    alice, _ = two_athletes
    for offset in range(14):
        day = date.today() - timedelta(days=offset)
        pg.execute(text("""
            INSERT INTO health_metric (
                id, user_id, metric_type, value, unit, recorded_at, source,
                created_at
            ) VALUES (
                :id, :u, 'weight', 82.0, 'kg', :recorded, 'manual', NOW()
            )
        """), {
            "id": str(uuid.uuid4()), "u": alice,
            "recorded": datetime.combine(
                day, datetime.min.time(),
            ).replace(tzinfo=UTC),
        })
    pg.commit()
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)
    outcome = automation.execute(pg, alice, _request())
    assert outcome.denial.value == "insufficient_coverage"


@requires_pg
def test_an_evidence_requiring_policy_refuses_without_evidence(
    pg, two_athletes,
):
    from app.schemas.fitness_coach import AutomationDenial
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(
        pg, alice, _policy_in(requires_evidence=True), approved_by=alice,
    )
    assert automation.execute(
        pg, alice, _request(),
    ).denial is AutomationDenial.EVIDENCE_REQUIRED

    with_evidence = automation.execute(
        pg, alice, _request(science_chunk_ids=["chunk-1"]),
    )
    assert with_evidence.decision.value == "applied_notified"
    # The cited chunk reaches the receipt, so the evidence is recoverable.
    evidence = pg.execute(text("""
        SELECT evidence_refs::text FROM action_receipt
        WHERE action_id = CAST(:id AS uuid)
    """), {"id": with_evidence.receipt_id}).scalar()
    assert "chunk-1" in evidence


# ─────────────────────────────────────────────────────────────────────────
# Expiry, revocation, the off switch
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_an_expired_policy_authorizes_nothing(pg, two_athletes):
    """A permission with no end is one nobody remembers giving, so it has
    one — and the end is enforced on every attempt."""
    from app.schemas.fitness_coach import AutomationDenial
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)
    pg.execute(text("""
        UPDATE fitness_automation_policy
        SET expires_at = NOW() - INTERVAL '1 day' WHERE user_id = :u
    """), {"u": alice})
    pg.commit()

    outcome = automation.execute(pg, alice, _request())
    assert outcome.denial is AutomationDenial.POLICY_EXPIRED
    assert "nobody remembers giving" in outcome.reason


@requires_pg
def test_granting_an_already_expired_policy_is_refused(pg, two_athletes):
    from app.services.fitness import automation

    alice, _ = two_athletes
    with pytest.raises(automation.AutomationError) as excinfo:
        automation.grant_policy(
            pg, alice,
            _policy_in(expires_at=datetime.now(UTC) - timedelta(days=1)),
            approved_by=alice,
        )
    assert "already past" in str(excinfo.value)


@requires_pg
def test_disabling_a_policy_stops_future_actions(pg, two_athletes):
    """The §30 completion criterion, stated as the thing somebody would
    check: switch it off, and the next attempt is denied."""
    from app.schemas.fitness_coach import AutomationAction, AutomationDenial
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)
    assert automation.execute(
        pg, alice, _request(change=-50.0),
    ).decision.value == "applied_notified"

    automation.set_enabled(
        pg, alice, AutomationAction.CALORIE_ADJUST, False,
    )
    after = automation.execute(pg, alice, _request(change=-50.0))
    assert after.decision.value == "denied"
    assert after.denial is AutomationDenial.POLICY_DISABLED

    # And on again.
    automation.set_enabled(pg, alice, AutomationAction.CALORIE_ADJUST, True)
    assert automation.execute(
        pg, alice, _request(change=-50.0),
    ).decision.value == "applied_notified"


@requires_pg
def test_a_revoked_policy_denies_and_says_why(pg, two_athletes):
    from app.schemas.fitness_coach import AutomationAction, AutomationDenial
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)
    automation.revoke_policy(
        pg, alice, AutomationAction.CALORIE_ADJUST,
        reason="I want to do this by hand for a while",
    )
    outcome = automation.execute(pg, alice, _request())
    assert outcome.denial is AutomationDenial.POLICY_REVOKED
    assert "by hand" in outcome.reason


@requires_pg
def test_a_revocation_needs_a_reason(pg, two_athletes):
    from app.schemas.fitness_coach import AutomationAction
    from app.services.fitness import automation

    alice, _ = two_athletes
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)
    with pytest.raises(automation.AutomationError):
        automation.revoke_policy(
            pg, alice, AutomationAction.CALORIE_ADJUST, reason="x",
        )


@requires_pg
def test_regranting_replaces_rather_than_stacking(pg, two_athletes):
    """Two live policies for one action would mean two answers to "what did
    I agree to", and whichever the code read first would win."""
    from app.services.fitness import automation

    alice, _ = two_athletes
    automation.grant_policy(pg, alice, _policy_in(max_change=100),
                            approved_by=alice)
    automation.grant_policy(pg, alice, _policy_in(max_change=200),
                            approved_by=alice)
    live = pg.execute(text("""
        SELECT COUNT(*) FROM fitness_automation_policy
        WHERE user_id = :u AND action = 'calorie_adjust'
          AND revoked_at IS NULL
    """), {"u": alice}).scalar()
    assert live == 1
    # The old one is kept, with its reason, because actions reference it.
    total = pg.execute(text("""
        SELECT COUNT(*) FROM fitness_automation_policy WHERE user_id = :u
    """), {"u": alice}).scalar()
    assert total == 2


@requires_pg
def test_the_database_allows_only_one_live_policy_per_action(pg, two_athletes):
    alice, _ = two_athletes
    for _ in range(2):
        try:
            pg.execute(text("""
                INSERT INTO fitness_automation_policy (
                    id, user_id, action, max_change, max_actions_per_window,
                    window_days, min_coverage_days, coverage_window_days,
                    expires_at, approved_by
                ) VALUES (
                    :id, :u, 'calorie_adjust', 100, 1, 7, 5, 7,
                    NOW() + INTERVAL '30 days', :u
                )
            """), {"id": str(uuid.uuid4()), "u": alice})
            pg.commit()
        except (IntegrityError, DBAPIError):
            pg.rollback()
            break
    else:
        pytest.fail("two live policies for one action were accepted")


# ─────────────────────────────────────────────────────────────────────────
# Pain, staleness, idempotency
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_reported_pain_stops_an_unrelated_automated_change(pg, two_athletes):
    """§30.3. An automated calorie cut while something hurts is the wrong
    priority — it needs a person."""
    from app.schemas.fitness_coach import AutomationDenial
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)
    pg.execute(text("""
        INSERT INTO fitness_pain_report (
            id, user_id, occurred_at, logical_date, pain_present, severity,
            location, source, created_at
        ) VALUES (
            :id, :u, NOW() - INTERVAL '1 day', CURRENT_DATE - 1, TRUE, 6,
            'left knee', 'user', NOW()
        )
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    outcome = automation.execute(pg, alice, _request())
    assert outcome.denial is AutomationDenial.PAIN_REPORTED
    assert "wrong priority" in outcome.reason


@requires_pg
def test_a_pain_load_reduction_is_the_one_action_pain_does_not_block(
    pg, two_athletes,
):
    """Blocking it would be the wrong way round: reducing load after a pain
    report is the response, not a change to defer."""
    from app.schemas.fitness_coach import AutomationAction
    from app.services.fitness import automation

    alice, _ = two_athletes
    # Logged sessions, which is what this action's coverage counts.
    workout_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO workout (id, user_id, title, created_at)
        VALUES (:id, :u, 'Session', NOW())
    """), {"id": workout_id, "u": alice})
    for offset in range(12):
        pg.execute(text("""
            INSERT INTO workout_log (
                id, workout_id, user_id, set_index, reps, load_value,
                load_unit, session_date, created_at
            ) VALUES (
                :id, :w, :u, 0, 5, 100, 'kg', CURRENT_DATE - :offset, NOW()
            )
        """), {
            "id": str(uuid.uuid4()), "w": workout_id, "u": alice,
            "offset": offset,
        })
    pg.commit()
    pg.execute(text("""
        INSERT INTO fitness_pain_report (
            id, user_id, occurred_at, logical_date, pain_present, severity,
            location, source, created_at
        ) VALUES (
            :id, :u, NOW() - INTERVAL '1 day', CURRENT_DATE - 1, TRUE, 7,
            'left shoulder', 'user', NOW()
        )
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    automation.grant_policy(
        pg, alice,
        _policy_in(
            action=AutomationAction.PAIN_LOAD_REDUCTION, max_change=0.25,
            min_change=0.05, min_coverage_days=8, coverage_window_days=14,
        ),
        approved_by=alice,
    )
    outcome = automation.execute(pg, alice, _request(
        action=AutomationAction.PAIN_LOAD_REDUCTION, change=-0.1,
        reason="pain reported on the last session",
    ))
    assert outcome.decision.value == "applied_notified"


@requires_pg
def test_an_unreadable_pain_table_does_not_proceed_as_though_clear(
    pg, two_athletes, monkeypatch,
):
    """A gate that cannot read the pain reports does not treat that as "no
    pain". Failing closed is the only safe direction here."""
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)

    # `_recent_pain` returns 10 when it cannot read the table — failing
    # closed is the only safe direction, and this is that path.
    monkeypatch.setattr(automation, "_recent_pain", lambda db, uid: 10)
    outcome = automation.execute(pg, alice, _request())
    assert outcome.denial.value == "pain_reported"


@requires_pg
def test_a_stale_target_revision_denies_the_action(pg, two_athletes):
    """The plan's "stale/current revision". Somebody edited their targets
    between the proposal and the execution."""
    from app.schemas.fitness_coach import AutomationDenial
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)

    outcome = automation.execute(pg, alice, _request(
        expected_target_revision_id="a-revision-that-is-not-current",
    ))
    assert outcome.denial is AutomationDenial.STALE_REVISION
    assert "edited their targets" in outcome.reason


@requires_pg
def test_a_matching_current_revision_is_allowed(pg, two_athletes):
    """The staleness check has to let the ordinary case through, or it is
    just an outage."""
    from app.services.fitness import automation
    from app.schemas.fitness_coach import (
        TargetRevisionIn, TargetScope, TargetValues,
    )
    from app.services.fitness.targets import create_target_revision

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)

    revision = create_target_revision(
        pg, alice,
        TargetRevisionIn(
            scope=TargetScope.DEFAULT,
            valid_from=date.today() - timedelta(days=7),
            training=TargetValues(calories=2400, protein_g=180),
            source="user",
        ),
        approved_by=alice,
    )
    outcome = automation.execute(pg, alice, _request(
        expected_target_revision_id=revision.id,
    ))
    assert outcome.decision.value == "applied_notified"


@requires_pg
def test_a_stale_program_revision_denies_the_action(pg, two_athletes):
    from app.schemas.fitness_coach import AutomationAction
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)
    outcome = automation.execute(pg, alice, _request(
        expected_program_revision=4,
    ))
    assert outcome.denial.value == "stale_revision"
    assert "program revision 4" in outcome.reason


@requires_pg
def test_a_retry_with_the_same_key_does_not_apply_twice(pg, two_athletes):
    """The plan's "idempotency". A worker that loses its connection after
    the change and before its own bookkeeping retries the whole attempt."""
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)

    key = f"daily-nutrition:{date.today().isoformat()}"
    first = automation.execute(
        pg, alice, _request(change=-100.0, idempotency_key=key),
    )
    second = automation.execute(
        pg, alice, _request(change=-100.0, idempotency_key=key),
    )
    assert first.decision.value == "applied_notified"
    assert second.receipt_id == first.receipt_id
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_automation_action WHERE user_id = :u
    """), {"u": alice}).scalar() == 1
    assert pg.execute(text("""
        SELECT COUNT(*) FROM action_receipt
        WHERE user_id = :u AND action_type = 'fitness_automation'
    """), {"u": alice}).scalar() == 1


@requires_pg
def test_an_action_with_no_idempotency_key_is_refused(pg, two_athletes):
    from app.services.fitness import automation

    alice, _ = two_athletes
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)
    for bad in ("", "   "):
        with pytest.raises(automation.AutomationError) as excinfo:
            automation.execute(
                pg, alice, _request(idempotency_key=bad),
            )
        assert "applies the change twice" in str(excinfo.value)


@requires_pg
def test_an_applied_change_is_actually_applied(pg, two_athletes):
    """The `apply` callable runs in the same transaction as the receipt, so
    a receipt cannot claim an effect that rolled back."""
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)

    applied = []

    def apply(db, change):
        applied.append(change)
        return "revision-123"

    outcome = automation.execute(pg, alice, _request(
        change=-100.0, apply=apply,
    ))
    assert applied == [-100.0]
    target = pg.execute(text("""
        SELECT target FROM action_receipt
        WHERE action_id = CAST(:id AS uuid)
    """), {"id": outcome.receipt_id}).scalar()
    assert target == "revision-123"


@requires_pg
def test_a_failing_apply_logs_a_denial_and_changes_nothing(pg, two_athletes):
    """An attempt that errored is not an attempt that never happened, and
    the next sweep should see it."""
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)

    def apply(db, change):
        raise RuntimeError("the target table is locked")

    outcome = automation.execute(pg, alice, _request(apply=apply))
    assert outcome.decision.value == "denied"
    assert "could not be applied" in outcome.reason
    assert outcome.receipt_id is None
    assert pg.execute(text("""
        SELECT COUNT(*) FROM action_receipt
        WHERE user_id = :u AND action_type = 'fitness_automation'
    """), {"u": alice}).scalar() == 0


@requires_pg
def test_an_action_row_cannot_be_rewritten(pg, two_athletes):
    """The log is the record of what was done under a permission. A mutable
    one is a cache."""
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)
    automation.execute(pg, alice, _request(change=-100.0))

    action_id = pg.execute(text("""
        SELECT id FROM fitness_automation_action WHERE user_id = :u
    """), {"u": alice}).scalar()
    for column, value in (
        ("decision", "'denied'"),
        ("applied_change", "-999"),
        ("reason", "'something else'"),
        ("receipt_id", "'another-receipt'"),
    ):
        with pytest.raises((IntegrityError, DBAPIError)) as excinfo:
            pg.execute(text(
                f"UPDATE fitness_automation_action SET {column} = {value} "
                f"WHERE id = :id"
            ), {"id": action_id})
            pg.commit()
        assert "cannot be rewritten" in str(excinfo.value)
        pg.rollback()

    # `notified` may change — that is the one field a delivery updates.
    pg.execute(text("""
        UPDATE fitness_automation_action SET notified = TRUE WHERE id = :id
    """), {"id": action_id})
    pg.commit()


@requires_pg
def test_a_denial_is_logged_with_its_reason(pg, two_athletes):
    """"Why did nothing happen on Tuesday" is a question somebody asks, and
    a log of successes answers it with silence."""
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice, days=2)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)
    automation.execute(pg, alice, _request())

    row = pg.execute(text("""
        SELECT decision, denial, reason, coverage_days, policy_snapshot
        FROM fitness_automation_action WHERE user_id = :u
    """), {"u": alice}).fetchone()
    assert row.decision == "denied"
    assert row.denial == "insufficient_coverage"
    assert row.coverage_days == 2
    # The bounds as they were, because a policy can be edited afterwards.
    snapshot = row.policy_snapshot
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    assert snapshot["max_change"] == 150


@requires_pg
def test_one_athlete_cannot_act_under_anothers_policy(pg, two_athletes):
    from app.services.fitness import automation

    alice, bob = two_athletes
    _coverage(pg, alice)
    _coverage(pg, bob)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)

    # Bob has no policy of his own, whatever Alice approved.
    assert automation.execute(
        pg, bob, _request(),
    ).denial.value == "no_policy"
    assert automation.list_policies(pg, bob) == []


# ─────────────────────────────────────────────────────────────────────────
# Monitoring (§30.5)
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_health_groups_denials_by_reason(pg, two_athletes):
    """An automation denied every day for insufficient coverage is not
    working as agreed — it is configured for data that does not exist, and
    the fix is a conversation rather than a wider bound."""
    from app.services.fitness import automation

    alice, _ = two_athletes
    _coverage(pg, alice, days=2)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)
    for _ in range(3):
        automation.execute(pg, alice, _request())

    report = automation.health(pg, alice)
    bucket = report["by_action"]["calorie_adjust"]
    assert bucket["denied"] == 3
    assert bucket["denials"]["insufficient_coverage"] == 3
    assert report["any_enabled"] is True


@requires_pg
def test_health_says_so_when_nothing_is_enabled(pg, two_athletes):
    """A policy with no live grant is the normal state, and the health view
    says so rather than looking like a broken automation."""
    from app.services.fitness import automation

    alice, _ = two_athletes
    report = automation.health(pg, alice)
    assert report["policies"] == []
    assert report["any_enabled"] is False


# ─────────────────────────────────────────────────────────────────────────
# The source contract (§30.4)
# ─────────────────────────────────────────────────────────────────────────

def _contract(**over):
    from app.schemas.fitness_coach import SourceAdapterContract, SourceKind

    body = {
        "kind": SourceKind.SCALE,
        "vendor": "test_scale",
        "external_id_field": "measurement_id",
        "writes_metrics": ["weight"],
        "timestamp_convention": "aware_utc",
        "requires_consent": True,
        "may_overwrite": False,
    }
    body.update(over)
    return SourceAdapterContract(**body)


def _observation(**over):
    from app.services.fitness.sources import Observation

    body = {
        "metric": "weight",
        "value": 82.4,
        "unit": "kg",
        "observed_at": datetime.now(UTC) - timedelta(hours=3),
        "external_id": f"sample-{uuid.uuid4().hex[:12]}",
    }
    body.update(over)
    return Observation(**body)


@requires_pg
def test_healthkit_is_described_by_the_same_contract(pg, two_athletes):
    """§30.4: "existing HealthKit remains supported throughout". The way to
    keep that true is for it to be described by the contract a future
    source will be, rather than being the one special case."""
    from app.services.fitness import sources

    contract = sources.ensure_healthkit(pg, None)
    assert contract["vendor"] == "apple_health"
    stored = sources.get_contract(pg, None, "apple_health")
    assert "weight" in stored["writes_metrics"]
    assert stored["timestamp_convention"] == "aware_utc"
    # Registered is not enabled. The existing ingest path keeps working
    # exactly as it does; this row describes it.
    assert stored["enabled"] is False
    pg.execute(text("DELETE FROM fitness_source_adapter WHERE user_id IS NULL"))
    pg.commit()


@requires_pg
def test_an_unregistered_source_cannot_write(pg, two_athletes):
    from app.services.fitness import sources

    alice, _ = two_athletes
    with pytest.raises(LookupError):
        sources.ingest(pg, alice, "some_new_vendor", [_observation()])


@requires_pg
def test_registration_is_not_consent(pg, two_athletes):
    """A source that reads as soon as it is installed is the failure this
    field exists to prevent."""
    from app.services.fitness import sources

    alice, _ = two_athletes
    sources.register(pg, alice, _contract(), enabled=False)
    with pytest.raises(sources.SourceError) as excinfo:
        sources.ingest(pg, alice, "test_scale", [_observation()])
    assert "no consent on file" in str(excinfo.value)


@requires_pg
def test_enabling_a_consenting_source_without_consent_is_refused(
    pg, two_athletes,
):
    from app.services.fitness import sources

    alice, _ = two_athletes
    with pytest.raises(sources.SourceError):
        sources.register(pg, alice, _contract(), enabled=True)


@requires_pg
def test_a_consented_source_writes_and_a_resync_does_not_duplicate(
    pg, two_athletes,
):
    """The plan's idempotency, at the source boundary. Without a stable
    per-observation id a re-sync duplicates a year of weigh-ins, and the
    duplicates are indistinguishable from genuine double entries."""
    from app.services.fitness import sources

    alice, _ = two_athletes
    sources.register(
        pg, alice, _contract(), consented_at=datetime.now(UTC), enabled=True,
    )
    observation = _observation()
    first = sources.ingest(pg, alice, "test_scale", [observation])
    second = sources.ingest(pg, alice, "test_scale", [observation])

    assert first["written"] == 1
    assert second["written"] == 0
    assert second["skipped"] == []
    assert pg.execute(text("""
        SELECT COUNT(*) FROM health_metric
        WHERE user_id = :u AND source = 'test_scale'
    """), {"u": alice}).scalar() == 1


@requires_pg
def test_an_undeclared_metric_is_refused_not_written(pg, two_athletes):
    """A source that can write anything will overwrite something. The
    declaration is the value."""
    from app.services.fitness import sources

    alice, _ = two_athletes
    sources.register(
        pg, alice, _contract(writes_metrics=["weight"]),
        consented_at=datetime.now(UTC), enabled=True,
    )
    result = sources.ingest(
        pg, alice, "test_scale", [_observation(metric="body_fat", value=14.2)],
    )
    assert result["written"] == 0
    assert "not declared" in result["skipped"][0]
    assert pg.execute(text("""
        SELECT COUNT(*) FROM health_metric
        WHERE user_id = :u AND metric_type = 'body_fat'
    """), {"u": alice}).scalar() == 0


@requires_pg
def test_an_observation_with_no_external_id_is_refused(pg, two_athletes):
    from app.services.fitness import sources

    alice, _ = two_athletes
    sources.register(
        pg, alice, _contract(), consented_at=datetime.now(UTC), enabled=True,
    )
    result = sources.ingest(
        pg, alice, "test_scale", [_observation(external_id="")],
    )
    assert result["written"] == 0
    assert "no external id" in result["skipped"][0]


@requires_pg
def test_a_source_conflict_on_one_instant_is_reported_not_silent(
    pg, two_athletes,
):
    """The plan's "source integration conflicts". A later sync from a worse
    source replacing a manual entry is data loss that nothing reports —
    this reports it."""
    from app.services.fitness import sources

    alice, _ = two_athletes
    instant = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=5)
    pg.execute(text("""
        INSERT INTO health_metric (
            id, user_id, metric_type, value, unit, recorded_at, source,
            created_at
        ) VALUES (
            :id, :u, 'weight', 83.0, 'kg', :recorded, 'manual', NOW()
        )
    """), {"id": str(uuid.uuid4()), "u": alice, "recorded": instant})
    pg.commit()

    sources.register(
        pg, alice, _contract(), consented_at=datetime.now(UTC), enabled=True,
    )
    result = sources.ingest(
        pg, alice, "test_scale",
        [_observation(value=81.9, observed_at=instant)],
    )
    assert result["written"] == 0
    assert result["skipped"]
    assert "manual" in result["skipped"][0]
    assert "may not overwrite" in result["skipped"][0]
    # The manual value stands.
    assert float(pg.execute(text("""
        SELECT value FROM health_metric
        WHERE user_id = :u AND recorded_at = :recorded
    """), {"u": alice, "recorded": instant}).scalar()) == 83.0


@requires_pg
def test_withdrawing_consent_switches_the_source_off(pg, two_athletes):
    """A source that keeps writing after consent is withdrawn is the
    failure this prevents, and leaving `enabled` true would allow it."""
    from app.services.fitness import sources

    alice, _ = two_athletes
    sources.register(
        pg, alice, _contract(), consented_at=datetime.now(UTC), enabled=True,
    )
    result = sources.set_consent(pg, alice, "test_scale", False)
    assert result["enabled"] is False
    with pytest.raises(sources.SourceError):
        sources.ingest(pg, alice, "test_scale", [_observation()])


@requires_pg
def test_a_second_contract_for_one_vendor_is_refused(pg, two_athletes):
    """Two contracts for one vendor means two answers to what it may
    write."""
    from app.services.fitness import sources

    alice, _ = two_athletes
    sources.register(pg, alice, _contract())
    with pytest.raises(sources.SourceError) as excinfo:
        sources.register(pg, alice, _contract(writes_metrics=["body_fat"]))
    assert "already registered" in str(excinfo.value)


@requires_pg
def test_a_naive_local_timestamp_is_converted_by_the_declared_convention(
    pg, two_athletes,
):
    """Three conventions exist in this database. A source that does not
    declare which it sends lands its data 4-5 hours out, and the error looks
    like the athlete logging at odd hours."""
    from app.services.fitness import sources

    alice, _ = two_athletes
    pg.execute(text("""
        INSERT INTO fitness_athlete_profile (
            id, user_id, available_days, equipment, preferred_exercise_ids,
            excluded_exercise_ids, dietary_restrictions,
            dietary_preferences, supplements, calculation_sex,
            training_level, coaching_style, monitoring_consent, timezone,
            weight_unit, length_unit, row_version, created_at, updated_at
        ) VALUES (
            :id, :u, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
            '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, 'male', 'advanced',
            'unset', FALSE, 'America/New_York', 'lb', 'in', 1, NOW(), NOW()
        )
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    sources.register(
        pg, alice, _contract(timestamp_convention="naive_local"),
        consented_at=datetime.now(UTC), enabled=True,
    )
    # 07:30 on the athlete's clock, with no zone attached.
    local_morning = datetime(2026, 7, 15, 7, 30)
    sources.ingest(
        pg, alice, "test_scale",
        [_observation(observed_at=local_morning)],
    )
    stored = pg.execute(text("""
        SELECT recorded_at FROM health_metric
        WHERE user_id = :u AND source = 'test_scale'
    """), {"u": alice}).scalar()
    # July in New York is UTC-4, so 07:30 local is 11:30Z — not 07:30Z,
    # which is what a naive insert would have stored.
    assert stored.astimezone(UTC).hour == 11
    assert stored.astimezone(UTC).minute == 30


@requires_pg
def test_an_aware_contract_refuses_a_naive_timestamp(pg, two_athletes):
    """One of the two is wrong, and guessing would put the reading on the
    wrong day."""
    from app.services.fitness import sources

    alice, _ = two_athletes
    sources.register(
        pg, alice, _contract(timestamp_convention="aware_utc"),
        consented_at=datetime.now(UTC), enabled=True,
    )
    with pytest.raises(sources.SourceError) as excinfo:
        sources.ingest(
            pg, alice, "test_scale",
            [_observation(observed_at=datetime(2026, 7, 15, 7, 30))],
        )
    assert "wrong day" in str(excinfo.value)


# ─────────────────────────────────────────────────────────────────────────
# Longitudinal summaries (§30.1)
# ─────────────────────────────────────────────────────────────────────────

def _goal_window(pg, user_id, kind, start, end=None):
    pg.execute(text("""
        INSERT INTO fitness_athlete_goal (
            id, user_id, kind, is_primary, priority, rationale, rate_basis,
            valid_from, valid_until, recorded_at, source
        ) VALUES (
            :id, :u, :kind, FALSE, 2, :rationale, 'none', :start, :end,
            NOW(), 'user'
        )
    """), {
        "id": str(uuid.uuid4()), "u": user_id, "kind": kind,
        "rationale": f"{kind} block", "start": start, "end": end,
    })
    pg.commit()


def _year_of_weigh_ins(pg, user_id, *, start, days, first_kg, last_kg):
    step = (last_kg - first_kg) / max(days - 1, 1)
    for offset in range(days):
        pg.execute(text("""
            INSERT INTO health_metric (
                id, user_id, metric_type, value, unit, recorded_at, source,
                created_at
            ) VALUES (
                :id, :u, 'weight', :value, 'kg', :recorded, 'manual', NOW()
            )
        """), {
            "id": str(uuid.uuid4()), "u": user_id,
            "value": round(first_kg + step * offset, 2),
            "recorded": datetime.combine(
                start + timedelta(days=offset), datetime.min.time(),
            ).replace(tzinfo=UTC) + timedelta(hours=7),
        })
    pg.commit()


@requires_pg
def test_history_splits_where_the_goal_changed(pg, two_athletes):
    """§30.1: compare goals/phases/protocols explicitly. Two stretches with
    different goals are two different experiments."""
    from app.services.fitness import longitudinal

    alice, _ = two_athletes
    today = date.today()
    start = today - timedelta(days=240)
    middle = today - timedelta(days=120)
    _goal_window(pg, alice, "cut", start, middle)
    _goal_window(pg, alice, "gain", middle, None)

    periods = longitudinal.comparable_periods(pg, alice, start, today)
    assert len(periods) == 2
    assert periods[0].goal_kind == "cut"
    assert periods[1].goal_kind == "gain"


@requires_pg
def test_a_stretch_too_short_to_rate_is_not_a_period(pg, two_athletes):
    """A two-week stretch between goal changes cannot support a weekly
    rate."""
    from app.services.fitness import longitudinal

    alice, _ = two_athletes
    today = date.today()
    start = today - timedelta(days=100)
    _goal_window(pg, alice, "cut", start, start + timedelta(days=10))
    _goal_window(pg, alice, "gain", start + timedelta(days=10), None)

    periods = longitudinal.comparable_periods(pg, alice, start, today)
    assert [one.goal_kind for one in periods] == ["gain"]


@requires_pg
def test_a_period_summary_qualifies_every_number(pg, two_athletes):
    """Over a year most of these are partly missing, and a bare float
    cannot tell a rate from 40 weigh-ins from one from 6."""
    from app.services.fitness import longitudinal

    alice, _ = two_athletes
    today = date.today()
    start = today - timedelta(days=90)
    _goal_window(pg, alice, "cut", start, None)
    _year_of_weigh_ins(pg, alice, start=start, days=60,
                       first_kg=86.0, last_kg=82.0)

    periods = longitudinal.comparable_periods(pg, alice, start, today)
    summary = longitudinal.summarise_period(pg, alice, periods[0])

    assert summary.weight_change.value is not None
    assert summary.weight_change.value < 0
    assert summary.weight_change.observed_days == 60
    assert summary.weight_change.expected_days == 90
    assert summary.weight_rate_weekly.value is not None
    # Nutrition and sleep were never logged: absent, not zero.
    assert summary.calorie_mean.value is None
    assert summary.calorie_mean.unavailable_reason is not None
    assert summary.sleep_mean.value is None
    # And coverage is the weakest stream, not the average — a period with
    # 90% weigh-ins and no food logs cannot support a nutrition claim.
    assert summary.coverage_ratio == 0.0
    assert summary.coverage.value == "sparse"


@requires_pg
def test_periods_with_different_goals_are_not_compared(pg, two_athletes):
    """The `not_compared` list is the result, not an apology."""
    from app.services.fitness import longitudinal

    alice, _ = two_athletes
    today = date.today()
    start = today - timedelta(days=240)
    middle = today - timedelta(days=120)
    _goal_window(pg, alice, "cut", start, middle)
    _goal_window(pg, alice, "gain", middle, None)
    _year_of_weigh_ins(pg, alice, start=start, days=239,
                       first_kg=86.0, last_kg=90.0)

    result = longitudinal.compare(pg, alice, start, today)
    assert result.comparisons == []
    assert result.not_compared
    assert "different goals" in result.not_compared[0]
    assert "two experiments" in result.not_compared[0]


@requires_pg
def test_sparse_periods_are_summarised_but_not_compared(pg, two_athletes):
    """A claim from 30% coverage is a claim about the 30%, and comparing two
    of those is a claim about neither."""
    from app.services.fitness import longitudinal

    alice, _ = two_athletes
    today = date.today()
    start = today - timedelta(days=200)
    middle = today - timedelta(days=100)
    _goal_window(pg, alice, "cut", start, middle)
    _goal_window(pg, alice, "cut", middle, None)
    # Ten weigh-ins across 200 days.
    _year_of_weigh_ins(pg, alice, start=start, days=10,
                       first_kg=86.0, last_kg=85.0)

    result = longitudinal.compare(pg, alice, start, today)
    assert len(result.periods) == 2
    assert result.comparisons == []
    assert any("coverage" in one for one in result.not_compared)


@requires_pg
def test_the_module_fits_no_correlations(pg, two_athletes):
    """§30.1: "do not fit unexplained multi-year correlations". There is no
    function here that takes two series and returns an r value, and this is
    the check that keeps one from appearing."""
    import ast as ast_module

    from app.services.fitness import longitudinal

    tree = ast_module.parse(open(longitudinal.__file__).read())
    for node in ast_module.walk(tree):
        if isinstance(node, (ast_module.ClassDef, ast_module.FunctionDef,
                             ast_module.AsyncFunctionDef, ast_module.Module)):
            body = node.body
            if (body and isinstance(body[0], ast_module.Expr)
                    and isinstance(body[0].value, ast_module.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast_module.Pass()]
    code = ast_module.unparse(ast_module.fix_missing_locations(tree))
    for forbidden in ("pearson", "spearman", "corrcoef", "linregress",
                      "polyfit", "r_squared", "np.corr"):
        assert forbidden not in code, forbidden


@requires_pg
def test_an_oversized_span_is_refused(pg, two_athletes):
    """The bound is what keeps a malformed date range from scanning
    everything."""
    from app.services.fitness import longitudinal
    from app.services.fitness.data_access import FitnessDataError

    alice, _ = two_athletes
    with pytest.raises(FitnessDataError):
        longitudinal.comparable_periods(
            pg, alice, date(2015, 1, 1), date.today(),
        )


@requires_pg
def test_a_comparison_carries_its_caveat(pg, two_athletes):
    """The number above it invites exactly the mistake the caveat names."""
    from app.services.fitness import longitudinal

    alice, _ = two_athletes
    today = date.today()
    start = today - timedelta(days=200)
    middle = today - timedelta(days=100)
    _goal_window(pg, alice, "cut", start, middle)
    _goal_window(pg, alice, "cut", middle, None)
    _year_of_weigh_ins(pg, alice, start=start, days=200,
                       first_kg=90.0, last_kg=84.0)
    for offset in range(200):
        day = start + timedelta(days=offset)
        pg.execute(text("""
            INSERT INTO food_log (
                id, user_id, meal_type, food_items, calories, protein,
                carbs, fats, logged_at, created_at
            ) VALUES (
                :id, :u, 'lunch', '["meal"]', 2200, 170, 200, 70,
                :logged, NOW()
            )
        """), {
            "id": str(uuid.uuid4()), "u": alice,
            "logged": datetime.combine(day, datetime.min.time())
            + timedelta(hours=13),
        })
        pg.execute(text("""
            INSERT INTO daily_recovery_log (
                id, user_id, log_date, sleep_hours, created_at
            ) VALUES (:id, :u, :day, 7.5, NOW())
        """), {"id": str(uuid.uuid4()), "u": alice, "day": day})
    pg.commit()

    result = longitudinal.compare(pg, alice, start, today)
    assert result.comparisons, result.not_compared
    comparison = result.comparisons[0]
    assert "not a cause" in comparison["caveat"]
    assert comparison["goal_kind"] == "cut"
    assert comparison["deltas"]["calorie_mean"]["delta"] is not None


# ─────────────────────────────────────────────────────────────────────────
# Privacy: export and deletion over a long history
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_an_export_covers_the_subsystem_and_says_what_it_kept(
    pg, two_athletes,
):
    """The plan's "privacy export/deletion with multi-year history"."""
    from app.services.fitness import privacy

    alice, _ = two_athletes
    _coverage(pg, alice, days=14)
    _year_of_weigh_ins(
        pg, alice, start=date.today() - timedelta(days=700), days=120,
        first_kg=95.0, last_kg=84.0,
    )

    result = privacy.export_fitness_data(pg, alice)
    assert result.user_id == alice
    assert result.counts.get("food_log") == 14
    assert result.counts.get("health_metric", 0) >= 120
    # A partial export presented as complete is worse than a failed one.
    assert result.unreadable == []
    assert result.complete is True


@requires_pg
def test_an_export_names_what_it_truncated(pg, two_athletes):
    """An export that silently stopped at the bound would tell somebody
    their four-year history is four months long."""
    from app.services.fitness import privacy

    alice, _ = two_athletes
    _coverage(pg, alice, days=20)
    result = privacy.export_fitness_data(pg, alice, page=5)
    assert "food_log" in result.truncated
    assert result.counts["food_log"] == 5
    assert result.complete is False


@requires_pg
def test_an_export_is_owner_scoped(pg, two_athletes):
    from app.services.fitness import privacy

    alice, bob = two_athletes
    _coverage(pg, alice, days=5)
    result = privacy.export_fitness_data(pg, bob)
    assert result.counts.get("food_log", 0) == 0
    for rows in result.tables.values():
        for row in rows:
            assert row.get("user_id") in (None, bob)


@requires_pg
def test_deletion_needs_the_athletes_own_id(pg, two_athletes):
    """A stray `true` from a mis-parsed request deletes a training history,
    and the id is the one value a caller cannot supply by accident."""
    from app.services.fitness import privacy
    from app.services.fitness.data_access import FitnessDataError

    alice, bob = two_athletes
    _coverage(pg, alice, days=3)
    for bad in ("true", "yes", bob, ""):
        with pytest.raises(FitnessDataError):
            privacy.delete_fitness_data(pg, alice, confirm=bad)
    assert pg.execute(text("""
        SELECT COUNT(*) FROM food_log WHERE user_id = :u
    """), {"u": alice}).scalar() == 3


@requires_pg
def test_deletion_removes_the_subsystem_and_keeps_the_health_authority(
    pg, two_athletes,
):
    """`health_metric` is the authority for body numbers across the whole
    system, and emptying it from a fitness-scoped call would take the health
    history with it. So it is kept, and the result says so."""
    from app.services.fitness import automation, privacy

    alice, bob = two_athletes
    _coverage(pg, alice, days=10)
    _coverage(pg, bob, days=4)
    automation.grant_policy(pg, alice, _policy_in(), approved_by=alice)

    result = privacy.delete_fitness_data(pg, alice, confirm=alice)
    assert result.complete, result.failed
    assert result.deleted.get("food_log") == 10
    assert result.deleted.get("fitness_automation_policy") == 1
    assert "health_metric" in result.kept_tables

    assert pg.execute(text("""
        SELECT COUNT(*) FROM food_log WHERE user_id = :u
    """), {"u": alice}).scalar() == 0
    assert pg.execute(text("""
        SELECT COUNT(*) FROM health_metric WHERE user_id = :u
    """), {"u": alice}).scalar() == 10
    # And the other athlete is untouched.
    assert pg.execute(text("""
        SELECT COUNT(*) FROM food_log WHERE user_id = :u
    """), {"u": bob}).scalar() == 4


@requires_pg
def test_deletion_of_a_multi_year_history_is_one_transaction(pg, two_athletes):
    """A half-deleted athlete is worse than an undeleted one, because the
    half that remains is unreachable from the half that is gone."""
    from app.services.fitness import privacy

    alice, _ = two_athletes
    for year_offset in (700, 400, 100):
        _coverage_at(pg, alice, start=date.today() - timedelta(days=year_offset))

    before = pg.execute(text("""
        SELECT COUNT(*) FROM food_log WHERE user_id = :u
    """), {"u": alice}).scalar()
    assert before == 30

    result = privacy.delete_fitness_data(pg, alice, confirm=alice)
    assert result.complete
    assert result.deleted["food_log"] == 30
    assert pg.execute(text("""
        SELECT COUNT(*) FROM food_log WHERE user_id = :u
    """), {"u": alice}).scalar() == 0


def _coverage_at(pg, user_id, *, start, days=10):
    for offset in range(days):
        day = start + timedelta(days=offset)
        pg.execute(text("""
            INSERT INTO food_log (
                id, user_id, meal_type, food_items, calories, protein,
                carbs, fats, logged_at, created_at
            ) VALUES (
                :id, :u, 'lunch', '["meal"]', 2100, 160, 190, 65,
                :logged, NOW()
            )
        """), {
            "id": str(uuid.uuid4()), "u": user_id,
            "logged": datetime.combine(day, datetime.min.time())
            + timedelta(hours=13),
        })
    pg.commit()


@requires_pg
def test_deletion_reports_photo_bytes_it_could_not_remove(
    pg, two_athletes, monkeypatch,
):
    """"Deleted" while the file is still in storage is the one message this
    must not send — the same rule the progress-photo delete follows."""
    from app.services.fitness import photos, privacy

    alice, _ = two_athletes
    photo_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO progress_photo (
            id, user_id, storage_key, mime_type, taken_at, created_at
        ) VALUES (:id, :u, 'key-1', 'image/jpeg', NOW(), NOW())
    """), {"id": photo_id, "u": alice})
    pg.commit()

    monkeypatch.setattr(
        photos, "delete_photo",
        lambda db, uid, pid: {
            "deleted": False, "cleanup_state": "pending_cleanup",
            "message": "the bytes are still in storage",
        },
    )
    result = privacy.delete_fitness_data(pg, alice, confirm=alice)
    assert result.pending_cleanup == 1
    assert result.complete is False
