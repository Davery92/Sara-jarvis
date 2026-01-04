"""
Context Router Service

Determines which contexts (memory, cognitive, insight) to inject based on
message intent and conversation state. This reduces token usage by only
injecting context when relevant.
"""

from typing import List, NamedTuple
import logging

logger = logging.getLogger(__name__)


class ContextDecision(NamedTuple):
    """Decision about which contexts to inject"""
    inject_memory: bool
    inject_cognitive: bool
    inject_insight: bool
    reason: str


class ContextRouter:
    """
    Determines which contexts to inject based on intent and conversation state.

    This reduces token usage by avoiding unnecessary context injection:
    - Memory context: Only when recalling past or asking personal questions
    - Cognitive context: Only on personal/conversational messages
    - Insight context: Only on substantive questions
    """

    # Keywords that indicate memory retrieval is needed
    MEMORY_KEYWORDS = [
        'remember', 'recall', 'earlier', 'before', 'last time', 'yesterday',
        'previously', 'told you', 'mentioned', 'we discussed', 'we talked',
        'did i', 'did we', 'have i', 'have we', 'what did', 'when did',
        'my history', 'in the past'
    ]

    # Intents that typically benefit from memory context
    # GENERAL included because it's the fallback for unclear messages that may need context
    MEMORY_INTENTS = ['MEMORY', 'NOTES', 'CONVERSATIONAL', 'GENERAL']

    # Intents for personal/conversational context
    COGNITIVE_INTENTS = ['CONVERSATIONAL', 'MEMORY']

    # Intents that don't need insight injection (task-focused)
    NO_INSIGHT_INTENTS = ['TIME', 'HOME', 'FITNESS', 'CHESS']

    def decide(
        self,
        intent: str,
        message: str,
        turn_count: int,
        has_question: bool = None
    ) -> ContextDecision:
        """
        Determine which contexts to inject for a message.

        Args:
            intent: The classified intent (from ToolIntentClassifier)
            message: The user's message text
            turn_count: Number of turns in the conversation
            has_question: Whether the message contains a question (auto-detect if None)

        Returns:
            ContextDecision with boolean flags for each context type
        """
        if has_question is None:
            has_question = '?' in message

        message_lower = message.lower()

        # Determine if memory context should be injected
        inject_memory = self._should_inject_memory(intent, message_lower, turn_count, has_question)

        # Determine if cognitive context should be injected
        inject_cognitive = self._should_inject_cognitive(intent, turn_count)

        # Determine if insight context should be injected
        inject_insight = self._should_inject_insight(intent, has_question)

        # Build reason string for logging
        reasons = []
        if inject_memory:
            reasons.append("memory")
        if inject_cognitive:
            reasons.append("cognitive")
        if inject_insight:
            reasons.append("insight")

        reason = f"Injecting: {', '.join(reasons) if reasons else 'none'}"

        decision = ContextDecision(
            inject_memory=inject_memory,
            inject_cognitive=inject_cognitive,
            inject_insight=inject_insight,
            reason=reason
        )

        logger.info(
            f"[ContextRouter] Intent={intent}, turns={turn_count}, "
            f"has_q={has_question} -> {reason}"
        )

        return decision

    def _should_inject_memory(
        self,
        intent: str,
        message_lower: str,
        turn_count: int,
        has_question: bool
    ) -> bool:
        """
        Memory context is needed when:
        1. User is explicitly recalling past conversations
        2. User is asking a question
        3. Intent involves memory, notes, conversation, or is unclear (GENERAL)
        4. Early in conversation (context helps establish rapport)

        For a personal AI assistant, memory should be available most of the time.
        Only skip for simple task-focused intents like TIME, HOME, FITNESS.
        """
        # Explicit recall keywords always need memory
        if any(kw in message_lower for kw in self.MEMORY_KEYWORDS):
            return True

        # Memory/Notes/Conversational/General intents need context
        if intent in self.MEMORY_INTENTS:
            return True

        # Questions often benefit from context
        if has_question:
            return True

        # Early turns benefit from context (establishes rapport)
        if turn_count <= 2:
            return True

        return False

    def _should_inject_cognitive(self, intent: str, turn_count: int) -> bool:
        """
        Cognitive context (hypotheses, relationship insights) is needed when:
        1. Personal/conversational interaction
        2. Early in conversation (first 2 turns)
        """
        # Only for personal intents
        if intent not in self.COGNITIVE_INTENTS:
            return False

        # Only in early turns
        if turn_count > 2:
            return False

        return True

    def _should_inject_insight(self, intent: str, has_question: bool) -> bool:
        """
        Insight context is needed when:
        1. User is asking a substantive question
        2. Not a task-focused intent (timer, home automation, etc.)
        """
        # Skip for task-focused intents
        if intent in self.NO_INSIGHT_INTENTS:
            return False

        # Only inject for questions
        if not has_question:
            return False

        return True


# Singleton instance
_context_router = None


def get_context_router() -> ContextRouter:
    """Get or create the context router singleton"""
    global _context_router
    if _context_router is None:
        _context_router = ContextRouter()
    return _context_router
