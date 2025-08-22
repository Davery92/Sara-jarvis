"""
Habit Streak Worker - Daily streak maintenance and notifications
"""

import asyncio
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os

logger = logging.getLogger(__name__)


class HabitStreakWorker:
    """Worker that maintains habit streaks and sends streak-related notifications"""
    
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
    
    async def run_daily_maintenance(self) -> Dict[str, Any]:
        """
        Main streak maintenance function - should run at 23:55 daily
        
        Updates all habit streaks based on today's completions
        """
        logger.info("🔥 Starting daily habit streak maintenance...")
        
        start_time = datetime.now()
        today = date.today()
        results = {
            "date": today.isoformat(),
            "users_processed": 0,
            "habits_updated": 0,
            "streaks_broken": 0,
            "streaks_extended": 0,
            "new_streaks": 0,
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
                    user_results = await self._update_streaks_for_user(db, user_id, today)
                    results["users_processed"] += 1
                    results["habits_updated"] += user_results["habits_updated"]
                    results["streaks_broken"] += user_results["streaks_broken"]
                    results["streaks_extended"] += user_results["streaks_extended"]
                    results["new_streaks"] += user_results["new_streaks"]
                    
                    logger.info(f"✅ User {user_id}: {user_results['habits_updated']} habits updated")
                    
                except Exception as e:
                    error_msg = f"Failed to update streaks for user {user_id}: {str(e)}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)
            
            results["execution_time_seconds"] = (datetime.now() - start_time).total_seconds()
            
            logger.info(f"🎉 Streak maintenance complete: {results['habits_updated']} habits, {results['streaks_extended']} extended, {results['streaks_broken']} broken")
            
        except Exception as e:
            logger.error(f"❌ Streak maintenance failed: {e}")
            results["errors"].append(f"Critical error: {str(e)}")
        finally:
            db.close()
        
        return results
    
    async def _update_streaks_for_user(self, db: Session, user_id: str, target_date: date) -> Dict[str, int]:
        """Update streaks for all habits of a specific user"""
        from app.services.habit_streaks import HabitStreakCalculator
        
        # Get all active habits with current streak data
        query = text("""
            SELECT 
                h.id, h.title, h.grace_days, h.current_streak, h.best_streak, h.last_completed,
                h.vacation_from, h.vacation_to
            FROM habits h
            WHERE h.user_id = :user_id AND h.paused = 0
        """)
        
        habits = db.execute(query, {"user_id": user_id}).fetchall()
        
        habits_updated = 0
        streaks_broken = 0
        streaks_extended = 0
        new_streaks = 0
        
        for habit_row in habits:
            try:
                # Get completion dates for this habit
                completion_dates = await self._get_completion_dates(db, habit_row.id, target_date)
                
                # Get vacation periods
                vacation_periods = []
                if habit_row.vacation_from and habit_row.vacation_to:
                    vacation_periods.append((habit_row.vacation_from, habit_row.vacation_to))
                
                # Calculate new streak values
                current_streak, best_streak, last_completed = HabitStreakCalculator.calculate_streak(
                    completion_dates=completion_dates,
                    grace_days=habit_row.grace_days or 0,
                    vacation_periods=vacation_periods,
                    as_of_date=target_date
                )
                
                # Determine what happened to the streak
                old_current = habit_row.current_streak or 0
                old_best = habit_row.best_streak or 0
                
                if current_streak > old_current:
                    if old_current == 0:
                        new_streaks += 1
                    else:
                        streaks_extended += 1
                elif current_streak == 0 and old_current > 0:
                    streaks_broken += 1
                
                # Update the habit record
                update_query = text("""
                    UPDATE habits 
                    SET 
                        current_streak = :current_streak,
                        best_streak = :best_streak,
                        last_completed = :last_completed,
                        updated_at = :updated_at
                    WHERE id = :habit_id
                """)
                
                db.execute(update_query, {
                    "current_streak": current_streak,
                    "best_streak": max(best_streak, old_best),
                    "last_completed": last_completed,
                    "updated_at": datetime.now(),
                    "habit_id": habit_row.id
                })
                
                habits_updated += 1
                
                logger.debug(f"  ✓ {habit_row.title}: {old_current} → {current_streak} (best: {max(best_streak, old_best)})")
                
            except Exception as e:
                logger.error(f"Failed to update streak for habit {habit_row.id}: {e}")
        
        db.commit()
        
        return {
            "habits_updated": habits_updated,
            "streaks_broken": streaks_broken,
            "streaks_extended": streaks_extended,
            "new_streaks": new_streaks
        }
    
    async def _get_completion_dates(self, db: Session, habit_id: str, up_to_date: date) -> List[date]:
        """Get all completion dates for a habit up to a specific date"""
        query = text("""
            SELECT DISTINCT hi.date
            FROM habit_instances hi
            WHERE hi.habit_id = :habit_id 
                AND hi.date <= :up_to_date
                AND hi.status = 'complete'
            ORDER BY hi.date
        """)
        
        rows = db.execute(query, {"habit_id": habit_id, "up_to_date": up_to_date}).fetchall()
        return [row.date for row in rows]
    
    async def get_streak_alerts(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get habits that need streak-related notifications
        
        Returns habits that are:
        - At risk of breaking (in grace period)
        - Have milestone streaks (7, 30, 100+ days)
        - Just broke a streak
        """
        db = self.SessionLocal()
        alerts = []
        
        try:
            # Get habits with streak status
            query = text("""
                SELECT 
                    h.id, h.title, h.current_streak, h.best_streak, h.grace_days,
                    h.last_completed, h.vacation_from, h.vacation_to
                FROM habits h
                WHERE h.user_id = :user_id AND h.paused = 0
                    AND h.current_streak > 0
            """)
            
            habits = db.execute(query, {"user_id": user_id}).fetchall()
            today = date.today()
            
            for habit in habits:
                from app.services.habit_streaks import HabitStreakCalculator
                
                # Get vacation periods
                vacation_periods = []
                if habit.vacation_from and habit.vacation_to:
                    vacation_periods.append((habit.vacation_from, habit.vacation_to))
                
                # Get streak status
                status = HabitStreakCalculator.get_streak_status(
                    current_streak=habit.current_streak,
                    last_completed=habit.last_completed,
                    grace_days=habit.grace_days or 0,
                    vacation_periods=vacation_periods,
                    as_of_date=today
                )
                
                # Check for alerts
                if status["is_at_risk"]:
                    alerts.append({
                        "type": "streak_at_risk",
                        "habit_id": habit.id,
                        "habit_title": habit.title,
                        "current_streak": habit.current_streak,
                        "days_until_break": status["days_until_break"],
                        "message": f"🚨 Your {habit.current_streak}-day {habit.title} streak is at risk! Complete it today to keep going."
                    })
                
                # Check for milestones
                if habit.current_streak in [7, 14, 21, 30, 50, 75, 100, 200, 365]:
                    alerts.append({
                        "type": "streak_milestone",
                        "habit_id": habit.id,
                        "habit_title": habit.title,
                        "current_streak": habit.current_streak,
                        "message": f"🎉 Amazing! You've reached a {habit.current_streak}-day streak with {habit.title}!"
                    })
                
                # Check if today extends a long streak
                if (habit.last_completed == today and 
                    habit.current_streak > 0 and 
                    habit.current_streak % 7 == 0 and 
                    habit.current_streak >= 14):
                    alerts.append({
                        "type": "streak_momentum",
                        "habit_id": habit.id,
                        "habit_title": habit.title,
                        "current_streak": habit.current_streak,
                        "message": f"🔥 Incredible momentum! {habit.current_streak} days of {habit.title} and counting!"
                    })
            
        except Exception as e:
            logger.error(f"Failed to get streak alerts for user {user_id}: {e}")
        finally:
            db.close()
        
        return alerts
    
    async def get_broken_streak_recovery(self, user_id: str, days_back: int = 3) -> List[Dict[str, Any]]:
        """
        Find recently broken streaks that can be recovered with retro logging
        """
        db = self.SessionLocal()
        recovery_opportunities = []
        
        try:
            # Find habits that had streaks but don't now
            query = text("""
                SELECT 
                    h.id, h.title, h.current_streak, h.best_streak, h.last_completed,
                    h.grace_days
                FROM habits h
                WHERE h.user_id = :user_id AND h.paused = 0
                    AND h.current_streak = 0 AND h.best_streak > 0
                    AND h.last_completed >= :cutoff_date
            """)
            
            cutoff_date = date.today() - timedelta(days=days_back)
            habits = db.execute(query, {"user_id": user_id, "cutoff_date": cutoff_date}).fetchall()
            
            for habit in habits:
                days_since_last = (date.today() - habit.last_completed).days
                if days_since_last <= (habit.grace_days or 0) + 2:  # Still recoverable
                    recovery_opportunities.append({
                        "habit_id": habit.id,
                        "habit_title": habit.title,
                        "last_completed": habit.last_completed.isoformat(),
                        "days_since": days_since_last,
                        "previous_best": habit.best_streak,
                        "message": f"💔 Your {habit.best_streak}-day {habit.title} streak ended. Log recent completions to recover it!"
                    })
        
        except Exception as e:
            logger.error(f"Failed to get recovery opportunities for user {user_id}: {e}")
        finally:
            db.close()
        
        return recovery_opportunities


async def main():
    """Test runner for development"""
    logging.basicConfig(level=logging.INFO)
    
    database_url = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")
    worker = HabitStreakWorker(database_url)
    
    print("🧪 Testing Habit Streak Worker...")
    
    # Test daily maintenance
    results = await worker.run_daily_maintenance()
    print(f"✅ Daily maintenance: {results}")
    
    # Test streak alerts for first user
    db = worker.SessionLocal()
    try:
        first_user = db.execute(text("SELECT id FROM app_user LIMIT 1")).fetchone()
        if first_user:
            alerts = await worker.get_streak_alerts(first_user.id)
            print(f"✅ Streak alerts: {alerts}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())