#!/usr/bin/env python3
"""One real call to the local background model, against the real draft prompt.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 29.2 produces a program draft from a
model and Step 29.3 validates it in code. The 80 tests in
`tests/test_fitness_programming_pg.py` cover the validator thoroughly with a
stubbed model — including prose instead of JSON and an invented field — but a
stub cannot catch:

* `enable_thinking` in the wrong place in the payload (Qwen returns an empty
  `content` and every draft fails with "the model returned nothing");
* a draft schema the model simply will not hold — `ProgramDraftV1` is far
  larger than the review output, with four levels of nesting and a set list
  per exercise, and `extra="forbid"` all the way down;
* `MAX_OUTPUT_TOKENS` too small for a four-week block, which truncates the
  JSON mid-object so it parses as nothing;
* a validator rule that is wrong in a way only real output reveals. This is
  not hypothetical: the Step 20 live run was refused by our own safety gate
  for the phrase "take a deload", because `TREATMENT_TERMS` held the bare
  substring "take a".

It talks to the model and NOTHING else: no database, no draft row, no
athlete. The constraints, the exercise list and the performance history are
synthetic and hand-written here, so a failure is unambiguously about
transport, about the model's ability to hold the contract, or about a
validator rule — not about fixture data.

`_known_exercises` is patched to the same synthetic library the prompt
offers, which is what lets the real `validate_draft` run its whole
length — equipment, limitations, duration, volume, intensity, rep ranges,
load units and the beginner-default check — against genuine model output.

    python backend/scripts/fitness_draft_smoke.py
    python backend/scripts/fitness_draft_smoke.py --repeat 3 --verbose

Exit 0 means the transport works and the model produced a draft that passes
the real validator with nothing blocking. Exit 1 means it did not, and the
reason is printed. Needs host networking to reach the Mac Studio lane; the
disposable test network deliberately cannot.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

UTC = timezone.utc


#: The library the prompt offers and the validator checks against. Equipment
#: is on each one because the equipment rule is the one most likely to fire
#: on real output: a model reaching for a leg press the athlete does not own
#: is exactly the mistake §29.3 asks the validator to catch.
SYNTHETIC_LIBRARY = {
    "Barbell Bench Press": ["barbell", "bench"],
    "Incline Barbell Bench Press": ["barbell", "bench"],
    "Barbell Back Squat": ["barbell", "rack"],
    "Barbell Deadlift": ["barbell"],
    "Barbell Row": ["barbell"],
    "Overhead Press": ["barbell", "rack"],
    "Dumbbell Bench Press": ["dumbbells", "bench"],
    "Dumbbell Row": ["dumbbells", "bench"],
    "Dumbbell Lateral Raise": ["dumbbells"],
    "Dumbbell Curl": ["dumbbells"],
    "Romanian Deadlift": ["barbell"],
    "Bulgarian Split Squat": ["dumbbells", "bench"],
    "Lat Pulldown": ["cables"],
    "Cable Row": ["cables"],
    "Cable Triceps Pushdown": ["cables"],
    "Cable Face Pull": ["cables"],
    "Leg Extension": ["leg extension machine"],
    "Hanging Leg Raise": ["pull-up bar"],
    "Plank": [],
    # Deliberately present with equipment the athlete does NOT have, so the
    # offered list and the validator can disagree if the model picks it.
    "Leg Press": ["leg press machine"],
}

#: What the athlete has. `leg press machine` and `leg extension machine` are
#: absent on purpose.
EQUIPMENT = ["barbell", "rack", "bench", "dumbbells", "cables", "pull-up bar"]

#: `exercise_library.injury_contraindications`, as the real table carries
#: them. Kept at module level rather than inside the patched library so the
#: offered list and the validator read the SAME source — which is the whole
#: lesson of the 2026-10-02 runs: production's `allowed_exercises` withholds
#: these, and a script that offered them would hand the model a landmine and
#: then blame it for stepping on one.
CONTRAINDICATED = {
    "Barbell Bench Press": ["shoulder"],
    "Overhead Press": ["shoulder"],
}


def limited_areas(constraints) -> set:
    """Areas with an active limitation, as `allowed_exercises` computes
    them. One definition, used by the offered list and the library patch."""
    return {
        one["area"] for one in constraints.limitations if one.get("area")
    }


def synthetic_constraints():
    """An experienced lifter with a real limitation.

    Advanced with six years logged, because §29.3's beginner-default check
    only fires for somebody the history says is not a novice — and that
    check is one of the two things most worth testing against live output
    (the other being equipment). A shoulder limitation is included because
    a model asked to respect one is also a model that might explain it,
    which §29.3 forbids.
    """
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.programming import AthleteConstraints

    return AthleteConstraints(
        equipment=set(EQUIPMENT),
        available_days={"monday", "wednesday", "friday"},
        preferred_minutes=75,
        training_level="advanced",
        experience_years=6.0,
        logged_sessions=412,
        limitations=[{
            "area": "shoulder",
            # The athlete's own words. Passed through unaltered and not to
            # be interpreted — the prompt says so and this checks it.
            "description": "left shoulder complains on heavy flat pressing",
            "excluded_ids": set(),
            "modified_ids": set(),
            "severity": "moderate",
        }],
        excluded_exercise_ids=set(),
        goals=[
            "add 10kg to the bench without losing the squat",
            "keep the shoulder quiet",
        ],
        weight_unit=Unit.LB,
    )


def synthetic_performance():
    """Deterministic recent performance, as `performance_summary` renders it.

    §29.2 gives the model computed numbers rather than a log to read. These
    are the shape it produces: top and mean load in kilograms, min reps,
    set count and a mean RPE per session.
    """
    return {
        "Barbell Bench Press": [
            {"date": "2026-09-29", "top_load": 107.5, "mean_load": 102.5,
             "unit": "kg", "min_reps": 5, "sets": 4, "mean_rpe": 8.5},
            {"date": "2026-09-22", "top_load": 105.0, "mean_load": 100.0,
             "unit": "kg", "min_reps": 6, "sets": 4, "mean_rpe": 8.0},
        ],
        "Barbell Back Squat": [
            {"date": "2026-09-27", "top_load": 160.0, "mean_load": 150.0,
             "unit": "kg", "min_reps": 5, "sets": 5, "mean_rpe": 8.5},
        ],
        "Barbell Row": [
            {"date": "2026-09-29", "top_load": 95.0, "mean_load": 90.0,
             "unit": "kg", "min_reps": 8, "sets": 4, "mean_rpe": 7.5},
        ],
        "Overhead Press": [
            {"date": "2026-09-25", "top_load": 65.0, "mean_load": 62.5,
             "unit": "kg", "min_reps": 6, "sets": 3, "mean_rpe": 8.0},
        ],
    }


def patch_library(programming, constraints):
    """Point `_known_exercises` at the synthetic library.

    The only patch in this script. Without it `validate_draft` would mark
    every exercise unknown and the run would prove nothing about the model.
    With it, the whole validator runs: a name the model invented is still
    unknown, and equipment it does not have still fires.
    """
    def known(db, user_id, names):
        found = {}
        for name in names or []:
            key = str(name).strip().lower()
            for real, equipment in SYNTHETIC_LIBRARY.items():
                if real.strip().lower() == key:
                    found[key] = {
                        "id": f"lib-{real.replace(' ', '-').lower()}",
                        "name": real,
                        "normalized_name": real.lower(),
                        "equipment_required": equipment,
                        # The shoulder contraindication, so the limitation
                        # rule has something real to match on.
                        "injury_contraindications": CONTRAINDICATED.get(
                            real, []
                        ),
                        "load_convention": "total",
                    }
        return found

    programming._known_exercises = known


async def one_run(
    verbose: bool, *, request: str, timeout: float, max_tokens: int,
) -> tuple[bool, str]:
    from app.prompts import fitness_program_draft as prompts
    from app.schemas.fitness_coach import DraftBlockKind
    from app.services.fitness import programming

    constraints = synthetic_constraints()
    patch_library(programming, constraints)

    payload = programming.constraints_payload(constraints)
    # Filtered the way `allowed_exercises` filters, which is the whole
    # point: production never offers an exercise whose equipment the
    # athlete lacks, so a run that offered all twenty would blame the model
    # for picking something it was handed. The 2026-10-02 run did exactly
    # that and reported a BLOCKING equipment finding that was this
    # script's fault.
    offered = sorted(
        name for name, equipment in SYNTHETIC_LIBRARY.items()
        if not (set(equipment) - set(EQUIPMENT))
        and not (set(CONTRAINDICATED.get(name, [])) & limited_areas(constraints))
    )
    user_prompt = prompts.build_user_prompt(
        payload, offered,
        performance=synthetic_performance(),
        request=request,
    )

    started = time.monotonic()
    try:
        content, model = await programming._chat(
            prompts.SYSTEM_PROMPT, user_prompt,
            timeout=timeout, max_tokens=max_tokens,
        )
    except programming.TruncatedDraft as exc:
        return False, (
            f"OUTPUT CAP: {exc}\n"
            f"prompt was {len(user_prompt)} chars (~{len(user_prompt) // 4} tok)"
        )
    except Exception as exc:
        return False, (
            f"transport failed ({type(exc).__name__}): {exc}"
            + (
                f"\n  (the wait was {timeout:.0f}s; one week measured 197s "
                f"on 2026-10-02, so a timeout here means the ask is bigger "
                f"than one week or the lane is slower than it was)"
                if isinstance(exc, asyncio.TimeoutError) else ""
            )
        )
    elapsed = time.monotonic() - started

    if not content:
        return False, (
            f"model={model} {elapsed:.1f}s — EMPTY content. This is the "
            f"`enable_thinking` payload shape (§9): it must be nested in "
            f"`chat_template_kwargs`, not top level."
        )

    draft, errors = programming._parse_draft(content, DraftBlockKind.BLOCK)
    repaired = False
    if draft is None:
        print(f"    first attempt rejected: {'; '.join(errors)[:300]}")
        print("    spending the one repair turn...")
        repair_started = time.monotonic()
        content, repair_model = await programming._chat(
            prompts.SYSTEM_PROMPT,
            user_prompt + "\n\n" + prompts.build_repair_prompt(errors),
            timeout=timeout, max_tokens=max_tokens,
        )
        elapsed += time.monotonic() - repair_started
        model = repair_model or model
        draft, repair_errors = programming._parse_draft(
            content, DraftBlockKind.BLOCK,
        )
        repaired = True
        if draft is None:
            return False, (
                f"model={model} {elapsed:.1f}s — did not hold the schema in "
                f"two attempts.\nfirst:  {'; '.join(errors)[:400]}\n"
                f"repair: {'; '.join(repair_errors)[:400]}\n"
                f"raw (first 600): {content[:600]}"
            )

    # The real validator, with the real constraints.
    validation = programming.validate_draft(None, "smoke-athlete", draft,
                                            constraints)

    if verbose:
        print(json.dumps(draft.model_dump(mode="json"), indent=2))

    sessions = sum(len(week.sessions) for week in draft.weeks)
    slots = sum(
        len(session.slots) for week in draft.weeks
        for session in week.sessions
    )
    minutes = [
        session.estimated_minutes()
        for week in draft.weeks for session in week.sessions
    ]
    lines = [
        f"model={model} {elapsed:.1f}s"
        + ("  (took the repair turn)" if repaired else ""),
        # Sizing evidence. ~4 chars per token is close enough to choose
        # MAX_OUTPUT_TOKENS from, and guessing is what put it at 3600.
        f"prompt {len(user_prompt)} chars (~{len(user_prompt) // 4} tok), "
        f"output {len(content)} chars (~{len(content) // 4} tok) "
        f"of a {max_tokens} cap",
        f"kind={draft.kind.value} weeks={len(draft.weeks)} "
        f"sessions={sessions} slots={slots} "
        f"working_sets={sum(w.working_sets for w in draft.weeks)}",
        f"session minutes: {[round(m) for m in minutes]}",
        f"title: {draft.title}",
        f"goals addressed: {draft.addresses_goals}",
    ]
    if draft.questions:
        lines.append("asked: " + "; ".join(draft.questions))
    if draft.limitations_respected:
        lines.append("limitations: " + "; ".join(draft.limitations_respected))

    blocking = validation.blocking
    questions = validation.questions
    if blocking:
        lines.append(f"BLOCKING ({len(blocking)}):")
        lines += [f"  [{one.code.value}] {one.message}" for one in blocking]
    advisory = [
        one for one in validation.findings
        if not one.blocking and one not in questions
    ]
    if advisory:
        lines.append(f"advisory ({len(advisory)}):")
        lines += [f"  [{one.code.value}] {one.message}" for one in advisory]
    if questions:
        lines.append(f"questions ({len(questions)}):")
        lines += [f"  {one.message}" for one in questions]

    # No bespoke diagnosis list here any more. The first version of this
    # script carried one and immediately made the mistake `safety` had
    # already learned: it flagged "rotator cuff health" as a diagnosis,
    # where `DIAGNOSIS_TERMS` holds "rotator cuff tear" — the condition —
    # and leaves the anatomy alone. A smoke script that re-implements the
    # control it is testing tests the re-implementation.
    #
    # `validate_draft` now runs `safety.check_text` over the draft's prose,
    # so a language violation arrives above as a DIAGNOSTIC_LANGUAGE
    # finding like any other.

    return not blocking, "\n".join(lines)


def programming_defaults() -> tuple[float, int]:
    """Production's timeout and output cap, so a plain run measures what
    production would actually do."""
    from app.prompts import fitness_program_draft as prompts
    from app.services.fitness import programming

    return programming.DRAFT_TIMEOUT_SECONDS, prompts.MAX_OUTPUT_TOKENS


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=1,
                        help="runs; >1 checks the model holds the schema "
                             "repeatedly, not just once by luck")
    parser.add_argument("--verbose", action="store_true",
                        help="print the full parsed draft")
    parser.add_argument("--request", default=(
        "Draft the next four-week upper/lower block. Bench has stalled at "
        "107.5kg for three weeks."
    ), help="the ask, so one week and four weeks can be compared")
    parser.add_argument("--timeout", type=float, default=None,
                        help="override DRAFT_TIMEOUT_SECONDS, for measuring")
    parser.add_argument("--max-tokens", type=int, default=None,
                        help="override MAX_OUTPUT_TOKENS, for measuring")
    args = parser.parse_args()

    from app.prompts import fitness_program_draft as prompts

    areas = limited_areas(synthetic_constraints())
    withheld = sorted(
        name for name, equipment in SYNTHETIC_LIBRARY.items()
        if (set(equipment) - set(EQUIPMENT))
        or (set(CONTRAINDICATED.get(name, [])) & areas)
    )
    print(
        f"prompt: {prompts.PROMPT_VERSION} "
        f"(max_tokens={prompts.MAX_OUTPUT_TOKENS}, "
        f"temperature={prompts.TEMPERATURE}, "
        f"timeout={programming_defaults()[0]:.0f}s)\n"
        f"offered {len(SYNTHETIC_LIBRARY) - len(withheld)} of "
        f"{len(SYNTHETIC_LIBRARY)} exercises; equipment filter withheld "
        f"{withheld}"
    )

    passes = 0
    for attempt in range(1, args.repeat + 1):
        ok, message = await one_run(
            args.verbose, request=args.request,
            timeout=args.timeout or programming_defaults()[0],
            max_tokens=args.max_tokens or programming_defaults()[1],
        )
        print(f"\n--- run {attempt}/{args.repeat}: "
              f"{'PASS' if ok else 'FAIL'} ---\n{message}")
        passes += int(ok)

    print(f"\n{passes}/{args.repeat} runs passed")
    return 0 if passes == args.repeat else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
