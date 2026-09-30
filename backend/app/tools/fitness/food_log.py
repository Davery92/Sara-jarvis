"""
Food Log Tools
Tools for tracking meals, nutrition, and dietary information
"""
from typing import Dict, Any, List, Tuple
from app.services.civil_time import (
    AmbiguousTimeError,
    TIME_PARAMETER_CONTRACT,
    as_utc,
    describe_instant,
    parse_user_datetime,
)
from app.tools.base import BaseTool, ToolResult
from sqlalchemy import text
from datetime import datetime, timezone, timedelta
import re
import uuid
import json


def get_fitness_db():
    """Get database session"""
    from app.db.session import get_db
    return next(get_db())


# "6 oz chicken thighs" -> (6.0, "oz", "chicken thighs"). Best-effort only —
# this manual tool has no resolved food_id/serving to fall back on, but a
# leading quantity+unit is common enough in what David actually says that
# writing a flat quantity:1/unit:"serving" every time was quietly poisoning
# Recent's "last amount logged" memory for these foods (B1).
_QTY_UNIT_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?|\d+/\d+)\s*"
    r"(oz|ounce|ounces|g|gram|grams|lb|lbs|pound|pounds|cup|cups|"
    r"tbsp|tablespoon|tablespoons|tsp|teaspoon|teaspoons|ml|l|"
    r"slice|slices|serving|servings)\b\.?\s+(.+)$",
    re.IGNORECASE,
)


def _parse_quantity_unit(description: str) -> Tuple[float, str, str]:
    """Best-effort (quantity, unit, name) from a free-text description.
    Falls back to (1, "serving", description) when nothing parses."""
    text_in = (description or "").strip()
    m = _QTY_UNIT_RE.match(text_in)
    if not m:
        return 1.0, "serving", text_in
    raw_qty, unit, rest = m.group(1), m.group(2).lower(), m.group(3).strip()
    if "/" in raw_qty:
        num, den = raw_qty.split("/", 1)
        try:
            qty = float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            return 1.0, "serving", text_in
    else:
        qty = float(raw_qty)
    return qty, unit, rest or text_in


def local_day_window(start_day, end_day) -> Tuple[datetime, datetime]:
    """The naive-UTC half-open window covering David's local days.

    `food_log.logged_at` is a naive `timestamp` column holding UTC (the session
    TimeZone is UTC), and these queries compared it against bare `date` values
    — which Postgres casts to midnight UTC. So "today" was 00:00-24:00 UTC, and
    every meal David ate after 8pm ET counted as the NEXT day: the day totals
    he read back were not the day he asked about. Converting his local day
    bounds to UTC first is what makes a "day" his day.
    """
    from app.core.timezone import local_day_bounds

    start_local, _ = local_day_bounds(start_day)
    _, end_local = local_day_bounds(end_day)
    return (
        start_local.astimezone(timezone.utc).replace(tzinfo=None),
        end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )


class FoodLogCreateTool(BaseTool):
    """Log a meal with food items and nutrition information"""

    @property
    def name(self) -> str:
        return "food_log_create"

    @property
    def description(self) -> str:
        return "MANUAL food logging tool - use ONLY when the user provides specific nutrition values (calories, protein, carbs, fats) or when food_search_and_log tool is not appropriate. For natural language food descriptions, use food_search_and_log instead for automatic FatSecret nutrition lookup."

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

        # Create food_items from description — parse a leading quantity+unit
        # ("6 oz chicken thighs") so Recent remembers the real amount rather
        # than a flat 1 serving (B1).
        if food_description:
            qty, unit, name = _parse_quantity_unit(food_description)
            food_items = [{"name": name, "quantity": qty, "unit": unit}]
        elif notes:
            qty, unit, name = _parse_quantity_unit(notes)
            food_items = [{"name": name, "quantity": qty, "unit": unit}]
        elif calories or protein or carbs or fats:
            food_items = [{"name": "Food entry", "quantity": 1, "unit": "serving"}]
        else:
            return ToolResult(
                success=False,
                message="Please provide food_description or nutritional information"
            )

        # One timestamp contract, shared with reminders/timers/calendar (see
        # app/services/civil_time.py). Finding 35 recorded a "~4-hour-wrong
        # default logged_at timestamp" on a food entry: a naive local time from
        # the model was read as UTC, so a 7pm dinner landed at 3pm.
        _logged_at_note = ""
        if logged_at_str:
            try:
                _interpretation = parse_user_datetime(logged_at_str)
                logged_at = _interpretation.instant
                _logged_at_note = _interpretation.note
            except AmbiguousTimeError:
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
                    "when": describe_instant(logged_at),
                    "created_at": row.created_at.isoformat() if row.created_at else None
                },
                message=(
                    f"Logged {meal_type}: {items_str}"
                    + (f" ({calories} cal)" if calories else "")
                    + f" at {describe_instant(logged_at)}"
                    + (f" — {_logged_at_note}" if _logged_at_note else "")
                )
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
            _start_utc, _end_utc = local_day_window(start_date, end_date)
            params = {
                "user_id": user_id,
                "start_date": _start_utc,
                "end_date": _end_utc,
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
        _summary_start_utc, _summary_end_utc = local_day_window(start_date, end_date)

        try:
            # Get summary statistics
            sql = text("""
                SELECT
                    COUNT(*) as total_entries,
                    COUNT(DISTINCT DATE(logged_at AT TIME ZONE 'UTC'
                          AT TIME ZONE 'America/New_York')) as days_logged,
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
                "start_date": _summary_start_utc,
                "end_date": _summary_end_utc
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
                "start_date": _summary_start_utc,
                "end_date": _summary_end_utc
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


class FoodLogCorrectTool(BaseTool):
    """Correct an existing food entry — reliable-assistant plan Phase C4.

    "Expose coherent operations such as… correct food quantity… Do not require
    the model to improvise coupled delete/create sequences."

    Two confirmed findings are the same missing operation:

    * **35** — `food_search_and_log` logged a flat 1-serving (100g/165cal)
      entry for a requested 150g, and Sara "worked around it with a manually
      computed correct entry (248 cal for 150g) rather than fixing the wrong
      one, leaving BOTH in the log." There was no fix-the-wrong-one available.
    * **7/9** — a real food entry was denied, then listed in the next summary.
      A correction that adds a row instead of changing one guarantees the two
      readbacks disagree.

    So this updates one row in place, scales the macros with the quantity when
    it can, and never leaves a second entry behind.
    """

    @property
    def name(self) -> str:
        return "food_log_correct"

    @property
    def description(self) -> str:
        return (
            "Fix a food entry David has already logged — 'that was 150 grams not 100', "
            "'make it two eggs', 'that was lunch not breakfast', 'I had that at 7 not 3'. "
            "Changes the existing entry: use this rather than logging a corrected copy, "
            "which leaves both the wrong entry and the right one in his day's totals.\n"
            "Pass `scale_by` when the AMOUNT changed and you want the calories and macros "
            "scaled with it (150g instead of 100g is scale_by 1.5) — or pass explicit "
            "calories/protein/carbs/fats to set them outright. Find the entry first with "
            "food_log_search and pass its real log_id."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "log_id": {
                    "type": "string",
                    "description": "The entry to fix (from food_log_search).",
                },
                "food_description": {
                    "type": "string",
                    "description": "Corrected description, e.g. '150g chicken breast'.",
                },
                "scale_by": {
                    "type": "number",
                    "description": (
                        "Multiply the existing calories and macros by this. 1.5 for "
                        "'150g not 100g', 2 for 'two of them not one'. Ignored if "
                        "explicit calories/macros are given."
                    ),
                },
                "calories": {"type": "number", "description": "Set calories outright."},
                "protein": {"type": "number", "description": "Set protein (g) outright."},
                "carbs": {"type": "number", "description": "Set carbs (g) outright."},
                "fats": {"type": "number", "description": "Set fats (g) outright."},
                "meal_type": {
                    "type": "string",
                    "enum": ["breakfast", "lunch", "dinner", "snack"],
                    "description": "Corrected meal, if he had the wrong one.",
                },
                "logged_at": {
                    "type": "string",
                    "description": "Corrected time. " + TIME_PARAMETER_CONTRACT,
                },
            },
            "required": ["log_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        log_id = kwargs.get("log_id")
        if not log_id:
            return ToolResult(success=False, message="log_id is required.")

        scale_by = kwargs.get("scale_by")
        explicit = {
            field: kwargs.get(field)
            for field in ("calories", "protein", "carbs", "fats")
            if kwargs.get(field) is not None
        }
        new_description = kwargs.get("food_description")
        new_meal = kwargs.get("meal_type")
        new_logged_at_str = kwargs.get("logged_at")

        if not any([scale_by, explicit, new_description, new_meal, new_logged_at_str]):
            return ToolResult(
                success=False,
                message="Nothing to correct — say what changed (amount, macros, meal, or time).",
            )

        time_note = ""
        new_logged_at = None
        if new_logged_at_str:
            try:
                interpretation = parse_user_datetime(new_logged_at_str)
            except AmbiguousTimeError as exc:
                return ToolResult(success=False, message=str(exc))
            new_logged_at = interpretation.instant
            time_note = interpretation.note

        db = get_fitness_db()
        try:
            row = db.execute(text("""
                SELECT id, meal_type, food_items, calories, protein, carbs, fats,
                       notes, logged_at
                FROM food_log WHERE id = :id AND user_id = :uid
            """), {"id": log_id, "uid": user_id}).mappings().first()
            if not row:
                return ToolResult(
                    success=False,
                    message="That food entry isn't there — nothing was changed.",
                )

            before = {
                "calories": row["calories"], "protein": row["protein"],
                "carbs": row["carbs"], "fats": row["fats"],
                "meal_type": row["meal_type"],
                "logged_at": as_utc(row["logged_at"]),
            }

            values: Dict[str, Any] = {}
            changed: List[str] = []

            if explicit:
                for field, value in explicit.items():
                    values[field] = float(value)
                changed.append("macros")
            elif scale_by:
                try:
                    factor = float(scale_by)
                except (TypeError, ValueError):
                    return ToolResult(success=False, message="scale_by must be a number.")
                if factor <= 0:
                    return ToolResult(
                        success=False,
                        message="scale_by must be greater than zero — to remove an entry, say so.",
                    )
                for field in ("calories", "protein", "carbs", "fats"):
                    current = row[field]
                    if current is not None:
                        values[field] = round(float(current) * factor, 1)
                changed.append(f"amount (×{factor:g})")

            if new_description:
                values["food_items"] = json.dumps([
                    {"name": new_description, "quantity": 1, "unit": "serving"}
                ])
                changed.append("description")
            if new_meal and new_meal != row["meal_type"]:
                values["meal_type"] = new_meal
                changed.append(f"meal ({row['meal_type']} → {new_meal})")
            if new_logged_at is not None:
                values["logged_at"] = new_logged_at
                changed.append("time")

            if not values:
                return ToolResult(
                    success=False,
                    message="That entry already reads that way — nothing changed.",
                )

            assignments = ", ".join(f"{field} = :{field}" for field in values)
            values_with_keys = dict(values)
            values_with_keys.update({"id": log_id, "uid": user_id})
            result = db.execute(text(
                f"UPDATE food_log SET {assignments}, updated_at = NOW() "
                "WHERE id = :id AND user_id = :uid"
            ), values_with_keys)
            if not result.rowcount:
                db.rollback()
                return ToolResult(
                    success=False,
                    message="That food entry isn't there any more — nothing was changed.",
                )
            db.commit()

            after = db.execute(text(
                "SELECT meal_type, calories, protein, carbs, fats, logged_at "
                "FROM food_log WHERE id = :id"
            ), {"id": log_id}).mappings().first()

            summary = f"Fixed that entry: {', '.join(changed)}."
            if after["calories"] is not None:
                summary += f" Now {after['calories']:g} cal"
                if after["protein"] is not None:
                    summary += f", {after['protein']:g}g protein"
                summary += "."
            summary += f" Still one entry, at {describe_instant(as_utc(after['logged_at']))}."
            if time_note:
                summary += f" — {time_note}"

            return ToolResult(
                success=True,
                data={
                    "log_id": log_id,
                    "changed": changed,
                    "before": {
                        k: (v.isoformat() if hasattr(v, "isoformat") else v)
                        for k, v in before.items()
                    },
                    "after": {
                        "meal_type": after["meal_type"],
                        "calories": after["calories"],
                        "protein": after["protein"],
                        "carbs": after["carbs"],
                        "fats": after["fats"],
                        "logged_at": as_utc(after["logged_at"]).isoformat(),
                        "when": describe_instant(as_utc(after["logged_at"])),
                    },
                },
                message=summary,
            )
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to correct the entry: {e}")
        finally:
            db.close()
