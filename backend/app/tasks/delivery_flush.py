"""Delivery-policy flush — deliver overnight-held notifications at sensed wake.

Runs every 15 min. If David is awake and items were held while he slept
(unified delivery policy §3.6 / N1 fix), deliver them as a SINGLE digest push
rather than a burst of individual buzzes — one civilized morning summary beats
five 5 AM pings, and morning-brief-timed delivery gets a ~100% read rate.

Items past their `deliver_after` are always flushed even if sleep sensing is
uncertain, so nothing can get stuck in the queue indefinitely.
"""
import asyncio
import logging

from app.celery_app import celery_app
from app.core.timezone import now as local_now
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

_DAVID = get_owner_id()

# Don't sit on held items forever, even if we can't confidently sense wake.
_MAX_HOLD_HOURS = 12

# Give the 06:00 morning-brief task first refusal on overnight items. Without
# this small coordination window, the 15-minute generic flush can observe wake
# at 05:xx/06:00, drain the queue, and then the brief creates a second morning
# push a few minutes later.
_MORNING_ANCHOR_START_HOUR = 4
_MORNING_ANCHOR_READY_HOUR = 6
_MORNING_ANCHOR_READY_MINUTE = 10


def _waiting_for_morning_anchor(moment) -> bool:
    minutes = moment.hour * 60 + moment.minute
    start = _MORNING_ANCHOR_START_HOUR * 60
    ready = _MORNING_ANCHOR_READY_HOUR * 60 + _MORNING_ANCHOR_READY_MINUTE
    return start <= minutes < ready


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _flush(user_id: str) -> dict:
    from sqlalchemy import text
    from app.db.session import get_async_session_factory
    from app.services.delivery_policy import sense_sleep_state
    from app.services.unified_notification import send_notification

    from app.services.unified_notification import _log_notification

    sf = get_async_session_factory()
    async with sf() as db:
        # 'await_departure' items (Phase 4) are drained by departure_brief.py,
        # not swept into this generic wake digest — queuing them here would
        # defeat the point of timing them to just before David leaves.
        pending = (await db.execute(text("""
            SELECT id, title, message, category, priority, source, topic, held_at, deliver_after
            FROM held_notification
            WHERE user_id = :uid AND status = 'held'
              AND held_reason IS DISTINCT FROM 'await_departure'
            ORDER BY held_at ASC
        """), {"uid": user_id})).fetchall()

        if not pending:
            return {"effect": "no_held_items", "flushed": 0}
        # The brief owns the normal wake-anchor window and folds these rows into
        # one useful push. Truly stale rows may still escape the guard so a
        # failed brief job cannot strand a notification indefinitely.
        now = local_now()
        if _waiting_for_morning_anchor(now):
            stale = [
                row for row in pending
                if row.held_at and (now - row.held_at).total_seconds() >= _MAX_HOLD_HOURS * 3600
            ]
            if not stale:
                return {
                    "effect": "awaiting_morning_anchor", "flushed": 0,
                    "held": len(pending),
                }

        sleep = await sense_sleep_state(db, user_id)

        # Deliver when awake, OR for any item past its deliver_after / max hold.
        force_ids = (await db.execute(text("""
            SELECT id FROM held_notification
            WHERE user_id = :uid AND status = 'held'
              AND held_reason IS DISTINCT FROM 'await_departure'
              AND (
                (deliver_after IS NOT NULL AND deliver_after <= NOW())
                OR held_at <= NOW() - MAKE_INTERVAL(hours => :maxh)
              )
        """), {"uid": user_id, "maxh": _MAX_HOLD_HOURS})).fetchall()
        force = {r[0] for r in force_ids}

        if sleep.asleep and not force:
            return {
                "effect": "still_asleep", "flushed": 0, "held": len(pending),
                "sleep_source": sleep.source,
            }

        to_deliver = pending if not sleep.asleep else [p for p in pending if p[0] in force]
        if not to_deliver:
            return {"effect": "nothing_due", "flushed": 0, "held": len(pending)}

        ids = [row[0] for row in to_deliver]

        # Build a single digest. One line per held item.
        if len(to_deliver) == 1:
            row = to_deliver[0]
            title = row[1]
            message = row[2] or ""
        else:
            title = f"While you slept — {len(to_deliver)} updates"
            lines = []
            for row in to_deliver:
                t = row[1]
                lines.append(f"• {t}")
            message = "\n".join(lines[:10])
            if len(to_deliver) > 10:
                message += f"\n…and {len(to_deliver) - 10} more"

        # Deliver via the normal pipeline. source='held_flush' is in the policy's
        # always-deliver set, so this can't recursively re-hold itself.
        result = await send_notification(
            user_id=user_id, title=title, message=message,
            priority="normal", category="general", source="held_flush",
            topic=f"held_flush:{local_now().strftime('%Y%m%d_%H')}",
            db=db, _bypass_attention=True,
        )
        delivered = bool(result.get("sent"))

        await db.execute(text("""
            UPDATE held_notification
            SET status = :st, resolved_at = NOW()
            WHERE id = ANY(:ids)
        """), {"st": "delivered" if delivered else "dropped", "ids": ids})
        await db.commit()

        if delivered:
            # Phase 3c: log-only per-item rows (sent=True, original category) so
            # category cooldowns/rate-limits see these as delivered even though
            # only the single digest push actually buzzed.
            for row in to_deliver:
                try:
                    await _log_notification(
                        db, user_id, row.topic or f"{row.category}:held{row.id}",
                        row.category or "general", row.title, row.message or "",
                        row.priority or "normal", "held_flush_item", None, 0,
                        sent=True, dedup_blocked=False,
                    )
                except Exception as e:
                    logger.debug(f"held-item cooldown arming skipped for id={row.id}: {e}")
            await db.commit()

        logger.info(
            f"🌅 Flushed {len(ids)} held notification(s) as digest "
            f"(delivered={delivered}, sleep={sleep.source})"
        )
        return {
            "effect": "flushed_held", "flushed": len(ids),
            "delivered": delivered, "sleep_source": sleep.source,
        }


@celery_app.task(name="app.tasks.delivery_flush.flush_held_notifications")
def flush_held_notifications():
    """Deliver overnight-held notifications once David is awake (§3.6 / N1)."""
    return _run_async(_flush(_DAVID))
