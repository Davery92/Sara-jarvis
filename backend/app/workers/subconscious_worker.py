"""
Sara's Subconscious Worker

DEPRECATED: Replaced by unified_agent.py which consolidates both this worker
(sensing/state) and unified_heartbeat.py (LLM agent loop) into a single 4-phase
Celery task running every 15 minutes.

Stop the systemd service: sudo systemctl stop sara-subconscious.service
The Celery beat schedule (unified-agent) handles everything this worker did.

This file is kept for backward compatibility but should no longer be started.

Original description:
Background service that maintains a running mental model of the user's state.
Runs every 30 minutes during waking hours (6 AM - 10 PM), every hour at night.
"""

import asyncio
import logging
import signal
import sys
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# Add the backend directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/home/david/jarvis/logs/subconscious_worker.log')
    ]
)
logger = logging.getLogger(__name__)

# Configuration
DATABASE_URL = os.getenv('DATABASE_URL')

# Timezone (Eastern time for David)
from app.core.timezone import USER_TIMEZONE
USER_TZ = USER_TIMEZONE

# Waking hours
WAKING_HOURS_START = 6   # 6 AM
WAKING_HOURS_END = 22    # 10 PM

# Intervals
WAKING_INTERVAL_MINUTES = 30
SLEEP_INTERVAL_MINUTES = 60


class SubconsciousWorker:
    """
    Background worker for Sara's subconscious processing.

    Maintains a running mental model of the user's state by:
    - Gathering signals from various sources
    - Computing derived state metrics
    - Detecting threshold crossings
    - Generating nudges when something needs attention
    """

    def __init__(self, database_url: str):
        self.running = False
        self.tz = USER_TZ
        self.engine = create_engine(database_url)
        self.SessionLocal = sessionmaker(bind=self.engine)

        # Lazy load service to avoid circular imports
        self._service = None

    @property
    def service(self):
        """Lazy load the SubconsciousService"""
        if self._service is None:
            from app.services.subconscious_service import SubconsciousService
            self._service = SubconsciousService(DATABASE_URL)
        return self._service

    def _is_waking_hours(self, now: datetime) -> bool:
        """Check if current time is during waking hours"""
        return WAKING_HOURS_START <= now.hour < WAKING_HOURS_END

    def _get_interval_seconds(self, now: datetime) -> int:
        """Get sleep interval based on time of day"""
        if self._is_waking_hours(now):
            return WAKING_INTERVAL_MINUTES * 60
        return SLEEP_INTERVAL_MINUTES * 60

    def _get_active_users(self, db) -> list:
        """Get users with recent activity (last 7 days)"""
        result = db.execute(text("""
            SELECT DISTINCT user_id FROM episode
            WHERE created_at >= NOW() - INTERVAL '7 days'
            UNION
            SELECT DISTINCT user_id FROM food_log
            WHERE logged_at >= NOW() - INTERVAL '7 days'
        """))
        return [row.user_id for row in result.fetchall()]

    async def run_cycle(self):
        """Run a single subconscious cycle for all active users"""
        now = datetime.now(self.tz)
        is_waking = self._is_waking_hours(now)

        logger.info(f"Starting subconscious cycle at {now.strftime('%Y-%m-%d %H:%M:%S')} "
                   f"(waking hours: {is_waking})")

        db = self.SessionLocal()
        try:
            # Get all active users
            users = self._get_active_users(db)
            logger.info(f"Processing {len(users)} active users")

            for user_id in users:
                try:
                    await self.service.process_user(db, user_id)
                    db.commit()
                except Exception as e:
                    logger.error(f"Error processing user {user_id}: {e}", exc_info=True)
                    try:
                        db.rollback()
                    except Exception:
                        pass

            logger.info("Subconscious cycle completed successfully")

        except Exception as e:
            logger.error(f"Subconscious cycle error: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()

    async def run(self):
        """Main worker loop"""
        self.running = True
        logger.info("=" * 50)
        logger.info("Sara's Subconscious Worker started")
        logger.info(f"Schedule: {WAKING_INTERVAL_MINUTES} min (waking), {SLEEP_INTERVAL_MINUTES} min (sleep)")
        logger.info(f"Waking hours: {WAKING_HOURS_START}:00 - {WAKING_HOURS_END}:00")
        logger.info("=" * 50)

        while self.running:
            now = datetime.now(self.tz)

            try:
                await self.run_cycle()
            except Exception as e:
                logger.error(f"Worker loop error: {e}", exc_info=True)

            # Calculate next interval
            interval = self._get_interval_seconds(now)
            next_run = now.timestamp() + interval
            next_run_str = datetime.fromtimestamp(next_run, self.tz).strftime('%H:%M:%S')

            logger.info(f"Next cycle in {interval // 60} minutes (at {next_run_str})")
            await asyncio.sleep(interval)

        logger.info("Subconscious worker stopped")

    def stop(self):
        """Stop the worker gracefully"""
        logger.info("Stopping subconscious worker...")
        self.running = False


async def main():
    """Main entry point"""
    # Ensure log directory exists
    os.makedirs('/home/david/jarvis/logs', exist_ok=True)

    worker = SubconsciousWorker(DATABASE_URL)
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()
        worker.stop()

    # Register signal handlers
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    # Start the worker
    worker_task = asyncio.create_task(worker.run())

    try:
        # Wait for shutdown signal
        await shutdown_event.wait()
    finally:
        worker.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    logger.info("Subconscious worker shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
