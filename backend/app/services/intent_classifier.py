"""
Intent Classification System for Semantic Retrieval Routing

Uses pre-computed intent prototypes and cosine similarity to classify
user messages without requiring additional LLM calls.
"""

import asyncio
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class IntentScore:
    """Score for a specific intent category"""
    intent: str
    score: float
    matched_prototype: str


@dataclass
class ClassificationResult:
    """Result of intent classification"""
    primary_intent: str
    confidence: float
    all_scores: Dict[str, float]
    recommended_scopes: List[str]
    should_retrieve: bool


# Intent prototype definitions
# Each intent has example phrases that represent that category
INTENT_PROTOTYPES = {
    "fitness_history": [
        "I'm sore from my workout",
        "How is my recovery going",
        "My muscles are tired",
        "Haven't recovered yet",
        "Feeling fatigued after training",
        "My legs are killing me",
        "Still feeling yesterday's workout",
        "Need to check my fitness progress",
        "How many workouts this week",
        "What was my last workout"
    ],
    "emotional_check": [
        "I'm feeling down today",
        "Stressed about work",
        "My mood has been off lately",
        "Feeling anxious about something",
        "I've been happier recently",
        "Emotionally drained",
        "Overwhelmed with everything"
    ],
    "explicit_recall": [
        "What did we talk about yesterday",
        "Do you remember when I mentioned",
        "Last time I told you about",
        "You should remember that",
        "Find what I said about",
        "Search for when I discussed",
        "Recall our conversation about"
    ],
    "planning_future": [
        "I need to schedule something",
        "Tomorrow I should do",
        "Planning to work out next week",
        "Set a reminder for me",
        "Add this to my calendar",
        "I want to plan my week"
    ],
    "note_search": [
        "Find my note about",
        "What did I write about",
        "Search my notes for",
        "I documented something about",
        "Look in my knowledge garden"
    ],
    "document_search": [
        "Find that PDF I uploaded",
        "What does the document say",
        "Search my uploaded files",
        "Look in my documents for"
    ],
    "chitchat": [
        "Hello there",
        "How are you",
        "Thanks for that",
        "Okay sounds good",
        "Got it",
        "Sure thing",
        "Goodbye",
        "See you later"
    ],
    "health_status": [
        "How am I sleeping",
        "My energy levels lately",
        "Check my HRV trends",
        "How's my heart rate",
        "My weight trends",
        "Sleep quality this week"
    ]
}

# Mapping from intents to retrieval scopes
INTENT_TO_SCOPES = {
    "fitness_history": ["episodes", "fitness"],
    "emotional_check": ["episodes"],
    "explicit_recall": ["episodes", "notes"],
    "planning_future": ["calendar", "reminders"],
    "note_search": ["notes"],
    "document_search": ["documents"],
    "chitchat": [],  # No retrieval needed
    "health_status": ["episodes", "fitness", "health"]
}


class SemanticIntentClassifier:
    """
    Classifies user intents using semantic similarity to prototype embeddings.

    This approach is fast (one embedding + cosine similarities) and doesn't
    require additional LLM calls for routing decisions.
    """

    def __init__(self):
        self.prototype_embeddings: Dict[str, List[Tuple[str, List[float]]]] = {}
        self.initialized = False
        self._initialization_lock = asyncio.Lock()

    async def initialize(self):
        """Pre-compute embeddings for all intent prototypes"""
        if self.initialized:
            return

        async with self._initialization_lock:
            if self.initialized:  # Double-check after acquiring lock
                return

            logger.info("[IntentClassifier] Initializing prototype embeddings...")

            from app.services.embeddings import get_embedding

            for intent, prototypes in INTENT_PROTOTYPES.items():
                self.prototype_embeddings[intent] = []

                for prototype in prototypes:
                    try:
                        embedding = await get_embedding(prototype)
                        self.prototype_embeddings[intent].append((prototype, embedding))
                    except Exception as e:
                        logger.error(f"[IntentClassifier] Failed to embed prototype '{prototype}': {e}")

                logger.info(f"[IntentClassifier] Embedded {len(self.prototype_embeddings[intent])} prototypes for '{intent}'")

            self.initialized = True
            logger.info("[IntentClassifier] Initialization complete")

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        v1 = np.array(vec1)
        v2 = np.array(vec2)

        dot_product = np.dot(v1, v2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))

    async def classify(self, message: str) -> ClassificationResult:
        """
        Classify user message intent using semantic similarity.

        Returns:
            ClassificationResult with primary intent, confidence, and recommended scopes
        """
        if not self.initialized:
            await self.initialize()

        from app.services.embeddings import get_embedding

        # Get embedding for user message
        message_embedding = await get_embedding(message)

        # Calculate similarity to each intent's prototypes
        intent_scores: Dict[str, IntentScore] = {}

        for intent, prototypes in self.prototype_embeddings.items():
            max_similarity = 0.0
            best_prototype = ""

            # Find max similarity across all prototypes for this intent
            for prototype_text, prototype_embedding in prototypes:
                similarity = self._cosine_similarity(message_embedding, prototype_embedding)
                if similarity > max_similarity:
                    max_similarity = similarity
                    best_prototype = prototype_text

            intent_scores[intent] = IntentScore(
                intent=intent,
                score=max_similarity,
                matched_prototype=best_prototype
            )

        # Find primary intent (highest score)
        sorted_intents = sorted(intent_scores.values(), key=lambda x: x.score, reverse=True)
        primary = sorted_intents[0]

        # Determine recommended scopes based on confidence
        recommended_scopes = []
        should_retrieve = True

        if primary.intent == "chitchat" and primary.score > 0.7:
            # High confidence chitchat - skip retrieval
            should_retrieve = False
        elif primary.score > 0.6:
            # High confidence - use narrow scope for primary intent
            recommended_scopes = INTENT_TO_SCOPES.get(primary.intent, ["episodes"])
        elif primary.score > 0.4:
            # Medium confidence - broader retrieval
            recommended_scopes = INTENT_TO_SCOPES.get(primary.intent, ["episodes"])
            # Add episodes as fallback if not already present
            if "episodes" not in recommended_scopes:
                recommended_scopes.append("episodes")
        else:
            # Low confidence - full retrieval as fallback
            recommended_scopes = ["episodes", "notes"]

        # Build result
        result = ClassificationResult(
            primary_intent=primary.intent,
            confidence=primary.score,
            all_scores={intent: score.score for intent, score in intent_scores.items()},
            recommended_scopes=recommended_scopes,
            should_retrieve=should_retrieve
        )

        logger.info(
            f"[IntentClassifier] Classified '{message[:50]}...' as {primary.intent} "
            f"(conf={primary.score:.3f}, scopes={recommended_scopes})"
        )

        return result

    async def get_query_embedding(self, query: str) -> List[float]:
        """Get embedding for a query (useful for semantic search)"""
        from app.services.embeddings import get_embedding
        return await get_embedding(query)


# Fallback keyword-based classification for when embeddings aren't available
class KeywordIntentClassifier:
    """
    Fast keyword-based intent classification as fallback.
    Less accurate but very fast.
    """

    KEYWORD_PATTERNS = {
        "fitness_history": [
            "sore", "soreness", "recover", "recovery", "workout", "exercise",
            "tired", "fatigue", "fatigued", "muscle", "training", "gym",
            "fitness", "hrv", "heart rate", "sleep"
        ],
        "emotional_check": [
            "feeling", "mood", "anxious", "stressed", "happy", "sad",
            "overwhelmed", "down", "depressed", "emotional"
        ],
        "explicit_recall": [
            "remember", "recall", "what did we", "when did", "last time",
            "told you", "mentioned", "discussed", "talked about"
        ],
        "planning_future": [
            "schedule", "reminder", "tomorrow", "next week", "plan",
            "calendar", "appointment", "meeting"
        ],
        "note_search": [
            "note", "notes", "wrote", "documented", "knowledge garden"
        ],
        "document_search": [
            "document", "pdf", "file", "uploaded"
        ],
        "chitchat": [
            "hello", "hi ", "hey ", "thanks", "thank you", "goodbye",
            "bye", "okay", "sure", "got it", "sounds good"
        ]
    }

    def classify(self, message: str) -> ClassificationResult:
        """Classify using keyword matching"""
        message_lower = message.lower()

        # Count keyword matches for each intent
        scores = {}
        for intent, keywords in self.KEYWORD_PATTERNS.items():
            matches = sum(1 for kw in keywords if kw in message_lower)
            scores[intent] = matches / len(keywords)

        # Find primary intent
        primary_intent = max(scores, key=scores.get)
        confidence = scores[primary_intent]

        # Determine scopes
        if primary_intent == "chitchat" and confidence > 0.3:
            should_retrieve = False
            recommended_scopes = []
        elif confidence > 0.2:
            should_retrieve = True
            recommended_scopes = INTENT_TO_SCOPES.get(primary_intent, ["episodes"])
        else:
            # Default to episodes search
            should_retrieve = True
            recommended_scopes = ["episodes"]

        return ClassificationResult(
            primary_intent=primary_intent,
            confidence=confidence,
            all_scores=scores,
            recommended_scopes=recommended_scopes,
            should_retrieve=should_retrieve
        )


# Singleton instances
_semantic_classifier: Optional[SemanticIntentClassifier] = None
_keyword_classifier = KeywordIntentClassifier()


async def get_semantic_classifier() -> SemanticIntentClassifier:
    """Get or create the semantic intent classifier singleton"""
    global _semantic_classifier
    if _semantic_classifier is None:
        _semantic_classifier = SemanticIntentClassifier()
    if not _semantic_classifier.initialized:
        await _semantic_classifier.initialize()
    return _semantic_classifier


def get_keyword_classifier() -> KeywordIntentClassifier:
    """Get the keyword intent classifier (fast fallback)"""
    return _keyword_classifier
