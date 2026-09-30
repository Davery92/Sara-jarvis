"""Reschedule as a real operation — reliable-assistant plan Phase C4.

"Expose coherent operations such as reschedule reminder… Do not require the
model to improvise coupled delete/create sequences."

Before this, the registry had create/list/cancel and nothing else, so "move the
vet one to seven" had two available shapes: cancel+create (finding 28's
mechanism — "a compensating undo request created a brand-new duplicate reminder
rather than truly restoring the original"), or nothing while claiming
otherwise. Every assertion below reads the stored row.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.civil_time import as_utc

pytestmark = pytest.mark.integration


def _pg_available() -> bool:
    return os.getenv("DATABASE_URL", "").startswith("postgresql")


requires_pg = pytest.mark.skipif(
    not _pg_available(), reason="needs the disposable PostgreSQL database")


@pytest.fixture
def pg():
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def user_id(pg):
    uid = str(uuid.uuid4())
    pg.execute(text(
        "INSERT INTO app_user (id, email, password_hash) VALUES (:id, :email, 'x')"
    ), {"id": uid, "email": f"resched-{uid}@test.invalid"})
    pg.commit()
    yield uid
    pg.rollback()
    for table in ("world_event_processing",):
        pg.execute(text(
            f"DELETE FROM {table} WHERE event_id IN "
            "(SELECT event_id FROM world_event WHERE user_id = :u)"
        ), {"u": uid})
    for table in ("world_event", "reminder"):
        pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})
    pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": uid})
    pg.commit()


async def create(user_id, title, when, description=""):
    from app.tools.reminders import RemindersCreateTool
    result = await RemindersCreateTool().execute(
        user_id=user_id, title=title, reminder_time=when,
        description=description, confirm_time=True,
    )
    assert result.success, result.message
    return result.data["reminder_id"]


async def reschedule(user_id, reminder_id, when):
    from app.tools.reminders import RemindersRescheduleTool
    return await RemindersRescheduleTool().execute(
        user_id=user_id, reminder_id=reminder_id, reminder_time=when)


def row(pg, reminder_id):
    pg.rollback()
    # `reminder_time`/`created_at` are naive `timestamp` columns storing UTC
    # wall clock (the session TimeZone is UTC), so every comparison here reads
    # them through `as_utc` rather than relying on the container's local zone.
    return pg.execute(text(
        "SELECT id, title, reminder_time, is_completed, notified_at, "
        "delivery_status, claimed_at, delivery_attempts "
        "FROM reminder WHERE id = :i"
    ), {"i": reminder_id}).fetchone()


def count(pg, user_id):
    pg.rollback()
    return pg.execute(text("SELECT count(*) FROM reminder WHERE user_id = :u"),
                      {"u": user_id}).scalar()


@requires_pg
class TestIdentityIsPreserved:
    @pytest.mark.asyncio
    async def test_moving_a_reminder_keeps_one_row_with_the_same_id(self, pg, user_id):
        rid = await create(user_id, "Call the vet", "2026-10-01T17:00:00")
        result = await reschedule(user_id, rid, "2026-10-01T19:00:00")
        assert result.success, result.message
        assert count(pg, user_id) == 1, "a reschedule must not leave a second row"
        stored = row(pg, rid)
        assert str(stored.id) == rid
        assert as_utc(stored.reminder_time).hour == 23  # 19:00 EDT

    @pytest.mark.asyncio
    async def test_the_readback_is_in_his_own_clock(self, pg, user_id):
        rid = await create(user_id, "Call the vet", "2026-10-01T17:00:00")
        result = await reschedule(user_id, rid, "2026-10-01T19:00:00")
        assert "7:00 PM" in result.data["when"]
        assert "7:00 PM" in result.message
        assert "5:00 PM" in result.message, "it should say what it moved FROM"

    @pytest.mark.asyncio
    async def test_a_sibling_reminder_is_untouched(self, pg, user_id):
        vet = await create(user_id, "Call the vet", "2026-10-01T17:00:00")
        dentist = await create(user_id, "Dentist cleaning", "2026-10-02T09:00:00")
        before = row(pg, dentist)
        assert (await reschedule(user_id, vet, "2026-10-01T19:00:00")).success
        after = row(pg, dentist)
        assert after.reminder_time == before.reminder_time
        assert after.is_completed == before.is_completed


@requires_pg
class TestDeliveryStateIsReset:
    @pytest.mark.asyncio
    async def test_a_reminder_that_already_fired_becomes_deliverable_again(self, pg, user_id):
        """The predispatch query skips any row with a terminal `notified_at`
        (app/tasks/inproc_schedulers.py). A reschedule that leaves it set is a
        reminder that will never fire again — which is worse than refusing."""
        rid = await create(user_id, "Call the vet", "2026-10-01T17:00:00")
        pg.execute(text(
            "UPDATE reminder SET notified_at = now(), delivery_status = 'sent', "
            "delivery_attempts = 2, last_error = 'x' WHERE id = :i"
        ), {"i": rid})
        pg.commit()

        assert (await reschedule(user_id, rid, "2026-10-05T19:00:00")).success
        stored = row(pg, rid)
        assert stored.notified_at is None
        assert stored.delivery_status is None
        assert stored.claimed_at is None
        assert stored.delivery_attempts == 0

    @pytest.mark.asyncio
    async def test_a_claimed_reminder_is_released(self, pg, user_id):
        rid = await create(user_id, "Call the vet", "2026-10-01T17:00:00")
        pg.execute(text(
            "UPDATE reminder SET delivery_status = 'claimed', claimed_at = now() "
            "WHERE id = :i"
        ), {"i": rid})
        pg.commit()
        assert (await reschedule(user_id, rid, "2026-10-05T19:00:00")).success
        stored = row(pg, rid)
        assert stored.delivery_status is None
        assert stored.claimed_at is None

    @pytest.mark.asyncio
    async def test_moving_a_completed_reminder_reactivates_it_and_says_so(self, pg, user_id):
        rid = await create(user_id, "Call the vet", "2026-10-01T17:00:00")
        from app.tools.reminders import RemindersCancelTool
        assert (await RemindersCancelTool().execute(
            user_id=user_id, reminder_id=rid)).success
        assert row(pg, rid).is_completed is True

        result = await reschedule(user_id, rid, "2026-10-05T19:00:00")
        assert result.success
        assert result.data["reactivated"] is True
        assert "active again" in result.message
        assert row(pg, rid).is_completed is False


@requires_pg
class TestItRefusesRatherThanLie:
    @pytest.mark.asyncio
    async def test_a_reminder_that_does_not_exist(self, pg, user_id):
        result = await reschedule(user_id, str(uuid.uuid4()), "2026-10-05T19:00:00")
        assert result.success is False
        assert "not found" in result.message.lower()

    @pytest.mark.asyncio
    async def test_another_users_reminder(self, pg, user_id):
        other = str(uuid.uuid4())
        pg.execute(text(
            "INSERT INTO app_user (id, email, password_hash) VALUES (:id, :email, 'x')"
        ), {"id": other, "email": f"other-{other}@test.invalid"})
        pg.commit()
        try:
            rid = await create(other, "Theirs", "2026-10-01T17:00:00")
            before = row(pg, rid).reminder_time
            result = await reschedule(user_id, rid, "2026-10-05T19:00:00")
            assert result.success is False
            assert row(pg, rid).reminder_time == before
        finally:
            pg.rollback()
            pg.execute(text(
                "DELETE FROM world_event_processing WHERE event_id IN "
                "(SELECT event_id FROM world_event WHERE user_id = :u)"), {"u": other})
            for table in ("world_event", "reminder"):
                pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": other})
            pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": other})
            pg.commit()

    @pytest.mark.asyncio
    async def test_moving_it_to_the_time_it_already_has(self, pg, user_id):
        rid = await create(user_id, "Call the vet", "2026-10-01T17:00:00")
        result = await reschedule(user_id, rid, "2026-10-01T17:00:00")
        assert result.success is False
        assert "nothing to move" in result.message

    @pytest.mark.asyncio
    async def test_an_unreadable_time_changes_nothing(self, pg, user_id):
        rid = await create(user_id, "Call the vet", "2026-10-01T17:00:00")
        before = row(pg, rid).reminder_time
        result = await reschedule(user_id, rid, "next tuesday")
        assert result.success is False
        assert "ISO 8601" in result.message
        assert row(pg, rid).reminder_time == before


@requires_pg
class TestUpdateChangesWordingOnly:
    @pytest.mark.asyncio
    async def test_it_changes_the_title_and_leaves_the_time(self, pg, user_id):
        from app.tools.reminders import RemindersUpdateTool
        rid = await create(user_id, "Call the vet", "2026-10-01T17:00:00")
        before = row(pg, rid).reminder_time
        result = await RemindersUpdateTool().execute(
            user_id=user_id, reminder_id=rid,
            title="Call the vet about the vaccination")
        assert result.success, result.message
        stored = row(pg, rid)
        assert stored.title == "Call the vet about the vaccination"
        assert stored.reminder_time == before
        assert count(pg, user_id) == 1

    @pytest.mark.asyncio
    async def test_a_no_op_update_is_refused_not_reported_as_done(self, pg, user_id):
        from app.tools.reminders import RemindersUpdateTool
        rid = await create(user_id, "Call the vet", "2026-10-01T17:00:00")
        result = await RemindersUpdateTool().execute(
            user_id=user_id, reminder_id=rid, title="Call the vet")
        assert result.success is False
        assert "already says that" in result.message


@requires_pg
class TestTheCreateContractItself:
    @pytest.mark.asyncio
    async def test_a_naive_time_is_his_local_clock(self, pg, user_id):
        """Finding 16 directly: a naive 7pm used to be stored as 19:00 UTC,
        which is 3pm his time."""
        rid = await create(user_id, "Call the vet", "2026-10-01T19:00:00")
        stored = as_utc(row(pg, rid).reminder_time)
        assert stored.hour == 23, f"19:00 local should be 23:00 UTC in October, got {stored}"

    @pytest.mark.asyncio
    async def test_an_explicit_offset_is_still_respected(self, pg, user_id):
        rid = await create(user_id, "Call the vet", "2026-10-01T19:00:00Z")
        stored = as_utc(row(pg, rid).reminder_time)
        assert stored.hour == 19
