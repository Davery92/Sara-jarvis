"""B5 — deterministic, explainable ranking of /food-log/recent-foods.

TWO_A_DAY_AM_SETS_AND_FOOD_REPEAT_PLAN_2026_09_18 Part B5: score = frequency
+ recency decay + meal-type match + time-of-day match + training-day
agreement, no model. A fixed history should always produce the same order,
and every row must carry a human `reason`.
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
               {"id": uid, "email": f"rank-test-{uid}@example.invalid"})
    pg.commit()
    yield uid
    for stmt in ("DELETE FROM food_log WHERE user_id = :uid", "DELETE FROM app_user WHERE id = :uid"):
        try:
            pg.execute(text(stmt), {"uid": uid})
            pg.commit()
        except Exception:
            pg.rollback()


def _log(pg, user_id, *, name, food_id, meal_type, hour, days_ago, calories=200):
    logged_at = datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    detailed = [{"food_id": food_id, "name": name, "source": "fatsecret", "serving_id": "sv-1",
                 "serving_description": "1 serving", "quantity": 1, "unit": "serving",
                 "calories": calories, "protein": 10, "carbs": 10, "fats": 5}]
    pg.execute(text("""
        INSERT INTO food_log (id, user_id, meal_type, food_items, detailed_items,
                              calories, protein, carbs, fats, logged_at)
        VALUES (:id, :uid, :meal, CAST(:fi AS json), CAST(:di AS jsonb), :cal, 10, 10, 5, :logged_at)
    """), {
        "id": str(uuid.uuid4()), "uid": user_id, "meal": meal_type,
        "fi": json.dumps([{"name": name, "quantity": 1, "unit": "serving"}]),
        "di": json.dumps(detailed), "cal": calories, "logged_at": logged_at,
    })
    pg.commit()


@requires_pg
@pytest.mark.asyncio
class TestRecentFoodsRanking:
    async def test_every_row_carries_a_reason(self, pg, user_id):
        from app.routes.fitness import get_recent_foods
        _log(pg, user_id, name="Oatmeal", food_id="fs-oat", meal_type="breakfast", hour=7, days_ago=0)

        result = await get_recent_foods(limit=20, user_id=user_id, db=pg)
        assert all(f.get("reason") for f in result["recent_foods"])
        assert all(isinstance(f.get("score"), float) for f in result["recent_foods"])

    async def test_meal_type_match_can_outrank_higher_frequency(self, pg, user_id):
        """Oatmeal: logged 5x, always at breakfast. Pizza: logged 6x, always
        at dinner. Asking for breakfast should surface oatmeal first despite
        pizza's higher raw frequency."""
        from app.routes.fitness import get_recent_foods

        for i in range(5):
            _log(pg, user_id, name="Oatmeal", food_id="fs-oat", meal_type="breakfast", hour=7, days_ago=i)
        for i in range(6):
            _log(pg, user_id, name="Pizza", food_id="fs-pizza", meal_type="dinner", hour=19, days_ago=i)

        result = await get_recent_foods(limit=20, meal_type="breakfast", user_id=user_id, db=pg)
        names = [f["name"] for f in result["recent_foods"]]
        assert names.index("Oatmeal") < names.index("Pizza")

        oat = next(f for f in result["recent_foods"] if f["name"] == "Oatmeal")
        assert oat["reason"] == "Usual breakfast"

    async def test_with_no_meal_type_hint_frequency_and_recency_still_rank(self, pg, user_id):
        from app.routes.fitness import get_recent_foods
        for i in range(6):
            _log(pg, user_id, name="Pizza", food_id="fs-pizza", meal_type="dinner", hour=19, days_ago=i)
        _log(pg, user_id, name="Rare Snack", food_id="fs-rare", meal_type="snack", hour=15, days_ago=20)

        result = await get_recent_foods(limit=20, user_id=user_id, db=pg)
        names = [f["name"] for f in result["recent_foods"]]
        assert names.index("Pizza") < names.index("Rare Snack")

    async def test_logged_today_and_yesterday_reasons(self, pg, user_id):
        from app.routes.fitness import get_recent_foods
        _log(pg, user_id, name="Today Food", food_id="fs-today", meal_type="snack", hour=10, days_ago=0)
        _log(pg, user_id, name="Yesterday Food", food_id="fs-yesterday", meal_type="snack", hour=10, days_ago=1)

        result = await get_recent_foods(limit=20, user_id=user_id, db=pg)
        by_name = {f["name"]: f for f in result["recent_foods"]}
        assert by_name["Today Food"]["reason"] == "Logged today"
        assert by_name["Yesterday Food"]["reason"] == "Logged yesterday"

    async def test_ranking_is_deterministic_for_a_fixed_history(self, pg, user_id):
        from app.routes.fitness import get_recent_foods
        _log(pg, user_id, name="Oatmeal", food_id="fs-oat", meal_type="breakfast", hour=7, days_ago=0)
        _log(pg, user_id, name="Eggs", food_id="fs-eggs", meal_type="breakfast", hour=7, days_ago=2)

        first = await get_recent_foods(limit=20, meal_type="breakfast", user_id=user_id, db=pg)
        second = await get_recent_foods(limit=20, meal_type="breakfast", user_id=user_id, db=pg)
        assert [f["food_id"] for f in first["recent_foods"]] == [f["food_id"] for f in second["recent_foods"]]

    async def test_an_unknown_meal_type_hint_is_ignored_not_500(self, pg, user_id):
        from app.routes.fitness import get_recent_foods
        _log(pg, user_id, name="Oatmeal", food_id="fs-oat", meal_type="breakfast", hour=7, days_ago=0)
        result = await get_recent_foods(limit=20, meal_type="brunch", user_id=user_id, db=pg)
        assert len(result["recent_foods"]) == 1
