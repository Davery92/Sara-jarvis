"""
Action Policy Engine (Phase 1 — Cortana Evolution).

Gates every autonomous action through risk-tier policy. Replaces/subsumes action_confidence.py.

Risk tiers:
  Tier 0 (read-only):    Always allow
  Tier 1 (reversible):   Allow if confidence >= 0.7 OR covered by standing order
  Tier 2 (irreversible): Requires explicit confirm or allowlisted standing order

Unknown tools default to Tier 2 (defer/deny) — forces explicit registration.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.services.autonomy.action_tracer import RISK_TIERS, DEFAULT_RISK_TIER, get_risk_tier

logger = logging.getLogger(__name__)


# Confidence threshold for Tier 1 actions without standing order coverage
TIER_1_CONFIDENCE_THRESHOLD = 0.7


@dataclass
class PolicyDecision:
    """Result of policy evaluation."""
    decision: str  # "allow", "deny", "defer"
    reason: str
    risk_tier: int
    standing_order_id: Optional[int] = None  # If covered by a standing order


class ActionPolicyEngine:
    """
    Evaluates whether an autonomous action should be allowed, denied, or deferred.

    Decision matrix:
    - Tier 0: Always allow (read-only)
    - Tier 1: Allow if confidence >= threshold OR standing order covers it
    - Tier 2: Only allow if an active standing order explicitly covers it
    - Unknown tool: Treat as Tier 2 (defer/deny)
    """

    def evaluate(
        self,
        action_name: str,
        action_args: Optional[Dict[str, Any]] = None,
        confidence: float = 0.5,
        standing_order_coverage: Optional[Dict[str, Any]] = None,
    ) -> PolicyDecision:
        """
        Evaluate whether an action should proceed.

        Args:
            action_name: The tool/action name
            action_args: Arguments to the action
            confidence: LLM's confidence in the action (0.0-1.0)
            standing_order_coverage: Dict with standing order info if covered
                                     {"order_id": int, "confidence": float, "risk_tier": int}
        """
        risk_tier = get_risk_tier(action_name)

        # Tier 0: always allow read-only
        if risk_tier == 0:
            return PolicyDecision(
                decision="allow",
                reason="Read-only action, always allowed",
                risk_tier=risk_tier,
            )

        # Check standing order coverage
        covered_by_order = standing_order_coverage is not None
        order_id = standing_order_coverage.get("order_id") if covered_by_order else None

        # Tier 1: allow if confidence meets threshold OR standing order covers it
        if risk_tier == 1:
            if covered_by_order:
                return PolicyDecision(
                    decision="allow",
                    reason=f"Covered by standing order #{order_id}",
                    risk_tier=risk_tier,
                    standing_order_id=order_id,
                )
            if confidence >= TIER_1_CONFIDENCE_THRESHOLD:
                return PolicyDecision(
                    decision="allow",
                    reason=f"Confidence {confidence:.2f} >= threshold {TIER_1_CONFIDENCE_THRESHOLD}",
                    risk_tier=risk_tier,
                )
            return PolicyDecision(
                decision="defer",
                reason=f"Confidence {confidence:.2f} < threshold {TIER_1_CONFIDENCE_THRESHOLD}, no standing order",
                risk_tier=risk_tier,
            )

        # Tier 2 (irreversible / unknown): only allow with standing order
        if covered_by_order:
            return PolicyDecision(
                decision="allow",
                reason=f"Tier 2 action covered by standing order #{order_id}",
                risk_tier=risk_tier,
                standing_order_id=order_id,
            )

        # Hard safety gate: Tier 2 without standing order is always deferred
        if action_name not in RISK_TIERS:
            return PolicyDecision(
                decision="deny",
                reason=f"Unknown tool '{action_name}' (default Tier 2), not in risk matrix",
                risk_tier=risk_tier,
            )
        return PolicyDecision(
            decision="defer",
            reason="Tier 2 (irreversible) action requires standing order or explicit confirmation",
            risk_tier=risk_tier,
        )

    def evaluate_hard_safety_gate(self, action_name: str) -> Optional[PolicyDecision]:
        """
        Hard safety gate — always active, independent of POLICY_ENGINE flag.

        Returns a deny/defer decision if the action MUST be blocked, or None if it passes.
        This is a 5-line check called from _execute_tool() regardless of feature flags.
        """
        risk_tier = get_risk_tier(action_name)
        if risk_tier >= 2:
            return PolicyDecision(
                decision="deny",
                reason=f"Hard safety gate: Tier {risk_tier} action '{action_name}' blocked without standing order",
                risk_tier=risk_tier,
            )
        return None

    def is_covered_by_standing_order(
        self,
        action_name: str,
        action_args: Optional[Dict[str, Any]],
        standing_orders: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Check if an action is covered by any active standing order.

        Returns standing order info dict if covered, None otherwise.
        Matching is based on action_type + entity_id overlap.
        """
        entity_id = None
        if action_args:
            entity_id = action_args.get("entity_id") or action_args.get("device")

        for order in standing_orders:
            if order.get("status") != "active":
                continue
            order_action = order.get("action_type", "")
            order_config = order.get("action_config", {})

            # Match action type
            if order_action == action_name or order_config.get("tool") == action_name:
                # If order specifies an entity, must match
                order_entity = order_config.get("entity_id") or order_config.get("device")
                if order_entity and entity_id and order_entity != entity_id:
                    continue
                return {
                    "order_id": order.get("id"),
                    "confidence": order.get("confidence", 0.7),
                    "risk_tier": order.get("risk_tier", 1),
                }
        return None


# Module-level singleton
policy_engine = ActionPolicyEngine()
