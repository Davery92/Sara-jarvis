"""
Report Scheduler Service
Automatically generates periodic intelligence reports
"""
from typing import Optional
from datetime import datetime, date, timedelta, timezone
from sqlalchemy.orm import Session
import logging
import asyncio

from app.db.session import get_db
from app.services.temporal_intelligence import get_temporal_intelligence

logger = logging.getLogger(__name__)


class ReportScheduler:
    """Scheduled report generation service"""

    def __init__(self):
        self.running = False
        self.last_weekly_run: Optional[datetime] = None
        self.last_monthly_run: Optional[datetime] = None
        self.last_quarterly_run: Optional[datetime] = None

    async def run_weekly_job(self):
        """Generate weekly reports for all users (Sundays at 9pm)"""
        if self.running:
            logger.warning("Weekly job already running, skipping")
            return

        self.running = True
        start_time = datetime.now(timezone.utc)

        try:
            logger.info("📅 Starting weekly report generation job")

            db = next(get_db())

            try:
                # Get all users
                from sqlalchemy import text
                result = db.execute(text("SELECT DISTINCT id FROM app_user"))
                users = [row.id for row in result.fetchall()]

                logger.info(f"Generating weekly reports for {len(users)} users")

                # Calculate last Monday
                today = date.today()
                days_since_monday = today.weekday()
                last_monday = today - timedelta(days=days_since_monday + 7)

                # Generate report for each user
                success_count = 0
                fail_count = 0

                for user_id in users:
                    try:
                        engine = get_temporal_intelligence(db)
                        await engine.generate_weekly_report(user_id=user_id, week_start=last_monday)
                        success_count += 1

                        # Small delay to avoid overload
                        await asyncio.sleep(0.5)

                    except Exception as e:
                        logger.error(f"Failed to generate weekly report for user {user_id}: {e}")
                        fail_count += 1

                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                logger.info(f"✅ Weekly job complete: {success_count} success, {fail_count} failed in {duration:.1f}s")

                self.last_weekly_run = datetime.now(timezone.utc)

            finally:
                db.close()

        except Exception as e:
            logger.error(f"❌ Weekly job failed: {e}", exc_info=True)

        finally:
            self.running = False

    async def run_monthly_job(self):
        """Generate monthly reports for all users (1st of month at 8am)"""
        if self.running:
            logger.warning("Monthly job already running, skipping")
            return

        self.running = True
        start_time = datetime.now(timezone.utc)

        try:
            logger.info("📅 Starting monthly report generation job")

            db = next(get_db())

            try:
                # Get all users
                from sqlalchemy import text
                result = db.execute(text("SELECT DISTINCT id FROM app_user"))
                users = [row.id for row in result.fetchall()]

                logger.info(f"Generating monthly reports for {len(users)} users")

                # Calculate first day of last month
                today = date.today()
                first_of_last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)

                # Generate report for each user
                success_count = 0
                fail_count = 0

                for user_id in users:
                    try:
                        engine = get_temporal_intelligence(db)
                        await engine.generate_monthly_report(user_id=user_id, month=first_of_last_month)
                        success_count += 1

                        # Small delay to avoid overload
                        await asyncio.sleep(0.5)

                    except Exception as e:
                        logger.error(f"Failed to generate monthly report for user {user_id}: {e}")
                        fail_count += 1

                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                logger.info(f"✅ Monthly job complete: {success_count} success, {fail_count} failed in {duration:.1f}s")

                self.last_monthly_run = datetime.now(timezone.utc)

            finally:
                db.close()

        except Exception as e:
            logger.error(f"❌ Monthly job failed: {e}", exc_info=True)

        finally:
            self.running = False

    async def run_quarterly_job(self):
        """Generate quarterly reports for all users (Every 3 months on 1st at 8am)"""
        if self.running:
            logger.warning("Quarterly job already running, skipping")
            return

        self.running = True
        start_time = datetime.now(timezone.utc)

        try:
            logger.info("📅 Starting quarterly report generation job")

            db = next(get_db())

            try:
                # Get all users
                from sqlalchemy import text
                result = db.execute(text("SELECT DISTINCT id FROM app_user"))
                users = [row.id for row in result.fetchall()]

                logger.info(f"Generating quarterly reports for {len(users)} users")

                # Calculate first day of last quarter
                today = date.today()
                current_quarter = (today.month - 1) // 3

                if current_quarter == 0:
                    quarter_start = date(today.year - 1, 10, 1)  # Q4 of last year
                else:
                    quarter_month = (current_quarter - 1) * 3 + 1
                    quarter_start = date(today.year, quarter_month, 1)

                # Generate report for each user
                success_count = 0
                fail_count = 0

                for user_id in users:
                    try:
                        engine = get_temporal_intelligence(db)
                        await engine.generate_quarterly_report(user_id=user_id, quarter_start=quarter_start)
                        success_count += 1

                        # Small delay to avoid overload
                        await asyncio.sleep(0.5)

                    except Exception as e:
                        logger.error(f"Failed to generate quarterly report for user {user_id}: {e}")
                        fail_count += 1

                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                logger.info(f"✅ Quarterly job complete: {success_count} success, {fail_count} failed in {duration:.1f}s")

                self.last_quarterly_run = datetime.now(timezone.utc)

            finally:
                db.close()

        except Exception as e:
            logger.error(f"❌ Quarterly job failed: {e}", exc_info=True)

        finally:
            self.running = False

    def get_status(self) -> dict:
        """Get scheduler status"""
        return {
            "running": self.running,
            "last_weekly_run": self.last_weekly_run.isoformat() if self.last_weekly_run else None,
            "last_monthly_run": self.last_monthly_run.isoformat() if self.last_monthly_run else None,
            "last_quarterly_run": self.last_quarterly_run.isoformat() if self.last_quarterly_run else None
        }


# Global scheduler instance
report_scheduler = ReportScheduler()


async def schedule_intelligence_reports():
    """
    Schedule periodic intelligence report generation

    Schedule:
    - Weekly: Sundays at 9pm
    - Monthly: 1st of month at 8am
    - Quarterly: Every 3 months on 1st at 8am
    """
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = AsyncIOScheduler()

        # Weekly reports: Sunday at 9pm
        scheduler.add_job(
            report_scheduler.run_weekly_job,
            trigger=CronTrigger(day_of_week='sun', hour=21, minute=0),
            id='weekly_intelligence_report',
            name='Weekly Intelligence Report',
            replace_existing=True
        )

        # Monthly reports: 1st of month at 8am
        scheduler.add_job(
            report_scheduler.run_monthly_job,
            trigger=CronTrigger(day=1, hour=8, minute=0),
            id='monthly_intelligence_report',
            name='Monthly Intelligence Report',
            replace_existing=True
        )

        # Quarterly reports: 1st of Jan/Apr/Jul/Oct at 8am
        scheduler.add_job(
            report_scheduler.run_quarterly_job,
            trigger=CronTrigger(month='1,4,7,10', day=1, hour=8, minute=0),
            id='quarterly_intelligence_report',
            name='Quarterly Intelligence Report',
            replace_existing=True
        )

        scheduler.start()

        logger.info("📅 Scheduled intelligence report generation:")
        logger.info("  - Weekly: Sundays at 9pm")
        logger.info("  - Monthly: 1st of month at 8am")
        logger.info("  - Quarterly: Jan/Apr/Jul/Oct 1st at 8am")

        return scheduler

    except Exception as e:
        logger.error(f"Failed to schedule intelligence reports: {e}")
        return None


# Manual trigger helpers
async def trigger_weekly_report_now(user_id: Optional[str] = None):
    """Manually trigger weekly report generation"""
    if user_id:
        db = next(get_db())
        try:
            engine = get_temporal_intelligence(db)
            return await engine.generate_weekly_report(user_id=user_id)
        finally:
            db.close()
    else:
        return await report_scheduler.run_weekly_job()


async def trigger_monthly_report_now(user_id: Optional[str] = None):
    """Manually trigger monthly report generation"""
    if user_id:
        db = next(get_db())
        try:
            engine = get_temporal_intelligence(db)
            return await engine.generate_monthly_report(user_id=user_id)
        finally:
            db.close()
    else:
        return await report_scheduler.run_monthly_job()


async def trigger_quarterly_report_now(user_id: Optional[str] = None):
    """Manually trigger quarterly report generation"""
    if user_id:
        db = next(get_db())
        try:
            engine = get_temporal_intelligence(db)
            return await engine.generate_quarterly_report(user_id=user_id)
        finally:
            db.close()
    else:
        return await report_scheduler.run_quarterly_job()
