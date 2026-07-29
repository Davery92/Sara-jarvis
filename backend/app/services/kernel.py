"""
The Kernel — one consciousness, four states (ONE_MIND §3.3).

The organizing principle of ONE_MIND is that everything which thinks on Sara's
behalf is *one mind in a different state*, not a federation of departments each
with its own loop, prompt, and self-narrative. This module is the single named
surface for that mind. It grows out of `deliberation.py` (the ambient reasoner)
rather than replacing it: today `ambient_turn()` delegates to the existing
deliberation engine, so there is zero behaviour change — but every background
thought now flows through one entry point with an explicit *state* and
*wake-reason*, which is what later phases fold the check-in / anticipation /
idle / daemon loops into instead of running parallel selves.

Four states (different budgets, same identity/memory/voice):
  • ENGAGED   — David present (chat, voice, app foregrounded)
  • AMBIENT   — the background hum: deliberation, check-ins, anticipation, the
                daemon's think — all one turn, one prompt
  • FOCUSED   — long-running missions (research, code, workspace jobs)
  • DREAMING  — consolidation, reflection, forgetting, overnight work

The live state + wake-reason are published to Redis so surfaces (the honest
orb, the greeting, Sara's Interior) can show the *real* state of the one mind
rather than guessing. selves=1 (ONE_MIND §5): the sara-VM daemon proxies its
tick to `ambient_turn(wake_reason=DAEMON_PROXY)` instead of running its own
567-line prompt-identity.
"""

import json
import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

_STATE_KEY = "kernel:state:{user_id}"
_STATE_TTL = 3600  # a live-state readout; refreshed on every turn


class KernelState(str, Enum):
    ENGAGED = "engaged"
    AMBIENT = "ambient"
    FOCUSED = "focused"
    DREAMING = "dreaming"


class WakeReason(str, Enum):
    """Why the mind woke for an ambient turn — the taxonomy that replaces
    'cognition wearing a cron costume' (ONE_MIND §3.3 scheduler diet). Each
    former deliberation/check-in/anticipation/idle job becomes one of these."""
    PROMOTED_EVENT = "promoted_event"     # salience threshold crossed (event-driven)
    SLEEP_PRESSURE = "sleep_pressure"     # idle floor — adaptive cadence (ACS2)
    SCHEDULED_ANCHOR = "scheduled_anchor"  # morning / evening anchor
    INTEROCEPTION = "interoception"       # a body/vital changed (§3.1, Phase 1)
    CHECKIN = "checkin"                   # proactive check-in / follow-up sweep
    ANTICIPATION = "anticipation"         # look-ahead
    DAEMON_PROXY = "daemon_proxy"         # the VM body's tick, proxied (selves=1)
    MANUAL = "manual"                     # explicitly requested (debug / user)


# Arc 3.1: which wake reasons default to the deep (strong-model, wider
# observation window) budget when a caller doesn't pass `deep` explicitly.
# Only the twice-daily scheduled anchor gets the heavier pass by default —
# everything else is the routine hourly-cadence budget. Explicit `deep=`
# always wins; this is only the fallback so wake_reason has one source of
# truth for budget instead of two independently-passed params.
_WAKE_REASON_DEFAULT_DEEP = {WakeReason.SCHEDULED_ANCHOR}


async def _redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True
    )


async def set_state(
    user_id: str,
    state: KernelState,
    wake_reason: Optional[WakeReason] = None,
    detail: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> None:
    """Publish the live kernel state so surfaces can read the one mind's real
    condition (honest orb / greeting / Interior). Best-effort."""
    try:
        r = await _redis()
        payload = {
            "state": state.value,
            "wake_reason": wake_reason.value if wake_reason else None,
            "detail": detail,
            "at": datetime.now(timezone.utc).isoformat(),
            "correlation_id": correlation_id,
        }
        await r.set(_STATE_KEY.format(user_id=user_id), json.dumps(payload), ex=_STATE_TTL)
        try:
            await r.close()
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"[kernel] set_state failed: {e}")


async def get_state(user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """Return the live kernel state, or a resting default."""
    try:
        r = await _redis()
        raw = await r.get(_STATE_KEY.format(user_id=user_id))
        try:
            await r.close()
        except Exception:
            pass
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.debug(f"[kernel] get_state failed: {e}")
    return {"state": KernelState.AMBIENT.value, "wake_reason": None, "detail": None, "at": None,
            "correlation_id": None}


async def ambient_turn(
    user_id: str = DEFAULT_USER_ID,
    wake_reason: WakeReason = WakeReason.PROMOTED_EVENT,
    deep: Optional[bool] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """The single ambient-state cognition entry. All background thinking —
    deliberation, check-ins, anticipation, the daemon's think — resolves here,
    so there is one prompt-identity, one memory, one voice.

    Delegates to the deliberation engine (the ambient reasoner) + gate today.
    `force` skips the should_deliberate rate/threshold check (used by scheduled
    anchors and the daemon proxy, which have already decided to think).

    Arc 3.1 (2026-07-29): `wake_reason` shapes this turn's *context and
    budget* — never a different cognition. If `deep` isn't given explicitly,
    it's derived from `wake_reason` (`_WAKE_REASON_DEFAULT_DEEP`) so budget
    has one source of truth instead of two independently-passed params that
    happen to agree at every call site today. `wake_reason` is also threaded
    into the deliberation prompt as one line of context (why the mind woke),
    so a routine safety-net pass reads differently from a promoted event
    without a second prompt or a dispatch branch.

    Returns the deliberation summary plus the kernel state/wake-reason it ran in.
    """
    if deep is None:
        deep = wake_reason in _WAKE_REASON_DEFAULT_DEEP

    from app.services.autonomy.coordination import get_coordinator
    from app.core.correlation import CorrelationIds, bind_correlation, new_id

    # Mint one kernel_turn_id for this turn and bind it so anything this turn
    # calls (deliberation, the gate, notification sends) can pick it up from
    # `get_current_correlation()` without threading it through every signature
    # (SINGULAR_SARA §C0/§C1 — one correlation spine per causal chain).
    kernel_turn_id = new_id("turn")
    bind_correlation(CorrelationIds(kernel_turn_id=kernel_turn_id))

    # Every call that reaches the kernel is, by definition, the *target*
    # ambient-cognition path (SINGULAR_SARA §C0 path counters) — the direct
    # `deliberation_engine.run()` call sites still in `app/tasks/autonomy.py`
    # that bypass this function record "legacy" instead.
    try:
        from app.services.legacy_path_counters import record_target_path
        await record_target_path("ambient_cognition")
    except Exception:
        pass

    coordinator = get_coordinator()
    if not await coordinator.acquire_exclusive("deliberation", "heavy_llm"):
        return {"skipped": "exclusive_group_busy", "state": KernelState.AMBIENT.value,
                "correlation_id": kernel_turn_id}

    try:
        if not force:
            from app.services.salience import salience_scorer
            if not await salience_scorer.should_deliberate(user_id):
                return {"skipped": "below_threshold", "state": KernelState.AMBIENT.value,
                        "correlation_id": kernel_turn_id}

            # Reflex/ponder split (Phase 5.5): for event-driven wakes, a 2-3s A3B
            # triage decides whether this deserves the minute-long full deliberation.
            # Routine home events get DROPped here instead of spinning up the 27B.
            if wake_reason == WakeReason.PROMOTED_EVENT and not deep:
                try:
                    from app.services.reflex import reflex_triage
                    verdict = await reflex_triage(user_id)
                    if verdict == "drop":
                        # finally releases the coordinator.
                        return {"skipped": "reflex_drop", "state": KernelState.AMBIENT.value,
                                "wake_reason": wake_reason.value, "correlation_id": kernel_turn_id}
                except Exception as _re:
                    pass  # fail-open: fall through to full deliberation

        await set_state(user_id, KernelState.AMBIENT, wake_reason,
                        detail=f"thinking ({wake_reason.value})", correlation_id=kernel_turn_id)

        from app.services.deliberation import deliberation_engine
        from app.services.deliberation_gate import process_deliberation_result

        result = await deliberation_engine.run(user_id, deep=deep, wake_reason=wake_reason.value)
        summary = await process_deliberation_result(result, user_id)

        # Return to a resting ambient state once the turn completes.
        await set_state(user_id, KernelState.AMBIENT, None, detail="resting", correlation_id=kernel_turn_id)

        return {
            "status": "completed",
            "state": KernelState.AMBIENT.value,
            "wake_reason": wake_reason.value,
            "thought": (result.thought or "")[:200],
            "notifications": summary["notifications_sent"],
            "home_actions": summary["home_actions_executed"],
            "observations_consumed": summary["observations_consumed"],
            "tasks_dispatched": summary.get("tasks_dispatched", 0),
            "tasks_proposed": summary.get("tasks_proposed", 0),
            "duration": result.duration_seconds,
            "correlation_id": kernel_turn_id,
        }
    finally:
        await coordinator.release_exclusive("heavy_llm", "deliberation")


async def engaged_turn(
    user_id: str = DEFAULT_USER_ID,
    conversation_id: Optional[str] = None,
    message_preview: str = "",
) -> Dict[str, Any]:
    """The single engaged-state cognition entry (§4.4).

    SHADOW ONLY today: assembles the same context packet a real chat turn
    would need — canonical context snapshot (world/self/relationship),
    open-intent count, and a `memory.recall()` pass seeded with the latest
    message — and returns it. Nothing consumes this output yet; the live
    `/chat/stream` handler calls this fire-and-forget, behind the
    `SINGULAR_KERNEL` flag (default OFF), purely to prove the assembly is
    correct against real conversations before anything depends on it. It
    does not touch tool routing, streaming, or the response David sees.
    """
    from app.core.correlation import CorrelationIds, bind_correlation, new_id
    from app.services.legacy_path_counters import record_target_path

    kernel_turn_id = new_id("turn")
    bind_correlation(CorrelationIds(kernel_turn_id=kernel_turn_id))
    await set_state(user_id, KernelState.ENGAGED, detail="shadow context assembly",
                    correlation_id=kernel_turn_id)

    try:
        await record_target_path("engaged_cognition")
    except Exception:
        pass

    context: Dict[str, Any] = {}
    open_intents = 0
    recall_traces = 0

    try:
        from app.db.session import SessionLocal
        from app.services.context_snapshot import get_context_snapshot
        from app.services.intent_graph_projection import get_intent_graph

        db = SessionLocal()
        try:
            context = await get_context_snapshot(db, user_id)
            open_intents = get_intent_graph(db, user_id)["total"]
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"[kernel] engaged_turn context assembly failed: {e}")

    try:
        from app.services.memory_recall import recall as memory_recall
        recalled = await memory_recall(user_id=user_id, query=message_preview or "", k=5)
        recall_traces = len(recalled.get("traces") or [])
    except Exception as e:
        logger.debug(f"[kernel] engaged_turn recall failed: {e}")

    await set_state(user_id, KernelState.ENGAGED, detail="resting", correlation_id=kernel_turn_id)

    return {
        "state": KernelState.ENGAGED.value,
        "correlation_id": kernel_turn_id,
        "conversation_id": conversation_id,
        "context": context,
        "open_intents": open_intents,
        "recall_traces": recall_traces,
    }


async def dreaming_turn(user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """The single dreaming-state cognition entry (§4.4/§C6).

    Wraps the existing reflection agent's cycle (pattern detection, proposal
    generation) under one kernel state and correlation ID — the same
    fold-in pattern C5 used for ambient cognition. Flag-gated by
    `SINGULAR_KERNEL` in `app.tasks.reflection._run_reflection_async`; when
    the flag is off (default), that task calls the reflection agent
    directly and this function is never invoked.

    Deliberately does not touch `run_consolidation` or `run_dream_cycle` —
    those are the deterministic maintenance pipelines §C6 explicitly says to
    keep separate from cognition ("Keep deterministic maintenance jobs
    separate from cognition"). Only the LLM-driven reflection/proposal step
    is cognition in the kernel's sense.
    """
    from app.core.correlation import CorrelationIds, bind_correlation, new_id
    from app.services.legacy_path_counters import record_target_path

    kernel_turn_id = new_id("turn")
    bind_correlation(CorrelationIds(kernel_turn_id=kernel_turn_id))
    await set_state(user_id, KernelState.DREAMING, detail="reflection cycle", correlation_id=kernel_turn_id)

    try:
        await record_target_path("dreaming_cognition")
    except Exception:
        pass

    from app.db.session import get_async_session_factory
    from app.services.reflection.agent import get_reflection_agent

    async_session = get_async_session_factory()
    async with async_session() as db:
        reflection_agent = await get_reflection_agent(db)
        result = await reflection_agent.run_reflection_cycle()
        result_dict = result.to_dict()

    await set_state(user_id, KernelState.DREAMING, detail="resting", correlation_id=kernel_turn_id)

    return {
        "state": KernelState.DREAMING.value,
        "correlation_id": kernel_turn_id,
        **result_dict,
    }


async def focused_turn(
    db,
    user_id: str = DEFAULT_USER_ID,
    *,
    task_description: str,
    mode: str = "auto",
    working_directory: Optional[str] = None,
    notify_on_complete: bool = False,
    target_host: Optional[str] = None,
) -> Dict[str, Any]:
    """The single focused-state cognition entry (§4.4/§C7).

    Wraps the existing mission-dispatch pipeline
    (`agent_dispatch_service.dispatch_task` — VM Claude/Qwen sessions,
    resumable via `resume_task`/`retry_task`, already durable across backend
    restarts per the "Durable dispatch" project) under one kernel state and
    correlation ID, the same fold-in pattern used for ambient/dreaming. The
    dispatch pipeline itself is untouched: this brackets it with
    ENGAGED->FOCUSED state publication (visible in Interior) and binds the
    correlation ID so anything the mission does downstream (notifications,
    action receipts) can be traced back to the turn that started it.

    Does not itself evaluate mission outcomes — the mission runs
    asynchronously on the VM/Celery `dispatch` queue after this call
    returns with a task_id; outcome evaluation happens where it already
    does (`agent_dispatch_service._notify_completion` /
    `unified_notification`), not synchronously inside this function.
    """
    from app.core.correlation import CorrelationIds, bind_correlation, new_id
    from app.services.legacy_path_counters import record_target_path

    kernel_turn_id = new_id("turn")
    bind_correlation(CorrelationIds(kernel_turn_id=kernel_turn_id))
    await set_state(user_id, KernelState.FOCUSED, detail="dispatching mission", correlation_id=kernel_turn_id)

    try:
        await record_target_path("focused_cognition")
    except Exception:
        pass

    from app.services.agent_dispatch import agent_dispatch_service

    try:
        result = await agent_dispatch_service.dispatch_task(
            db=db,
            user_id=user_id,
            task_description=task_description,
            mode=mode,
            working_directory=working_directory,
            notify_on_complete=notify_on_complete,
            target_host=target_host,
        )
    finally:
        await set_state(user_id, KernelState.AMBIENT, detail="resting", correlation_id=kernel_turn_id)

    result["correlation_id"] = kernel_turn_id
    return result
