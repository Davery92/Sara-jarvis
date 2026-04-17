"""
Reflection system Celery tasks.

Handles:
- Periodic reflection cycles (every 4 hours)
- Proposal outcome assessment
- Scratchpad cleanup
"""

import logging
import asyncio
from datetime import datetime, timedelta, timezone

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.reflection.run_reflection_cycle",
    bind=True,
    queue="reflection",
    max_retries=2,
    default_retry_delay=300
)
def run_reflection_cycle(self):
    """
    Run a complete reflection cycle.

    Audits consolidation, detects patterns, generates proposals.
    """
    logger.info("Starting reflection cycle task")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _run_reflection_async()
        )
        logger.info(f"Reflection cycle complete: {result}")
        return result
    except RuntimeError:
        result = asyncio.run(_run_reflection_async())
        logger.info(f"Reflection cycle complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Reflection cycle failed: {e}")
        raise self.retry(exc=e)


async def _run_reflection_async():
    """Async implementation of reflection cycle."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    import os

    from app.services.reflection.agent import get_reflection_agent

    database_url = os.getenv("DATABASE_URL")
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        reflection_agent = await get_reflection_agent(db)
        result = await reflection_agent.run_reflection_cycle()
        result_dict = result.to_dict()

        # Generate policy candidates from reflection (Phase 3 — Cortana Evolution)
        try:
            from app.core.config import settings
            if getattr(settings, 'autonomy_policy_candidates_enabled', False):
                from app.services.autonomy.policy_candidate import policy_candidate_service
                candidate_ids = await policy_candidate_service.generate_from_reflection(
                    db=db, user_id="64f37c56-85cb-4590-8de9-adfc17d343ed",
                    reflection_data=result_dict,
                )
                await db.commit()
                if candidate_ids:
                    logger.info(f"Generated {len(candidate_ids)} policy candidates from reflection")
                    result_dict["policy_candidates"] = len(candidate_ids)
        except Exception as e:
            logger.debug(f"Policy candidate generation from reflection failed (non-fatal): {e}")

        return result_dict


@celery_app.task(
    name="app.tasks.reflection.assess_proposal_outcome",
    bind=True,
    queue="reflection"
)
def assess_proposal_outcome(self, proposal_id: int):
    """
    Assess the outcome of an implemented proposal.

    Called 3 days after proposal implementation to evaluate success.
    """
    logger.info(f"Assessing proposal {proposal_id} outcome")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _assess_proposal_async(proposal_id)
        )
        return result
    except RuntimeError:
        result = asyncio.run(_assess_proposal_async(proposal_id))
        return result
    except Exception as e:
        logger.error(f"Proposal assessment failed: {e}")
        raise


async def _assess_proposal_async(proposal_id: int):
    """Async implementation of proposal outcome assessment."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import os

    database_url = os.getenv("DATABASE_URL")
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        # Get proposal details
        result = await db.execute(
            text("""
                SELECT status, target_agent
                FROM prompt_proposals
                WHERE proposal_id = :proposal_id
            """),
            {"proposal_id": proposal_id}
        )
        row = result.fetchone()

        if not row:
            return {"status": "skipped", "reason": "Proposal not found"}
        if row[0] != "implemented":
            return {
                "status": "skipped",
                "reason": "Proposal not implemented",
                "proposal_status": row[0],
            }

        # Mark as assessed (no karma scoring)
        assessment = "neutral"

        await db.execute(
            text("""
                UPDATE prompt_proposals
                SET outcome_assessment = :assessment
                WHERE proposal_id = :proposal_id
            """),
            {
                "proposal_id": proposal_id,
                "assessment": assessment,
            }
        )

        await db.commit()

        return {
            "status": "assessed",
            "assessment": assessment,
        }


@celery_app.task(
    name="app.tasks.reflection.cleanup_scratchpad",
    bind=True,
    queue="maintenance"
)
def cleanup_scratchpad(self):
    """
    Clean up expired observations from the reflection scratchpad.
    """
    logger.info("Cleaning up reflection scratchpad")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _cleanup_scratchpad_async()
        )
        return result
    except RuntimeError:
        result = asyncio.run(_cleanup_scratchpad_async())
        return result
    except Exception as e:
        logger.error(f"Scratchpad cleanup failed: {e}")
        raise


async def _cleanup_scratchpad_async():
    """Async implementation of scratchpad cleanup."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    import os

    from app.services.reflection.scratchpad import get_reflection_scratchpad

    database_url = os.getenv("DATABASE_URL")
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        scratchpad = await get_reflection_scratchpad(db)
        count = await scratchpad.cleanup_expired()

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "expired_removed": count,
        }


@celery_app.task(
    name="app.tasks.reflection.generate_reflection_report",
    bind=True,
    queue="low_priority"
)
def generate_reflection_report(self):
    """
    Generate a summary report of reflection activity.
    """
    logger.info("Generating reflection report")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _generate_report_async()
        )
        return result
    except RuntimeError:
        result = asyncio.run(_generate_report_async())
        return result
    except Exception as e:
        logger.error(f"Reflection report failed: {e}")
        raise


async def _generate_report_async():
    """Async implementation of reflection report generation."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import os

    from app.services.reflection.scratchpad import get_reflection_scratchpad

    database_url = os.getenv("DATABASE_URL")
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        scratchpad = await get_reflection_scratchpad(db)
        summary = await scratchpad.get_scratchpad_summary()

        # Get proposal stats
        proposal_result = await db.execute(
            text("""
                SELECT status, COUNT(*)
                FROM prompt_proposals
                WHERE created_at > NOW() - INTERVAL '7 days'
                GROUP BY status
            """)
        )
        proposal_stats = dict(proposal_result.fetchall())

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scratchpad_summary": summary,
            "proposal_stats": proposal_stats,
        }

        logger.info(f"Reflection report: {summary}")
        return report
