"""Compose+Review beat task (SARA_MIND_V2 Phase 2, §3.7).

SHADOW MODE: finds `judged_send` candidates the judge has already ranked,
composes a real message, reviews it, and persists the result to
`composed_utterance` for inspection. Never calls send_notification — there
is no live cutover here, only a growing, readable record of what the
pipeline WOULD have said, for you to judge before Phase 2 ever flips.
"""
import asyncio
import json
import logging
import uuid

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

_VERDICT_STAT_KEY = {"approve": "approved", "edit": "edited", "kill": "killed"}


@celery_app.task(
    name="app.tasks.compose.run_compose_cycle",
    queue="cognitive",
)
def run_compose_cycle():
    try:
        return asyncio.run(_run_async())
    except Exception as e:
        logger.error(f"[compose] cycle task failed: {e}")
        raise


async def _run_async():
    from sqlalchemy import text
    from app.db.session import get_async_session_factory
    from app.services.candidate_states import CandidateStatus
    from app.services.compose import compose_utterance, ComposeDeclined
    from app.services.review import review_utterance
    from app.services.world_brief import get_rendered_brief
    from app.services.judge import _gather_utterance_history, _gather_recent_chat

    user_id = DEFAULT_USER_ID
    factory = get_async_session_factory()

    async with factory() as db:
        rows = (await db.execute(text("""
            SELECT sc.id, sc.kind, sc.summary, sc.evidence, sc.judge_reason
            FROM say_candidate sc
            WHERE sc.user_id = :uid AND sc.status = :status
              AND NOT EXISTS (SELECT 1 FROM composed_utterance cu WHERE cu.candidate_id = sc.id)
            ORDER BY sc.created_at ASC LIMIT 10
        """), {"uid": user_id, "status": CandidateStatus.JUDGED_SEND.value})).fetchall()

    if not rows:
        return {"skipped": "no_candidates"}

    async with factory() as db:
        brief_text = await get_rendered_brief(db, user_id)
        utterance_history = await _gather_utterance_history(db, user_id)
        recent_chat = await _gather_recent_chat(db, user_id)

    stats = {"composed": 0, "approved": 0, "edited": 0, "killed": 0, "errors": 0}

    for r in rows:
        candidate = {
            "id": str(r.id), "kind": r.kind, "summary": r.summary,
            "evidence": r.evidence, "judge_reason": r.judge_reason,
        }

        try:
            composed = await compose_utterance(candidate, brief_text, recent_chat)
        except ComposeDeclined as e:
            # Deterministic — the payload is too thin no matter how many
            # times we retry. Advance past judged_send so it stops being
            # picked up by every future cycle (unlike a real transient
            # error below, which we deliberately leave to retry).
            logger.info(f"[compose] declined for {candidate['id']}: {e}")
            async with factory() as db:
                await db.execute(text("""
                    UPDATE say_candidate SET status = :status
                    WHERE id = :cid AND user_id = :uid
                """), {"status": CandidateStatus.DECLINED.value, "cid": candidate["id"], "uid": user_id})
                await db.commit()
            stats["declined"] = stats.get("declined", 0) + 1
            continue
        except Exception as e:
            logger.warning(f"[compose] compose failed for {candidate['id']}: {e}")
            stats["errors"] += 1
            continue

        try:
            review = await review_utterance(composed["text"], candidate, brief_text, utterance_history)
        except Exception as e:
            logger.warning(f"[compose] review raised unexpectedly for {candidate['id']}: {e}")
            review = {"verdict": "kill", "reason": f"review_exception: {e}", "edited_text": None}

        final_text = None
        if review["verdict"] == "approve":
            final_text = composed["text"]
        elif review["verdict"] == "edit":
            final_text = review["edited_text"]

        async with factory() as db:
            await db.execute(text("""
                INSERT INTO composed_utterance
                    (id, candidate_id, user_id, text, refs, urgency, review_verdict, review_reason, final_text)
                VALUES
                    (:id, :cid, :uid, :text, CAST(:refs AS jsonb), :urgency, :verdict, :reason, :final_text)
            """), {
                "id": str(uuid.uuid4()), "cid": candidate["id"], "uid": user_id,
                "text": composed["text"], "refs": json.dumps(composed["refs"]),
                "urgency": composed["urgency"], "verdict": review["verdict"],
                "reason": review["reason"], "final_text": final_text,
            })
            # Advance the candidate out of judged_send now that a
            # composed_utterance row exists for it — the NOT EXISTS guard
            # above already made re-processing safe, but leaving status
            # stuck at judged_send forever made the state machine a lie
            # (Arc 1.1: composed is a real, queryable state, not just an
            # implicit "a composed_utterance row happens to exist").
            await db.execute(text("""
                UPDATE say_candidate SET status = :status
                WHERE id = :cid AND user_id = :uid
            """), {"status": CandidateStatus.COMPOSED.value, "cid": candidate["id"], "uid": user_id})
            await db.commit()

        stats["composed"] += 1
        stats[_VERDICT_STAT_KEY[review["verdict"]]] += 1

    logger.info(f"[compose] cycle complete: {stats}")
    return stats
