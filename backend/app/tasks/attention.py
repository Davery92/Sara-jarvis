"""
Attention queue Celery tasks.

SARA_PROACTIVENESS_AUDIT_AND_PLAN_2026_07_25 §5.3/§7.2 + IMPLEMENTATION_PLAN
P2/P8.1: the old ``escalate_unread_attention`` used to push unread
``autonomy_attention_item`` rows to David after ESCALATION_HOURS, bumping
their priority to "high" regardless of the original judgment. That is
exactly the "silence becomes urgency" bug the audit called out as the
single largest dismissed-notification cohort (66 sent / 42 dismissed in the
30-day sample): an item the attention market correctly judged unworthy of a
push became a push merely because David hadn't opened it yet. "Unread is
not urgent. Age does not create value." (audit §5.3)

Escalation-to-push is deleted outright, not tuned. What remains:

- ``expire_stale_attention``: items that sat unread past their useful
  window are marked ``expired`` (not ``sent``) so they stop showing as an
  unread obligation in Today/inbox, without ever having been force-pushed.
  This is the P2 "expiration before delivery" policy applied to the legacy
  queue while the rest of the arbiter work lands.
"""

import asyncio
import logging

from sqlalchemy import text

from app.celery_app import celery_app
from app.core.timezone import now as local_now
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

# How long an attention item can sit unread before it's considered stale.
# It expires quietly — it is never promoted to a push. (Was: escalated to a
# forced "high" priority push after this same threshold — deleted per P8.1.)
EXPIRE_HOURS = 24.0


@celery_app.task(
    name="app.tasks.attention.escalate_unread_attention",
    queue="cognitive",
)
def escalate_unread_attention():
    """Deprecated name kept so the DB-scheduled job row (now disabled) and
    any stale beat cache resolve to a real, harmless task instead of an
    'unknown task' error. Delegates to the real (non-escalating) sweep."""
    return expire_stale_attention()


@celery_app.task(
    name="app.tasks.attention.expire_stale_attention",
    queue="cognitive",
)
def expire_stale_attention():
    """Quietly expire attention items that have sat unread too long. Never
    pushes, never bumps priority, never bypasses the attention gate."""
    try:
        return asyncio.run(_expire_stale_attention_async())
    except Exception as e:
        logger.error(f"Attention expiry sweep failed: {e}")
        raise


async def _expire_stale_attention_async() -> dict:
    db = SessionLocal()
    try:
        archived_confirmations = db.execute(text("""
            UPDATE autonomy_attention_item
            SET status = 'archived', archived_at = NOW(), updated_at = NOW()
            WHERE status = 'new'
              AND payload->>'prediction_grade' = 'confirmation'
            RETURNING id
        """)).fetchall()
        if archived_confirmations:
            db.commit()

        # Reuse the existing terminal 'archived' status (already excluded from
        # every unread/badge/Today query across autonomy_attention.py and
        # attention_queue.py) rather than inventing a new status value that
        # would silently keep showing as unread anywhere those NOT IN(...)
        # filters weren't updated. The payload tag distinguishes "expired
        # quietly" from a user-initiated archive for observability.
        expired = db.execute(text("""
            UPDATE autonomy_attention_item
            SET status = 'archived', archived_at = NOW(), updated_at = NOW(),
                payload = COALESCE(payload, '{}'::jsonb) || '{"expired_stale": true}'::jsonb
            WHERE status = 'new'
              AND COALESCE(payload->>'prediction_grade', '') != 'confirmation'
              AND created_at < NOW() - MAKE_INTERVAL(secs => :age_secs)
            RETURNING id
        """), {"age_secs": int(EXPIRE_HOURS * 3600)}).fetchall()
        if expired:
            db.commit()

        return {
            "checked_at": local_now().isoformat(),
            "archived_confirmations": len(archived_confirmations),
            "expired": len(expired),
        }
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()
