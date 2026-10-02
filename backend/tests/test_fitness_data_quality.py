"""Step 16 of FITNESS_COACH_IMPLEMENTATION_PLAN: data quality is an
independent output, not a footnote on another number.

Why it has to be independent (§9.6): a review can be very confident about a
conclusion drawn from two days of data, and be wrong for exactly that
reason. Coverage confidence and model confidence answer different questions,
so folding them into one field makes it impossible to see which is doing the
work.

And the second rule: **every unavailable metric says why**, so "what would
help?" is answerable from the state alone rather than needing someone to
work it out from an empty chart.
"""
from datetime import date, timedelta

import pytest

from app.schemas.fitness_coach import DataQuality, Unavailable, Unit
from app.services.fitness.analytics import (
    DailyValue,
    NutritionDay,
    SessionRecord,
    SetRecord,
    SleepNight,
    data_quality,
    nutrition_metrics,
    sleep_metrics,
    training_metrics,
    weight_metrics,
)

AS_OF = date(2026, 10, 1)


def days_before(n: int) -> date:
    return AS_OF - timedelta(days=n)


# ── Independence from confidence ──────────────────────────────────────────

def test_coverage_and_confidence_are_never_the_same_field():
    """A confident conclusion from thin data is the failure mode.

    If coverage were a confidence score, a review could not report "I am
    fairly sure, and there is almost no data" — which is the one combination
    a reader most needs to see.
    """
    fields = set(DataQuality.model_fields)
    for forbidden in ("confidence", "model_confidence", "certainty", "score"):
        assert forbidden not in fields, (
            f"{forbidden} belongs to the model's interpretation, not to coverage"
        )
    # What coverage does carry: counts and reasons.
    assert {
        "observed_weight_days", "expected_weight_days", "sleep_nights",
        "nutrition_complete_days", "nutrition_partial_days",
        "nutrition_unknown_days", "missing_fields",
    } <= fields


def test_an_empty_quality_report_claims_nothing():
    quality = data_quality()
    assert quality.observed_weight_days is None
    assert quality.expected_weight_days is None
    assert quality.sleep_nights is None
    assert quality.nutrition_complete_days == 0
    assert quality.missing_fields == []
    assert quality.overdue_cadences == []
    assert quality.stale_profile is False
    assert quality.no_effective_target is False


# ── Counts come from the groups themselves ────────────────────────────────

def test_weight_coverage_is_observed_over_expected():
    weight = weight_metrics(
        [DailyValue(day=days_before(n), value=81.0, unit=Unit.KG)
         for n in (6, 4, 2)],
        AS_OF,
    )
    quality = data_quality(weight_group=weight)
    assert quality.observed_weight_days == 3
    assert quality.expected_weight_days == 7


def test_the_three_nutrition_counts_are_reported_separately():
    """Unknown is not partial and partial is not complete.

    Collapsing them would make a week with one confirmed day look the same
    as a week with seven.
    """
    days = [
        NutritionDay(day=days_before(6), calories=3000, protein_g=200,
                     carbs_g=None, fat_g=None, status="complete", meal_count=3),
        NutritionDay(day=days_before(5), calories=3100, protein_g=210,
                     carbs_g=None, fat_g=None, status="complete", meal_count=3),
        NutritionDay(day=days_before(4), calories=900, protein_g=60,
                     carbs_g=None, fat_g=None, status="partial", meal_count=1),
    ]
    quality = data_quality(nutrition_group=nutrition_metrics(days, AS_OF))
    assert quality.nutrition_complete_days == 2
    assert quality.nutrition_partial_days == 1
    assert quality.nutrition_unknown_days == 4
    assert (
        quality.nutrition_complete_days
        + quality.nutrition_partial_days
        + quality.nutrition_unknown_days
    ) == 7


def test_sleep_nights_are_counted():
    nights = [SleepNight(day=days_before(n), hours=7.5) for n in (6, 5, 3)]
    quality = data_quality(sleep_group=sleep_metrics(nights, AS_OF))
    assert quality.sleep_nights == 3


# ── Every absence explains itself ─────────────────────────────────────────

def test_each_unavailable_metric_contributes_its_reason():
    """So "what would help?" is answerable from the state alone.

    An empty chart with no explanation leaves the athlete to guess whether
    Sara is broken, whether she needs more data, or whether nothing changed.
    """
    weight = weight_metrics(
        [DailyValue(day=days_before(1), value=81.0, unit=Unit.KG)], AS_OF,
    )
    quality = data_quality(weight_group=weight)

    reasons = {field.split(": ")[-1] for field in quality.missing_fields}
    assert Unavailable.INSUFFICIENT_COVERAGE.value in reasons

    named = {field.split(":")[0] for field in quality.missing_fields}
    assert "weight.velocity_weekly" in named
    assert "weight.trend_slope_weekly" in named
    # The one metric that IS available is not listed as missing.
    assert not any("weight.latest" in field for field in quality.missing_fields)


def test_no_data_and_insufficient_coverage_are_distinguished():
    """"Nothing recorded" and "not enough recorded" lead to different asks:
    start logging, versus keep logging."""
    nothing = data_quality(weight_group=weight_metrics([], AS_OF))
    assert any(
        Unavailable.NO_DATA.value in field for field in nothing.missing_fields
    )

    some = data_quality(weight_group=weight_metrics(
        [DailyValue(day=days_before(n), value=81.0, unit=Unit.KG) for n in (3, 1)],
        AS_OF,
    ))
    assert any(
        Unavailable.INSUFFICIENT_COVERAGE.value in field
        for field in some.missing_fields
    )


def test_a_missing_target_is_reported_as_no_target_not_as_no_data():
    """The fix is different: record a target, rather than log more food."""
    days = [
        NutritionDay(day=days_before(n), calories=3000, protein_g=200,
                     carbs_g=None, fat_g=None, status="complete", meal_count=3)
        for n in (6, 5, 4)
    ]
    quality = data_quality(nutrition_group=nutrition_metrics(days, AS_OF))
    adherence = [
        field for field in quality.missing_fields
        if "calorie_adherence" in field
    ]
    assert adherence
    assert Unavailable.NO_TARGET.value in adherence[0]


def test_group_limitations_are_carried_into_the_quality_notes():
    """A limitation is a caveat on the whole group, not on one metric, so it
    has nowhere else to go."""
    values = [DailyValue(day=days_before(n), value=81.0, unit=Unit.KG)
              for n in range(1, 28)]
    weight = weight_metrics(
        values, AS_OF, goal_rate_per_week=-0.4, goal_changed_on=days_before(10),
    )
    quality = data_quality(weight_group=weight)
    assert any("goal changed" in note for note in quality.notes)


# ── Overdue is the athlete's own setting ──────────────────────────────────

def test_nothing_is_overdue_unless_the_athlete_asked_for_it():
    """This module does not decide what should be measured.

    An athlete who never opted into tape measurements is not behind on them,
    and telling them otherwise is a nag for something they declined.
    """
    assert data_quality().overdue_cadences == []
    assert data_quality(overdue_cadences=[]).overdue_cadences == []
    opted_in = data_quality(overdue_cadences=["tape measurements", "photos"])
    assert opted_in.overdue_cadences == ["tape measurements", "photos"]


# ── Unresolved identities and conflicts ───────────────────────────────────

def test_unresolved_units_and_identities_are_counted_not_hidden():
    """Both are reasons a number might be wrong, and a reader deserves to
    know how many rows the caveat covers."""
    quality = data_quality(
        unresolved_units=4,
        unresolved_exercise_identities=11,
        source_conflicts=2,
        incomplete_workouts=1,
    )
    assert quality.unresolved_units == 4
    assert quality.unresolved_exercise_identities == 11
    assert quality.source_conflicts == 2
    assert quality.incomplete_workouts == 1


def test_insufficient_exposures_names_the_lifts():
    """"Not enough data" is actionable only if it says for what."""
    quality = data_quality(
        insufficient_exposures=["Bench Press", "Barbell Row"],
    )
    assert quality.insufficient_comparable_exposures == [
        "Bench Press", "Barbell Row",
    ]


def test_a_stale_profile_and_a_missing_target_are_separate_flags():
    """One means "tell me about yourself", the other "set a target". Folding
    them into one would make the prompt wrong half the time."""
    quality = data_quality(stale_profile=True, no_effective_target=False)
    assert quality.stale_profile is True
    assert quality.no_effective_target is False


# ── Training coverage ─────────────────────────────────────────────────────

def test_an_unavailable_session_adherence_appears_as_a_missing_field():
    training = training_metrics([
        SessionRecord(key="s1", day=days_before(3), status="completed",
                      was_planned=True),
    ], [], AS_OF)
    quality = data_quality(training_group=training)
    assert any(
        "session_adherence" in field for field in quality.missing_fields
    )


def test_a_full_week_reports_full_coverage_and_no_gaps_for_weight():
    weight = weight_metrics(
        [DailyValue(day=days_before(n), value=81.0 - n * 0.05, unit=Unit.KG)
         for n in range(1, 15)],
        AS_OF,
    )
    quality = data_quality(weight_group=weight)
    assert quality.observed_weight_days == 7
    assert quality.expected_weight_days == 7
    # The 7-day mean and the velocity are both available with a full
    # fortnight, so neither is listed as missing.
    assert not any("weight.mean_7d" in f for f in quality.missing_fields)
    assert not any("weight.velocity_weekly" in f for f in quality.missing_fields)


# ── Composition ───────────────────────────────────────────────────────────

def test_all_four_groups_compose_into_one_report():
    weight = weight_metrics(
        [DailyValue(day=days_before(n), value=81.0, unit=Unit.KG) for n in (6, 4, 2)],
        AS_OF,
    )
    nutrition = nutrition_metrics([
        NutritionDay(day=days_before(n), calories=3000, protein_g=200,
                     carbs_g=None, fat_g=None, status="complete", meal_count=3)
        for n in (6, 5, 4)
    ], AS_OF)
    sleep = sleep_metrics(
        [SleepNight(day=days_before(n), hours=7.5) for n in (6, 5, 4)], AS_OF,
    )
    training = training_metrics(
        [SessionRecord(key="s1", day=days_before(3), status="completed",
                       was_planned=True)],
        [SetRecord(
            set_id="x", day=days_before(3), exercise_id="ex", exercise_name="Bench",
            occurrence_id=None, session_key="s1", reps=5, load=225.0,
            load_unit=Unit.LB, set_kind="working",
        )],
        AS_OF, planned_from_snapshot=4,
    )

    quality = data_quality(
        weight_group=weight, nutrition_group=nutrition,
        sleep_group=sleep, training_group=training,
    )
    assert quality.observed_weight_days == 3
    assert quality.nutrition_complete_days == 3
    assert quality.sleep_nights == 3
    # Fields from more than one section are present, each namespaced so a
    # reader can tell which surface is short of data.
    sections = {field.split(".")[0] for field in quality.missing_fields}
    assert len(sections) >= 2
