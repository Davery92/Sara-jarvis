import logging
from datetime import datetime, timedelta, timezone
from typing import List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, text

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.episode import Episode
from app.models.memory import SemanticSummary
from app.models.reminder import Reminder, Timer
from app.models.user import User
from app.services.memory_service import MemoryService
from app.core.llm import llm_client

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service for managing scheduled tasks"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=settings.timezone)
        self._setup_jobs()
    
    def _setup_jobs(self):
        """Set up all scheduled jobs"""
        
        # Daily compaction at 2:10 AM local time
        self.scheduler.add_job(
            func=self.daily_compaction,
            trigger=CronTrigger(
                hour=settings.memory_compaction_daily_hour,
                minute=settings.memory_compaction_daily_minute,
                timezone=settings.timezone
            ),
            id="daily_compaction",
            name="Daily Memory Compaction",
            replace_existing=True
        )
        
        # Weekly compaction on Sunday at 3:00 AM local time
        self.scheduler.add_job(
            func=self.weekly_compaction,
            trigger=CronTrigger(
                day_of_week=settings.memory_compaction_weekly_day,
                hour=settings.memory_compaction_weekly_hour,
                minute=0,
                timezone=settings.timezone
            ),
            id="weekly_compaction",
            name="Weekly Memory Compaction",
            replace_existing=True
        )
        
        # Check reminders and timers every minute
        self.scheduler.add_job(
            func=self.check_reminders_and_timers,
            trigger=IntervalTrigger(minutes=1),
            id="reminder_timer_check",
            name="Reminder and Timer Check",
            replace_existing=True
        )
        
        logger.info("Scheduled jobs configured")
    
    def start(self):
        """Start the scheduler"""
        try:
            self.scheduler.start()
            logger.info("Scheduler started successfully")
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
    
    def shutdown(self):
        """Shutdown the scheduler"""
        try:
            self.scheduler.shutdown(wait=True)
            logger.info("Scheduler shut down successfully")
        except Exception as e:
            logger.error(f"Failed to shutdown scheduler: {e}")
    
    async def daily_compaction(self):
        """Run daily memory compaction for all users"""
        logger.info("Starting daily memory compaction")
        
        db = SessionLocal()
        try:
            # Get all users
            users = db.query(User).all()
            
            for user in users:
                try:
                    await self._compact_daily_for_user(user.id, db)
                except Exception as e:
                    logger.error(f"Daily compaction failed for user {user.id}: {e}")
            
            logger.info(f"Completed daily compaction for {len(users)} users")
            
        except Exception as e:
            logger.error(f"Daily compaction job failed: {e}")
        finally:
            db.close()
    
    async def _compact_daily_for_user(self, user_id: str, db: Session):
        """Create daily summary for a specific user"""
        
        # Get yesterday's date
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=1)
        
        # Find episodes from yesterday
        episodes = db.query(Episode).filter(
            and_(
                Episode.user_id == user_id,
                Episode.created_at >= start_date,
                Episode.created_at < end_date
            )
        ).order_by(Episode.created_at).all()
        
        if not episodes:
            logger.debug(f"No episodes found for user {user_id} on {start_date.date()}")
            return
        
        memory_service = MemoryService(db)
        
        # Check if daily summary already exists
        scope = f"daily:{start_date.strftime('%Y-%m-%d')}"
        existing = db.query(SemanticSummary).filter(
            and_(
                SemanticSummary.user_id == user_id,
                SemanticSummary.scope == scope
            )
        ).first()
        
        if existing:
            logger.debug(f"Daily summary already exists for user {user_id} on {start_date.date()}")
            return
        
        # Create daily summary
        content_parts = []
        episode_ids = []
        
        for episode in episodes:
            content_parts.append(f"[{episode.source}] {episode.role}: {episode.content}")
            episode_ids.append(str(episode.id))
        
        combined_content = "\n\n".join(content_parts)
        
        # Generate summary using LLM
        messages = [
            {
                "role": "system",
                "content": f"Summarize this day's activities for {settings.assistant_name} in 200-400 tokens. Focus on key topics, decisions, tasks completed, information learned, and important interactions. Organize by themes if helpful."
            },
            {
                "role": "user",
                "content": f"Day: {start_date.strftime('%B %d, %Y')}\n\nActivities:\n{combined_content}"
            }
        ]
        
        try:
            result = await llm_client.chat_completion(messages, temperature=0.3)
            summary_text = result["choices"][0]["message"]["content"]
            
            # Get embedding for summary
            from app.services.embeddings import get_embedding
            embedding = await get_embedding(summary_text)
            
            # Create summary record
            summary = SemanticSummary(
                user_id=user_id,
                scope=scope,
                summary=summary_text,
                embedding=embedding,
                coverage={"episode_ids": episode_ids, "date": start_date.strftime('%Y-%m-%d')}
            )
            
            db.add(summary)
            db.commit()
            
            logger.info(f"Created daily summary for user {user_id} on {start_date.date()}")
            
        except Exception as e:
            logger.error(f"Failed to create daily summary for user {user_id}: {e}")
            db.rollback()
    
    async def weekly_compaction(self):
        """Run weekly memory compaction for all users"""
        logger.info("Starting weekly memory compaction")
        
        db = SessionLocal()
        try:
            # Get all users
            users = db.query(User).all()
            
            for user in users:
                try:
                    await self._compact_weekly_for_user(user.id, db)
                except Exception as e:
                    logger.error(f"Weekly compaction failed for user {user.id}: {e}")
            
            logger.info(f"Completed weekly compaction for {len(users)} users")
            
        except Exception as e:
            logger.error(f"Weekly compaction job failed: {e}")
        finally:
            db.close()
    
    async def _compact_weekly_for_user(self, user_id: str, db: Session):
        """Create weekly summary for a specific user"""
        
        # Get last week's date range
        today = datetime.now(timezone.utc).date()
        days_since_sunday = today.weekday() + 1  # Monday = 0, so Sunday = 6, add 1 to make Sunday = 7
        if days_since_sunday == 7:
            days_since_sunday = 0  # If today is Sunday, use 0
        
        last_sunday = today - timedelta(days=days_since_sunday + 7)
        week_start = datetime.combine(last_sunday, datetime.min.time()).replace(tzinfo=timezone.utc)
        week_end = week_start + timedelta(days=7)
        
        # Find daily summaries from last week
        daily_summaries = db.query(SemanticSummary).filter(
            and_(
                SemanticSummary.user_id == user_id,
                SemanticSummary.scope.like('daily:%'),
                SemanticSummary.created_at >= week_start,
                SemanticSummary.created_at < week_end
            )
        ).order_by(SemanticSummary.created_at).all()
        
        if len(daily_summaries) < 2:  # Need at least 2 days to make a weekly summary
            logger.debug(f"Insufficient daily summaries for user {user_id} for week starting {last_sunday}")
            return
        
        # Check if weekly summary already exists
        year, week_num, _ = last_sunday.isocalendar()
        scope = f"weekly:{year}-W{week_num:02d}"
        existing = db.query(SemanticSummary).filter(
            and_(
                SemanticSummary.user_id == user_id,
                SemanticSummary.scope == scope
            )
        ).first()
        
        if existing:
            logger.debug(f"Weekly summary already exists for user {user_id} for {scope}")
            return
        
        # Create weekly summary from daily summaries
        content_parts = []
        episode_ids = []
        
        for summary in daily_summaries:
            day = summary.scope.replace('daily:', '')
            content_parts.append(f"[{day}] {summary.summary}")
            
            # Collect episode IDs if available
            if 'episode_ids' in summary.coverage:
                episode_ids.extend(summary.coverage['episode_ids'])
        
        combined_content = "\n\n".join(content_parts)
        
        # Generate weekly synthesis using LLM
        messages = [
            {
                "role": "system",
                "content": f"Create a weekly synthesis from these daily summaries in 400-800 tokens. Identify patterns, themes, progress on goals, key decisions, and important developments. Structure as a coherent weekly narrative for {settings.assistant_name}."
            },
            {
                "role": "user",
                "content": f"Week of {last_sunday.strftime('%B %d, %Y')}:\n\n{combined_content}"
            }
        ]
        
        try:
            result = await llm_client.chat_completion(messages, temperature=0.3)
            synthesis_text = result["choices"][0]["message"]["content"]
            
            # Get embedding for synthesis
            from app.services.embeddings import get_embedding
            embedding = await get_embedding(synthesis_text)
            
            # Create weekly summary record
            summary = SemanticSummary(
                user_id=user_id,
                scope=scope,
                summary=synthesis_text,
                embedding=embedding,
                coverage={
                    "daily_summary_ids": [str(s.id) for s in daily_summaries],
                    "week_start": week_start.strftime('%Y-%m-%d'),
                    "week_end": (week_end - timedelta(days=1)).strftime('%Y-%m-%d'),
                    "episode_count": len(set(episode_ids))
                }
            )
            
            db.add(summary)
            db.commit()
            
            logger.info(f"Created weekly summary for user {user_id} for {scope}")
            
        except Exception as e:
            logger.error(f"Failed to create weekly summary for user {user_id}: {e}")
            db.rollback()
    
    async def check_reminders_and_timers(self):
        """Check for due reminders and expired timers"""
        
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            
            # Check reminders
            due_reminders = db.query(Reminder).filter(
                and_(
                    Reminder.status == "scheduled",
                    Reminder.due_at <= now
                )
            ).all()
            
            for reminder in due_reminders:
                try:
                    await self._process_due_reminder(reminder, db)
                except Exception as e:
                    logger.error(f"Failed to process reminder {reminder.id}: {e}")
            
            # Check timers
            expired_timers = db.query(Timer).filter(
                and_(
                    Timer.status == "running",
                    Timer.ends_at <= now
                )
            ).all()
            
            for timer in expired_timers:
                try:
                    await self._process_expired_timer(timer, db)
                except Exception as e:
                    logger.error(f"Failed to process timer {timer.id}: {e}")
            
            if due_reminders or expired_timers:
                logger.info(f"Processed {len(due_reminders)} reminders and {len(expired_timers)} timers")
            
        except Exception as e:
            logger.error(f"Reminder/timer check failed: {e}")
        finally:
            db.close()
    
    async def _process_due_reminder(self, reminder: Reminder, db: Session):
        """Process a due reminder"""
        
        # Update reminder status
        reminder.status = "completed"
        
        # Create system episode for the reminder firing
        memory_service = MemoryService(db)
        await memory_service.store_episode(
            user_id=str(reminder.user_id),
            source="system",
            role="system",
            content=f"Reminder: {reminder.text}",
            meta={
                "reminder_id": str(reminder.id),
                "due_at": reminder.due_at.isoformat(),
                "type": "reminder_fired"
            }
        )
        
        db.commit()
        logger.info(f"Processed due reminder: {reminder.text}")
    
    async def _process_expired_timer(self, timer: Timer, db: Session):
        """Process an expired timer"""
        
        # Update timer status
        timer.status = "completed"
        
        # Calculate duration
        duration = timer.ends_at - timer.created_at
        duration_minutes = int(duration.total_seconds() / 60)
        
        # Create system episode for the timer completion
        memory_service = MemoryService(db)
        timer_text = f"Timer completed: {timer.label or 'Unnamed timer'} ({duration_minutes} minutes)"
        
        await memory_service.store_episode(
            user_id=str(timer.user_id),
            source="system",
            role="system",
            content=timer_text,
            meta={
                "timer_id": str(timer.id),
                "duration_minutes": duration_minutes,
                "label": timer.label,
                "type": "timer_completed"
            }
        )
        
        db.commit()
        logger.info(f"Processed expired timer: {timer.label} ({duration_minutes}m)")


# Global scheduler service instance
scheduler_service = SchedulerService()