"""
ACS auditor Celery tasks.

The watchdog (rule-based) runs inline inside Sara's session loop. The
periodic auditor runs as a beat task and uses an LLM check to catch the
softer failure modes (drift, scope creep, ignoring the day's plan) that
the rules wouldn't catch.

Every 20 minutes, this task wakes up, looks at any actively-running
ACS session, asks the auditor LLM "is Sara making meaningful progress?",
and if the answer is no, triggers an audit dialogue.
"""

import asyncio
import logging

from sqlalchemy import text

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.acs_auditor.periodic_audit_check",
    queue="acs",
    max_retries=0,
)
def periodic_audit_check():
    """Beat-driven check that asks the auditor LLM if Sara is making progress."""
    try:
        return asyncio.run(_periodic_audit_check_async())
    except Exception as e:
        logger.warning(f"Periodic audit check failed: {e}")
        return {"error": str(e)}


async def _periodic_audit_check_async() -> dict:
    from app.db.session import get_async_session_factory
    from app.services.acs.auditor import (
        acquire_audit_lock,
        release_audit_lock,
        count_session_audits,
        run_dialogue,
        is_audit_locked,
        MAX_AUDITS_PER_SESSION,
        _read_recent_transcript,
        _format_recent_transcript,
        _llm_call,
    )

    async_session = get_async_session_factory()

    # Find active sessions that have been running long enough to warrant a check.
    # We don't audit a session that just started.
    async with async_session() as db:
        rows = (await db.execute(text("""
            SELECT id::text, user_id, started_at, turns_completed,
                   EXTRACT(EPOCH FROM (NOW() - started_at))/60 AS elapsed_min
            FROM acs_session
            WHERE state = 'autonomous'
              AND started_at < NOW() - INTERVAL '20 minutes'
            ORDER BY started_at ASC
        """))).fetchall()

    if not rows:
        return {"checked": 0, "skipped": 0, "audited": 0}

    audited = 0
    skipped = 0

    for row in rows:
        session_id = row[0]
        user_id = row[1]
        turns = row[3] or 0
        elapsed_min = float(row[4] or 0)

        # Skip if locked
        if await is_audit_locked(session_id):
            skipped += 1
            continue
        # At audit ceiling: force-stop the session instead of letting it
        # run unsupervised. This closes the gap where the periodic task
        # could bypass the ceiling and let stuck sessions run forever.
        audit_count = await count_session_audits(session_id)
        if audit_count >= MAX_AUDITS_PER_SESSION:
            logger.warning(
                f"Periodic check: session {session_id[:8]} at audit ceiling "
                f"({MAX_AUDITS_PER_SESSION}); force-stopping"
            )
            # Persist transcript before force-stopping
            try:
                import redis.asyncio as aioredis
                import json as _json
                import os
                _redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
                r = await aioredis.from_url(_redis_url, decode_responses=True)
                try:
                    raw = await r.get(f"sara:acs:transcript:{session_id}")
                finally:
                    if hasattr(r, "aclose"):
                        await r.aclose()
                    else:
                        await r.close()
                if raw:
                    from app.services.acs.audit_logger import TranscriptBuffer, persist_transcript_durable_only
                    data = _json.loads(raw)
                    buf = TranscriptBuffer(data["session_id"], data.get("mode"))
                    buf.started_at = data.get("started_at", "")
                    buf.entries = data.get("entries", [])
                    await persist_transcript_durable_only(user_id, buf)
            except Exception as e:
                logger.debug(f"Force-stop transcript persist failed for {session_id[:8]}: {e}")
            try:
                async with async_session() as db:
                    await db.execute(text("""
                        UPDATE acs_session
                        SET state = 'pausing',
                            end_reason = COALESCE(end_reason, 'audit_ceiling')
                        WHERE id = :sid AND state = 'autonomous'
                    """), {"sid": session_id})
                    await db.commit()
            except Exception as e:
                logger.error(f"Failed to force-stop session {session_id[:8]}: {e}")
            skipped += 1
            continue

        # Pull the latest transcript and ask a quick LLM check
        recent = await _read_recent_transcript(session_id)
        if not recent:
            skipped += 1
            continue
        transcript_text = _format_recent_transcript(recent)

        check_prompt = f"""You are a quick progress checker for Sara's autonomous AI session.

Session has been running for {elapsed_min:.0f} minutes ({turns} turns recorded).

## Recent Transcript
{transcript_text}

## Question
Is Sara making meaningful, concrete progress right now? Answer in this exact format on a single line:

VERDICT: PROGRESS | STUCK | DRIFTING
REASON: <one sentence>

- PROGRESS: she's actively producing useful artifacts (notes, results, decisions)
- STUCK: she's looping on the same blocker, repeating tool calls, or going in circles
- DRIFTING: she's wandering off-topic from her stated mode/plan
"""
        check_response = await _llm_call([
            {"role": "system", "content": "You are a brief, judgmental progress checker. Be honest. Single line answer in the requested format."},
            {"role": "user", "content": check_prompt},
        ])

        verdict = "PROGRESS"
        reason = "(no LLM response)"
        for line in (check_response or "").splitlines():
            line = line.strip()
            if line.upper().startswith("VERDICT:"):
                v = line.split(":", 1)[1].strip().upper()
                if "STUCK" in v:
                    verdict = "STUCK"
                elif "DRIFTING" in v:
                    verdict = "DRIFTING"
                else:
                    verdict = "PROGRESS"
            elif line.upper().startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()

        if verdict == "PROGRESS":
            skipped += 1
            logger.debug(f"Periodic audit: session {session_id[:8]} → PROGRESS, {reason[:80]}")
            continue

        # Trigger an audit dialogue
        full_reason = f"Periodic check ({elapsed_min:.0f}min in, {turns} turns): {verdict} — {reason}"
        logger.info(f"Periodic auditor firing on session {session_id[:8]}: {full_reason[:140]}")

        got_lock = await acquire_audit_lock(session_id)
        if not got_lock:
            skipped += 1
            continue

        # Mark state
        try:
            async with async_session() as db:
                await db.execute(text("""
                    UPDATE acs_session SET state = 'audit_paused'
                    WHERE id = :sid AND state = 'autonomous'
                """), {"sid": session_id})
                await db.commit()
        except Exception:
            pass

        try:
            await run_dialogue(
                session_id=session_id,
                user_id=user_id,
                trigger_kind="periodic_checkin",
                trigger_reason=full_reason,
                prior_audit_count=audit_count,
            )
            audited += 1
        except Exception as e:
            logger.error(f"Periodic audit dialogue crashed: {e}", exc_info=True)
        finally:
            try:
                async with async_session() as db:
                    await db.execute(text("""
                        UPDATE acs_session SET state = 'autonomous'
                        WHERE id = :sid AND state = 'audit_paused'
                    """), {"sid": session_id})
                    await db.commit()
            except Exception:
                pass
            await release_audit_lock(session_id)

    # Safety-net: durable-persist transcripts for all active sessions.
    # Even if the in-loop rate-limited persist missed a window, the auditor
    # runs every ~20min and ensures Postgres has the latest snapshot.
    for row in rows:
        session_id = row[0]
        user_id = row[1]
        try:
            import redis.asyncio as aioredis
            import json as _json
            import os
            _redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            r = await aioredis.from_url(_redis_url, decode_responses=True)
            try:
                raw = await r.get(f"sara:acs:transcript:{session_id}")
            finally:
                if hasattr(r, "aclose"):
                    await r.aclose()
                else:
                    await r.close()
            if raw:
                from app.services.acs.audit_logger import TranscriptBuffer, persist_transcript_durable_only
                data = _json.loads(raw)
                buf = TranscriptBuffer(data["session_id"], data.get("mode"))
                buf.started_at = data.get("started_at", "")
                buf.entries = data.get("entries", [])
                await persist_transcript_durable_only(user_id, buf)
        except Exception as e:
            logger.debug(f"Safety-net transcript persist failed for {session_id[:8]}: {e}")

    return {
        "checked": len(rows),
        "audited": audited,
        "skipped": skipped,
    }
