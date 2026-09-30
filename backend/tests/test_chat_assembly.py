"""Tests against the actual outgoing chat payload (living-world-context
plan, Phase 0/2): assemble_local_provider_messages is the exact function
main_simple.py calls to build `all_messages` for local-provider turns — not
a reconstruction of what the payload is supposed to look like.
"""
from app.schemas.chat import ChatMessage
from app.services.chat_assembly import (
    WORLD_BRIEF_MARKER,
    assemble_local_provider_messages,
    assemble_non_local_provider_messages,
    assemble_voice_messages,
    compose_voice_persona,
    replace_world_state_core_in_messages,
)

STABLE = "You are Sara, David's assistant. [stable persona text]"


def _assemble(**overrides):
    kwargs = dict(
        full_sys=STABLE,
        stable_system_prompt=STABLE,
        conversation_history=[],
        merged_request_messages=[ChatMessage(role="user", content="What's up?")],
        dialogue_block="",
        world_state_core="",
        world_brief="",
        datetime_line="It's Thursday, 2:00 PM ET.",
        live_context_char_budget=4500,
    )
    kwargs.update(overrides)
    return assemble_local_provider_messages(**kwargs)


def _last_user_content(result) -> str:
    messages = result["all_messages"]
    user_msgs = [m for m in messages if m.role == "user"]
    content = user_msgs[-1].content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


class TestWorldFactsSurviveAllocation:
    """The user's explicit requirement: 'current world facts must survive
    context allocation' — proven against the real outgoing message list,
    not the allocator alone."""

    def test_world_state_core_reaches_the_actual_outgoing_message(self):
        result = _assemble(
            full_sys=STABLE + "\n\n" + "y" * 6000,  # a huge engaged-context-shaped blob
            world_state_core="Workout in progress: Upper Body A (started 8 minutes ago).",
        )
        content = _last_user_content(result)
        assert "Workout in progress: Upper Body A" in content

    def test_world_brief_reaches_the_actual_outgoing_message_even_when_huge_engaged_context_precedes_it(self):
        """The exact Finding #1 reproduction, end to end through the real
        assembly function: a huge engaged-context blob is appended ahead of
        the World Brief in `full_sys`, exactly as main_simple.py does it."""
        brief_text = "David's 3pm dentist appointment is in one hour."
        full_sys = STABLE + "\n\n" + ("z" * 6000) + WORLD_BRIEF_MARKER + brief_text

        result = _assemble(full_sys=full_sys, world_brief=brief_text)

        content = _last_user_content(result)
        assert "dentist appointment" in content

    def test_dialogue_state_corrections_also_survive_alongside_world_state_core(self):
        result = _assemble(
            full_sys=STABLE + "\n\n" + ("x" * 6000),
            dialogue_block="## Conversation state (this turn)\nCorrections David has made this conversation:\n- 4 sets not 1",
            world_state_core="Workout in progress: Leg Day.",
        )
        content = _last_user_content(result)
        assert "4 sets not 1" in content
        assert "Workout in progress: Leg Day" in content

    def test_the_hard_budget_invariant_always_holds(self):
        result = _assemble(
            full_sys=STABLE + "\n\n" + ("w " * 5000),
            dialogue_block="d " * 300,
            world_state_core="c " * 300,
            world_brief=WORLD_BRIEF_MARKER.strip() and "b " * 300,
            live_context_char_budget=4500,
        )
        assert len(result["volatile"]) <= 4500


class TestOutgoingMessageStructure:
    def test_stable_system_prompt_is_the_leading_message(self):
        result = _assemble()
        first = result["all_messages"][0]
        assert first.role == "system"
        assert first.content == STABLE

    def test_live_context_is_spliced_into_the_last_user_message_not_appended_as_a_new_one(self):
        result = _assemble()
        messages = result["all_messages"]
        user_messages = [m for m in messages if m.role == "user"]
        assert len(user_messages) == 1
        assert "<live_context>" in _last_user_content(result)
        assert "</live_context>" in _last_user_content(result)

    def test_davids_actual_words_survive_after_the_closing_tag(self):
        result = _assemble(
            merged_request_messages=[ChatMessage(role="user", content="Did the workout finish?")]
        )
        content = _last_user_content(result)
        assert content.rstrip().endswith("Did the workout finish?")

    def test_multimodal_user_content_keeps_its_image_parts(self):
        result = _assemble(
            merged_request_messages=[ChatMessage(
                role="user",
                content=[{"type": "image", "data": "base64...", "media_type": "image/jpeg"},
                         {"type": "text", "text": "what is this"}],
            )]
        )
        last_user = [m for m in result["all_messages"] if m.role == "user"][-1]
        assert isinstance(last_user.content, list)
        kinds = [p.get("type") for p in last_user.content]
        assert "image" in kinds
        assert "text" in kinds  # the original text part
        # live context block was prepended as its own text part
        assert last_user.content[0]["type"] == "text"
        assert "<live_context>" in last_user.content[0]["text"]

    def test_no_user_turn_falls_back_to_a_leading_system_block(self):
        result = _assemble(merged_request_messages=[], conversation_history=[])
        messages = result["all_messages"]
        assert not any(m.role == "user" for m in messages)
        assert any("<live_context>" in (m.content or "") for m in messages if m.role == "system")

    def test_conversation_history_is_preserved_in_order(self):
        history = [
            ChatMessage(role="user", content="earlier question"),
            ChatMessage(role="assistant", content="earlier answer"),
        ]
        result = _assemble(conversation_history=history)
        roles_and_content = [(m.role, m.content) for m in result["all_messages"]]
        assert ("user", "earlier question") in [
            (r, c) for r, c in roles_and_content if not isinstance(c, list)
        ]


class TestProviderParity:
    """Living-world-context plan, Phase 2 item 8: 'Use the same fact
    precedence and freshness behavior for local and non-local providers.'
    Non-local (Claude/Gemini/codex) turns used to get neither
    dialogue_block nor world_state_core at all — only the local-provider
    branch spliced them in."""

    def test_world_state_core_reaches_a_non_local_providers_payload_too(self):
        result = assemble_non_local_provider_messages(
            full_sys=STABLE + "\n\n" + "engaged context here",
            dialogue_block="",
            world_state_core="Workout in progress: Leg Day.",
            datetime_line="It's Thursday, 2pm ET.",
            conversation_history=[],
            merged_request_messages=[ChatMessage(role="user", content="hi")],
        )
        system = result["all_messages"][0]
        assert system.role == "system"
        assert "Workout in progress: Leg Day" in system.content

    def test_dialogue_state_reaches_a_non_local_providers_payload_too(self):
        result = assemble_non_local_provider_messages(
            full_sys=STABLE, dialogue_block="Corrections David has made: 4 sets not 1",
            world_state_core="", datetime_line="It's Thursday.",
            conversation_history=[], merged_request_messages=[ChatMessage(role="user", content="hi")],
        )
        assert "4 sets not 1" in result["all_messages"][0].content

    def test_both_providers_see_the_same_world_state_core_content(self):
        """Not just 'present on both' — the same fact string, so neither
        provider can end up contradicting the other mid-conversation if a
        model switch happens."""
        core = "Workout in progress: Upper Body A (started 8 minutes ago)."
        local = assemble_local_provider_messages(
            full_sys=STABLE, stable_system_prompt=STABLE,
            conversation_history=[], merged_request_messages=[ChatMessage(role="user", content="hi")],
            dialogue_block="", world_state_core=core, world_brief="",
            datetime_line="It's Thursday.", live_context_char_budget=4500,
        )
        non_local = assemble_non_local_provider_messages(
            full_sys=STABLE, dialogue_block="", world_state_core=core,
            datetime_line="It's Thursday.", conversation_history=[],
            merged_request_messages=[ChatMessage(role="user", content="hi")],
        )

        def _text(messages):
            return "".join(
                (m.content if isinstance(m.content, str) else "".join(p.get("text", "") for p in m.content))
                for m in messages
            )

        assert core in _text(local["all_messages"])
        assert core in _text(non_local["all_messages"])

    def test_no_facts_produces_no_stray_blank_section(self):
        result = assemble_non_local_provider_messages(
            full_sys=STABLE, dialogue_block="", world_state_core="",
            datetime_line="It's Thursday.", conversation_history=[],
            merged_request_messages=[ChatMessage(role="user", content="hi")],
        )
        # datetime_line, a blank line, then full_sys directly — no
        # leftover "\n\n\n\n" gap where the (empty) core block would go.
        assert result["all_messages"][0].content == "It's Thursday.\n\n" + STABLE


class TestVoiceMessagesParity:
    """Living-world-context plan, Turn 3 item 1: voice
    (`/api/pi-dashboard/voice/chat`) is a third, independent
    context-assembly path — it reuses chat_with_tools for the actual model
    call but has always built its own `llm_messages` list, and that
    construction never included dialogue_state or world_state_core at all.
    These tests are against `assemble_voice_messages`, the exact function
    main_simple.py's voice endpoint now calls to build that list — not a
    reconstruction of what it should look like."""

    def test_world_state_core_reaches_voices_actual_outgoing_payload(self):
        messages = assemble_voice_messages(
            system_prompt="You are Sara, David's voice assistant.",
            dialogue_block="",
            world_state_core="Workout in progress: Upper Body A (started 8 minutes ago).",
            conversation_history=[],
            user_message="how's it going",
        )
        system = messages[0]
        assert system["role"] == "system"
        assert "Workout in progress: Upper Body A" in system["content"]

    def test_dialogue_state_reaches_voices_actual_outgoing_payload(self):
        messages = assemble_voice_messages(
            system_prompt="You are Sara.",
            dialogue_block="Corrections David has made: 4 sets not 1",
            world_state_core="",
            conversation_history=[],
            user_message="ok",
        )
        assert "4 sets not 1" in messages[0]["content"]

    def test_voice_history_and_new_message_land_after_the_system_message(self):
        history = [{"role": "user", "content": "earlier turn"}, {"role": "assistant", "content": "earlier reply"}]
        messages = assemble_voice_messages(
            system_prompt="You are Sara.", dialogue_block="", world_state_core="",
            conversation_history=history, user_message="latest turn",
        )
        assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
        assert messages[-1]["content"] == "latest turn"
        assert messages[1] == history[0]
        assert messages[2] == history[1]

    def test_no_facts_produces_no_stray_blank_section_in_voice_either(self):
        messages = assemble_voice_messages(
            system_prompt="You are Sara.", dialogue_block="", world_state_core="",
            conversation_history=[], user_message="hi",
        )
        assert messages[0]["content"] == "You are Sara."

    def test_voice_local_and_non_local_all_see_the_same_world_state_core_content(self):
        """Three independent assembly paths, one fact — parity across all
        of them, not just the original two."""
        core = "Workout in progress: Upper Body A (started 8 minutes ago)."
        local = assemble_local_provider_messages(
            full_sys=STABLE, stable_system_prompt=STABLE,
            conversation_history=[], merged_request_messages=[ChatMessage(role="user", content="hi")],
            dialogue_block="", world_state_core=core, world_brief="",
            datetime_line="It's Thursday.", live_context_char_budget=4500,
        )
        non_local = assemble_non_local_provider_messages(
            full_sys=STABLE, dialogue_block="", world_state_core=core,
            datetime_line="It's Thursday.", conversation_history=[],
            merged_request_messages=[ChatMessage(role="user", content="hi")],
        )
        voice = assemble_voice_messages(
            system_prompt=STABLE, dialogue_block="", world_state_core=core,
            conversation_history=[], user_message="hi",
        )

        def _local_non_local_text(messages):
            return "".join(
                (m.content if isinstance(m.content, str) else "".join(p.get("text", "") for p in m.content))
                for m in messages
            )

        assert core in _local_non_local_text(local["all_messages"])
        assert core in _local_non_local_text(non_local["all_messages"])
        assert core in voice[0]["content"]


class TestComposeVoicePersona:
    """Harness/thinking/personality plan, Phase 2: voice's persona used to
    be built by mutating a `system_prompt` string with `+=` across ~300
    lines of a 700-line SSE generator with no test coverage of its own.
    `compose_voice_persona` is the extracted, pure composition — these
    tests are against the ACTUAL function main_simple.py's voice endpoint
    now calls, not a reconstruction of it."""

    def test_datetime_comes_first_then_the_shared_persona(self):
        result = compose_voice_persona(
            datetime_line="It's Thursday, 6:54 AM.",
            persona="You are Sara, David's assistant.",
            overlay_parts=[],
        )
        assert result.startswith("It's Thursday, 6:54 AM.\n\n---\n\nYou are Sara")

    def test_overlay_parts_appended_in_order_after_the_persona(self):
        result = compose_voice_persona(
            datetime_line="dt", persona="PERSONA",
            overlay_parts=["## Canvas/Workspace Mode Active", "## Relevant Past Context:\n1. thing"],
        )
        persona_idx = result.index("PERSONA")
        canvas_idx = result.index("Canvas/Workspace Mode Active")
        context_idx = result.index("Relevant Past Context")
        assert persona_idx < canvas_idx < context_idx

    def test_falsy_overlay_entries_produce_no_stray_blank_sections(self):
        result = compose_voice_persona(
            datetime_line="dt", persona="PERSONA", overlay_parts=["", None, "real content"],
        )
        assert "\n\n\n\n" not in result
        assert result.endswith("real content")

    def test_no_overlay_is_just_datetime_plus_persona(self):
        result = compose_voice_persona(datetime_line="dt", persona="PERSONA", overlay_parts=[])
        assert result == "dt\n\n---\n\nPERSONA"

    def test_feeds_directly_into_assemble_voice_messages(self):
        """The composed persona is exactly what ends up as the system
        message's content — parity with the local/non-local provider
        functions, which all return the persona verbatim in messages[0]."""
        persona_text = compose_voice_persona(
            datetime_line="dt", persona="You are Sara.", overlay_parts=["extra context"],
        )
        messages = assemble_voice_messages(
            system_prompt=persona_text, dialogue_block="", world_state_core="",
            conversation_history=[], user_message="hi",
        )
        assert messages[0]["content"] == persona_text
        assert "extra context" in messages[0]["content"]


class TestReplaceWorldStateCoreInMessages:
    """Living-world-context plan, Turn 3 item 2: a fact that moves mid-turn
    must REPLACE the stale value already baked into the round loop's
    messages, not sit alongside it as a second, conflicting copy."""

    def test_replaces_stale_value_in_a_dict_system_message(self):
        messages = [{"role": "system", "content": "prefix\n\nWorkout in progress: Leg Day.\n\nsuffix"}]
        result, changed = replace_world_state_core_in_messages(
            messages, "Workout in progress: Leg Day.", "Workout finished: Leg Day (42 min)."
        )
        assert changed is True
        assert "Workout finished: Leg Day (42 min)." in result[0]["content"]
        assert "Workout in progress: Leg Day." not in result[0]["content"]
        # Not appended alongside — replaced exactly once.
        assert result[0]["content"].count("Workout") == 1

    def test_replaces_stale_value_inside_a_multipart_user_message(self):
        messages = [
            {"role": "system", "content": "persona"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "<live_context>\nWorkout in progress: Leg Day.\n</live_context>\n\nhow's it going"},
                ],
            },
        ]
        result, changed = replace_world_state_core_in_messages(
            messages, "Workout in progress: Leg Day.", "Workout finished: Leg Day (42 min)."
        )
        assert changed is True
        text = result[1]["content"][0]["text"]
        assert "Workout finished: Leg Day (42 min)." in text
        assert "Workout in progress: Leg Day." not in text

    def test_object_message_content_also_gets_replaced(self):
        """Local-provider assembly builds ChatMessage objects, not dicts, before
        they're serialized for the wire — the replacement must work on those too."""
        msg = ChatMessage(role="system", content="Workout in progress: Leg Day.")
        result, changed = replace_world_state_core_in_messages(
            [msg], "Workout in progress: Leg Day.", "Workout finished: Leg Day (42 min)."
        )
        assert changed is True
        assert result[0].content == "Workout finished: Leg Day (42 min)."

    def test_no_op_when_old_value_not_present(self):
        """Already evicted by context pressure, or never was in this
        message list — nothing to replace, and that's not an error."""
        messages = [{"role": "system", "content": "persona only"}]
        result, changed = replace_world_state_core_in_messages(
            messages, "Workout in progress: Leg Day.", "Workout finished: Leg Day (42 min)."
        )
        assert changed is False
        assert result[0]["content"] == "persona only"

    def test_no_op_when_value_is_unchanged(self):
        messages = [{"role": "system", "content": "Workout in progress: Leg Day."}]
        result, changed = replace_world_state_core_in_messages(
            messages, "Workout in progress: Leg Day.", "Workout in progress: Leg Day."
        )
        assert changed is False

    def test_no_op_when_old_value_is_empty(self):
        messages = [{"role": "system", "content": "persona only"}]
        result, changed = replace_world_state_core_in_messages(messages, "", "anything")
        assert changed is False
        assert result[0]["content"] == "persona only"


class TestBudgetPressureStillPreservesPriority:
    def test_when_nothing_fits_world_state_core_still_wins_over_generic_rest(self):
        """A punishing budget: only the guaranteed-priority sections should
        survive at all."""
        result = _assemble(
            full_sys=STABLE + "\n\n" + ("q " * 20000),
            world_state_core="Workout in progress: Leg Day.",
            live_context_char_budget=200,
        )
        content = _last_user_content(result)
        assert "Workout in progress" in content
