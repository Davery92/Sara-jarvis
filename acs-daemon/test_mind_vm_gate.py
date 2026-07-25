"""Unit tests for the VM-tool interest-approval gate (mind.py).

SARA_PROACTIVENESS critique 2026-07-25 §4: the original gate checked "does
ANY interest have status approved/active" — meaning approving one proposal
silently unlocked provision_container/exec_in_container for every OTHER
interest too. These tests lock in the fix: the gate must resolve the
SPECIFIC interest_id a call claims to be doing work for and validate that
one's status, not just presence of some approved interest anywhere.

Pure sync tests, no daemon/network dependencies — run with plain `pytest`
from this directory.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mind import Mind  # noqa: E402

APPROVED = {"id": "aaaa1111-0000-0000-0000-000000000000", "display_name": "Approved thing", "status": "approved"}
ACTIVE = {"id": "bbbb2222-0000-0000-0000-000000000000", "display_name": "Active thing", "status": "active"}
NOTICED = {"id": "cccc3333-0000-0000-0000-000000000000", "display_name": "Just noticed", "status": "noticed"}
REJECTED = {"id": "dddd4444-0000-0000-0000-000000000000", "display_name": "Rejected thing", "status": "rejected"}

INTERESTS = [APPROVED, ACTIVE, NOTICED, REJECTED]


class TestResolveInterest:
    def test_resolves_by_short_id(self):
        found = Mind._resolve_interest("aaaa1111", INTERESTS)
        assert found is APPROVED

    def test_resolves_by_full_id(self):
        found = Mind._resolve_interest(ACTIVE["id"], INTERESTS)
        assert found is ACTIVE

    def test_none_for_unknown_id(self):
        assert Mind._resolve_interest("ffffffff", INTERESTS) is None

    def test_none_for_too_short_id(self):
        assert Mind._resolve_interest("aaa", INTERESTS) is None

    def test_none_for_empty(self):
        assert Mind._resolve_interest("", INTERESTS) is None


class TestApprovedInterestForCall:
    def test_missing_interest_id_is_blocked(self):
        interest, error = Mind._approved_interest_for_call({}, INTERESTS)
        assert interest is None
        assert "missing interest_id" in error

    def test_approved_interest_passes(self):
        interest, error = Mind._approved_interest_for_call(
            {"interest_id": "aaaa1111"}, INTERESTS,
        )
        assert error is None
        assert interest is APPROVED

    def test_active_interest_passes(self):
        interest, error = Mind._approved_interest_for_call(
            {"interest_id": "bbbb2222"}, INTERESTS,
        )
        assert error is None
        assert interest is ACTIVE

    def test_noticed_interest_is_blocked(self):
        """Regression: a real interest that simply hasn't been approved yet
        must still block, even though it resolves fine."""
        interest, error = Mind._approved_interest_for_call(
            {"interest_id": "cccc3333"}, INTERESTS,
        )
        assert interest is None
        assert "not approved/active" in error

    def test_unrelated_approved_interest_does_not_unlock_this_one(self):
        """The core regression this fix closes: calling with a NOTICED
        interest_id must NOT pass just because some OTHER interest
        (APPROVED) exists in the list."""
        interest, error = Mind._approved_interest_for_call(
            {"interest_id": "cccc3333"}, INTERESTS,
        )
        assert interest is None
        assert error is not None

    def test_unknown_interest_id_is_blocked(self):
        interest, error = Mind._approved_interest_for_call(
            {"interest_id": "ffffffff"}, INTERESTS,
        )
        assert interest is None
        assert "not found" in error

    def test_rejected_interest_is_blocked(self):
        interest, error = Mind._approved_interest_for_call(
            {"interest_id": "dddd4444"}, INTERESTS,
        )
        assert interest is None
        assert "not approved/active" in error

    def test_no_interests_at_all_is_blocked(self):
        interest, error = Mind._approved_interest_for_call(
            {"interest_id": "aaaa1111"}, [],
        )
        assert interest is None
        assert "not found" in error

    def test_none_interests_is_blocked(self):
        interest, error = Mind._approved_interest_for_call(
            {"interest_id": "aaaa1111"}, None,
        )
        assert interest is None
        assert "not found" in error
