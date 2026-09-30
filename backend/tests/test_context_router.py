"""
Tests for ContextRouter — which context layers get injected for a given message.
"""

import pytest
from app.services.context_router import ContextRouter, ContextDecision


class TestMemoryInjection:
    def test_memory_injected_for_memory_keywords(self, context_router):
        d = context_router.decide("GENERAL", "do you remember when we discussed that?", turn_count=5)
        assert d.inject_memory is True

    def test_memory_injected_first_turn(self, context_router):
        d = context_router.decide("FITNESS", "log my lunch", turn_count=0)
        assert d.inject_memory is True

    def test_memory_injected_for_questions(self, context_router):
        d = context_router.decide("FITNESS", "how many calories did I eat?", turn_count=5)
        assert d.inject_memory is True

    def test_no_memory_for_simple_command(self, context_router):
        d = context_router.decide("TIME", "set a timer for 5 minutes", turn_count=5)
        assert d.inject_memory is False

    def test_memory_injected_for_memory_intent(self, context_router):
        d = context_router.decide("MEMORY", "some message", turn_count=5)
        assert d.inject_memory is True

    def test_memory_injected_for_general_intent(self, context_router):
        d = context_router.decide("GENERAL", "some message", turn_count=5)
        assert d.inject_memory is True


class TestCognitiveInjection:
    def test_cognitive_for_conversational_early(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "hey, how are things?", turn_count=1)
        assert d.inject_cognitive is True

    def test_no_cognitive_after_turn_2(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "tell me more", turn_count=5)
        assert d.inject_cognitive is False

    def test_no_cognitive_for_task_intent(self, context_router):
        d = context_router.decide("FITNESS", "log my workout", turn_count=1)
        assert d.inject_cognitive is False


class TestInsightInjection:
    def test_insight_for_question(self, context_router):
        d = context_router.decide("GENERAL", "what patterns do you see?", turn_count=3)
        assert d.inject_insight is True

    def test_no_insight_for_task_intents(self, context_router):
        d = context_router.decide("TIME", "what's on my calendar?", turn_count=3)
        assert d.inject_insight is False

    def test_no_insight_without_question(self, context_router):
        d = context_router.decide("GENERAL", "just thinking out loud", turn_count=3)
        assert d.inject_insight is False


class TestDailyBriefInjection:
    def test_daily_brief_in_normal_mode(self, context_router):
        d = context_router.decide("GENERAL", "hello", turn_count=1, in_work_mode=False)
        assert d.inject_daily_brief is True

    def test_daily_brief_suppressed_in_work_mode(self, context_router):
        d = context_router.decide("GENERAL", "hello", turn_count=1, in_work_mode=True)
        assert d.inject_daily_brief is False

    def test_daily_brief_in_work_mode_with_keyword(self, context_router):
        d = context_router.decide("TIME", "what's on my calendar today?", turn_count=3, in_work_mode=True)
        assert d.inject_daily_brief is True


class TestBodyStateInjection:
    def test_body_state_in_normal_mode(self, context_router):
        d = context_router.decide("GENERAL", "hello", turn_count=1, in_work_mode=False)
        assert d.inject_body_state is True

    def test_body_state_suppressed_in_work_mode(self, context_router):
        d = context_router.decide("GENERAL", "hello", turn_count=1, in_work_mode=True)
        assert d.inject_body_state is False

    def test_body_state_in_work_mode_with_keyword(self, context_router):
        d = context_router.decide("GENERAL", "I'm feeling tired today", turn_count=3, in_work_mode=True)
        assert d.inject_body_state is True


class TestSoulInjection:
    def test_soul_always_injected(self, context_router):
        d = context_router.decide("TIME", "set timer 5 min", turn_count=10, in_work_mode=True)
        assert d.inject_soul is True


class TestPKGInjection:
    def test_pkg_for_personal_questions(self, context_router):
        d = context_router.decide("GENERAL", "what do you know about me?", turn_count=3)
        assert d.inject_pkg is True

    def test_pkg_first_turn(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "hey there", turn_count=0)
        assert d.inject_pkg is True

    def test_pkg_for_conversational_intent(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "I like cooking Italian food", turn_count=3)
        assert d.inject_pkg is True

    def test_pkg_suppressed_in_work_mode(self, context_router):
        d = context_router.decide("GENERAL", "some task", turn_count=3, in_work_mode=True)
        assert d.inject_pkg is False

    def test_pkg_in_work_mode_with_keyword(self, context_router):
        d = context_router.decide("GENERAL", "what do you know about me?", turn_count=3, in_work_mode=True)
        assert d.inject_pkg is True


class TestPatternInjection:
    def test_patterns_for_keyword(self, context_router):
        d = context_router.decide("GENERAL", "have you noticed any patterns?", turn_count=3)
        assert d.inject_patterns is True

    def test_patterns_first_turn_conversational(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "good morning", turn_count=0)
        assert d.inject_patterns is True

    def test_patterns_suppressed_in_work_mode(self, context_router):
        d = context_router.decide("GENERAL", "some task", turn_count=3, in_work_mode=True)
        assert d.inject_patterns is False


class TestActivityContext:
    def test_activity_context_always_on(self, context_router):
        d = context_router.decide("TIME", "set timer", turn_count=10, in_work_mode=True)
        assert d.inject_activity_context is True


class TestLearningRecall:
    def test_learning_recall_for_topic_question(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "how does quantum computing work exactly?", turn_count=3)
        assert d.inject_learning_recall is True

    def test_learning_recall_suppressed_in_work_mode(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "how does quantum computing work?", turn_count=3, in_work_mode=True)
        assert d.inject_learning_recall is False

    def test_learning_recall_not_for_short_messages(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "ok thanks", turn_count=3)
        assert d.inject_learning_recall is False

    def test_learning_recall_not_for_task_intent(self, context_router):
        d = context_router.decide("TIME", "how does my calendar look for the rest of the day?", turn_count=3)
        assert d.inject_learning_recall is False


class TestChangesBrief:
    def test_changes_brief_first_turn(self, context_router):
        d = context_router.decide("GENERAL", "hey", turn_count=0)
        assert d.inject_changes_brief is True

    def test_changes_brief_catch_me_up(self, context_router):
        d = context_router.decide("GENERAL", "catch me up on what happened", turn_count=5)
        assert d.inject_changes_brief is True

    def test_no_changes_brief_mid_conversation(self, context_router):
        d = context_router.decide("GENERAL", "tell me more", turn_count=5)
        assert d.inject_changes_brief is False


class TestLessonsInjection:
    def test_lessons_for_conversational(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "let's chat", turn_count=1)
        assert d.inject_lessons is True

    def test_lessons_suppressed_in_work_mode(self, context_router):
        d = context_router.decide("CONVERSATIONAL", "let's chat", turn_count=1, in_work_mode=True)
        assert d.inject_lessons is False

    def test_no_lessons_for_task_intents(self, context_router):
        d = context_router.decide("TIME", "set timer 5 min", turn_count=1)
        assert d.inject_lessons is False


class TestDecisionStructure:
    def test_decision_is_namedtuple(self, context_router):
        d = context_router.decide("GENERAL", "hello", turn_count=0)
        assert isinstance(d, ContextDecision)
        assert len(d) == 13  # 12 bool fields + reason string

    def test_reason_string_present(self, context_router):
        d = context_router.decide("GENERAL", "hello", turn_count=0)
        assert isinstance(d.reason, str)
        assert "Injecting:" in d.reason

    def test_work_mode_in_reason(self, context_router):
        d = context_router.decide("GENERAL", "hello", turn_count=0, in_work_mode=True)
        assert "[WORK MODE]" in d.reason


class TestWorkModeSuppression:
    def test_work_mode_suppresses_extras(self, context_router):
        d = context_router.decide("GENERAL", "some task", turn_count=5, in_work_mode=True)
        # Work mode suppresses cognitive, patterns, daily_brief, body_state, pkg, lessons
        assert d.inject_cognitive is False
        assert d.inject_patterns is False
        assert d.inject_daily_brief is False
        assert d.inject_body_state is False
        assert d.inject_pkg is False
        assert d.inject_lessons is False
        # But soul and activity context stay on
        assert d.inject_soul is True
        assert d.inject_activity_context is True


# ═══════════════════════════════════════════════════════════════════════════
# Personal-conversation remediation plan (2026-09-23), step 2:
# classify_conversation_mode(). The three "David said" rows and the six
# counterexamples both come from the plan itself (fixture names and
# specifics redacted/paraphrased — no health values, private names, or task
# titles committed here per the plan's step 1 fixture guidance).
# ═══════════════════════════════════════════════════════════════════════════

from app.services.context_router import (
    AMBIENT_SUPPRESS_MODES,
    classify_conversation_mode,
    has_active_urgent_alert,
)


class TestConversationModeRealTranscriptTurns:
    """Verbatim text of the three real turns the plan's evidence table is
    built from (2026-09-22/23, already quoted in the plan doc itself) — not
    paraphrases. Replaying these against the classifier during
    implementation caught a real bug (see TestCurlyApostrophe below) that no
    synthetic test case would have."""

    def test_plain_greeting_is_social(self):
        assert classify_conversation_mode("Good evening") == "social"

    def test_ordinary_tiredness_with_no_question_is_personal_vulnerable(self):
        # Curly apostrophe, exactly as iOS autocorrect sent it.
        assert classify_conversation_mode("Just relaxing lol I’m tired") == "personal_vulnerable"

    def test_family_emergency_with_no_explicit_ask_is_personal_vulnerable(self):
        msg = "i had to take my dad to the er last night at 10 and got home at 2. im so tired"
        assert classify_conversation_mode(msg) == "personal_vulnerable"


class TestCurlyApostrophe:
    """iOS/keyboard autocorrect sends curly apostrophes (U+2019), not
    straight ones — a keyword list written with straight quotes silently
    misses every one of them. Found by replaying David's actual message
    text against this classifier, not by a synthetic test case."""

    def test_curly_apostrophe_matches_the_same_as_straight(self):
        straight = classify_conversation_mode("I'm tired")
        curly = classify_conversation_mode("I’m tired")
        assert straight == curly == "personal_vulnerable"

    def test_curly_apostrophe_in_a_greeting_contraction(self):
        assert classify_conversation_mode("how’s it going") == "social"


class TestConversationModeCounterexamples:
    """The plan's step 1 fixture list: greeting, playful small talk, ordinary
    tiredness, fatigue with an explicit health question, a family emergency,
    explicit request to postpone work, explicit request to triage urgent
    work, and a substantive request made in the same message as distress."""

    def test_playful_small_talk_is_social(self):
        assert classify_conversation_mode("haha you're something else") == "social"

    def test_fatigue_with_explicit_health_question_is_mixed(self):
        msg = "so tired today, is my HRV low again?"
        assert classify_conversation_mode(msg) == "mixed"

    def test_explicit_request_to_postpone_work_alongside_distress_is_mixed(self):
        """The plan is explicit that "an explicit request for work in a
        vulnerable message remains actionable" — the request must not be
        swallowed by the personal/vulnerable demotion."""
        msg = "can you push my 9am to tomorrow, I'm exhausted"
        assert classify_conversation_mode(msg) == "mixed"

    def test_explicit_request_to_triage_urgent_work_is_action(self):
        assert classify_conversation_mode("catch me up on anything urgent") == "action"

    def test_substantive_request_alongside_distress_is_mixed(self):
        msg = "rough night with my dad in the hospital, can you email the team I'm out tomorrow"
        assert classify_conversation_mode(msg) == "mixed"

    def test_plain_factual_question_is_factual_advice(self):
        assert classify_conversation_mode("what's the capital of Oregon?") == "factual_advice"


class TestConversationModeDefaults:
    def test_empty_message_is_social(self):
        assert classify_conversation_mode("") == "social"

    def test_unrecognized_longer_message_defaults_to_social_not_full_context(self):
        """Degrading to "social" (least ambient context) rather than
        "factual_advice" (full context) is the conservative direction — a
        false "quiet down" costs a slightly flatter reply, a false "show
        everything" is the exact failure this plan exists to fix."""
        msg = "the sunset over the water was really something tonight"
        assert classify_conversation_mode(msg) == "social"


class TestAmbiguousActionVerbFix:
    """2026-09-24 fix: "schedule", "cancel", "reschedule", "draft" were bare
    substring entries in _ACTION_SIGNALS — no word boundary (matched inside
    "rescheduled") and no noun/figurative guard (matched "a meeting
    schedule" or "my brain scheduled..."). Reproduced 3x during
    SARA_NATURAL_CONVERSATION_EVALUATION_PLAN_2026_09_23.md's testing
    (case 11, turn 7 / turn 6 x2) and confirmed live through the full
    assembly pipeline: 4-of-4 leak across 2 independent trials before this
    fix, 4-of-4 correctly suppressed after — see that study's FINDINGS.md,
    "Item 4", and item 3's `context_router_candidate.py` for the isolated
    design this production fix is drawn from.
    """

    def test_reproduced_bug_figurative_brain_scheduled_stays_social(self):
        # The exact reproduced text (Stage 2/case11/turn7, Stage 3/case11/turn6).
        msg = "meanwhile my brain scheduled a full review meeting"
        assert classify_conversation_mode(msg) == "social"

    def test_other_figurative_subjects_also_excluded(self):
        for msg in (
            "my head is running its own meeting schedule at 3am and I never agreed to it",
            # Bare infinitive form ("to schedule") after a figurative
            # subject -- exercises the figurative-subject guard directly,
            # since past-tense forms like "scheduled" are already excluded
            # by word-boundary matching alone.
            "i really want my brain to schedule literally anything else tonight",
        ):
            assert classify_conversation_mode(msg) == "social", msg

    def test_noun_usage_is_not_action_chess_set_canary(self):
        """The reviewer's specific canary: fixing the "schedule"
        noun/metaphor gap must not introduce a NEW false positive on an
        unrelated noun-phrase sentence. "chess set" never touches
        "schedule"/"cancel"/"reschedule"/"draft" at all — included as an
        explicit pin so a future change to this area can't quietly
        regress it."""
        assert classify_conversation_mode("I bought a chess set") == "social"

    def test_noun_usage_of_the_ambiguous_verbs_themselves(self):
        for msg in (
            "my sleep schedule is all over the place",
            "I read the first draft of the report last night",
            "the meeting was rescheduled for next week",  # inflected form, not the bare word
        ):
            assert classify_conversation_mode(msg) == "social", msg

    def test_genuine_bare_imperative_requests_still_trigger_action(self):
        for msg in (
            "schedule a follow-up call with the doctor's office for tomorrow",
            "draft an email to the team",
        ):
            assert classify_conversation_mode(msg) == "action", msg

    def test_genuine_request_via_can_you_phrase_unaffected(self):
        assert classify_conversation_mode("can you reschedule this for tomorrow") == "action"

    def test_vulnerable_word_in_the_same_message_still_yields_mixed(self):
        """"hospital" is a vulnerable signal — a genuine request alongside
        it must stay actionable (mode "mixed"), not get swallowed by the
        vulnerable demotion. Confirms the fix doesn't interact badly with
        the existing vulnerable+action logic."""
        msg = "can you schedule a reminder for 3pm to call the hospital"
        assert classify_conversation_mode(msg) == "mixed"

    def test_relevant_callback_suppression_is_unchanged_by_this_fix(self):
        """Documented, NOT fixed by this patch (out of its narrow scope):
        a relevant recent-event callback with no vulnerable/action signal
        still gets swept into AMBIENT_SUPPRESS_MODES same as irrelevant
        noise — this fix only narrows the action-verb false-positive
        surface, it does not add a relevance carve-out."""
        assert classify_conversation_mode("the printer and i are enemies again") == "social"


class TestVulnerableQuestionFix:
    """2026-09-24 fix: a bare trailing question was, on its own, enough to
    promote a vulnerable disclosure past "personal_vulnerable" straight to
    full-context mode. Reproduced live during Stage 5 adaptive testing
    (SARA_NATURAL_CONVERSATION_EVALUATION_PLAN_2026_09_23.md's FINDINGS.md,
    case 09 turn 2): "my dad's got some tests tomorrow... what are you up
    to today?" leaked an unrelated calendar item into Sara's reply because
    the trailing pleasantry alone flipped the mode to "factual_advice".
    Two independent gaps fixed together: (1) the disclosure itself carried
    no _VULNERABLE_SIGNALS match at all ("tests tomorrow" wasn't one);
    (2) even with that fixed, a bare question still needs to NOT promote
    the turn on its own — but the plan's own required counterexample
    ("so tired today, is my HRV low again?") must stay "mixed", so the
    fix distinguishes a genuine self-referential information question
    from a pleasantry addressed at Sara, scoped to the question's own
    sentence/clause (see _question_is_self_referential).
    """

    def test_reproduced_leak_case_stays_personal_vulnerable(self):
        msg = (
            "the 'get up and do something' one sounds good. honestly just... "
            "my dad's got some tests tomorrow. he's acting super chill about "
            "it but i can't really be chill about it. what are you up to today?"
        )
        assert classify_conversation_mode(msg) == "personal_vulnerable"

    def test_other_pleasantry_questions_after_a_vulnerable_disclosure(self):
        for msg in (
            "i'm really worried about the results. anyway how's your day going?",
            "rough night, kid was up sick. did you sleep okay?",
        ):
            assert classify_conversation_mode(msg) == "personal_vulnerable", msg

    def test_required_counterexample_self_referential_health_question_stays_mixed(self):
        """This exact case is already covered in
        TestConversationModeCounterexamples — repeated here as an explicit
        regression pin for this fix specifically, since a naive "no
        question ever promotes a vulnerable turn" fix would have broken
        it."""
        assert classify_conversation_mode("so tired today, is my HRV low again?") == "mixed"

    def test_comma_joined_disclosure_and_pleasantry_stays_suppressed(self):
        """Correction (2026-09-24, second review pass): the first version
        of this fix scoped the self-referential check to the last
        SENTENCE, so a disclosure and a trailing pleasantry joined by a
        comma (one sentence, not two) let the disclosure's own "my" ("my
        dad has tests tomorrow") satisfy the check for the unrelated
        question that followed it — the exact failure this fix exists to
        prevent, just moved one comma to the left. Also asserts on
        AMBIENT_SUPPRESS_MODES directly (the actual context-exposure
        outcome), not just the mode string."""
        msg = "my dad has tests tomorrow, how's your day?"
        mode = classify_conversation_mode(msg)
        assert mode == "personal_vulnerable"
        assert mode in AMBIENT_SUPPRESS_MODES

    def test_question_in_the_middle_of_the_message_is_still_found(self):
        """Correction (2026-09-24, second review pass): the first version
        also assumed the question was always the LAST sentence-shaped
        chunk — "I'm tired. Is my HRV low again? Just wondering." puts the
        actual question in the MIDDLE, with trailing text after it, so
        checking only the last chunk ("Just wondering") missed the
        self-referential "my HRV" entirely."""
        msg = "I'm tired. Is my HRV low again? Just wondering."
        mode = classify_conversation_mode(msg)
        assert mode == "mixed"
        assert mode not in AMBIENT_SUPPRESS_MODES

    def test_explicit_request_alongside_distress_stays_mixed_regardless_of_question(self):
        """"Preserve genuine requests embedded in emotional disclosures" —
        a real action verb (not just a question) must keep the turn
        actionable, independent of the question-pleasantry distinction."""
        for msg in (
            "my dad's tests are tomorrow and I'm anxious about it -- "
            "can you schedule a reminder for 3pm to call and check on him",
            "can you push my 9am to tomorrow, I am exhausted",
            "rough night with my dad in the hospital, can you email the team I am out tomorrow",
        ):
            assert classify_conversation_mode(msg) == "mixed", msg

    def test_non_vulnerable_plain_question_is_unaffected(self):
        """The fix only changes behavior INSIDE the vulnerable branch —
        an ordinary factual question with no vulnerable signal must keep
        its existing "factual_advice" classification."""
        assert classify_conversation_mode("what's the capital of Oregon?") == "factual_advice"


class TestAmbiguousActionVerbGenuineRequestsAfterBackgroundClauses:
    """The determiner guard added for the noun/metaphor fix (see
    TestAmbiguousActionVerbFix) must not reach across a background/reason
    clause and suppress a genuine request that follows it — a comma or a
    short non-determiner phrase between an earlier noun mention and the
    real imperative should leave the request untouched."""

    def test_genuine_requests_survive_a_preceding_background_clause(self):
        for msg in (
            "since my calendar got so packed, cancel my 3pm meeting",
            "after the schedule change, reschedule my dentist appointment",
            "my draft is a mess but please draft a new proposal for the client",
        ):
            assert classify_conversation_mode(msg) == "action", msg


class TestAmbientSuppressModes:
    def test_suppress_modes_are_exactly_social_and_personal_vulnerable(self):
        assert AMBIENT_SUPPRESS_MODES == frozenset({"social", "personal_vulnerable"})

    def test_action_and_mixed_are_not_suppressed(self):
        assert "action" not in AMBIENT_SUPPRESS_MODES
        assert "mixed" not in AMBIENT_SUPPRESS_MODES
        assert "factual_advice" not in AMBIENT_SUPPRESS_MODES


class TestHasActiveUrgentAlert:
    class _Row:
        def __init__(self, present):
            self._present = present

        def fetchone(self):
            return (1,) if self._present else None

    class _DB:
        def __init__(self, present):
            self._present = present

        def execute(self, *_a, **_kw):
            return TestHasActiveUrgentAlert._Row(self._present)

    def test_true_when_a_row_is_found(self):
        assert has_active_urgent_alert(self._DB(True), "u1") is True

    def test_false_when_no_row_is_found(self):
        assert has_active_urgent_alert(self._DB(False), "u1") is False

    def test_fails_closed_on_query_error(self):
        class _BrokenDB:
            def execute(self, *_a, **_kw):
                raise RuntimeError("db unavailable")

        assert has_active_urgent_alert(_BrokenDB(), "u1") is False
