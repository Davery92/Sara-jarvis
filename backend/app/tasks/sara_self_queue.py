"""Self-authored inbox seeding from Sara's standing interests.

The closing piece of the interests loop: when Sara has no active inbox items
AND a high-weight interest has gone stale, the backend promotes the interest
into a queued inbox item so she pulls on it during her next think turn.

Without this, interests are decoration in her ambient context — she sees them
but has no friction-free path to act on them. With this, the cycle is:

  reflection notices recurring theme  →  add_interest
  time passes, interest goes stale     →  promote_stale_interests_to_inbox
  she sees the queued item             →  pickup → web_search/write_note → touch
  …loop…

Caps to avoid spam:
  • Skip entirely if she already has any queued/in_progress item (David's or
    her own). One thing at a time.
  • Max 6 self-authored inbox items in any 24h rolling window.
  • Skip if the same interest has already been promoted in the last 24h
    (regardless of completion status).
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.celery_app import celery_app
from app.db.session import get_async_session_factory
from app.tasks.autonomy import _run_async  # reuse the loop runner

logger = logging.getLogger(__name__)


# ─── Tunables ──────────────────────────────────────────────────────────────

MIN_INTEREST_WEIGHT = 1.0      # below this, don't bother promoting
STALE_HOURS = 12               # interest must not have been acted on in this many hours
MAX_SELF_QUEUES_PER_DAY = 6    # rolling 24h cap on auto-queued items
SAME_INTEREST_COOLDOWN_HOURS = 24  # don't re-promote the same interest within this window


PROMOTE_PROMPT_TEMPLATE = (
    "Spend some time on a thread you've been carrying: {display_name}.\n\n"
    "{why}\n\n"
    "Pull on it however feels right — search memory or web, fetch one or two "
    "good sources, write a short note synthesising what you find. When you've "
    "made any real progress, complete this item with a short summary AND call "
    "touch_interest(id={interest_id}) so the staleness clock resets."
)


@celery_app.task(
    name="app.tasks.sara_self_queue.promote_stale_interests_to_inbox",
    bind=True,
    queue="cognitive",
    max_retries=0,
)
def promote_stale_interests_to_inbox(self):
    """Periodic — promote one stale interest into Sara's inbox if conditions allow."""
    try:
        return _run_async(_promote_async())
    except Exception as e:
        logger.error("self-queue promotion failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


async def _promote_async() -> dict:
    async_session = get_async_session_factory()
    async with async_session() as db:
        # 1) Skip if she's busy with anything (David's or her own).
        active = (await db.execute(
            text(
                "SELECT COUNT(*) FROM sara_inbox "
                "WHERE status IN ('queued', 'in_progress')"
            )
        )).scalar_one()
        if active and active > 0:
            return {"status": "skip", "reason": "active_inbox", "active": int(active)}

        # 2) Daily cap on self-authored items.
        recent_self = (await db.execute(
            text(
                "SELECT COUNT(*) FROM sara_inbox "
                "WHERE created_by = 'sara_self' "
                "  AND created_at > NOW() - INTERVAL '24 hours'"
            )
        )).scalar_one()
        if recent_self and int(recent_self) >= MAX_SELF_QUEUES_PER_DAY:
            return {
                "status": "skip", "reason": "daily_cap",
                "self_queued_24h": int(recent_self),
            }

        # 3) Pick the top stale, non-recently-promoted interest.
        # We embed the interest id in the inbox prompt as `[from_interest:<id>]`
        # so we can tell which interests were already promoted by reading prompts.
        # Slightly hacky vs. a proper FK column, but lets us ship without a
        # schema change. The migration to add source_interest_id can come later.
        row = (await db.execute(
            text(
                """
                SELECT i.id, i.display_name, i.why, i.weight,
                       i.last_acted_at, i.created_at
                FROM sara_interest i
                WHERE NOT i.blocked
                  AND i.weight >= :min_weight
                  AND (i.last_acted_at IS NULL
                       OR i.last_acted_at < NOW() - make_interval(hours => :stale_hours))
                  AND NOT EXISTS (
                      SELECT 1 FROM sara_inbox b
                      WHERE b.created_by = 'sara_self'
                        AND b.created_at > NOW() - make_interval(hours => :cooldown_hours)
                        AND b.prompt LIKE '%[from_interest:' || i.id::text || ']%'
                  )
                ORDER BY i.weight DESC, i.last_updated_at DESC
                LIMIT 1
                """
            ),
            {
                "min_weight": MIN_INTEREST_WEIGHT,
                "stale_hours": STALE_HOURS,
                "cooldown_hours": SAME_INTEREST_COOLDOWN_HOURS,
            },
        )).mappings().first()

        if not row:
            return {"status": "skip", "reason": "no_stale_interest"}

        interest_id = str(row["id"])
        why = (row["why"] or "").strip() or (
            "You marked this as something worth returning to. Time to return to it."
        )
        prompt_body = PROMOTE_PROMPT_TEMPLATE.format(
            display_name=row["display_name"],
            why=why,
            interest_id=interest_id,
        )
        # Marker so future runs know we already promoted this one.
        prompt_with_marker = prompt_body + f"\n\n[from_interest:{interest_id}]"

        # 4) Insert. urgency=low so it doesn't compete with David-queued work.
        await db.execute(
            text(
                """
                INSERT INTO sara_inbox (created_by, urgency, prompt, context, status)
                VALUES ('sara_self', 'low', :prompt, :ctx, 'queued')
                """
            ),
            {
                "prompt": prompt_with_marker,
                "ctx": (
                    f"Auto-promoted from your standing interest "
                    f"(weight={float(row['weight']):.1f}, "
                    f"last_acted={row['last_acted_at'] or 'never'})."
                ),
            },
        )
        await db.commit()

    logger.info(
        "self-queue: promoted interest %s (%r) to inbox",
        interest_id, row["display_name"],
    )
    return {
        "status": "promoted",
        "interest_id": interest_id,
        "display_name": row["display_name"],
        "weight": float(row["weight"]),
    }
