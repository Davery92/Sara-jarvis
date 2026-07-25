"""
Tests for the P2/P8.1 quiet-expiry sweep (app.tasks.attention).

SARA_PROACTIVENESS_AUDIT_AND_PLAN_2026_07_25 §5.3: the old
escalate_unread_attention force-pushed unread items after 24h at bumped
priority. It's deleted; these tests lock in that the replacement
(expire_stale_attention) only ever archives rows — it must never call
send_notification / any push path — and that the old task name still
resolves harmlessly by delegating to the new one.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.tasks import attention


def _mock_session(confirmation_rows=None, expired_rows=None):
    db = MagicMock()
    confirmation_result = MagicMock()
    confirmation_result.fetchall.return_value = confirmation_rows or []
    expired_result = MagicMock()
    expired_result.fetchall.return_value = expired_rows or []
    # First execute() call is the confirmation sweep, second is the stale sweep.
    db.execute.side_effect = [confirmation_result, expired_result]
    return db


class TestExpireStaleAttentionAsync:
    @pytest.mark.asyncio
    async def test_never_calls_send_notification(self):
        """The whole point of the fix: expiry must be silent."""
        db = _mock_session(expired_rows=[(1,), (2,)])
        with patch("app.tasks.attention.SessionLocal", return_value=db), \
             patch("app.services.unified_notification.send_notification") as mock_send:
            await attention._expire_stale_attention_async()
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_archives_confirmations_and_stale_items(self):
        db = _mock_session(confirmation_rows=[(1,)], expired_rows=[(2,), (3,), (4,)])
        with patch("app.tasks.attention.SessionLocal", return_value=db):
            result = await attention._expire_stale_attention_async()

        assert result["archived_confirmations"] == 1
        assert result["expired"] == 3
        assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_sql_never_sets_priority_or_high(self):
        """Regression guard against re-introducing the old escalation
        behavior: the UPDATE statements must set status='archived', never
        touch priority."""
        db = _mock_session()
        with patch("app.tasks.attention.SessionLocal", return_value=db):
            await attention._expire_stale_attention_async()

        for call in db.execute.call_args_list:
            sql = str(call.args[0])
            assert "priority" not in sql.lower()
            assert "'archived'" in sql or "status = 'archived'" in sql

    @pytest.mark.asyncio
    async def test_expired_items_tagged_for_observability(self):
        db = _mock_session(expired_rows=[(1,)])
        with patch("app.tasks.attention.SessionLocal", return_value=db):
            await attention._expire_stale_attention_async()

        stale_sweep_sql = str(db.execute.call_args_list[1].args[0])
        assert "expired_stale" in stale_sweep_sql

    @pytest.mark.asyncio
    async def test_commits_only_when_rows_affected(self):
        db = _mock_session()  # no rows either sweep
        with patch("app.tasks.attention.SessionLocal", return_value=db):
            await attention._expire_stale_attention_async()
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_closes_session_even_on_error(self):
        db = MagicMock()
        db.execute.side_effect = RuntimeError("db exploded")
        with patch("app.tasks.attention.SessionLocal", return_value=db):
            with pytest.raises(RuntimeError):
                await attention._expire_stale_attention_async()
        db.close.assert_called_once()


class TestDeprecatedAliasDelegates:
    def test_escalate_unread_attention_delegates_to_expire(self):
        with patch("app.tasks.attention.expire_stale_attention",
                   return_value={"expired": 0}) as mock_expire:
            result = attention.escalate_unread_attention()
        mock_expire.assert_called_once()
        assert result == {"expired": 0}
