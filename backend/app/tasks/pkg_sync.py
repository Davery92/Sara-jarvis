"""PKG sync reconciliation — ensures Neo4j and pgvector shadow table are in sync."""

import asyncio
import logging
import os

from app.celery_app import celery_app
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)
DEFAULT_USER_ID = get_owner_id()


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _reconcile(user_id: str):
    """Check Neo4j node count vs pgvector shadow table and backfill gaps."""
    from app.db.session import get_async_session_factory
    from sqlalchemy import text

    async_session = get_async_session_factory()
    async with async_session() as db:
        # Count pgvector shadow entries.
        # Solo system: pkg_embedding has no user_id column (keyed by pkg_id),
        # so we count all shadow rows. Filtering by :uid raised
        # "column user_id does not exist" every run and the task swallowed it.
        result = await db.execute(text("""
            SELECT COUNT(*) FROM pkg_embedding
        """))
        pg_count = result.scalar() or 0

    # Count Neo4j nodes (sync driver)
    neo4j_count = 0
    try:
        from app.services.personal_knowledge_graph import personal_kg
        if personal_kg._ensure_driver():
            with personal_kg.driver.session() as session:
                result = session.run(
                    "MATCH (n) WHERE EXISTS(n.pkg_id) RETURN COUNT(n) AS cnt"
                )
                record = result.single()
                neo4j_count = record["cnt"] if record else 0
    except Exception as e:
        logger.debug(f"Neo4j count check failed: {e}")
        return {"status": "neo4j_unavailable", "pg_count": pg_count}

    gap = abs(neo4j_count - pg_count)
    logger.info(f"PKG sync: Neo4j={neo4j_count}, pgvector={pg_count}, gap={gap}")

    if gap > 5:
        # Find Neo4j nodes missing from pgvector and re-embed them
        try:
            from app.services.personal_knowledge_graph import personal_kg

            # Get all pkg_ids from Neo4j
            neo4j_ids = set()
            if personal_kg._ensure_driver():
                with personal_kg.driver.session() as session:
                    result = session.run(
                        "MATCH (n) WHERE EXISTS(n.pkg_id) RETURN n.pkg_id AS pid, labels(n)[0] AS lbl, "
                        "n.value AS val LIMIT 500"
                    )
                    neo4j_nodes = [(r["pid"], r["lbl"], r["val"]) for r in result]
                    neo4j_ids = {n[0] for n in neo4j_nodes}

            # Get existing pgvector pkg_ids
            pg_ids = set()
            async with async_session() as db:
                result = await db.execute(text(
                    "SELECT pkg_id FROM pkg_embedding"
                ))
                pg_ids = {r[0] for r in result.fetchall()}

            missing = neo4j_ids - pg_ids
            if missing:
                backfilled = 0
                for pid, lbl, val in neo4j_nodes:
                    if pid in missing and val:
                        fact_type = lbl.replace("PKG_", "") if lbl else "Fact"
                        personal_kg._schedule_embedding(pid, fact_type, {"value": val}, 0.7)
                        backfilled += 1
                logger.info(f"PKG sync: backfilled {backfilled} missing embeddings")
        except Exception as e:
            logger.warning(f"PKG sync backfill failed: {e}")

    return {"neo4j": neo4j_count, "pgvector": pg_count, "gap": gap}


@celery_app.task(name="app.tasks.pkg_sync.reconcile_pkg", bind=True, max_retries=0)
def reconcile_pkg(self):
    """Hourly PKG reconciliation between Neo4j and pgvector."""
    try:
        result = _run_async(_reconcile(DEFAULT_USER_ID))
        return result
    except Exception as e:
        logger.warning(f"PKG reconciliation failed: {e}")


async def _stale_goal_sweep() -> dict:
    """Mark active PKG_Goal nodes whose target_date passed >7 days ago as stale.

    Goals don't auto-close themselves and re-mentioning a past goal used to
    bump its last_confirmed (Sara would keep treating last quarter's "10:30
    call with Matt" as upcoming). Combined with the upsert closed-status
    guard and the context-query freshness filter, this sweep is the safety
    net that prevents indefinite drift.
    """
    from app.services.personal_knowledge_graph import personal_kg
    from datetime import datetime, timezone, timedelta

    if not personal_kg._ensure_driver():
        return {"checked": 0, "marked_stale": 0, "neo4j_unavailable": True}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    marked = 0
    try:
        with personal_kg.driver.session() as s:
            row = s.run(
                """
                MATCH (g:PKG_Goal)
                WHERE g.superseded_by IS NULL
                  AND (g.status IS NULL OR toLower(g.status) = 'active')
                  AND g.target_date IS NOT NULL
                  AND g.target_date < $cutoff
                SET g.status = 'stale',
                    g.stale_at = $now,
                    g.progress_notes = COALESCE(g.progress_notes, '') +
                        ' [auto-stale: target_date passed >7 days ago]'
                RETURN count(g) AS n
                """,
                {"cutoff": cutoff, "now": datetime.now(timezone.utc).isoformat()},
            ).single()
            if row:
                marked = int(row["n"])
        if marked:
            logger.info(f"PKG stale-goal sweep: marked {marked} past-due goals as stale")
    except Exception as e:
        logger.warning(f"PKG stale-goal sweep failed: ({type(e).__name__}) {e}")

    return {"marked_stale": marked, "cutoff_iso": cutoff}


@celery_app.task(name="app.tasks.pkg_sync.stale_goal_sweep", bind=True, max_retries=0)
def stale_goal_sweep(self):
    """Daily: auto-stale PKG_Goal nodes whose target_date passed >7d ago."""
    try:
        return _run_async(_stale_goal_sweep())
    except Exception as e:
        logger.warning(f"PKG stale-goal sweep crashed: ({type(e).__name__}) {e}")
