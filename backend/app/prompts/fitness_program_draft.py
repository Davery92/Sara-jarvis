"""The program-draft prompt.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 29.2: "LLM outputs constrained
draft only, never writes activated templates."

What the prompt is responsible for, and what it is not. It is responsible
for producing JSON in one shape with exercises from one list. It is NOT
responsible for keeping that promise — `programming.validate_draft` checks
every constraint in code, and the schema rejects an unknown field. A prompt
rule is a request; the validator is the enforcement, and the two are kept
separate on purpose so a reader can see which is which.

The list of allowed exercise names is given explicitly rather than
described. A model asked to "use exercises the athlete has equipment for"
will invent plausible ones; a model given 60 names and told to pick from
them picks from them, and the validator catches the rest.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

PROMPT_VERSION = "fitness_program_draft_v1"
MAX_OUTPUT_TOKENS = 3600
TEMPERATURE = 0.3

SYSTEM_PROMPT = """You draft training programs for one athlete, as JSON, for a human to review.

You are drafting. Nothing you produce is applied: a person reads it, and either accepts it or does not. So the draft has to be inspectable — every session's exercises, sets, reps and effort targets written out, and a rationale that says what the plan is for.

Return ONLY a JSON object:

{
  "kind": "program" | "block" | "week",
  "title": "<short name for this plan>",
  "rationale": "<why this plan, for this athlete, now>",
  "addresses_goals": ["<the athlete's own goals this serves>"],
  "weeks": [
    {
      "program_week": <absolute program week, 1-based>,
      "block_week": <week within this block, optional>,
      "is_deload": false,
      "sessions": [
        {
          "name": "<session name, e.g. 'Upper A'>",
          "scheduled_days": ["monday"],
          "order_in_phase": 0,
          "slots": [
            {
              "order": 0,
              "exercise_name": "<EXACTLY as given in ALLOWED_EXERCISES>",
              "progression": "double_progression" | "linear" | "percentage" | "manual",
              "sets": [
                {
                  "index": 0,
                  "role": "warmup" | "top" | "backoff" | "working",
                  "metric": "reps",
                  "reps_low": 5, "reps_high": 8,
                  "effort": "rpe", "rpe": 8,
                  "rest_seconds": 180
                }
              ]
            }
          ]
        }
      ]
    }
  ],
  "questions": ["<what you could not decide without asking>"],
  "limitations_respected": ["<how the recorded limitations shaped this>"]
}

Rules, each of which is also checked in code:

1. **Only names from ALLOWED_EXERCISES.** Exactly as spelled. A name that is not on the list resolves to nothing, has no history to progress from, and no contraindications to check — so it is rejected, and whatever you built on it goes with it.
2. **Respect the recorded limitations, and do not interpret them.** The constraints say which exercises to avoid. Avoid them. Do not name a condition, offer a cause, or suggest a treatment: you are reading a list, not an MRI.
3. **Fit the equipment and the time on file.** A session whose own sets and rests add up past the stated preference is a session that will not happen.
4. **Ask instead of assuming.** If something you need is not in the constraints — a reference max for percentage work, which days are available, whether an injury still limits anything — put it in `questions`. A question costs a day. A guessed constraint costs the block.
5. **Program for the lifter on file.** If the constraints show years of training or hundreds of logged sessions, do not draft a novice plan: no plan where nothing goes above RPE 8 and nothing carries more than three working sets. That draft is rejected outright.
6. **A rep range is a range, an RPE is an effort target, and a percentage needs a reference.** Do not prescribe both a weight and a percentage for the same set.
7. **No nutrition, no calories, no body-composition claims.** This is a training draft. Targets are decided one at a time, elsewhere.

Every set is written out. Do not write "3x8" and leave the sets implied: three sets at eight reps is three entries, because the person reviewing this is checking the sets."""


ALLOWED_HEADER = (
    "ALLOWED_EXERCISES (the ONLY names you may use, exactly as spelled):"
)


def build_user_prompt(
    constraints: Dict[str, Any],
    allowed_exercises: List[str],
    *,
    performance: Optional[Dict[str, Any]] = None,
    evidence: Optional[List[Dict[str, Any]]] = None,
    request: Optional[str] = None,
) -> str:
    """The user turn: constraints, the name list, the data, the ask.

    `performance` is deterministic — recent loads and rep performance
    computed in code, not the model's reading of a workout log. §29.2: the
    draft rests on deterministic performance data, and a model asked to
    summarise its own inputs summarises them wrong.
    """
    sections: List[str] = [
        ALLOWED_HEADER + "\n" + json.dumps(sorted(allowed_exercises), indent=0),
        "CONSTRAINTS:\n" + json.dumps(constraints, indent=0, default=str),
    ]
    if performance:
        sections.append(
            "RECENT PERFORMANCE (computed, not your reading of a log):\n"
            + json.dumps(performance, indent=0, default=str)
        )
    if evidence:
        sections.append(
            "ACCEPTED EVIDENCE (the only research you may lean on; cite a "
            "chunk_id in evidence_refs):\n"
            + json.dumps(evidence, indent=0, default=str)
        )
    sections.append(
        "REQUEST: " + (request or "Draft the next training block.")
    )
    sections.append("Return the JSON object now. No prose, no fence.")
    return "\n\n".join(sections)


REPAIR_INSTRUCTION = """Your previous draft was rejected. Reasons:

{errors}

Return ONLY the corrected JSON object, same shape, no prose, no fence.

If a rejection was about an exercise name, replace it with one from ALLOWED_EXERCISES or drop the slot — do not rename it to something that sounds closer. If it was about a missing constraint, move it into `questions` rather than choosing a value: a draft with an open question is reviewable, and a draft built on a guess is not."""


def build_repair_prompt(errors: List[str]) -> str:
    return REPAIR_INSTRUCTION.format(
        errors="\n".join(f"- {one}" for one in errors[:10])
    )


def prompt_text() -> str:
    """Everything whose change should change the stored prompt hash."""
    return SYSTEM_PROMPT + "\n" + ALLOWED_HEADER + "\n" + REPAIR_INSTRUCTION
