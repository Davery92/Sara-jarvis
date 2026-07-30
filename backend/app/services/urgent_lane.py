"""Urgent lane (work-order item 3, 2026-07-30): single-pass judge-skip
delivery for time-critical candidates.

The normal Mind V2 pipeline is judge -> compose -> deliver, each on an
independent ~180s Celery beat — up to ~9min worst-case sequential latency.
That's fine for anything with a wide delivery window (calendar_prep's
20-minute window absorbs it comfortably) but too tight a margin for a
message whose entire value is being on time (travel_nudge's "leave now").

This lane skips the judge step entirely — urgency is the caller's own
determination, not something to re-litigate against other pending
candidates — and runs compose -> review -> deliver inline, synchronously,
in the same request that detected the urgent condition. Same voice
(compose_utterance), same skepticism (review_utterance, same hedging-
linter enforcement as the batched path), same delivery policy
(send_notification) — just no beat-interval latency between the three.

Writes the same say_candidate + composed_utterance rows the batched path
would, so history/audit/kill-rate queries see one consistent story
regardless of which lane a message took.
"""
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def deliver_urgent(
    db_factory,
    user_id: str,
    *,
    source: str,
    kind: str,
    summary: str,
    evidence: Optional[List[Any]] = None,
    topic_entities: Optional[List[str]] = None,
    valid_until,
    dedupe_key: Optional[str] = None,
    notification_title: str = "Sara",
    notification_category: str = "general",
    notification_priority: str = "high",
) -> Dict[str, Any]:
    """Returns {"sent": bool, "reason": str, "candidate_id": str|None}."""
    from app.services.say_candidate import create_candidate
    from app.services.candidate_states import CandidateStatus
    from app.services.world_brief import get_rendered_brief
    from app.services.judge import _gather_utterance_history
    from app.services.compose import compose_utterance, ComposeDeclined
    from app.services.review import review_utterance
    from app.services.unified_notification import send_notification

    async with db_factory() as db:
        candidate_id = await create_candidate(
            db, user_id=user_id, source=source, kind=kind, summary=summary,
            evidence=evidence, topic_entities=topic_entities,
            valid_until=valid_until, dedupe_key=dedupe_key,
        )
    if candidate_id is None:
        return {"sent": False, "reason": "duplicate_suppressed", "candidate_id": None}
    candidate_id = str(candidate_id)

    async with db_factory() as db:
        brief_text = await get_rendered_brief(db, user_id)
        utterance_history = await _gather_utterance_history(db, user_id)

    candidate = {"id": candidate_id, "kind": kind, "summary": summary, "evidence": evidence or []}

    try:
        composed = await compose_utterance(candidate, brief_text, user_id=user_id)
    except ComposeDeclined as e:
        logger.info(f"[urgent_lane] compose declined for {candidate_id}: {e}")
        return await _finalize_no_send(db_factory, user_id, candidate_id, "compose_declined")
    except Exception as e:
        logger.warning(f"[urgent_lane] compose failed for {candidate_id}: {e}")
        return await _finalize_no_send(db_factory, user_id, candidate_id, f"compose_failed: {e}")

    try:
        review = await review_utterance(composed["text"], candidate, brief_text, utterance_history)
    except Exception as e:
        logger.warning(f"[urgent_lane] review raised unexpectedly for {candidate_id}: {e}")
        review = {"verdict": "kill", "reason": f"review_exception: {e}", "edited_text": None}

    final_text = None
    if review["verdict"] == "approve":
        final_text = composed["text"]
    elif review["verdict"] == "edit":
        final_text = review["edited_text"]

    # Same deterministic hedging enforcement as the batched compose path
    # (Arc 4.1) — urgency doesn't exempt a claim from calibration reality.
    if final_text:
        try:
            from app.services.prediction_engine import compute_calibration
            from app.services.voice_linter import infer_domain, lint_hedging
            async with db_factory() as db:
                report = await compute_calibration(db, user_id)
            calibration_by_domain = {
                domain: stat["hit_rate"]
                for domain, stat in (report.get("by_domain") or {}).items()
                if stat.get("hit_rate") is not None
            }
            if calibration_by_domain:
                domain = infer_domain(candidate)
                hedge_check = lint_hedging(final_text, domain, calibration_by_domain)
                if hedge_check["violation"]:
                    logger.info(
                        f"[urgent_lane] hedging violation for {candidate_id}: domain={domain} "
                        f"confidence={hedge_check['confidence']} — killing unhedged low-confidence claim"
                    )
                    review = {
                        "verdict": "kill",
                        "reason": (
                            f"[hedging linter] unhedged claim in '{domain}' domain "
                            f"({hedge_check['confidence']:.0%} recent accuracy) — original "
                            f"verdict was {review['verdict']!r}: {review['reason']}"
                        ),
                        "edited_text": None,
                    }
                    final_text = None
        except Exception as e:
            logger.debug(f"[urgent_lane] calibration/hedging check skipped: {e}")

    composed_id = str(uuid.uuid4())
    async with db_factory() as db:
        await db.execute(text("""
            INSERT INTO composed_utterance
                (id, candidate_id, user_id, text, refs, urgency, review_verdict, review_reason, final_text)
            VALUES
                (:id, :cid, :uid, :text, CAST(:refs AS jsonb), :urgency, :verdict, :reason, :final_text)
        """), {
            "id": composed_id, "cid": candidate_id, "uid": user_id,
            "text": composed["text"], "refs": json.dumps(composed.get("refs") or []),
            "urgency": composed.get("urgency") or "high",
            "verdict": review["verdict"], "reason": review["reason"], "final_text": final_text,
        })
        await db.execute(text("""
            UPDATE say_candidate SET status = :status WHERE id = :cid AND user_id = :uid
        """), {"status": CandidateStatus.COMPOSED.value, "cid": candidate_id, "uid": user_id})
        await db.commit()

    if not final_text:
        logger.info(f"[urgent_lane] killed at review: {candidate_id} ({review['reason']})")
        return {"sent": False, "reason": f"killed: {review['reason']}", "candidate_id": candidate_id}

    async with db_factory() as db:
        result = await send_notification(
            user_id=user_id,
            title=notification_title,
            message=final_text,
            priority=notification_priority,
            topic=f"urgent:{composed_id}",
            category=notification_category,
            source=source,
            db=db,
            _skip_phrasing=True,
        )
        # send_notification only self-commits when it opened its own session
        # (db=None) — we pass ours, so we own the commit (same footgun fixed
        # session-wide 2026-07-30 in mindv2_deliver.py and friends).
        await db.commit()

    async with db_factory() as db:
        await db.execute(text("""
            UPDATE composed_utterance
            SET delivered_at = NOW(), delivery_result = CAST(:result AS jsonb)
            WHERE id = :id
        """), {"id": composed_id, "result": json.dumps(result)})
        await db.commit()

    logger.info(
        f"[urgent_lane] delivered {composed_id} (source={source}): "
        f"sent={result.get('sent')} reason={result.get('reason')}"
    )
    return {"sent": bool(result.get("sent")), "reason": result.get("reason"), "candidate_id": candidate_id}


async def _finalize_no_send(db_factory, user_id: str, candidate_id: str, reason: str) -> Dict[str, Any]:
    from app.services.candidate_states import CandidateStatus
    async with db_factory() as db:
        await db.execute(text("""
            UPDATE say_candidate SET status = :status, judge_reason = :reason
            WHERE id = :cid AND user_id = :uid
        """), {"status": CandidateStatus.DECLINED.value, "reason": reason[:2000], "cid": candidate_id, "uid": user_id})
        await db.commit()
    return {"sent": False, "reason": reason, "candidate_id": candidate_id}
