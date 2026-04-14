"""Text utility functions extracted from main_simple.py.

Pure functions with no global state dependencies — safe to import anywhere.
"""

import json
import logging
import re
import uuid
from typing import Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def extract_text_content(content) -> str:
    """Extract plain text from message content that may be a string or multimodal list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return str(content) if content else ""


def is_local_base_url(base_url: str) -> bool:
    u = (base_url or "").lower()
    return ("11434" in u) or ("8080" in u) or ("8686" in u) or ("ollama" in u) or ("localhost" in u)


def safe_parse_iso_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        from datetime import timezone
        candidate = value.strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        dt = datetime.fromisoformat(candidate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def parse_glm45_tool_calls(content: str) -> tuple[str, list]:
    """Parse GLM-4.5 XML-formatted tool calls and convert to OpenAI JSON format."""
    tool_call_pattern = r'<tool_call>(.*?)</tool_call>'
    matches = re.findall(tool_call_pattern, content, re.DOTALL)

    if not matches:
        return content, []

    tool_calls = []
    for match in matches:
        match = match.strip()
        parts = match.split()
        if not parts:
            logger.warning("Empty tool_call block found")
            continue

        function_name = parts[0]
        arguments = {}
        arg_key_pattern = r'<arg_key>(.*?)</arg_key>'
        arg_value_pattern = r'<arg_value>(.*?)</arg_value>'
        keys = re.findall(arg_key_pattern, match)
        values = re.findall(arg_value_pattern, match)
        for key, value in zip(keys, values):
            arguments[key.strip()] = value.strip()

        tool_call = {
            "id": f"call_{str(uuid.uuid4())[:8]}",
            "type": "function",
            "function": {
                "name": function_name,
                "arguments": json.dumps(arguments) if arguments else "{}"
            }
        }
        tool_calls.append(tool_call)
        logger.info(f"Parsed GLM-4.5 tool call: {function_name} with args: {arguments}")

    cleaned_content = re.sub(tool_call_pattern, '', content, flags=re.DOTALL).strip()
    think_pattern = r'<think>(.*?)</think>'
    think_matches = re.findall(think_pattern, cleaned_content, re.DOTALL)
    if think_matches:
        reasoning = " ".join([m.strip() for m in think_matches])
        logger.debug(f"GLM-4.5 reasoning: {reasoning[:100]}...")
        cleaned_content = re.sub(think_pattern, '', cleaned_content, flags=re.DOTALL).strip()

    return cleaned_content, tool_calls


# Known tool names for JSON text parsing
_KNOWN_TOOLS = {
    'create_note', 'search_notes', 'edit_note', 'delete_note', 'list_notes',
    'notes_create', 'notes_search', 'notes_edit', 'notes_delete', 'notes_list',
    'create_reminder', 'list_reminders', 'cancel_reminder',
    'reminders_create', 'reminders_list', 'reminders_cancel',
    'start_timer', 'timer_status', 'cancel_timer',
    'timers_start', 'timers_status', 'timers_cancel',
    'memory_search', 'search_memory',
    'web_search', 'open_page', 'get_page_details', 'get_web_search_details',
    'calendar_list', 'calendar_create', 'create_calendar_event',
    'food_log_create', 'food_log_search', 'food_log_summary', 'food_search_and_log',
    'workout_log_create', 'workout_list', 'workout_details', 'workout_stats',
    'fitness_note_create', 'fitness_note_search', 'fitness_note_edit', 'fitness_summary',
    'load_tool_categories',
    'knowledge_graph_search', 'find_connections', 'discover_knowledge_clusters', 'analyze_knowledge_gaps'
}


def parse_json_text_tool_calls(content: str) -> tuple[str, list]:
    """Parse tool calls that are output as JSON text in the response content."""
    tool_calls = []
    cleaned_content = content

    # Try markdown code blocks first
    code_block_pattern = r'```(?:json)?\s*(\{[^`]+\})\s*```'
    matches = re.findall(code_block_pattern, content, re.DOTALL)

    # Bare JSON objects at start
    if not matches:
        json_pattern = r'^\s*(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})'
        match = re.match(json_pattern, content.strip(), re.DOTALL)
        if match:
            matches = [match.group(1)]

    # JSON anywhere in content
    if not matches:
        json_pattern = r'(\{["\'](?:tool|name|function)["\']:\s*["\'][^"\']+["\'][^}]*\})'
        matches = re.findall(json_pattern, content, re.DOTALL)

    for match in matches:
        try:
            json_obj = json.loads(match)
            tool_name = None
            arguments = {}

            if 'tool' in json_obj:
                tool_name = json_obj.pop('tool')
                arguments = json_obj
            elif 'name' in json_obj:
                tool_name = json_obj.pop('name')
                if 'arguments' in json_obj:
                    arguments = json_obj['arguments'] if isinstance(json_obj['arguments'], dict) else json.loads(json_obj['arguments'])
                else:
                    arguments = json_obj
            elif 'function' in json_obj:
                tool_name = json_obj.pop('function')
                arguments = json_obj

            if tool_name and tool_name in _KNOWN_TOOLS:
                tool_call = {
                    "id": f"call_{str(uuid.uuid4())[:8]}",
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(arguments) if arguments else "{}"
                    }
                }
                tool_calls.append(tool_call)
                logger.info(f"Parsed JSON text tool call: {tool_name} with args: {arguments}")
                cleaned_content = cleaned_content.replace(match, '').strip()
                cleaned_content = re.sub(r'```(?:json)?\s*```', '', cleaned_content).strip()

        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse potential JSON tool call: {e}")
            continue

    cleaned_content = re.sub(r'```(?:json)?\s*```', '', cleaned_content).strip()
    return cleaned_content, tool_calls
