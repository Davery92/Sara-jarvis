"""
Proactive Intelligence Engine
Pattern recognition and smart suggestions
"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta, time as dt_time
from pydantic import BaseModel
import json
import logging

logger = logging.getLogger(__name__)


class ProactiveSuggestion(BaseModel):
    """Proactive suggestion model"""
    id: Optional[int] = None
    user_id: str
    suggestion_type: str
    title: str
    description: Optional[str] = None
    action_data: Dict[str, Any] = {}
    confidence: Optional[float] = None
    priority: int = 5
    status: str = "pending"
    expires_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class DetectedPattern(BaseModel):
    """Detected pattern model"""
    id: Optional[int] = None
    user_id: str
    pattern_type: str
    description: str
    pattern_data: Dict[str, Any] = {}
    confidence: Optional[float] = None
    occurrences: int = 1
    first_detected: Optional[datetime] = None
    last_detected: Optional[datetime] = None


class ProactiveIntelligenceEngine:
    """Generates suggestions and detects patterns"""

    def __init__(self, db: Session, event_bus=None):
        self.db = db
        self.event_bus = event_bus

        # Duplicate prevention window (24 hours)
        self.duplicate_window_hours = 24

    async def analyze_and_suggest(self, user_id: str) -> List[ProactiveSuggestion]:
        """
        Analyze user data and generate proactive suggestions

        Args:
            user_id: User ID

        Returns:
            List of new suggestions
        """
        suggestions = []

        # Detect patterns
        patterns = await self._detect_patterns(user_id)

        # Generate suggestions based on patterns
        for pattern in patterns:
            if pattern.pattern_type == "meal_timing":
                meal_suggestion = await self._suggest_meal(user_id, pattern)
                if meal_suggestion:
                    suggestions.append(meal_suggestion)

            elif pattern.pattern_type == "workout_schedule":
                workout_suggestion = await self._suggest_workout(user_id, pattern)
                if workout_suggestion:
                    suggestions.append(workout_suggestion)

            elif pattern.pattern_type == "productivity_peak":
                break_suggestion = await self._suggest_break(user_id, pattern)
                if break_suggestion:
                    suggestions.append(break_suggestion)

        # Check for deficits (e.g., low protein at 3pm)
        deficit_suggestions = await self._check_deficits(user_id)
        suggestions.extend(deficit_suggestions)

        # Save suggestions
        for suggestion in suggestions:
            await self._save_suggestion(suggestion)

        logger.info(f"🧠 Generated {len(suggestions)} proactive suggestions for {user_id}")

        return suggestions

    async def _detect_patterns(self, user_id: str) -> List[DetectedPattern]:
        """Detect patterns in user behavior"""
        patterns = []

        # Meal timing pattern
        meal_pattern = await self._detect_meal_timing_pattern(user_id)
        if meal_pattern:
            patterns.append(meal_pattern)

        # Workout schedule pattern
        workout_pattern = await self._detect_workout_schedule_pattern(user_id)
        if workout_pattern:
            patterns.append(workout_pattern)

        # Sleep schedule pattern
        sleep_pattern = await self._detect_sleep_schedule_pattern(user_id)
        if sleep_pattern:
            patterns.append(sleep_pattern)

        # Save detected patterns
        for pattern in patterns:
            await self._save_pattern(pattern)

        return patterns

    async def _detect_meal_timing_pattern(self, user_id: str) -> Optional[DetectedPattern]:
        """Detect typical meal timing patterns"""
        try:
            # Get meal times from last 14 days
            query = text("""
                SELECT
                    EXTRACT(HOUR FROM logged_at) as hour,
                    COUNT(*) as count
                FROM food_log
                WHERE user_id = :user_id
                AND logged_at > NOW() - INTERVAL '14 days'
                GROUP BY EXTRACT(HOUR FROM logged_at)
                HAVING COUNT(*) >= 3
                ORDER BY count DESC
                LIMIT 3
            """)

            result = self.db.execute(query, {"user_id": user_id})
            rows = result.fetchall()

            if not rows:
                return None

            typical_hours = [int(row.hour) for row in rows]

            return DetectedPattern(
                user_id=user_id,
                pattern_type="meal_timing",
                description=f"Typically eats at {', '.join([f'{h}:00' for h in typical_hours])}",
                pattern_data={"typical_hours": typical_hours},
                confidence=0.8,
                occurrences=sum(row.count for row in rows)
            )

        except Exception as e:
            logger.error(f"Error detecting meal pattern: {e}")
            return None

    async def _detect_workout_schedule_pattern(self, user_id: str) -> Optional[DetectedPattern]:
        """Detect typical workout day/time patterns"""
        try:
            query = text("""
                SELECT
                    EXTRACT(DOW FROM logged_at) as dow,
                    EXTRACT(HOUR FROM logged_at) as hour,
                    COUNT(*) as count
                FROM workout_log
                WHERE user_id = :user_id
                AND logged_at > NOW() - INTERVAL '30 days'
                GROUP BY EXTRACT(DOW FROM logged_at), EXTRACT(HOUR FROM logged_at)
                HAVING COUNT(*) >= 2
                ORDER BY count DESC
                LIMIT 1
            """)

            result = self.db.execute(query, {"user_id": user_id})
            row = result.fetchone()

            if not row:
                return None

            day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            typical_day = day_names[int(row.dow)]
            typical_hour = int(row.hour)

            return DetectedPattern(
                user_id=user_id,
                pattern_type="workout_schedule",
                description=f"Typically works out on {typical_day} at {typical_hour}:00",
                pattern_data={"day": int(row.dow), "hour": typical_hour},
                confidence=0.75,
                occurrences=row.count
            )

        except Exception as e:
            logger.error(f"Error detecting workout pattern: {e}")
            return None

    async def _detect_sleep_schedule_pattern(self, user_id: str) -> Optional[DetectedPattern]:
        """Detect sleep schedule patterns"""
        try:
            query = text("""
                SELECT AVG(sleep_hours) as avg_sleep
                FROM daily_recovery_log
                WHERE user_id = :user_id
                AND logged_at > NOW() - INTERVAL '30 days'
            """)

            result = self.db.execute(query, {"user_id": user_id})
            row = result.fetchone()

            if not row or not row.avg_sleep:
                return None

            avg_sleep = round(row.avg_sleep, 1)

            return DetectedPattern(
                user_id=user_id,
                pattern_type="sleep_schedule",
                description=f"Averages {avg_sleep}h of sleep per night",
                pattern_data={"avg_hours": avg_sleep},
                confidence=0.9,
                occurrences=30
            )

        except Exception as e:
            logger.error(f"Error detecting sleep pattern: {e}")
            return None

    async def _suggest_meal(self, user_id: str, pattern: DetectedPattern) -> Optional[ProactiveSuggestion]:
        """Suggest meal based on typical timing"""
        try:
            current_hour = datetime.utcnow().hour
            typical_hours = pattern.pattern_data.get("typical_hours", [])

            # Check if approaching typical meal time (within 30min before)
            for meal_hour in typical_hours:
                if meal_hour - 1 <= current_hour < meal_hour:
                    # Check if already logged a meal recently
                    recent_meal = await self._check_recent_meal(user_id, hours=2)
                    if recent_meal:
                        return None

                    # Check for duplicates
                    if await self._is_duplicate_suggestion(user_id, "meal", hours=self.duplicate_window_hours):
                        return None

                    return ProactiveSuggestion(
                        user_id=user_id,
                        suggestion_type="meal",
                        title=f"Time for {self._get_meal_name(meal_hour)}?",
                        description=f"You usually eat around {meal_hour}:00. Want to log a meal?",
                        action_data={"type": "log_meal", "suggested_time": meal_hour},
                        confidence=0.7,
                        priority=6,
                        expires_at=datetime.utcnow() + timedelta(hours=1)
                    )

            return None

        except Exception as e:
            logger.error(f"Error suggesting meal: {e}")
            return None

    async def _suggest_workout(self, user_id: str, pattern: DetectedPattern) -> Optional[ProactiveSuggestion]:
        """Suggest workout based on typical schedule"""
        try:
            now = datetime.utcnow()
            typical_day = pattern.pattern_data.get("day")
            typical_hour = pattern.pattern_data.get("hour")

            if typical_day is None or typical_hour is None:
                return None

            # Check if today matches typical day and approaching typical hour
            if now.weekday() == typical_day and typical_hour - 1 <= now.hour < typical_hour:
                # Check if already worked out today
                today_workout = await self._check_workout_today(user_id)
                if today_workout:
                    return None

                # Check for duplicates
                if await self._is_duplicate_suggestion(user_id, "workout", hours=self.duplicate_window_hours):
                    return None

                return ProactiveSuggestion(
                    user_id=user_id,
                    suggestion_type="workout",
                    title="Ready for your workout?",
                    description=f"You usually train around {typical_hour}:00. Want to start a session?",
                    action_data={"type": "start_workout"},
                    confidence=0.75,
                    priority=7,
                    expires_at=datetime.utcnow() + timedelta(hours=2)
                )

            return None

        except Exception as e:
            logger.error(f"Error suggesting workout: {e}")
            return None

    async def _suggest_break(self, user_id: str, pattern: DetectedPattern) -> Optional[ProactiveSuggestion]:
        """Suggest break based on productivity patterns"""
        # Placeholder for future implementation
        return None

    async def _check_deficits(self, user_id: str) -> List[ProactiveSuggestion]:
        """Check for nutritional or activity deficits"""
        suggestions = []

        # Check if it's 3pm and haven't eaten much today
        now = datetime.utcnow()
        if now.hour == 15:  # 3pm
            today_meals = await self._get_meals_today(user_id)
            if len(today_meals) < 2:
                # Check for duplicates
                if not await self._is_duplicate_suggestion(user_id, "meal_deficit", hours=self.duplicate_window_hours):
                    suggestions.append(ProactiveSuggestion(
                        user_id=user_id,
                        suggestion_type="meal_deficit",
                        title="Haven't eaten much today",
                        description=f"Only {len(today_meals)} meal(s) logged. Consider a healthy snack.",
                        action_data={"type": "log_meal"},
                        confidence=0.8,
                        priority=8,
                        expires_at=datetime.utcnow() + timedelta(hours=2)
                    ))

        return suggestions

    def _get_meal_name(self, hour: int) -> str:
        """Get meal name based on hour"""
        if 6 <= hour < 11:
            return "breakfast"
        elif 11 <= hour < 15:
            return "lunch"
        elif 15 <= hour < 18:
            return "snack"
        else:
            return "dinner"

    async def _check_recent_meal(self, user_id: str, hours: int = 2) -> bool:
        """Check if user logged a meal recently"""
        try:
            query = text("""
                SELECT COUNT(*) as count
                FROM food_log
                WHERE user_id = :user_id
                AND logged_at > NOW() - INTERVAL ':hours hours'
            """)

            result = self.db.execute(query, {"user_id": user_id, "hours": hours})
            row = result.fetchone()

            return row.count > 0

        except Exception as e:
            logger.error(f"Error checking recent meal: {e}")
            return False

    async def _check_workout_today(self, user_id: str) -> bool:
        """Check if user worked out today"""
        try:
            query = text("""
                SELECT COUNT(*) as count
                FROM workout_log
                WHERE user_id = :user_id
                AND DATE(logged_at) = CURRENT_DATE
            """)

            result = self.db.execute(query, {"user_id": user_id})
            row = result.fetchone()

            return row.count > 0

        except Exception as e:
            logger.error(f"Error checking workout today: {e}")
            return False

    async def _get_meals_today(self, user_id: str) -> List[Dict[str, Any]]:
        """Get meals logged today"""
        try:
            query = text("""
                SELECT id, logged_at
                FROM food_log
                WHERE user_id = :user_id
                AND DATE(logged_at) = CURRENT_DATE
            """)

            result = self.db.execute(query, {"user_id": user_id})

            return [{"id": row.id, "logged_at": row.logged_at} for row in result.fetchall()]

        except Exception as e:
            logger.error(f"Error getting meals today: {e}")
            return []

    async def _is_duplicate_suggestion(
        self,
        user_id: str,
        suggestion_type: str,
        hours: int = 24
    ) -> bool:
        """Check if similar suggestion was made recently"""
        try:
            query = text("""
                SELECT COUNT(*) as count
                FROM proactive_suggestion
                WHERE user_id = :user_id
                AND suggestion_type = :suggestion_type
                AND created_at > NOW() - INTERVAL ':hours hours'
            """)

            result = self.db.execute(query, {
                "user_id": user_id,
                "suggestion_type": suggestion_type,
                "hours": hours
            })
            row = result.fetchone()

            return row.count > 0

        except Exception as e:
            logger.error(f"Error checking duplicate: {e}")
            return False

    async def _save_suggestion(self, suggestion: ProactiveSuggestion) -> int:
        """Save suggestion to database"""
        try:
            query = text("""
                INSERT INTO proactive_suggestion (
                    user_id, suggestion_type, title, description,
                    action_data, confidence, priority, expires_at
                )
                VALUES (
                    :user_id, :suggestion_type, :title, :description,
                    :action_data, :confidence, :priority, :expires_at
                )
                RETURNING id
            """)

            result = self.db.execute(query, {
                "user_id": suggestion.user_id,
                "suggestion_type": suggestion.suggestion_type,
                "title": suggestion.title,
                "description": suggestion.description,
                "action_data": json.dumps(suggestion.action_data),
                "confidence": suggestion.confidence,
                "priority": suggestion.priority,
                "expires_at": suggestion.expires_at
            })

            self.db.commit()

            suggestion_id = result.fetchone()[0]
            suggestion.id = suggestion_id

            logger.info(f"💡 Suggestion created: {suggestion_id} - {suggestion.title}")

            return suggestion_id

        except Exception as e:
            logger.error(f"Error saving suggestion: {e}")
            self.db.rollback()
            raise

    async def _save_pattern(self, pattern: DetectedPattern) -> int:
        """Save or update detected pattern"""
        try:
            # Check if pattern already exists
            check_query = text("""
                SELECT id, occurrences
                FROM detected_pattern
                WHERE user_id = :user_id
                AND pattern_type = :pattern_type
            """)

            result = self.db.execute(check_query, {
                "user_id": pattern.user_id,
                "pattern_type": pattern.pattern_type
            })
            existing = result.fetchone()

            if existing:
                # Update existing pattern
                update_query = text("""
                    UPDATE detected_pattern
                    SET
                        description = :description,
                        pattern_data = :pattern_data,
                        confidence = :confidence,
                        occurrences = :occurrences,
                        last_detected = NOW()
                    WHERE id = :id
                """)

                self.db.execute(update_query, {
                    "id": existing.id,
                    "description": pattern.description,
                    "pattern_data": json.dumps(pattern.pattern_data),
                    "confidence": pattern.confidence,
                    "occurrences": existing.occurrences + pattern.occurrences
                })

                self.db.commit()

                return existing.id

            else:
                # Insert new pattern
                insert_query = text("""
                    INSERT INTO detected_pattern (
                        user_id, pattern_type, description,
                        pattern_data, confidence, occurrences
                    )
                    VALUES (
                        :user_id, :pattern_type, :description,
                        :pattern_data, :confidence, :occurrences
                    )
                    RETURNING id
                """)

                result = self.db.execute(insert_query, {
                    "user_id": pattern.user_id,
                    "pattern_type": pattern.pattern_type,
                    "description": pattern.description,
                    "pattern_data": json.dumps(pattern.pattern_data),
                    "confidence": pattern.confidence,
                    "occurrences": pattern.occurrences
                })

                self.db.commit()

                pattern_id = result.fetchone()[0]

                logger.info(f"📊 Pattern detected: {pattern_id} - {pattern.description}")

                return pattern_id

        except Exception as e:
            logger.error(f"Error saving pattern: {e}")
            self.db.rollback()
            raise

    async def accept_suggestion(self, suggestion_id: int, user_id: str) -> bool:
        """Mark suggestion as accepted"""
        try:
            query = text("""
                UPDATE proactive_suggestion
                SET status = 'accepted', accepted_at = NOW()
                WHERE id = :suggestion_id AND user_id = :user_id
            """)

            self.db.execute(query, {"suggestion_id": suggestion_id, "user_id": user_id})
            self.db.commit()

            logger.info(f"✅ Suggestion accepted: {suggestion_id}")

            return True

        except Exception as e:
            logger.error(f"Error accepting suggestion: {e}")
            self.db.rollback()
            return False

    async def dismiss_suggestion(self, suggestion_id: int, user_id: str) -> bool:
        """Mark suggestion as dismissed"""
        try:
            query = text("""
                UPDATE proactive_suggestion
                SET status = 'dismissed', dismissed_at = NOW()
                WHERE id = :suggestion_id AND user_id = :user_id
            """)

            self.db.execute(query, {"suggestion_id": suggestion_id, "user_id": user_id})
            self.db.commit()

            logger.info(f"❌ Suggestion dismissed: {suggestion_id}")

            return True

        except Exception as e:
            logger.error(f"Error dismissing suggestion: {e}")
            self.db.rollback()
            return False

    async def get_active_suggestions(self, user_id: str) -> List[ProactiveSuggestion]:
        """Get active suggestions for user"""
        try:
            query = text("""
                SELECT
                    id, user_id, suggestion_type, title, description,
                    action_data, confidence, priority, status,
                    expires_at, accepted_at, dismissed_at, created_at
                FROM proactive_suggestion
                WHERE user_id = :user_id
                AND status = 'pending'
                AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY priority DESC, created_at DESC
            """)

            result = self.db.execute(query, {"user_id": user_id})

            suggestions = []
            for row in result.fetchall():
                suggestions.append(ProactiveSuggestion(
                    id=row.id,
                    user_id=row.user_id,
                    suggestion_type=row.suggestion_type,
                    title=row.title,
                    description=row.description,
                    action_data=json.loads(row.action_data) if isinstance(row.action_data, str) else row.action_data,
                    confidence=row.confidence,
                    priority=row.priority,
                    status=row.status,
                    expires_at=row.expires_at,
                    accepted_at=row.accepted_at,
                    dismissed_at=row.dismissed_at,
                    created_at=row.created_at
                ))

            return suggestions

        except Exception as e:
            logger.error(f"Error getting active suggestions: {e}")
            return []


def get_proactive_intelligence(db: Session, event_bus=None) -> ProactiveIntelligenceEngine:
    """Get proactive intelligence engine instance"""
    return ProactiveIntelligenceEngine(db, event_bus)
