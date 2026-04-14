"""
Implicit Feedback Detector for Sara Learning System.

Detects positive/negative signals from user messages without explicit ratings.
Used to trigger lesson extraction.
"""

import re
import logging
from typing import Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class SignalType(str, Enum):
    """Type of implicit feedback signal."""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class SignalStrength(str, Enum):
    """Strength of the feedback signal."""
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


@dataclass
class ImplicitFeedback:
    """Result of implicit feedback analysis."""
    signal_type: SignalType
    strength: SignalStrength
    trigger_phrase: str
    context: str
    confidence: float  # 0-1 confidence in detection

    def is_actionable(self) -> bool:
        """Returns True if this feedback should trigger an action."""
        return (
            self.signal_type != SignalType.NEUTRAL and
            self.confidence >= 0.5 and
            self.strength in (SignalStrength.STRONG, SignalStrength.MODERATE)
        )


# Strong negative indicators - clear signs Sara made a mistake
STRONG_NEGATIVE_PATTERNS = [
    (r"\b(wrong|incorrect|false|untrue)\b", "explicit_error"),
    (r"\b(not what i (asked|wanted|meant))\b", "misunderstanding"),
    (r"\b(you misunderstood|you got it wrong|that'?s not right)\b", "explicit_correction"),
    (r"\b(completely wrong|totally wrong|way off)\b", "strong_error"),
    (r"\b(no,?\s+that'?s not)\b", "direct_denial"),
    (r"\b(you'?re wrong|you are wrong)\b", "direct_correction"),
    (r"\b(didn'?t ask for that|wasn'?t asking for)\b", "off_topic"),
]

# Moderate negative indicators - subtle corrections or clarifications
MODERATE_NEGATIVE_PATTERNS = [
    (r"\b(actually),?\s", "soft_correction"),
    (r"\b(not quite|not exactly|not really)\b", "partial_disagreement"),
    (r"\b(let me clarify|to clarify|i should clarify)\b", "clarification_needed"),
    (r"\b(i meant|what i meant was)\b", "meaning_correction"),
    (r"\b(no,?\s+(i|it'?s|the))\b", "gentle_denial"),
    (r"\b(that'?s not what i)\b", "expectation_mismatch"),
    (r"\b(but i said|i already said|i told you)\b", "repetition_frustration"),
]

# Strong positive indicators - clear signs of success
STRONG_POSITIVE_PATTERNS = [
    (r"\b(perfect|exactly|precisely)\b", "exact_match"),
    (r"\b(great job|well done|excellent|awesome)\b", "explicit_praise"),
    (r"\b(thank(s| you)!+|thanks!+)\b", "enthusiastic_thanks"),
    (r"\b(that'?s (exactly )?what i (needed|wanted))\b", "need_fulfilled"),
    (r"\b(you'?re (the )?best)\b", "direct_praise"),
    (r"\b(love it|nailed it)\b", "strong_approval"),
]

# Moderate positive indicators - general satisfaction
MODERATE_POSITIVE_PATTERNS = [
    (r"\b(thanks|thank you)\b", "standard_thanks"),
    (r"\b(good|great|nice)\b(?!\s+job)", "positive_adjective"),
    (r"\b(helpful|useful)\b", "utility_acknowledgment"),
    (r"\b(makes sense|got it|understood)\b", "comprehension_confirmed"),
    (r"\b(yes,?\s+that'?s (it|right))\b", "confirmation"),
]


class ImplicitFeedbackDetector:
    """
    Analyzes user messages for implicit positive/negative feedback signals.

    This detector looks for linguistic patterns that indicate whether the user
    is satisfied or dissatisfied with Sara's previous response, without
    requiring explicit feedback mechanisms.
    """

    def __init__(self):
        # Compile patterns for efficiency
        self._strong_negative = [(re.compile(p, re.IGNORECASE), label) for p, label in STRONG_NEGATIVE_PATTERNS]
        self._moderate_negative = [(re.compile(p, re.IGNORECASE), label) for p, label in MODERATE_NEGATIVE_PATTERNS]
        self._strong_positive = [(re.compile(p, re.IGNORECASE), label) for p, label in STRONG_POSITIVE_PATTERNS]
        self._moderate_positive = [(re.compile(p, re.IGNORECASE), label) for p, label in MODERATE_POSITIVE_PATTERNS]

    def analyze(
        self,
        message: str,
        previous_response: Optional[str] = None,
        conversation_context: Optional[List[dict]] = None
    ) -> ImplicitFeedback:
        """
        Analyze a user message for implicit feedback signals.

        Args:
            message: The current user message to analyze
            previous_response: Sara's previous response (for context)
            conversation_context: Recent conversation history

        Returns:
            ImplicitFeedback with detected signal type, strength, and details
        """
        message_lower = message.lower().strip()

        # Check for strong negative signals first
        match, label = self._find_pattern_match(message, self._strong_negative)
        if match:
            return ImplicitFeedback(
                signal_type=SignalType.NEGATIVE,
                strength=SignalStrength.STRONG,
                trigger_phrase=match.group(),
                context=self._extract_context(message, match),
                confidence=0.9
            )

        # Check for moderate negative signals
        match, label = self._find_pattern_match(message, self._moderate_negative)
        if match:
            # "Actually" at start of message is stronger than in middle
            confidence = 0.75 if message_lower.startswith("actually") else 0.6
            return ImplicitFeedback(
                signal_type=SignalType.NEGATIVE,
                strength=SignalStrength.MODERATE,
                trigger_phrase=match.group(),
                context=self._extract_context(message, match),
                confidence=confidence
            )

        # Check for strong positive signals
        match, label = self._find_pattern_match(message, self._strong_positive)
        if match:
            return ImplicitFeedback(
                signal_type=SignalType.POSITIVE,
                strength=SignalStrength.STRONG,
                trigger_phrase=match.group(),
                context=self._extract_context(message, match),
                confidence=0.85
            )

        # Check for moderate positive signals
        match, label = self._find_pattern_match(message, self._moderate_positive)
        if match:
            # Simple "thanks" might be politeness, lower confidence
            confidence = 0.5 if label == "standard_thanks" else 0.65
            return ImplicitFeedback(
                signal_type=SignalType.POSITIVE,
                strength=SignalStrength.MODERATE,
                trigger_phrase=match.group(),
                context=self._extract_context(message, match),
                confidence=confidence
            )

        # No clear signal detected
        return ImplicitFeedback(
            signal_type=SignalType.NEUTRAL,
            strength=SignalStrength.WEAK,
            trigger_phrase="",
            context=message[:100],
            confidence=0.3
        )

    def _find_pattern_match(
        self,
        message: str,
        patterns: List[Tuple[re.Pattern, str]]
    ) -> Tuple[Optional[re.Match], Optional[str]]:
        """Find the first matching pattern in the message."""
        for pattern, label in patterns:
            match = pattern.search(message)
            if match:
                return match, label
        return None, None

    def _extract_context(self, message: str, match: re.Match, window: int = 50) -> str:
        """Extract surrounding context around the matched phrase."""
        start = max(0, match.start() - window)
        end = min(len(message), match.end() + window)
        context = message[start:end]
        if start > 0:
            context = "..." + context
        if end < len(message):
            context = context + "..."
        return context


# Singleton instance
implicit_feedback_detector = ImplicitFeedbackDetector()


async def analyze_message_for_feedback(
    message: str,
    previous_response: Optional[str] = None,
    conversation_context: Optional[List[dict]] = None
) -> ImplicitFeedback:
    """
    Convenience function to analyze a message for implicit feedback.

    Args:
        message: The user message to analyze
        previous_response: Sara's previous response
        conversation_context: Recent conversation history

    Returns:
        ImplicitFeedback result
    """
    return implicit_feedback_detector.analyze(
        message=message,
        previous_response=previous_response,
        conversation_context=conversation_context
    )
