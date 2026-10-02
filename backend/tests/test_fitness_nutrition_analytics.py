"""Step 15 of FITNESS_COACH_IMPLEMENTATION_PLAN: nutrition analytics, against
hand-derived fixtures.

The three claims that do the work:

1. **A day with nothing logged is unknown, not zero calories.** Averaging it
   as zero reports a deficit nobody ran, and a deficit is what drives a
   calorie recommendation.
2. **Only confirmed-complete days enter a mean.** A partially logged day's
   total is a lower bound, and averaging lower bounds understates intake —
   again in the direction that invents a deficit.
3. **Each day is compared against ITS OWN target.** Comparing a month of
   intake against today's target is not adherence; it is an artefact of when
   the target was last edited.
"""
from datetime import date, timedelta

import pytest

from app.schemas.fitness_coach import (
    DayType,
    ResolvedTargets,
    TargetProvenance,
    TargetScope,
    TargetValues,
    Unavailable,
    Unit,
)
from app.services.fitness.analytics import (
    MIN_COMPLETE_DAYS_FOR_NUTRITION,
    NutritionDay,
    nutrition_metrics,
)

AS_OF = date(2026, 10, 1)
ATHLETE = "athlete-nutrition"


def days_before(n: int) -> date:
    return AS_OF - timedelta(days=n)


def day(
    offset: int, *, calories=None, protein=None, carbs=None, fat=None,
    status="complete", meals=3, estimated=False,
) -> NutritionDay:
    return NutritionDay(
        day=days_before(offset),
        calories=calories, protein_g=protein, carbs_g=carbs, fat_g=fat,
        status=status, meal_count=meals, has_estimated_items=estimated,
    )


def target(
    offset: int, *, calories=3000, protein=200, tolerance=10.0,
    history_unknown=False,
) -> tuple[date, ResolvedTargets]:
    return days_before(offset), ResolvedTargets(
        user_id=ATHLETE,
        on_date=days_before(offset),
        day_type=DayType.TRAINING,
        values=TargetValues(
            calories=calories, protein_g=protein,
            calorie_tolerance_pct=tolerance, protein_tolerance_pct=tolerance,
        ),
        provenance=TargetProvenance.APPROVED_REVISION,
        scope=TargetScope.DEFAULT,
        phase_id=None, phase_name=None,
        revision_id="rev-1", revision_version=1,
        effective_from=days_before(60), effective_until=None,
        history_unknown=history_unknown,
    )


# ── Day classification ────────────────────────────────────────────────────

def test_a_day_with_nothing_logged_is_unknown_not_zero():
    """The arithmetic that would invent a deficit.

    Two complete days at 3000 kcal in a 7-day window. Averaging the other
    five as zero gives ~857 kcal/day, which reads as a catastrophic cut.
    """
    days = [day(6, calories=3000, protein=200),
            day(5, calories=3000, protein=200),
            day(4, calories=3000, protein=200)]
    group = nutrition_metrics(days, AS_OF)

    mean = group.metrics["calories_mean"]
    assert mean.value == pytest.approx(3000)
    assert mean.value != pytest.approx(3 * 3000 / 7)
    assert mean.observed_days == 3
    assert mean.expected_days == 7

    assert group.metrics["complete_days"].value == 3.0
    assert group.metrics["unknown_days"].value == 4.0
    assert "not days of zero intake" in (group.metrics["unknown_days"].note or "")


def test_a_partial_day_is_counted_separately_and_excluded_from_the_mean():
    """A partial day's total is a lower bound.

    Averaging lower bounds understates intake, in the direction that invents
    a deficit.
    """
    days = [
        day(6, calories=3000), day(5, calories=3100), day(4, calories=2900),
        day(3, calories=900, status="partial", meals=1),
    ]
    group = nutrition_metrics(days, AS_OF)
    assert group.metrics["calories_mean"].value == pytest.approx(
        (3000 + 3100 + 2900) / 3
    )
    assert group.metrics["complete_days"].value == 3.0
    assert group.metrics["partial_days"].value == 1.0
    # A day with a meal on it is not an unknown day.
    assert group.metrics["unknown_days"].value == 3.0


def test_the_three_day_counts_are_independent():
    days = [
        day(6, calories=3000),
        day(5, calories=1200, status="partial", meals=1),
        day(4, calories=None, status="unknown", meals=0),
    ]
    group = nutrition_metrics(days, AS_OF)
    assert group.metrics["complete_days"].value == 1.0
    assert group.metrics["partial_days"].value == 1.0
    # Offsets 1, 2, 3 and 4 had nothing logged (offset 4 has meal_count 0).
    assert group.metrics["unknown_days"].value == 5.0


def test_too_few_complete_days_gives_no_mean():
    days = [day(6, calories=3000), day(5, calories=3100)]
    group = nutrition_metrics(days, AS_OF)
    mean = group.metrics["calories_mean"]
    assert mean.value is None
    assert mean.unavailable_reason is Unavailable.INSUFFICIENT_COVERAGE
    assert str(MIN_COMPLETE_DAYS_FOR_NUTRITION) in (mean.note or "")


# ── Per-field denominators ────────────────────────────────────────────────

def test_each_macro_has_its_own_denominator():
    """A day can know its calories and not know its fat.

    Averaging fat over the calorie denominator understates it; averaging the
    missing ones as zero understates it worse.
    """
    days = [
        day(6, calories=3000, protein=200, fat=80),
        day(5, calories=3100, protein=210, fat=None),
        day(4, calories=2900, protein=190, fat=None),
        day(3, calories=3050, protein=None, fat=85),
    ]
    group = nutrition_metrics(days, AS_OF)

    assert group.metrics["calories_mean"].value == pytest.approx(
        (3000 + 3100 + 2900 + 3050) / 4
    )
    assert group.metrics["calories_mean"].observed_days == 4

    assert group.metrics["protein_g_mean"].value == pytest.approx(
        (200 + 210 + 190) / 3
    )
    assert group.metrics["protein_g_mean"].observed_days == 3

    # Only two days know fat, below the threshold — so no fat mean at all
    # rather than one built from two days or from zeros.
    fat = group.metrics["fat_g_mean"]
    assert fat.value is None
    assert fat.unavailable_reason is Unavailable.INSUFFICIENT_COVERAGE


def test_a_genuine_zero_is_a_value():
    """Someone who ate no carbs that day ate no carbs.

    It is not a missing reading, and excluding it would overstate the mean.
    """
    days = [
        day(6, calories=2000, carbs=0),
        day(5, calories=2100, carbs=0),
        day(4, calories=2050, carbs=20),
    ]
    group = nutrition_metrics(days, AS_OF)
    assert group.metrics["carbs_g_mean"].value == pytest.approx((0 + 0 + 20) / 3)
    assert group.metrics["carbs_g_mean"].observed_days == 3


def test_estimated_nutrition_is_declared_as_a_limitation():
    days = [
        day(6, calories=3000), day(5, calories=3100),
        day(4, calories=2900, estimated=True),
    ]
    group = nutrition_metrics(days, AS_OF)
    assert any("estimated nutrition" in note for note in group.limitations)


# ── Adherence ─────────────────────────────────────────────────────────────

def test_adherence_counts_days_within_the_targets_own_tolerance():
    """The tolerance comes from the target revision, not a constant.

    "Within 10%" is a versioned setting someone can inspect and change; a
    hard-coded one would be invisible.
    """
    days = [
        day(6, calories=3000, protein=200),   # exactly on target
        day(5, calories=3200, protein=200),   # +6.7%, inside 10%
        day(4, calories=3600, protein=200),   # +20%, outside
        day(3, calories=2800, protein=200),   # -6.7%, inside
    ]
    targets = dict(target(n) for n in (6, 5, 4, 3))
    group = nutrition_metrics(days, AS_OF, targets_by_day=targets)

    adherence = group.metrics["calorie_adherence"]
    assert adherence.value == pytest.approx(3 / 4)
    assert "3 of 4 eligible days" in (adherence.note or "")
    assert "7 calendar days" in (adherence.note or "")


def test_a_tighter_tolerance_changes_adherence():
    days = [day(n, calories=3200, protein=200) for n in (6, 5, 4)]
    loose = dict(target(n, tolerance=10.0) for n in (6, 5, 4))
    tight = dict(target(n, tolerance=5.0) for n in (6, 5, 4))

    # +6.7% is inside 10% and outside 5%.
    assert nutrition_metrics(days, AS_OF, targets_by_day=loose) \
        .metrics["calorie_adherence"].value == pytest.approx(1.0)
    assert nutrition_metrics(days, AS_OF, targets_by_day=tight) \
        .metrics["calorie_adherence"].value == pytest.approx(0.0)


def test_a_day_with_no_recorded_target_is_not_eligible_either_way():
    """It cannot be adherent or non-adherent to a target nobody set.

    Counting it as a miss would manufacture non-adherence; counting it as a
    hit would manufacture the opposite.
    """
    days = [day(n, calories=3000, protein=200) for n in (6, 5, 4, 3)]
    # Only three of the four days have a target.
    targets = dict(target(n) for n in (6, 5, 4))
    group = nutrition_metrics(days, AS_OF, targets_by_day=targets)
    adherence = group.metrics["calorie_adherence"]
    assert adherence.observed_days == 3, "the untargeted day is not in the denominator"
    assert adherence.value == pytest.approx(1.0)


def test_a_day_before_recorded_target_history_is_not_eligible():
    """`history_unknown` means the current values are not asserted to have
    applied then — so judging that day against them would be a fabrication."""
    days = [day(n, calories=3000, protein=200) for n in (6, 5, 4, 3)]
    targets = dict(
        [target(6, history_unknown=True), target(5), target(4), target(3)]
    )
    group = nutrition_metrics(days, AS_OF, targets_by_day=targets)
    assert group.metrics["calorie_adherence"].observed_days == 3


def test_no_targets_at_all_means_no_adherence_figure():
    days = [day(n, calories=3000) for n in (6, 5, 4)]
    group = nutrition_metrics(days, AS_OF)
    for key in ("calorie_adherence", "protein_adherence", "calorie_delta_mean"):
        metric = group.metrics[key]
        assert metric.value is None
        assert metric.unavailable_reason is Unavailable.NO_TARGET


def test_protein_adherence_is_one_sided():
    """Exceeding a protein target is not a miss.

    There is no clinical upper requirement this system is in a position to
    assert, and inventing one would mark a perfectly good day as
    non-adherent.
    """
    days = [
        day(6, calories=3000, protein=200),   # exactly on
        day(5, calories=3000, protein=260),   # well over — still a hit
        day(4, calories=3000, protein=150),   # under — a miss
    ]
    targets = dict(target(n, protein=200) for n in (6, 5, 4))
    group = nutrition_metrics(days, AS_OF, targets_by_day=targets)
    protein = group.metrics["protein_adherence"]
    assert protein.value == pytest.approx(2 / 3)
    assert "One-sided" in (protein.note or "")


# ── Calorie delta ─────────────────────────────────────────────────────────

def test_each_day_is_compared_against_its_own_target():
    """The target changed mid-window.

    Comparing all four days against the current 2600 would report a +300
    surplus for the two days whose target was 3000 — an artefact of when the
    target was edited, not a surplus anyone ate.
    """
    days = [day(n, calories=3000) for n in (6, 5, 4, 3)]
    targets = dict([
        target(6, calories=3000), target(5, calories=3000),
        target(4, calories=2600), target(3, calories=2600),
    ])
    group = nutrition_metrics(days, AS_OF, targets_by_day=targets)
    delta = group.metrics["calorie_delta_mean"]
    # (0 + 0 + 400 + 400) / 4
    assert delta.value == pytest.approx(200.0)
    assert delta.unit is Unit.KCAL
    assert "each day against its own target" in (delta.note or "")
    assert "2 different targets" in (delta.note or "")

    # Against the single current target it would have been 400 throughout.
    naive = dict(target(n, calories=2600) for n in (6, 5, 4, 3))
    naive_delta = nutrition_metrics(days, AS_OF, targets_by_day=naive) \
        .metrics["calorie_delta_mean"]
    assert naive_delta.value == pytest.approx(400.0)
    assert naive_delta.value != delta.value


def test_a_single_target_window_says_so():
    days = [day(n, calories=3100) for n in (6, 5, 4)]
    targets = dict(target(n, calories=3000) for n in (6, 5, 4))
    group = nutrition_metrics(days, AS_OF, targets_by_day=targets)
    delta = group.metrics["calorie_delta_mean"]
    assert delta.value == pytest.approx(100.0)
    assert "different targets" not in (delta.note or "")


def test_a_zero_target_is_handled_without_dividing_by_it():
    days = [day(n, calories=0, protein=0) for n in (6, 5, 4)]
    targets = dict(target(n, calories=0, protein=0) for n in (6, 5, 4))
    group = nutrition_metrics(days, AS_OF, targets_by_day=targets)
    # An intake of zero against a target of zero is adherent, and nothing
    # divides by the target.
    assert group.metrics["calorie_adherence"].value == pytest.approx(1.0)


# ── Window ────────────────────────────────────────────────────────────────

def test_the_as_of_day_is_excluded_from_the_window():
    """Today is not over.

    A partially logged current day would drag the mean down and read as a
    sudden cut.
    """
    days = [
        day(3, calories=3000), day(2, calories=3000), day(1, calories=3000),
        day(0, calories=400),   # today, one meal in
    ]
    group = nutrition_metrics(days, AS_OF)
    mean = group.metrics["calories_mean"]
    assert mean.value == pytest.approx(3000.0)
    assert mean.observed_days == 3


def test_a_longer_span_can_be_requested():
    days = [day(n, calories=3000) for n in range(1, 28)]
    group = nutrition_metrics(days, AS_OF, span=28)
    assert group.metrics["calories_mean"].expected_days == 28
    assert group.metrics["calories_mean"].observed_days == 27


def test_days_outside_the_window_are_ignored():
    days = [
        day(6, calories=3000), day(5, calories=3000), day(4, calories=3000),
        day(40, calories=1000),   # long before the window
    ]
    group = nutrition_metrics(days, AS_OF)
    assert group.metrics["calories_mean"].value == pytest.approx(3000.0)
    assert group.metrics["calories_mean"].observed_days == 3


# ── Determinism ───────────────────────────────────────────────────────────

def test_the_result_does_not_depend_on_input_order():
    days = [
        day(6, calories=3000, protein=200), day(5, calories=3100, protein=210),
        day(4, calories=2900, protein=190), day(3, calories=3050, protein=205),
    ]
    targets = dict(target(n) for n in (6, 5, 4, 3))
    forward = nutrition_metrics(days, AS_OF, targets_by_day=targets)
    backward = nutrition_metrics(list(reversed(days)), AS_OF, targets_by_day=targets)
    for key in forward.metrics:
        assert forward.metrics[key].value == backward.metrics[key].value, key


def test_every_metric_names_its_formula():
    days = [day(n, calories=3000, protein=200) for n in (6, 5, 4)]
    targets = dict(target(n) for n in (6, 5, 4))
    group = nutrition_metrics(days, AS_OF, targets_by_day=targets)
    for key, metric in group.metrics.items():
        assert metric.formula, f"{key} does not name its formula"
        assert metric.analytics_version >= 1
