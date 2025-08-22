"""
Habit Streak Service - Streak calculation with grace days and vacation handling
"""

from datetime import datetime, date, timedelta
from typing import List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class HabitStreakCalculator:
    """Calculates and manages habit streaks with grace days and vacation periods"""

    @staticmethod
    def calculate_streak(
        completion_dates: List[date],
        grace_days: int = 0,
        vacation_periods: List[Tuple[date, date]] = None,
        as_of_date: Optional[date] = None
    ) -> Tuple[int, int, Optional[date]]:
        """
        Calculate current and best streaks for a habit
        
        Args:
            completion_dates: List of dates when habit was completed
            grace_days: Number of grace days allowed for streak continuation
            vacation_periods: List of (start, end) vacation periods to ignore
            as_of_date: Calculate streak as of this date (defaults to today)
        
        Returns:
            (current_streak, best_streak, last_completed_date)
        """
        if not completion_dates:
            return 0, 0, None
        
        if as_of_date is None:
            as_of_date = date.today()
        
        # Sort completion dates
        sorted_dates = sorted(set(completion_dates))
        
        if not sorted_dates:
            return 0, 0, None
        
        vacation_periods = vacation_periods or []
        
        # Calculate current streak working backwards from as_of_date
        current_streak = HabitStreakCalculator._calculate_current_streak(
            sorted_dates, grace_days, vacation_periods, as_of_date
        )
        
        # Calculate best streak by finding longest consecutive sequence
        best_streak = HabitStreakCalculator._calculate_best_streak(
            sorted_dates, grace_days, vacation_periods
        )
        
        last_completed = sorted_dates[-1] if sorted_dates else None
        
        return current_streak, max(best_streak, current_streak), last_completed

    @staticmethod
    def _calculate_current_streak(
        completion_dates: List[date],
        grace_days: int,
        vacation_periods: List[Tuple[date, date]],
        as_of_date: date
    ) -> int:
        """Calculate current active streak"""
        if not completion_dates:
            return 0
        
        # Start from as_of_date and work backwards
        current_date = as_of_date
        streak = 0
        last_completion = None
        
        # Find the most recent completion
        for completion_date in reversed(completion_dates):
            if completion_date <= as_of_date:
                last_completion = completion_date
                break
        
        if not last_completion:
            return 0
        
        # Check if the gap between last completion and as_of_date breaks the streak
        gap_days = (as_of_date - last_completion).days
        
        # Account for vacation days in the gap
        vacation_days_in_gap = HabitStreakCalculator._count_vacation_days(
            last_completion + timedelta(days=1),
            as_of_date,
            vacation_periods
        )
        
        effective_gap = gap_days - vacation_days_in_gap
        
        # If gap exceeds grace days, no current streak
        if effective_gap > grace_days:
            return 0
        
        # Count consecutive days working backwards
        expected_date = last_completion
        
        for completion_date in reversed(completion_dates):
            # Check if this completion extends our streak
            if HabitStreakCalculator._extends_streak(
                completion_date, expected_date, grace_days, vacation_periods
            ):
                streak += 1
                expected_date = completion_date - timedelta(days=1)
            else:
                break
        
        return streak

    @staticmethod
    def _calculate_best_streak(
        completion_dates: List[date],
        grace_days: int,
        vacation_periods: List[Tuple[date, date]]
    ) -> int:
        """Calculate the best (longest) streak ever achieved"""
        if not completion_dates:
            return 0
        
        best_streak = 0
        current_streak = 0
        last_date = None
        
        for completion_date in completion_dates:
            if last_date is None:
                # First completion
                current_streak = 1
            else:
                # Check if this completion extends the streak
                if HabitStreakCalculator._extends_streak(
                    completion_date, last_date + timedelta(days=1), grace_days, vacation_periods
                ):
                    current_streak += 1
                else:
                    # Streak broken, start new streak
                    best_streak = max(best_streak, current_streak)
                    current_streak = 1
            
            last_date = completion_date
        
        # Don't forget the final streak
        best_streak = max(best_streak, current_streak)
        
        return best_streak

    @staticmethod
    def _extends_streak(
        completion_date: date,
        expected_date: date,
        grace_days: int,
        vacation_periods: List[Tuple[date, date]]
    ) -> bool:
        """Check if a completion date extends a streak from the expected date"""
        
        # If completion is exactly on expected date, it extends
        if completion_date == expected_date:
            return True
        
        # If completion is before expected date, check gap
        if completion_date < expected_date:
            gap_days = (expected_date - completion_date).days - 1
            
            # Count vacation days in the gap
            vacation_days = HabitStreakCalculator._count_vacation_days(
                completion_date + timedelta(days=1),
                expected_date - timedelta(days=1),
                vacation_periods
            )
            
            effective_gap = gap_days - vacation_days
            
            # Allow grace days
            return effective_gap <= grace_days
        
        # If completion is after expected date, it doesn't extend the streak
        return False

    @staticmethod
    def _count_vacation_days(
        start_date: date,
        end_date: date,
        vacation_periods: List[Tuple[date, date]]
    ) -> int:
        """Count vacation days within a date range"""
        if start_date > end_date:
            return 0
        
        vacation_days = 0
        
        for vacation_start, vacation_end in vacation_periods:
            # Find overlap between [start_date, end_date] and [vacation_start, vacation_end]
            overlap_start = max(start_date, vacation_start)
            overlap_end = min(end_date, vacation_end)
            
            if overlap_start <= overlap_end:
                vacation_days += (overlap_end - overlap_start).days + 1
        
        return vacation_days

    @staticmethod
    def update_streak_after_completion(
        current_streak: int,
        best_streak: int,
        last_completed: Optional[date],
        new_completion_date: date,
        grace_days: int = 0,
        vacation_periods: List[Tuple[date, date]] = None
    ) -> Tuple[int, int, date]:
        """
        Update streak counters after a new completion
        
        Returns: (new_current_streak, new_best_streak, last_completed_date)
        """
        vacation_periods = vacation_periods or []
        
        if last_completed is None:
            # First completion
            return 1, max(1, best_streak), new_completion_date
        
        # Don't allow completions in the past to break existing streaks
        if new_completion_date < last_completed:
            return current_streak, best_streak, last_completed
        
        # Check if new completion extends current streak
        expected_next_date = last_completed + timedelta(days=1)
        
        if HabitStreakCalculator._extends_streak(
            new_completion_date, expected_next_date, grace_days, vacation_periods
        ):
            # Extends current streak
            new_current = current_streak + 1
            new_best = max(best_streak, new_current)
        else:
            # Breaks current streak, start new streak
            new_current = 1
            new_best = best_streak  # Best streak unchanged
        
        return new_current, new_best, new_completion_date

    @staticmethod
    def get_streak_status(
        current_streak: int,
        last_completed: Optional[date],
        grace_days: int = 0,
        vacation_periods: List[Tuple[date, date]] = None,
        as_of_date: Optional[date] = None
    ) -> dict:
        """Get detailed streak status information"""
        if as_of_date is None:
            as_of_date = date.today()
        
        vacation_periods = vacation_periods or []
        
        if not last_completed or current_streak == 0:
            return {
                "status": "no_streak",
                "message": "No active streak",
                "days_until_break": 0,
                "is_at_risk": False
            }
        
        # Calculate days since last completion
        days_since = (as_of_date - last_completed).days
        
        # Account for vacation days
        vacation_days = HabitStreakCalculator._count_vacation_days(
            last_completed + timedelta(days=1),
            as_of_date,
            vacation_periods
        )
        
        effective_days_since = days_since - vacation_days
        days_until_break = grace_days - effective_days_since + 1
        
        if effective_days_since <= grace_days:
            if effective_days_since == 0:
                status = "current"
                message = f"🔥 {current_streak} day streak!"
            else:
                status = "grace_period"
                message = f"🔥 {current_streak} day streak (grace period)"
            
            is_at_risk = effective_days_since >= grace_days - 1
        else:
            status = "broken"
            message = "💔 Streak broken"
            days_until_break = 0
            is_at_risk = False
        
        return {
            "status": status,
            "message": message,
            "days_until_break": max(0, days_until_break),
            "is_at_risk": is_at_risk,
            "effective_days_since": effective_days_since,
            "vacation_days": vacation_days
        }