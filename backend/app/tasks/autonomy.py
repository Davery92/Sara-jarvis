"""
Autonomy system Celery tasks (Phase 4).

Handles:
- Proactive checks (consider if action is needed)
- Anticipation (morning/evening preparation)
- Memory consolidation (nightly processing)
- Learning digest (weekly summary)
- Idle processing (productive quiet time)
"""

import logging
import asyncio
from datetime import datetime, timedelta

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.autonomy.proactive_check",
    bind=True,
    queue="cognitive",
    max_retries=2
)
def proactive_check(self):
    """
    Periodic proactive check - Sara reviews context and considers action.

    Runs every 15 minutes to look for opportunities to help.
    """
    logger.info("Starting proactive check")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _proactive_check_async()
        )
        logger.info(f"Proactive check complete: {result}")
        return result
    except RuntimeError:
        result = asyncio.run(_proactive_check_async())
        logger.info(f"Proactive check complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Proactive check failed: {e}")
        raise self.retry(countdown=60, exc=e)


async def _proactive_check_async():
    """Async implementation of proactive check."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    import os

    from app.services.autonomy.proactive import get_proactive_service
    from app.services.autonomy.coordination import get_coordinator

    # Check if we should run
    coordinator = get_coordinator()
    if not await coordinator.should_run_worker("proactive-check"):
        return {"skipped": "resource_constraints"}

    # Try to acquire exclusive access
    if not await coordinator.acquire_exclusive("proactive-check", "heavy_llm"):
        return {"skipped": "exclusive_group_busy"}

    try:
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
        )

        if database_url.startswith("postgresql://"):
            async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
        elif database_url.startswith("postgresql+psycopg://"):
            async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
        else:
            async_url = database_url

        engine = create_async_engine(async_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as db:
            service = await get_proactive_service(db)
            actions = await service.run_proactive_check()

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "actions_taken": len(actions),
                "action_types": [a.action_type.value for a in actions],
            }

        await engine.dispose()
    finally:
        await coordinator.release_exclusive("heavy_llm")


@celery_app.task(
    name="app.tasks.autonomy.morning_anticipation",
    bind=True,
    queue="cognitive"
)
def morning_anticipation(self):
    """
    Morning anticipation - prepare for the day ahead.

    Runs at 7 AM daily.
    """
    logger.info("Starting morning anticipation")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _anticipation_async("morning")
        )
        logger.info(f"Morning anticipation complete: {result}")
        return result
    except RuntimeError:
        result = asyncio.run(_anticipation_async("morning"))
        logger.info(f"Morning anticipation complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Morning anticipation failed: {e}")
        raise


@celery_app.task(
    name="app.tasks.autonomy.evening_anticipation",
    bind=True,
    queue="cognitive"
)
def evening_anticipation(self):
    """
    Evening anticipation - prepare for tomorrow.

    Runs at 9 PM daily.
    """
    logger.info("Starting evening anticipation")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _anticipation_async("evening")
        )
        logger.info(f"Evening anticipation complete: {result}")
        return result
    except RuntimeError:
        result = asyncio.run(_anticipation_async("evening"))
        logger.info(f"Evening anticipation complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Evening anticipation failed: {e}")
        raise


async def _anticipation_async(time_of_day: str):
    """Async implementation of anticipation."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    import os

    from app.services.autonomy.anticipation import get_anticipation_service
    from app.services.autonomy.coordination import get_coordinator

    coordinator = get_coordinator()
    task_name = f"{time_of_day}-anticipation"

    if not await coordinator.acquire_exclusive(task_name, "heavy_llm"):
        return {"skipped": "exclusive_group_busy"}

    try:
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
        )

        if database_url.startswith("postgresql://"):
            async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
        elif database_url.startswith("postgresql+psycopg://"):
            async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
        else:
            async_url = database_url

        engine = create_async_engine(async_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as db:
            service = await get_anticipation_service(db)

            if time_of_day == "morning":
                preparations = await service.run_morning_anticipation()
            else:
                preparations = await service.run_evening_anticipation()

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "time_of_day": time_of_day,
                "preparations": len(preparations),
                "prep_types": [p.prep_type.value for p in preparations],
            }

        await engine.dispose()
    finally:
        await coordinator.release_exclusive("heavy_llm")


@celery_app.task(
    name="app.tasks.autonomy.nightly_memory_consolidation",
    bind=True,
    queue="maintenance"
)
def nightly_memory_consolidation(self):
    """
    Nightly memory consolidation - process the day's experiences.

    Runs at 3 AM daily.
    """
    logger.info("Starting nightly memory consolidation")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _memory_consolidation_async()
        )
        logger.info(f"Memory consolidation complete: {result}")
        return result
    except RuntimeError:
        result = asyncio.run(_memory_consolidation_async())
        logger.info(f"Memory consolidation complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Memory consolidation failed: {e}")
        raise


async def _memory_consolidation_async():
    """Async implementation of memory consolidation."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import os

    from app.services.autonomy.coordination import get_coordinator

    coordinator = get_coordinator()

    if not await coordinator.acquire_exclusive("nightly-consolidation", "reflection"):
        return {"skipped": "exclusive_group_busy"}

    try:
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
        )

        if database_url.startswith("postgresql://"):
            async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
        elif database_url.startswith("postgresql+psycopg://"):
            async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
        else:
            async_url = database_url

        engine = create_async_engine(async_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as db:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0)

            # Count today's episodes
            episode_result = await db.execute(
                text("""
                    SELECT COUNT(*) FROM episode
                    WHERE created_at >= :today
                """),
                {"today": today_start}
            )
            episode_count = episode_result.fetchone()[0] or 0

            # Mark low-importance episodes for decay (simplified)
            decay_result = await db.execute(
                text("""
                    UPDATE episodes
                    SET importance = importance * 0.95
                    WHERE created_at < :today
                    AND importance < 0.3
                """),
                {"today": today_start}
            )
            decayed = decay_result.rowcount

            # Clean up old working memory
            cleanup_result = await db.execute(
                text("""
                    DELETE FROM working_memory_actions
                    WHERE status = 'completed'
                    AND completed_at < NOW() - INTERVAL '7 days'
                """)
            )
            cleaned = cleanup_result.rowcount

            await db.commit()

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "episodes_today": episode_count,
                "episodes_decayed": decayed,
                "actions_cleaned": cleaned,
            }

        await engine.dispose()
    finally:
        await coordinator.release_exclusive("reflection")


@celery_app.task(
    name="app.tasks.autonomy.weekly_learning_digest",
    bind=True,
    queue="reflection"
)
def weekly_learning_digest(self):
    """
    Weekly learning digest - comprehensive self-assessment.

    Runs Sunday at 10 AM.
    """
    logger.info("Starting weekly learning digest")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _learning_digest_async()
        )
        logger.info(f"Learning digest complete: {result}")
        return result
    except RuntimeError:
        result = asyncio.run(_learning_digest_async())
        logger.info(f"Learning digest complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Learning digest failed: {e}")
        raise


async def _learning_digest_async():
    """
    Async implementation of learning digest.

    PHASE 4: Now invokes Sara to generate a thoughtful weekly digest
    reflecting on growth, learnings, and intentions.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import os

    from app.services.karma import get_karma_service
    from app.services.autonomy.sara_invocation import get_sara_invocation_service

    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
    )

    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url.startswith("postgresql+psycopg://"):
        async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    else:
        async_url = database_url

    engine = create_async_engine(async_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        week_start = datetime.utcnow() - timedelta(days=7)

        # Get karma dashboard
        karma_service = await get_karma_service(db)
        karma_dashboard = await karma_service.get_karma_dashboard()

        # Count interactions
        interaction_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM episode
                WHERE created_at >= :week_start
            """),
            {"week_start": week_start}
        )
        interaction_count = interaction_result.fetchone()[0] or 0

        # Count actions and outcomes
        action_result = await db.execute(
            text("""
                SELECT outcome_status, COUNT(*)
                FROM action_log
                WHERE created_at >= :week_start
                GROUP BY outcome_status
            """),
            {"week_start": week_start}
        )
        action_stats = dict(action_result.fetchall())

        # Count proposals
        proposal_result = await db.execute(
            text("""
                SELECT status, COUNT(*)
                FROM prompt_proposals
                WHERE created_at >= :week_start
                GROUP BY status
            """),
            {"week_start": week_start}
        )
        proposal_stats = dict(proposal_result.fetchall())

        # Build data summary
        raw_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "week_start": week_start.isoformat(),
            "karma": {
                "agents": karma_dashboard.get("agents", []),
                "alerts": karma_dashboard.get("alerts", []),
            },
            "interactions": interaction_count,
            "action_outcomes": action_stats,
            "proposals": proposal_stats,
        }

        # Invoke Sara to generate a thoughtful digest
        try:
            sara = await get_sara_invocation_service(db)

            context_summary = f"""This week's data:
- Total interactions with David: {interaction_count}
- Karma: {karma_dashboard.get('agents', [])}
- Karma alerts: {karma_dashboard.get('alerts', [])}
- Actions taken: {action_stats}
- Proposals: {proposal_stats}"""

            generation_result = await sara.invoke_for_generation(
                context=context_summary,
                prompt="""Generate a thoughtful weekly digest reflecting on your week.
Include:
1. What went well this week
2. Areas where you struggled or could improve
3. Notable interactions or learnings
4. Intentions for next week
5. Any karma-related observations (where you excelled or need work)

Write in first person as Sara. Be genuine and reflective.""",
                max_tokens=800
            )

            digest_content = generation_result.content

            logger.info(f"Weekly digest generated: {interaction_count} interactions")

            return {
                "digest": digest_content,
                "raw_data": raw_data,
                "generated_at": datetime.utcnow().isoformat(),
                "invocation_id": generation_result.invocation_id
            }

        except Exception as e:
            logger.warning(f"Sara digest generation failed, returning raw data: {e}")
            return raw_data

    await engine.dispose()


@celery_app.task(
    name="app.tasks.autonomy.idle_processing",
    bind=True,
    queue="low_priority"
)
def idle_processing(self):
    """
    Idle processing - productive use of quiet time.

    Runs every 10 minutes when system is idle.
    """
    logger.info("Starting idle processing")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _idle_processing_async()
        )
        return result
    except RuntimeError:
        result = asyncio.run(_idle_processing_async())
        return result
    except Exception as e:
        logger.error(f"Idle processing failed: {e}")
        raise


async def _idle_processing_async():
    """Async implementation of idle processing."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text
    import os

    from app.services.autonomy.coordination import get_coordinator

    coordinator = get_coordinator()

    # Check if system is actually idle
    if not await coordinator.should_run_worker("idle-processing"):
        return {"skipped": "not_idle"}

    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
    )

    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url.startswith("postgresql+psycopg://"):
        async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    else:
        async_url = database_url

    engine = create_async_engine(async_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        tasks_done = []

        # Task 1: Clean up old consolidation discards
        cleanup_result = await db.execute(
            text("""
                DELETE FROM consolidation_discards
                WHERE created_at < NOW() - INTERVAL '30 days'
            """)
        )
        if cleanup_result.rowcount:
            tasks_done.append(f"Cleaned {cleanup_result.rowcount} old discards")

        # Task 2: Update karma trends
        # (Could add more sophisticated trend calculation here)

        # Task 3: Prune expired raw buffer stats
        stats_result = await db.execute(
            text("""
                DELETE FROM raw_buffer_stats
                WHERE window_end < NOW() - INTERVAL '7 days'
            """)
        )
        if stats_result.rowcount:
            tasks_done.append(f"Cleaned {stats_result.rowcount} old stats")

        await db.commit()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "tasks_done": tasks_done,
        }

    await engine.dispose()
