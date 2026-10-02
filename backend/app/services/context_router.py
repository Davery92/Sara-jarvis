"""
Context Router Service

Determines which contexts (memory, cognitive, insight) to inject based on
message intent and conversation state. This reduces token usage by only
injecting context when relevant.
"""

from typing import List, NamedTuple, Optional
import logging
import re

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
        # Added with the Fitness Coach (Step 23). "How's my weight
        # trending?" is among the most common questions Sara gets about
        # fitness and matched none of the above, so the block carrying the
        # goal, the targets and the limitations was absent for it.
        'weight', 'weigh', 'weighed', 'weighing', 'bodyweight',
        'lbs', 'kilos', 'kg', 'leaner', 'bulk', 'cut', 'cutting',
        'sore', 'soreness', 'reps', 'sets', 'pr', 'squat', 'bench',
        'deadlift', 'press', 'macro', 'hydration', 'steps',
    ]

    # Intents that benefit from fitness context
    FITNESS_INTENTS = ['FITNESS', 'HEALTH']

    # Word-boundary matching, compiled once.
    #
    # A bare `kw in message_lower` matched 'eat' inside "weather", so "What's
    # the weather like?" injected a nutrition block — budget spent on an
    # unrelated turn, and a macro remainder in front of the model on a
    # weather question. The same substring bug reaches "great", "repeat",
    # "feature", "defeat" and "theater". Multi-word phrases work unchanged:
    # \b applies at the ends of the phrase.
    _FITNESS_KEYWORD_RE = re.compile(
        r"\b(?:" + "|".join(re.escape(kw) for kw in FITNESS_KEYWORDS) + r")\b"
    )

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
        return bool(self._FITNESS_KEYWORD_RE.search(message_lower))


# ---------------------------------------------------------------------------
# Conversation mode (personal-conversation remediation plan, 2026-09-23)
# ---------------------------------------------------------------------------
# A turn-level classification separate from `ContextRouter.decide()`'s
# per-source injection flags. `decide()` answers "does this KIND of context
# help answer the question" from intent; a family emergency and a request
# for tonight's calendar can both classify CONVERSATIONAL/GENERAL and both
# score inject_daily_brief/inject_pkg True under those rules. Conversation
# mode answers a different question — is this turn asking for ambient
# awareness at all, or is David just talking to Sara — so callers can demote
# world-brief/health/work/proactive material on the turns where surfacing it
# was never wanted, independent of whether that material would otherwise be
# "relevant" by topic.

_GREETING_OR_SMALLTALK_RE = re.compile(
    r"^(hi+|hey+|hello+|yo+|sup|g'?day|"
    r"good\s*(morning|afternoon|evening|night)|morning|evening|"
    r"how'?s?\s*(it\s*going|you\s*doin'?g?|things)|what'?s\s*up|"
    r"thanks?( you)?|ty|np|no\s*problem|lol+|haha+|nice|cool|great|"
    r"ok(ay)?|k|sounds?\s*good|got\s*it|will\s*do|"
    r"(just\s+)?(relax(ing)?|chill(ing)?|hanging\s*out|vibing))"
    r"[\s!.,?]*$",
    re.IGNORECASE,
)

# Fatigue, distress, and vulnerable-disclosure language. Deliberately mixes
# mundane tiredness with severe disclosure — "I'm tired" and "I just got
# back from the ER with my dad" are the same MODE for ambient-context
# purposes (both ask Sara to meet David where he is, not run an analysis)
# even though their severity is wildly different. Mostly multi-word phrases
# rather than single common words — a bare "down" or "beat" matches inside
# too many unrelated sentences ("write this down", "the Jets beat the
# Patriots") to be a safe substring signal. Keyword matching is a known
# blunt instrument (the plan's own evidence table says so); this only ever
# governs what gets DEMOTED, never what gets refused or escalated, so a
# false positive costs a slightly quieter reply, not a wrong action.
_VULNERABLE_SIGNALS = [
    "i'm tired", "im tired", "so tired", "really tired", "pretty tired",
    "exhausted", "drained", "worn out", "burnt out", "burned out",
    "rough day", "rough night", "hard day", "long day", "long night",
    "bad day", "bad night", "stressed", "overwhelmed", "anxious", "anxiety",
    "so worried", "really worried", "scared", "feeling sad", "feeling down",
    "feeling low", "depressed", "lonely", "crying", "i cried", "sick",
    "not feeling well", "not feeling good", "in pain", "hurt",
    "can't sleep", "cant sleep", "not sleeping well",
    "emergency", "hospital", "ambulance", "urgent care", "emergency room",
    "surgery", "passed away", "passed on", "funeral", "car accident",
    "broke up", "breakup", "got divorced", "getting divorced", "got fired",
    "laid off",
    # 2026-09-24 fix: a family member's health-appointment disclosure
    # ("my dad's got some tests tomorrow") carried none of the above
    # signals at all, so `vulnerable` was False for it before this turn
    # even reached the question-override bug below — reproduced live in
    # Stage 5 adaptive testing (case 09 turn 2). Narrow, appointment-
    # specific additions rather than a broad "health" keyword.
    "tests tomorrow", "test tomorrow", "test results", "the results",
    "waiting on results", "appointment tomorrow", "scan tomorrow",
    "checkup tomorrow", "biopsy", "diagnosis",
]

# Standalone-word patterns that would be too dangerous as plain substrings
# (a naive "er" would match inside "her", "later", "premier" — see the note
# above). `\b` word-boundary anchoring keeps this to the actual standalone
# token: "took my dad to the ER" matches, "her plan" does not.
_VULNERABLE_WORD_RE = re.compile(r"\ber\b", re.IGNORECASE)

# Explicit requests — a verb aimed at Sara doing something. If one of these
# is present alongside a vulnerable signal, the request stays actionable
# (mode "mixed") rather than being swallowed by the personal/vulnerable
# demotion — the plan is explicit that "an explicit request for work in a
# vulnerable message remains actionable."
#
# 2026-09-24 fix: "schedule", "cancel", "reschedule", "draft" used to be
# bare entries here, checked with a plain Python `in` substring test. Two
# independent bugs from that: (1) no word boundary, so "schedule" matched
# inside "rescheduled"/"scheduler"/"unscheduled"; (2) no noun/figurative
# guard, so a plain NOUN use ("a meeting schedule", "my sleep schedule")
# or a figurative subject ("my brain scheduled a review meeting") both
# counted as real action evidence. Reproduced 3x during
# SARA_NATURAL_CONVERSATION_EVALUATION_PLAN_2026_09_23.md's testing
# (Stage 2/case11/turn7, Stage 3 C1+C2/case11/turn6) and confirmed live
# through the full assembly pipeline (4-of-4 leak across 2 independent
# trials before this fix; see the study's FINDINGS.md). Moved to
# `_ambiguous_action_verb` below, which requires an exact word-boundary
# match AND excludes noun-phrase and figurative-subject uses. The other
# entries here keep their existing phrase-level matching unchanged — they
# already carry enough surrounding context (e.g. "set a", "book ") not to
# match ordinary nouns like "a chess set".
_ACTION_SIGNALS = [
    "can you", "could you", "would you", "will you", "please ",
    "remind me", "set a", "start a",
    "log my", "log this", "add this", "add a", "create a", "note that",
    "send ", "email ", "reply to", "book ", "order ",
    "turn on", "turn off", "lock the", "unlock the", "check my", "check the",
    "look up", "find out", "what's my", "what is my",
    "what do i have", "what's on my", "what happened", "catch me up",
]

# Bare verbs that are ambiguous with noun usage ("a draft", "the schedule")
# or whose base form is easily confused with a figurative/reported use
# ("my brain scheduled..."). Matched as an exact word (so inflected forms
# like "scheduled"/"rescheduled" — almost always a reported PAST state,
# not a request — no longer match at all), then vetoed if the word
# immediately before it reads as a noun phrase or a figurative subject.
_AMBIGUOUS_ACTION_VERBS = ("schedule", "cancel", "reschedule", "draft")
_AMBIGUOUS_ACTION_VERB_RE = re.compile(
    r"\b(" + "|".join(_AMBIGUOUS_ACTION_VERBS) + r")\b", re.IGNORECASE
)

# A determiner/possessive, optionally followed by up to two more words
# (adjectives/nouns), immediately before the match means it's a noun
# phrase ("a chess set" — not one of these verbs, but the same shape;
# "my sleep schedule", "the first draft"), not a request. The 0-2 word
# allowance (vs. a stricter 0-word check) is needed for phrases like "a
# full review meeting" or "my sleep schedule".
_DETERMINER_BEFORE_VERB_RE = re.compile(
    r"\b(the|a|an|my|his|her|our|their|this|that|your|its)\b(?:\s+\w+){0,2}\s*$",
    re.IGNORECASE,
)

# "My brain/head/mind scheduled..." — a figurative, non-Sara-directed
# subject immediately before the verb. Narrow and explicit rather than a
# broad heuristic: the cost of missing an unusual figurative phrasing is
# a slightly-too-eager mode change, not a wrong action, so this stays a
# short, literal list rather than trying to detect "not a real request"
# in general.
_FIGURATIVE_SUBJECT_BEFORE_VERB_RE = re.compile(
    r"\b(my|his|her|their|our)\s+(brain|head|mind|thoughts?)\b(?:\s+\w+){0,2}\s*$",
    re.IGNORECASE,
)


def _has_ambiguous_action_verb(lowered: str) -> bool:
    for m in _AMBIGUOUS_ACTION_VERB_RE.finditer(lowered):
        before = lowered[: m.start()]
        if _DETERMINER_BEFORE_VERB_RE.search(before):
            continue
        if _FIGURATIVE_SUBJECT_BEFORE_VERB_RE.search(before):
            continue
        return True
    return False


# 2026-09-24 fix: a bare trailing question was enough, on its own, to
# promote a vulnerable disclosure straight past "personal_vulnerable" —
# "my dad's got some tests tomorrow... what are you up to today?" was
# reproduced (Stage 5 adaptive testing, case 09 turn 2) flipping the
# whole turn to full-context mode on the strength of an ordinary
# pleasantry tacked onto the end. The plan's own required counterexample
# ("so tired today, is my HRV low again?" — must stay "mixed", not
# demote) rules out simply "no question ever promotes a vulnerable turn"
# — the fix has to tell a genuine self-referential information question
# ("is MY hrv low", "do I have anything urgent") apart from a pleasantry
# addressed at Sara ("what are YOU up to", "how's your day").
_SELF_REFERENTIAL_QUESTION_RE = re.compile(
    r"\b(my|i've|i have|do i|am i|have i|did i|should i)\b", re.IGNORECASE
)

# 2026-09-24 correction: the first version of this fix scoped the check to
# the last SENTENCE (split on . ! ? \n only), which had two independent
# bugs. (1) A comma-joined disclosure+question ("my dad has tests
# tomorrow, how's your day?") is ONE sentence, so the disclosure's own
# "my" satisfied the check for an unrelated trailing pleasantry — the
# exact failure this fix exists to prevent, just moved one comma to the
# left. (2) A question followed by MORE text in the same message ("I'm
# tired. Is my HRV low again? Just wondering.") put the actual question
# in the MIDDLE sentence, not the last one, so "Just wondering" (no self-
# reference) was checked instead of "Is my HRV low again" (has one).
#
# Fixed by finding the actual clause that ENDS in "?" — splitting on the
# same clause-boundary set tool_mutation.py's own `_CLAUSE_BREAK_RE`
# already uses for the identical "a comma separates two unrelated things"
# problem (commas/semicolons/common conjunctions), in addition to sentence
# terminators — rather than assuming the question is always the last
# sentence-shaped chunk of the whole message.
_QUESTION_CLAUSE_TOKEN_RE = re.compile(
    r"([.!?\n,;]| but | however | although | yet | and )", re.IGNORECASE
)


def _question_clauses(text: str) -> List[str]:
    """Every clause (by the boundary set above) that itself ends in '?' —
    there can be more than one question in a message; each is checked
    independently."""
    clauses: List[str] = []
    buf = ""
    for token in _QUESTION_CLAUSE_TOKEN_RE.split(text):
        if token and _QUESTION_CLAUSE_TOKEN_RE.fullmatch(token):
            if token.strip() == "?":
                clauses.append(buf + "?")
            buf = ""
        else:
            buf += token or ""
    return clauses


def _question_is_self_referential(text: str) -> bool:
    return any(_SELF_REFERENTIAL_QUESTION_RE.search(c) for c in _question_clauses(text))


def classify_conversation_mode(
    message: str,
    intent: Optional[str] = None,
    has_question: Optional[bool] = None,
) -> str:
    """Personal-conversation remediation plan, step 2: classify the CURRENT
    turn into a small set of modes that govern how much ambient context
    (world brief, health metrics, work queues, proactive nudges) is worth
    showing the model, independent of ContextRouter.decide()'s per-source
    flags.

    Returns one of "social", "personal_vulnerable", "action",
    "factual_advice", "mixed". Never raises; unrecognized/empty input
    degrades to "social" — the most conservative, least-ambient-context
    default — rather than to "action"/"factual_advice", which would leave
    the full context payload flowing on exactly the turns this exists to
    quiet down.
    """
    text = (message or "").strip()
    if not text:
        return "social"
    # iOS/keyboard autocorrect sends curly apostrophes ("I’m tired") — a
    # plain "i'm tired"/straight-quote keyword list silently misses every
    # one of them. Caught by replaying David's actual 2026-09-22 messages
    # against this classifier (the plan's own step-1 evidence), not by any
    # synthetic test case.
    text = text.replace("’", "'").replace("‘", "'").replace("ʼ", "'")
    lowered = text.lower()
    if has_question is None:
        has_question = "?" in text

    vulnerable = (
        any(kw in lowered for kw in _VULNERABLE_SIGNALS)
        or bool(_VULNERABLE_WORD_RE.search(lowered))
    )
    has_action_verb = (
        any(kw in lowered for kw in _ACTION_SIGNALS)
        or _has_ambiguous_action_verb(lowered)
    )

    if vulnerable:
        # A real action verb always keeps the request live — "an explicit
        # request for work in a vulnerable message remains actionable" —
        # regardless of whether a question is also present.
        if has_action_verb:
            return "mixed"
        # A bare question only counts as action-evidence here when it
        # reads as a genuine, self-referential information request (see
        # _question_is_self_referential's docstring) — a pleasantry
        # tacked onto the disclosure must not do this on its own.
        if has_question and _question_is_self_referential(text):
            return "mixed"
        return "personal_vulnerable"

    action = has_question or has_action_verb
    if action:
        return "action" if has_action_verb else "factual_advice"

    if len(lowered) < 40 or _GREETING_OR_SMALLTALK_RE.match(text):
        return "social"

    # Longer message, no question, no action verb, no vulnerable signal —
    # ordinary conversation. Treated the same as "social" for ambient-context
    # purposes rather than defaulting to the full-context "factual_advice"
    # path just because it ran out of more specific matches.
    return "social"


# Modes where ambient world-brief/health/work/proactive material should be
# demoted or omitted unless a genuinely urgent alert overrides it (plan step
# 2). "mixed" and "action" are deliberately excluded — those turns carry an
# explicit request and keep full context/tool availability.
AMBIENT_SUPPRESS_MODES = frozenset({"social", "personal_vulnerable"})

# How long an unacknowledged urgent/critical outbox item still counts as a
# live override for AMBIENT_SUPPRESS_MODES — a defined source (outbox_item's
# own `priority` column) and a defined expiry, rather than treating every
# open task as urgent (the exact failure mode the plan's step 2 calls out).
URGENT_ALERT_WINDOW_HOURS = 6


def has_active_urgent_alert(db, user_id: str) -> bool:
    """True when an urgent/critical item is still live in the outbox — the
    override that lets ambient context back in even on a social/
    personal_vulnerable turn. Fails closed (False) on any error: a broken
    query must never become the reason a family-emergency turn gets a
    health readout or a task list."""
    try:
        from sqlalchemy import text as _sql_text
        from datetime import datetime, timedelta, timezone

        since = datetime.now(timezone.utc) - timedelta(hours=URGENT_ALERT_WINDOW_HOURS)
        row = db.execute(_sql_text("""
            SELECT 1 FROM outbox_item
            WHERE user_id = :uid
              AND status IN ('new', 'sent')
              AND priority IN ('urgent', 'critical')
              AND created_at >= :since
            LIMIT 1
        """), {"uid": user_id, "since": since}).fetchone()
        return row is not None
    except Exception as e:
        logger.debug(f"[ContextRouter] urgent-alert check failed (fail-closed): {e}")
        return False


# Singleton instance
_context_router = None


def get_context_router() -> ContextRouter:
    """Get or create the context router singleton"""
    global _context_router
    if _context_router is None:
        _context_router = ContextRouter()
    return _context_router
