"""R01 review remediation round 4 (2026-09-27): bind the requested
operation to a resolved, owner-scoped target, not domain vocabulary.

Confirmed gaps in round 3's `tool_domain_evidenced` (still real, still
present as the fallback for unresolved domains — see the last test class
here): "Cancel the dentist reminder" evidenced the reminders DOMAIN, which
authorized cancelling ANY reminder the model called, including a wrong
one; and a domain noun appearing ANYWHERE in the message (e.g. "show my
reminders" inside "show my reminders, but cancel that research task")
could authorize an unrelated call in that domain even though the message
never actually asked to cancel a reminder.

`target_authorization.py` resolves the tool call's own argument to the
REAL, owner-scoped row (a lookup scoped by `user_id`, so a wrong owner
never matches), then checks whether the message references THAT
SPECIFIC row's own identifying words — not the domain in general. Runs
against the real disposable Postgres throughout: the owner-scoping and
resolution are properties of a real query, not something a mock should
stand in for.
"""
import uuid

import pytest
from sqlalchemy import text as sa_text

from app.db.base import SessionLocal
from app.services.target_authorization import (
    find_target_unauthorized_mutations,
    target_reference_evidenced,
)


def _tc(name, call_id, args):
    import json
    return {"id": call_id, "function": {"name": name, "arguments": json.dumps(args)}}


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def two_users(db):
    uid_a = str(uuid.uuid4())
    uid_b = str(uuid.uuid4())
    for uid in (uid_a, uid_b):
        db.execute(sa_text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :email, 'x', NOW())
        """), {"id": uid, "email": f"{uid}@test.local"})
    db.commit()
    yield uid_a, uid_b
    for uid in (uid_a, uid_b):
        db.execute(sa_text("DELETE FROM reminder WHERE user_id = :id"), {"id": uid})
        db.execute(sa_text("DELETE FROM research_plan WHERE user_id = :id"), {"id": uid})
        db.execute(sa_text("DELETE FROM app_user WHERE id = :id"), {"id": uid})
    db.commit()


def _make_reminder(db, user_id, title, description=""):
    from app.models.reminder import Reminder
    from datetime import datetime, timezone
    r = Reminder(id=str(uuid.uuid4()), user_id=user_id, title=title, description=description,
                 reminder_time=datetime.now(timezone.utc), is_completed=False)
    db.add(r)
    db.commit()
    return r.id


def _make_research_plan(db, user_id, title, objective=""):
    from app.models.research_plan import ResearchPlan
    p = ResearchPlan(id=str(uuid.uuid4()), user_id=user_id, title=title, objective=objective, steps=[])
    db.add(p)
    db.commit()
    return p.id


class TestSameDomainWrongTarget:
    """The exact review finding 2 scenario: 'Cancel the dentist reminder'
    naming ONE specific reminder must not authorize cancelling ANOTHER."""

    def test_the_correct_target_is_authorized(self, db, two_users):
        uid_a, _ = two_users
        dentist_id = _make_reminder(db, uid_a, "Dentist appointment", "Root canal follow-up")
        assert target_reference_evidenced(
            db, uid_a, "reminders_cancel", {"reminder_id": dentist_id},
            "Cancel the dentist reminder",
        ) is True

    def test_a_different_reminder_with_no_shared_words_is_blocked(self, db, two_users):
        uid_a, _ = two_users
        _make_reminder(db, uid_a, "Dentist appointment", "Root canal follow-up")
        rent_id = _make_reminder(db, uid_a, "Pay rent", "Due the 1st")
        # The model mis-resolved "the dentist reminder" to the WRONG
        # reminder (rent_id) — the message never mentions rent/paying.
        assert target_reference_evidenced(
            db, uid_a, "reminders_cancel", {"reminder_id": rent_id},
            "Cancel the dentist reminder",
        ) is False

    def test_find_target_unauthorized_mutations_blocks_the_wrong_target_call(self, db, two_users):
        uid_a, _ = two_users
        _make_reminder(db, uid_a, "Dentist appointment")
        rent_id = _make_reminder(db, uid_a, "Pay rent")
        calls = [_tc("reminders_cancel", "c1", {"reminder_id": rent_id})]
        blocked = find_target_unauthorized_mutations(db, uid_a, calls, "Cancel the dentist reminder")
        assert blocked == ["c1"]


class TestDomainWordsElsewhereInMessage:
    """The exact review finding 2 second scenario: 'show my reminders, but
    cancel that research task' legitimately authorizes cancelling the
    research plan, but must NOT authorize cancelling an unrelated
    reminder just because 'reminders' also appears in the message."""

    def test_reminders_cancel_is_blocked_despite_the_word_reminders_appearing(self, db, two_users):
        uid_a, _ = two_users
        dentist_id = _make_reminder(db, uid_a, "Dentist appointment")
        message = "Show my reminders, but cancel that research task."
        assert target_reference_evidenced(
            db, uid_a, "reminders_cancel", {"reminder_id": dentist_id}, message,
        ) is False

    def test_cancel_research_plan_is_authorized_for_the_named_task(self, db, two_users):
        uid_a, _ = two_users
        plan_id = _make_research_plan(db, uid_a, "Quarterly widget research", "Investigate widget market trends")
        message = "Show my reminders, but cancel that research task."
        assert target_reference_evidenced(
            db, uid_a, "cancel_research_plan", {"plan_id": plan_id}, message,
        ) is True

    def test_find_target_unauthorized_mutations_authorizes_one_blocks_the_other(self, db, two_users):
        uid_a, _ = two_users
        dentist_id = _make_reminder(db, uid_a, "Dentist appointment")
        plan_id = _make_research_plan(db, uid_a, "Quarterly widget research", "Investigate widget market trends")
        message = "Show my reminders, but cancel that research task."
        calls = [
            _tc("reminders_cancel", "wrong", {"reminder_id": dentist_id}),
            _tc("cancel_research_plan", "right", {"plan_id": plan_id}),
        ]
        blocked = find_target_unauthorized_mutations(db, uid_a, calls, message)
        assert blocked == ["wrong"]


class TestOwnerScoping:
    def test_a_target_belonging_to_a_different_user_is_never_authorized(self, db, two_users):
        uid_a, uid_b = two_users
        # Reminder belongs to user B; user A's call names it anyway
        # (a cross-tenant id leak or a forged argument).
        other_id = _make_reminder(db, uid_b, "Dentist appointment")
        assert target_reference_evidenced(
            db, uid_a, "reminders_cancel", {"reminder_id": other_id},
            "Cancel the dentist reminder",
        ) is False

    def test_a_nonexistent_target_id_falls_back_to_domain_evidence_not_an_unconditional_block(self, db, two_users):
        """A hallucinated/malformed id (or a fabricated id with no backing
        row at all — the realistic shape of a chat-loop-mechanics test)
        is NOT the same risk as a real cross-tenant reference: blocking it
        outright would manufacture false refusals for legitimately-
        authorized requests whose specific target just can't be resolved.
        The domain-level check still applies underneath."""
        uid_a, _ = two_users
        assert target_reference_evidenced(
            db, uid_a, "reminders_cancel", {"reminder_id": "does-not-exist"},
            "Cancel the dentist reminder",
        ) is True  # "reminder" is domain evidence — the fallback authorizes it
        assert target_reference_evidenced(
            db, uid_a, "reminders_cancel", {"reminder_id": "does-not-exist"},
            "What's the weather like today?",
        ) is False  # no domain evidence either — still correctly blocked

    def test_a_cross_tenant_reference_is_always_blocked_even_with_domain_evidence(self, db, two_users):
        """The real security case, distinguished from the above: an id
        that DOES exist, but belongs to someone else. Domain evidence
        (even a perfect one) must never override this."""
        uid_a, uid_b = two_users
        other_id = _make_reminder(db, uid_b, "Dentist appointment")
        assert target_reference_evidenced(
            db, uid_a, "reminders_cancel", {"reminder_id": other_id},
            "Cancel the dentist reminder",
        ) is False


class TestResearchPlanPrefixLookup:
    def test_an_8_char_prefix_resolves_the_same_as_the_full_id(self, db, two_users):
        uid_a, _ = two_users
        plan_id = _make_research_plan(db, uid_a, "Quarterly widget research", "Investigate widget trends")
        prefix = plan_id[:8]
        assert target_reference_evidenced(
            db, uid_a, "cancel_research_plan", {"plan_id": prefix},
            "cancel that widget research",
        ) is True


class TestUnresolvedDomainFallsBackToDomainVocabulary:
    """Domains without a real resolver (e.g. threads) keep round 3's
    domain-vocabulary behavior — a documented, known remaining gap, not a
    silent one."""

    def test_resolve_thread_falls_back_to_domain_evidence(self, db, two_users):
        uid_a, _ = two_users
        assert target_reference_evidenced(
            db, uid_a, "resolve_thread", {"thread_id": "anything"},
            "Close that thread, it's handled.",
        ) is True
        assert target_reference_evidenced(
            db, uid_a, "resolve_thread", {"thread_id": "anything"},
            "What's the weather like?",
        ) is False


class TestFailsClosedOnResolverError:
    def test_a_resolver_exception_blocks_rather_than_authorizes(self, db, two_users):
        uid_a, _ = two_users

        class _BrokenSession:
            def query(self, *a, **kw):
                raise RuntimeError("simulated DB failure")

        assert target_reference_evidenced(
            _BrokenSession(), uid_a, "reminders_cancel", {"reminder_id": "r1"},
            "Cancel the dentist reminder",
        ) is False
