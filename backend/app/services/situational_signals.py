"""Cross-domain situational signals for deliberation (Phase 10D).

Feeds the brain the three cheap signals it was missing so it can *derive* the
office/rest-day and pre-gym-meal scenarios instead of falling back to a generic
"how's your day": today's training-day status, a food-log digest, and typical
meal timing. Location + life facts are injected separately (10A/10B). Includes
the prompt guidance that turns these signals into specific, actionable asks.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

_GUIDANCE = (
    "When schedule facts and current location/logging disagree, ask ONE specific "
    "question with a proposed action, not a generic check-in. E.g. office day + no "
    "breakfast logged by ~11 -> 'You usually eat before the gym — nothing logged, grab "
    "your bowl?' (SILENT if food is logged OR the scratchpad already covers it — the "
    "scratchpad wins). Weekday ~11:30 + not at the office + no office arrival -> "
    "'You're not at the office — skip the 1:10 workout and switch to rest-day nutrition?' "
    "(one tap -> set_day_type(today,'rest')). One ask per topic per day; drop on ignore."
)


async def build_situational_block(user_id: str = DEFAULT_USER_ID) -> Optional[str]:
    from app.db.session import get_async_session_factory, SessionLocal
    from app.core.timezone import today as _today, now as _now

    lines = []
    # Training-day status (sync helper).
    try:
        from app.services.training_day import is_training_day
        db = SessionLocal()
        try:
            td = is_training_day(db, user_id, _today())
        finally:
            db.close()
        lines.append(f"Today is a {'TRAINING' if td['is_training_day'] else 'REST'} day ({td['reason']}).")
    except Exception:
        pass

    # Food-log digest for today.
    try:
        factory = get_async_session_factory()
        async with factory() as adb:
            rows = (await adb.execute(text("""
                SELECT meal_type, food_items, logged_at FROM food_log
                WHERE user_id = :uid AND logged_at::date = CURRENT_DATE
                ORDER BY logged_at
            """), {"uid": user_id})).mappings().all()
        if not rows:
            lines.append("Food logged today: nothing yet.")
        else:
            bits = []
            for r in rows[:4]:
                t = r["logged_at"].strftime("%H:%M") if r["logged_at"] else "?"
                label = (r["meal_type"] or (r["food_items"] or "meal"))
                bits.append(f"{label} {t}")
            lines.append("Food logged today: " + "; ".join(bits) + ".")
    except Exception as e:
        logger.debug(f"food digest failed: {e}")

    if not lines:
        return None
    return "## Today's body & fuel (Phase 10D)\n" + " ".join(lines) + "\n" + _GUIDANCE
