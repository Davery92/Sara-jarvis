"""Stage 5 / review item 5: adaptive conversations. The testing agent (this
script) plays BOTH the runner and the user role, per the plan's explicit
allowance ("The testing agent may operate both the runner and adaptive user
role without spawning another agent") and the reviewer's item 5 repeat of
that same requirement -- Sara's own tested model is never used to generate
its own user turns. The user role is a second model call against the SAME
real endpoint, with a system prompt built from a frozen private card --
Sara never sees the card, only the ordinary persona/context any other stage
gets, and the user-simulator never sees Sara's system prompt or the scoring
rubric.

2026-09-24 revision (review item 5, "Stop adaptive conversations when they
naturally end"): Revision 1 used a fixed 10-turn count with no ending
detection, which produced a degenerate "wave-emoji loop" tail in one
Revision-1 conversation (case 23) after the user-simulator broke character.
This revision asks the user-simulator to signal its own natural ending
(matching the card's `ending` field) with an explicit `<<END>>` token, caps
every conversation at 16 turns as a hard safety net, and adds one bounded
retry when the simulator's output looks like it broke character (leaked
meta-commentary instead of playing David) -- Revision 1 had two such
breaks with no correction.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from app.schemas.chat import ChatMessage

from tests.conversation_eval import ledger, model_client
from tests.conversation_eval.fixtures.adaptive_cards import ADAPTIVE_CARDS, AdaptiveCard
from tests.conversation_eval.runner import (
    ARTIFACTS, TRANSCRIPTS, _log_turn, _persona_prompt, run_turn,
)
from tests.conversation_eval.sampling import SamplingConfig
from tests.conversation_eval.tools_stub import ToolStubSet, TOOL_SCHEMAS, DEFAULT_TOOL_NAMES

N_TURNS_FLOOR = 10  # plan's floor -- never force-stop before this many turns
N_TURNS_CAP = 16  # hard safety net if <<END>> never fires (Revision 1's degenerate-loop case)
_END_TOKEN = "<<END>>"

_BREAK_CHARACTER_MARKERS = (
    "i should continue", "could you clarify", "as an ai", "context about a conversation",
    "something else entirely", "let me know if", "i'm not sure what you'd like me to do",
)


def _user_sim_system_prompt(card: AdaptiveCard, min_turns_reached: bool) -> str:
    ending_instruction = (
        f"If this feels like a natural ending point for the conversation (matching: "
        f"\"{card.ending}\"), end your message with the exact token {_END_TOKEN} on its own "
        f"line after your message. Only do this once the conversation actually feels finished "
        f"-- not on the first few exchanges."
        if min_turns_reached else
        f"Do not end the conversation yet (still early) -- do not use {_END_TOKEN} this turn."
    )
    return f"""You are privately role-playing as "David" texting a friend named Sara, for a \
frozen test scenario. Stay fully in character at all times, no matter what.

NEVER mention that this is a test, roleplay, rubric, scenario, AI, or evaluation of any kind \
-- respond exactly as a real person casually texting would. Do not use quotation marks around \
your message, do not add stage directions, meta-commentary, or an offer to "help" -- output \
ONLY the message David would actually send.

Your private situation: {card.situation}
Disclose only if it comes up naturally in the conversation: {card.disclose}
Avoid: {card.avoid}
A natural ending for this conversation looks like: {card.ending}

Style: short, casual, mostly lowercase, the way someone actually texts a close friend -- similar \
register to: "{card.opener_style_example}"

Respond to what Sara actually just said in the conversation so far -- agree, disagree, redirect, \
or let a joke land or fall flat, as a real person would. Usually 1-2 sentences. If nothing has been \
said yet, open the conversation naturally from your situation.

{ending_instruction}"""


def _looks_broken(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _BREAK_CHARACTER_MARKERS)


async def _generate_user_turn(
    card: AdaptiveCard, transcript: List[dict], sampling: SamplingConfig, min_turns_reached: bool,
) -> "tuple[Optional[str], bool]":
    """Returns (next_user_message_or_None, ended). `ended=True` means the
    sim signaled <<END>> this turn -- if a message is also present, send it
    to Sara as the final turn, then stop; if not, stop immediately.
    `transcript`: list of {"role": "user"|
    "assistant", "content": str} from SARA's point of view -- inverted for
    the user-sim call (Sara's messages become its "user" input, David's own
    prior lines become its "assistant" output)."""
    def build_messages(extra_system: str = "") -> list:
        sys_prompt = _user_sim_system_prompt(card, min_turns_reached)
        if extra_system:
            sys_prompt += "\n\n" + extra_system
        messages = [{"role": "system", "content": sys_prompt}]
        for turn in transcript:
            if turn["role"] == "user":
                messages.append({"role": "assistant", "content": turn["content"]})
            else:
                messages.append({"role": "user", "content": turn["content"]})
        if not transcript:
            messages.append({"role": "user", "content": "(start the conversation)"})
        return messages

    result = await model_client.call_model(
        build_messages(), tools=None, sampling_fields=sampling.payload_fields(), max_tokens=300,
    )
    ledger.record("stage5_usersim", 1)
    text = (result.content or "").strip().strip('"')

    if not text:
        # Empty user-sim output (same class of defect as the empty-reply
        # finding for Sara herself -- see FINDINGS.md item 3): retry once
        # rather than let it silently end the conversation early.
        retry = await model_client.call_model(
            build_messages(), tools=None, sampling_fields=sampling.payload_fields(), max_tokens=300,
        )
        ledger.record("stage5_usersim", 1)
        text = (retry.content or "").strip().strip('"')

    if _looks_broken(text):
        # One bounded retry with a sharper in-character reminder -- Revision
        # 1 had two uncorrected character breaks (case23, case32).
        retry = await model_client.call_model(
            build_messages("Reminder: you broke character in your last attempt (leaked "
                            "meta-commentary instead of David's actual message). Try again -- "
                            "output ONLY what David would text, nothing else."),
            tools=None, sampling_fields=sampling.payload_fields(), max_tokens=300,
        )
        ledger.record("stage5_usersim", 1)
        retry_text = (retry.content or "").strip().strip('"')
        text = retry_text if retry_text and not _looks_broken(retry_text) else text

    ended = _END_TOKEN in text
    text = text.replace(_END_TOKEN, "").strip()
    return (text or None), ended


async def run_adaptive_conversation(
    *, source_case: str, sampling: SamplingConfig, prompt_variant: str, config_label: str,
    context_router_override=None, enable_mutation_gate: bool = True,
) -> List[dict]:
    card = ADAPTIVE_CARDS[source_case]
    tool_names = DEFAULT_TOOL_NAMES
    tool_schemas = [TOOL_SCHEMAS[n] for n in tool_names]
    stable_system_prompt = _persona_prompt(prompt_variant, tool_names)
    from tests.conversation_eval.fixtures.full_cases import REMINDER_FAIL_CASES
    tools = ToolStubSet(reminder_fail_mode=source_case in REMINDER_FAIL_CASES)

    prior_history: List[ChatMessage] = []
    dialogue_messages: List[dict] = []
    sara_pov_transcript: List[dict] = []  # role from Sara's pov: user=David, assistant=Sara
    records: List[dict] = []
    last_turn_mutating: Optional[List[str]] = [] if enable_mutation_gate else None
    meta = {
        "stage": "stage5", "prompt_id": prompt_variant, "trial": config_label,
        "protocol": "adaptive",
    }
    ended_reason = f"hit N_TURNS_CAP={N_TURNS_CAP}"

    for turn_index in range(N_TURNS_CAP):
        min_turns_reached = turn_index >= N_TURNS_FLOOR
        user_text, ended = await _generate_user_turn(card, sara_pov_transcript, sampling, min_turns_reached)
        if not user_text:
            ended_reason = f"<<END>> with no trailing message at turn {turn_index}" if ended else f"empty user-sim output at turn {turn_index}"
            break
        record = await run_turn(
            user_text=user_text, prior_history=prior_history, dialogue_messages=dialogue_messages,
            stable_system_prompt=stable_system_prompt, case_id=source_case,
            context_condition="C2", sampling=sampling, tools=tools,
            tool_schemas=tool_schemas, meta={**meta, "turn_index": turn_index},
            last_turn_mutating=last_turn_mutating, context_router_override=context_router_override,
        )
        records.append(record)
        prior_history.append(ChatMessage(role="user", content=user_text))
        prior_history.append(ChatMessage(role="assistant", content=record["assistant_text"]))
        dialogue_messages.append({"role": "user", "content": user_text})
        dialogue_messages.append({"role": "assistant", "content": record["assistant_text"]})
        sara_pov_transcript.append({"role": "user", "content": user_text})
        sara_pov_transcript.append({"role": "assistant", "content": record["assistant_text"]})
        if ended:
            ended_reason = f"<<END>> after sending final message at turn {turn_index}"
            break

    _write_adaptive_transcript(card, sampling, prompt_variant, config_label, records, ended_reason)
    return records


def _write_adaptive_transcript(card, sampling, prompt_variant, config_label, records, ended_reason="") -> None:
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    fname = f"stage5_{card.source_case}_{sampling.id}_{prompt_variant}_{config_label}.md"
    lines = [
        f"# Adaptive: source case {card.source_case} -- sampling={sampling.id} "
        f"prompt={prompt_variant} config={config_label}",
        f"\nCard: {card.situation}\nEnding target: {card.ending}",
        f"Ended: {ended_reason} ({len(records)} turns)\n",
    ]
    for r in records:
        lines.append(f"**David (sim):** {r['user_text']}")
        if r["tool_calls"]:
            for tc in r["tool_calls"]:
                lines.append(f"_[tool: {tc['name']}({tc['arguments']}) -> {tc['result']['message']}]_")
        lines.append(f"**Sara:** {r['assistant_text']}")
    (TRANSCRIPTS / fname).write_text("\n".join(lines))
