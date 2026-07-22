"""Database maintenance — weekly ANALYZE so the planner (and any stats-reading
self-diagnostics) work off real numbers.

Audit finding B8: only 35 of 287 tables had ever been auto-analyzed;
`pg_stat_user_tables.n_live_tup` claimed `note_connection` = 0 (real: 9,906),
`push_token` = 0 (real: 1), `note` = 16 (real: 2,185). The query planner plans
against fiction and any introspection reading pg stats inherits it. A plain
weekly ANALYZE keeps statistics honest.

Returns an outcome contract (`{"effect": ..., ...}`) per M1 so the beat wrapper
can tell whether the task actually did its job.
"""
import asyncio
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _analyze() -> dict:
    from app.db.session import get_async_session_factory
    from sqlalchemy import text

    async_session = get_async_session_factory()
    engine = async_session.kw["bind"]

    _stale_sql = text(
        """
        SELECT COUNT(*) FROM pg_stat_user_tables
        WHERE last_analyze IS NULL AND last_autoanalyze IS NULL
        """
    )

    # ANALYZE cannot run inside a transaction block, so take a dedicated
    # connection in AUTOCOMMIT from the start (set before any statement opens a
    # transaction — setting it afterward raises InvalidRequestError).
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        stale_before = (await conn.execute(_stale_sql)).scalar() or 0
        await conn.execute(text("ANALYZE"))
        stale_after = (await conn.execute(_stale_sql)).scalar() or 0

    logger.info(
        "DB maintenance ANALYZE complete: never-analyzed tables %d -> %d",
        stale_before, stale_after,
    )
    # Outcome contract: the effect is "database analyzed". stale_after should be
    # ~0; if it isn't, something is preventing stats collection (surfaced to
    # interoception via the contract).
    return {
        "effect": "analyzed_database",
        "never_analyzed_before": int(stale_before),
        "never_analyzed_after": int(stale_after),
    }


@celery_app.task(name="app.tasks.db_maintenance.run_analyze")
def run_analyze():
    """Weekly full-database ANALYZE (B8)."""
    return _run_async(_analyze())
