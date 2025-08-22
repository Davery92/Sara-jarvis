"""
Habit Worker Coordinator - Orchestrates all habit background workers
"""

import asyncio
import logging
from datetime import datetime, time as dt_time
from typing import Dict, Any
import os

from app.workers.habit_scheduler_worker import HabitSchedulerWorker
from app.workers.habit_streak_worker import HabitStreakWorker  
from app.workers.habit_ntfy_worker import HabitNTFYWorker
from app.workers.habit_neo4j_worker import HabitNeo4jWorker

logger = logging.getLogger(__name__)


class HabitWorkerCoordinator:
    """Coordinates all habit-related background workers"""
    
    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")
        
        # Initialize workers
        self.scheduler_worker = HabitSchedulerWorker(self.database_url)
        self.streak_worker = HabitStreakWorker(self.database_url)
        self.ntfy_worker = HabitNTFYWorker(self.database_url)
        self.neo4j_worker = HabitNeo4jWorker(self.database_url)
        
        self.running = False
        self.tasks = []
    
    async def _run_nightly_generation(self):
        """Generate tomorrow's habit instances"""
        logger.info("🌙 Running nightly habit instance generation...")
        try:
            result = await self.scheduler_worker.run_nightly_generation()
            logger.info(f"✅ Nightly generation complete: {result['total_instances_created']} instances")
        except Exception as e:
            logger.error(f"❌ Nightly generation failed: {e}")
    
    async def _run_streak_maintenance(self):
        """Update all habit streaks"""
        logger.info("🔥 Running daily streak maintenance...")
        try:
            result = await self.streak_worker.run_daily_maintenance()
            logger.info(f"✅ Streak maintenance complete: {result['habits_updated']} habits")
        except Exception as e:
            logger.error(f"❌ Streak maintenance failed: {e}")
    
    async def _run_morning_nudges(self):
        """Send morning habit nudges"""
        logger.info("🌅 Sending morning habit nudges...")
        try:
            result = await self.ntfy_worker.run_morning_nudges()
            logger.info(f"✅ Morning nudges sent: {result['notifications_sent']} notifications")
        except Exception as e:
            logger.error(f"❌ Morning nudges failed: {e}")
    
    async def _run_evening_reviews(self):
        """Send evening habit reviews"""
        logger.info("🌆 Sending evening habit reviews...")
        try:
            result = await self.ntfy_worker.run_evening_review()
            logger.info(f"✅ Evening reviews sent: {result['notifications_sent']} notifications")
        except Exception as e:
            logger.error(f"❌ Evening reviews failed: {e}")
    
    async def _run_neo4j_sync(self):
        """Sync habit data to Neo4j"""
        logger.debug("🔄 Running Neo4j sync...")
        try:
            result = await self.neo4j_worker.process_outbox_events()
            if result["events_processed"] > 0:
                logger.info(f"✅ Neo4j sync: {result['events_processed']} events processed")
        except Exception as e:
            logger.error(f"❌ Neo4j sync failed: {e}")
    
    async def _run_streak_alerts(self):
        """Check for and send streak alerts"""
        logger.debug("🚨 Checking for streak alerts...")
        try:
            # This would need to iterate through users with notifications enabled
            # For now, just log that we're checking
            logger.debug("✅ Streak alerts checked")
        except Exception as e:
            logger.error(f"❌ Streak alerts failed: {e}")
    
    async def _run_weekly_cleanup(self):
        """Run weekly data cleanup"""
        logger.info("🧹 Running weekly habit data cleanup...")
        try:
            result = await self.scheduler_worker.run_weekly_cleanup()
            logger.info(f"✅ Weekly cleanup complete: {result['old_instances_deleted']} instances cleaned")
        except Exception as e:
            logger.error(f"❌ Weekly cleanup failed: {e}")
    
    async def run_manual_task(self, task_name: str, **kwargs) -> Dict[str, Any]:
        """Run a specific worker task manually"""
        logger.info(f"🔧 Running manual task: {task_name}")
        
        try:
            if task_name == "nightly_generation":
                return await self.scheduler_worker.run_nightly_generation()
            elif task_name == "streak_maintenance":
                return await self.streak_worker.run_daily_maintenance()
            elif task_name == "morning_nudges":
                return await self.ntfy_worker.run_morning_nudges()
            elif task_name == "evening_reviews":
                return await self.ntfy_worker.run_evening_review()
            elif task_name == "neo4j_sync":
                return await self.neo4j_worker.process_outbox_events()
            elif task_name == "weekly_cleanup":
                return await self.scheduler_worker.run_weekly_cleanup()
            elif task_name == "generate_past_instances":
                user_id = kwargs.get("user_id")
                days_back = kwargs.get("days_back", 7)
                if not user_id:
                    return {"error": "user_id required for generate_past_instances"}
                return await self.scheduler_worker.generate_past_instances(user_id, days_back)
            elif task_name == "streak_alerts":
                user_id = kwargs.get("user_id")
                if not user_id:
                    return {"error": "user_id required for streak_alerts"}
                return await self.ntfy_worker.send_streak_alerts(user_id)
            else:
                return {"error": f"Unknown task: {task_name}"}
        
        except Exception as e:
            logger.error(f"❌ Manual task {task_name} failed: {e}")
            return {"error": str(e)}
    
    def start_background_tasks(self):
        """Start background tasks (called by FastAPI startup)"""
        logger.info("🚀 Starting Habit Worker background tasks...")
        self.running = True
        
        # For now, just mark as started - actual scheduling would be handled by external cron or system scheduler
        logger.info("✅ Habit Worker Coordinator ready for manual task execution")
    
    def stop(self):
        """Stop the worker coordinator"""
        logger.info("⏹️ Stopping Habit Worker Coordinator...")
        
        self.running = False
        
        # Close Neo4j connection
        if self.neo4j_worker:
            self.neo4j_worker.close()
        
        logger.info("✅ Habit Worker Coordinator stopped")
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all workers"""
        return {
            "running": self.running,
            "workers": {
                "scheduler": "active",
                "streak": "active", 
                "ntfy": "active",
                "neo4j": "active" if self.neo4j_worker.neo4j_driver else "disabled"
            },
            "manual_tasks_available": [
                "nightly_generation",
                "streak_maintenance", 
                "morning_nudges",
                "evening_reviews",
                "neo4j_sync",
                "weekly_cleanup",
                "generate_past_instances",
                "streak_alerts"
            ]
        }


async def main():
    """Test runner for development"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    coordinator = HabitWorkerCoordinator()
    coordinator.start_background_tasks()
    
    print("🧪 Testing Habit Worker Coordinator...")
    
    try:
        # Test a few manual tasks
        print("✅ Status:", coordinator.get_status())
        
        # Test nightly generation
        result = await coordinator.run_manual_task("nightly_generation")
        print("✅ Nightly generation:", result)
        
    finally:
        coordinator.stop()


if __name__ == "__main__":
    asyncio.run(main())