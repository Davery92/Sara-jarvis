"""Recipe management routes (knowledge-garden side).

Shares the `recipe` table with routes/fitness.py — those endpoints handle
nutrition-driven flows; these handle chat/UI-driven flows with embeddings,
tags, starred, and last-made tracking.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Text, cast, func, or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.recipe import Recipe
from app.models.user import User
from app.schemas.recipes import RecipeCreate, RecipeResponse, RecipeUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recipes", tags=["Recipes"])


def _norm_tags(tags: Optional[List[str]]) -> List[str]:
    if not tags:
        return []
    out, seen = [], set()
    for raw in tags:
        if raw is None:
            continue
        t = str(raw).strip().lower()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t[:48])
        if len(out) >= 20:
            break
    return out


def _serialize_ingredients(raw) -> List[dict]:
    if raw is None:
        return []
    if isinstance(raw, str):
        import json as _json
        try:
            raw = _json.loads(raw)
        except Exception:
            return []
    if isinstance(raw, list):
        return [dict(item) if isinstance(item, dict) else {"name": str(item)} for item in raw]
    return []


def serialize_recipe(r: Recipe) -> RecipeResponse:
    return RecipeResponse(
        id=r.id,
        name=r.name,
        description=r.description or "",
        category=r.category,
        ingredients=_serialize_ingredients(r.ingredients),
        instructions=r.instructions or "",
        prep_time_minutes=r.prep_time_minutes,
        cook_time_minutes=r.cook_time_minutes,
        servings=r.servings or 1,
        meal_type=r.meal_type,
        cuisine=r.cuisine,
        tags=list(r.tags or []),
        source_url=r.source_url,
        source_name=r.source_name,
        recipe_notes=r.recipe_notes or "",
        starred=bool(r.starred),
        rating=r.rating,
        calories=float(r.calories) if r.calories is not None else None,
        protein=float(r.protein) if r.protein is not None else None,
        carbs=float(r.carbs) if r.carbs is not None else None,
        fats=float(r.fats) if r.fats is not None else None,
        last_made_at=r.last_made_at.isoformat() if r.last_made_at else None,
        times_made=r.times_made or 0,
        created_at=r.created_at.isoformat() if r.created_at else "",
        updated_at=r.updated_at.isoformat() if r.updated_at else "",
    )


def _embed_text_for(r: Recipe) -> str:
    ingredients = _serialize_ingredients(r.ingredients)
    ing_str = "; ".join(
        f"{i.get('quantity','')} {i.get('unit','')} {i.get('name','')}".strip()
        for i in ingredients
    )
    parts = [r.name or ""]
    if r.description:
        parts.append(r.description)
    if ing_str:
        parts.append("Ingredients: " + ing_str)
    if r.instructions:
        parts.append("Instructions: " + r.instructions)
    if r.tags:
        parts.append("Tags: " + ", ".join(r.tags))
    return "\n".join(p for p in parts if p)


@router.get("", response_model=List[RecipeResponse])
async def list_recipes(
    meal_type: Optional[str] = None,
    category: Optional[str] = None,
    cuisine: Optional[str] = None,
    starred: Optional[bool] = None,
    tag: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Recipe).filter(Recipe.user_id == current_user.id)
    if meal_type:
        q = q.filter(Recipe.meal_type == meal_type)
    if category:
        q = q.filter(Recipe.category == category)
    if cuisine:
        q = q.filter(Recipe.cuisine == cuisine)
    if starred is not None:
        q = q.filter(Recipe.starred == starred)
    if tag:
        q = q.filter(cast(Recipe.tags, Text).ilike(f"%{tag.lower()}%"))
    rows = q.order_by(Recipe.updated_at.desc()).limit(limit).all()
    return [serialize_recipe(r) for r in rows]


@router.post("", response_model=RecipeResponse)
async def create_recipe(
    payload: RecipeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not payload.name or not payload.name.strip():
        raise HTTPException(status_code=400, detail="name is required")

    ingredients_list = [i.model_dump() for i in (payload.ingredients or [])]

    recipe = Recipe(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        name=payload.name.strip(),
        description=payload.description or "",
        category=payload.category,
        ingredients=ingredients_list,
        instructions=payload.instructions or "",
        prep_time_minutes=payload.prep_time_minutes,
        cook_time_minutes=payload.cook_time_minutes,
        servings=payload.servings or 1,
        meal_type=payload.meal_type,
        cuisine=payload.cuisine,
        tags=_norm_tags(payload.tags),
        source_url=payload.source_url,
        source_name=payload.source_name,
        recipe_notes=payload.recipe_notes or "",
        starred=bool(payload.starred),
        rating=payload.rating,
        calories=payload.calories,
        protein=payload.protein,
        carbs=payload.carbs,
        fats=payload.fats,
    )

    try:
        from app.services.embeddings import get_embedding
        recipe.embedding = await get_embedding(_embed_text_for(recipe))
    except Exception as e:
        logger.warning(f"Recipe embedding failed (continuing without): {e}")

    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return serialize_recipe(recipe)


@router.get("/search", response_model=List[RecipeResponse])
async def search_recipes(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    like = f"%{q.lower()}%"
    rows = (
        db.query(Recipe)
        .filter(Recipe.user_id == current_user.id)
        .filter(or_(
            func.lower(Recipe.name).like(like),
            func.lower(Recipe.description).like(like),
            func.lower(cast(Recipe.ingredients, Text)).like(like),
            func.lower(cast(Recipe.tags, Text)).like(like),
        ))
        .order_by(Recipe.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [serialize_recipe(r) for r in rows]


@router.get("/{recipe_id}", response_model=RecipeResponse)
async def get_recipe(
    recipe_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    r = db.query(Recipe).filter(
        Recipe.id == recipe_id, Recipe.user_id == current_user.id
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return serialize_recipe(r)


@router.patch("/{recipe_id}", response_model=RecipeResponse)
async def update_recipe(
    recipe_id: str,
    payload: RecipeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    r = db.query(Recipe).filter(
        Recipe.id == recipe_id, Recipe.user_id == current_user.id
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="Recipe not found")

    data = payload.model_dump(exclude_unset=True)
    if "tags" in data:
        data["tags"] = _norm_tags(data["tags"])
    if "ingredients" in data and data["ingredients"] is not None:
        data["ingredients"] = [
            i if isinstance(i, dict) else i.model_dump() for i in data["ingredients"]
        ]

    for k, v in data.items():
        setattr(r, k, v)

    if any(k in data for k in ("name", "description", "ingredients", "instructions", "tags")):
        try:
            from app.services.embeddings import get_embedding
            r.embedding = await get_embedding(_embed_text_for(r))
        except Exception as e:
            logger.warning(f"Recipe re-embedding failed: {e}")

    db.commit()
    db.refresh(r)
    return serialize_recipe(r)


@router.delete("/{recipe_id}")
async def delete_recipe(
    recipe_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    r = db.query(Recipe).filter(
        Recipe.id == recipe_id, Recipe.user_id == current_user.id
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="Recipe not found")
    db.delete(r)
    db.commit()
    return {"deleted": recipe_id}


@router.post("/{recipe_id}/log-made", response_model=RecipeResponse)
async def log_recipe_made(
    recipe_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    r = db.query(Recipe).filter(
        Recipe.id == recipe_id, Recipe.user_id == current_user.id
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="Recipe not found")
    r.last_made_at = datetime.now(timezone.utc)
    r.times_made = (r.times_made or 0) + 1
    db.commit()
    db.refresh(r)
    return serialize_recipe(r)
