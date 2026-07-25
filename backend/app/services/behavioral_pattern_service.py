"""
Behavioral Pattern Service for Sara's Proactive Autonomy.

Manages the lifecycle of behavioral patterns:
- Creating patterns from observed behaviors
- Evaluating trigger conditions
- Updating pattern confidence based on evidence
- Managing pattern lifecycle (learning → active → confirmed/dormant)
"""

import logging
import json
from datetime import datetime, date, time, timedelta
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


class TriggerType(str, Enum):
    """Types of triggers that can activate a pattern."""
    WEATHER = "weather"
    TIME = "time"
    DAY_OF_WEEK = "day_of_week"
    AFTER_EVENT = "after_event"
    LOCATION = "location"
    COMPOSITE = "composite"


class ActionType(str, Enum):
    """Types of actions a pattern can suggest."""
    AUTOMATION = "automation"
    REMINDER = "reminder"
    SUGGESTION = "suggestion"
    QUESTION = "question"


class PatternStatus(str, Enum):
    """Lifecycle status of a pattern."""
    LEARNING = "learning"      # Not enough evidence yet
    ACTIVE = "active"          # Ready to suggest when triggered
    SUGGESTED = "suggested"    # Currently waiting for user response
    CONFIRMED = "confirmed"    # User accepted, pattern validated
    REJECTED = "rejected"      # User rejected this time
    DORMANT = "dormant"        # User rejected multiple times, stop suggesting


class PatternCategory(str, Enum):
    """Categories for organizing patterns."""
    HOME = "home"
    FITNESS = "fitness"
    WORK = "work"
    HEALTH = "health"
    COMMUNICATION = "communication"
    SCHEDULE = "schedule"
    NUTRITION = "nutrition"
    ENTERTAINMENT = "entertainment"
    OTHER = "other"


@dataclass
class BehavioralPattern:
    """Represents a behavioral pattern."""
    id: str
    user_id: str
    trigger_type: TriggerType
    trigger_conditions: Dict[str, Any]
    action_type: ActionType
    action_payload: Dict[str, Any]
    description: str
    source_context: str
    category: PatternCategory
    evidence_dates: List[date]
    evidence_count: int
    confidence: float
    min_occurrences: int
    status: PatternStatus
    times_suggested: int
    times_accepted: int
    times_rejected: int
    last_triggered_at: Optional[datetime]
    last_suggested_at: Optional[datetime]
    suggestion_window_start: time
    suggestion_window_end: time
    cooldown_hours: int
    created_at: datetime
    updated_at: datetime


@dataclass
class TriggerContext:
    """Context for evaluating triggers."""
    current_temp_f: Optional[float] = None
    current_humidity: Optional[int] = None
    weather_description: Optional[str] = None
    current_time: Optional[time] = None
    current_day: Optional[str] = None  # Mon, Tue, etc.
    current_date: Optional[date] = None
    recent_events: Optional[List[str]] = None
    location: Optional[str] = None


class BehavioralPatternService:
    """
    Service for managing behavioral patterns.

    Handles pattern creation, evaluation, and lifecycle management.
    """

    # Confidence thresholds
    CONFIDENCE_ACTIVE_THRESHOLD = 0.6  # Confidence needed to become active
    CONFIDENCE_INCREMENT = 0.15  # How much confidence increases per observation
    CONFIDENCE_DECAY = 0.02  # Daily decay if pattern not observed

    # Rejection thresholds. SARA_PROACTIVENESS_AUDIT_AND_PLAN_2026_07_25 §7.2/
    # IMPLEMENTATION_PLAN P4 home patterns: "propose once ... use rejection or
    # Never to block recurrence; never escalate an ignored proposal." Was 3 —
    # meaning David had to reject the SAME home-automation proposal three
    # separate times (each re-suggested after only a 24h cooldown, per
    # `cooldown_hours` default) before it stopped. One explicit "no" is a
    # decision, not the start of a negotiation.
    MAX_REJECTIONS_BEFORE_DORMANT = 1

    async def create_pattern(
        self,
        db: Session,
        user_id: str,
        trigger_type: TriggerType,
        trigger_conditions: Dict[str, Any],
        action_type: ActionType,
        action_payload: Dict[str, Any],
        description: str,
        source_context: str,
        category: PatternCategory = PatternCategory.OTHER,
        initial_evidence_date: Optional[date] = None
    ) -> str:
        """
        Create a new behavioral pattern.

        Returns the pattern ID.
        """
        pattern_id = str(uuid.uuid4())
        evidence_dates = [initial_evidence_date] if initial_evidence_date else []
        evidence_count = 1 if initial_evidence_date else 0
        initial_confidence = self.CONFIDENCE_INCREMENT if initial_evidence_date else 0.0

        try:
            db.execute(
                text("""
                    INSERT INTO behavioral_pattern (
                        id, user_id, trigger_type, trigger_conditions,
                        action_type, action_payload, description, source_context,
                        category, evidence_dates, evidence_count, confidence,
                        status, created_at, updated_at
                    ) VALUES (
                        :id, :user_id, :trigger_type, :trigger_conditions,
                        :action_type, :action_payload, :description, :source_context,
                        :category, :evidence_dates, :evidence_count, :confidence,
                        'learning', NOW(), NOW()
                    )
                """),
                {
                    "id": pattern_id,
                    "user_id": user_id,
                    "trigger_type": trigger_type.value,
                    "trigger_conditions": json.dumps(trigger_conditions),
                    "action_type": action_type.value,
                    "action_payload": json.dumps(action_payload),
                    "description": description,
                    "source_context": source_context,
                    "category": category.value,
                    "evidence_dates": evidence_dates,
                    "evidence_count": evidence_count,
                    "confidence": initial_confidence
                }
            )
            db.commit()

            logger.info(f"Created behavioral pattern: {description} (id={pattern_id})")
            return pattern_id

        except Exception as e:
            logger.error(f"Failed to create pattern: {e}")
            db.rollback()
            raise

    async def add_evidence(
        self,
        db: Session,
        pattern_id: str,
        evidence_date: date,
        context: Optional[str] = None
    ) -> None:
        """
        Add evidence for an existing pattern, increasing confidence.
        """
        try:
            # Get current pattern state
            result = db.execute(
                text("""
                    SELECT evidence_dates, evidence_count, confidence, status, min_occurrences
                    FROM behavioral_pattern
                    WHERE id = :pattern_id
                """),
                {"pattern_id": pattern_id}
            ).fetchone()

            if not result:
                logger.warning(f"Pattern {pattern_id} not found")
                return

            current_dates = result.evidence_dates or []
            current_count = result.evidence_count or 0
            current_confidence = result.confidence or 0.0
            current_status = result.status
            min_occurrences = result.min_occurrences or 2

            # Add evidence date if not already present
            if evidence_date not in current_dates:
                current_dates.append(evidence_date)
                current_count += 1
                current_confidence = min(1.0, current_confidence + self.CONFIDENCE_INCREMENT)

            # Check if pattern should become active
            new_status = current_status
            if (current_status == PatternStatus.LEARNING.value and
                current_count >= min_occurrences and
                current_confidence >= self.CONFIDENCE_ACTIVE_THRESHOLD):
                new_status = PatternStatus.ACTIVE.value
                logger.info(f"Pattern {pattern_id} graduated to ACTIVE status")

            # Update pattern
            db.execute(
                text("""
                    UPDATE behavioral_pattern
                    SET evidence_dates = :evidence_dates,
                        evidence_count = :evidence_count,
                        confidence = :confidence,
                        status = :status,
                        source_context = CASE
                            WHEN CAST(:context AS TEXT) IS NOT NULL
                            THEN source_context || E'\n' || CAST(:context AS TEXT)
                            ELSE source_context
                        END,
                        updated_at = NOW()
                    WHERE id = :pattern_id
                """),
                {
                    "pattern_id": pattern_id,
                    "evidence_dates": current_dates,
                    "evidence_count": current_count,
                    "confidence": current_confidence,
                    "status": new_status,
                    "context": context
                }
            )
            db.commit()

            logger.debug(f"Added evidence to pattern {pattern_id}: count={current_count}, confidence={current_confidence:.2f}")

        except Exception as e:
            logger.error(f"Failed to add evidence: {e}")
            db.rollback()

    async def get_active_patterns(
        self,
        db: Session,
        user_id: str,
        category: Optional[PatternCategory] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all active patterns for a user.
        """
        try:
            query = """
                SELECT * FROM behavioral_pattern
                WHERE user_id = :user_id
                  AND status IN ('active', 'confirmed')
            """
            params = {"user_id": user_id}

            if category:
                query += " AND category = :category"
                params["category"] = category.value

            query += " ORDER BY confidence DESC"

            result = db.execute(text(query), params).fetchall()

            patterns = []
            for row in result:
                patterns.append({
                    "id": row.id,
                    "trigger_type": row.trigger_type,
                    "trigger_conditions": row.trigger_conditions,
                    "action_type": row.action_type,
                    "action_payload": row.action_payload,
                    "description": row.description,
                    "category": row.category,
                    "confidence": row.confidence,
                    "status": row.status,
                    "times_accepted": row.times_accepted,
                    "times_rejected": row.times_rejected,
                    "suggestion_window_start": row.suggestion_window_start,
                    "suggestion_window_end": row.suggestion_window_end,
                    "cooldown_hours": row.cooldown_hours,
                    "last_suggested_at": row.last_suggested_at
                })

            return patterns

        except Exception as e:
            logger.error(f"Failed to get active patterns: {e}")
            return []

    async def evaluate_trigger(
        self,
        pattern: Dict[str, Any],
        context: TriggerContext
    ) -> Tuple[bool, str]:
        """
        Evaluate if a pattern's trigger conditions are met.

        Returns (triggered: bool, reason: str)
        """
        trigger_type = pattern["trigger_type"]
        conditions = pattern["trigger_conditions"]

        if isinstance(conditions, str):
            conditions = json.loads(conditions)

        if trigger_type == TriggerType.WEATHER.value:
            return self._evaluate_weather_trigger(conditions, context)
        elif trigger_type == TriggerType.TIME.value:
            return self._evaluate_time_trigger(conditions, context)
        elif trigger_type == TriggerType.DAY_OF_WEEK.value:
            return self._evaluate_day_trigger(conditions, context)
        elif trigger_type == TriggerType.AFTER_EVENT.value:
            return self._evaluate_event_trigger(conditions, context)
        elif trigger_type == TriggerType.COMPOSITE.value:
            return self._evaluate_composite_trigger(conditions, context)
        else:
            return False, f"Unknown trigger type: {trigger_type}"

    def _evaluate_weather_trigger(
        self,
        conditions: Dict[str, Any],
        context: TriggerContext
    ) -> Tuple[bool, str]:
        """Evaluate weather-based trigger."""
        if context.current_temp_f is None:
            return False, "No weather data available"

        # Check temperature conditions
        if "temp_below_f" in conditions:
            if context.current_temp_f < conditions["temp_below_f"]:
                return True, f"Temperature {context.current_temp_f}°F is below {conditions['temp_below_f']}°F"

        if "temp_above_f" in conditions:
            if context.current_temp_f > conditions["temp_above_f"]:
                return True, f"Temperature {context.current_temp_f}°F is above {conditions['temp_above_f']}°F"

        # Check humidity
        if "humidity_above" in conditions and context.current_humidity:
            if context.current_humidity > conditions["humidity_above"]:
                return True, f"Humidity {context.current_humidity}% is above {conditions['humidity_above']}%"

        return False, "Weather conditions not met"

    def _evaluate_time_trigger(
        self,
        conditions: Dict[str, Any],
        context: TriggerContext
    ) -> Tuple[bool, str]:
        """Evaluate time-based trigger."""
        if context.current_time is None:
            return False, "No time data available"

        # Check if current time is within range
        if "time" in conditions:
            target_time = datetime.strptime(conditions["time"], "%H:%M").time()
            # Allow 30-minute window around target time
            time_diff = abs(
                (context.current_time.hour * 60 + context.current_time.minute) -
                (target_time.hour * 60 + target_time.minute)
            )
            if time_diff <= 30:
                return True, f"Current time is near {conditions['time']}"

        if "after" in conditions and "before" in conditions:
            after_time = datetime.strptime(conditions["after"], "%H:%M").time()
            before_time = datetime.strptime(conditions["before"], "%H:%M").time()
            if after_time <= context.current_time <= before_time:
                return True, f"Current time is between {conditions['after']} and {conditions['before']}"

        return False, "Time conditions not met"

    def _evaluate_day_trigger(
        self,
        conditions: Dict[str, Any],
        context: TriggerContext
    ) -> Tuple[bool, str]:
        """Evaluate day-of-week trigger."""
        if context.current_day is None:
            return False, "No day data available"

        if "days" in conditions:
            if context.current_day in conditions["days"]:
                return True, f"Today is {context.current_day}"

        return False, "Day conditions not met"

    def _evaluate_event_trigger(
        self,
        conditions: Dict[str, Any],
        context: TriggerContext
    ) -> Tuple[bool, str]:
        """Evaluate after-event trigger."""
        if not context.recent_events:
            return False, "No recent events"

        if "event_type" in conditions:
            if conditions["event_type"] in context.recent_events:
                return True, f"Event '{conditions['event_type']}' occurred recently"

        return False, "Event conditions not met"

    def _evaluate_composite_trigger(
        self,
        conditions: Dict[str, Any],
        context: TriggerContext
    ) -> Tuple[bool, str]:
        """Evaluate composite trigger with multiple conditions."""
        if "all" in conditions:
            # All conditions must be met
            reasons = []
            for sub_condition in conditions["all"]:
                sub_type = sub_condition.get("type", "")
                if sub_type == "weather":
                    met, reason = self._evaluate_weather_trigger(sub_condition, context)
                elif sub_type == "time":
                    met, reason = self._evaluate_time_trigger(sub_condition, context)
                elif sub_type == "day":
                    met, reason = self._evaluate_day_trigger(sub_condition, context)
                else:
                    met, reason = False, f"Unknown sub-condition type: {sub_type}"

                if not met:
                    return False, reason
                reasons.append(reason)

            return True, " AND ".join(reasons)

        if "any" in conditions:
            # Any condition can be met
            for sub_condition in conditions["any"]:
                sub_type = sub_condition.get("type", "")
                if sub_type == "weather":
                    met, reason = self._evaluate_weather_trigger(sub_condition, context)
                elif sub_type == "time":
                    met, reason = self._evaluate_time_trigger(sub_condition, context)
                elif sub_type == "day":
                    met, reason = self._evaluate_day_trigger(sub_condition, context)
                else:
                    continue

                if met:
                    return True, reason

            return False, "No conditions in 'any' were met"

        return False, "Invalid composite condition structure"

    async def can_suggest_pattern(
        self,
        db: Session,
        pattern: Dict[str, Any],
        current_time: datetime
    ) -> Tuple[bool, str]:
        """
        Check if a pattern can be suggested right now.

        Considers:
        - Suggestion window (time of day)
        - Cooldown period
        - Pattern status
        """
        # Check status
        status = pattern.get("status")
        if status not in (PatternStatus.ACTIVE.value, PatternStatus.CONFIRMED.value):
            return False, f"Pattern status is {status}"

        # Check suggestion window
        window_start = pattern.get("suggestion_window_start")
        window_end = pattern.get("suggestion_window_end")

        if window_start and window_end:
            current_time_only = current_time.time()
            if not (window_start <= current_time_only <= window_end):
                return False, f"Outside suggestion window ({window_start} - {window_end})"

        # Check cooldown
        last_suggested = pattern.get("last_suggested_at")
        cooldown_hours = pattern.get("cooldown_hours", 24)

        if last_suggested:
            if isinstance(last_suggested, str):
                last_suggested = datetime.fromisoformat(last_suggested)

            # last_suggested_at is a naive (DB `timestamp`) value; current_time is
            # aware ET (local_now()). Comparing them raises "can't compare
            # offset-naive and offset-aware datetimes" — normalize both to naive
            # UTC. (Latent until belief_promotion started setting last_suggested_at.)
            from app.core.timezone import to_naive_utc
            ls = to_naive_utc(last_suggested)
            ct = to_naive_utc(current_time)
            cooldown_end = ls + timedelta(hours=cooldown_hours)
            if ct < cooldown_end:
                return False, f"In cooldown until {cooldown_end}"

        return True, "Can suggest"

    async def record_suggestion(
        self,
        db: Session,
        pattern_id: str,
        trigger_context: Dict[str, Any],
        message_sent: str
    ) -> str:
        """
        Record that a pattern suggestion was sent.

        Returns the suggestion log ID.
        """
        try:
            log_id = str(uuid.uuid4())

            # Get user_id from pattern
            result = db.execute(
                text("SELECT user_id FROM behavioral_pattern WHERE id = :pattern_id"),
                {"pattern_id": pattern_id}
            ).fetchone()

            if not result:
                raise ValueError(f"Pattern {pattern_id} not found")

            user_id = result.user_id

            # Insert suggestion log
            db.execute(
                text("""
                    INSERT INTO pattern_suggestion_log (
                        id, pattern_id, user_id, trigger_context, message_sent,
                        suggested_at, expires_at
                    ) VALUES (
                        :id, :pattern_id, :user_id, :trigger_context, :message_sent,
                        NOW(), NOW() + INTERVAL '4 hours'
                    )
                """),
                {
                    "id": log_id,
                    "pattern_id": pattern_id,
                    "user_id": user_id,
                    "trigger_context": json.dumps(trigger_context),
                    "message_sent": message_sent
                }
            )

            # Update pattern
            db.execute(
                text("""
                    UPDATE behavioral_pattern
                    SET times_suggested = times_suggested + 1,
                        last_suggested_at = NOW(),
                        status = 'suggested',
                        updated_at = NOW()
                    WHERE id = :pattern_id
                """),
                {"pattern_id": pattern_id}
            )

            db.commit()
            logger.info(f"Recorded suggestion for pattern {pattern_id}")

            return log_id

        except Exception as e:
            logger.error(f"Failed to record suggestion: {e}")
            db.rollback()
            raise

    async def record_response(
        self,
        db: Session,
        pattern_id: str,
        accepted: bool,
        user_response: Optional[str] = None
    ) -> None:
        """
        Record user's response to a pattern suggestion.
        """
        try:
            outcome = "accepted" if accepted else "rejected"

            # Update suggestion log. Postgres UPDATE doesn't support ORDER BY/LIMIT
            # directly — target the latest unresolved row via a subquery instead.
            db.execute(
                text("""
                    UPDATE pattern_suggestion_log
                    SET outcome = :outcome,
                        user_response = :user_response,
                        responded_at = NOW(),
                        action_taken = :action_taken
                    WHERE id = (
                        SELECT id FROM pattern_suggestion_log
                        WHERE pattern_id = :pattern_id AND outcome IS NULL
                        ORDER BY suggested_at DESC
                        LIMIT 1
                    )
                """),
                {
                    "pattern_id": pattern_id,
                    "outcome": outcome,
                    "user_response": user_response,
                    "action_taken": accepted
                }
            )

            # Update pattern
            if accepted:
                db.execute(
                    text("""
                        UPDATE behavioral_pattern
                        SET times_accepted = times_accepted + 1,
                            last_accepted_at = NOW(),
                            status = 'confirmed',
                            confidence = LEAST(1.0, confidence + 0.1),
                            updated_at = NOW()
                        WHERE id = :pattern_id
                    """),
                    {"pattern_id": pattern_id}
                )
            else:
                # Check if should go dormant
                result = db.execute(
                    text("SELECT times_rejected FROM behavioral_pattern WHERE id = :pattern_id"),
                    {"pattern_id": pattern_id}
                ).fetchone()

                new_rejections = (result.times_rejected or 0) + 1
                new_status = "dormant" if new_rejections >= self.MAX_REJECTIONS_BEFORE_DORMANT else "active"

                db.execute(
                    text("""
                        UPDATE behavioral_pattern
                        SET times_rejected = :rejections,
                            status = :status,
                            confidence = GREATEST(0.0, confidence - 0.15),
                            user_feedback = :feedback,
                            updated_at = NOW()
                        WHERE id = :pattern_id
                    """),
                    {
                        "pattern_id": pattern_id,
                        "rejections": new_rejections,
                        "status": new_status,
                        "feedback": user_response
                    }
                )

                if new_status == "dormant":
                    logger.info(f"Pattern {pattern_id} moved to dormant after {new_rejections} rejections")

            db.commit()
            logger.info(f"Recorded {outcome} response for pattern {pattern_id}")

        except Exception as e:
            logger.error(f"Failed to record response: {e}")
            db.rollback()

    async def find_similar_pattern(
        self,
        db: Session,
        user_id: str,
        trigger_type: TriggerType,
        trigger_conditions: Dict[str, Any],
        action_type: ActionType
    ) -> Optional[str]:
        """
        Find an existing pattern similar to the given criteria.

        Returns pattern ID if found, None otherwise.
        """
        try:
            result = db.execute(
                text("""
                    SELECT id, trigger_conditions
                    FROM behavioral_pattern
                    WHERE user_id = :user_id
                      AND trigger_type = :trigger_type
                      AND action_type = :action_type
                      AND status != 'dormant'
                """),
                {
                    "user_id": user_id,
                    "trigger_type": trigger_type.value,
                    "action_type": action_type.value
                }
            ).fetchall()

            for row in result:
                existing_conditions = row.trigger_conditions
                if isinstance(existing_conditions, str):
                    existing_conditions = json.loads(existing_conditions)

                # Simple similarity check - could be made more sophisticated
                if self._conditions_similar(trigger_conditions, existing_conditions):
                    return row.id

            return None

        except Exception as e:
            logger.error(f"Failed to find similar pattern: {e}")
            return None

    def _conditions_similar(self, cond1: Dict, cond2: Dict) -> bool:
        """Check if two trigger conditions are similar enough to be the same pattern."""
        # Entity-scoped patterns (home routines) are only the same pattern if
        # they concern the same entity — otherwise every light active at the
        # same hour collapses into one pattern.
        if cond1.get("entity_id") != cond2.get("entity_id"):
            return False

        # A light turning ON and the same light turning OFF are different
        # patterns even at the same entity/hour — never merge across direction.
        if cond1.get("to_state") != cond2.get("to_state"):
            return False

        # For weather triggers, check if thresholds are close
        if "temp_below_f" in cond1 and "temp_below_f" in cond2:
            if abs(cond1["temp_below_f"] - cond2["temp_below_f"]) <= 10:
                return True

        if "temp_above_f" in cond1 and "temp_above_f" in cond2:
            if abs(cond1["temp_above_f"] - cond2["temp_above_f"]) <= 10:
                return True

        # For time triggers, check if times are close
        if "time" in cond1 and "time" in cond2:
            t1 = datetime.strptime(cond1["time"], "%H:%M")
            t2 = datetime.strptime(cond2["time"], "%H:%M")
            if abs((t1 - t2).total_seconds()) <= 3600:  # Within 1 hour
                return True

        # For day triggers, check overlap
        if "days" in cond1 and "days" in cond2:
            overlap = set(cond1["days"]) & set(cond2["days"])
            if len(overlap) >= len(cond1["days"]) * 0.5:
                return True

        return False


# Singleton instance
behavioral_pattern_service = BehavioralPatternService()
