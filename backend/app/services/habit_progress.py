"""
Habit Progress Service - Progress calculation for all habit types
"""

import json
from datetime import datetime, date
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class HabitType(Enum):
    BINARY = "binary"
    QUANTITATIVE = "quantitative" 
    CHECKLIST = "checklist"
    TIME = "time"


class HabitStatus(Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    SKIPPED = "skipped"


class HabitProgressCalculator:
    """Calculates progress and completion status for all habit types"""

    @staticmethod
    def calculate_progress(
        habit_type: str,
        logs: List[Dict[str, Any]],
        target_numeric: Optional[float] = None,
        checklist_items: List[Dict[str, Any]] = None,
        checklist_mode: str = "all",
        checklist_threshold: float = 1.0
    ) -> Tuple[float, str, Optional[float]]:
        """
        Calculate progress for a habit based on its type and logs
        
        Returns: (progress_percentage, status, total_amount)
        - progress_percentage: 0.0 to 1.0
        - status: pending, complete, skipped
        - total_amount: raw amount for quantitative habits
        """
        
        if not logs:
            return 0.0, HabitStatus.PENDING.value, None
        
        habit_type_enum = HabitType(habit_type.lower())
        
        if habit_type_enum == HabitType.BINARY:
            return HabitProgressCalculator._calculate_binary_progress(logs)
        
        elif habit_type_enum == HabitType.QUANTITATIVE:
            return HabitProgressCalculator._calculate_quantitative_progress(
                logs, target_numeric
            )
        
        elif habit_type_enum == HabitType.CHECKLIST:
            return HabitProgressCalculator._calculate_checklist_progress(
                logs, checklist_items, checklist_mode, checklist_threshold
            )
        
        elif habit_type_enum == HabitType.TIME:
            return HabitProgressCalculator._calculate_time_progress(
                logs, target_numeric
            )
        
        else:
            logger.error(f"Unknown habit type: {habit_type}")
            return 0.0, HabitStatus.PENDING.value, None

    @staticmethod
    def _calculate_binary_progress(logs: List[Dict[str, Any]]) -> Tuple[float, str, None]:
        """Calculate progress for binary habits (done/not done)"""
        # For binary habits, any log entry means completion
        if logs:
            return 1.0, HabitStatus.COMPLETE.value, None
        return 0.0, HabitStatus.PENDING.value, None

    @staticmethod
    def _calculate_quantitative_progress(
        logs: List[Dict[str, Any]], 
        target: Optional[float]
    ) -> Tuple[float, str, Optional[float]]:
        """Calculate progress for quantitative habits (amounts with targets)"""
        if not target or target <= 0:
            logger.warning("Invalid target for quantitative habit")
            return 0.0, HabitStatus.PENDING.value, 0.0
        
        total_amount = 0.0
        
        for log in logs:
            try:
                # Parse payload to get amount
                if log.get('payload'):
                    payload = json.loads(log['payload']) if isinstance(log['payload'], str) else log['payload']
                    amount = payload.get('amount', 0.0)
                    if isinstance(amount, (int, float)):
                        total_amount += float(amount)
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning(f"Failed to parse log payload: {e}")
                continue
        
        progress = min(total_amount / target, 1.0)  # Cap at 100%
        status = HabitStatus.COMPLETE.value if progress >= 1.0 else HabitStatus.PENDING.value
        
        return progress, status, total_amount

    @staticmethod 
    def _calculate_checklist_progress(
        logs: List[Dict[str, Any]],
        checklist_items: Optional[List[Dict[str, Any]]],
        checklist_mode: str,
        checklist_threshold: float
    ) -> Tuple[float, str, None]:
        """Calculate progress for checklist habits"""
        if not checklist_items:
            logger.warning("No checklist items provided for checklist habit")
            return 0.0, HabitStatus.PENDING.value, None
        
        total_items = len(checklist_items)
        if total_items == 0:
            return 0.0, HabitStatus.PENDING.value, None
        
        # Track which items have been completed
        completed_items = set()
        
        for log in logs:
            try:
                if log.get('payload'):
                    payload = json.loads(log['payload']) if isinstance(log['payload'], str) else log['payload']
                    
                    # Handle different payload formats
                    if 'item_id' in payload:
                        completed_items.add(payload['item_id'])
                    elif 'completed_items' in payload:
                        # Bulk completion format
                        items = payload['completed_items']
                        if isinstance(items, list):
                            completed_items.update(items)
                    elif 'item_index' in payload:
                        # Index-based completion
                        completed_items.add(payload['item_index'])
                        
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning(f"Failed to parse checklist log payload: {e}")
                continue
        
        completed_count = len(completed_items)
        progress = completed_count / total_items
        
        # Determine completion based on mode
        if checklist_mode == "all":
            is_complete = completed_count == total_items
        elif checklist_mode == "percent":
            is_complete = progress >= checklist_threshold
        else:
            logger.warning(f"Unknown checklist mode: {checklist_mode}")
            is_complete = completed_count == total_items
        
        status = HabitStatus.COMPLETE.value if is_complete else HabitStatus.PENDING.value
        
        return progress, status, None

    @staticmethod
    def _calculate_time_progress(
        logs: List[Dict[str, Any]], 
        target_minutes: Optional[float]
    ) -> Tuple[float, str, Optional[float]]:
        """Calculate progress for time-bound habits"""
        if not target_minutes or target_minutes <= 0:
            logger.warning("Invalid target minutes for time habit")
            return 0.0, HabitStatus.PENDING.value, 0.0
        
        total_minutes = 0.0
        
        for log in logs:
            try:
                if log.get('payload'):
                    payload = json.loads(log['payload']) if isinstance(log['payload'], str) else log['payload']
                    
                    # Handle different time tracking formats
                    if 'duration_minutes' in payload:
                        duration = payload['duration_minutes']
                    elif 'timer_completed' in payload and payload['timer_completed']:
                        # Timer completion - use the timer's duration
                        duration = payload.get('timer_duration_minutes', target_minutes)
                    elif 'minutes' in payload:
                        duration = payload['minutes']
                    else:
                        # Default to target if no specific duration
                        duration = target_minutes
                    
                    if isinstance(duration, (int, float)):
                        total_minutes += float(duration)
                        
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning(f"Failed to parse time log payload: {e}")
                continue
        
        progress = min(total_minutes / target_minutes, 1.0)  # Cap at 100%
        status = HabitStatus.COMPLETE.value if progress >= 1.0 else HabitStatus.PENDING.value
        
        return progress, status, total_minutes

    @staticmethod
    def is_habit_complete(
        habit_type: str,
        logs: List[Dict[str, Any]],
        target_numeric: Optional[float] = None,
        checklist_items: List[Dict[str, Any]] = None,
        checklist_mode: str = "all",
        checklist_threshold: float = 1.0
    ) -> bool:
        """Check if a habit is complete based on its progress"""
        progress, status, _ = HabitProgressCalculator.calculate_progress(
            habit_type=habit_type,
            logs=logs,
            target_numeric=target_numeric,
            checklist_items=checklist_items,
            checklist_mode=checklist_mode,
            checklist_threshold=checklist_threshold
        )
        
        return status == HabitStatus.COMPLETE.value

    @staticmethod
    def get_progress_summary(
        habit_type: str,
        progress: float,
        total_amount: Optional[float],
        target: Optional[float],
        unit: Optional[str] = None
    ) -> str:
        """Generate a human-readable progress summary"""
        habit_type_enum = HabitType(habit_type.lower())
        
        if habit_type_enum == HabitType.BINARY:
            return "✅ Complete" if progress >= 1.0 else "⏳ Pending"
        
        elif habit_type_enum == HabitType.QUANTITATIVE:
            unit_str = unit or "units"
            if total_amount is not None and target:
                return f"{total_amount:.1f}/{target:.1f} {unit_str} ({progress:.0%})"
            return f"{progress:.0%} complete"
        
        elif habit_type_enum == HabitType.CHECKLIST:
            return f"{progress:.0%} of items completed"
        
        elif habit_type_enum == HabitType.TIME:
            unit_str = unit or "min"
            if total_amount is not None and target:
                return f"{total_amount:.0f}/{target:.0f} {unit_str} ({progress:.0%})"
            return f"{progress:.0%} complete"
        
        return f"{progress:.0%} complete"