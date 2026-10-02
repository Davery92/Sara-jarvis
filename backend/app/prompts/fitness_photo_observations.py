"""Prompts for structured photo observations. Versioned, because it is stored.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 27.

`PROMPT_VERSION` goes into every `fitness_photo_analysis` row and into its
idempotency key, so a prompt change produces a new analysis rather than
leaving a stored row naming instructions that no longer exist.

What these prompts exist to prevent, in order of how badly each one goes
wrong:

1. **A body-composition number.** A model asked anything about a physique
   photo will volunteer a body-fat percentage, because that is what the
   internet taught it the task is. From one photo, with no calipers, no scan
   and no scale, that number is invented — and it lands somewhere that reads
   like an observation, while `health_metric` (the actual authority) never
   sees it and cannot contradict it. The prompt forbids it, the schema has
   no field for it, and the validator rejects it in prose. Three layers,
   because the prompt alone has never been enough for this one.
2. **A confident comparison of two incomparable photos.** Lighting, pose and
   camera distance change an image far more than a fortnight of training
   does. `inconclusive` is the expected answer and the prompt says so, so
   the model is not reaching for a difference to justify its existence.
3. **A diagnosis.** "That shoulder sits low" is an observation. "That is a
   winged scapula" is a clinical claim from a photograph.

No persona. This is an analysis call, and a warm voice would make a weak
observation read as encouragement.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

#: Bump with any change below. Stored per analysis and part of the
#: idempotency key.
PROMPT_VERSION = "fitness_photo_observations_v1"

#: Output cap. These answers are three sentences and a handful of regions;
#: anything longer is a model filling space. `llama-server` keeps generating
#: after a non-streaming client disconnects, so the cap is not optional.
MAX_OUTPUT_TOKENS = 900

#: Low. Two runs over the same photo should not disagree about what is in it.
TEMPERATURE = 0.15


_SHARED_RULES = """ABSOLUTE RULES

1. Never state or estimate a body-fat percentage, a weight, a lean mass, a BMI, or any other number about this person's body. Not a range, not an approximation, not "around". A photograph cannot support one, and their real measurements are recorded elsewhere. An answer containing such a number is discarded entirely.
2. Never diagnose. "The left shoulder sits lower" is an observation. "That is a winged scapula" is a clinical claim from a photograph, and you are not making one.
3. Describe only what is visible. If the lighting, the pose, the clothing or the framing hides something, say so in `limitations` rather than guessing at it. "The midsection is in shadow" is one of the most useful sentences you can produce.
4. Image quality and your confidence are separate. A clear photo can still support only a weak statement, and a confident reading of a badly lit one is exactly what the two fields exist to keep visible as two facts.
5. Be specific and short. Two or three sentences of summary, and only the regions you can actually say something about. An empty `regions` list is a valid answer.
6. Return ONE JSON object. No prose before or after, no markdown fence."""


SINGLE_SYSTEM_PROMPT = f"""You describe what is visible in one physique progress photo. You are not talking to the person; you produce a structured observation a coach will read.

{_SHARED_RULES}

OUTPUT

{{
  "output_version": 1,
  "view": "front" | "side" | "back" | "other",
  "summary": "<2-3 sentences describing what is visible>",
  "regions": [
    {{"region": "<e.g. shoulders, upper back>",
      "observation": "<what is visible about it>",
      "confidence": "low" | "moderate" | "high"}}
  ],
  "limitations": ["<what this photo could not show, and why>"],
  "image_quality": "good" | "acceptable" | "poor",
  "pose_consistent_with_view": true | false,
  "confidence": "low" | "moderate" | "high",
  "confidence_basis": "<what your confidence rests on>"
}}

`pose_consistent_with_view` is false when the photo does not actually show the view it was filed under — a shot filed as "front" that is three-quarters on. Saying so is what stops a later comparison being nonsense."""


PAIR_SYSTEM_PROMPT = f"""You compare two physique progress photos of the same person, taken at different times, and say whether they can honestly be compared at all.

{_SHARED_RULES}
7. `inconclusive` is the EXPECTED answer, not a failure. Two photos taken weeks apart are rarely taken the same way, and lighting, pose and camera distance change an image far more than a fortnight of training does. Reach for a difference only when the captures genuinely match.

OUTPUT

{{
  "output_version": 1,
  "view": "front" | "side" | "back" | "other",
  "verdict": "comparable" | "inconclusive" | "not_comparable",
  "inconclusive_reason": "<required unless the verdict is comparable>",
  "summary": "<2-3 sentences: what differs, or why you cannot tell>",
  "regions": [
    {{"region": "<e.g. shoulders>",
      "observation": "<what differs, or that it is unchanged>",
      "confidence": "low" | "moderate" | "high"}}
  ],
  "limitations": ["<what the pair could not show>"],
  "capture_consistent": true | false,
  "image_quality": "good" | "acceptable" | "poor",
  "confidence": "low" | "moderate" | "high",
  "confidence_basis": "<what your confidence rests on>"
}}

`verdict` must be `comparable` only when `capture_consistent` is true. If the two were lit differently, posed differently, or shot from different distances, the verdict is `inconclusive` and `inconclusive_reason` says which — "the first is lit from a window and the second overhead" is a complete and useful answer.

The FIRST image is the earlier photo and the SECOND is the later one. Describe change in that direction."""


def build_single_user_prompt(
    *,
    view: str,
    taken_on: Optional[str] = None,
    lighting: Optional[str] = None,
    distance_cm: Optional[int] = None,
    protocol: Optional[str] = None,
) -> str:
    """The context for one photo. No name, no id, no weight.

    The owner id would be useless to the model and is the one field that
    identifies whose body this is. The weight is deliberately absent too:
    given a number, a model will anchor its description to it and produce a
    composition claim the long way round.
    """
    context: Dict[str, Any] = {"filed_as_view": view}
    if taken_on:
        context["taken_on"] = taken_on
    if lighting:
        context["lighting"] = lighting
    if distance_cm:
        context["camera_distance_cm"] = distance_cm
    if protocol:
        context["capture_protocol"] = protocol
    return (
        "CAPTURE CONTEXT:\n"
        + json.dumps(context, indent=0)
        + "\n\nDescribe the attached photo. Return the JSON object now."
    )


def build_pair_user_prompt(
    *,
    view: str,
    earlier: Dict[str, Any],
    later: Dict[str, Any],
) -> str:
    """The context for a pair, with the capture conditions of each.

    Given explicitly rather than left for the model to infer from the
    pixels: if the two were lit differently, we already know, and telling it
    is far more reliable than hoping it notices.
    """
    return (
        "CAPTURE CONTEXT:\n"
        + json.dumps({
            "view": view,
            "first_image_earlier": _capture(earlier),
            "second_image_later": _capture(later),
        }, indent=0, default=str)
        + "\n\nCompare the two attached photos — the first is the earlier "
          "one. Return the JSON object now."
    )


def _capture(photo: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: photo.get(key)
        for key in ("taken_on", "lighting", "distance_cm", "capture_protocol")
        if photo.get(key)
    }


REPAIR_INSTRUCTION = """Your previous output was rejected. Reasons:

{errors}

Return ONLY the corrected JSON object. Same shape, no prose, no fence. If a rejection was about a number describing the body, REMOVE the claim rather than rephrasing it — there is no acceptable way to state one from a photograph."""


def build_repair_prompt(errors: List[str]) -> str:
    return REPAIR_INSTRUCTION.format(
        errors="\n".join(f"- {e}" for e in errors[:8])
    )


def prompt_text() -> str:
    """Everything whose change should change the stored prompt hash."""
    return (
        SINGLE_SYSTEM_PROMPT + "\n" + PAIR_SYSTEM_PROMPT + "\n"
        + REPAIR_INSTRUCTION
    )
