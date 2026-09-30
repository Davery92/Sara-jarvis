"""R01 review remediation round 4 (2026-09-27): "A sufficiently long reply
containing a domain noun does not prove the user saw the proposed
operation, target, parameters, and recurring scope... A denial or
unrelated discussion must not create confirmable authority."

Pure unit tests of `app/services/proposal_presentation.py` — no DB needed,
mirroring how `tool_mutation.py`'s own text-logic functions are tested.
"""
from app.services.proposal_presentation import (
    is_denial,
    presented_summary_matches_proposal,
    render_structured_summary,
)

STANDING_ORDER_ARGS = {"trigger_type": "presence", "action_type": "home_control", "entity_id": "light.porch"}


class TestRenderStructuredSummary:
    def test_renders_key_value_pairs_from_arguments(self):
        rendered = render_structured_summary("standing_order_create", STANDING_ORDER_ARGS)
        assert "light.porch" in rendered
        assert "home_control" in rendered

    def test_empty_arguments_render_nothing(self):
        assert render_structured_summary("standing_order_create", {}) == ""
        assert render_structured_summary("standing_order_create", None) == ""

    def test_internal_keys_are_skipped(self):
        rendered = render_structured_summary("standing_order_create", {"user_id": "u1", "action_type": "home_control"})
        assert "u1" not in rendered
        assert "home_control" in rendered


class TestIsDenial:
    def test_a_flat_denial_with_no_invitation_is_a_denial(self):
        assert is_denial("I can't do that without more detail.") is True
        assert is_denial("I won't set that up.") is True
        assert is_denial("I don't have enough information to do that.") is True

    def test_a_denial_that_still_invites_confirmation_is_not_a_denial(self):
        assert is_denial(
            "I won't turn that into a standing order automatically — want me to go ahead anyway?"
        ) is False
        assert is_denial(
            "I can't make it recurring without your say-so. Should I set it up as standing?"
        ) is False

    def test_a_genuine_offer_with_no_denial_phrase_is_not_a_denial(self):
        assert is_denial("I can set that up as a standing order for the porch light — want me to go ahead?") is False

    def test_empty_text_is_not_a_denial(self):
        assert is_denial("") is False
        assert is_denial(None) is False


class TestPresentedSummaryMatchesProposal:
    def test_a_genuine_offer_referencing_the_arguments_matches(self):
        assert presented_summary_matches_proposal(
            "standing_order_create", STANDING_ORDER_ARGS,
            "I can set that up as a standing order for the porch light — want me to go ahead?",
            require_recurring=True,
        ) is True

    def test_a_flat_denial_never_matches_even_if_specific(self):
        """The exact review concern: a specific-sounding reply that is
        actually a hard denial must not become confirmable authority."""
        assert presented_summary_matches_proposal(
            "standing_order_create", STANDING_ORDER_ARGS,
            "I won't set up a standing order for the porch light automatically without you confirming first.",
        ) is False

    def test_unrelated_discussion_does_not_match(self):
        assert presented_summary_matches_proposal(
            "standing_order_create", STANDING_ORDER_ARGS,
            "Sure, here's what's on your calendar for tomorrow afternoon.",
        ) is False

    def test_a_reply_mentioning_only_the_domain_but_not_the_specific_parameters_does_not_match(self):
        """The exact review finding: a domain noun alone is not enough
        when there ARE specific arguments to bind to — matching is against
        the ARGUMENT VALUES (the actual device, here), not the tool's own
        name, so "standing order" alone (with no device reference) is not
        sufficient once real parameters exist to bind to."""
        assert presented_summary_matches_proposal(
            "standing_order_create", STANDING_ORDER_ARGS,
            "I could set up a standing order for something else entirely, if you want.",
        ) is False

    def test_a_reply_about_a_completely_different_device_does_not_match(self):
        assert presented_summary_matches_proposal(
            "standing_order_create", STANDING_ORDER_ARGS,
            "I set up a reminder about your dentist appointment instead.",
        ) is False

    def test_recurring_establishing_tool_requires_recurring_framing_in_the_presented_text(self):
        """The presented text itself must frame this as standing/recurring
        — not merely the original user message (checked separately,
        elsewhere, against source_message)."""
        assert presented_summary_matches_proposal(
            "standing_order_create", STANDING_ORDER_ARGS,
            "I can turn the porch light on for you right now.",
            require_recurring=True,
        ) is False

    def test_no_arguments_falls_back_to_domain_level_check(self):
        assert presented_summary_matches_proposal(
            "standing_order_create", {},
            "I can set that up as a standing order — want me to go ahead?",
            require_recurring=True,
        ) is True
        assert presented_summary_matches_proposal(
            "standing_order_create", {},
            "Sure, here's what's on your calendar for tomorrow afternoon.",
        ) is False
