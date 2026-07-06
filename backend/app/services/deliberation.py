"""
Deliberation Engine — Sara's focused decision-making.

Replaces the unified agent's multi-turn LLM tool-calling loop with a single
structured LLM call. Reads pre-synthesized working memory + pending observations,
returns structured decisions.

Usage:
    from app.services.deliberation import deliberation_engine
    result = await deliberation_engine.run(user_id)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.deliberation_prompt import build_deliberation_prompt
from app.services.observation_log import Observation, get_pending_observations
from app.services.working_memory import read_memory

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


@dataclass
class NotificationProposal:
    title: str
    message: str
    priority: str = "normal"  # normal, high, critical
    category: str = "general"  # schedule, security, social, health, check_in, home
    reason: str = ""


@dataclass
class HomeActionProposal:
    action: str  # light_control, lock_control, switch_control
    entity_id: str
    state: str  # on, off
    reason: str = ""


@dataclass
class TaskProposal:
    description: str  # What the task should accomplish
    category: str     # research, pkg_update, note_organization, home_control, maintenance
    confidence: float = 0.7  # How confident Sara is this is useful
    reason: str = ""  # Why Sara thinks this is worth doing


@dataclass
class DeliberationResult:
    thought: str = ""
    journal_note: str = ""
    notification_proposals: List[NotificationProposal] = field(default_factory=list)
    home_actions: List[HomeActionProposal] = field(default_factory=list)
    task_proposals: List[TaskProposal] = field(default_factory=list)
    research_proposals: List[str] = field(default_factory=list)
    state_update: Dict[str, Any] = field(default_factory=dict)
    handoff_note: str = ""
    watching_for: str = ""
    observations_consumed: List[str] = field(default_factory=list)
    raw_response: str = ""
    tokens_used: int = 0
    duration_seconds: float = 0.0


class DeliberationEngine:
    """
    Focused LLM deliberation: single call, structured JSON output.
    No tool-calling loop — working memory already has all the context.
    """

    def __init__(self):
        self._llm_client = None

    def _get_llm_client(self):
        if self._llm_client is None:
            from app.core.llm import get_background_llm_client
            self._llm_client = get_background_llm_client()
        return self._llm_client

    async def run(self, user_id: str = DEFAULT_USER_ID) -> DeliberationResult:
        """
        Run a deliberation cycle.
        1. Read working memory
        2. Get pending observations
        3. Build prompt
        4. Single LLM call for structured JSON
        5. Parse and return result
        """
        start_time = datetime.now(timezone.utc)
        result = DeliberationResult()

        # 1. Read working memory
        memory = await read_memory(user_id)

        # 2. Get pending observations
        observations = await get_pending_observations(user_id, min_salience=0.0, limit=15)

        # 2b. Off-rhythm deviations — salience input only, never pushed directly.
        off_rhythm_flags: List[Dict[str, str]] = []
        try:
            from app.db.base import SessionLocal
            from app.services.daily_rhythm import get_off_rhythm_flags
            with SessionLocal() as db:
                off_rhythm_flags = get_off_rhythm_flags(db, user_id, current_place_type=memory.current_place_type)
        except Exception as e:
            logger.warning(f"Off-rhythm flag gather failed: {e}")

        # 3. Build prompt
        system_msg, user_msg = build_deliberation_prompt(
            memory=memory,
            observations=observations,
            recent_handoff=memory.last_heartbeat_handoff,
            off_rhythm_flags=off_rhythm_flags,
        )

        # 4. LLM call
        try:
            client = self._get_llm_client()
            response = await client.chat_completion(
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.4,
                max_tokens=1500,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )

            # Extract content from OpenAI-compatible response
            raw = ""
            if isinstance(response, dict):
                choices = response.get("choices", [])
                if choices:
                    raw = choices[0].get("message", {}).get("content", "")
                result.tokens_used = response.get("usage", {}).get("total_tokens", 0)
            else:
                raw = str(response)
            result.raw_response = raw

        except Exception as e:
            logger.error(f"[Deliberation] LLM call failed: {e}")
            result.thought = f"Deliberation failed: {e}"
            result.duration_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
            return result

        # 5. Parse response
        try:
            parsed = self._parse_response(raw)
            result.thought = parsed.get("thought", "")
            result.journal_note = parsed.get("journal_note", "")
            result.handoff_note = parsed.get("handoff_note", "")
            result.watching_for = parsed.get("watching_for", "")

            # Parse notification proposals
            for np in parsed.get("notification_proposals", []):
                if isinstance(np, dict) and np.get("title"):
                    result.notification_proposals.append(NotificationProposal(
                        title=np["title"],
                        message=np.get("message", ""),
                        priority=np.get("priority", "normal"),
                        category=np.get("category", "general"),
                    ))

            # Parse home actions
            for ha in parsed.get("home_actions", []):
                if isinstance(ha, dict) and ha.get("action") and ha.get("entity_id"):
                    result.home_actions.append(HomeActionProposal(
                        action=ha["action"],
                        entity_id=ha["entity_id"],
                        state=ha.get("state", "off"),
                        reason=ha.get("reason", ""),
                    ))

            # Parse task proposals
            for tp in parsed.get("task_proposals", []):
                if isinstance(tp, dict) and tp.get("description"):
                    result.task_proposals.append(TaskProposal(
                        description=tp["description"],
                        category=tp.get("category", "research"),
                        confidence=float(tp.get("confidence", 0.7)),
                        reason=tp.get("reason", ""),
                    ))

            # Parse research proposals
            for rp in parsed.get("research_proposals", []):
                if isinstance(rp, str) and rp.strip():
                    result.research_proposals.append(rp.strip())

            # Parse state update
            result.state_update = parsed.get("state_update", {})

        except Exception as e:
            logger.error(f"[Deliberation] Response parse failed: {e}")
            result.thought = f"Parse failed: {e}. Raw: {raw[:200]}"

        # Always consume observations after deliberation — even on parse failure.
        # Otherwise stale observations persist and re-trigger the same deliberation loop.
        result.observations_consumed = [obs.id for obs in observations]

        result.duration_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(
            f"[Deliberation] Complete in {result.duration_seconds:.1f}s: "
            f"{len(result.notification_proposals)} notifications, "
            f"{len(result.home_actions)} home actions, "
            f"{len(result.task_proposals)} task proposals, "
            f"{len(result.research_proposals)} research proposals, "
            f"{len(result.observations_consumed)} observations consumed"
        )
        return result

    def _parse_response(self, raw: str) -> dict:
        """Parse LLM response as JSON, handling markdown fences and leading prose."""
        text = raw.strip()

        # Strip markdown code fences
        if "```" in text:
            # Extract content between first ``` and last ```
            parts = text.split("```")
            if len(parts) >= 3:
                inner = parts[1]
                # Remove optional language tag (e.g., "json")
                if inner.startswith("json"):
                    inner = inner[4:]
                text = inner.strip()
            else:
                # Single ``` pair — strip all fence lines
                lines = text.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines).strip()

        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # LLM sometimes prefixes JSON with prose — find first { and try from there
        brace_idx = text.find("{")
        if brace_idx > 0:
            candidate = text[brace_idx:]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        # Last resort: try to find JSON object between first { and last }
        if brace_idx >= 0:
            last_brace = text.rfind("}")
            if last_brace > brace_idx:
                candidate = text[brace_idx:last_brace + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass

        # Nothing worked — raise the original error
        raise json.JSONDecodeError("No valid JSON found in response", text, 0)


# Module-level singleton
deliberation_engine = DeliberationEngine()
