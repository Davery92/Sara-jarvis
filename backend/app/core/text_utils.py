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
    """True for any self-hosted inference endpoint (LAN, Tailscale, loopback).

    Host-based rather than port-based: the Mac Studio lanes (:8081 bg, :8082
    chat), her (:8686/:8100/:11434) and anything on RFC1918 / 100.64/10 CGNAT
    (Tailscale) are local. Port hints kept for odd hostnames.
    """
    u = (base_url or "").lower()
    if "localhost" in u or "127.0.0.1" in u or "ollama" in u:
        return True
    m = re.search(r"https?://(\d+\.\d+\.\d+\.\d+)", u)
    if m:
        a, b = (int(x) for x in m.group(1).split(".")[:2])
        if a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168) or (a == 100 and 64 <= b <= 127):
            return True
    return any(p in u for p in ("11434", "8080", "8081", "8082", "8686"))


# Claude models that reject non-default sampling params (temperature/top_p/top_k)
# and budget_tokens — Anthropic returns HTTP 400 ("`temperature` is deprecated for
# this model.") if any are sent, on both the native /messages API and the
# OpenAI-compatible /chat/completions endpoint. Applies to Sonnet 5, Opus 4.7,
# Opus 4.8, Fable 5, and Mythos 5. Older Claude models (Opus 4.6, Sonnet 4.6,
# Haiku 4.5, and earlier) still accept these params.
_CLAUDE_NO_SAMPLING_MARKERS = ("opus-4-7", "opus-4-8", "sonnet-5", "fable-5", "mythos-5")


def claude_rejects_sampling_params(model_id: str) -> bool:
    """True if this Claude model 400s when temperature/top_p/top_k is supplied."""
    m = (model_id or "").lower()
    if not m.startswith("claude"):
        return False
    return any(marker in m for marker in _CLAUDE_NO_SAMPLING_MARKERS)


def claude_thinking_always_on(model_id: str) -> bool:
    """True for Claude models where thinking is always on and an explicit
    `thinking: {"type": "disabled"}` returns a 400 (Fable 5 / Mythos 5).
    For these, omit the `thinking` field entirely."""
    m = (model_id or "").lower()
    return ("fable-5" in m) or ("mythos-5" in m)


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


# A legal tool name is a bare identifier — anything else (markup fragments like
# "<function=calendar_list>") means the dialect parse went wrong and the "call"
# must be dropped, never sent to the registry.
_TOOL_NAME_RE = re.compile(r'^[A-Za-z_][\w\-\.]*$')


def _coerce_param_value(raw: str):
    """Best-effort typing for text-dialect parameter values: 'true' -> True,
    '3' -> 3, valid JSON -> parsed; anything else stays a string."""
    val = raw.strip()
    try:
        return json.loads(val)
    except (json.JSONDecodeError, ValueError):
        return val


def strip_tool_markup(content: str) -> str:
    """Remove any residual tool-call markup from user-visible text.

    Leak guard: models on the text-dialect path occasionally emit raw
    <tool_call>/<function=...>/<parameter=...> blocks that were not salvaged
    into real tool calls. Those must never reach the user."""
    if not content or '<' not in content:
        return content
    cleaned = re.sub(r'<tool_call>.*?(?:</tool_call>|$)', '', content, flags=re.DOTALL)
    cleaned = re.sub(r'<function=[^>]*>.*?(?:</function>|$)', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'<parameter=[^>]*>|</parameter>|</function>|</tool_call>', '', cleaned)
    return cleaned.strip()


def parse_glm45_tool_calls(content: str) -> tuple[str, list]:
    """Parse XML-text tool calls (GLM-4.5 and Qwen3.x dialects) into OpenAI JSON format.

    GLM-4.5:  <tool_call>name <arg_key>k</arg_key><arg_value>v</arg_value></tool_call>
    Qwen3.x:  <tool_call> <function=name> <parameter=k> v </parameter> </function> </tool_call>

    The Qwen form is tolerant of missing </parameter>/</function> close tags —
    a parameter value runs until the next parameter, the function close, or the
    end of the block.
    """
    tool_call_pattern = r'<tool_call>(.*?)(?:</tool_call>|$)'
    matches = re.findall(tool_call_pattern, content, re.DOTALL)

    if not matches:
        return content, []

    tool_calls = []
    for match in matches:
        match = match.strip()
        if not match:
            logger.warning("Empty tool_call block found")
            continue

        # Qwen3.x dialect: <function=name> ... <parameter=key> value </parameter> ...
        fn_tag = re.search(r'<function=([^>\s]+)\s*>', match)
        if fn_tag:
            function_name = fn_tag.group(1).strip()
            arguments = {}
            param_pattern = (
                r'<parameter=([^>\s]+)\s*>'          # key
                r'(.*?)'                              # value (lazy)
                r'(?=</parameter>|<parameter=|</function>|</tool_call>|$)'
            )
            for key, value in re.findall(param_pattern, match, re.DOTALL):
                arguments[key.strip()] = _coerce_param_value(value)
        else:
            # GLM-4.5 dialect: first token is the bare tool name
            parts = match.split()
            function_name = parts[0]
            arguments = {}
            keys = re.findall(r'<arg_key>(.*?)</arg_key>', match)
            values = re.findall(r'<arg_value>(.*?)</arg_value>', match)
            for key, value in zip(keys, values):
                arguments[key.strip()] = value.strip()

        if not _TOOL_NAME_RE.match(function_name):
            logger.warning(
                f"Dropping text tool call with malformed name {function_name!r} "
                f"(block: {match[:120]!r})"
            )
            continue

        tool_call = {
            "id": f"call_{str(uuid.uuid4())[:8]}",
            "type": "function",
            "function": {
                "name": function_name,
                "arguments": json.dumps(arguments) if arguments else "{}"
            }
        }
        tool_calls.append(tool_call)
        logger.info(f"Parsed text-dialect tool call: {function_name} with args: {arguments}")

    cleaned_content = re.sub(tool_call_pattern, '', content, flags=re.DOTALL).strip()
    think_pattern = r'<think>(.*?)</think>'
    think_matches = re.findall(think_pattern, cleaned_content, re.DOTALL)
    if think_matches:
        reasoning = " ".join([m.strip() for m in think_matches])
        logger.debug(f"Model reasoning: {reasoning[:100]}...")
        cleaned_content = re.sub(think_pattern, '', cleaned_content, flags=re.DOTALL).strip()
    cleaned_content = strip_tool_markup(cleaned_content)

    return cleaned_content, tool_calls


# Known tool names for JSON text parsing
_KNOWN_TOOLS = {
    'create_note', 'search_notes', 'edit_note', 'delete_note', 'list_notes',
    'notes_create', 'notes_search', 'notes_edit', 'notes_delete', 'notes_list',
    'notes_list_folders', 'notes_create_folder',
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
