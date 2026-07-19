"""Reflex triage — the fast half of the reflex/ponder split (Phase 5.5).

Full deliberation on the local 27B measures 53–61s. That's fine for pondering,
wrong for reacting: a light turning on shouldn't spin up a minute of thought. So
for event-driven (PROMOTED_EVENT) wakes we first ask the fast A3B, in 2–3s,
whether this is worth Sara's full attention. It answers DROP (nothing to do) or
ESCALATE (worth the slow think). Cortana answers in a beat; the minute-long
think is for when it matters.

Fail-open: any error → ESCALATE (never silently drop a real signal).
"""
from __future__ import annotations

import logging
import os
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

Verdict = Literal["drop", "escalate"]

_SYSTEM = (
    "You are Sara's fast reflex. You get a short list of things that just happened. "
    "Decide if any of it is worth Sara's full, careful attention *right now* (a minute "
    "of deliberation), or if it's routine/ambient and can be noted without a full think. "
    "Reply with ONE word: ESCALATE (worth a full think) or DROP (routine, no action). "
    "Bias toward DROP for single routine home events (a light, a lock, a sensor). "
    "Bias toward ESCALATE for anything about David's plans, health, messages, or anomalies."
)


def _cfg():
    from app.core.config import settings
    url = getattr(settings, "reflex_model_url", None) or os.getenv("FAST_MODEL_URL", "http://10.185.1.8:8686/v1")
    model = getattr(settings, "reflex_model", None) or os.getenv("FAST_MODEL", "qwen3.6-35b-a3b")
    enabled = getattr(settings, "reflex_enabled", True)
    return url, model, enabled


async def reflex_triage(user_id: str, max_obs: int = 8) -> Verdict:
    """Return 'drop' or 'escalate' for the current pending observations."""
    url, model, enabled = _cfg()
    if not enabled:
        return "escalate"
    try:
        from app.services.observation_log import get_pending_observations
        obs = await get_pending_observations(user_id)
    except Exception as e:
        logger.debug(f"[reflex] could not read observations: {e}")
        return "escalate"

    if not obs:
        return "drop"

    # Build a tight summary — one line per observation.
    lines = []
    for o in obs[:max_obs]:
        summ = (getattr(o, "summary", None) or getattr(o, "content", None)
                or (o.get("summary") if isinstance(o, dict) else None) or str(o))
        lines.append(f"- {str(summ)[:140]}")
    prompt = "Things that just happened:\n" + "\n".join(lines)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=2.0)) as c:
            r = await c.post(f"{url.rstrip('/')}/chat/completions", json={
                "model": model,
                "messages": [{"role": "system", "content": _SYSTEM},
                             {"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": 4,
                "chat_template_kwargs": {"enable_thinking": False},
            })
            r.raise_for_status()
            txt = (r.json().get("choices", [{}])[0].get("message", {}).get("content", "") or "").upper()
    except Exception as e:
        logger.debug(f"[reflex] triage call failed, escalating: {e}")
        return "escalate"

    verdict: Verdict = "drop" if "DROP" in txt and "ESCALATE" not in txt else "escalate"
    logger.info(f"[reflex] {len(obs)} obs -> {verdict} ({txt.strip()[:20]!r})")
    return verdict
