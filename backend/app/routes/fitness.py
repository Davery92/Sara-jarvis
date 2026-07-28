"""
Fitness Routes
API endpoints for fitness tracking: notes, food logging, workouts
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, validator
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta, timezone
from app.core.timezone import naive_local_now
import uuid

from app.core.timezone import now as local_now
import logging
import re
import asyncio
import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.config import settings as app_settings
import httpx
import io

# Tool imports
from app.tools.fitness import (
    FitnessNoteCreateTool, FitnessNoteSearchTool, FitnessNoteEditTool,
    FoodLogCreateTool, FoodLogSearchTool, FoodLogSummaryTool,
    WorkoutListTool, WorkoutLogCreateTool, WorkoutStatsTool,
    RecoveryLogCreateTool, RecoveryLogGetTool, RecoveryLogRecentTool
)
from app.prompts.fitness_system_prompt import get_fitness_system_prompt
from app.main_simple import SimpleLLMClient
from app.tools.registry import ToolRegistry
from app.services.workout_session_service import workout_session_service
from app.services.phase_resolution import (
    annotate_effective_statuses,
    get_effective_phase,
    reconcile_active_program_phase_statuses,
)

logger = logging.getLogger(__name__)
router = APIRouter()

from app.services.event_bus import EventType


def _emit_domain_event_safe(event_type: "EventType", user_id: str, payload: dict) -> None:
    """Fire-and-forget domain event so Sara's cognitive system sees app activity
    (meal logged, workout done). A Redis/pubsub hiccup must never fail the
    underlying action, so this schedules the emit and swallows everything."""
    try:
        from app.services.event_bus import emit_event
        asyncio.ensure_future(emit_event(event_type, user_id, payload=payload, source="fitness_route"))
    except Exception as e:
        logger.debug(f"domain event emit failed ({event_type}): {e}")


# Simple message class for SimpleLLMClient compatibility
class SimpleMessage:
    """Simple message object compatible with SimpleLLMClient"""
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content

# Pydantic models for request/response
class FitnessNoteCreate(BaseModel):
    title: Optional[str] = ""
    content: str
    category: str  # nutrition, workout, goal, progress, general


class FitnessNoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None


class FoodItem(BaseModel):
    name: str
    quantity: float
    unit: str


VALID_MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack"}


class FoodLogCreate(BaseModel):
    meal_type: str  # breakfast, lunch, dinner, snack
    food_items: List[FoodItem]

    @validator("meal_type", pre=True)
    def validate_meal_type(cls, v):
        if not isinstance(v, str) or v.lower() not in VALID_MEAL_TYPES:
            return "snack"
        return v.lower()
    detailed_items: Optional[List[dict]] = None  # Detailed food items from food database
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None
    notes: Optional[str] = ""
    logged_at: Optional[str] = None


class WorkoutSetLog(BaseModel):
    workout_id: Optional[str] = None  # Optional now - can be auto-generated
    exercise_name: Optional[str] = None  # For quick logging without pre-existing workout
    exercise_id: Optional[str] = None
    template_exercise_id: Optional[str] = None  # Link to template_exercise for progression tracking
    set_index: int
    weight: Optional[float] = None
    reps: Optional[int] = None
    rpe: Optional[int] = None
    notes: Optional[str] = ""
    session_date: Optional[str] = None  # YYYY-MM-DD format
    session_time: Optional[str] = None  # Full ISO timestamp
    skipped: Optional[bool] = False  # Mark exercise as skipped


class WorkoutSetUpdate(BaseModel):
    """Model for PATCH updates - all fields optional"""
    weight: Optional[float] = None
    reps: Optional[int] = None
    rpe: Optional[int] = None
    notes: Optional[str] = None
    session_date: Optional[str] = None
    session_time: Optional[str] = None
    skipped: Optional[bool] = None


class FitnessChatRequest(BaseModel):
    message: str
    context: Optional[Dict[str, Any]] = {}


class NutritionGoals(BaseModel):
    calories: Optional[int] = 2000
    protein: Optional[int] = 150
    carbs: Optional[int] = 200
    fats: Optional[int] = 70


class RecoveryLogCreate(BaseModel):
    log_date: str  # YYYY-MM-DD format
    hrv: Optional[int] = None
    heart_rate: Optional[int] = None
    sleep_hours: Optional[float] = None
    soreness_level: Optional[int] = None  # 1-10
    body_weight: Optional[float] = None  # Body weight
    weight_unit: Optional[str] = "lbs"  # 'lbs' or 'kg'
    notes: Optional[str] = ""


class RecoveryLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    log_date: str
    hrv: Optional[int] = None
    heart_rate: Optional[int] = None
    sleep_hours: Optional[float] = None
    soreness_level: Optional[int] = None
    body_weight: Optional[float] = None
    weight_unit: Optional[str] = None
    notes: Optional[str] = None
    created_at: str
    updated_at: str
    # Server-computed readiness (single source of truth — app just displays it).
    readiness_score: Optional[int] = None
    readiness_label: Optional[str] = None
    readiness_status: Optional[str] = None
    readiness_color: Optional[str] = None


class IngredientItem(BaseModel):
    name: str
    # Optional: Sara's chat-based recipe tool stores freeform ingredient lines
    # she couldn't parse (e.g. "3/4 cup mayonnaise") as {name: <full line>,
    # quantity: None, unit: None} rather than failing to save the recipe.
    quantity: Optional[float] = None
    unit: Optional[str] = None  # g, oz, cup, tbsp, etc.
    # Optional manual nutrition override (per total quantity)
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None
    # Provenance for live-lookup ingredients (R1). Rides the existing JSON
    # column — old rows without these keys parse fine (all Optional).
    food_id: Optional[str] = None  # FatSecret food id, for re-resolve/audit
    source: Optional[str] = None  # "fatsecret" | "user" | "manual"
    serving_description: Optional[str] = None  # e.g. "1 cup, cooked"




class RecipeCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    category: Optional[str] = None  # breakfast, lunch, dinner, snack, dessert
    ingredients: List[IngredientItem]
    instructions: str
    prep_time_minutes: Optional[int] = None
    servings: int = 1


class RecipeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    ingredients: Optional[List[IngredientItem]] = None
    instructions: Optional[str] = None
    prep_time_minutes: Optional[int] = None
    servings: Optional[int] = None


class RecipeResponse(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str]
    category: Optional[str]
    ingredients: List[IngredientItem]
    instructions: str
    prep_time_minutes: Optional[int]
    servings: int
    calories: Optional[float]
    protein: Optional[float]
    carbs: Optional[float]
    fats: Optional[float]
    created_at: str
    updated_at: str


def get_current_user_id() -> str:
    """Get current user ID (simplified for now)"""
    # In production, this would come from JWT token
    import os
    return os.getenv("SOLO_USER_ID", "default-user")


# ============================================================================
# HELPER FUNCTIONS FOR MEMORY & DAILY LOGS
# ============================================================================

async def save_to_episodic_memory(
    db: Session,
    user_id: str,
    source: str,
    content: str,
    importance: float = 0.6
):
    """Save fitness activity to episodic memory"""
    try:
        episode_sql = text("""
            INSERT INTO episode (id, user_id, source, role, content, importance, created_at)
            VALUES (:id, :user_id, :source, :role, :content, :importance, :created_at)
        """)
        db.execute(episode_sql, {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "source": source,
            "role": "user",
            "content": content,
            "importance": importance,
            "created_at": datetime.now(timezone.utc)
        })
        db.commit()
        logger.info(f"💪 Saved {source} to episodic memory for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to save to episodic memory: {e}")
        db.rollback()


async def update_daily_log(
    db: Session,
    user_id: str,
    log_date: date,
    activity_type: str,
    nutrition_data: Optional[Dict] = None,
    workout_data: Optional[Dict] = None
):
    """Update or create fitness daily log"""
    try:
        # Check if log exists for this date
        check_sql = text("""
            SELECT id FROM fitness_daily_log
            WHERE user_id = :user_id AND log_date = :log_date
        """)
        result = db.execute(check_sql, {"user_id": user_id, "log_date": log_date})
        existing = result.fetchone()

        if existing:
            # Update existing log
            update_parts = ["updated_at = NOW()"]
            params = {"user_id": user_id, "log_date": log_date}

            if activity_type == "chat":
                update_parts.append("chat_count = chat_count + 1")
            elif activity_type == "food":
                update_parts.append("food_entries = food_entries + 1")
                if nutrition_data:
                    update_parts.append("total_calories = COALESCE(total_calories, 0) + :calories")
                    update_parts.append("total_protein = COALESCE(total_protein, 0) + :protein")
                    update_parts.append("total_carbs = COALESCE(total_carbs, 0) + :carbs")
                    update_parts.append("total_fats = COALESCE(total_fats, 0) + :fats")
                    params.update({
                        "calories": nutrition_data.get("calories", 0) or 0,
                        "protein": nutrition_data.get("protein", 0) or 0,
                        "carbs": nutrition_data.get("carbs", 0) or 0,
                        "fats": nutrition_data.get("fats", 0) or 0
                    })
            elif activity_type == "workout":
                update_parts.append("workout_sessions = workout_sessions + 1")
                if workout_data:
                    update_parts.append("total_sets = COALESCE(total_sets, 0) + 1")
                    if workout_data.get("reps"):
                        update_parts.append("total_reps = COALESCE(total_reps, 0) + :reps")
                        params["reps"] = workout_data["reps"]
            elif activity_type == "note":
                update_parts.append("notes_created = notes_created + 1")

            update_sql = text(f"""
                UPDATE fitness_daily_log
                SET {', '.join(update_parts)}
                WHERE user_id = :user_id AND log_date = :log_date
            """)
            db.execute(update_sql, params)
        else:
            # Create new log
            insert_sql = text("""
                INSERT INTO fitness_daily_log (
                    id, user_id, log_date,
                    chat_count, food_entries, workout_sessions, notes_created,
                    total_calories, total_protein, total_carbs, total_fats,
                    total_sets, total_reps,
                    created_at, updated_at
                )
                VALUES (
                    :id, :user_id, :log_date,
                    :chat_count, :food_entries, :workout_sessions, :notes_created,
                    :total_calories, :total_protein, :total_carbs, :total_fats,
                    :total_sets, :total_reps,
                    NOW(), NOW()
                )
            """)

            params = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "log_date": log_date,
                "chat_count": 1 if activity_type == "chat" else 0,
                "food_entries": 1 if activity_type == "food" else 0,
                "workout_sessions": 1 if activity_type == "workout" else 0,
                "notes_created": 1 if activity_type == "note" else 0,
                "total_calories": nutrition_data.get("calories") if nutrition_data else None,
                "total_protein": nutrition_data.get("protein") if nutrition_data else None,
                "total_carbs": nutrition_data.get("carbs") if nutrition_data else None,
                "total_fats": nutrition_data.get("fats") if nutrition_data else None,
                "total_sets": 1 if activity_type == "workout" else 0,
                "total_reps": workout_data.get("reps") if workout_data else 0
            }
            db.execute(insert_sql, params)

        db.commit()
        logger.info(f"📊 Updated daily log for {log_date} - {activity_type}")
    except Exception as e:
        logger.error(f"Failed to update daily log: {e}")
        db.rollback()


# ============================================================================
# FITNESS NOTES ENDPOINTS
# ============================================================================

@router.post("/notes")
async def create_fitness_note(
    note: FitnessNoteCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Create a fitness note - saves to episodic memory and daily log"""
    tool = FitnessNoteCreateTool()
    result = await tool.execute(
        user_id=user_id,
        title=note.title,
        content=note.content,
        category=note.category
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    # Save to episodic memory
    note_content = f"Created fitness note [{note.category}]: {note.title}\n{note.content}"
    await save_to_episodic_memory(db, user_id, "fitness_note", note_content)

    # Update daily log
    await update_daily_log(db, user_id, date.today(), "note")

    return result.data


@router.get("/notes/search")
async def search_fitness_notes(
    query: str,
    category: str = "all",
    limit: int = 10,
    user_id: str = Depends(get_current_user_id)
):
    """Search fitness notes"""
    tool = FitnessNoteSearchTool()
    result = await tool.execute(
        user_id=user_id,
        query=query,
        category=category,
        limit=limit
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return result.data


@router.patch("/notes/{note_id}")
async def update_fitness_note(
    note_id: str,
    updates: FitnessNoteUpdate,
    user_id: str = Depends(get_current_user_id)
):
    """Update a fitness note"""
    tool = FitnessNoteEditTool()

    # Build kwargs with only provided fields
    kwargs = {"note_id": note_id}
    if updates.title is not None:
        kwargs["title"] = updates.title
    if updates.content is not None:
        kwargs["content"] = updates.content
    if updates.category is not None:
        kwargs["category"] = updates.category

    result = await tool.execute(user_id=user_id, **kwargs)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return result.data


# ============================================================================
# FOOD LOG ENDPOINTS
# ============================================================================


@router.get("/food-log")
async def list_food_log(
    limit: int = 50,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """List recent food log entries"""
    try:
        import json as json_mod

        query = text("""
            SELECT id as log_id, user_id, meal_type, food_items, detailed_items, calories, protein, carbs, fats, notes, logged_at
            FROM food_log
            WHERE user_id = :user_id
            ORDER BY logged_at DESC
            LIMIT :limit
        """)

        result = db.execute(query, {"user_id": user_id, "limit": limit})
        entries = []
        for row in result:
            entry = dict(row._mapping)

            # Parse JSON fields that may come back as strings
            for json_field in ("food_items", "detailed_items"):
                val = entry.get(json_field)
                if isinstance(val, str):
                    try:
                        entry[json_field] = json_mod.loads(val)
                    except (json_mod.JSONDecodeError, TypeError):
                        entry[json_field] = []

            # Serialize logged_at to ISO string
            if entry.get("logged_at") and hasattr(entry["logged_at"], "isoformat"):
                entry["logged_at"] = entry["logged_at"].isoformat()

            entries.append(entry)
        return entries
    except Exception as e:
        logger.error(f"Failed to list food log: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/food-log")
async def create_food_log(
    log: FoodLogCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Log a meal - saves to episodic memory and daily log"""
    import json

    try:
        log_id = str(uuid.uuid4())
        food_items = [item.dict() for item in log.food_items] if log.food_items else []

        # Handle detailed_items if provided
        detailed_items_json = None
        if hasattr(log, 'detailed_items') and log.detailed_items:
            detailed_items_json = json.dumps(log.detailed_items)

        query = text("""
            INSERT INTO food_log (
                id, user_id, meal_type, food_items, detailed_items,
                calories, protein, carbs, fats, notes, logged_at
            ) VALUES (
                :id, :user_id, :meal_type, CAST(:food_items AS jsonb), CAST(:detailed_items AS jsonb),
                :calories, :protein, :carbs, :fats, :notes, :logged_at
            )
            RETURNING id
        """)

        # Use provided logged_at or current time in Eastern timezone
        # This prevents meals logged at night from appearing as next day
        from zoneinfo import ZoneInfo
        eastern = ZoneInfo("America/New_York")

        if log.logged_at:
            logged_at_time = log.logged_at
        else:
            # Get current time in Eastern timezone, then remove timezone info for storage
            logged_at_time = datetime.now(eastern).replace(tzinfo=None)

        result = db.execute(query, {
            "id": log_id,
            "user_id": user_id,
            "meal_type": log.meal_type,
            "food_items": json.dumps(food_items),
            "detailed_items": detailed_items_json,
            "calories": log.calories,
            "protein": log.protein,
            "carbs": log.carbs,
            "fats": log.fats,
            "notes": log.notes or "",
            "logged_at": logged_at_time
        })

        db.commit()

        # Save to episodic memory
        food_list = ", ".join([f"{item['name']} ({item['quantity']} {item['unit']})" for item in food_items])
        food_content = f"Logged {log.meal_type}: {food_list}"
        if log.calories:
            food_content += f" | {log.calories} cal"
        if log.protein:
            food_content += f", {log.protein}g protein"
        if log.notes:
            food_content += f" | Notes: {log.notes}"
        await save_to_episodic_memory(db, user_id, "fitness_food", food_content)

        # Update daily log
        nutrition_data = {
            "calories": log.calories,
            "protein": log.protein,
            "carbs": log.carbs,
            "fats": log.fats
        }
        await update_daily_log(db, user_id, date.today(), "food", nutrition_data=nutrition_data)

        # Tell Sara's cognitive system David just ate (contact + domain action).
        _emit_domain_event_safe(EventType.FOOD_LOGGED, user_id, {
            "meal_type": log.meal_type,
            "food": (food_items[0]["name"] if food_items else None),
            "calories": log.calories,
        })

        return {"success": True, "message": "Food logged successfully", "log_id": log_id}
    except Exception as e:
        logger.error(f"Failed to create food log: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/food-log/{log_id}")
async def update_food_log_entry(
    log_id: str,
    request: FoodLogCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Update a food log entry"""
    try:
        import json

        food_items = [item.dict() for item in request.food_items] if request.food_items else []

        # Handle detailed_items if provided
        detailed_items_json = None
        if hasattr(request, 'detailed_items') and request.detailed_items:
            detailed_items_json = json.dumps(request.detailed_items)

        query = text("""
            UPDATE food_log
            SET meal_type = :meal_type,
                food_items = CAST(:food_items AS jsonb),
                detailed_items = CAST(:detailed_items AS jsonb),
                calories = :calories,
                protein = :protein,
                carbs = :carbs,
                fats = :fats,
                notes = :notes,
                logged_at = :logged_at,
                updated_at = NOW()
            WHERE id = :log_id AND user_id = :user_id
            RETURNING id
        """)

        result = db.execute(query, {
            "log_id": log_id,
            "user_id": user_id,
            "meal_type": request.meal_type,
            "food_items": json.dumps(food_items),
            "detailed_items": detailed_items_json,
            "calories": request.calories,
            "protein": request.protein,
            "carbs": request.carbs,
            "fats": request.fats,
            "notes": request.notes or "",
            "logged_at": request.logged_at or naive_local_now()
        })

        updated = result.fetchone()
        db.commit()

        if not updated:
            raise HTTPException(status_code=404, detail="Food log entry not found")

        return {"success": True, "message": "Food log entry updated"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update food log entry: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/food-log/{log_id}")
async def patch_food_log_entry(
    log_id: str,
    updates: dict,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Partial update of a food log entry (e.g. change meal_type)"""
    try:
        allowed_fields = {"meal_type", "notes"}
        fields_to_update = {k: v for k, v in updates.items() if k in allowed_fields}

        if not fields_to_update:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        set_clauses = ", ".join(f"{k} = :{k}" for k in fields_to_update)
        query = text(f"""
            UPDATE food_log
            SET {set_clauses}, updated_at = NOW()
            WHERE id = :log_id AND user_id = :user_id
            RETURNING id
        """)

        fields_to_update["log_id"] = log_id
        fields_to_update["user_id"] = user_id

        result = db.execute(query, fields_to_update)
        updated = result.fetchone()
        db.commit()

        if not updated:
            raise HTTPException(status_code=404, detail="Food log entry not found")

        return {"success": True, "message": "Food log entry updated"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to patch food log entry: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/food-log/{log_id}")
async def delete_food_log_entry(
    log_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Delete a food log entry"""
    try:
        query = text("""
            DELETE FROM food_log
            WHERE id = :log_id AND user_id = :user_id
            RETURNING id
        """)

        result = db.execute(query, {"log_id": log_id, "user_id": user_id})
        deleted = result.fetchone()
        db.commit()

        if not deleted:
            raise HTTPException(status_code=404, detail="Food log entry not found")

        _emit_domain_event_safe(EventType.FOOD_DELETED, user_id, {"log_id": log_id})

        return {"success": True, "message": "Food log entry deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete food log entry: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/food-log/search")
async def search_food_logs(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    meal_type: str = "all",
    limit: int = 20,
    user_id: str = Depends(get_current_user_id)
):
    """Search food logs by date range"""
    tool = FoodLogSearchTool()
    result = await tool.execute(
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        meal_type=meal_type,
        limit=limit
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return result.data


@router.get("/food-log/summary")
async def get_food_log_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    period: str = "week",
    user_id: str = Depends(get_current_user_id)
):
    """Get nutrition summary"""
    tool = FoodLogSummaryTool()
    result = await tool.execute(
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        period=period
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return result.data


@router.get("/food-log/recent-foods")
async def get_recent_foods(
    limit: int = 20,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get recently logged foods for quick re-logging.
    Returns unique food items from detailed_items, ordered by frequency and recency.
    Like MyFitnessPal's recent foods feature.
    """
    from datetime import timedelta
    from collections import Counter

    try:
        # Get food logs from the last 30 days. Prefer rich detailed_items, but
        # fall back to food_items (name/qty/unit) so logs made before detailed_items
        # was populated still surface — for single-item logs the row-level macros
        # ARE that item's macros (multi-item logs can't be split, so macros stay null).
        thirty_days_ago = naive_local_now() - timedelta(days=30)

        query = text("""
            SELECT food_items, detailed_items, calories, protein, carbs, fats, logged_at
            FROM food_log
            WHERE user_id = :user_id
              AND logged_at >= :since
            ORDER BY logged_at DESC
        """)

        result = db.execute(query, {
            "user_id": user_id,
            "since": thirty_days_ago
        })

        def _parse_json_col(col):
            if isinstance(col, str):
                try:
                    return json.loads(col)
                except Exception:
                    return None
            return col

        # Extract unique foods and count frequency
        food_frequency = Counter()
        food_details = {}  # Store full details for each food
        food_last_logged = {}  # Track when each food was last logged

        for row in result.fetchall():
            logged_at = row.logged_at
            detailed = _parse_json_col(row.detailed_items)
            food_items = _parse_json_col(row.food_items)

            if detailed:
                items = detailed
                from_detailed = True
            elif food_items:
                items = food_items
                from_detailed = False
            else:
                continue

            # Row macros only map cleanly onto a single-item log.
            single_item = len(items) == 1

            for item in items:
                food_name = (item.get("name") or "").strip()
                if not food_name:
                    continue

                # Use food_id if available, otherwise name as key
                food_key = item.get("food_id") or food_name.lower()

                food_frequency[food_key] += 1

                # Store details (keep most recent version)
                if food_key not in food_details:
                    if from_detailed:
                        food_details[food_key] = {
                            "food_id": item.get("food_id"),
                            "id": item.get("id") or item.get("food_id"),
                            "name": food_name,
                            "calories": item.get("calculated_calories") or item.get("calories"),
                            "protein": item.get("calculated_protein") or item.get("protein"),
                            "carbs": item.get("calculated_carbs") or item.get("carbs"),
                            "fats": item.get("calculated_fats") or item.get("fats"),
                            "serving_description": item.get("serving_description"),
                            "serving_size": item.get("quantity") or item.get("serving_size") or 1,
                            "serving_unit": item.get("serving_unit") or item.get("selected_serving", {}).get("serving_description") or "serving",
                            "source": item.get("source", "history"),
                            "is_custom": item.get("is_custom", False)
                        }
                    else:
                        # food_items fallback: name/quantity/unit only.
                        food_details[food_key] = {
                            "food_id": item.get("food_id"),
                            "id": item.get("food_id"),
                            "name": food_name,
                            "calories": row.calories if single_item else None,
                            "protein": row.protein if single_item else None,
                            "carbs": row.carbs if single_item else None,
                            "fats": row.fats if single_item else None,
                            "serving_description": item.get("unit"),
                            "serving_size": item.get("quantity") or 1,
                            "serving_unit": item.get("unit") or "serving",
                            "source": "history",
                            "is_custom": False
                        }
                    food_last_logged[food_key] = logged_at

        # Sort by frequency (descending), then by recency
        sorted_foods = sorted(
            food_frequency.keys(),
            key=lambda k: (food_frequency[k], food_last_logged.get(k, datetime.min)),
            reverse=True
        )[:limit]

        # Build response with frequency info
        recent_foods = []
        for food_key in sorted_foods:
            details = food_details[food_key]
            details["count"] = food_frequency[food_key]  # How many times logged in last 30 days
            details["last_logged"] = food_last_logged.get(food_key).isoformat() if food_last_logged.get(food_key) else None
            recent_foods.append(details)

        return {
            "recent_foods": recent_foods,
            "total": len(recent_foods)
        }

    except Exception as e:
        logger.error(f"Error getting recent foods: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get recent foods: {str(e)}")


@router.get("/food-log/yesterday")
async def get_yesterday_foods(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get all foods logged yesterday, grouped by meal type.
    Useful for quick re-logging of similar meals.
    """
    from datetime import timedelta

    try:
        # Get yesterday's date range
        today = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today - timedelta(days=1)
        yesterday_end = today

        query = text("""
            SELECT id, meal_type, food_items, detailed_items, calories, protein, carbs, fats, logged_at
            FROM food_log
            WHERE user_id = :user_id
            AND logged_at >= :start
            AND logged_at < :end
            ORDER BY logged_at ASC
        """)

        result = db.execute(query, {
            "user_id": user_id,
            "start": yesterday_start,
            "end": yesterday_end
        })

        meals = {
            "breakfast": [],
            "lunch": [],
            "dinner": [],
            "snack": []
        }

        for row in result.fetchall():
            meal_type = row.meal_type or "snack"

            # Parse detailed_items
            detailed_items = row.detailed_items
            if isinstance(detailed_items, str):
                try:
                    detailed_items = json.loads(detailed_items)
                except:
                    detailed_items = []

            # Parse food_items
            food_items = row.food_items
            if isinstance(food_items, str):
                try:
                    food_items = json.loads(food_items)
                except:
                    food_items = []

            meal_entry = {
                "log_id": row.id,
                "meal_type": meal_type,
                "food_items": food_items,
                "detailed_items": detailed_items or [],
                "calories": row.calories,
                "protein": row.protein,
                "carbs": row.carbs,
                "fats": row.fats,
                "logged_at": row.logged_at.isoformat() if row.logged_at else None
            }

            if meal_type in meals:
                meals[meal_type].append(meal_entry)
            else:
                meals["snack"].append(meal_entry)

        # Also extract individual foods for easy re-logging
        all_foods = []
        for meal_type, entries in meals.items():
            for entry in entries:
                # Prefer detailed_items, but fall back to food_items if detailed_items is empty
                items_to_use = entry.get("detailed_items") or []
                if not items_to_use:
                    # Fall back to food_items and enrich with entry-level nutrition
                    food_items = entry.get("food_items") or []
                    # If there's only one food item, use the entry's nutrition
                    if len(food_items) == 1:
                        item = food_items[0]
                        normalized_food = {
                            "id": None,
                            "food_id": None,
                            "name": item.get("name"),
                            "calories": entry.get("calories"),
                            "protein": entry.get("protein"),
                            "carbs": entry.get("carbs"),
                            "fats": entry.get("fats"),
                            "serving_size": item.get("quantity") or 1,
                            "serving_unit": item.get("unit") or "serving",
                            "serving_description": item.get("unit"),
                            "source": "history",
                            "is_custom": False,
                            "meal_type": meal_type
                        }
                        all_foods.append(normalized_food)
                    else:
                        # Multiple food items without detailed nutrition - just include names
                        for item in food_items:
                            if item.get("name"):
                                normalized_food = {
                                    "id": None,
                                    "food_id": None,
                                    "name": item.get("name"),
                                    "calories": None,
                                    "protein": None,
                                    "carbs": None,
                                    "fats": None,
                                    "serving_size": item.get("quantity") or 1,
                                    "serving_unit": item.get("unit") or "serving",
                                    "serving_description": item.get("unit"),
                                    "source": "history",
                                    "is_custom": False,
                                    "meal_type": meal_type
                                }
                                all_foods.append(normalized_food)
                else:
                    for item in items_to_use:
                        if item.get("name"):
                            # Normalize the format for consistent frontend usage
                            normalized_food = {
                                "id": item.get("id") or item.get("food_id"),
                                "food_id": item.get("food_id"),
                                "name": item.get("name"),
                                "calories": item.get("calculated_calories") or item.get("calories"),
                                "protein": item.get("calculated_protein") or item.get("protein"),
                                "carbs": item.get("calculated_carbs") or item.get("carbs"),
                                "fats": item.get("calculated_fats") or item.get("fats"),
                                "serving_size": item.get("quantity") or item.get("serving_size") or 1,
                                "serving_unit": item.get("serving_unit") or item.get("selected_serving", {}).get("serving_description") or "serving",
                                "serving_description": item.get("serving_description") or item.get("selected_serving", {}).get("serving_description"),
                                "source": item.get("source", "history"),
                                "is_custom": item.get("is_custom", False),
                                "meal_type": meal_type
                            }
                            all_foods.append(normalized_food)

        return {
            "date": yesterday_start.strftime("%Y-%m-%d"),
            "meals": meals,
            "all_foods": all_foods,
            "total_foods": len(all_foods)
        }

    except Exception as e:
        logger.error(f"Error getting yesterday's foods: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get yesterday's foods: {str(e)}")


# ============================================================================
# WORKOUT LOG ENDPOINTS
# ============================================================================

def _attach_watch_heart_rate(db: Session, user_id: str, workouts_dict: dict, workout_windows: dict) -> None:
    """Meld Apple-Watch HR/calories onto each logged workout, matched by ET
    calendar day.

    Done at read time, so it always reflects the latest synced watch data — no
    persistence or reconcile job, and no race with the post-workout sync delay.
    Day-based (not strict time overlap) so it's robust to clock skew between
    Sara's logged set times and the watch. Prefers a strength-type watch workout,
    then the closest start time.
    """
    if not workout_windows:
        return
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    overall_start = min(w[0] for w in workout_windows.values()) - timedelta(days=1)
    overall_end = max(w[1] for w in workout_windows.values()) + timedelta(days=1)
    rows = db.execute(text("""
        SELECT activity_type, avg_heart_rate, max_heart_rate, min_heart_rate,
               total_energy_kcal, total_distance_m, duration_seconds, started_at
        FROM external_workout
        WHERE user_id = :uid AND started_at >= :start AND started_at <= :end
    """), {"uid": user_id, "start": overall_start, "end": overall_end}).fetchall()
    if not rows:
        return

    from app.services.workout_session_service import WorkoutSessionService
    names = WorkoutSessionService._ACTIVITY_NAMES
    strength_types = {"50", "35", "63"}

    for wid, (wstart, wend) in workout_windows.items():
        sess_day = wstart.astimezone(et).date()
        best = None
        best_key = (-1, 1.0)  # (is_strength, -gap_seconds)
        for r in rows:
            if r.started_at.astimezone(et).date() != sess_day:
                continue
            gap = abs((r.started_at - wstart).total_seconds())
            key = (1 if str(r.activity_type) in strength_types else 0, -gap)
            if best is None or key > best_key:
                best_key = key
                best = r
        if best is not None and wid in workouts_dict:
            workouts_dict[wid]["heart_rate"] = {
                "activity": names.get(str(best.activity_type), "Workout"),
                "avg_heart_rate": best.avg_heart_rate,
                "max_heart_rate": best.max_heart_rate,
                "min_heart_rate": best.min_heart_rate,
                "calories": round(float(best.total_energy_kcal)) if best.total_energy_kcal is not None else None,
                "distance_m": round(float(best.total_distance_m)) if best.total_distance_m is not None else None,
                "duration_min": round(best.duration_seconds / 60) if best.duration_seconds else None,
            }


@router.get("/exercises")
async def get_exercise_variants(
    movement: Optional[str] = None,
    for_exercise_name: Optional[str] = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Variant-history API — SARA_UNLEASHED Phase U.7 layer 2.

    Every variant David has ever logged for a movement pattern (e.g.
    horizontal_press: Flat DB Bench, ISO bench press, Barbell or Machine
    Chest Press, ...), each with last-performed date, last weight x reps,
    and PR — answered from workout_log at read time via the
    exercise_library link (migration 093). Omit `movement` to list every
    variant across all patterns.

    `for_exercise_name` is an alternative to `movement` for callers (the
    iOS Workout Mode picker) that only know the exercise/slot name, not the
    movement-pattern taxonomy: resolves it to a movement_pattern via an
    exact exercise_library match, falling back to the same keyword
    classifier used at seed time.
    """
    if for_exercise_name and not movement:
        row = db.execute(
            text("SELECT movement_pattern FROM exercise_library WHERE lower(name) = lower(:name)"),
            {"name": for_exercise_name.strip()},
        ).fetchone()
        if row:
            movement = row[0]
        else:
            from app.services.exercise_library_seed import classify
            movement, _equipment = classify(for_exercise_name)

    # LEFT JOIN from exercise_library, not workout_log: a variant just added
    # via "Add exercise..." (POST /exercises) has zero logged sets yet and
    # must still appear in the picker — an inner join from workout_log would
    # make a brand-new custom exercise invisible until its first set.
    query = """
        SELECT el.id as exercise_id, el.name, el.movement_pattern, el.equipment_required,
               wl.weight, wl.reps, wl.session_date, wl.created_at
        FROM exercise_library el
        LEFT JOIN workout_log wl ON wl.exercise_library_id = el.id AND wl.user_id = :uid
        WHERE 1=1
    """
    params: Dict[str, Any] = {"uid": user_id}
    if movement:
        query += " AND el.movement_pattern = :movement"
        params["movement"] = movement
    query += " ORDER BY el.id, COALESCE(wl.session_date, wl.created_at::date) DESC NULLS LAST, wl.created_at DESC NULLS LAST"

    rows = db.execute(text(query), params).fetchall()

    variants: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        vid = r.exercise_id
        if vid not in variants:
            equipment = r.equipment_required
            if isinstance(equipment, str):
                try:
                    equipment = json.loads(equipment)
                except (TypeError, ValueError):
                    equipment = []
            variants[vid] = {
                "exercise_id": vid,
                "name": r.name,
                "movement_pattern": r.movement_pattern,
                "equipment": equipment or [],
                "last_performed": None,
                "last_weight": None,
                "last_reps": None,
                "pr_weight": None,
                "pr_reps": None,
                "total_sets": 0,
            }
        v = variants[vid]
        if r.weight is None and r.reps is None and r.session_date is None and r.created_at is None and v["total_sets"] == 0:
            continue  # the LEFT JOIN's all-NULL row for a never-logged exercise
        v["total_sets"] += 1
        session_day = r.session_date or (r.created_at.date() if r.created_at else None)
        if v["last_performed"] is None:
            # First row for this variant in the DESC-ordered result = most recent.
            v["last_performed"] = session_day.isoformat() if session_day else None
            v["last_weight"] = r.weight
            v["last_reps"] = r.reps
        if r.weight is not None and (v["pr_weight"] is None or r.weight > v["pr_weight"]):
            v["pr_weight"] = r.weight
            v["pr_reps"] = r.reps

    result = sorted(variants.values(), key=lambda v: v["last_performed"] or "", reverse=True)
    return {"movement": movement, "variants": result}


@router.post("/exercises")
async def create_exercise_variant(
    request: Request,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Create a new exercise_library row inline — backs the Workout Mode
    picker's 'Add exercise...' action (U.7 layer 3). Movement is inherited
    from the slot the picker was opened from, not re-derived."""
    body = await request.json()
    name = (body.get("name") or "").strip()
    movement_pattern = (body.get("movement_pattern") or "").strip()
    equipment = body.get("equipment")
    if not name or not movement_pattern:
        raise HTTPException(status_code=400, detail="name and movement_pattern are required")

    existing = db.execute(
        text("SELECT id FROM exercise_library WHERE lower(name) = lower(:name)"),
        {"name": name},
    ).fetchone()
    if existing:
        return {"exercise_id": existing[0], "name": name, "created": False}

    new_id = str(uuid.uuid4())
    equipment_list = [equipment] if isinstance(equipment, str) and equipment else (equipment or [])
    db.execute(text("""
        INSERT INTO exercise_library (id, name, movement_pattern, equipment_required, created_at, updated_at)
        VALUES (:id, :name, :movement, CAST(:equipment AS json), NOW(), NOW())
    """), {
        "id": new_id, "name": name, "movement": movement_pattern,
        "equipment": json.dumps(equipment_list),
    })
    db.commit()
    return {"exercise_id": new_id, "name": name, "movement_pattern": movement_pattern, "created": True}


@router.get("/workouts")
async def list_workouts(
    status: str = "all",
    limit: int = 200,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    List workout sessions with their sets grouped together

    Returns workout sessions with all their exercise sets properly grouped.
    """
    from sqlalchemy import text
    from collections import defaultdict

    try:
        # Query workouts with their sets
        query = text("""
            SELECT
                w.id as workout_id,
                w.title,
                w.phase,
                w.week,
                w.day_of_week,
                w.duration_min,
                w.status,
                w.created_at as workout_created_at,
                wl.id as set_id,
                wl.exercise_id,
                wl.set_index,
                wl.weight,
                wl.reps,
                wl.rpe,
                wl.notes,
                wl.session_date,
                wl.session_time,
                wl.created_at as set_created_at
            FROM workout w
            LEFT JOIN workout_log wl ON w.id = wl.workout_id
            WHERE w.user_id = :user_id
            ORDER BY w.created_at DESC, wl.set_index ASC
            LIMIT :limit
        """)

        result = db.execute(query, {"user_id": user_id, "limit": limit})

        # Group sets by workout_id
        workouts_dict = {}
        workout_windows = {}  # workout_id -> [earliest_set_time, latest_set_time]
        for row in result.fetchall():
            workout_id = row.workout_id

            # Initialize workout entry if not exists
            if workout_id not in workouts_dict:
                workouts_dict[workout_id] = {
                    "id": workout_id,
                    "title": row.title,
                    "phase": row.phase,
                    "week": row.week,
                    "day_of_week": row.day_of_week,
                    "duration_min": row.duration_min,
                    "status": row.status,
                    "session_date": row.session_date.isoformat() if row.session_date else None,
                    "created_at": row.workout_created_at.isoformat() if row.workout_created_at else None,
                    "exercises": []
                }

            # Track this workout's time span from its set timestamps, for the
            # Apple-Watch HR meld below.
            st = row.session_time or row.set_created_at
            if st:
                w = workout_windows.get(workout_id)
                if w is None:
                    workout_windows[workout_id] = [st, st]
                else:
                    if st < w[0]:
                        w[0] = st
                    if st > w[1]:
                        w[1] = st

            # Add set to workout if set data exists
            if row.set_id:
                workouts_dict[workout_id]["exercises"].append({
                    "id": row.set_id,
                    "exercise_id": row.exercise_id,
                    "exercise_name": row.exercise_id,  # exercise_id actually stores the name
                    "set_index": row.set_index,
                    "weight": row.weight,
                    "reps": row.reps,
                    "rpe": row.rpe,
                    "notes": row.notes,
                    "session_date": row.session_date.isoformat() if row.session_date else None,
                    "session_time": row.session_time.isoformat() if row.session_time else None,
                    "created_at": row.set_created_at.isoformat() if row.set_created_at else None
                })

        # Meld Apple-Watch HR/calories onto each workout by time overlap.
        try:
            _attach_watch_heart_rate(db, user_id, workouts_dict, workout_windows)
        except Exception as e:
            logger.warning(f"Watch HR meld (history) failed: {e}")

        workouts = list(workouts_dict.values())
        return {"workouts": workouts, "total": len(workouts)}

    except Exception as e:
        logger.error(f"Error fetching workout logs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch workout logs: {str(e)}")


@router.post("/workout-log")
async def log_workout_set(
    log: WorkoutSetLog,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Log a workout set - saves to episodic memory and daily log

    Supports two modes:
    1. Structured: Provide workout_id for pre-existing workouts
    2. Quick logging: Provide exercise_name, auto-creates workout entry

    New features:
    - skipped: Mark an exercise as skipped (logs but no weight/reps required)
    - template_exercise_id: Link to template for progression tracking
    - PR detection: Automatically checks and records personal records
    """
    import uuid
    from sqlalchemy import text
    from datetime import datetime

    # Handle skipped exercises
    if log.skipped:
        # Create a skipped entry in workout_log
        log_id = str(uuid.uuid4())
        exercise_label = log.exercise_name or log.exercise_id or "exercise"

        db.execute(text("""
            INSERT INTO workout_log (id, user_id, exercise_id, set_index, skipped, template_exercise_id, notes, session_date, created_at)
            VALUES (:id, :user_id, :exercise_id, :set_index, true, :template_exercise_id, :notes, :session_date, CURRENT_TIMESTAMP)
        """), {
            "id": log_id,
            "user_id": user_id,
            "exercise_id": log.exercise_id or log.exercise_name,
            "set_index": log.set_index,
            "template_exercise_id": log.template_exercise_id,
            "notes": log.notes or "Skipped",
            "session_date": log.session_date or date.today().isoformat()
        })
        db.commit()

        # Save to episodic memory
        await save_to_episodic_memory(db, user_id, "fitness_workout", f"Skipped {exercise_label}")

        return {
            "success": True,
            "set_id": log_id,
            "message": f"Marked {exercise_label} as skipped",
            "skipped": True
        }

    # Let the WorkoutLogCreateTool handle workout creation
    # It will auto-create or reuse today's workout with consistent title format
    # Don't create workout here to avoid conflicts

    # Now log the set using the tool - it will auto-create/reuse today's workout
    # DEBUG: Log what we're receiving
    logger.info(f"📥 Received workout log request - session_date: {log.session_date}, session_time: {log.session_time}")

    tool = WorkoutLogCreateTool()
    result = await tool.execute(
        user_id=user_id,
        exercise_id=log.exercise_id or log.exercise_name,  # Use exercise_name as exercise_id if not provided
        set_index=log.set_index,
        weight=log.weight,
        reps=log.reps,
        rpe=log.rpe,
        notes=log.notes,
        session_date=log.session_date,
        session_time=log.session_time
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    # Update the workout_log entry with template_exercise_id if provided
    if log.template_exercise_id and result.data and result.data.get("set_id"):
        db.execute(text("""
            UPDATE workout_log SET template_exercise_id = :template_exercise_id
            WHERE id = :set_id
        """), {"template_exercise_id": log.template_exercise_id, "set_id": result.data["set_id"]})
        db.commit()

    # Check for PR if we have weight and reps
    pr_result = None
    exercise_label = log.exercise_name or log.exercise_id or "exercise"
    if log.weight and log.reps and log.weight > 0 and log.reps > 0:
        session_date = datetime.strptime(log.session_date, "%Y-%m-%d").date() if log.session_date else date.today()
        pr_result = await check_and_record_pr(
            db=db,
            user_id=user_id,
            exercise_name=exercise_label,
            weight=log.weight,
            reps=log.reps,
            achieved_at=session_date,
            workout_set_id=result.data.get("set_id") if result.data else None
        )
        db.commit()

    # Save to episodic memory
    workout_content = f"Logged {exercise_label} set #{log.set_index}"
    if log.weight:
        workout_content += f" | {log.weight} lbs"
    if log.reps:
        workout_content += f" x {log.reps} reps"
    if log.rpe:
        workout_content += f" (RPE: {log.rpe})"
    if log.notes:
        workout_content += f" | Notes: {log.notes}"
    if pr_result and pr_result.get("is_pr"):
        workout_content += f" | 🏆 NEW PR! Est. 1RM: {pr_result['estimated_1rm']} lbs"
    await save_to_episodic_memory(db, user_id, "fitness_workout", workout_content)

    # Update daily log
    workout_data = {"reps": log.reps}
    await update_daily_log(db, user_id, date.today(), "workout", workout_data=workout_data)

    # Add PR info to response
    response_data = result.data or {}
    if pr_result:
        response_data["pr"] = pr_result

    _emit_domain_event_safe(EventType.WORKOUT_LOGGED, user_id, {
        "type": exercise_label,
        "set_index": log.set_index,
        "is_pr": bool(pr_result and pr_result.get("is_pr")),
    })

    return response_data


@router.patch("/workout-log/{set_id}")
async def update_workout_set(
    set_id: str,
    updates: WorkoutSetUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Update an existing workout set"""
    from sqlalchemy import text

    try:
        # Build UPDATE SQL dynamically for fields that are provided
        update_fields = []
        params = {"set_id": set_id, "user_id": user_id}

        if updates.weight is not None:
            update_fields.append("weight = :weight")
            params["weight"] = updates.weight

        if updates.reps is not None:
            update_fields.append("reps = :reps")
            params["reps"] = updates.reps

        if updates.rpe is not None:
            update_fields.append("rpe = :rpe")
            params["rpe"] = updates.rpe

        if updates.notes is not None:
            update_fields.append("notes = :notes")
            params["notes"] = updates.notes

        # Handle session_date if provided
        if updates.session_date:
            update_fields.append("session_date = :session_date")
            params["session_date"] = updates.session_date

        # Handle session_time if provided
        if updates.session_time:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            try:
                # Parse as naive datetime (no timezone), then localize to Eastern
                if 'Z' in updates.session_time or '+' in updates.session_time:
                    # Has timezone info, parse directly
                    session_time = datetime.fromisoformat(updates.session_time.replace('Z', '+00:00'))
                else:
                    # No timezone info - treat as Eastern time
                    naive_dt = datetime.fromisoformat(updates.session_time)
                    eastern = ZoneInfo("America/New_York")
                    session_time = naive_dt.replace(tzinfo=eastern)

                update_fields.append("session_time = :session_time")
                params["session_time"] = session_time
                logger.info(f"🕐 PATCH session_time: {updates.session_time} → {session_time}")
            except (ValueError, AttributeError) as e:
                # If parsing fails, skip updating session_time
                logger.warning(f"⚠️  Failed to parse session_time in PATCH: {e}")
                pass

        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")

        update_sql = text(f"""
            UPDATE workout_log
            SET {', '.join(update_fields)}
            WHERE id = :set_id AND user_id = :user_id
            RETURNING id, exercise_id, set_index, weight, reps, rpe, session_date, session_time
        """)

        result = db.execute(update_sql, params)
        row = result.fetchone()
        db.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Workout set not found")

        return {
            "id": row.id,
            "exercise_id": row.exercise_id,
            "set_index": row.set_index,
            "weight": row.weight,
            "reps": row.reps,
            "rpe": row.rpe,
            "session_date": row.session_date.isoformat() if row.session_date else None,
            "session_time": row.session_time.isoformat() if row.session_time else None
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update workout set: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/workouts/{workout_set_id}")
async def delete_workout_set(
    workout_set_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Delete a workout set or entire workout session

    If workout_set_id is a workout ID, deletes the entire workout and all associated sets.
    If workout_set_id is a workout_log ID, deletes just that individual set.
    """
    from sqlalchemy import text

    try:
        # First try to delete as a workout (will cascade delete all workout_log entries)
        delete_workout_sql = text("""
            DELETE FROM workout
            WHERE id = :workout_id AND user_id = :user_id
        """)
        result = db.execute(delete_workout_sql, {"workout_id": workout_set_id, "user_id": user_id})

        if result.rowcount > 0:
            # Also delete associated workout_log entries
            delete_logs_sql = text("""
                DELETE FROM workout_log
                WHERE workout_id = :workout_id AND user_id = :user_id
            """)
            db.execute(delete_logs_sql, {"workout_id": workout_set_id, "user_id": user_id})
            db.commit()
            return {"success": True, "message": "Workout session deleted"}

        # If not a workout, try to delete as a workout_log entry
        delete_set_sql = text("""
            DELETE FROM workout_log
            WHERE id = :set_id AND user_id = :user_id
        """)
        result = db.execute(delete_set_sql, {"set_id": workout_set_id, "user_id": user_id})
        db.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Workout or set not found")

        return {"success": True, "message": "Workout set deleted"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete workout set: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/workouts/{workout_set_id}")
async def update_workout_set(
    workout_set_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Update a workout set"""
    from sqlalchemy import text

    try:
        # Get the request body
        request_data = await request.json()

        # Build dynamic UPDATE query based on provided fields
        updates = []
        params = {"set_id": workout_set_id, "user_id": user_id}

        if "weight" in request_data and request_data["weight"] is not None:
            updates.append("weight = :weight")
            params["weight"] = request_data["weight"]
        if "reps" in request_data and request_data["reps"] is not None:
            updates.append("reps = :reps")
            params["reps"] = request_data["reps"]
        if "rpe" in request_data and request_data["rpe"] is not None:
            updates.append("rpe = :rpe")
            params["rpe"] = request_data["rpe"]
        if "notes" in request_data and request_data["notes"] is not None:
            updates.append("notes = :notes")
            params["notes"] = request_data["notes"]
        if "created_at" in request_data and request_data["created_at"] is not None:
            updates.append("created_at = :created_at")
            params["created_at"] = request_data["created_at"]

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        update_sql = text(f"""
            UPDATE workout_log
            SET {', '.join(updates)}
            WHERE id = :set_id AND user_id = :user_id
        """)
        result = db.execute(update_sql, params)
        db.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Workout set not found")

        return {"success": True, "message": "Workout set updated"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update workout set: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workout-log/stats")
async def get_workout_stats(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    period: str = "week",
    user_id: str = Depends(get_current_user_id)
):
    """Get workout statistics"""
    tool = WorkoutStatsTool()
    result = await tool.execute(
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        period=period
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return result.data


@router.get("/weight-suggestion")
async def get_weight_suggestion(
    exercise_name: str,
    template_id: Optional[str] = None,
    target_reps: int = 10,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get AI weight suggestion for an exercise

    Uses progressive overload logic based on:
    - Exercise history (last 4 weeks)
    - RPE trends
    - Recovery metrics
    - Template starting weights (if provided)
    """
    try:
        import json
        from app.services.progressive_overload import suggest_weight

        logger.info(f"Weight suggestion requested: exercise={exercise_name}, template_id={template_id}, user_id={user_id}")

        # Get template starting weights if template_id provided
        starting_weight = None
        if template_id:
            template_query = text("""
                SELECT starting_weights
                FROM fitness_template
                WHERE id = :template_id AND user_id = :user_id
            """)
            template = db.execute(template_query, {
                "template_id": template_id,
                "user_id": user_id
            }).fetchone()

            logger.info(f"Template lookup result: found={template is not None}")

            if template and template.starting_weights:
                try:
                    starting_weights_dict = template.starting_weights
                    starting_weight = starting_weights_dict.get(exercise_name)
                    logger.info(f"Starting weights from template: {starting_weights_dict}, for {exercise_name}: {starting_weight}")
                except Exception as e:
                    logger.error(f"Error parsing starting_weights: {e}")
                    pass

        # Morning recovery snapshot (frozen at the AM sync — not intraday).
        from app.services.progressive_overload import get_morning_recovery
        recovery_data = get_morning_recovery(db, user_id, date.today())

        # Generate AI suggestion
        suggestion = suggest_weight(
            db=db,
            user_id=user_id,
            exercise_name=exercise_name,
            target_reps=target_reps,
            recovery_data=recovery_data,
            starting_weight=starting_weight
        )

        logger.info(f"Weight suggestion result: {suggestion}")
        return suggestion

    except Exception as e:
        logger.error(f"Failed to get weight suggestion: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# ============================================================================
# FITNESS CHAT ENDPOINT
# ============================================================================

@router.post("/chat")
async def fitness_chat(
    request: FitnessChatRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Chat with fitness-focused Sara - with full fitness context access"""
    try:
        import httpx
        import os
        from datetime import datetime, timedelta
        import uuid
        import json

        # Get LLM configuration
        OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://100.104.68.115:8081/v1")
        OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "dummy")
        OPENAI_MODEL = os.getenv("OPENAI_MODEL", "Qwen3.5-35B-A3B")

        # ===== GATHER FITNESS CONTEXT =====

        # 1. Get custom system prompt from settings
        custom_prompt_result = db.execute(text("""
            SELECT system_prompt FROM fitness_settings WHERE user_id = :user_id
        """), {"user_id": user_id}).fetchone()
        custom_prompt = custom_prompt_result[0] if custom_prompt_result and custom_prompt_result[0] else None

        # 2. Get nutrition goals
        goals_result = db.execute(text("""
            SELECT calories, protein, carbs, fats FROM fitness_goals WHERE user_id = :user_id
        """), {"user_id": user_id}).fetchone()
        goals = dict(goals_result._mapping) if goals_result else None

        # 3. Get the dated phase of the already-approved active program.
        active_phase = get_effective_phase(db, user_id, local_now().date())

        # 4. Get today's scheduled templates
        today_dow = naive_local_now().strftime('%A').lower()
        templates_result = db.execute(text("""
            SELECT id, name, scheduled_days, exercises, notes
            FROM fitness_template
            WHERE user_id = :user_id
              AND (phase_id = :phase_id OR phase_id IS NULL)
              AND (:today = ANY(string_to_array(scheduled_days::text, ','))
                  OR scheduled_days::text LIKE :today_pattern)
        """), {
            "user_id": user_id,
            "phase_id": active_phase["id"] if active_phase else None,
            "today": today_dow,
            "today_pattern": f'%{today_dow}%',
        }).fetchall()
        todays_templates = [dict(t._mapping) for t in templates_result]

        # 5. Get recent workouts (last 7 days) - grouped by session
        week_ago = naive_local_now() - timedelta(days=7)
        recent_workouts = db.execute(text("""
            SELECT session_date, COUNT(DISTINCT exercise_id) as exercise_count,
                   STRING_AGG(DISTINCT notes, '; ') as notes
            FROM workout_log
            WHERE user_id = :user_id AND session_date >= :week_ago AND session_date IS NOT NULL
              AND voided_at IS NULL
            GROUP BY session_date
            ORDER BY session_date DESC LIMIT 10
        """), {"user_id": user_id, "week_ago": week_ago.date()}).fetchall()
        recent_workouts_list = [dict(w._mapping) for w in recent_workouts]

        # 6. Get recent food logs (last 3 days)
        three_days_ago = naive_local_now() - timedelta(days=3)
        recent_food = db.execute(text("""
            SELECT DATE(logged_at) as log_date, meal_type, food_items,
                   calories, protein, carbs, fats
            FROM food_log
            WHERE user_id = :user_id AND logged_at >= :three_days_ago
            ORDER BY logged_at DESC LIMIT 15
        """), {"user_id": user_id, "three_days_ago": three_days_ago}).fetchall()
        recent_food_list = [dict(f._mapping) for f in recent_food]

        # 7. Get recent fitness notes
        recent_notes = db.execute(text("""
            SELECT category, content, created_at
            FROM fitness_note
            WHERE user_id = :user_id
            ORDER BY created_at DESC LIMIT 10
        """), {"user_id": user_id}).fetchall()
        recent_notes_list = [dict(n._mapping) for n in recent_notes]

        # 8. Get recent recovery data (last 7 days)
        recovery_result = db.execute(text("""
            SELECT log_date, hrv, heart_rate, sleep_hours, soreness_level, notes
            FROM daily_recovery_log
            WHERE user_id = :user_id
            ORDER BY log_date DESC LIMIT 7
        """), {"user_id": user_id}).fetchall()
        recent_recovery = [dict(r._mapping) for r in recovery_result]

        # 9. Get conversation history (last 20 messages)
        history = db.execute(text("""
            SELECT role, content, created_at
            FROM episode
            WHERE user_id = :user_id AND source = 'fitness_chat'
            ORDER BY created_at DESC LIMIT 20
        """), {"user_id": user_id}).fetchall()
        conversation_history = [{"role": h[0], "content": h[1]} for h in reversed(history)]

        # ===== BUILD CONTEXT-RICH SYSTEM PROMPT =====

        context_prompt = get_fitness_system_prompt()

        # Add custom prompt if available
        if custom_prompt:
            context_prompt = f"{custom_prompt}\n\n{context_prompt}"

        # Add personalized context
        context_sections = []

        if goals:
            context_sections.append(f"""
**YOUR NUTRITION GOALS:**
- Daily Calories: {goals['calories']}
- Protein: {goals['protein']}g
- Carbs: {goals['carbs']}g
- Fats: {goals['fats']}g
""")

        if active_phase:
            context_sections.append(f"""
**CURRENT TRAINING PHASE:**
- Phase: {active_phase['name']}
- Goal: {active_phase['goal']}
- Dates: {active_phase.get('start_date', 'Not set')} to {active_phase.get('end_date', 'Not set')}
- Notes: {active_phase.get('notes', 'None')}
""")

        if todays_templates:
            templates_text = "\n".join([
                f"  • {t['name']}: {len(json.loads(t['exercises']) if isinstance(t['exercises'], str) else t['exercises'])} exercises"
                for t in todays_templates
            ])
            context_sections.append(f"""
**TODAY'S SCHEDULED WORKOUTS ({today_dow.upper()}):**
{templates_text}
""")

        if recent_workouts_list:
            workouts_text = "\n".join([
                f"  • {w['session_date']}: {w.get('exercise_count', 0)} exercises - {w.get('notes', 'No notes') or 'No notes'}"
                for w in recent_workouts_list[:5]
            ])
            context_sections.append(f"""
**RECENT WORKOUTS (Last 7 days):**
{workouts_text}
""")

        if recent_food_list:
            food_text = "\n".join([
                f"  • {f['log_date']} ({f['meal_type']}): {int(f['calories'] or 0)} cal, {int(f['protein'] or 0)}g protein"
                for f in recent_food_list[:5]
            ])
            context_sections.append(f"""
**RECENT MEALS (Last 3 days):**
{food_text}
""")

        if recent_notes_list:
            notes_text = "\n".join([
                f"  • [{n['category']}] {n['content'][:100]}..."
                for n in recent_notes_list[:3]
            ])
            context_sections.append(f"""
**RECENT FITNESS NOTES:**
{notes_text}
""")

        if recent_recovery:
            # Get today's recovery data (first in list)
            today_recovery = recent_recovery[0] if recent_recovery else None

            # Calculate recovery averages
            hrv_values = [r['hrv'] for r in recent_recovery if r['hrv'] is not None]
            hr_values = [r['heart_rate'] for r in recent_recovery if r['heart_rate'] is not None]
            sleep_values = [r['sleep_hours'] for r in recent_recovery if r['sleep_hours'] is not None]
            soreness_values = [r['soreness_level'] for r in recent_recovery if r['soreness_level'] is not None]

            avg_hrv = sum(hrv_values) / len(hrv_values) if hrv_values else None
            avg_hr = sum(hr_values) / len(hr_values) if hr_values else None
            avg_sleep = sum(sleep_values) / len(sleep_values) if sleep_values else None
            avg_soreness = sum(soreness_values) / len(soreness_values) if soreness_values else None

            recovery_text = []
            if today_recovery:
                recovery_text.append(f"**Today's Recovery Status ({today_recovery['log_date']}):**")
                if today_recovery['hrv']:
                    recovery_text.append(f"  • HRV: {today_recovery['hrv']} ms")
                if today_recovery['heart_rate']:
                    recovery_text.append(f"  • Resting HR: {today_recovery['heart_rate']} bpm")
                if today_recovery['sleep_hours']:
                    recovery_text.append(f"  • Sleep: {today_recovery['sleep_hours']} hours")
                if today_recovery['soreness_level']:
                    soreness_desc = "Fresh" if today_recovery['soreness_level'] <= 2 else \
                                   "Minimal" if today_recovery['soreness_level'] <= 4 else \
                                   "Moderate" if today_recovery['soreness_level'] <= 6 else \
                                   "High" if today_recovery['soreness_level'] <= 8 else "Very High"
                    recovery_text.append(f"  • Soreness: {today_recovery['soreness_level']}/10 ({soreness_desc})")
                if today_recovery['notes']:
                    recovery_text.append(f"  • Notes: {today_recovery['notes']}")

            if len(recent_recovery) > 1:
                recovery_text.append(f"\n**7-Day Recovery Averages:**")
                if avg_hrv:
                    recovery_text.append(f"  • Avg HRV: {avg_hrv:.0f} ms")
                if avg_hr:
                    recovery_text.append(f"  • Avg Resting HR: {avg_hr:.0f} bpm")
                if avg_sleep:
                    recovery_text.append(f"  • Avg Sleep: {avg_sleep:.1f} hours")
                if avg_soreness:
                    recovery_text.append(f"  • Avg Soreness: {avg_soreness:.1f}/10")

            context_sections.append("\n".join(recovery_text))

        # Combine everything
        full_context = context_prompt + "\n\n" + "\n".join(context_sections)

        # ===== BUILD MESSAGES WITH HISTORY =====

        messages = [{"role": "system", "content": full_context}]

        # Add conversation history (keep last 10 exchanges)
        messages.extend(conversation_history[-10:])

        # Add current user message
        messages.append({"role": "user", "content": request.message})

        # ===== SAVE USER MESSAGE =====

        user_episode_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO episode (id, user_id, source, role, content, importance, created_at)
            VALUES (:id, :user_id, :source, :role, :content, :importance, :created_at)
        """), {
            "id": user_episode_id,
            "user_id": user_id,
            "source": "fitness_chat",
            "role": "user",
            "content": request.message,
            "importance": 0.6,
            "created_at": datetime.now(timezone.utc)
        })
        db.commit()

        # ===== PREPARE FITNESS TOOLS =====

        from app.tools.fitness import (
            FitnessNoteCreateTool, FitnessNoteSearchTool, FitnessNoteEditTool,
            FoodLogCreateTool, FoodLogSearchTool, FoodLogSummaryTool,
            WorkoutListTool, WorkoutLogCreateTool, WorkoutStatsTool,
            RecoveryLogCreateTool, RecoveryLogGetTool, RecoveryLogRecentTool,
            TemplateListTool, TemplateGetTool, TemplateUpdateTool,
            ProgramListTool, ProgramGetTool,
            PhaseListTool, PhaseGetTool, PhaseUpdateTool, PhaseActivateTool,
            TrainingScheduleTool
        )
        from app.tools.fitness.food_search_log import FoodSearchAndLogTool

        # Create tool instances
        fitness_tools = [
            FitnessNoteCreateTool(), FitnessNoteSearchTool(), FitnessNoteEditTool(),
            FoodSearchAndLogTool(),  # Natural language food logging with USDA search
            FoodLogCreateTool(), FoodLogSearchTool(), FoodLogSummaryTool(),
            WorkoutListTool(), WorkoutLogCreateTool(), WorkoutStatsTool(),
            RecoveryLogCreateTool(), RecoveryLogGetTool(), RecoveryLogRecentTool(),
            TemplateListTool(), TemplateGetTool(), TemplateUpdateTool(),
            ProgramListTool(), ProgramGetTool(),
            PhaseListTool(), PhaseGetTool(), PhaseUpdateTool(), PhaseActivateTool(),
            TrainingScheduleTool()
        ]

        # Get tool schemas
        tools_schemas = [tool.to_openai_schema() for tool in fitness_tools]

        # ===== CALL LLM WITH SimpleLLMClient (includes XML filtering) =====

        logger.info(f"💪 Fitness chat starting with {len(messages)} context messages")

        # Convert messages to SimpleMessage objects for SimpleLLMClient
        message_objects = [SimpleMessage(msg["role"], msg["content"]) for msg in messages]

        # Use SimpleLLMClient which handles XML filtering, multi-round tool calling
        llm_client = SimpleLLMClient()

        final_response = await llm_client.chat_with_tools(
            messages=message_objects,
            tools=tools_schemas,
            user_id=user_id,
            conversation_id=f"fitness_{user_id}"
        )

        # Remove any remaining XML tags from the response
        final_response = re.sub(r'<tool_call>.*?</tool_call>', '', final_response, flags=re.DOTALL).strip()
        final_response = re.sub(r'<[^>]+>', '', final_response).strip()

        logger.info(f"✅ Fitness chat complete, response length: {len(final_response)}")

        # Save Sara's response to memory
        db.execute(text("""
            INSERT INTO episode (id, user_id, source, role, content, importance, created_at)
            VALUES (:id, :user_id, :source, :role, :content, :importance, :created_at)
        """), {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "source": "fitness_chat",
            "role": "assistant",
            "content": final_response,
            "importance": 0.6,
            "created_at": datetime.now(timezone.utc)
        })
        db.commit()

        logger.info(f"💪 Fitness chat complete for user {user_id}")

        # Update daily log
        await update_daily_log(db, user_id, date.today(), "chat")

        return {
            "response": final_response,
            "model": OPENAI_MODEL
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fitness chat error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def fitness_chat_stream(
    request: FitnessChatRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Streaming fitness chat endpoint"""
    try:
        from app.tools.fitness.template_tools import TemplateListTool, TemplateGetTool
        from app.core.config import settings
        import logging

        logger = logging.getLogger("app.main_simple")
        logger.info(f"🏋️ Fitness chat: user_id={user_id}, type={type(user_id)}")

        OPENAI_MODEL = settings.openai_model
        ASSISTANT_NAME = settings.assistant_name

        # Build context (same as non-streaming version)
        context_prompt = get_fitness_system_prompt()

        # Get conversation history
        history_result = db.execute(text("""
            SELECT role, content
            FROM episode
            WHERE user_id = :user_id AND source = 'fitness_chat'
            ORDER BY created_at DESC
            LIMIT 20
        """), {"user_id": user_id})

        conversation_history = []
        for row in reversed(list(history_result.fetchall())):
            conversation_history.append({"role": row.role, "content": row.content})

        # Build messages
        messages = [{"role": "system", "content": context_prompt}]
        messages.extend(conversation_history[-10:])
        messages.append({"role": "user", "content": request.message})

        # Save user message
        user_episode_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO episode (id, user_id, source, role, content, importance, created_at)
            VALUES (:id, :user_id, :source, :role, :content, :importance, :created_at)
        """), {
            "id": user_episode_id,
            "user_id": user_id,
            "source": "fitness_chat",
            "role": "user",
            "content": request.message,
            "importance": 0.6,
            "created_at": datetime.now(timezone.utc)
        })
        db.commit()

        # Prepare fitness tools
        from app.tools.fitness import (
            FitnessNoteCreateTool, FitnessNoteSearchTool, FitnessNoteEditTool,
            FoodLogCreateTool, FoodLogSearchTool, FoodLogSummaryTool,
            WorkoutListTool, WorkoutLogCreateTool, WorkoutStatsTool,
            RecoveryLogCreateTool, RecoveryLogGetTool, RecoveryLogRecentTool,
            TemplateListTool, TemplateGetTool, TemplateUpdateTool,
            ProgramListTool, ProgramGetTool,
            PhaseListTool, PhaseGetTool, PhaseUpdateTool, PhaseActivateTool,
            TrainingScheduleTool
        )
        from app.tools.fitness.food_search_log import FoodSearchAndLogTool

        fitness_tools = [
            FitnessNoteCreateTool(), FitnessNoteSearchTool(), FitnessNoteEditTool(),
            FoodSearchAndLogTool(),
            FoodLogCreateTool(), FoodLogSearchTool(), FoodLogSummaryTool(),
            WorkoutListTool(), WorkoutLogCreateTool(), WorkoutStatsTool(),
            RecoveryLogCreateTool(), RecoveryLogGetTool(), RecoveryLogRecentTool(),
            TemplateListTool(), TemplateGetTool(), TemplateUpdateTool(),
            ProgramListTool(), ProgramGetTool(),
            PhaseListTool(), PhaseGetTool(), PhaseUpdateTool(), PhaseActivateTool(),
            TrainingScheduleTool()
        ]

        tools_schemas = [tool.to_openai_schema() for tool in fitness_tools]

        async def generate_events():
            try:
                # Create event queue for streaming
                event_queue = asyncio.Queue()

                # Set up streaming LLM client
                streaming_client = SimpleLLMClient()
                streaming_client.set_event_queue(event_queue)

                # Convert messages to SimpleMessage objects
                message_objects = [SimpleMessage(msg["role"], msg["content"]) for msg in messages]

                # Start LLM processing in background task
                async def process_chat():
                    response_content = await streaming_client.chat_with_tools(
                        messages=message_objects,
                        tools=tools_schemas,
                        user_id=user_id,
                        conversation_id=f"fitness_{user_id}"
                    )

                    # Clean up XML tags
                    response_content = re.sub(r'<tool_call>.*?</tool_call>', '', response_content, flags=re.DOTALL).strip()
                    response_content = re.sub(r'<[^>]+>', '', response_content).strip()

                    # Save Sara's response to memory
                    db.execute(text("""
                        INSERT INTO episode (id, user_id, source, role, content, importance, created_at)
                        VALUES (:id, :user_id, :source, :role, :content, :importance, :created_at)
                    """), {
                        "id": str(uuid.uuid4()),
                        "user_id": user_id,
                        "source": "fitness_chat",
                        "role": "assistant",
                        "content": response_content,
                        "importance": 0.6,
                        "created_at": datetime.now(timezone.utc)
                    })
                    db.commit()

                    # Update daily log
                    await update_daily_log(db, user_id, date.today(), "chat")

                    await event_queue.put({
                        "type": "final_response",
                        "data": {
                            "content": response_content,
                            "timestamp": local_now().isoformat()
                        }
                    })
                    await event_queue.put({"type": "done"})

                # Start processing
                task = asyncio.create_task(process_chat())

                # Stream events as they come in
                while True:
                    try:
                        event = await asyncio.wait_for(event_queue.get(), timeout=1.0)

                        if event.get("type") == "done":
                            break

                        # Format as Server-Sent Event
                        event_data = json.dumps(event)
                        yield f"data: {event_data}\n\n"

                    except asyncio.TimeoutError:
                        # Send heartbeat to keep connection alive
                        yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': local_now().isoformat()})}\n\n"
                    except Exception as e:
                        logger.error(f"Error in event stream: {e}")
                        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                        break

                # Ensure task is cleaned up
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            except Exception as e:
                logger.error(f"Error in fitness chat stream: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        return StreamingResponse(
            generate_events(),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive"
            }
        )

    except Exception as e:
        logger.error(f"Fitness chat stream error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DASHBOARD / STATS ENDPOINT
# ============================================================================

@router.get("/dashboard")
async def get_fitness_dashboard(user_id: str = Depends(get_current_user_id)):
    """Get fitness dashboard data"""
    try:
        # Get food summary for the week
        food_tool = FoodLogSummaryTool()
        food_result = await food_tool.execute(user_id=user_id, period="week")

        # Get workout stats for the week
        workout_tool = WorkoutStatsTool()
        workout_result = await workout_tool.execute(user_id=user_id, period="week")

        dashboard = {
            "nutrition": food_result.data if food_result.success else {},
            "workouts": workout_result.data if workout_result.success else {},
            "updated_at": local_now().isoformat()
        }

        return dashboard

    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DAILY LOG ENDPOINTS
# ============================================================================

@router.get("/daily-log/{log_date}")
async def get_daily_log(
    log_date: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get fitness daily log for a specific date (format: YYYY-MM-DD or 'today')"""
    try:
        # Handle 'today' keyword
        if log_date.lower() == "today":
            target_date = date.today()
        else:
            target_date = datetime.strptime(log_date, "%Y-%m-%d").date()

        # Get daily log summary
        log_sql = text("""
            SELECT
                log_date, chat_count, food_entries, workout_sessions, notes_created,
                total_calories, total_protein, total_carbs, total_fats,
                total_exercises, total_sets, total_reps,
                summary, created_at, updated_at
            FROM fitness_daily_log
            WHERE user_id = :user_id AND log_date = :log_date
        """)
        result = db.execute(log_sql, {"user_id": user_id, "log_date": target_date})
        log_row = result.fetchone()

        if not log_row:
            return {
                "date": target_date.isoformat(),
                "has_data": False,
                "message": f"No fitness activity logged for {target_date.strftime('%A, %B %d, %Y')}"
            }

        # Get detailed episodes for this date
        episodes_sql = text("""
            SELECT source, role, content, created_at
            FROM episode
            WHERE user_id = :user_id
              AND source LIKE 'fitness_%'
              AND DATE(created_at) = :log_date
            ORDER BY created_at
        """)
        episodes_result = db.execute(episodes_sql, {"user_id": user_id, "log_date": target_date})
        episodes = []
        for ep_row in episodes_result:
            episodes.append({
                "source": ep_row[0],
                "role": ep_row[1],
                "content": ep_row[2],
                "time": ep_row[3].strftime("%I:%M %p")
            })

        return {
            "date": target_date.isoformat(),
            "day_name": target_date.strftime("%A"),
            "has_data": True,
            "summary": {
                "chat_count": log_row[1],
                "food_entries": log_row[2],
                "workout_sessions": log_row[3],
                "notes_created": log_row[4]
            },
            "nutrition": {
                "total_calories": log_row[5],
                "total_protein": log_row[6],
                "total_carbs": log_row[7],
                "total_fats": log_row[8]
            },
            "workout": {
                "total_exercises": log_row[9],
                "total_sets": log_row[10],
                "total_reps": log_row[11]
            },
            "narrative_summary": log_row[12],
            "activities": episodes,
            "first_activity": log_row[13].strftime("%I:%M %p"),
            "last_activity": log_row[14].strftime("%I:%M %p")
        }

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD or 'today'")
    except Exception as e:
        logger.error(f"Get daily log error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily-logs")
async def get_daily_logs_range(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 30,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get fitness daily logs for a date range"""
    try:
        # Default to last 30 days if not specified
        if not end_date:
            end = date.today()
        else:
            end = datetime.strptime(end_date, "%Y-%m-%d").date()

        if not start_date:
            from datetime import timedelta
            start = end - timedelta(days=limit-1)
        else:
            start = datetime.strptime(start_date, "%Y-%m-% d").date()

        logs_sql = text("""
            SELECT
                log_date, chat_count, food_entries, workout_sessions, notes_created,
                total_calories, total_protein, total_carbs, total_fats,
                total_sets, total_reps
            FROM fitness_daily_log
            WHERE user_id = :user_id
              AND log_date BETWEEN :start_date AND :end_date
            ORDER BY log_date DESC
            LIMIT :limit
        """)
        result = db.execute(logs_sql, {
            "user_id": user_id,
            "start_date": start,
            "end_date": end,
            "limit": limit
        })

        logs = []
        for row in result:
            logs.append({
                "date": row[0].isoformat(),
                "day_name": row[0].strftime("%A"),
                "chat_count": row[1],
                "food_entries": row[2],
                "workout_sessions": row[3],
                "notes_created": row[4],
                "total_calories": row[5],
                "total_protein": row[6],
                "total_carbs": row[7],
                "total_fats": row[8],
                "total_sets": row[9],
                "total_reps": row[10]
            })

        return {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "total_days": len(logs),
            "logs": logs
        }

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    except Exception as e:
        logger.error(f"Get daily logs range error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# NUTRITION GOALS ENDPOINTS
# ============================================================================

@router.get("/goals")
async def get_nutrition_goals(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get user's nutrition goals or return defaults"""
    try:
        # Query for user's existing goals
        result = db.execute(
            text("""
                SELECT calories, protein, carbs, fats
                FROM fitness_goals
                WHERE user_id = :user_id
                ORDER BY updated_at DESC
                LIMIT 1
            """),
            {"user_id": user_id}
        )
        row = result.fetchone()

        if row:
            return {
                "calories": row[0],
                "protein": row[1],
                "carbs": row[2],
                "fats": row[3]
            }
        else:
            # Return default goals
            return {
                "calories": 2000,
                "protein": 150,
                "carbs": 200,
                "fats": 70
            }

    except Exception as e:
        logger.error(f"Get nutrition goals error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/goals")
async def update_nutrition_goals(
    goals: NutritionGoals,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Update user's nutrition goals"""
    try:
        # Check if user has existing goals
        result = db.execute(
            text("""
                SELECT id FROM fitness_goals
                WHERE user_id = :user_id
                ORDER BY updated_at DESC
                LIMIT 1
            """),
            {"user_id": user_id}
        )
        existing = result.fetchone()

        if existing:
            # Update existing goals
            db.execute(
                text("""
                    UPDATE fitness_goals
                    SET calories = :calories,
                        protein = :protein,
                        carbs = :carbs,
                        fats = :fats,
                        updated_at = NOW()
                    WHERE user_id = :user_id
                """),
                {
                    "user_id": user_id,
                    "calories": goals.calories,
                    "protein": goals.protein,
                    "carbs": goals.carbs,
                    "fats": goals.fats
                }
            )
        else:
            # Insert new goals
            db.execute(
                text("""
                    INSERT INTO fitness_goals (id, user_id, calories, protein, carbs, fats, created_at, updated_at)
                    VALUES (gen_random_uuid(), :user_id, :calories, :protein, :carbs, :fats, NOW(), NOW())
                """),
                {
                    "user_id": user_id,
                    "calories": goals.calories,
                    "protein": goals.protein,
                    "carbs": goals.carbs,
                    "fats": goals.fats
                }
            )

        db.commit()

        return {
            "success": True,
            "message": "Nutrition goals updated successfully",
            "goals": {
                "calories": goals.calories,
                "protein": goals.protein,
                "carbs": goals.carbs,
                "fats": goals.fats
            }
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Update nutrition goals error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# TTS ENDPOINT (Wyoming/Piper)
# ============================================================================

class TTSRequest(BaseModel):
    text: str
    voice: str = "alloy"  # Default OpenAI-compatible voice (alloy, echo, fable, onyx, nova, shimmer)

@router.post("/tts")
async def text_to_speech(request: TTSRequest):
    """Convert text to speech using Wyoming/Piper TTS"""
    try:
        TTS_URL = "http://10.185.1.8:9000/v1/audio/speech"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                TTS_URL,
                json={
                    "model": "tts-1",
                    "input": request.text,
                    "voice": request.voice
                }
            )

            logger.info(f"Wyoming/Piper response: status={response.status_code}, size={len(response.content)} bytes")

            if response.status_code == 200:
                # Return audio as streaming response
                return StreamingResponse(
                    io.BytesIO(response.content),
                    media_type="audio/wav",
                    headers={
                        "Content-Disposition": "inline; filename=speech.wav"
                    }
                )
            else:
                logger.error(f"Wyoming/Piper error: status={response.status_code}, body={response.text}")
                raise HTTPException(status_code=500, detail=f"TTS service error: {response.text}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS error - Type: {type(e).__name__}, Message: {str(e)}, Repr: {repr(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")

# ============================================
# PROGRAM MANAGEMENT APIs
# ============================================

class ProgramCreate(BaseModel):
    name: str
    goal: str  # cut, bulk, maintenance, recomp, strength
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None


class ProgramUpdate(BaseModel):
    name: Optional[str] = None
    goal: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


@router.get("/programs")
async def list_programs(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """List all programs for user"""
    try:
        programs = db.execute(text("""
            SELECT id, name, goal, start_date, end_date, is_active, notes, created_at, updated_at
            FROM fitness_program
            WHERE user_id = :user_id
            ORDER BY is_active DESC, start_date DESC NULLS LAST, created_at DESC
        """), {"user_id": user_id}).fetchall()

        return {"programs": [dict(row._mapping) for row in programs]}
    except Exception as e:
        logger.error(f"Failed to list programs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/programs/active")
async def get_active_program(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Get the currently active program with its phases"""
    try:
        effective = reconcile_active_program_phase_statuses(db, user_id, local_now().date())
        db.commit()
        program = db.execute(text("""
            SELECT id, name, goal, start_date, end_date, is_active, notes, plan_markdown, created_at, updated_at
            FROM fitness_program
            WHERE user_id = :user_id AND is_active = true
            LIMIT 1
        """), {"user_id": user_id}).fetchone()

        if not program:
            return {"program": None, "phases": []}

        program_dict = dict(program._mapping)

        # Get phases for this program
        phases = db.execute(text(f"""
            SELECT {PHASE_SELECT_COLS}
            FROM fitness_phase
            WHERE user_id = :user_id AND program_id = :program_id
            ORDER BY order_index ASC, start_date ASC NULLS LAST
        """), {"user_id": user_id, "program_id": program_dict['id']}).fetchall()

        phase_dicts = [dict(row._mapping) for row in phases]
        return {
            "program": program_dict,
            "phases": annotate_effective_statuses(
                phase_dicts,
                effective["id"] if effective else None,
                local_now().date(),
            ),
        }
    except Exception as e:
        logger.error(f"Failed to get active program: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/programs/{program_id}")
async def get_program(program_id: str, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Get a specific program with its phases"""
    try:
        program = db.execute(text("""
            SELECT id, name, goal, start_date, end_date, is_active, notes, plan_markdown, created_at, updated_at
            FROM fitness_program
            WHERE id = :program_id AND user_id = :user_id
        """), {"program_id": program_id, "user_id": user_id}).fetchone()

        if not program:
            raise HTTPException(status_code=404, detail="Program not found")

        program_dict = dict(program._mapping)

        # Get phases for this program
        phases = db.execute(text(f"""
            SELECT {PHASE_SELECT_COLS}
            FROM fitness_phase
            WHERE user_id = :user_id AND program_id = :program_id
            ORDER BY order_index ASC, start_date ASC NULLS LAST
        """), {"user_id": user_id, "program_id": program_id}).fetchall()

        return {
            "program": program_dict,
            "phases": [dict(row._mapping) for row in phases]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get program: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/programs")
async def create_program(program: ProgramCreate, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Create a new training program"""
    try:
        program_id = str(uuid.uuid4())

        db.execute(text("""
            INSERT INTO fitness_program (id, user_id, name, goal, start_date, end_date, is_active, notes)
            VALUES (:id, :user_id, :name, :goal, :start_date, :end_date, false, :notes)
        """), {
            "id": program_id,
            "user_id": user_id,
            "name": program.name,
            "goal": program.goal,
            "start_date": program.start_date,
            "end_date": program.end_date,
            "notes": program.notes
        })
        db.commit()

        return {"success": True, "program_id": program_id, "message": "Program created successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create program: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/programs/{program_id}")
async def update_program(program_id: str, program: ProgramUpdate, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Update a program"""
    try:
        updates = []
        params = {"program_id": program_id, "user_id": user_id}

        if program.name is not None:
            updates.append("name = :name")
            params["name"] = program.name
        if program.goal is not None:
            updates.append("goal = :goal")
            params["goal"] = program.goal
        if program.start_date is not None:
            updates.append("start_date = :start_date")
            params["start_date"] = program.start_date
        if program.end_date is not None:
            updates.append("end_date = :end_date")
            params["end_date"] = program.end_date
        if program.is_active is not None:
            updates.append("is_active = :is_active")
            params["is_active"] = program.is_active
        if program.notes is not None:
            updates.append("notes = :notes")
            params["notes"] = program.notes

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            sql = f"UPDATE fitness_program SET {', '.join(updates)} WHERE id = :program_id AND user_id = :user_id"
            db.execute(text(sql), params)
            db.commit()

        return {"success": True, "message": "Program updated successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update program: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/programs/{program_id}/activate")
async def activate_program(program_id: str, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Activate a program (deactivates any other active program)"""
    try:
        # Deactivate all other programs
        db.execute(text("""
            UPDATE fitness_program SET is_active = false, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = :user_id AND is_active = true
        """), {"user_id": user_id})

        # Activate this program
        result = db.execute(text("""
            UPDATE fitness_program SET is_active = true, updated_at = CURRENT_TIMESTAMP
            WHERE id = :program_id AND user_id = :user_id
            RETURNING id
        """), {"program_id": program_id, "user_id": user_id}).fetchone()

        if not result:
            db.rollback()
            raise HTTPException(status_code=404, detail="Program not found")

        db.commit()
        return {"success": True, "message": "Program activated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to activate program: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/programs/{program_id}")
async def delete_program(program_id: str, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Delete a program (also deletes associated phases)"""
    try:
        # First clear program_id from phases (don't delete phases, just unlink)
        db.execute(text("""
            UPDATE fitness_phase SET program_id = NULL
            WHERE program_id = :program_id AND user_id = :user_id
        """), {"program_id": program_id, "user_id": user_id})

        # Delete the program
        db.execute(text("""
            DELETE FROM fitness_program WHERE id = :program_id AND user_id = :user_id
        """), {"program_id": program_id, "user_id": user_id})
        db.commit()
        return {"success": True, "message": "Program deleted successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete program: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# PHASE MANAGEMENT APIs
# ============================================

class PhaseCreate(BaseModel):
    name: str
    goal: Optional[str] = None
    program_id: Optional[str] = None
    order_index: Optional[int] = 0
    duration_weeks: Optional[int] = None
    parent_phase_id: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    # Nutrition targets — single (weekly average / fallback)
    calories_target: Optional[int] = None
    protein_target: Optional[int] = None
    carbs_target: Optional[int] = None
    fat_target: Optional[int] = None
    # Nutrition targets — calorie cycling (training day vs rest day)
    calories_training_day: Optional[int] = None
    calories_rest_day: Optional[int] = None
    carbs_training_day: Optional[int] = None
    carbs_rest_day: Optional[int] = None
    fat_training_day: Optional[int] = None
    fat_rest_day: Optional[int] = None
    daily_steps_target: Optional[int] = None
    training_days_per_week: Optional[int] = None
    deload_week: Optional[int] = None
    notes: Optional[str] = None


class PhaseUpdate(BaseModel):
    name: Optional[str] = None
    goal: Optional[str] = None
    program_id: Optional[str] = None
    order_index: Optional[int] = None
    duration_weeks: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[str] = None
    # Nutrition targets — single (weekly average / fallback)
    calories_target: Optional[int] = None
    protein_target: Optional[int] = None
    carbs_target: Optional[int] = None
    fat_target: Optional[int] = None
    # Nutrition targets — calorie cycling
    calories_training_day: Optional[int] = None
    calories_rest_day: Optional[int] = None
    carbs_training_day: Optional[int] = None
    carbs_rest_day: Optional[int] = None
    fat_training_day: Optional[int] = None
    fat_rest_day: Optional[int] = None
    daily_steps_target: Optional[int] = None
    training_days_per_week: Optional[int] = None
    deload_week: Optional[int] = None
    notes: Optional[str] = None


# Canonical column list for fitness_phase SELECT — keeps GET endpoints in sync
PHASE_SELECT_COLS = """
    id, name, goal, program_id, order_index, duration_weeks,
    parent_phase_id, start_date, end_date,
    calories_target, protein_target, carbs_target, fat_target,
    calories_training_day, calories_rest_day,
    carbs_training_day, carbs_rest_day,
    fat_training_day, fat_rest_day,
    daily_steps_target,
    training_days_per_week, deload_week,
    status, notes, created_at, updated_at
"""

@router.get("/phases")
async def list_phases(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """List all phases for user (hierarchical)"""
    try:
        effective = reconcile_active_program_phase_statuses(db, user_id, local_now().date())
        db.commit()
        phases = db.execute(text(f"""
            SELECT {PHASE_SELECT_COLS}
            FROM fitness_phase
            WHERE user_id = :user_id
            ORDER BY program_id NULLS LAST, order_index ASC, start_date DESC NULLS LAST, created_at DESC
        """), {"user_id": user_id}).fetchall()
        phase_dicts = [dict(row._mapping) for row in phases]
        return {
            "phases": annotate_effective_statuses(
                phase_dicts,
                effective["id"] if effective else None,
                local_now().date(),
            )
        }
    except Exception as e:
        logger.error(f"Failed to list phases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/phases")
async def create_phase(phase: PhaseCreate, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Create a new training phase"""
    try:
        phase_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO fitness_phase (
                id, user_id, name, goal, program_id, order_index, duration_weeks,
                parent_phase_id, start_date, end_date,
                calories_target, protein_target, carbs_target, fat_target,
                calories_training_day, calories_rest_day,
                carbs_training_day, carbs_rest_day,
                fat_training_day, fat_rest_day,
                daily_steps_target,
                training_days_per_week, deload_week,
                status, notes
            )
            VALUES (
                :id, :user_id, :name, :goal, :program_id, :order_index, :duration_weeks,
                :parent_phase_id, :start_date, :end_date,
                :calories_target, :protein_target, :carbs_target, :fat_target,
                :calories_training_day, :calories_rest_day,
                :carbs_training_day, :carbs_rest_day,
                :fat_training_day, :fat_rest_day,
                :daily_steps_target,
                :training_days_per_week, :deload_week,
                :status, :notes
            )
        """), {
            "id": phase_id,
            "user_id": user_id,
            "name": phase.name,
            "goal": phase.goal,
            "program_id": phase.program_id,
            "order_index": phase.order_index or 0,
            "duration_weeks": phase.duration_weeks,
            "parent_phase_id": phase.parent_phase_id,
            "start_date": phase.start_date,
            "end_date": phase.end_date,
            "calories_target": phase.calories_target,
            "protein_target": phase.protein_target,
            "carbs_target": phase.carbs_target,
            "fat_target": phase.fat_target,
            "calories_training_day": phase.calories_training_day,
            "calories_rest_day": phase.calories_rest_day,
            "carbs_training_day": phase.carbs_training_day,
            "carbs_rest_day": phase.carbs_rest_day,
            "fat_training_day": phase.fat_training_day,
            "fat_rest_day": phase.fat_rest_day,
            "daily_steps_target": phase.daily_steps_target,
            "training_days_per_week": phase.training_days_per_week,
            "deload_week": phase.deload_week,
            "status": "planned",
            "notes": phase.notes
        })
        db.commit()

        return {"success": True, "phase_id": phase_id, "message": "Phase created successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create phase: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/phases/{phase_id}")
async def update_phase(phase_id: str, phase: PhaseUpdate, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Update a phase"""
    try:
        updates = []
        params = {"phase_id": phase_id, "user_id": user_id}

        if phase.name is not None:
            updates.append("name = :name")
            params["name"] = phase.name
        if phase.goal is not None:
            updates.append("goal = :goal")
            params["goal"] = phase.goal
        if phase.program_id is not None:
            updates.append("program_id = :program_id")
            params["program_id"] = phase.program_id
        if phase.order_index is not None:
            updates.append("order_index = :order_index")
            params["order_index"] = phase.order_index
        if phase.duration_weeks is not None:
            updates.append("duration_weeks = :duration_weeks")
            params["duration_weeks"] = phase.duration_weeks
        if phase.start_date is not None:
            updates.append("start_date = :start_date")
            params["start_date"] = phase.start_date
        if phase.end_date is not None:
            updates.append("end_date = :end_date")
            params["end_date"] = phase.end_date
        if phase.status is not None:
            updates.append("status = :status")
            params["status"] = phase.status
        if phase.calories_target is not None:
            updates.append("calories_target = :calories_target")
            params["calories_target"] = phase.calories_target
        if phase.protein_target is not None:
            updates.append("protein_target = :protein_target")
            params["protein_target"] = phase.protein_target
        if phase.carbs_target is not None:
            updates.append("carbs_target = :carbs_target")
            params["carbs_target"] = phase.carbs_target
        if phase.fat_target is not None:
            updates.append("fat_target = :fat_target")
            params["fat_target"] = phase.fat_target
        if phase.calories_training_day is not None:
            updates.append("calories_training_day = :calories_training_day")
            params["calories_training_day"] = phase.calories_training_day
        if phase.calories_rest_day is not None:
            updates.append("calories_rest_day = :calories_rest_day")
            params["calories_rest_day"] = phase.calories_rest_day
        if phase.carbs_training_day is not None:
            updates.append("carbs_training_day = :carbs_training_day")
            params["carbs_training_day"] = phase.carbs_training_day
        if phase.carbs_rest_day is not None:
            updates.append("carbs_rest_day = :carbs_rest_day")
            params["carbs_rest_day"] = phase.carbs_rest_day
        if phase.fat_training_day is not None:
            updates.append("fat_training_day = :fat_training_day")
            params["fat_training_day"] = phase.fat_training_day
        if phase.fat_rest_day is not None:
            updates.append("fat_rest_day = :fat_rest_day")
            params["fat_rest_day"] = phase.fat_rest_day
        if phase.daily_steps_target is not None:
            updates.append("daily_steps_target = :daily_steps_target")
            params["daily_steps_target"] = phase.daily_steps_target
        if phase.training_days_per_week is not None:
            updates.append("training_days_per_week = :training_days_per_week")
            params["training_days_per_week"] = phase.training_days_per_week
        if phase.deload_week is not None:
            updates.append("deload_week = :deload_week")
            params["deload_week"] = phase.deload_week
        if phase.notes is not None:
            updates.append("notes = :notes")
            params["notes"] = phase.notes

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            sql = f"UPDATE fitness_phase SET {', '.join(updates)} WHERE id = :phase_id AND user_id = :user_id"
            db.execute(text(sql), params)
            db.commit()

        return {"success": True, "message": "Phase updated successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update phase: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/phases/{phase_id}")
async def delete_phase(phase_id: str, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Delete a phase"""
    try:
        db.execute(text("""
            DELETE FROM fitness_phase WHERE id = :phase_id AND user_id = :user_id
        """), {"phase_id": phase_id, "user_id": user_id})
        db.commit()
        return {"success": True, "message": "Phase deleted successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete phase: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/today-target")
async def get_today_nutrition_target(
    on_date: Optional[date] = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Return today's nutrition target, picking training-day vs rest-day macros from
    the active phase based on whether a workout_session is scheduled for the date.

    Falls back to single (weekly average) targets if no cycling is configured.
    """
    # Use Eastern (user) date — date.today() would use the server's UTC clock
    # and roll over hours early/late, mislabeling the day near midnight.
    target_date = on_date or local_now().date()

    # The active program and its dated child phase are the single authority.
    phase = reconcile_active_program_phase_statuses(db, user_id, target_date)
    db.commit()

    if not phase:
        return {
            "date": target_date.isoformat(),
            "is_training_day": False,
            "phase": None,
            "target": None,
        }

    # Is today a training day? Two independent signals, either one counts:
    #   1. A materialized workout_session exists for the date (created by
    #      activate_phase / toggle-training-day / actually logging a workout).
    #   2. A template is *scheduled* for this weekday (plan-imported phases set
    #      status='active' without ever materializing sessions, so the schedule
    #      is the only signal). Mirrors /templates/today and the iOS fallback.
    sess = db.execute(text("""
        SELECT id FROM workout_session
        WHERE user_id = :uid AND session_date = :d
        LIMIT 1
    """), {"uid": user_id, "d": target_date}).fetchone()
    is_training = sess is not None

    if not is_training:
        import json as _json
        weekday = target_date.strftime("%A").lower()
        # Templates from the active phase, or standalone (no phase) templates.
        sched_templates = db.execute(text("""
            SELECT scheduled_days
            FROM fitness_template
            WHERE user_id = :uid
              AND (phase_id = :pid OR phase_id IS NULL)
        """), {"uid": user_id, "pid": phase["id"]}).fetchall()
        for trow in sched_templates:
            try:
                days = _json.loads(trow.scheduled_days or "[]")
            except (ValueError, TypeError):
                days = []
            if weekday in [str(d).lower() for d in days]:
                is_training = True
                break

    # Pick the right macros
    if is_training:
        target = {
            "calories": phase.get("calories_training_day") or phase.get("calories_target"),
            "protein": phase.get("protein_target"),
            "carbs": phase.get("carbs_training_day") or phase.get("carbs_target"),
            "fat": phase.get("fat_training_day") or phase.get("fat_target"),
        }
    else:
        target = {
            "calories": phase.get("calories_rest_day") or phase.get("calories_target"),
            "protein": phase.get("protein_target"),
            "carbs": phase.get("carbs_rest_day") or phase.get("carbs_target"),
            "fat": phase.get("fat_rest_day") or phase.get("fat_target"),
        }

    # Compute deload state too — useful for the food log to show why training-day
    # macros may be appropriate even on a deload day.
    from app.services.progressive_overload import get_deload_state
    deload = get_deload_state(db, user_id, target_date)

    return {
        "date": target_date.isoformat(),
        "is_training_day": is_training,
        "is_deload": deload["is_deload"],
        "week_of_phase": deload["week_of_phase"],
        "phase": {
            "id": phase["id"],
            "name": phase["name"],
            "daily_steps_target": phase.get("daily_steps_target"),
        },
        "target": target,
    }


@router.post("/toggle-training-day")
async def toggle_training_day(
    target_date: Optional[date] = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Toggle a date between training day and rest day.
    If a workout_session exists for the date, remove it (→ rest day).
    If none exists, create a placeholder session (→ training day).
    Returns the new state.
    """
    d = target_date or date.today()

    existing = db.execute(text("""
        SELECT id, template_id, status FROM workout_session
        WHERE user_id = :uid AND session_date = :d
        ORDER BY created_at ASC
    """), {"uid": user_id, "d": d}).fetchall()

    if existing:
        # Remove all sessions for this date → becomes rest day
        db.execute(text("""
            DELETE FROM workout_session
            WHERE user_id = :uid AND session_date = :d
        """), {"uid": user_id, "d": d})
        db.commit()
        return {"date": d.isoformat(), "is_training_day": False, "action": "removed"}
    else:
        # Create a placeholder session → becomes training day
        session_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO workout_session (id, user_id, session_date, status, created_at, updated_at)
            VALUES (:id, :uid, :d, 'planned', NOW(), NOW())
        """), {"id": session_id, "uid": user_id, "d": d})
        db.commit()
        return {"date": d.isoformat(), "is_training_day": True, "action": "created", "session_id": session_id}


@router.get("/phases/active")
async def get_active_phases(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Get currently active phases with nutrition targets"""
    try:
        reconcile_active_program_phase_statuses(db, user_id, local_now().date())
        db.commit()
        phases = db.execute(text(f"""
            SELECT {PHASE_SELECT_COLS}
            FROM fitness_phase
            WHERE user_id = :user_id AND status = 'active'
            ORDER BY order_index ASC, start_date DESC NULLS LAST
        """), {"user_id": user_id}).fetchall()

        return {"phases": [dict(row._mapping) for row in phases]}
    except Exception as e:
        logger.error(f"Failed to get active phases: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/phases/{phase_id}/activate")
async def activate_phase(phase_id: str, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """
    Activate a training phase:
    - Deactivates any currently active phase
    - Creates calendar events for all templates based on scheduled days (if dates set)
    - Creates workout_session entries in 'planned' status
    - Updates phase status to 'active'
    """
    try:
        from datetime import datetime, timedelta
        import json

        # 1. Fetch phase details
        phase = db.execute(text("""
            SELECT id, name, start_date, end_date, status, duration_weeks
            FROM fitness_phase
            WHERE id = :phase_id AND user_id = :user_id
        """), {"phase_id": phase_id, "user_id": user_id}).fetchone()

        if not phase:
            raise HTTPException(status_code=404, detail="Phase not found")

        phase_dict = dict(phase._mapping)

        if phase_dict['status'] == 'active':
            raise HTTPException(status_code=400, detail="Phase is already active")

        # 2. Deactivate any currently active phases for this user
        db.execute(text("""
            UPDATE fitness_phase
            SET status = 'inactive', updated_at = CURRENT_TIMESTAMP
            WHERE user_id = :user_id AND status = 'active'
        """), {"user_id": user_id})

        # 3. Determine date range for calendar events
        start_date = phase_dict.get('start_date')
        end_date = phase_dict.get('end_date')
        duration_weeks = phase_dict.get('duration_weeks') or 4

        # If no dates set, use today + duration_weeks
        if not start_date:
            start_date = local_now().date()
        if not end_date:
            end_date = start_date + timedelta(weeks=duration_weeks)

        # Update phase with calculated dates
        db.execute(text("""
            UPDATE fitness_phase
            SET start_date = :start_date, end_date = :end_date
            WHERE id = :phase_id AND user_id = :user_id
        """), {"phase_id": phase_id, "user_id": user_id, "start_date": start_date, "end_date": end_date})

        # 4. Fetch all templates for this phase
        templates = db.execute(text("""
            SELECT id, name, scheduled_days, exercises
            FROM fitness_template
            WHERE phase_id = :phase_id AND user_id = :user_id
        """), {"phase_id": phase_id, "user_id": user_id}).fetchall()

        created_events = []
        created_sessions = []

        if templates:
            # Day mapping
            day_map = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                'friday': 4, 'saturday': 5, 'sunday': 6
            }

            # 5. For each template, generate calendar events
            for template_row in templates:
                template = dict(template_row._mapping)
                template_id = template['id']
                template_name = template['name']
                scheduled_days_json = template['scheduled_days']

                # Parse scheduled days
                try:
                    scheduled_days = json.loads(scheduled_days_json) if scheduled_days_json else []
                except:
                    scheduled_days = []

                if not scheduled_days:
                    continue

                # Convert scheduled days to day numbers
                scheduled_day_nums = [day_map[d.lower().strip()] for d in scheduled_days if d.lower().strip() in day_map]

                if not scheduled_day_nums:
                    continue

                # Generate all dates between start_date and end_date that match scheduled days
                current_date = start_date
                while current_date <= end_date:
                    if current_date.weekday() in scheduled_day_nums:
                        # Create calendar event
                        event_id = str(uuid.uuid4())
                        event_start = datetime.combine(current_date, datetime.min.time().replace(hour=13, minute=0))
                        event_end = datetime.combine(current_date, datetime.min.time().replace(hour=14, minute=30))

                        db.execute(text("""
                            INSERT INTO calendar_event (id, user_id, title, start_time, end_time, description, location, source)
                            VALUES (:id, :user_id, :title, :start_time, :end_time, :description, :location, 'sara')
                        """), {
                            "id": event_id,
                            "user_id": user_id,
                            "title": f"🏋️ {template_name}",
                            "start_time": event_start,
                            "end_time": event_end,
                            "description": f"Workout: {template_name}\nPhase: {phase_dict['name']}",
                            "location": ""
                        })

                        # Create workout session
                        session_id = str(uuid.uuid4())
                        db.execute(text("""
                            INSERT INTO workout_session (id, user_id, template_id, session_date, status, calendar_event_id)
                            VALUES (:id, :user_id, :template_id, :session_date, :status, :calendar_event_id)
                        """), {
                            "id": session_id,
                            "user_id": user_id,
                            "template_id": template_id,
                            "session_date": current_date,
                            "status": "planned",
                            "calendar_event_id": event_id
                        })

                        created_events.append({
                            "event_id": event_id,
                            "template_name": template_name,
                            "date": current_date.isoformat()
                        })
                        created_sessions.append({
                            "session_id": session_id,
                            "template_id": template_id,
                            "date": current_date.isoformat()
                        })

                    current_date += timedelta(days=1)

        # 6. Update phase status to 'active'
        db.execute(text("""
            UPDATE fitness_phase
            SET status = 'active', updated_at = CURRENT_TIMESTAMP
            WHERE id = :phase_id AND user_id = :user_id
        """), {"phase_id": phase_id, "user_id": user_id})

        db.commit()

        return {
            "success": True,
            "message": f"Phase '{phase_dict['name']}' activated successfully",
            "summary": {
                "phase_name": phase_dict['name'],
                "start_date": start_date.isoformat() if hasattr(start_date, 'isoformat') else str(start_date),
                "end_date": end_date.isoformat() if hasattr(end_date, 'isoformat') else str(end_date),
                "templates_count": len(templates) if templates else 0,
                "events_created": len(created_events),
                "sessions_created": len(created_sessions)
            },
            "note": f"Created {len(created_events)} calendar events" if created_events else "No templates linked - add templates to this phase to auto-schedule workouts"
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to activate phase: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# TEMPLATE MANAGEMENT APIs
# ============================================

class TemplateCreate(BaseModel):
    name: str
    phase_id: Optional[str] = None
    scheduled_days: List[str] = []  # ["monday", "thursday", "saturday"]
    exercises: List[Dict] = []  # [{"name": "Bench Press", "sets": 3, "reps": "8-10", "rpe_target": 7}]
    notes: Optional[str] = None
    starting_weights: Optional[Dict[str, float]] = None  # {"Bench Press": 135.0, "Squat": 225.0}

class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    phase_id: Optional[str] = None
    scheduled_days: Optional[List[str]] = None
    exercises: Optional[List[Dict]] = None
    notes: Optional[str] = None

@router.get("/templates")
async def list_templates(
    phase_id: Optional[str] = None,
    active_only: bool = True,  # Default to showing only active phase templates
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """List all templates (optionally filtered by phase, defaults to active phase)"""
    try:
        import json
        from datetime import datetime

        # Get today's day name for sorting
        today = naive_local_now().strftime("%A").lower()

        sql = """
            SELECT t.id, t.phase_id, t.name, t.scheduled_days, t.exercises,
                   t.order_in_phase, t.notes, t.created_at, t.updated_at
            FROM fitness_template t
            WHERE t.user_id = :user_id
        """
        params = {"user_id": user_id}

        if phase_id:
            sql += " AND t.phase_id = :phase_id"
            params["phase_id"] = phase_id
        elif active_only:
            effective = get_effective_phase(db, user_id, local_now().date())
            if effective:
                sql += " AND t.phase_id = :effective_phase_id"
                params["effective_phase_id"] = effective["id"]
            else:
                sql += " AND 1 = 0"

        sql += " ORDER BY t.created_at DESC"

        templates = db.execute(text(sql), params).fetchall()

        # Parse JSON fields and sort with today's workout first
        result = []
        today_templates = []
        other_templates = []

        for row in templates:
            template_dict = dict(row._mapping)
            if template_dict.get("scheduled_days"):
                template_dict["scheduled_days"] = json.loads(template_dict["scheduled_days"])
            if template_dict.get("exercises"):
                template_dict["exercises"] = json.loads(template_dict["exercises"])

            # Check if this is today's workout
            scheduled = template_dict.get("scheduled_days", [])
            if today in [d.lower() for d in scheduled]:
                template_dict["is_today"] = True
                today_templates.append(template_dict)
            else:
                template_dict["is_today"] = False
                other_templates.append(template_dict)

        # Today's workouts first, then others
        result = today_templates + other_templates

        return {"templates": result, "today": today}
    except Exception as e:
        logger.error(f"Failed to list templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/templates")
async def create_template(template: TemplateCreate, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Create a new workout template"""
    try:
        import json
        template_id = str(uuid.uuid4())

        db.execute(text("""
            INSERT INTO fitness_template (id, user_id, phase_id, name, scheduled_days, exercises, notes, starting_weights)
            VALUES (:id, :user_id, :phase_id, :name, :scheduled_days, :exercises, :notes, :starting_weights)
        """), {
            "id": template_id,
            "user_id": user_id,
            "phase_id": template.phase_id,
            "name": template.name,
            "scheduled_days": json.dumps(template.scheduled_days),
            "exercises": json.dumps(template.exercises),
            "notes": template.notes,
            "starting_weights": json.dumps(template.starting_weights) if template.starting_weights else None
        })
        db.commit()

        return {"success": True, "template_id": template_id, "message": "Template created successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create template: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/templates/today")
async def get_today_template(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Get template scheduled for today - prioritizes active phase templates"""
    try:
        import json
        from datetime import datetime

        day_of_week = naive_local_now().strftime("%A").lower()

        # Resolve the dated phase of the approved active program.
        active_phase = reconcile_active_program_phase_statuses(
            db, user_id, local_now().date()
        )
        db.commit()
        active_phase_id = active_phase["id"] if active_phase else None

        templates = db.execute(text("""
            SELECT id, phase_id, name, scheduled_days, exercises, notes
            FROM fitness_template
            WHERE user_id = :user_id
        """), {"user_id": user_id}).fetchall()

        # Find templates that have today in their scheduled_days
        active_phase_templates = []
        other_templates = []

        for row in templates:
            template_dict = dict(row._mapping)
            scheduled_days = json.loads(template_dict.get("scheduled_days", "[]"))
            if day_of_week in [d.lower() for d in scheduled_days]:
                template_dict["scheduled_days"] = scheduled_days
                template_dict["exercises"] = json.loads(template_dict.get("exercises", "[]"))

                # Prioritize templates from active phase
                if active_phase_id and template_dict.get("phase_id") == active_phase_id:
                    active_phase_templates.append(template_dict)
                elif not template_dict.get("phase_id"):
                    # Templates not linked to any phase (standalone)
                    other_templates.append(template_dict)

        # Return active phase templates first, then standalone templates
        # Don't include templates from inactive phases
        matching_templates = active_phase_templates + other_templates

        return {
            "templates": matching_templates,
            "day_of_week": day_of_week,
            "active_phase": {
                "id": active_phase["id"],
                "name": active_phase["name"],
            } if active_phase else None
        }
    except Exception as e:
        logger.error(f"Failed to get today's template: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/templates/{template_id}")
async def update_template(template_id: str, template: TemplateUpdate, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Update a template"""
    try:
        import json
        updates = []
        params = {"template_id": template_id, "user_id": user_id}

        if template.name is not None:
            updates.append("name = :name")
            params["name"] = template.name
        if template.phase_id is not None:
            updates.append("phase_id = :phase_id")
            params["phase_id"] = template.phase_id
        if template.scheduled_days is not None:
            updates.append("scheduled_days = :scheduled_days")
            params["scheduled_days"] = json.dumps(template.scheduled_days)
        if template.exercises is not None:
            updates.append("exercises = :exercises")
            params["exercises"] = json.dumps(template.exercises)
        if template.notes is not None:
            updates.append("notes = :notes")
            params["notes"] = template.notes

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            sql = f"UPDATE fitness_template SET {', '.join(updates)} WHERE id = :template_id AND user_id = :user_id"
            db.execute(text(sql), params)
            db.commit()

        return {"success": True, "message": "Template updated successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update template: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Delete a template"""
    try:
        db.execute(text("""
            DELETE FROM fitness_template WHERE id = :template_id AND user_id = :user_id
        """), {"template_id": template_id, "user_id": user_id})
        db.commit()
        return {"success": True, "message": "Template deleted successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# TEMPLATE EXERCISE APIs
# ============================================

class TemplateExerciseCreate(BaseModel):
    exercise_name: str
    order_index: Optional[int] = 0
    target_sets: Optional[int] = 3
    rep_range_low: Optional[int] = 8
    rep_range_high: Optional[int] = 12
    target_rpe: Optional[float] = None
    rest_seconds: Optional[int] = 120
    progression_rule: Optional[str] = "DOUBLE_PROGRESSION"  # DOUBLE_PROGRESSION, LINEAR, RPE_BASED
    notes: Optional[str] = None
    # Advanced execution markers
    metric_type: Optional[str] = "reps"          # 'reps' | 'time_seconds'
    is_per_side: Optional[bool] = False          # unilateral exercises (per-leg/per-arm)
    superset_group: Optional[str] = None         # short label like "A" — exercises sharing it are supersetted
    set_technique: Optional[str] = None          # 'drop_set' | 'rest_pause' | 'amrap' | 'myo_reps' (typically applied to last set)


class TemplateExerciseUpdate(BaseModel):
    exercise_name: Optional[str] = None
    order_index: Optional[int] = None
    target_sets: Optional[int] = None
    rep_range_low: Optional[int] = None
    rep_range_high: Optional[int] = None
    target_rpe: Optional[float] = None
    rest_seconds: Optional[int] = None
    progression_rule: Optional[str] = None
    notes: Optional[str] = None
    metric_type: Optional[str] = None
    is_per_side: Optional[bool] = None
    superset_group: Optional[str] = None
    set_technique: Optional[str] = None


def _exercise_row_to_json(row_mapping: dict) -> dict:
    """Convert a template_exercise row dict to the JSON exercise dict shape used by
    fitness_template.exercises (which is what the live workout view reads)."""
    lo = row_mapping.get("rep_range_low")
    hi = row_mapping.get("rep_range_high")
    if lo is not None and hi is not None and lo != hi:
        reps_str = f"{lo}-{hi}"
    elif lo is not None:
        reps_str = str(lo)
    else:
        reps_str = "8-10"
    return {
        "name": row_mapping.get("exercise_name"),
        "sets": row_mapping.get("target_sets") or 3,
        "reps": reps_str,
        "rep_range_low": lo,
        "rep_range_high": hi,
        "rpe_target": float(row_mapping["target_rpe"]) if row_mapping.get("target_rpe") is not None else None,
        "rest_seconds": row_mapping.get("rest_seconds") or 120,
        "progression_rule": row_mapping.get("progression_rule") or "DOUBLE_PROGRESSION",
        "notes": row_mapping.get("notes") or "",
        # Advanced markers
        "metric_type": row_mapping.get("metric_type") or "reps",
        "is_per_side": bool(row_mapping.get("is_per_side") or False),
        "superset_group": row_mapping.get("superset_group"),
        "set_technique": row_mapping.get("set_technique"),
    }


def _sync_template_exercises_json(db: Session, template_id: str) -> None:
    """Rebuild fitness_template.exercises JSON from the relational template_exercise rows.
    Called after every create/update/delete/reorder of a template_exercise so the JSON
    (which the live workout view reads from) stays in sync with the relational data."""
    import json as _json
    rows = db.execute(text("""
        SELECT exercise_name, order_index, target_sets, rep_range_low, rep_range_high,
               target_rpe, rest_seconds, progression_rule, notes,
               metric_type, is_per_side, superset_group, set_technique
        FROM template_exercise
        WHERE template_id = :tid
        ORDER BY order_index ASC, created_at ASC
    """), {"tid": template_id}).fetchall()
    exercises_json = [_exercise_row_to_json(dict(r._mapping)) for r in rows]
    db.execute(text("""
        UPDATE fitness_template
        SET exercises = :ex, updated_at = CURRENT_TIMESTAMP
        WHERE id = :tid
    """), {"ex": _json.dumps(exercises_json), "tid": template_id})


@router.get("/templates/{template_id}/exercises")
async def list_template_exercises(
    template_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get all exercises for a template"""
    try:
        # Verify user owns this template
        template = db.execute(text("""
            SELECT id FROM fitness_template WHERE id = :template_id AND user_id = :user_id
        """), {"template_id": template_id, "user_id": user_id}).fetchone()

        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        exercises = db.execute(text("""
            SELECT id, template_id, exercise_name, order_index, target_sets,
                   rep_range_low, rep_range_high, target_rpe, rest_seconds,
                   progression_rule, notes,
                   metric_type, is_per_side, superset_group, set_technique,
                   created_at, updated_at
            FROM template_exercise
            WHERE template_id = :template_id
            ORDER BY order_index ASC
        """), {"template_id": template_id}).fetchall()

        return {"exercises": [dict(row._mapping) for row in exercises]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list template exercises: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/templates/{template_id}/exercises")
async def create_template_exercise(
    template_id: str,
    exercise: TemplateExerciseCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Add an exercise to a template"""
    try:
        # Verify user owns this template
        template = db.execute(text("""
            SELECT id FROM fitness_template WHERE id = :template_id AND user_id = :user_id
        """), {"template_id": template_id, "user_id": user_id}).fetchone()

        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        exercise_id = str(uuid.uuid4())

        db.execute(text("""
            INSERT INTO template_exercise (
                id, template_id, exercise_name, order_index, target_sets,
                rep_range_low, rep_range_high, target_rpe, rest_seconds,
                progression_rule, notes,
                metric_type, is_per_side, superset_group, set_technique
            ) VALUES (
                :id, :template_id, :exercise_name, :order_index, :target_sets,
                :rep_range_low, :rep_range_high, :target_rpe, :rest_seconds,
                :progression_rule, :notes,
                :metric_type, :is_per_side, :superset_group, :set_technique
            )
        """), {
            "id": exercise_id,
            "template_id": template_id,
            "exercise_name": exercise.exercise_name,
            "order_index": exercise.order_index or 0,
            "target_sets": exercise.target_sets or 3,
            "rep_range_low": exercise.rep_range_low or 8,
            "rep_range_high": exercise.rep_range_high or 12,
            "target_rpe": exercise.target_rpe,
            "rest_seconds": exercise.rest_seconds or 120,
            "progression_rule": exercise.progression_rule or "DOUBLE_PROGRESSION",
            "notes": exercise.notes,
            "metric_type": exercise.metric_type or "reps",
            "is_per_side": bool(exercise.is_per_side),
            "superset_group": exercise.superset_group,
            "set_technique": exercise.set_technique,
        })
        _sync_template_exercises_json(db, template_id)
        db.commit()

        return {"success": True, "exercise_id": exercise_id, "message": "Exercise added to template"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create template exercise: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/templates/{template_id}/exercises/{exercise_id}")
async def update_template_exercise(
    template_id: str,
    exercise_id: str,
    exercise: TemplateExerciseUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Update an exercise in a template"""
    try:
        # Verify user owns this template
        template = db.execute(text("""
            SELECT id FROM fitness_template WHERE id = :template_id AND user_id = :user_id
        """), {"template_id": template_id, "user_id": user_id}).fetchone()

        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        updates = []
        params = {"exercise_id": exercise_id, "template_id": template_id}

        if exercise.exercise_name is not None:
            updates.append("exercise_name = :exercise_name")
            params["exercise_name"] = exercise.exercise_name
        if exercise.order_index is not None:
            updates.append("order_index = :order_index")
            params["order_index"] = exercise.order_index
        if exercise.target_sets is not None:
            updates.append("target_sets = :target_sets")
            params["target_sets"] = exercise.target_sets
        if exercise.rep_range_low is not None:
            updates.append("rep_range_low = :rep_range_low")
            params["rep_range_low"] = exercise.rep_range_low
        if exercise.rep_range_high is not None:
            updates.append("rep_range_high = :rep_range_high")
            params["rep_range_high"] = exercise.rep_range_high
        if exercise.target_rpe is not None:
            updates.append("target_rpe = :target_rpe")
            params["target_rpe"] = exercise.target_rpe
        if exercise.rest_seconds is not None:
            updates.append("rest_seconds = :rest_seconds")
            params["rest_seconds"] = exercise.rest_seconds
        if exercise.progression_rule is not None:
            updates.append("progression_rule = :progression_rule")
            params["progression_rule"] = exercise.progression_rule
        if exercise.notes is not None:
            updates.append("notes = :notes")
            params["notes"] = exercise.notes
        if exercise.metric_type is not None:
            updates.append("metric_type = :metric_type")
            params["metric_type"] = exercise.metric_type
        if exercise.is_per_side is not None:
            updates.append("is_per_side = :is_per_side")
            params["is_per_side"] = bool(exercise.is_per_side)
        if exercise.superset_group is not None:
            # Allow clearing by passing empty string
            updates.append("superset_group = :superset_group")
            params["superset_group"] = exercise.superset_group or None
        if exercise.set_technique is not None:
            updates.append("set_technique = :set_technique")
            params["set_technique"] = exercise.set_technique or None

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            sql = f"UPDATE template_exercise SET {', '.join(updates)} WHERE id = :exercise_id AND template_id = :template_id"
            db.execute(text(sql), params)
            _sync_template_exercises_json(db, template_id)
            db.commit()

        return {"success": True, "message": "Exercise updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update template exercise: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/templates/{template_id}/exercises/{exercise_id}")
async def delete_template_exercise(
    template_id: str,
    exercise_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Remove an exercise from a template"""
    try:
        # Verify user owns this template
        template = db.execute(text("""
            SELECT id FROM fitness_template WHERE id = :template_id AND user_id = :user_id
        """), {"template_id": template_id, "user_id": user_id}).fetchone()

        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        db.execute(text("""
            DELETE FROM template_exercise
            WHERE id = :exercise_id AND template_id = :template_id
        """), {"exercise_id": exercise_id, "template_id": template_id})
        _sync_template_exercises_json(db, template_id)
        db.commit()

        return {"success": True, "message": "Exercise removed from template"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete template exercise: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/templates/{template_id}/exercises/reorder")
async def reorder_template_exercises(
    template_id: str,
    exercise_ids: List[str],
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Reorder exercises in a template"""
    try:
        # Verify user owns this template
        template = db.execute(text("""
            SELECT id FROM fitness_template WHERE id = :template_id AND user_id = :user_id
        """), {"template_id": template_id, "user_id": user_id}).fetchone()

        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # Update order_index for each exercise
        for idx, exercise_id in enumerate(exercise_ids):
            db.execute(text("""
                UPDATE template_exercise
                SET order_index = :order_index, updated_at = CURRENT_TIMESTAMP
                WHERE id = :exercise_id AND template_id = :template_id
            """), {"order_index": idx, "exercise_id": exercise_id, "template_id": template_id})

        _sync_template_exercises_json(db, template_id)
        db.commit()
        return {"success": True, "message": "Exercises reordered successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to reorder exercises: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# EXERCISE PR (Personal Record) APIs
# ============================================

class ExercisePRCreate(BaseModel):
    exercise_name: str
    weight: float
    reps: int
    achieved_at: date
    workout_set_id: Optional[str] = None


@router.get("/prs")
async def list_exercise_prs(
    exercise_name: Optional[str] = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get all PRs, optionally filtered by exercise"""
    try:
        if exercise_name:
            prs = db.execute(text("""
                SELECT id, exercise_name, weight, reps, estimated_1rm, achieved_at, workout_set_id, created_at
                FROM exercise_pr
                WHERE user_id = :user_id AND exercise_name = :exercise_name
                ORDER BY estimated_1rm DESC, achieved_at DESC
            """), {"user_id": user_id, "exercise_name": exercise_name}).fetchall()
        else:
            # Get best PR for each exercise
            prs = db.execute(text("""
                SELECT DISTINCT ON (exercise_name)
                    id, exercise_name, weight, reps, estimated_1rm, achieved_at, workout_set_id, created_at
                FROM exercise_pr
                WHERE user_id = :user_id
                ORDER BY exercise_name, estimated_1rm DESC
            """), {"user_id": user_id}).fetchall()

        return {"prs": [dict(row._mapping) for row in prs]}
    except Exception as e:
        logger.error(f"Failed to list PRs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prs/{exercise_name}")
async def get_exercise_pr_history(
    exercise_name: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get PR history for a specific exercise"""
    try:
        prs = db.execute(text("""
            SELECT id, exercise_name, weight, reps, estimated_1rm, achieved_at, workout_set_id, created_at
            FROM exercise_pr
            WHERE user_id = :user_id AND exercise_name = :exercise_name
            ORDER BY achieved_at DESC
        """), {"user_id": user_id, "exercise_name": exercise_name}).fetchall()

        return {"prs": [dict(row._mapping) for row in prs]}
    except Exception as e:
        logger.error(f"Failed to get PR history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def calculate_estimated_1rm(weight: float, reps: int) -> float:
    """Calculate estimated 1RM using Brzycki formula"""
    if reps == 1:
        return weight
    if reps > 12:
        reps = 12  # Cap at 12 for accuracy
    return round(weight * (36 / (37 - reps)), 2)


async def check_and_record_pr(
    db: Session,
    user_id: str,
    exercise_name: str,
    weight: float,
    reps: int,
    achieved_at: date,
    workout_set_id: Optional[str] = None
) -> Optional[dict]:
    """Check if this is a new PR and record it if so"""
    try:
        estimated_1rm = calculate_estimated_1rm(weight, reps)

        # Check current best PR for this exercise
        current_best = db.execute(text("""
            SELECT MAX(estimated_1rm) as best_1rm
            FROM exercise_pr
            WHERE user_id = :user_id AND exercise_name = :exercise_name
        """), {"user_id": user_id, "exercise_name": exercise_name}).fetchone()

        is_pr = current_best is None or current_best.best_1rm is None or estimated_1rm > current_best.best_1rm

        if is_pr:
            pr_id = str(uuid.uuid4())
            db.execute(text("""
                INSERT INTO exercise_pr (id, user_id, exercise_name, weight, reps, estimated_1rm, achieved_at, workout_set_id)
                VALUES (:id, :user_id, :exercise_name, :weight, :reps, :estimated_1rm, :achieved_at, :workout_set_id)
            """), {
                "id": pr_id,
                "user_id": user_id,
                "exercise_name": exercise_name,
                "weight": weight,
                "reps": reps,
                "estimated_1rm": estimated_1rm,
                "achieved_at": achieved_at,
                "workout_set_id": workout_set_id
            })

            return {
                "is_pr": True,
                "pr_id": pr_id,
                "estimated_1rm": estimated_1rm,
                "previous_best": current_best.best_1rm if current_best and current_best.best_1rm else None
            }

        return {"is_pr": False, "estimated_1rm": estimated_1rm}
    except Exception as e:
        logger.error(f"Failed to check/record PR: {e}")
        return None


# ============================================
# WEIGHT TREND APIs
# ============================================

class WeightEntryCreate(BaseModel):
    date: date
    raw_weight: float


@router.get("/weight/trend")
async def get_weight_trend(
    days: int = 30,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get weight trend data for the specified number of days"""
    try:
        weights = db.execute(text("""
            SELECT id, date, raw_weight, trend_weight, weekly_delta, created_at
            FROM weight_trend
            WHERE user_id = :user_id
            AND date >= CURRENT_DATE - INTERVAL ':days days'
            ORDER BY date ASC
        """.replace(":days", str(days))), {"user_id": user_id}).fetchall()

        return {"weights": [dict(row._mapping) for row in weights]}
    except Exception as e:
        logger.error(f"Failed to get weight trend: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/weight")
async def log_weight(
    entry: WeightEntryCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Log a weight entry and update trend"""
    try:
        # Get recent weights for trend calculation (7-day exponential moving average)
        recent = db.execute(text("""
            SELECT raw_weight, trend_weight, date
            FROM weight_trend
            WHERE user_id = :user_id AND date < :date
            ORDER BY date DESC
            LIMIT 7
        """), {"user_id": user_id, "date": entry.date}).fetchall()

        # Calculate trend using exponential smoothing (alpha = 0.1)
        alpha = 0.1
        if recent and recent[0].trend_weight:
            trend_weight = round(alpha * entry.raw_weight + (1 - alpha) * float(recent[0].trend_weight), 2)
        else:
            trend_weight = entry.raw_weight

        # Calculate weekly delta
        weekly_delta = None
        if len(recent) >= 7:
            week_ago_weight = recent[6].raw_weight
            weekly_delta = round(entry.raw_weight - float(week_ago_weight), 2)

        weight_id = str(uuid.uuid4())

        # Upsert (in case logging for same date twice)
        db.execute(text("""
            INSERT INTO weight_trend (id, user_id, date, raw_weight, trend_weight, weekly_delta)
            VALUES (:id, :user_id, :date, :raw_weight, :trend_weight, :weekly_delta)
            ON CONFLICT (user_id, date)
            DO UPDATE SET
                raw_weight = EXCLUDED.raw_weight,
                trend_weight = EXCLUDED.trend_weight,
                weekly_delta = EXCLUDED.weekly_delta
        """), {
            "id": weight_id,
            "user_id": user_id,
            "date": entry.date,
            "raw_weight": entry.raw_weight,
            "trend_weight": trend_weight,
            "weekly_delta": weekly_delta
        })
        db.commit()

        return {
            "success": True,
            "raw_weight": entry.raw_weight,
            "trend_weight": trend_weight,
            "weekly_delta": weekly_delta
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to log weight: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/weight/latest")
async def get_latest_weight(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get the most recent weight entry"""
    try:
        weight = db.execute(text("""
            SELECT id, date, raw_weight, trend_weight, weekly_delta, created_at
            FROM weight_trend
            WHERE user_id = :user_id
            ORDER BY date DESC
            LIMIT 1
        """), {"user_id": user_id}).fetchone()

        if weight:
            return dict(weight._mapping)
        return {"message": "No weight entries found"}
    except Exception as e:
        logger.error(f"Failed to get latest weight: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# FITNESS SETTINGS APIs
# ============================================

class FitnessSettingsUpdate(BaseModel):
    system_prompt: Optional[str] = None

@router.get("/settings")
async def get_fitness_settings(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Get fitness settings including custom system prompt"""
    try:
        settings = db.execute(text("""
            SELECT id, system_prompt, created_at, updated_at
            FROM fitness_settings
            WHERE user_id = :user_id
        """), {"user_id": user_id}).fetchone()

        if settings:
            return dict(settings._mapping)
        else:
            # Return default
            return {"system_prompt": None, "message": "No custom settings yet"}
    except Exception as e:
        logger.error(f"Failed to get settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/settings")
async def update_fitness_settings(settings: FitnessSettingsUpdate, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Update fitness settings"""
    try:
        # Upsert settings
        db.execute(text("""
            INSERT INTO fitness_settings (id, user_id, system_prompt, updated_at)
            VALUES (:id, :user_id, :system_prompt, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id)
            DO UPDATE SET
                system_prompt = EXCLUDED.system_prompt,
                updated_at = CURRENT_TIMESTAMP
        """), {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "system_prompt": settings.system_prompt
        })
        db.commit()

        return {"success": True, "message": "Settings updated successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# RECOVERY LOG ENDPOINTS
# =============================================================================

def _recovery_baseline(db: Session, user_id: str, days: int = 7) -> dict:
    """Trailing-window averages used to score HRV/resting-HR relative to normal."""
    row = db.execute(text("""
        SELECT AVG(hrv) AS avg_hrv, AVG(heart_rate) AS avg_hr
        FROM daily_recovery_log
        WHERE user_id = :uid
          AND log_date >= (CURRENT_DATE - (:days || ' days')::interval)
    """), {"uid": user_id, "days": days}).fetchone()
    return {
        "avg_hrv": float(row.avg_hrv) if row and row.avg_hrv is not None else None,
        "avg_hr": float(row.avg_hr) if row and row.avg_hr is not None else None,
    }


def _recovery_response(row, baseline: dict) -> RecoveryLogResponse:
    """Build a RecoveryLogResponse from a daily_recovery_log row, attaching the
    server-computed readiness score (single source of truth)."""
    from app.services.recovery_score import compute_readiness
    r = compute_readiness({
        "sleep_hours": float(row['sleep_hours']) if row['sleep_hours'] else None,
        "hrv": row['hrv'],
        "heart_rate": row['heart_rate'],
        "soreness_level": row['soreness_level'],
    }, baseline)
    return RecoveryLogResponse(
        id=row['id'],
        user_id=row['user_id'],
        log_date=row['log_date'].isoformat(),
        hrv=row['hrv'],
        heart_rate=row['heart_rate'],
        sleep_hours=float(row['sleep_hours']) if row['sleep_hours'] else None,
        soreness_level=row['soreness_level'],
        body_weight=float(row['body_weight']) if row['body_weight'] else None,
        weight_unit=row['weight_unit'],
        notes=row['notes'],
        created_at=row['created_at'].isoformat(),
        updated_at=row['updated_at'].isoformat(),
        readiness_score=r["score"],
        readiness_label=r["label"],
        readiness_status=r["status"],
        readiness_color=r["color"],
    )


@router.post("/recovery", response_model=RecoveryLogResponse)
async def create_or_update_recovery_log(
    recovery_data: RecoveryLogCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Create or update daily recovery log"""
    try:
        # Validate soreness level if provided
        if recovery_data.soreness_level is not None:
            if recovery_data.soreness_level < 1 or recovery_data.soreness_level > 10:
                raise HTTPException(status_code=400, detail="Soreness level must be between 1 and 10")

        # Parse log_date
        try:
            log_date = datetime.strptime(recovery_data.log_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

        # Check if entry exists for this date
        check_query = text("""
            SELECT id FROM daily_recovery_log
            WHERE user_id = :user_id AND log_date = :log_date
        """)
        existing = db.execute(check_query, {"user_id": user_id, "log_date": log_date}).fetchone()

        if existing:
            # Update existing entry
            update_query = text("""
                UPDATE daily_recovery_log
                SET hrv = :hrv,
                    heart_rate = :heart_rate,
                    sleep_hours = :sleep_hours,
                    soreness_level = :soreness_level,
                    body_weight = :body_weight,
                    weight_unit = :weight_unit,
                    notes = :notes,
                    updated_at = NOW()
                WHERE user_id = :user_id AND log_date = :log_date
                RETURNING id, user_id, log_date, hrv, heart_rate, sleep_hours, soreness_level, body_weight, weight_unit, notes, created_at, updated_at
            """)
            result = db.execute(update_query, {
                "user_id": user_id,
                "log_date": log_date,
                "hrv": recovery_data.hrv,
                "heart_rate": recovery_data.heart_rate,
                "sleep_hours": recovery_data.sleep_hours,
                "soreness_level": recovery_data.soreness_level,
                "body_weight": recovery_data.body_weight,
                "weight_unit": recovery_data.weight_unit,
                "notes": recovery_data.notes
            }).fetchone()
        else:
            # Insert new entry
            insert_query = text("""
                INSERT INTO daily_recovery_log
                (id, user_id, log_date, hrv, heart_rate, sleep_hours, soreness_level, body_weight, weight_unit, notes, created_at, updated_at)
                VALUES (:id, :user_id, :log_date, :hrv, :heart_rate, :sleep_hours, :soreness_level, :body_weight, :weight_unit, :notes, NOW(), NOW())
                RETURNING id, user_id, log_date, hrv, heart_rate, sleep_hours, soreness_level, body_weight, weight_unit, notes, created_at, updated_at
            """)
            result = db.execute(insert_query, {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "log_date": log_date,
                "hrv": recovery_data.hrv,
                "heart_rate": recovery_data.heart_rate,
                "sleep_hours": recovery_data.sleep_hours,
                "soreness_level": recovery_data.soreness_level,
                "body_weight": recovery_data.body_weight,
                "weight_unit": recovery_data.weight_unit,
                "notes": recovery_data.notes
            }).fetchone()

        # If body_weight was logged, also sync to weight_trend table for dashboard
        if recovery_data.body_weight:
            # Check if weight_trend entry exists for this date
            existing_weight = db.execute(text("""
                SELECT id FROM weight_trend WHERE user_id = :user_id AND date = :date
            """), {"user_id": user_id, "date": log_date}).fetchone()

            # Get previous weight for trend calculation
            prev_weight = db.execute(text("""
                SELECT trend_weight FROM weight_trend
                WHERE user_id = :user_id AND date < :date
                ORDER BY date DESC LIMIT 1
            """), {"user_id": user_id, "date": log_date}).fetchone()

            prev_trend = prev_weight.trend_weight if prev_weight else recovery_data.body_weight
            alpha = 0.1  # Smoothing factor
            trend_weight = round(alpha * recovery_data.body_weight + (1 - alpha) * float(prev_trend), 2)

            if existing_weight:
                db.execute(text("""
                    UPDATE weight_trend
                    SET raw_weight = :raw_weight, trend_weight = :trend_weight, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = :user_id AND date = :date
                """), {
                    "user_id": user_id,
                    "date": log_date,
                    "raw_weight": recovery_data.body_weight,
                    "trend_weight": trend_weight
                })
            else:
                db.execute(text("""
                    INSERT INTO weight_trend (id, user_id, date, raw_weight, trend_weight)
                    VALUES (:id, :user_id, :date, :raw_weight, :trend_weight)
                """), {
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "date": log_date,
                    "raw_weight": recovery_data.body_weight,
                    "trend_weight": trend_weight
                })

        db.commit()

        # Convert result to response model (with server-computed readiness)
        return _recovery_response(result._mapping, _recovery_baseline(db, user_id))

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save recovery log: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recovery/{log_date}", response_model=Optional[RecoveryLogResponse])
async def get_recovery_log(
    log_date: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get recovery log for a specific date"""
    try:
        # Parse and validate date
        try:
            parsed_date = datetime.strptime(log_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

        query = text("""
            SELECT id, user_id, log_date, hrv, heart_rate, sleep_hours, soreness_level, body_weight, weight_unit, notes, created_at, updated_at
            FROM daily_recovery_log
            WHERE user_id = :user_id AND log_date = :log_date
        """)
        result = db.execute(query, {"user_id": user_id, "log_date": parsed_date}).fetchone()

        if not result:
            return None

        return _recovery_response(result._mapping, _recovery_baseline(db, user_id))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get recovery log: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recovery/recent/list", response_model=List[RecoveryLogResponse])
async def get_recent_recovery_logs(
    days: int = 7,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get recent recovery logs (default: last 7 days)"""
    try:
        # Limit days to reasonable range
        if days < 1:
            days = 7
        if days > 90:
            days = 90

        query = text("""
            SELECT id, user_id, log_date, hrv, heart_rate, sleep_hours, soreness_level, body_weight, weight_unit, notes, created_at, updated_at
            FROM daily_recovery_log
            WHERE user_id = :user_id
            ORDER BY log_date DESC
            LIMIT :limit
        """)
        results = db.execute(query, {"user_id": user_id, "limit": days}).fetchall()

        # One baseline over the window, so each day's score is stable across the
        # series (matches how the app drew its trend line).
        baseline = _recovery_baseline(db, user_id, days)
        return [_recovery_response(row._mapping, baseline) for row in results]

    except Exception as e:
        logger.error(f"Failed to get recent recovery logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RECIPE ROUTES
# ============================================================================

async def estimate_recipe_nutrition(ingredients: List[IngredientItem], servings: int = 1) -> dict:
    """
    Per-serving macros from FatSecret (services.recipe_nutrition), reusing the
    same quantity/unit scaling meal logging uses. Explicit per-ingredient macros
    (live-picked or manual) win; only unresolved ingredients hit FatSecret.

    Returns {calories, protein, carbs, fats}. Values are None when not a single
    ingredient could be resolved — callers store NULL rather than a fake 0.00
    (the macaroni-salad bug, see recipe_nutrition.macros_missing).
    """
    from app.services.recipe_nutrition import estimate_recipe_nutrition as _estimate

    ing_dicts = [ing.dict() for ing in (ingredients or [])]
    result = await _estimate(ing_dicts, servings)
    if not result:
        return {"calories": None, "protein": None, "carbs": None, "fats": None}
    return result


@router.get("/recipes", response_model=List[RecipeResponse])
async def list_recipes(
    category: Optional[str] = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """List all recipes with optional category filter"""
    try:
        if category:
            query = text("""
                SELECT id, user_id, name, description, category, ingredients, instructions,
                       prep_time_minutes, servings, calories, protein, carbs, fats,
                       created_at, updated_at
                FROM recipe
                WHERE user_id = :user_id AND category = :category
                ORDER BY created_at DESC
            """)
            results = db.execute(query, {"user_id": user_id, "category": category}).fetchall()
        else:
            query = text("""
                SELECT id, user_id, name, description, category, ingredients, instructions,
                       prep_time_minutes, servings, calories, protein, carbs, fats,
                       created_at, updated_at
                FROM recipe
                WHERE user_id = :user_id
                ORDER BY created_at DESC
            """)
            results = db.execute(query, {"user_id": user_id}).fetchall()

        recipes = []
        for row in results:
            row_dict = dict(row._mapping)
            try:
                # Parse JSON ingredients
                ingredients_data = row_dict['ingredients']
                if isinstance(ingredients_data, str):
                    import json
                    ingredients_data = json.loads(ingredients_data)

                ingredients = [IngredientItem(**ing) for ing in ingredients_data]

                recipes.append(RecipeResponse(
                    id=row_dict['id'],
                    user_id=row_dict['user_id'],
                    name=row_dict['name'],
                    description=row_dict['description'],
                    category=row_dict['category'],
                    ingredients=ingredients,
                    instructions=row_dict['instructions'],
                    prep_time_minutes=row_dict['prep_time_minutes'],
                    servings=row_dict['servings'],
                    calories=float(row_dict['calories']) if row_dict['calories'] else None,
                    protein=float(row_dict['protein']) if row_dict['protein'] else None,
                    carbs=float(row_dict['carbs']) if row_dict['carbs'] else None,
                    fats=float(row_dict['fats']) if row_dict['fats'] else None,
                    created_at=row_dict['created_at'].isoformat(),
                    updated_at=row_dict['updated_at'].isoformat()
                ))
            except Exception as row_err:
                # One malformed recipe must never take the whole list down —
                # this exact bug (a single bad row 500ing the entire endpoint)
                # is why the iOS Recipes screen failed to load at all.
                logger.error(f"Skipping unparseable recipe {row_dict.get('id')}: {row_err}")
                continue

        return recipes

    except Exception as e:
        logger.error(f"Failed to list recipes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recipes", response_model=RecipeResponse)
async def create_recipe(
    recipe: RecipeCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Create a new recipe with auto nutrition calculation"""
    try:
        import uuid
        import json

        recipe_id = str(uuid.uuid4())

        # Calculate nutrition (accurate FatSecret estimator)
        nutrition = await estimate_recipe_nutrition(recipe.ingredients, recipe.servings)

        # Convert ingredients to JSON
        ingredients_json = json.dumps([ing.dict() for ing in recipe.ingredients])

        query = text("""
            INSERT INTO recipe
            (id, user_id, name, description, category, ingredients, instructions,
             prep_time_minutes, servings, calories, protein, carbs, fats, created_at, updated_at)
            VALUES (:id, :user_id, :name, :description, :category, :ingredients, :instructions,
                    :prep_time_minutes, :servings, :calories, :protein, :carbs, :fats, NOW(), NOW())
            RETURNING id, user_id, name, description, category, ingredients, instructions,
                      prep_time_minutes, servings, calories, protein, carbs, fats, created_at, updated_at
        """)

        result = db.execute(query, {
            "id": recipe_id,
            "user_id": user_id,
            "name": recipe.name,
            "description": recipe.description,
            "category": recipe.category,
            "ingredients": ingredients_json,
            "instructions": recipe.instructions,
            "prep_time_minutes": recipe.prep_time_minutes,
            "servings": recipe.servings,
            "calories": nutrition['calories'],
            "protein": nutrition['protein'],
            "carbs": nutrition['carbs'],
            "fats": nutrition['fats']
        }).fetchone()

        db.commit()

        row_dict = dict(result._mapping)
        ingredients_data = json.loads(row_dict['ingredients']) if isinstance(row_dict['ingredients'], str) else row_dict['ingredients']
        ingredients = [IngredientItem(**ing) for ing in ingredients_data]

        return RecipeResponse(
            id=row_dict['id'],
            user_id=row_dict['user_id'],
            name=row_dict['name'],
            description=row_dict['description'],
            category=row_dict['category'],
            ingredients=ingredients,
            instructions=row_dict['instructions'],
            prep_time_minutes=row_dict['prep_time_minutes'],
            servings=row_dict['servings'],
            calories=float(row_dict['calories']) if row_dict['calories'] else None,
            protein=float(row_dict['protein']) if row_dict['protein'] else None,
            carbs=float(row_dict['carbs']) if row_dict['carbs'] else None,
            fats=float(row_dict['fats']) if row_dict['fats'] else None,
            created_at=row_dict['created_at'].isoformat(),
            updated_at=row_dict['updated_at'].isoformat()
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create recipe: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recipes/{recipe_id}", response_model=RecipeResponse)
async def get_recipe(
    recipe_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get a specific recipe by ID"""
    try:
        import json

        query = text("""
            SELECT id, user_id, name, description, category, ingredients, instructions,
                   prep_time_minutes, servings, calories, protein, carbs, fats,
                   created_at, updated_at
            FROM recipe
            WHERE id = :recipe_id AND user_id = :user_id
        """)

        result = db.execute(query, {"recipe_id": recipe_id, "user_id": user_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Recipe not found")

        row_dict = dict(result._mapping)
        ingredients_data = json.loads(row_dict['ingredients']) if isinstance(row_dict['ingredients'], str) else row_dict['ingredients']
        ingredients = [IngredientItem(**ing) for ing in ingredients_data]

        return RecipeResponse(
            id=row_dict['id'],
            user_id=row_dict['user_id'],
            name=row_dict['name'],
            description=row_dict['description'],
            category=row_dict['category'],
            ingredients=ingredients,
            instructions=row_dict['instructions'],
            prep_time_minutes=row_dict['prep_time_minutes'],
            servings=row_dict['servings'],
            calories=float(row_dict['calories']) if row_dict['calories'] else None,
            protein=float(row_dict['protein']) if row_dict['protein'] else None,
            carbs=float(row_dict['carbs']) if row_dict['carbs'] else None,
            fats=float(row_dict['fats']) if row_dict['fats'] else None,
            created_at=row_dict['created_at'].isoformat(),
            updated_at=row_dict['updated_at'].isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get recipe: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/recipes/{recipe_id}", response_model=RecipeResponse)
async def update_recipe(
    recipe_id: str,
    updates: RecipeUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Update a recipe"""
    try:
        import json

        # Check recipe exists
        check_query = text("SELECT id FROM recipe WHERE id = :recipe_id AND user_id = :user_id")
        exists = db.execute(check_query, {"recipe_id": recipe_id, "user_id": user_id}).fetchone()

        if not exists:
            raise HTTPException(status_code=404, detail="Recipe not found")

        # Build update query dynamically
        update_fields = []
        params = {"recipe_id": recipe_id, "user_id": user_id}

        if updates.name is not None:
            update_fields.append("name = :name")
            params["name"] = updates.name

        if updates.description is not None:
            update_fields.append("description = :description")
            params["description"] = updates.description

        if updates.category is not None:
            update_fields.append("category = :category")
            params["category"] = updates.category

        if updates.instructions is not None:
            update_fields.append("instructions = :instructions")
            params["instructions"] = updates.instructions

        if updates.prep_time_minutes is not None:
            update_fields.append("prep_time_minutes = :prep_time_minutes")
            params["prep_time_minutes"] = updates.prep_time_minutes

        if updates.servings is not None:
            update_fields.append("servings = :servings")
            params["servings"] = updates.servings

        if updates.ingredients is not None:
            # Recalculate nutrition (accurate FatSecret estimator)
            servings = updates.servings if updates.servings else 1
            nutrition = await estimate_recipe_nutrition(updates.ingredients, servings)

            ingredients_json = json.dumps([ing.dict() for ing in updates.ingredients])
            update_fields.append("ingredients = :ingredients")
            update_fields.append("calories = :calories")
            update_fields.append("protein = :protein")
            update_fields.append("carbs = :carbs")
            update_fields.append("fats = :fats")
            params["ingredients"] = ingredients_json
            params["calories"] = nutrition['calories']
            params["protein"] = nutrition['protein']
            params["carbs"] = nutrition['carbs']
            params["fats"] = nutrition['fats']

        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")

        update_fields.append("updated_at = NOW()")

        update_query = text(f"""
            UPDATE recipe
            SET {', '.join(update_fields)}
            WHERE id = :recipe_id AND user_id = :user_id
            RETURNING id, user_id, name, description, category, ingredients, instructions,
                      prep_time_minutes, servings, calories, protein, carbs, fats, created_at, updated_at
        """)

        result = db.execute(update_query, params).fetchone()
        db.commit()

        row_dict = dict(result._mapping)
        ingredients_data = json.loads(row_dict['ingredients']) if isinstance(row_dict['ingredients'], str) else row_dict['ingredients']
        ingredients = [IngredientItem(**ing) for ing in ingredients_data]

        return RecipeResponse(
            id=row_dict['id'],
            user_id=row_dict['user_id'],
            name=row_dict['name'],
            description=row_dict['description'],
            category=row_dict['category'],
            ingredients=ingredients,
            instructions=row_dict['instructions'],
            prep_time_minutes=row_dict['prep_time_minutes'],
            servings=row_dict['servings'],
            calories=float(row_dict['calories']) if row_dict['calories'] else None,
            protein=float(row_dict['protein']) if row_dict['protein'] else None,
            carbs=float(row_dict['carbs']) if row_dict['carbs'] else None,
            fats=float(row_dict['fats']) if row_dict['fats'] else None,
            created_at=row_dict['created_at'].isoformat(),
            updated_at=row_dict['updated_at'].isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update recipe: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/recipes/{recipe_id}")
async def delete_recipe(
    recipe_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Delete a recipe"""
    try:
        query = text("DELETE FROM recipe WHERE id = :recipe_id AND user_id = :user_id RETURNING id")
        result = db.execute(query, {"recipe_id": recipe_id, "user_id": user_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Recipe not found")

        db.commit()
        return {"message": "Recipe deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete recipe: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# =============================================================================
# WORKOUT SESSION MANAGEMENT ENDPOINTS (Phase 6)
# =============================================================================

class WorkoutSetLog(BaseModel):
    exercise_name: str
    set_number: int
    weight: Optional[float] = None
    reps: Optional[int] = None
    rpe: Optional[int] = None  # Rate of Perceived Exertion (1-10)
    notes: Optional[str] = ""


@router.get("/sessions/by-event/{event_id}")
async def get_session_by_event_id(
    event_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Helper endpoint to get workout session ID from calendar event ID
    """
    try:
        query = text("""
            SELECT id FROM workout_session
            WHERE calendar_event_id = :event_id AND user_id = :user_id
        """)
        result = db.execute(query, {"event_id": event_id, "user_id": user_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Workout session not found for this event")

        return {"session_id": result.id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session by event ID: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}")
async def get_workout_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get workout session details including template, exercises, and logged sets
    """
    try:
        import json
        from app.services.progressive_overload import suggest_weight, get_deload_state, get_morning_recovery

        # Get session with template
        session_query = text("""
            SELECT
                ws.id, ws.user_id, ws.template_id, ws.session_date, ws.status,
                ws.started_at, ws.completed_at, ws.created_at,
                ft.name as template_name, ft.exercises, ft.notes as template_notes,
                ft.starting_weights, ft.phase_id
            FROM workout_session ws
            LEFT JOIN fitness_template ft ON ws.template_id = ft.id
            WHERE ws.id = :session_id AND ws.user_id = :user_id
        """)
        session = db.execute(session_query, {"session_id": session_id, "user_id": user_id}).fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Workout session not found")

        session_dict = dict(session._mapping)

        # Parse exercises JSON
        if session_dict.get('exercises'):
            session_dict['exercises'] = json.loads(session_dict['exercises'])
        else:
            session_dict['exercises'] = []

        # Parse starting_weights JSON
        starting_weights = None
        if session_dict.get('starting_weights'):
            try:
                starting_weights = json.loads(session_dict['starting_weights'])
            except:
                starting_weights = None

        # Get logged sets for this session
        sets_query = text("""
            SELECT id, exercise_id, set_index, weight, reps, rpe, notes,
                   set_kind, set_group_id, group_sequence, parent_set_id,
                   COALESCE(session_time, created_at) AS logged_at
            FROM workout_log
            WHERE session_id = :session_id AND voided_at IS NULL
            ORDER BY COALESCE(session_time, created_at), group_sequence
        """)
        logged_sets = db.execute(sets_query, {"session_id": session_id}).fetchall()
        session_dict['logged_sets'] = [dict(row._mapping) for row in logged_sets]

        # Morning recovery snapshot (frozen at the AM sync — not intraday).
        session_dict['recovery_data'] = get_morning_recovery(db, user_id, date.today())

        # Determine deload state for the session date (or today if missing)
        deload = get_deload_state(
            db=db,
            user_id=user_id,
            on_date=session_dict.get('session_date') or date.today(),
        )
        session_dict['is_deload'] = deload['is_deload']
        session_dict['week_of_phase'] = deload['week_of_phase']
        session_dict['deload_week'] = deload['deload_week']
        session_dict['phase_name'] = deload['phase_name']

        # Pull active phase nutrition targets so the frontend can display
        # training-day vs rest-day macros + step goals during the workout.
        if session_dict.get('phase_id'):
            phase_nut = db.execute(text("""
                SELECT calories_target, protein_target, carbs_target, fat_target,
                       calories_training_day, calories_rest_day,
                       carbs_training_day, carbs_rest_day,
                       fat_training_day, fat_rest_day,
                       daily_steps_target
                FROM fitness_phase
                WHERE id = :pid
            """), {"pid": session_dict['phase_id']}).fetchone()
            session_dict['phase_nutrition'] = dict(phase_nut._mapping) if phase_nut else None
        else:
            session_dict['phase_nutrition'] = None

        # Generate AI weight suggestions for each exercise.
        # Apply deload sets-halving and surface advanced fields (per_side, metric_type,
        # superset_group, set_technique) the JSON dicts now carry.
        recovery_data = session_dict['recovery_data']
        for exercise in session_dict['exercises']:
            exercise_name = exercise['name']

            # Extract target reps (parse "8-10" or "10" format)
            target_reps = 10  # Default
            if exercise.get('reps'):
                try:
                    reps_str = str(exercise['reps'])
                    if '-' in reps_str:
                        # Take the lower end of the range (e.g., "8-10" -> 8)
                        target_reps = int(reps_str.split('-')[0])
                    else:
                        target_reps = int(reps_str)
                except:
                    target_reps = 10

            # Get starting weight if configured
            starting_weight = None
            if starting_weights and exercise_name in starting_weights:
                starting_weight = starting_weights[exercise_name]

            # Generate AI suggestion (deload-aware)
            suggestion = suggest_weight(
                db=db,
                user_id=user_id,
                exercise_name=exercise_name,
                target_reps=target_reps,
                recovery_data=recovery_data,
                starting_weight=starting_weight,
                is_deload=session_dict['is_deload'],
            )

            exercise['weight_suggestion'] = suggestion

            # On deload, halve target sets (min 2). Reflect this on the exercise dict
            # so the UI shows the deload prescription instead of the normal one.
            if session_dict['is_deload'] and exercise.get('sets'):
                try:
                    base_sets = int(exercise['sets'])
                    exercise['sets_original'] = base_sets
                    exercise['sets'] = max(2, base_sets // 2)
                except (TypeError, ValueError):
                    pass

            # Defaults so older JSON dicts (without the new keys) don't break the UI
            exercise.setdefault('metric_type', 'reps')
            exercise.setdefault('is_per_side', False)
            exercise.setdefault('superset_group', None)
            exercise.setdefault('set_technique', None)

        return session_dict

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get workout session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/start")
async def start_workout_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Start a workout session
    - Updates status to 'in_progress'
    - Sets started_at timestamp
    """
    try:
        # Verify session exists and belongs to user
        check_query = text("""
            SELECT status FROM workout_session
            WHERE id = :session_id AND user_id = :user_id
        """)
        session = db.execute(check_query, {"session_id": session_id, "user_id": user_id}).fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Workout session not found")

        if session.status == 'completed':
            raise HTTPException(status_code=400, detail="Cannot start a completed workout")

        # Update session
        update_query = text("""
            UPDATE workout_session
            SET status = 'in_progress', started_at = NOW(), updated_at = NOW()
            WHERE id = :session_id AND user_id = :user_id
        """)
        db.execute(update_query, {"session_id": session_id, "user_id": user_id})
        db.commit()

        return {"message": "Workout session started", "session_id": session_id, "status": "in_progress"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to start workout session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/log-set")
async def log_workout_set(
    session_id: str,
    set_data: WorkoutSetLog,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Log a single set during an active workout session
    """
    try:
        # Verify session exists
        check_query = text("""
            SELECT id FROM workout_session
            WHERE id = :session_id AND user_id = :user_id
        """)
        session = db.execute(check_query, {"session_id": session_id, "user_id": user_id}).fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Workout session not found")

        # Insert set log
        log_id = str(uuid.uuid4())
        insert_query = text("""
            INSERT INTO workout_log (
                id, user_id, session_id, exercise_id, set_index,
                weight, reps, rpe, notes, logged_at
            )
            VALUES (
                :id, :user_id, :session_id, :exercise_id, :set_index,
                :weight, :reps, :rpe, :notes, NOW()
            )
        """)

        db.execute(insert_query, {
            "id": log_id,
            "user_id": user_id,
            "session_id": session_id,
            "exercise_id": set_data.exercise_name,  # Using exercise name as ID for simplicity
            "set_index": set_data.set_number,
            "weight": set_data.weight,
            "reps": set_data.reps,
            "rpe": set_data.rpe,
            "notes": set_data.notes
        })
        db.commit()

        return {
            "message": "Set logged successfully",
            "log_id": log_id,
            "exercise": set_data.exercise_name,
            "set_number": set_data.set_number
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to log workout set: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/complete")
async def complete_workout_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Complete a workout session
    - Updates status to 'completed'
    - Sets completed_at timestamp
    """
    try:
        # Verify session exists
        check_query = text("""
            SELECT id, status FROM workout_session
            WHERE id = :session_id AND user_id = :user_id
        """)
        session = db.execute(check_query, {"session_id": session_id, "user_id": user_id}).fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Workout session not found")

        if session.status == 'completed':
            raise HTTPException(status_code=400, detail="Workout session already completed")

        # Update session status
        update_query = text("""
            UPDATE workout_session
            SET status = 'completed', completed_at = NOW(), updated_at = NOW()
            WHERE id = :session_id AND user_id = :user_id
        """)
        db.execute(update_query, {"session_id": session_id, "user_id": user_id})
        db.commit()

        # Get completion summary
        summary_query = text("""
            SELECT
                COUNT(DISTINCT exercise_id) as exercises_completed,
                -- Working sets only: a three-segment drop set is one set done,
                -- and volume still counts every segment (§4.4).
                COUNT(*) FILTER (WHERE COALESCE(counts_toward_target, true)) as total_sets,
                SUM(weight * reps) as total_volume
            FROM workout_log
            WHERE session_id = :session_id AND voided_at IS NULL
        """)
        summary = db.execute(summary_query, {"session_id": session_id}).fetchone()

        summary_dict = dict(summary._mapping) if summary else {}
        _emit_domain_event_safe(EventType.WORKOUT_COMPLETED, user_id, {
            "type": "workout",
            "exercises": summary_dict.get("exercises_completed"),
            "total_sets": summary_dict.get("total_sets"),
        })

        return {
            "message": "Workout session completed successfully",
            "session_id": session_id,
            "status": "completed",
            "summary": summary_dict
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to complete workout session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ACTIVE WORKOUT SESSION ENDPOINTS (Real-time Sara Coaching)
# =============================================================================

class StartWorkoutRequest(BaseModel):
    """Request body for starting a workout session"""
    template_id: str


class LogSetRequest(BaseModel):
    """Request body for logging a set during active workout"""
    weight: Optional[float] = None
    reps: Optional[int] = None
    rpe: Optional[int] = None
    rpe_feeling: Optional[str] = None  # "light", "moderate", "hard", "failed"
    notes: Optional[str] = None


class RestTimerRequest(BaseModel):
    """Request body for rest timer actions"""
    action: str  # "start" or "stop"
    duration: Optional[int] = None  # seconds, only for "start"


@router.post("/workout-session/start")
async def start_active_workout(
    request: StartWorkoutRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Start an active workout session for real-time Sara coaching.

    - Creates new session with workout snapshot including weight suggestions
    - Returns session with full exercise plan

    With WORKOUT_COMMAND_V2_ENABLED off this still implicitly abandons any
    running session, as it always has. With it on, a different active workout
    is a 409 the user resolves with Resume or End — a second controller (the
    Watch) must not be able to wipe a workout mid-set (§6.6).
    """
    from app.services.workout_command_service import WorkoutConflict
    try:
        result = await workout_session_service.start_workout(
            user_id=user_id,
            template_id=request.template_id,
            db=db
        )
        return {"session": result}
    except WorkoutConflict as c:
        raise HTTPException(status_code=409, detail={
            "code": c.code, "message": c.message, "projection": c.projection,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start workout session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workout-session/active")
async def get_active_workout(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get the user's current active workout session.

    Returns null if no active session exists.
    Used by iOS app to restore workout state on app launch.
    """
    try:
        session = await workout_session_service.get_active_session(user_id, db)
        return {"session": session}
    except Exception as e:
        logger.error(f"Failed to get active workout session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workout-session/log-set")
async def log_workout_set(
    request: LogSetRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Log a set during an active workout session.

    - Automatically determines current exercise from session state
    - Updates session progress (current_set_index, total_volume, etc.)
    - Auto-advances to next exercise when all sets complete
    - Returns coaching feedback and next set info

    Supports flexible input:
    - Explicit: weight=185, reps=8, rpe=8
    - Feeling-based: rpe_feeling="light" (Sara suggests weight increase)
    - Minimal: Just "done" - uses expected values from snapshot
    """
    try:
        result = await workout_session_service.log_set(
            user_id=user_id,
            weight=request.weight,
            reps=request.reps,
            rpe=request.rpe,
            rpe_feeling=request.rpe_feeling,
            notes=request.notes,
            db=db
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to log workout set: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workout-session/skip")
async def skip_current_exercise(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Skip the current exercise and move to the next one.

    Used when user wants to skip an exercise (equipment busy, injury, etc.)
    """
    try:
        result = await workout_session_service.skip_exercise(user_id, db)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to skip exercise: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SelectExerciseRequest(BaseModel):
    """Request body for jumping to a specific exercise during active workout"""
    exercise_index: int


@router.post("/workout-session/select-exercise")
async def select_workout_exercise(
    request: SelectExerciseRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Jump the active workout to a specific exercise by index.

    Lets the user do exercises in any order (e.g. a machine is taken, move on and
    come back). Set progress for the chosen exercise resumes from what's logged.
    """
    try:
        result = await workout_session_service.select_exercise(
            user_id=user_id,
            exercise_index=request.exercise_index,
            db=db,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to select exercise: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SetVariantRequest(BaseModel):
    """Request body for recording the machine/variation used for an exercise"""
    exercise_index: int
    variant: Optional[str] = None


@router.post("/workout-session/set-variant")
async def set_workout_variant(
    request: SetVariantRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Record the actual machine/variation used for an exercise during a workout.

    e.g. a "Squat" slot performed on the hack-squat machine — logs and weight
    suggestions are then scoped to "Hack Squat" so they don't corrupt the barbell
    squat's history. Pass an empty/blank variant to revert to the base lift.
    """
    try:
        result = await workout_session_service.set_exercise_variant(
            user_id=user_id,
            exercise_index=request.exercise_index,
            variant=request.variant,
            db=db,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set exercise variant: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workout-session/rest-timer")
async def manage_rest_timer(
    request: RestTimerRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Start or stop the rest timer for active workout.

    Actions:
    - "start": Start timer with specified duration (default 120s for compounds)
    - "stop": Cancel the rest timer
    """
    try:
        if request.action == "start":
            result = await workout_session_service.start_rest_timer(
                user_id=user_id,
                duration_seconds=request.duration or 120,
                db=db
            )
        elif request.action == "stop":
            # Routed through the command service too, so stopping rest on the
            # phone bumps the session version and the Watch sees it (§4.4).
            result = await workout_session_service.stop_rest_timer(user_id, db)
        else:
            raise HTTPException(status_code=400, detail="Invalid action. Use 'start' or 'stop'")

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to manage rest timer: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workout-session/rest-timer")
async def get_rest_timer_status(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get current rest timer status.

    Returns remaining seconds and whether timer is active.
    Used by iOS app for countdown display.
    """
    try:
        result = await workout_session_service.get_rest_timer_status(user_id, db)
        return result
    except Exception as e:
        logger.error(f"Failed to get rest timer status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class CompleteWorkoutRequest(BaseModel):
    """Optional body for completing a workout.

    The Watch supplies the HealthKit workout UUID it just finalized so the
    physiological record is bound to this exact session instead of being
    matched by the same-day heuristic (§4.5).
    """
    healthkit_workout_uuid: Optional[str] = None


@router.post("/workout-session/complete")
async def complete_active_workout(
    request: Optional[CompleteWorkoutRequest] = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Complete the active workout session.

    - Sets status to 'completed' and records completion time
    - Returns workout summary (total volume, sets, duration, PRs)
    """
    try:
        result = await workout_session_service.complete_workout(
            user_id, db,
            healthkit_workout_uuid=(request.healthkit_workout_uuid if request else None),
        )

        summary = (result or {}).get("summary") if isinstance(result, dict) else None
        _emit_domain_event_safe(EventType.WORKOUT_COMPLETED, user_id, {
            "type": "workout",
            "exercises": (summary or {}).get("exercises_completed") if isinstance(summary, dict) else None,
        })

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to complete workout session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workout-session/abandon")
async def abandon_active_workout(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Abandon the active workout session.

    Used when user wants to quit workout early without completing.
    Sets status to 'abandoned'.
    """
    try:
        result = await workout_session_service.abandon_workout(user_id, db)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to abandon workout session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workout-session/context")
async def get_workout_context(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get the workout context string for Sara's system prompt.

    Returns formatted context about current workout state.
    Used internally by chat_stream for context injection.
    """
    try:
        context = await workout_session_service.get_workout_context(user_id, db)
        return {"context": context}
    except Exception as e:
        logger.error(f"Failed to get workout context: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════════
# Plan Import — upload a plan document, parse it with the in-house LLM,
# preview, then apply (creates + activates a new program). See
# app/services/plan_importer.py.
# ════════════════════════════════════════════════════════════════════════

def _extract_uploaded_text(filename: str, content_type: str, raw: bytes) -> str:
    """Best-effort text extraction for md/txt/pdf/docx uploads."""
    name = (filename or "").lower()
    ctype = (content_type or "").lower()
    if name.endswith((".md", ".markdown", ".txt", ".text")) or ctype.startswith("text/"):
        for enc in ("utf-8", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="ignore")
    if name.endswith(".pdf") or ctype == "application/pdf":
        try:
            from pypdf import PdfReader  # maintained successor to PyPDF2
        except ImportError:
            from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:200])
    if name.endswith((".docx", ".doc")) or "word" in ctype:
        try:
            import docx  # python-docx
            document = docx.Document(io.BytesIO(raw))
            return "\n".join(p.text for p in document.paragraphs)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Could not read this Word file. Export to PDF or Markdown, or paste the text instead.",
            )
    # Unknown type — try utf-8 as a last resort
    return raw.decode("utf-8", errors="ignore")


class ApplyPlanRequest(BaseModel):
    plan: Dict[str, Any]
    source_text: Optional[str] = ""
    start_date: Optional[str] = None  # YYYY-MM-DD; defaults to next Monday


@router.post("/import-plan/parse")
async def import_plan_parse(
    file: Optional[UploadFile] = File(None),
    text_input: Optional[str] = Form(None),
    user_id: str = Depends(get_current_user_id),
):
    """Parse an uploaded document (or pasted text) into a structured plan. Read-only."""
    from app.services.plan_importer import parse_plan_document, validate_parsed

    source_text = ""
    if file is not None:
        raw = await file.read()
        source_text = _extract_uploaded_text(file.filename, file.content_type, raw)
    elif text_input:
        source_text = text_input

    if not source_text or not source_text.strip():
        raise HTTPException(status_code=400, detail="No document content found. Upload a file or paste the plan text.")

    try:
        parsed = await parse_plan_document(source_text)
    except Exception as e:
        logger.error(f"Plan parse failed: {e}")
        raise HTTPException(status_code=502, detail=f"Could not parse the plan: {e}")

    return {"parsed": parsed, "source_text": source_text, "warnings": validate_parsed(parsed)}


@router.post("/import-plan/apply")
async def import_plan_apply(
    req: ApplyPlanRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Apply a (previewed) parsed plan: create + activate a new program."""
    from app.services.plan_importer import apply_imported_plan

    try:
        summary = apply_imported_plan(
            db, user_id, req.plan, source_text=req.source_text or "", start_date=req.start_date
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Plan apply failed: {e}")
        raise HTTPException(status_code=500, detail=f"Could not apply the plan: {e}")

    return {"success": True, **summary}


@router.get("/nutrition-guide")
async def get_nutrition_guide(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Structured nutrition guide stored on the active program (drives the Nutrition tab)."""
    row = db.execute(text(
        "SELECT nutrition_guide FROM fitness_program "
        "WHERE user_id=:uid AND is_active=true ORDER BY updated_at DESC LIMIT 1"
    ), {"uid": user_id}).fetchone()
    if not row or not row[0]:
        return {"guide": None}
    try:
        return {"guide": json.loads(row[0])}
    except (json.JSONDecodeError, TypeError):
        return {"guide": None}
