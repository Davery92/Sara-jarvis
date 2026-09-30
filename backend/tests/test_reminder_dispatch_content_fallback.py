"""`reminder.content` does not exist on the Reminder model (Sara repair plan
R06, evidence REMINDER_DISPATCH_CRASH_NO_DESCRIPTION). Only `title` and
`description` exist. `description or reminder.content or "..."` evaluates
`reminder.content` whenever `description` is falsy (empty string, the
column's own default, or None) — which is most reminders — and raises
AttributeError, crashing dispatch instead of falling back to the title.

Reproduces against the real dispatch/alert call sites directly (not a
reimplementation of the fallback logic), for every falsy-description shape
the column can actually hold.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _reminder(title="Call the bank", description=""):
    # A plain object with exactly Reminder's real columns — no `content`
    # attribute at all, so `reminder.content` raises AttributeError just
    # like the real ORM instance would for a reminder with no content.
    return SimpleNamespace(
        id="r1", user_id="user-a", title=title, description=description,
        event_id=None,
    )


class TestDispatchReminderContentFallback:
    @pytest.mark.asyncio
    async def test_empty_description_does_not_crash_and_falls_back_to_title(self, monkeypatch):
        from app.tasks import inproc_schedulers as mod

        sent = {}

        async def _fake_send_push_to_user(user_id, title, body, notification_data=None):
            sent["title"] = title
            sent["body"] = body

        monkeypatch.setattr("app.routes.push_tokens.send_push_to_user", _fake_send_push_to_user)

        await mod._dispatch_reminder(_reminder(title="Call the bank", description=""))

        assert sent["body"] == "Call the bank"

    @pytest.mark.asyncio
    async def test_none_description_does_not_crash(self, monkeypatch):
        from app.tasks import inproc_schedulers as mod

        sent = {}

        async def _fake_send_push_to_user(user_id, title, body, notification_data=None):
            sent["body"] = body

        monkeypatch.setattr("app.routes.push_tokens.send_push_to_user", _fake_send_push_to_user)

        await mod._dispatch_reminder(_reminder(title="Take out trash", description=None))

        assert sent["body"] == "Take out trash"

    @pytest.mark.asyncio
    async def test_real_description_is_preferred_over_title(self, monkeypatch):
        from app.tasks import inproc_schedulers as mod

        sent = {}

        async def _fake_send_push_to_user(user_id, title, body, notification_data=None):
            sent["body"] = body

        monkeypatch.setattr("app.routes.push_tokens.send_push_to_user", _fake_send_push_to_user)

        await mod._dispatch_reminder(_reminder(title="Call the bank", description="Ask about the wire transfer"))

        assert sent["body"] == "Ask about the wire transfer"
