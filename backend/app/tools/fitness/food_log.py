"""
Food Log Tools
Tools for tracking meals, nutrition, and dietary information
"""
from typing import Dict, Any, List
from app.tools.base import BaseTool, ToolResult
from sqlalchemy import text
from datetime import datetime, timezone, timedelta
import uuid
import json


def get_fitness_db():
    """Get database session"""
    from app.db.session import get_db
    return next(get_db())


class FoodLogCreateTool(BaseTool):
    """Log a meal with food items and nutrition information"""

    @property
    def name(self) -> str:
        return "food_log_create"

    @property
    def description(self) -> str:
        return "MANUAL food logging tool - use ONLY when the user provides specific nutrition values (calories, protein, carbs, fats) or when food_search_and_log tool is not appropriate. For natural language food descriptions, use food_search_and_log instead for automatic USDA nutrition lookup."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "meal_type": {
                    "type": "string",
                    "description": "Type of meal",
                    "enum": ["breakfast", "lunch", "dinner", "snack"]
                },
                "food_description": {
                    "type": "string",
                    "description": "Simple description of food items (e.g., '3 eggs, 4oz ground beef'). Do NOT use JSON arrays."
                },
                "calories": {
                    "type": "number",
                    "description": "Total calories (optional)"
                },
                "protein": {
                    "type": "number",
                    "description": "Protein in grams (optional)"
                },
                "carbs": {
                    "type": "number",
                    "description": "Carbohydrates in grams (optional)"
                },
                "fats": {
                    "type": "number",
                    "description": "Fats in grams (optional)"
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes about the meal"
                },
                "logged_at": {
                    "type": "string",
                    "description": "When the meal was eaten (ISO format, defaults to now)"
                }
            },
            "required": ["meal_type"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Create a food log entry"""
        meal_type = kwargs.get("meal_type")
        food_description = kwargs.get("food_description", "")
        calories = kwargs.get("calories")
        protein = kwargs.get("protein")
        carbs = kwargs.get("carbs")
        fats = kwargs.get("fats")
        notes = kwargs.get("notes", "")
        logged_at_str = kwargs.get("logged_at")

        # Convert numeric strings to numbers
        if isinstance(calories, str):
            try:
                calories = float(calories)
            except:
                calories = None
        if isinstance(protein, str):
            try:
                protein = float(protein)
            except:
                protein = None
        if isinstance(carbs, str):
            try:
                carbs = float(carbs)
            except:
                carbs = None
        if isinstance(fats, str):
            try:
                fats = float(fats)
            except:
                fats = None

        # Create food_items from description
        if food_description:
            food_items = [{"name": food_description, "quantity": 1, "unit": "serving"}]
        elif notes:
            food_items = [{"name": notes, "quantity": 1, "unit": "serving"}]
        elif calories or protein or carbs or fats:
            food_items = [{"name": "Food entry", "quantity": 1, "unit": "serving"}]
        else:
            return ToolResult(
                success=False,
                message="Please provide food_description or nutritional information"
            )

        # Parse logged_at timestamp
        if logged_at_str:
            try:
                logged_at = datetime.fromisoformat(logged_at_str.replace('Z', '+00:00'))
            except:
                logged_at = datetime.now(timezone.utc)
        else:
            logged_at = datetime.now(timezone.utc)

        db = get_fitness_db()

        try:
            log_id = str(uuid.uuid4())
            stmt = text("""
                INSERT INTO food_log
                (id, user_id, meal_type, food_items, calories, protein, carbs, fats, notes, logged_at, created_at, updated_at)
                VALUES
                (:id, :user_id, :meal_type, :food_items, :calories, :protein, :carbs, :fats, :notes, :logged_at, NOW(), NOW())
                RETURNING id, created_at
            """)

            result = db.execute(stmt, {
                "id": log_id,
                "user_id": user_id,
                "meal_type": meal_type,
                "food_items": json.dumps(food_items),
                "calories": calories,
                "protein": protein,
                "carbs": carbs,
                "fats": fats,
                "notes": notes,
                "logged_at": logged_at
            })
            db.commit()

            row = result.fetchone()

            # Format food items summary
            if food_description:
                items_str = food_description
            else:
                items_str = ", ".join([f"{item['quantity']} {item.get('unit', '')} {item['name']}" for item in food_items])

            return ToolResult(
                success=True,
                data={
                    "log_id": log_id,
                    "meal_type": meal_type,
                    "food_items": food_items,
                    "calories": calories,
                    "protein": protein,
                    "carbs": carbs,
                    "fats": fats,
                    "logged_at": logged_at.isoformat(),
                    "created_at": row.created_at.isoformat() if row.created_at else None
                },
                message=f"Logged {meal_type}: {items_str}" + (f" ({calories} cal)" if calories else "")
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to create food log: {str(e)}"
            )
        finally:
            db.close()


class FoodLogSearchTool(BaseTool):
    """Search food log entries by date range"""

    @property
    def name(self) -> str:
        return "food_log_search"

    @property
    def description(self) -> str:
        return "Search food log entries by date range. Returns meals with nutritional totals."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date (ISO format, defaults to today)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (ISO format, defaults to today)"
                },
                "meal_type": {
                    "type": "string",
                    "description": "Filter by meal type (optional)",
                    "enum": ["breakfast", "lunch", "dinner", "snack", "all"]
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default: 20)",
                    "default": 20
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Search food log entries"""
        start_date_str = kwargs.get("start_date")
        end_date_str = kwargs.get("end_date")
        meal_type = kwargs.get("meal_type", "all")
        limit = kwargs.get("limit", 20)

        # Default to today
        today = datetime.now(timezone.utc).date()
        start_date = today
        end_date = today

        if start_date_str:
            try:
                start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
            except:
                pass

        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            except:
                pass

        db = get_fitness_db()

        try:
            meal_filter = ""
            params = {
                "user_id": user_id,
                "start_date": start_date,
                "end_date": end_date + timedelta(days=1),  # Include full day
                "limit": limit
            }

            if meal_type != "all":
                meal_filter = "AND meal_type = :meal_type"
                params["meal_type"] = meal_type

            sql = text(f"""
                SELECT id, meal_type, food_items, calories, protein, carbs, fats, notes, logged_at, created_at
                FROM food_log
                WHERE user_id = :user_id
                AND logged_at >= :start_date
                AND logged_at < :end_date
                {meal_filter}
                ORDER BY logged_at DESC
                LIMIT :limit
            """)

            result = db.execute(sql, params)

            entries = []
            total_calories = 0
            total_protein = 0
            total_carbs = 0
            total_fats = 0

            for row in result.fetchall():
                food_items = json.loads(row.food_items) if isinstance(row.food_items, str) else row.food_items

                entry = {
                    "log_id": row.id,
                    "meal_type": row.meal_type,
                    "food_items": food_items,
                    "calories": row.calories,
                    "protein": row.protein,
                    "carbs": row.carbs,
                    "fats": row.fats,
                    "notes": row.notes,
                    "logged_at": row.logged_at.isoformat() if row.logged_at else None
                }
                entries.append(entry)

                # Sum totals
                if row.calories:
                    total_calories += row.calories
                if row.protein:
                    total_protein += row.protein
                if row.carbs:
                    total_carbs += row.carbs
                if row.fats:
                    total_fats += row.fats

            return ToolResult(
                success=True,
                data={
                    "entries": entries,
                    "totals": {
                        "calories": round(total_calories, 1),
                        "protein": round(total_protein, 1),
                        "carbs": round(total_carbs, 1),
                        "fats": round(total_fats, 1)
                    },
                    "date_range": {
                        "start": start_date.isoformat(),
                        "end": end_date.isoformat()
                    },
                    "total_entries": len(entries)
                },
                message=f"Found {len(entries)} food log entries from {start_date} to {end_date}"
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Food log search failed: {str(e)}"
            )
        finally:
            db.close()


class FoodLogSummaryTool(BaseTool):
    """Get daily/weekly nutrition summary"""

    @property
    def name(self) -> str:
        return "food_log_summary"

    @property
    def description(self) -> str:
        return "Get nutrition summary for a date range (daily averages, totals, meal distribution)."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date (ISO format)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (ISO format)"
                },
                "period": {
                    "type": "string",
                    "description": "Summary period",
                    "enum": ["day", "week", "month"],
                    "default": "week"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get food log summary"""
        period = kwargs.get("period", "week")
        start_date_str = kwargs.get("start_date")
        end_date_str = kwargs.get("end_date")

        # Default to last week
        today = datetime.now(timezone.utc).date()
        if period == "day":
            start_date = today
            end_date = today
        elif period == "month":
            start_date = today - timedelta(days=30)
            end_date = today
        else:  # week
            start_date = today - timedelta(days=7)
            end_date = today

        if start_date_str:
            try:
                start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
            except:
                pass

        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            except:
                pass

        db = get_fitness_db()

        try:
            # Get summary statistics
            sql = text("""
                SELECT
                    COUNT(*) as total_entries,
                    COUNT(DISTINCT DATE(logged_at)) as days_logged,
                    SUM(calories) as total_calories,
                    AVG(calories) as avg_calories,
                    SUM(protein) as total_protein,
                    AVG(protein) as avg_protein,
                    SUM(carbs) as total_carbs,
                    AVG(carbs) as avg_carbs,
                    SUM(fats) as total_fats,
                    AVG(fats) as avg_fats
                FROM food_log
                WHERE user_id = :user_id
                AND logged_at >= :start_date
                AND logged_at < :end_date
            """)

            result = db.execute(sql, {
                "user_id": user_id,
                "start_date": start_date,
                "end_date": end_date + timedelta(days=1)
            })

            row = result.fetchone()

            # Get meal distribution
            meal_dist_sql = text("""
                SELECT meal_type, COUNT(*) as count
                FROM food_log
                WHERE user_id = :user_id
                AND logged_at >= :start_date
                AND logged_at < :end_date
                GROUP BY meal_type
            """)

            meal_result = db.execute(meal_dist_sql, {
                "user_id": user_id,
                "start_date": start_date,
                "end_date": end_date + timedelta(days=1)
            })

            meal_distribution = {m.meal_type: m.count for m in meal_result.fetchall()}

            days_logged = row.days_logged or 1  # Avoid division by zero

            summary = {
                "period": period,
                "date_range": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat()
                },
                "statistics": {
                    "total_entries": row.total_entries or 0,
                    "days_logged": days_logged,
                    "daily_averages": {
                        "calories": round(row.total_calories / days_logged, 1) if row.total_calories else 0,
                        "protein": round(row.total_protein / days_logged, 1) if row.total_protein else 0,
                        "carbs": round(row.total_carbs / days_logged, 1) if row.total_carbs else 0,
                        "fats": round(row.total_fats / days_logged, 1) if row.total_fats else 0
                    },
                    "totals": {
                        "calories": round(row.total_calories, 1) if row.total_calories else 0,
                        "protein": round(row.total_protein, 1) if row.total_protein else 0,
                        "carbs": round(row.total_carbs, 1) if row.total_carbs else 0,
                        "fats": round(row.total_fats, 1) if row.total_fats else 0
                    }
                },
                "meal_distribution": meal_distribution
            }

            return ToolResult(
                success=True,
                data=summary,
                message=f"Food log summary for {start_date} to {end_date}: {row.total_entries or 0} entries across {days_logged} days"
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to generate summary: {str(e)}"
            )
        finally:
            db.close()
