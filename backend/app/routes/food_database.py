"""
Food Database API Routes
Manages individual foods with nutritional information
Uses FatSecret API for food search (replacing USDA)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.session import get_db
import uuid
import json
import logging
import os

logger = logging.getLogger(__name__)
router = APIRouter()


def get_current_user_id() -> str:
    """Get current user ID (simplified for now)"""
    return os.getenv("SOLO_USER_ID", "default-user")


# Response models
class FoodServing(BaseModel):
    """A single serving option for a food item"""
    serving_id: str
    serving_description: str
    metric_serving_amount: Optional[float] = None
    metric_serving_unit: Optional[str] = None
    calories: float
    protein: float
    carbs: float
    fat: float
    fiber: Optional[float] = None
    sugar: Optional[float] = None
    sodium: Optional[float] = None


class FoodResponse(BaseModel):
    """Basic food response for search results"""
    id: str
    name: str
    brand: Optional[str] = None
    serving_size: float
    serving_unit: str
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None
    fiber: Optional[float] = None
    sugar: Optional[float] = None
    sodium: Optional[float] = None
    is_custom: bool
    source: str  # 'fatsecret', 'user', 'recipe'


class FoodDetailResponse(BaseModel):
    """Detailed food response with all serving options"""
    id: str
    fatsecret_id: Optional[str] = None
    name: str
    brand: Optional[str] = None
    food_type: Optional[str] = None
    servings: List[FoodServing]
    is_custom: bool
    source: str


class FoodCreate(BaseModel):
    """Request model for creating custom foods"""
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


# ============================================================================
# FATSECRET FOOD SEARCH
# ============================================================================

@router.get("/foods/search")
async def search_foods(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, le=50, description="Max results"),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Search for foods by name.
    Searches custom foods first, then FatSecret database.
    Powered by FatSecret.
    """
    try:
        foods = []

        # 1. Search user's custom foods first
        custom_query = text("""
            SELECT * FROM food_database
            WHERE user_id = :user_id
            AND LOWER(name) LIKE LOWER(:search)
            ORDER BY updated_at DESC
            LIMIT :limit
        """)

        custom_result = db.execute(custom_query, {
            "user_id": user_id,
            "search": f"%{q}%",
            "limit": limit
        })

        for row in custom_result.fetchall():
            foods.append({
                "id": str(row.id),
                "name": row.name,
                "brand": row.brand,
                "serving_size": row.serving_size,
                "serving_unit": row.serving_unit,
                "calories": row.calories,
                "protein": row.protein,
                "carbs": row.carbs,
                "fats": row.fats,
                "fiber": row.fiber,
                "sugar": row.sugar,
                "sodium": row.sodium,
                "is_custom": True,
                "source": "user"
            })

        # 2. Search FatSecret if we need more results
        if len(foods) < limit:
            fatsecret_foods = await search_fatsecret_foods(q, limit - len(foods), db)
            foods.extend(fatsecret_foods)

        return foods

    except Exception as e:
        logger.error(f"Failed to search foods: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def search_fatsecret_foods(query: str, limit: int, db: Session) -> List[Dict[str, Any]]:
    """Search FatSecret database for foods"""
    try:
        from app.services.fatsecret_service import get_fatsecret_service

        service = get_fatsecret_service()
        results, total = await service.search_foods(query, page=0, max_results=limit)

        foods = []
        for f in results:
            # Cache the food in our database for future lookups
            await cache_fatsecret_food(db, f)

            foods.append({
                "id": f"fs-{f['food_id']}",  # Prefix with fs- to identify FatSecret foods
                "fatsecret_id": f["food_id"],
                "name": f["food_name"],
                "brand": f.get("brand_name"),
                "food_type": f.get("food_type"),
                "serving_size": 1,
                "serving_unit": f.get("serving_description") or "serving",
                "calories": f.get("calories"),
                "protein": f.get("protein"),
                "carbs": f.get("carbs"),
                "fats": f.get("fat"),
                "is_custom": False,
                "source": "fatsecret"
            })

        return foods

    except ValueError as e:
        # FatSecret not configured - log warning and return empty
        logger.warning(f"FatSecret not configured: {e}")
        return []
    except Exception as e:
        logger.error(f"FatSecret search error: {e}", exc_info=True)
        return []


async def cache_fatsecret_food(db: Session, food_data: Dict[str, Any]) -> None:
    """Cache a FatSecret food item in our database"""
    try:
        food_id = food_data.get("food_id")
        if not food_id:
            return

        # Check if already cached
        check_query = text("SELECT id FROM fatsecret_food_cache WHERE fatsecret_id = :fatsecret_id")
        existing = db.execute(check_query, {"fatsecret_id": str(food_id)}).fetchone()

        if existing:
            return  # Already cached

        # Insert into cache (basic info from search results)
        insert_query = text("""
            INSERT INTO fatsecret_food_cache (id, fatsecret_id, name, brand, food_type, cached_at)
            VALUES (:id, :fatsecret_id, :name, :brand, :food_type, NOW())
            ON CONFLICT (fatsecret_id) DO NOTHING
        """)

        db.execute(insert_query, {
            "id": str(uuid.uuid4()),
            "fatsecret_id": str(food_id),
            "name": food_data.get("food_name", ""),
            "brand": food_data.get("brand_name"),
            "food_type": food_data.get("food_type")
        })
        db.commit()

    except Exception as e:
        logger.warning(f"Failed to cache FatSecret food: {e}")
        db.rollback()


# ============================================================================
# BARCODE LOOKUP (Premium Feature)
# ============================================================================

@router.get("/foods/barcode/{barcode}")
async def lookup_barcode(
    barcode: str,
    region: str = Query("US", description="Region code (US, FR, etc.)"),
    db: Session = Depends(get_db)
) -> FoodDetailResponse:
    """
    Look up a food by barcode (UPC-A, EAN-13, EAN-8).
    Uses FatSecret Premium barcode database.
    """
    try:
        from app.services.fatsecret_service import get_fatsecret_service

        service = get_fatsecret_service()
        food = await service.get_food_by_barcode(barcode, region)

        if not food:
            raise HTTPException(
                status_code=404,
                detail=f"No food found for barcode: {barcode}"
            )

        # Cache the food for future lookups
        await cache_fatsecret_food(db, {
            "food_id": food.food_id,
            "food_name": food.food_name,
            "brand_name": food.brand_name,
            "food_type": food.food_type
        })

        return FoodDetailResponse(
            id=f"fs-{food.food_id}",
            fatsecret_id=food.food_id,
            name=food.food_name,
            brand=food.brand_name,
            food_type=food.food_type,
            servings=[
                FoodServing(
                    serving_id=s.serving_id,
                    serving_description=s.serving_description,
                    metric_serving_amount=s.metric_serving_amount,
                    metric_serving_unit=s.metric_serving_unit,
                    calories=s.calories,
                    protein=s.protein,
                    carbs=s.carbohydrate,
                    fat=s.fat,
                    fiber=s.fiber,
                    sugar=s.sugar,
                    sodium=s.sodium
                )
                for s in food.servings
            ],
            is_custom=False,
            source="fatsecret"
        )

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"FatSecret not configured: {e}")
        raise HTTPException(status_code=503, detail="FatSecret API not configured")
    except Exception as e:
        logger.error(f"Barcode lookup error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# GET FOOD DETAILS (with serving sizes)
# ============================================================================

@router.get("/foods/{food_id}/details")
async def get_food_details(
    food_id: str,
    db: Session = Depends(get_db)
) -> FoodDetailResponse:
    """
    Get detailed food information including all serving sizes.
    For FatSecret foods (id starts with 'fs-'), fetches from FatSecret API.
    For custom foods, returns the stored data.
    """
    try:
        # Check if this is a FatSecret food
        if food_id.startswith("fs-"):
            fatsecret_id = food_id[3:]  # Remove 'fs-' prefix
            return await get_fatsecret_food_details(fatsecret_id, db)

        # Check if this is a recipe (Phase U.6 recipe search results are prefixed "recipe-<uuid>")
        if food_id.startswith("recipe-"):
            recipe_id = food_id[len("recipe-"):]
            return await get_recipe_food_details(recipe_id, db)

        # Otherwise, look up custom food. food_database.id is a uuid column, so a
        # non-UUID id (e.g. a synthetic "quick-..." quick-add entry) is simply not
        # a stored food — return 404 rather than letting the cast 500.
        import uuid as _uuid
        try:
            _uuid.UUID(str(food_id))
        except (ValueError, AttributeError, TypeError):
            raise HTTPException(status_code=404, detail="Food not found")

        query = text("SELECT * FROM food_database WHERE id = :id")
        result = db.execute(query, {"id": food_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Food not found")

        return FoodDetailResponse(
            id=str(result.id),
            name=result.name,
            brand=result.brand,
            food_type="Custom",
            servings=[
                FoodServing(
                    serving_id="default",
                    serving_description=f"{result.serving_size} {result.serving_unit}",
                    metric_serving_amount=result.serving_size,
                    metric_serving_unit=result.serving_unit,
                    calories=result.calories or 0,
                    protein=result.protein or 0,
                    carbs=result.carbs or 0,
                    fat=result.fats or 0,
                    fiber=result.fiber,
                    sugar=result.sugar,
                    sodium=result.sodium
                )
            ],
            is_custom=True,
            source="user"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get food details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def get_recipe_food_details(recipe_id: str, db: Session) -> FoodDetailResponse:
    """Get detailed food info for a recipe, expressed as macros per serving."""
    query = text("""
        SELECT id, name, servings, calories, protein, carbs, fats
        FROM recipe
        WHERE id = :recipe_id
    """)
    result = db.execute(query, {"recipe_id": recipe_id}).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Recipe not found")

    servings = result.servings or 1

    def per_serving(total):
        return float(total) / servings if total is not None else 0.0

    return FoodDetailResponse(
        id=f"recipe-{result.id}",
        name=result.name,
        brand=None,
        food_type="Recipe",
        servings=[
            FoodServing(
                serving_id="1",
                serving_description="1 serving",
                metric_serving_amount=1,
                metric_serving_unit="serving",
                calories=per_serving(result.calories),
                protein=per_serving(result.protein),
                carbs=per_serving(result.carbs),
                fat=per_serving(result.fats),
            )
        ],
        is_custom=True,
        source="recipe"
    )


async def get_fatsecret_food_details(fatsecret_id: str, db: Session) -> FoodDetailResponse:
    """Get detailed food info from FatSecret, caching servings"""
    try:
        # Check cache first
        cache_query = text("""
            SELECT * FROM fatsecret_food_cache
            WHERE fatsecret_id = :fatsecret_id
            AND servings_json IS NOT NULL
        """)
        cached = db.execute(cache_query, {"fatsecret_id": fatsecret_id}).fetchone()

        if cached and cached.servings_json:
            # Return from cache
            servings_data = cached.servings_json if isinstance(cached.servings_json, list) else json.loads(cached.servings_json)
            return FoodDetailResponse(
                id=f"fs-{fatsecret_id}",
                fatsecret_id=fatsecret_id,
                name=cached.name,
                brand=cached.brand,
                food_type=cached.food_type,
                servings=[
                    FoodServing(
                        serving_id=s.get("serving_id", ""),
                        serving_description=s.get("serving_description", ""),
                        metric_serving_amount=s.get("metric_serving_amount"),
                        metric_serving_unit=s.get("metric_serving_unit"),
                        calories=s.get("calories", 0),
                        protein=s.get("protein", 0),
                        carbs=s.get("carbohydrate", 0),
                        fat=s.get("fat", 0),
                        fiber=s.get("fiber"),
                        sugar=s.get("sugar"),
                        sodium=s.get("sodium")
                    )
                    for s in servings_data
                ],
                is_custom=False,
                source="fatsecret"
            )

        # Fetch from FatSecret API
        from app.services.fatsecret_service import get_fatsecret_service

        service = get_fatsecret_service()
        food = await service.get_food(fatsecret_id)

        if not food:
            raise HTTPException(status_code=404, detail="Food not found in FatSecret")

        # Cache the detailed info
        servings_json = [
            {
                "serving_id": s.serving_id,
                "serving_description": s.serving_description,
                "metric_serving_amount": s.metric_serving_amount,
                "metric_serving_unit": s.metric_serving_unit,
                "calories": s.calories,
                "protein": s.protein,
                "carbohydrate": s.carbohydrate,
                "fat": s.fat,
                "fiber": s.fiber,
                "sugar": s.sugar,
                "sodium": s.sodium
            }
            for s in food.servings
        ]

        update_query = text("""
            UPDATE fatsecret_food_cache
            SET servings_json = CAST(:servings_json AS jsonb), updated_at = NOW()
            WHERE fatsecret_id = :fatsecret_id
        """)
        db.execute(update_query, {
            "fatsecret_id": fatsecret_id,
            "servings_json": json.dumps(servings_json)
        })
        db.commit()

        return FoodDetailResponse(
            id=f"fs-{fatsecret_id}",
            fatsecret_id=fatsecret_id,
            name=food.food_name,
            brand=food.brand_name,
            food_type=food.food_type,
            servings=[
                FoodServing(
                    serving_id=s.serving_id,
                    serving_description=s.serving_description,
                    metric_serving_amount=s.metric_serving_amount,
                    metric_serving_unit=s.metric_serving_unit,
                    calories=s.calories,
                    protein=s.protein,
                    carbs=s.carbohydrate,
                    fat=s.fat,
                    fiber=s.fiber,
                    sugar=s.sugar,
                    sodium=s.sodium
                )
                for s in food.servings
            ],
            is_custom=False,
            source="fatsecret"
        )

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"FatSecret not configured: {e}")
        raise HTTPException(status_code=503, detail="FatSecret API not configured")
    except Exception as e:
        logger.error(f"Failed to get FatSecret food details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CUSTOM FOODS (User Created)
# ============================================================================

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


@router.get("/foods/recent")
async def get_recent_foods(
    limit: int = Query(20, le=50),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """Get recently used/created custom foods"""
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
            foods.append({
                "id": str(row.id),
                "name": row.name,
                "brand": row.brand,
                "serving_size": row.serving_size,
                "serving_unit": row.serving_unit,
                "calories": row.calories,
                "protein": row.protein,
                "carbs": row.carbs,
                "fats": row.fats,
                "fiber": row.fiber,
                "sugar": row.sugar,
                "sodium": row.sodium,
                "is_custom": row.is_custom,
                "source": row.source
            })

        return foods

    except Exception as e:
        logger.error(f"Failed to get recent foods: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ATTRIBUTION (Required by FatSecret Terms of Service)
# ============================================================================

@router.get("/foods/attribution")
async def get_attribution():
    """Get FatSecret attribution info (required by ToS)"""
    return {
        "text": "Powered by FatSecret",
        "url": "https://www.fatsecret.com",
        "logo_url": "https://platform.fatsecret.com/api/static/images/powered_by_fatsecret.png"
    }
