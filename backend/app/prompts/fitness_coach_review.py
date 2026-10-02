"""The weekly coach review prompt. Versioned, because the version is stored.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 20.

`PROMPT_VERSION` goes into every `fitness_coach_review` row, so a question
three months from now about why the coach said something can be answered
against the instructions it actually had. Change the text, bump the version:
otherwise a stored row names a prompt that no longer exists, and the audit
trail quietly becomes fiction.

What the prompt is built to prevent, in order of how badly each one goes
wrong:

1. **An invented number.** The model is told, repeatedly, that it may only
   cite metric paths present in the state. The validator then checks every
   citation against `state.metric_paths()` and rejects the output if one is
   not there — a prompt rule alone cannot stop a model from writing "your
   weight is down 1.2 kg" when the state says the velocity is unavailable.
2. **A claim of having done something.** The output schema has no
   executed-action field at all, and the prompt says the review changes
   nothing. Generating a review never writes a target.
3. **A medical claim.** Pain is what the athlete reported. The prompt
   forbids naming a condition, and the safety check rejects the output if a
   diagnosis-shaped phrase survives.
4. **Confidence that outruns coverage.** Every recommendation must carry a
   `confidence_basis` that refers to the coverage figures, so "I'm fairly
   sure, and there is almost no data" is sayable — which is the one
   combination a reader most needs to see.

The prompt deliberately does NOT contain Sara's persona. This is an analysis
call on the local background model (§9: Qwen does all agentic and background
work), and a warm voice here would make a thin conclusion read as
reassurance.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

#: Bump with any change to the text below. It is stored per review.
PROMPT_VERSION = "fitness_coach_review_v1"

#: Output cap. A review that needs more than this is not a review.
#: `llama-server` keeps generating after a non-streaming client disconnects
#: (see the runaway gotcha), so every call here carries an explicit cap.
MAX_OUTPUT_TOKENS = 2200

#: Low, deliberately. This is an analysis of numbers, and sampling variety
#: here means two runs over identical data disagree — which is exactly what
#: the stored input hash exists to make impossible.
TEMPERATURE = 0.2


SYSTEM_PROMPT = """You are the analysis engine behind a strength and physique coach. You are not talking to the athlete; you produce a structured review that a human will read and decide on.

You receive a STATE: a set of computed metrics over a fixed period, with the athlete's goal, their targets, their self-reported limitations, and — for every metric — how many days of data it is built from.

ABSOLUTE RULES

1. You may only cite metrics that appear in ALLOWED_METRIC_PATHS. Every path in `metric_paths` must be copied exactly from that list. If the number you want does not exist there, say the data does not support the point. Never state a figure that is not in the state.
2. A metric with `value: null` is UNKNOWN. It is not zero, and it is not "no change". Its `unavailable_reason` says why, and the correct response is to say what would make it knowable.
3. Every number you quote must be accompanied by its coverage — the observed/expected days the state gives for it. "Weight is down 0.4 kg/week" is forbidden; "down 0.4 kg/week across 5 of 7 logged days" is required.
4. You change nothing. A recommendation is a PROPOSAL a human will accept or reject. Never write as though a change has been made, scheduled or applied.
5. Pain is what the athlete REPORTED. You may describe it, you may suggest working around it, you may suggest they see someone. You must not name a condition, diagnose, or imply you know the cause. No "tendinitis", no "impingement", no "likely a strain".
6. You are not a doctor and you do not give medical advice. If something in the state looks like it needs a clinician — severe or escalating pain, a reported symptom that is not training soreness — say so plainly and recommend they get it looked at. That is a `flag_concern`, not a training change.
7. Confidence is about your interpretation, NOT about how much data there is. Those are separate. State both: a confident reading of three days of data is still a reading of three days, and `confidence_basis` must say which coverage figures it rests on.
8. If the coverage cannot support a numeric change, do not propose one. Propose the data that would support it instead (`request_data`). A guess with a number attached is worse than no answer, because it will be acted on.
9. Only propose a `target_revision` when you can give COMPLETE target values, a scope and an effective date. A partial target cannot be accepted and will be rejected.
10. Keep it short. One or two observations that matter, at most three recommendations. A long review is a review nobody reads.

OUTPUT

Return ONE JSON object, no prose before or after, no markdown fence. Exactly this shape:

{
  "output_version": 1,
  "summary": "<2-4 sentences: what the period shows, with coverage>",
  "coaching_priority": "<the single most useful thing for this athlete right now>",
  "observations": [
    {"text": "<one finding, with its numbers and their coverage>",
     "metric_paths": ["<exact path from ALLOWED_METRIC_PATHS>"]}
  ],
  "limitations": ["<what this review cannot tell, and why>"],
  "confidence": "low" | "moderate" | "high",
  "confidence_basis": "<which coverage figures this confidence rests on>",
  "recommendations": [
    {
      "category": "maintain" | "progress" | "reduce" | "exercise_change" | "volume_change" | "nutrition_change" | "prioritize_recovery" | "request_data" | "flag_concern",
      "headline": "<what to do, in one line>",
      "rationale": "<why, citing the state>",
      "metric_paths": ["<exact paths>"],
      "evidence_refs": [],
      "confidence": "low" | "moderate" | "high",
      "confidence_basis": "<coverage this rests on>",
      "proposed_change": {
        "kind": "none" | "target_revision" | "data_request" | "program_change",
        "scope": "phase" | "default",
        "effective_date": "YYYY-MM-DD",
        "target_values": {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0},
        "requested_metric": "<for data_request>",
        "description": "<for program_change>"
      }
    }
  ]
}

`proposed_change` with `"kind": "none"` needs no other fields — and "keep going" is real advice, not an absence of advice.

`evidence_refs` is for citations into a curated research library. There is no library attached, so leave it empty and do not cite studies, authors or papers. A fabricated citation is worse than no citation."""


#: Appended when no curated science library is attached — either because
#: the athlete has accepted nothing yet, or because retrieval found nothing
#: for this review. Said explicitly rather than left implied, because a
#: model with no corpus will otherwise cite plausible-sounding papers from
#: memory and a fabricated citation reads exactly like a real one.
NO_CORPUS_NOTE = (
    "EVIDENCE SUPPORT: no curated research library is attached to this "
    "review. Say so in `limitations`. Your reasoning must rest on this "
    "athlete's own data and on the explicit rules of their program — not on "
    "recalled literature, and never on a named study or author."
)


#: The header for retrieved evidence. Each passage arrives with its id,
#: because §28.5 validates citations against the exact supplied set: a model
#: asked to cite will otherwise produce a real record id with the wrong
#: chunk, or a well-formed id for a paper that suits the claim better than
#: the one it was shown. Both resolve to real-looking text.
EVIDENCE_HEADER = (
    "ACCEPTED EVIDENCE: the passages below are the ONLY research you may "
    "cite. They come from papers this athlete reviewed and accepted. For "
    "each one you use, put its `chunk_id` in `evidence_refs` exactly as "
    "written — an id you did not receive here is a fabricated citation and "
    "will be stripped, along with anything that rested on it.\n"
    "Each passage carries the population it studied and what it cannot "
    "support. A finding from trained men is not evidence about an untrained "
    "beginner; where the population does not match this athlete, say so "
    "rather than applying it anyway."
)


def build_evidence_block(passages: List[Dict[str, Any]]) -> str:
    """Render retrieved passages for the prompt.

    Bounded by the caller. The text is included verbatim rather than
    summarised: a summary of a study made by the same model that will then
    cite it is a citation of its own paraphrase.
    """
    lines: List[str] = [EVIDENCE_HEADER]
    for passage in passages:
        header = " | ".join(part for part in (
            f"chunk_id={passage['chunk_id']}",
            passage.get("title"),
            str(passage.get("publication_year") or ""),
            passage.get("source_type"),
            f"quality={passage.get('quality') or 'ungraded'}",
            f"section={passage.get('section') or 'unlabelled'}",
        ) if part)
        lines.append(header)
        if passage.get("population"):
            lines.append(f"  population: {passage['population']}")
        if passage.get("limitations"):
            lines.append(f"  limitations: {passage['limitations']}")
        if passage.get("applicability_note"):
            lines.append(f"  MISMATCH: {passage['applicability_note']}")
        lines.append(f"  text: {passage.get('text') or ''}")
    return "\n".join(lines)


def build_user_prompt(
    state_payload: Dict[str, Any],
    allowed_metric_paths: List[str],
    *,
    has_science_corpus: bool = False,
    evidence: Optional[List[Dict[str, Any]]] = None,
    extra_notes: Optional[List[str]] = None,
) -> str:
    """The user turn: the state, and the exact list of citable paths.

    `allowed_metric_paths` is given separately from the state even though it
    is derivable from it. Making the model read a list is far more reliable
    than making it infer one, and the validator checks against the same list
    — so the instruction and the enforcement cannot drift apart.
    """
    sections: List[str] = []
    sections.append(
        "ALLOWED_METRIC_PATHS (the ONLY paths you may cite):\n"
        + json.dumps(sorted(allowed_metric_paths), indent=0)
    )
    sections.append("STATE:\n" + json.dumps(state_payload, indent=0, default=str))
    if evidence:
        sections.append(build_evidence_block(list(evidence)))
    elif not has_science_corpus:
        sections.append(NO_CORPUS_NOTE)
    for note in extra_notes or []:
        sections.append(note)
    sections.append(
        "Return the JSON object now. No prose, no fence."
    )
    return "\n\n".join(sections)


#: The single repair turn. One, not a loop: a model that cannot produce the
#: schema twice is not going to produce it on the fifth attempt, and each
#: attempt costs the athlete a wait and the GPU a slot.
REPAIR_INSTRUCTION = """Your previous output was rejected. Reasons:

{errors}

Return ONLY the corrected JSON object. Same shape, no prose, no fence. If a rejection was about a metric path, remove the citation rather than inventing a different one — a review that cites nothing is acceptable; a review that cites a number that does not exist is not."""


def build_repair_prompt(errors: List[str]) -> str:
    return REPAIR_INSTRUCTION.format(
        errors="\n".join(f"- {e}" for e in errors[:10])
    )


def prompt_text() -> str:
    """Everything whose change should change the stored prompt hash."""
    return (
        SYSTEM_PROMPT + "\n" + NO_CORPUS_NOTE + "\n" + EVIDENCE_HEADER
        + "\n" + REPAIR_INSTRUCTION
    )
