"""
Regression test for a real bug found in the Arc 1.5 write-freeze audit
(work-order item 4, 2026-07-30): MorningProactiveService._send_notification()
returned False when MOUTH_ONLY_MORNING_PROACTIVE is on, and the caller only
calls behavioral_pattern_service.record_suggestion() `if success:` — so with
the flag on, the accept/reject learning feedback loop silently stopped
recording suggestions entirely. The say_candidate dual-write happens
unconditionally right after this call regardless of what it returns, so
"success" must mean "the mouth pipeline will handle delivery."
"""
from unittest.mock import patch

import pytest

from app.services.morning_proactive_service import MorningProactiveService


@pytest.fixture
def service():
    return MorningProactiveService()


class TestMouthOnlyReturnValue:
    @pytest.mark.asyncio
    async def test_mouth_only_on_returns_true_not_false(self, service):
        """The actual regression: this used to return False, silently
        breaking record_suggestion's `if success:` gate."""
        with patch("app.core.feature_flags.is_enabled", return_value=True):
            result = await service._send_notification(
                db=None, user_id="user-1",
                message={"title": "t", "body": "b"},
                pattern={"id": "p1"},
            )
        assert result is True
