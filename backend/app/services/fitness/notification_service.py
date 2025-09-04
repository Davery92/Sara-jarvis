"""
Fitness Notification Service

Handles fitness-related notifications including readiness reminders,
adjustment alerts, and workout notifications. Integrates with NTFY
for cross-platform notifications.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, date, timedelta, time
import logging
import httpx
import os
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.models.fitness import MorningReadiness, Workout, ReadinessAdjustment
from app.models.user import User

logger = logging.getLogger(__name__)


class FitnessNotificationService:
    """Handles fitness-related notifications and triggers"""
    
    def __init__(self):
        self.ntfy_base_url = "https://ntfy.sh"
        self.fitness_topic = os.getenv("NTFY_FITNESS_TOPIC", "sara_fitness")
        
        # Notification schedules
        self.readiness_reminder_time = time(hour=8, minute=0)  # 8:00 AM
        self.workout_reminder_time = time(hour=17, minute=0)   # 5:00 PM
        
        # Notification types and priorities
        self.notification_types = {
            'readiness_reminder': {
                'priority': 'default',
                'title': 'Daily Readiness Check',
                'icon': '💪'
            },
            'adjustment_alert': {
                'priority': 'high',
                'title': 'Workout Adjustment',
                'icon': '⚡'
            },
            'workout_reminder': {
                'priority': 'default',
                'title': 'Workout Reminder',
                'icon': '🏋️'
            },
            'baseline_milestone': {
                'priority': 'low',
                'title': 'Baseline Update',
                'icon': '📊'
            }
        }
    
    async def send_notification(
        self,
        user_id: str,
        notification_type: str,
        message: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send a fitness notification via NTFY"""
        
        try:
            if notification_type not in self.notification_types:
                logger.warning(f"Unknown notification type: {notification_type}")
                return {"success": False, "error": "Unknown notification type"}
            
            config = self.notification_types[notification_type]
            
            # Prepare notification payload
            payload = {
                "topic": f"{self.fitness_topic}_{user_id}",
                "title": f"{config['icon']} {config['title']}",
                "message": message,
                "priority": config['priority'],
                "tags": ["fitness", notification_type]
            }
            
            # Add action buttons for certain notification types
            if notification_type == 'readiness_reminder':
                payload["actions"] = [
                    {
                        "action": "view",
                        "label": "Submit Readiness",
                        "url": f"{os.getenv('FRONTEND_URL', 'https://sara.avery.cloud')}/fitness/readiness"
                    }
                ]
            elif notification_type == 'adjustment_alert':
                payload["actions"] = [
                    {
                        "action": "view", 
                        "label": "Review Adjustments",
                        "url": f"{os.getenv('FRONTEND_URL', 'https://sara.avery.cloud')}/fitness/adjustments"
                    }
                ]
            
            # Add custom data if provided
            if data:
                payload["extras"] = data
            
            # Send via NTFY
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.ntfy_base_url}",
                    json=payload
                )
                
                if response.status_code == 200:
                    logger.info(f"Sent {notification_type} notification to user {user_id}")
                    return {
                        "success": True,
                        "notification_id": response.headers.get("x-message-id"),
                        "type": notification_type
                    }
                else:
                    logger.error(f"NTFY notification failed: {response.status_code} {response.text}")
                    return {
                        "success": False,
                        "error": f"NTFY error: {response.status_code}"
                    }
            
        except Exception as e:
            logger.error(f"Failed to send notification to user {user_id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def check_readiness_reminders(self, db: Session) -> List[Dict[str, Any]]:
        """Check for users who need readiness reminders"""
        
        notifications_sent = []
        today = datetime.utcnow().date()
        current_time = datetime.utcnow().time()
        
        # Only send reminders during morning hours (8-11 AM)
        if not (time(8, 0) <= current_time <= time(11, 0)):
            return notifications_sent
        
        try:
            # Get all users who haven't submitted readiness today
            users_without_readiness = db.query(User).filter(
                ~User.id.in_(
                    db.query(MorningReadiness.user_id).filter(
                        func.date(MorningReadiness.created_at) == today
                    )
                )
            ).all()
            
            for user in users_without_readiness:
                # Check if user has workouts scheduled
                has_workout = db.query(Workout).filter(
                    and_(
                        Workout.user_id == str(user.id),
                        Workout.status == "scheduled"
                    )
                ).first() is not None
                
                if has_workout:
                    message = "Time for your daily readiness check! Let's optimize today's workout based on how you're feeling."
                    
                    result = await self.send_notification(
                        user_id=str(user.id),
                        notification_type="readiness_reminder",
                        message=message,
                        data={"date": today.isoformat()}
                    )
                    
                    if result["success"]:
                        notifications_sent.append({
                            "user_id": str(user.id),
                            "type": "readiness_reminder",
                            "sent_at": datetime.utcnow().isoformat()
                        })
            
        except Exception as e:
            logger.error(f"Failed to check readiness reminders: {e}")
        
        return notifications_sent
    
    async def check_adjustment_alerts(self, db: Session) -> List[Dict[str, Any]]:
        """Check for new workout adjustments that need user attention"""
        
        notifications_sent = []
        cutoff_time = datetime.utcnow() - timedelta(minutes=15)  # Only recent adjustments
        
        try:
            # Get recent adjustments that haven't been acted upon
            pending_adjustments = db.query(ReadinessAdjustment).filter(
                and_(
                    ReadinessAdjustment.status == "proposed",
                    ReadinessAdjustment.created_at >= cutoff_time,
                    ReadinessAdjustment.strategy.in_(["reduce", "swap", "move"])  # Only significant adjustments
                )
            ).all()
            
            for adjustment in pending_adjustments:
                # Get associated workout
                workout = db.query(Workout).filter(
                    Workout.id == adjustment.workout_id
                ).first()
                
                if not workout:
                    continue
                
                # Customize message based on strategy
                strategy_messages = {
                    "reduce": f"Your readiness score ({adjustment.readiness_score}) suggests reducing intensity for today's {workout.title}. Would you like to apply the recommended adjustments?",
                    "swap": f"Low readiness score ({adjustment.readiness_score}) detected. Consider swapping {workout.title} for active recovery or easier exercises.",
                    "move": f"Very low readiness ({adjustment.readiness_score}). Moving today's {workout.title} to tomorrow might be best for your recovery."
                }
                
                message = strategy_messages.get(
                    adjustment.strategy,
                    f"Workout adjustments available based on your readiness score of {adjustment.readiness_score}."
                )
                
                result = await self.send_notification(
                    user_id=adjustment.user_id,
                    notification_type="adjustment_alert",
                    message=message,
                    data={
                        "adjustment_id": str(adjustment.id),
                        "workout_id": str(workout.id),
                        "strategy": adjustment.strategy,
                        "readiness_score": adjustment.readiness_score
                    }
                )
                
                if result["success"]:
                    notifications_sent.append({
                        "user_id": adjustment.user_id,
                        "type": "adjustment_alert",
                        "adjustment_id": str(adjustment.id),
                        "sent_at": datetime.utcnow().isoformat()
                    })
            
        except Exception as e:
            logger.error(f"Failed to check adjustment alerts: {e}")
        
        return notifications_sent
    
    async def check_workout_reminders(self, db: Session) -> List[Dict[str, Any]]:
        """Send reminders for upcoming workouts"""
        
        notifications_sent = []
        current_time = datetime.utcnow()
        
        # Only send reminders in the evening (5-7 PM) for next day workouts
        if not (time(17, 0) <= current_time.time() <= time(19, 0)):
            return notifications_sent
        
        tomorrow = (current_time + timedelta(days=1)).date()
        
        try:
            # Get scheduled workouts for tomorrow
            tomorrow_workouts = db.query(Workout).filter(
                and_(
                    Workout.status == "scheduled",
                    # In production, would filter by actual workout date
                    Workout.created_at >= current_time.date()
                )
            ).all()
            
            for workout in tomorrow_workouts:
                # Check if user has submitted readiness for tomorrow
                has_readiness = db.query(MorningReadiness).filter(
                    and_(
                        MorningReadiness.user_id == workout.user_id,
                        func.date(MorningReadiness.created_at) >= tomorrow
                    )
                ).first() is not None
                
                if not has_readiness:
                    message = f"You have '{workout.title}' scheduled for tomorrow. Don't forget to submit your morning readiness check for the best workout experience!"
                    
                    result = await self.send_notification(
                        user_id=workout.user_id,
                        notification_type="workout_reminder",
                        message=message,
                        data={
                            "workout_id": str(workout.id),
                            "workout_title": workout.title,
                            "target_date": tomorrow.isoformat()
                        }
                    )
                    
                    if result["success"]:
                        notifications_sent.append({
                            "user_id": workout.user_id,
                            "type": "workout_reminder",
                            "workout_id": str(workout.id),
                            "sent_at": datetime.utcnow().isoformat()
                        })
            
        except Exception as e:
            logger.error(f"Failed to check workout reminders: {e}")
        
        return notifications_sent
    
    async def send_baseline_milestone(
        self,
        db: Session,
        user_id: str,
        milestone_type: str,
        details: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send notification for baseline learning milestones"""
        
        milestone_messages = {
            "first_week": "Great progress! You've completed your first week of readiness tracking. Your baselines are starting to take shape.",
            "confidence_50": "Your baseline confidence has reached 50%! Sara is getting better at understanding your unique patterns.",
            "confidence_80": "Excellent! Your baselines are now highly reliable (80% confidence). Sara can provide more accurate recommendations.",
            "trend_improving": f"Your {details.get('metric', 'health')} trend is improving! Keep up the great work with consistent tracking.",
            "trend_declining": f"Your {details.get('metric', 'health')} trend shows some decline. Consider reviewing your recovery strategies."
        }
        
        message = milestone_messages.get(
            milestone_type,
            "Your fitness baselines have been updated with new insights!"
        )
        
        return await self.send_notification(
            user_id=user_id,
            notification_type="baseline_milestone",
            message=message,
            data={
                "milestone_type": milestone_type,
                "details": details
            }
        )
    
    async def run_notification_checks(self, db: Session) -> Dict[str, Any]:
        """Run all notification checks - called by scheduled task"""
        
        logger.info("Running fitness notification checks")
        
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "checks_run": [],
            "total_sent": 0
        }
        
        try:
            # Check readiness reminders
            readiness_notifications = await self.check_readiness_reminders(db)
            results["checks_run"].append({
                "type": "readiness_reminders",
                "count": len(readiness_notifications),
                "notifications": readiness_notifications
            })
            
            # Check adjustment alerts
            adjustment_notifications = await self.check_adjustment_alerts(db)
            results["checks_run"].append({
                "type": "adjustment_alerts", 
                "count": len(adjustment_notifications),
                "notifications": adjustment_notifications
            })
            
            # Check workout reminders
            workout_notifications = await self.check_workout_reminders(db)
            results["checks_run"].append({
                "type": "workout_reminders",
                "count": len(workout_notifications),
                "notifications": workout_notifications
            })
            
            results["total_sent"] = (
                len(readiness_notifications) + 
                len(adjustment_notifications) + 
                len(workout_notifications)
            )
            
            logger.info(f"Sent {results['total_sent']} fitness notifications")
            
        except Exception as e:
            logger.error(f"Error in notification checks: {e}")
            results["error"] = str(e)
        
        return results
    
    async def subscribe_user_to_fitness_notifications(
        self,
        user_id: str,
        device_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Set up fitness notifications for a user"""
        
        try:
            topic = f"{self.fitness_topic}_{user_id}"
            
            # Return subscription info for client-side setup
            subscription_info = {
                "topic": topic,
                "ntfy_url": self.ntfy_base_url,
                "subscribe_url": f"{self.ntfy_base_url}/{topic}",
                "notification_types": list(self.notification_types.keys()),
                "schedule": {
                    "readiness_reminder": "8:00 AM daily",
                    "workout_reminder": "5:00 PM (day before workout)",
                    "adjustment_alert": "As needed",
                    "baseline_milestone": "Weekly"
                }
            }
            
            return {
                "success": True,
                "subscription": subscription_info,
                "message": f"Fitness notifications set up for user {user_id}"
            }
            
        except Exception as e:
            logger.error(f"Failed to set up notifications for user {user_id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }