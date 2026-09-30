"""B1 — Recent/Yesterday/last-used remember the actual serving David logged.

TWO_A_DAY_AM_SETS_AND_FOOD_REPEAT_PLAN_2026_09_18 Part B1: before this,
`/food-log/recent-foods` and the FoodLogModal preset path reset every recent
item to `servings[0]` at quantity 1, discarding the amount actually logged
last time. These pin the backend half: the three endpoints (recent-foods,
yesterday, last-used) surface the most recent serving/quantity/unit per food,
plus per-serving macros so a client can rescale without a re-fetch.

Runs against real Postgres (JSONB `detailed_items`), inside the disposable
test stack — see test_workout_command_service.py's docstring for the pattern.
"""
import json
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from tests.test_workout_command_service import requires_pg  # same env-gated skip


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
               {"id": uid, "email": f"food-test-{uid}@example.invalid"})
    pg.commit()
    yield uid
    for stmt in ("DELETE FROM food_log WHERE user_id = :uid", "DELETE FROM app_user WHERE id = :uid"):
        try:
            pg.execute(text(stmt), {"uid": uid})
            pg.commit()
        except Exception:
            pg.rollback()


def _log(pg, user_id, *, name, food_id, serving_id, quantity, unit, calories,
         meal_type="lunch", days_ago=0, hours_offset=0):
    logged_at = datetime.now() - timedelta(days=days_ago, hours=-hours_offset)
    detailed = [{
        "food_id": food_id, "name": name, "source": "fatsecret",
        "serving_id": serving_id, "serving_description": f"{quantity} {unit}",
        "quantity": quantity, "unit": unit,
        "calories": calories, "protein": calories / 10, "carbs": calories / 5, "fats": calories / 20,
    }]
    pg.execute(text("""
        INSERT INTO food_log (id, user_id, meal_type, food_items, detailed_items,
                              calories, protein, carbs, fats, logged_at)
        VALUES (:id, :uid, :meal, CAST(:fi AS json), CAST(:di AS jsonb),
                :cal, :pro, :carb, :fat, :logged_at)
    """), {
        "id": str(uuid.uuid4()), "uid": user_id, "meal": meal_type,
        "fi": json.dumps([{"name": name, "quantity": quantity, "unit": unit}]),
        "di": json.dumps(detailed),
        "cal": calories, "pro": calories / 10, "carb": calories / 5, "fat": calories / 20,
        "logged_at": logged_at,
    })
    pg.commit()


CHICKEN_ID = "fs-61258"


@requires_pg
@pytest.mark.asyncio
class TestRecentFoodsLastUsed:
    async def test_last_quantity_is_the_most_recent_amount_logged(self, pg, user_id):
        """6 oz logged twice, 4 oz once (oldest) -> last_quantity reads 6, not
        an average and not the oldest entry."""
        from app.routes.fitness import get_recent_foods

        _log(pg, user_id, name="Chicken Thighs", food_id=CHICKEN_ID, serving_id="sv-1",
             quantity=4, unit="oz", calories=142, days_ago=3)
        _log(pg, user_id, name="Chicken Thighs", food_id=CHICKEN_ID, serving_id="sv-2",
             quantity=6, unit="oz", calories=213, days_ago=2)
        _log(pg, user_id, name="Chicken Thighs", food_id=CHICKEN_ID, serving_id="sv-2",
             quantity=6, unit="oz", calories=213, days_ago=1, meal_type="dinner")

        result = await get_recent_foods(limit=20, user_id=user_id, db=pg)
        chicken = next(f for f in result["recent_foods"] if f["food_id"] == CHICKEN_ID)

        assert chicken["last_quantity"] == 6
        assert chicken["last_unit"] == "oz"
        assert chicken["last_serving_id"] == "sv-2"
        assert chicken["last_meal_type"] == "dinner"
        assert chicken["times_30d"] == 3
        assert chicken["count"] == 3
        # Per-serving macros: 213 kcal at quantity 6 -> 35.5/unit.
        assert chicken["calories_per_serving"] == pytest.approx(213 / 6)

    async def test_yesterday_all_foods_carries_serving_id_and_quantity(self, pg, user_id):
        from app.routes.fitness import get_yesterday_foods

        _log(pg, user_id, name="Jasmine Rice", food_id="fs-99", serving_id="sv-rice",
             quantity=8, unit="oz", calories=280, days_ago=1)

        result = await get_yesterday_foods(user_id=user_id, db=pg)
        food = next(f for f in result["all_foods"] if f["food_id"] == "fs-99")
        assert food["serving_id"] == "sv-rice"
        assert food["quantity"] == 8
        assert food["unit"] == "oz"

    async def test_last_used_returns_the_newest_entry_per_id(self, pg, user_id):
        from app.routes.fitness import get_last_used_servings

        _log(pg, user_id, name="Chicken Thighs", food_id=CHICKEN_ID, serving_id="sv-1",
             quantity=4, unit="oz", calories=142, days_ago=5)
        _log(pg, user_id, name="Chicken Thighs", food_id=CHICKEN_ID, serving_id="sv-2",
             quantity=6, unit="oz", calories=213, days_ago=1)
        _log(pg, user_id, name="Jasmine Rice", food_id="fs-99", serving_id="sv-rice",
             quantity=8, unit="oz", calories=280, days_ago=1)

        result = await get_last_used_servings(
            food_ids=f"{CHICKEN_ID},fs-99,fs-nonexistent", user_id=user_id, db=pg)

        assert result[CHICKEN_ID]["serving_id"] == "sv-2"
        assert result[CHICKEN_ID]["quantity"] == 6
        assert result["fs-99"]["quantity"] == 8
        assert "fs-nonexistent" not in result

    async def test_a_food_with_no_history_is_simply_absent(self, pg, user_id):
        from app.routes.fitness import get_last_used_servings
        result = await get_last_used_servings(food_ids="fs-never-logged", user_id=user_id, db=pg)
        assert result == {}


@requires_pg
@pytest.mark.asyncio
class TestChatLoggedItemSurfacesWithItsServing:
    """food_search_log.py resolves a real serving_id now (B1) instead of
    always writing None — Recent should then remember it."""

    async def test_resolved_nutrition_carries_a_serving_id(self):
        from app.tools.fitness.food_search_log import FoodSearchAndLogTool
        import types

        tool = FoodSearchAndLogTool()

        class FakeServing:
            def __init__(self, serving_id, description, metric_unit=None, metric_amount=None,
                        calories=200, protein=20, carbohydrate=10, fat=5):
                self.serving_id = serving_id
                self.serving_description = description
                self.metric_serving_unit = metric_unit
                self.metric_serving_amount = metric_amount
                self.calories = calories
                self.protein = protein
                self.carbohydrate = carbohydrate
                self.fat = fat

        food = types.SimpleNamespace(servings=[
            FakeServing("sv-gram", "100 g", metric_unit="g", metric_amount=100),
            FakeServing("sv-default", "1 serving"),
        ])

        computed = tool._compute_item_nutrition(food, 6, "oz", "Chicken Thighs")
        assert computed is not None
        *_, serving_id = computed
        assert serving_id == "sv-gram"  # weight unit -> scaled off the gram serving


class TestManualToolParsesQuantity:
    """food_log.py's manual FoodLogCreateTool no longer flattens every entry
    to quantity:1/unit:'serving' when the description names an amount."""

    def test_leading_quantity_and_unit_are_parsed(self):
        from app.tools.fitness.food_log import _parse_quantity_unit
        assert _parse_quantity_unit("6 oz chicken thighs") == (6.0, "oz", "chicken thighs")
        assert _parse_quantity_unit("2 cups rice") == (2.0, "cups", "rice")
        assert _parse_quantity_unit("1/2 cup oats") == (0.5, "cup", "oats")

    def test_no_leading_quantity_falls_back_to_one_serving(self):
        from app.tools.fitness.food_log import _parse_quantity_unit
        assert _parse_quantity_unit("a protein shake") == (1.0, "serving", "a protein shake")
