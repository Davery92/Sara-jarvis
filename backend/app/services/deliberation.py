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
    category: str = "general"  # schedule, security, social, health, checkin, home
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
class ToolCall:
    """Work-order item 11 (KERNEL_HANDS, 2026-07-30): at most one tool call
    per deliberation turn — a lane-routed action (app/services/kernel_hands.py),
    not a multi-round agentic loop. Kept to the same "one structured decision"
    paradigm every other field in this schema already uses."""
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""


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
    tool_call: Optional[ToolCall] = None
    observations_consumed: List[str] = field(default_factory=list)
    raw_response: str = ""
    tokens_used: int = 0
    duration_seconds: float = 0.0
    is_deep: bool = False
    success: bool = True
    error: str = ""


async def _deep_llm_call(messages: List[Dict[str, str]], max_tokens: int = 3000) -> Dict[str, Any]:
    """Deep-deliberation LLM call — local-first fix (2026-07-31): this used to
    dispatch directly to the Anthropic API (`claude-sonnet-5` via a raw
    httpx POST), a local-first violation — deep deliberation is background
    cognition (2x/day, unattended), and Claude models are chat-persona only
    (feedback_local_first_llm). Routed through llm_broker's "kernel"
    capability instead (the same class every other background-cognition
    call uses — deliberation/ambient turns/consolidation — resolved to the
    local Qwen 27B host).

    Uses `resolve("kernel")` + a raw httpx POST rather than
    `get_broker_client()`'s AsyncOpenAI wrapper — found while wiring this up
    that `openai` isn't an installed dependency in this container, so that
    factory has never actually been callable (a separate, pre-existing bug,
    out of scope for this fix). httpx is already this module's proven,
    working transport.
    """
    import httpx
    from app.core.config import settings
    from app.services.llm_broker import resolve

    cap = resolve("kernel")
    base_url = (cap["base_url"] or "").rstrip("/")
    model = cap["model"]

    system_content = None
    filtered = []
    for m in messages:
        if m.get("role") == "system":
            system_content = m.get("content", "")
        else:
            filtered.append(m)
    if system_content:
        filtered = [{"role": "system", "content": system_content}] + filtered

    payload: Dict[str, Any] = {
        "model": model,
        "messages": filtered,
        "max_tokens": max_tokens,
        "temperature": 0.4,
        # gotcha_qwen_thinking: without this, `content` comes back empty for
        # structured/short outputs like this JSON turn.
        "chat_template_kwargs": {"enable_thinking": False},
    }

    # Same 180s the old Anthropic call used ("hourly deliberations measure
    # 53-61s, any slow sample on the local 27B was a coin-flip against the
    # old 90s kill threshold") — still the right budget on the same host.
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {getattr(settings, 'openai_api_key', '') or 'not-needed'}"},
        )
        response.raise_for_status()
        result = response.json()

    choices = result.get("choices", [])
    text = choices[0].get("message", {}).get("content", "") if choices else ""
    usage = result.get("usage", {})
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
    }


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

    async def run(
        self, user_id: str = DEFAULT_USER_ID, deep: bool = False,
        wake_reason: Optional[str] = None,
    ) -> DeliberationResult:
        """
        Run a deliberation cycle.
        1. Read working memory
        2. Get pending observations
        3. Build prompt
        4. Single LLM call for structured JSON
        5. Parse and return result

        SARA_UNLEASHED Phase C.3: `deep=True` runs with a wider observation
        window and a higher task-proposal cap than the hourly pass, on the
        same local Qwen "kernel" capability (local-first fix, 2026-07-31 —
        previously ran on Anthropic, a background-cognition local-first
        violation). Intended for 2x/day scheduled runs, not the
        salience-triggered hourly path.

        `wake_reason` (Arc 3.1) is passed straight through to the prompt
        builder as context only — see `build_deliberation_prompt`.
        """
        start_time = datetime.now(timezone.utc)
        result = DeliberationResult(is_deep=deep)

        # 1. Read working memory
        memory = await read_memory(user_id)

        # 2. Get pending observations — deep runs see a much wider window
        # (50 vs 15) since they run only 2x/day and are meant to catch
        # backlog the hourly pass missed, not just the freshest signals.
        observations = await get_pending_observations(user_id, min_salience=0.0, limit=50 if deep else 15)

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
        kernel_hands_on = False
        try:
            from app.core.feature_flags import Flag as _KhFlag, is_enabled as _kh_enabled
            kernel_hands_on = _kh_enabled(_KhFlag.KERNEL_HANDS)
        except Exception:
            pass
        system_msg, user_msg = build_deliberation_prompt(
            memory=memory,
            observations=observations,
            recent_handoff=memory.last_heartbeat_handoff,
            off_rhythm_flags=off_rhythm_flags,
            deep=deep,
            wake_reason=wake_reason,
            kernel_hands=kernel_hands_on,
        )

        # 3b. Interoception — inject a health digest so Sara can *feel* her own
        # broken parts and choose to tell David (Phase 2). Only surfaces tasks
        # that cross the escalation threshold; None when healthy.
        try:
            from app.services.diagnostics_service import build_health_digest
            _digest = await build_health_digest()
            if _digest:
                user_msg = f"{_digest}\n\n{user_msg}"
        except Exception as _de:
            logger.debug(f"health digest injection skipped: {_de}")

        # 3b2. Directives (Phase 12B) — David's standing rules, behavioral law.
        try:
            from app.services.directives import get_directives_for_context
            _dir = await get_directives_for_context(user_id)
            if _dir:
                user_msg = f"{_dir}\n\n{user_msg}"
        except Exception as _dre:
            logger.debug(f"directives injection skipped: {_dre}")

        # 3c. Life facts (Phase 10B) — David's known routine, so the brain reasons
        # from his schedule ("normally trains 13:10") instead of guessing.
        try:
            from app.services.life_facts import get_life_facts_summary
            _lf = await get_life_facts_summary(user_id)
            if _lf:
                user_msg = f"{_lf}\n\n{user_msg}"
        except Exception as _le:
            logger.debug(f"life facts injection skipped: {_le}")

        # 3d. Standing context scratchpad (Phase 10C) — things David told Sara to
        # keep front-of-mind ("meal prepped this week; smoothie every morning").
        try:
            from app.services.scratchpad import get_scratchpad_for_context
            _sp = await get_scratchpad_for_context(user_id)
            if _sp:
                user_msg = f"{_sp}\n\n{user_msg}"
        except Exception as _se:
            logger.debug(f"scratchpad injection skipped: {_se}")

        # 3e. Cross-domain signals (Phase 10D) — today's training-day status + a
        # food-log digest, plus guidance so deliberation *derives* the office/rest
        # and pre-gym-meal scenarios instead of a generic "how's your day".
        try:
            from app.services.situational_signals import build_situational_block
            _sig = await build_situational_block(user_id)
            if _sig:
                user_msg = f"{_sig}\n\n{user_msg}"
        except Exception as _sige:
            logger.debug(f"situational signals injection skipped: {_sige}")

        # 3f. Self-story (Arc 4.2) — "yesterday's self constrains today's."
        # sara_journal_service uses a sync Session; read fresh each turn
        # (same live-DB-read pattern as life_facts/scratchpad above), not
        # cached in working_memory's Redis snapshot.
        try:
            from app.db.session import SessionLocal
            from app.services.sara_journal_service import sara_journal
            with SessionLocal() as _sdb:
                _story = await sara_journal.get_self_story(_sdb, user_id)
            if _story:
                user_msg = f"## Your ongoing self-story\n{_story}\n\n{user_msg}"
        except Exception as _sse:
            logger.debug(f"self-story injection skipped: {_sse}")

        # 3g. Theory-of-David (Arc 4.5) — same live-DB-read pattern as 3f,
        # same table, same sync Session.
        try:
            from app.db.session import SessionLocal
            from app.services.sara_journal_service import sara_journal
            with SessionLocal() as _tdb:
                _tod = await sara_journal.get_theory_of_david(_tdb, user_id)
            if _tod:
                user_msg = f"## What you understand about David\n{_tod}\n\n{user_msg}"
        except Exception as _tode:
            logger.debug(f"theory-of-david injection skipped: {_tode}")

        # 4. LLM call — deep and hourly both stay local (qwen): deep via
        # llm_broker's "kernel" capability, hourly via BackgroundLLMClient.
        try:
            if deep:
                response = await _deep_llm_call(
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                    max_tokens=3000,
                )
            else:
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
            # Was a swallowed failure: this returned a normal-looking result
            # (empty proposals, no exception raised) with only a truncated
            # message buried in `thought` — the caller (kernel.ambient_turn)
            # had no way to distinguish "LLM call failed" from "legitimately
            # nothing to do," so it always reported status=completed and the
            # failure was invisible to interoception. `success`/`error` give
            # the caller an honest signal to act on.
            logger.error(f"[Deliberation] LLM call failed (deep={deep}): {e}")
            result.success = False
            result.error = str(e)
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

            # Parse tool_call (KERNEL_HANDS, work-order item 11) — at most
            # one, only meaningful when the flag is on (the prompt doesn't
            # describe the schema field otherwise, so the model shouldn't
            # emit it, but parse defensively either way).
            tc = parsed.get("tool_call")
            if isinstance(tc, dict) and tc.get("name"):
                result.tool_call = ToolCall(
                    name=str(tc["name"]),
                    args=tc.get("args") if isinstance(tc.get("args"), dict) else {},
                    reason=str(tc.get("reason", "")),
                )

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
