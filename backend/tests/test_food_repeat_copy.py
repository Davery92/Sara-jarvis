"""B4 — repeat a meal, copy a whole day, and saved meals.

TWO_A_DAY_AM_SETS_AND_FOOD_REPEAT_PLAN_2026_09_18 Part B4. Runs against real
Postgres — see test_workout_command_service.py's docstring for the pattern.
"""
import json
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from tests.test_workout_command_service import requires_pg


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
    pg.execute(text("INSERT INTO app_user (id, email, password_hash) VALUES (:id, :email, 'x')"),
               {"id": uid, "email": f"repeat-test-{uid}@example.invalid"})
    pg.commit()
    yield uid
    for stmt in ("DELETE FROM food_log WHERE user_id = :uid",
                 "DELETE FROM saved_meal WHERE user_id = :uid",
                 "DELETE FROM app_user WHERE id = :uid"):
        try:
            pg.execute(text(stmt), {"uid": uid})
            pg.commit()
        except Exception:
            pg.rollback()


def _log(pg, user_id, *, name, meal_type, calories, hour=12, days_ago=0, food_id="fs-1"):
    logged_at = datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    detailed = [{"food_id": food_id, "name": name, "source": "fatsecret", "serving_id": "sv-1",
                 "serving_description": "6 oz", "quantity": 6, "unit": "oz", "calories": calories,
                 "protein": 20, "carbs": 5, "fats": 8}]
    log_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO food_log (id, user_id, meal_type, food_items, detailed_items,
                              calories, protein, carbs, fats, logged_at)
        VALUES (:id, :uid, :meal, CAST(:fi AS json), CAST(:di AS jsonb),
                :cal, 20, 5, 8, :logged_at)
    """), {
        "id": log_id, "uid": user_id, "meal": meal_type,
        "fi": json.dumps([{"name": name, "quantity": 6, "unit": "oz"}]),
        "di": json.dumps(detailed), "cal": calories, "logged_at": logged_at,
    })
    pg.commit()
    return log_id


@requires_pg
@pytest.mark.asyncio
class TestRepeat:
    async def test_repeat_copies_items_and_totals(self, pg, user_id):
        from app.routes.fitness import repeat_food_log_entry, RepeatFoodLogRequest
        log_id = _log(pg, user_id, name="Chicken Thighs", meal_type="lunch", calories=280)

        result = await repeat_food_log_entry(
            log_id, RepeatFoodLogRequest(), user_id=user_id, db=pg)
        assert result["success"] is True
        new_id = result["log_id"]
        assert new_id != log_id

        row = pg.execute(text("""
            SELECT meal_type, calories, detailed_items FROM food_log WHERE id = :id
        """), {"id": new_id}).fetchone()
        assert row.meal_type == "lunch"
        assert row.calories == 280
        assert row.detailed_items[0]["name"] == "Chicken Thighs"

    async def test_repeat_can_change_meal_type(self, pg, user_id):
        from app.routes.fitness import repeat_food_log_entry, RepeatFoodLogRequest
        log_id = _log(pg, user_id, name="Oats", meal_type="breakfast", calories=150)

        result = await repeat_food_log_entry(
            log_id, RepeatFoodLogRequest(meal_type="snack"), user_id=user_id, db=pg)
        row = pg.execute(text("SELECT meal_type FROM food_log WHERE id = :id"),
                          {"id": result["log_id"]}).fetchone()
        assert row.meal_type == "snack"

    async def test_repeat_is_idempotent(self, pg, user_id):
        from app.routes.fitness import repeat_food_log_entry, RepeatFoodLogRequest
        log_id = _log(pg, user_id, name="Oats", meal_type="breakfast", calories=150)
        key = str(uuid.uuid4())

        first = await repeat_food_log_entry(
            log_id, RepeatFoodLogRequest(idempotency_key=key), user_id=user_id, db=pg)
        second = await repeat_food_log_entry(
            log_id, RepeatFoodLogRequest(idempotency_key=key), user_id=user_id, db=pg)
        assert first["log_id"] == second["log_id"]

        count = pg.execute(text(
            "SELECT COUNT(*) FROM food_log WHERE user_id = :uid AND id != :orig"
        ), {"uid": user_id, "orig": log_id}).scalar()
        assert count == 1

    async def test_repeating_a_missing_entry_404s(self, pg, user_id):
        from app.routes.fitness import repeat_food_log_entry, RepeatFoodLogRequest
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await repeat_food_log_entry(
                "does-not-exist", RepeatFoodLogRequest(), user_id=user_id, db=pg)
        assert exc_info.value.status_code == 404


@requires_pg
@pytest.mark.asyncio
class TestCopyDay:
    async def test_copies_every_meal_from_the_source_day(self, pg, user_id):
        from app.routes.fitness import copy_food_log_day, CopyDayRequest
        yesterday = (datetime.now() - timedelta(days=1)).date()
        today = datetime.now().date()

        _log(pg, user_id, name="Eggs", meal_type="breakfast", calories=200, hour=7, days_ago=1)
        _log(pg, user_id, name="Chicken", meal_type="lunch", calories=300, hour=12, days_ago=1)

        result = await copy_food_log_day(
            CopyDayRequest(from_date=yesterday.isoformat(), to_date=today.isoformat()),
            user_id=user_id, db=pg)
        assert result["copied"] == 2

        rows = pg.execute(text("""
            SELECT meal_type, logged_at FROM food_log
            WHERE user_id = :uid AND DATE(logged_at) = :d ORDER BY logged_at
        """), {"uid": user_id, "d": today}).fetchall()
        assert [r.meal_type for r in rows] == ["breakfast", "lunch"]
        # Time-of-day is preserved on the new date.
        assert rows[0].logged_at.hour == 7

    async def test_meals_filter_restricts_which_rows_copy(self, pg, user_id):
        from app.routes.fitness import copy_food_log_day, CopyDayRequest
        yesterday = (datetime.now() - timedelta(days=1)).date()
        today = datetime.now().date()

        _log(pg, user_id, name="Eggs", meal_type="breakfast", calories=200, days_ago=1)
        _log(pg, user_id, name="Chicken", meal_type="lunch", calories=300, days_ago=1)

        result = await copy_food_log_day(
            CopyDayRequest(from_date=yesterday.isoformat(), to_date=today.isoformat(), meals=["lunch"]),
            user_id=user_id, db=pg)
        assert result["copied"] == 1

    async def test_invalid_dates_are_a_400(self, pg, user_id):
        from app.routes.fitness import copy_food_log_day, CopyDayRequest
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await copy_food_log_day(
                CopyDayRequest(from_date="nope", to_date="2026-01-01"), user_id=user_id, db=pg)
        assert exc_info.value.status_code == 400


@requires_pg
@pytest.mark.asyncio
class TestSavedMeals:
    async def test_create_list_and_log_a_saved_meal(self, pg, user_id):
        from app.routes.fitness import (
            create_saved_meal, list_saved_meals, log_saved_meal,
            SavedMealCreate, SavedMealLogRequest,
        )
        items = [
            {"food_id": "fs-1", "name": "Chicken Thighs", "quantity": 6, "unit": "oz",
             "calories": 280, "protein": 40, "carbs": 0, "fats": 12},
            {"food_id": "fs-2", "name": "Jasmine Rice", "quantity": 8, "unit": "oz",
             "calories": 300, "protein": 6, "carbs": 65, "fats": 1},
        ]
        created = await create_saved_meal(
            SavedMealCreate(name="Post-workout lunch", default_meal_type="lunch", items=items),
            user_id=user_id, db=pg)
        assert created["success"] is True

        listed = await list_saved_meals(user_id=user_id, db=pg)
        assert len(listed["saved_meals"]) == 1
        assert listed["saved_meals"][0]["calories"] == 580

        logged = await log_saved_meal(
            created["saved_meal_id"], SavedMealLogRequest(), user_id=user_id, db=pg)
        assert logged["success"] is True

        row = pg.execute(text("""
            SELECT meal_type, calories, detailed_items FROM food_log WHERE id = :id
        """), {"id": logged["log_id"]}).fetchone()
        assert row.meal_type == "lunch"
        assert row.calories == 580
        assert len(row.detailed_items) == 2

    async def test_archiving_removes_it_from_the_list(self, pg, user_id):
        from app.routes.fitness import create_saved_meal, list_saved_meals, archive_saved_meal, SavedMealCreate
        created = await create_saved_meal(
            SavedMealCreate(name="Snack", items=[{"name": "Almonds", "quantity": 1, "unit": "oz",
                                                    "calories": 160, "protein": 6, "carbs": 6, "fats": 14}]),
            user_id=user_id, db=pg)
        await archive_saved_meal(created["saved_meal_id"], user_id=user_id, db=pg)
        listed = await list_saved_meals(user_id=user_id, db=pg)
        assert listed["saved_meals"] == []

    async def test_creating_with_no_items_is_a_400(self, pg, user_id):
        from app.routes.fitness import create_saved_meal, SavedMealCreate
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await create_saved_meal(SavedMealCreate(name="Empty", items=[]), user_id=user_id, db=pg)
        assert exc_info.value.status_code == 400

    async def test_logging_a_saved_meal_is_idempotent(self, pg, user_id):
        from app.routes.fitness import create_saved_meal, log_saved_meal, SavedMealCreate, SavedMealLogRequest
        created = await create_saved_meal(
            SavedMealCreate(name="Snack", items=[{"name": "Almonds", "quantity": 1, "unit": "oz",
                                                    "calories": 160, "protein": 6, "carbs": 6, "fats": 14}]),
            user_id=user_id, db=pg)
        key = str(uuid.uuid4())
        first = await log_saved_meal(created["saved_meal_id"], SavedMealLogRequest(idempotency_key=key),
                                     user_id=user_id, db=pg)
        second = await log_saved_meal(created["saved_meal_id"], SavedMealLogRequest(idempotency_key=key),
                                      user_id=user_id, db=pg)
        assert first["log_id"] == second["log_id"]
