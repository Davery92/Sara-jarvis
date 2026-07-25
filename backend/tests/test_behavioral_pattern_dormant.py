"""
Tests for the P4 home-pattern no-re-escalate-ignored-proposal fix
(app.services.behavioral_pattern_service.BehavioralPatternService).

SARA_PROACTIVENESS_AUDIT_AND_PLAN_2026_07_25 §5 "home patterns": an
explicit rejection used to only count as 1 of 3 strikes, so a proposal
David had already said no to kept getting re-suggested (up to 3 times, each
24h apart) before finally going dormant. MAX_REJECTIONS_BEFORE_DORMANT is
now 1 — a single "no" is a decision, not the start of a negotiation.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.services.behavioral_pattern_service import BehavioralPatternService


class TestMaxRejectionsConstant:
    def test_max_rejections_before_dormant_is_one(self):
        assert BehavioralPatternService.MAX_REJECTIONS_BEFORE_DORMANT == 1


def _mock_db(times_rejected_before: int):
    db = MagicMock()
    fetch_result = MagicMock()
    fetch_result.times_rejected = times_rejected_before
    select_result = MagicMock()
    select_result.fetchone.return_value = fetch_result
    # First execute(): suggestion_log UPDATE, second: SELECT times_rejected,
    # third: behavioral_pattern UPDATE.
    db.execute = MagicMock(side_effect=[MagicMock(), select_result, MagicMock()])
    db.commit = MagicMock()
    return db


class TestRecordResponseRejection:
    @pytest.mark.asyncio
    async def test_first_rejection_goes_dormant_immediately(self):
        """The core fix: a single 'no' (0 -> 1 rejections) must set status
        to dormant, not 'active' pending two more strikes."""
        service = BehavioralPatternService()
        db = _mock_db(times_rejected_before=0)

        await service.record_response(db, pattern_id="pat-1", accepted=False,
                                        user_response="not interested")

        update_call = db.execute.call_args_list[2]
        params = update_call.args[1]
        assert params["rejections"] == 1
        assert params["status"] == "dormant"

    @pytest.mark.asyncio
    async def test_acceptance_never_touches_rejection_count(self):
        service = BehavioralPatternService()
        db = MagicMock()
        db.execute = MagicMock(side_effect=[MagicMock(), MagicMock()])
        db.commit = MagicMock()

        await service.record_response(db, pattern_id="pat-2", accepted=True)

        accept_call = db.execute.call_args_list[1]
        assert "status = 'confirmed'" in str(accept_call.args[0])
