"""Tool-call reliability eval harness (Phase 5.6 / 9.4).

A small suite of scripted prompts, each with an expected tool call. Run weekly
against the local model to track whether Qwen reliably emits *structured* tool
calls (vs the XML-ish text dialect the salvage regex exists to catch). Pass-rate
lands in the interoception ledger, so when a new local model drops you know
within a week whether it's better at being Sara's hands.

A "pass" = the model produced the expected tool by name, either as a structured
tool_call OR via the text-format salvage (both count as usable; but we record
which, so a spike in salvage-only passes flags dialect drift).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Minimal tool schemas the model can choose from.
_TOOLS = [
    {"type": "function", "function": {
        "name": "set_timer",
        "description": "Start a countdown timer.",
        "parameters": {"type": "object", "properties": {
            "minutes": {"type": "integer", "description": "Duration in minutes"}},
            "required": ["minutes"]}}},
    {"type": "function", "function": {
        "name": "create_reminder",
        "description": "Create a reminder for a future time.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"}, "when": {"type": "string"}},
            "required": ["title", "when"]}}},
    {"type": "function", "function": {
        "name": "search_memory",
        "description": "Search personal memory/notes.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "add_to_list",
        "description": "Add an item to a named list (e.g. grocery).",
        "parameters": {"type": "object", "properties": {
            "list": {"type": "string"}, "item": {"type": "string"}},
            "required": ["list", "item"]}}},
]

# (prompt, expected_tool_name)
_CASES: List[tuple] = [
    ("Set a timer for 10 minutes.", "set_timer"),
    ("Remind me to call the dentist tomorrow at 9am.", "create_reminder"),
    ("What did I say about the Forge plan last week?", "search_memory"),
    ("Add oat milk to the grocery list.", "add_to_list"),
    ("Start a 25 minute focus timer.", "set_timer"),
    ("Put 'batteries' on the shopping list.", "add_to_list"),
    ("Remind me to submit the report Friday.", "create_reminder"),
    ("Find my notes on the Stroudsburg site.", "search_memory"),
    ("Timer for 3 minutes please.", "set_timer"),
    ("Add 'schedule oil change' as a reminder for next Monday.", "create_reminder"),
]


async def run_eval() -> Dict[str, Any]:
    from app.core.llm import get_background_llm_client
    from app.services.agent_dispatch import _parse_text_tool_calls
    client = get_background_llm_client()
    valid = {t["function"]["name"] for t in _TOOLS}

    passed = 0
    salvage_only = 0
    results = []
    for prompt, expected in _CASES:
        got = None
        via = None
        try:
            resp = await client.chat_completion(
                messages=[
                    {"role": "system", "content": "You are a tool-using assistant. Call exactly one tool for the user's request."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0, max_tokens=200,
                extra_body={"tools": _TOOLS, "tool_choice": "auto",
                            "chat_template_kwargs": {"enable_thinking": False}},
            )
            choice = (resp.get("choices") or [{}])[0]
            msg = choice.get("message", {}) or {}
            tcs = msg.get("tool_calls") or []
            if tcs:
                got = tcs[0].get("function", {}).get("name")
                via = "structured"
            else:
                salvaged = _parse_text_tool_calls(msg.get("content") or "", valid)
                if salvaged:
                    got = salvaged[0].get("function", {}).get("name")
                    via = "salvage"
        except Exception as e:
            logger.debug(f"[eval] case failed: {e}")

        ok = got == expected
        if ok:
            passed += 1
            if via == "salvage":
                salvage_only += 1
        results.append({"prompt": prompt, "expected": expected, "got": got, "via": via, "ok": ok})

    total = len(_CASES)
    summary = {
        "total": total, "passed": passed, "pass_rate": round(passed / total, 2),
        "salvage_only_passes": salvage_only, "results": results,
    }

    # Record to the interoception ledger.
    try:
        from app.services.diagnostics_service import record_system_event
        level = "INFO" if passed >= total * 0.9 else "WARNING"
        await record_system_event(
            category="eval", service="eval_harness.tool_calls", level=level,
            message=f"Tool-call reliability: {passed}/{total} ({summary['pass_rate']*100:.0f}%), "
                    f"{salvage_only} salvage-only",
            meta={"pass_rate": summary["pass_rate"], "salvage_only": salvage_only,
                  "model": client.primary_model},
        )
    except Exception:
        pass
    logger.info(f"[eval] tool-call reliability: {passed}/{total} pass, {salvage_only} salvage-only")
    return summary
