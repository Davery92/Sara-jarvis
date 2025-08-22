"""
Habit Scheduling Service - RRULE parsing and instance generation
"""

import json
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from dateutil.rrule import rrule, rrulestr, DAILY, WEEKLY, MONTHLY
import logging

logger = logging.getLogger(__name__)


class HabitScheduler:
    """Handles RRULE parsing and habit instance generation"""

    @staticmethod
    def parse_rrule(rrule_string: str) -> Optional[rrule]:
        """Parse RRULE string into dateutil rrule object"""
        try:
            # Handle simple frequency strings
            if rrule_string.upper() == "FREQ=DAILY":
                return rrule(DAILY)
            elif rrule_string.upper() == "FREQ=WEEKLY":
                return rrule(WEEKLY)
            elif rrule_string.upper() == "FREQ=MONTHLY":
                return rrule(MONTHLY)
            
            # Parse complex RRULE strings
            return rrulestr(rrule_string)
        except Exception as e:
            logger.error(f"Failed to parse RRULE '{rrule_string}': {e}")
            return None

    @staticmethod
    def generate_expected_dates(
        rrule_string: str,
        start_date: date,
        end_date: date,
        weekly_minimum: Optional[int] = None,
        pause_from: Optional[datetime] = None,
        pause_to: Optional[datetime] = None
    ) -> List[date]:
        """Generate list of expected dates for a habit"""
        
        rule = HabitScheduler.parse_rrule(rrule_string)
        if not rule:
            return []
        
        # Set rule to start from start_date
        rule = rule.replace(dtstart=datetime.combine(start_date, datetime.min.time()))
        
        expected_dates = []
        current_date = start_date
        
        while current_date <= end_date:
            # Check if date falls within RRULE
            rule_dates = list(rule.between(
                datetime.combine(current_date, datetime.min.time()),
                datetime.combine(current_date, datetime.max.time()),
                inc=True
            ))
            
            is_expected = len(rule_dates) > 0
            
            # Check if within pause period
            if pause_from and pause_to:
                pause_start = pause_from.date() if isinstance(pause_from, datetime) else pause_from
                pause_end = pause_to.date() if isinstance(pause_to, datetime) else pause_to
                
                if pause_start <= current_date <= pause_end:
                    is_expected = False
            
            if is_expected:
                expected_dates.append(current_date)
            
            current_date += timedelta(days=1)
        
        # Handle weekly minimum logic
        if weekly_minimum:
            expected_dates = HabitScheduler._apply_weekly_minimum(
                expected_dates, weekly_minimum, start_date, end_date
            )
        
        return expected_dates

    @staticmethod
    def _apply_weekly_minimum(
        expected_dates: List[date],
        weekly_minimum: int,
        start_date: date,
        end_date: date
    ) -> List[date]:
        """Apply weekly minimum logic to expected dates"""
        # Group dates by week and ensure weekly minimum is met
        weekly_groups = {}
        
        for d in expected_dates:
            # Get Monday of the week containing this date
            monday = d - timedelta(days=d.weekday())
            if monday not in weekly_groups:
                weekly_groups[monday] = []
            weekly_groups[monday].append(d)
        
        filtered_dates = []
        
        for monday, week_dates in weekly_groups.items():
            # If we have enough days in the week from RRULE, use them all
            if len(week_dates) >= weekly_minimum:
                filtered_dates.extend(week_dates)
            else:
                # If we don't have enough, we need to add more days from the week
                # This is a simplified approach - in practice you might want more sophisticated logic
                week_start = monday
                week_end = monday + timedelta(days=6)
                
                # Ensure we don't go outside our date range
                week_start = max(week_start, start_date)
                week_end = min(week_end, end_date)
                
                # Add consecutive days from start of week until we reach minimum
                current = week_start
                week_expected = []
                
                while current <= week_end and len(week_expected) < weekly_minimum:
                    week_expected.append(current)
                    current += timedelta(days=1)
                
                filtered_dates.extend(week_expected)
        
        return sorted(filtered_dates)

    @staticmethod
    def get_time_windows(windows_json: Optional[str]) -> List[Dict[str, str]]:
        """Parse time windows from JSON string"""
        if not windows_json:
            return [{
                "name": "All Day",
                "start": "00:00",
                "end": "23:59"
            }]
        
        try:
            windows = json.loads(windows_json)
            if not isinstance(windows, list):
                return []
            
            # Validate window format
            valid_windows = []
            for window in windows:
                if isinstance(window, dict) and all(k in window for k in ["name", "start", "end"]):
                    valid_windows.append(window)
            
            return valid_windows if valid_windows else [{
                "name": "All Day",
                "start": "00:00", 
                "end": "23:59"
            }]
            
        except json.JSONDecodeError:
            logger.error(f"Invalid windows JSON: {windows_json}")
            return [{
                "name": "All Day",
                "start": "00:00",
                "end": "23:59"
            }]

    @staticmethod
    def get_default_windows() -> List[Dict[str, str]]:
        """Get default time windows"""
        return [
            {"name": "Morning", "start": "06:00", "end": "12:00"},
            {"name": "Afternoon", "start": "12:00", "end": "17:00"},
            {"name": "Evening", "start": "17:00", "end": "22:00"}
        ]

    @staticmethod
    def is_within_time_window(current_time: datetime, window: Dict[str, str]) -> bool:
        """Check if current time falls within a time window"""
        try:
            start_time = datetime.strptime(window["start"], "%H:%M").time()
            end_time = datetime.strptime(window["end"], "%H:%M").time()
            current_time_only = current_time.time()
            
            if start_time <= end_time:
                # Normal window (e.g., 09:00-17:00)
                return start_time <= current_time_only <= end_time
            else:
                # Window crosses midnight (e.g., 22:00-06:00)
                return current_time_only >= start_time or current_time_only <= end_time
        except (ValueError, KeyError):
            # If window parsing fails, assume it's always valid
            return True

    @staticmethod
    def get_current_window(windows: List[Dict[str, str]], current_time: Optional[datetime] = None) -> Optional[str]:
        """Get the name of the current active time window"""
        if not current_time:
            current_time = datetime.now()
        
        for window in windows:
            if HabitScheduler.is_within_time_window(current_time, window):
                return window["name"]
        
        return None

    @staticmethod
    def should_generate_instance(
        habit_date: date,
        rrule_string: str,
        weekly_minimum: Optional[int] = None,
        pause_from: Optional[datetime] = None,
        pause_to: Optional[datetime] = None
    ) -> bool:
        """Check if an instance should be generated for a specific date"""
        expected_dates = HabitScheduler.generate_expected_dates(
            rrule_string=rrule_string,
            start_date=habit_date,
            end_date=habit_date,
            weekly_minimum=weekly_minimum,
            pause_from=pause_from,
            pause_to=pause_to
        )
        
        return habit_date in expected_dates