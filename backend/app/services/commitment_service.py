"""Commitments (SARA_MIND_V2_PLAN §3.9) — replaces `sara_goal`, which was
already dead code (0 references, 3 rows ever per the audit). A commitment
is something Sara told David she'd track: "I'll watch X and tell you when
Y." Created by the judge (or a chat verb, or the appraisal loop), rendered
in the World Brief's OPEN LOOPS, closed explicitly — closure itself becomes
a `say_candidate` so "it woke up — done" gets said, not silently marked
done in a table nobody reads (the fate `sara_goal` actually met).
"""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


async def create_commitment(
    db,
    user_id: str,
    text_: str,
    created_from: str,
    trigger_at=None,
    trigger_description: Optional[str] = None,
) -> UUID:
    row = (await db.execute(text("""
        INSERT INTO sara_commitment (user_id, text, created_from, trigger_at, trigger_description)
        VALUES (:uid, :text, :created_from, :trigger_at, :trigger_description)
        RETURNING id
    """), {
        "uid": user_id, "text": text_, "created_from": created_from,
        "trigger_at": trigger_at, "trigger_description": trigger_description,
    })).first()
    await db.commit()
    return row.id


async def list_open_commitments(db, user_id: str = DEFAULT_USER_ID, limit: int = 20) -> List[Dict[str, Any]]:
    rows = (await db.execute(text("""
        SELECT id, text, created_from, trigger_at, trigger_description, created_at
        FROM sara_commitment
        WHERE user_id = :uid AND status = 'open'
        ORDER BY created_at ASC LIMIT :limit
    """), {"uid": user_id, "limit": limit})).fetchall()
    return [
        {
            "id": str(r.id), "text": r.text, "created_from": r.created_from,
            "trigger_at": r.trigger_at.isoformat() if r.trigger_at else None,
            "trigger_description": r.trigger_description,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def close_commitment(
    db,
    user_id: str,
    commitment_id: str,
    closure_note: str,
    make_candidate: bool = True,
) -> bool:
    """Mark done + (by default) create a say_candidate so the closure gets
    a chance to be SAID ("the Jetson deploy woke up — done"), not just
    silently marked complete in a table nobody reads."""
    row = (await db.execute(text("""
        UPDATE sara_commitment
        SET status = 'done', closure_note = :note, closed_at = NOW()
        WHERE id = :id AND user_id = :uid AND status = 'open'
        RETURNING text
    """), {"id": commitment_id, "uid": user_id, "note": closure_note})).first()
    await db.commit()
    if not row:
        return False

    await _close_brief_entry(db, user_id, commitment_id)

    if make_candidate:
        try:
            from app.services.say_candidate import create_candidate
            await create_candidate(
                db, user_id, source="commitment_service", kind="inform",
                summary=f"Commitment closed: {row.text} — {closure_note}",
                evidence=[{"commitment_id": commitment_id}],
                value_guess=0.6,
            )
        except Exception as e:
            logger.warning(f"[commitment_service] closure candidate failed: {e}")

    return True


async def drop_commitment(db, user_id: str, commitment_id: str, reason: str) -> bool:
    row = (await db.execute(text("""
        UPDATE sara_commitment
        SET status = 'dropped', closure_note = :note, closed_at = NOW()
        WHERE id = :id AND user_id = :uid AND status = 'open'
        RETURNING id
    """), {"id": commitment_id, "uid": user_id, "note": reason})).first()
    await db.commit()
    if row is None:
        return False
    await _close_brief_entry(db, user_id, commitment_id)
    return True


async def _close_brief_entry(db, user_id: str, commitment_id: str) -> None:
    """The sweep only upserts CURRENTLY open commitments — it never learns
    a commitment just closed, so without this the stale "Sara commitment:
    ..." line would linger in OPEN LOOPS forever. Close it immediately
    instead of waiting on the next sweep to notice something it can't."""
    try:
        from app.services.world_brief import brief_patch
        await brief_patch(
            db, user_id, op="close", section="open_loops",
            item_key=f"commitment:{commitment_id}", source="commitment_service",
        )
    except Exception as e:
        logger.warning(f"[commitment_service] brief close failed: {e}")
