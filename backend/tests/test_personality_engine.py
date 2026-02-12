"""
Tests for PersonalityEngine — tone/verbosity adaptation based on activity + body state.
"""

import pytest
from app.services.personality_engine import (
    PersonalityContext,
    build_personality_context,
    _calibrate_verbosity,
    _build_emotional_modulation,
    _extract_topics_simple,
    ACTIVITY_TONES,
    ACTIVITY_VERBOSITY,
)


class TestBaseTone:
    def test_sleeping_tone(self):
        ctx = build_personality_context(activity_state="sleeping")
        assert "brief" in ctx.tone_directive.lower() or "whisper" in ctx.tone_directive.lower()

    def test_active_tone(self):
        ctx = build_personality_context(activity_state="active")
        assert "natural" in ctx.tone_directive.lower() or "conversational" in ctx.tone_directive.lower()

    def test_focused_work_tone(self):
        ctx = build_personality_context(activity_state="focused_work")
        assert "concise" in ctx.tone_directive.lower() or "direct" in ctx.tone_directive.lower()

    def test_exercising_tone(self):
        ctx = build_personality_context(activity_state="exercising")
        assert "brief" in ctx.tone_directive.lower() or "encouraging" in ctx.tone_directive.lower()

    def test_winding_down_tone(self):
        ctx = build_personality_context(activity_state="winding_down")
        assert "calm" in ctx.tone_directive.lower() or "gentle" in ctx.tone_directive.lower()

    def test_in_meeting_tone(self):
        ctx = build_personality_context(activity_state="in_meeting")
        assert "ultra" in ctx.tone_directive.lower() or "brief" in ctx.tone_directive.lower()


class TestBodyStateModulation:
    def test_high_stress_modulation(self):
        ctx = build_personality_context(activity_state="active", stress_load=0.8)
        assert "stress" in ctx.tone_directive.lower() or "warm" in ctx.tone_directive.lower()

    def test_low_alertness_modulation(self):
        ctx = build_personality_context(activity_state="active", alertness=0.2)
        assert "tired" in ctx.tone_directive.lower() or "gentle" in ctx.tone_directive.lower()

    def test_high_alertness_modulation(self):
        ctx = build_personality_context(activity_state="active", alertness=0.9)
        assert "alert" in ctx.tone_directive.lower() or "precise" in ctx.tone_directive.lower()

    def test_low_blood_sugar_modulation(self):
        ctx = build_personality_context(activity_state="active", blood_sugar=0.1)
        assert "eaten" in ctx.tone_directive.lower() or "proactive" in ctx.tone_directive.lower()

    def test_afternoon_dip(self):
        ctx = build_personality_context(activity_state="active", circadian_phase="afternoon_dip")
        assert "afternoon" in ctx.tone_directive.lower() or "energized" in ctx.tone_directive.lower()


class TestVerbosityCalibration:
    def test_sleeping_ultra_brief(self):
        ctx = build_personality_context(activity_state="sleeping")
        assert ctx.verbosity == "ultra_brief"

    def test_active_balanced(self):
        ctx = build_personality_context(activity_state="active", interruptibility=0.8)
        assert ctx.verbosity == "balanced"

    def test_low_interruptibility_forces_ultra_brief(self):
        result = _calibrate_verbosity("balanced", interruptibility=0.1, turn_count=5, conversation_depth=5)
        assert result == "ultra_brief"

    def test_low_interruptibility_caps_at_brief(self):
        result = _calibrate_verbosity("balanced", interruptibility=0.35, turn_count=5, conversation_depth=5)
        assert result in ("ultra_brief", "brief")

    def test_deep_conversation_allows_detailed(self):
        result = _calibrate_verbosity("balanced", interruptibility=0.7, turn_count=10, conversation_depth=12)
        assert result == "detailed"

    def test_moderate_depth_at_least_balanced(self):
        result = _calibrate_verbosity("brief", interruptibility=0.5, turn_count=5, conversation_depth=7)
        assert result in ("balanced", "detailed")

    def test_first_turn_never_detailed(self):
        result = _calibrate_verbosity("detailed", interruptibility=0.9, turn_count=1, conversation_depth=0)
        assert result != "detailed"

    def test_verbosity_scales_with_depth(self):
        shallow = build_personality_context(
            activity_state="active", interruptibility=0.7,
            turn_count=3, conversation_depth=2,
        )
        deep = build_personality_context(
            activity_state="active", interruptibility=0.7,
            turn_count=15, conversation_depth=15,
        )
        levels = ["ultra_brief", "brief", "balanced", "detailed"]
        assert levels.index(deep.verbosity) >= levels.index(shallow.verbosity)


class TestRender:
    def test_render_produces_string(self):
        ctx = build_personality_context(activity_state="active")
        output = ctx.render()
        assert isinstance(output, str)
        assert len(output) > 0

    def test_render_includes_tone(self):
        ctx = build_personality_context(activity_state="active")
        output = ctx.render()
        assert "Tone:" in output

    def test_render_includes_verbosity(self):
        ctx = build_personality_context(activity_state="active")
        output = ctx.render()
        assert "Verbosity:" in output

    def test_render_includes_memory_nudges(self):
        ctx = build_personality_context(
            activity_state="active",
            memory_nudges=["You mentioned liking pasta last week"],
        )
        output = ctx.render()
        assert "pasta" in output

    def test_render_includes_personality_header(self):
        ctx = build_personality_context(activity_state="active")
        output = ctx.render()
        assert "Personality layer" in output


class TestDefaultState:
    def test_default_neutral_state(self):
        ctx = build_personality_context()
        assert ctx.tone_directive != ""
        assert ctx.verbosity in ("ultra_brief", "brief", "balanced", "detailed")

    def test_no_body_state_references_in_output(self):
        """Output should never expose raw numbers like 'blood sugar: 0.3'."""
        ctx = build_personality_context(
            activity_state="active",
            stress_load=0.5, alertness=0.5, blood_sugar=0.5,
        )
        output = ctx.render()
        assert "blood_sugar" not in output
        assert "alertness score" not in output
        assert "0.5" not in output


class TestEmotionalModulation:
    def test_high_energy_detected(self):
        result = _build_emotional_modulation("active", 0.2, 0.9, 0.7, "normal", None)
        assert "high energy" in result

    def test_low_energy_detected(self):
        result = _build_emotional_modulation("active", 0.3, 0.2, 0.2, "normal", None)
        assert "low energy" in result

    def test_elevated_stress_detected(self):
        result = _build_emotional_modulation("active", 0.8, 0.5, 0.5, "normal", None)
        assert "elevated stress" in result

    def test_relaxed_detected(self):
        result = _build_emotional_modulation("active", 0.1, 0.5, 0.5, "normal", None)
        assert "relaxed" in result

    def test_default_normal_state(self):
        result = _build_emotional_modulation("active", 0.3, 0.5, 0.5, "normal", None)
        assert "normal" in result.lower() or "steady" in result.lower()


class TestTopicExtraction:
    def test_extract_meaningful_topics(self):
        topics = _extract_topics_simple("I was thinking about cooking pasta for dinner tonight")
        assert len(topics) > 0
        assert "cooking" in topics or "pasta" in topics or "dinner" in topics

    def test_short_message_no_topics(self):
        topics = _extract_topics_simple("hi there")
        assert topics == []

    def test_stop_words_filtered(self):
        topics = _extract_topics_simple("I was thinking about the things that happened")
        assert "the" not in topics
        assert "was" not in topics

    def test_proper_nouns_prioritized(self):
        topics = _extract_topics_simple("I was talking to Michael about the project")
        if topics:
            assert topics[0] == "michael"


class TestMemoryNudges:
    def test_nudges_capped_at_3(self):
        ctx = build_personality_context(
            memory_nudges=["one", "two", "three", "four", "five"],
        )
        assert len(ctx.memory_nudges) <= 3

    def test_no_nudges_when_empty(self):
        ctx = build_personality_context(memory_nudges=None)
        assert ctx.memory_nudges == []
