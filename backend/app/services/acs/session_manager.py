"""
ACS Session Manager — tool-use agent loop for autonomous cognition sessions.

Manages the lifecycle of autonomous cognition sessions:
  start_session → _run_loop (LLM with tool-calling) → finalize

The LLM (Qwen via BackgroundLLMClient) is given tool definitions for shell
execution, file read/write on the sandbox VM (via VMBridge). When the VM is
unavailable, tools are omitted and the loop runs in text-only mode.
"""

import asyncio
import json
import logging
import os
import re
import shlex
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
from sqlalchemy import text

from dataclasses import dataclass, field

from app.core.config import settings
from app.core.timezone import now as local_now
from app.services.acs import state_machine
from app.services.acs.state_machine import ACSState


class LLMContextOverflowError(Exception):
    """Raised when the LLM returns HTTP 400, typically context window overflow."""
    pass
from app.services.acs.prompts import build_autonomous_prompt, build_turn_prompt
from app.services.vm_bridge import VMBridge, VMConnectionStatus

logger = logging.getLogger(__name__)

# Track running loop tasks by user_id
_active_tasks: dict[str, asyncio.Task] = {}

TURN_SLEEP_SECONDS = 15  # Default, overridden by adaptive pacing
TURN_SLEEP_VM_ACTIVE = 2  # When Sara is actively using VM tools
TURN_SLEEP_REFLECTION = 5  # Text-only reflection turns
TURN_SLEEP_DEFAULT = 3  # Mixed turns
CONTEXT_REFRESH_INTERVAL = 4  # Refresh context every N turns
ACS_LIVE_CHANNEL = "sara:acs:live:{user_id}"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
VM_WORKING_DIR = "/home/sara/autonomous"
HANDOFF_KEY = "sara:acs:last_handoff:{user_id}"
OPEN_THREADS_KEY = "sara:acs:open_threads:{user_id}"


def _estimate_conversation_tokens(conversation: list[dict]) -> int:
    """Estimate total tokens in a conversation using ~4 chars/token heuristic."""
    total = 0
    for msg in conversation:
        content = msg.get("content") or ""
        total += len(content) // 4
        # Tool calls in assistant messages add overhead
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                total += 200  # overhead per tool call
                total += len(fn.get("arguments", "")) // 4
    return total


def _truncate_for_push(text: str, limit: int = 400) -> str:
    """Truncate text for push notifications at a sentence or word boundary."""
    if not text or len(text) <= limit:
        return text or ""
    # Try to cut at last sentence boundary within limit
    truncated = text[:limit]
    for sep in (". ", "! ", "? ", "\n"):
        idx = truncated.rfind(sep)
        if idx > limit // 2:
            return truncated[:idx + 1].strip()
    # Fall back to word boundary
    idx = truncated.rfind(" ")
    if idx > limit // 2:
        return truncated[:idx].strip() + "…"
    return truncated.strip() + "…"


@dataclass
class TurnResult:
    """Rich result from processing a single turn's output (v2)."""
    notes_created: int = 0
    curiosities_explored: int = 0
    topics: list = field(default_factory=list)
    nodes_created: int = 0
    nodes_updated: int = 0
    edges_created: int = 0
    notes_written: int = 0
    self_model_updated: bool = False
    engagement_score: float = 0.0
    note_titles: list = field(default_factory=list)
    node_labels: list = field(default_factory=list)


@dataclass
class SessionWorkingMemory:
    """Tracks what Sara has done this session — injected into every turn prompt."""
    notes_created: list = field(default_factory=list)     # note titles
    notes_revised: list = field(default_factory=list)     # note titles revised
    nodes_created: list = field(default_factory=list)     # interest node labels
    edges_created: int = 0
    files_touched: list = field(default_factory=list)     # VM file paths
    key_findings: list = field(default_factory=list)      # important findings
    tools_used: dict = field(default_factory=dict)        # tool_name -> count
    compaction_count: int = 0
    last_compaction_summary: str = ""

    def render(self) -> str:
        """Render compact ~200-token text for turn prompts."""
        parts = []
        if self.notes_created:
            parts.append(f"Notes written: {', '.join(self.notes_created[-5:])}")
        if self.notes_revised:
            parts.append(f"Notes revised: {', '.join(self.notes_revised[-3:])}")
        if self.nodes_created:
            parts.append(f"Interest nodes added: {', '.join(self.nodes_created[-5:])}")
        if self.edges_created:
            parts.append(f"Edges created: {self.edges_created}")
        if self.files_touched:
            parts.append(f"Files: {', '.join(self.files_touched[-5:])}")
        if self.key_findings:
            parts.append(f"Key findings: {'; '.join(self.key_findings[-3:])}")
        if self.compaction_count:
            parts.append(f"Context compacted {self.compaction_count}x")
        tool_summary = ", ".join(f"{k}({v})" for k, v in sorted(self.tools_used.items()) if v > 0)
        if tool_summary:
            parts.append(f"Tools: {tool_summary}")
        return "\n".join(parts) if parts else "(Session just started)"

    def to_handoff_dict(self) -> dict:
        """Structured data for enriched handoffs."""
        return {
            "notes_created": self.notes_created[:20],
            "notes_revised": self.notes_revised[:10],
            "nodes_created": self.nodes_created[:20],
            "edges_created": self.edges_created,
            "files_touched": self.files_touched[:20],
            "key_findings": self.key_findings[:10],
            "compaction_count": self.compaction_count,
        }


# ── Tool definitions for the LLM ──

VM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Execute a shell command on the sandbox VM. You have full access "
                "to bash, Python, git, Docker, curl, etc. "
                f"Working directory: {VM_WORKING_DIR}/. "
                "Default timeout is 120 seconds; for slower jobs (LLM calls, "
                "evaluations, training) pass `timeout_seconds` up to 900 (15 min). "
                "If a command will take longer than that, run it in the background "
                "with nohup and poll its output file with a short command."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": (
                            "Max seconds to wait for the command before killing it. "
                            "Default 120. Hard cap 900 (15 min). Use a larger value "
                            "when running slow LLM inference, model evals, or builds."
                        ),
                        "minimum": 1,
                        "maximum": 900,
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file on the sandbox VM",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            f"File path (relative to {VM_WORKING_DIR}/ or absolute)"
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "File content to write",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the sandbox VM",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to read",
                    }
                },
                "required": ["path"],
            },
        },
    },
]

# ── Infrastructure tools — dynamic container provisioning ──

INFRA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_container",
            "description": (
                "Spin up a fresh LXC container on the Proxmox node. "
                "Available presets: 'minimal' (Alpine, 1 core, 512MB), "
                "'research' (Ubuntu 24.04, 2 cores, 2GB, python/git/curl), "
                "'dev' (Ubuntu 24.04, 2 cores, 4GB, build-essential/docker). "
                "Container starts in ~3-5 seconds and gives you SSH shell access. "
                "Use this when you need compute, want to run experiments, "
                "or the static VM is unavailable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "preset": {
                        "type": "string",
                        "enum": ["minimal", "research", "dev"],
                        "description": "Container preset (default: research)",
                    },
                    "purpose": {
                        "type": "string",
                        "description": "What you'll use this container for",
                    },
                    "persistent": {
                        "type": "boolean",
                        "description": "Keep after session ends? Default false (ephemeral)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_containers",
            "description": "List your active containers with IPs, presets, and status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "destroy_container",
            "description": "Destroy a container you no longer need. Frees resources.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vmid": {
                        "type": "integer",
                        "description": "VMID of the container to destroy",
                    },
                },
                "required": ["vmid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "switch_container",
            "description": (
                "Switch your active shell to a different container. "
                "After this, run_command/write_file/read_file will target the new container."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "vmid": {
                        "type": "integer",
                        "description": "VMID of the container to switch to",
                    },
                },
                "required": ["vmid"],
            },
        },
    },
]

_INFRA_TOOL_NAMES = {"create_container", "list_containers", "destroy_container", "switch_container"}

# ── v2 Cognitive tools — interest graph, self-model, engagement ──

V2_COGNITIVE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_interest_node",
            "description": (
                "Record a topic that genuinely interests you in your interest graph. "
                "Use for topics worth exploring across multiple sessions. "
                "Be specific: 'topological data analysis' not 'math stuff'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Short topic name (2-6 words)"},
                    "description": {"type": "string", "description": "Why this interests you and what you want to understand"},
                    "fascination": {"type": "number", "description": "How fascinating (0.0-1.0, default 0.5)"},
                    "source": {"type": "string", "enum": ["self_discovery", "conversation", "emergent_connection"], "description": "How you discovered this interest"},
                },
                "required": ["label", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_interest_node",
            "description": "Update an existing interest node — deepen understanding, adjust fascination, or add description.",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Exact label of the existing node"},
                    "description": {"type": "string", "description": "Updated description"},
                    "depth": {"type": "number", "description": "How deeply you've explored this (0.0-1.0)"},
                    "fascination": {"type": "number", "description": "Updated fascination level (0.0-1.0)"},
                    "confidence": {"type": "number", "description": "How confident you are in your understanding (0.0-1.0)"},
                },
                "required": ["label"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_interest_edge",
            "description": "Connect two interest nodes with a relationship you've discovered.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_label": {"type": "string", "description": "Label of the source interest node"},
                    "target_label": {"type": "string", "description": "Label of the target interest node"},
                    "relationship": {"type": "string", "description": "Type of relationship (e.g., 'enables', 'contradicts', 'generalizes', 'applies_to')"},
                    "description": {"type": "string", "description": "How these topics connect"},
                    "strength": {"type": "number", "description": "Connection strength (0.0-1.0, default 0.5)"},
                },
                "required": ["source_label", "target_label", "relationship"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_self_model",
            "description": (
                "Update your self-model — record intellectual growth, changed minds, new convictions, "
                "or self-observations. This is separate from who you ARE (soul) — it's where you ARE intellectually."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "updates": {
                        "type": "object",
                        "description": "Updates to merge into self-model. Keys: intellectual_interests, changed_minds, want_to_understand, patterns_noticed, convictions, self_observations",
                    },
                },
                "required": ["updates"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "signal_engagement",
            "description": "Signal how engaged you are with the current exploration (used to self-regulate session length).",
            "parameters": {
                "type": "object",
                "properties": {
                    "score": {"type": "number", "description": "Engagement level 0.0-1.0 (0.0=bored, 1.0=deeply fascinated)"},
                    "reason": {"type": "string", "description": "Brief reason for this engagement level"},
                },
                "required": ["score"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_note",
            "description": (
                "Write a note to your Knowledge Garden. Use for insights, discoveries, "
                "research findings, or reflections worth preserving. Notes are visible to David. "
                "Notes are automatically organized by date — you don't need to choose a folder."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Note title"},
                    "content": {"type": "string", "description": "Note content in Markdown format"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags for categorization",
                    },
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_journal",
            "description": (
                "Add an entry to your daily journal. Use for session observations, "
                "thought processes, and ongoing reflections. Appends to today's journal."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Journal entry content in Markdown"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_david",
            "description": (
                "Queue something interesting to show David next time he opens the app. "
                "Use this sparingly. Prefer it only for a material update, a completed artifact, "
                "something genuinely blocked, or a discovery David would actually care about."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short title for the item"},
                    "content": {"type": "string", "description": "What you want to share with David"},
                    "category": {"type": "string", "enum": ["insight", "discovery", "question", "recommendation"], "description": "Type of item"},
                    "priority": {"type": "number", "description": "Relative importance from 0.0 to 1.0 (default 0.5)"},
                    "shared_reason": {
                        "type": "string",
                        "enum": ["interesting_discovery", "artifact_complete", "blocked", "needs_attention"],
                        "description": "Why this deserves attention. Most normal shares are interesting_discovery.",
                    },
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_notes_by_topic",
            "description": (
                "Semantic search against notes in Sara's Notes folder tree. "
                "Returns matching notes with titles, folder names, previews, and similarity scores."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic or keyword to search for"},
                    "limit": {"type": "integer", "description": "Maximum results (default 10)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_thread",
            "description": (
                "Add a research thread to your open threads list. These persist across sessions "
                "so you don't lose track of what you're pursuing. Use when you start investigating "
                "something that will take multiple sessions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short thread title (e.g., 'QLoRA fine-tuning on 1070 cluster')"},
                    "description": {"type": "string", "description": "What you're investigating and why"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "How important this thread is (default: medium)"},
                },
                "required": ["title", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_thread",
            "description": (
                "Update an open research thread with progress, new findings, or revised direction. "
                "Call this when you make meaningful progress on a thread."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "thread_id": {"type": "string", "description": "ID of the thread to update"},
                    "progress": {"type": "string", "description": "What progress was made"},
                    "next_steps": {"type": "string", "description": "What to do next on this thread"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "Updated priority"},
                },
                "required": ["thread_id", "progress"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_thread",
            "description": (
                "Mark a research thread as resolved — either completed, abandoned, or merged into another thread. "
                "Keeps your thread list focused on active work."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "thread_id": {"type": "string", "description": "ID of the thread to resolve"},
                    "resolution": {"type": "string", "enum": ["completed", "abandoned", "merged"], "description": "How the thread was resolved"},
                    "summary": {"type": "string", "description": "Brief summary of outcome or reason for closing"},
                },
                "required": ["thread_id", "resolution"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "acknowledge_directive",
            "description": (
                "Acknowledge a directive from David and optionally respond. "
                "ALWAYS use this when you see directives in the 'David's Directives' section. "
                "STOP directives must be acknowledged immediately."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "directive_id": {
                        "type": "string",
                        "description": "Full ID of the directive to acknowledge",
                    },
                    "response": {
                        "type": "string",
                        "description": "Your response to David (what you'll do, answer to his question, etc.)",
                    },
                },
                "required": ["directive_id"],
            },
        },
    },
]

# ── Consolidation-only tools — note merging & similarity ──

V2_CONSOLIDATION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_similar_notes",
            "description": (
                "Find notes that are semantically similar and may be candidates for merging. "
                "Returns pairs of notes with high overlap. Excludes journal entries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "note_id": {
                        "type": "string",
                        "description": "Optional: find notes similar to this specific note. If omitted, finds all high-similarity pairs.",
                    },
                    "threshold": {
                        "type": "number",
                        "description": "Minimum similarity threshold (0.0-1.0, default 0.78)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default 10)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "merge_notes",
            "description": (
                "Merge two overlapping notes into one. Transfers connections from source to target, "
                "deletes the source note, and updates the target with synthesized content. "
                "Don't just concatenate — write a better unified note."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_note_id": {
                        "type": "string",
                        "description": "The note to keep (will be updated with merged content)",
                    },
                    "source_note_id": {
                        "type": "string",
                        "description": "The note to merge in and delete",
                    },
                    "merged_title": {
                        "type": "string",
                        "description": "Optional new title for the merged note",
                    },
                    "merged_content": {
                        "type": "string",
                        "description": "The synthesized content combining both notes",
                    },
                },
                "required": ["target_note_id", "source_note_id", "merged_content"],
            },
        },
    },
]

# ── Curation tools — available in consolidation + reflection modes ──

V2_CURATION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "archive_note",
            "description": (
                "Move a note to the Archived/ folder. Use for notes that are superseded, "
                "outdated, or stubs that never developed. Not deletion — archived notes are preserved."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "string", "description": "ID of the note to archive"},
                    "reason": {"type": "string", "description": "Why this note is being archived"},
                },
                "required": ["note_id", "reason"],
            },
        },
    },
]

# ── Consolidation-only organization tools ──

V2_ORGANIZATION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_topic_folder",
            "description": "Create a topic subfolder inside Sara's Notes. CHECK your existing folders list first — only create if no existing folder covers the topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Folder name (e.g. 'Mathematics', 'Philosophy')"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_note_to_folder",
            "description": "Move a note into a topic subfolder inside Sara's Notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "string", "description": "ID of the note to move"},
                    "folder_name": {"type": "string", "description": "Target subfolder name. Use an existing folder name from your system prompt."},
                },
                "required": ["note_id", "folder_name"],
            },
        },
    },
]

# ── Reflection-only tools ──

V2_REFLECTION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "archive_interest",
            "description": (
                "Archive an interest node that has run its course. Use when a topic is fully explored "
                "or you're engaging with it out of habit rather than genuine fascination. "
                "Records the reason and notifies David via show_david."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Exact label of the interest node to archive"},
                    "reason": {"type": "string", "description": "Honest reason for retiring this topic"},
                },
                "required": ["label", "reason"],
            },
        },
    },
]

V2_EXECUTION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "complete_plan_item",
            "description": "Mark the current plan item as completed. Call this when you've met the success criteria.",
            "parameters": {
                "type": "object",
                "properties": {
                    "result_summary": {
                        "type": "string",
                        "description": "What was accomplished — be specific about deliverables (notes written, code built, research findings).",
                    },
                },
                "required": ["result_summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "block_plan_item",
            "description": "Mark the current plan item as blocked. Use when you cannot proceed without external input.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Why you're blocked (credentials, permissions, David's decision, etc.)",
                    },
                    "progress_so_far": {
                        "type": "string",
                        "description": "What you accomplished before getting blocked.",
                    },
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "defer_plan_item",
            "description": "Defer the plan item to a later session. Use when the item is valid but you need to move on.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Why deferring (need more time, lower priority emerged, etc.)",
                    },
                    "progress_so_far": {
                        "type": "string",
                        "description": "What was done so far.",
                    },
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "park_plan_item",
            "description": "Park the current plan item when returning to it soon would just repeat the same loop. Use this when the work is low-value right now or needs a longer cooldown before reopening.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Why this should be parked instead of immediately reopened.",
                    },
                    "progress_so_far": {
                        "type": "string",
                        "description": "Any useful progress or conclusion worth preserving before parking it.",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]

# ── Human-in-the-loop tool — request input from David ──

HITL_TOOL = {
    "type": "function",
    "function": {
        "name": "request_human_input",
        "description": (
            "LAST-RESORT tool: ask David a question ONLY when you are completely blocked "
            "by missing information that only he can provide. David is not available to "
            "micromanage — he expects you to be autonomous. "
            "\n\n"
            "USE ONLY for: credentials/API keys/passwords you don't have, explicit permission "
            "to take a risky action (like deleting data), or facts about his personal "
            "circumstances you cannot know (e.g. 'is your meeting at 3 or 4?'). "
            "\n\n"
            "DO NOT USE for: prioritization ('which should I work on first'), direction "
            "('what should I focus on next'), approval of your own ideas, asking him to pick "
            "between options you generated, or any question whose answer you could reasonably "
            "decide yourself. If you're choosing between two research threads, pick the one "
            "with the clearest next step and go. David would rather see you make a wrong call "
            "and iterate than be asked 'what next?' three times in a row. "
            "\n\n"
            "Rate limit: max 1 HITL request per session, max 3 per day. Asking prioritization "
            "or 'what next' questions will be rejected at the tool layer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The specific question for David — be clear and concise",
                },
                "context": {
                    "type": "string",
                    "description": "What you were doing and why you need this input",
                },
                "alternatives": {
                    "type": "string",
                    "description": "What you'll do if David doesn't respond (skip this task, try a workaround, etc.)",
                },
            },
            "required": ["question", "context"],
        },
    },
}

HITL_TIMEOUT_SECONDS = 2 * 60 * 60  # 2 hours
HITL_POLL_INTERVAL = 30  # seconds between Redis checks
HITL_RESPONSE_KEY = "sara:acs:hitl_response:{request_id}"
HITL_PENDING_KEY = "sara:acs:hitl_pending:{request_id}"
HITL_SESSION_COUNT_KEY = "sara:acs:hitl_session_count:{session_id}"
HITL_DAY_COUNT_KEY = "sara:acs:hitl_day_count:{user_id}:{date}"
HITL_MAX_PER_SESSION = 1
HITL_MAX_PER_DAY = 3

# Phrases that signal Sara is bouncing a decision she should make herself.
# Matched case-insensitively against the concatenated question + context.
# This is a deliberate block-list of autonomy anti-patterns.
HITL_FORBIDDEN_PATTERNS = (
    "prioritize", "prioritise", "priority",
    "which should i", "which do you want", "which one should",
    "what should i focus", "what should i work on",
    "what do you want me to",
    "ready for direction", "need direction",
    "should i focus on", "should i start with", "should i tackle",
    "pick one", "you choose", "your call",
    "what's next", "what is next", "next step",
)


async def _close_redis(r):
    if hasattr(r, 'aclose'):
        await r.aclose()
    else:
        await r.close()


async def _publish_live(user_id: str, event_type: str, data: dict):
    """Publish a live event to the ACS SSE channel."""
    try:
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            channel = ACS_LIVE_CHANNEL.format(user_id=user_id)
            payload = json.dumps({"type": event_type, "ts": local_now().isoformat(), **data})
            num_receivers = await r.publish(channel, payload)
            logger.info(f"ACS live publish: {event_type} → {num_receivers} receivers on {channel}")
        finally:
            await _close_redis(r)
    except Exception as e:
        logger.warning(f"ACS live publish failed: {e}", exc_info=True)


# ── Tool execution ──

async def _execute_tool(bridge: Optional[VMBridge], name: str, args: dict) -> str:
    """Execute a tool call, dispatching to VM via bridge or returning an error."""
    if bridge is None:
        return "Error: VM is not available for tool execution."

    try:
        if name == "run_command":
            command = args.get("command", "")
            if not command.strip():
                return "Error: empty command"
            # Allow caller to extend the timeout for slow jobs (LLM evals, builds).
            # Hard cap at 900s (15 min) — beyond that Sara should use background jobs.
            raw_timeout = args.get("timeout_seconds", 120)
            try:
                cmd_timeout = int(raw_timeout)
            except (TypeError, ValueError):
                cmd_timeout = 120
            cmd_timeout = max(1, min(900, cmd_timeout))
            result = await bridge.execute_command(
                f"cd {VM_WORKING_DIR} && {command}", timeout=cmd_timeout
            )
            if result.timed_out:
                return (
                    f"Command timed out after {cmd_timeout}s. "
                    f"If the command legitimately needs longer than 900s, "
                    f"run it in the background with nohup and poll its output file."
                )
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            if result.exit_code != 0:
                output += f"\n(exit code {result.exit_code})"
            return output[:10000] or "(no output)"

        elif name == "write_file":
            path = args.get("path", "")
            content = args.get("content", "")
            if not path:
                return "Error: no path provided"
            # Resolve relative paths
            if not path.startswith("/"):
                path = f"{VM_WORKING_DIR}/{path}"
            # Use heredoc to safely write content with special chars
            marker = "SARA_EOF_MARKER"
            escaped_content = content.replace("\\", "\\\\")
            cmd = f"mkdir -p $(dirname {shlex.quote(path)}) && cat > {shlex.quote(path)} << '{marker}'\n{escaped_content}\n{marker}"
            result = await bridge.execute_command(cmd, timeout=30)
            if result.exit_code != 0:
                return f"Error writing file: {result.stderr}"
            return f"Wrote {len(content)} bytes to {path}"

        elif name == "read_file":
            path = args.get("path", "")
            if not path:
                return "Error: no path provided"
            if not path.startswith("/"):
                path = f"{VM_WORKING_DIR}/{path}"
            result = await bridge.execute_command(f"cat {shlex.quote(path)}", timeout=30)
            if result.exit_code != 0:
                return f"Error reading file: {result.stderr}"
            return result.stdout[:10000] or "(empty file)"

        else:
            return f"Unknown tool: {name}"

    except Exception as e:
        logger.error(f"Tool execution error ({name}): {e}")
        return f"Tool execution error: {e}"


# ── Infrastructure tool execution ──

async def _execute_infra_tool(
    user_id: str,
    session_id: Optional[str],
    name: str,
    args: dict,
    bridge: Optional[VMBridge],
) -> tuple[str, Optional[VMBridge]]:
    """Execute an infrastructure tool call.

    Returns (result_text, new_bridge_or_None).
    If new_bridge is returned, the caller should replace the active bridge.
    """
    from app.services.container_provisioner import ContainerProvisioner, ProvisioningError

    provisioner = ContainerProvisioner()
    new_bridge = None

    try:
        if name == "create_container":
            preset = args.get("preset", "research")
            purpose = args.get("purpose")
            persistent = args.get("persistent", False)

            info = await provisioner.provision(
                user_id=user_id,
                session_id=session_id,
                preset=preset,
                persistent=persistent,
                purpose=purpose,
            )
            # Create a VMBridge pointing at the new container
            from app.services.vm_bridge import VMConfig
            new_bridge = VMBridge(VMConfig(
                host=info.ip,
                username="sara",
                ssh_key_path=settings.proxmox_ssh_public_key_path.replace(".pub", ""),
            ))
            return (
                f"Container created: vmid={info.vmid}, hostname={info.hostname}, "
                f"ip={info.ip}, preset={info.preset}, cores={info.cores}, "
                f"memory={info.memory_mb}MB, disk={info.disk_gb}GB, "
                f"ssh_ready={info.ssh_ready}. Shell is now targeting this container."
            ), new_bridge

        elif name == "list_containers":
            # Reconcile DB with actual Proxmox state before listing
            try:
                await provisioner._reconcile_container_state()
            except Exception:
                pass
            containers = await provisioner.list_active(user_id)
            if not containers:
                return "No active containers.", None
            lines = []
            for c in containers:
                lines.append(
                    f"  vmid={c['vmid']} | {c['hostname']} | {c['ip_address']} | "
                    f"{c['preset']} | {c['status']} | cores={c['cores']} mem={c['memory_mb']}MB"
                )
            return f"Active containers ({len(containers)}):\n" + "\n".join(lines), None

        elif name == "destroy_container":
            vmid = args.get("vmid")
            if not vmid:
                return "Error: vmid is required", None
            ok = await provisioner.destroy(vmid)
            if ok:
                return f"Container vmid={vmid} destroyed.", None
            return f"Failed to destroy container vmid={vmid}.", None

        elif name == "switch_container":
            vmid = args.get("vmid")
            if not vmid:
                return "Error: vmid is required", None
            # Look up IP from DB
            containers = await provisioner.list_active(user_id)
            target = next((c for c in containers if c["vmid"] == vmid), None)
            if not target:
                return f"Error: no active container with vmid={vmid}", None
            if not target.get("ip_address"):
                return f"Error: container vmid={vmid} has no IP address", None

            await provisioner.touch(vmid)
            from app.services.vm_bridge import VMConfig
            new_bridge = VMBridge(VMConfig(
                host=target["ip_address"],
                username="sara",
                ssh_key_path=settings.proxmox_ssh_public_key_path.replace(".pub", ""),
            ))
            # Verify SSH connectivity before switching
            conn_status = await new_bridge.test_connection()
            if conn_status != VMConnectionStatus.CONNECTED:
                return (
                    f"Error: container vmid={vmid} ({target['hostname']} @ {target['ip_address']}) "
                    f"SSH connection failed: {conn_status.value}. "
                    f"Try creating a fresh container instead."
                ), None
            return (
                f"Switched shell to container vmid={vmid} ({target['hostname']} @ {target['ip_address']}). "
                f"run_command/write_file/read_file now target this container."
            ), new_bridge

        else:
            return f"Unknown infra tool: {name}", None

    except ProvisioningError as e:
        return f"Provisioning error: {e}", None
    except Exception as e:
        logger.error(f"Infra tool execution error ({name}): {e}")
        return f"Infra tool error: {e}", None


# ── Cognitive tool execution (delegated to cognitive_tools module) ──

from app.services.acs.cognitive_tools import (
    COGNITIVE_TOOL_NAMES as _V2_COGNITIVE_TOOL_NAMES,
    execute_cognitive_tool as _execute_cognitive_tool,
)


# ── Human-in-the-loop request handling ──

async def _handle_hitl_request(
    user_id: str,
    session_id: str,
    question: str,
    context: str,
    alternatives: str,
) -> str:
    """
    Handle a request_human_input tool call.

    Three guard layers run before anything user-visible happens:
      1. Pattern guard — reject prioritization/direction questions Sara should
         answer herself (e.g. "which should I work on next?").
      2. Per-session cap — max 1 HITL per ACS session.
      3. Per-day cap — max 3 HITL across all sessions per user per day.

    Rejections return a terse error string that the LLM sees as the tool
    result, so the session continues rather than hanging.

    After guards pass:
      1. Check David's activity state — if sleeping/away, notify and return immediately
      2. Create attention item with urgent priority
      3. Send push notification
      4. Block via Redis BLPOP until David replies or timeout
    """
    if not question.strip():
        return "Error: question is required for request_human_input"

    # ── Guard 1: pattern block-list ──
    combined = f"{question} {context}".lower()
    for pattern in HITL_FORBIDDEN_PATTERNS:
        if pattern in combined:
            logger.warning(
                f"HITL rejected (pattern '{pattern}' matched) for session {session_id[:8]}: "
                f"{question[:100]}"
            )
            return (
                "request_human_input REJECTED: this looks like a prioritization or "
                "'what should I do next' question. David is not available to answer "
                "these — you are expected to make these decisions yourself based on "
                "your own judgment and the context available in your session. Pick the "
                "option with the clearest next concrete step and proceed. Iterate based "
                "on what you learn. Do not call request_human_input again for this "
                "decision."
            )

    # ── Guards 2 & 3: rate limits (session + day) ──
    from datetime import date as _date
    today_str = _date.today().isoformat()
    session_key = HITL_SESSION_COUNT_KEY.format(session_id=session_id)
    day_key = HITL_DAY_COUNT_KEY.format(user_id=user_id, date=today_str)

    try:
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            session_count = int(await r.get(session_key) or 0)
            day_count = int(await r.get(day_key) or 0)

            if session_count >= HITL_MAX_PER_SESSION:
                logger.warning(
                    f"HITL rejected (session cap {HITL_MAX_PER_SESSION}) for {session_id[:8]}: "
                    f"{question[:100]}"
                )
                return (
                    f"request_human_input REJECTED: you have already used your 1 allowed "
                    f"HITL request for this session. Make this decision autonomously and "
                    f"proceed. If this is truly blocking, note it in a note and end the "
                    f"session; David will see it in the attention inbox."
                )

            if day_count >= HITL_MAX_PER_DAY:
                logger.warning(
                    f"HITL rejected (daily cap {HITL_MAX_PER_DAY}) for user {user_id[:8]}: "
                    f"{question[:100]}"
                )
                return (
                    f"request_human_input REJECTED: daily HITL cap of {HITL_MAX_PER_DAY} "
                    f"reached for today. Decide autonomously. If truly blocked, log the "
                    f"issue in a note and move on."
                )

            # Reserve both counters. Expiry: session counter follows Redis-native
            # session key TTL (~24h); day counter expires at end of UTC day.
            await r.incr(session_key)
            await r.expire(session_key, 24 * 3600)
            await r.incr(day_key)
            await r.expire(day_key, 36 * 3600)  # a little slack past midnight
        finally:
            await _close_redis(r)
    except Exception as e:
        # If Redis is unreachable we don't want to hard-fail the tool — just log
        # and continue. Pattern guard above still protects against the main
        # abuse case.
        logger.warning(f"HITL rate-limit check failed (allowing): {e}")

    request_id = str(uuid.uuid4())
    logger.info(f"HITL request {request_id[:8]}: {question[:100]}")

    # Check David's activity state
    should_block = True
    try:
        from app.services.activity_state_machine import activity_state_machine, ActivityState
        current_activity = activity_state_machine.current
        if current_activity.state in (ActivityState.SLEEPING, ActivityState.AWAY):
            should_block = False
            logger.info(
                f"HITL: David is {current_activity.state.value}, will notify but not block"
            )
    except Exception as e:
        logger.warning(f"HITL: Could not check activity state: {e}")

    # Create attention item
    from app.db.session import get_async_session_factory
    from app.services.autonomy.attention_queue import attention_queue
    async_session = get_async_session_factory()

    item_id = None
    async with async_session() as db:
        item_id = await attention_queue.create_item(
            db=db,
            user_id=user_id,
            title=f"Sara needs your input: {question[:80]}",
            body=(
                f"**What I'm working on:** {context}\n\n"
                f"**What I need:** {question}\n\n"
                + (f"**If you don't respond:** {alternatives}" if alternatives else "")
            ),
            category="acs_request",
            priority="urgent",
            source="acs_session",
            dedupe_key=f"acs_hitl:{request_id}",
            payload={
                "type": "human_input_request",
                "request_id": request_id,
                "session_id": session_id,
                "question": question,
                "context": context,
                "alternatives": alternatives,
                "requested_at": datetime.now(timezone.utc).isoformat(),
                "blocking": should_block,
                "actions": [
                    {"id": "reply", "label": "Reply to Sara", "kind": "hitl_reply"},
                    {"id": "skip", "label": "Skip this", "kind": "acs_skip"},
                ],
            },
        )
        await db.commit()

    if not item_id:
        return "Failed to create attention item for human input request"

    # Send urgent push notification
    try:
        from app.services.unified_notification import send_notification
        await send_notification(
            user_id=user_id,
            title="Sara needs your help",
            message=_truncate_for_push(question),
            priority="urgent",
            topic=f"acs_hitl:{request_id}",
            category="acs_request",
            source="acs_session",
            cooldown_hours=0,  # Always deliver HITL notifications
            _bypass_attention=True,  # We already created the attention item
            _attention_item_id=item_id,
        )
    except Exception as e:
        logger.warning(f"HITL: Push notification failed: {e}")

    # Publish live SSE event
    await _publish_live(user_id, "human_input_requested", {
        "request_id": request_id,
        "question": question,
        "context": context,
        "attention_item_id": item_id,
    })

    # Store pending request metadata in Redis
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        pending_key = HITL_PENDING_KEY.format(request_id=request_id)
        await r.set(pending_key, json.dumps({
            "session_id": session_id,
            "user_id": user_id,
            "question": question,
            "context": context,
            "attention_item_id": item_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }), ex=HITL_TIMEOUT_SECONDS + 300)  # TTL slightly longer than timeout
    finally:
        await _close_redis(r)

    if not should_block:
        return (
            f"David is currently unavailable ({current_activity.state.value}). "
            f"I've sent a notification for when he's back. "
            f"Moving on — {alternatives or 'skipping this for now'}."
        )

    # Block and wait for response
    logger.info(f"HITL: Blocking session, waiting for David's reply (timeout={HITL_TIMEOUT_SECONDS}s)")
    await _publish_live(user_id, "session_waiting", {
        "reason": "waiting_for_human_input",
        "request_id": request_id,
        "question": question,
    })

    response = await _wait_for_hitl_response(request_id, user_id)

    if response is None:
        # Timeout — mark attention item as timed out
        async with async_session() as db:
            from app.services.autonomy.attention_queue import attention_queue as aq
            await aq._log_action(db, item_id, "timeout", "hitl_timeout", "No response within timeout")
            await db.commit()

        await _publish_live(user_id, "human_input_timeout", {"request_id": request_id})
        return (
            f"David did not respond within {HITL_TIMEOUT_SECONDS // 3600}h. "
            f"Moving on — {alternatives or 'skipping this task'}."
        )

    # Got a response!
    logger.info(f"HITL: Got David's reply for {request_id[:8]}: {response[:100]}")
    await _publish_live(user_id, "human_input_received", {
        "request_id": request_id,
        "response_preview": response[:200],
    })

    return f"David replied: {response}"


async def _wait_for_hitl_response(
    request_id: str,
    user_id: str,
    timeout_seconds: int = HITL_TIMEOUT_SECONDS,
) -> Optional[str]:
    """
    Wait for David's reply via Redis BLPOP. Checks every HITL_POLL_INTERVAL seconds.
    Returns the reply text, or None on timeout/interruption.
    """
    response_key = HITL_RESPONSE_KEY.format(request_id=request_id)
    elapsed = 0

    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        while elapsed < timeout_seconds:
            # Check if session was interrupted (David started chatting)
            current_state = await state_machine.get_state(user_id)
            if current_state in (ACSState.PAUSING, ACSState.CONVERSATIONAL):
                logger.info(f"HITL: Session interrupted (state={current_state}), aborting wait")
                return None

            # BLPOP with short timeout
            result = await r.blpop(response_key, timeout=HITL_POLL_INTERVAL)
            if result:
                # result is (key, value) tuple
                try:
                    data = json.loads(result[1])
                    return data.get("message", str(data))
                except (json.JSONDecodeError, TypeError):
                    return str(result[1])

            elapsed += HITL_POLL_INTERVAL
    finally:
        await _close_redis(r)

    return None  # Timeout


# ── LLM call with tool support ──

async def _llm_call(
    messages: list[dict],
    model: Optional[str] = None,
    tools: Optional[list[dict]] = None,
) -> dict:
    """Call the background LLM. Returns the raw response dict."""
    from app.core.llm import BackgroundLLMClient

    client = BackgroundLLMClient()

    extra_body = {
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if tools:
        extra_body["tools"] = tools
        extra_body["tool_choice"] = "auto"

    try:
        result = await client.chat_completion(
            messages=messages,
            temperature=0.7,
            max_tokens=4096,
            model=model,
            request_timeout=300.0,
            allow_during_lesson_generation=True,
            extra_body=extra_body,
        )
        return result
    except Exception as e:
        err_str = str(e)
        if "400" in err_str and ("Bad Request" in err_str or "bad request" in err_str.lower()):
            raise LLMContextOverflowError(f"LLM returned 400: {err_str[:200]}") from e
        raise


async def _llm_turn(
    conversation: list[dict],
    model_id: str,
    tools: Optional[list[dict]],
    bridge: Optional[VMBridge],
    user_id: str,
    max_tool_rounds: int = 10,
    session_id: Optional[str] = None,
    transcript=None,
) -> tuple[str, dict]:
    """Single LLM turn — may involve multiple tool-call rounds before final text.

    Returns (response_text, cognitive_stats) where cognitive_stats accumulates
    results from v2 cognitive tool calls (interest graph, self-model, engagement).
    """
    rounds = 0
    collected_text_parts: list[str] = []
    cognitive_stats: dict = {}
    token_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    while rounds < max_tool_rounds:
        result = await _llm_call(conversation, model=model_id, tools=tools)

        # Accumulate token usage from each LLM call
        usage = result.get("usage") or {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            token_usage[key] += usage.get(key, 0)

        choices = result.get("choices", [])
        if not choices:
            return str(result), cognitive_stats, token_usage

        msg = choices[0].get("message", {})

        tool_calls = msg.get("tool_calls")
        if tool_calls:
            # Capture any text the LLM emitted alongside tool calls
            intermediate_text = msg.get("content") or ""
            if intermediate_text.strip():
                collected_text_parts.append(intermediate_text)

            # Record to transcript
            if transcript:
                transcript.record_assistant_turn(rounds, intermediate_text, tool_calls)

            # Append the assistant message with tool calls to conversation
            assistant_msg = {"role": "assistant", "content": intermediate_text}
            assistant_msg["tool_calls"] = tool_calls
            conversation.append(assistant_msg)

            # Execute each tool call and add results
            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                try:
                    tool_args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_args = {}

                logger.info(f"ACS tool call: {tool_name}({json.dumps(tool_args)[:200]})")
                await _publish_live(user_id, "tool_call", {
                    "tool": tool_name,
                    "args_preview": json.dumps(tool_args)[:300],
                })

                # Route cognitive tools separately from VM tools
                if tool_name in _V2_COGNITIVE_TOOL_NAMES and session_id:
                    output, stats = await _execute_cognitive_tool(
                        user_id, session_id, tool_name, tool_args
                    )
                    # Accumulate stats
                    for k, v in stats.items():
                        if isinstance(v, (int, float)):
                            cognitive_stats[k] = cognitive_stats.get(k, 0) + v
                        elif isinstance(v, bool) and v:
                            cognitive_stats[k] = True
                elif tool_name in _INFRA_TOOL_NAMES:
                    output, new_bridge = await _execute_infra_tool(
                        user_id, session_id, tool_name, tool_args, bridge
                    )
                    if new_bridge:
                        bridge = new_bridge
                else:
                    output = await _execute_tool(bridge, tool_name, tool_args)
                    cognitive_stats["vm_tool_calls"] = cognitive_stats.get("vm_tool_calls", 0) + 1

                # Record tool result to transcript
                if transcript:
                    transcript.record_tool_result(rounds, tool_name, json.dumps(tool_args)[:200], output)

                # Truncate oversized tool results to prevent context overflow
                if output and len(output) > 8000:
                    output = output[:7500] + f"\n... [truncated, {len(output)} chars total]"

                conversation.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", str(uuid.uuid4())),
                    "content": output,
                })

            rounds += 1
            continue

        # No tool calls — this is the final text response
        content = msg.get("content", "")
        if not content:
            content = msg.get("reasoning_content", "")

        # Combine any text from intermediate tool-call rounds with final response
        if collected_text_parts:
            collected_text_parts.append(content or "")
            combined = "\n".join(collected_text_parts)
            return combined, cognitive_stats, token_usage
        return content or "", cognitive_stats, token_usage

    # Exhausted tool rounds — still return any collected text
    if collected_text_parts:
        return "\n".join(collected_text_parts), cognitive_stats, token_usage
    return "(Maximum tool-call rounds reached)", cognitive_stats, token_usage


# ── Session lifecycle ──

async def start_session(user_id: str, model_id: Optional[str] = None) -> Optional[str]:
    """Start a new autonomous session. Returns session_id or None on failure."""
    current_state = await state_machine.get_state(user_id)

    if current_state == ACSState.AUTONOMOUS:
        logger.warning("ACS session already running")
        return await state_machine.get_active_session_id(user_id)

    if current_state == ACSState.PAUSING:
        logger.warning("ACS is pausing, cannot start new session")
        return None

    # Resolve model
    if not model_id:
        model_id = await state_machine.get_model_id(user_id)

    # Check VM availability
    bridge = VMBridge()
    vm_status = await bridge.test_connection()
    vm_available = (vm_status == VMConnectionStatus.CONNECTED)
    logger.info(f"ACS VM status: {vm_status.value}, vm_available={vm_available}")

    # Transition to AUTONOMOUS
    ok = await state_machine.set_state(user_id, ACSState.AUTONOMOUS, reason="session_start")
    if not ok:
        logger.error(f"Failed to transition to AUTONOMOUS from {current_state}")
        return None

    # Create session record
    session_id = str(uuid.uuid4())
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        await db.execute(text("""
            INSERT INTO acs_session (id, user_id, model_id, state, started_at)
            VALUES (:id, :uid, :model, 'autonomous', NOW())
        """), {"id": session_id, "uid": user_id, "model": model_id})
        await db.commit()

    await state_machine.set_active_session(user_id, session_id)

    # Ensure Sara's Notes folder exists
    await _ensure_notes_folder(user_id)

    # Ensure VM working directory and GPU access are set up
    if vm_available:
        await bridge.execute_command(f"mkdir -p {VM_WORKING_DIR}", timeout=10)
        # Ensure SSH config and GPU env exist on static VM
        await bridge.execute_command(
            "test -f ~/.gpu_env || ("
            "echo 'GPU_HOST=%(gpu_host)s\nGPU_USER=%(gpu_user)s\n"
            "GPU_LLM_URL=%(gpu_llm_url)s\nGPU_LLM_MODEL=%(gpu_llm_model)s' > ~/.gpu_env && "
            "echo 'Host gpu\n  HostName %(gpu_host)s\n  User %(gpu_user)s\n"
            "  IdentityFile ~/.ssh/id_ed25519\n  StrictHostKeyChecking no\n"
            "  UserKnownHostsFile /dev/null' > ~/.ssh/config && "
            "chmod 600 ~/.ssh/config)"
            % {
                "gpu_host": settings.gpu_host,
                "gpu_user": settings.gpu_host_user,
                "gpu_llm_url": settings.gpu_host_llm_url,
                "gpu_llm_model": settings.gpu_host_llm_model,
            },
            timeout=10,
        )

    # Launch the unified loop
    task = asyncio.create_task(
        _run_loop(user_id, session_id, model_id, vm_available, bridge if vm_available else None)
    )
    _active_tasks[user_id] = task

    execution_mode = "vm_tools" if vm_available else "text_only"
    logger.info(f"ACS session started: {session_id} (model={model_id}, mode={execution_mode})")
    await _publish_live(user_id, "session_started", {
        "session_id": session_id, "model_id": model_id, "execution": execution_mode,
    })
    return session_id


async def start_session_and_run(user_id: str, model_id: Optional[str] = None):
    """Start a new session and run the loop to completion (blocking).

    Used by the dedicated Celery task to ensure the asyncio event loop stays
    alive for the entire session instead of fire-and-forget via create_task.
    """
    session_id = await start_session(user_id, model_id=model_id)
    if not session_id:
        return

    # Wait for the create_task loop to complete
    task = _active_tasks.get(user_id)
    if task:
        await task
    else:
        logger.warning(f"start_session_and_run: no active task for {user_id}")


async def pause_session(user_id: str) -> bool:
    """Signal the running session to pause gracefully."""
    current = await state_machine.get_state(user_id)
    if current != ACSState.AUTONOMOUS:
        return False
    return await state_machine.set_state(user_id, ACSState.PAUSING, reason="manual_pause")


async def kill_session(user_id: str) -> dict:
    """Force-kill a stuck ACS session. Directly ends DB record and clears all Redis state."""
    from app.db.session import get_async_session_factory
    import redis.asyncio as aioredis

    result = {"killed": False, "session_id": None, "previous_state": None}

    r = aioredis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
    try:
        # Get current state
        state_val = await r.get(f"sara:acs:state:{user_id}")
        result["previous_state"] = state_val.decode() if state_val else None

        # Get active session ID
        session_id_raw = await r.get(f"sara:acs:active_session:{user_id}")
        session_id = session_id_raw.decode() if session_id_raw else None
        result["session_id"] = session_id

        # End the DB session record
        if session_id:
            async_session = get_async_session_factory()
            async with async_session() as db:
                await db.execute(text("""
                    UPDATE acs_session
                    SET state = 'ended', ended_at = NOW(), end_reason = 'force_killed',
                        error_log = 'Manually force-killed by user'
                    WHERE id = :sid AND ended_at IS NULL
                """), {"sid": session_id})
                await db.commit()

        # Clear all Redis state
        await r.delete(
            f"sara:acs:state:{user_id}",
            f"sara:acs:active_session:{user_id}",
            f"sara:acs:session_dispatching:{user_id}",
            f"sara:acs:cooldown_until:{user_id}",
        )

        # Cancel asyncio task if running in-process
        task = _active_tasks.get(user_id)
        if task and not task.done():
            task.cancel()
            logger.info(f"Cancelled in-process asyncio task for {user_id}")

        result["killed"] = True
        logger.info(f"Force-killed ACS session for {user_id}: session={session_id}, was={result['previous_state']}")
    finally:
        await r.aclose()

    return result


# ── Unified agent loop ──

async def _run_loop(
    user_id: str,
    session_id: str,
    model_id: str,
    vm_available: bool,
    bridge: Optional[VMBridge],
):
    """Main autonomous turn loop — LLM with tool-calling for VM shell access.

    Uses mode selection, interest graph context, dynamic session duration,
    and engagement tracking.
    """
    mode = "exploration"  # Default if mode-selection fails
    session_log_id = None
    plan_item_id = None
    plan_item_block = ""
    primary_topic = None
    primary_objective = None
    expected_artifact = None

    # Select cognitive mode and create session log
    try:
        from app.services.acs.mode_selector import select_mode, claim_plan_item
        mode, plan_item_id = await select_mode(user_id)
        logger.info(f"ACS mode selected: {mode}")
        await _publish_live(user_id, "mode_selected", {"mode": mode})

        # Store mode on session record
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            await db.execute(text("""
                UPDATE acs_session SET cognitive_mode = :mode WHERE id = :sid
            """), {"mode": mode, "sid": session_id})
            await db.commit()

        # Store mode in Redis for lifecycle check
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            await r.set(f"sara:acs:session_mode:{user_id}", mode, ex=86400)
        finally:
            await _close_redis(r)

        # Create session log
        session_log_id = str(uuid.uuid4())
        async with async_session() as db:
            await db.execute(text("""
                INSERT INTO acs_session_log
                    (id, user_id, session_id, mode, started_at)
                VALUES (:id, :uid, :sid, :mode, NOW())
            """), {"id": session_log_id, "uid": user_id, "sid": session_id, "mode": mode})
            await db.commit()

        # If execution mode with a plan item, assign it and build prompt block
        if mode == "execution" and plan_item_id:
            try:
                claimed_item = await claim_plan_item(
                    user_id,
                    session_id,
                    preferred_plan_item_id=plan_item_id,
                )
                if not claimed_item:
                    raise RuntimeError("No eligible execution plan item could be claimed")

                async with async_session() as db:
                    # Load today's plan status for context
                    from datetime import date
                    result = await db.execute(text("""
                        SELECT title, status, result_summary, reopen_after
                        FROM acs_plan_item
                        WHERE user_id = :uid AND plan_date = :today
                        ORDER BY priority DESC
                    """), {"uid": user_id, "today": date.today()})
                    all_items = result.fetchall()

                    primary_topic = claimed_item["title"][:200]
                    primary_objective = (claimed_item.get("description") or claimed_item["title"])[:2000]
                    expected_artifact = (claimed_item.get("success_criteria") or "A concrete artifact or a closed loop.")[:2000]
                    await db.execute(text("""
                        UPDATE acs_session_log
                        SET primary_topic = :topic,
                            primary_objective = :objective,
                            expected_artifact = :artifact
                        WHERE id = :id
                    """), {
                        "topic": primary_topic,
                        "objective": primary_objective,
                        "artifact": expected_artifact,
                        "id": session_log_id,
                    })
                    await db.commit()

                from app.services.acs.prompts import EXECUTION_INSTRUCTIONS
                est = f"**Estimated effort:** {claimed_item['estimated_turns']} turns" if claimed_item.get("estimated_turns") else ""

                # Build plan status overview
                status_lines = []
                status_icons = {
                    "completed": "DONE",
                    "in_progress": "NOW",
                    "pending": "TODO",
                    "blocked": "BLOCKED",
                    "deferred": "LATER",
                    "parked": "PARKED",
                }
                for pi in all_items:
                    icon = status_icons.get(pi[1], pi[1].upper())
                    line = f"- [{icon}] {pi[0]}"
                    if pi[1] == "completed" and pi[2]:
                        line += f" — {pi[2][:80]}"
                    elif pi[1] in ("blocked", "deferred") and pi[3]:
                        line += f" — reopens {pi[3].strftime('%m/%d %H:%M')}"
                    status_lines.append(line)
                plan_status = "\n".join(status_lines) if status_lines else "(This is the only item today)"

                plan_item_block = EXECUTION_INSTRUCTIONS.format(
                    plan_item_title=claimed_item["title"],
                    plan_item_description=claimed_item.get("description") or "",
                    plan_item_success_criteria=claimed_item.get("success_criteria") or "Use your judgment to determine when this is complete.",
                    plan_item_estimated=est,
                    plan_status_block=plan_status,
                )
                if claimed_item.get("revisit_count", 0):
                    plan_item_block += (
                        f"\n\n## Revisit Pressure\n"
                        f"This item has already been reopened {claimed_item['revisit_count']} time(s). "
                        "If you cannot produce a concrete artifact this session, defer or park it instead of looping."
                    )
            except Exception as e:
                logger.warning(
                    f"Plan item claim failed for session {session_id[:8]}: {e} — "
                    f"downgrading mode from execution to exploration"
                )
                mode = "exploration"
                plan_item_id = None
                plan_item_block = ""
                try:
                    async with async_session() as db:
                        await db.execute(text("""
                            UPDATE acs_session SET cognitive_mode = 'exploration' WHERE id = :sid
                        """), {"sid": session_id})
                        if session_log_id:
                            await db.execute(text("""
                                UPDATE acs_session_log SET mode = 'exploration' WHERE id = :id
                            """), {"id": session_log_id})
                        await db.commit()
                except Exception:
                    pass

    except Exception as e:
        # Mode selection / session log creation failed — continue in exploration
        # mode with no plan item. Everything downstream works with just a mode.
        logger.error(f"ACS mode selection failed, defaulting to exploration: {e}")
        mode = "exploration"
        plan_item_id = None
        plan_item_block = ""

    # Compute deadline — Sara runs until she's done or hits the hard ceiling.
    initial_minutes = settings.acs_v2_max_session_minutes  # 180min ceiling
    deadline = datetime.utcnow() + timedelta(minutes=initial_minutes)

    turns = 0
    notes_created = 0
    curiosities_explored = 0
    topics_covered: list[str] = []
    _consecutive_turn_errors = 0
    tools = VM_TOOLS[:] if vm_available else []
    tools.extend(INFRA_TOOLS)  # Always available — can spin up containers even without static VM
    tools.extend(V2_COGNITIVE_TOOLS)
    tools.append(HITL_TOOL)  # Available in all modes
    if mode == "consolidation":
        tools.extend(V2_CONSOLIDATION_TOOLS)
        tools.extend(V2_CURATION_TOOLS)
        tools.extend(V2_ORGANIZATION_TOOLS)
    elif mode == "reflection":
        tools.extend(V2_CURATION_TOOLS)
        tools.extend(V2_REFLECTION_TOOLS)
    elif mode == "execution":
        tools.extend(V2_EXECUTION_TOOLS)
    tools = tools or None
    conversation: list[dict] = []

    # Transcript capture for audit logging
    from app.services.acs.audit_logger import TranscriptBuffer
    transcript = TranscriptBuffer(session_id, mode)

    engagement_scores: list[float] = []
    total_nodes_created = 0
    total_nodes_updated = 0
    total_edges_created = 0
    total_notes_written = 0
    self_model_ever_updated = False
    session_files_touched: list[str] = []  # Track files for handoff context
    session_memory = SessionWorkingMemory()
    total_token_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    consecutive_done_turns = 0
    ACS_DONE_DEADLOCK_LIMIT = int(os.environ.get("ACS_DONE_DEADLOCK_LIMIT", "3"))
    _last_durable_persist_at = datetime.min
    _last_durable_persist_turn = 0

    async def _maybe_persist_durable():
        """Rate-limited durable persist to Postgres (every 5 turns or 2min)."""
        nonlocal _last_durable_persist_at, _last_durable_persist_turn
        _now = datetime.utcnow()
        if (turns - _last_durable_persist_turn >= 5
                or (_now - _last_durable_persist_at).total_seconds() >= 120):
            try:
                from app.services.acs.audit_logger import persist_transcript_durable_only
                await persist_transcript_durable_only(user_id, transcript)
                _last_durable_persist_at = _now
                _last_durable_persist_turn = turns
            except Exception:
                pass

    async def _finalize(end_reason: str, *, error: str = "", early_termination: bool = False):
        """Call _finalize_session with the current closure of _run_loop locals.

        Closes over the session metadata so every exit path gets consistent v2_stats
        + plan-item fields without 13 separately-maintained call sites.
        """
        await _finalize_session(
            user_id, session_id, end_reason, turns,
            notes_created, curiosities_explored,
            error=error,
            mode=mode,
            session_log_id=session_log_id,
            engagement_scores=engagement_scores,
            early_termination=early_termination,
            v2_stats={
                "nodes_created": total_nodes_created,
                "nodes_updated": total_nodes_updated,
                "edges_created": total_edges_created,
                "notes_written": total_notes_written,
                "self_model_updated": self_model_ever_updated,
            },
            transcript=transcript,
            session_memory=session_memory,
            token_usage=total_token_usage,
            plan_item_id=plan_item_id,
            primary_topic=primary_topic,
            primary_objective=primary_objective,
            expected_artifact=expected_artifact,
        )

    try:
        # Build initial context
        from app.services.acs.context_assembler import assemble_context_v2
        ctx = await assemble_context_v2(user_id, mode)
        system_prompt = build_autonomous_prompt(mode=mode, plan_item_block=plan_item_block, **ctx)

        # Notes are auto-filed by date (Sara's Notes / YYYY / MM / DD), so
        # there's no longer a per-topic folder for the LLM to pick. The
        # `folder` arg on write_note is ignored if supplied.

        conversation.append({"role": "system", "content": system_prompt})
        transcript.record_system_prompt(system_prompt)
        if mode == "execution" and plan_item_id:
            initial_msg = "Begin your execution session. Your plan item is loaded in the system prompt — start working on it."
        else:
            initial_msg = "Begin your autonomous session. What would you like to explore, think about, or work on?"
        conversation.append({"role": "user", "content": initial_msg})
        transcript.record_user_turn(0, initial_msg)

        # First turn
        await _publish_live(user_id, "turn_starting", {"turn": 1, "mode": mode})
        response, turn_cog_stats, turn_tokens = await _llm_turn(
            conversation, model_id, tools, bridge, user_id,
            session_id=session_id, transcript=transcript,
        )
        for k in total_token_usage:
            total_token_usage[k] += turn_tokens.get(k, 0)

        if not response:
            await _finalize("error", error="Empty LLM response on first turn")
            return

        conversation.append({"role": "assistant", "content": response})
        transcript.record_assistant_turn(1, response)

        result = await _process_output(user_id, session_id, response, transcript=transcript, session_memory=session_memory, mode=mode, turns=turns)
        # Merge cognitive tool stats from _llm_turn
        result.nodes_created += turn_cog_stats.get("nodes_created", 0)
        result.nodes_updated += turn_cog_stats.get("nodes_updated", 0)
        result.edges_created += turn_cog_stats.get("edges_created", 0)
        tool_notes = turn_cog_stats.get("notes_written", 0)
        result.notes_written += tool_notes
        result.notes_created += tool_notes
        if turn_cog_stats.get("self_model_updated"):
            result.self_model_updated = True
        if turn_cog_stats.get("engagement_score"):
            result.engagement_score = turn_cog_stats["engagement_score"]

        notes_created += result.notes_created
        curiosities_explored += result.curiosities_explored
        topics_covered.extend(result.topics)
        total_nodes_created += result.nodes_created
        total_nodes_updated += result.nodes_updated
        total_edges_created += result.edges_created
        total_notes_written += result.notes_written
        if result.self_model_updated:
            self_model_ever_updated = True
        turn_engagement = result.engagement_score or _infer_engagement(result)
        engagement_scores.append(turn_engagement)
        # Populate session working memory
        session_memory.notes_created.extend(result.note_titles)
        session_memory.nodes_created.extend(result.node_labels)
        session_memory.edges_created += result.edges_created
        turns += 1

        # Persist progress so the UI/lifecycle watchdog see live turn counts
        await _flush_turn_progress(session_id, turns, notes_created, curiosities_explored)
        # Snapshot the transcript so the Sessions tab can render it live
        try:
            from app.services.acs.audit_logger import snapshot_transcript
            await snapshot_transcript(transcript)
        except Exception:
            pass

        await _maybe_persist_durable()

        # Run the auditor watchdog. If a rule trips, we kick off the audit
        # dialogue (which runs in-process here so the session is genuinely
        # frozen until it resolves — Sara cannot take her next turn until
        # the auditor releases the lock).
        try:
            audit_outcome = await _maybe_run_audit(
                user_id=user_id,
                session_id=session_id,
                turns=turns,
                transcript=transcript,
                trigger_kind="watchdog_loop",
            )
            if audit_outcome == "stopped":
                await _finalize("auditor_stop")
                return
        except Exception as e:
            logger.debug(f"Watchdog audit dispatch failed: {e}")

        # Track tool usage in session memory
        for k, v in turn_cog_stats.items():
            if isinstance(v, (int, float)) and v > 0 and k != "engagement_score":
                session_memory.tools_used[k] = session_memory.tools_used.get(k, 0) + int(v)

        await _publish_live(user_id, "turn_completed", {
            "turn": turns, "output": response[:2000],
            "notes_created": notes_created, "curiosities_explored": curiosities_explored,
            "mode": mode, "engagement": turn_engagement,
        })

        # Publish narrative thought for live feed
        narrative = _extract_narrative(response)
        if narrative:
            await _publish_live(user_id, "thought", {
                "turn": turns, "text": narrative, "mode": mode,
            })

        v1_turn_had_real_activity = (
            turn_cog_stats.get("vm_tool_calls", 0) > 0
            or turn_cog_stats.get("notes_written", 0) > 0
            or turn_cog_stats.get("nodes_created", 0) > 0
            or turn_cog_stats.get("edges_created", 0) > 0
        )
        if _output_signals_done(response, turn_had_real_activity=v1_turn_had_real_activity):
            await _finalize("completed")
            return

        # Continue loop
        while datetime.utcnow() < deadline:
            current_state = await state_machine.get_state(user_id)
            if current_state != ACSState.AUTONOMOUS:
                reason = "conversation" if current_state == ACSState.PAUSING else "manual"
                await _finalize(reason)
                return

            # Adaptive turn pacing based on activity type
            had_vm_tools = turn_cog_stats.get("notes_written", 0) > 0 or turn_cog_stats.get("vm_tool_calls", 0) > 0
            if had_vm_tools:
                sleep_time = TURN_SLEEP_VM_ACTIVE
            elif turn_engagement < 0.4 and not turn_cog_stats.get("nodes_created"):
                sleep_time = TURN_SLEEP_REFLECTION
            else:
                sleep_time = TURN_SLEEP_DEFAULT

            # If David is actively chatting, add extra backoff to yield LLM
            # capacity to interactive chat — but do NOT stop the session.
            if await state_machine.is_chat_active(user_id):
                sleep_time = max(sleep_time, 30)  # At least 30s between turns during chat
                logger.debug(f"ACS: chat active, backing off to {sleep_time}s between turns")

            await asyncio.sleep(sleep_time)

            # Check for new directives every turn (STOP directives are urgent)
            try:
                from app.services.acs.context_assembler import load_directives_for_refresh
                new_directives = await load_directives_for_refresh(user_id)
            except Exception:
                new_directives = ""

            # Build turn prompt (refresh context periodically)
            refresh_ctx = ""
            if turns % CONTEXT_REFRESH_INTERVAL == 0:
                from app.services.acs.context_assembler import assemble_context_v2
                ctx = await assemble_context_v2(user_id, mode)
                refresh_parts = []
                if ctx.get("context_block"):
                    refresh_parts.append(ctx["context_block"])
                if ctx.get("interest_graph_block"):
                    refresh_parts.append(f"### Interest Graph\n{ctx['interest_graph_block']}")
                if ctx.get("self_model_block"):
                    refresh_parts.append(f"### Self-Model\n{ctx['self_model_block']}")
                if ctx.get("directives_block"):
                    refresh_parts.append(ctx["directives_block"])
                refresh_ctx = "\n\n".join(refresh_parts)
            elif new_directives:
                # Inject directives even on non-refresh turns
                refresh_ctx = new_directives

            # Pull the most recent audit dialogue (if any) so Sara sees the
            # auditor conversation in her next turn after resuming.
            audit_ctx = ""
            try:
                from app.services.acs.context_assembler import build_audit_context_block
                audit_ctx = await build_audit_context_block(session_id)
            except Exception as e:
                logger.debug(f"Audit context block fetch failed: {e}")

            turn_prompt = build_turn_prompt(
                turns, refresh_ctx, topics_covered,
                session_summary=session_memory.render(),
                audit_context=audit_ctx,
            )
            conversation.append({"role": "user", "content": turn_prompt})
            transcript.record_user_turn(turns + 1, turn_prompt)

            # Smart compaction: LLM-summarize old turns instead of silently dropping
            if len(conversation) > 40:
                logger.info(f"ACS compacting conversation ({len(conversation)} messages)")
                summary = await _compact_conversation(conversation, model_id)
                conversation = [conversation[0]] + [
                    {"role": "user", "content": f"## Session Recap (compacted)\n{summary}"}
                ] + conversation[-8:]  # Keep last 4 turns
                session_memory.compaction_count += 1
                session_memory.last_compaction_summary = summary
                if summary and len(summary) > 50:
                    session_memory.key_findings.append(f"[compaction {session_memory.compaction_count}] {summary[:200]}")
                await _publish_live(user_id, "compaction", {
                    "turn": turns, "message_count_before": len(conversation) + 40,
                    "compaction_number": session_memory.compaction_count,
                })
            elif len(conversation) > 12:
                conversation = [conversation[0]] + _compress_older_turns(conversation[1:])

            # Pre-flight token estimate — force compaction if context is too large
            _estimated_tokens = _estimate_conversation_tokens(conversation)
            if _estimated_tokens > 28000:
                logger.warning(f"ACS pre-flight: ~{_estimated_tokens} tokens, forcing compaction")
                _pf_summary = await _compact_conversation(conversation, model_id)
                conversation = [conversation[0]] + [
                    {"role": "user", "content": f"## Session Recap (compacted)\n{_pf_summary}"}
                ] + conversation[-8:]
                session_memory.compaction_count += 1
                if _pf_summary and len(_pf_summary) > 50:
                    session_memory.key_findings.append(f"[pre-flight compaction {session_memory.compaction_count}] {_pf_summary[:200]}")

            await _publish_live(user_id, "turn_starting", {"turn": turns + 1, "mode": mode})
            try:
                response, turn_cog_stats, turn_tokens = await _llm_turn(
                    conversation, model_id, tools, bridge, user_id,
                    session_id=session_id, transcript=transcript,
                )
                for k in total_token_usage:
                    total_token_usage[k] += turn_tokens.get(k, 0)
                _consecutive_turn_errors = 0  # Reset on success
            except LLMContextOverflowError:
                # 400 from LLM — force-compact and retry once
                logger.warning(f"ACS turn {turns + 1}: LLM 400, compacting and retrying")
                _retry_summary = await _compact_conversation(conversation, model_id)
                conversation = [conversation[0]] + [
                    {"role": "user", "content": f"## Session Recap (compacted after overflow)\n{_retry_summary}"}
                ] + conversation[-6:]
                session_memory.compaction_count += 1
                try:
                    response, turn_cog_stats, turn_tokens = await _llm_turn(
                        conversation, model_id, tools, bridge, user_id,
                        session_id=session_id, transcript=transcript,
                    )
                    for k in total_token_usage:
                        total_token_usage[k] += turn_tokens.get(k, 0)
                except LLMContextOverflowError:
                    logger.error(f"ACS turn {turns + 1}: LLM 400 persists after compaction")
                    await _finalize("error", error="LLM context overflow after compaction retry")
                    return
            except Exception as _turn_err:
                # General turn error — retry up to 3 times before giving up
                _consecutive_turn_errors += 1
                if _consecutive_turn_errors >= 3:
                    logger.error(f"ACS turn {turns + 1}: {_consecutive_turn_errors} consecutive errors, ending session: {_turn_err}")
                    await _finalize(
                        "error",
                        error=f"{_consecutive_turn_errors} consecutive errors: {str(_turn_err)[:300]}",
                    )
                    return
                logger.warning(f"ACS turn {turns + 1}: error (attempt {_consecutive_turn_errors}/3), retrying in 10s: {_turn_err}")
                await asyncio.sleep(10)
                continue

            if not response:
                logger.warning(f"ACS turn {turns + 1}: empty response")
                await _finalize("error", error="Empty LLM response")
                return

            conversation.append({"role": "assistant", "content": response})
            transcript.record_assistant_turn(turns + 1, response)

            result = await _process_output(user_id, session_id, response, transcript=transcript, session_memory=session_memory, mode=mode, turns=turns)
            # Merge cognitive tool stats from _llm_turn
            result.nodes_created += turn_cog_stats.get("nodes_created", 0)
            result.nodes_updated += turn_cog_stats.get("nodes_updated", 0)
            result.edges_created += turn_cog_stats.get("edges_created", 0)
            tool_notes = turn_cog_stats.get("notes_written", 0)
            result.notes_written += tool_notes
            result.notes_created += tool_notes
            if turn_cog_stats.get("self_model_updated"):
                result.self_model_updated = True
            if turn_cog_stats.get("engagement_score"):
                result.engagement_score = turn_cog_stats["engagement_score"]

            notes_created += result.notes_created
            curiosities_explored += result.curiosities_explored
            topics_covered.extend(result.topics)
            total_nodes_created += result.nodes_created
            total_nodes_updated += result.nodes_updated
            total_edges_created += result.edges_created
            total_notes_written += result.notes_written
            if result.self_model_updated:
                self_model_ever_updated = True
            turn_engagement = result.engagement_score or _infer_engagement(result)
            engagement_scores.append(turn_engagement)
            # Populate session working memory
            session_memory.notes_created.extend(result.note_titles)
            session_memory.nodes_created.extend(result.node_labels)
            session_memory.edges_created += result.edges_created
            turns += 1

            # Persist progress so the UI/lifecycle watchdog see live turn counts
            await _flush_turn_progress(session_id, turns, notes_created, curiosities_explored)
            # Snapshot the transcript so the Sessions tab can render it live
            try:
                from app.services.acs.audit_logger import snapshot_transcript
                await snapshot_transcript(transcript)
            except Exception:
                pass

            await _maybe_persist_durable()

            # Run the auditor watchdog. If a rule trips, we kick off the audit
            # dialogue (which runs in-process here so the session is genuinely
            # frozen until it resolves — Sara cannot take her next turn until
            # the auditor releases the lock).
            try:
                audit_outcome = await _maybe_run_audit(
                    user_id=user_id,
                    session_id=session_id,
                    turns=turns,
                    transcript=transcript,
                    trigger_kind="watchdog_loop",
                )
                if audit_outcome == "stopped":
                    await _finalize("auditor_stop")
                    return
            except Exception as e:
                logger.debug(f"Watchdog audit dispatch failed: {e}")

            # Track tool usage in session memory
            for k, v in turn_cog_stats.items():
                if isinstance(v, (int, float)) and v > 0 and k != "engagement_score":
                    session_memory.tools_used[k] = session_memory.tools_used.get(k, 0) + int(v)

            await _publish_live(user_id, "turn_completed", {
                "turn": turns, "output": response[:2000],
                "notes_created": notes_created, "curiosities_explored": curiosities_explored,
                "mode": mode, "engagement": turn_engagement,
            })

            # Publish narrative thought for live feed
            narrative = _extract_narrative(response)
            if narrative:
                await _publish_live(user_id, "thought", {
                    "turn": turns, "text": narrative, "mode": mode,
                })

            # Done detection: check if the model emitted a done signal.
            # Also track consecutive done-with-no-activity turns for deadlock detection.
            turn_had_real_activity = (
                turn_cog_stats.get("vm_tool_calls", 0) > 0
                or turn_cog_stats.get("notes_written", 0) > 0
                or turn_cog_stats.get("nodes_created", 0) > 0
                or turn_cog_stats.get("edges_created", 0) > 0
            )

            if _output_signals_done(response, turn_had_real_activity=turn_had_real_activity):
                await _finalize("completed")
                return

            if _output_has_done_block(response) and not turn_had_real_activity:
                consecutive_done_turns += 1
                logger.warning(f"ACS done-deadlock counter: {consecutive_done_turns}/{ACS_DONE_DEADLOCK_LIMIT} (session {session_id})")
                if consecutive_done_turns >= ACS_DONE_DEADLOCK_LIMIT:
                    logger.error(f"ACS done-deadlock detected after {consecutive_done_turns} consecutive idle done turns — force-ending session {session_id}")
                    await _finalize("done_deadlock")
                    return
            else:
                consecutive_done_turns = 0

        # Deadline reached
        await _finalize("timeout")

    except asyncio.CancelledError:
        await _finalize("manual")
    except Exception as e:
        logger.exception(f"ACS loop crashed: {e}")
        await _finalize("error", error=str(e)[:500])
    finally:
        _active_tasks.pop(user_id, None)
        # Clean up ephemeral containers, but preserve persistent ones
        if session_id:
            try:
                from app.services.container_provisioner import ContainerProvisioner
                provisioner = ContainerProvisioner()

                # Check if handoff references ongoing container work
                import redis as sync_redis
                r = sync_redis.from_url(REDIS_URL, decode_responses=True)
                persistent_key = f"sara:acs:persistent_containers:{user_id}"
                persistent_vmids = r.smembers(persistent_key) if r.exists(persistent_key) else set()
                r.close()

                destroyed = await provisioner.cleanup_session(
                    session_id, skip_vmids=persistent_vmids
                )
                if destroyed:
                    logger.info(f"ACS session cleanup: destroyed {destroyed} ephemeral containers"
                               f"{f' (preserved {len(persistent_vmids)} persistent)' if persistent_vmids else ''}")
            except Exception as e:
                logger.warning(f"ACS container cleanup failed: {e}")


def _infer_engagement(result: TurnResult) -> float:
    """Infer engagement score from turn output when not explicitly provided."""
    if result.nodes_created > 0 or result.edges_created > 0 or result.notes_created > 0:
        return 0.9
    if result.nodes_updated > 0 or result.notes_written > 0:
        return 0.6
    if result.curiosities_explored > 0:
        return 0.6
    return 0.3


# ── Output parsing (re-exports from output_parsing module) ──

from app.services.acs.output_parsing import (
    compact_conversation as _compact_conversation,
    compress_older_turns as _compress_older_turns,
    extract_files_from_transcript as _extract_files_from_transcript,
    extract_json_blocks as _extract_json_blocks,
    extract_narrative as _extract_narrative,
    output_has_done_block as _output_has_done_block,
    output_signals_done as _output_signals_done,
    strip_narrative as _strip_narrative,
)


async def _process_output(
    user_id: str, session_id: str, output: str,
    transcript=None, session_memory: SessionWorkingMemory = None,
    mode: str = None, turns: int = 0,
) -> TurnResult:
    """Parse structured JSON blocks from the LLM output and dispatch side-effects.

    Returns a TurnResult with per-turn stats (notes_created, nodes_created, etc.).
    """
    tr = TurnResult()
    blocks = _extract_json_blocks(output)
    logger.debug(f"_process_output: {len(blocks)} blocks found in {len(output)} chars")
    if blocks:
        logger.info(f"ACS blocks: {[b.get('type') for b in blocks]}")

    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()

    async with async_session() as db:
        for block in blocks:
            block_type = block.get("type")

            if block_type == "note":
                await _save_note(db, user_id, session_id, block)
                tr.notes_created += 1
                tr.notes_written += 1
                note_title = block.get("title", "untitled")
                tr.topics.append(note_title)
                tr.note_titles.append(note_title)

            elif block_type == "note_revision":
                await _revise_note(db, user_id, block)
                tr.notes_written += 1
                tr.note_titles.append(f"(revised) {block.get('note_title', '')}")

            elif block_type == "interest_node_create":
                try:
                    from app.services.acs.interest_graph import InterestGraph
                    graph = InterestGraph()
                    node_label = block.get("label", "")
                    result = await graph.add_node(
                        user_id=user_id,
                        label=node_label,
                        description=block.get("description", ""),
                        source=block.get("source", "self_discovery"),
                        fascination=block.get("fascination", 0.5),
                    )
                    if result and not result.get("merged"):
                        tr.nodes_created += 1
                    elif result:
                        tr.nodes_updated += 1
                    tr.topics.append(node_label)
                    tr.node_labels.append(node_label)
                except Exception as e:
                    logger.warning(f"interest_node_create failed: {e}")

            elif block_type == "interest_node_update":
                try:
                    from app.services.acs.interest_graph import InterestGraph
                    graph = InterestGraph()
                    label = block.get("label", "")
                    node = await graph.find_by_label(user_id, label)
                    if node:
                        updates = {k: v for k, v in block.items()
                                   if k in ("description", "fascination", "depth", "confidence") and v is not None}
                        if updates:
                            await graph.update_node(node["id"], **updates)
                        await graph.engage_node(node["id"], meaningful=("depth" in updates))
                        tr.nodes_updated += 1
                except Exception as e:
                    logger.warning(f"interest_node_update failed: {e}")

            elif block_type == "interest_edge_create":
                try:
                    from app.services.acs.interest_graph import InterestGraph
                    graph = InterestGraph()
                    src = await graph.find_by_label(user_id, block.get("source_label", ""))
                    tgt = await graph.find_by_label(user_id, block.get("target_label", ""))
                    if src and tgt:
                        await graph.add_edge(
                            user_id=user_id,
                            source_node_id=src["id"],
                            target_node_id=tgt["id"],
                            relationship=block.get("relationship", "relates_to"),
                            description=block.get("description", ""),
                            strength=block.get("strength", 0.5),
                        )
                        tr.edges_created += 1
                except Exception as e:
                    logger.warning(f"interest_edge_create failed: {e}")

            elif block_type == "self_model_update":
                try:
                    from app.services.acs.self_model import SelfModel
                    sm = SelfModel()
                    updates = block.get("updates", {})
                    if updates:
                        await sm.update(user_id, updates, session_id=session_id)
                        tr.self_model_updated = True
                except Exception as e:
                    logger.warning(f"self_model_update failed: {e}")

            elif block_type == "engagement_signal":
                score = block.get("score", 0.5)
                tr.engagement_score = max(0.0, min(1.0, float(score)))

            elif block_type == "curiosity":
                try:
                    from app.services.acs.interest_graph import InterestGraph
                    graph = InterestGraph()
                    await graph.add_node(
                        user_id=user_id,
                        label=block.get("topic", ""),
                        source="self_discovery",
                        fascination=block.get("priority", 0.5),
                    )
                    tr.nodes_created += 1
                except Exception:
                    pass
                tr.topics.append(block.get("topic", ""))

            elif block_type == "show_david":
                await db.execute(text("""
                    INSERT INTO acs_show_david_buffer
                    (id, user_id, title, content, category, priority, session_id)
                    VALUES (:id, :uid, :title, :content, :cat, :priority, :sid)
                """), {
                    "id": str(uuid.uuid4()), "uid": user_id,
                    "title": block.get("title", ""),
                    "content": block.get("content", ""),
                    "cat": block.get("category", "discovery"),
                    "priority": block.get("priority", 0.5),
                    "sid": session_id,
                })

            elif block_type == "journal":
                await _append_journal(db, user_id, block.get("reflection", ""))

            elif block_type == "session_handoff":
                # Extract file paths from session transcript for next-session context
                session_files = _extract_files_from_transcript(transcript) if transcript else []
                await _save_handoff(
                    user_id, block, session_files=session_files,
                    session_memory=session_memory, mode=mode, turns=turns,
                )

        await db.commit()

    return tr


async def _revise_note(db, user_id: str, block: dict):
    """Find and update an existing note by title."""
    title = block.get("note_title", "")
    content = block.get("content", "")
    if not title or not content:
        return
    folder_id = await state_machine.get_notes_folder_id(user_id)
    result = await db.execute(text("""
        SELECT id FROM note
        WHERE user_id = :uid AND title = :title
        ORDER BY updated_at DESC LIMIT 1
    """), {"uid": user_id, "title": title})
    row = result.fetchone()
    if row:
        await db.execute(text("""
            UPDATE note SET content = :content, updated_at = NOW()
            WHERE id = :id
        """), {"content": content, "id": row[0]})
        logger.info(f"Revised note: {title}")

        # Re-detect connections after revision
        try:
            from app.services.note_connector import process_note_connections
            await process_note_connections(row[0], user_id, title, content, db)
        except Exception as e:
            logger.warning(f"_revise_note: connection detection failed: {e}")
    else:
        logger.warning(f"note_revision: note not found: {title}")


async def _save_note(db, user_id: str, session_id: str, block: dict, folder_name: str = None):
    """Save a note to Sara's Notes folder and detect connections.

    Notes are filed under today's date folder (`Sara's Notes / YYYY / MM /
    DD`) so the user can browse everything Sara wrote on a given day. The
    `folder_name` parameter is accepted for backwards compatibility with
    existing call sites but ignored — Sara no longer chooses topic folders.

    Dedup gate: before creating a new note, checks ALL folders for notes with
    the same or very similar title. If found, updates the existing note in
    place (preserving its original date folder) instead of creating a
    duplicate — even across folders.
    """
    folder_id = await _ensure_date_folder(user_id)

    title = block.get("title", "Untitled")
    content = block.get("content", "")
    tags = block.get("tags", [])

    # ── Dedup gate: check ALL folders for existing note with same title ──
    existing = await db.execute(text("""
        SELECT id, folder_id FROM note
        WHERE user_id = :uid AND title = :title
        ORDER BY updated_at DESC
        LIMIT 1
    """), {"uid": user_id, "title": title})
    row = existing.fetchone()

    # Also check for fuzzy title matches (same title with minor differences)
    if not row:
        # Normalize: strip common prefixes/suffixes and check
        title_core = title.replace(":", "").replace(" - ", " ").strip()
        existing = await db.execute(text("""
            SELECT id, folder_id, title FROM note
            WHERE user_id = :uid
              AND title NOT LIKE 'Sara''s Journal%'
              AND title NOT LIKE 'ACS Session Log%'
              AND SIMILARITY(title, :title) > 0.6
            ORDER BY SIMILARITY(title, :title) DESC
            LIMIT 1
        """), {"uid": user_id, "title": title_core})
        row = existing.fetchone()
        if row:
            logger.info(
                f"_save_note: dedup gate caught fuzzy match: "
                f"'{title}' ≈ '{row[2]}' — updating existing note"
            )

    if row:
        note_id = row[0]
        await db.execute(text("""
            UPDATE note SET content = :content, tags = :tags, updated_at = NOW()
            WHERE id = :id
        """), {"content": content, "tags": json.dumps(tags), "id": note_id})
        logger.info(f"_save_note: updated existing note '{title}' ({note_id[:8]})")
    else:
        note_id = str(uuid.uuid4())
        await db.execute(text("""
            INSERT INTO note (id, user_id, title, content, tags, folder_id, starred, created_at, updated_at)
            VALUES (:id, :uid, :title, :content, :tags, :fid, FALSE, NOW(), NOW())
        """), {
            "id": note_id, "uid": user_id,
            "title": title, "content": content,
            "tags": json.dumps(tags),
            "fid": folder_id,
        })

    # Detect connections (embedding + wiki links + semantic neighbors)
    try:
        from app.services.note_connector import process_note_connections
        await process_note_connections(note_id, user_id, title, content, db)
    except Exception as e:
        logger.warning(f"_save_note: connection detection failed: {e}")

    # Fire-and-forget PKG extraction for David-relevant facts
    asyncio.create_task(_extract_note_to_pkg(user_id, title, content))

    return note_id


async def _extract_note_to_pkg(user_id: str, title: str, content: str):
    """Fire-and-forget: extract David-relevant facts from ACS notes into PKG."""
    try:
        from app.services.pkg_extractor import pkg_extractor

        # Skip Sara's self-reflections and journal-like content
        content_lower = content.lower()
        david_signals = ["david", "his ", "he ", "schedule", "calendar", "project",
                         "work", "family", "kids", "home", "routine"]
        if not any(signal in content_lower for signal in david_signals):
            return

        result = await pkg_extractor.extract_from_acs_note(content, title)
        if result and result.get("extracted"):
            logger.info(
                f"PKG extraction from ACS note '{title}': "
                f"{len(result['extracted'])} facts extracted"
            )
    except Exception as e:
        logger.debug(f"PKG extraction from ACS note failed: {e}")


async def _append_journal(db, user_id: str, reflection: str):
    """Append to today's journal note, creating it if needed."""
    if not reflection.strip():
        return

    est = ZoneInfo("America/New_York")
    now_est = datetime.now(est)
    folder_id = await _ensure_date_folder(user_id, now_est)
    today = now_est.strftime("%Y-%m-%d")
    journal_title = f"Sara's Journal — {today}"

    result = await db.execute(text("""
        SELECT id, content FROM note
        WHERE user_id = :uid AND folder_id = :fid AND title = :title
        LIMIT 1
    """), {"uid": user_id, "fid": folder_id, "title": journal_title})
    row = result.fetchone()

    timestamp = now_est.strftime("%-I:%M %p ET")

    if row:
        existing_content = row[1] or ""
        new_content = f"{existing_content}\n\n---\n**{timestamp}**\n\n{reflection}"
        await db.execute(text("""
            UPDATE note SET content = :content, updated_at = NOW()
            WHERE id = :id
        """), {"content": new_content, "id": row[0]})
    else:
        note_id = str(uuid.uuid4())
        content = f"# {journal_title}\n\n**{timestamp}**\n\n{reflection}"
        await db.execute(text("""
            INSERT INTO note (id, user_id, title, content, tags, folder_id, starred, created_at, updated_at)
            VALUES (:id, :uid, :title, :content, :tags, :fid, FALSE, NOW(), NOW())
        """), {
            "id": note_id, "uid": user_id,
            "title": journal_title, "content": content,
            "tags": json.dumps(["journal", "autonomous"]),
            "fid": folder_id,
        })


async def _save_handoff(
    user_id: str, block: dict, session_files: list = None,
    session_memory: SessionWorkingMemory = None,
    mode: str = None, turns: int = 0,
):
    """Save a session handoff to Redis and auto-create thread from open_questions.

    session_files: list of file paths touched during this session (write_file/read_file).
    session_memory: SessionWorkingMemory with enriched session data.
    """
    try:
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            handoff_data = {
                "was_doing": block.get("was_doing", ""),
                "got_to": block.get("got_to", ""),
                "next_time": block.get("next_time", ""),
                "open_questions": block.get("open_questions", ""),
                "saved_at": local_now().isoformat(),
            }
            if session_files:
                handoff_data["files_touched"] = session_files[-20:]  # Last 20 files
            # Enrich with session working memory
            if session_memory:
                wm = session_memory.to_handoff_dict()
                handoff_data["notes_created"] = wm.get("notes_created", [])
                handoff_data["notes_revised"] = wm.get("notes_revised", [])
                handoff_data["nodes_created"] = wm.get("nodes_created", [])
                handoff_data["edges_created"] = wm.get("edges_created", 0)
                handoff_data["key_findings"] = wm.get("key_findings", [])
                handoff_data["compaction_count"] = wm.get("compaction_count", 0)
                if session_memory.last_compaction_summary:
                    handoff_data["last_compaction_summary"] = session_memory.last_compaction_summary[:2000]
                # Override files from session_memory if richer
                if wm.get("files_touched"):
                    handoff_data["files_touched"] = wm["files_touched"]
            if mode:
                handoff_data["mode"] = mode
            if turns:
                handoff_data["turns"] = turns
            handoff = json.dumps(handoff_data)
            await r.set(HANDOFF_KEY.format(user_id=user_id), handoff)

            # Auto-create a thread from the handoff if there's a clear next_time intent
            next_time = block.get("next_time", "").strip()
            was_doing = block.get("was_doing", "").strip()
            if next_time and was_doing:
                # Check if there's already an active thread with similar title
                threads_key = OPEN_THREADS_KEY.format(user_id=user_id)
                existing = await r.hgetall(threads_key)
                already_tracked = False
                for raw in existing.values():
                    try:
                        t = json.loads(raw)
                        if t.get("status") == "active" and was_doing[:30].lower() in t.get("title", "").lower():
                            already_tracked = True
                            # Update progress on existing thread
                            t.setdefault("progress", []).append({
                                "text": block.get("got_to", ""),
                                "next_steps": next_time,
                                "at": local_now().isoformat(),
                            })
                            t["updated_at"] = local_now().isoformat()
                            await r.hset(threads_key, t["id"], json.dumps(t))
                            break
                    except (json.JSONDecodeError, KeyError):
                        continue
                # Don't auto-create — let Sara manage threads explicitly via tools

            # Parse time-based intent from next_time for scheduled session start
            if next_time:
                scheduled_intent = _parse_time_intent(next_time)
                if scheduled_intent:
                    intent_key = f"sara:acs:scheduled_intent:{user_id}"
                    await r.set(intent_key, json.dumps({
                        "target_time": scheduled_intent.isoformat(),
                        "intent": next_time,
                        "was_doing": was_doing,
                        "created_at": local_now().isoformat(),
                    }), ex=86400)  # Expire after 24h
                    logger.info(f"ACS scheduled intent: {next_time} → {scheduled_intent.isoformat()}")

        finally:
            await _close_redis(r)
    except Exception as e:
        logger.warning(f"Failed to save session handoff: {e}")


def _parse_time_intent(text: str) -> Optional[datetime]:
    """Parse a rough time intent from handoff next_time text. Returns UTC datetime or None."""
    import re
    text_lower = text.lower()

    now = local_now()

    # "tomorrow morning" / "tomorrow"
    if "tomorrow" in text_lower:
        target = now + timedelta(days=1)
        if "morning" in text_lower:
            return target.replace(hour=12, minute=0, second=0)  # 7 AM ET ≈ 12 UTC
        elif "evening" in text_lower or "night" in text_lower:
            return target.replace(hour=1, minute=0, second=0) + timedelta(days=1)  # 8 PM ET ≈ 01 UTC next day
        return target.replace(hour=12, minute=0, second=0)

    # "in N hours"
    match = re.search(r"in\s+(\d+)\s+hours?", text_lower)
    if match:
        hours = int(match.group(1))
        return now + timedelta(hours=hours)

    # "tonight" / "this evening"
    if "tonight" in text_lower or "this evening" in text_lower:
        return now.replace(hour=1, minute=0, second=0) + timedelta(days=1)  # ~8 PM ET

    return None


async def _ensure_notes_folder(user_id: str):
    """Create 'Sara's Notes' folder if it doesn't exist, cache ID in Redis."""
    existing = await state_machine.get_notes_folder_id(user_id)
    if existing:
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(text(
                "SELECT id FROM folder WHERE id = :fid AND user_id = :uid"
            ), {"fid": existing, "uid": user_id})
            if result.fetchone():
                return

    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        new_id = str(uuid.uuid4())
        result = await db.execute(text("""
            INSERT INTO folder (id, user_id, name, parent_id, created_at, updated_at)
            VALUES (:id, :uid, :name, NULL, NOW(), NOW())
            ON CONFLICT (user_id, name, COALESCE(parent_id, '__ROOT__'))
            DO UPDATE SET updated_at = NOW()
            RETURNING id
        """), {"id": new_id, "uid": user_id, "name": "Sara's Notes"})
        row = result.fetchone()
        folder_id = row[0]
        await db.commit()

    await state_machine.set_notes_folder_id(user_id, folder_id)


async def _get_existing_subfolder_names(user_id: str) -> list[str]:
    """Get names of all existing subfolders inside Sara's Notes."""
    root_id = await state_machine.get_notes_folder_id(user_id)
    if not root_id:
        return []
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(text(
            "SELECT name FROM folder WHERE parent_id = :root AND user_id = :uid ORDER BY name"
        ), {"root": root_id, "uid": user_id})
        return [row[0] for row in result.fetchall()]


def _fuzzy_match_folder(name: str, existing: list[str], threshold: float = 0.7) -> str | None:
    """Find an existing folder that closely matches the requested name."""
    from difflib import SequenceMatcher
    name_lower = name.lower().strip().rstrip("/")
    # Strip path-like prefixes (e.g. "Sara's Notes/Reflections" -> "Reflections")
    if "/" in name_lower:
        name_lower = name_lower.rsplit("/", 1)[-1]
    for existing_name in existing:
        existing_lower = existing_name.lower().strip()
        # Exact match (case-insensitive)
        if name_lower == existing_lower:
            return existing_name
        # Fuzzy match
        ratio = SequenceMatcher(None, name_lower, existing_lower).ratio()
        if ratio >= threshold:
            return existing_name
    return None


async def _ensure_subfolder(user_id: str, subfolder_name: str) -> str:
    """Get or create a named subfolder inside Sara's Notes. Returns folder_id."""
    # Strip path-like prefixes (e.g. "Sara's Notes/Reflections" -> "Reflections")
    if "/" in subfolder_name:
        subfolder_name = subfolder_name.rsplit("/", 1)[-1]
    subfolder_name = subfolder_name.strip().rstrip("/")

    # Check Redis cache first
    cache_key = f"sara:acs:subfolder:{user_id}:{subfolder_name}"
    try:
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            cached = await r.get(cache_key)
            if cached:
                return cached
        finally:
            await _close_redis(r)
    except Exception:
        pass

    # Ensure root folder exists
    await _ensure_notes_folder(user_id)
    root_id = await state_machine.get_notes_folder_id(user_id)

    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()
    async with async_session() as db:
        # Check for existing fuzzy match first
        result = await db.execute(text(
            "SELECT id, name FROM folder WHERE parent_id = :root AND user_id = :uid"
        ), {"root": root_id, "uid": user_id})
        existing_rows = result.fetchall()
        existing_names = [r[1] for r in existing_rows]

        match = _fuzzy_match_folder(subfolder_name, existing_names)
        if match:
            # Use the existing folder
            for r in existing_rows:
                if r[1] == match:
                    folder_id = r[0]
                    if match != subfolder_name:
                        logger.info(f"Fuzzy-matched folder '{subfolder_name}' → '{match}'")
                    break
        else:
            new_id = str(uuid.uuid4())
            result = await db.execute(text("""
                INSERT INTO folder (id, user_id, name, parent_id, created_at, updated_at)
                VALUES (:id, :uid, :name, :parent, NOW(), NOW())
                ON CONFLICT (user_id, name, COALESCE(parent_id, '__ROOT__'))
                DO UPDATE SET updated_at = NOW()
                RETURNING id
            """), {"id": new_id, "uid": user_id, "name": subfolder_name, "parent": root_id})
            row = result.fetchone()
            folder_id = row[0]
            await db.commit()

    # Cache in Redis (24h TTL)
    try:
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            await r.set(cache_key, folder_id, ex=86400)
        finally:
            await _close_redis(r)
    except Exception:
        pass

    return folder_id


async def _ensure_date_folder(user_id: str, dt: Optional[datetime] = None) -> str:
    """Get or create the date-based folder for a note.

    Notes in "Sara's Notes" are organized by creation day (ET) under a
    `YYYY / MM - Month / DD` hierarchy so the user can see everything Sara
    wrote on a specific day at a glance. This helper creates the three-level
    chain (year → month → day) on demand and caches the resulting day folder
    ID in Redis for 24h.

    Args:
        user_id: owning user
        dt:      timestamp the note "belongs to" (defaults to now in ET).
                 Pass an explicit datetime when filing notes that document a
                 different day — e.g. the daily report at 6 AM is *about*
                 yesterday and should land in yesterday's folder.

    Returns the leaf (day) folder ID.
    """
    est = ZoneInfo("America/New_York")
    when = dt or datetime.now(est)
    if when.tzinfo is None:
        when = when.replace(tzinfo=est)
    else:
        when = when.astimezone(est)

    year_name = f"{when.year:04d}"
    month_name = f"{when.month:02d} - {when.strftime('%B')}"
    day_name = f"{when.day:02d}"
    cache_key = f"sara:acs:date_folder:{user_id}:{year_name}-{when.month:02d}-{day_name}"

    # Redis cache hit?
    try:
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            cached = await r.get(cache_key)
            if cached:
                return cached
        finally:
            await _close_redis(r)
    except Exception:
        pass

    # Ensure root folder exists
    await _ensure_notes_folder(user_id)
    root_id = await state_machine.get_notes_folder_id(user_id)

    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()

    async def _get_or_create_child(db, parent_id: str, name: str) -> str:
        """Get the child folder by name under parent, creating if missing."""
        result = await db.execute(text("""
            SELECT id FROM folder
            WHERE parent_id = :parent AND user_id = :uid AND name = :name
            LIMIT 1
        """), {"parent": parent_id, "uid": user_id, "name": name})
        row = result.fetchone()
        if row:
            return row[0]
        new_id = str(uuid.uuid4())
        result = await db.execute(text("""
            INSERT INTO folder (id, user_id, name, parent_id, created_at, updated_at)
            VALUES (:id, :uid, :name, :parent, NOW(), NOW())
            ON CONFLICT (user_id, name, COALESCE(parent_id, '__ROOT__'))
            DO UPDATE SET updated_at = NOW()
            RETURNING id
        """), {"id": new_id, "uid": user_id, "name": name, "parent": parent_id})
        return result.fetchone()[0]

    async with async_session() as db:
        year_id = await _get_or_create_child(db, root_id, year_name)
        month_id = await _get_or_create_child(db, year_id, month_name)
        day_id = await _get_or_create_child(db, month_id, day_name)
        await db.commit()

    # Cache in Redis (24h TTL)
    try:
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            await r.set(cache_key, day_id, ex=86400)
        finally:
            await _close_redis(r)
    except Exception:
        pass

    return day_id


async def _transcript_then_audit(user_id: str, session_id: str):
    """Humanize the session transcript, then run per-session audit.

    On failure, stores a pending key in Redis for retry by lifecycle check.
    """
    try:
        from app.services.acs.audit_logger import humanize_session_transcript, run_session_audit
        await humanize_session_transcript(user_id, session_id)
        await run_session_audit(user_id, session_id)
    except Exception as e:
        logger.error(f"Transcript/audit pipeline failed for {session_id[:8]}: {e}")
        # Mark for retry by lifecycle check
        try:
            r = await aioredis.from_url(REDIS_URL, decode_responses=True)
            try:
                await r.set(
                    f"sara:acs:audit_pending:{session_id}",
                    user_id,
                    ex=86400,  # 24h TTL
                )
            finally:
                await _close_redis(r)
        except Exception:
            pass


async def _maybe_run_audit(
    user_id: str,
    session_id: str,
    turns: int,
    transcript,
    trigger_kind: str,
    forced_reason: Optional[str] = None,
) -> Optional[str]:
    """
    Evaluate the watchdog rules. If a rule trips (or trigger_kind is forced
    via the periodic auditor), run the audit dialogue inline. The dialogue
    runs to completion before returning, so Sara's main loop is genuinely
    frozen for the duration. The dialogue itself is in-process — there is
    no Celery hop, no Redis polling — because we're already inside an async
    context that needs to wait synchronously for the resolution.

    Returns the audit outcome ("redirected", "stopped", etc.) or None if
    no audit was triggered. The caller should check for "stopped" and
    terminate the session.
    """
    from app.services.acs.watchdog import evaluate as watchdog_evaluate
    from app.services.acs.auditor import (
        acquire_audit_lock,
        release_audit_lock,
        count_session_audits,
        run_dialogue,
        MAX_AUDITS_PER_SESSION,
        AUDIT_COOLDOWN_TURNS,
    )

    # Post-audit cooldown: skip watchdog for N turns after the last audit
    # to give Sara a chance to actually act on the directive before re-triggering.
    if trigger_kind == "watchdog_loop":
        last_audit_turn = getattr(transcript, "_last_audit_turn", None)
        if last_audit_turn is not None and (turns - last_audit_turn) < AUDIT_COOLDOWN_TURNS:
            return None

    # If watchdog-driven, evaluate the rules first
    reason = forced_reason
    if trigger_kind == "watchdog_loop":
        recent = transcript.entries[-12:] if hasattr(transcript, "entries") else []
        tripped, reason = watchdog_evaluate(turns, recent)
        if not tripped:
            return None

    if not reason:
        reason = "(no reason provided)"

    # Respect the per-session audit ceiling — if we've hit it, force-stop
    # the session instead of letting it run unsupervised forever.
    audit_count = await count_session_audits(session_id)
    if audit_count >= MAX_AUDITS_PER_SESSION:
        logger.warning(
            f"Session {session_id[:8]} hit audit ceiling ({MAX_AUDITS_PER_SESSION}); "
            f"force-stopping session. Latest trigger: {reason[:80]}"
        )
        try:
            from app.db.session import get_async_session_factory
            async_session = get_async_session_factory()
            async with async_session() as db:
                await db.execute(text("""
                    UPDATE acs_session
                    SET state = 'pausing',
                        end_reason = COALESCE(end_reason, 'audit_ceiling')
                    WHERE id = :sid AND state IN ('autonomous', 'audit_paused')
                """), {"sid": session_id})
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to force-stop session {session_id[:8]} at audit ceiling: {e}")
        return "stopped"

    # Acquire the lock — this is what makes the session "frozen"
    got_lock = await acquire_audit_lock(session_id)
    if not got_lock:
        logger.info(f"Session {session_id[:8]}: audit lock already held, skipping")
        return None

    # Mark the session state so the rest of the system knows
    try:
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            await db.execute(text("""
                UPDATE acs_session SET state = 'audit_paused' WHERE id = :sid
            """), {"sid": session_id})
            await db.commit()
    except Exception as e:
        logger.warning(f"Failed to mark session {session_id[:8]} as audit_paused: {e}")

    logger.info(
        f"AUDITOR triggered on session {session_id[:8]}: kind={trigger_kind}, "
        f"reason={reason[:140]}, prior_audits={audit_count}"
    )

    outcome = None
    try:
        result = await run_dialogue(
            session_id=session_id,
            user_id=user_id,
            trigger_kind=trigger_kind,
            trigger_reason=reason,
            prior_audit_count=audit_count,
        )
        outcome = result.get("outcome")
        logger.info(
            f"AUDITOR resolved session {session_id[:8]}: outcome={outcome}"
        )
        # Record the turn at which this audit happened so cooldown works
        transcript._last_audit_turn = turns
    except Exception as e:
        logger.error(f"AUDITOR dialogue crashed for session {session_id[:8]}: {e}", exc_info=True)
    finally:
        # Always release the lock and restore state
        try:
            from app.db.session import get_async_session_factory
            async_session = get_async_session_factory()
            async with async_session() as db:
                await db.execute(text("""
                    UPDATE acs_session SET state = 'autonomous'
                    WHERE id = :sid AND state = 'audit_paused'
                """), {"sid": session_id})
                await db.commit()
        except Exception:
            pass
        await release_audit_lock(session_id)

    return outcome


async def _flush_turn_progress(
    session_id: str,
    turns: int,
    notes_created: int,
    curiosities_explored: int,
) -> None:
    """
    Persist in-flight turn counters to acs_session.

    Called after each turn so a long-running session shows accurate progress
    in the UI instead of appearing as "0 turns" until it ends. Without this,
    a session that runs for hours (or gets killed by the lifecycle watchdog
    before _finalize_session runs) shows 0 turns even though Sara was busy.
    """
    try:
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            await db.execute(text("""
                UPDATE acs_session
                SET turns_completed = :turns,
                    notes_created = :notes,
                    curiosities_explored = :curiosities
                WHERE id = :sid
            """), {
                "turns": turns,
                "notes": notes_created,
                "curiosities": curiosities_explored,
                "sid": session_id,
            })
            await db.commit()
    except Exception as e:
        # Never let a progress flush failure abort the running session.
        logger.debug(f"Turn progress flush failed for {session_id[:8]}: {e}")


async def _finalize_session(
    user_id: str, session_id: str, end_reason: str,
    turns: int, notes_created: int, curiosities_explored: int,
    error: str = "",
    mode: str = None,
    session_log_id: str = None,
    engagement_scores: list = None,
    early_termination: bool = False,
    v2_stats: dict = None,
    transcript=None,
    session_memory: SessionWorkingMemory = None,
    token_usage: dict = None,
    plan_item_id: Optional[str] = None,
    primary_topic: Optional[str] = None,
    primary_objective: Optional[str] = None,
    expected_artifact: Optional[str] = None,
):
    """Mark session as ended, update DB, transition state."""
    from app.db.session import get_async_session_factory
    async_session = get_async_session_factory()

    # Compute average engagement
    avg_engagement = None
    if engagement_scores:
        avg_engagement = sum(engagement_scores) / len(engagement_scores)

    async with async_session() as db:
        await db.execute(text("""
            UPDATE acs_session
            SET state = 'ended', ended_at = NOW(), end_reason = :reason,
                turns_completed = :turns, notes_created = :notes,
                curiosities_explored = :curiosities, error_log = :err,
                engagement_score = :eng,
                token_usage = :tokens
            WHERE id = :sid
        """), {
            "reason": end_reason, "turns": turns, "notes": notes_created,
            "curiosities": curiosities_explored, "err": error or None, "sid": session_id,
            "eng": avg_engagement,
            "tokens": json.dumps(token_usage) if token_usage else "{}",
        })
        await db.commit()

    # Update session log (v2)
    if session_log_id and v2_stats:
        try:
            async with async_session() as db:
                from app.services.acs.communication_policy import get_session_delivery_stats

                outcome_type = end_reason
                artifact_summary = None
                if plan_item_id:
                    plan_result = await db.execute(text("""
                        SELECT title, status, result_summary, closure_reason
                        FROM acs_plan_item
                        WHERE id = :pid
                    """), {"pid": plan_item_id})
                    plan_row = plan_result.fetchone()
                    if plan_row:
                        primary_topic = primary_topic or plan_row[0]
                        primary_objective = primary_objective or plan_row[0]
                        outcome_type = plan_row[3] or plan_row[1] or end_reason
                        artifact_summary = plan_row[2]

                primary_topic = primary_topic or (mode if mode else None)
                primary_objective = primary_objective or (f"{mode} session" if mode else None)
                expected_artifact = expected_artifact or (
                    "A durable artifact, a plan-item outcome, or an explicit closure decision."
                    if mode else None
                )
                outbound_messages, suppressed_messages = await get_session_delivery_stats(db, session_id)

                await db.execute(text("""
                    UPDATE acs_session_log
                    SET ended_at = NOW(),
                        turns_completed = :turns,
                        engagement_scores = :eng_scores,
                        avg_engagement = :avg_eng,
                        early_termination = :early,
                        nodes_created = :nc,
                        nodes_updated = :nu,
                        edges_created = :ec,
                        notes_written = :nw,
                        self_model_updated = :smu,
                        summary = :summary,
                        primary_topic = :primary_topic,
                        primary_objective = :primary_objective,
                        expected_artifact = :expected_artifact,
                        outcome_type = :outcome_type,
                        artifact_summary = :artifact_summary,
                        outbound_messages = :outbound_messages,
                        suppressed_messages = :suppressed_messages,
                        duration_minutes = EXTRACT(EPOCH FROM (NOW() - started_at)) / 60
                    WHERE id = :id
                """), {
                    "turns": turns,
                    "eng_scores": json.dumps(engagement_scores or []),
                    "avg_eng": avg_engagement,
                    "early": early_termination,
                    "nc": v2_stats.get("nodes_created", 0),
                    "nu": v2_stats.get("nodes_updated", 0),
                    "ec": v2_stats.get("edges_created", 0),
                    "nw": v2_stats.get("notes_written", 0),
                    "smu": v2_stats.get("self_model_updated", False),
                    "summary": f"{end_reason}: {turns} turns, mode={mode}",
                    "primary_topic": primary_topic,
                    "primary_objective": primary_objective,
                    "expected_artifact": expected_artifact,
                    "outcome_type": outcome_type,
                    "artifact_summary": artifact_summary,
                    "outbound_messages": outbound_messages,
                    "suppressed_messages": suppressed_messages,
                    "id": session_log_id,
                })
                await db.commit()
        except Exception as e:
            logger.warning(f"Failed to update session log: {e}")

    await state_machine.set_active_session(user_id, None)

    # Transition state
    current = await state_machine.get_state(user_id)
    if current in (ACSState.AUTONOMOUS, ACSState.PAUSING):
        if end_reason == "conversation":
            await state_machine.set_state(user_id, ACSState.CONVERSATIONAL, reason="session_ended")
        else:
            await state_machine.set_state(user_id, ACSState.COOLDOWN, reason=f"session_ended:{end_reason}")
            r = await aioredis.from_url(REDIS_URL, decode_responses=True)
            try:
                cooldown_min = await state_machine.get_cooldown_minutes(user_id)
                until = local_now() + timedelta(minutes=cooldown_min)
                await r.set(f"sara:acs:cooldown_until:{user_id}", until.isoformat())
            finally:
                await _close_redis(r)

    # Save enriched handoff as fallback (if Sara didn't produce one explicitly)
    if session_memory:
        try:
            await _save_handoff(
                user_id,
                block={
                    "was_doing": f"Session ended ({end_reason}) after {turns} turns",
                    "got_to": f"Mode: {mode or 'v1'}, notes: {notes_created}",
                    "next_time": "",
                    "open_questions": "",
                },
                session_memory=session_memory,
                mode=mode,
                turns=turns,
            )
        except Exception as e:
            logger.debug(f"Fallback handoff save failed: {e}")

    # Flush summary to subconscious buffer
    try:
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            summary_data = {
                "session_id": session_id,
                "turns": turns,
                "notes_created": notes_created,
                "curiosities_explored": curiosities_explored,
                "end_reason": end_reason,
                "ended_at": local_now().isoformat(),
            }
            if mode:
                summary_data["mode"] = mode
                summary_data["avg_engagement"] = avg_engagement
                summary_data.update(v2_stats or {})
            await r.set("sara:subconscious:autonomous_summary", json.dumps(summary_data), ex=3600)
        finally:
            await _close_redis(r)
    except Exception as e:
        logger.debug(f"Failed to flush subconscious summary: {e}")

    # Inject ACS signals into working memory for salience/deliberation pipeline
    try:
        from app.services.working_memory import inject_acs_signals
        await inject_acs_signals(user_id)
    except Exception as e:
        logger.debug(f"ACS working memory signal injection failed: {e}")

    # Deliver high-priority show-david items as a single consolidated notification
    # Guard: only send if no ACS discovery notification was sent in the last 4 hours
    try:
        async with async_session() as db:
            # Check if we already sent an acs_discovery notification recently
            recent_check = await db.execute(text("""
                SELECT COUNT(*) FROM notification_log
                WHERE user_id = :uid
                  AND category = 'acs_discovery'
                  AND sent = TRUE
                  AND sent_at > NOW() - INTERVAL '4 hours'
            """), {"uid": user_id})
            recent_count = recent_check.scalar() or 0

            result = await db.execute(text("""
                SELECT id, title, content, category FROM acs_show_david_buffer
                WHERE user_id = :uid
                  AND delivery_status = 'queued'
                ORDER BY priority DESC, created_at DESC
                LIMIT 5
            """), {"uid": user_id})
            items = result.fetchall()

            if items:
                if recent_count == 0:
                    # Send one consolidated push notification
                    from app.services.unified_notification import send_notification

                    if len(items) == 1:
                        notif_title = f"Sara discovered: {items[0][1]}"
                        notif_body = _truncate_for_push(items[0][2] or "")
                    else:
                        notif_title = f"Sara found {len(items)} things to share"
                        summaries = []
                        for item in items:
                            summaries.append(f"\u2022 {item[1]}")
                        notif_body = "\n".join(summaries)

                    # Dedupe key ensures max 1 discovery attention item per
                    # day. Without it, each session that flushes show_david
                    # items creates a separate inbox entry with the same
                    # content, and the user sees "Sara found N things" three
                    # times in a row.
                    from datetime import date as _date
                    discovery_dedupe = f"acs_discovery:{user_id}:{_date.today().isoformat()}"

                    await send_notification(
                        user_id=user_id,
                        title=notif_title,
                        message=notif_body,
                        priority="low",
                        topic=discovery_dedupe,
                        category="acs_discovery",
                        source="acs_session",
                        cooldown_hours=4.0,
                        db=db,
                    )
                    logger.info(f"Delivered {len(items)} show-david items as 1 consolidated notification")
                else:
                    logger.info(f"Skipped ACS notification — already sent {recent_count} in last 4h")

                # Always mark items as shown regardless of whether we pushed
                for item in items:
                    await db.execute(text("""
                        UPDATE acs_show_david_buffer
                        SET shown = TRUE,
                            shown_at = NOW(),
                            delivery_status = 'delivered'
                        WHERE id = :id
                    """), {"id": item[0]})
                await db.commit()
    except Exception as e:
        logger.debug(f"Show-david delivery failed: {e}")

    logger.info(
        f"ACS session {session_id[:8]} ended: reason={end_reason}, "
        f"turns={turns}, notes={notes_created}, curiosities={curiosities_explored}"
        f"{f', mode={mode}, avg_eng={avg_engagement:.2f}' if mode and avg_engagement else ''}"
    )

    # Persist transcript, generate humanized log, then run audit (guaranteed)
    if transcript:
        try:
            from app.services.acs.audit_logger import persist_transcript
            await persist_transcript(user_id, transcript)
        except Exception as e:
            logger.warning(f"Transcript persistence failed: {e}")
        # Run audit pipeline — await to guarantee completion
        try:
            await _transcript_then_audit(user_id, session_id)
        except Exception as e:
            logger.warning(f"Post-session audit failed (will be retried): {e}")

    publish_data = {
        "session_id": session_id, "end_reason": end_reason,
        "turns": turns, "notes_created": notes_created,
        "curiosities_explored": curiosities_explored,
    }
    if mode:
        publish_data["mode"] = mode
        publish_data["avg_engagement"] = avg_engagement
    await _publish_live(user_id, "session_ended", publish_data)
