"""
Action Confidence Classification

Determines whether Sara should act directly, suggest, or just note an observation
based on confidence level and action reversibility.

Higher thresholds for interruptive/irreversible actions.
Lower thresholds for safe/reversible actions.
"""

import logging

logger = logging.getLogger(__name__)

# Thresholds by action type: (act_threshold, suggest_threshold)
# Below suggest_threshold → just note it in observations
THRESHOLDS = {
    "home_control": {"act": 0.7, "suggest": 0.4},       # Reversible (lights, thermostat)
    "notification": {"act": 0.85, "suggest": 0.6},       # Interruptive
    "reminder": {"act": 0.8, "suggest": 0.5},
    "calendar": {"act": 0.9, "suggest": 0.7},            # Hard to undo
    "message": {"act": 0.95, "suggest": 0.8},            # Sending messages is very high bar
    "health_alert": {"act": 0.75, "suggest": 0.5},       # Safety-sensitive, lower threshold
    "observation": {"act": 0.3, "suggest": 0.1},         # Always note observations
    "default": {"act": 0.8, "suggest": 0.5},
}


def classify_action_confidence(confidence: float, action_type: str) -> str:
    """
    Classify an action based on confidence level.

    Args:
        confidence: Float 0.0-1.0
        action_type: One of the keys in THRESHOLDS

    Returns:
        "act" — execute directly
        "suggest" — send "Should I...?" notification
        "note" — record in observations only
    """
    t = THRESHOLDS.get(action_type, THRESHOLDS["default"])

    if confidence >= t["act"]:
        return "act"
    elif confidence >= t["suggest"]:
        return "suggest"
    else:
        return "note"


def get_confidence_protocol_prompt() -> str:
    """Returns the confidence protocol text for the heartbeat system prompt"""
    return """
## Action Confidence Protocol
Before taking any action, assess your confidence (0.0-1.0) that the action is appropriate right now:

**Home Control** (reversible actions like lights, thermostat):
- >= 0.7: Act directly, report in summary ("I turned off the porch lights because it's past midnight")
- 0.4-0.7: Send "Should I...?" notification
- < 0.4: Note in observations

**Notifications** (interrupting David):
- >= 0.85: Send notification directly
- 0.6-0.85: Draft notification and note in observations for next check
- < 0.6: Just note it

**Reminders** (creating/modifying reminders):
- >= 0.8: Create reminder directly
- 0.5-0.8: Suggest via notification
- < 0.5: Note for later

**General Rule**: When in doubt, prefer "suggest" over "act". It's better to ask than to act wrongly.
The cost of an unnecessary notification is much lower than an unwanted action.
"""
