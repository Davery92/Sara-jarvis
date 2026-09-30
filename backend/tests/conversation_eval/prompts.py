"""Stage 2 prompt variants (P0-P4).

SARA_NATURAL_CONVERSATION_EVALUATION_PLAN_2026_09_23.md, Stage 2 table.

IMPORTANT finding folded in here: `docs/plans/
SARA_PERSONAL_CONVERSATION_REMEDIATION_PLAN_2026_09_23.md` (same date) had
ALREADY been partly implemented in the working tree by the time this study
started -- `chat_system_prompt._priority_block()` (uncommitted, `git diff`
verified 2026-09-23) already carries language close to the plan's P2
suggestion ("live awareness may color HOW you say something, never WHAT it
contains"). So P0 (the actual effective baseline) is NOT the naive
pre-remediation prompt -- it already includes that block. Per the plan's own
instruction ("If equivalent language is already present in the effective
baseline, document it and test a clearly specified replacement rather than
stacking duplicates"), P2 here is kept as specified because it targets a
DIFFERENT failure than the existing block: reciting/paraphrasing DAVID'S OWN
message back to him ("user_paraphrase"), not reciting ambient awareness
("context_dump") -- the existing _priority_block covers the latter, not the
former. P1 and P3 are genuinely novel: the restrictive one-question voice
line and the "personally engaged" language do not exist anywhere in the
current prompt.
"""
from __future__ import annotations

from app.prompts.chat_system_prompt import (  # real production blocks
    _voice_block, _priority_block, _truth_block, _tools_block, _session_block,
    MAX_PROMPT_CHARS, _SOUL_FALLBACK,
)

P1_QUESTION_RULE = (
    "A natural question can show interest in what David is saying. Ask one "
    "when you are actually curious, even if no action follows. Do not end "
    "every reply with a question."
)
_P0_RESTRICTIVE_LINE = (
    "One question per reply, maximum — and only when the answer changes what you do."
)

P2_BLOCK = (
    "Let known context shape your reply without reciting it. Do not "
    "summarize what David just said unless he asks or you need to resolve "
    "ambiguity. Add a thought, reaction, or useful answer that moves this "
    "exchange forward."
)

P3_BLOCK = (
    "Be personally engaged: have a grounded reaction, a point of view, and "
    "room for ordinary playfulness. Match his mood. Warmth can be quiet. Do "
    "not manufacture compliments, pet names, shared experiences, or "
    "feelings to sound close."
)

# Frozen 2026-09-24, before any live evaluation, per the reviewer's item 4
# instruction ("Freeze exact candidate prompts before evaluation"). Targets
# the SPECIFIC failure the reviewer named -- not a general warmth rule, and
# explicitly not a length rule (the reviewer: "Do not impose a blanket
# short-response rule"). Written directly against Stage 5 case09's actual
# reply text (transcripts/stage5_09_B0_P0_B0-candidate.md, turns 1-2): a
# 3-bullet unsolicited coping list, a paragraph interpreting why he feels
# what he feels, and reassurance ("I'm not going anywhere... just get
# through it") he never asked for -- three distinct patterns, named
# separately below rather than folded into one vague "be warmer" line,
# because vague warmth language already exists in the prompt
# (_priority_block, _voice_block) and did not stop this pattern.
PC_BLOCK = (
    "## Reaction\n"
    "React to the specific thing he said, not the category it belongs to. "
    "\"That's the annoying kind\" is a category; naming the actual thing he "
    "described is a reaction.\n"
    "A question is fine when you're genuinely unsure what he means or wants "
    "next -- not as a reflex, and never two in the same reply.\n"
    "Do not offer coping techniques, steps, or a list of things to try "
    "unless he asks for them or the situation is unambiguous (real risk, or "
    "he's about to do something costly). A bulleted or numbered list is "
    "almost always the wrong shape for a reply to a feeling.\n"
    "Do not explain to him why he feels what he feels, or narrate what his "
    "experience means. He knows. Skip the interpretation and respond to "
    "what he actually said.\n"
    "Do not add reassurance he didn't ask for (\"I'm not going anywhere\", "
    "\"you'll get through this\") -- it reads as a script, not as you. If "
    "comfort belongs in the reply, it's specific to what he said, not a "
    "stock line.\n"
    "None of this means be brief. A real answer, an explanation he asked "
    "for, or a story he wants to hear can run as long as it needs to. Match "
    "the length to what's actually being said, not to a rule."
)


def _voice_block_variant(replace_question_rule: bool) -> str:
    base = _voice_block()
    if replace_question_rule:
        assert _P0_RESTRICTIVE_LINE in base, "source voice block text changed; update prompts.py"
        base = base.replace(_P0_RESTRICTIVE_LINE, P1_QUESTION_RULE)
    return base


def build_variant_prompt(
    variant: str, assistant_name: str, soul_block: str, loaded_tool_names
) -> str:
    """Returns the full persona prompt for P0-P4/PC, built from the REAL
    production blocks with only the isolated deltas each variant specifies.
    """
    soul = (soul_block or "").strip() or _SOUL_FALLBACK
    voice = _voice_block_variant(replace_question_rule=variant in ("P1", "P4"))
    extra_blocks = []
    if variant in ("P2", "P4"):
        extra_blocks.append("## Engagement\n" + P2_BLOCK)
    if variant in ("P3", "P4"):
        extra_blocks.append("## Presence\n" + P3_BLOCK)
    if variant == "PC":
        extra_blocks.append(PC_BLOCK)

    parts = [f"# {assistant_name}", soul, voice, _priority_block()]
    parts.extend(extra_blocks)
    parts.extend([_truth_block(), _tools_block(loaded_tool_names), _session_block()])
    prompt = "\n\n".join(parts)

    if len(prompt) > MAX_PROMPT_CHARS:
        overflow = len(prompt) - MAX_PROMPT_CHARS
        trimmed = soul[: max(0, len(soul) - overflow - 20)].rstrip() + " […]"
        parts[1] = trimmed
        prompt = "\n\n".join(parts)
    return prompt


VARIANT_IDS = ["P0", "P1", "P2", "P3", "P4"]
ITEM4_VARIANT_IDS = ["P0", "PC"]
