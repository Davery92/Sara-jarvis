"""
Automation status constants — single source of truth for automation_task.status values.

Used by: models/automation.py, tasks/automation.py, tools/automation.py, unified_agent.py
"""


class AutomationStatus:
    PENDING_CONFIRMATION = "pending_confirmation"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    TERMINAL = {COMPLETED, FAILED, CANCELLED}
    NON_TERMINAL = {PENDING_CONFIRMATION, ACTIVE, PAUSED}
    ALL = TERMINAL | NON_TERMINAL
