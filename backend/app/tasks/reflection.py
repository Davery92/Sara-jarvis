"""
Reflection system Celery tasks.

Handles:
- Periodic reflection cycles (every 4 hours)
- Proposal outcome assessment
- Scratchpad cleanup
"""

import logging
import asyncio
from datetime import datetime, timedelta

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

    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url.startswith("postgresql+psycopg://"):
        async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    else:
        async_url = database_url

    engine = create_async_engine(async_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
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
    finally:
        await engine.dispose()


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

    from app.services.karma import get_karma_service, KarmaEvent

    database_url = os.getenv("DATABASE_URL")

    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url.startswith("postgresql+psycopg://"):
        async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    else:
        async_url = database_url

    engine = create_async_engine(async_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with async_session() as db:
            # Get proposal details
            result = await db.execute(
                text("""
                    SELECT status, target_agent, karma_state_at_implementation
                    FROM prompt_proposals
                    WHERE proposal_id = :proposal_id
                """),
                {"proposal_id": proposal_id}
            )
            row = result.fetchone()

            if not row or row[0] != "implemented":
                return {"status": "skipped", "reason": "Proposal not implemented"}

            target_agent = row[1]
            karma_at_impl = row[2] or {}

            # Get current karma
            karma_service = await get_karma_service(db)
            current_karma = await karma_service.get_agent_karma(target_agent)

            if not current_karma:
                return {"status": "error", "reason": "Agent not found"}

            # Calculate delta
            old_score = karma_at_impl.get("composite_score", 50)
            new_score = current_karma.composite_score
            delta = new_score - old_score

            # Determine assessment
            if delta > 2:
                assessment = "improvement"
                reflection_delta = 2.0
            elif delta < -2:
                assessment = "regression"
                reflection_delta = -3.0
                logger.warning(f"Proposal {proposal_id} may have caused regression")
            else:
                assessment = "neutral"
                reflection_delta = 0

            # Update proposal
            await db.execute(
                text("""
                    UPDATE prompt_proposals
                    SET outcome_assessment = :assessment,
                        outcome_karma_delta = :delta
                    WHERE proposal_id = :proposal_id
                """),
                {
                    "proposal_id": proposal_id,
                    "assessment": assessment,
                    "delta": delta,
                }
            )

            # Adjust reflection karma
            if reflection_delta != 0:
                await karma_service.record_event(KarmaEvent(
                    agent_id="reflection",
                    dimension_name="insight_quality",
                    delta=reflection_delta,
                    reason=f"Proposal {proposal_id} assessment: {assessment} (delta={delta:.1f})",
                    evidence_type="proposal_outcome",
                    evidence_ids=[str(proposal_id)],
                ))

            await db.commit()

            return {
                "status": "assessed",
                "assessment": assessment,
                "karma_delta": delta,
            }
    finally:
        await engine.dispose()


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

    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url.startswith("postgresql+psycopg://"):
        async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    else:
        async_url = database_url

    engine = create_async_engine(async_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with async_session() as db:
            scratchpad = await get_reflection_scratchpad(db)
            count = await scratchpad.cleanup_expired()

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "expired_removed": count,
            }
    finally:
        await engine.dispose()


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

    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url.startswith("postgresql+psycopg://"):
        async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    else:
        async_url = database_url

    engine = create_async_engine(async_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
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
                "timestamp": datetime.utcnow().isoformat(),
                "scratchpad_summary": summary,
                "proposal_stats": proposal_stats,
            }

            logger.info(f"Reflection report: {summary}")
            return report
    finally:
        await engine.dispose()
