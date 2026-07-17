"""
Body State Estimation Service

Maintains running estimates of physiological state based on available signals:
- Blood sugar / hunger (from meal timing and composition)
- Fatigue / alertness (from sleep, time awake, cognitive load)
- Stress load (emergent from multiple signals)
- Physical recovery (from workout logs)
- Pattern breaks (deviations from personal norms)

These estimates inform Sara's passive awareness without being announced directly.
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from zoneinfo import ZoneInfo
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Timezone - Pennsylvania is Eastern Time
USER_TZ = ZoneInfo("America/New_York")


@dataclass
class BodyStateEstimate:
    """Current physiological state estimates (all values 0-1 unless noted)"""

    # Blood sugar / hunger
    blood_sugar: float = 0.5  # 0=empty, 1=just ate
    blood_sugar_trend: str = "stable"  # rising, falling, stable, crashing
    hours_of_fuel_remaining: float = 0.0  # Estimated hours until "empty"

    # Fatigue / alertness
    alertness: float = 0.5  # 0=exhausted, 1=peak alertness
    sleep_debt_hours: float = 0.0  # Cumulative deficit
    cognitive_drain: float = 0.0  # How much deep work has depleted you today
    circadian_phase: str = "normal"  # morning_peak, afternoon_dip, evening_wind_down

    # Stress
    stress_load: float = 0.3  # 0=relaxed, 1=highly stressed
    stress_trend: str = "stable"  # rising, falling, stable
    stress_contributors: List[str] = field(default_factory=list)  # What's driving it

    # Sleep quality (from stage breakdown — distinct from quantity)
    sleep_quality: float = 0.7   # 0=poor architecture, 1=textbook
    sleep_efficiency: float = 0.0  # asleep / (asleep+awake), 0-1
    sleep_deep_pct: float = 0.0
    sleep_rem_pct: float = 0.0

    # Autonomic recovery (from HRV vs personal baseline)
    autonomic_recovery: float = 0.7  # 0=stressed/sick, 1=well recovered
    hrv_zscore: Optional[float] = None  # latest HRV vs 7d mean, in std-deviations

    # Physical recovery
    recovery_status: Dict[str, float] = field(default_factory=dict)  # muscle_group -> 0-1
    overall_physical_readiness: float = 0.8  # 0=wrecked, 1=fully recovered

    # Pattern breaks
    pattern_anomalies: List[str] = field(default_factory=list)
    anomaly_severity: float = 0.0  # 0=normal day, 1=very unusual

    # Meta
    confidence: float = 0.5  # How much data we have to work with
    last_updated: Optional[datetime] = None


class BodyStateService:
    """
    Service for estimating physiological state from available signals.

    Design principles:
    - Estimates decay/change over time even without new data
    - Multiple signals combine for more reliable estimates
    - Confidence reflects data availability
    - All estimates are directional, not medically precise
    """

    def __init__(self):
        self.tz = USER_TZ

        # Blood sugar model parameters
        self.BASE_METABOLIC_RATE = 80  # calories/hour at rest
        self.COGNITIVE_MULTIPLIER = 1.3  # Deep work burns more
        self.PROTEIN_SUSTAIN_FACTOR = 1.4  # Protein extends satiety
        self.FAT_SUSTAIN_FACTOR = 1.3
        self.CARB_SPIKE_FACTOR = 0.7  # Simple carbs = faster crash

        # Fatigue model parameters
        self.IDEAL_SLEEP_HOURS = 7.5
        self.ALERTNESS_DECAY_PER_HOUR = 0.04  # Natural decay while awake
        self.COGNITIVE_DRAIN_FACTOR = 0.02  # Additional drain from deep work
        self.CIRCADIAN_DIP_START = 13  # 1 PM
        self.CIRCADIAN_DIP_END = 15  # 3 PM
        self.CIRCADIAN_DIP_MAGNITUDE = 0.15

        # Recovery model parameters
        self.MUSCLE_GROUPS = {
            'legs': ['squat', 'leg press', 'lunge', 'deadlift', 'leg curl', 'leg extension', 'calf'],
            'chest': ['bench', 'chest press', 'fly', 'push-up', 'pushup', 'dip'],
            'back': ['row', 'pull-up', 'pullup', 'lat pulldown', 'deadlift'],
            'shoulders': ['overhead press', 'lateral raise', 'front raise', 'shoulder press'],
            'arms': ['curl', 'tricep', 'bicep', 'hammer'],
            'core': ['plank', 'crunch', 'ab', 'sit-up', 'situp']
        }
        self.BASE_RECOVERY_HOURS = {
            'legs': 72,  # Large muscle groups need more time
            'back': 72,
            'chest': 48,
            'shoulders': 48,
            'arms': 36,
            'core': 24
        }

    async def estimate_body_state(
        self,
        db: Session,
        user_id: str,
        subconscious_state: Optional[dict] = None
    ) -> BodyStateEstimate:
        """
        Calculate comprehensive body state estimate.

        Args:
            db: Database session
            user_id: User ID
            subconscious_state: Optional dict with mood/energy from LLM analysis
        """
        now = datetime.now(self.tz)
        estimate = BodyStateEstimate(last_updated=now)

        # Load personal coefficients (learned from user feedback)
        coefficients = await self._get_personal_coefficients(db, user_id)

        # Gather all signals
        signals = await self._gather_signals(db, user_id, now)

        # Calculate each estimate with personal coefficients
        await self._estimate_blood_sugar(estimate, signals, now, coefficients)
        await self._estimate_alertness(estimate, signals, subconscious_state, now, coefficients)
        await self._estimate_stress(estimate, signals, subconscious_state, now, coefficients)
        await self._estimate_autonomic_recovery(estimate, signals)
        await self._estimate_recovery(estimate, signals, now, coefficients)
        await self._detect_pattern_breaks(estimate, signals, db, user_id, now)

        # Calculate overall confidence based on data availability
        estimate.confidence = self._calculate_confidence(signals)

        logger.info(f"Body state estimate: blood_sugar={estimate.blood_sugar:.2f}, "
                   f"alertness={estimate.alertness:.2f}, stress={estimate.stress_load:.2f}, "
                   f"anomalies={len(estimate.pattern_anomalies)}")

        return estimate

    async def _gather_signals(self, db: Session, user_id: str, now: datetime) -> dict:
        """Gather all available signals for body state estimation."""
        signals = {
            'meals': [],
            'sleep': None,
            'sleep_history': [],
            'workouts': [],
            'presence': None,
            'first_activity': None,
            'message_count': 0,
            'calendar_events': 0,
            'historical_patterns': {}
        }

        # Recent meals (last 24 hours)
        # Note: food_log table has 'fats' column, no 'fiber' column - we'll estimate fiber as 0
        meals = db.execute(text("""
            SELECT meal_type, logged_at, calories, protein, carbs, fats as fat, 0 as fiber
            FROM food_log
            WHERE user_id = :user_id
              AND logged_at >= NOW() - INTERVAL '24 hours'
            ORDER BY logged_at DESC
        """), {"user_id": user_id}).fetchall()

        signals['meals'] = [dict(m._mapping) for m in meals]

        # Last night's sleep
        sleep = db.execute(text("""
            SELECT value, recorded_at
            FROM health_metric
            WHERE user_id = :user_id
              AND metric_type = 'sleep_hours'
              AND recorded_at >= NOW() - INTERVAL '36 hours'
            ORDER BY recorded_at DESC
            LIMIT 1
        """), {"user_id": user_id}).fetchone()

        if sleep:
            signals['sleep'] = float(sleep.value)

        # Sleep history (last 7 days for debt calculation)
        sleep_history = db.execute(text("""
            SELECT value, recorded_at
            FROM health_metric
            WHERE user_id = :user_id
              AND metric_type = 'sleep_hours'
              AND recorded_at >= NOW() - INTERVAL '7 days'
            ORDER BY recorded_at DESC
        """), {"user_id": user_id}).fetchall()

        signals['sleep_history'] = [float(s.value) for s in sleep_history]

        # Last night's sleep STAGE breakdown (deep/REM/core/awake) — drives sleep
        # quality scoring distinct from total hours. Each stage has its own row
        # in health_metric, all stamped at the morning's 6 AM canonical timestamp.
        stage_rows = db.execute(text("""
            SELECT metric_type, value
            FROM health_metric
            WHERE user_id = :user_id
              AND metric_type IN ('sleep_deep_min','sleep_rem_min','sleep_core_min','sleep_awake_min')
              AND recorded_at >= NOW() - INTERVAL '36 hours'
        """), {"user_id": user_id}).fetchall()
        if stage_rows:
            signals['sleep_stages'] = {r.metric_type: float(r.value) for r in stage_rows}

        # Recent HRV — latest reading + 7-day daily-average history for autonomic
        # recovery scoring. Prefer hrv_morning when present (single canonical row
        # per day stamped 6 AM); fall back to all-day samples otherwise.
        hrv_latest = db.execute(text("""
            SELECT value, recorded_at, metric_type
            FROM health_metric
            WHERE user_id = :user_id
              AND metric_type IN ('hrv_morning','hrv')
              AND recorded_at >= NOW() - INTERVAL '36 hours'
            ORDER BY
              CASE metric_type WHEN 'hrv_morning' THEN 0 ELSE 1 END,
              recorded_at DESC
            LIMIT 1
        """), {"user_id": user_id}).fetchone()
        if hrv_latest:
            signals['hrv_latest'] = float(hrv_latest.value)

        # Per-day HRV averages over the last 7 days for baseline comparison.
        hrv_daily = db.execute(text("""
            SELECT DATE(recorded_at AT TIME ZONE 'America/New_York') AS d,
                   AVG(value) AS avg_value
            FROM health_metric
            WHERE user_id = :user_id
              AND metric_type IN ('hrv_morning','hrv')
              AND recorded_at >= NOW() - INTERVAL '7 days'
            GROUP BY DATE(recorded_at AT TIME ZONE 'America/New_York')
            ORDER BY d ASC
        """), {"user_id": user_id}).fetchall()
        signals['hrv_history_daily'] = [float(r.avg_value) for r in hrv_daily if r.avg_value is not None]

        # Recent workouts (last 5 days for recovery tracking)
        # workout_sessions has the actual session data, workout_log has individual sets
        workouts = db.execute(text("""
            SELECT
                ws.id,
                w.title as workout_type,
                ws.started_at,
                ws.completed_at,
                '' as notes,
                COALESCE(
                    (SELECT json_agg(json_build_object(
                        'exercise', wl.exercise_id,
                        'sets', 1,
                        'reps', wl.reps,
                        'weight', wl.weight
                    ))
                    FROM workout_log wl
                    WHERE wl.session_id = ws.id),
                    '[]'::json
                ) as exercises
            FROM workout_sessions ws
            JOIN workout w ON w.id = ws.workout_id
            WHERE ws.user_id = :user_id
              AND ws.started_at >= NOW() - INTERVAL '5 days'
              AND ws.session_state = 'completed'
            ORDER BY ws.started_at DESC
        """), {"user_id": user_id}).fetchall()

        signals['workouts'] = [dict(w._mapping) for w in workouts]

        # External workouts from HealthKit (Apple Watch / Fitness app) — separate
        # stream from app-logged strength sessions. Surfaced as a parallel signal
        # so cardio load (long walks, runs, etc.) influences recovery estimates.
        ext_workouts = db.execute(text("""
            SELECT activity_type, started_at, ended_at, duration_seconds,
                   total_energy_kcal, avg_heart_rate, max_heart_rate
            FROM external_workout
            WHERE user_id = :user_id
              AND started_at >= NOW() - INTERVAL '5 days'
            ORDER BY started_at DESC
        """), {"user_id": user_id}).fetchall()
        signals['external_workouts'] = [dict(w._mapping) for w in ext_workouts]

        # First activity today
        # Convert to UTC for DB comparisons (DB stores timestamps in UTC)
        today_start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start = today_start_local.astimezone(ZoneInfo('UTC'))
        first_activity = db.execute(text("""
            SELECT MIN(activity_time) as first_activity FROM (
                SELECT created_at as activity_time FROM presence_log
                WHERE user_id = :user_id AND created_at >= :today_start
                UNION ALL
                SELECT created_at as activity_time FROM episode
                WHERE user_id = :user_id AND created_at >= :today_start AND role = 'user'
            ) combined
        """), {"user_id": user_id, "today_start": today_start}).fetchone()

        if first_activity and first_activity.first_activity:
            signals['first_activity'] = first_activity.first_activity
            # DB returns UTC - if naive, treat as UTC then convert to user TZ
            if signals['first_activity'].tzinfo is None:
                signals['first_activity'] = signals['first_activity'].replace(tzinfo=ZoneInfo('UTC')).astimezone(self.tz)
            else:
                signals['first_activity'] = signals['first_activity'].astimezone(self.tz)

        # Message count today (for cognitive load)
        msg_count = db.execute(text("""
            SELECT COUNT(*) as count
            FROM episode
            WHERE user_id = :user_id
              AND created_at >= :today_start
              AND role = 'user'
        """), {"user_id": user_id, "today_start": today_start}).fetchone()

        signals['message_count'] = msg_count.count if msg_count else 0

        # Calendar density today
        calendar_count = db.execute(text("""
            SELECT COUNT(*) as count
            FROM calendar_event
            WHERE user_id = :user_id
              AND start_time >= :today_start
              AND start_time < :today_start + INTERVAL '1 day'
        """), {"user_id": user_id, "today_start": today_start}).fetchone()

        signals['calendar_events'] = calendar_count.count if calendar_count else 0

        # Historical patterns (14-day rolling averages)
        signals['historical_patterns'] = await self._get_historical_patterns(db, user_id)

        return signals

    async def _get_historical_patterns(self, db: Session, user_id: str) -> dict:
        """Calculate 14-day rolling averages for pattern comparison."""
        patterns = {}
        user_tz = 'America/New_York'

        # Average wake time - IMPORTANT: Convert to user's timezone before extracting hour/date
        # Normalize timestamps in UNION: presence_log is tz-aware, episode is naive (UTC)
        # Then convert uniformly to user timezone for grouping and extraction
        # Filter: >= 4 AM (exclude late night), <= 10 AM (exclude days user didn't use app until later)
        wake_times = db.execute(text("""
            SELECT EXTRACT(HOUR FROM MIN(activity_time AT TIME ZONE :tz)) +
                   EXTRACT(MINUTE FROM MIN(activity_time AT TIME ZONE :tz))/60.0 as wake_hour,
                   DATE(activity_time AT TIME ZONE :tz) as day
            FROM (
                SELECT created_at as activity_time FROM presence_log
                WHERE user_id = :user_id AND created_at >= NOW() - INTERVAL '14 days'
                UNION ALL
                SELECT created_at AT TIME ZONE 'UTC' as activity_time FROM episode
                WHERE user_id = :user_id AND created_at >= NOW() - INTERVAL '14 days' AND role = 'user'
            ) combined
            GROUP BY DATE(activity_time AT TIME ZONE :tz)
            HAVING EXTRACT(HOUR FROM MIN(activity_time AT TIME ZONE :tz)) >= 4
               AND EXTRACT(HOUR FROM MIN(activity_time AT TIME ZONE :tz)) <= 10
        """), {"user_id": user_id, "tz": user_tz}).fetchall()

        if wake_times:
            # Convert Decimal to float for pattern calculations
            wake_hours = [float(w.wake_hour) for w in wake_times if w.wake_hour is not None]
            if wake_hours:
                patterns['avg_wake_hour'] = sum(wake_hours) / len(wake_hours)
                patterns['wake_hour_std'] = self._calculate_std(wake_hours)

        # Average meal times by type
        # NOTE: food_log stores naive timestamps in EASTERN time (not UTC!) - extract hour directly
        for meal_type in ['breakfast', 'lunch', 'dinner']:
            meal_times = db.execute(text("""
                SELECT EXTRACT(HOUR FROM logged_at) +
                       EXTRACT(MINUTE FROM logged_at)/60.0 as meal_hour
                FROM food_log
                WHERE user_id = :user_id
                  AND meal_type = :meal_type
                  AND logged_at >= NOW() - INTERVAL '14 days'
            """), {"user_id": user_id, "meal_type": meal_type}).fetchall()

            if meal_times:
                meal_hours = [float(m.meal_hour) for m in meal_times if m.meal_hour is not None]
                if meal_hours:
                    patterns[f'avg_{meal_type}_hour'] = sum(meal_hours) / len(meal_hours)

        # Average daily message count - also use user timezone for date grouping
        # Use double AT TIME ZONE for consistent handling of naive timestamps
        daily_msgs = db.execute(text("""
            SELECT COUNT(*) as count, DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE :tz) as day
            FROM episode
            WHERE user_id = :user_id
              AND created_at >= NOW() - INTERVAL '14 days'
              AND role = 'user'
            GROUP BY DATE(created_at AT TIME ZONE 'UTC' AT TIME ZONE :tz)
        """), {"user_id": user_id, "tz": user_tz}).fetchall()

        if daily_msgs:
            msg_counts = [int(d.count) for d in daily_msgs]
            patterns['avg_daily_messages'] = sum(msg_counts) / len(msg_counts)

        # Average sleep
        if patterns.get('sleep_history'):
            patterns['avg_sleep'] = sum(patterns['sleep_history']) / len(patterns['sleep_history'])

        return patterns

    def _calculate_std(self, values: List[float]) -> float:
        """Calculate standard deviation."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return math.sqrt(variance)

    async def _get_personal_coefficients(self, db: Session, user_id: str) -> dict:
        """Get user's personal coefficients learned from feedback."""
        try:
            result = db.execute(text("""
                SELECT
                    blood_sugar_decay_rate,
                    meal_sustain_factor,
                    sleep_target_hours,
                    sleep_debt_sensitivity,
                    circadian_phase_shift,
                    recovery_rate_multiplier,
                    stress_tolerance
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
                }
        except Exception as e:
            logger.warning(f"Could not load personal coefficients: {e}")

        # Return defaults
        return {
            'blood_sugar_decay_rate': 1.0,
            'meal_sustain_factor': 1.0,
            'sleep_target_hours': 7.5,
            'sleep_debt_sensitivity': 1.0,
            'circadian_phase_shift': 0.0,
            'recovery_rate_multiplier': 1.0,
            'stress_tolerance': 1.0,
        }

    async def _estimate_blood_sugar(
        self,
        estimate: BodyStateEstimate,
        signals: dict,
        now: datetime,
        coefficients: dict = None
    ):
        """
        Estimate blood sugar / hunger level based on meal timing and composition.

        Model:
        - Starts at 1.0 after eating
        - Decays based on time and metabolic rate
        - Macro composition affects decay rate
        - Protein/fat slow decay, simple carbs accelerate it
        """
        meals = signals.get('meals', [])

        if not meals:
            # No meals logged - estimate based on time awake
            if signals.get('first_activity'):
                hours_awake = (now - signals['first_activity']).total_seconds() / 3600
                # Assume they started at ~0.6 (overnight fast)
                estimate.blood_sugar = max(0.1, 0.6 - (hours_awake * 0.08))
                estimate.blood_sugar_trend = "falling"
                estimate.hours_of_fuel_remaining = estimate.blood_sugar / 0.08
            else:
                estimate.blood_sugar = 0.4
                estimate.blood_sugar_trend = "unknown"
            return

        # Get most recent meal
        last_meal = meals[0]
        meal_time = last_meal['logged_at']
        if meal_time.tzinfo is None:
            meal_time = meal_time.replace(tzinfo=self.tz)

        hours_since_meal = (now - meal_time).total_seconds() / 3600

        # Calculate meal sustain factor based on macros
        # Convert to float to avoid Decimal type issues from database
        calories = float(last_meal.get('calories') or 400)
        protein = float(last_meal.get('protein') or 0)
        fat = float(last_meal.get('fat') or 0)
        carbs = float(last_meal.get('carbs') or 0)
        fiber = float(last_meal.get('fiber') or 0)

        # Higher protein/fat ratio = slower decay
        total_macros = protein + fat + carbs + 1  # Avoid division by zero
        protein_ratio = protein / total_macros
        fat_ratio = fat / total_macros
        carb_ratio = carbs / total_macros

        # Fiber slows absorption
        fiber_factor = 1 + (fiber / 30) * 0.2  # Up to 20% slower with high fiber

        # Calculate sustain multiplier (how long this meal lasts)
        sustain_factor = (
            1.0 +
            protein_ratio * (self.PROTEIN_SUSTAIN_FACTOR - 1) +
            fat_ratio * (self.FAT_SUSTAIN_FACTOR - 1) -
            carb_ratio * (1 - self.CARB_SPIKE_FACTOR)
        ) * fiber_factor

        # Apply personal meal sustain coefficient (learned from feedback)
        if coefficients:
            sustain_factor *= coefficients.get('meal_sustain_factor', 1.0)

        # Larger meals sustain longer (logarithmic scaling)
        calorie_factor = math.log(calories / 300 + 1) / math.log(2)  # ~1.0 at 300cal, ~1.4 at 600cal

        # Calculate decay rate (hours until blood sugar drops by 0.5)
        base_hours_to_half = 2.5
        adjusted_hours_to_half = base_hours_to_half * sustain_factor * calorie_factor

        # Apply personal decay rate coefficient (learned from feedback)
        if coefficients:
            adjusted_hours_to_half /= coefficients.get('blood_sugar_decay_rate', 1.0)

        # Exponential decay from 1.0
        decay_rate = 0.693 / adjusted_hours_to_half  # ln(2) / half-life
        estimate.blood_sugar = max(0.1, math.exp(-decay_rate * hours_since_meal))

        # Determine trend
        if hours_since_meal < 0.5:
            estimate.blood_sugar_trend = "rising" if hours_since_meal < 0.25 else "peak"
        elif estimate.blood_sugar > 0.6:
            estimate.blood_sugar_trend = "stable"
        elif estimate.blood_sugar > 0.3:
            estimate.blood_sugar_trend = "falling"
        else:
            estimate.blood_sugar_trend = "low"

        # Hours of fuel remaining (rough estimate)
        if estimate.blood_sugar > 0.2:
            estimate.hours_of_fuel_remaining = math.log(estimate.blood_sugar / 0.2) / decay_rate
        else:
            estimate.hours_of_fuel_remaining = 0

    async def _estimate_alertness(
        self,
        estimate: BodyStateEstimate,
        signals: dict,
        subconscious_state: Optional[dict],
        now: datetime,
        coefficients: dict = None
    ):
        """
        Estimate alertness / fatigue level.

        Model:
        - Starts based on sleep quality
        - Decays through the day
        - Cognitive work accelerates decay
        - Circadian rhythm creates afternoon dip
        """
        # Personal sleep target (learned from feedback)
        ideal_sleep = self.IDEAL_SLEEP_HOURS
        sleep_debt_sensitivity = 1.0
        circadian_shift = 0.0
        if coefficients:
            ideal_sleep = coefficients.get('sleep_target_hours', self.IDEAL_SLEEP_HOURS)
            sleep_debt_sensitivity = coefficients.get('sleep_debt_sensitivity', 1.0)
            circadian_shift = coefficients.get('circadian_phase_shift', 0.0)

        # Base alertness from sleep
        sleep_hours = signals.get('sleep')
        if sleep_hours:
            # Personal ideal hours = optimal (alertness 0.9)
            # Less sleep = lower starting point
            sleep_ratio = sleep_hours / ideal_sleep
            base_alertness = min(0.95, 0.5 + sleep_ratio * 0.4)

            # Calculate sleep debt
            sleep_history = signals.get('sleep_history', [])
            if sleep_history:
                total_deficit = sum(max(0, ideal_sleep - s) for s in sleep_history)
                estimate.sleep_debt_hours = total_deficit
                # Chronic debt reduces base alertness (scaled by personal sensitivity)
                debt_penalty = min(0.2, total_deficit * 0.02 * sleep_debt_sensitivity)
                base_alertness -= debt_penalty
        else:
            base_alertness = 0.6  # Assume moderate if no data

        # Sleep QUALITY adjustment from stage breakdown (HealthKit/Apple Watch).
        # Quantity alone misses fragmented or low-deep-sleep nights — a 7h night
        # with poor architecture leaves you less rested than 6h with healthy
        # cycles. We compute three signals and fold them into base_alertness.
        stages = signals.get('sleep_stages')
        if stages:
            deep = stages.get('sleep_deep_min', 0.0)
            rem = stages.get('sleep_rem_min', 0.0)
            core = stages.get('sleep_core_min', 0.0)
            awake = stages.get('sleep_awake_min', 0.0)
            asleep = deep + rem + core
            if asleep > 0:
                efficiency = asleep / (asleep + awake) if (asleep + awake) > 0 else 1.0
                deep_pct = deep / asleep
                rem_pct = rem / asleep
                # Healthy adult targets: ~13-23% deep, ~20-25% REM, ~85%+ efficiency.
                # Score each component on a [0,1] scale around the target band.
                deep_score = min(1.0, deep_pct / 0.18)        # 18% is comfortable target
                rem_score = min(1.0, rem_pct / 0.22)          # 22% target
                eff_score = max(0.0, (efficiency - 0.7) / 0.25)  # ramps from 70%→95%
                quality = max(0.0, min(1.0, 0.4 * deep_score + 0.3 * rem_score + 0.3 * eff_score))
                estimate.sleep_quality = round(quality, 3)
                estimate.sleep_efficiency = round(efficiency, 3)
                estimate.sleep_deep_pct = round(deep_pct, 3)
                estimate.sleep_rem_pct = round(rem_pct, 3)
                # Quality biases base alertness up to ±0.1 — meaningful but not dominant.
                base_alertness += (quality - 0.7) * 0.15
                base_alertness = min(0.95, max(0.1, base_alertness))

        # Decay based on time awake
        if signals.get('first_activity'):
            hours_awake = (now - signals['first_activity']).total_seconds() / 3600
            time_decay = hours_awake * self.ALERTNESS_DECAY_PER_HOUR
        else:
            hours_awake = 8  # Assume if unknown
            time_decay = hours_awake * self.ALERTNESS_DECAY_PER_HOUR

        # Cognitive drain from deep work
        message_count = signals.get('message_count', 0)
        # Assume high message count = active engagement = cognitive work
        # Also factor in focus intensity if available from subconscious
        focus_intensity = 0.5
        if subconscious_state:
            focus_intensity = subconscious_state.get('focus_intensity', 0.5) or 0.5

        cognitive_hours = hours_awake * focus_intensity
        estimate.cognitive_drain = min(0.4, cognitive_hours * self.COGNITIVE_DRAIN_FACTOR)

        # Circadian rhythm adjustment (with personal phase shift - night owls get later dip)
        hour = now.hour - circadian_shift  # Shift the effective hour
        circadian_adjustment = 0
        if self.CIRCADIAN_DIP_START <= hour <= self.CIRCADIAN_DIP_END:
            # Afternoon dip
            dip_progress = (hour - self.CIRCADIAN_DIP_START) / (self.CIRCADIAN_DIP_END - self.CIRCADIAN_DIP_START)
            circadian_adjustment = -self.CIRCADIAN_DIP_MAGNITUDE * math.sin(dip_progress * math.pi)
            estimate.circadian_phase = "afternoon_dip"
        elif hour < 10:
            # Morning ramp-up
            estimate.circadian_phase = "morning_peak"
            circadian_adjustment = 0.05
        elif hour >= 21:
            # Evening wind-down
            estimate.circadian_phase = "evening_wind_down"
            circadian_adjustment = -0.1
        else:
            estimate.circadian_phase = "normal"

        # Blood sugar affects alertness
        blood_sugar_effect = (estimate.blood_sugar - 0.5) * 0.15  # Low blood sugar = lower alertness

        # Calculate final alertness
        estimate.alertness = max(0.1, min(0.95,
            base_alertness - time_decay - estimate.cognitive_drain + circadian_adjustment + blood_sugar_effect
        ))

    async def _estimate_stress(
        self,
        estimate: BodyStateEstimate,
        signals: dict,
        subconscious_state: Optional[dict],
        now: datetime,
        coefficients: dict = None
    ):
        """
        Estimate stress load from multiple signals.

        Stress is emergent - no single signal indicates it, but patterns do:
        - Poor sleep
        - Skipped/irregular meals
        - Declining energy/mood
        - High calendar density
        - Pattern disruptions
        """
        # Personal stress tolerance (learned from feedback)
        stress_tolerance = 1.0
        if coefficients:
            stress_tolerance = coefficients.get('stress_tolerance', 1.0)

        stress_contributors = []
        stress_score = 0.2  # Base level

        # Sleep quality contribution
        sleep_hours = signals.get('sleep')
        if sleep_hours:
            if sleep_hours < 5:
                stress_score += 0.2
                stress_contributors.append("poor sleep")
            elif sleep_hours < 6:
                stress_score += 0.1
                stress_contributors.append("light sleep")

        # Sleep debt contribution
        if estimate.sleep_debt_hours > 5:
            stress_score += 0.15
            stress_contributors.append("accumulated sleep debt")

        # Meal regularity
        meals = signals.get('meals', [])
        if signals.get('first_activity'):
            hours_awake = (now - signals['first_activity']).total_seconds() / 3600
            if hours_awake > 4 and len(meals) == 0:
                stress_score += 0.15
                stress_contributors.append("no food logged")
            elif hours_awake > 6 and len(meals) < 2:
                stress_score += 0.1
                stress_contributors.append("irregular eating")

        # Calendar density
        calendar_events = signals.get('calendar_events', 0)
        if calendar_events > 5:
            stress_score += 0.15
            stress_contributors.append("packed schedule")
        elif calendar_events > 3:
            stress_score += 0.05

        # Mood/energy from subconscious
        if subconscious_state:
            mood = subconscious_state.get('inferred_mood', '')
            energy = subconscious_state.get('inferred_energy_level', 0.5) or 0.5

            if mood in ['stressed', 'frustrated', 'anxious', 'overwhelmed']:
                stress_score += 0.2
                stress_contributors.append(f"feeling {mood}")
            elif mood in ['tired', 'drained']:
                stress_score += 0.1

            if energy < 0.3:
                stress_score += 0.1
                stress_contributors.append("low energy")

        # Low alertness compounds stress
        if estimate.alertness < 0.35:
            stress_score += 0.1
            stress_contributors.append("running on empty")

        # Low blood sugar compounds stress
        if estimate.blood_sugar < 0.25:
            stress_score += 0.1

        # Apply personal stress tolerance (higher tolerance = lower stress for same inputs)
        estimate.stress_load = min(0.95, stress_score / stress_tolerance)
        estimate.stress_contributors = stress_contributors

        # Determine trend (would need historical data to do properly)
        # For now, base on contributor count
        if len(stress_contributors) > 3:
            estimate.stress_trend = "elevated"
        elif len(stress_contributors) > 1:
            estimate.stress_trend = "rising"
        else:
            estimate.stress_trend = "stable"

    async def _estimate_autonomic_recovery(
        self,
        estimate: BodyStateEstimate,
        signals: dict,
    ):
        """
        Estimate autonomic recovery from HRV.

        Latest HRV is compared against the 7-day daily-average mean. A drop
        of >1σ below baseline signals stress/fatigue/illness; well above
        baseline signals well-recovered. Result feeds into the overall
        recovery readiness alongside muscular recovery.
        """
        latest = signals.get('hrv_latest')
        history = signals.get('hrv_history_daily') or []
        if latest is None or len(history) < 3:
            return  # keep default 0.7

        mean = sum(history) / len(history)
        if len(history) >= 2:
            var = sum((v - mean) ** 2 for v in history) / (len(history) - 1)
            std = var ** 0.5
        else:
            std = 0.0

        if std > 0:
            z = (latest - mean) / std
        else:
            z = 0.0
        estimate.hrv_zscore = round(z, 2)

        # Map z-score to recovery score in [0.2, 1.0]:
        #   z = -2σ → 0.3 (significantly stressed)
        #   z =  0  → 0.7 (baseline)
        #   z = +2σ → 0.95 (well recovered)
        recovery = 0.7 + 0.125 * z
        estimate.autonomic_recovery = round(max(0.2, min(0.95, recovery)), 3)

    async def _estimate_recovery(
        self,
        estimate: BodyStateEstimate,
        signals: dict,
        now: datetime,
        coefficients: dict = None
    ):
        """
        Estimate muscle group recovery status from workout logs.

        Model:
        - Each workout impacts specific muscle groups
        - Recovery is exponential based on time
        - Intensity affects recovery time
        - HealthKit cardio (long walks, runs) adds whole-body load
        """
        workouts = signals.get('workouts', [])
        recovery_status = {}

        # Initialize all groups as fully recovered
        for group in self.MUSCLE_GROUPS.keys():
            recovery_status[group] = 1.0

        for workout in workouts:
            workout_time = workout.get('started_at') or workout.get('completed_at')
            if not workout_time:
                continue

            if workout_time.tzinfo is None:
                workout_time = workout_time.replace(tzinfo=self.tz)

            hours_since = (now - workout_time).total_seconds() / 3600
            exercises = workout.get('exercises') or []

            # Identify muscle groups worked
            groups_worked = set()
            total_volume = 0

            for ex in exercises:
                if not isinstance(ex, dict):
                    continue
                exercise_name = (ex.get('exercise') or '').lower()
                sets = ex.get('sets') or 0
                reps = ex.get('reps') or 0
                weight = ex.get('weight') or 0

                volume = sets * reps * (weight if weight else 1)
                total_volume += volume

                # Match exercise to muscle groups
                for group, keywords in self.MUSCLE_GROUPS.items():
                    if any(kw in exercise_name for kw in keywords):
                        groups_worked.add(group)

            # Calculate intensity factor (rough estimate)
            intensity = min(1.0, total_volume / 5000)  # Normalize

            # Apply recovery impact to each group worked
            for group in groups_worked:
                base_recovery_hours = self.BASE_RECOVERY_HOURS.get(group, 48)

                # Apply personal recovery rate (learned from feedback)
                # Higher multiplier = faster recovery
                recovery_multiplier = 1.0
                if coefficients:
                    recovery_multiplier = coefficients.get('recovery_rate_multiplier', 1.0)

                adjusted_recovery_hours = base_recovery_hours * (0.7 + intensity * 0.6) / recovery_multiplier

                # Exponential recovery
                recovery_progress = 1 - math.exp(-hours_since / (adjusted_recovery_hours / 3))

                # Take minimum (worst case if multiple workouts hit same group)
                recovery_status[group] = min(recovery_status[group], recovery_progress)

        estimate.recovery_status = recovery_status

        # Overall physical readiness (weighted average, legs/back weighted higher)
        weights = {'legs': 0.25, 'back': 0.25, 'chest': 0.15, 'shoulders': 0.15, 'arms': 0.1, 'core': 0.1}
        muscular_readiness = sum(recovery_status.get(g, 1.0) * w for g, w in weights.items())

        # Cardio load from HealthKit-tracked workouts. Long aerobic sessions
        # (runs, hikes, cycling) deplete recovery globally even though they
        # don't show up in workout_log. We compute an exponential decay on
        # cumulative duration in the last 48h.
        cardio_penalty = 0.0
        for ext in signals.get('external_workouts', []) or []:
            started = ext.get('started_at')
            if not started:
                continue
            if started.tzinfo is None:
                started = started.replace(tzinfo=self.tz)
            hours_since = (now - started).total_seconds() / 3600
            if hours_since > 48:
                continue
            duration_min = (ext.get('duration_seconds') or 0) / 60
            # Roughly: 60min run within 24h ≈ 0.10 penalty; decays exponentially
            base_load = min(0.15, duration_min / 600)
            cardio_penalty += base_load * math.exp(-hours_since / 24)
        cardio_penalty = min(0.25, cardio_penalty)

        # Blend muscular recovery with autonomic recovery (HRV-based) and
        # subtract cardio load. Final readiness is a holistic single number.
        autonomic = estimate.autonomic_recovery
        estimate.overall_physical_readiness = max(0.0, min(1.0,
            0.55 * muscular_readiness + 0.35 * autonomic + 0.10 * 1.0 - cardio_penalty
        ))

    async def _detect_pattern_breaks(
        self,
        estimate: BodyStateEstimate,
        signals: dict,
        db: Session,
        user_id: str,
        now: datetime
    ):
        """
        Detect deviations from personal norms.

        Looks for:
        - Unusual wake time
        - Unusual meal timing
        - Unusual activity levels
        """
        anomalies = []
        severity = 0.0
        patterns = signals.get('historical_patterns', {})

        # Check wake time
        if signals.get('first_activity') and patterns.get('avg_wake_hour'):
            # Convert first_activity to user's timezone for proper hour extraction
            first_activity = signals['first_activity']
            if first_activity.tzinfo is None:
                # If naive datetime (from DB in UTC), make it aware as UTC then convert
                first_activity = first_activity.replace(tzinfo=ZoneInfo('UTC')).astimezone(self.tz)
            else:
                # If already aware, convert to user's timezone
                first_activity = first_activity.astimezone(self.tz)

            wake_hour = first_activity.hour + first_activity.minute / 60
            avg_wake = patterns['avg_wake_hour']

            # Only flag as anomaly if wake hour is reasonable (not late-night activity)
            if wake_hour >= 4:  # Ignore activity before 4 AM as late night, not wake time
                wake_diff = abs(wake_hour - avg_wake)

                if wake_diff > 2:
                    direction = "earlier" if wake_hour < avg_wake else "later"
                    anomalies.append(f"woke {wake_diff:.1f}hrs {direction} than usual")
                    severity += 0.2
                elif wake_diff > 1:
                    direction = "earlier" if wake_hour < avg_wake else "later"
                    anomalies.append(f"woke {wake_diff:.1f}hr {direction} than usual")
                    severity += 0.1

        # Check meal timing
        meals = signals.get('meals', [])
        # food_log stores naive timestamps in EASTERN time (not UTC!)
        for meal in meals:
            if meal['logged_at'].tzinfo is None:
                meal['logged_at'] = meal['logged_at'].replace(tzinfo=self.tz)
            else:
                meal['logged_at'] = meal['logged_at'].astimezone(self.tz)
        meals_today = [m for m in meals if m['logged_at'].date() == now.date()]

        for meal_type in ['breakfast', 'lunch', 'dinner']:
            avg_key = f'avg_{meal_type}_hour'
            if patterns.get(avg_key):
                avg_hour = patterns[avg_key]
                # Check if meal was logged
                type_meals = [m for m in meals_today if m['meal_type'] == meal_type]

                if type_meals:
                    meal_logged = type_meals[0]['logged_at']
                    meal_hour = meal_logged.hour + meal_logged.minute / 60
                    diff = abs(meal_hour - avg_hour)
                    if diff > 2:
                        direction = "earlier" if meal_hour < avg_hour else "later"
                        anomalies.append(f"{meal_type} {diff:.1f}hrs {direction} than usual")
                        severity += 0.1
                else:
                    # Check if we're past the usual time
                    current_hour = now.hour + now.minute / 60
                    if current_hour > avg_hour + 2:
                        anomalies.append(f"no {meal_type} logged (usually by {int(avg_hour)}:00)")
                        severity += 0.15

        # Check message volume
        if patterns.get('avg_daily_messages'):
            avg_msgs = patterns['avg_daily_messages']
            today_msgs = signals.get('message_count', 0)
            hours_into_day = now.hour + now.minute / 60

            # Project expected messages at this point in day
            expected_at_this_hour = avg_msgs * (hours_into_day / 16)  # Assume 16 waking hours

            if today_msgs < expected_at_this_hour * 0.3 and hours_into_day > 10:
                anomalies.append(f"unusually quiet today ({today_msgs} messages vs ~{int(expected_at_this_hour)} typical)")
                severity += 0.15
            elif today_msgs > expected_at_this_hour * 2:
                anomalies.append(f"unusually active today ({today_msgs} messages)")
                severity += 0.1

        estimate.pattern_anomalies = anomalies
        estimate.anomaly_severity = min(1.0, severity)

    def _calculate_confidence(self, signals: dict) -> float:
        """Calculate confidence based on data availability."""
        confidence = 0.3  # Base confidence

        if signals.get('meals'):
            confidence += 0.15
        if signals.get('sleep'):
            confidence += 0.15
        if signals.get('first_activity'):
            confidence += 0.1
        if signals.get('workouts'):
            confidence += 0.1
        if signals.get('historical_patterns'):
            confidence += 0.2

        return min(1.0, confidence)

    def generate_context_summary(self, estimate: BodyStateEstimate) -> str:
        """
        Generate a compact context summary for injection into Sara's prompt.

        This is the key output - a human-readable summary that gives Sara
        passive awareness without requiring her to announce it.
        """
        lines = ["[Background awareness - inform responses but don't mention unless relevant]"]

        # Blood sugar / nutrition
        if estimate.blood_sugar < 0.25:
            lines.append(f"Nutrition: running on empty (blood sugar ~{estimate.blood_sugar:.0%})")
        elif estimate.blood_sugar < 0.4:
            lines.append(f"Nutrition: getting hungry (~{estimate.hours_of_fuel_remaining:.1f}hrs fuel remaining)")
        elif estimate.blood_sugar > 0.7:
            lines.append("Nutrition: recently ate, well-fueled")

        # Alertness / fatigue
        if estimate.alertness < 0.35:
            components = []
            if estimate.sleep_debt_hours > 3:
                components.append(f"{estimate.sleep_debt_hours:.0f}hr sleep debt")
            if estimate.cognitive_drain > 0.2:
                components.append("heavy cognitive load")
            if estimate.circadian_phase == "afternoon_dip":
                components.append("afternoon dip")

            detail = f" ({', '.join(components)})" if components else ""
            lines.append(f"Alertness: low{detail}")
        elif estimate.alertness < 0.5:
            lines.append(f"Alertness: moderate, {estimate.circadian_phase.replace('_', ' ')}")
        elif estimate.circadian_phase == "afternoon_dip":
            lines.append("Alertness: good despite afternoon dip window")

        # Stress
        if estimate.stress_load > 0.6:
            contributors = ", ".join(estimate.stress_contributors[:3])
            lines.append(f"Stress: elevated ({contributors})")
        elif estimate.stress_load > 0.4:
            lines.append(f"Stress: slightly elevated, {estimate.stress_trend}")

        # Physical recovery
        recovering_groups = [g for g, v in estimate.recovery_status.items() if v < 0.6]
        if recovering_groups:
            lines.append(f"Recovery: {', '.join(recovering_groups)} still recovering from recent workout")

        # Pattern breaks
        if estimate.pattern_anomalies:
            lines.append(f"Unusual: {'; '.join(estimate.pattern_anomalies[:3])}")

        # Confidence caveat if low
        if estimate.confidence < 0.5:
            lines.append("(Limited data - estimates are rough)")

        return "\n".join(lines)


# Singleton instance
body_state_service = BodyStateService()
