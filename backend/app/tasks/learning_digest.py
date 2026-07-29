"""
Weekly learning digest — Phase 6 of PHENOMENAL_ASSISTANT_PLAN.md.

The theta table moves invisibly week to week. Trust comes from seeing it.
Runs Sunday ~7 PM ET: snapshots current theta, diffs against last week's
snapshot, adds 7-day promotion/engagement stats + behavioral_pattern
accept/reject counts, and has the LLM craft one first-person note in Sara's
voice ("I've backed off HRV dips — you never open them.") — journal entry +
normal-priority inbox item, never a push (this is reflective, not urgent).
"""

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.celery_app import celery_app
from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)
DEFAULT_USER_ID = os.getenv("SOLO_USER_ID", "64f37c56-85cb-4590-8de9-adfc17d343ed")


def _within_last_7_days(iso_timestamp: Optional[str]) -> bool:
    if not iso_timestamp:
        return False
    try:
        ts = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts) <= timedelta(days=7)
    except ValueError:
        return False


def _run_async(coro):
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(name="app.tasks.learning_digest.send_weekly_digest", bind=True, max_retries=0)
def send_weekly_digest(self):
    try:
        return _run_async(_send_weekly_digest_async(DEFAULT_USER_ID))
    except Exception as e:
        logger.warning(f"[learning_digest] failed: {e}")
        raise  # failures must fail — Celery records FAILURE (Phase 1.3)


async def _send_weekly_digest_async(user_id: str) -> dict:
    from sqlalchemy import text
    from app.db.session import get_async_session_factory

    session_factory = get_async_session_factory()
    async with session_factory() as db:
        now = local_now()

        # ── Snapshot current theta (always, before diffing) ──
        current = (await db.execute(text(
            "SELECT domain, context, threshold FROM attention_policy WHERE user_id=:u"
        ), {"u": user_id})).fetchall()
        for domain, context, threshold in current:
            await db.execute(text("""
                INSERT INTO attention_policy_snapshot (id, user_id, domain, context, threshold, captured_at)
                VALUES (:id, :u, :d, :c, :t, :ts)
            """), {"id": str(uuid.uuid4()), "u": user_id, "d": domain, "c": context,
                   "t": threshold, "ts": now})
        await db.commit()

        # ── Diff against ~7 days ago (closest prior snapshot per cell) ──
        prior_rows = (await db.execute(text("""
            SELECT DISTINCT ON (domain, context) domain, context, threshold, captured_at
            FROM attention_policy_snapshot
            WHERE user_id=:u AND captured_at < :cutoff
            ORDER BY domain, context, captured_at DESC
        """), {"u": user_id, "cutoff": now - __import__("datetime").timedelta(days=6)})).fetchall()
        prior = {(d, c): t for d, c, t, _ in prior_rows}

        moves = []
        for domain, context, threshold in current:
            prev = prior.get((domain, context))
            if prev is None:
                continue
            delta = threshold - prev
            if abs(delta) < 0.02:
                continue
            direction = "backed off" if delta > 0 else "leaned in on"
            moves.append({"domain": domain, "context": context, "delta": round(delta, 3), "direction": direction})
        moves.sort(key=lambda m: -abs(m["delta"]))

        # ── 7-day promotion + engagement stats ──
        promo_rows = (await db.execute(text("""
            SELECT domain, count(*) FILTER (WHERE promoted), count(*)
            FROM promotion_event WHERE user_id=:u AND created_at > now() - interval '7 days'
            GROUP BY domain
        """), {"u": user_id})).fetchall()
        promo_stats = [{"domain": d, "promoted": int(p or 0), "evaluated": int(e or 0)} for d, p, e in promo_rows]

        engagement_rows = (await db.execute(text("""
            SELECT category, count(*), sum(CASE WHEN engaged THEN 1 ELSE 0 END)
            FROM notification_log WHERE user_id=:u AND sent_at > now() - interval '7 days' AND sent=true
            GROUP BY category
        """), {"u": user_id})).fetchall()
        engagement_stats = [{"category": c, "sent": int(s or 0), "engaged": int(e or 0)} for c, s, e in engagement_rows]

        # ── behavioral_pattern accepts/rejects (cumulative — no per-week
        # reject timestamp exists, so this is "to date" not "this week") ──
        pattern_row = (await db.execute(text("""
            SELECT count(*) FILTER (WHERE last_accepted_at > now() - interval '7 days'),
                   sum(times_accepted), sum(times_rejected)
            FROM behavioral_pattern WHERE user_id=:u
        """), {"u": user_id})).fetchone()
        pattern_stats = {
            "accepted_this_week": int(pattern_row[0] or 0) if pattern_row else 0,
            "total_accepted": int(pattern_row[1] or 0) if pattern_row else 0,
            "total_rejected": int(pattern_row[2] or 0) if pattern_row else 0,
        }

        # ── Rhythm drift week-over-week (daily_rhythm uses a sync session —
        # bridge it in, same pattern as memory_subscribers' derived refresh) ──
        rhythm_drifts = []
        try:
            import os as _os
            from sqlalchemy import create_engine as _ce
            from sqlalchemy.orm import sessionmaker as _sm, Session as _S
            from app.services.daily_rhythm import get_rhythm_drift

            _db_url = _os.getenv("DATABASE_URL", "")
            if "+asyncpg" in _db_url:
                _db_url = _db_url.replace("+asyncpg", "+psycopg")
            elif "+psycopg" not in _db_url and "postgresql://" in _db_url:
                _db_url = _db_url.replace("postgresql://", "postgresql+psycopg://")
            _eng = _ce(_db_url, echo=False)
            _sess = _sm(_eng, class_=_S, expire_on_commit=False)
            _sdb = _sess()
            try:
                for key in ("wake", "bedtime", "dinner", "gym_window"):
                    drift = get_rhythm_drift(_sdb, user_id, key)
                    if drift:
                        rhythm_drifts.append(drift)
            finally:
                _sdb.close()
                _eng.dispose()
        except Exception as e:
            logger.warning(f"[learning_digest] rhythm drift gather failed: {e}")

        # ── Voice/wake-word stats (B3) — dataset growth + training outcomes
        # this week, straight from the voice control plane's Redis state.
        voice_stats: Dict[str, Any] = {}
        try:
            from app.services.voice.control_plane import list_jobs, get_model_registry as get_voice_model_registry

            recent_voice_jobs = [
                j for j in list_jobs(limit=100)
                if j.get("job_type") in ("train_wake_word", "train_speakers")
                and j.get("status") == "completed"
                and _within_last_7_days(j.get("updated_at"))
            ]
            voice_stats = {
                "wake_word_trainings_completed": sum(1 for j in recent_voice_jobs if j.get("job_type") == "train_wake_word"),
                "speaker_trainings_completed": sum(1 for j in recent_voice_jobs if j.get("job_type") == "train_speakers"),
                "wake_word_active_version": (get_voice_model_registry().get("wake_word") or {}).get("active_version"),
            }
        except Exception as e:
            logger.debug(f"[learning_digest] voice stats gather failed: {e}")

        # ── ML model promotions (C4) — tabular models activated this week.
        ml_promotions = []
        try:
            from app.services.ml.control_plane import get_model_registry as get_ml_model_registry

            ml_registry = get_ml_model_registry()
            for family, entry in ml_registry.items():
                if not isinstance(entry, dict):
                    continue
                for version in entry.get("versions", []):
                    if version.get("status") == "active" and _within_last_7_days(version.get("created_at")):
                        ml_promotions.append({"family": family, "version": version.get("version"), "metrics": version.get("metrics")})
        except Exception as e:
            logger.debug(f"[learning_digest] ml promotions gather failed: {e}")

        if (
            not moves and not promo_stats and pattern_stats["accepted_this_week"] == 0
            and not rhythm_drifts and not voice_stats.get("wake_word_trainings_completed")
            and not voice_stats.get("speaker_trainings_completed") and not ml_promotions
        ):
            logger.info("[learning_digest] nothing to report this week — skipping")
            return {"sent": False, "reason": "nothing_to_report"}

        note = await _craft_digest_note(moves, promo_stats, engagement_stats, pattern_stats, rhythm_drifts, voice_stats, ml_promotions)
        if not note:
            return {"sent": False, "reason": "llm_failed"}

        # Journal entry (Sara's user-facing journal — content, not the
        # internal `thought` field; see gotcha_journal_vs_thought)
        await db.execute(text("""
            INSERT INTO sara_journal (id, user_id, entry_type, content, context, created_at)
            VALUES (:id, :u, 'weekly_digest', :content, CAST(:context AS jsonb), :ts)
        """), {"id": str(uuid.uuid4()), "u": user_id, "content": note,
               "context": json.dumps({
                   "moves": moves, "promo_stats": promo_stats, "pattern_stats": pattern_stats,
                   "rhythm_drifts": [
                       {**d, "this_week_avg": str(d["this_week_avg"]), "last_week_avg": str(d["last_week_avg"])}
                       for d in rhythm_drifts
                   ],
                   "voice_stats": voice_stats, "ml_promotions": ml_promotions,
               }),
               "ts": now})
        await db.commit()

        digest_topic = f"weekly_digest:{now.date().isoformat()}"
        # Arc 1.5 write-freeze: legacy send disabled once
        # MOUTH_ONLY_LEARNING_DIGEST is on — dual-write below is
        # unconditional either way. Flag default OFF.
        from app.core.feature_flags import Flag, is_enabled
        if is_enabled(Flag.MOUTH_ONLY_LEARNING_DIGEST):
            logger.info(f"[mouth-only] learning_digest legacy send skipped (candidate queued): {digest_topic}")
        else:
            from app.services.unified_notification import send_notification
            await send_notification(
                user_id=user_id, title="What I've learned this week", message=note,
                topic=digest_topic, priority="normal", source="learning_digest",
            )

        # Mind V2 rewire plan Workstream B (long tail) — dual-write into the
        # say_candidate queue. Wrapped so a candidate-queue failure never
        # breaks the legacy send above.
        try:
            from datetime import timedelta
            from app.services.say_candidate import create_candidate
            await create_candidate(
                db, user_id=user_id, source="learning_digest", kind="inform",
                summary=note[:2000], evidence=[{"moves": len(moves)}],
                topic_entities=[digest_topic],
                valid_until=now + timedelta(days=7),
                dedupe_key=digest_topic,
            )
        except Exception as e:
            logger.warning(f"[say_candidate] learning_digest dual-write failed: {e}")

        return {"sent": True, "moves": len(moves)}


async def _craft_digest_note(
    moves: list, promo_stats: list, engagement_stats: list, pattern_stats: dict,
    rhythm_drifts: list = None, voice_stats: Optional[Dict[str, Any]] = None,
    ml_promotions: Optional[list] = None,
) -> str:
    """LLM-crafted first-person digest note. enable_thinking off — short output,
    same reasoning as every other short-form background LLM call in this codebase."""
    from app.core.llm import get_background_llm_client

    facts = {
        "attention_threshold_moves": moves[:6],
        "promotions_last_7d": promo_stats,
        "notification_engagement_last_7d": engagement_stats,
        "behavioral_patterns": pattern_stats,
        "rhythm_drift_this_week": [
            f"{d['rhythm_key']} shifted {abs(d['delta_minutes'])} min {d['direction']} "
            f"(was ~{d['last_week_avg']}, now ~{d['this_week_avg']})"
            for d in (rhythm_drifts or [])
        ],
        "voice_wake_word_stats_this_week": voice_stats or {},
        "ml_model_promotions_this_week": ml_promotions or [],
    }
    prompt = (
        "You are Sara, David's assistant, writing a short first-person weekly self-report "
        "on what you've learned about when to speak up, how David's daily rhythm (wake/bed/"
        "meal/gym times) has shifted this week if it has, and any voice/wake-word retraining "
        "or ML model promotions that happened. Use the data below. Be concrete and "
        "specific (name a domain and what changed), not generic. 2-4 sentences. No greeting, "
        "no sign-off — just the note. Omit any category with no data rather than mentioning "
        "'nothing changed' for it.\n\n"
        f"Data: {json.dumps(facts, default=str)}"
    )
    try:
        llm = get_background_llm_client()
        response = await llm.chat_completion(
            messages=[
                {"role": "system", "content": "You write Sara's first-person weekly learning digest. Concrete, warm, brief."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5, max_tokens=250,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        return response["choices"][0]["message"].get("content", "").strip()
    except Exception as e:
        logger.warning(f"[learning_digest] LLM craft failed: {e}")
        return ""
