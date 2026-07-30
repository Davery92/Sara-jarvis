"""
Tests for context_snapshot.get_extended_signals() — the Arc 2.3 gap-closing
fetcher (2026-07-29). Calls the exact same underlying services the legacy
~19-source assembly's fetchers call (pkg_context_provider, daily_brief
service, sara_journal_service, behavioral_pattern table, device_orchestrator,
working_memory), so one failing category never blocks the others or the turn.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.context_snapshot import get_extended_signals


class TestGetExtendedSignals:
    @pytest.mark.asyncio
    async def test_all_categories_present_when_everything_succeeds(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchall.return_value = [
            MagicMock(description="side door locks at midnight", confidence=1.0)
        ]

        mock_recall_prose = AsyncMock(return_value="David co-founded Risk Ninja.")

        mock_brief_service = MagicMock()
        mock_brief_service.get_compiled_brief = AsyncMock(return_value="Meeting at 2pm.")

        mock_journal = MagicMock()
        mock_journal.get_entries_for_conversation_context = AsyncMock(return_value="Quiet morning.")

        mock_device_orch = MagicMock()
        mock_device_orch.get_device_context_for_chat = AsyncMock(return_value="[Device awareness] iPhone.")

        mock_wm = MagicMock(sara_emotional_tone="attentive", sara_emotional_intensity=0.6)

        with patch("app.services.memory_recall.recall_facts_prose", mock_recall_prose), \
             patch("app.services.daily_brief.daily_brief_service", mock_brief_service), \
             patch("app.services.sara_journal_service.sara_journal", mock_journal), \
             patch("app.services.device_orchestrator.device_orchestrator", mock_device_orch), \
             patch("app.services.working_memory.read_memory", new=AsyncMock(return_value=mock_wm)):

            result = await get_extended_signals(mock_db, "user-1", "how's my day")

        assert result["pkg"] == "David co-founded Risk Ninja."
        assert result["daily_brief"] == "Meeting at 2pm."
        assert result["journal"] == "Quiet morning."
        assert "side door locks at midnight" in result["patterns"]
        assert result["device"] == "[Device awareness] iPhone."
        assert result["emotional_tone"] == "attentive (0.60)"

    @pytest.mark.asyncio
    async def test_one_category_failing_does_not_block_the_others(self):
        mock_db = MagicMock()
        mock_db.execute.side_effect = RuntimeError("db exploded for patterns")

        mock_recall_prose = AsyncMock(return_value="still works")

        with patch("app.services.memory_recall.recall_facts_prose", mock_recall_prose), \
             patch("app.services.daily_brief.daily_brief_service") as mock_brief, \
             patch("app.services.sara_journal_service.sara_journal") as mock_journal, \
             patch("app.services.device_orchestrator.device_orchestrator") as mock_device, \
             patch("app.services.working_memory.read_memory", new=AsyncMock(side_effect=RuntimeError("boom"))):
            mock_brief.get_compiled_brief = AsyncMock(side_effect=RuntimeError("boom"))
            mock_journal.get_entries_for_conversation_context = AsyncMock(side_effect=RuntimeError("boom"))
            mock_device.get_device_context_for_chat = AsyncMock(side_effect=RuntimeError("boom"))

            result = await get_extended_signals(mock_db, "user-1", "test")

        assert result["pkg"] == "still works"
        assert result["patterns"] is None
        assert result["daily_brief"] is None
        assert result["journal"] is None
        assert result["device"] is None
        assert result["emotional_tone"] is None

    @pytest.mark.asyncio
    async def test_empty_string_results_become_none(self):
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchall.return_value = []

        mock_recall_prose = AsyncMock(return_value="")

        with patch("app.services.memory_recall.recall_facts_prose", mock_recall_prose), \
             patch("app.services.daily_brief.daily_brief_service") as mock_brief, \
             patch("app.services.sara_journal_service.sara_journal") as mock_journal, \
             patch("app.services.device_orchestrator.device_orchestrator") as mock_device, \
             patch("app.services.working_memory.read_memory", new=AsyncMock(return_value=None)):
            mock_brief.get_compiled_brief = AsyncMock(return_value="")
            mock_journal.get_entries_for_conversation_context = AsyncMock(return_value="   ")
            mock_device.get_device_context_for_chat = AsyncMock(return_value=None)

            result = await get_extended_signals(mock_db, "user-1", "test")

        assert result == {
            "pkg": None, "daily_brief": None, "journal": None,
            "patterns": None, "device": None, "emotional_tone": None,
        }
