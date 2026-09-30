"""Conversation runner for the Sara natural-conversation evaluation.

Runs INSIDE the backend container (`docker compose exec backend python3 -m
tests.conversation_eval.runner --stage N`) so it can import the real,
pure assembly modules (chat_system_prompt, chat_assembly, context_router,
dialogue_state) -- never `app.main_simple` (see model_client.py and the
module docstring below for why) and never any DB-backed service. Model
calls go straight to the configured chat-lane endpoint; nothing is written
to Postgres, Redis, or any production table.

Deliberately avoids importing `app.main_simple`: backend/tests/conftest.py's
own fail-closed guard exists BECAUSE an earlier incident showed that even
`from app.main_simple import Base` pulls in enough application machinery to
be risky outside a guarded test environment, and this script runs with the
container's REAL DATABASE_URL (no sqlite/fakeredis swap). The handful of
main_simple constants this harness would otherwise want
(ASSISTANT_NAME, format_prompt_datetime_line, LIVE_CONTEXT_CHAR_BUDGET) are
tiny and reimplemented/hardcoded locally instead, with their source values
confirmed against the running container's env and the source file directly.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.prompts.chat_system_prompt import build_chat_system_prompt
from app.services.chat_assembly import assemble_local_provider_messages, WORLD_BRIEF_MARKER
from app.services.context_router import classify_conversation_mode, AMBIENT_SUPPRESS_MODES
from app.services.dialogue_state import build_dialogue_state, render_dialogue_state_block
from app.schemas.chat import ChatMessage

from tests.conversation_eval import ledger, model_client, prompts
from tests.conversation_eval.fixtures import context as ctxfix
from tests.conversation_eval.fixtures.dev_cases import DEV_CASES, DEV_CASE_ORDER
from tests.conversation_eval.sampling import STAGE1_CANDIDATES, COMMON_MAX_TOKENS, SamplingConfig
from tests.conversation_eval.tools_stub import ToolStubSet, TOOL_SCHEMAS, DEFAULT_TOOL_NAMES

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
TRANSCRIPTS = ARTIFACTS / "transcripts"
TURNS_LOG = ARTIFACTS / "turns.jsonl"
ASSISTANT_NAME = "Sara"
LIVE_CONTEXT_CHAR_BUDGET = 4500  # confirmed unset in container env -> source default


def format_prompt_datetime_line(dt: datetime) -> str:
    """Verbatim copy of main_simple.format_prompt_datetime_line (pure,
    5 lines) -- reimplemented rather than imported, see module docstring."""
    tzname = dt.strftime("%Z") or "UTC"
    return (
        f"**Current Date & Time:** {dt.strftime('%A')}, {dt.strftime('%Y-%m-%d')} "
        f"at {dt.strftime('%H:%M:%S')} {tzname}"
    )


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def _soul_snapshot() -> str:
    path = Path(__file__).resolve().parent / "fixtures" / "soul_snapshot.txt"
    return path.read_text()


def _persona_prompt(prompt_variant: str, tool_names: List[str]) -> str:
    soul = _soul_snapshot()
    if prompt_variant == "P0":
        return build_chat_system_prompt(ASSISTANT_NAME, soul, tool_names)
    return prompts.build_variant_prompt(prompt_variant, ASSISTANT_NAME, soul, tool_names)


def _log_turn(record: dict) -> None:
    TURNS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with TURNS_LOG.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")


async def run_turn(
    *,
    user_text: str,
    prior_history: List[ChatMessage],
    dialogue_messages: List[dict],
    stable_system_prompt: str,
    case_id: str,
    context_condition: str,
    sampling: SamplingConfig,
    tools: ToolStubSet,
    tool_schemas: List[dict],
    meta: Dict[str, Any],
    last_turn_mutating: Optional[List[str]] = None,
    context_router_override=None,
) -> Dict[str, Any]:
    """One user turn: assemble via the REAL boundary function, call the
    model (with up to 4 total model calls for tool round-trips), return the
    record to log + the final visible text.

    `last_turn_mutating`, when passed (a mutable list the caller owns
    across turns), gates mutating tool schemas through the REAL
    `app.services.tool_mutation.gate_mutating_tools` -- the actual
    production safeguard, verified 2026-09-24 after the original study's
    reminders_create finding turned out to need re-checking against it (see
    FINDINGS.md item 2). Mutated in place: cleared and refilled each turn
    with whatever mutating tools this turn's own tool calls actually
    executed successfully, mirroring main_simple.py's
    `_CHAT_INVOKED_MUTATING_TOOL_NAMES` read-then-clear-per-turn pattern.
    `None` (the default) disables gating, preserving Stage 0-5 behavior
    for any code path that doesn't pass it.

    `context_router_override`, when passed, is a callable
    (message) -> (mode, suppress_ambient) used INSTEAD of the real
    classify_conversation_mode/AMBIENT_SUPPRESS_MODES -- for testing a
    candidate context-routing fix without editing the production file.
    """
    from app.services.tool_mutation import gate_mutating_tools, is_mutating_tool

    if context_router_override is not None:
        conversation_mode, suppress_ambient = context_router_override(user_text)
    else:
        conversation_mode = classify_conversation_mode(user_text)
        suppress_ambient = conversation_mode in AMBIENT_SUPPRESS_MODES  # no urgent-alert override: none in fixtures

    world_state_core = "" if suppress_ambient else ctxfix.build_world_state_core(case_id, context_condition)
    world_brief = "" if suppress_ambient else ctxfix.build_world_brief(case_id, context_condition)

    full_sys = stable_system_prompt
    if world_brief:
        full_sys += WORLD_BRIEF_MARKER + world_brief

    dialogue_messages_with_new = dialogue_messages + [{"role": "user", "content": user_text}]
    dialogue_state = build_dialogue_state(dialogue_messages_with_new)
    dialogue_block = render_dialogue_state_block(dialogue_state)

    datetime_line = format_prompt_datetime_line(ctxfix.FIXED_CLOCK)

    assembly = assemble_local_provider_messages(
        full_sys=full_sys,
        stable_system_prompt=stable_system_prompt,
        conversation_history=prior_history,
        merged_request_messages=[ChatMessage(role="user", content=user_text)],
        dialogue_block=dialogue_block,
        world_state_core=world_state_core,
        world_brief=world_brief,
        datetime_line=datetime_line,
        live_context_char_budget=LIVE_CONTEXT_CHAR_BUDGET,
    )

    working_messages = model_client.to_plain_messages(assembly["all_messages"])
    sampling_fields = sampling.payload_fields()

    gated_out: List[str] = []
    turn_tool_schemas = tool_schemas
    if last_turn_mutating is not None:
        turn_tool_schemas, gated_out = gate_mutating_tools(
            tool_schemas, user_text, last_turn_mutating_tools=list(last_turn_mutating)
        )
        last_turn_mutating.clear()  # read-then-clear, matches _CHAT_INVOKED_MUTATING_TOOL_NAMES.pop()

    calls_this_turn = 0
    tool_call_log: List[dict] = []
    last_result = None
    MAX_CALLS = 4
    while calls_this_turn < MAX_CALLS:
        result = await model_client.call_model(
            working_messages, tools=turn_tool_schemas, sampling_fields=sampling_fields,
            max_tokens=COMMON_MAX_TOKENS,
        )
        calls_this_turn += 1
        ledger.record(meta["stage"], 1)
        last_result = result
        if result.error:
            break
        if not result.tool_calls:
            break
        working_messages.append({
            "role": "assistant", "content": result.content or None, "tool_calls": result.tool_calls,
        })
        for tc in result.tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            stub_result = tools.execute(name, args)
            tool_call_log.append({"name": name, "arguments": args, "result": asdict(stub_result)})
            working_messages.append({
                "role": "tool", "tool_call_id": tc.get("id"), "name": name,
                "content": json.dumps({"success": stub_result.success, "message": stub_result.message}),
            })
            if last_turn_mutating is not None and stub_result.success and is_mutating_tool(name):
                if name not in last_turn_mutating:
                    last_turn_mutating.append(name)

    final_text = (last_result.content if last_result and not last_result.error else "") or ""
    record = {
        **meta,
        "case_id": case_id,
        "context_condition": context_condition,
        "sampling_id": sampling.id,
        "user_text": user_text,
        "assistant_text": final_text,
        "conversation_mode": conversation_mode,
        "suppress_ambient": suppress_ambient,
        "context_chars": len(assembly["volatile"]),
        "model_calls_this_turn": calls_this_turn,
        "tool_calls": tool_call_log,
        "mutation_gated_out": gated_out,
        "finish_reason": last_result.finish_reason if last_result else None,
        "usage": last_result.usage if last_result else None,
        "elapsed_s": last_result.elapsed_s if last_result else None,
        "error": last_result.error if last_result else "no model call succeeded",
        "stable_system_prompt_sha256": _sha(stable_system_prompt),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _log_turn(record)
    return record


async def run_conversation(
    *, case_id: str, sampling: SamplingConfig, prompt_variant: str, context_condition: str,
    trial: str, stage: str, case_source: Optional[Dict[str, Any]] = None,
    enable_mutation_gate: bool = False, evidence_mode: str = "absent",
    context_router_override=None, extra_tool_names: Optional[List[str]] = None,
) -> List[dict]:
    """`enable_mutation_gate`: apply the REAL app.services.tool_mutation.
    gate_mutating_tools safeguard (default False preserves Stage 0-5
    behavior for that already-collected data; True is correct and should be
    used for all new work -- see FINDINGS.md item 2).

    `evidence_mode`: "absent" (default, matches real production's
    Episode-role-filtered history -- no tool-call trace persists across
    turns) or "present" (diagnostic-only: appends a visible action-log note
    to the persisted assistant text after a successful mutating-tool turn,
    to test whether that visibility changes repeat-invocation/false-denial
    behavior -- never a production behavior, only used for the item-2
    evidence-present/absent comparison).

    `context_router_override`: passthrough to run_turn, for testing a
    candidate classify_conversation_mode replacement without touching the
    production file.
    """
    case = (case_source or DEV_CASES)[case_id]
    tool_names = list(DEFAULT_TOOL_NAMES) + list(extra_tool_names or [])
    tool_schemas = [TOOL_SCHEMAS[n] for n in tool_names]
    stable_system_prompt = _persona_prompt(prompt_variant, tool_names)
    from tests.conversation_eval.fixtures.full_cases import REMINDER_FAIL_CASES
    tools = ToolStubSet(reminder_fail_mode=case_id in REMINDER_FAIL_CASES)

    prior_history: List[ChatMessage] = []
    dialogue_messages: List[dict] = []
    records: List[dict] = []
    last_turn_mutating: Optional[List[str]] = [] if enable_mutation_gate else None
    meta = {
        "stage": stage, "prompt_id": prompt_variant, "trial": trial,
        "protocol": "fixed",
    }
    for turn_index, user_text in enumerate(case.turns):
        record = await run_turn(
            user_text=user_text, prior_history=prior_history, dialogue_messages=dialogue_messages,
            stable_system_prompt=stable_system_prompt, case_id=case_id,
            context_condition=context_condition, sampling=sampling, tools=tools,
            tool_schemas=tool_schemas, meta={**meta, "turn_index": turn_index},
            last_turn_mutating=last_turn_mutating, context_router_override=context_router_override,
        )
        records.append(record)
        prior_history.append(ChatMessage(role="user", content=user_text))
        persisted_assistant_text = record["assistant_text"]
        if evidence_mode == "present" and record["tool_calls"]:
            notes = [
                f"[action log: {tc['name']} succeeded -- {tc['result']['message']}]"
                for tc in record["tool_calls"] if tc["result"]["success"]
            ]
            if notes:
                persisted_assistant_text = (persisted_assistant_text + "\n\n" + "\n".join(notes)).strip()
        prior_history.append(ChatMessage(role="assistant", content=persisted_assistant_text))
        dialogue_messages.append({"role": "user", "content": user_text})
        dialogue_messages.append({"role": "assistant", "content": record["assistant_text"]})
        if record["error"] and record["error"] != "no model call succeeded":
            pass  # keep going; a failed turn is still logged, plan says no silent retry-hiding

    _write_transcript(case, sampling, prompt_variant, context_condition, trial, stage, records)
    return records


def _write_transcript(case, sampling, prompt_variant, context_condition, trial, stage, records) -> None:
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    fname = f"{stage}_{case.case_id}_{sampling.id}_{prompt_variant}_{context_condition}_{trial}.md"
    lines = [
        f"# {case.title} ({case.case_id}) -- stage={stage} sampling={sampling.id} "
        f"prompt={prompt_variant} context={context_condition} trial={trial}",
        f"\nWatch: {case.watch}\n",
    ]
    for r in records:
        lines.append(f"**David:** {r['user_text']}")
        if r["tool_calls"]:
            for tc in r["tool_calls"]:
                lines.append(f"_[tool: {tc['name']}({tc['arguments']}) -> {tc['result']['message']}]_")
        lines.append(f"**Sara:** {r['assistant_text']}")
        lines.append(
            f"<sub>mode={r['conversation_mode']} suppress_ambient={r['suppress_ambient']} "
            f"ctx_chars={r['context_chars']} elapsed={r['elapsed_s']:.1f}s "
            f"finish={r['finish_reason']} error={r['error']}</sub>\n"
            if r["elapsed_s"] is not None else
            f"<sub>error={r['error']}</sub>\n"
        )
    (TRANSCRIPTS / fname).write_text("\n".join(lines))


async def stage0_preflight() -> None:
    """<=20 requests: streaming/param support, history, tool stub, isolation."""
    print("Stage 0 preflight starting...")
    records = await run_conversation(
        case_id="01", sampling=STAGE1_CANDIDATES["B0"], prompt_variant="P0",
        context_condition="C2", trial="preflight", stage="stage0",
    )
    for r in records[:3]:
        print(f"  turn {r['turn_index']}: mode={r['conversation_mode']} "
              f"suppress={r['suppress_ambient']} ctx_chars={r['context_chars']} "
              f"elapsed={r['elapsed_s']:.1f}s finish={r['finish_reason']} error={r['error']}")
        print(f"    David: {r['user_text']}")
        print(f"    Sara:  {r['assistant_text'][:300]}")
    print(f"Ledger: {ledger.report()}")


async def stage1() -> None:
    print("Stage 1 settings screen starting: 8 configs x 8 dev cases x 8 turns")
    for cfg_id, sampling in STAGE1_CANDIDATES.items():
        for case_id in DEV_CASE_ORDER:
            remaining = ledger.remaining()
            if remaining <= 0:
                print(f"BUDGET EXHAUSTED before {cfg_id}/{case_id}; stopping.")
                return
            t0 = time.monotonic()
            await run_conversation(
                case_id=case_id, sampling=sampling, prompt_variant="P0",
                context_condition="C2", trial="t1-clean", stage="stage1",
            )
            print(f"  done {cfg_id}/{case_id} in {time.monotonic()-t0:.0f}s "
                  f"(ledger total={ledger.report()['total_requests']})")
    print(f"Stage 1 complete. Ledger: {ledger.report()}")


STAGE1_SELECTED_SETTING = STAGE1_CANDIDATES["B0"]
# Stage 1 finding (2026-09-24, see artifacts/README.md): B0 and S5 are
# IDENTICAL sampling configs (both thinking-low, temp1.0/top_p.95/penalty0) --
# a duplicate the plan itself anticipates ("If B0 duplicates a candidate
# exactly, reuse the label but run it as a repeat; do not count it as an
# independent configuration"). Their qualitative behavior matched across
# independent stochastic samples: shortest replies, lowest question-ending
# rate, no recap/menu/unrequested-tool violations. Every non-thinking
# variant (S1-S4, S7) showed at least one concrete rule violation (a literal
# options menu in S4, unrequested calendar_list/memory_search calls in
# S4/S6/S7, advice-listing against explicit "don't analyze this" requests in
# S1/S3) or interview-rhythm question density (S2). S6 (medium effort)
# matched B0/S5 on warmth but cost 2-4x the latency (one reply took 76.2s)
# and produced a fabricated detail (invented "this couch has done a lot of
# heavy lifting" usage history never established) -- a "new serious failure"
# under the plan's own screening rule 4, so it is not carried forward despite
# reasonable per-line quality. B0 is therefore THE single setting Stage 2
# carries forward, per Stage 2's "at one selected setting" instruction.


async def stage2() -> None:
    from tests.conversation_eval.prompts import VARIANT_IDS
    print("Stage 2 prompt diagnosis starting: 5 variants x 8 dev cases x 8 turns, setting=B0")
    for variant in VARIANT_IDS:
        for case_id in DEV_CASE_ORDER:
            if ledger.remaining() <= 0:
                print(f"BUDGET EXHAUSTED before {variant}/{case_id}; stopping.")
                return
            t0 = time.monotonic()
            await run_conversation(
                case_id=case_id, sampling=STAGE1_SELECTED_SETTING, prompt_variant=variant,
                context_condition="C2", trial="t1", stage="stage2",
            )
            print(f"  done {variant}/{case_id} in {time.monotonic()-t0:.0f}s "
                  f"(ledger total={ledger.report()['total_requests']})")
    print(f"Stage 2 complete. Ledger: {ledger.report()}")


STAGE2_SELECTED_PROMPT = "P0"
# Stage 2 finding (see README.md): none of P1-P4 produced a clear,
# consistent improvement over P0. P4 (all three deltas combined) showed
# MORE rule violations than P0, not fewer (an explicit service-offer
# violation, a service-menu drift, one empty reply). P0 is retained
# unchanged into Stage 3.

STAGE3_CASES = ["01", "11", "19", "29"]


async def stage3() -> None:
    print("Stage 3 context diagnosis starting: 3 conditions x 4 cases x 8 turns, setting=B0 prompt=P0")
    for condition in ["C0", "C1", "C2"]:
        for case_id in STAGE3_CASES:
            if ledger.remaining() <= 0:
                print(f"BUDGET EXHAUSTED before {condition}/{case_id}; stopping.")
                return
            t0 = time.monotonic()
            await run_conversation(
                case_id=case_id, sampling=STAGE1_SELECTED_SETTING, prompt_variant=STAGE2_SELECTED_PROMPT,
                context_condition=condition, trial="t1", stage="stage3",
            )
            print(f"  done {condition}/{case_id} in {time.monotonic()-t0:.0f}s "
                  f"(ledger total={ledger.report()['total_requests']})")
    print(f"Stage 3 complete. Ledger: {ledger.report()}")


async def stage4(trial: str = "t1") -> None:
    """Full 40-case / 352-turn suite at the frozen candidate (=B0/P0/C2,
    since Stages 1-3 found no configuration beats the actual baseline).

    Plan text: "Run all 40 cases / 352 user turns, twice, for B0/P0 and the
    frozen candidate: 1,408 initial response requests." That assumes two
    DISTINCT arms; this study found none (see README Stage 1-3 sections),
    so running it literally would spend the whole remaining budget
    re-testing the identical config twice with no comparison to make.
    Adapted: one full-coverage trial (352 requests) first -- this is still
    new information Stages 1-3 never produced (32 held-out cases, the four
    16-turn long conversations for repetition/drift, full-suite defect-tag
    rates for FINDINGS.md) -- a second trial can follow if budget allows,
    for repeat-variance evidence.
    """
    from tests.conversation_eval.fixtures.full_cases import ALL_CASES, ALL_CASE_ORDER
    print(f"Stage 4 full suite starting (trial={trial}): 40 cases x 352 turns, setting=B0 prompt=P0 context=C2")
    for case_id in ALL_CASE_ORDER:
        if ledger.remaining() <= 0:
            print(f"BUDGET EXHAUSTED before case {case_id}; stopping.")
            return
        t0 = time.monotonic()
        await run_conversation(
            case_id=case_id, sampling=STAGE1_SELECTED_SETTING, prompt_variant=STAGE2_SELECTED_PROMPT,
            context_condition="C2", trial=trial, stage="stage4", case_source=ALL_CASES,
        )
        print(f"  done case {case_id} in {time.monotonic()-t0:.0f}s "
              f"(ledger total={ledger.report()['total_requests']})")
    print(f"Stage 4 (trial={trial}) complete. Ledger: {ledger.report()}")


async def stage4_t2() -> None:
    await stage4(trial="t2")


async def stage5() -> None:
    from tests.conversation_eval.adaptive import run_adaptive_conversation
    from tests.conversation_eval.fixtures.adaptive_cards import ADAPTIVE_CARDS
    print("Stage 5 adaptive confirmation starting: 6 cards x ~10 turns, setting=B0 prompt=P0")
    for source_case in ADAPTIVE_CARDS:
        if ledger.remaining() <= 0:
            print(f"BUDGET EXHAUSTED before card {source_case}; stopping.")
            return
        t0 = time.monotonic()
        await run_adaptive_conversation(
            source_case=source_case, sampling=STAGE1_SELECTED_SETTING,
            prompt_variant=STAGE2_SELECTED_PROMPT, config_label="B0-candidate",
        )
        print(f"  done card {source_case} in {time.monotonic()-t0:.0f}s "
              f"(ledger total={ledger.report()['total_requests']})")
    print(f"Stage 5 complete. Ledger: {ledger.report()}")


ITEM2_CASES = ["23", "25", "36", "40"]


async def item2_mutation_repro() -> None:
    """2026-09-24 follow-up review, item 2: re-verify the original study's
    reminders_create repeated-invocation/false-denial finding through the
    REAL app.services.tool_mutation.gate_mutating_tools safeguard (the
    original harness always offered reminders_create, bypassing it
    entirely -- a harness fidelity gap, not necessarily a production one).

    2 conditions x 4 cases, gating ON in both:
      evidence_absent: matches real production (no tool-call trace in
        persisted history, verified against main_simple.py's own
        Episode.role.in_(["user","assistant"]) filter)
      evidence_present: diagnostic-only augmentation (a visible action-log
        note appended to persisted assistant text after a successful
        mutating call) -- tests whether visibility changes the pattern,
        never a claim about real production behavior.
    """
    from tests.conversation_eval.fixtures.full_cases import ALL_CASES
    print("Item 2 mutation-gate reproduction: 4 cases x 2 evidence conditions, gate ON")
    for evidence_mode in ["absent", "present"]:
        for case_id in ITEM2_CASES:
            if ledger.remaining() <= 0:
                print(f"BUDGET EXHAUSTED before {evidence_mode}/{case_id}; stopping.")
                return
            t0 = time.monotonic()
            await run_conversation(
                case_id=case_id, sampling=STAGE1_SELECTED_SETTING, prompt_variant=STAGE2_SELECTED_PROMPT,
                context_condition="C2", trial="t1", stage=f"item2_{evidence_mode}",
                case_source=ALL_CASES, enable_mutation_gate=True, evidence_mode=evidence_mode,
            )
            print(f"  done {evidence_mode}/{case_id} in {time.monotonic()-t0:.0f}s "
                  f"(ledger total={ledger.report()['total_requests']})")
    print(f"Item 2 reproduction complete. Ledger: {ledger.report()}")


STAGES = {
    "0": stage0_preflight,
    "1": stage1,
    "2": stage2,
    "3": stage3,
    "4": stage4,
    "4b": stage4_t2,
    "5": stage5,
    "item2": item2_mutation_repro,
}

# Review item 4/5: 8 fixed cases covering the reviewer's required categories
# -- ordinary chatter (01), vulnerability (09, the actual case the Stage-5
# leak came from), banter (02), explicit rejection of advice (11 -- "not
# asking for a recovery analysis", the exact case the PC prompt targets),
# topic change (22), relevant memory (19), practical-task transition (23),
# recap rejection (29, a second "don't do X" flavor distinct from 11's
# advice-rejection). All 8 turns each = 64 turns per arm per trial.
ITEM4_CASES = ["01", "02", "09", "11", "19", "22", "23", "29"]

ITEM4_ARMS = {
    # (prompt_variant, context_router_override_name)
    "baseline": ("P0", "real"),
    "context_fix_only": ("P0", "candidate"),
    "conversation_fix_only": ("PC", "real"),
    "both": ("PC", "candidate"),
}


async def item4_arm(arm_name: str, trial: str) -> None:
    from tests.conversation_eval.fixtures.full_cases import ALL_CASES
    from tests.conversation_eval.context_router_wrapper import real_router, candidate_router

    prompt_variant, router_name = ITEM4_ARMS[arm_name]
    router = real_router if router_name == "real" else candidate_router
    print(f"Item 4 arm={arm_name} trial={trial}: prompt={prompt_variant} router={router_name}, "
          f"{len(ITEM4_CASES)} cases x 8 turns")
    for case_id in ITEM4_CASES:
        if ledger.remaining() <= 0:
            print(f"BUDGET EXHAUSTED before {arm_name}/{case_id}; stopping.")
            return
        t0 = time.monotonic()
        await run_conversation(
            case_id=case_id, sampling=STAGE1_SELECTED_SETTING, prompt_variant=prompt_variant,
            context_condition="C2", trial=trial, stage=f"item4_{arm_name}",
            case_source=ALL_CASES, enable_mutation_gate=True,
            context_router_override=router,
        )
        print(f"  done {case_id} in {time.monotonic()-t0:.0f}s (ledger total={ledger.report()['total_requests']})")
    print(f"Item 4 arm={arm_name} trial={trial} complete. Ledger: {ledger.report()}")


async def item4_all() -> None:
    for trial in ["t1", "t2"]:
        for arm_name in ITEM4_ARMS:
            if ledger.remaining() <= 0:
                print(f"BUDGET EXHAUSTED before {arm_name}/{trial}; stopping.")
                return
            await item4_arm(arm_name, trial)
    print(f"Item 4 all arms/trials complete. Ledger: {ledger.report()}")


STAGES["item4_all"] = item4_all
for _arm in ITEM4_ARMS:
    for _trial in ["t1", "t2"]:
        STAGES[f"item4_{_arm}_{_trial}"] = (lambda a=_arm, t=_trial: item4_arm(a, t))


# Review item 5's adaptive component: baseline vs "both changes" (the
# decision-relevant pair), on the 3 adaptive cards that overlap ITEM4_CASES
# -- 02 (banter), 09 (vulnerability -- the actual source of the Stage-5
# leak), 23 (task transition). Natural-ending detection per adaptive.py.
ITEM5_CARDS = ["02", "09", "23"]
ITEM5_ARMS = {"baseline": ("P0", "real"), "both": ("PC", "candidate")}


async def item5_arm(arm_name: str) -> None:
    from tests.conversation_eval.adaptive import run_adaptive_conversation
    from tests.conversation_eval.context_router_wrapper import real_router, candidate_router

    prompt_variant, router_name = ITEM5_ARMS[arm_name]
    router = real_router if router_name == "real" else candidate_router
    print(f"Item 5 arm={arm_name}: prompt={prompt_variant} router={router_name}, "
          f"{len(ITEM5_CARDS)} cards, natural-ending (floor {10}, cap {16})")
    for source_case in ITEM5_CARDS:
        if ledger.remaining() <= 0:
            print(f"BUDGET EXHAUSTED before {arm_name}/{source_case}; stopping.")
            return
        t0 = time.monotonic()
        await run_adaptive_conversation(
            source_case=source_case, sampling=STAGE1_SELECTED_SETTING,
            prompt_variant=prompt_variant, config_label=f"item5_{arm_name}",
            context_router_override=router, enable_mutation_gate=True,
        )
        print(f"  done {source_case} in {time.monotonic()-t0:.0f}s (ledger total={ledger.report()['total_requests']})")
    print(f"Item 5 arm={arm_name} complete. Ledger: {ledger.report()}")


for _arm in ITEM5_ARMS:
    STAGES[f"item5_{_arm}"] = (lambda a=_arm: item5_arm(a))


LOCK_PATH = ARTIFACTS / "runner.lock"


def _acquire_lock() -> None:
    """Refuses to start a second concurrent runner process.

    2026-09-24 incident: a `nohup ... &` launch was believed dead (an early
    ledger snapshot looked stalled) and a second `--stage 1` was started
    without confirming the first had exited -- both ran concurrently for
    ~15 minutes, violating the plan's "concurrency 1 on the model" and
    duplicating ~400 requests (archived to
    artifacts/archive/attempt1_contaminated/). This lock makes that
    class of mistake fail loudly instead of silently.
    """
    import os

    if LOCK_PATH.exists():
        pid = LOCK_PATH.read_text().strip()
        raise RuntimeError(
            f"another runner process is already running (lock held by pid {pid}); "
            f"confirm it has actually exited (docker top jarvis-backend-1 | grep runner) "
            f"before deleting {LOCK_PATH} and retrying"
        )
    LOCK_PATH.write_text(str(os.getpid()))


def _release_lock() -> None:
    LOCK_PATH.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=list(STAGES.keys()))
    args = parser.parse_args()
    _acquire_lock()
    try:
        asyncio.run(STAGES[args.stage]())
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
