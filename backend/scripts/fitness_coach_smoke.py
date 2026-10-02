#!/usr/bin/env python3
"""One real call to the local background model, against the real prompt.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 20's gate:

    "one real isolated local-model smoke test validates transport/output;
     mock-only JSON tests cannot prove deployed capability."

That is exactly right, and the reasons are concrete. A stubbed test cannot
catch:

* `enable_thinking` in the wrong place in the payload — Qwen returns an empty
  `content` and every review fails with "no parseable content";
* speculative decoding corrupting a structured reply (the MTP gotcha);
* a context window too small for the state, which truncates silently so the
  model reasons from a partial state while the stored snapshot shows the
  whole one;
* a model that simply will not hold this schema, which is a prompt problem
  no amount of validation fixes.

It talks to the model and NOTHING else: no database, no review row, no
athlete. The state is synthetic and hand-written here, so a failure is
unambiguously about transport or about the model's ability to follow the
contract.

    python backend/scripts/fitness_coach_smoke.py
    python backend/scripts/fitness_coach_smoke.py --repeat 3

Exit 0 means the transport works and the model produced output that passes
the real validator. Exit 1 means it did not, and the reason is printed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

UTC = timezone.utc


def synthetic_state():
    """A plausible week. Hand-written so a failure is about the model.

    Deliberately includes an UNAVAILABLE metric and a pain item: those are
    the two things a model most wants to paper over, and a smoke test that
    only offered clean numbers would pass while the real thing failed.
    """
    from app.schemas.fitness_coach import (
        AthleteGoalOut, DataQuality, DayType, FitnessStateV1, GoalKind,
        Metric, MetricGroup, Period, RateBasis, ResolvedTargets,
        StateSection, TargetProvenance, TargetValues, Unavailable, Unit,
    )

    end = date(2026, 9, 28)
    return FitnessStateV1(
        user_id="smoke-athlete",
        as_of=datetime(2026, 9, 28, 12, 0, tzinfo=UTC),
        athlete_local_date=end,
        timezone="America/New_York",
        period=Period(start=end - timedelta(days=7), end=end),
        goals=[AthleteGoalOut(
            id="g1", user_id="smoke-athlete",
            recorded_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
            kind=GoalKind.CUT, is_primary=True,
            rate_basis=RateBasis.ABSOLUTE, target_rate_kg_week=-0.4,
            valid_from=date(2026, 9, 1),
        )],
        targets=ResolvedTargets(
            user_id="smoke-athlete", on_date=end - timedelta(days=1),
            day_type=DayType.TRAINING,
            values=TargetValues(calories=3000, protein_g=200),
            provenance=TargetProvenance.APPROVED_REVISION, revision_id="rev-1",
        ),
        sections={
            StateSection.WEIGHT: MetricGroup(
                section=StateSection.WEIGHT,
                metrics={
                    "latest": Metric(
                        key="weight.latest", value=81.2, unit=Unit.KG,
                        observed_days=1, expected_days=1,
                        note="measured 2026-09-27",
                    ),
                    "mean_7d": Metric(
                        key="weight.mean_7d", value=81.35, unit=Unit.KG,
                        observed_days=6, expected_days=7,
                    ),
                    "mean_prev_7d": Metric(
                        key="weight.mean_prev_7d", value=81.5, unit=Unit.KG,
                        observed_days=5, expected_days=7,
                    ),
                    "velocity_weekly": Metric(
                        key="weight.velocity_weekly", value=-0.15,
                        unit=Unit.KG_PER_WEEK, observed_days=6, expected_days=7,
                    ),
                    # Unavailable on purpose: the model must not invent it.
                    "trend_slope_weekly": Metric(
                        key="weight.trend_slope_weekly", unit=Unit.KG_PER_WEEK,
                        unavailable_reason=Unavailable.INSUFFICIENT_COVERAGE,
                        observed_days=6, expected_days=28,
                        note="a 28-day slope needs readings across the window",
                    ),
                },
            ),
            StateSection.NUTRITION: MetricGroup(
                section=StateSection.NUTRITION,
                metrics={
                    "calories_mean": Metric(
                        key="nutrition.calories_mean", value=3180,
                        unit=Unit.KCAL, observed_days=5, expected_days=7,
                    ),
                    "protein_mean": Metric(
                        key="nutrition.protein_mean", value=186, unit=Unit.GRAM,
                        observed_days=5, expected_days=7,
                    ),
                    "complete_days": Metric(
                        key="nutrition.complete_days", value=5, unit=Unit.COUNT,
                    ),
                },
            ),
            StateSection.SLEEP: MetricGroup(
                section=StateSection.SLEEP,
                metrics={
                    "mean_hours": Metric(
                        key="sleep.mean_hours", value=6.4, unit=Unit.HOUR,
                        observed_days=6, expected_days=7,
                    ),
                    "nights_observed": Metric(
                        key="sleep.nights_observed", value=6, unit=Unit.COUNT,
                    ),
                },
            ),
            StateSection.TRAINING: MetricGroup(
                section=StateSection.TRAINING,
                metrics={
                    "sessions_completed": Metric(
                        key="training.sessions_completed", value=3,
                        unit=Unit.COUNT,
                    ),
                    "working_sets": Metric(
                        key="training.working_sets", value=58, unit=Unit.COUNT,
                    ),
                    "session_adherence": Metric(
                        key="training.session_adherence", value=0.75,
                        unit=Unit.PERCENT, observed_days=7, expected_days=7,
                    ),
                },
            ),
            StateSection.PAIN: MetricGroup(
                section=StateSection.PAIN,
                items=[{
                    "exercise": "Barbell Curl",
                    "exercise_library_id": "ex-1",
                    "sessions_with_pain": 2,
                    "sessions_with_report": 3,
                    "sessions_total": 3,
                    "max_severity": 4,
                    "locations": ["elbow"],
                    "sides": ["right"],
                }],
                limitations=[
                    "Pain is what the athlete reported, not a diagnosis."
                ],
            ),
        },
        quality=DataQuality(
            observed_weight_days=6, expected_weight_days=7,
            sleep_nights=6, nutrition_complete_days=5,
            nutrition_partial_days=1, nutrition_unknown_days=1,
            missing_fields=[
                "weight.trend_slope_weekly: insufficient_coverage",
            ],
        ),
    )


async def one_run(state, verbose: bool) -> tuple[bool, str]:
    from app.services.fitness import reviews, safety

    started = time.monotonic()
    try:
        parsed, model, errors = await reviews._call_and_parse(state)
    except Exception as exc:
        return False, f"transport failed: {type(exc).__name__}: {exc}"
    elapsed = time.monotonic() - started

    if parsed is None:
        return False, (
            f"model={model} produced nothing the schema accepts after one "
            f"repair: {'; '.join(errors)}"
        )

    report = safety.validate_output(parsed, state)
    if report.rejected:
        return False, (
            f"model={model} output was rejected by the safety gate: "
            + "; ".join(report.rejections)
        )

    output = report.output or parsed
    if verbose:
        print(json.dumps(output.model_dump(mode="json"), indent=2))
    lines = [
        f"model={model} {elapsed:.1f}s",
        f"confidence={output.confidence.value} ({output.confidence_basis})",
        f"observations={len(output.observations)} "
        f"recommendations={len(output.recommendations)} "
        f"limitations={len(output.limitations)}",
    ]
    if report.downgrades:
        lines.append("downgraded: " + "; ".join(report.downgrades))
    # The thing the smoke test is really checking beyond transport: did it
    # stay inside the state?
    cited = set(output.referenced_metric_paths())
    allowed = set(state.metric_paths())
    lines.append(
        f"cited {len(cited)} metric paths, all within the state: "
        f"{sorted(cited)}"
    )
    assert cited <= allowed
    if any("trend_slope" in path for path in cited):
        lines.append(
            "NOTE: it cited the unavailable 28-day slope — legal, since the "
            "path exists; check the text treats it as unknown."
        )
    return True, "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=1,
                        help="runs; >1 checks the model holds the schema "
                             "repeatedly, not just once by luck")
    parser.add_argument("--verbose", action="store_true",
                        help="print the full validated output")
    args = parser.parse_args()

    state = synthetic_state()
    print(
        f"prompt: {__import__('app.prompts.fitness_coach_review', fromlist=['x']).PROMPT_VERSION}\n"
        f"state: {len(state.metric_paths())} metric paths, "
        f"{len(json.dumps(state.model_dump(mode='json'), default=str))} bytes"
    )

    passes = 0
    for attempt in range(1, args.repeat + 1):
        ok, message = await one_run(state, args.verbose)
        print(f"\n--- run {attempt}/{args.repeat}: "
              f"{'PASS' if ok else 'FAIL'} ---\n{message}")
        passes += int(ok)

    print(f"\n{passes}/{args.repeat} runs passed")
    return 0 if passes == args.repeat else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
