"""Assistant verbs sweep — SARA_UNLEASHED Phase C.1.

Deterministic triggers for deterministic value. The deliberation engine
(qwen, 27B, taught for months to prefer silence) sat on 31 unhandled
important emails for 36 hours without proposing a single email_draft, even
though the fully-built, send-proof draft handler was sitting right there
(R5/R6). LLM judgment should decide content and tone — never whether the
obviously-useful thing happens at all. This sweep makes the "does an
unhandled important email get drafted" question deterministic, and leaves
deliberation free to handle judgment calls.

Runs every 30 min during waking hours:
- Email drafts: any unread, important/action-required email older than 4h
  gets a reply drafted (oldest first), capped at 3/day. Uses the existing
  send-proof handler (deliberation_gate._generate_email_draft) — no new
  send capability, still fully dedup'd via action_ledger.
- Commitment nudges: the ripest open commitment thread gets surfaced,
  riding the existing anti-nag mention caps in thread_manager.
"""

import asyncio
import logging
import os

from app.celery_app import celery_app
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)
DEFAULT_USER_ID = get_owner_id()

WAKING_START_HOUR = 8
WAKING_END_HOUR = 21
DAILY_DRAFT_CAP = 3


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _drafts_sent_today(user_id: str) -> int:
    from sqlalchemy import text
    from app.db.session import get_async_session_factory
    from app.core.timezone import now as local_now

    factory = get_async_session_factory()
    async with factory() as db:
        today_start = local_now().replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        res = await db.execute(text("""
            SELECT COUNT(*) FROM action_ledger
            WHERE user_id = :uid AND action_type = 'email_draft'
              AND executed_at >= :since
        """), {"uid": user_id, "since": today_start})
        return int(res.scalar() or 0)


async def _run_email_drafts(user_id: str) -> int:
    from app.services.deliberation_gate import _generate_email_draft

    already = await _drafts_sent_today(user_id)
    drafted = 0
    remaining = max(0, DAILY_DRAFT_CAP - already)
    for _ in range(remaining):
        did_something = await _generate_email_draft(user_id)
        if not did_something:
            break
        drafted += 1
    return drafted


async def _run_commitment_nudge(user_id: str) -> bool:
    from app.services.deliberation_gate import _nudge_commitment
    return await _nudge_commitment(user_id)


async def _sweep(user_id: str) -> dict:
    from app.core.timezone import now as local_now

    hour = local_now().hour
    if not (WAKING_START_HOUR <= hour < WAKING_END_HOUR):
        return {"skipped": "outside_waking_hours"}

    result = {"drafted": 0, "commitment_nudged": False}
    try:
        result["drafted"] = await _run_email_drafts(user_id)
    except Exception as e:
        logger.error(f"assistant_verbs_sweep email drafts failed: {e}")

    try:
        result["commitment_nudged"] = await _run_commitment_nudge(user_id)
    except Exception as e:
        logger.error(f"assistant_verbs_sweep commitment nudge failed: {e}")

    return result


@celery_app.task(
    name="app.tasks.assistant_verbs.assistant_verbs_sweep",
    bind=True,
    queue="cognitive",
    max_retries=1,
)
def assistant_verbs_sweep(self):
    """Deterministic verbs: email drafts (capped 3/day, oldest unhandled
    important email first) + commitment nudges. See module docstring."""
    try:
        return _run_async(_sweep(DEFAULT_USER_ID))
    except Exception as e:
        logger.error(f"assistant_verbs_sweep failed: {e}")
        raise  # failures must fail — Celery records FAILURE (Phase 1.3)
