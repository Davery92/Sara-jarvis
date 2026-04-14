"""
Daily Brief Scheduler - Background tasks for layer updates
Schedules hourly consolidation, daily context updates, and weekly synthesis.
"""
import asyncio
import logging
from datetime import datetime, time
from typing import Optional

import pytz

logger = logging.getLogger(__name__)

# Eastern timezone for scheduling
EASTERN = pytz.timezone('America/New_York')


class DailyBriefScheduler:
    """
    Schedules background tasks for the daily brief system:
    - Hourly: Day layer consolidation (8 AM - 11 PM)
    - Daily: Context layer update (11 PM)
    - Daily: Day layer archival (midnight)
    - Weekly: Stable layer synthesis (Sunday 3 AM)
    """

    def __init__(self):
        self.running = False
        self._tasks = []
        self._db_session_factory = None

    def set_db_factory(self, factory):
        """Set the database session factory."""
        self._db_session_factory = factory

    async def start(self):
        """Start all scheduled tasks."""
        if self.running:
            logger.warning("DailyBriefScheduler already running")
            return

        self.running = True
        logger.info("📅 Starting DailyBriefScheduler")

        # Start background tasks
        self._tasks = [
            asyncio.create_task(self._hourly_consolidation_loop()),
            asyncio.create_task(self._daily_context_loop()),
            asyncio.create_task(self._nightly_archive_loop()),
            asyncio.create_task(self._weekly_synthesis_loop()),
        ]

    async def stop(self):
        """Stop all scheduled tasks."""
        self.running = False
        logger.info("📅 Stopping DailyBriefScheduler")

        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._tasks = []

    def _get_eastern_now(self) -> datetime:
        """Get current time in Eastern timezone."""
        return datetime.now(EASTERN)

    def _is_active_hours(self) -> bool:
        """Check if we're in active hours (8 AM - 11 PM Eastern)."""
        now = self._get_eastern_now()
        return 8 <= now.hour < 23

    def _is_end_of_day(self) -> bool:
        """Check if it's end of day (11 PM Eastern)."""
        now = self._get_eastern_now()
        return now.hour == 23 and now.minute < 30

    def _is_midnight(self) -> bool:
        """Check if it's around midnight (12 AM - 12:30 AM)."""
        now = self._get_eastern_now()
        return now.hour == 0 and now.minute < 30

    def _is_sunday_3am(self) -> bool:
        """Check if it's Sunday 3 AM Eastern."""
        now = self._get_eastern_now()
        return now.weekday() == 6 and now.hour == 3 and now.minute < 30

    async def _get_all_user_ids(self) -> list:
        """Get all user IDs that have brief directories."""
        from pathlib import Path
        briefs_dir = Path("/home/david/jarvis/data/briefs")

        if not briefs_dir.exists():
            return []

        user_ids = []
        for user_dir in briefs_dir.iterdir():
            if user_dir.is_dir():
                user_ids.append(user_dir.name)

        return user_ids

    async def _hourly_consolidation_loop(self):
        """Run hourly consolidation during active hours."""
        logger.info("📅 Started hourly consolidation loop")

        while self.running:
            try:
                # Check every 30 minutes
                await asyncio.sleep(30 * 60)

                if not self._is_active_hours():
                    continue

                logger.info("📦 Running hourly day layer consolidation check")

                from .day_layer import day_layer

                for user_id in await self._get_all_user_ids():
                    try:
                        if day_layer.needs_consolidation(user_id):
                            await day_layer.consolidate(user_id)
                    except Exception as e:
                        logger.error(f"Consolidation failed for {user_id[:8]}: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in hourly consolidation loop: {e}")
                await asyncio.sleep(60)

    async def _daily_context_loop(self):
        """Run daily context layer update at 11 PM."""
        logger.info("📅 Started daily context loop")

        last_run_date = None

        while self.running:
            try:
                await asyncio.sleep(60)  # Check every minute

                now = self._get_eastern_now()
                today = now.date()

                # Run at 11 PM, but only once per day
                if self._is_end_of_day() and last_run_date != today:
                    logger.info("📋 Running daily context layer update")

                    from .day_layer import day_layer
                    from .context_layer import context_layer

                    for user_id in await self._get_all_user_ids():
                        try:
                            day_content = day_layer.read(user_id)
                            if day_content:
                                await context_layer.daily_update(user_id, day_content)
                        except Exception as e:
                            logger.error(f"Context update failed for {user_id[:8]}: {e}")

                    last_run_date = today

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in daily context loop: {e}")
                await asyncio.sleep(60)

    async def _nightly_archive_loop(self):
        """Archive day layers at midnight."""
        logger.info("📅 Started nightly archive loop")

        last_run_date = None

        while self.running:
            try:
                await asyncio.sleep(60)  # Check every minute

                now = self._get_eastern_now()
                today = now.date()

                # Run at midnight, but only once per day
                if self._is_midnight() and last_run_date != today:
                    logger.info("📦 Running nightly day layer archival")

                    from .day_layer import day_layer
                    from .archiver import archiver

                    for user_id in await self._get_all_user_ids():
                        try:
                            content = day_layer.read(user_id)
                            if content:
                                await archiver.archive_day_layer(user_id, content)
                                # Reset day layer for new day
                                day_layer.clear(user_id)
                        except Exception as e:
                            logger.error(f"Archive failed for {user_id[:8]}: {e}")

                    last_run_date = today

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in nightly archive loop: {e}")
                await asyncio.sleep(60)

    async def _weekly_synthesis_loop(self):
        """Run weekly stable layer synthesis on Sunday 3 AM."""
        logger.info("📅 Started weekly synthesis loop")

        last_run_week = None

        while self.running:
            try:
                await asyncio.sleep(60)  # Check every minute

                now = self._get_eastern_now()
                current_week = now.isocalendar()[1]

                # Run Sunday 3 AM, but only once per week
                if self._is_sunday_3am() and last_run_week != current_week:
                    logger.info("🧠 Running weekly stable layer synthesis")

                    if not self._db_session_factory:
                        logger.warning("No database session factory configured")
                        last_run_week = current_week
                        continue

                    from .stable_layer import stable_layer

                    for user_id in await self._get_all_user_ids():
                        db = None
                        try:
                            db = self._db_session_factory()
                            await stable_layer.weekly_synthesis(user_id, db)
                        except Exception as e:
                            logger.error(f"Weekly synthesis failed for {user_id[:8]}: {e}")
                        finally:
                            if db:
                                db.close()

                    last_run_week = current_week

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in weekly synthesis loop: {e}")
                await asyncio.sleep(60)

    async def run_manual_consolidation(self, user_id: str):
        """Manually trigger consolidation for a user."""
        from .day_layer import day_layer
        return await day_layer.consolidate(user_id)

    async def run_manual_context_update(self, user_id: str):
        """Manually trigger context update for a user."""
        from .day_layer import day_layer
        from .context_layer import context_layer

        day_content = day_layer.read(user_id)
        return await context_layer.daily_update(user_id, day_content)

    async def run_manual_synthesis(self, user_id: str, db):
        """Manually trigger stable layer synthesis for a user."""
        from .stable_layer import stable_layer
        return await stable_layer.weekly_synthesis(user_id, db)


# Singleton instance
daily_brief_scheduler = DailyBriefScheduler()
