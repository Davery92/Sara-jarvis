"""
Safety configuration and validation for automation tasks.

Enforces limits on execution frequency, task count, and resource usage
to prevent runaway automations.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AutomationSafetyConfig:
    """Safety limits for automation system."""

    # Task limits
    MAX_CONCURRENT_TASKS_PER_USER: int = 10
    MAX_CONCURRENT_TASKS_GLOBAL: int = 50

    # Execution frequency limits
    MIN_INTERVAL_SECONDS: int = 60  # No faster than 1/minute
    MAX_EXECUTIONS_PER_HOUR: int = 30  # Rate limit per task

    # Error handling
    CONSECUTIVE_ERROR_LIMIT: int = 3  # Auto-pause after 3 failures in a row

    # Expiration
    DEFAULT_EXPIRATION_HOURS: int = 24
    MAX_EXPIRATION_DAYS: int = 7  # 1 week max

    # Complexity limits
    MAX_ACTIONS_PER_TASK: int = 10
    MAX_CONDITIONS_PER_TASK: int = 5
    MAX_DELAY_SECONDS: int = 86400  # 24 hours max delay between steps

    # Primitive-specific limits
    MAX_HTTP_TIMEOUT_SECONDS: int = 30
    MAX_NOTIFICATION_LENGTH: int = 1000

    # Allowed primitives
    ALLOWED_PRIMITIVES: Tuple[str, ...] = (
        "home_assistant",
        "notify",
        "delay",
        "store_state",
        "check_state",
        "http_request",
    )


class AutomationSafetyValidator:
    """Validates automation tasks against safety rules."""

    def __init__(self, config: Optional[AutomationSafetyConfig] = None):
        self.config = config or AutomationSafetyConfig()

    def validate_task(self, task_definition: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate a task definition before creation.

        Args:
            task_definition: Dict with schedule_definition, actions, conditions

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []

        # Validate schedule
        schedule = task_definition.get("schedule_definition", {})
        schedule_errors = self._validate_schedule(schedule)
        errors.extend(schedule_errors)

        # Validate actions
        actions = task_definition.get("actions", [])
        action_errors = self._validate_actions(actions)
        errors.extend(action_errors)

        # Validate conditions
        conditions = task_definition.get("conditions", [])
        condition_errors = self._validate_conditions(conditions)
        errors.extend(condition_errors)

        # Validate expiration
        expires_at = task_definition.get("expires_at")
        expiration_errors = self._validate_expiration(expires_at)
        errors.extend(expiration_errors)

        return len(errors) == 0, errors

    def _validate_schedule(self, schedule: Dict[str, Any]) -> List[str]:
        """Validate schedule definition."""
        errors = []

        schedule_type = schedule.get("type")
        if not schedule_type:
            errors.append("Schedule type is required")
            return errors

        valid_types = ("interval", "cron", "one_time", "state_change")
        if schedule_type not in valid_types:
            errors.append(f"Invalid schedule type: {schedule_type}. Must be one of: {valid_types}")
            return errors

        if schedule_type == "interval":
            interval = schedule.get("interval_seconds", 0)
            if interval < self.config.MIN_INTERVAL_SECONDS:
                errors.append(
                    f"Interval too short: {interval}s. "
                    f"Minimum is {self.config.MIN_INTERVAL_SECONDS}s (1 minute)"
                )

        elif schedule_type == "cron":
            cron_expr = schedule.get("cron_expr")
            if not cron_expr:
                errors.append("Cron expression is required for cron schedule")
            # Basic cron validation - should have 5 fields
            elif len(cron_expr.split()) != 5:
                errors.append(f"Invalid cron expression: {cron_expr}. Expected 5 fields (min hour dom mon dow)")

        elif schedule_type == "one_time":
            run_at = schedule.get("run_at")
            if not run_at:
                errors.append("run_at timestamp is required for one_time schedule")

        elif schedule_type == "state_change":
            entity_id = schedule.get("entity_id")
            if not entity_id:
                errors.append("entity_id is required for state_change schedule")
            # Verify polling interval is set
            poll_interval = schedule.get("poll_interval_seconds", 300)
            if poll_interval < self.config.MIN_INTERVAL_SECONDS:
                errors.append(
                    f"Poll interval too short: {poll_interval}s. "
                    f"Minimum is {self.config.MIN_INTERVAL_SECONDS}s"
                )

        return errors

    def _validate_actions(self, actions: List[Dict[str, Any]]) -> List[str]:
        """Validate action sequence."""
        errors = []

        if not actions:
            errors.append("At least one action is required")
            return errors

        if len(actions) > self.config.MAX_ACTIONS_PER_TASK:
            errors.append(
                f"Too many actions: {len(actions)}. "
                f"Maximum is {self.config.MAX_ACTIONS_PER_TASK}"
            )

        total_delay = 0
        for i, action in enumerate(actions):
            primitive = action.get("primitive")
            if not primitive:
                errors.append(f"Action {i}: primitive type is required")
                continue

            if primitive not in self.config.ALLOWED_PRIMITIVES:
                errors.append(
                    f"Action {i}: unknown primitive '{primitive}'. "
                    f"Allowed: {self.config.ALLOWED_PRIMITIVES}"
                )
                continue

            # Primitive-specific validation
            if primitive == "delay":
                delay = action.get("seconds", 0)
                if delay > self.config.MAX_DELAY_SECONDS:
                    errors.append(
                        f"Action {i}: delay too long: {delay}s. "
                        f"Maximum is {self.config.MAX_DELAY_SECONDS}s (24 hours)"
                    )
                if delay < 0:
                    errors.append(f"Action {i}: delay cannot be negative")
                total_delay += delay

            elif primitive == "home_assistant":
                if not action.get("entity_id"):
                    errors.append(f"Action {i}: entity_id is required for home_assistant")
                if not action.get("service"):
                    errors.append(f"Action {i}: service is required for home_assistant")

            elif primitive == "notify":
                message = action.get("message", "")
                if len(message) > self.config.MAX_NOTIFICATION_LENGTH:
                    errors.append(
                        f"Action {i}: notification message too long: {len(message)} chars. "
                        f"Maximum is {self.config.MAX_NOTIFICATION_LENGTH}"
                    )

            elif primitive == "http_request":
                if not action.get("endpoint_name"):
                    errors.append(f"Action {i}: endpoint_name is required for http_request")
                timeout = action.get("timeout_seconds", 30)
                if timeout > self.config.MAX_HTTP_TIMEOUT_SECONDS:
                    errors.append(
                        f"Action {i}: HTTP timeout too long: {timeout}s. "
                        f"Maximum is {self.config.MAX_HTTP_TIMEOUT_SECONDS}s"
                    )

            elif primitive == "store_state":
                if not action.get("key"):
                    errors.append(f"Action {i}: key is required for store_state")

            elif primitive == "check_state":
                if not action.get("key"):
                    errors.append(f"Action {i}: key is required for check_state")
                if not action.get("condition"):
                    errors.append(f"Action {i}: condition is required for check_state")

        # Warn if total delay is very long
        if total_delay > 3600:  # 1 hour
            logger.warning(
                f"Automation has {total_delay}s total delay between steps. "
                "This may cause unexpected behavior."
            )

        return errors

    def _validate_conditions(self, conditions: List[Dict[str, Any]]) -> List[str]:
        """Validate conditions."""
        errors = []

        if len(conditions) > self.config.MAX_CONDITIONS_PER_TASK:
            errors.append(
                f"Too many conditions: {len(conditions)}. "
                f"Maximum is {self.config.MAX_CONDITIONS_PER_TASK}"
            )

        for i, condition in enumerate(conditions):
            cond_type = condition.get("type")
            if not cond_type:
                errors.append(f"Condition {i}: type is required")
                continue

            valid_types = ("time_window", "state_check", "day_of_week")
            if cond_type not in valid_types:
                errors.append(
                    f"Condition {i}: unknown type '{cond_type}'. "
                    f"Allowed: {valid_types}"
                )

        return errors

    def _validate_expiration(self, expires_at: Optional[str]) -> List[str]:
        """Validate expiration time."""
        errors = []

        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                max_exp = datetime.now(exp_dt.tzinfo) + timedelta(days=self.config.MAX_EXPIRATION_DAYS)
                if exp_dt > max_exp:
                    errors.append(
                        f"Expiration too far in future. "
                        f"Maximum is {self.config.MAX_EXPIRATION_DAYS} days from now"
                    )
            except ValueError:
                errors.append(f"Invalid expiration timestamp format: {expires_at}")

        return errors

    async def check_user_task_limit(self, db, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        Check if user has room for another active task.

        Returns:
            Tuple of (can_create, error_message)
        """
        from sqlalchemy import text

        result = await db.execute(
            text("""
                SELECT COUNT(*) FROM automation_task
                WHERE user_id = :user_id
                AND status IN ('pending_confirmation', 'active', 'paused')
            """),
            {"user_id": user_id}
        )
        count = result.scalar() or 0

        if count >= self.config.MAX_CONCURRENT_TASKS_PER_USER:
            return False, (
                f"Task limit reached: you have {count} active automations. "
                f"Maximum is {self.config.MAX_CONCURRENT_TASKS_PER_USER}. "
                "Please cancel or complete some tasks first."
            )

        return True, None

    async def check_global_task_limit(self, db) -> Tuple[bool, Optional[str]]:
        """
        Check if system has room for another active task.

        Returns:
            Tuple of (can_create, error_message)
        """
        from sqlalchemy import text

        result = await db.execute(
            text("""
                SELECT COUNT(*) FROM automation_task
                WHERE status IN ('active')
            """)
        )
        count = result.scalar() or 0

        if count >= self.config.MAX_CONCURRENT_TASKS_GLOBAL:
            return False, (
                f"System task limit reached: {count} active automations globally. "
                "Please try again later."
            )

        return True, None

    def should_pause_task(self, consecutive_errors: int) -> bool:
        """Check if task should be auto-paused due to errors."""
        return consecutive_errors >= self.config.CONSECUTIVE_ERROR_LIMIT


# Global validator instance
safety_validator = AutomationSafetyValidator()


def get_safety_validator() -> AutomationSafetyValidator:
    """Get the global safety validator instance."""
    return safety_validator
