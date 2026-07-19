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

from datetime import datetime, timedelta, timezone
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

    # Base tools always available (essential for most interactions).
    # 'fleet' is here because David refers to his machines by name in short,
    # keyword-less messages ("check nyx", "how's nyx") that classify as
    # CONVERSATIONAL — without it in the base set, Sara wouldn't see fleet_status/
    # fleet_diag and would wrongly claim she can't check his servers.
    BASE_TOOLS = ['memory', 'notes', 'time', 'agents', 'fleet']

    # Extended default tools for general/unclear intent
    DEFAULT_TOOLS = ['memory', 'notes', 'time', 'web', 'fitness', 'learning', 'home', 'fleet']

    # Intent patterns - more specific patterns checked first
    INTENT_PATTERNS = {
        # RECIPES must precede FITNESS/NOTES: a recipe request often contains
        # fitness keywords ('protein', 'meal') or 'save this' (NOTES), which would
        # otherwise steal the intent and hide recipes_create from the model.
        'RECIPES': [
            'recipe', 'recipes',
        ],
        # LOCATION must precede NOTES ('save this' collides) and TIME
        # ('remind'/'reminder' collides with "remind me ... when I get home") —
        # SARA_UNLEASHED Phase U.8: these tools existed and data was flowing
        # (location_event, known_place) but were unreachable from chat because
        # no intent ever routed to them.
        'LOCATION': [
            'save this location', 'save my location', 'save this place',
            'save my current location', 'remember this place', 'remember where',
            'known place', 'known places', 'saved places', 'saved place', 'my places',
            'forget this place', 'forget that place', 'delete this place',
            'add this as a known place', 'add this as a place',
            'when i get home', 'when i leave', 'when i arrive', 'when i get to',
            'leave here', 'get home', 'location reminder', 'geofence', 'where am i',
        ],
        # PEOPLE must precede MEMORY ('have i'/'have we' collides with "who
        # have i been talking to") — SARA_UNLEASHED U.8 registry sweep found
        # list_people (Phase D's people-graph tool, real data, zero routing).
        'PEOPLE': [
            'who am i overdue with', 'overdue with', "who's new this week",
            'who is new this week', "haven't talked to", 'have not talked to',
            'catch up with', 'who have i been talking to', "who've i been talking to",
            'people i talk to', 'reconnect with', 'who am i overdue to',
        ],
        # GOALS must precede PERSONAL_KNOWLEDGE ('my goals' is already one of
        # its keywords) — SARA_UNLEASHED U.8 found manage_goal (Phase E's
        # persistent-goal tool, same table the ACS daemon reads) with zero
        # routing. A tracked goal is a better answer than a generic fact.
        'GOALS': [
            'a goal', 'track progress on', 'mark that goal', 'mark this goal',
            'goal done', 'complete that goal', 'complete this goal', 'my goals',
            'persistent goal', 'goal progress', 'stalled goal',
        ],
        # FLEET — health + read-only diagnostics for David's machines (the fleet
        # agents). Host names can't be enumerated here, so this catches the
        # generic phrasings; short host-named messages ("check nyx") are covered
        # by 'fleet' being in BASE_TOOLS.
        'FLEET': [
            'the fleet', 'my fleet', 'fleet status', 'fleet health', "how's the fleet",
            'my servers', 'my machines', 'my boxes', 'server health', 'server status',
            'are my servers', 'is my server', 'anything wrong with my',
            'disk space on', 'disk usage on', 'why is the server', 'why is the box',
            'check the server', 'check my server', 'check the box', 'health of my',
        ],
        'FITNESS': [
            'log', 'food', 'calories', 'workout', 'exercise', 'meal', 'weight',
            'protein', 'carbs', 'fat', 'macros', 'ate', 'eating', 'breakfast',
            'lunch', 'dinner', 'snack', 'gym', 'lift', 'run', 'cardio', 'recovery',
            'sleep', 'steps', 'burned', 'nutrition', 'fasting', 'diet',
            'program', 'training program', 'phase', 'training phase', 'template',
            'workout template', 'mesocycle', 'block', 'hypertrophy', 'strength program',
            'deload', 'periodization', 'training block'
        ],
        # Interactive surfaces — explicit construction language only (B3 layer 2).
        'SURFACES': [
            'checklist', 'check list',
            'cook mode', 'cook-mode', 'cooking mode', 'recipe mode',
            'enter cook', 'enter cooking', 'start cook', 'start cooking',
            'cook along', 'cooking along', 'follow along', 'cook-along',
            'walk me through the recipe', 'step me through', 'guide me through the recipe',
            'interactive checklist', 'live checklist', 'shopping list surface',
            'step by step surface', 'step-by-step', 'pickup window', 'pick-up window',
            'make a form', 'quick form', 'build a surface', 'interactive surface',
            'tick off', 'check off as i',
            # Workspace-job phrasing (workspace_job_run lives in this category)
            'pull the attachments', 'pull attachments', 'grab the attachments',
            'grab those files', 'collect the attachments', 'collect the files',
            'gather the attachments', 'gather the files', 'attachments to a folder',
            'pull those files', 'pull the files',
        ],
        # Before NOTES: NOTES owns the bare word 'document', so explicit
        # file-generation phrasing must be matched first (SURFACES_DESIGN §A).
        'AUTHORING': [
            'word doc', 'word document', 'docx', '.docx', 'pdf', '.pdf',
            'as a pdf', 'as a word', 'as a doc', 'to pdf', 'into a pdf',
            'export as', 'export this', 'export it', 'download as',
            'generate a document', 'generate a pdf', 'generate a report',
            'make a pdf', 'make me a doc', 'make me a word', 'make a word',
            'create a pdf', 'create a document', 'write it up as', 'write that up as',
            'turn it into a doc', 'turn this into a doc', 'formatted document',
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
        # Before MEMORY/HOME/CONVERSATIONAL: their broad keywords ('did i',
        # 'is the', 'hey') would otherwise swallow "hey what's the notification?"
        # / badge questions. Device-targeted phrasing ("send a notification to
        # my pc") still wins via the priority check above.
        'NOTIFICATIONS': [
            'the notification', 'that notification', 'notifications',
            'what notification', 'which notification', 'badge',
            'did you send me', 'what did you send', 'did i miss',
            'miss anything', 'missed anything', 'did you notify',
            'why did you ping', 'pinged me', 'what was that alert',
        ],
        'MEMORY': [
            'remember', 'recall', 'earlier', 'yesterday', 'last time',
            'before', 'previously', 'did i', 'did we', 'have i', 'have we',
            'what did', 'when did', 'told you', 'mentioned'
        ],
        'HOME': [
            'lights', 'light', 'lamp', 'lamps', 'thermostat', 'home assistant',
            'turn on', 'turn off', 'shut off', 'switch on', 'switch off',
            'temperature', 'fan', 'switch', 'door', 'lock', 'unlock', 'garage',
            'automation', 'sensor', 'smart home', 'home status',
            'dim', 'bright', 'brighten', 'darken',
            'air conditioning', 'ac', 'heat', 'heating', 'cooling',
            'blinds', 'shades', 'curtains', 'cover',
            'scene', 'goodnight', 'movie mode',
            'porch', 'bedroom light', 'kitchen light', 'living room light',
            'is the', 'are the lights', 'house', 'my home',
            'all lights', 'lights off', 'lights on',
            'what lights', 'which lights', 'home overview',
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
            'connected devices', 'what devices', 'list devices', 'show devices',
            'what am i looking at', "what's on my screen", 'whats on my screen',
            "what's this on my screen", 'on my screen', 'my screen',
            'look at my screen', 'see my screen'
        ],
        'WORKSPACE': [
            'map', 'maps', 'mindmap', 'mind map', 'flowchart', 'flow chart',
            'diagram', 'graph', 'node', 'nodes', 'canvas', 'workspace',
            'explode', 'expand the', 'spread out', 'resize', 'layout',
            'show the map', 'hide the map', 'create a map', 'add node',
            'connect nodes', 'visualization', 'visualize'
        ],
        'EMAIL': [
            'email', 'emails', 'mail', 'email inbox', 'message', 'unread',
            'sender', 'from', 'attachment', 'attachments', 'riskninja',
            'mailbox', 'outlook', 'sent', 'received'
        ],
        'AUTOMATION': [
            'automation', 'automate', 'every hour', 'every day', 'every minute',
            'schedule this', 'recurring', 'automatically', 'auto', 'trigger',
            'when the', 'if the', 'alert me', 'notify me when',
            'confirm', 'activate', 'activate it', 'yes activate', 'do it',
            'start it', 'enable it', 'turn it on'
        ],
        'SOUL': [
            'soul', 'your soul', 'identity', 'your identity', 'who you are',
            'operating principles', 'principles', 'boundaries', 'your boundaries',
            'growth areas', 'how you operate', 'your rules', 'change yourself',
            'propose a change', 'soul change', 'self-modification', 'your personality',
            'personality', 'what are you', 'define yourself', 'evolution'
        ],
        'HEARTBEAT': [
            'heartbeat', 'monitoring', 'what are you watching', 'what are you tracking',
            'add a monitor', 'remind me about', 'keep an eye on', 'watch for',
            'check on', 'alert if', 'heartbeat items', 'your checklist',
            'what are you checking', 'periodic checks', 'daily checks'
        ],
        'HEALTH': [
            'health', 'hrv', 'heart rate', 'resting heart rate', 'blood pressure',
            'steps today', 'calories burned', 'health metrics', 'health data',
            'health trends', 'sleep quality', 'sleep score', 'body temperature',
            'oxygen', 'spo2', 'vo2', 'respiratory'
        ],
        'INBOX': [
            'saved articles', 'reading list', 'what i saved', 'saved links',
            'shared content', 'content inbox', 'stuff i saved', 'articles i saved'
        ],
        'PATTERNS': [
            'patterns', 'correlations', 'trends over time', 'notice any pattern',
            'relationship between', 'behavioral pattern', 'what have you noticed',
            'any trends', 'data correlations'
        ],
        'PERSONAL_KNOWLEDGE': [
            'what do you know about me', 'my preferences', 'about me',
            'you know that i', 'my routine', 'my goals', 'facts about me',
            'what have you learned about me', 'my habits'
        ],
        'STANDING_ORDERS': [
            'standing order', 'pre-authorize', 'always do this', 'from now on always',
            'automatic action', 'pre-approved', 'blanket permission'
        ],
        'BEHAVIOR_CONFIG': [
            'change how you', 'act differently', 'be more', 'be less',
            'stop being so', 'when coaching', 'your approach to',
            'modify your behavior', 'change your style'
        ],
        'KNOWLEDGE_GRAPH': [
            'connections between', 'related to', 'how is.*connected',
            'knowledge clusters', 'linked notes', 'note connections'
        ],
    }

    # Map intents to tool categories
    INTENT_TO_TOOL_CATEGORIES = {
        'CONVERSATIONAL': [],  # Will inherit from conversation context
        'RECIPES': ['recipes'],  # Structured recipe storage (recipes_create, not notes)
        'LOCATION': ['location', 'time'],  # 'time' too — location_reminder is reminder-adjacent
        'PEOPLE': ['people'],
        'GOALS': ['goals'],
        'FITNESS': ['fitness'],
        'FLEET': ['fleet'],
        'NOTES': ['notes'],
        'AUTHORING': ['authoring', 'canvas'],
        'SURFACES': ['surfaces'],
        'TIME': ['time'],
        'WEB': ['web'],
        'MEMORY': ['memory', 'knowledge_graph'],
        'HOME': ['home', 'standing_orders'],
        'CHESS': ['chess'],
        'LEARNING': ['learning', 'web'],
        'PROJECTS': ['projects'],
        'MORNING_BRIEF': ['daily', 'time'],
        'AGENTS': ['agents', 'web'],
        'NOTIFICATIONS': ['notifications'],  # Badge / "what's the notification?"
        'DEVICES': ['devices'],  # Cross-device commands
        'WORKSPACE': ['workspace', 'maps'],  # Canvas and map control
        'EMAIL': ['email'],  # Email search and reading
        'AUTOMATION': ['standing_orders', 'home'],  # Routed to standing orders
        'SOUL': ['soul', 'self_knowledge'],  # Sara's identity and self-modification
        'HEARTBEAT': ['heartbeat'],  # Sara's monitoring checklist
        'HEALTH': ['health', 'fitness'],
        'INBOX': ['inbox'],
        'PATTERNS': ['patterns', 'fitness'],
        'PERSONAL_KNOWLEDGE': ['personal_knowledge', 'memory'],
        'STANDING_ORDERS': ['standing_orders', 'home'],
        'BEHAVIOR_CONFIG': ['behavior', 'soul'],
        'KNOWLEDGE_GRAPH': ['knowledge_graph', 'notes'],
        'GENERAL': ['notes', 'memory', 'web', 'fitness', 'time', 'devices', 'email', 'home', 'location', 'people', 'goals'],  # Expanded fallback
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
            if datetime.now(timezone.utc) - ctx.last_update > timedelta(minutes=self.CONTEXT_TTL_MINUTES):
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
                    last_update=datetime.now(timezone.utc)
                )
                self._conversation_contexts[session_id] = ctx

            # Add current intent/tools, keeping only last N turns
            ctx.recent_intents = ([intent] + ctx.recent_intents)[:self.CONTEXT_TURNS]
            ctx.recent_tools = (tools + ctx.recent_tools)[:self.CONTEXT_TURNS * 3]
            ctx.last_update = datetime.now(timezone.utc)

            # Periodically clean up old sessions (every 100 updates)
            if len(self._conversation_contexts) > 100:
                self._cleanup_old_contexts()

    def _cleanup_old_contexts(self):
        """Remove expired conversation contexts"""
        now = datetime.now(timezone.utc)
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

        # Authoring is ADDITIVE, not a competing intent. "Create a PDF of my
        # nutrition" classifies as FITNESS (so the data tools load), but the
        # user also wants a file — so whenever explicit file-generation phrasing
        # is present, make document_generate available alongside the primary
        # intent's tools. Without this, single-intent routing hides the tool and
        # the model falls back to hand-building files via the VM agent.
        if self._has_authoring_signal(message) and 'authoring' not in tools:
            tools = tools + ['authoring']

        # Surfaces are likewise additive + progressive-disclosure: only merged in
        # on explicit construction language ("make a checklist of…"), never in the
        # default schema (B3 layer 2).
        if self._has_surface_signal(message) and 'surfaces' not in tools:
            tools = tools + ['surfaces']

        logger.info(f"[ToolIntent] '{message[:50]}...' -> {explicit_intent}, tools={tools}")
        return explicit_intent, tools

    def _has_authoring_signal(self, message: str) -> bool:
        """True if the message explicitly asks for a generated file (doc/pdf)."""
        message_lower = message.lower()
        return any(kw in message_lower for kw in self.INTENT_PATTERNS.get('AUTHORING', []))

    def _has_surface_signal(self, message: str) -> bool:
        """True if the message explicitly asks to build an interactive surface."""
        message_lower = message.lower()
        return any(kw in message_lower for kw in self.INTENT_PATTERNS.get('SURFACES', []))

    def classify_multi(self, message: str, max_intents: int = 3) -> List[Tuple[str, float]]:
        """
        Return top N intents with confidence scores for multi-intent messages.

        Scores all intents against the message and returns those above threshold.
        Used when messages contain conjunctions ("and", "also", "then", "plus").
        """
        import re
        message_lower = message.lower()
        scores: Dict[str, float] = {}

        for intent, keywords in self.INTENT_PATTERNS.items():
            match_count = 0
            for keyword in keywords:
                if len(keyword) <= 3:
                    if re.search(rf'\b{re.escape(keyword)}\b', message_lower):
                        match_count += 1
                else:
                    if keyword in message_lower:
                        match_count += 1
            if match_count > 0:
                scores[intent] = match_count / len(keywords)

        # Sort by score descending, take top N with score > 0
        sorted_intents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_intents[:max_intents]

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
