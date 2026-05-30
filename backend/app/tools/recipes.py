"""Recipe tools — first-class recipe storage so Sara doesn't fall back to notes.

Shares the `recipe` table with the fitness recipe routes. Schema fields:
name, ingredients (structured list), instructions (text), category, meal_type,
cuisine, tags, plus tracking (starred, last_made_at, times_made).
"""
from typing import Any, Dict, List, Optional
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.recipe import Recipe
from app.services.embeddings import get_embedding
from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


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


def _norm_ingredients(items: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """Accept either list[str] ('2 cups flour') or list[{name, quantity, unit, ...}].

    Strings are stored as {"name": "<full string>"}; structured dicts are passed through.
    """
    if not items:
        return []
    out = []
    for raw in items:
        if raw is None:
            continue
        if isinstance(raw, dict):
            name = (raw.get("name") or "").strip()
            if not name:
                continue
            out.append({
                "name": name,
                "quantity": raw.get("quantity"),
                "unit": raw.get("unit"),
                "calories": raw.get("calories"),
                "protein": raw.get("protein"),
                "carbs": raw.get("carbs"),
                "fats": raw.get("fats"),
            })
        else:
            s = str(raw).strip()
            if s:
                out.append({"name": s, "quantity": None, "unit": None})
        if len(out) >= 100:
            break
    return out


def _instructions_from(steps_or_text: Any) -> str:
    """Accept either a single instructions string or a list of step strings."""
    if steps_or_text is None:
        return ""
    if isinstance(steps_or_text, list):
        steps = [str(s).strip() for s in steps_or_text if s and str(s).strip()]
        return "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
    return str(steps_or_text).strip()


def _ingredients_for_embed(items: List[Dict[str, Any]]) -> str:
    parts = []
    for i in items:
        chunk = f"{i.get('quantity') or ''} {i.get('unit') or ''} {i.get('name') or ''}".strip()
        if chunk:
            parts.append(chunk)
    return "; ".join(parts)


def _embed_text(name: str, description: str, ingredients: List[Dict[str, Any]],
                instructions: str, tags: List[str]) -> str:
    parts = [name]
    if description:
        parts.append(description)
    ing = _ingredients_for_embed(ingredients)
    if ing:
        parts.append("Ingredients: " + ing)
    if instructions:
        parts.append("Instructions: " + instructions)
    if tags:
        parts.append("Tags: " + ", ".join(tags))
    return "\n".join(parts)


def _summary(r: Recipe) -> Dict[str, Any]:
    return {
        "recipe_id": r.id,
        "name": r.name,
        "description": (r.description or "")[:200],
        "category": r.category,
        "meal_type": r.meal_type,
        "cuisine": r.cuisine,
        "tags": list(r.tags or []),
        "servings": r.servings,
        "prep_time_minutes": r.prep_time_minutes,
        "cook_time_minutes": r.cook_time_minutes,
        "starred": bool(r.starred),
        "rating": r.rating,
        "times_made": r.times_made or 0,
        "last_made_at": r.last_made_at.isoformat() if r.last_made_at else None,
        "calories_per_serving": float(r.calories) if r.calories is not None else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _full(r: Recipe) -> Dict[str, Any]:
    d = _summary(r)
    d.update({
        "ingredients": list(r.ingredients or []),
        "instructions": r.instructions or "",
        "source_url": r.source_url,
        "source_name": r.source_name,
        "recipe_notes": r.recipe_notes or "",
        "protein": float(r.protein) if r.protein is not None else None,
        "carbs": float(r.carbs) if r.carbs is not None else None,
        "fats": float(r.fats) if r.fats is not None else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    })
    return d


class RecipeCreateTool(BaseTool):
    @property
    def name(self) -> str:
        return "recipes_create"

    @property
    def description(self) -> str:
        return (
            "Save a recipe with ingredients and instructions. "
            "ALWAYS use this — not notes_create — when David asks to save a recipe. "
            "Recipes have structured ingredients, steps, prep/cook time, servings, and macros."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Recipe name"},
                "description": {"type": "string", "description": "Short description / blurb"},
                "ingredients": {
                    "type": "array",
                    "items": {
                        "anyOf": [
                            {"type": "string"},
                            {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "quantity": {"type": "number"},
                                    "unit": {"type": "string"},
                                },
                                "required": ["name"],
                            },
                        ]
                    },
                    "description": "List of ingredients. Either plain strings like '2 cups flour' or structured {name, quantity, unit}.",
                },
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered preparation steps (will be joined into instructions).",
                },
                "instructions": {
                    "type": "string",
                    "description": "Alternative to steps — single instructions block. If both given, steps wins.",
                },
                "servings": {"type": "integer", "description": "Number of servings (default 1)"},
                "prep_time_minutes": {"type": "integer"},
                "cook_time_minutes": {"type": "integer"},
                "category": {"type": "string", "description": "Generic category (e.g. 'baking')"},
                "cuisine": {"type": "string", "description": "e.g. Italian, Thai, Mexican"},
                "meal_type": {
                    "type": "string",
                    "enum": ["breakfast", "lunch", "dinner", "snack", "dessert", "side", "drink"],
                },
                "tags": {"type": "array", "items": {"type": "string"}},
                "source_url": {"type": "string"},
                "source_name": {"type": "string"},
                "recipe_notes": {"type": "string", "description": "David's personal notes / modifications"},
                "calories": {"type": "number", "description": "Calories per serving (optional)"},
                "protein": {"type": "number"},
                "carbs": {"type": "number"},
                "fats": {"type": "number"},
            },
            "required": ["name", "ingredients"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        name = (kwargs.get("name") or "").strip()
        if not name:
            return ToolResult(success=False, message="name is required")

        ingredients = _norm_ingredients(kwargs.get("ingredients"))
        if not ingredients:
            return ToolResult(success=False, message="ingredients are required")

        steps = kwargs.get("steps")
        instructions = _instructions_from(steps) if steps else _instructions_from(kwargs.get("instructions"))

        description = kwargs.get("description") or ""
        tags = _norm_tags(kwargs.get("tags"))

        embedding = None
        try:
            embedding = await get_embedding(_embed_text(name, description, ingredients, instructions, tags))
        except Exception as e:
            logger.warning(f"Recipe embedding failed (continuing): {e}")

        db: Session = next(get_db())
        try:
            r = Recipe(
                id=str(uuid.uuid4()),
                user_id=user_id,
                name=name,
                description=description,
                category=kwargs.get("category"),
                ingredients=ingredients,
                instructions=instructions,
                prep_time_minutes=kwargs.get("prep_time_minutes"),
                cook_time_minutes=kwargs.get("cook_time_minutes"),
                servings=kwargs.get("servings") or 1,
                meal_type=kwargs.get("meal_type"),
                cuisine=kwargs.get("cuisine"),
                tags=tags,
                source_url=kwargs.get("source_url"),
                source_name=kwargs.get("source_name"),
                recipe_notes=kwargs.get("recipe_notes") or "",
                calories=kwargs.get("calories"),
                protein=kwargs.get("protein"),
                carbs=kwargs.get("carbs"),
                fats=kwargs.get("fats"),
                embedding=embedding,
            )
            db.add(r)
            db.commit()
            db.refresh(r)
            return ToolResult(success=True, data=_full(r), message=f"Saved recipe: {r.name}")
        except Exception as e:
            db.rollback()
            logger.exception("recipes_create failed")
            return ToolResult(success=False, message=f"Failed to save recipe: {e}")
        finally:
            db.close()


class RecipeSearchTool(BaseTool):
    @property
    def name(self) -> str:
        return "recipes_search"

    @property
    def description(self) -> str:
        return (
            "Search David's recipes by name, ingredients, tags, or general topic. "
            "Combines text matching with semantic similarity. Returns summaries — call "
            "recipes_get for full ingredients/instructions."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "meal_type": {"type": "string"},
                "tag": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        query = (kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(success=False, message="query is required")
        limit = int(kwargs.get("limit", 10) or 10)
        meal_type = kwargs.get("meal_type")
        tag = (kwargs.get("tag") or "").strip().lower() or None

        db: Session = next(get_db())
        try:
            results: List[Dict[str, Any]] = []
            seen: set = set()

            like = f"%{query.lower()}%"
            text_sql = text("""
                SELECT id FROM recipe
                WHERE user_id = :user_id
                  AND (
                    LOWER(name) LIKE :like
                    OR LOWER(description) LIKE :like
                    OR LOWER(ingredients::text) LIKE :like
                    OR LOWER(tags::text) LIKE :like
                  )
                  AND (CAST(:meal_type AS TEXT) IS NULL OR meal_type = CAST(:meal_type AS TEXT))
                  AND (CAST(:tag AS TEXT) IS NULL OR LOWER(tags::text) LIKE CAST(:tag_like AS TEXT))
                ORDER BY updated_at DESC
                LIMIT :limit
            """)
            rows = db.execute(text_sql, {
                "user_id": user_id,
                "like": like,
                "meal_type": meal_type,
                "tag": tag,
                "tag_like": f"%{tag}%" if tag else None,
                "limit": limit,
            }).fetchall()

            ids = [row.id for row in rows]
            if ids:
                recipes = db.query(Recipe).filter(Recipe.id.in_(ids)).all()
                by_id = {r.id: r for r in recipes}
                for rid in ids:
                    if rid in by_id and rid not in seen:
                        seen.add(rid)
                        results.append(_summary(by_id[rid]))

            if len(results) < limit:
                try:
                    qemb = await get_embedding(query)
                    vec_sql = text("""
                        SELECT id, (1 - (embedding <=> CAST(:qemb AS vector))) AS similarity
                        FROM recipe
                        WHERE user_id = :user_id
                          AND embedding IS NOT NULL
                          AND (CAST(:meal_type AS TEXT) IS NULL OR meal_type = CAST(:meal_type AS TEXT))
                          AND (CAST(:tag AS TEXT) IS NULL OR LOWER(tags::text) LIKE CAST(:tag_like AS TEXT))
                        ORDER BY embedding <=> CAST(:qemb AS vector)
                        LIMIT :limit
                    """)
                    vrows = db.execute(vec_sql, {
                        "qemb": str(qemb),
                        "user_id": user_id,
                        "meal_type": meal_type,
                        "tag": tag,
                        "tag_like": f"%{tag}%" if tag else None,
                        "limit": limit,
                    }).fetchall()
                    vids = [v.id for v in vrows if v.id not in seen]
                    if vids:
                        vrecipes = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(vids)).all()}
                        for v in vrows:
                            if v.id in vrecipes and len(results) < limit:
                                seen.add(v.id)
                                d = _summary(vrecipes[v.id])
                                d["similarity"] = round(float(v.similarity or 0.0), 3)
                                results.append(d)
                except Exception as e:
                    logger.warning(f"recipes_search vector path failed: {e}")

            return ToolResult(
                success=True,
                data={"recipes": results, "query": query, "total_found": len(results)},
                message=f"Found {len(results)} recipe(s) for '{query}'",
                citations=[f"recipe:{r['recipe_id']}" for r in results],
            )
        except Exception as e:
            logger.exception("recipes_search failed")
            return ToolResult(success=False, message=f"Recipe search failed: {e}")
        finally:
            db.close()


class RecipeGetTool(BaseTool):
    @property
    def name(self) -> str:
        return "recipes_get"

    @property
    def description(self) -> str:
        return "Get a single recipe's full ingredients, instructions, and metadata by ID."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {"recipe_id": {"type": "string"}},
            "required": ["recipe_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        recipe_id = kwargs.get("recipe_id")
        if not recipe_id:
            return ToolResult(success=False, message="recipe_id is required")
        db: Session = next(get_db())
        try:
            r = db.query(Recipe).filter(Recipe.id == recipe_id, Recipe.user_id == user_id).first()
            if not r:
                return ToolResult(success=False, message="Recipe not found")
            return ToolResult(success=True, data=_full(r), message=f"Recipe: {r.name}")
        finally:
            db.close()


class RecipeListTool(BaseTool):
    @property
    def name(self) -> str:
        return "recipes_list"

    @property
    def description(self) -> str:
        return "List David's recipes, most recently updated first. Optional filters by meal_type, starred, tag."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "meal_type": {"type": "string"},
                "starred": {"type": "boolean"},
                "tag": {"type": "string"},
                "limit": {"type": "integer", "default": 25},
            },
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        limit = int(kwargs.get("limit", 25) or 25)
        meal_type = kwargs.get("meal_type")
        starred = kwargs.get("starred")
        tag = (kwargs.get("tag") or "").strip().lower() or None

        db: Session = next(get_db())
        try:
            q = db.query(Recipe).filter(Recipe.user_id == user_id)
            if meal_type:
                q = q.filter(Recipe.meal_type == meal_type)
            if starred is not None:
                q = q.filter(Recipe.starred == bool(starred))
            if tag:
                q = q.filter(text("LOWER(tags::text) LIKE :tag_like")).params(tag_like=f"%{tag}%")
            rows = q.order_by(Recipe.updated_at.desc()).limit(limit).all()
            return ToolResult(
                success=True,
                data={"recipes": [_summary(r) for r in rows], "total": len(rows)},
                message=f"{len(rows)} recipe(s)",
            )
        finally:
            db.close()


class RecipeEditTool(BaseTool):
    @property
    def name(self) -> str:
        return "recipes_edit"

    @property
    def description(self) -> str:
        return "Edit an existing recipe. Provide only the fields you want to change."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "recipe_id": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "ingredients": {"type": "array"},
                "instructions": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}},
                "servings": {"type": "integer"},
                "prep_time_minutes": {"type": "integer"},
                "cook_time_minutes": {"type": "integer"},
                "category": {"type": "string"},
                "cuisine": {"type": "string"},
                "meal_type": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "source_url": {"type": "string"},
                "source_name": {"type": "string"},
                "recipe_notes": {"type": "string"},
                "starred": {"type": "boolean"},
                "rating": {"type": "integer"},
                "calories": {"type": "number"},
                "protein": {"type": "number"},
                "carbs": {"type": "number"},
                "fats": {"type": "number"},
            },
            "required": ["recipe_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        recipe_id = kwargs.pop("recipe_id", None)
        if not recipe_id:
            return ToolResult(success=False, message="recipe_id is required")

        db: Session = next(get_db())
        try:
            r = db.query(Recipe).filter(Recipe.id == recipe_id, Recipe.user_id == user_id).first()
            if not r:
                return ToolResult(success=False, message="Recipe not found")

            content_changed = False

            # Handle steps → instructions conversion
            if "steps" in kwargs and kwargs["steps"] is not None:
                kwargs["instructions"] = _instructions_from(kwargs.pop("steps"))

            for k, v in list(kwargs.items()):
                if v is None:
                    continue
                if k == "tags":
                    v = _norm_tags(v)
                elif k == "ingredients":
                    v = _norm_ingredients(v)
                if k in ("name", "description", "ingredients", "instructions", "tags"):
                    content_changed = True
                if hasattr(r, k):
                    setattr(r, k, v)

            if content_changed:
                try:
                    r.embedding = await get_embedding(_embed_text(
                        r.name or "", r.description or "",
                        list(r.ingredients or []),
                        r.instructions or "",
                        list(r.tags or []),
                    ))
                except Exception as e:
                    logger.warning(f"recipes_edit re-embed failed: {e}")

            db.commit()
            db.refresh(r)
            return ToolResult(success=True, data=_full(r), message=f"Updated recipe: {r.name}")
        except Exception as e:
            db.rollback()
            logger.exception("recipes_edit failed")
            return ToolResult(success=False, message=f"Failed to edit recipe: {e}")
        finally:
            db.close()


class RecipeDeleteTool(BaseTool):
    @property
    def name(self) -> str:
        return "recipes_delete"

    @property
    def description(self) -> str:
        return "Delete a recipe by ID."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {"recipe_id": {"type": "string"}},
            "required": ["recipe_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        recipe_id = kwargs.get("recipe_id")
        if not recipe_id:
            return ToolResult(success=False, message="recipe_id is required")
        db: Session = next(get_db())
        try:
            r = db.query(Recipe).filter(Recipe.id == recipe_id, Recipe.user_id == user_id).first()
            if not r:
                return ToolResult(success=False, message="Recipe not found")
            name = r.name
            db.delete(r)
            db.commit()
            return ToolResult(success=True, data={"deleted": recipe_id}, message=f"Deleted recipe: {name}")
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to delete: {e}")
        finally:
            db.close()


class RecipeLogMadeTool(BaseTool):
    @property
    def name(self) -> str:
        return "recipes_log_made"

    @property
    def description(self) -> str:
        return "Record that David made this recipe. Bumps times_made and updates last_made_at."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {"recipe_id": {"type": "string"}},
            "required": ["recipe_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        recipe_id = kwargs.get("recipe_id")
        if not recipe_id:
            return ToolResult(success=False, message="recipe_id is required")
        db: Session = next(get_db())
        try:
            r = db.query(Recipe).filter(Recipe.id == recipe_id, Recipe.user_id == user_id).first()
            if not r:
                return ToolResult(success=False, message="Recipe not found")
            r.last_made_at = datetime.now(timezone.utc)
            r.times_made = (r.times_made or 0) + 1
            db.commit()
            db.refresh(r)
            return ToolResult(
                success=True,
                data=_summary(r),
                message=f"Logged: made {r.name} (total: {r.times_made}x)",
            )
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to log: {e}")
        finally:
            db.close()


RECIPE_TOOLS = [
    RecipeCreateTool(),
    RecipeSearchTool(),
    RecipeGetTool(),
    RecipeListTool(),
    RecipeEditTool(),
    RecipeDeleteTool(),
    RecipeLogMadeTool(),
]
