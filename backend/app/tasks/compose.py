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


def _partition_batch_groups(rows):
    """Work-order item 12 (batch digest hybrid): split judged_send rows into
    individually-composed ones and batch-origin groups eligible for a
    digest. A candidate is "batch-origin" if the judge tagged it
    `[slot=morning]`/`[slot=evening]` (mindv2_batch_flush.py's own marker,
    unchanged by the batch->judged_send promotion). Grouped by slot since
    a flush window only ever promotes one slot's candidates together, but
    grouping explicitly rather than assuming keeps this correct even if
    that ever changes. Returns (individual_rows, {slot: [rows]}).
    """
    import re as _re
    individual = []
    by_slot: dict = {}
    for r in rows:
        m = _re.match(r"^\[slot=(morning|evening)\]", r.judge_reason or "")
        if m:
            by_slot.setdefault(m.group(1), []).append(r)
        else:
            individual.append(r)

    # Only groups of 3+ actually digest — 1-2 batch-origin candidates in
    # this cycle fall back to individual composition, same as before.
    digest_groups = {slot: group for slot, group in by_slot.items() if len(group) >= 3}
    for slot, group in by_slot.items():
        if len(group) < 3:
            individual.extend(group)
    return individual, digest_groups


async def _run_async():
    from sqlalchemy import text
    from app.db.session import get_async_session_factory
    from app.services.candidate_states import CandidateStatus
    from app.services.compose import compose_utterance, compose_digest_utterance, ComposeDeclined
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

    individual_rows, digest_groups = _partition_batch_groups(rows)

    async with factory() as db:
        brief_text = await get_rendered_brief(db, user_id)
        utterance_history = await _gather_utterance_history(db, user_id)
        recent_chat = await _gather_recent_chat(db, user_id)

    # Arc 4.1 "consequence with teeth": flatten compute_calibration's
    # by_domain into {domain: hit_rate} for the hedging linter — the
    # reliability of each domain's predictions, aggregated across
    # confidence buckets. Best-effort: a failure here must never block
    # composition; an empty dict just means no domain requires hedging yet
    # (lint_hedging treats an unmeasured domain as not-a-violation).
    calibration_by_domain: dict = {}
    try:
        from app.services.prediction_engine import compute_calibration
        async with factory() as db:
            report = await compute_calibration(db, user_id)
        for domain, stat in (report.get("by_domain") or {}).items():
            if stat.get("hit_rate") is not None:
                calibration_by_domain[domain] = stat["hit_rate"]
    except Exception as e:
        logger.debug(f"[compose] calibration fetch for hedging check failed: {e}")

    stats = {"composed": 0, "approved": 0, "edited": 0, "killed": 0, "errors": 0, "digested": 0}

    # Work-order item 12 (batch digest hybrid): 3+ batch-origin candidates
    # in this cycle compose into ONE utterance instead of N. Each
    # contributing candidate still individually transitions to composed/
    # declined below — that per-candidate status transition IS the
    # tell-once ledger (once composed, no future compose cycle, batch-
    # flush, or the original source system's own dedup_key check can pick
    # it up again), so nothing double-fires later even though only one
    # candidate_id can be the composed_utterance row's own FK.
    for slot, group in digest_groups.items():
        candidates = [
            {"id": str(r.id), "kind": r.kind, "summary": r.summary,
             "evidence": r.evidence, "judge_reason": r.judge_reason}
            for r in group
        ]
        primary = candidates[0]
        other_ids = [c["id"] for c in candidates[1:]]

        try:
            composed = await compose_digest_utterance(candidates, brief_text, recent_chat, user_id=user_id)
        except ComposeDeclined as e:
            logger.info(f"[compose] digest declined for slot={slot} ({len(candidates)} items): {e}")
            async with factory() as db:
                for c in candidates:
                    await db.execute(text("""
                        UPDATE say_candidate SET status = :status
                        WHERE id = :cid AND user_id = :uid
                    """), {"status": CandidateStatus.DECLINED.value, "cid": c["id"], "uid": user_id})
                await db.commit()
            stats["declined"] = stats.get("declined", 0) + len(candidates)
            continue
        except Exception as e:
            logger.warning(f"[compose] digest compose failed for slot={slot}: {e}")
            stats["errors"] += 1
            continue

        # Synthetic "digest candidate" for the reviewer — real summaries
        # from every item, not just the primary's, so the editor actually
        # sees what it's checking (review_utterance only reads kind/summary).
        review_candidate = {
            "kind": "digest",
            "summary": f"Batched digest of {len(candidates)} items: " +
                       "; ".join(c["summary"] for c in candidates),
        }
        try:
            review = await review_utterance(composed["text"], review_candidate, brief_text, utterance_history)
        except Exception as e:
            logger.warning(f"[compose] digest review raised unexpectedly for slot={slot}: {e}")
            review = {"verdict": "kill", "reason": f"review_exception: {e}", "edited_text": None}

        final_text = None
        if review["verdict"] == "approve":
            final_text = composed["text"]
        elif review["verdict"] == "edit":
            final_text = review["edited_text"]

        # Arc 4.1 "consequence with teeth", extended to digests: a digest
        # can span multiple domains, so check every contributing
        # candidate's domain — one unhedged low-confidence claim anywhere
        # in the paragraph is enough to kill the whole thing (fails
        # closed, same as the single-candidate path; there's no clean way
        # to strip just the offending clause out of a woven paragraph).
        if final_text and calibration_by_domain:
            from app.services.voice_linter import infer_domain, lint_hedging
            for c in candidates:
                domain = infer_domain(c)
                hedge_check = lint_hedging(final_text, domain, calibration_by_domain)
                if hedge_check["violation"]:
                    logger.info(
                        f"[compose] digest hedging violation for slot={slot}: domain={domain} "
                        f"confidence={hedge_check['confidence']} — killing unhedged low-confidence digest"
                    )
                    review = {
                        "verdict": "kill",
                        "reason": (
                            f"[hedging linter] unhedged claim in '{domain}' domain (from one of "
                            f"{len(candidates)} batched items), whose predictions have only been "
                            f"right {hedge_check['confidence']:.0%} of the time recently — original "
                            f"review verdict was {review['verdict']!r}: {review['reason']}"
                        ),
                        "edited_text": None,
                    }
                    final_text = None
                    break

        digest_refs = list(composed["refs"]) + [f"digest_candidate:{cid}" for cid in other_ids]

        async with factory() as db:
            await db.execute(text("""
                INSERT INTO composed_utterance
                    (id, candidate_id, user_id, text, refs, urgency, slot, review_verdict, review_reason, final_text)
                VALUES
                    (:id, :cid, :uid, :text, CAST(:refs AS jsonb), :urgency, :slot, :verdict, :reason, :final_text)
            """), {
                "id": str(uuid.uuid4()), "cid": primary["id"], "uid": user_id,
                "text": composed["text"], "refs": json.dumps(digest_refs),
                "urgency": composed["urgency"], "slot": slot,
                "verdict": review["verdict"], "reason": review["reason"], "final_text": final_text,
            })
            # Every contributing candidate advances to composed — not just
            # the primary — so none of them can be re-picked-up (this is
            # the "tell-once ledger, individually" requirement).
            for c in candidates:
                await db.execute(text("""
                    UPDATE say_candidate SET status = :status
                    WHERE id = :cid AND user_id = :uid
                """), {"status": CandidateStatus.COMPOSED.value, "cid": c["id"], "uid": user_id})
            await db.commit()

        stats["composed"] += 1
        stats["digested"] += len(candidates)
        stats[_VERDICT_STAT_KEY[review["verdict"]]] += 1

    for r in individual_rows:
        candidate = {
            "id": str(r.id), "kind": r.kind, "summary": r.summary,
            "evidence": r.evidence, "judge_reason": r.judge_reason,
        }

        try:
            composed = await compose_utterance(candidate, brief_text, recent_chat, user_id=user_id)
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

        # Arc 4.1 "consequence with teeth": review approving/editing a
        # claim doesn't override a proven-unreliable domain going out
        # unhedged. Deterministic, runs regardless of what the LLM review
        # decided — the actual enforcement, not just a logged finding.
        if final_text and calibration_by_domain:
            from app.services.voice_linter import infer_domain, lint_hedging
            domain = infer_domain(candidate)
            hedge_check = lint_hedging(final_text, domain, calibration_by_domain)
            if hedge_check["violation"]:
                logger.info(
                    f"[compose] hedging violation for {candidate['id']}: domain={domain} "
                    f"confidence={hedge_check['confidence']} — killing unhedged low-confidence claim"
                )
                review = {
                    "verdict": "kill",
                    "reason": (
                        f"[hedging linter] unhedged claim in '{domain}' domain, whose predictions "
                        f"have only been right {hedge_check['confidence']:.0%} of the time recently — "
                        f"original review verdict was {review['verdict']!r}: {review['reason']}"
                    ),
                    "edited_text": None,
                }
                final_text = None

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
