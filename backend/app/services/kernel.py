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
    return {"state": KernelState.AMBIENT.value, "wake_reason": None, "detail": None, "at": None}


async def ambient_turn(
    user_id: str = DEFAULT_USER_ID,
    wake_reason: WakeReason = WakeReason.PROMOTED_EVENT,
    deep: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """The single ambient-state cognition entry. All background thinking —
    deliberation, check-ins, anticipation, the daemon's think — resolves here,
    so there is one prompt-identity, one memory, one voice.

    Delegates to the deliberation engine (the ambient reasoner) + gate today.
    `force` skips the should_deliberate rate/threshold check (used by scheduled
    anchors and the daemon proxy, which have already decided to think).

    Returns the deliberation summary plus the kernel state/wake-reason it ran in.
    """
    from app.services.autonomy.coordination import get_coordinator

    coordinator = get_coordinator()
    if not await coordinator.acquire_exclusive("deliberation", "heavy_llm"):
        return {"skipped": "exclusive_group_busy", "state": KernelState.AMBIENT.value}

    try:
        if not force:
            from app.services.salience import salience_scorer
            if not await salience_scorer.should_deliberate(user_id):
                return {"skipped": "below_threshold", "state": KernelState.AMBIENT.value}

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
                                "wake_reason": wake_reason.value}
                except Exception as _re:
                    pass  # fail-open: fall through to full deliberation

        await set_state(user_id, KernelState.AMBIENT, wake_reason,
                        detail=f"thinking ({wake_reason.value})")

        from app.services.deliberation import deliberation_engine
        from app.services.deliberation_gate import process_deliberation_result

        result = await deliberation_engine.run(user_id, deep=deep)
        summary = await process_deliberation_result(result, user_id)

        # Return to a resting ambient state once the turn completes.
        await set_state(user_id, KernelState.AMBIENT, None, detail="resting")

        return {
            "status": "completed",
            "state": KernelState.AMBIENT.value,
            "wake_reason": wake_reason.value,
            "thought": (result.thought or "")[:200],
            "notifications": summary["notifications_sent"],
            "home_actions": summary["home_actions_executed"],
            "observations_consumed": summary["observations_consumed"],
            "duration": result.duration_seconds,
        }
    finally:
        await coordinator.release_exclusive("heavy_llm", "deliberation")
