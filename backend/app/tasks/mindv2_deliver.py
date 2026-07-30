"""Mind V2 delivery beat task (SARA_ALIVE_BUILD_PLAN Arc 1.4).

Composed+reviewed utterances actually deliver: picks up composed_utterance
rows with review_verdict in (approve, edit) that haven't been delivered yet
and sends them through the real delivery/attention policy (interruptibility,
quiet hours, cooldowns, tell-once dedup) — the same `send_notification` path
every other sender in the system already goes through, with `_skip_phrasing`
set because the text is already fully composed in Sara's one voice; running
it back through notification_composer would be a second, competing voice.

Gated by the MINDV2_COMPOSE feature flag (default OFF, fail toward doing
nothing) so this can ship dark and be flipped on independently of a deploy.
"""
import asyncio
import json
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

# Candidate `kind` -> notification category. Drives cooldown/tunable lookup
# in unified_notification — everything else about "one voice" is already
# baked into the composed text itself.
_KIND_TO_CATEGORY = {
    "inform": "checkin",
    "followup": "checkin",
    "prep": "calendar_prep",
    "alert": "general",
    "retrospective": "general",
}


@celery_app.task(
    name="app.tasks.mindv2_deliver.run_delivery_cycle",
    queue="cognitive",
)
def run_delivery_cycle():
    try:
        return asyncio.run(_run_async())
    except Exception as e:
        logger.error(f"[mindv2_deliver] cycle task failed: {e}")
        raise


async def _run_async():
    from app.core.feature_flags import Flag, is_enabled

    if not is_enabled(Flag.MINDV2_COMPOSE):
        return {"skipped": "flag_off"}

    from sqlalchemy import text
    from app.db.session import get_async_session_factory

    user_id = DEFAULT_USER_ID
    factory = get_async_session_factory()

    async with factory() as db:
        rows = (await db.execute(text("""
            SELECT cu.id, cu.candidate_id, cu.final_text, cu.text, cu.urgency, cu.created_at,
                   sc.kind, sc.source
            FROM composed_utterance cu
            JOIN say_candidate sc ON sc.id = cu.candidate_id
            WHERE cu.user_id = :uid AND cu.delivered_at IS NULL
              AND cu.review_verdict IN ('approve', 'edit')
            ORDER BY cu.created_at ASC LIMIT 10
        """), {"uid": user_id})).fetchall()

    if not rows:
        return {"skipped": "no_pending"}

    from datetime import datetime, timedelta, timezone
    from app.services.unified_notification import send_notification

    # Composed text can carry time-relative phrasing ("before bed", "this
    # afternoon", "in 20 minutes") that's accurate when compose runs but
    # stale by the time delivery actually gets to it — found live: a real
    # HRV-alert candidate composed at 9:14 PM said "before bed" and was
    # still sitting undelivered at 6:44 AM (its own valid_until doesn't
    # expire until 9:09 AM, so the TTL alone doesn't catch this). Compose
    # doesn't re-run per delivery attempt, so the safe move is to drop a
    # message that's gone stale rather than deliver possibly-wrong phrasing.
    MAX_AGE = timedelta(hours=2)

    stats = {"delivered": 0, "errors": 0, "stale": 0}

    for r in rows:
        age = datetime.now(timezone.utc) - r.created_at
        if age > MAX_AGE:
            logger.info(f"[mindv2_deliver] dropping stale composed_utterance {r.id} (age={age})")
            async with factory() as db:
                await db.execute(text("""
                    UPDATE composed_utterance
                    SET delivered_at = NOW(), delivery_result = CAST(:result AS jsonb)
                    WHERE id = :id
                """), {"id": str(r.id), "result": json.dumps({"sent": False, "reason": "stale_on_delivery"})})
                await db.commit()
            stats["stale"] += 1
            continue

        message = (r.final_text or r.text or "").strip()
        category = _KIND_TO_CATEGORY.get(r.kind, "general")
        topic = f"mindv2:{r.id}"  # unique per row — inherently tell-once

        try:
            async with factory() as db:
                result = await send_notification(
                    user_id=user_id,
                    title="Sara",
                    message=message,
                    priority=r.urgency or "normal",
                    topic=topic,
                    category=category,
                    source="mindv2_compose",
                    db=db,
                    _skip_phrasing=True,  # already composed in the one voice
                )
                # send_notification only self-commits when it opened its own
                # session (db=None) — since we pass ours explicitly, we own
                # the commit. Found live 2026-07-30: without this, the
                # notification_log row (and any writes made after the
                # attention item's own earlier commit inside the send path)
                # silently rolled back on this `async with` block's exit —
                # composed_utterance.delivered_at + delivery_result still got
                # set below (unaffected, different session), so every past
                # delivery looked successful while its notification_log
                # audit row was actually never persisted.
                await db.commit()
        except Exception as e:
            # A real delivery error (LLM/DB/network hiccup downstream) — leave
            # delivered_at NULL so the next cycle retries.
            logger.warning(f"[mindv2_deliver] delivery failed for {r.id}: {e}")
            stats["errors"] += 1
            continue

        # Every outcome from send_notification past this point (sent=True,
        # routed to the attention queue, cooldown-suppressed, tuner-
        # suppressed, banned) is the real policy having made a real decision
        # about this exact message — that's delivery, in the same sense
        # morning_proactive already treats attention-queue routing as
        # delivered. Only an exception above should trigger a retry.
        async with factory() as db:
            await db.execute(text("""
                UPDATE composed_utterance
                SET delivered_at = NOW(), delivery_result = CAST(:result AS jsonb)
                WHERE id = :id
            """), {"id": str(r.id), "result": json.dumps(result)})
            await db.commit()

        stats["delivered"] += 1
        logger.info(
            f"[mindv2_deliver] delivered {r.id} (source={r.source}, kind={r.kind}): "
            f"sent={result.get('sent')} reason={result.get('reason')}"
        )

    logger.info(f"[mindv2_deliver] cycle complete: {stats}")
    return stats
