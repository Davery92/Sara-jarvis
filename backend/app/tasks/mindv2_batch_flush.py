"""Mind V2 batch-flush beat task (SARA_ALIVE_BUILD_PLAN Arc 1.5 follow-up,
found + fixed 2026-07-29).

`judged_batch` was a documented, permanent dead end: `candidate_states.py`'s
own comment said so ("batch delivery isn't wired yet; SHADOW MODE") and it
sat in `TERMINAL_STATUSES`. The judge already decides some candidates are
"worth mentioning, but in a scheduled slot (morning or evening), not now"
and writes `[slot=morning]`/`[slot=evening]` into `judge_reason` — but
nothing ever promoted those candidates onward, so they just accumulated
forever, never reaching David.

This task is that promotion, and nothing more: on a tick that falls inside
the labeled slot's delivery window, OR for any batched candidate whose
`valid_until` is closing in regardless of label (a safety net so nothing
that's about to expire is lost while its "proper" window hasn't arrived
yet), it promotes matching `judged_batch` candidates to `judged_send` so
the existing compose -> review -> deliver pipeline picks them up exactly
the way it already handles `send_now` candidates. Deliberately does NOT
combine multiple batched candidates into one digest message — that's a real
composition decision (one message vs. several, how staleness interacts
across them) that deserves its own design, not something to invent as a
side effect of unsticking the pipeline. One candidate in, one message out,
same as everything else that already reaches compose.

Windows are deliberately wide (not a tight 2-hour slot) — the judge's own
"batch" reasoning ranges from "before the day progresses" to "before the
2:30 PM meeting," i.e. same-day delivery, not literally next-calendar-day
7-9 AM. Exact cadence tuning is a real product question (see the plan doc);
this is the minimal fix that makes "batch" no longer mean "never."
"""
import asyncio
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

# Delivery windows in ET, matching the plain-English "morning"/"evening"
# slot labels the judge already writes into judge_reason.
_MORNING_WINDOW = (8, 12)   # [8:00, 12:00) ET
_EVENING_WINDOW = (16, 21)  # [16:00, 21:00) ET — before bedtime_intelligence's 20-22h window

# Safety net: a batched candidate this close to expiring gets flushed
# regardless of slot/window, rather than silently lost.
_EXPIRY_SAFETY_MARGIN_HOURS = 1.5


@celery_app.task(
    name="app.tasks.mindv2_batch_flush.run_batch_flush",
    queue="cognitive",
)
def run_batch_flush():
    try:
        return asyncio.run(_run_async())
    except Exception as e:
        logger.error(f"[mindv2_batch_flush] cycle task failed: {e}")
        raise


async def _run_async():
    from datetime import datetime, timedelta, timezone
    from app.core.timezone import now as local_now
    from sqlalchemy import text
    from app.db.session import get_async_session_factory
    from app.services.candidate_states import CandidateStatus

    hour = local_now().hour
    if _MORNING_WINDOW[0] <= hour < _MORNING_WINDOW[1]:
        slot = "morning"
    elif _EVENING_WINDOW[0] <= hour < _EVENING_WINDOW[1]:
        slot = "evening"
    else:
        slot = None

    user_id = DEFAULT_USER_ID
    factory = get_async_session_factory()
    now = datetime.now(timezone.utc)
    expiry_cutoff = now + timedelta(hours=_EXPIRY_SAFETY_MARGIN_HOURS)

    async with factory() as db:
        if slot:
            rows = (await db.execute(text("""
                SELECT id, valid_until FROM say_candidate
                WHERE user_id = :uid AND status = :status
                  AND (judge_reason LIKE :slot_prefix OR valid_until < :cutoff)
                ORDER BY created_at ASC LIMIT 20
            """), {"uid": user_id, "status": CandidateStatus.JUDGED_BATCH.value,
                   "slot_prefix": f"[slot={slot}]%", "cutoff": expiry_cutoff})).fetchall()
        else:
            # Outside both windows — only the expiry safety net applies.
            rows = (await db.execute(text("""
                SELECT id, valid_until FROM say_candidate
                WHERE user_id = :uid AND status = :status AND valid_until < :cutoff
                ORDER BY created_at ASC LIMIT 20
            """), {"uid": user_id, "status": CandidateStatus.JUDGED_BATCH.value,
                   "cutoff": expiry_cutoff})).fetchall()

    if not rows:
        return {"skipped": "no_candidates", "slot": slot}

    promoted, expired = 0, 0

    async with factory() as db:
        for r in rows:
            if r.valid_until and r.valid_until < now:
                await db.execute(text("""
                    UPDATE say_candidate SET status = :status WHERE id = :cid
                """), {"status": CandidateStatus.EXPIRED.value, "cid": str(r.id)})
                expired += 1
                continue
            await db.execute(text("""
                UPDATE say_candidate SET status = :status WHERE id = :cid
            """), {"status": CandidateStatus.JUDGED_SEND.value, "cid": str(r.id)})
            promoted += 1
        await db.commit()

    logger.info(f"[mindv2_batch_flush] slot={slot} promoted={promoted} expired={expired}")
    return {"slot": slot, "promoted": promoted, "expired": expired}
