"""Real turn counter for the legacy 19-source context assembly deletion gate
(work-order item 5, 2026-07-30). David's bar: delete the legacy fallback
once SINGULAR_CONTEXT has >=200 clean real turns logged — event count, not
elapsed time, and not manufactured via replay. See
main_simple.py's `_new_rendered and _context_cutover_live` branch, the one
place a turn genuinely used the new kernel-only assembly instead of the
old ~19-source one.
"""
import logging

logger = logging.getLogger(__name__)


def record_clean_turn(user_id: str) -> None:
    try:
        from app.db.base import SessionLocal
        from sqlalchemy import text
        with SessionLocal() as db:
            db.execute(text(
                "INSERT INTO singular_context_turn_log (user_id) VALUES (:uid)"
            ), {"uid": user_id})
            db.commit()
    except Exception as e:
        logger.debug(f"singular_context turn-count skipped: {e}")


def clean_turn_count() -> dict:
    from app.db.base import SessionLocal
    from sqlalchemy import text
    with SessionLocal() as db:
        row = db.execute(text("""
            SELECT COUNT(*) AS n, MIN(created_at) AS since
            FROM singular_context_turn_log
        """)).fetchone()
        return {
            "count": row.n or 0,
            "since": row.since.isoformat() if row.since else None,
            "meets_bar": (row.n or 0) >= 200,
        }
