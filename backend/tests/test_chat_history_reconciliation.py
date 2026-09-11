"""Regression for SARA_CONVERSATION_COMPETENCE_PLAN_2026_09_10 Phase 2:
audit of the rule that skipped server history whenever a client sent more
than 2 messages. That rule assumed ">2 messages" meant "the client sent
its whole conversation" — true for the normal case (the web app resends
its full local state every turn) but silently wrong on a reload/reconnect
where the client's local state is itself a partial slice of a much longer
stored conversation.
"""

from app.core.chat_helpers import resolve_should_load_db_history


class TestResolveShouldLoadDbHistory:
    def test_no_conversation_id_never_loads(self):
        assert not resolve_should_load_db_history(10, False, None)
        assert not resolve_should_load_db_history(1, False, 50)

    def test_short_client_payload_always_backfills(self):
        assert resolve_should_load_db_history(1, True, None)
        assert resolve_should_load_db_history(2, True, 0)

    def test_full_history_client_is_trusted(self):
        # Client sent 40 messages; storage roughly agrees — no reload needed.
        assert not resolve_should_load_db_history(40, True, 40)
        assert not resolve_should_load_db_history(40, True, 41)

    def test_partial_client_history_triggers_backfill(self):
        # Client sent only 4 messages after a reconnect, but 50 are stored.
        assert resolve_should_load_db_history(4, True, 50)

    def test_small_count_drift_does_not_trigger_backfill(self):
        # Slack of 5 absorbs a turn not yet flushed / an unechoed system msg.
        assert not resolve_should_load_db_history(10, True, 14)

    def test_unknown_stored_count_defers_to_message_count_only(self):
        assert not resolve_should_load_db_history(10, True, None)
