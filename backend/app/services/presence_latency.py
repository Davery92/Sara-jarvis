"""
Presence latency (Arc 6.1, work-order item 6) — "the three-speed contract,
enforced." Presence (chat persona) has a real budget: <2s to first token.
This is the timing-assertion + red-line half of that: black-box measured
from outside the streaming generator (start of the request to the first
real content chunk yielded), not by threading a timer through main_simple.
py's chat_stream internals — the same number the plan's own baseline
("85s first token") was framed around, and the only measurement that
actually reflects what David experiences.

Same Redis-as-operational-telemetry precedent as `system:health_status`
(the heartbeat's health dict) — not a new memory/fact store, a rolling
operational signal for the Interior to render.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

PRESENCE_BUDGET_SECONDS = 2.0
_RECENT_KEY = "sara:presence_latency:recent"
_LAST_BREACH_KEY = "sara:presence_latency:last_breach"
_RECENT_MAX = 50


async def record_first_token_latency(elapsed_seconds: float) -> None:
    """Call once per chat_stream turn, on the first real content chunk
    yielded. Best-effort — a Redis hiccup must never affect the actual
    chat response, so failures here only log."""
    try:
        from app.services.unified_context import _get_redis
        r = await _get_redis()

        entry = json.dumps({"at": local_now().isoformat(), "elapsed": round(elapsed_seconds, 3)})
        await r.lpush(_RECENT_KEY, entry)
        await r.ltrim(_RECENT_KEY, 0, _RECENT_MAX - 1)

        if elapsed_seconds > PRESENCE_BUDGET_SECONDS:
            logger.warning(
                f"🔴 [three-speed] presence RED LINE breached: "
                f"{elapsed_seconds:.2f}s > {PRESENCE_BUDGET_SECONDS}s budget"
            )
            await r.set(_LAST_BREACH_KEY, json.dumps({
                "at": local_now().isoformat(),
                "elapsed": round(elapsed_seconds, 3),
                "budget": PRESENCE_BUDGET_SECONDS,
            }))
        else:
            logger.info(f"⏱️ [three-speed] presence first-token: {elapsed_seconds:.2f}s")
    except Exception as e:
        logger.debug(f"[presence_latency] record failed (non-critical): {e}")


async def get_presence_latency_status(user_id: Optional[str] = None) -> Dict[str, Any]:
    """For the Interior (`/mind/self`). p50/p90 over the last <=50 real
    turns, plus the most recent budget breach if any (None if the last
    breach predates the current rolling window's oldest surviving
    sample — an old, aged-out breach shouldn't read as a current red
    line)."""
    try:
        from app.services.unified_context import _get_redis
        r = await _get_redis()

        raw_recent = await r.lrange(_RECENT_KEY, 0, _RECENT_MAX - 1)
        samples: List[float] = []
        for item in raw_recent:
            try:
                samples.append(json.loads(item)["elapsed"])
            except Exception:
                continue
        samples_sorted = sorted(samples)

        def _pct(p: float) -> Optional[float]:
            if not samples_sorted:
                return None
            idx = min(len(samples_sorted) - 1, int(len(samples_sorted) * p))
            return round(samples_sorted[idx], 3)

        last_breach = None
        raw_breach = await r.get(_LAST_BREACH_KEY)
        if raw_breach:
            try:
                candidate = json.loads(raw_breach)
                # Only report it as current if it's still within the
                # rolling sample window (by count, since we don't retain
                # timestamps on the trimmed-out entries) — otherwise a
                # single breach from days ago would read as a permanent
                # red flag on the Interior forever.
                if raw_recent and any(
                    json.loads(item).get("at") == candidate.get("at") for item in raw_recent
                ):
                    last_breach = candidate
            except Exception:
                pass

        return {
            "budget_seconds": PRESENCE_BUDGET_SECONDS,
            "sample_count": len(samples_sorted),
            "p50": _pct(0.5),
            "p90": _pct(0.9),
            "red_line": last_breach is not None,
            "last_breach": last_breach,
        }
    except Exception as e:
        logger.debug(f"[presence_latency] status read failed (non-critical): {e}")
        return {
            "budget_seconds": PRESENCE_BUDGET_SECONDS,
            "sample_count": 0,
            "p50": None,
            "p90": None,
            "red_line": False,
            "last_breach": None,
        }
