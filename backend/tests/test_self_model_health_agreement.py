"""
Test for Arc 2.2 (SARA_ALIVE_BUILD_PLAN) — one self-health verdict.

/api/sara/brief's self_status and /api/mind/self's health used to be computed
independently (body_state_projection vs self_model._health()) and could
disagree in the same minute. self_model._health() now reads the same
canonical projection, so this pins that down.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.contracts import BodyComponentV1, BodyStateV1, ComponentStatus
from datetime import datetime, timezone


def _projection(components):
    degraded = [c for c in components if c.status == ComponentStatus.DEGRADED]
    return BodyStateV1(
        as_of=datetime.now(timezone.utc),
        healthy=not degraded,
        components=components,
        degraded_count=len(degraded),
        confidence=1.0,
    )


class TestSelfModelReadsCanonicalProjection:
    @pytest.mark.asyncio
    async def test_healthy_projection_means_ok(self):
        from app.services.self_model import _health

        with patch(
            "app.services.body_state_projection.get_body_state_projection",
            new=AsyncMock(return_value=_projection([])),
        ):
            health = await _health(db=None, user_id="u1")

        assert health["ok"] is True
        assert health["issue_count"] == 0

    @pytest.mark.asyncio
    async def test_degraded_component_surfaces_as_issue(self):
        from app.services.self_model import _health

        components = [BodyComponentV1(
            name="task_failure:sync_emails", label="sync_emails failing",
            status=ComponentStatus.DEGRADED, impact="ConnectionError (3x)",
            severity="error", source="self_model_health",
            as_of=datetime.now(timezone.utc), confidence=1.0,
        )]
        with patch(
            "app.services.body_state_projection.get_body_state_projection",
            new=AsyncMock(return_value=_projection(components)),
        ):
            health = await _health(db=None, user_id="u1")

        assert health["ok"] is False
        assert health["issue_count"] == 1
        assert health["issues"][0]["kind"] == "task_failure"
        assert health["issues"][0]["what"] == "sync_emails failing"

    @pytest.mark.asyncio
    async def test_healthy_ok_summary(self):
        from app.services.self_model import _summarize

        assert "no unresolved" in _summarize({"ok": True, "issue_count": 0, "issues": []}).lower()

    @pytest.mark.asyncio
    async def test_degraded_summary_names_top_issue(self):
        from app.services.self_model import _summarize

        summary = _summarize({
            "ok": False, "issue_count": 2,
            "issues": [{"what": "consolidation stalled"}, {"what": "other"}],
        })
        assert "consolidation stalled" in summary
