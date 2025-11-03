"""
Food Search and Log Tool
Parses natural language food descriptions, searches USDA database, and logs meals automatically
"""
from typing import Dict, Any, List, Optional, Tuple
from app.tools.base import BaseTool, ToolResult
from sqlalchemy import text
from datetime import datetime
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
    """Parse natural language food descriptions, search USDA, and log meals"""

    @property
    def name(self) -> str:
        return "food_search_and_log"

    @property
    def description(self) -> str:
        return ("PREFERRED TOOL for logging meals. Parse natural language food descriptions "
                "(e.g., '3 eggs and 4oz ground beef' or 'chicken breast 6oz and rice 1 cup'), "
                "automatically search USDA nutrition database for accurate data, calculate nutritional totals, "
                "and log the meal. Use this whenever the user mentions eating food in natural language. "
                "This provides accurate USDA nutrition data instead of estimates.")

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
                # Search USDA database
                usda_result = await self._search_food(food_name)

                if not usda_result:
                    logger.warning(f"No USDA result found for: {food_name}")
                    simple_items.append({
                        "name": food_name,
                        "quantity": quantity,
                        "unit": unit or "serving"
                    })
                    continue

                # Convert quantity to grams
                grams = self._convert_to_grams(quantity, unit, food_name)

                # Scale nutrition from per-100g to actual quantity
                scaling_factor = grams / 100.0

                item_calories = (usda_result.get("calories") or 0) * scaling_factor
                item_protein = (usda_result.get("protein") or 0) * scaling_factor
                item_carbs = (usda_result.get("carbs") or 0) * scaling_factor
                item_fats = (usda_result.get("fats") or 0) * scaling_factor

                # Add to totals
                total_calories += item_calories
                total_protein += item_protein
                total_carbs += item_carbs
                total_fats += item_fats

                # Store detailed item
                detailed_items.append({
                    "food_id": usda_result.get("id"),
                    "name": usda_result.get("name"),
                    "quantity": quantity,
                    "unit": unit or "g",
                    "grams": round(grams, 1),
                    "calories": round(item_calories, 1),
                    "protein": round(item_protein, 1),
                    "carbs": round(item_carbs, 1),
                    "fats": round(item_fats, 1),
                    "source": "usda"
                })

                # Simple item for food_items field
                simple_items.append({
                    "name": usda_result.get("name"),
                    "quantity": quantity,
                    "unit": unit or "g"
                })

            if not detailed_items:
                return ToolResult(
                    success=False,
                    message="Could not find any matching foods in the USDA database. Please try again with different food names."
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
        """Search USDA database for a food item"""
        try:
            from app.routes.food_database import search_usda_foods

            # Search USDA
            results = await search_usda_foods(food_name, limit=1)

            if results and len(results) > 0:
                # Return the first (best) match
                food = results[0]
                return {
                    "id": food.id,
                    "name": food.name,
                    "calories": food.calories,
                    "protein": food.protein,
                    "carbs": food.carbs,
                    "fats": food.fats,
                    "fiber": food.fiber,
                    "sugar": food.sugar
                }

            return None

        except Exception as e:
            logger.error(f"Error searching for food '{food_name}': {e}")
            return None

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
                "notes": "Auto-logged via USDA search",
                "logged_at": datetime.now()
            })

            db.commit()

            return log_id

        except Exception as e:
            db.rollback()
            logger.error(f"Error saving food log: {e}", exc_info=True)
            raise
        finally:
            db.close()
