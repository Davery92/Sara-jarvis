"""
Autonomy cycle state machine (Phase 1 — Cortana Evolution).

Defines the 6-phase cycle protocol: SENSE → PLAN → SIMULATE → EXECUTE → VERIFY → RECORD.
Also defines PlannedAction and ExecutionPlan dataclasses used by the structured plan parser.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CyclePhase(str, Enum):
    """Phases of the autonomy cycle."""
    SENSE = "sense"
    PLAN = "plan"
    SIMULATE = "simulate"
    EXECUTE = "execute"
    VERIFY = "verify"
    RECORD = "record"


class ActionDecision(str, Enum):
    """Policy decision on a planned action."""
    ALLOW = "allow"
    DENY = "deny"
    DEFER = "defer"


class RiskTier(int, Enum):
    """Risk classification for autonomous actions."""
    READ_ONLY = 0       # Always allow
    REVERSIBLE = 1      # Allow if confidence >= threshold or standing-order-covered
    IRREVERSIBLE = 2    # Requires explicit confirm or allowlisted standing order


@dataclass
class PlannedAction:
    """A single action in a structured execution plan."""
    action_name: str
    action_args: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    priority: int = 0  # 0 = highest
    risk_tier: Optional[int] = None  # Filled by policy engine
    simulation_result: Optional[Dict[str, Any]] = None
    decision: Optional[str] = None  # allow/deny/defer
    decision_reason: Optional[str] = None
    execution_result: Optional[Dict[str, Any]] = None
    success: Optional[bool] = None
    duration_ms: Optional[int] = None


@dataclass
class PlannedNotification:
    """A notification planned by the LLM."""
    title: str
    message: str
    priority: str = "normal"
    category: str = "general"
    reason: str = ""


@dataclass
class ExecutionPlan:
    """Structured output from the PLAN phase."""
    actions: List[PlannedAction] = field(default_factory=list)
    notifications: List[PlannedNotification] = field(default_factory=list)
    observations: List[str] = field(default_factory=list)
    handoff_note: str = ""
    watching_for: str = ""
    reasoning: str = ""
    fallback: bool = False  # True if JSON parse failed and we fell back to 4-phase

    def to_json(self) -> Dict[str, Any]:
        """Serialize for storage in agent_run_log.plan_summary."""
        return {
            "actions": [
                {
                    "action_name": a.action_name,
                    "action_args": a.action_args,
                    "reason": a.reason,
                    "priority": a.priority,
                }
                for a in self.actions
            ],
            "notifications": [
                {
                    "title": n.title,
                    "message": n.message,
                    "priority": n.priority,
                    "category": n.category,
                    "reason": n.reason,
                }
                for n in self.notifications
            ],
            "observations": self.observations,
            "handoff_note": self.handoff_note,
            "watching_for": self.watching_for,
            "reasoning": self.reasoning,
            "fallback": self.fallback,
        }

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "ExecutionPlan":
        """Deserialize from agent_run_log.plan_summary."""
        return cls(
            actions=[
                PlannedAction(
                    action_name=a["action_name"],
                    action_args=a.get("action_args", {}),
                    reason=a.get("reason", ""),
                    priority=a.get("priority", 0),
                )
                for a in data.get("actions", [])
            ],
            notifications=[
                PlannedNotification(
                    title=n["title"],
                    message=n["message"],
                    priority=n.get("priority", "normal"),
                    category=n.get("category", "general"),
                    reason=n.get("reason", ""),
                )
                for n in data.get("notifications", [])
            ],
            observations=data.get("observations", []),
            handoff_note=data.get("handoff_note", ""),
            watching_for=data.get("watching_for", ""),
            reasoning=data.get("reasoning", ""),
            fallback=data.get("fallback", False),
        )


def parse_structured_plan(raw_text: str) -> Optional[ExecutionPlan]:
    """
    Parse structured JSON plan from LLM output.

    Expected format:
    ```json
    {
      "actions": [{"action_name": "...", "action_args": {...}, "reason": "..."}],
      "notifications": [{"title": "...", "message": "...", "priority": "..."}],
      "observations": ["..."],
      "handoff_note": "...",
      "watching_for": "..."
    }
    ```

    Returns None if parsing fails (caller should fall back to 4-phase behavior).
    """
    import json
    import re

    # Try to extract JSON from markdown code blocks
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw_text, re.DOTALL)
    if json_match:
        raw_json = json_match.group(1).strip()
    else:
        # Try to find raw JSON object
        brace_start = raw_text.find('{')
        if brace_start == -1:
            return None
        # Find matching closing brace
        depth = 0
        for i, c in enumerate(raw_text[brace_start:], brace_start):
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    raw_json = raw_text[brace_start:i + 1]
                    break
        else:
            return None

    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, UnboundLocalError):
        return None

    # Validate required structure
    if not isinstance(data, dict):
        return None

    try:
        return ExecutionPlan.from_json(data)
    except (KeyError, TypeError):
        return None
