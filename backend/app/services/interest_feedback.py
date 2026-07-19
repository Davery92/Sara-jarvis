"""Interest feedback signal (Phase 6.3).

David's reactions to Sara's interest-driven output feed back into whether she
keeps pulling at a topic. Dismiss / ignore / negative-sentiment each add a strike
and dampen the weight; at two strikes the interest is auto-muted via the existing
`blocked` flag (never deleted — reflection re-creates deletions, see
sara_interest.blocked). The whole point is that a quiet dismissal or two catches
it *before* David has to rage-type in all caps.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Reaction -> (weight delta, strike delta)
_REACTIONS = {
    "dismiss": (-1.0, 1),
    "ignore": (-0.5, 1),
    "negative": (-3.0, 1),   # explicit "stop telling me about X"
    "rage": (-100.0, 2),     # all-caps fury — instant mute
    "positive": (+1.0, -1),  # engaged — reinforce, heal a strike
}
STRIKES_TO_MUTE = 2


async def record_reaction(interest: str, reaction: str, note: str = "") -> dict:
    """Apply a reaction to an interest (by id or topic/display_name). Returns the
    new state incl. whether it just got muted."""
    if reaction not in _REACTIONS:
        return {"error": f"unknown reaction '{reaction}'"}
    dweight, dstrike = _REACTIONS[reaction]

    from app.db.session import get_async_session_factory
    factory = get_async_session_factory()
    async with factory() as db:
        # Resolve by uuid, else by topic/display_name (case-insensitive contains).
        row = None
        try:
            row = (await db.execute(text(
                "SELECT id, display_name, weight, strikes, blocked FROM sara_interest WHERE id::text = :i"),
                {"i": interest})).mappings().first()
        except Exception:
            row = None
        if not row:
            row = (await db.execute(text(
                """SELECT id, display_name, weight, strikes, blocked FROM sara_interest
                   WHERE lower(topic) LIKE :q OR lower(display_name) LIKE :q
                   ORDER BY weight DESC LIMIT 1"""),
                {"q": f"%{interest.lower()}%"})).mappings().first()
        if not row:
            return {"error": f"no interest matching '{interest}'"}

        new_strikes = max(0, (row["strikes"] or 0) + dstrike)
        new_weight = max(0.0, (row["weight"] or 0.0) + dweight)
        should_mute = new_strikes >= STRIKES_TO_MUTE and not row["blocked"]

        await db.execute(text(
            """UPDATE sara_interest
               SET weight = :w, strikes = :s, blocked = :b, last_reaction_at = NOW()
               WHERE id = :id"""),
            {"w": new_weight, "s": new_strikes,
             "b": True if should_mute else row["blocked"], "id": row["id"]})
        await db.commit()

    result = {
        "interest": row["display_name"], "id": str(row["id"]),
        "reaction": reaction, "strikes": new_strikes, "weight": round(new_weight, 2),
        "muted": should_mute or bool(row["blocked"]),
        "just_muted": should_mute,
    }
    if should_mute:
        logger.info(f"[interest_feedback] auto-muted '{row['display_name']}' after {new_strikes} strikes ({reaction})")
        # Visible + reversible: log to the ledger and an internal activity entry.
        try:
            from app.services.diagnostics_service import record_system_event
            await record_system_event(
                category="interest_muted", service="interest_feedback", level="INFO",
                message=f"Auto-muted interest '{row['display_name']}' after 2 strikes ({reaction})",
                meta={"interest_id": str(row["id"]), "note": note})
        except Exception:
            pass
    return result
