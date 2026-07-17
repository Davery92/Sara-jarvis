"""
Action Simulator (Phase 1 — Cortana Evolution).

Precondition checks before executing an action:
- Entity exists (for HA actions)
- Bounds checking (temperature 60-80F for climate)
- Rate limiting (no duplicate actions within window)
- Conflict detection (standing order vs planned action)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SimulationCheck:
    """Result of a single precondition check."""
    name: str
    passed: bool
    reason: str


@dataclass
class SimulationResult:
    """Result of simulating an action."""
    allowed: bool
    checks: List[SimulationCheck] = field(default_factory=list)
    reason: str = ""

    def to_json(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "checks": [{"name": c.name, "passed": c.passed, "reason": c.reason} for c in self.checks],
            "reason": self.reason,
        }


# Bounds for climate control (Fahrenheit)
CLIMATE_TEMP_MIN = 60
CLIMATE_TEMP_MAX = 80

# Rate limit: same action on same entity within this window is duplicate
RATE_LIMIT_WINDOW_SECONDS = 300  # 5 minutes

# Actions that target HA entities
HA_ENTITY_ACTIONS = {
    "home_light_control",
    "home_switch_control",
    "home_lock_control",
    "home_climate_control",
}


class ActionSimulator:
    """Runs precondition checks on planned actions before execution."""

    async def simulate(
        self,
        action_name: str,
        action_args: Optional[Dict[str, Any]] = None,
        recent_traces: Optional[List[Dict[str, Any]]] = None,
        standing_order_actions: Optional[List[Dict[str, Any]]] = None,
    ) -> SimulationResult:
        """
        Simulate an action and check preconditions.

        Args:
            action_name: The tool/action name
            action_args: Arguments to the action
            recent_traces: Recent action traces for rate-limit checking
            standing_order_actions: Actions already taken by standing orders this cycle
        """
        checks = []
        args = action_args or {}

        # Check 1: Entity existence (for HA actions)
        if action_name in HA_ENTITY_ACTIONS:
            entity_id = args.get("entity_id") or args.get("device")
            if entity_id:
                check = await self._check_entity_exists(entity_id)
                checks.append(check)
                if not check.passed:
                    return SimulationResult(
                        allowed=False, checks=checks,
                        reason=f"Entity not found: {entity_id}",
                    )

        # Check 2: Bounds checking (climate)
        if action_name in ("home_climate_control",):
            temp = args.get("temperature")
            if temp is not None:
                check = self._check_temperature_bounds(temp)
                checks.append(check)
                if not check.passed:
                    return SimulationResult(
                        allowed=False, checks=checks,
                        reason=f"Temperature {temp}°F out of bounds [{CLIMATE_TEMP_MIN}-{CLIMATE_TEMP_MAX}]",
                    )

        # Check 3: Rate limiting
        if recent_traces:
            check = self._check_rate_limit(action_name, args, recent_traces)
            checks.append(check)
            if not check.passed:
                return SimulationResult(
                    allowed=False, checks=checks,
                    reason=f"Rate limit: duplicate action within {RATE_LIMIT_WINDOW_SECONDS}s",
                )

        # Check 4: Standing order conflict detection
        if standing_order_actions:
            check = self._check_standing_order_conflict(action_name, args, standing_order_actions)
            checks.append(check)
            if not check.passed:
                return SimulationResult(
                    allowed=False, checks=checks,
                    reason="Conflict: action already taken by standing order this cycle",
                )

        return SimulationResult(
            allowed=True, checks=checks,
            reason="All precondition checks passed",
        )

    async def _check_entity_exists(self, entity_id: str) -> SimulationCheck:
        """Check if a Home Assistant entity exists."""
        try:
            from app.services.ha_control_service import ha_control
            state = await ha_control.get_entity_state(entity_id)
            if state and state.get("state") != "unavailable":
                return SimulationCheck(
                    name="entity_exists", passed=True,
                    reason=f"Entity {entity_id} exists (state: {state.get('state', 'unknown')})",
                )
            return SimulationCheck(
                name="entity_exists", passed=False,
                reason=f"Entity {entity_id} unavailable or not found",
            )
        except Exception as e:
            # If HA is unreachable, fail open for non-critical or fail closed
            logger.warning(f"HA unreachable during entity check: {e}")
            return SimulationCheck(
                name="entity_exists", passed=False,
                reason=f"HA unreachable: {e}",
            )

    def _check_temperature_bounds(self, temperature: float) -> SimulationCheck:
        """Check if a temperature value is within safe bounds."""
        if CLIMATE_TEMP_MIN <= temperature <= CLIMATE_TEMP_MAX:
            return SimulationCheck(
                name="temperature_bounds", passed=True,
                reason=f"Temperature {temperature}°F within [{CLIMATE_TEMP_MIN}-{CLIMATE_TEMP_MAX}]",
            )
        return SimulationCheck(
            name="temperature_bounds", passed=False,
            reason=f"Temperature {temperature}°F outside [{CLIMATE_TEMP_MIN}-{CLIMATE_TEMP_MAX}]",
        )

    def _check_rate_limit(
        self,
        action_name: str,
        action_args: Dict[str, Any],
        recent_traces: List[Dict[str, Any]],
    ) -> SimulationCheck:
        """Check if the same action was executed recently (within rate limit window)."""
        entity_id = action_args.get("entity_id") or action_args.get("device")
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)

        for trace in recent_traces:
            if trace.get("action_name") != action_name:
                continue
            trace_args = trace.get("action_args") or {}
            trace_entity = trace_args.get("entity_id") or trace_args.get("device")
            if entity_id and trace_entity and entity_id != trace_entity:
                continue
            trace_time = trace.get("created_at")
            if isinstance(trace_time, str):
                try:
                    trace_time = datetime.fromisoformat(trace_time)
                except ValueError:
                    continue
            if trace_time and trace_time > cutoff:
                return SimulationCheck(
                    name="rate_limit", passed=False,
                    reason=f"Duplicate {action_name} on {entity_id or 'same target'} within {RATE_LIMIT_WINDOW_SECONDS}s",
                )

        return SimulationCheck(
            name="rate_limit", passed=True,
            reason="No recent duplicate",
        )

    def _check_standing_order_conflict(
        self,
        action_name: str,
        action_args: Dict[str, Any],
        standing_order_actions: List[Dict[str, Any]],
    ) -> SimulationCheck:
        """Check if this action was already taken by a standing order this cycle."""
        entity_id = action_args.get("entity_id") or action_args.get("device")

        for so_action in standing_order_actions:
            so_name = so_action.get("action_name") or so_action.get("tool")
            so_args = so_action.get("args", {})
            so_entity = so_args.get("entity_id") or so_args.get("device")

            if so_name == action_name:
                if not entity_id or not so_entity or entity_id == so_entity:
                    return SimulationCheck(
                        name="standing_order_conflict", passed=False,
                        reason=f"Already executed by standing order: {action_name} on {entity_id or 'target'}",
                    )

        return SimulationCheck(
            name="standing_order_conflict", passed=True,
            reason="No standing order conflict",
        )


# Module-level singleton
action_simulator = ActionSimulator()
