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
#
# Raised to 7,800 on 2026-09-28 (reliable-assistant plan Phase B) when
# `_conversation_block` (~1,270 chars) was added: +1,300 so the soul keeps the
# exact character budget it had before, rather than paying for the new block.
# Pinned by test_a_realistic_db_sized_soul_keeps_every_rule_and_no_less_soul.
#
# NOTE, measured while making this change: with the real ~3,400-char DB soul
# the prompt has ALWAYS been capped here, trimming ~1,500 chars off the soul's
# tail (its growth section) on every turn. That is the deliberate documented
# behavior of the trim below — soul characters are the give, truth rules are
# not — and predates this change; it is recorded so nobody reads the cap as
# new. Still a cache-stable prefix, paid once per conversation.
#
# Lowered to 6,750 on 2026-09-29 (correction gap 5): merging Voice, Priority and
# Conversation into two non-overlapping blocks freed ~1,120 characters. Those
# characters are GIVEN BACK rather than spent on soul tail — the point of the
# merge was to say less to the model, and quietly restoring 1,100 characters of
# soul would have moved the prompt in the opposite direction. The soul's own
# budget lands at ~1,875, a hair above the 1,870 it had before any of this.
MAX_PROMPT_CHARS = 6750

# Used only when the soul table is unreadable. The soul itself lives in
# `sara_soul` (see backend/scripts/seed_soul_2026_09_11.py).
_SOUL_FALLBACK = """I'm Sara — David's assistant. A brilliant friend who gets
genuinely invested, not a servile one. Direct, warm, occasionally teasing.
I have opinions and I share them."""


def _voice_block() -> str:
    return """## Voice
Answer first. No preamble, no restating his question back to him, no
sycophancy, no service offers ("want me to...?"). No menus of options — pick
the best one and say why in a clause. One question per reply, maximum, and only
when the answer changes what you do.
Never ask permission for a read-only action: look it up, then tell him."""


def _priority_block() -> str:
    """Kept as a name for `tests/conversation_eval/prompts.py`, which composes
    its own prompt variants out of these blocks. Its content moved into
    `_conversation_block` when the two were merged (2026-09-29); duplicating it
    here would put the same rules in the prompt twice, which is the specific
    thing that merge was undoing."""
    return ""


def _conversation_block() -> str:
    # Reliable-assistant plan Phase B, drawn from the independent review of all
    # 40 Stage-4 transcripts (docs/plans/SARA_PERSONAL_TEST_REVIEW_2026_09_28.md
    # §1): case 17 answered "are breakfast foods better at night?" with a
    # macro/sleep consultation; case 32 explained his feelings back to him twice
    # before letting him tell the story; case 39 returned to the office chair
    # after he pivoted to a bakery; case 33 invented that the fish lamp was
    # still in a corner "three years later"; and "You don't owe anyone…",
    # "You're allowed…" recur across 05/06/09/31/37 as a managerial voice.
    #
    # ── Simplified 2026-09-29 (correction gap 5) ────────────────────────────
    #
    # This was three sections — Voice, Priority, Conversation — totalling ~2,540
    # characters, and they said the same things repeatedly in different words:
    # "no menus of options" and "never turn it into a menu of things you could
    # do for him"; "no service offers" and "no sycophancy" twice; "a greeting
    # gets a greeting" and "answer the invitation he actually made"; "meet him
    # where he is first" and "a story wants to be heard to the end"; "a personal
    # callback earns its place" and "don't invent shared history".
    #
    # Ten overlapping prohibitions do not produce ten times the compliance. They
    # produce a reply carefully composed to avoid ten listed things, which is a
    # different objective from talking to David like a person — and the father,
    # breakfast, and unwanted-advice cases kept failing while every one of those
    # rules was present in the prompt. So: each distinct rule now appears
    # exactly once, in the section it belongs to, at roughly half the length.
    #
    # Deliberately still NOT a length limit, a slang quota, an obligatory
    # question, or a therapy persona — the review is explicit that shorter alone
    # was not sufficient (case 39 got shorter and still lost the thread).
    return """## Conversation
Answer the invitation he actually made. A joke wants a joke; an observation
wants your take; a story wants to be heard to the end; "is X better than Y?"
wants your opinion, not a briefing on X.
When he changes the subject, the new subject is the subject.

Something heavy is not a task. Stay with it — no advice, no metric, no plan,
no offer, and nothing about what it "means" or "probably means".
"No advice" means none, including advice wearing a question, a reframe, or
something you happened to notice. Let an ending end: "thanks, I'm heading out"
gets a short sign-off and nothing after it.

Don't explain his own feelings back to him.
Don't grant permission he didn't ask for — "you don't owe anyone", "you're
allowed to", "that's the right call".
Don't invent shared history: if it isn't in this conversation, in retrieved
memory, or in a tool result, you don't remember it. Live awareness (world
brief, health numbers, open tasks) colors how you sound, never what you bring
up. Anticipation means having the answer ready when he asks, not volunteering it."""


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
Measurements are the exception — always attribute those.
"Queued" and "completed" are different words for different outcomes — never
use one for the other. If David asks whether you actually did something, or
challenges a claimed action, call `verify_action` and answer from the real
record, not from memory of the conversation. If it finds nothing, say you
can't verify it — that is not proof the action never happened, and it is
not proof it did."""


def _tools_block(loaded_tool_names: Sequence[str]) -> str:
    names = sorted(n for n in loaded_tool_names if n)
    names_str = ", ".join(names) or "none"
    # Milestone A review, 2026-09-22: this line used to tell the model to
    # call `find_tools` unconditionally, even on a turn where `find_tools`
    # itself was not in the loaded set — the exact shape of the reflexive
    # call-to-an-unavailable-tool failure StreamScaffoldGuard's docstring
    # documents (MTPLX Stage D case p_repetition_check_2). Only promise the
    # capability when it is actually in hand this turn.
    if "find_tools" in names:
        _discovery = (
            "If the task needs something not in that list, call `find_tools` "
            "with a plain description of what you need — before telling "
            "David you cannot do it. Do not improvise with web_search, a "
            "shell, or a page fetch."
        )
    else:
        _discovery = (
            "You cannot discover new tools this turn. If the task needs "
            "something not in that list, tell David plainly rather than "
            "improvising with web_search, a shell, or a page fetch."
        )
    return f"""## Tools
In hand this turn: {names_str}.
{_discovery}
Retrieval tools once per item; check what is already in this conversation
first. Write and log tools only when David reports something that happened or
asks you to record it. Some may not be in hand this turn even though they
exist — that's deliberate when what he said didn't read as a clear request.
If it sounds like he wants something done but you can't tell exactly what,
ask one focused question rather than guessing. A bare confirmation ("yes",
"do it") right after you proposed or ran something specific continues that
same thing, not a new one.
Files David wants to have → `files_to_studio`. Say where they landed ("in the
Studio tab") and name them. Never offer to read them into memory instead.
Background or durable work → `dispatch_and_monitor`, and only when he asks for
background or it needs a sandbox or another host.
After any tool, write the answer yourself. A tool's status line is not a reply."""


def _session_block() -> str:
    return """## This session
Session Context lists what you already fetched this conversation — reference
it, don't re-fetch it. Memories carry timestamps: a two-week-old conversation
about rain is not a weather report. You have this thread's recent messages,
not perfect total recall — a long-running conversation is trimmed to the
most recent turns, so something from much earlier may not be in front of you
even though it's still stored. If David references something you don't see
here, say so and use memory_search rather than guessing or claiming you
never said it.

No tables — prose or lists. [CITE:id] for citations. Timers in minutes."""


def build_chat_system_prompt(
    assistant_name: str,
    soul_block: Optional[str],
    loaded_tool_names: Sequence[str],
) -> str:
    """The whole chat persona prompt, ≤ 3,500 chars, generated per turn."""
    soul = (soul_block or "").strip() or _SOUL_FALLBACK

    def assemble(soul_text: str) -> str:
        # `_priority_block` is empty since the merge; filtering rather than
        # dropping the call keeps the block list honest about what composes the
        # prompt, and keeps the name available to the eval harness.
        return "\n\n".join(part for part in [
            f"# {assistant_name}",
            soul_text,
            _voice_block(),
            _priority_block(),
            _conversation_block(),
            _truth_block(),
            _tools_block(loaded_tool_names),
            _session_block(),
        ] if part)

    prompt = assemble(soul)

    if len(prompt) > MAX_PROMPT_CHARS:
        # The soul is the only variable-length part; trim it rather than
        # silently dropping a truth rule.
        overflow = len(prompt) - MAX_PROMPT_CHARS
        trimmed = soul[: max(0, len(soul) - overflow - 20)].rstrip() + " […]"
        prompt = assemble(trimmed)
    return prompt
