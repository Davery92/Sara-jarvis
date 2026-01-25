"""
Karma system Celery tasks.

Handles:
- Daily karma decay (drift toward neutral)
- Karma alerts and notifications
- Karma statistics aggregation
"""

import logging
import asyncio
from datetime import datetime

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.karma.apply_karma_decay",
    bind=True,
    queue="maintenance",
    max_retries=3
)
def apply_karma_decay(self):
    """
    Apply daily karma decay - drift scores toward neutral.

    Runs once per day to:
    - Decrease scores above min_score_for_decay
    - Increase scores below max_score_for_recovery
    - Log decay events for auditing

    This ensures karma doesn't stay artificially high or low forever.
    """
    logger.info("Starting karma decay task")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _apply_decay_async()
        )
        logger.info(f"Karma decay complete: {result}")
        return result
    except RuntimeError:
        # No event loop running, create one
        result = asyncio.run(_apply_decay_async())
        logger.info(f"Karma decay complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Karma decay failed: {e}")
        raise self.retry(countdown=300, exc=e)


async def _apply_decay_async():
    """Async implementation of karma decay."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    import os

    from app.services.karma.service import get_karma_service

    # Get database URL
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
    )

    # Convert to async URL
    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url.startswith("postgresql+psycopg://"):
        async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    else:
        async_url = database_url

    # Create async engine
    engine = create_async_engine(async_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        karma_service = await get_karma_service(db)
        decay_results = await karma_service.apply_decay()

        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "agents_affected": len(decay_results),
            "total_adjustments": sum(len(events) for events in decay_results.values()),
            "details": decay_results
        }

        return summary

    await engine.dispose()


@celery_app.task(
    name="app.tasks.karma.check_karma_alerts",
    bind=True,
    queue="maintenance"
)
def check_karma_alerts(self):
    """
    Check for karma alerts that need attention.

    Runs periodically to identify agents with critically low karma
    and generate notifications if configured.
    """
    logger.info("Checking karma alerts")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _check_alerts_async()
        )
        return result
    except RuntimeError:
        result = asyncio.run(_check_alerts_async())
        return result
    except Exception as e:
        logger.error(f"Karma alert check failed: {e}")
        raise


async def _check_alerts_async():
    """Async implementation of karma alert checking."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    import os

    from app.services.karma.service import get_karma_service

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
        karma_service = await get_karma_service(db)
        dashboard = await karma_service.get_karma_dashboard()

        alerts = dashboard.get("alerts", [])

        if alerts:
            logger.warning(f"Karma alerts detected: {len(alerts)}")
            for alert in alerts:
                logger.warning(f"  [{alert['level']}] {alert['message']}")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "alerts": alerts,
            "alert_count": len(alerts)
        }

    await engine.dispose()


@celery_app.task(
    name="app.tasks.karma.generate_karma_report",
    bind=True,
    queue="low_priority"
)
def generate_karma_report(self):
    """
    Generate a karma status report.

    Creates a summary of karma state for logging/monitoring.
    """
    logger.info("Generating karma report")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _generate_report_async()
        )
        return result
    except RuntimeError:
        result = asyncio.run(_generate_report_async())
        return result
    except Exception as e:
        logger.error(f"Karma report generation failed: {e}")
        raise


async def _generate_report_async():
    """Async implementation of karma report generation."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    import os

    from app.services.karma.service import get_karma_service

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
        karma_service = await get_karma_service(db)
        dashboard = await karma_service.get_karma_dashboard()

        # Log summary
        logger.info("=== Karma Status Report ===")
        for agent in dashboard.get("agents", []):
            logger.info(
                f"  {agent['display_name']}: {agent['composite_score']:.1f} "
                f"({agent['threshold']})"
            )
        logger.info(f"  Events (24h): {dashboard.get('recent_events_24h', 0)}")
        logger.info("===========================")

        return dashboard

    await engine.dispose()
