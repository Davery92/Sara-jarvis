"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C9 attention shadow recorder:
decision classification, persistence shape, and — critically — that a
recorder failure can never affect the real `send_notification()` result.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import attention_shadow_recorder as recorder


class TestClassifyDecision:
    def test_not_sent_is_internal_only(self):
        assert recorder._classify_decision(False, "high") == "internal_only"

    def test_sent_urgent_is_interruptive(self):
        assert recorder._classify_decision(True, "urgent") == "interruptive_notification"

    def test_sent_critical_is_interruptive(self):
        assert recorder._classify_decision(True, "critical") == "interruptive_notification"

    def test_sent_normal_is_quiet(self):
        assert recorder._classify_decision(True, "normal") == "quiet_notification"


class TestRecordNotificationDecision:
    @pytest.mark.asyncio
    async def test_persists_outbound_intent_and_attention_item(self):
        db = MagicMock()

        insert_result = MagicMock()
        insert_result.first.return_value = ("outbound-id-123",)
        db.execute = AsyncMock(side_effect=[insert_result, MagicMock()])

        await recorder.record_notification_decision(
            db, user_id="user-1", title="Heads up", message="Something happened",
            priority="high", category="system_health", topic="topic-1",
            result={"sent": True, "reason": "sent"},
        )

        assert db.execute.await_count == 2
        first_call_params = db.execute.await_args_list[0][0][1]
        assert first_call_params["user_id"] == "user-1"
        assert first_call_params["dedupe_key"] == "topic-1"

        second_call_params = db.execute.await_args_list[1][0][1]
        assert second_call_params["outbound_intent_id"] == "outbound-id-123"
        assert second_call_params["decision"] == "quiet_notification"
        assert second_call_params["sent"] is True

    @pytest.mark.asyncio
    async def test_never_raises_on_db_failure(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=RuntimeError("db exploded"))

        # Must not raise.
        await recorder.record_notification_decision(
            db, user_id="user-1", title="t", message="m", priority="normal",
            category="general", topic=None, result={"sent": False, "reason": "dedup"},
        )

    @pytest.mark.asyncio
    async def test_unsent_notification_recorded_as_internal_only(self):
        db = MagicMock()
        insert_result = MagicMock()
        insert_result.first.return_value = ("outbound-id-456",)
        db.execute = AsyncMock(side_effect=[insert_result, MagicMock()])

        await recorder.record_notification_decision(
            db, user_id="user-1", title="t", message="m", priority="high",
            category="general", topic=None, result={"sent": False, "reason": "dedup"},
        )

        second_call_params = db.execute.await_args_list[1][0][1]
        assert second_call_params["decision"] == "internal_only"
        assert second_call_params["sent"] is False
