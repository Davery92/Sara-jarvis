"""
Habit Scheduler Worker - Nightly instance generation
"""

import asyncio
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os

logger = logging.getLogger(__name__)


class HabitSchedulerWorker:
    """Worker that runs nightly to generate habit instances for the next day"""
    
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
    
    async def run_nightly_generation(self) -> Dict[str, Any]:
        """
        Main worker function - generates instances for tomorrow
        
        Should be called every night at 23:30 to prepare for next day
        """
        logger.info("🕚 Starting nightly habit instance generation...")
        
        start_time = datetime.now()
        tomorrow = date.today() + timedelta(days=1)
        results = {
            "date": tomorrow.isoformat(),
            "users_processed": 0,
            "total_instances_created": 0,
            "habits_processed": 0,
            "errors": [],
            "execution_time_seconds": 0
        }
        
        db = self.SessionLocal()
        try:
            # Get all active users
            users = db.execute(text("SELECT id FROM app_user")).fetchall()
            
            for user_row in users:
                user_id = user_row.id
                try:
                    user_results = await self._generate_instances_for_user(db, user_id, tomorrow)
                    results["users_processed"] += 1
                    results["total_instances_created"] += user_results["instances_created"]
                    results["habits_processed"] += user_results["habits_processed"]
                    
                    logger.info(f"✅ User {user_id}: {user_results['instances_created']} instances for {user_results['habits_processed']} habits")
                    
                except Exception as e:
                    error_msg = f"Failed to process user {user_id}: {str(e)}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)
            
            # Calculate execution time
            results["execution_time_seconds"] = (datetime.now() - start_time).total_seconds()
            
            logger.info(f"🎉 Nightly generation complete: {results['total_instances_created']} instances for {results['users_processed']} users")
            
        except Exception as e:
            logger.error(f"❌ Nightly generation failed: {e}")
            results["errors"].append(f"Critical error: {str(e)}")
        finally:
            db.close()
        
        return results
    
    async def _generate_instances_for_user(self, db: Session, user_id: str, target_date: date) -> Dict[str, int]:
        """Generate instances for a specific user"""
        from app.services.habit_instances import HabitInstanceGenerator
        
        # Import here to avoid circular dependencies
        query = text("""
            SELECT id, title, type, rrule, weekly_minimum, pause_from, pause_to, windows, target_numeric, paused
            FROM habits 
            WHERE user_id = :user_id AND paused = 0
        """)
        
        habits = db.execute(query, {"user_id": user_id}).fetchall()
        
        instances_created = 0
        habits_processed = 0
        
        for habit_row in habits:
            try:
                # Create a mock habit object for the generator
                class MockHabit:
                    def __init__(self, row):
                        self.id = row.id
                        self.user_id = user_id
                        self.title = row.title
                        self.type = row.type
                        self.rrule = row.rrule
                        self.weekly_minimum = row.weekly_minimum
                        self.pause_from = row.pause_from
                        self.pause_to = row.pause_to
                        self.windows = row.windows
                        self.target_numeric = row.target_numeric
                
                habit = MockHabit(habit_row)
                
                # Generate instances for tomorrow only
                instance_ids = HabitInstanceGenerator.generate_instances_for_habit(
                    db, habit, target_date, target_date
                )
                
                instances_created += len(instance_ids)
                habits_processed += 1
                
                if instance_ids:
                    logger.debug(f"  ✓ {habit.title}: {len(instance_ids)} instances")
                
            except Exception as e:
                logger.error(f"Failed to generate instances for habit {habit_row.id}: {e}")
        
        return {
            "instances_created": instances_created,
            "habits_processed": habits_processed
        }
    
    async def run_weekly_cleanup(self) -> Dict[str, Any]:
        """
        Weekly cleanup of old instances and logs
        
        Should be called every Sunday at 02:00
        """
        logger.info("🧹 Starting weekly habit data cleanup...")
        
        start_time = datetime.now()
        results = {
            "old_instances_deleted": 0,
            "old_logs_deleted": 0,
            "execution_time_seconds": 0,
            "errors": []
        }
        
        db = self.SessionLocal()
        try:
            # Clean up instances older than 90 days
            from app.services.habit_instances import HabitInstanceGenerator
            deleted_instances = HabitInstanceGenerator.cleanup_old_instances(db, older_than_days=90)
            results["old_instances_deleted"] = deleted_instances
            
            # Clean up logs older than 180 days
            cutoff_date = date.today() - timedelta(days=180)
            deleted_logs = db.execute(text("""
                DELETE FROM habit_logs 
                WHERE created_at < :cutoff_date
            """), {"cutoff_date": cutoff_date}).rowcount
            
            db.commit()
            results["old_logs_deleted"] = deleted_logs
            
            results["execution_time_seconds"] = (datetime.now() - start_time).total_seconds()
            
            logger.info(f"🎉 Cleanup complete: {deleted_instances} instances, {deleted_logs} logs deleted")
            
        except Exception as e:
            error_msg = f"Cleanup failed: {str(e)}"
            logger.error(error_msg)
            results["errors"].append(error_msg)
            db.rollback()
        finally:
            db.close()
        
        return results
    
    async def generate_past_instances(self, user_id: str, days_back: int = 7) -> Dict[str, Any]:
        """
        Generate missing instances for past days (for retro logging)
        
        Useful when users want to log habits retroactively
        """
        logger.info(f"🔄 Generating past instances for user {user_id} ({days_back} days back)")
        
        start_date = date.today() - timedelta(days=days_back)
        end_date = date.today() - timedelta(days=1)  # Don't include today
        
        db = self.SessionLocal()
        try:
            from app.services.habit_instances import HabitInstanceGenerator
            results = HabitInstanceGenerator.generate_instances_for_all_habits(
                db, user_id, start_date, end_date
            )
            
            total_instances = sum(len(instance_ids) for instance_ids in results.values())
            
            logger.info(f"✅ Generated {total_instances} past instances for {len(results)} habits")
            
            return {
                "user_id": user_id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "habits_processed": len(results),
                "total_instances": total_instances,
                "results": results
            }
            
        except Exception as e:
            logger.error(f"❌ Past instance generation failed: {e}")
            raise
        finally:
            db.close()


async def main():
    """Test runner for development"""
    logging.basicConfig(level=logging.INFO)
    
    database_url = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")
    worker = HabitSchedulerWorker(database_url)
    
    print("🧪 Testing Habit Scheduler Worker...")
    
    # Test nightly generation
    results = await worker.run_nightly_generation()
    print(f"✅ Nightly generation: {results}")
    
    # Test weekly cleanup
    cleanup_results = await worker.run_weekly_cleanup()
    print(f"✅ Weekly cleanup: {cleanup_results}")


if __name__ == "__main__":
    asyncio.run(main())