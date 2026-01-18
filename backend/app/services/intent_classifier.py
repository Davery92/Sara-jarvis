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


# ============================================================================
# Tool Intent Classifier - Maps messages to tool categories for token savings
# ============================================================================

from datetime import datetime, timedelta
from threading import Lock

@dataclass
class ConversationContext:
    """Stores context for a conversation session"""
    recent_intents: List[str]  # Last N intents classified
    recent_tools: List[str]    # Tool categories used in recent turns
    last_update: datetime


class ToolIntentClassifier:
    """
    Conversation-aware intent classifier that determines which tool categories to load.

    This reduces token usage by only sending relevant tools to the LLM while
    preserving context across conversation turns. Conversational follow-ups
    inherit tools from recent turns to maintain continuity.
    """

    # Base tools always available (essential for most interactions)
    BASE_TOOLS = ['memory', 'notes', 'time']

    # Extended default tools for general/unclear intent
    DEFAULT_TOOLS = ['memory', 'notes', 'time', 'web', 'fitness', 'learning']

    # Intent patterns - more specific patterns checked first
    INTENT_PATTERNS = {
        'FITNESS': [
            'log', 'food', 'calories', 'workout', 'exercise', 'meal', 'weight',
            'protein', 'carbs', 'fat', 'macros', 'ate', 'eating', 'breakfast',
            'lunch', 'dinner', 'snack', 'gym', 'lift', 'run', 'cardio', 'recovery',
            'sleep', 'steps', 'burned', 'nutrition', 'fasting', 'diet',
            'program', 'training program', 'phase', 'training phase', 'template',
            'workout template', 'mesocycle', 'block', 'hypertrophy', 'strength program',
            'deload', 'periodization', 'training block'
        ],
        'NOTES': [
            'note', 'notes', 'write down', 'save this', 'folder', 'jot down',
            'document', 'record this', 'keep track', 'knowledge garden'
        ],
        'TIME': [
            'remind', 'reminder', 'timer', 'calendar', 'schedule', 'alarm',
            'appointment', 'event', 'meeting', 'tomorrow', 'next week', 'when is'
        ],
        'AGENTS': [
            'hand off', 'handoff', 'have your agents', 'background task',
            'research this in the background', 'look into this for me',
            'agents research', 'agent task', 'delegate this', 'deep research',
            'thorough research', 'investigate this', 'dig into this',
            'your agent', 'the agent', 'start the agent', 'kick it off',
            'kick off', 'run the agent', 'agent build', 'agent research',
            'build a report', 'build me a report', 'full report',
            'your agents research', 'agents look into', 'agents investigate'
        ],
        'WEB': [
            'search', 'look up', 'find out', 'google', 'look for',
            'research', 'news about', 'latest on', 'who is', 'what is'
        ],
        'MEMORY': [
            'remember', 'recall', 'earlier', 'yesterday', 'last time',
            'before', 'previously', 'did i', 'did we', 'have i', 'have we',
            'what did', 'when did', 'told you', 'mentioned'
        ],
        'HOME': [
            'lights', 'thermostat', 'home assistant', 'turn on', 'turn off',
            'temperature', 'fan', 'switch', 'door', 'lock', 'garage',
            'automation', 'sensor', 'smart home'
        ],
        'CHESS': [
            'chess', 'checkmate', 'chess opening', 'chess endgame', 'chess tactics',
            'pawn', 'knight move', 'bishop move', 'rook move', 'castling',
            'chess game', 'play chess', 'chess match', 'chess position'
        ],
        'LEARNING': [
            'learn', 'study', 'topic', 'course', 'teach', 'explain how',
            'understand', 'lesson', 'tutorial', 'quiz'
        ],
        'PROJECTS': [
            'project', 'commit', 'pull request', 'branch', 'deploy',
            'repository', 'sprint', 'ticket', 'jira', 'github', 'task'
        ],
        'MORNING_BRIEF': [
            'morning brief', 'daily brief', 'briefing', "what's on today",
            "what do i have", 'agenda', 'my day'
        ],
        'CONVERSATIONAL': [
            'hello', 'hi', 'hey', 'thanks', 'thank you', 'bye', 'goodbye',
            'good morning', 'good night', 'good evening', 'good afternoon',
            "how are you", "what's up", 'howdy', 'yo', 'sup', 'ok', 'okay',
            'sounds good', 'got it', 'nice', 'great', 'awesome', 'cool'
        ],
        'DEVICES': [
            'device', 'devices', 'desktop', 'computer', 'pc', 'my pc',
            'my computer', 'my desktop', 'my laptop', 'macbook', 'windows',
            'send notification', 'send a notification', 'notify', 'notification',
            'open on my', 'open url on', 'open this on', 'on my computer',
            'on my desktop', 'on my pc', 'screenshot', 'take screenshot',
            'connected devices', 'what devices', 'list devices', 'show devices'
        ],
        'WORKSPACE': [
            'map', 'maps', 'mindmap', 'mind map', 'flowchart', 'flow chart',
            'diagram', 'graph', 'node', 'nodes', 'canvas', 'workspace',
            'explode', 'expand the', 'spread out', 'resize', 'layout',
            'show the map', 'hide the map', 'create a map', 'add node',
            'connect nodes', 'visualization', 'visualize'
        ],
    }

    # Map intents to tool categories
    INTENT_TO_TOOL_CATEGORIES = {
        'CONVERSATIONAL': [],  # Will inherit from conversation context
        'FITNESS': ['fitness'],
        'NOTES': ['notes'],
        'TIME': ['time'],
        'WEB': ['web'],
        'MEMORY': ['memory', 'knowledge_graph'],
        'HOME': ['home'],
        'CHESS': ['chess'],
        'LEARNING': ['learning', 'web'],
        'PROJECTS': ['projects'],
        'MORNING_BRIEF': ['morning_brief', 'time'],
        'AGENTS': ['agents', 'web'],
        'DEVICES': ['devices'],  # Cross-device commands
        'WORKSPACE': ['workspace', 'maps'],  # Canvas and map control
        'GENERAL': ['notes', 'memory', 'web', 'fitness', 'time', 'devices'],  # Expanded fallback with devices
    }

    # How many recent turns to preserve context from
    CONTEXT_TURNS = 3
    # How long to keep context before expiring (30 minutes)
    CONTEXT_TTL_MINUTES = 30

    def __init__(self):
        self._conversation_contexts: Dict[str, ConversationContext] = {}
        self._context_lock = Lock()

    def _get_context(self, session_id: str) -> Optional[ConversationContext]:
        """Get conversation context for a session, if it exists and isn't expired"""
        with self._context_lock:
            ctx = self._conversation_contexts.get(session_id)
            if ctx is None:
                return None

            # Check if context has expired
            if datetime.utcnow() - ctx.last_update > timedelta(minutes=self.CONTEXT_TTL_MINUTES):
                del self._conversation_contexts[session_id]
                return None

            return ctx

    def _update_context(self, session_id: str, intent: str, tools: List[str]):
        """Update conversation context with latest intent and tools"""
        with self._context_lock:
            ctx = self._conversation_contexts.get(session_id)

            if ctx is None:
                ctx = ConversationContext(
                    recent_intents=[],
                    recent_tools=[],
                    last_update=datetime.utcnow()
                )
                self._conversation_contexts[session_id] = ctx

            # Add current intent/tools, keeping only last N turns
            ctx.recent_intents = ([intent] + ctx.recent_intents)[:self.CONTEXT_TURNS]
            ctx.recent_tools = (tools + ctx.recent_tools)[:self.CONTEXT_TURNS * 3]
            ctx.last_update = datetime.utcnow()

            # Periodically clean up old sessions (every 100 updates)
            if len(self._conversation_contexts) > 100:
                self._cleanup_old_contexts()

    def _cleanup_old_contexts(self):
        """Remove expired conversation contexts"""
        now = datetime.utcnow()
        expired = [
            sid for sid, ctx in self._conversation_contexts.items()
            if now - ctx.last_update > timedelta(minutes=self.CONTEXT_TTL_MINUTES)
        ]
        for sid in expired:
            del self._conversation_contexts[sid]

    def classify(self, message: str) -> str:
        """
        Returns intent category based on keyword matching.

        Args:
            message: The user's message text

        Returns:
            Intent category string (e.g., 'FITNESS', 'NOTES', 'CONVERSATIONAL')
        """
        import re
        message_lower = message.lower()

        # Priority check: Device-targeting phrases should override other intents
        # These phrases indicate the user wants to do something ON a device
        device_targeting_phrases = [
            'on my pc', 'on my desktop', 'on my computer', 'on my laptop',
            'on my macbook', 'on my windows', 'to my pc', 'to my desktop',
            'to my computer', 'to my laptop', 'send notification', 'send a notification',
            'notify my', 'screenshot of my', 'open on my'
        ]
        for phrase in device_targeting_phrases:
            if phrase in message_lower:
                return 'DEVICES'

        # Check each intent pattern
        for intent, keywords in self.INTENT_PATTERNS.items():
            for keyword in keywords:
                # Use word boundary matching for short keywords
                if len(keyword) <= 3:
                    if re.search(rf'\b{re.escape(keyword)}\b', message_lower):
                        return intent
                else:
                    if keyword in message_lower:
                        return intent

        # Default logic for unmatched messages
        # Questions default to GENERAL (may need tools)
        if '?' in message:
            return 'GENERAL'

        # Short messages without keywords are likely conversational
        if len(message.split()) <= 5:
            return 'CONVERSATIONAL'

        # Longer statements default to GENERAL
        return 'GENERAL'

    def get_tool_categories(self, intent: str) -> List[str]:
        """
        Returns tool categories to load for given intent.

        Args:
            intent: The classified intent string

        Returns:
            List of tool category strings to load
        """
        return self.INTENT_TO_TOOL_CATEGORIES.get(intent, self.DEFAULT_TOOLS)

    def classify_with_context(self, message: str, session_id: Optional[str] = None) -> Tuple[str, List[str]]:
        """
        Classify message with conversation context awareness.

        Conversational messages will inherit tools from recent conversation turns,
        ensuring follow-up messages can still use tools that were relevant before.

        Args:
            message: The user's message text
            session_id: Optional session identifier for context tracking

        Returns:
            Tuple of (intent, list of tool categories)
        """
        explicit_intent = self.classify(message)
        explicit_tools = self.INTENT_TO_TOOL_CATEGORIES.get(explicit_intent, [])

        # If we have a session and the intent is conversational or general,
        # inherit tools from recent conversation
        if session_id:
            ctx = self._get_context(session_id)

            if explicit_intent == 'CONVERSATIONAL':
                # Conversational messages inherit tools from recent turns
                if ctx and ctx.recent_tools:
                    # Get unique tools from recent context
                    inherited_tools = list(dict.fromkeys(ctx.recent_tools))[:6]
                    tools = list(set(inherited_tools + self.BASE_TOOLS))
                    logger.info(f"[ToolIntent] CONVERSATIONAL inheriting tools from context: {tools}")
                else:
                    # No context - use base tools
                    tools = list(self.BASE_TOOLS)
            elif explicit_intent == 'GENERAL':
                # General intent gets expanded defaults plus any recent context
                tools = list(self.DEFAULT_TOOLS)
                if ctx and ctx.recent_tools:
                    # Merge with recent tools
                    tools = list(set(tools + ctx.recent_tools[:3]))
            else:
                # Specific intent - use its tools plus base tools
                tools = list(set(explicit_tools + self.BASE_TOOLS))

            # Update context with this turn
            self._update_context(session_id, explicit_intent, tools)
        else:
            # No session tracking - use simple logic
            if explicit_intent == 'CONVERSATIONAL':
                tools = list(self.BASE_TOOLS)
            elif explicit_intent == 'GENERAL':
                tools = list(self.DEFAULT_TOOLS)
            else:
                tools = list(set(explicit_tools + self.BASE_TOOLS))

        logger.info(f"[ToolIntent] '{message[:50]}...' -> {explicit_intent}, tools={tools}")
        return explicit_intent, tools

    def classify_with_categories(self, message: str) -> Tuple[str, List[str]]:
        """
        Convenience method that returns both intent and categories (without context).

        Args:
            message: The user's message text

        Returns:
            Tuple of (intent, list of tool categories)
        """
        intent = self.classify(message)
        categories = self.get_tool_categories(intent)
        # Always include base tools
        categories = list(set(categories + self.BASE_TOOLS))
        return intent, categories


# Singleton instance
_tool_intent_classifier: Optional[ToolIntentClassifier] = None


def get_tool_intent_classifier() -> ToolIntentClassifier:
    """Get or create the tool intent classifier singleton"""
    global _tool_intent_classifier
    if _tool_intent_classifier is None:
        _tool_intent_classifier = ToolIntentClassifier()
    return _tool_intent_classifier
