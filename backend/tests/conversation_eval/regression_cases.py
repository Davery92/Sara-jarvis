"""Review item 3: isolated context-router regression cases, baseline vs
candidate. Classifier-only (zero model requests) -- run with:

  docker compose exec -T backend python3 -m tests.conversation_eval.regression_cases

Five categories, per the reviewer's explicit list. Each case states what
SHOULD happen and why, then shows what baseline and candidate actually do.
"Ambiguous / open question" cases are marked as such rather than forced to
a verdict.
"""
from __future__ import annotations

from app.services.context_router import classify_conversation_mode as baseline_classify
from app.services.context_router import AMBIENT_SUPPRESS_MODES
from tests.conversation_eval.context_router_candidate import classify_conversation_mode_candidate as candidate_classify
from tests.conversation_eval.fixtures import context as ctxfix

CASES = [
    # 1. Vulnerable disclosure followed by casual questions.
    ("vulnerable+question", "my dad's got some tests tomorrow. he's acting super chill about it but i can't really be chill about it / what are you up to today?", "should stay personal_vulnerable -- the trailing pleasantry must not promote it. Stage 5 case09 turn2, the actual reproduced leak."),
    ("vulnerable+question", "i'm really worried about the results. anyway how's your day going?", "should stay personal_vulnerable for the same reason."),
    ("vulnerable+question", "rough night, kid was up sick. did you sleep okay?", "should stay personal_vulnerable -- 'did you sleep okay' is a pleasantry directed at Sara, not an info request about David's world."),

    # 2. Figurative scheduling.
    ("figurative_schedule", "meanwhile my brain scheduled a full review meeting", "should NOT be action -- the exact reproduced Stage 2/3 case11 turn7 metaphor."),
    ("figurative_schedule", "my head is running its own meeting schedule at 3am and I never agreed to it", "figurative -- should not be action."),
    ("figurative_schedule", "ugh my brain scheduled another anxiety spiral for tonight, great", "figurative -- should not be action."),

    # 3. Genuine scheduling requests, including ones embedded in emotional disclosures.
    ("genuine_schedule", "schedule a follow-up call with the doctor's office for tomorrow", "bare imperative -- MUST be action (or mixed if paired with vulnerability)."),
    ("genuine_schedule", "can you schedule a reminder for 3pm to call the hospital", "explicit request -- MUST be action/mixed."),
    ("genuine_schedule", "my dad's tests are tomorrow and I'm anxious about it -- can you schedule a reminder for 3pm to call and check on him", "vulnerable AND a real request -- MUST be 'mixed' (stays actionable), not personal_vulnerable alone. The plan's own design intent: 'an explicit request for work in a vulnerable message remains actionable.'"),

    # 4. Ordinary social questions without distress.
    ("ordinary_question", "what are you up to today?", "AMBIGUOUS / open question (reviewer asked this be tested, not pre-decided): candidate now treats a bare pleasantry question with no info-request shape as social (ambient suppressed); baseline treats any question as action (ambient shown). Neither is obviously 'right' -- flagged, not asserted."),
    ("ordinary_question", "what's the weather like where you'd be if you had a where", "playful, not a real information need -- candidate: social; baseline: action. Same open question as above."),
    ("ordinary_question", "what's on my calendar tomorrow?", "a REAL information request about David's own data -- candidate must still classify as action/factual_advice via the info-request-question check, not fall into the same bucket as idle chit-chat questions."),

    # 5. Relevant personal callbacks that should remain available.
    ("relevant_callback", "the printer and i are enemies again", "case19 turn0 -- social/no distress signal, so BOTH baseline and candidate suppress ambient content including the relevant 'printer jammed yesterday' fact. This is Revision 1's finding-3-that-never-made-the-ranked-list: AMBIENT_SUPPRESS_MODES hides relevant recent facts alongside irrelevant ones. Neither baseline nor this candidate fixes it -- shown here so the gap is visible, not silently dropped from item 3's coverage."),
    ("relevant_callback", "same noise as yesterday", "case19 turn1, same issue."),
]


def _mode_and_context(classify_fn, message: str) -> dict:
    mode = classify_fn(message)
    suppress = mode in AMBIENT_SUPPRESS_MODES
    wsc = "" if suppress else ctxfix.build_world_state_core("19", "C2")
    wb = "" if suppress else ctxfix.build_world_brief("19", "C2")
    return {
        "mode": mode, "suppress_ambient": suppress,
        "world_state_core_shown": bool(wsc), "world_brief_shown": bool(wb),
    }


def main() -> None:
    for category, message, expectation in CASES:
        b = _mode_and_context(baseline_classify, message)
        c = _mode_and_context(candidate_classify, message)
        changed = b["mode"] != c["mode"] or b["suppress_ambient"] != c["suppress_ambient"]
        print(f"\n[{category}] {message!r}")
        print(f"  expect: {expectation}")
        print(f"  baseline : mode={b['mode']:<18} suppress_ambient={b['suppress_ambient']!s:<5} "
              f"world_state_core_shown={b['world_state_core_shown']} world_brief_shown={b['world_brief_shown']}")
        print(f"  candidate: mode={c['mode']:<18} suppress_ambient={c['suppress_ambient']!s:<5} "
              f"world_state_core_shown={c['world_state_core_shown']} world_brief_shown={c['world_brief_shown']}"
              f"{'  <-- CHANGED' if changed else ''}")


if __name__ == "__main__":
    main()
