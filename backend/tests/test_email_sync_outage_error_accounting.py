"""Email sync error accounting (Sara repair plan R12, evidence
P03_SOURCE_UNAVAILABLE_MISREPORTED_AS_ZERO_ERRORS).

Confirmed mechanism: `MSGraphService.get_emails` caught every exception
internally (including a genuine connection failure) and returned `[]` — the
real error was logged, but never propagated. Its two real callers in
`app/tasks/email_sync.py` (inbound sync, sent-items sync) each wrap the call
in `except Exception: total_errors += 1; continue`, so as long as
`get_emails` swallowed the exception, a real outage and a genuinely empty
inbox produced an IDENTICAL task result: `{"emails_synced": 0, "errors": 0}`
— indistinguishable to any caller, including chat tools that report on sync
health.
"""
import pytest


class TestGetEmailsPropagatesRealFailures:
    @pytest.mark.asyncio
    async def test_a_real_api_failure_raises_instead_of_returning_empty(self, monkeypatch):
        from app.services.msgraph_service import MSGraphService

        service = MSGraphService.__new__(MSGraphService)

        async def _fake_api_request(*a, **kw):
            raise RuntimeError("Temporary failure in name resolution")

        monkeypatch.setattr(service, "_api_request", _fake_api_request)

        with pytest.raises(RuntimeError):
            await service.get_emails("davery@riskninja.ai", since=None, top=50)

    @pytest.mark.asyncio
    async def test_a_genuinely_empty_inbox_still_returns_an_empty_list_not_an_error(self, monkeypatch):
        """The fix must not turn a real empty-but-reachable inbox into a
        false error — only an actual fetch failure should raise."""
        from app.services.msgraph_service import MSGraphService

        service = MSGraphService.__new__(MSGraphService)

        async def _fake_api_request(*a, **kw):
            return {"value": []}

        monkeypatch.setattr(service, "_api_request", _fake_api_request)

        result = await service.get_emails("davery@riskninja.ai", since=None, top=50)
        assert result == []


class TestSyncTaskCountsARealOutageAsAnError:
    @pytest.mark.asyncio
    async def test_sync_emails_async_reports_a_nonzero_error_count_on_outage(self, monkeypatch):
        """End-to-end against the real (disposable) database: with the
        source genuinely unreachable, the task's own returned summary must
        say so — not report the exact same shape as a quiet inbox."""
        import app.tasks.email_sync as sync_mod
        import app.services.msgraph_service as msgraph_mod
        from app.core.config import settings

        class _FailingMsgraph:
            async def get_emails(self, mailbox, since=None, top=50, folder="inbox"):
                raise RuntimeError("Temporary failure in name resolution")

            async def get_unread_ids(self, mailbox, folder="inbox"):
                return None  # documented "unknown" sentinel — unaffected by this fix

        # get_msgraph_service is imported LOCALLY inside _sync_emails_async
        # (`from app.services.msgraph_service import get_msgraph_service`),
        # so the source module attribute is what must be patched.
        monkeypatch.setattr(msgraph_mod, "get_msgraph_service", lambda: _FailingMsgraph())
        monkeypatch.setattr(settings, "msgraph_mailboxes", ["outage-test@example.com"])

        result = await sync_mod._sync_emails_async()

        assert result["emails_synced"] == 0
        assert result["errors"] >= 1, (
            "a real source outage must not be reported identically to a "
            "genuinely empty inbox (errors stayed 0)"
        )
