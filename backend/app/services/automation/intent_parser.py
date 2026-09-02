"""
Intent parser for natural language automation requests.

Uses LLM to parse user intent like "turn the heat on for an hour every two hours"
into structured automation task definitions.
"""
import logging
import json
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ParsedIntent:
    """Result of parsing a natural language automation request."""
    name: str
    description: str
    schedule_definition: Dict[str, Any]
    actions: list
    conditions: list
    expires_at: Optional[datetime]
    max_executions: Optional[int]
    confirmation_summary: str
    parse_confidence: float


INTENT_PARSE_PROMPT = """You are an automation intent parser. Parse the user's request into a structured automation task.

Available primitives (the ONLY actions automations can perform):
1. home_assistant - Control Home Assistant entities
   - entity_id: The HA entity (e.g., "light.office", "climate.thermostat", "switch.fan")
   - service: The service to call (e.g., "turn_on", "turn_off", "toggle", "set_hvac_mode", "set_temperature")
   - params: Optional parameters (e.g., {{"brightness": 255}}, {{"hvac_mode": "heat"}}, {{"temperature": 72}})

2. notify - Send a push notification to the user's phone
   - title: Notification title
   - message: Notification message
   - priority: "default", "high", or "urgent"

3. delay - Wait before the next action (sets next_wake_at)
   - seconds: Number of seconds to wait

4. store_state - Save a value for later comparison
   - key: State key name
   - value_source: {{"entity_id": "sensor.door"}} to fetch from HA, or omit for literal value
   - value: Literal value if not using value_source

5. check_state - Check stored state against a condition
   - key: State key to check
   - condition: "equals", "not_equals", "changed", "contains", "greater_than", "less_than"
   - expected: The expected value

6. http_request - Call a registered HTTP endpoint (must be pre-registered by admin)
   - endpoint_name: Name of registered endpoint
   - path: URL path
   - method: HTTP method (GET, POST, etc.)
   - body: Optional request body

Schedule types:
- interval: {{"type": "interval", "interval_seconds": N}}
- cron: {{"type": "cron", "cron_expr": "min hour dom mon dow"}}
- one_time: {{"type": "one_time", "run_at": "ISO8601 datetime"}}
- state_change: {{"type": "state_change", "entity_id": "...", "poll_interval_seconds": 300}}

Condition types (checked before each execution):
- time_window: {{"type": "time_window", "start": "HH:MM", "end": "HH:MM"}}
- day_of_week: {{"type": "day_of_week", "days": [0, 1, 2, 3, 4]}} (0=Monday, 6=Sunday)
- state_check: {{"type": "state_check", "entity_id": "...", "state": "..."}}

User's request: {user_request}

Current time: {current_time}
User's timezone: America/New_York

Parse this into a JSON object with:
{{
  "name": "Short descriptive name",
  "description": "What this automation will do",
  "schedule_definition": {{ schedule object }},
  "actions": [ list of action objects ],
  "conditions": [ optional list of condition objects ],
  "expires_hours": number (default 24, max 168 for 1 week),
  "max_executions": null or number (null = unlimited until expiration),
  "confirmation_summary": "Human-readable summary for user to confirm",
  "confidence": 0.0 to 1.0 (how confident you are in this parsing)
}}

If you cannot parse the request or it requires capabilities not available, set confidence to 0 and explain in description.

IMPORTANT:
- For "turn X on for Y time", use: [turn on action, delay Y seconds, turn off action]
- For monitoring/alerts, use: store_state + check_state + conditional notify
- Be conservative with intervals - minimum 1 minute (60 seconds)
- Default expiration is 24 hours unless user specifies otherwise

Respond with ONLY the JSON object, no other text."""


async def parse_automation_intent(
    user_request: str,
    llm_client=None,
    model: Optional[str] = None,
    available_entities: Optional[list] = None
) -> ParsedIntent:
    """
    Parse a natural language automation request into a structured task definition.

    Args:
        user_request: Natural language automation request
        llm_client: Optional LLM client (unused, uses httpx directly)
        model: Optional model override
        available_entities: Optional list of real Home Assistant entity dicts with entity_id and friendly_name
    """
    import httpx
    import os

    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Build entity context if available
    entity_context = ""
    if available_entities:
        # Group entities by domain for cleaner presentation
        by_domain = {}
        for entity in available_entities:
            entity_id = entity.get("entity_id", "")
            domain = entity_id.split(".")[0] if "." in entity_id else "unknown"
            if domain not in by_domain:
                by_domain[domain] = []
            friendly_name = entity.get("friendly_name", entity_id)
            by_domain[domain].append(f"{entity_id} ({friendly_name})")

        # Only include relevant domains for automations
        relevant_domains = ["light", "switch", "climate", "cover", "fan", "lock", "scene", "script", "sensor", "binary_sensor"]
        entity_lines = []
        for domain in relevant_domains:
            if domain in by_domain:
                entity_lines.append(f"\n{domain.upper()}:")
                for e in by_domain[domain][:20]:  # Limit to 20 per domain
                    entity_lines.append(f"  - {e}")
                if len(by_domain[domain]) > 20:
                    entity_lines.append(f"  ... and {len(by_domain[domain]) - 20} more")

        entity_context = f"""
AVAILABLE HOME ASSISTANT ENTITIES (use these exact entity_ids):
{''.join(entity_lines)}

IMPORTANT: Only use entity_ids from the list above. Match user intent to the closest entity."""

    # Explicit prompt with examples
    prompt = f"""Parse this automation request into JSON:

"{user_request}"

Current time: {current_time}
{entity_context}

SCHEDULE TYPES (pick one):
- For repeating tasks: {{"type": "interval", "interval_seconds": 7200}} (7200 = 2 hours)
- For specific times: {{"type": "cron", "cron_expr": "0 8 * * 1-5"}} (8am weekdays)
- For one-time: {{"type": "one_time", "run_at": "2024-01-29T15:00:00Z"}}

ACTION TYPES:
- home_assistant: {{"primitive": "home_assistant", "entity_id": "switch.heater", "service": "turn_on", "params": {{}}}}
- delay: {{"primitive": "delay", "seconds": 3600}} (wait 1 hour before next action)
- notify: {{"primitive": "notify", "title": "Alert", "message": "Something happened"}}

IMPORTANT for "turn X on for Y time every Z time":
- schedule_definition.interval_seconds = Z converted to seconds (e.g., 2 hours = 7200)
- actions = [turn_on, delay Y seconds, turn_off]

Return JSON:
{{
  "name": "short name",
  "description": "what it does",
  "schedule_definition": {{"type": "interval", "interval_seconds": <SECONDS>}},
  "actions": [<action objects>],
  "conditions": [],
  "expires_hours": 24,
  "max_executions": null,
  "confirmation_summary": "human readable summary",
  "confidence": 0.9
}}

Return ONLY valid JSON, no other text."""

    try:
        from app.core.llm_config import llm_config
        # Arc 6 broker migration (work-order item 2.5, 2026-07-30): resolve
        # "utility" instead of an OPENAI_MODEL env read, so a live
        # rename_model() DB update actually takes effect here.
        from app.services.llm_broker import resolve as _resolve_capability
        _cap = _resolve_capability("utility")
        # bg lane, not OPENAI_BASE_URL: in the backend process that env var is the
        # 1-slot CHAT lane (:8082). Automation parsing is not a chat turn.
        openai_base = _cap["base_url"] or llm_config.bg_primary_url
        openai_model = model or _cap["model"] or llm_config.fast_model
        openai_key = os.getenv("OPENAI_API_KEY", "")

        headers = {}
        if openai_key:
            headers["Authorization"] = f"Bearer {openai_key}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{openai_base}/chat/completions",
                json={
                    "model": openai_model,
                    "messages": [
                        {"role": "system", "content": "You are an automation parser. Return only valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 2000,
                    # Local qwen: disable thinking or `content` comes back empty.
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                headers=headers
            )
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]

        # Extract JSON from response
        parsed = _extract_json(content)

        if not parsed:
            return ParsedIntent(
                name="Parse Error",
                description="Failed to parse your request. Please try rephrasing.",
                schedule_definition={"type": "one_time", "run_at": datetime.now(timezone.utc).isoformat()},
                actions=[],
                conditions=[],
                expires_at=None,
                max_executions=None,
                confirmation_summary="Could not understand the request.",
                parse_confidence=0.0
            )

        # Calculate expiration
        expires_hours = parsed.get("expires_hours", 24)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=min(expires_hours, 168))

        return ParsedIntent(
            name=parsed.get("name", "Unnamed Automation"),
            description=parsed.get("description", ""),
            schedule_definition=parsed.get("schedule_definition", {"type": "one_time"}),
            actions=parsed.get("actions", []),
            conditions=parsed.get("conditions", []),
            expires_at=expires_at,
            max_executions=parsed.get("max_executions"),
            confirmation_summary=parsed.get("confirmation_summary", "Ready to activate."),
            parse_confidence=parsed.get("confidence", 0.5)
        )

    except Exception as e:
        logger.error(f"Intent parsing failed: {e}", exc_info=True)
        return ParsedIntent(
            name="Parse Error",
            description=f"Failed to parse request: {e}",
            schedule_definition={"type": "one_time", "run_at": datetime.now(timezone.utc).isoformat()},
            actions=[],
            conditions=[],
            expires_at=None,
            max_executions=None,
            confirmation_summary="An error occurred while parsing.",
            parse_confidence=0.0
        )


def _extract_json(content: str) -> Optional[Dict[str, Any]]:
    """Extract JSON object from LLM response."""
    # Try to find JSON block
    json_match = re.search(r'```json?\s*([\s\S]*?)\s*```', content)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try parsing the whole content as JSON
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in content
    brace_match = re.search(r'\{[\s\S]*\}', content)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass

    return None


def generate_confirmation_message(parsed: ParsedIntent) -> str:
    """
    Generate a human-friendly confirmation message for the user.

    Args:
        parsed: The parsed intent

    Returns:
        Confirmation message string
    """
    parts = [parsed.confirmation_summary, ""]

    # Schedule info
    schedule = parsed.schedule_definition
    schedule_type = schedule.get("type", "unknown")

    if schedule_type == "interval":
        interval_sec = schedule.get("interval_seconds", 0)
        if interval_sec >= 3600:
            interval_str = f"every {interval_sec // 3600} hour(s)"
        elif interval_sec >= 60:
            interval_str = f"every {interval_sec // 60} minute(s)"
        else:
            interval_str = f"every {interval_sec} seconds"
        parts.append(f"Schedule: {interval_str}")

    elif schedule_type == "cron":
        parts.append(f"Schedule: {schedule.get('cron_expr', 'custom cron')}")

    elif schedule_type == "one_time":
        run_at = schedule.get("run_at", "soon")
        parts.append(f"Runs once: {run_at}")

    elif schedule_type == "state_change":
        entity = schedule.get("entity_id", "unknown")
        poll = schedule.get("poll_interval_seconds", 300) // 60
        parts.append(f"Monitors: {entity} (checks every {poll} min)")

    # Actions summary
    action_count = len(parsed.actions)
    if action_count == 1:
        parts.append(f"Action: {_describe_action(parsed.actions[0])}")
    elif action_count > 1:
        parts.append(f"Actions: {action_count} steps")
        for i, action in enumerate(parsed.actions[:3], 1):
            parts.append(f"  {i}. {_describe_action(action)}")
        if action_count > 3:
            parts.append(f"  ...and {action_count - 3} more")

    # Conditions
    if parsed.conditions:
        cond_strs = [_describe_condition(c) for c in parsed.conditions]
        parts.append(f"Only when: {', '.join(cond_strs)}")

    # Expiration
    if parsed.expires_at:
        from zoneinfo import ZoneInfo
        est = ZoneInfo("America/New_York")
        expires_est = parsed.expires_at.astimezone(est)
        expires_str = expires_est.strftime("%Y-%m-%d %I:%M %p ET")
        parts.append(f"Expires: {expires_str}")

    if parsed.max_executions:
        parts.append(f"Max runs: {parsed.max_executions}")

    return "\n".join(parts)


def _describe_action(action: Dict[str, Any]) -> str:
    """Generate a short description of an action."""
    primitive = action.get("primitive", "unknown")

    if primitive == "home_assistant":
        entity = action.get("entity_id", "device")
        service = action.get("service", "control")
        return f"{service} {entity}"

    elif primitive == "notify":
        title = action.get("title", "notification")
        return f"send notification: {title}"

    elif primitive == "delay":
        seconds = action.get("seconds", 0)
        if seconds >= 3600:
            return f"wait {seconds // 3600}h"
        elif seconds >= 60:
            return f"wait {seconds // 60}m"
        return f"wait {seconds}s"

    elif primitive == "store_state":
        key = action.get("key", "value")
        return f"save state '{key}'"

    elif primitive == "check_state":
        key = action.get("key", "value")
        cond = action.get("condition", "check")
        return f"if {key} {cond}"

    elif primitive == "http_request":
        endpoint = action.get("endpoint_name", "endpoint")
        method = action.get("method", "GET")
        return f"{method} {endpoint}"

    return primitive


def _describe_condition(condition: Dict[str, Any]) -> str:
    """Generate a short description of a condition."""
    cond_type = condition.get("type", "unknown")

    if cond_type == "time_window":
        start = condition.get("start", "00:00")
        end = condition.get("end", "23:59")
        return f"{start}-{end}"

    elif cond_type == "day_of_week":
        days = condition.get("days", [])
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        day_strs = [day_names[d] for d in days if 0 <= d <= 6]
        return ", ".join(day_strs) or "any day"

    elif cond_type == "state_check":
        entity = condition.get("entity_id", "entity")
        state = condition.get("state", "state")
        return f"{entity} is {state}"

    return cond_type


async def validate_and_enhance_intent(
    parsed: ParsedIntent,
    available_entities: Optional[list] = None
) -> Tuple[ParsedIntent, list]:
    """
    Validate parsed intent and enhance with additional context.

    Args:
        parsed: The parsed intent to validate
        available_entities: Optional list of available HA entities for validation

    Returns:
        Tuple of (enhanced ParsedIntent, list of warnings/suggestions)
    """
    warnings = []

    # Check for empty actions
    if not parsed.actions:
        warnings.append("No actions defined - this automation won't do anything")

    # Validate HA entities if we have the list
    if available_entities:
        for action in parsed.actions:
            if action.get("primitive") == "home_assistant":
                entity_id = action.get("entity_id")
                if entity_id and entity_id not in available_entities:
                    warnings.append(f"Entity '{entity_id}' not found in Home Assistant")

    # Check for very short intervals
    schedule = parsed.schedule_definition
    if schedule.get("type") == "interval":
        interval = schedule.get("interval_seconds", 0)
        if interval < 60:
            warnings.append(f"Interval {interval}s is too short. Minimum is 60 seconds.")

    # Check for missing delay in "on for X time" patterns
    has_turn_on = any(
        a.get("primitive") == "home_assistant" and
        a.get("service") in ("turn_on", "set_hvac_mode") and
        a.get("params", {}).get("hvac_mode") in ("heat", "cool")
        for a in parsed.actions
    )
    has_delay = any(a.get("primitive") == "delay" for a in parsed.actions)
    has_turn_off = any(
        a.get("primitive") == "home_assistant" and
        a.get("service") in ("turn_off", "set_hvac_mode") and
        a.get("params", {}).get("hvac_mode") == "off"
        for a in parsed.actions
    )

    if has_turn_on and not has_delay and not has_turn_off:
        warnings.append("Detected 'turn on' without 'turn off' - device will stay on indefinitely")

    return parsed, warnings
