"""
Fact verification loop (ONE_MIND §3.4 / §5).

Sara extracts facts about David's world with a confidence score, but low-
confidence facts just sat there — never confirmed, never retired, quietly
polluting recall. This loop closes that: it surfaces the ripest unverified fact
as ONE natural yes/no question at a natural moment, and David's answer either
*graduates* the fact (→ confirmed tier) or *retires* it. Facts trend toward
truth instead of accreting.

Discipline (feedback_no_repetitive_nags): one question at a time, a hard daily
cap, and a per-fact cooldown so the same fact is never re-asked for days. This
is the mechanism behind the evening-recap line in the acceptance day:
  "I have 'leaves for work at 7' as confirmed — still right?" → tap yes → graduates.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

DAVID_USER_ID = get_owner_id()

# A fact is "unverified" below this confidence with no real confirmations.
_UNVERIFIED_BELOW = 0.55
# On confirm, graduate to a solid confirmed value.
_CONFIRMED_CONFIDENCE = 0.85
# Per-fact re-ask cooldown, and daily question cap.
_ASK_COOLDOWN_SECONDS = 7 * 24 * 3600
_DAILY_CAP = 2

_ASKED_KEY = "fact_verify:asked:{user_id}"      # hash pkg_id -> iso ts
_COUNT_KEY = "fact_verify:count:{user_id}:{day}"  # daily counter

# Ephemeral subjects should DECAY, not be verified — asking David to confirm the
# weather is nonsense. These are forgotten by the dreaming pass, not this loop.
_EPHEMERAL = (
    "weather", "forecast", "snow", "rain", "temperature", "traffic", "road",
    "commute time", "today", "right now", "currently", "this morning",
)


async def _redis():
    from app.core.redis import get_redis
    return await get_redis()


def _is_ephemeral(subject: str, predicate: str) -> bool:
    blob = f"{subject} {predicate}".lower()
    return any(k in blob for k in _EPHEMERAL)


def _fact_text(subject: str, predicate: str, obj: str) -> str:
    parts = [p.strip() for p in (subject, predicate, obj) if p and p.strip()]
    return " ".join(parts).replace("  ", " ").strip()


def _phrase(subject: str, predicate: str, obj: str) -> str:
    """A natural, low-pressure verification question."""
    text = _fact_text(subject, predicate, obj)
    return f"Quick memory check — I have this noted: “{text}”. Still accurate?"


def _list_unverified(limit: int = 25) -> List[Dict[str, Any]]:
    """Pull candidate unverified facts from Neo4j (sync driver)."""
    try:
        from app.services.personal_knowledge_graph import personal_kg
        if not personal_kg._ensure_driver():
            return []
        with personal_kg.driver.session() as session:
            rows = session.run("""
                MATCH (f:PKG_Fact)
                WHERE f.confidence < $thresh
                  AND coalesce(f.times_confirmed, 1) <= 1
                  AND coalesce(f.subject, '') <> ''
                RETURN f.pkg_id AS pkg_id, f.subject AS subject,
                       f.predicate AS predicate, f.object AS object,
                       f.confidence AS confidence, coalesce(f.category,'') AS category
                ORDER BY f.confidence ASC
                LIMIT $limit
            """, {"thresh": _UNVERIFIED_BELOW, "limit": limit})
            return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"[fact_verify] list_unverified failed: {e}")
        return []


async def count_unverified() -> int:
    """Total unverified facts — the metric that must trend down week-over-week."""
    try:
        from app.services.personal_knowledge_graph import personal_kg
        if not personal_kg._ensure_driver():
            return 0
        with personal_kg.driver.session() as session:
            row = session.run("""
                MATCH (f:PKG_Fact)
                WHERE f.confidence < $thresh AND coalesce(f.times_confirmed, 1) <= 1
                RETURN count(*) AS c
            """, {"thresh": _UNVERIFIED_BELOW}).single()
            return int(row["c"]) if row else 0
    except Exception as e:
        logger.debug(f"[fact_verify] count_unverified failed: {e}")
        return 0


async def pick_question(user_id: str = DAVID_USER_ID, mark_asked: bool = True) -> Optional[Dict[str, Any]]:
    """Return the ripest unverified fact as a question, or None if there's
    nothing to ask, the daily cap is hit, or everything is on cooldown."""
    r = await _redis()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    count_key = _COUNT_KEY.format(user_id=user_id, day=day)
    asked_key = _ASKED_KEY.format(user_id=user_id)

    try:
        sent_today = int(await r.get(count_key) or 0)
    except Exception:
        sent_today = 0
    if sent_today >= _DAILY_CAP:
        return None

    asked = await r.hgetall(asked_key) or {}
    now = datetime.now(timezone.utc)

    for fact in _list_unverified():
        pkg_id = fact.get("pkg_id")
        if not pkg_id:
            continue
        if _is_ephemeral(fact.get("subject", ""), fact.get("predicate", "")):
            continue
        # cooldown check
        last = asked.get(pkg_id)
        if last:
            try:
                age = (now - datetime.fromisoformat(last)).total_seconds()
                if age < _ASK_COOLDOWN_SECONDS:
                    continue
            except Exception:
                pass

        question = _phrase(fact.get("subject", ""), fact.get("predicate", ""), fact.get("object", ""))
        if mark_asked:
            await r.hset(asked_key, pkg_id, now.isoformat())
            await r.expire(asked_key, _ASK_COOLDOWN_SECONDS * 2)
            await r.incr(count_key)
            await r.expire(count_key, 2 * 24 * 3600)
        return {
            "pkg_id": pkg_id,
            "question": question,
            "fact": _fact_text(fact.get("subject", ""), fact.get("predicate", ""), fact.get("object", "")),
            "confidence": fact.get("confidence"),
        }
    return None


async def record_answer(user_id: str, pkg_id: str, confirmed: bool) -> Dict[str, Any]:
    """Apply David's answer. confirmed → graduate to the confirmed tier; denied
    → retire the fact (delete node + its pgvector shadow)."""
    from app.services.personal_knowledge_graph import personal_kg

    if confirmed:
        ok = personal_kg.mark_reviewed(pkg_id, new_confidence=_CONFIRMED_CONFIDENCE)
        # bump times_confirmed so it can't be re-picked as unverified
        try:
            if personal_kg._ensure_driver():
                with personal_kg.driver.session() as session:
                    session.run("""
                        MATCH (f {pkg_id: $pkg_id})
                        SET f.times_confirmed = coalesce(f.times_confirmed, 1) + 1
                    """, {"pkg_id": pkg_id})
        except Exception as e:
            logger.debug(f"[fact_verify] times_confirmed bump failed: {e}")
        _sync_embedding_confidence(pkg_id, _CONFIRMED_CONFIDENCE)
        return {"pkg_id": pkg_id, "outcome": "graduated", "confidence": _CONFIRMED_CONFIDENCE, "ok": ok}

    # denied → retire
    deleted = False
    try:
        if personal_kg._ensure_driver():
            with personal_kg.driver.session() as session:
                session.run("MATCH (f {pkg_id: $pkg_id}) DETACH DELETE f", {"pkg_id": pkg_id})
                deleted = True
    except Exception as e:
        logger.warning(f"[fact_verify] retire (neo4j delete) failed: {e}")
    _delete_embedding(pkg_id)
    return {"pkg_id": pkg_id, "outcome": "retired", "deleted": deleted}


def _sync_embedding_confidence(pkg_id: str, confidence: float) -> None:
    try:
        from sqlalchemy import text
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            db.execute(text("UPDATE pkg_embedding SET confidence = :c WHERE pkg_id = :p"),
                       {"c": confidence, "p": pkg_id})
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"[fact_verify] embedding confidence sync failed: {e}")


def _delete_embedding(pkg_id: str) -> None:
    try:
        from sqlalchemy import text
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            db.execute(text("DELETE FROM pkg_embedding WHERE pkg_id = :p"), {"p": pkg_id})
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"[fact_verify] embedding delete failed: {e}")
