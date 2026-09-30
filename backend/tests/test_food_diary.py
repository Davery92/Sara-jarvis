"""B2 — /api/fitness/food-diary: targets, totals, remaining, items by meal.

TWO_A_DAY_AM_SETS_AND_FOOD_REPEAT_PLAN_2026_09_18 Part B2. Runs against real
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
               {"id": uid, "email": f"diary-test-{uid}@example.invalid"})
    pg.commit()
    yield uid
    for stmt in ("DELETE FROM food_log WHERE user_id = :uid",
                 "DELETE FROM fitness_phase WHERE user_id = :uid",
                 "DELETE FROM fitness_program WHERE user_id = :uid",
                 "DELETE FROM app_user WHERE id = :uid"):
        try:
            pg.execute(text(stmt), {"uid": uid})
            pg.commit()
        except Exception:
            pg.rollback()


def _log(pg, user_id, *, name, meal_type, calories, protein=0, carbs=0, fats=0,
         hour=12, days_ago=0, food_id="fs-1"):
    logged_at = datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    detailed = [{"food_id": food_id, "name": name, "source": "fatsecret", "serving_id": "sv-1",
                 "serving_description": "1 serving", "quantity": 1, "unit": "serving",
                 "calories": calories, "protein": protein, "carbs": carbs, "fats": fats}]
    pg.execute(text("""
        INSERT INTO food_log (id, user_id, meal_type, food_items, detailed_items,
                              calories, protein, carbs, fats, logged_at)
        VALUES (:id, :uid, :meal, CAST(:fi AS json), CAST(:di AS jsonb),
                :cal, :pro, :carb, :fat, :logged_at)
    """), {
        "id": str(uuid.uuid4()), "uid": user_id, "meal": meal_type,
        "fi": json.dumps([{"name": name, "quantity": 1, "unit": "serving"}]),
        "di": json.dumps(detailed), "cal": calories, "pro": protein, "carb": carbs, "fat": fats,
        "logged_at": logged_at,
    })
    pg.commit()


@requires_pg
@pytest.mark.asyncio
class TestFoodDiary:
    async def test_items_are_grouped_by_meal_with_subtotals(self, pg, user_id):
        from app.routes.fitness import get_food_diary
        today = datetime.now().date()

        _log(pg, user_id, name="Eggs", meal_type="breakfast", calories=200, protein=15)
        _log(pg, user_id, name="Chicken Thighs", meal_type="lunch", calories=300, protein=30)
        _log(pg, user_id, name="Rice", meal_type="lunch", calories=200, protein=4)

        result = await get_food_diary(date_param=today.isoformat(), days=1, user_id=user_id, db=pg)

        assert result["date"] == today.isoformat()
        assert len(result["meals"]["breakfast"]["items"]) == 1
        assert result["meals"]["breakfast"]["subtotal"]["calories"] == 200
        assert len(result["meals"]["lunch"]["items"]) == 2
        assert result["meals"]["lunch"]["subtotal"]["calories"] == 500
        assert result["meals"]["dinner"]["items"] == []

    async def test_totals_and_remaining_are_derived_from_all_meals(self, pg, user_id):
        from app.routes.fitness import get_food_diary
        today = datetime.now().date()

        _log(pg, user_id, name="Eggs", meal_type="breakfast", calories=200, protein=15, carbs=2, fats=10)
        _log(pg, user_id, name="Chicken Thighs", meal_type="dinner", calories=300, protein=30, carbs=0, fats=15)

        result = await get_food_diary(date_param=today.isoformat(), days=1, user_id=user_id, db=pg)

        assert result["totals"]["calories"] == 500
        assert result["totals"]["protein"] == 45
        # remaining is None when there's no active phase/target configured for
        # this throwaway user — never a crash, and never silently 0.
        assert "remaining" in result
        for field in ("calories", "protein", "carbs", "fats"):
            assert field in result["remaining"]

    async def test_items_carry_log_id_and_line_id(self, pg, user_id):
        from app.routes.fitness import get_food_diary
        today = datetime.now().date()
        _log(pg, user_id, name="Eggs", meal_type="breakfast", calories=200)

        result = await get_food_diary(date_param=today.isoformat(), days=1, user_id=user_id, db=pg)
        item = result["meals"]["breakfast"]["items"][0]
        assert item["log_id"]
        assert item["line_id"] == f"{item['log_id']}:0"

    async def test_days_param_returns_the_trailing_week(self, pg, user_id):
        from app.routes.fitness import get_food_diary
        today = datetime.now().date()

        _log(pg, user_id, name="Eggs", meal_type="breakfast", calories=200, days_ago=0)
        _log(pg, user_id, name="Oats", meal_type="breakfast", calories=150, days_ago=1)

        result = await get_food_diary(date_param=today.isoformat(), days=3, user_id=user_id, db=pg)
        assert len(result["days"]) == 3
        assert result["days"][-1]["date"] == today.isoformat()
        assert result["days"][-1]["totals"]["calories"] == 200
        assert result["days"][-2]["totals"]["calories"] == 150

    async def test_invalid_date_is_a_400(self, pg, user_id):
        from app.routes.fitness import get_food_diary
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_food_diary(date_param="not-a-date", days=1, user_id=user_id, db=pg)
        assert exc_info.value.status_code == 400

    async def test_an_empty_day_has_zeroed_meals_not_an_error(self, pg, user_id):
        from app.routes.fitness import get_food_diary
        today = datetime.now().date()
        result = await get_food_diary(date_param=today.isoformat(), days=1, user_id=user_id, db=pg)
        assert result["totals"] == {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fats": 0.0}
        for meal in ("breakfast", "lunch", "dinner", "snack"):
            assert result["meals"][meal]["items"] == []
