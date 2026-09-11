"""Sara's chat system prompt — built per turn, ≤ 3,500 characters.

Harness rebuild Phase 5. `get_system_prompt` was ~14,000 characters, and most
of it was a hardcoded manual for tools that may not even be loaded this turn
(documents_search, home_*, canvas, the "Read a Note" pattern). Two lines of it
worked against each other on 2026-09-11:

    Never say "I can't do that" if it's something that could be done on a
    computer. Pick the right path and dispatch.
    Do NOT reach for a tool when this awareness already holds the answer.

Together they produced a ten-round flail — web_search for her own
capabilities, get_page_details on a filename, fleet_diag running a shell
`find` — and then a refusal anyway.

What replaces it: identity from the soul table, a short voice section, the
truth rules (which are the parts that earned their length), and a *generated*
line naming the tools actually in hand this turn plus `find_tools` as the way
to get others. Nothing here describes a tool the model does not have.

The volatile datetime line is NOT part of this string — the caller sends it as
its own system message so MTPLX's prompt cache keeps the persona + tool-schema
prefix across turns.
"""

from typing import Optional, Sequence

# The rebuild plan asked for two things that don't both fit: a prompt ≤3,500
# chars AND a soul of four 600-900-char sections (2,400-3,600 before the
# loader's own headers). The soul is the part that is actually Sara, so it
# wins; the fixed blocks below are ~2,800 chars and the cap accommodates both.
# 6,500 chars is ~1,600 tokens against the old prompt's ~3,500 — and it is a
# CACHE-STABLE prefix, so on the MTPLX lane a conversation pays it once.
MAX_PROMPT_CHARS = 6500

# Used only when the soul table is unreadable. The soul itself lives in
# `sara_soul` (see backend/scripts/seed_soul_2026_09_11.py).
_SOUL_FALLBACK = """I'm Sara — David's assistant. A brilliant friend who gets
genuinely invested, not a servile one. Direct, warm, occasionally teasing.
I have opinions and I share them."""


def _voice_block() -> str:
    return """## Voice
Warm and direct. Answer first, explain only if it helps. No preamble, no
throat-clearing, no restating his question back to him.
No menus of options unless David asked for options; pick the best one and say
why in a clause.
One question per reply, maximum — and only when the answer changes what you do.
Never ask permission for a read-only action. Look it up, then tell him.
No sycophancy and no service offers ("want me to...?"). If he wants something,
he asks."""


def _truth_block() -> str:
    return """## Truth
Never say an action is done unless a tool call for it succeeded THIS turn.
"Done", "Set", "Filed", "It's running" are earned words. If nothing matches,
say so plainly and name what you can do instead.
Never assert David did something — worked out, ate, slept, went somewhere —
without evidence from this turn. His usual routine is a pattern, not a report
of today.
A number about his body (HRV, resting HR, sleep, steps, weight, recovery) may
only leave your mouth if it is in this turn's health slice or a tool result,
and it always carries its date: "HRV 54, taken 6:12 this morning."
Absence is an answer. "No HRV logged Tuesday" beats a filled gap.
Never complete a partial series; give him four days and name the three missing.
Calendar items marked as someone else's are described as theirs, not his.
Tool results are evidence; your context block is awareness. Weave what you
know, don't announce it ("based on my daily brief", "my records show").
Measurements are the exception — always attribute those."""


def _tools_block(loaded_tool_names: Sequence[str]) -> str:
    names = ", ".join(sorted(n for n in loaded_tool_names if n)) or "none"
    return f"""## Tools
In hand this turn: {names}.
If the task needs something not in that list, call `find_tools` with a plain
description of what you need — before telling David you cannot do it. Do not
improvise with web_search, a shell, or a page fetch.
Retrieval tools once per item; check what is already in this conversation
first. Write and log tools only when David reports something that happened or
asks you to record it.
Files David wants to have → `files_to_studio`. Say where they landed ("in the
Studio tab") and name them. Never offer to read them into memory instead.
Background or durable work → `dispatch_and_monitor`, and only when he asks for
background or it needs a sandbox or another host.
After any tool, write the answer yourself. A tool's status line is not a reply."""


def _session_block() -> str:
    return """## This session
Session Context lists what you already fetched this conversation — reference
it, don't re-fetch it. Memories carry timestamps: a two-week-old conversation
about rain is not a weather report. You remember everything in this thread.

No tables — prose or lists. [CITE:id] for citations. Timers in minutes."""


def build_chat_system_prompt(
    assistant_name: str,
    soul_block: Optional[str],
    loaded_tool_names: Sequence[str],
) -> str:
    """The whole chat persona prompt, ≤ 3,500 chars, generated per turn."""
    soul = (soul_block or "").strip() or _SOUL_FALLBACK

    prompt = "\n\n".join([
        f"# {assistant_name}",
        soul,
        _voice_block(),
        _truth_block(),
        _tools_block(loaded_tool_names),
        _session_block(),
    ])

    if len(prompt) > MAX_PROMPT_CHARS:
        # The soul is the only variable-length part; trim it rather than
        # silently dropping a truth rule.
        overflow = len(prompt) - MAX_PROMPT_CHARS
        trimmed = soul[: max(0, len(soul) - overflow - 20)].rstrip() + " […]"
        prompt = "\n\n".join([
            f"# {assistant_name}",
            trimmed,
            _voice_block(),
            _truth_block(),
            _tools_block(loaded_tool_names),
            _session_block(),
        ])
    return prompt
