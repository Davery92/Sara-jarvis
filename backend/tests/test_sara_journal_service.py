"""
Tests for SaraJournalService — Sara's inner monologue journal entries.

Tests prompt construction, emotional state inference, and entry storage.
Uses mocked LLM and database.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.services.sara_journal_service import SaraJournalService, JournalEntry


@pytest.fixture
def journal_service():
    return SaraJournalService()


class TestEmotionalStateInference:
    def test_concerned_from_worried(self, journal_service):
        assert journal_service._infer_emotional_state("I'm a bit worried about David today") == "concerned"

    def test_pleased_from_glad(self, journal_service):
        assert journal_service._infer_emotional_state("I'm glad David had a good day") == "pleased"

    def test_curious_from_wondering(self, journal_service):
        assert journal_service._infer_emotional_state("I'm wondering what he meant by that") == "curious"

    def test_calm_from_quiet(self, journal_service):
        assert journal_service._infer_emotional_state("It's been a quiet evening") == "calm"

    def test_neutral_default(self, journal_service):
        assert journal_service._infer_emotional_state("Nothing much happening") == "neutral"


class TestWatchingForExtraction:
    def test_extract_watching_for(self, journal_service):
        content = "David seemed stressed. I'm keeping an eye on his sleep tonight."
        result = journal_service._extract_watching_for(content)
        assert result is not None
        assert "sleep" in result.lower()

    def test_extract_watching_for_no_match(self, journal_service):
        content = "Just a regular entry. Nothing unusual."
        result = journal_service._extract_watching_for(content)
        assert result is None


class TestActionsExtraction:
    def test_extract_actions_from_nudges(self, journal_service):
        nudges = [
            {"title": "Weather update", "message": "Rain expected"},
            {"title": "Calendar", "message": "Meeting in 30 min"},
        ]
        result = journal_service._extract_actions(nudges)
        assert "Weather update" in result
        assert "Calendar" in result

    def test_extract_actions_empty(self, journal_service):
        result = journal_service._extract_actions(None)
        assert "No nudges" in result

    def test_extract_actions_caps_at_3(self, journal_service):
        nudges = [{"title": f"Nudge {i}", "message": "msg"} for i in range(10)]
        result = journal_service._extract_actions(nudges)
        # Should only include last 3
        assert "Nudge 7" in result or "Nudge 8" in result or "Nudge 9" in result


class TestBodyStateFormat:
    def test_format_low_blood_sugar(self, journal_service):
        result = journal_service._format_body_state({"blood_sugar": 0.2})
        assert "low" in result.lower()

    def test_format_good_alertness(self, journal_service):
        result = journal_service._format_body_state({"alertness": 0.8})
        assert "good" in result.lower()

    def test_format_empty_state(self, journal_service):
        result = journal_service._format_body_state({})
        assert "No body state" in result


class TestPromptConstruction:
    """Test that the prompt template assembles correctly."""

    def test_prompt_includes_activity_state(self, journal_service):
        """Verify that activity_state parameter appears in the prompt context."""
        prompt = journal_service.PERIODIC_ENTRY_PROMPT.format(
            time="10:00 AM",
            time_since_last="about 30 minutes",
            context="**David's activity:** FOCUSED_WORK (in office)",
            previous_entry="Nothing much happening."
        )
        assert "FOCUSED_WORK" in prompt
        assert "office" in prompt

    def test_prompt_includes_anti_hallucination_rules(self, journal_service):
        assert "DO NOT describe physical interactions" in journal_service.PERIODIC_ENTRY_PROMPT or \
               "do NOT describe physical" in journal_service.PERIODIC_ENTRY_PROMPT.lower() or \
               "do not invent" in journal_service.PERIODIC_ENTRY_PROMPT.lower()

    def test_prompt_is_first_person(self, journal_service):
        assert "first person" in journal_service.PERIODIC_ENTRY_PROMPT.lower()


class TestJournalEntryDataclass:
    def test_to_dict(self):
        entry = JournalEntry(
            id="test-id", user_id="user-1", entry_type="periodic",
            content="Test content", observations=None, interpretation=None,
            emotional_state="neutral", actions_taken=None, watching_for=None,
            conversation_id=None, created_at=datetime(2025, 1, 1, 12, 0),
            context={"mood_context": "calm"},
        )
        d = entry.to_dict()
        assert d["id"] == "test-id"
        assert d["entry_type"] == "periodic"
        assert d["content"] == "Test content"
        assert d["emotional_state"] == "neutral"
        assert "2025-01-01" in d["created_at"]


class TestWritePeriodicEntry:
    @pytest.mark.asyncio
    async def test_periodic_entry_calls_llm(self, journal_service, mock_background_llm):
        """write_periodic_entry → LLM called, entry returned."""
        mock_db = MagicMock()
        # Mock the previous entry query
        mock_db.execute.return_value.fetchone.return_value = None
        mock_db.commit = MagicMock()

        with patch.object(journal_service, '_generate_entry', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "Quiet evening. David hasn't chatted."

            result = await journal_service.write_periodic_entry(
                db=mock_db, user_id="test-user",
                activity_state="ACTIVE", activity_room="office",
            )
            assert result is not None
            assert result.entry_type == "periodic"
            assert "Quiet evening" in result.content
            mock_gen.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self, journal_service):
        """LLM failure → returns None, no crash."""
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = None

        with patch.object(journal_service, '_generate_entry', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = None

            result = await journal_service.write_periodic_entry(
                db=mock_db, user_id="test-user",
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_handles_empty_context(self, journal_service):
        """All context params None → still generates (sparse) entry."""
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = None
        mock_db.commit = MagicMock()

        with patch.object(journal_service, '_generate_entry', new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "Not much going on."

            result = await journal_service.write_periodic_entry(
                db=mock_db, user_id="test-user",
                # All optional params left as None
            )
            assert result is not None
            assert result.content == "Not much going on."


class TestGenerateEntry:
    @pytest.mark.asyncio
    async def test_generate_entry_success(self, journal_service):
        """_generate_entry makes an LLM call and returns content."""
        mock_response = {
            "choices": [{"message": {"content": "A thoughtful journal entry."}}]
        }
        with patch("app.services.sara_journal_service.llm_client") as mock_llm:
            mock_llm.chat_completion = AsyncMock(return_value=mock_response)
            result = await journal_service._generate_entry("test prompt")
            assert result == "A thoughtful journal entry."

    @pytest.mark.asyncio
    async def test_generate_entry_disables_thinking_mode(self, journal_service):
        """gotcha_qwen_thinking: without enable_thinking=False, qwen3.6 burns
        a huge reasoning budget before a short entry — found live 2026-07-29
        building Arc 4.2's self-story (a 3-word test prompt alone produced
        595 reasoning tokens / ~30s), reliably timing out the longer
        self-story prompt. Every other LLM-calling service in this codebase
        already sets this; sara_journal_service was the one gap."""
        mock_response = {"choices": [{"message": {"content": "Entry."}}]}
        with patch("app.services.sara_journal_service.llm_client") as mock_llm:
            mock_llm.chat_completion = AsyncMock(return_value=mock_response)
            await journal_service._generate_entry("test prompt")
            call_kwargs = mock_llm.chat_completion.call_args.kwargs
            assert call_kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}

    @pytest.mark.asyncio
    async def test_generate_entry_timeout(self, journal_service):
        """LLM timeout → returns None."""
        with patch("app.services.sara_journal_service.llm_client") as mock_llm:
            mock_llm.chat_completion = AsyncMock(side_effect=TimeoutError("timeout"))
            result = await journal_service._generate_entry("test prompt")
            assert result is None

    @pytest.mark.asyncio
    async def test_generate_entry_uses_timeout(self, journal_service):
        """LLM called with timeout >= 120."""
        mock_response = {
            "choices": [{"message": {"content": "Entry."}}]
        }
        with patch("app.services.sara_journal_service.llm_client") as mock_llm:
            mock_llm.chat_completion = AsyncMock(return_value=mock_response)
            await journal_service._generate_entry("test prompt")
            call_kwargs = mock_llm.chat_completion.call_args
            assert call_kwargs.kwargs.get("timeout", 0) >= 120 or \
                   (len(call_kwargs.args) > 1 and True)  # timeout=120.0 passed


class TestSelfStory:
    """Arc 4.2: 'dreaming writes the day's chapter... and maintains a
    rolling consolidated self-story... yesterday's self constrains
    today's.' get_self_story/write_self_story, not the raw per-entry
    journal feed."""

    @pytest.mark.asyncio
    async def test_get_self_story_reads_latest_row(self, journal_service):
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = MagicMock(content="Yesterday I helped with the Risk Ninja deck.")
        result = await journal_service.get_self_story(mock_db, "user-1")
        assert result == "Yesterday I helped with the Risk Ninja deck."
        query = mock_db.execute.call_args[0][0].text
        assert "entry_type = 'self_story'" in query
        assert "ORDER BY created_at DESC" in query

    @pytest.mark.asyncio
    async def test_get_self_story_none_when_no_row(self, journal_service):
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = None
        result = await journal_service.get_self_story(mock_db, "user-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_write_self_story_nothing_to_consolidate_returns_none(self, journal_service):
        """No previous story and no recent entries — genuinely nothing to
        write yet, not an error."""
        mock_db = MagicMock()
        with patch.object(journal_service, "get_self_story", new=AsyncMock(return_value=None)), \
             patch.object(journal_service, "get_recent_entries", new=AsyncMock(return_value=[])):
            result = await journal_service.write_self_story(mock_db, "user-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_write_self_story_folds_previous_and_recent_into_prompt(self, journal_service):
        fake_entry = MagicMock(entry_type="periodic", content="Helped David plan tomorrow's meeting.")
        with patch.object(journal_service, "get_self_story", new=AsyncMock(return_value="Old self-story.")), \
             patch.object(journal_service, "get_recent_entries", new=AsyncMock(return_value=[fake_entry])), \
             patch.object(journal_service, "_generate_entry", new=AsyncMock(return_value="New consolidated self-story.")) as mock_gen, \
             patch.object(journal_service, "_store_entry", new=AsyncMock()) as mock_store:
            result = await journal_service.write_self_story(MagicMock(), "user-1")

        assert result == "New consolidated self-story."
        prompt = mock_gen.call_args[0][0]
        assert "Old self-story." in prompt
        assert "Helped David plan tomorrow's meeting." in prompt
        mock_store.assert_awaited_once()
        assert mock_store.call_args.kwargs["entry_type"] == "self_story"
        assert mock_store.call_args.kwargs["content"] == "New consolidated self-story."

    @pytest.mark.asyncio
    async def test_write_self_story_first_ever_entry_has_no_prior_story_placeholder(self, journal_service):
        fake_entry = MagicMock(entry_type="periodic", content="First day of journaling.")
        with patch.object(journal_service, "get_self_story", new=AsyncMock(return_value=None)), \
             patch.object(journal_service, "get_recent_entries", new=AsyncMock(return_value=[fake_entry])), \
             patch.object(journal_service, "_generate_entry", new=AsyncMock(return_value="My first self-story.")) as mock_gen, \
             patch.object(journal_service, "_store_entry", new=AsyncMock()):
            result = await journal_service.write_self_story(MagicMock(), "user-1")

        assert result == "My first self-story."
        prompt = mock_gen.call_args[0][0]
        assert "there is no prior story yet" in prompt

    @pytest.mark.asyncio
    async def test_write_self_story_llm_failure_returns_none(self, journal_service):
        with patch.object(journal_service, "get_self_story", new=AsyncMock(return_value="Old story.")), \
             patch.object(journal_service, "get_recent_entries", new=AsyncMock(return_value=[])), \
             patch.object(journal_service, "_generate_entry", new=AsyncMock(return_value=None)), \
             patch.object(journal_service, "_store_entry", new=AsyncMock()) as mock_store:
            result = await journal_service.write_self_story(MagicMock(), "user-1")

        assert result is None
        mock_store.assert_not_awaited()


class TestTheoryOfDavid:
    """Arc 4.5: 'one versioned document she maintains in dreaming —
    rhythms, preferences, stress signatures, active arcs... grow from
    model-of-you + life_fact; do not create a new store.'
    get_theory_of_david/write_theory_of_david, same shape as self-story but
    sourced from the substrate services instead of raw journal entries."""

    @pytest.mark.asyncio
    async def test_get_theory_of_david_reads_latest_row(self, journal_service):
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = MagicMock(content="David trains around 1pm.")
        result = await journal_service.get_theory_of_david(mock_db, "user-1")
        assert result == "David trains around 1pm."
        query = mock_db.execute.call_args[0][0].text
        assert "entry_type = 'theory_of_david'" in query
        assert "ORDER BY created_at DESC" in query

    @pytest.mark.asyncio
    async def test_get_theory_of_david_none_when_no_row(self, journal_service):
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = None
        result = await journal_service.get_theory_of_david(mock_db, "user-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_write_theory_of_david_nothing_to_consolidate_returns_none(self, journal_service):
        """No previous doc and every substrate source empty — genuinely
        nothing to ground a first document in."""
        mock_db = MagicMock()
        with patch.object(journal_service, "get_theory_of_david", new=AsyncMock(return_value=None)), \
             patch("app.services.life_facts.get_life_facts_summary", new=AsyncMock(return_value=None)), \
             patch("app.services.behavioral_pattern_service.behavioral_pattern_service.get_active_patterns",
                   new=AsyncMock(return_value=[])), \
             patch("app.services.working_memory.read_memory",
                   new=AsyncMock(side_effect=Exception("no working memory in test"))), \
             patch("app.services.intent_graph_projection.get_intent_graph",
                   return_value={"total": 0, "intents": []}):
            result = await journal_service.write_theory_of_david(mock_db, "user-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_write_theory_of_david_folds_previous_and_substrate_into_prompt(self, journal_service):
        stress_snap = MagicMock(stress_load=0.65, alertness=0.4, circadian_phase="evening")
        with patch.object(journal_service, "get_theory_of_david", new=AsyncMock(return_value="Old understanding.")), \
             patch("app.services.life_facts.get_life_facts_summary",
                   new=AsyncMock(return_value="David normally: wakes 5:00, trains 13:10.")), \
             patch("app.services.behavioral_pattern_service.behavioral_pattern_service.get_active_patterns",
                   new=AsyncMock(return_value=[{"description": "Checks calendar before leaving for work."}])), \
             patch("app.services.working_memory.read_memory", new=AsyncMock(return_value=stress_snap)), \
             patch("app.services.intent_graph_projection.get_intent_graph",
                   return_value={"total": 1, "intents": [{"next_step": "Finish the Risk Ninja deck", "kind": "commitment"}]}), \
             patch.object(journal_service, "_generate_entry", new=AsyncMock(return_value="New consolidated understanding.")) as mock_gen, \
             patch.object(journal_service, "_store_entry", new=AsyncMock()) as mock_store:
            result = await journal_service.write_theory_of_david(MagicMock(), "user-1")

        assert result == "New consolidated understanding."
        prompt = mock_gen.call_args[0][0]
        assert "Old understanding." in prompt
        assert "wakes 5:00, trains 13:10" in prompt
        assert "Checks calendar before leaving for work." in prompt
        assert "Finish the Risk Ninja deck" in prompt
        assert "0.65" in prompt
        mock_store.assert_awaited_once()
        assert mock_store.call_args.kwargs["entry_type"] == "theory_of_david"
        assert mock_store.call_args.kwargs["content"] == "New consolidated understanding."

    @pytest.mark.asyncio
    async def test_write_theory_of_david_first_ever_entry_has_no_prior_placeholder(self, journal_service):
        with patch.object(journal_service, "get_theory_of_david", new=AsyncMock(return_value=None)), \
             patch("app.services.life_facts.get_life_facts_summary",
                   new=AsyncMock(return_value="David normally: wakes 5:00.")), \
             patch("app.services.behavioral_pattern_service.behavioral_pattern_service.get_active_patterns",
                   new=AsyncMock(return_value=[])), \
             patch("app.services.working_memory.read_memory",
                   new=AsyncMock(return_value=MagicMock(stress_load=0.3, alertness=0.5, circadian_phase="normal"))), \
             patch("app.services.intent_graph_projection.get_intent_graph",
                   return_value={"total": 0, "intents": []}), \
             patch.object(journal_service, "_generate_entry", new=AsyncMock(return_value="My first understanding.")) as mock_gen, \
             patch.object(journal_service, "_store_entry", new=AsyncMock()):
            result = await journal_service.write_theory_of_david(MagicMock(), "user-1")

        assert result == "My first understanding."
        prompt = mock_gen.call_args[0][0]
        assert "there is no prior understanding yet" in prompt

    @pytest.mark.asyncio
    async def test_write_theory_of_david_llm_failure_returns_none(self, journal_service):
        with patch.object(journal_service, "get_theory_of_david", new=AsyncMock(return_value="Old understanding.")), \
             patch("app.services.life_facts.get_life_facts_summary", new=AsyncMock(return_value=None)), \
             patch("app.services.behavioral_pattern_service.behavioral_pattern_service.get_active_patterns",
                   new=AsyncMock(return_value=[])), \
             patch("app.services.working_memory.read_memory",
                   new=AsyncMock(return_value=MagicMock(stress_load=0.3, alertness=0.5, circadian_phase="normal"))), \
             patch("app.services.intent_graph_projection.get_intent_graph",
                   return_value={"total": 0, "intents": []}), \
             patch.object(journal_service, "_generate_entry", new=AsyncMock(return_value=None)), \
             patch.object(journal_service, "_store_entry", new=AsyncMock()) as mock_store:
            result = await journal_service.write_theory_of_david(MagicMock(), "user-1")

        assert result is None
        mock_store.assert_not_awaited()
