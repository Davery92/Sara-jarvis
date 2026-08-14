"""
Food Search and Log Tool
Parses natural language food descriptions, searches FatSecret database, and logs meals automatically
"""
from typing import Dict, Any, List, Optional, Tuple
from app.tools.base import BaseTool, ToolResult
from sqlalchemy import text
from datetime import datetime
from app.core.timezone import naive_local_now
import uuid
import json
import re
import logging

logger = logging.getLogger(__name__)


def get_fitness_db():
    """Get database session"""
    from app.db.session import get_db
    return next(get_db())


class FoodSearchAndLogTool(BaseTool):
    """Parse natural language food descriptions, search FatSecret, and log meals"""

    @property
    def name(self) -> str:
        return "food_search_and_log"

    @property
    def description(self) -> str:
        return ("PREFERRED TOOL for logging meals. Parse natural language food descriptions "
                "(e.g., '3 eggs and 4oz ground beef' or 'chicken breast 6oz and rice 1 cup'), "
                "automatically search FatSecret nutrition database for accurate data, calculate nutritional totals, "
                "and log the meal. Use this whenever the user mentions eating food in natural language. "
                "This provides accurate FatSecret nutrition data instead of estimates.")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "user_input": {
                    "type": "string",
                    "description": "Natural language food description like '3 eggs and 4oz ground beef' or '2 chicken breasts and 1 cup rice'"
                },
                "meal_type": {
                    "type": "string",
                    "description": "Type of meal",
                    "enum": ["breakfast", "lunch", "dinner", "snack"]
                }
            },
            "required": ["user_input", "meal_type"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Execute the food search and log operation"""
        user_input = kwargs.get("user_input", "")
        meal_type = kwargs.get("meal_type", "")

        if not user_input or not meal_type:
            return ToolResult(
                success=False,
                message="Missing required parameters: user_input and meal_type"
            )

        try:
            # Parse food items from natural language
            food_items = self._parse_food_items(user_input)

            if not food_items:
                return ToolResult(
                    success=False,
                    message=f"Could not parse any food items from: '{user_input}'. Please try rephrasing."
                )

            # Search USDA and calculate nutrition for each item
            detailed_items = []
            total_calories = 0.0
            total_protein = 0.0
            total_carbs = 0.0
            total_fats = 0.0

            simple_items = []  # For food_items field

            for quantity, unit, food_name in food_items:
                # Search FatSecret database
                fatsecret_result = await self._search_food(food_name)

                if not fatsecret_result or not fatsecret_result.get("id"):
                    logger.warning(f"No FatSecret result found for: {food_name}")
                    simple_items.append({
                        "name": food_name,
                        "quantity": quantity,
                        "unit": unit or "serving"
                    })
                    continue

                # Resolve accurate macros for the requested quantity+unit using the
                # food's real serving list — e.g. "4 oz chicken" converts to grams
                # and scales off the gram serving, instead of blindly logging the
                # summary serving × 4 (which over-counted ~4x).
                nutrition = await self._resolve_nutrition(
                    fatsecret_result["id"], quantity, unit, food_name, fatsecret_result
                )
                item_calories, item_protein, item_carbs, item_fats, serving_label = nutrition

                # Add to totals
                total_calories += item_calories
                total_protein += item_protein
                total_carbs += item_carbs
                total_fats += item_fats

                # Store detailed item
                detailed_items.append({
                    "food_id": fatsecret_result.get("id"),
                    "name": fatsecret_result.get("name"),
                    "source": "fatsecret",
                    "serving_id": None,
                    "serving_description": serving_label,
                    "quantity": quantity,
                    "unit": unit or "serving",
                    "calories": round(item_calories, 1),
                    "protein": round(item_protein, 1),
                    "carbs": round(item_carbs, 1),
                    "fats": round(item_fats, 1),
                })

                # Simple item for food_items field
                simple_items.append({
                    "name": fatsecret_result.get("name"),
                    "quantity": quantity,
                    "unit": unit or "serving"
                })

            if not detailed_items:
                return ToolResult(
                    success=False,
                    message="Could not find any matching foods in the FatSecret database. Please try again with different food names."
                )

            # Log to database
            log_id = await self._save_food_log(
                user_id=user_id,
                meal_type=meal_type,
                food_items=simple_items,
                detailed_items=detailed_items,
                calories=total_calories,
                protein=total_protein,
                carbs=total_carbs,
                fats=total_fats
            )

            # Build success message
            food_list = ", ".join([f"{item['quantity']}{item['unit']} {item['name']}"
                                  for item in detailed_items])

            message = (f"✅ Logged {meal_type}: {food_list}\n"
                      f"📊 Totals: {round(total_calories)} cal | "
                      f"P: {round(total_protein)}g | C: {round(total_carbs)}g | F: {round(total_fats)}g")

            # Emit FOOD_LOGGED so chat/Siri-driven logging counts as app activity
            # too (bumps last_app_activity_at via the working-memory subscriber).
            try:
                from app.services.event_bus import emit_event, EventType
                await emit_event(
                    EventType.FOOD_LOGGED, user_id,
                    payload={
                        "meal_type": meal_type,
                        "food": (detailed_items[0]["name"] if detailed_items else None),
                        "calories": round(total_calories, 1),
                    },
                    source="food_search_and_log",
                )
            except Exception as _e:
                logger.debug(f"FOOD_LOGGED emit failed: {_e}")

            return ToolResult(
                success=True,
                data={
                    "log_id": log_id,
                    "meal_type": meal_type,
                    "items": detailed_items,
                    "totals": {
                        "calories": round(total_calories, 1),
                        "protein": round(total_protein, 1),
                        "carbs": round(total_carbs, 1),
                        "fats": round(total_fats, 1)
                    }
                },
                message=message
            )

        except Exception as e:
            logger.error(f"Error in food_search_and_log: {e}", exc_info=True)
            return ToolResult(
                success=False,
                message=f"Failed to log food: {str(e)}"
            )

    def _parse_food_items(self, user_input: str) -> List[Tuple[float, Optional[str], str]]:
        """
        Parse natural language into food items with quantities
        Returns: List of (quantity, unit, food_name) tuples
        """
        # Split by common separators
        parts = re.split(r'\s+and\s+|,\s*', user_input.lower())

        food_items = []

        # Pattern: quantity + optional unit + food name
        # Examples: "3 eggs", "4oz ground beef", "2 large chicken breasts", "1 cup rice"
        pattern = r'(\d+(?:\.\d+)?)\s*(oz|g|gram|grams|cup|cups|tbsp|tsp|large|medium|small|slice|slices)?\s*(.+)'

        for part in parts:
            part = part.strip()
            if not part:
                continue

            match = re.match(pattern, part)
            if match:
                quantity = float(match.group(1))
                unit = match.group(2)
                food_name = match.group(3).strip()

                food_items.append((quantity, unit, food_name))
            else:
                # Try without quantity (assume 1 serving)
                if part:
                    food_items.append((1.0, None, part.strip()))

        return food_items

    async def _search_food(self, food_name: str) -> Optional[Dict[str, Any]]:
        """Search FatSecret database for a food item"""
        try:
            from app.services.fatsecret_service import get_fatsecret_service

            service = get_fatsecret_service()
            results, total = await service.search_foods(food_name, page=0, max_results=1)

            if results and len(results) > 0:
                # Return the first (best) match
                food = results[0]
                return {
                    "id": food.get("food_id"),
                    "name": food.get("food_name"),
                    "calories": food.get("calories"),
                    "protein": food.get("protein"),
                    "carbs": food.get("carbs"),
                    "fats": food.get("fat"),
                    "serving_description": food.get("serving_description"),
                    "serving_unit": food.get("serving_description", "serving")
                }

            return None

        except Exception as e:
            logger.error(f"Error searching for food '{food_name}': {e}")
            return None

    _WEIGHT_UNITS = {"oz", "ounce", "ounces", "g", "gram", "grams", "lb", "lbs", "pound", "pounds", "kg"}

    async def _resolve_nutrition(
        self, food_id, quantity: float, unit: Optional[str], food_name: str, fallback: Dict[str, Any]
    ) -> Tuple[float, float, float, float, str]:
        """Accurate macros for quantity+unit using the food's full serving list.

        Returns (calories, protein, carbs, fats, serving_label). Falls back to the
        legacy "summary serving × quantity" if the full food can't be fetched.
        """
        try:
            from app.services.fatsecret_service import get_fatsecret_service
            svc = get_fatsecret_service()
            fid = str(food_id)
            if fid.startswith("fs-"):
                fid = fid[3:]
            food = await svc.get_food(fid)
            if food and food.servings:
                computed = self._compute_item_nutrition(food, quantity, unit, food_name)
                if computed:
                    return computed
        except Exception as e:
            logger.warning(f"resolve_nutrition fell back for '{food_name}': {e}")

        # Legacy fallback: scale the summary serving by the raw quantity.
        c = (fallback.get("calories") or 0) * quantity
        p = (fallback.get("protein") or 0) * quantity
        cb = (fallback.get("carbs") or 0) * quantity
        f = (fallback.get("fats") or 0) * quantity
        label = f"{quantity:g} × {fallback.get('serving_description') or 'serving'}"
        return (c, p, cb, f, label)

    def _compute_item_nutrition(
        self, food, quantity: float, unit: Optional[str], food_name: str
    ) -> Optional[Tuple[float, float, float, float, str]]:
        """Pick the right serving and scale it for (quantity, unit)."""
        servings = food.servings or []
        if not servings:
            return None
        default = servings[0]

        def macros(s) -> Tuple[float, float, float, float]:
            return (s.calories or 0, s.protein or 0, s.carbohydrate or 0, s.fat or 0)

        def gram_serving():
            # A serving whose metric amount is in grams/ml — lets us scale by weight.
            for s in servings:
                mu = (s.metric_serving_unit or "").lower()
                if mu in ("g", "gram", "grams", "ml") and s.metric_serving_amount:
                    return s
            return None

        u = (unit or "").lower().strip()

        # 1. Weight unit → convert to grams, scale off a gram-based serving.
        if u in self._WEIGHT_UNITS:
            gs = gram_serving()
            if gs and gs.metric_serving_amount:
                target_g = self._convert_to_grams(quantity, unit, food_name)
                ratio = target_g / gs.metric_serving_amount
                c, p, cb, f = macros(gs)
                return (c * ratio, p * ratio, cb * ratio, f * ratio,
                        f"{quantity:g} {unit} (~{round(target_g)}g)")

        # 2. Unit names a real serving (e.g. "cup", "slice") → use that serving × qty.
        if u:
            match = next((s for s in servings if u in (s.serving_description or "").lower()), None)
            if match:
                c, p, cb, f = macros(match)
                return (c * quantity, p * quantity, cb * quantity, f * quantity,
                        f"{quantity:g} × {match.serving_description}")

        # 3. Other volume/size unit → grams approximation off a gram serving.
        if u:
            gs = gram_serving()
            if gs and gs.metric_serving_amount:
                target_g = self._convert_to_grams(quantity, unit, food_name)
                ratio = target_g / gs.metric_serving_amount
                c, p, cb, f = macros(gs)
                return (c * ratio, p * ratio, cb * ratio, f * ratio,
                        f"{quantity:g} {unit} (~{round(target_g)}g)")

        # 4. No/unknown unit → treat quantity as a count of the default serving.
        c, p, cb, f = macros(default)
        return (c * quantity, p * quantity, cb * quantity, f * quantity,
                f"{quantity:g} × {default.serving_description}")

    def _convert_to_grams(self, quantity: float, unit: Optional[str], food_name: str) -> float:
        """Convert quantity to grams for nutrition calculation"""
        if not unit:
            # Try to infer from food name
            if 'egg' in food_name.lower():
                return quantity * 50  # 1 egg ≈ 50g
            return quantity * 100  # Default to 100g per serving

        unit = unit.lower()

        # Weight conversions
        if unit in ['oz', 'ounce', 'ounces']:
            return quantity * 28.35
        elif unit in ['g', 'gram', 'grams']:
            return quantity
        elif unit in ['lb', 'pound', 'pounds']:
            return quantity * 453.592

        # Volume conversions (approximate)
        elif unit in ['cup', 'cups']:
            return quantity * 240  # Approximate for most foods
        elif unit in ['tbsp', 'tablespoon', 'tablespoons']:
            return quantity * 15
        elif unit in ['tsp', 'teaspoon', 'teaspoons']:
            return quantity * 5

        # Size-based (approximate)
        elif unit in ['large']:
            if 'egg' in food_name.lower():
                return quantity * 50
            return quantity * 150  # Large portion
        elif unit in ['medium']:
            return quantity * 100
        elif unit in ['small']:
            return quantity * 50
        elif unit in ['slice', 'slices']:
            return quantity * 30  # Approximate slice

        # Default
        return quantity * 100

    async def _save_food_log(
        self,
        user_id: str,
        meal_type: str,
        food_items: List[Dict],
        detailed_items: List[Dict],
        calories: float,
        protein: float,
        carbs: float,
        fats: float
    ) -> str:
        """Save food log entry to database"""
        db = get_fitness_db()

        try:
            log_id = str(uuid.uuid4())

            query = text("""
                INSERT INTO food_log (
                    id, user_id, meal_type, food_items, detailed_items,
                    calories, protein, carbs, fats, notes, logged_at
                ) VALUES (
                    :id, :user_id, :meal_type,
                    CAST(:food_items AS jsonb),
                    CAST(:detailed_items AS jsonb),
                    :calories, :protein, :carbs, :fats, :notes, :logged_at
                )
                RETURNING id
            """)

            result = db.execute(query, {
                "id": log_id,
                "user_id": user_id,
                "meal_type": meal_type,
                "food_items": json.dumps(food_items),
                "detailed_items": json.dumps(detailed_items),
                "calories": round(calories, 1),
                "protein": round(protein, 1),
                "carbs": round(carbs, 1),
                "fats": round(fats, 1),
                "notes": "Auto-logged via FatSecret search",
                "logged_at": naive_local_now()
            })

            db.commit()

            return log_id

        except Exception as e:
            db.rollback()
            logger.error(f"Error saving food log: {e}", exc_info=True)
            raise
        finally:
            db.close()
