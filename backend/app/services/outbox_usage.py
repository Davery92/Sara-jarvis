"""Phase G step 7 usage-window counter (work-order 2026-07-30).

Real, best-effort instrumentation of outbox_item traffic through the two
live read endpoints (compute_badge/build_unified_inbox) and the live write
path (attention_queue.create_item/mark_engaged/mark_archived/mark_completed
and the auxiliary UPDATE paths in notification_ack/memory_subscribers/
tasks). Never blocks or raises — a counting failure must not affect the
request it's counting.

David's bar: >=50 reads, >=20 writes across web + iOS, badge parity on
every check, zero regressions — measured as real traffic accrues, not
manufactured.
"""
import logging

logger = logging.getLogger(__name__)


def record_read(surface: str) -> None:
    try:
        from app.db.base import SessionLocal
        from sqlalchemy import text
        with SessionLocal() as db:
            db.execute(text(
                "INSERT INTO outbox_usage_log (kind, surface) VALUES ('read', :s)"
            ), {"s": surface[:50]})
            db.commit()
    except Exception as e:
        logger.debug(f"outbox usage read-count skipped: {e}")


async def record_write_async(surface: str) -> None:
    try:
        from app.db.session import get_async_session_factory
        from sqlalchemy import text
        factory = get_async_session_factory()
        async with factory() as db:
            await db.execute(text(
                "INSERT INTO outbox_usage_log (kind, surface) VALUES ('write', :s)"
            ), {"s": surface[:50]})
            await db.commit()
    except Exception as e:
        logger.debug(f"outbox usage write-count skipped: {e}")


def usage_summary() -> dict:
    from app.db.base import SessionLocal
    from sqlalchemy import text
    with SessionLocal() as db:
        row = db.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM outbox_usage_log WHERE kind = 'read') AS reads,
                (SELECT COUNT(*) FROM outbox_usage_log WHERE kind = 'write') AS writes,
                (SELECT COUNT(DISTINCT surface) FROM outbox_usage_log WHERE kind = 'read') AS read_surfaces,
                (SELECT MIN(created_at) FROM outbox_usage_log) AS since
        """)).fetchone()
        return {
            "reads": row.reads or 0,
            "writes": row.writes or 0,
            "read_surfaces": row.read_surfaces or 0,
            "since": row.since.isoformat() if row.since else None,
            "meets_bar": (row.reads or 0) >= 50 and (row.writes or 0) >= 20,
        }
