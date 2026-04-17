"""
Nightly Importance Rescoring Job
Runs at 3am daily to rescore all episodes
"""
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.importance_scorer import get_importance_scorer
from datetime import datetime, timezone
import logging
import asyncio

logger = logging.getLogger(__name__)


class NightlyRescoringJob:
    """Background job for importance rescoring"""

    def __init__(self):
        self.running = False
        self.last_run: Optional[datetime] = None
        self.last_stats: Optional[Dict[str, Any]] = None

    async def run(self, user_id: Optional[str] = None):
        """
        Run the nightly rescoring job

        Args:
            user_id: Optional user ID (None = all users)

        Returns:
            Job statistics
        """
        if self.running:
            logger.warning("Rescoring job already running, skipping")
            return {"status": "skipped", "reason": "already_running"}

        self.running = True
        start_time = datetime.now(timezone.utc)

        try:
            logger.info("🌙 Starting nightly importance rescoring job")

            # Get database session
            db = next(get_db())

            try:
                # Create scorer
                scorer = get_importance_scorer(db)

                # Run rescoring
                stats = await scorer.rescore_all_episodes(
                    user_id=user_id,
                    batch_size=100,
                    max_batches=None  # Process all
                )

                # Add timing info
                end_time = datetime.now(timezone.utc)
                duration = (end_time - start_time).total_seconds()

                stats["start_time"] = start_time.isoformat()
                stats["end_time"] = end_time.isoformat()
                stats["duration_seconds"] = duration

                # Store results
                self.last_run = end_time
                self.last_stats = stats

                logger.info(f"✅ Nightly rescoring complete: {stats['rescored']} episodes in {duration:.1f}s")

                return {
                    "status": "success",
                    **stats
                }

            finally:
                db.close()

        except Exception as e:
            logger.error(f"❌ Nightly rescoring job failed: {e}", exc_info=True)
            return {
                "status": "failed",
                "error": str(e)
            }

        finally:
            self.running = False

    def get_status(self) -> Dict[str, Any]:
        """Get job status"""
        return {
            "running": self.running,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_stats": self.last_stats
        }


# Global job instance
nightly_rescoring_job = NightlyRescoringJob()


# Scheduler integration (using APScheduler or similar)
async def schedule_nightly_rescoring():
    """Schedule the nightly rescoring job"""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler()

    # Schedule for 3am daily
    scheduler.add_job(
        nightly_rescoring_job.run,
        trigger=CronTrigger(hour=3, minute=0),
        id='nightly_importance_rescoring',
        name='Nightly Importance Rescoring',
        replace_existing=True
    )

    scheduler.start()
    logger.info("📅 Scheduled nightly importance rescoring job (3am daily)")

    return scheduler


# Manual trigger endpoint helper
async def trigger_rescoring_now(user_id: Optional[str] = None) -> Dict[str, Any]:
    """Manually trigger rescoring job (for testing or manual runs)"""
    return await nightly_rescoring_job.run(user_id)
