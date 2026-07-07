"""One-time historical person seed — SARA_UNLEASHED Phase D.1.

R9: the person table has ~4 organically-created rows after a week because
inflow is inbound-email-only going forward, never backfilled. This replays
every existing `email` row (chronological, oldest first) through the exact
same `upsert_person_from_email()` the live inbound sync already uses — no
new merge logic, no duplicated identity matching — so the cadence EWMAs in
`signal_baseline` are real from day one instead of needing weeks to warm up.

Deliberately breaks the project's usual "no backfill" rule, and says so:
every person row CREATED by this pass (not merged into an existing organic
row) is tagged `notes='seed_2026_07'` so it's a one-statement reversible
operation: `DELETE FROM person WHERE notes = 'seed_2026_07'`.
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)

SEED_TAG = "seed_2026_07"


async def seed_people_from_email_history(user_id: str) -> Dict[str, int]:
    from sqlalchemy import text
    from app.db.session import get_async_session_factory
    from app.services.person_service import upsert_person_from_email

    factory = get_async_session_factory()
    processed = 0
    skipped = 0

    async with factory() as db:
        existing_ids = {
            r[0] for r in (await db.execute(text(
                "SELECT id FROM person WHERE user_id = :uid"
            ), {"uid": user_id})).fetchall()
        }

        rows = (await db.execute(text("""
            SELECT sender_email, sender_name, category
            FROM email
            WHERE user_id = :uid
            ORDER BY received_at ASC
        """), {"uid": user_id})).fetchall()

        for sender_email, sender_name, category in rows:
            person_id = await upsert_person_from_email(
                db, user_id, sender_email, sender_name,
                category=category, direction="email_in",
            )
            if person_id:
                processed += 1
            else:
                skipped += 1
        await db.commit()

        new_ids = {
            r[0] for r in (await db.execute(text(
                "SELECT id FROM person WHERE user_id = :uid"
            ), {"uid": user_id})).fetchall()
        } - existing_ids

        if new_ids:
            await db.execute(text("""
                UPDATE person SET notes = :tag
                WHERE id = ANY(:ids) AND (notes IS NULL OR notes = '')
            """), {"tag": SEED_TAG, "ids": list(new_ids)})
            await db.commit()

    logger.info(
        f"person seed: {len(rows)} emails replayed, {processed} upserts, "
        f"{skipped} skipped (bulk senders), {len(new_ids)} new person rows tagged '{SEED_TAG}'"
    )
    return {
        "emails_replayed": len(rows),
        "upserts": processed,
        "skipped": skipped,
        "new_person_rows": len(new_ids),
    }
