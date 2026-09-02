"""Ground-truth Phase 4: one entity, one message, one mouth.

Deliberation used to call `send_notification` directly, beside the Mind V2
judge→compose→review→deliver pipeline, and deduped on a hash of title+message. So
five re-wordings of one Laura Weippert concern each looked new and each went out
— and the prompt told Sara that proposing nothing "is a FAILURE, not restraint".
"""
from __future__ import annotations

import pathlib
import re

import pytest

from app.services.deliberation import NotificationProposal
from app.services.deliberation_gate import entity_dedupe_key

GATE = pathlib.Path("app/services/deliberation_gate.py")
PROMPT = pathlib.Path("app/services/deliberation_prompt.py")


class TestOnlyOneMouth:
    def test_the_gate_no_longer_sends_anything_itself(self):
        """The plan's acceptance check, as a test: grep must find nothing."""
        source = GATE.read_text()
        calls = [
            line for line in source.splitlines()
            if re.search(r"(?<!_)send_notification\s*\(", line)
        ]
        assert not calls, "deliberation_gate still sends directly:\n" + "\n".join(calls)

    def test_every_gate_output_path_goes_through_the_candidate_queue(self):
        source = GATE.read_text()
        assert "_queue_candidate" in source
        assert source.count("await _queue_candidate(") >= 3, (
            "email_draft, commitment_nudge and task proposals must all queue"
        )


class TestEntityKeyedDedup:
    def test_the_entity_is_the_key_when_the_proposal_names_one(self):
        proposal = NotificationProposal(
            title="Laura is waiting", message="She asked to reschedule.",
            entity_ref="entity:75ec1d5b-98cb-487b-bab6-af2af70ab6a1",
        )
        assert entity_dedupe_key(proposal, "abc123") == \
            "entity:75ec1d5b-98cb-487b-bab6-af2af70ab6a1"

    def test_a_bare_id_is_namespaced(self):
        proposal = NotificationProposal(title="t", message="m", entity_ref="75ec1d5b")
        assert entity_dedupe_key(proposal, "abc123") == "entity:75ec1d5b"

    def test_rewording_the_same_entity_produces_the_same_key(self):
        """The whole point. Two different phrasings, one entity, one key."""
        first = NotificationProposal(
            title="Laura wants to reschedule", message="She emailed this morning.",
            entity_ref="entity:75ec1d5b")
        second = NotificationProposal(
            title="Reminder about Laura's call", message="Still waiting on your reply.",
            entity_ref="entity:75ec1d5b")
        assert entity_dedupe_key(first, "hash-one") == entity_dedupe_key(second, "hash-two")

    def test_an_entityless_proposal_still_gets_a_key(self):
        proposal = NotificationProposal(title="t", message="m", category="home")
        assert entity_dedupe_key(proposal, "abc123") == "home:abc123"


class TestSilenceIsNotFailure:
    def test_the_failure_paragraphs_are_gone(self):
        source = PROMPT.read_text()
        assert "FAILURE, not" not in source
        assert "is a FAILURE" not in source
        assert "failure to catch" not in source

    def test_the_prompt_points_at_the_entity_ledger_instead(self):
        source = PROMPT.read_text()
        assert "Entity Ledger" in source
        assert "no live candidate and no delivered message today" in source

    def test_proposals_must_name_their_entity(self):
        source = PROMPT.read_text()
        assert '"entity_ref"' in source

    def test_the_proposal_dataclass_carries_it(self):
        assert NotificationProposal(title="t", message="m").entity_ref == ""


class TestEntityLedger:
    def test_the_ledger_renders_one_line_per_entity(self):
        """It degrades to empty rather than raising — a broken ledger must not
        take the deliberation turn down with it."""
        from app.services.deliberation_prompt import _format_entity_ledger

        rendered = _format_entity_ledger()
        assert isinstance(rendered, str)
        if rendered:
            assert "candidate_live:" in rendered
            assert "last_told:" in rendered
            # Invariant 4: times in the ledger are rendered, never raw.
            assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:", rendered)


class TestCandidateDedupIsStructural:
    def test_the_guard_is_not_scoped_to_one_source(self):
        """Deliberation, the appraiser and calendar_prep each queuing their own
        copy of one concern used to produce three deliveries."""
        source = pathlib.Path("app/services/say_candidate.py").read_text()
        guard = source.split("if dedupe_key:")[1].split("topics = list")[0]
        assert "AND source = :source" not in guard
        assert "notification_log" in guard, "must also check what was already sent today"
