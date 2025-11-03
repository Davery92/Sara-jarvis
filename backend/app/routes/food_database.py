"""
Food Database API Routes
Manages individual foods with nutritional information
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import get_db
import uuid
import logging
import os

# Define get_current_user_id locally to avoid circular import
def get_current_user_id() -> str:
    """Get current user ID (simplified for now)"""
    # In production, this would come from JWT token
    return os.getenv("SOLO_USER_ID", "default-user")

logger = logging.getLogger(__name__)
router = APIRouter()

# Simple in-memory cache for USDA searches (60 second TTL)
_usda_search_cache = {}
_cache_timestamps = {}


class FoodCreate(BaseModel):
    name: str
    brand: Optional[str] = None
    serving_size: float = 1
    serving_unit: str = "serving"
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None
    fiber: Optional[float] = None
    sugar: Optional[float] = None
    sodium: Optional[float] = None


class FoodResponse(BaseModel):
    id: str
    name: str
    brand: Optional[str]
    serving_size: float
    serving_unit: str
    calories: Optional[float]
    protein: Optional[float]
    carbs: Optional[float]
    fats: Optional[float]
    fiber: Optional[float]
    sugar: Optional[float]
    sodium: Optional[float]
    is_custom: bool
    source: str


@router.post("/foods", response_model=FoodResponse)
async def create_food(
    food: FoodCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Create a custom food entry"""
    try:
        food_id = str(uuid.uuid4())

        query = text("""
            INSERT INTO food_database (
                id, user_id, name, brand, serving_size, serving_unit,
                calories, protein, carbs, fats, fiber, sugar, sodium,
                is_custom, source
            ) VALUES (
                :id, :user_id, :name, :brand, :serving_size, :serving_unit,
                :calories, :protein, :carbs, :fats, :fiber, :sugar, :sodium,
                true, 'user'
            )
            RETURNING *
        """)

        result = db.execute(query, {
            "id": food_id,
            "user_id": user_id,
            **food.dict()
        })

        db.commit()
        row = result.fetchone()

        return FoodResponse(
            id=str(row.id),
            name=row.name,
            brand=row.brand,
            serving_size=row.serving_size,
            serving_unit=row.serving_unit,
            calories=row.calories,
            protein=row.protein,
            carbs=row.carbs,
            fats=row.fats,
            fiber=row.fiber,
            sugar=row.sugar,
            sodium=row.sodium,
            is_custom=row.is_custom,
            source=row.source
        )

    except Exception as e:
        logger.error(f"Failed to create food: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/foods/search", response_model=List[FoodResponse])
async def search_foods(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=100),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Search for foods by name - searches both custom foods and USDA database"""
    try:
        # First, search user's custom foods
        custom_query = text("""
            SELECT * FROM food_database
            WHERE user_id = :user_id
            AND LOWER(name) LIKE LOWER(:search)
            ORDER BY name
            LIMIT :limit
        """)

        custom_result = db.execute(custom_query, {
            "user_id": user_id,
            "search": f"%{q}%",
            "limit": limit
        })

        foods = []
        for row in custom_result.fetchall():
            foods.append(FoodResponse(
                id=str(row.id),
                name=row.name,
                brand=row.brand,
                serving_size=row.serving_size,
                serving_unit=row.serving_unit,
                calories=row.calories,
                protein=row.protein,
                carbs=row.carbs,
                fats=row.fats,
                fiber=row.fiber,
                sugar=row.sugar,
                sodium=row.sodium,
                is_custom=row.is_custom,
                source=row.source
            ))

        # If we have room for more results, search USDA database
        if len(foods) < limit:
            usda_foods = await search_usda_foods(q, limit - len(foods))
            foods.extend(usda_foods)

        return foods

    except Exception as e:
        logger.error(f"Failed to search foods: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def search_usda_foods(query: str, limit: int) -> List[FoodResponse]:
    """Search USDA FoodData Central database with caching"""
    import httpx
    import time

    # Check cache first (60 second TTL)
    cache_key = f"{query.lower()}:{limit}"
    now = time.time()

    if cache_key in _usda_search_cache:
        cached_time = _cache_timestamps.get(cache_key, 0)
        if now - cached_time < 60:  # Cache for 60 seconds
            logger.debug(f"📦 USDA cache hit for '{query}'")
            return _usda_search_cache[cache_key]

    # Get API key from environment or use DEMO_KEY
    # To get your own free key (1000 requests/hour): https://fdc.nal.usda.gov/api-key-signup.html
    usda_api_key = os.getenv("USDA_API_KEY", "DEMO_KEY")
    usda_api_url = "https://api.nal.usda.gov/fdc/v1/foods/search"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                usda_api_url,
                params={
                    "query": query,
                    "dataType": ["SR Legacy", "Foundation"],  # Standard Reference and Foundation foods
                    "pageSize": limit,
                    "api_key": usda_api_key
                }
            )

            if response.status_code == 429:
                logger.warning(f"⚠️ USDA API rate limit exceeded. Get your free API key at: https://fdc.nal.usda.gov/api-key-signup.html")
                return []

            if response.status_code != 200:
                logger.warning(f"USDA API returned {response.status_code}")
                return []

            data = response.json()
            foods = []

            for item in data.get("foods", [])[:limit]:
                # Extract nutrition data - build dict with unit info for energy
                nutrients = {}
                calories = 0

                for n in item.get("foodNutrients", []):
                    nutrient_name = n.get("nutrientName", "")
                    nutrient_value = n.get("value", 0)
                    unit_name = n.get("unitName", "")

                    # Special handling for Energy to get KCAL not kJ
                    # Check for various energy field names in USDA data
                    if unit_name == "KCAL" and ("Energy" in nutrient_name or "energy" in nutrient_name):
                        # Prefer "Energy" exact match, then Atwater General, then any energy field
                        if nutrient_name == "Energy" or calories == 0:
                            calories = nutrient_value
                    else:
                        nutrients[nutrient_name] = nutrient_value

                # Map USDA nutrients to our schema (calories already extracted above)
                protein = nutrients.get("Protein", 0)
                carbs = nutrients.get("Carbohydrate, by difference", 0)
                fats = nutrients.get("Total lipid (fat)", 0)
                fiber = nutrients.get("Fiber, total dietary", 0)
                sugar = nutrients.get("Sugars, total including NLEA", 0)
                sodium = nutrients.get("Sodium, Na", 0) / 1000  # Convert mg to g

                foods.append(FoodResponse(
                    id=f"usda-{item['fdcId']}",  # Prefix with usda- to distinguish
                    name=item["description"],
                    brand=item.get("brandOwner"),
                    serving_size=100,  # USDA data is per 100g
                    serving_unit="g",
                    calories=calories,
                    protein=protein,
                    carbs=carbs,
                    fats=fats,
                    fiber=fiber,
                    sugar=sugar,
                    sodium=sodium,
                    is_custom=False,
                    source="usda"
                ))

            # Cache the results
            _usda_search_cache[cache_key] = foods
            _cache_timestamps[cache_key] = now
            logger.debug(f"💾 USDA results cached for '{query}'")

            return foods

    except httpx.TimeoutException:
        logger.warning("USDA API timeout")
        return []
    except Exception as e:
        logger.error(f"USDA API error: {e}")
        return []


@router.get("/foods/recent", response_model=List[FoodResponse])
async def get_recent_foods(
    limit: int = Query(20, le=50),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get recently used foods"""
    try:
        query = text("""
            SELECT * FROM food_database
            WHERE user_id = :user_id
            ORDER BY updated_at DESC
            LIMIT :limit
        """)

        result = db.execute(query, {"user_id": user_id, "limit": limit})

        foods = []
        for row in result.fetchall():
            foods.append(FoodResponse(
                id=str(row.id),
                name=row.name,
                brand=row.brand,
                serving_size=row.serving_size,
                serving_unit=row.serving_unit,
                calories=row.calories,
                protein=row.protein,
                carbs=row.carbs,
                fats=row.fats,
                fiber=row.fiber,
                sugar=row.sugar,
                sodium=row.sodium,
                is_custom=row.is_custom,
                source=row.source
            ))

        return foods

    except Exception as e:
        logger.error(f"Failed to get recent foods: {e}")
        raise HTTPException(status_code=500, detail=str(e))
