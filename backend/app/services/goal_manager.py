"""
Goal Management Service
CRUD operations and auto-progress calculation for goals
"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, date
from pydantic import BaseModel
import json
import logging

logger = logging.getLogger(__name__)


class Goal(BaseModel):
    """Goal model"""
    id: Optional[int] = None
    user_id: str
    title: str
    description: Optional[str] = None
    goal_type: str  # fitness, nutrition, learning, habit, custom
    target_value: Optional[float] = None
    current_value: Optional[float] = None
    unit: Optional[str] = None
    target_date: Optional[date] = None
    status: str = "active"  # active, completed, abandoned
    priority: int = 5
    metadata: Dict[str, Any] = {}
    auto_tracking: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class GoalMilestone(BaseModel):
    """Goal milestone model"""
    id: Optional[int] = None
    goal_id: int
    title: str
    target_value: Optional[float] = None
    target_date: Optional[date] = None
    completed: bool = False
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class GoalProgress(BaseModel):
    """Goal progress entry"""
    id: Optional[int] = None
    goal_id: int
    value: float
    notes: Optional[str] = None
    source: str  # manual, auto, event
    source_id: Optional[str] = None
    logged_at: Optional[datetime] = None


class GoalManager:
    """Manages goals with auto-progress tracking"""

    def __init__(self, db: Session, event_bus=None):
        self.db = db
        self.event_bus = event_bus

    async def create_goal(self, goal: Goal) -> int:
        """
        Create a new goal

        Args:
            goal: Goal data

        Returns:
            Goal ID
        """
        try:
            query = text("""
                INSERT INTO goal (
                    user_id, title, description, goal_type,
                    target_value, current_value, unit, target_date,
                    status, priority, metadata, auto_tracking
                )
                VALUES (
                    :user_id, :title, :description, :goal_type,
                    :target_value, :current_value, :unit, :target_date,
                    :status, :priority, :metadata, :auto_tracking
                )
                RETURNING id
            """)

            result = self.db.execute(query, {
                "user_id": goal.user_id,
                "title": goal.title,
                "description": goal.description,
                "goal_type": goal.goal_type,
                "target_value": goal.target_value,
                "current_value": goal.current_value,
                "unit": goal.unit,
                "target_date": goal.target_date,
                "status": goal.status,
                "priority": goal.priority,
                "metadata": json.dumps(goal.metadata),
                "auto_tracking": goal.auto_tracking
            })

            self.db.commit()

            goal_id = result.fetchone()[0]
            goal.id = goal_id

            logger.info(f"✅ Goal created: {goal_id} - {goal.title}")

            # Emit event
            if self.event_bus:
                await self.event_bus.publish({
                    "event_type": "goal.created",
                    "user_id": goal.user_id,
                    "payload": {"goal_id": goal_id, "title": goal.title}
                })

            return goal_id

        except Exception as e:
            logger.error(f"Error creating goal: {e}")
            self.db.rollback()
            raise

    async def get_goal(self, goal_id: int, user_id: str) -> Optional[Goal]:
        """Get goal by ID"""
        try:
            query = text("""
                SELECT
                    id, user_id, title, description, goal_type,
                    target_value, current_value, unit, target_date,
                    status, priority, metadata, auto_tracking,
                    created_at, updated_at, completed_at
                FROM goal
                WHERE id = :goal_id AND user_id = :user_id
            """)

            result = self.db.execute(query, {"goal_id": goal_id, "user_id": user_id})
            row = result.fetchone()

            if not row:
                return None

            return Goal(
                id=row.id,
                user_id=row.user_id,
                title=row.title,
                description=row.description,
                goal_type=row.goal_type,
                target_value=row.target_value,
                current_value=row.current_value,
                unit=row.unit,
                target_date=row.target_date,
                status=row.status,
                priority=row.priority,
                metadata=json.loads(row.metadata) if isinstance(row.metadata, str) else row.metadata,
                auto_tracking=row.auto_tracking,
                created_at=row.created_at,
                updated_at=row.updated_at,
                completed_at=row.completed_at
            )

        except Exception as e:
            logger.error(f"Error getting goal: {e}")
            return None

    async def list_goals(
        self,
        user_id: str,
        status: Optional[str] = None,
        goal_type: Optional[str] = None
    ) -> List[Goal]:
        """List goals for user"""
        try:
            conditions = ["user_id = :user_id"]
            params = {"user_id": user_id}

            if status:
                conditions.append("status = :status")
                params["status"] = status

            if goal_type:
                conditions.append("goal_type = :goal_type")
                params["goal_type"] = goal_type

            where_clause = " AND ".join(conditions)

            query = text(f"""
                SELECT
                    id, user_id, title, description, goal_type,
                    target_value, current_value, unit, target_date,
                    status, priority, metadata, auto_tracking,
                    created_at, updated_at, completed_at
                FROM goal
                WHERE {where_clause}
                ORDER BY priority DESC, created_at DESC
            """)

            result = self.db.execute(query, params)

            goals = []
            for row in result.fetchall():
                goals.append(Goal(
                    id=row.id,
                    user_id=row.user_id,
                    title=row.title,
                    description=row.description,
                    goal_type=row.goal_type,
                    target_value=row.target_value,
                    current_value=row.current_value,
                    unit=row.unit,
                    target_date=row.target_date,
                    status=row.status,
                    priority=row.priority,
                    metadata=json.loads(row.metadata) if isinstance(row.metadata, str) else row.metadata,
                    auto_tracking=row.auto_tracking,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    completed_at=row.completed_at
                ))

            return goals

        except Exception as e:
            logger.error(f"Error listing goals: {e}")
            return []

    async def update_goal(self, goal_id: int, user_id: str, updates: Dict[str, Any]) -> bool:
        """Update goal"""
        try:
            # Build dynamic update query
            set_clauses = []
            params = {"goal_id": goal_id, "user_id": user_id}

            for key, value in updates.items():
                if key in ["title", "description", "target_value", "current_value", "unit",
                          "target_date", "status", "priority", "auto_tracking"]:
                    set_clauses.append(f"{key} = :{key}")
                    params[key] = value
                elif key == "metadata":
                    set_clauses.append("metadata = :metadata")
                    params["metadata"] = json.dumps(value)

            if not set_clauses:
                return True

            set_clauses.append("updated_at = NOW()")

            query = text(f"""
                UPDATE goal
                SET {', '.join(set_clauses)}
                WHERE id = :goal_id AND user_id = :user_id
            """)

            self.db.execute(query, params)
            self.db.commit()

            logger.info(f"✅ Goal updated: {goal_id}")

            return True

        except Exception as e:
            logger.error(f"Error updating goal: {e}")
            self.db.rollback()
            return False

    async def delete_goal(self, goal_id: int, user_id: str) -> bool:
        """Delete goal"""
        try:
            query = text("""
                DELETE FROM goal
                WHERE id = :goal_id AND user_id = :user_id
            """)

            self.db.execute(query, {"goal_id": goal_id, "user_id": user_id})
            self.db.commit()

            logger.info(f"✅ Goal deleted: {goal_id}")

            return True

        except Exception as e:
            logger.error(f"Error deleting goal: {e}")
            self.db.rollback()
            return False

    async def add_progress(self, progress: GoalProgress) -> int:
        """Add progress entry"""
        try:
            query = text("""
                INSERT INTO goal_progress (
                    goal_id, value, notes, source, source_id
                )
                VALUES (
                    :goal_id, :value, :notes, :source, :source_id
                )
                RETURNING id
            """)

            result = self.db.execute(query, {
                "goal_id": progress.goal_id,
                "value": progress.value,
                "notes": progress.notes,
                "source": progress.source,
                "source_id": progress.source_id
            })

            self.db.commit()

            progress_id = result.fetchone()[0]

            # Update current_value if auto-tracking
            await self._update_current_value(progress.goal_id)

            logger.info(f"✅ Progress logged: {progress_id} for goal {progress.goal_id}")

            return progress_id

        except Exception as e:
            logger.error(f"Error adding progress: {e}")
            self.db.rollback()
            raise

    async def _update_current_value(self, goal_id: int):
        """Recalculate current_value from progress entries"""
        try:
            # Get latest progress value
            query = text("""
                SELECT value
                FROM goal_progress
                WHERE goal_id = :goal_id
                ORDER BY logged_at DESC
                LIMIT 1
            """)

            result = self.db.execute(query, {"goal_id": goal_id})
            row = result.fetchone()

            if row:
                update_query = text("""
                    UPDATE goal
                    SET current_value = :value, updated_at = NOW()
                    WHERE id = :goal_id
                """)

                self.db.execute(update_query, {"goal_id": goal_id, "value": row.value})
                self.db.commit()

                # Check if goal is completed
                await self._check_goal_completion(goal_id)

        except Exception as e:
            logger.error(f"Error updating current value: {e}")
            self.db.rollback()

    async def _check_goal_completion(self, goal_id: int):
        """Check if goal has reached target and mark as completed"""
        try:
            query = text("""
                SELECT current_value, target_value, status
                FROM goal
                WHERE id = :goal_id
            """)

            result = self.db.execute(query, {"goal_id": goal_id})
            row = result.fetchone()

            if not row or row.status != "active":
                return

            if row.current_value is not None and row.target_value is not None:
                if row.current_value >= row.target_value:
                    # Goal completed!
                    update_query = text("""
                        UPDATE goal
                        SET status = 'completed', completed_at = NOW(), updated_at = NOW()
                        WHERE id = :goal_id
                    """)

                    self.db.execute(update_query, {"goal_id": goal_id})
                    self.db.commit()

                    logger.info(f"🎉 Goal completed: {goal_id}")

                    # Emit event
                    if self.event_bus:
                        await self.event_bus.publish({
                            "event_type": "goal.completed",
                            "user_id": row.user_id,
                            "payload": {"goal_id": goal_id}
                        })

        except Exception as e:
            logger.error(f"Error checking goal completion: {e}")

    async def calculate_percentage(self, goal_id: int) -> Optional[float]:
        """Calculate goal completion percentage"""
        try:
            query = text("""
                SELECT current_value, target_value
                FROM goal
                WHERE id = :goal_id
            """)

            result = self.db.execute(query, {"goal_id": goal_id})
            row = result.fetchone()

            if not row or not row.target_value:
                return None

            current = row.current_value or 0
            percentage = (current / row.target_value) * 100

            return min(100.0, max(0.0, percentage))

        except Exception as e:
            logger.error(f"Error calculating percentage: {e}")
            return None

    async def get_progress_history(
        self,
        goal_id: int,
        limit: int = 100
    ) -> List[GoalProgress]:
        """Get progress history for a goal"""
        try:
            query = text("""
                SELECT
                    id, goal_id, value, notes, source, source_id, logged_at
                FROM goal_progress
                WHERE goal_id = :goal_id
                ORDER BY logged_at DESC
                LIMIT :limit
            """)

            result = self.db.execute(query, {"goal_id": goal_id, "limit": limit})

            history = []
            for row in result.fetchall():
                history.append(GoalProgress(
                    id=row.id,
                    goal_id=row.goal_id,
                    value=row.value,
                    notes=row.notes,
                    source=row.source,
                    source_id=row.source_id,
                    logged_at=row.logged_at
                ))

            return history

        except Exception as e:
            logger.error(f"Error getting progress history: {e}")
            return []


def get_goal_manager(db: Session, event_bus=None) -> GoalManager:
    """Get goal manager instance"""
    return GoalManager(db, event_bus)
