"""Bounded recovery when an explicit request produced no tool call.

Gap 3 of the 2026-09-29 correction: *"Implement bounded recovery for explicit
requests that produce no tool call, preserving authorization and idempotency."*

The live failure this is written against, from the acceptance trial: "Scratch
the vet one, I already called them." — a CANCEL the contract would have
authorized, against a reminder that existed, answered with "Hey! How's your
morning going?" and no call at all.

Every test here is deterministic: no generation is involved in recovery, by
design, so none is involved in checking it either.
"""
import uuid
from datetime import datetime, timedelta

import pytest

from app.services.request_recovery import RecoveredCall, recover


# ---------------------------------------------------------------------------
# Fixtures: real rows, because resolution is a database question
# ---------------------------------------------------------------------------


def _db():
    from app.db.session import get_db
    gen = get_db()
    return next(gen)


@pytest.fixture
def owner():
    from app.models.user import User
    db = _db()
    try:
        u = User(email=f"recovery-{uuid.uuid4().hex[:8]}@test.invalid",
                 password_hash="x")
        db.add(u)
        db.commit()
        db.refresh(u)
        return str(u.id)
    finally:
        db.close()


@pytest.fixture
def other_owner():
    from app.models.user import User
    db = _db()
    try:
        u = User(email=f"recovery-{uuid.uuid4().hex[:8]}@test.invalid",
                 password_hash="x")
        db.add(u)
        db.commit()
        db.refresh(u)
        return str(u.id)
    finally:
        db.close()


def make_reminder(owner_id, title):
    from app.models.reminder import Reminder
    db = _db()
    try:
        row = Reminder(user_id=owner_id, title=title, is_completed=False,
                       reminder_time=datetime.utcnow() + timedelta(days=1))
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)
    finally:
        db.close()


def make_timer(owner_id, title):
    from app.models.reminder import Timer
    db = _db()
    try:
        row = Timer(user_id=owner_id, title=title, is_active=True,
                    duration_minutes=10,
                    start_time=datetime.utcnow(),
                    end_time=datetime.utcnow() + timedelta(minutes=10))
        db.add(row)
        db.commit()
        db.refresh(row)
        return str(row.id)
    finally:
        db.close()


def try_recover(owner_id, message, tools=("reminders_cancel", "timers_cancel",
                                          "reminders_reschedule")):
    db = _db()
    try:
        return recover(db, owner_id, message, offered_tools=list(tools))
    finally:
        db.close()


# ---------------------------------------------------------------------------


class TestTheLiveFailure:
    def test_the_vet_cancellation_is_recovered(self, owner):
        row_id = make_reminder(owner, "Call the vet")
        result = try_recover(owner, "Scratch the vet one, I already called them.")
        assert isinstance(result, RecoveredCall), "nothing was recovered"
        assert result.tool_name == "reminders_cancel"
        assert result.arguments == {"reminder_id": row_id}

    def test_the_recovered_call_names_a_row_david_actually_owns(self, owner):
        make_reminder(owner, "Call the vet")
        result = try_recover(owner, "Scratch the vet one, I already called them.")
        from app.models.reminder import Reminder
        db = _db()
        try:
            row = db.query(Reminder).filter(
                Reminder.id == result.arguments["reminder_id"]).first()
            assert str(row.user_id) == owner
        finally:
            db.close()


class TestItRefusesToGuess:
    def test_an_unidentifiable_operation_recovers_nothing(self, owner):
        """The other half of gap 1. An imperative whose verb the application
        does not understand grants nothing — and recovery is not a back door
        into granting it anyway."""
        make_reminder(owner, "Call the vet")
        assert try_recover(owner, "Yeet the vet one.") is None

    def test_two_matching_rows_recover_nothing(self, owner):
        make_reminder(owner, "Call the vet")
        make_reminder(owner, "Vet food pickup")
        assert try_recover(owner, "Cancel the vet one.") is None

    def test_no_matching_row_recovers_nothing(self, owner):
        make_reminder(owner, "Call the vet")
        assert try_recover(owner, "Cancel the dentist one.") is None

    def test_another_owners_row_is_never_recovered(self, owner, other_owner):
        make_reminder(other_owner, "Call the vet")
        assert try_recover(owner, "Scratch the vet one.") is None

    def test_a_question_recovers_nothing(self, owner):
        make_reminder(owner, "Call the vet")
        assert try_recover(owner, "Is the vet one still set?") is None

    def test_a_hypothetical_recovers_nothing(self, owner):
        make_reminder(owner, "Call the vet")
        assert try_recover(
            owner, "If I end up going in person, should I cancel the vet one?") is None

    def test_a_create_is_never_recovered(self, owner):
        """A create needs a title and a time composed from prose. Getting that
        wrong writes a wrong row, which is worse than writing nothing."""
        assert try_recover(
            owner, "Add a reminder to water the plants tonight at 8",
            tools=("reminders_create", "reminders_cancel")) is None

    def test_two_domains_both_matching_recover_nothing(self, owner):
        """He has a reminder AND a timer called "pasta". Which one "cancel the
        pasta one" means is a question, not a coin flip."""
        make_reminder(owner, "Pasta water")
        make_timer(owner, "Pasta timer")
        assert try_recover(owner, "Cancel the pasta one.") is None

    def test_the_right_domain_is_picked_by_the_rows_not_the_menu(self, owner):
        """Both cancel tools are on the menu and only the timer domain holds a
        matching row, so the timer is what he meant."""
        make_reminder(owner, "Call the vet")
        timer_id = make_timer(owner, "Laundry")
        result = try_recover(owner, "Cancel the laundry one.")
        assert result is not None
        assert result.tool_name == "timers_cancel"
        assert result.arguments == {"timer_id": timer_id}

    def test_a_tool_that_was_not_offered_is_not_recovered(self, owner):
        make_reminder(owner, "Call the vet")
        assert try_recover(owner, "Scratch the vet one.",
                           tools=("reminders_list",)) is None


class TestRescheduleNeedsAnExplicitTime:
    def test_a_reschedule_with_a_clock_time_is_recovered(self, owner):
        row_id = make_reminder(owner, "Call the vet")
        result = try_recover(owner, "Move the vet one to 4pm.")
        assert result is not None
        assert result.tool_name == "reminders_reschedule"
        assert result.arguments["reminder_id"] == row_id
        assert result.arguments["new_time"].lower().replace(" ", "") == "4pm"

    def test_a_vague_time_recovers_nothing(self, owner):
        make_reminder(owner, "Call the vet")
        assert try_recover(owner, "Move the vet one to later today.") is None

    def test_two_times_recover_nothing(self, owner):
        make_reminder(owner, "Call the vet")
        assert try_recover(owner, "Move the vet one from 9am to 4pm.") is None


class TestItIsInert:
    def test_an_empty_message_recovers_nothing(self, owner):
        assert try_recover(owner, "") is None

    def test_no_owner_recovers_nothing(self):
        assert try_recover("", "Cancel the vet one.") is None

    def test_recovery_itself_writes_nothing(self, owner):
        """It builds a call; it does not execute one. Execution goes through
        `execute_tool`, so the contract and the receipt both still apply."""
        from app.models.reminder import Reminder
        row_id = make_reminder(owner, "Call the vet")
        try_recover(owner, "Scratch the vet one.")
        db = _db()
        try:
            row = db.query(Reminder).filter(Reminder.id == row_id).first()
            assert row.is_completed is False, "recovery must not write by itself"
        finally:
            db.close()
