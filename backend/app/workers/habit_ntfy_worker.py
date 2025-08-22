"""
Habit NTFY Worker - Ambient notifications for habit tracking
"""

import asyncio
import aiohttp
import logging
from datetime import datetime, date, time, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os
import json

logger = logging.getLogger(__name__)


class HabitNTFYWorker:
    """Worker that sends habit-related NTFY notifications"""
    
    def __init__(self, database_url: str, ntfy_base_url: str = "https://ntfy.sh"):
        self.engine = create_engine(database_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.ntfy_base_url = ntfy_base_url
    
    async def send_notification(self, topic: str, title: str, message: str, 
                               priority: str = "default", tags: str = None, actions: List[Dict] = None) -> bool:
        """Send a notification via NTFY"""
        try:
            headers = {
                "Title": title,
                "Priority": priority,
            }
            
            if tags:
                headers["Tags"] = tags
            
            payload = message
            if actions:
                # NTFY actions format
                headers["Actions"] = json.dumps(actions)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ntfy_base_url}/{topic}",
                    data=payload,
                    headers=headers
                ) as response:
                    if response.status == 200:
                        logger.info(f"✅ NTFY sent to {topic}: {title}")
                        return True
                    else:
                        logger.error(f"❌ NTFY failed ({response.status}): {await response.text()}")
                        return False
        
        except Exception as e:
            logger.error(f"❌ NTFY error: {e}")
            return False
    
    async def run_morning_nudges(self, target_time: time = time(9, 0)) -> Dict[str, Any]:
        """
        Send morning habit nudges at specified time
        
        Default: 9:00 AM - gentle reminder about today's habits
        """
        logger.info(f"🌅 Sending morning habit nudges at {target_time}")
        
        start_time = datetime.now()
        today = date.today()
        results = {
            "time": target_time.isoformat(),
            "date": today.isoformat(),
            "users_processed": 0,
            "notifications_sent": 0,
            "errors": [],
            "execution_time_seconds": 0
        }
        
        db = self.SessionLocal()
        try:
            # Get users who want morning nudges
            # For now, skip NTFY notifications since user table doesn't have ntfy_topic field
            users = []  # db.execute(text("SELECT id, email FROM app_user")).fetchall()
            
            for user in users:
                try:
                    if await self._send_morning_nudge(db, user, today):
                        results["notifications_sent"] += 1
                    results["users_processed"] += 1
                    
                except Exception as e:
                    error_msg = f"Failed morning nudge for user {user.id}: {str(e)}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)
            
            results["execution_time_seconds"] = (datetime.now() - start_time).total_seconds()
            
            logger.info(f"🎉 Morning nudges complete: {results['notifications_sent']} sent to {results['users_processed']} users")
            
        except Exception as e:
            logger.error(f"❌ Morning nudges failed: {e}")
            results["errors"].append(f"Critical error: {str(e)}")
        finally:
            db.close()
        
        return results
    
    async def _send_morning_nudge(self, db: Session, user, target_date: date) -> bool:
        """Send morning nudge for a specific user"""
        # Get today's habits for user
        query = text("""
            SELECT 
                hi.instance_id, hi.habit_id, hi.status, hi.progress,
                h.title, h.type, h.target_numeric, h.unit
            FROM (
                SELECT 
                    hi.id as instance_id,
                    hi.habit_id,
                    hi.status,
                    hi.progress,
                    h.title,
                    h.type,
                    h.target_numeric,
                    h.unit
                FROM habit_instances hi
                JOIN habits h ON hi.habit_id = h.id
                WHERE hi.user_id = :user_id 
                    AND hi.date = :target_date
                    AND hi.expected = 1
                    AND h.paused = 0
            ) hi
            ORDER BY hi.title
        """)
        
        habits = db.execute(query, {"user_id": user.id, "target_date": target_date}).fetchall()
        
        if not habits:
            return False
        
        # Count pending habits
        pending_habits = [h for h in habits if h.status == "pending"]
        in_progress_habits = [h for h in habits if h.status == "in_progress"]
        
        if not pending_habits and not in_progress_habits:
            # All done, send celebration
            title = "🎉 All habits complete!"
            message = f"Amazing! You've completed all {len(habits)} habits for today. Keep up the momentum!"
            tags = "white_check_mark,muscle"
        else:
            # Send morning motivation
            total = len(habits)
            remaining = len(pending_habits) + len(in_progress_habits)
            
            title = f"🌅 Good morning! {remaining} habits waiting"
            
            habit_list = []
            for habit in pending_habits[:3]:  # Show up to 3 habits
                if habit.type == "quantitative":
                    habit_list.append(f"• {habit.title} ({habit.target_numeric} {habit.unit})")
                else:
                    habit_list.append(f"• {habit.title}")
            
            if len(pending_habits) > 3:
                habit_list.append(f"• ... and {len(pending_habits) - 3} more")
            
            message = f"Ready to tackle today's habits?\n\n" + "\n".join(habit_list)
            
            if in_progress_habits:
                message += f"\n\n💪 {len(in_progress_habits)} already in progress!"
            
            tags = "sunrise,target"
        
        # Add action buttons
        actions = [
            {
                "action": "view",
                "label": "Open Sara",
                "url": "https://sara.avery.cloud"
            }
        ]
        
        return await self.send_notification(
            topic=user.ntfy_topic,
            title=title,
            message=message,
            priority="default",
            tags=tags,
            actions=actions
        )
    
    async def run_evening_review(self, target_time: time = time(21, 0)) -> Dict[str, Any]:
        """
        Send evening habit review at specified time
        
        Default: 9:00 PM - review progress and plan for tomorrow
        """
        logger.info(f"🌆 Sending evening habit reviews at {target_time}")
        
        start_time = datetime.now()
        today = date.today()
        results = {
            "time": target_time.isoformat(),
            "date": today.isoformat(),
            "users_processed": 0,
            "notifications_sent": 0,
            "errors": [],
            "execution_time_seconds": 0
        }
        
        db = self.SessionLocal()
        try:
            # Get users who want evening reviews
            # For now, skip NTFY notifications since user table doesn't have ntfy_topic field
            users = []  # db.execute(text("SELECT id, email FROM app_user")).fetchall()
            
            for user in users:
                try:
                    if await self._send_evening_review(db, user, today):
                        results["notifications_sent"] += 1
                    results["users_processed"] += 1
                    
                except Exception as e:
                    error_msg = f"Failed evening review for user {user.id}: {str(e)}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)
            
            results["execution_time_seconds"] = (datetime.now() - start_time).total_seconds()
            
            logger.info(f"🎉 Evening reviews complete: {results['notifications_sent']} sent to {results['users_processed']} users")
            
        except Exception as e:
            logger.error(f"❌ Evening reviews failed: {e}")
            results["errors"].append(f"Critical error: {str(e)}")
        finally:
            db.close()
        
        return results
    
    async def _send_evening_review(self, db: Session, user, target_date: date) -> bool:
        """Send evening review for a specific user"""
        # Get today's progress
        query = text("""
            SELECT 
                COUNT(*) as total_habits,
                COUNT(CASE WHEN hi.status = 'complete' THEN 1 END) as completed,
                COUNT(CASE WHEN hi.status = 'in_progress' THEN 1 END) as in_progress,
                AVG(hi.progress) as avg_progress
            FROM habit_instances hi
            JOIN habits h ON hi.habit_id = h.id
            WHERE hi.user_id = :user_id 
                AND hi.date = :target_date
                AND hi.expected = 1
                AND h.paused = 0
        """)
        
        stats = db.execute(query, {"user_id": user.id, "target_date": target_date}).fetchone()
        
        if not stats or stats.total_habits == 0:
            return False
        
        total = stats.total_habits
        completed = stats.completed
        in_progress = stats.in_progress
        avg_progress = stats.avg_progress or 0
        
        # Calculate completion rate
        completion_rate = (completed / total) * 100 if total > 0 else 0
        
        # Choose message based on performance
        if completion_rate == 100:
            title = "🏆 Perfect day!"
            message = f"Outstanding! You completed all {total} habits today. You're building incredible momentum!"
            tags = "trophy,fire"
            priority = "high"
        elif completion_rate >= 80:
            title = "🌟 Excellent progress!"
            message = f"Great work! You completed {completed}/{total} habits today ({completion_rate:.0f}%). Almost perfect!"
            tags = "star,muscle"
            priority = "default"
        elif completion_rate >= 60:
            title = "👍 Good progress!"
            remaining = total - completed
            message = f"Nice work! You completed {completed}/{total} habits today. {remaining} remaining for tomorrow."
            tags = "thumbsup,calendar"
            priority = "default"
        else:
            title = "💪 Tomorrow's opportunity"
            remaining = total - completed
            message = f"Today: {completed}/{total} completed. No worries! Tomorrow is a fresh start to get back on track."
            tags = "sunrise,heart"
            priority = "low"
        
        # Add streak information
        streak_query = text("""
            SELECT h.title, h.current_streak
            FROM habits h
            WHERE h.user_id = :user_id 
                AND h.current_streak > 0
                AND h.paused = 0
            ORDER BY h.current_streak DESC
            LIMIT 3
        """)
        
        streaks = db.execute(streak_query, {"user_id": user.id}).fetchall()
        
        if streaks:
            message += "\n\n🔥 Active streaks:"
            for streak in streaks:
                message += f"\n• {streak.title}: {streak.current_streak} days"
        
        # Add action buttons
        actions = [
            {
                "action": "view",
                "label": "Review Progress",
                "url": "https://sara.avery.cloud/#habits"
            }
        ]
        
        return await self.send_notification(
            topic=user.ntfy_topic,
            title=title,
            message=message,
            priority=priority,
            tags=tags,
            actions=actions
        )
    
    async def send_streak_alerts(self, user_id: str) -> Dict[str, Any]:
        """Send notifications for streak-related events"""
        from app.workers.habit_streak_worker import HabitStreakWorker
        
        streak_worker = HabitStreakWorker(str(self.engine.url))
        alerts = await streak_worker.get_streak_alerts(user_id)
        
        results = {
            "user_id": user_id,
            "alerts_found": len(alerts),
            "notifications_sent": 0,
            "errors": []
        }
        
        db = self.SessionLocal()
        try:
            # Get user's NTFY topic
            # For now, skip NTFY notifications since user table doesn't have ntfy_topic field
            user = None  # db.execute(text("SELECT id FROM app_user WHERE id = :user_id"), {"user_id": user_id}).fetchone()
            
            if not user:
                return results
            
            for alert in alerts:
                try:
                    # Choose priority and tags based on alert type
                    if alert["type"] == "streak_at_risk":
                        priority = "high"
                        tags = "warning,fire"
                    elif alert["type"] == "streak_milestone":
                        priority = "high"
                        tags = "party,fire"
                    elif alert["type"] == "streak_momentum":
                        priority = "default"
                        tags = "muscle,fire"
                    else:
                        priority = "default"
                        tags = "information_source"
                    
                    success = await self.send_notification(
                        topic=user.ntfy_topic,
                        title=f"Habit Streak: {alert['habit_title']}",
                        message=alert["message"],
                        priority=priority,
                        tags=tags,
                        actions=[{
                            "action": "view",
                            "label": "Open Sara",
                            "url": "https://sara.avery.cloud/#habits"
                        }]
                    )
                    
                    if success:
                        results["notifications_sent"] += 1
                
                except Exception as e:
                    error_msg = f"Failed to send alert {alert['type']}: {str(e)}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)
        
        finally:
            db.close()
        
        return results


async def main():
    """Test runner for development"""
    logging.basicConfig(level=logging.INFO)
    
    database_url = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")
    worker = HabitNTFYWorker(database_url)
    
    print("🧪 Testing Habit NTFY Worker...")
    
    # Test sending a simple notification
    success = await worker.send_notification(
        topic="test-habits",
        title="🧪 Test Notification",
        message="This is a test from the Habit NTFY Worker",
        tags="test,gear"
    )
    print(f"✅ Test notification: {'sent' if success else 'failed'}")
    
    # Test morning nudges
    results = await worker.run_morning_nudges()
    print(f"✅ Morning nudges: {results}")


if __name__ == "__main__":
    asyncio.run(main())