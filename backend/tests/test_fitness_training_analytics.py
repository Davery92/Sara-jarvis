"""Step 16 of FITNESS_COACH_IMPLEMENTATION_PLAN: training analytics, against
hand-derived fixtures.

The claims that take the most care, each of which would otherwise produce a
confidently wrong number that drives a programming decision:

* **Two-a-days are two sessions; one bout's planned and active rows are
  one.** Counting the rows gives three sessions for one workout.
* **A top set is a working set.** `set_role` is a role, not a `set_kind`,
  and treating it as a kind would stop a top set counting toward the target.
* **Tonnage only sums comparable loads.** Adding assisted pull-up
  "weight" inverts the meaning — more assistance is less work.
* **Primary and secondary muscle sets are never added.** A bench press is
  not three chest sets and three triceps sets of equal weight.
* **"No recorded improvement" over two exposures is not a plateau**, and
  only the plateau justifies adding volume.
* **Epley is not applied above ten reps**, so a set of twenty cannot claim
  a one-rep max.
"""
from datetime import date, timedelta

import pytest

from app.schemas.fitness_coach import Quality, Unavailable, Unit
from app.services.fitness.analytics import (
    EPLEY_FORMULA_VERSION,
    MIN_EXPOSURES_FOR_TREND,
    MIN_SPAN_DAYS_FOR_TREND,
    SessionRecord,
    SetRecord,
    epley_1rm,
    estimated_1rm_metric,
    exercise_frequency,
    strength_trend,
    training_metrics,
    window,
)

AS_OF = date(2026, 10, 1)


def days_before(n: int) -> date:
    return AS_OF - timedelta(days=n)


def session(offset, status="completed", planned=True, sets=0, key=None):
    return SessionRecord(
        key=key or f"s-{offset}-{status}",
        day=days_before(offset), status=status,
        was_planned=planned, completed_sets=sets,
    )


def a_set(
    offset, *, reps=5, load=225.0, kind="working", role=None, voided=False,
    skipped=False, comparable=True, unit=Unit.LB, exercise="Bench Press",
    exercise_id="ex-bench", primary=("chest",), secondary=("triceps",),
    effort=None, effort_scale=None, session_key="s-1", set_id=None,
):
    return SetRecord(
        set_id=set_id or f"set-{offset}-{kind}-{load}-{reps}",
        day=days_before(offset),
        exercise_id=exercise_id, exercise_name=exercise,
        occurrence_id=None, session_key=session_key,
        reps=reps, load=load, load_unit=unit,
        set_kind=kind, set_role=role,
        counts_toward_target=(kind == "working"),
        voided=voided, skipped=skipped,
        effort=effort, effort_scale=effort_scale,
        load_comparable=comparable,
        primary_muscles=primary, secondary_muscles=secondary,
    )


# ── Session counting ──────────────────────────────────────────────────────

def test_a_two_a_day_counts_as_two_sessions():
    """Two bouts on one day are two bouts.

    Deduplicating by date would lose the PM session entirely — which is the
    one-template-per-weekday failure, in a different place.
    """
    sessions = [
        session(2, key="morning"),
        session(2, key="evening"),
        session(1, key="next-day"),
    ]
    group = training_metrics(sessions, [], AS_OF)
    assert group.metrics["sessions_completed"].value == 3.0


def test_skipped_and_in_progress_are_not_completed():
    """In progress is not skipped, and neither is completed.

    Collapsing them would either credit an unfinished workout or write off
    one still being done.
    """
    sessions = [
        session(4, status="completed"),
        session(3, status="skipped"),
        session(2, status="in_progress"),
    ]
    group = training_metrics(sessions, [], AS_OF)
    assert group.metrics["sessions_completed"].value == 1.0
    assert group.metrics["sessions_skipped"].value == 1.0
    assert group.metrics["sessions_in_progress"].value == 1.0
    assert "not the same as skipped" in (
        group.metrics["sessions_in_progress"].note or ""
    )


def test_adherence_is_unavailable_without_a_recorded_prescription():
    """Using today's templates would let a template edit change last week's
    adherence — the same class of error target revisions exist to prevent."""
    group = training_metrics([session(3)], [], AS_OF)
    adherence = group.metrics["session_adherence"]
    assert adherence.value is None
    assert adherence.unavailable_reason is Unavailable.NO_DATA
    assert "never recorded" in (adherence.note or "")
    assert "today's" in (adherence.note or "")


def test_adherence_uses_the_snapshot_denominator():
    sessions = [session(5), session(3), session(1)]
    group = training_metrics(sessions, [], AS_OF, planned_from_snapshot=4)
    adherence = group.metrics["session_adherence"]
    assert adherence.value == pytest.approx(3 / 4)
    assert "3 of 4 prescribed" in (adherence.note or "")


def test_nothing_prescribed_is_not_zero_adherence():
    """Zero out of zero is not a failure; it is not applicable."""
    group = training_metrics([], [], AS_OF, planned_from_snapshot=0)
    adherence = group.metrics["session_adherence"]
    assert adherence.value is None
    assert adherence.unavailable_reason is Unavailable.NOT_APPLICABLE


def test_sessions_outside_the_window_are_ignored():
    sessions = [session(3), session(40)]
    group = training_metrics(sessions, [], AS_OF)
    assert group.metrics["sessions_completed"].value == 1.0


# ── Set counting ──────────────────────────────────────────────────────────

def test_a_top_set_is_a_working_set_and_counts():
    """`set_role` is a role OF a working set.

    Treating it as a kind would make a top set stop counting toward the
    prescribed target — a real regression dressed as better modelling.
    """
    sets = [
        a_set(3, role="top", load=245.0, reps=3),
        a_set(3, role="backoff", load=215.0, reps=8, set_id="backoff-1"),
        a_set(3, role="amrap", load=215.0, reps=12, set_id="amrap-1"),
    ]
    group = training_metrics([], sets, AS_OF)
    assert group.metrics["working_sets"].value == 3.0
    assert "roles of a working set" in (group.metrics["working_sets"].note or "")


def test_warmups_and_drops_are_counted_separately_from_working_sets():
    sets = [
        a_set(3, kind="working"),
        a_set(3, kind="warmup", load=135.0, reps=10, set_id="warm-1"),
        a_set(3, kind="warmup", load=185.0, reps=5, set_id="warm-2"),
        a_set(3, kind="drop", load=185.0, reps=5, set_id="drop-1"),
    ]
    group = training_metrics([], sets, AS_OF)
    assert group.metrics["working_sets"].value == 1.0
    assert group.metrics["warmup_sets"].value == 2.0
    assert group.metrics["drop_segments"].value == 1.0
    assert "never counted toward a prescribed target" in (
        group.metrics["warmup_sets"].note or ""
    )


def test_voided_and_skipped_sets_are_excluded():
    sets = [
        a_set(3),
        a_set(3, voided=True, set_id="voided-1"),
        a_set(3, skipped=True, set_id="skipped-1"),
    ]
    group = training_metrics([], sets, AS_OF)
    assert group.metrics["working_sets"].value == 1.0


# ── Tonnage ───────────────────────────────────────────────────────────────

def test_tonnage_is_load_times_reps_summed():
    sets = [
        a_set(3, load=225.0, reps=5),
        a_set(3, load=225.0, reps=4, set_id="s2"),
        a_set(2, load=230.0, reps=5, set_id="s3"),
    ]
    expected = 225 * 5 + 225 * 4 + 230 * 5
    group = training_metrics([], sets, AS_OF)
    tonnage = group.metrics["tonnage"]
    assert tonnage.value == pytest.approx(expected)
    assert tonnage.unit is Unit.LB


def test_a_non_comparable_load_is_excluded_from_tonnage():
    """Adding assisted pull-up "weight" inverts the meaning.

    More assistance is less work, so a bigger number would mean an easier
    set and tonnage would reward getting weaker.
    """
    sets = [
        a_set(3, load=225.0, reps=5),
        a_set(3, load=40.0, reps=10, comparable=False,
              exercise="Assisted Pull Up", exercise_id="ex-pullup", set_id="assisted"),
    ]
    group = training_metrics([], sets, AS_OF)
    tonnage = group.metrics["tonnage"]
    assert tonnage.value == pytest.approx(225 * 5)
    assert "1 excluded" in (tonnage.note or "")
    assert Quality.PARTIAL_DAY in tonnage.quality_flags


def test_tonnage_says_it_is_not_a_hypertrophy_dose():
    """Equal tonnage can be very different work, and the number invites
    being read as a training dose if nothing says otherwise."""
    group = training_metrics([], [a_set(3)], AS_OF)
    assert "Not a hypertrophy dose" in (group.metrics["tonnage"].note or "")


def test_no_comparable_sets_at_all_gives_no_tonnage():
    sets = [
        a_set(3, load=0.0, reps=10, comparable=False,
              exercise="Push Up", exercise_id="ex-pushup"),
    ]
    group = training_metrics([], sets, AS_OF)
    tonnage = group.metrics["tonnage"]
    assert tonnage.value is None
    assert tonnage.unavailable_reason is Unavailable.NOT_COMPARABLE
    assert "assisted, bodyweight, machine-stack" in (tonnage.note or "")


def test_mixed_units_block_tonnage():
    sets = [
        a_set(3, load=100.0, reps=5, unit=Unit.KG),
        a_set(3, load=225.0, reps=5, unit=Unit.LB, set_id="lb-set"),
    ]
    group = training_metrics([], sets, AS_OF)
    assert group.metrics["tonnage"].unavailable_reason is Unavailable.NOT_COMPARABLE


# ── Muscle exposure ───────────────────────────────────────────────────────

def test_primary_and_secondary_sets_are_never_added_together():
    """A bench press trains the chest directly and the triceps indirectly.

    Three bench sets are three chest sets, not three chest plus three
    triceps sets of equal weight — adding them overstates both.
    """
    sets = [
        a_set(3, primary=("chest",), secondary=("triceps", "front_delt")),
        a_set(3, primary=("chest",), secondary=("triceps", "front_delt"), set_id="s2"),
        a_set(3, primary=("chest",), secondary=("triceps", "front_delt"), set_id="s3"),
    ]
    group = training_metrics([], sets, AS_OF)
    assert group.metrics["direct_sets_chest"].value == 3.0
    assert group.metrics["secondary_sets_triceps"].value == 3.0
    assert group.metrics["secondary_sets_front_delt"].value == 3.0
    # Two distinct metrics, never one sum.
    assert "direct_sets_triceps" not in group.metrics
    assert "overstate every one of them" in (
        group.metrics["secondary_sets_triceps"].note or ""
    )


def test_a_set_with_no_classification_is_unclassified_not_attributed():
    """A guess here would invent muscle volume for a muscle never trained."""
    sets = [
        a_set(3, primary=("chest",), secondary=()),
        a_set(3, primary=(), secondary=(), exercise="Mystery Machine",
              exercise_id="ex-mystery", set_id="unclassified-1"),
    ]
    group = training_metrics([], sets, AS_OF)
    assert group.metrics["direct_sets_chest"].value == 1.0
    assert group.metrics["unclassified_sets"].value == 1.0
    assert "would invent muscle volume" in (
        group.metrics["unclassified_sets"].note or ""
    )


def test_warmups_do_not_inflate_muscle_exposure():
    sets = [
        a_set(3, kind="working", primary=("chest",)),
        a_set(3, kind="warmup", primary=("chest",), set_id="warm"),
        a_set(3, kind="drop", primary=("chest",), set_id="drop"),
    ]
    group = training_metrics([], sets, AS_OF)
    assert group.metrics["direct_sets_chest"].value == 1.0


# ── Epley ─────────────────────────────────────────────────────────────────

def test_epley_at_one_rep_returns_the_performed_load():
    """A true single IS the maximum.

    Applying the formula would inflate it by 3.3% and report a max the
    athlete never lifted.
    """
    assert epley_1rm(315.0, 1) == 315.0


def test_epley_is_the_stated_formula():
    assert epley_1rm(100.0, 5) == pytest.approx(100 * (1 + 5 / 30))
    assert epley_1rm(225.0, 8) == pytest.approx(225 * (1 + 8 / 30))
    assert epley_1rm(225.0, 10) == pytest.approx(225 * (1 + 10 / 30))


def test_epley_refuses_above_ten_reps():
    """A set of twenty cannot claim a one-rep max.

    The formula's error grows past the point where the number supports a
    decision, and reporting it anyway would put a fabricated max on a chart.
    """
    assert epley_1rm(135.0, 11) is None
    assert epley_1rm(135.0, 20) is None
    assert epley_1rm(135.0, 0) is None


def test_epley_refuses_a_non_positive_load():
    assert epley_1rm(0.0, 5) is None
    assert epley_1rm(-10.0, 5) is None


def test_the_e1rm_metric_picks_the_best_eligible_set():
    period = window(AS_OF, 28)
    sets = [
        a_set(10, load=225.0, reps=5),            # 262.5
        a_set(5, load=245.0, reps=3, set_id="s2"),  # 269.5
        a_set(2, load=315.0, reps=1, set_id="s3"),  # 315 exact
    ]
    metric = estimated_1rm_metric(sets, period, exercise_name="Bench Press")
    assert metric.value == pytest.approx(315.0)
    assert metric.formula == EPLEY_FORMULA_VERSION
    assert "actual single" in (metric.note or "")


def test_a_multi_rep_best_is_labelled_an_estimate():
    period = window(AS_OF, 28)
    sets = [a_set(5, load=245.0, reps=3)]
    metric = estimated_1rm_metric(sets, period, exercise_name="Bench Press")
    assert metric.value == pytest.approx(245 * (1 + 3 / 30))
    assert "ESTIMATE" in (metric.note or "")
    assert "not a tested max" in (metric.note or "")


def test_ineligible_sets_cannot_produce_an_e1rm():
    period = window(AS_OF, 28)
    sets = [
        a_set(3, kind="warmup", load=135.0, reps=10),
        a_set(3, kind="drop", load=185.0, reps=5, set_id="drop"),
        a_set(3, voided=True, load=405.0, reps=5, set_id="voided"),
        a_set(3, load=135.0, reps=20, set_id="high-rep"),
        a_set(3, load=40.0, reps=8, comparable=False, set_id="assisted"),
    ]
    metric = estimated_1rm_metric(sets, period, exercise_name="Bench Press")
    assert metric.value is None
    assert metric.unavailable_reason is Unavailable.INSUFFICIENT_COVERAGE
    assert "live working set" in (metric.note or "")


# ── Strength trend ────────────────────────────────────────────────────────

def test_two_exposures_are_not_a_plateau():
    """The distinction that decides whether volume gets added.

    "No recorded improvement" over two sessions and "a genuine plateau" are
    different claims, and only the second justifies changing a program.
    """
    sets = [
        a_set(20, load=225.0, reps=5),
        a_set(3, load=225.0, reps=5, set_id="s2"),
    ]
    trend = strength_trend(sets, AS_OF, exercise_name="Bench Press")
    assert trend.value is None
    assert trend.unavailable_reason is Unavailable.INSUFFICIENT_COVERAGE
    assert "NOT a plateau" in (trend.note or "")
    assert str(MIN_EXPOSURES_FOR_TREND) in (trend.note or "")


def test_three_exposures_in_four_days_are_not_a_trend():
    sets = [
        a_set(5, load=225.0, reps=5),
        a_set(3, load=230.0, reps=5, set_id="s2"),
        a_set(2, load=235.0, reps=5, set_id="s3"),
    ]
    trend = strength_trend(sets, AS_OF, exercise_name="Bench Press")
    assert trend.value is None
    assert str(MIN_SPAN_DAYS_FOR_TREND) in (trend.note or "")
    assert "before a direction means anything" in (trend.note or "")


def test_a_real_trend_reports_its_change_and_its_basis():
    sets = [
        a_set(25, load=225.0, reps=5),             # 262.5
        a_set(15, load=235.0, reps=5, set_id="s2"),  # 274.17
        a_set(5, load=245.0, reps=5, set_id="s3"),   # 285.83
    ]
    trend = strength_trend(sets, AS_OF, exercise_name="Bench Press")
    expected = 245 * (1 + 5 / 30) - 225 * (1 + 5 / 30)
    assert trend.value == pytest.approx(expected)
    assert "3 exposures over 20 days" in (trend.note or "")
    assert "rep-range noise" in (trend.note or "")


def test_several_sets_on_one_day_are_one_exposure():
    """Three sets in a session is one data point for a trend.

    Counting sets would let a single session satisfy the exposure threshold
    and produce a "trend" from one day.
    """
    sets = [
        a_set(3, load=225.0, reps=5, set_id="s1"),
        a_set(3, load=225.0, reps=4, set_id="s2"),
        a_set(3, load=225.0, reps=3, set_id="s3"),
    ]
    trend = strength_trend(sets, AS_OF, exercise_name="Bench Press")
    assert trend.value is None
    assert "1 comparable exposures" in (trend.note or "")


def test_the_best_set_of_each_day_is_the_days_value():
    sets = [
        a_set(25, load=225.0, reps=5, set_id="a1"),
        a_set(25, load=200.0, reps=5, set_id="a2"),   # worse, same day
        a_set(15, load=235.0, reps=5, set_id="b1"),
        a_set(5, load=245.0, reps=5, set_id="c1"),
    ]
    trend = strength_trend(sets, AS_OF, exercise_name="Bench Press")
    expected = 245 * (1 + 5 / 30) - 225 * (1 + 5 / 30)
    assert trend.value == pytest.approx(expected)


# ── Frequency ─────────────────────────────────────────────────────────────

def test_frequency_counts_days_not_sets():
    sets = [
        a_set(10, set_id="a1"), a_set(10, set_id="a2"), a_set(10, set_id="a3"),
        a_set(3, set_id="b1"),
    ]
    frequency = exercise_frequency(sets, AS_OF)
    assert frequency["frequency_ex-bench"].value == 2.0
    assert "days, not sets" in (frequency["frequency_ex-bench"].note or "")


def test_frequency_is_per_exercise():
    sets = [
        a_set(5, exercise="Bench Press", exercise_id="ex-bench"),
        a_set(3, exercise="Barbell Row", exercise_id="ex-row", set_id="row-1"),
        a_set(1, exercise="Barbell Row", exercise_id="ex-row", set_id="row-2"),
    ]
    frequency = exercise_frequency(sets, AS_OF)
    assert frequency["frequency_ex-bench"].value == 1.0
    assert frequency["frequency_ex-row"].value == 2.0


def test_frequency_falls_back_to_the_name_for_an_unresolved_exercise():
    """So an unresolved identity is still counted, under the name it was
    logged with rather than merged into some other lift."""
    sets = [a_set(3, exercise="Odd Machine", exercise_id=None)]
    frequency = exercise_frequency(sets, AS_OF)
    assert frequency["frequency_Odd Machine"].value == 1.0


# ── Data quality ──────────────────────────────────────────────────────────

def test_data_quality_collects_every_unavailable_reason():
    """So "what would help?" is answerable from the state alone."""
    from app.services.fitness.analytics import (
        DailyValue, data_quality, nutrition_metrics, weight_metrics,
    )

    weight = weight_metrics([DailyValue(day=days_before(1), value=81.0,
                                        unit=Unit.KG)], AS_OF)
    nutrition = nutrition_metrics([], AS_OF)
    quality = data_quality(weight_group=weight, nutrition_group=nutrition)

    assert quality.observed_weight_days == 1
    assert quality.expected_weight_days == 7
    assert quality.nutrition_complete_days == 0
    assert quality.nutrition_unknown_days == 7
    assert any("weight.velocity_weekly" in field for field in quality.missing_fields)
    assert any("insufficient_coverage" in field for field in quality.missing_fields)


def test_overdue_cadences_come_from_the_athletes_own_preferences():
    """Nothing is overdue because this module thinks it should be measured."""
    from app.services.fitness.analytics import data_quality
    assert data_quality().overdue_cadences == []
    assert data_quality(overdue_cadences=["tape measurements"]).overdue_cadences \
        == ["tape measurements"]


def test_data_quality_carries_group_limitations_through():
    from app.services.fitness.analytics import DailyValue, data_quality, weight_metrics

    values = [DailyValue(day=days_before(n), value=81.0, unit=Unit.KG)
              for n in range(1, 28)]
    weight = weight_metrics(values, AS_OF, goal_rate_per_week=-0.4,
                            goal_changed_on=days_before(10))
    quality = data_quality(weight_group=weight)
    assert any("goal changed" in note for note in quality.notes)


def test_coverage_is_separate_from_any_confidence_claim():
    """A review can be confident and wrong for exactly the reason that the
    coverage is thin, so the two are never one field."""
    from app.schemas.fitness_coach import DataQuality
    fields = set(DataQuality.model_fields)
    assert "confidence" not in fields
    assert "model_confidence" not in fields
    assert "observed_weight_days" in fields
    assert "expected_weight_days" in fields


# ── Determinism ───────────────────────────────────────────────────────────

def test_training_metrics_do_not_depend_on_input_order():
    sessions = [session(5), session(3), session(1)]
    sets = [a_set(5, set_id="a"), a_set(3, set_id="b"), a_set(1, set_id="c")]
    forward = training_metrics(sessions, sets, AS_OF, planned_from_snapshot=4)
    backward = training_metrics(
        list(reversed(sessions)), list(reversed(sets)), AS_OF,
        planned_from_snapshot=4,
    )
    assert set(forward.metrics) == set(backward.metrics)
    for key in forward.metrics:
        assert forward.metrics[key].value == backward.metrics[key].value, key


def test_every_training_metric_names_its_formula():
    group = training_metrics([session(3)], [a_set(3)], AS_OF,
                             planned_from_snapshot=4)
    for key, metric in group.metrics.items():
        assert metric.formula, f"{key} does not name its formula"
        assert metric.analytics_version >= 1
