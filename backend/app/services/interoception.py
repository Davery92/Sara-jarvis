"""Interoception / internal-clock header — Brain Alignment H6.

One generated, single-sourced line prepended to every chat and deliberation
prompt so Sara never has to *infer* the time, David's availability, her own
emotional state, or how much she's already interrupted him today. The
circadian/proprioceptive sense a mind has for free.

Single source of truth: the working-memory snapshot (already maintained by
context_writer). No caller hand-writes any of these values.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _notif_cap() -> int:
    """Soft daily notification cap for the 'sent today vs cap' readout."""
    try:
        from app.services.tunables import get_tunable_int
        return get_tunable_int("notification.daily_soft_cap", 8)
    except Exception:
        return 8


async def build_interoception_header(user_id: str) -> Optional[str]:
    """Build the one-line clock + interoception header from working memory.

    Returns e.g.:
      "Now: Tuesday 2026-07-08 15:04 ET. David: available (interruptibility 0.72).
       You feel: curious (0.41). Notifications sent today: 2/8."
    """
    from app.core.timezone import now as local_now

    now = local_now()
    clock = now.strftime("%A %Y-%m-%d %H:%M ET")

    activity = "unknown"
    interruptibility = None
    tone = None
    intensity = None
    notifs = None
    try:
        from app.services.working_memory import read_memory
        snap = await read_memory(user_id)
        if snap:
            activity = (snap.activity_state or "unknown").lower()
            interruptibility = snap.interruptibility
            tone = snap.sara_emotional_tone
            intensity = snap.sara_emotional_intensity
            notifs = snap.notifications_sent_today
    except Exception as e:
        logger.debug(f"interoception snapshot read failed: {e}")

    parts = [f"Now: {clock}."]
    if interruptibility is not None:
        parts.append(f"David: {activity} (interruptibility {interruptibility:.2f}).")
    else:
        parts.append(f"David: {activity}.")
    if tone:
        parts.append(f"You feel: {tone} ({(intensity or 0.0):.2f}).")
    if notifs is not None:
        parts.append(f"Notifications sent today: {notifs}/{_notif_cap()}.")

    return "## Right now (your internal clock & state)\n" + " ".join(parts)
