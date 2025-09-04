"""
Habit Instance Generation Service - Creates daily habit instances
"""

import uuid
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


class HabitInstanceGenerator:
    """Generates and manages habit instances for daily tracking"""

    @staticmethod
    def generate_instances_for_habit(
        db: Session,
        habit: Any,  # Habit model instance
        start_date: date,
        end_date: date,
        force_regenerate: bool = False
    ) -> List[str]:
        """
        Generate habit instances for a date range
        
        Returns list of instance IDs created
        """
        from app.services.habit_scheduler import HabitScheduler
        from app.models import HabitInstance  # Import here to avoid circular imports
        
        instance_ids = []
        
        # Get expected dates from scheduler
        expected_dates = HabitScheduler.generate_expected_dates(
            rrule_string=habit.rrule,
            start_date=start_date,
            end_date=end_date,
            weekly_minimum=habit.weekly_minimum,
            pause_from=habit.pause_from,
            pause_to=habit.pause_to
        )
        
        # Get time windows
        windows = HabitScheduler.get_time_windows(habit.windows)
        
        for expected_date in expected_dates:
            # Check if instance already exists
            existing = db.query(HabitInstance).filter(
                HabitInstance.habit_id == habit.id,
                HabitInstance.date == expected_date
            ).first()
            
            if existing and not force_regenerate:
                continue
            
            if existing and force_regenerate:
                # Update existing instance
                existing.expected = True
                existing.window = windows[0]["name"] if windows else None
                existing.target = habit.target_numeric
                existing.updated_at = datetime.now()
                db.commit()
                instance_ids.append(existing.id)
            else:
                # Create new instance
                instance = HabitInstance(
                    id=str(uuid.uuid4()),
                    habit_id=habit.id,
                    user_id=habit.user_id,
                    date=expected_date,
                    window=windows[0]["name"] if windows else None,
                    expected=True,
                    status="pending",
                    progress=0.0,
                    total_amount=0.0 if habit.type in ["quantitative", "time"] else None,
                    target=habit.target_numeric
                )
                
                db.add(instance)
                db.commit()
                db.refresh(instance)
                instance_ids.append(instance.id)
        
        return instance_ids

    @staticmethod
    def generate_instances_for_all_habits(
        db: Session,
        user_id: str,
        start_date: date,
        end_date: date
    ) -> Dict[str, List[str]]:
        """Generate instances for all user's habits in date range"""
        from app.models import Habit  # Import here to avoid circular imports
        
        # Get all active habits for user
        habits = db.query(Habit).filter(
            Habit.user_id == user_id,
            Habit.paused == 0  # Only active habits
        ).all()
        
        results = {}
        
        for habit in habits:
            try:
                instance_ids = HabitInstanceGenerator.generate_instances_for_habit(
                    db, habit, start_date, end_date
                )
                results[habit.id] = instance_ids
                logger.info(f"Generated {len(instance_ids)} instances for habit {habit.title}")
            except Exception as e:
                logger.error(f"Failed to generate instances for habit {habit.id}: {e}")
                results[habit.id] = []
        
        return results

    @staticmethod
    def get_today_instances(db: Session, user_id: str, target_date: Optional[date] = None) -> List[Dict[str, Any]]:
        """Get today's habit instances with habit details"""
        if target_date is None:
            target_date = date.today()
        
        # Raw SQL query to get instances with habit details
        query = text("""
            SELECT 
                hi.id as instance_id,
                hi.habit_id,
                hi.date,
                hi.window,
                hi.expected,
                hi.status,
                hi.progress,
                hi.total_amount,
                hi.target,
                h.title,
                h.type,
                h.unit,
                h.target_numeric as habit_target,
                h.checklist_mode,
                h.checklist_threshold
            FROM habit_instances hi
            JOIN habits h ON hi.habit_id = h.id
            WHERE hi.user_id = :user_id 
                AND hi.date = :target_date
                AND hi.expected = 1
            ORDER BY h.title
        """)
        
        result = db.execute(query, {"user_id": user_id, "target_date": target_date})
        rows = result.fetchall()
        
        instances = []
        for row in rows:
            instances.append({
                "instance_id": row.instance_id,
                "habit_id": row.habit_id,
                "date": row.date.isoformat(),
                "window": row.window,
                "expected": bool(row.expected),
                "status": row.status,
                "progress": row.progress,
                "total_amount": row.total_amount,
                "target": row.target or row.habit_target,
                "title": row.title,
                "type": row.type,
                "unit": row.unit
            })
        
        return instances

    @staticmethod
    def update_instance_progress(
        db: Session,
        instance_id: str,
        logs: List[Dict[str, Any]],
        habit: Any,
        checklist_items: List[Dict[str, Any]] = None
    ) -> bool:
        """Update instance progress based on logs"""
        from app.services.habit_progress import HabitProgressCalculator
        from app.models import HabitInstance
        
        instance = db.query(HabitInstance).filter(HabitInstance.id == instance_id).first()
        if not instance:
            logger.error(f"Instance {instance_id} not found")
            return False
        
        # Calculate progress
        progress, status, total_amount = HabitProgressCalculator.calculate_progress(
            habit_type=habit.type,
            logs=logs,
            target_numeric=habit.target_numeric,
            checklist_items=checklist_items,
            checklist_mode=habit.checklist_mode or "all",
            checklist_threshold=habit.checklist_threshold or 1.0
        )
        
        # Update instance
        instance.progress = progress
        instance.status = status
        instance.total_amount = total_amount
        instance.updated_at = datetime.now()
        
        db.commit()
        
        logger.info(f"Updated instance {instance_id}: progress={progress:.2f}, status={status}")
        return True

    @staticmethod
    def create_missed_instances(
        db: Session,
        habit: Any,
        up_to_date: Optional[date] = None
    ) -> List[str]:
        """Create instances for missed days (for retro logging)"""
        if up_to_date is None:
            up_to_date = date.today()
        
        # Find the habit's creation date
        creation_date = habit.created_at.date() if isinstance(habit.created_at, datetime) else habit.created_at
        
        # Generate instances from creation date to up_to_date
        return HabitInstanceGenerator.generate_instances_for_habit(
            db, habit, creation_date, up_to_date
        )

    @staticmethod
    def cleanup_old_instances(db: Session, older_than_days: int = 90) -> int:
        """Clean up old instances to prevent database bloat"""
        from app.models import HabitInstance
        
        cutoff_date = date.today() - timedelta(days=older_than_days)
        
        # Delete old instances that are completed or skipped
        deleted_count = db.query(HabitInstance).filter(
            HabitInstance.date < cutoff_date,
            HabitInstance.status.in_(["complete", "skipped"])
        ).delete()
        
        db.commit()
        
        logger.info(f"Cleaned up {deleted_count} old habit instances")
        return deleted_count

    @staticmethod
    def get_instance_by_habit_and_date(
        db: Session,
        habit_id: str,
        target_date: date
    ) -> Optional[Dict[str, Any]]:
        """Get or create instance for a specific habit and date"""
        from app.models import HabitInstance, Habit
        
        # Try to find existing instance
        instance = db.query(HabitInstance).filter(
            HabitInstance.habit_id == habit_id,
            HabitInstance.date == target_date
        ).first()
        
        if instance:
            return {
                "instance_id": instance.id,
                "habit_id": instance.habit_id,
                "date": instance.date.isoformat(),
                "status": instance.status,
                "progress": instance.progress,
                "total_amount": instance.total_amount,
                "target": instance.target
            }
        
        # If no instance exists, check if one should be created
        habit = db.query(Habit).filter(Habit.id == habit_id).first()
        if not habit:
            return None
        
        from app.services.habit_scheduler import HabitScheduler
        
        should_exist = HabitScheduler.should_generate_instance(
            habit_date=target_date,
            rrule_string=habit.rrule,
            weekly_minimum=habit.weekly_minimum,
            pause_from=habit.pause_from,
            pause_to=habit.pause_to
        )
        
        if should_exist:
            # Create the instance
            instance_ids = HabitInstanceGenerator.generate_instances_for_habit(
                db, habit, target_date, target_date
            )
            
            if instance_ids:
                # Return the newly created instance
                instance = db.query(HabitInstance).filter(HabitInstance.id == instance_ids[0]).first()
                if instance:
                    return {
                        "instance_id": instance.id,
                        "habit_id": instance.habit_id,
                        "date": instance.date.isoformat(),
                        "status": instance.status,
                        "progress": instance.progress,
                        "total_amount": instance.total_amount,
                        "target": instance.target
                    }
        
        return None

    @staticmethod
    def generate_next_30_days(db: Session, user_id: str) -> Dict[str, int]:
        """Generate instances for the next 30 days for all user habits"""
        start_date = date.today()
        end_date = start_date + timedelta(days=30)
        
        results = HabitInstanceGenerator.generate_instances_for_all_habits(
            db, user_id, start_date, end_date
        )
        
        # Return summary
        summary = {}
        for habit_id, instance_ids in results.items():
            summary[habit_id] = len(instance_ids)
        
        total_instances = sum(summary.values())
        logger.info(f"Generated {total_instances} instances for next 30 days for user {user_id}")
        
        return summary