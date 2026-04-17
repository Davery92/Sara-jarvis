"""Pure parsing helpers for ACS LLM output.

The session loop produces a stream of structured JSON blocks interleaved with
narrative prose. This module owns extraction, done-detection, narrative
stripping, and conversation compression — all pure functions / small LLM
calls that don't need to live in the 4k-line session_manager.
"""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── JSON block extraction ──

def extract_json_blocks(output: str) -> list[dict]:
    """Extract JSON objects (with a `type` key) from output, one per line.

    Falls back to a regex sweep for inline `{...}` fragments if full-line
    JSON parse fails.
    """
    blocks: list[dict] = []
    for line in output.split("\n"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and "type" in obj:
                blocks.append(obj)
        except json.JSONDecodeError:
            match = re.search(r'\{[^{}]*"type"\s*:\s*"[^"]+?"[^{}]*\}', line)
            if match:
                try:
                    blocks.append(json.loads(match.group()))
                except json.JSONDecodeError:
                    pass
    return blocks


# ── Done detection ──

_DONE_STOP_PHRASES = (
    "nothing meaningful",
    "nothing to do",
    "no more",
    "stopping",
)


def _iter_done_blocks(output: str):
    """Yield parsed done blocks from output (ignores other block types)."""
    try:
        for line in output.strip().split("\n"):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                block = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(block, dict) and block.get("type") == "done":
                yield block
    except Exception:
        return


def output_signals_done(output: str, turn_had_real_activity: bool = True) -> bool:
    """Return True if a done block in `output` represents a real stop signal.

    A stop is signaled when:
      - the summary contains one of the explicit stop phrases, or
      - the turn produced no real activity and the summary is non-empty
        (Sara said 'done' without actually doing anything this turn).
    """
    for block in _iter_done_blocks(output):
        summary = block.get("summary", "") or ""
        if any(phrase in summary.lower() for phrase in _DONE_STOP_PHRASES):
            return True
        if not turn_had_real_activity and summary.strip():
            return True
    return False


def output_has_done_block(output: str) -> bool:
    """Return True if any {"type":"done"} block is present, regardless of content."""
    for _ in _iter_done_blocks(output):
        return True
    return False


# ── Narrative / transcript helpers ──

def strip_narrative(output: str) -> str:
    """Strip narrative prose from assistant output, keeping only JSON blocks.

    Used to compress older turns in conversation history so narration doesn't
    consume context budget across a long session.
    """
    lines = []
    for line in output.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("{"):
            try:
                obj = json.loads(stripped)
                if isinstance(obj, dict) and "type" in obj:
                    lines.append(stripped)
                    continue
            except json.JSONDecodeError:
                pass
    return "\n".join(lines) if lines else output[:200]


def extract_narrative(output: str) -> str:
    """Extract narrative prose, stripping JSON blocks. Capped at 800 chars."""
    lines = []
    for line in output.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("{"):
            try:
                obj = json.loads(stripped)
                if isinstance(obj, dict) and "type" in obj:
                    continue
            except json.JSONDecodeError:
                pass
        lines.append(stripped)
    return " ".join(lines)[:800]


def compress_older_turns(messages: list[dict]) -> list[dict]:
    """Compress older assistant turns by stripping narration; keep recent intact.

    Keeps the last 6 messages (3 turns) with full narration. Older assistant
    messages get narration stripped to just JSON blocks. Drops messages beyond
    21 to bound total size.
    """
    if len(messages) <= 6:
        return messages

    recent = messages[-6:]
    older = messages[-21:-6] if len(messages) > 21 else messages[:-6]

    compressed = []
    for msg in older:
        if msg.get("role") == "assistant":
            compressed.append({
                "role": "assistant",
                "content": strip_narrative(msg["content"]),
            })
        else:
            compressed.append(msg)

    return compressed + recent


async def compact_conversation(conversation: list[dict], model_id: str) -> str:
    """LLM-summarize old turns into a checkpoint instead of silently dropping them.

    Summarizes messages [1:-8] (keeps system prompt + last 4 turns unchanged).
    Returns the summary text, or a sentinel string on failure.
    """
    from app.core.llm import BackgroundLLMClient

    old_messages = conversation[1:-8]
    if not old_messages:
        return ""

    old_text_parts = []
    for msg in old_messages:
        role = msg.get("role", "?")
        content = (msg.get("content") or "")[:2000]
        if role == "tool":
            old_text_parts.append(f"[Tool result]: {content[:500]}")
        elif content:
            old_text_parts.append(f"[{role}]: {content}")
    old_text = "\n\n".join(old_text_parts)

    client = BackgroundLLMClient()
    compaction_prompt = (
        "Summarize this ACS session conversation into a compact recap covering:\n"
        "- What was accomplished (notes, tools, findings)\n"
        "- Current working state (files created, things built)\n"
        "- Decisions made and reasoning\n"
        "- What was being worked on most recently\n"
        "- Open questions or next steps\n"
        "Be specific — include file paths, note titles, concrete findings. Under 1500 tokens."
    )

    try:
        result = await client.chat_completion(
            messages=[
                {"role": "system", "content": compaction_prompt},
                {"role": "user", "content": old_text},
            ],
            temperature=0.3,
            max_tokens=2000,
            model=model_id,
            request_timeout=120.0,
            allow_during_lesson_generation=True,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        choices = result.get("choices", [])
        if choices:
            summary = choices[0].get("message", {}).get("content", "")
            if summary:
                return summary
    except Exception as e:
        logger.warning(f"Compaction LLM call failed: {e}")

    return "(Compaction failed — previous turns were trimmed to save context)"


def extract_files_from_transcript(transcript) -> list[str]:
    """Extract file paths from write_file/read_file tool calls in the transcript."""
    files: list[str] = []
    seen: set[str] = set()
    for entry in transcript.entries:
        if entry.get("type") == "tool_result" and entry.get("tool") in ("write_file", "read_file"):
            args_str = entry.get("args", "")
            try:
                args = json.loads(args_str) if args_str.startswith("{") else {}
                path = args.get("path", "")
            except (json.JSONDecodeError, AttributeError):
                path = ""
            if path and path not in seen:
                files.append(path)
                seen.add(path)
        if entry.get("type") == "assistant_turn" and entry.get("tool_calls"):
            for tc in entry["tool_calls"]:
                if tc.get("name") in ("write_file", "read_file"):
                    try:
                        args = json.loads(tc.get("args", "{}"))
                        path = args.get("path", "")
                    except (json.JSONDecodeError, AttributeError):
                        path = ""
                    if path and path not in seen:
                        files.append(path)
                        seen.add(path)
    return files
