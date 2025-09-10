"""
Jarvis Monitors Package - Phase 4 TODO

This package contains proactive monitors that watch for patterns
and issues, feeding insights to the Jarvis inbox.

Monitors:
- calendar_monitor: Calendar conflicts and scheduling issues
- reminder_monitor: Overdue tasks and slippage patterns  
- habit_monitor: Habit streaks and opportunities

TODO: Implement in Phase 4
"""

from .calendar_monitor import calendar_monitor
# TODO: Add other monitors in Phase 4
# from .reminder_monitor import reminder_monitor  
# from .habit_monitor import habit_monitor

__all__ = ['calendar_monitor']