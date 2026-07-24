"""
Tests for the SINGULAR_SARA_MASTER_PLAN §C9 attention shadow recorder:
decision classification, persistence shape, and — critically — that a
recorder failure can never affect the real `send_notification()` result.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import attention_shadow_recorder as recorder
from app.services import unified_notification


class TestCheckRecentDuplicate:
    @pytest.mark.asyncio
    async def test_true_when_matching_row_found(self):
        db = MagicMock()
        result = MagicMock()
        result.first.return_value = (1,)
        db.execute = AsyncMock(return_value=result)

        found = await recorder.check_recent_duplicate(db, "user-1", "general", "Same message")
        assert found is True

    @pytest.mark.asyncio
    async def test_false_when_no_matching_row(self):
        db = MagicMock()
        result = MagicMock()
        result.first.return_value = None
        db.execute = AsyncMock(return_value=result)

        found = await recorder.check_recent_duplicate(db, "user-1", "general", "New message")
        assert found is False

    @pytest.mark.asyncio
    async def test_fails_open_on_db_error(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=RuntimeError("db exploded"))

        # Must not raise, and must fail toward "not a duplicate" — a broken
        # check must never itself block a legitimate send.
        found = await recorder.check_recent_duplicate(db, "user-1", "general", "Whatever")
        assert found is False


class TestClassifyDecision:
    def test_not_sent_no_attention_item_is_internal_only(self):
        assert recorder._classify_decision({"sent": False}, "high") == "internal_only"

    def test_sent_urgent_is_interruptive(self):
        assert recorder._classify_decision({"sent": True}, "urgent") == "interruptive_notification"

    def test_sent_critical_is_interruptive(self):
        assert recorder._classify_decision({"sent": True}, "critical") == "interruptive_notification"

    def test_sent_normal_is_quiet(self):
        assert recorder._classify_decision({"sent": True}, "normal") == "quiet_notification"

    def test_not_sent_but_real_attention_item_exists_is_add_to_today(self):
        """The live attention queue (route_through_attention_queue) created a
        real autonomy_attention_item row and decided not to push (learned
        buzz decision) — that's visible in Today, not truly silent."""
        result = {"sent": False, "attention_item_id": "attn-123",
                  "reason": "Low/normal priority routed to attention queue (buzz decision: inbox-only)"}
        assert recorder._classify_decision(result, "normal") == "add_to_today"

    def test_not_sent_attention_cooldown_is_internal_only(self):
        """attention_cooldown returns before an item is ever created — no
        attention_item_id — so it's genuinely internal_only, not add_to_today."""
        result = {"sent": False, "reason": "attention_cooldown"}
        assert recorder._classify_decision(result, "normal") == "internal_only"

    def test_sent_takes_priority_over_attention_item_presence(self):
        """High priority pushed AND has an attention_item_id (routed_through_
        attention path) — still classified by what actually reached David."""
        result = {"sent": True, "attention_item_id": "attn-456"}
        assert recorder._classify_decision(result, "urgent") == "interruptive_notification"


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

    @pytest.mark.asyncio
    async def test_real_attention_item_id_recorded_as_evidence_in_why_now(self):
        db = MagicMock()
        insert_result = MagicMock()
        insert_result.first.return_value = ("outbound-id-789",)
        db.execute = AsyncMock(side_effect=[insert_result, MagicMock()])

        await recorder.record_notification_decision(
            db, user_id="user-1", title="t", message="m", priority="normal",
            category="general", topic=None,
            result={"sent": False, "attention_item_id": "attn-999",
                    "reason": "Low/normal priority routed to attention queue (buzz decision: inbox-only)"},
        )

        first_call_params = db.execute.await_args_list[0][0][1]
        assert "attn-999" in first_call_params["why_now"]
        second_call_params = db.execute.await_args_list[1][0][1]
        assert second_call_params["decision"] == "add_to_today"


class TestSendNotificationDedupGate:
    """The real §C9 cutover: send_notification()'s outer wrapper gates on
    the content-dedup check when SINGULAR_ATTENTION is on."""

    @pytest.mark.asyncio
    async def test_flag_on_and_duplicate_skips_real_send(self):
        db = MagicMock()
        db.execute = AsyncMock()

        mock_impl = AsyncMock()

        with patch("app.core.feature_flags.is_enabled", return_value=True), \
             patch("app.services.attention_shadow_recorder.check_recent_duplicate",
                   new=AsyncMock(return_value=True)), \
             patch("app.services.unified_notification._send_notification_impl", mock_impl):

            result = await unified_notification.send_notification(
                user_id="user-1", title="t", message="Duplicate content", db=db,
            )

        assert result == {"sent": False, "reason": "attention_market_dedup"}
        mock_impl.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_flag_on_and_not_duplicate_proceeds_normally(self):
        db = MagicMock()
        db.execute = AsyncMock()

        mock_impl = AsyncMock(return_value={"sent": True, "reason": "sent"})

        with patch("app.core.feature_flags.is_enabled", return_value=True), \
             patch("app.services.attention_shadow_recorder.check_recent_duplicate",
                   new=AsyncMock(return_value=False)), \
             patch("app.services.unified_notification._send_notification_impl", mock_impl), \
             patch("app.services.attention_shadow_recorder.record_notification_decision", new=AsyncMock()):

            result = await unified_notification.send_notification(
                user_id="user-1", title="t", message="Fresh content", db=db,
            )

        mock_impl.assert_awaited_once()
        assert result["sent"] is True

    @pytest.mark.asyncio
    async def test_flag_off_skips_dedup_check_entirely(self):
        db = MagicMock()
        db.execute = AsyncMock()

        mock_impl = AsyncMock(return_value={"sent": True, "reason": "sent"})
        mock_dupe_check = AsyncMock(return_value=True)  # would suppress if it ran

        with patch("app.core.feature_flags.is_enabled", return_value=False), \
             patch("app.services.attention_shadow_recorder.check_recent_duplicate", mock_dupe_check), \
             patch("app.services.unified_notification._send_notification_impl", mock_impl), \
             patch("app.services.attention_shadow_recorder.record_notification_decision", new=AsyncMock()):

            result = await unified_notification.send_notification(
                user_id="user-1", title="t", message="Whatever", db=db,
            )

        mock_dupe_check.assert_not_awaited()
        mock_impl.assert_awaited_once()
        assert result["sent"] is True

    @pytest.mark.asyncio
    async def test_bypass_attention_skips_the_gate_to_avoid_self_dedup(self):
        """route_through_attention_queue's internal delivery call
        (_bypass_attention=True) must never be re-gated by this — it's the
        attention market's own decision already being executed."""
        db = MagicMock()
        db.execute = AsyncMock()

        mock_impl = AsyncMock(return_value={"sent": True, "reason": "sent"})
        mock_dupe_check = AsyncMock(return_value=True)

        with patch("app.core.feature_flags.is_enabled", return_value=True), \
             patch("app.services.attention_shadow_recorder.check_recent_duplicate", mock_dupe_check), \
             patch("app.services.unified_notification._send_notification_impl", mock_impl), \
             patch("app.services.attention_shadow_recorder.record_notification_decision", new=AsyncMock()):

            result = await unified_notification.send_notification(
                user_id="user-1", title="t", message="Whatever", db=db, _bypass_attention=True,
            )

        mock_dupe_check.assert_not_awaited()
        mock_impl.assert_awaited_once()
        assert result["sent"] is True
