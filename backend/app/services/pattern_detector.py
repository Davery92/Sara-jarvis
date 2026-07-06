"""
Pattern Detector for Sara's Learning System.

Analyzes day replay data across multiple days to detect recurring
behavioral patterns. Correlates actions with context (weather, time,
day of week) to create actionable patterns.

Example patterns detected:
- "User runs heat automation when temperature is below 20°F"
- "User works out on Monday/Wednesday/Friday mornings"
- "User logs breakfast before 9 AM on weekdays"
"""

import logging
import json
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.behavioral_pattern_service import (
    behavioral_pattern_service,
    TriggerType,
    ActionType,
    PatternCategory,
    PatternStatus
)
from app.services.day_replay_builder import DayReplay, DayReplayEvent, DataSource
from app.services.weather_service import weather_service

logger = logging.getLogger(__name__)


class PatternDetector:
    """
    Detects behavioral patterns from day replay data.

    Analyzes recent days to find:
    - Recurring automations with environmental triggers
    - Time-based habits (workout times, meal times)
    - Day-of-week patterns (leg day on Thursday, etc.)
    - Event sequences (always does X after Y)
    """

    # Minimum occurrences to consider a pattern
    MIN_OCCURRENCES = 2

    # How many days back to analyze
    ANALYSIS_WINDOW_DAYS = 14

    async def detect_patterns(
        self,
        db: Session,
        user_id: str,
        replays: List[DayReplay],
        weather_history: Optional[Dict[date, Dict]] = None
    ) -> List[Dict[str, Any]]:
        """
        Detect patterns from a list of day replays.

        Args:
            db: Database session
            user_id: User to detect patterns for
            replays: List of DayReplay objects to analyze
            weather_history: Optional weather data keyed by date

        Returns:
            List of detected patterns (new or updated)
        """
        logger.info(f"Detecting patterns from {len(replays)} days of data")

        detected_patterns = []

        # Detect automation patterns (like heat when cold)
        automation_patterns = await self._detect_automation_patterns(
            db, user_id, replays, weather_history
        )
        detected_patterns.extend(automation_patterns)

        # Detect workout patterns (day of week, time of day)
        workout_patterns = await self._detect_workout_patterns(
            db, user_id, replays
        )
        detected_patterns.extend(workout_patterns)

        # Detect meal timing patterns
        meal_patterns = await self._detect_meal_patterns(
            db, user_id, replays
        )
        detected_patterns.extend(meal_patterns)

        # Detect habit patterns (recurring completions)
        habit_patterns = await self._detect_habit_patterns(
            db, user_id, replays
        )
        detected_patterns.extend(habit_patterns)

        # Detect home routines (doors, lights, motion) from HA activity
        home_patterns = await self._detect_home_routine_patterns(
            db, user_id, replays
        )
        detected_patterns.extend(home_patterns)

        logger.info(f"Detected {len(detected_patterns)} potential patterns")

        return detected_patterns

    async def _detect_automation_patterns(
        self,
        db: Session,
        user_id: str,
        replays: List[DayReplay],
        weather_history: Optional[Dict[date, Dict]]
    ) -> List[Dict[str, Any]]:
        """
        Detect automation patterns, especially weather-correlated ones.

        Example: "Heat automation runs when temp < 20°F"
        """
        patterns = []

        # Collect automation events across all days
        automation_days = defaultdict(list)  # automation_name -> [(date, details)]

        for replay in replays:
            for event in replay.events:
                if event.source == DataSource.AUTOMATIONS:
                    name = event.details.get("automation_name")
                    if name:
                        automation_days[name].append({
                            "date": replay.replay_date,
                            "run_count": event.details.get("run_count", 1),
                            "details": event.details
                        })

        # Analyze each automation for patterns
        for automation_name, occurrences in automation_days.items():
            if len(occurrences) < self.MIN_OCCURRENCES:
                continue

            # Check for weather correlation
            if weather_history:
                weather_pattern = self._analyze_weather_correlation(
                    occurrences, weather_history
                )
                if weather_pattern:
                    # Check if pattern already exists
                    existing_id = await behavioral_pattern_service.find_similar_pattern(
                        db, user_id,
                        TriggerType.WEATHER,
                        weather_pattern["trigger_conditions"],
                        ActionType.AUTOMATION
                    )

                    if existing_id:
                        # Add evidence to existing pattern
                        for occ in occurrences:
                            await behavioral_pattern_service.add_evidence(
                                db, existing_id, occ["date"],
                                f"Automation ran {occ['run_count']} times"
                            )
                        patterns.append({
                            "type": "existing_updated",
                            "pattern_id": existing_id,
                            "automation_name": automation_name
                        })
                    else:
                        # Create new pattern
                        description = f"{automation_name} when {weather_pattern['description']}"
                        pattern_id = await behavioral_pattern_service.create_pattern(
                            db=db,
                            user_id=user_id,
                            trigger_type=TriggerType.WEATHER,
                            trigger_conditions=weather_pattern["trigger_conditions"],
                            action_type=ActionType.AUTOMATION,
                            action_payload={
                                "automation_name": automation_name,
                                "description": occurrences[0]["details"].get("description"),
                                "suggest_message": f"Should I run the '{automation_name}' automation?"
                            },
                            description=description,
                            source_context=f"Observed automation running on {len(occurrences)} days with similar weather",
                            category=PatternCategory.HOME,
                            initial_evidence_date=occurrences[0]["date"]
                        )

                        # Add remaining evidence
                        for occ in occurrences[1:]:
                            await behavioral_pattern_service.add_evidence(
                                db, pattern_id, occ["date"]
                            )

                        patterns.append({
                            "type": "new",
                            "pattern_id": pattern_id,
                            "automation_name": automation_name,
                            "trigger": weather_pattern
                        })

        return patterns

    def _analyze_weather_correlation(
        self,
        occurrences: List[Dict],
        weather_history: Dict[date, Dict]
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze if automation occurrences correlate with weather conditions.

        Returns trigger conditions if correlation found.
        """
        temps = []
        for occ in occurrences:
            weather = weather_history.get(occ["date"])
            if weather and "temp_high" in weather:
                temps.append(weather["temp_high"])
            elif weather and "current_temp" in weather:
                temps.append(weather["current_temp"])

        if not temps:
            return None

        avg_temp = sum(temps) / len(temps)
        max_temp = max(temps)
        min_temp = min(temps)

        # Check for cold weather pattern (all days below freezing)
        if max_temp < 32:
            return {
                "trigger_conditions": {"temp_below_f": 32},
                "description": "temperature is below freezing",
                "confidence": 0.8
            }

        # Check for cold weather pattern (all days below 20)
        if max_temp < 20:
            return {
                "trigger_conditions": {"temp_below_f": 20},
                "description": "temperature is below 20°F",
                "confidence": 0.9
            }

        # Check for generally cold pattern
        if avg_temp < 40 and max_temp < 50:
            threshold = int(max_temp) + 5  # Round up with buffer
            return {
                "trigger_conditions": {"temp_below_f": threshold},
                "description": f"temperature is below {threshold}°F",
                "confidence": 0.7
            }

        # Check for hot weather pattern
        if min_temp > 80:
            return {
                "trigger_conditions": {"temp_above_f": 80},
                "description": "temperature is above 80°F",
                "confidence": 0.7
            }

        return None

    async def _detect_workout_patterns(
        self,
        db: Session,
        user_id: str,
        replays: List[DayReplay]
    ) -> List[Dict[str, Any]]:
        """
        Detect workout timing and day-of-week patterns.

        Example: "User does push workouts on Monday and Thursday"
        """
        patterns = []

        # Collect workout events by day of week
        workout_by_day = defaultdict(list)  # day_name -> [workout_types]
        workout_by_type = defaultdict(list)  # workout_type -> [day_names]

        for replay in replays:
            day_name = replay.replay_date.strftime("%a")  # Mon, Tue, etc.

            for event in replay.events:
                if event.source == DataSource.FITNESS_WORKOUTS:
                    workout_type = event.details.get("workout_type", "general")
                    workout_by_day[day_name].append(workout_type)
                    workout_by_type[workout_type].append(day_name)

        # Find workout type -> day patterns
        for workout_type, days in workout_by_type.items():
            if len(days) < self.MIN_OCCURRENCES:
                continue

            # Count day occurrences
            day_counts = defaultdict(int)
            for day in days:
                day_counts[day] += 1

            # Find days that appear frequently
            frequent_days = [day for day, count in day_counts.items() if count >= 2]

            if frequent_days:
                # Check if pattern exists
                existing_id = await behavioral_pattern_service.find_similar_pattern(
                    db, user_id,
                    TriggerType.DAY_OF_WEEK,
                    {"days": frequent_days},
                    ActionType.SUGGESTION
                )

                if not existing_id:
                    days_str = ", ".join(frequent_days)
                    pattern_id = await behavioral_pattern_service.create_pattern(
                        db=db,
                        user_id=user_id,
                        trigger_type=TriggerType.DAY_OF_WEEK,
                        trigger_conditions={"days": frequent_days},
                        action_type=ActionType.SUGGESTION,
                        action_payload={
                            "workout_type": workout_type,
                            "suggest_message": f"It's {workout_type} day - ready for your workout?"
                        },
                        description=f"{workout_type} workout on {days_str}",
                        source_context=f"Observed {workout_type} workouts on {days_str} over {len(days)} occurrences",
                        category=PatternCategory.FITNESS
                    )

                    patterns.append({
                        "type": "new",
                        "pattern_id": pattern_id,
                        "workout_type": workout_type,
                        "days": frequent_days
                    })

        return patterns

    async def _detect_meal_patterns(
        self,
        db: Session,
        user_id: str,
        replays: List[DayReplay]
    ) -> List[Dict[str, Any]]:
        """
        Detect meal timing patterns.

        Example: "User usually eats breakfast between 7-8 AM"
        """
        patterns = []

        # Collect meal times by type
        meal_times = defaultdict(list)  # meal_type -> [hour]

        for replay in replays:
            for event in replay.events:
                if event.source == DataSource.FITNESS_FOOD and event.event_type == "meal_logged":
                    meal_type = event.details.get("meal_type")
                    if meal_type:
                        hour = event.timestamp.hour
                        meal_times[meal_type].append(hour)

        # Find consistent meal times
        for meal_type, hours in meal_times.items():
            if len(hours) < self.MIN_OCCURRENCES:
                continue

            avg_hour = sum(hours) / len(hours)
            # Check consistency (standard deviation)
            variance = sum((h - avg_hour) ** 2 for h in hours) / len(hours)
            std_dev = variance ** 0.5

            # If meals are within 1.5 hours of each other consistently
            if std_dev < 1.5:
                time_str = f"{int(avg_hour):02d}:00"
                existing_id = await behavioral_pattern_service.find_similar_pattern(
                    db, user_id,
                    TriggerType.TIME,
                    {"time": time_str},
                    ActionType.SUGGESTION
                )

                if not existing_id:
                    pattern_id = await behavioral_pattern_service.create_pattern(
                        db=db,
                        user_id=user_id,
                        trigger_type=TriggerType.TIME,
                        trigger_conditions={"time": time_str},
                        action_type=ActionType.SUGGESTION,
                        action_payload={
                            "meal_type": meal_type,
                            "suggest_message": f"Time for {meal_type}?"
                        },
                        description=f"{meal_type} around {time_str}",
                        source_context=f"Observed {meal_type} logged around {time_str} on {len(hours)} days",
                        category=PatternCategory.NUTRITION
                    )

                    patterns.append({
                        "type": "new",
                        "pattern_id": pattern_id,
                        "meal_type": meal_type,
                        "typical_time": time_str
                    })

        return patterns

    async def _detect_habit_patterns(
        self,
        db: Session,
        user_id: str,
        replays: List[DayReplay]
    ) -> List[Dict[str, Any]]:
        """
        Detect patterns in habit completion.

        Example: "User usually completes morning habits by 9 AM"
        """
        # For now, habits are tracked separately
        # This could analyze habit completion patterns if needed
        return []

    # domain -> {to_state: HA service to call to actually reach that state}.
    # Only these (domain, to_state) pairs get a real actionable "automation"
    # payload; anything else (sensors, locks' intermediate states, richer
    # media_player states, etc.) stays an informational "suggestion" like
    # before — we only promise an action Sara can actually execute correctly.
    _CONTROLLABLE_SERVICES = {
        "light": {"on": "light.turn_on", "off": "light.turn_off"},
        "switch": {"on": "switch.turn_on", "off": "switch.turn_off"},
        "lock": {"locked": "lock.lock", "unlocked": "lock.unlock"},
        "media_player": {"on": "media_player.turn_on", "off": "media_player.turn_off"},
        "fan": {"on": "fan.turn_on", "off": "fan.turn_off"},
        "cover": {"open": "cover.open_cover", "closed": "cover.close_cover"},
    }

    async def _detect_home_routine_patterns(
        self,
        db: Session,
        user_id: str,
        replays: List[DayReplay]
    ) -> List[Dict[str, Any]]:
        """
        Detect daily home routines from HA entity STATE TRANSITIONS.

        Keyed by (entity, to_state) rather than just entity — "the office
        light turns off around 19:00" and "the office light turns on around
        06:00" are different facts, not the same "active" blob. This is what
        makes the resulting pattern promotable into a real standing order
        (turn off vs. turn on aren't interchangeable) instead of a no-op
        "suggestion" that just acknowledges itself.

        Example: "Side door typically opens around 07:00"
        """
        patterns = []

        # (entity_id, to_state) -> {replay_date -> set(ET hours seen)}
        entity_days: Dict[Tuple[str, str], Dict[date, set]] = defaultdict(dict)
        names: Dict[str, str] = {}
        domains: Dict[str, str] = {}

        for replay in replays:
            for event in replay.events:
                if event.source != DataSource.HOME or event.event_type != "home_entity_activity":
                    continue
                eid = event.details.get("entity_id")
                to_state = event.details.get("to_state")
                if not eid or not to_state:
                    continue
                key = (eid, to_state)
                entity_days[key][replay.replay_date] = set(event.details.get("active_hours") or [])
                names[eid] = event.details.get("friendly_name") or eid
                domains[eid] = event.details.get("domain") or eid.split(".")[0]

        for (eid, to_state), day_hours in entity_days.items():
            total_days = len(day_hours)
            if total_days < max(self.MIN_OCCURRENCES, 3):
                continue

            # Count, per hour (±1h smoothing), on how many days it transitioned to this state
            hour_day_counts: Dict[int, int] = defaultdict(int)
            for hours in day_hours.values():
                smoothed = set()
                for h in hours:
                    smoothed.update({(h - 1) % 24, h, (h + 1) % 24})
                for h in smoothed:
                    hour_day_counts[h] += 1

            # A routine hour recurs on most observed days
            required = max(3, int(total_days * 0.6))
            routine_hours = [h for h, c in hour_day_counts.items() if c >= required]
            if not routine_hours:
                continue

            best_hour = max(routine_hours, key=lambda h: hour_day_counts[h])
            time_str = f"{best_hour:02d}:00"
            label = names[eid]
            domain = domains[eid]
            trigger_conditions = {"time": time_str, "entity_id": eid, "to_state": to_state}

            service = self._CONTROLLABLE_SERVICES.get(domain, {}).get(to_state)
            verb = {"on": "turns on", "off": "turns off", "locked": "locks", "unlocked": "unlocks",
                    "open": "opens", "closed": "closes"}.get(to_state, f"goes to {to_state}")
            description = f"{label} {verb} around {time_str}"

            action_type = ActionType.AUTOMATION if service else ActionType.SUGGESTION
            if service:
                action_payload = {
                    "entity_id": eid,
                    "domain": domain,
                    "service": service,
                    "observation": description,
                    "suggest_message": f"{label} usually {verb} around {time_str}. Want me to do that automatically?",
                }
            else:
                action_payload = {
                    "entity_id": eid,
                    "domain": domain,
                    "to_state": to_state,
                    "observation": description,
                    "suggest_message": f"{label} usually {verb} around {time_str}.",
                }

            existing_id = await behavioral_pattern_service.find_similar_pattern(
                db, user_id,
                TriggerType.TIME,
                trigger_conditions,
                action_type,
            )
            if existing_id:
                for d in sorted(day_hours):
                    await behavioral_pattern_service.add_evidence(
                        db, existing_id, d, f"{label} {verb}"
                    )
                patterns.append({
                    "type": "existing_updated",
                    "pattern_id": existing_id,
                    "entity_id": eid
                })
                continue

            pattern_id = await behavioral_pattern_service.create_pattern(
                db=db,
                user_id=user_id,
                trigger_type=TriggerType.TIME,
                trigger_conditions=trigger_conditions,
                action_type=action_type,
                action_payload=action_payload,
                description=description,
                source_context=(
                    f"Observed {label} {verb} around {time_str} on "
                    f"{hour_day_counts[best_hour]} of {total_days} days"
                ),
                category=PatternCategory.HOME,
                initial_evidence_date=min(day_hours)
            )
            for d in sorted(day_hours)[1:]:
                await behavioral_pattern_service.add_evidence(db, pattern_id, d)

            patterns.append({
                "type": "new",
                "pattern_id": pattern_id,
                "entity_id": eid,
                "typical_time": time_str
            })

        return patterns

    async def get_weather_history(
        self,
        db: Session,
        start_date: date,
        end_date: date
    ) -> Dict[date, Dict]:
        """
        Get historical weather data for pattern analysis.

        For now, uses cached data or fetches current weather.
        In production, would use a weather history API.
        """
        weather_history = {}

        try:
            # Try to get cached weather from day_replay_cache
            result = db.execute(
                text("""
                    SELECT replay_date, replay_data
                    FROM day_replay_cache
                    WHERE replay_date BETWEEN :start_date AND :end_date
                """),
                {"start_date": start_date, "end_date": end_date}
            ).fetchall()

            for row in result:
                replay_data = row.replay_data
                if isinstance(replay_data, str):
                    replay_data = json.loads(replay_data)

                # Extract weather if stored
                if "weather" in replay_data:
                    weather_history[row.replay_date] = replay_data["weather"]

        except Exception as e:
            logger.warning(f"Failed to get weather history: {e}")

        return weather_history

    async def run_detection_cycle(
        self,
        db: Session,
        user_id: str
    ) -> Dict[str, Any]:
        """
        Run a full pattern detection cycle.

        This is called during the nightly dream cycle.
        """
        from app.services.day_replay_builder import day_replay_builder

        logger.info(f"Starting pattern detection cycle for {user_id}")

        # Get replays from the last N days
        end_date = date.today() - timedelta(days=1)  # Yesterday
        start_date = end_date - timedelta(days=self.ANALYSIS_WINDOW_DAYS)

        replays = []
        current_date = start_date

        while current_date <= end_date:
            try:
                replay = await day_replay_builder.build_replay(db, user_id, current_date)
                if replay.total_events > 0:
                    replays.append(replay)
            except Exception as e:
                logger.warning(f"Failed to build replay for {current_date}: {e}")

            current_date += timedelta(days=1)

        if not replays:
            logger.info("No replay data available for pattern detection")
            return {"patterns_detected": 0, "message": "No data available"}

        # Get weather history
        weather_history = await self.get_weather_history(db, start_date, end_date)

        # Detect patterns
        patterns = await self.detect_patterns(db, user_id, replays, weather_history)

        return {
            "patterns_detected": len(patterns),
            "days_analyzed": len(replays),
            "patterns": patterns
        }


# Singleton instance
pattern_detector = PatternDetector()
