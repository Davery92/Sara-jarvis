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
    inject_daily_brief: bool
    inject_soul: bool  # Always True - Sara's core identity
    inject_pkg: bool  # Personal Knowledge Graph about David
    inject_patterns: bool  # Discovered behavioral patterns
    inject_activity_context: bool  # Activity state & interruptibility for tone adaptation
    inject_learning_recall: bool  # Test recall on topics David is studying
    inject_changes_brief: bool  # Changes since last chat (re-entry, first msg of day, "catch me up")
    inject_lessons: bool  # Lessons learned from past mistakes (self-correction)
    inject_fitness: bool  # Today's nutrition plan, macros eaten/remaining
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

    # Keywords that force daily brief injection even in work mode
    DAILY_BRIEF_KEYWORDS = [
        'schedule', 'today', 'calendar', 'my day', 'what do i have',
        'meetings', 'brief', 'agenda', 'plans for', 'appointments'
    ]

    # Keywords that trigger PKG injection
    PKG_KEYWORDS = [
        'i like', 'i prefer', 'i usually', 'my favorite', 'my goal',
        'do you know about me', 'do you remember', 'what do you know',
        'i always', 'i never', 'i love', 'i hate', 'my routine',
        'my schedule', 'my habit', 'about me', 'you know me'
    ]

    # Intents that benefit from PKG context
    PKG_INTENTS = ['CONVERSATIONAL', 'MEMORY', 'GENERAL', 'FITNESS']

    # Keywords that trigger pattern injection
    PATTERN_KEYWORDS = [
        'usually', 'pattern', 'routine', 'habit', 'every',
        'trend', 'notice', 'always seem', 'tend to'
    ]

    # Intents that benefit from pattern injection
    PATTERN_INTENTS = ['CONVERSATIONAL', 'FITNESS', 'GENERAL']

    # Keywords that suggest learning-adjacent questions (recall testing opportunities)
    LEARNING_RECALL_KEYWORDS = [
        'learn', 'study', 'review', 'practice', 'explain',
        'how does', 'what is', 'tell me about', 'how do',
        'what are', 'why does', 'why is', 'can you explain',
    ]

    # Intents eligible for learning recall injection
    LEARNING_RECALL_INTENTS = ['CONVERSATIONAL', 'KNOWLEDGE', 'GENERAL']

    # Keywords that trigger changes brief (what happened while away)
    CHANGES_BRIEF_KEYWORDS = [
        'catch me up', 'what happened', 'what did i miss', 'any updates',
        'anything new', 'what\'s new', 'fill me in', 'bring me up to speed',
        'while i was away', 'since last time',
    ]

    # Intents eligible for lesson injection (conversational quality improvement)
    LESSON_INTENTS = ['CONVERSATIONAL', 'GENERAL', 'KNOWLEDGE', 'MEMORY', 'NOTES']

    # Keywords that trigger fitness/nutrition context injection
    FITNESS_KEYWORDS = [
        'eat', 'eating', 'ate', 'meal', 'lunch', 'dinner', 'breakfast', 'snack',
        'packing', 'cook', 'cooking', 'making', 'food', 'recipe',
        'calories', 'calorie', 'carbs', 'protein', 'fat', 'fats', 'macros',
        'nutrition', 'diet', 'good choice', 'healthy', 'should i eat',
        'how much', 'portion', 'serving',
        'workout', 'training', 'gym', 'exercise', 'lift', 'cardio',
        'recovery', 'rest day', 'training day', 'phase', 'deload',
    ]

    # Intents that benefit from fitness context
    FITNESS_INTENTS = ['FITNESS', 'HEALTH']

    def decide(
        self,
        intent: str,
        message: str,
        turn_count: int,
        has_question: bool = None,
        in_work_mode: bool = False
    ) -> ContextDecision:
        """
        Determine which contexts to inject for a message.

        Args:
            intent: The classified intent (from ToolIntentClassifier)
            message: The user's message text
            turn_count: Number of turns in the conversation
            has_question: Whether the message contains a question (auto-detect if None)
            in_work_mode: Whether the user is in work mode (lean, task-focused context)

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

        # Determine if daily brief should be injected (body state removed from chat)
        inject_daily_brief = self._should_inject_daily_brief(message_lower, in_work_mode)
        # Soul is always injected - it's Sara's core identity
        inject_soul = True

        # Determine if PKG and patterns should be injected
        inject_pkg = self._should_inject_pkg(intent, message_lower, turn_count, in_work_mode)
        inject_patterns = self._should_inject_patterns(intent, message_lower, turn_count, in_work_mode)

        # Activity context is always injected (lightweight, drives tone)
        inject_activity_context = True

        # Determine if learning recall testing should be injected
        inject_learning_recall = self._should_inject_learning_recall(intent, message_lower, in_work_mode)

        # Determine if changes brief should be injected (first msg after gap, "catch me up", etc.)
        inject_changes_brief = self._should_inject_changes_brief(message_lower, turn_count)

        # Determine if lessons from past mistakes should be injected
        inject_lessons = self._should_inject_lessons(intent, in_work_mode)

        # Determine if fitness/nutrition context should be injected
        inject_fitness = self._should_inject_fitness(intent, message_lower)

        # Build reason string for logging
        reasons = ["soul"]  # Always included
        if inject_memory:
            reasons.append("memory")
        if inject_cognitive:
            reasons.append("cognitive")
        if inject_insight:
            reasons.append("insight")
        if inject_daily_brief:
            reasons.append("daily_brief")
        if inject_pkg:
            reasons.append("pkg")
        if inject_patterns:
            reasons.append("patterns")
        if inject_activity_context:
            reasons.append("activity")
        if inject_learning_recall:
            reasons.append("learning_recall")
        if inject_changes_brief:
            reasons.append("changes_brief")
        if inject_lessons:
            reasons.append("lessons")
        if inject_fitness:
            reasons.append("fitness")

        reason = f"Injecting: {', '.join(reasons)}"
        if in_work_mode:
            reason = f"[WORK MODE] {reason}"

        decision = ContextDecision(
            inject_memory=inject_memory,
            inject_cognitive=inject_cognitive,
            inject_insight=inject_insight,
            inject_daily_brief=inject_daily_brief,
            inject_soul=inject_soul,
            inject_pkg=inject_pkg,
            inject_patterns=inject_patterns,
            inject_activity_context=inject_activity_context,
            inject_learning_recall=inject_learning_recall,
            inject_changes_brief=inject_changes_brief,
            inject_lessons=inject_lessons,
            inject_fitness=inject_fitness,
            reason=reason
        )

        logger.info(
            f"[ContextRouter] Intent={intent}, turns={turn_count}, "
            f"has_q={has_question}, work_mode={in_work_mode} -> {reason}"
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

    def _should_inject_daily_brief(self, message_lower: str, in_work_mode: bool) -> bool:
        """
        Daily brief is injected when:
        1. Schedule-related keywords detected (always)
        2. Not in work mode AND message is substantive (>15 chars)
        Skip for ultra-short messages (greetings, single words) to save latency.
        """
        # Schedule keywords always trigger regardless of mode
        if any(kw in message_lower for kw in self.DAILY_BRIEF_KEYWORDS):
            return True

        if in_work_mode:
            return False

        # Skip for greetings / ultra-short messages — not useful context
        if len(message_lower.strip()) < 15:
            return False

        return True

    def _should_inject_pkg(self, intent: str, message_lower: str,
                           turn_count: int, in_work_mode: bool) -> bool:
        """
        PKG is always-on — personal knowledge improves every response.
        Only skip for ultra-short messages (greetings) to save latency.
        The provider itself handles graceful fallback if Neo4j is unavailable.
        """
        # Skip for greetings / ultra-short messages
        if len(message_lower.strip()) < 10:
            return False

        return True

    def _should_inject_learning_recall(self, intent: str, message_lower: str,
                                      in_work_mode: bool) -> bool:
        """
        Learning recall testing should be injected when:
        1. Not in work mode
        2. Intent is conversational/knowledge/general
        3. Message contains learning-adjacent question keywords
        4. Message is long enough to be a real question (not a quick command)
        """
        if in_work_mode:
            return False
        if intent not in self.LEARNING_RECALL_INTENTS:
            return False
        if len(message_lower) < 20:
            return False
        return any(kw in message_lower for kw in self.LEARNING_RECALL_KEYWORDS)

    def _should_inject_patterns(self, intent: str, message_lower: str,
                                turn_count: int, in_work_mode: bool) -> bool:
        """
        Pattern context is injected when:
        1. Pattern-related keywords detected
        2. First turn of day (morning greeting), if message is substantive
        3. Conversational/fitness/general intents (not work mode)
        Skip for ultra-short messages (greetings) to save latency.
        """
        # Skip for greetings / ultra-short messages
        if len(message_lower.strip()) < 10:
            return False

        if in_work_mode:
            return any(kw in message_lower for kw in self.PATTERN_KEYWORDS)

        # Pattern keywords always trigger
        if any(kw in message_lower for kw in self.PATTERN_KEYWORDS):
            return True

        # First turn (likely greeting / start of session)
        if turn_count <= 1 and intent in self.PATTERN_INTENTS:
            return True

        return False

    def _should_inject_changes_brief(self, message_lower: str, turn_count: int) -> bool:
        """
        Changes brief is injected when:
        1. First message of a conversation (turn_count <= 1) — re-entry context
        2. User explicitly asks "catch me up" / "what did I miss"
        """
        # First message — likely re-entry
        if turn_count <= 1:
            return True

        # Explicit request for updates
        if any(kw in message_lower for kw in self.CHANGES_BRIEF_KEYWORDS):
            return True

        return False

    def _should_inject_lessons(self, intent: str, in_work_mode: bool) -> bool:
        """
        Lesson injection is needed when:
        1. Not in work mode
        2. Intent is conversational/general/knowledge (where mistakes matter most)
        """
        if in_work_mode:
            return False
        return intent in self.LESSON_INTENTS

    def _should_inject_fitness(self, intent: str, message_lower: str) -> bool:
        """
        Fitness context is needed when the user is talking about food, meals,
        nutrition, workouts, or anything where knowing their plan/targets helps.
        """
        if intent in self.FITNESS_INTENTS:
            return True
        return any(kw in message_lower for kw in self.FITNESS_KEYWORDS)


# Singleton instance
_context_router = None


def get_context_router() -> ContextRouter:
    """Get or create the context router singleton"""
    global _context_router
    if _context_router is None:
        _context_router = ContextRouter()
    return _context_router
