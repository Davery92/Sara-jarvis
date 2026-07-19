"""
Pattern Discovery Worker

Background worker that runs pattern correlation analysis.

Schedules:
- Hourly: Aggregate temporal bins for the current day
- 2:30 AM: Full pattern discovery (after nightly dream at 2:00 AM)

Usage:
    python -m app.workers.pattern_discovery_worker

Or as systemd service:
    systemctl start sara-pattern-discovery
"""

import asyncio
import logging
import signal
import sys
from datetime import date, datetime, timedelta
from app.core.timezone import naive_local_now
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.pattern_correlation_service import pattern_correlation_service
from app.services.temporal_bin_service import temporal_bin_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/home/david/jarvis/logs/pattern_discovery.log')
    ]
)
logger = logging.getLogger(__name__)

# Database connection
DATABASE_URL = settings.database_url
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# Shutdown flag
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_requested = True


async def run_hourly_aggregation():
    """
    Aggregate temporal bins for the current day.
    Runs every hour to keep bins up to date.
    """
    logger.info("⏰ Running hourly temporal bin aggregation...")

    db = SessionLocal()
    try:
        # Get all active users
        users = db.execute(text("""
            SELECT DISTINCT id FROM app_user
            WHERE id IN (
                SELECT DISTINCT user_id FROM episode
                WHERE created_at > NOW() - INTERVAL '7 days'
            )
        """)).fetchall()

        today = date.today()

        for user in users:
            user_id = user.id
            try:
                await temporal_bin_service.aggregate_daily_bin(db, user_id, today)
                logger.debug(f"✅ Aggregated bin for user {user_id}")
            except Exception as e:
                logger.error(f"❌ Failed to aggregate bin for user {user_id}: {e}")

        logger.info(f"✅ Hourly aggregation complete for {len(users)} users")

    except Exception as e:
        logger.error(f"❌ Hourly aggregation failed: {e}", exc_info=True)
    finally:
        db.close()


async def run_nightly_discovery():
    """
    Run full pattern discovery analysis.
    Runs at 2:30 AM after the nightly dream service.
    """
    logger.info("🌙 Starting nightly pattern discovery...")

    db = SessionLocal()
    try:
        # Get all active users
        users = db.execute(text("""
            SELECT DISTINCT id FROM app_user
            WHERE id IN (
                SELECT DISTINCT user_id FROM episode
                WHERE created_at > NOW() - INTERVAL '30 days'
            )
        """)).fetchall()

        for user in users:
            user_id = user.id
            try:
                logger.info(f"🔍 Running discovery for user {user_id}...")
                result = await pattern_correlation_service.run_discovery(
                    db, user_id, lookback_days=30
                )
                logger.info(f"✅ Discovery complete for user {user_id}: "
                           f"discovered={result.get('patterns_discovered', 0)}, "
                           f"validated={result.get('patterns_validated', 0)}")
            except Exception as e:
                logger.error(f"❌ Discovery failed for user {user_id}: {e}")

        logger.info(f"✅ Nightly discovery complete for {len(users)} users")

    except Exception as e:
        logger.error(f"❌ Nightly discovery failed: {e}", exc_info=True)
    finally:
        db.close()


async def should_run_nightly() -> bool:
    """Check if it's time for nightly discovery (2:30 AM)."""
    now = naive_local_now()
    return now.hour == 2 and 25 <= now.minute <= 35


async def main_loop():
    """Main worker loop."""
    global shutdown_requested

    logger.info("🚀 Pattern Discovery Worker starting...")

    # Track last run times
    last_hourly_run = None
    last_nightly_run = None

    while not shutdown_requested:
        try:
            now = naive_local_now()
            current_hour = now.replace(minute=0, second=0, microsecond=0)
            current_date = now.date()

            # Hourly aggregation
            if last_hourly_run != current_hour:
                await run_hourly_aggregation()
                last_hourly_run = current_hour

            # Nightly discovery (2:30 AM)
            if await should_run_nightly() and last_nightly_run != current_date:
                await run_nightly_discovery()
                last_nightly_run = current_date

            # Sleep for 1 minute before checking again
            await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
            await asyncio.sleep(60)

    logger.info("👋 Pattern Discovery Worker shutting down...")


def main():
    """Entry point for the worker."""
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run the main loop
    asyncio.run(main_loop())


if __name__ == "__main__":
    main()
