"""Correcting a food entry, and whose day it lands on.

Reliable-assistant plan Phase C4/F, Food row: *"Lookup, serving/unit
arithmetic, atomic corrections, working registry contracts, no duplicate
replacement records."*

Finding 35: `food_search_and_log` logged a flat 1-serving entry for a requested
150g, and Sara "worked around it with a manually computed correct entry (248 cal
for 150g) rather than fixing the wrong one, **leaving both in the log**" — plus
a "~4-hour-wrong default logged_at timestamp". Finding 9: a real food entry was
denied and then listed in the next summary.
"""
import json
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
    ), {"id": uid, "email": f"food-{uid}@test.invalid"})
    pg.commit()
    yield uid
    pg.rollback()
    pg.execute(text("DELETE FROM food_log WHERE user_id = :u"), {"u": uid})
    pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": uid})
    pg.commit()


async def log(user_id, **kwargs):
    from app.tools.fitness.food_log import FoodLogCreateTool
    result = await FoodLogCreateTool().execute(user_id=user_id, **kwargs)
    assert result.success, result.message
    return result.data["log_id"]


async def fix(user_id, log_id, **kwargs):
    from app.tools.fitness.food_log import FoodLogCorrectTool
    return await FoodLogCorrectTool().execute(user_id=user_id, log_id=log_id, **kwargs)


def entries(pg, user_id):
    pg.rollback()
    return pg.execute(text(
        "SELECT id, meal_type, food_items, calories, protein, logged_at "
        "FROM food_log WHERE user_id = :u ORDER BY created_at"
    ), {"u": user_id}).mappings().all()


@requires_pg
class TestACorrectionChangesOneRow:
    @pytest.mark.asyncio
    async def test_scaling_a_quantity_updates_the_entry_in_place(self, pg, user_id):
        """Finding 35's exact shape: 100g logged, 150g meant."""
        log_id = await log(
            user_id, meal_type="lunch", food_description="100g chicken breast",
            calories=165, protein=31, carbs=0, fats=3.6,
        )
        result = await fix(user_id, log_id, scale_by=1.5,
                           food_description="150g chicken breast")
        assert result.success, result.message

        rows = entries(pg, user_id)
        assert len(rows) == 1, "a correction must not leave the wrong entry behind"
        assert rows[0]["calories"] == pytest.approx(247.5, abs=0.6)
        assert rows[0]["protein"] == pytest.approx(46.5, abs=0.2)
        assert "150g" in json.dumps(rows[0]["food_items"])

    @pytest.mark.asyncio
    async def test_explicit_macros_win_over_scaling(self, pg, user_id):
        log_id = await log(user_id, meal_type="lunch",
                           food_description="chicken", calories=165, protein=31)
        assert (await fix(user_id, log_id, calories=248, protein=46)).success
        row = entries(pg, user_id)[0]
        assert row["calories"] == 248
        assert row["protein"] == 46

    @pytest.mark.asyncio
    async def test_correcting_the_meal_keeps_one_entry(self, pg, user_id):
        log_id = await log(user_id, meal_type="breakfast",
                           food_description="chicken", calories=165)
        result = await fix(user_id, log_id, meal_type="lunch")
        assert result.success
        rows = entries(pg, user_id)
        assert len(rows) == 1
        assert rows[0]["meal_type"] == "lunch"
        assert "breakfast → lunch" in result.message

    @pytest.mark.asyncio
    async def test_another_entry_the_same_day_is_untouched(self, pg, user_id):
        breakfast = await log(user_id, meal_type="breakfast",
                              food_description="oats", calories=300)
        lunch = await log(user_id, meal_type="lunch",
                          food_description="100g chicken", calories=165)
        assert (await fix(user_id, lunch, scale_by=1.5)).success
        by_meal = {r["meal_type"]: r["calories"] for r in entries(pg, user_id)}
        assert by_meal["breakfast"] == 300
        assert by_meal["lunch"] == pytest.approx(247.5, abs=0.6)

    @pytest.mark.asyncio
    async def test_the_result_says_it_is_still_one_entry(self, pg, user_id):
        log_id = await log(user_id, meal_type="lunch",
                           food_description="chicken", calories=165)
        result = await fix(user_id, log_id, scale_by=1.5)
        assert "one entry" in result.message


@requires_pg
class TestItRefusesRatherThanLie:
    @pytest.mark.asyncio
    async def test_an_entry_that_does_not_exist(self, pg, user_id):
        result = await fix(user_id, str(uuid.uuid4()), scale_by=1.5)
        assert result.success is False
        assert "isn't there" in result.message

    @pytest.mark.asyncio
    async def test_another_users_entry(self, pg, user_id):
        other = str(uuid.uuid4())
        pg.execute(text(
            "INSERT INTO app_user (id, email, password_hash) VALUES (:id, :email, 'x')"
        ), {"id": other, "email": f"other-{other}@test.invalid"})
        pg.commit()
        try:
            log_id = await log(other, meal_type="lunch",
                               food_description="theirs", calories=100)
            result = await fix(user_id, log_id, scale_by=2)
            assert result.success is False
            assert entries(pg, other)[0]["calories"] == 100
        finally:
            pg.rollback()
            pg.execute(text("DELETE FROM food_log WHERE user_id = :u"), {"u": other})
            pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": other})
            pg.commit()

    @pytest.mark.asyncio
    async def test_nothing_to_correct_is_refused(self, pg, user_id):
        log_id = await log(user_id, meal_type="lunch",
                           food_description="chicken", calories=165)
        result = await fix(user_id, log_id)
        assert result.success is False
        assert "Nothing to correct" in result.message

    @pytest.mark.asyncio
    async def test_a_zero_or_negative_scale_is_refused(self, pg, user_id):
        log_id = await log(user_id, meal_type="lunch",
                           food_description="chicken", calories=165)
        for factor in (0, -1):
            result = await fix(user_id, log_id, scale_by=factor)
            assert result.success is False
        assert entries(pg, user_id)[0]["calories"] == 165

    @pytest.mark.asyncio
    async def test_an_unreadable_time_changes_nothing(self, pg, user_id):
        log_id = await log(user_id, meal_type="lunch",
                           food_description="chicken", calories=165)
        before = entries(pg, user_id)[0]["logged_at"]
        result = await fix(user_id, log_id, logged_at="sometime")
        assert result.success is False
        assert entries(pg, user_id)[0]["logged_at"] == before


@requires_pg
class TestTimestampsAreHisClock:
    @pytest.mark.asyncio
    async def test_a_naive_logged_at_is_his_local_time(self, pg, user_id):
        """Finding 35's "~4-hour-wrong default logged_at": a naive 7pm read as
        UTC stores a 3pm dinner."""
        log_id = await log(user_id, meal_type="dinner", food_description="steak",
                           calories=600, logged_at="2026-10-01T19:00:00")
        stored = as_utc(entries(pg, user_id)[0]["logged_at"])
        assert stored.hour == 23, f"19:00 local is 23:00 UTC in October, got {stored}"

    @pytest.mark.asyncio
    async def test_the_readback_is_in_his_clock(self, pg, user_id):
        from app.tools.fitness.food_log import FoodLogCreateTool
        result = await FoodLogCreateTool().execute(
            user_id=user_id, meal_type="dinner", food_description="steak",
            calories=600, logged_at="2026-10-01T19:00:00")
        assert "7:00 PM" in result.message
        assert "7:00 PM" in result.data["when"]

    @pytest.mark.asyncio
    async def test_a_late_dinner_counts_on_the_day_he_ate_it(self, pg, user_id):
        """`logged_at` holds UTC and the day queries compared it to bare dates,
        so a 9pm ET dinner (01:00 UTC next day) was counted as tomorrow — the
        day totals he read back were not the day he asked about."""
        from app.tools.fitness.food_log import FoodLogSearchTool

        await log(user_id, meal_type="dinner", food_description="late steak",
                  calories=600, logged_at="2026-10-01T21:00:00")
        result = await FoodLogSearchTool().execute(
            user_id=user_id, start_date="2026-10-01", end_date="2026-10-01")
        assert result.success, result.message
        assert result.data["total_entries"] == 1, (
            "a 9pm dinner must count on the day he ate it, not the next UTC day"
        )

    @pytest.mark.asyncio
    async def test_the_next_day_does_not_claim_it(self, pg, user_id):
        from app.tools.fitness.food_log import FoodLogSearchTool

        await log(user_id, meal_type="dinner", food_description="late steak",
                  calories=600, logged_at="2026-10-01T21:00:00")
        result = await FoodLogSearchTool().execute(
            user_id=user_id, start_date="2026-10-02", end_date="2026-10-02")
        assert result.data["total_entries"] == 0


@requires_pg
class TestTheRequiredJourneyShape:
    @pytest.mark.asyncio
    async def test_log_correct_inspect_no_duplicate(self, pg, user_id):
        """Plan journey 4: log → correct quantity → inspect totals → verify no
        duplicate or lost entry."""
        from app.tools.fitness.food_log import FoodLogSearchTool

        await log(user_id, meal_type="breakfast", food_description="oats",
                  calories=300, protein=10, logged_at="2026-10-01T08:00:00")
        lunch = await log(user_id, meal_type="lunch",
                          food_description="100g chicken breast",
                          calories=165, protein=31, logged_at="2026-10-01T12:30:00")

        assert (await fix(user_id, lunch, scale_by=1.5,
                          food_description="150g chicken breast")).success

        found = await FoodLogSearchTool().execute(
            user_id=user_id, start_date="2026-10-01", end_date="2026-10-01")
        assert found.data["total_entries"] == 2, "no duplicate, nothing lost"
        totals = sum(e["calories"] or 0 for e in found.data["entries"])
        assert totals == pytest.approx(547.5, abs=1.0)
