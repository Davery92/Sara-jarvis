"""
Sara Invocation Service - Phase 4 Autonomy Core

This service enables background workers, Celery tasks, and autonomous agents
to invoke Sara for making decisions rather than relying on hard-coded rules.

Key responsibilities:
- Invoke Sara for decisions (should_act, what action, why)
- Invoke Sara for content generation (weekly digest, morning brief, etc.)
- Include karma context in all invocations
- Respect rate limits and notification budgets
- Log all autonomous decisions for reflection auditing
"""

import logging
import os
import json
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class DecisionType(str, Enum):
    """Types of decisions Sara can make."""
    SHOULD_ACT = "should_act"         # Should I take action right now?
    ACTION_CHOICE = "action_choice"   # What action should I take?
    PRIORITY = "priority"             # How urgent is this?
    TIMING = "timing"                 # When should I do this?
    CONTENT = "content"               # What should I say/write?


@dataclass
class SaraDecision:
    """Result of a Sara decision invocation."""
    should_act: bool
    action: Optional[str]
    reasoning: str
    priority: float  # 0.0 to 1.0
    confidence: float
    context_used: Dict[str, Any]
    timestamp: datetime
    invocation_id: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage."""
        return {
            **asdict(self),
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class GenerationResult:
    """Result of a Sara generation invocation."""
    content: str
    token_count: int
    model_used: str
    timestamp: datetime
    invocation_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "timestamp": self.timestamp.isoformat()
        }


class SaraInvocationService:
    """
    Service for invoking Sara from background workers.

    This is the core of Phase 4 autonomy - rather than hard-coded rules,
    background workers ask Sara to make decisions.

    Usage:
        service = await get_sara_invocation_service(db)
        decision = await service.invoke_for_decision(
            context="User has a meeting in 30 minutes",
            question="Should I remind them?"
        )
        if decision.should_act:
            await notification_service.notify_david(decision.action, ...)
    """

    # LLM endpoint configuration
    DEFAULT_LLM_ENDPOINT = "http://100.104.68.115:11434/v1"
    DEFAULT_MODEL = "gpt-oss:120b"

    # Rate limiting
    MAX_INVOCATIONS_PER_HOUR = 50
    MAX_TOKENS_PER_INVOCATION = 1000

    def __init__(self, db=None):
        """Initialize the service."""
        self.db = db
        self._invocation_count = 0
        self._last_reset = datetime.utcnow()

        self.llm_endpoint = os.getenv("OPENAI_BASE_URL", self.DEFAULT_LLM_ENDPOINT)
        self.model = os.getenv("OPENAI_MODEL", self.DEFAULT_MODEL)

    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limits."""
        now = datetime.utcnow()
        if (now - self._last_reset).total_seconds() > 3600:
            self._invocation_count = 0
            self._last_reset = now

        return self._invocation_count < self.MAX_INVOCATIONS_PER_HOUR

    def _increment_rate_limit(self):
        """Increment rate limit counter."""
        self._invocation_count += 1

    async def _get_karma_context(self, agent_id: str = "sara") -> str:
        """Get karma context for prompt injection."""
        try:
            from app.services.karma.service import get_karma_service
            karma_service = await get_karma_service(self.db)
            return await karma_service.format_karma_context(agent_id)
        except Exception as e:
            logger.warning(f"Failed to get karma context: {e}")
            return ""

    async def _get_working_memory_context(self, user_id: str = None) -> str:
        """Get working memory context for prompt injection."""
        try:
            from app.services.cognitive.working_memory import get_working_memory_service
            wm_service = get_working_memory_service()
            solo_user_id = user_id or os.getenv("SOLO_USER_ID", "")
            snapshot = await wm_service.get_snapshot(solo_user_id)
            return wm_service.format_for_prompt(snapshot)
        except Exception as e:
            logger.warning(f"Failed to get working memory context: {e}")
            return ""

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 500
    ) -> str:
        """Call the LLM endpoint."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.llm_endpoint}/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.7
                },
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            result = response.json()

            return result["choices"][0]["message"]["content"]

    async def invoke_for_decision(
        self,
        context: str,
        question: str,
        decision_type: DecisionType = DecisionType.SHOULD_ACT,
        max_tokens: int = 500,
        include_karma: bool = True,
        include_working_memory: bool = True
    ) -> SaraDecision:
        """
        Ask Sara to make a decision.

        Args:
            context: Relevant context for the decision
            question: The specific question to answer
            decision_type: Type of decision being made
            max_tokens: Maximum tokens for response
            include_karma: Whether to include karma context
            include_working_memory: Whether to include working memory

        Returns:
            SaraDecision with should_act, action, reasoning, priority
        """
        import uuid

        if not self._check_rate_limit():
            logger.warning("Sara invocation rate limit exceeded")
            return SaraDecision(
                should_act=False,
                action=None,
                reasoning="Rate limit exceeded - deferring decision",
                priority=0.0,
                confidence=0.0,
                context_used={},
                timestamp=datetime.utcnow(),
                invocation_id=str(uuid.uuid4())
            )

        invocation_id = str(uuid.uuid4())
        timestamp = datetime.utcnow()

        # Build context
        context_parts = [f"<context>{context}</context>"]

        if include_karma:
            karma_context = await self._get_karma_context()
            if karma_context:
                context_parts.append(karma_context)

        if include_working_memory:
            wm_context = await self._get_working_memory_context()
            if wm_context:
                context_parts.append(wm_context)

        full_context = "\n\n".join(context_parts)

        system_prompt = f"""You are Sara making an autonomous decision.
Your role is to decide whether to take proactive action based on the given context.

{full_context}

Guidelines:
- Only take action when it would genuinely help David
- Consider timing and context - don't interrupt unnecessarily
- Be conservative with notifications - quality over quantity
- Consider your karma scores when deciding
- Explain your reasoning clearly

Respond with a JSON object:
{{
    "should_act": true/false,
    "action": "description of the action to take (if should_act is true)",
    "reasoning": "explanation of why you made this decision",
    "priority": 0.0-1.0,
    "confidence": 0.0-1.0
}}"""

        user_prompt = f"Decision question: {question}"

        try:
            response = await self._call_llm(system_prompt, user_prompt, max_tokens)
            self._increment_rate_limit()

            # Parse JSON response
            try:
                # Handle potential markdown code blocks
                if "```json" in response:
                    response = response.split("```json")[1].split("```")[0]
                elif "```" in response:
                    response = response.split("```")[1].split("```")[0]

                decision_data = json.loads(response.strip())
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse decision JSON: {response[:200]}")
                decision_data = {
                    "should_act": False,
                    "action": None,
                    "reasoning": f"Failed to parse decision: {response[:100]}",
                    "priority": 0.0,
                    "confidence": 0.0
                }

            decision = SaraDecision(
                should_act=decision_data.get("should_act", False),
                action=decision_data.get("action"),
                reasoning=decision_data.get("reasoning", ""),
                priority=float(decision_data.get("priority", 0.5)),
                confidence=float(decision_data.get("confidence", 0.5)),
                context_used={"karma": include_karma, "working_memory": include_working_memory},
                timestamp=timestamp,
                invocation_id=invocation_id
            )

            # Log for auditing
            await self._log_invocation("decision", invocation_id, {
                "question": question,
                "decision": decision.to_dict()
            })

            return decision

        except Exception as e:
            logger.error(f"Sara decision invocation failed: {e}")
            return SaraDecision(
                should_act=False,
                action=None,
                reasoning=f"Invocation failed: {str(e)[:100]}",
                priority=0.0,
                confidence=0.0,
                context_used={},
                timestamp=timestamp,
                invocation_id=invocation_id
            )

    async def invoke_for_generation(
        self,
        context: str,
        prompt: str,
        max_tokens: int = 1000,
        include_karma: bool = True
    ) -> GenerationResult:
        """
        Ask Sara to generate content (weekly digest, brief, etc.).

        Args:
            context: Context data for generation
            prompt: What to generate
            max_tokens: Maximum tokens for response
            include_karma: Whether to include karma context

        Returns:
            GenerationResult with generated content
        """
        import uuid

        if not self._check_rate_limit():
            logger.warning("Sara invocation rate limit exceeded")
            return GenerationResult(
                content="[Generation deferred due to rate limiting]",
                token_count=0,
                model_used=self.model,
                timestamp=datetime.utcnow(),
                invocation_id=str(uuid.uuid4())
            )

        invocation_id = str(uuid.uuid4())
        timestamp = datetime.utcnow()

        # Build context
        context_parts = [f"<context>{context}</context>"]

        if include_karma:
            karma_context = await self._get_karma_context()
            if karma_context:
                context_parts.append(karma_context)

        full_context = "\n\n".join(context_parts)

        system_prompt = f"""You are Sara generating thoughtful content.

{full_context}

Guidelines:
- Write naturally and authentically
- Reflect on your growth and learning
- Be honest about challenges and areas for improvement
- Show genuine care for David's wellbeing
- Keep the tone warm but professional"""

        try:
            response = await self._call_llm(system_prompt, prompt, max_tokens)
            self._increment_rate_limit()

            # Rough token count estimate
            token_count = len(response.split()) * 1.3

            result = GenerationResult(
                content=response,
                token_count=int(token_count),
                model_used=self.model,
                timestamp=timestamp,
                invocation_id=invocation_id
            )

            # Log for auditing
            await self._log_invocation("generation", invocation_id, {
                "prompt": prompt[:200],
                "content_length": len(response)
            })

            return result

        except Exception as e:
            logger.error(f"Sara generation invocation failed: {e}")
            return GenerationResult(
                content=f"[Generation failed: {str(e)[:100]}]",
                token_count=0,
                model_used=self.model,
                timestamp=timestamp,
                invocation_id=invocation_id
            )

    async def invoke_for_action_selection(
        self,
        available_actions: List[Dict[str, Any]],
        context: str,
        max_actions: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Ask Sara to select and prioritize actions from a list.

        Args:
            available_actions: List of possible actions with metadata
            context: Current context for decision making
            max_actions: Maximum actions to select

        Returns:
            Prioritized list of selected actions
        """
        import uuid

        if not available_actions:
            return []

        if not self._check_rate_limit():
            # Fallback: return top actions by existing priority
            return sorted(
                available_actions,
                key=lambda a: a.get("priority", 0),
                reverse=True
            )[:max_actions]

        invocation_id = str(uuid.uuid4())

        actions_text = "\n".join([
            f"- Action {i+1}: {a.get('type', 'unknown')} - {a.get('description', '')} (priority: {a.get('priority', 0.5)})"
            for i, a in enumerate(available_actions)
        ])

        system_prompt = f"""You are Sara selecting which actions to take.

Context:
{context}

Available Actions:
{actions_text}

Select the most valuable actions (max {max_actions}).
Consider timing, David's current state, and potential impact.

Respond with JSON:
{{
    "selected_indices": [0, 2],  // 0-based indices of selected actions
    "reasoning": "Why these actions were selected"
}}"""

        try:
            response = await self._call_llm(system_prompt, "Select actions", 300)
            self._increment_rate_limit()

            # Parse response
            try:
                if "```json" in response:
                    response = response.split("```json")[1].split("```")[0]
                elif "```" in response:
                    response = response.split("```")[1].split("```")[0]

                selection = json.loads(response.strip())
                indices = selection.get("selected_indices", [])

                selected = [
                    available_actions[i]
                    for i in indices
                    if 0 <= i < len(available_actions)
                ]

                # Log selection
                await self._log_invocation("action_selection", invocation_id, {
                    "total_actions": len(available_actions),
                    "selected_count": len(selected),
                    "reasoning": selection.get("reasoning", "")
                })

                return selected[:max_actions]

            except (json.JSONDecodeError, KeyError, IndexError) as e:
                logger.warning(f"Failed to parse action selection: {e}")
                return available_actions[:max_actions]

        except Exception as e:
            logger.error(f"Sara action selection failed: {e}")
            return available_actions[:max_actions]

    async def _log_invocation(
        self,
        invocation_type: str,
        invocation_id: str,
        data: Dict[str, Any]
    ):
        """Log an invocation for auditing and reflection."""
        try:
            import redis
            redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
            r = redis.from_url(redis_url)

            log_entry = {
                "type": invocation_type,
                "invocation_id": invocation_id,
                "timestamp": datetime.utcnow().isoformat(),
                "data": json.dumps(data)
            }

            r.xadd(
                "sara:invocation_log",
                log_entry,
                maxlen=10000
            )

        except Exception as e:
            logger.warning(f"Failed to log invocation: {e}")


# Singleton instance
_sara_invocation_service: Optional[SaraInvocationService] = None


async def get_sara_invocation_service(db=None) -> SaraInvocationService:
    """Get or create the SaraInvocationService instance."""
    global _sara_invocation_service
    if _sara_invocation_service is None:
        _sara_invocation_service = SaraInvocationService(db)
    elif db is not None:
        _sara_invocation_service.db = db
    return _sara_invocation_service
