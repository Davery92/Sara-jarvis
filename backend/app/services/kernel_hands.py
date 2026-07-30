"""
Kernel-hands (work-order item 11, 2026-07-30): lane-routed tool execution
for the kernel's ambient cognition.

The selves=1 daemon cutover (Arc 3.3) retired the VM daemon's own
Mind.think()/reflect() loop in favor of proxying to kernel.ambient_turn().
That loop could call 15 tools inline mid-turn — web research, notes,
goals/interests, Proxmox sandboxes — real, actively-used capability (1200+
historical calls, several tools active within days of the cutover). The
kernel's deliberation_engine.run() is a single structured-JSON call with no
tool-calling loop, so that capability had no kernel-side equivalent — an
open gap the cutover flagged rather than silently dropped. This module,
plus the KERNEL_HANDS-gated single tool_call field in DeliberationResult,
is the resolution.

David's pre-authorized trust lanes (verbatim, 2026-07-30):
  - read-only tools (search, memory, notes-read, list/goal reads)
    -> autonomous at current trust
  - reversible writes (notes-write, interests/goals touch, journal)
    -> autonomous with ledger entry
  - anything irreversible or resource-creating (container provisioning,
    external sends, deletes) -> propose-first, no exceptions
  - a tool that doesn't fit cleanly into a lane defaults to a focused-turn
    mission, not an ambient action
  - a tool with zero calls in the last 90 days doesn't get migrated —
    list it as retired and let mind.py's deletion take it

Profiled 2026-07-30 (sara_activity_log, all-time + 90-day windows):
destroy_container and bump_interest never had a single call in the entire
history of the daemon — retired, not migrated. The other 15 are lane-
mapped below. exec_in_container joins provision_container in the
propose-first lane, matching the old Mind class's own _SUBSTANTIVE_VM_
TOOLS gate (the two it already treated as higher-stakes than the rest).

Reuses the SAME real backend implementations Mind.think() called over
HTTP (app/routes/acs_daemon_tools.py) — invoking the handler functions
directly in-process now that we're already inside the backend, no HTTP
round-trip needed.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

READ_ONLY_TOOLS = {
    "web_search", "web_fetch", "search_notes", "search_memory",
    "list_goals", "list_interests", "list_containers", "node_status",
}
REVERSIBLE_WRITE_TOOLS = {
    "write_note", "add_interest", "touch_interest", "create_goal", "update_goal",
}
PROPOSE_FIRST_TOOLS = {
    "provision_container", "exec_in_container",
}
# Zero calls ever (not just zero in 90 days) at the point of migration —
# retired per David's rule, not given kernel-hands support.
RETIRED_TOOLS = {"destroy_container", "bump_interest"}

_LANES: Dict[str, str] = {
    **{t: "read" for t in READ_ONLY_TOOLS},
    **{t: "write" for t in REVERSIBLE_WRITE_TOOLS},
    **{t: "propose" for t in PROPOSE_FIRST_TOOLS},
}


def lane_for(tool_name: str) -> Optional[str]:
    """'read' | 'write' | 'propose' | 'retired' | None (unknown tool —
    caller should route it as a focused-turn mission, not an ambient
    action, per David's default-lane rule)."""
    if tool_name in RETIRED_TOOLS:
        return "retired"
    return _LANES.get(tool_name)


async def _call_tool_handler(tool_name: str, args: Dict[str, Any]) -> Any:
    """Invoke the real route handler directly — same Pydantic input model
    validation the daemon's HTTP call used to get for free, just without
    the round-trip."""
    from app.routes import acs_daemon_tools as t

    dispatch = {
        "web_search": (t.web_search, t.WebSearchIn),
        "web_fetch": (t.web_fetch, t.WebFetchIn),
        "search_notes": (t.search_notes_endpoint, t.SearchNotesIn),
        "search_memory": (t.search_memory, t.SearchMemoryIn),
        "list_goals": (t.list_goals_tool, t.ListGoalsIn),
        "list_interests": (t.list_interests_tool, t.ListInterestsIn),
        "list_containers": (t.list_containers, t.ListContainersIn),
        "node_status": (t.node_status, t.NodeStatusIn),
        "write_note": (t.write_note, t.WriteNoteIn),
        "add_interest": (t.add_interest_tool, t.AddInterestIn),
        "touch_interest": (t.touch_interest_tool, t.InterestIdIn),
        "create_goal": (t.create_goal_tool, t.CreateGoalIn),
        "update_goal": (t.update_goal_tool, t.UpdateGoalIn),
    }
    if tool_name not in dispatch:
        raise ValueError(f"no handler wired for {tool_name!r}")
    handler, input_model = dispatch[tool_name]
    payload = input_model(**args)
    result = await handler(payload)
    return result.model_dump() if hasattr(result, "model_dump") else result


async def _ledger(tool_name: str, args: Dict[str, Any], *, result: Any = None, error: Optional[str] = None) -> None:
    """Same activity-log shape Mind.think()'s tool_call/tool_result entries
    used (dedup + audience classification included, free) — keeps
    continuity with existing history/queries, just sourced from the
    kernel instead of the daemon."""
    try:
        import json as _json
        from app.routes.acs_daemon import append_activity, ActivityIn
        summary = f"{tool_name}(...)" + (" → error" if error else "")
        body = (_json.dumps(result, default=str)[:8000] if result is not None
                else (error or "")[:8000])
        await append_activity(ActivityIn(
            kind="tool_result",
            summary=summary[:500],
            body=body,
            tags=["error"] if error else [],
            metadata={"tool": tool_name, "args": args, "source": "kernel_hands", "error": error},
        ))
    except Exception as e:
        logger.debug(f"[kernel_hands] ledger write skipped for {tool_name}: {e}")


async def _propose_first(tool_name: str, args: Dict[str, Any], user_id: str, reason: str) -> Dict[str, Any]:
    """Irreversible/resource-creating tools never execute from the kernel —
    they become a real say_candidate through the normal judge -> compose ->
    review -> deliver pipeline, same as everything else Sara says.
    Deliberately does NOT auto-execute even if David later approves in
    chat — reconnecting an approval to actual execution is real follow-up
    work, not built in this pass (flagged in SARA_ALIVE_BUILD_PLAN)."""
    try:
        from app.db.session import get_async_session_factory
        from app.services.say_candidate import create_candidate
        args_str = ", ".join(f"{k}={v}" for k, v in args.items())
        factory = get_async_session_factory()
        async with factory() as db:
            candidate_id = await create_candidate(
                db, user_id=user_id, source="kernel_hands", kind="inform",
                summary=f"I'd like to {tool_name}({args_str}) — {reason or 'came up during an ambient turn'}",
                evidence=[reason] if reason else [],
                topic_entities=[tool_name],
                value_guess=0.5,
                dedupe_key=f"kernel_hands:{tool_name}:{args_str}"[:200],
            )
        if candidate_id is None:
            return {"status": "duplicate_suppressed"}
        await _ledger(tool_name, args, result={"proposed": True, "candidate_id": str(candidate_id)})
        return {"status": "proposed", "candidate_id": str(candidate_id)}
    except Exception as e:
        logger.warning(f"[kernel_hands] propose-first write failed for {tool_name}: {e}")
        return {"status": "error", "error": str(e)}


async def execute_kernel_tool(
    tool_name: str, args: Dict[str, Any], user_id: str, *, reason: str = "",
) -> Dict[str, Any]:
    """The one entry point deliberation_gate calls. Never raises — errors
    come back as {"status": "error", ...} so a bad tool call degrades the
    turn instead of crashing it (same discipline as every other best-
    effort block in the deliberation pipeline)."""
    lane = lane_for(tool_name)

    if lane is None:
        return {
            "status": "no_lane",
            "detail": f"{tool_name!r} doesn't fit a trust lane — route as a focused-turn mission, not an ambient action",
        }
    if lane == "retired":
        return {"status": "retired", "detail": f"{tool_name!r} had zero calls ever at migration — not available"}
    if lane == "propose":
        return await _propose_first(tool_name, args, user_id, reason)

    try:
        result = await _call_tool_handler(tool_name, args)
    except Exception as e:
        logger.warning(f"[kernel_hands] {tool_name} failed: {e}")
        await _ledger(tool_name, args, error=str(e))
        return {"status": "error", "error": str(e)}

    await _ledger(tool_name, args, result=result)
    return {"status": "ok", "result": result}
