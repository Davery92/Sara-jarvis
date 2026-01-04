"""
Body State Calibration Service

Implements feedback loop for personalizing body state estimation.
When Sara mentions body state and user responds, we learn from the feedback.

Flow:
1. Sara's response mentions body state (e.g., "you're running on empty")
2. Store the pending calibration context
3. User's next message is analyzed for confirmation/correction
4. Coefficients are updated based on feedback
"""

import logging
import re
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.timezone import USER_TIMEZONE

logger = logging.getLogger(__name__)

USER_TZ = USER_TIMEZONE


@dataclass
class PendingCalibration:
    """Context for a body state mention awaiting user feedback."""
    user_id: str
    estimate_type: str  # 'blood_sugar', 'alertness', 'stress', 'recovery'
    estimated_value: float
    estimated_label: str  # 'low', 'running_on_empty', 'tired', etc.
    context: Dict  # hours_since_meal, hours_since_sleep, etc.
    mentioned_at: datetime
    sara_message: str


# Patterns for detecting body state mentions in Sara's responses
BODY_STATE_PATTERNS = {
    'blood_sugar': [
        (r'running on empty', 'low', 0.1),
        (r'blood sugar.{0,20}(low|dropping|falling)', 'low', 0.2),
        (r'haven\'t eaten', 'low', 0.3),
        (r'fuel(ing|ed)? up', 'low', 0.3),
        (r'time (for|to eat)', 'moderate', 0.4),
        (r'energy.{0,15}(dip|crash|low)', 'low', 0.2),
    ],
    'alertness': [
        (r'(seem|look|sound).{0,10}tired', 'low', 0.3),
        (r'running on.{0,10}(fumes|low sleep)', 'low', 0.2),
        (r'sleep.{0,15}(deficit|debt|deprived)', 'low', 0.3),
        (r'energy.{0,10}(low|flagging)', 'low', 0.3),
        (r'(afternoon|post-lunch).{0,10}(slump|dip)', 'moderate', 0.5),
    ],
    'stress': [
        (r'(seem|sound).{0,10}stressed', 'high', 0.7),
        (r'lot on your plate', 'high', 0.6),
        (r'tough (stretch|day|time)', 'high', 0.6),
        (r'overwhelm', 'high', 0.7),
    ],
    'recovery': [
        (r'muscles.{0,15}(sore|recovering)', 'recovering', 0.5),
        (r'rest day', 'needs_rest', 0.4),
        (r'recovery.{0,10}(time|day)', 'recovering', 0.5),
    ]
}

# Patterns for detecting user confirmation/correction
CONFIRMATION_PATTERNS = [
    (r'^(yeah|yes|yep|exactly|right|correct|true|spot on|accurate)', 'confirmation'),
    (r'you\'re right', 'confirmation'),
    (r'good (call|point)', 'confirmation'),
    (r'that\'s (right|true|accurate)', 'confirmation'),
    (r'(definitely|absolutely|totally)', 'confirmation'),
    (r'(grabbing|getting|about to).{0,20}(food|lunch|dinner|breakfast|snack|eat)', 'confirmation'),
    (r'need(ed)? (to eat|food|a break)', 'confirmation'),
]

CORRECTION_PATTERNS = [
    # User ate but forgot to log
    (r'(already|just) (ate|eaten|had)', 'correction', 'blood_sugar', 'higher', 0.5),
    (r'forgot to log', 'correction', 'blood_sugar', 'higher', 0.4),
    (r'ate.{0,20}(ago|earlier)', 'correction', 'blood_sugar', 'higher', 0.4),

    # User feels fine despite estimate
    (r'(actually |feeling |I\'m )?(fine|good|great|okay|energized)', 'correction', None, 'higher', 0.3),
    (r'not (that )?(tired|hungry|stressed)', 'correction', None, 'higher', 0.3),
    (r'don\'t (need|feel)', 'correction', None, 'higher', 0.2),

    # User feels worse than estimate
    (r'(more|really|very|so) (tired|exhausted|hungry|stressed)', 'correction', None, 'lower', 0.3),
    (r'(worse|rougher) than', 'correction', None, 'lower', 0.3),
    (r'(didn\'t|couldn\'t) sleep', 'correction', 'alertness', 'lower', 0.4),
]


class BodyStateCalibrationService:
    """
    Service for learning personal body state coefficients from user feedback.
    """

    def __init__(self):
        # In-memory cache of pending calibrations (user_id -> PendingCalibration)
        # These expire after 5 minutes if no response
        self._pending: Dict[str, PendingCalibration] = {}

        # Learning rate for coefficient updates
        self.learning_rate = 0.1  # Conservative - takes ~10 consistent signals to shift significantly

    def detect_body_state_mention(
        self,
        sara_response: str,
        user_id: str,
        current_body_state: Optional[Dict] = None
    ) -> Optional[PendingCalibration]:
        """
        Detect if Sara's response mentions body state.
        If so, create a pending calibration awaiting user feedback.
        """
        response_lower = sara_response.lower()

        for estimate_type, patterns in BODY_STATE_PATTERNS.items():
            for pattern, label, default_value in patterns:
                if re.search(pattern, response_lower):
                    # Get actual estimated value if available
                    estimated_value = default_value
                    if current_body_state:
                        if estimate_type == 'blood_sugar':
                            estimated_value = current_body_state.get('blood_sugar', default_value)
                        elif estimate_type == 'alertness':
                            estimated_value = current_body_state.get('alertness', default_value)
                        elif estimate_type == 'stress':
                            estimated_value = current_body_state.get('stress_proxy', default_value)

                    pending = PendingCalibration(
                        user_id=user_id,
                        estimate_type=estimate_type,
                        estimated_value=estimated_value,
                        estimated_label=label,
                        context={
                            'hours_since_meal': current_body_state.get('hours_since_meal') if current_body_state else None,
                            'hours_awake': current_body_state.get('hours_awake') if current_body_state else None,
                            'time_of_day': datetime.now(USER_TZ).hour + datetime.now(USER_TZ).minute / 60.0
                        },
                        mentioned_at=datetime.now(USER_TZ),
                        sara_message=sara_response[:500]
                    )

                    self._pending[user_id] = pending
                    logger.info(f"📊 Body state mention detected: {estimate_type}={label} for user {user_id[:8]}")
                    return pending

        return None

    def analyze_user_response(
        self,
        user_message: str,
        user_id: str,
        db: Session
    ) -> Optional[Dict]:
        """
        Analyze user's response for confirmation/correction of a pending calibration.
        Returns calibration result if applicable.
        """
        # Check for pending calibration
        pending = self._pending.get(user_id)
        if not pending:
            return None

        # Check if pending calibration is still valid (within 5 minutes)
        if datetime.now(USER_TZ) - pending.mentioned_at > timedelta(minutes=5):
            del self._pending[user_id]
            return None

        message_lower = user_message.lower()

        # Check for confirmation
        for pattern, feedback_type in CONFIRMATION_PATTERNS:
            if re.search(pattern, message_lower):
                result = self._process_feedback(
                    db, pending,
                    feedback_type='confirmation',
                    user_response=user_message,
                    direction='accurate',
                    magnitude=0.0
                )
                del self._pending[user_id]
                return result

        # Check for correction
        for pattern, feedback_type, affects_type, direction, magnitude in CORRECTION_PATTERNS:
            if re.search(pattern, message_lower):
                # If affects_type is None, use the pending estimate type
                actual_type = affects_type or pending.estimate_type

                result = self._process_feedback(
                    db, pending,
                    feedback_type='correction',
                    user_response=user_message,
                    direction=direction,
                    magnitude=magnitude
                )
                del self._pending[user_id]
                return result

        # No clear signal - keep pending for a bit longer or clear it
        # If the message is unrelated, clear the pending
        if len(user_message) > 50:  # Longer messages are probably new topics
            del self._pending[user_id]

        return None

    def _process_feedback(
        self,
        db: Session,
        pending: PendingCalibration,
        feedback_type: str,
        user_response: str,
        direction: str,
        magnitude: float
    ) -> Dict:
        """
        Process feedback and update coefficients.
        """
        user_id = pending.user_id

        # Determine which coefficient to adjust
        coefficient_map = {
            'blood_sugar': 'blood_sugar_decay_rate',
            'alertness': 'sleep_debt_sensitivity',
            'stress': 'stress_tolerance',
            'recovery': 'recovery_rate_multiplier'
        }

        affected_coefficient = coefficient_map.get(pending.estimate_type)
        coefficient_adjustment = 0.0

        if feedback_type == 'correction' and affected_coefficient:
            # Calculate adjustment
            # If user says they feel better than estimated, reduce sensitivity
            # If user says they feel worse than estimated, increase sensitivity
            if direction == 'higher':
                # Model overestimated the problem - reduce sensitivity
                coefficient_adjustment = -self.learning_rate * magnitude
            elif direction == 'lower':
                # Model underestimated the problem - increase sensitivity
                coefficient_adjustment = self.learning_rate * magnitude

            # Apply coefficient update
            self._update_coefficient(db, user_id, affected_coefficient, coefficient_adjustment)

        # Log the calibration event
        self._log_calibration_event(
            db, pending, feedback_type, user_response,
            direction, magnitude, affected_coefficient, coefficient_adjustment
        )

        result = {
            'user_id': user_id,
            'estimate_type': pending.estimate_type,
            'feedback_type': feedback_type,
            'direction': direction,
            'coefficient_adjusted': affected_coefficient,
            'adjustment': coefficient_adjustment
        }

        logger.info(f"📈 Calibration processed: {pending.estimate_type} {feedback_type} "
                   f"({direction}) -> {affected_coefficient} {coefficient_adjustment:+.3f}")

        return result

    def _update_coefficient(
        self,
        db: Session,
        user_id: str,
        coefficient_name: str,
        adjustment: float
    ):
        """Update a user's personal coefficient."""
        # Ensure user has a coefficients row
        existing = db.execute(text(
            "SELECT id FROM body_state_coefficients WHERE user_id = :user_id"
        ), {"user_id": user_id}).fetchone()

        if not existing:
            db.execute(text("""
                INSERT INTO body_state_coefficients (id, user_id)
                VALUES (gen_random_uuid()::text, :user_id)
            """), {"user_id": user_id})

        # Update the specific coefficient with bounds
        # Coefficients are multipliers, so keep them between 0.5 and 2.0
        db.execute(text(f"""
            UPDATE body_state_coefficients
            SET {coefficient_name} = GREATEST(0.5, LEAST(2.0, {coefficient_name} + :adjustment)),
                calibration_count = calibration_count + 1,
                last_calibrated_at = NOW(),
                updated_at = NOW()
            WHERE user_id = :user_id
        """), {"user_id": user_id, "adjustment": adjustment})

        db.commit()

    def _log_calibration_event(
        self,
        db: Session,
        pending: PendingCalibration,
        feedback_type: str,
        user_response: str,
        direction: str,
        magnitude: float,
        affected_coefficient: Optional[str],
        coefficient_adjustment: float
    ):
        """Log the calibration event for history and analysis."""
        db.execute(text("""
            INSERT INTO body_state_calibration (
                id, user_id, estimate_type, estimated_value, estimated_label,
                feedback_type, user_response, correction_direction, correction_magnitude,
                hours_since_meal, hours_since_sleep, time_of_day,
                affected_coefficient, coefficient_adjustment
            ) VALUES (
                gen_random_uuid()::text, :user_id, :estimate_type, :estimated_value, :estimated_label,
                :feedback_type, :user_response, :direction, :magnitude,
                :hours_since_meal, :hours_since_sleep, :time_of_day,
                :affected_coefficient, :coefficient_adjustment
            )
        """), {
            "user_id": pending.user_id,
            "estimate_type": pending.estimate_type,
            "estimated_value": pending.estimated_value,
            "estimated_label": pending.estimated_label,
            "feedback_type": feedback_type,
            "user_response": user_response[:500],
            "direction": direction,
            "magnitude": magnitude,
            "hours_since_meal": pending.context.get('hours_since_meal'),
            "hours_since_sleep": pending.context.get('hours_awake'),  # hours awake = hours since sleep
            "time_of_day": pending.context.get('time_of_day'),
            "affected_coefficient": affected_coefficient,
            "coefficient_adjustment": coefficient_adjustment
        })
        db.commit()

    def get_user_coefficients(self, db: Session, user_id: str) -> Dict:
        """Get a user's personal coefficients, or defaults if none exist."""
        result = db.execute(text("""
            SELECT
                blood_sugar_decay_rate,
                meal_sustain_factor,
                sleep_target_hours,
                sleep_debt_sensitivity,
                circadian_phase_shift,
                recovery_rate_multiplier,
                stress_tolerance,
                calibration_count,
                last_calibrated_at
            FROM body_state_coefficients
            WHERE user_id = :user_id
        """), {"user_id": user_id}).fetchone()

        if result:
            return {
                'blood_sugar_decay_rate': float(result.blood_sugar_decay_rate),
                'meal_sustain_factor': float(result.meal_sustain_factor),
                'sleep_target_hours': float(result.sleep_target_hours),
                'sleep_debt_sensitivity': float(result.sleep_debt_sensitivity),
                'circadian_phase_shift': float(result.circadian_phase_shift),
                'recovery_rate_multiplier': float(result.recovery_rate_multiplier),
                'stress_tolerance': float(result.stress_tolerance),
                'calibration_count': result.calibration_count,
                'last_calibrated_at': result.last_calibrated_at
            }

        # Return defaults
        return {
            'blood_sugar_decay_rate': 1.0,
            'meal_sustain_factor': 1.0,
            'sleep_target_hours': 7.5,
            'sleep_debt_sensitivity': 1.0,
            'circadian_phase_shift': 0.0,
            'recovery_rate_multiplier': 1.0,
            'stress_tolerance': 1.0,
            'calibration_count': 0,
            'last_calibrated_at': None
        }

    def get_calibration_history(
        self,
        db: Session,
        user_id: str,
        limit: int = 20
    ) -> List[Dict]:
        """Get recent calibration events for a user."""
        result = db.execute(text("""
            SELECT
                estimate_type, estimated_value, estimated_label,
                feedback_type, correction_direction,
                affected_coefficient, coefficient_adjustment,
                created_at
            FROM body_state_calibration
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"user_id": user_id, "limit": limit}).fetchall()

        return [
            {
                'estimate_type': r.estimate_type,
                'estimated_value': float(r.estimated_value),
                'estimated_label': r.estimated_label,
                'feedback_type': r.feedback_type,
                'direction': r.correction_direction,
                'coefficient': r.affected_coefficient,
                'adjustment': float(r.coefficient_adjustment) if r.coefficient_adjustment else 0,
                'created_at': r.created_at.isoformat() if r.created_at else None
            }
            for r in result
        ]


# Global instance
calibration_service = BodyStateCalibrationService()
