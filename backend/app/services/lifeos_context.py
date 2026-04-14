"""
LifeOS Unified Context State
Aggregates all user data into holistic life context
"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta
from app.core.timezone import now as local_now
import json
import logging
from app.services.event_bus import EventSubscriber, Event, EventType

logger = logging.getLogger(__name__)


class LifeOSContextAggregator:
    """Aggregates user data into unified life context"""

    def __init__(self, db: Session):
        self.db = db

    async def aggregate_context(self, user_id: str) -> Dict[str, Any]:
        """
        Aggregate all context for a user

        Returns complete life context including:
        - Active goals
        - Current habits
        - Health status
        - Mood profile
        - Stress level
        - Energy level
        """
        context = {
            "user_id": user_id,
            "active_goals": await self._get_active_goals(user_id),
            "current_habits": await self._get_current_habits(user_id),
            "current_projects": await self._get_current_projects(user_id),
            "health_status": await self._calculate_health_status(user_id),
            "focus_mode": await self._detect_focus_mode(user_id),
            "stress_level": await self._estimate_stress_level(user_id),
            "mood_profile": await self._build_mood_profile(user_id),
            "energy_level": await self._estimate_energy_level(user_id),
            "updated_at": local_now().isoformat()
        }

        return context

    async def _get_active_goals(self, user_id: str) -> List[Dict[str, Any]]:
        """Get active goals"""
        try:
            # Query goals table (will be created in Phase 3)
            # For now, return empty list
            query = text("""
                SELECT id, title, type, target_value, current_value, deadline, status
                FROM goals
                WHERE user_id = :user_id
                AND status IN ('active', 'in_progress')
                ORDER BY created_at DESC
                LIMIT 10
            """)

            result = self.db.execute(query, {"user_id": user_id})

            goals = []
            for row in result.fetchall():
                progress = 0
                if row.target_value and row.current_value:
                    progress = min(100, (row.current_value / row.target_value) * 100)

                goals.append({
                    "id": row.id,
                    "title": row.title,
                    "type": row.type,
                    "progress": round(progress, 1),
                    "deadline": row.deadline.isoformat() if row.deadline else None,
                    "status": row.status
                })

            return goals

        except Exception as e:
            logger.debug(f"Goals table not yet created or error: {e}")
            return []

    async def _get_current_habits(self, user_id: str) -> List[Dict[str, Any]]:
        """Detect current habits from event patterns"""
        try:
            # Analyze event patterns for the last 30 days
            query = text("""
                SELECT event_type, COUNT(*) as frequency,
                       EXTRACT(DOW FROM timestamp) as day_of_week
                FROM event_log
                WHERE user_id = :user_id
                AND timestamp > NOW() - INTERVAL '30 days'
                GROUP BY event_type, EXTRACT(DOW FROM timestamp)
                HAVING COUNT(*) >= 4
                ORDER BY frequency DESC
            """)

            result = self.db.execute(query, {"user_id": user_id})

            habits = []
            for row in result.fetchall():
                habit_name = self._event_to_habit_name(row.event_type)
                if habit_name:
                    habits.append({
                        "name": habit_name,
                        "frequency": row.frequency,
                        "day_of_week": row.day_of_week,
                        "consistency": "high" if row.frequency >= 12 else "moderate"
                    })

            return habits[:10]  # Top 10 habits

        except Exception as e:
            logger.error(f"Error detecting habits: {e}")
            return []

    def _event_to_habit_name(self, event_type: str) -> Optional[str]:
        """Convert event type to habit name"""
        mapping = {
            "workout.logged": "Regular workouts",
            "food.logged": "Meal tracking",
            "note.created": "Journaling",
            "recovery.logged": "Recovery tracking",
            "timer.started": "Time blocking"
        }
        return mapping.get(event_type)

    async def _get_current_projects(self, user_id: str) -> List[Dict[str, Any]]:
        """Get current projects from notes"""
        try:
            # Find notes tagged as projects
            query = text("""
                SELECT id, title, created_at, updated_at
                FROM notes
                WHERE user_id = :user_id
                AND (title ILIKE '%project%' OR content ILIKE '%project:%')
                ORDER BY updated_at DESC
                LIMIT 5
            """)

            result = self.db.execute(query, {"user_id": user_id})

            projects = []
            for row in result.fetchall():
                projects.append({
                    "id": row.id,
                    "title": row.title,
                    "last_updated": row.updated_at.isoformat() if row.updated_at else None
                })

            return projects

        except Exception as e:
            logger.error(f"Error getting projects: {e}")
            return []

    async def _calculate_health_status(self, user_id: str) -> Dict[str, Any]:
        """Calculate health status from recovery logs and workouts"""
        try:
            # Get latest recovery metrics (last 7 days)
            query = text("""
                SELECT
                    AVG(sleep_hours) as avg_sleep,
                    AVG(hrv) as avg_hrv,
                    AVG(heart_rate) as avg_hr,
                    AVG(soreness_level) as avg_soreness,
                    COUNT(DISTINCT DATE(logged_at)) as days_tracked
                FROM recovery_log
                WHERE user_id = :user_id
                AND logged_at > NOW() - INTERVAL '7 days'
            """)

            result = self.db.execute(query, {"user_id": user_id})
            row = result.fetchone()

            # Get workout frequency
            workout_query = text("""
                SELECT COUNT(DISTINCT DATE(session_date)) as workout_days
                FROM workout_log
                WHERE user_id = :user_id
                AND session_date > NOW() - INTERVAL '7 days'
            """)

            workout_result = self.db.execute(workout_query, {"user_id": user_id})
            workout_row = workout_result.fetchone()

            health_status = {
                "avg_sleep_hours": round(row.avg_sleep, 1) if row.avg_sleep else None,
                "avg_hrv": round(row.avg_hrv, 1) if row.avg_hrv else None,
                "avg_heart_rate": round(row.avg_hr, 1) if row.avg_hr else None,
                "avg_soreness": round(row.avg_soreness, 1) if row.avg_soreness else None,
                "workout_frequency": workout_row.workout_days if workout_row else 0,
                "recovery_tracking_days": row.days_tracked if row.days_tracked else 0,
                "overall_score": await self._calculate_health_score(row, workout_row)
            }

            return health_status

        except Exception as e:
            logger.error(f"Error calculating health status: {e}")
            return {}

    async def _calculate_health_score(self, recovery_row, workout_row) -> Optional[float]:
        """Calculate overall health score (0-100)"""
        try:
            score = 50.0  # Base score

            # Sleep contribution (0-20 points)
            if recovery_row and recovery_row.avg_sleep:
                if recovery_row.avg_sleep >= 7:
                    score += 20
                elif recovery_row.avg_sleep >= 6:
                    score += 15
                elif recovery_row.avg_sleep >= 5:
                    score += 10

            # HRV contribution (0-20 points)
            if recovery_row and recovery_row.avg_hrv:
                if recovery_row.avg_hrv >= 70:
                    score += 20
                elif recovery_row.avg_hrv >= 50:
                    score += 15
                elif recovery_row.avg_hrv >= 30:
                    score += 10

            # Workout contribution (0-20 points)
            if workout_row and workout_row.workout_days:
                if workout_row.workout_days >= 4:
                    score += 20
                elif workout_row.workout_days >= 3:
                    score += 15
                elif workout_row.workout_days >= 2:
                    score += 10

            # Soreness penalty
            if recovery_row and recovery_row.avg_soreness:
                if recovery_row.avg_soreness > 7:
                    score -= 10
                elif recovery_row.avg_soreness > 5:
                    score -= 5

            return round(min(100, max(0, score)), 1)

        except Exception as e:
            logger.error(f"Error calculating health score: {e}")
            return None

    async def _detect_focus_mode(self, user_id: str) -> Optional[str]:
        """Detect current focus mode from recent activity"""
        try:
            # Look at events in the last hour
            query = text("""
                SELECT event_type, COUNT(*) as count
                FROM event_log
                WHERE user_id = :user_id
                AND timestamp > NOW() - INTERVAL '1 hour'
                GROUP BY event_type
                ORDER BY count DESC
                LIMIT 1
            """)

            result = self.db.execute(query, {"user_id": user_id})
            row = result.fetchone()

            if not row:
                return None

            # Map events to focus modes
            mode_mapping = {
                "workout.logged": "fitness",
                "food.logged": "fitness",
                "recovery.logged": "fitness",
                "note.created": "work",
                "timer.started": "work",
                "calendar_event.created": "work"
            }

            return mode_mapping.get(row.event_type, "personal")

        except Exception as e:
            logger.error(f"Error detecting focus mode: {e}")
            return None

    async def _estimate_stress_level(self, user_id: str) -> Optional[int]:
        """Estimate stress level from HRV, sleep, and activity patterns"""
        try:
            # Get recent recovery data
            query = text("""
                SELECT hrv, sleep_hours, soreness_level
                FROM recovery_log
                WHERE user_id = :user_id
                ORDER BY logged_at DESC
                LIMIT 3
            """)

            result = self.db.execute(query, {"user_id": user_id})
            rows = result.fetchall()

            if not rows:
                return None

            stress_indicators = []

            for row in rows:
                # Low HRV = higher stress
                if row.hrv and row.hrv < 40:
                    stress_indicators.append(7)
                elif row.hrv and row.hrv < 50:
                    stress_indicators.append(5)
                else:
                    stress_indicators.append(3)

                # Poor sleep = higher stress
                if row.sleep_hours and row.sleep_hours < 6:
                    stress_indicators.append(7)
                elif row.sleep_hours and row.sleep_hours < 7:
                    stress_indicators.append(5)
                else:
                    stress_indicators.append(3)

                # High soreness = higher stress
                if row.soreness_level and row.soreness_level > 7:
                    stress_indicators.append(6)

            avg_stress = sum(stress_indicators) / len(stress_indicators) if stress_indicators else 5
            return round(avg_stress)

        except Exception as e:
            logger.error(f"Error estimating stress level: {e}")
            return None

    async def _build_mood_profile(self, user_id: str) -> Dict[str, Any]:
        """Build mood profile from emotional memory (Phase 2)"""
        try:
            # This will be enhanced in Phase 2 with emotional memory
            # For now, return basic mood indicators
            query = text("""
                SELECT emotion_metadata
                FROM episodes
                WHERE user_id = :user_id
                AND emotion_metadata IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 10
            """)

            result = self.db.execute(query, {"user_id": user_id})
            rows = result.fetchall()

            if not rows:
                return {"trend": "neutral", "confidence": "low"}

            # Aggregate emotions (simplified)
            positive_count = 0
            negative_count = 0

            for row in rows:
                if row.emotion_metadata:
                    sentiment = row.emotion_metadata.get("sentiment", 0)
                    if sentiment > 0.3:
                        positive_count += 1
                    elif sentiment < -0.3:
                        negative_count += 1

            if positive_count > negative_count:
                trend = "positive"
            elif negative_count > positive_count:
                trend = "negative"
            else:
                trend = "neutral"

            return {
                "trend": trend,
                "positive_count": positive_count,
                "negative_count": negative_count,
                "confidence": "high" if len(rows) >= 7 else "moderate"
            }

        except Exception as e:
            logger.debug(f"Emotional memory not yet available: {e}")
            return {"trend": "neutral", "confidence": "low"}

    async def _estimate_energy_level(self, user_id: str) -> Optional[int]:
        """Estimate energy level from sleep and activity"""
        try:
            # Get latest sleep data
            query = text("""
                SELECT sleep_hours, hrv
                FROM recovery_log
                WHERE user_id = :user_id
                ORDER BY logged_at DESC
                LIMIT 1
            """)

            result = self.db.execute(query, {"user_id": user_id})
            row = result.fetchone()

            if not row:
                return None

            energy = 5  # Base energy

            # Sleep contribution
            if row.sleep_hours:
                if row.sleep_hours >= 8:
                    energy += 3
                elif row.sleep_hours >= 7:
                    energy += 2
                elif row.sleep_hours >= 6:
                    energy += 1
                else:
                    energy -= 1

            # HRV contribution
            if row.hrv:
                if row.hrv >= 70:
                    energy += 2
                elif row.hrv >= 50:
                    energy += 1
                elif row.hrv < 40:
                    energy -= 1

            return min(10, max(1, energy))

        except Exception as e:
            logger.error(f"Error estimating energy: {e}")
            return None

    async def update_context(self, user_id: str) -> Dict[str, Any]:
        """Update and store user's life context"""
        try:
            # Aggregate context
            context = await self.aggregate_context(user_id)

            # Upsert to database
            upsert_query = text("""
                INSERT INTO user_life_context (
                    user_id, active_goals, current_habits, current_projects,
                    health_status, focus_mode, stress_level, mood_profile,
                    energy_level, updated_at
                )
                VALUES (
                    :user_id, :active_goals, :current_habits, :current_projects,
                    :health_status, :focus_mode, :stress_level, :mood_profile,
                    :energy_level, NOW()
                )
                ON CONFLICT (user_id) DO UPDATE SET
                    active_goals = EXCLUDED.active_goals,
                    current_habits = EXCLUDED.current_habits,
                    current_projects = EXCLUDED.current_projects,
                    health_status = EXCLUDED.health_status,
                    focus_mode = EXCLUDED.focus_mode,
                    stress_level = EXCLUDED.stress_level,
                    mood_profile = EXCLUDED.mood_profile,
                    energy_level = EXCLUDED.energy_level,
                    updated_at = NOW()
            """)

            self.db.execute(upsert_query, {
                "user_id": user_id,
                "active_goals": json.dumps(context["active_goals"]),
                "current_habits": json.dumps(context["current_habits"]),
                "current_projects": json.dumps(context["current_projects"]),
                "health_status": json.dumps(context["health_status"]),
                "focus_mode": context["focus_mode"],
                "stress_level": context["stress_level"],
                "mood_profile": json.dumps(context["mood_profile"]),
                "energy_level": context["energy_level"]
            })

            self.db.commit()

            logger.info(f"✅ Updated LifeOS context for user {user_id}")
            return context

        except Exception as e:
            logger.error(f"Error updating context: {e}")
            self.db.rollback()
            raise

    async def create_snapshot(self, user_id: str) -> None:
        """Create daily snapshot of context"""
        try:
            # Get current context
            query = text("""
                SELECT active_goals, current_habits, current_projects, health_status,
                       focus_mode, stress_level, mood_profile, energy_level
                FROM user_life_context
                WHERE user_id = :user_id
            """)

            result = self.db.execute(query, {"user_id": user_id})
            row = result.fetchone()

            if not row:
                logger.warning(f"No context found for user {user_id}")
                return

            # Create snapshot
            snapshot_data = {
                "active_goals": row.active_goals,
                "current_habits": row.current_habits,
                "current_projects": row.current_projects,
                "health_status": row.health_status,
                "focus_mode": row.focus_mode,
                "stress_level": row.stress_level,
                "mood_profile": row.mood_profile,
                "energy_level": row.energy_level
            }

            insert_query = text("""
                INSERT INTO context_snapshots (user_id, snapshot_data, snapshot_date)
                VALUES (:user_id, :snapshot_data, CURRENT_DATE)
                ON CONFLICT (user_id, snapshot_date) DO UPDATE
                SET snapshot_data = EXCLUDED.snapshot_data
            """)

            self.db.execute(insert_query, {
                "user_id": user_id,
                "snapshot_data": json.dumps(snapshot_data)
            })

            self.db.commit()

            logger.info(f"📸 Created context snapshot for user {user_id}")

        except Exception as e:
            logger.error(f"Error creating snapshot: {e}")
            self.db.rollback()


class LifeOSContextSubscriber(EventSubscriber):
    """Subscriber that updates context on relevant events"""

    def __init__(self, db: Session):
        super().__init__(name="LifeOSContextSubscriber")
        self.db = db
        self.aggregator = LifeOSContextAggregator(db)

        # Subscribe to context-affecting events
        self.subscribe_to(
            EventType.WORKOUT_LOGGED,
            EventType.FOOD_LOGGED,
            EventType.RECOVERY_LOGGED,
            EventType.GOAL_CREATED,
            EventType.GOAL_PROGRESS_LOGGED,
            EventType.NOTE_CREATED,
            EventType.CONTEXT_MODE_CHANGED
        )

    async def handle_event(self, event: Event):
        """Update context when relevant events occur"""
        try:
            await self.aggregator.update_context(event.user_id)
            logger.debug(f"Updated LifeOS context for {event.user_id} after {event.event_type.value}")
        except Exception as e:
            logger.error(f"Failed to update context: {e}")
