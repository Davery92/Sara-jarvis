"""Recipe nutrition estimation — SARA_UNLEASHED Phase U.6.

Computes per-serving macros for a recipe from its structured ingredients by
looking each one up against FatSecret, reusing the exact quantity+unit ->
accurate-macros machinery `FoodSearchAndLogTool` already built for meal
logging (serving-list scaling, unit conversion) rather than re-deriving it.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def estimate_recipe_nutrition(
    ingredients: List[Dict[str, Any]], servings: int
) -> Optional[Dict[str, float]]:
    """Return {calories, protein, carbs, fats} PER SERVING, or None if not a
    single ingredient could be resolved against FatSecret. Ingredients
    lacking a separate quantity/unit (saved as a single free-text string,
    e.g. "2 cups flour") are parsed the same way natural-language food
    logging parses them.
    """
    from app.tools.fitness.food_search_log import FoodSearchAndLogTool

    helper = FoodSearchAndLogTool()
    total = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fats": 0.0}
    resolved_any = False

    for ing in ingredients or []:
        name = (ing.get("name") or "").strip()
        if not name:
            continue

        # R1: explicit per-ingredient macros win — from a live FatSecret pick
        # (already scaled to the chosen quantity/serving) or manual entry. Only
        # ingredients WITHOUT explicit macros fall through to a fresh lookup.
        explicit_cals = ing.get("calories")
        if explicit_cals is not None:
            total["calories"] += float(explicit_cals or 0)
            total["protein"] += float(ing.get("protein") or 0)
            total["carbs"] += float(ing.get("carbs") or 0)
            total["fats"] += float(ing.get("fats") or 0)
            resolved_any = True
            continue

        quantity = ing.get("quantity")
        unit = ing.get("unit")
        if quantity is None:
            parsed = helper._parse_food_items(name)
            if not parsed:
                continue
            quantity, unit, name = parsed[0]
        try:
            quantity = float(quantity or 1)
        except (TypeError, ValueError):
            quantity = 1.0

        try:
            food = await helper._search_food(name)
            if not food or not food.get("id"):
                continue
            cals, prot, carb, fat, _label = await helper._resolve_nutrition(
                food["id"], quantity, unit, name, food
            )
        except Exception as e:
            logger.warning(f"Recipe nutrition lookup failed for ingredient '{name}': {e}")
            continue

        total["calories"] += cals
        total["protein"] += prot
        total["carbs"] += carb
        total["fats"] += fat
        resolved_any = True

    if not resolved_any:
        return None

    servings = max(1, int(servings or 1))
    return {k: round(v / servings, 1) for k, v in total.items()}


def macros_missing(calories, protein, carbs, fats) -> bool:
    """0.00 must be treated as missing, not data (R27 — the macaroni-salad
    bug: recipes_create accepts calories as optional, and a flat 0.00 across
    every field is what a naive INSERT with no value produces, not a real
    zero-calorie recipe)."""
    values = [calories, protein, carbs, fats]
    if all(v is None for v in values):
        return True
    return all((v is None or float(v) == 0.0) for v in values)
