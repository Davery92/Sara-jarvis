"""Recipe schemas (knowledge-garden side; coexists with fitness recipe schemas)."""
from typing import Optional, List, Any, Dict
from pydantic import BaseModel


class IngredientItem(BaseModel):
    name: str
    quantity: Optional[float] = None
    unit: Optional[str] = None
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None


class RecipeCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    category: Optional[str] = None
    ingredients: List[IngredientItem] = []
    instructions: str = ""
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    servings: int = 1
    meal_type: Optional[str] = None
    cuisine: Optional[str] = None
    tags: List[str] = []
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    recipe_notes: Optional[str] = ""
    starred: bool = False
    rating: Optional[int] = None
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None


class RecipeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    ingredients: Optional[List[IngredientItem]] = None
    instructions: Optional[str] = None
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    servings: Optional[int] = None
    meal_type: Optional[str] = None
    cuisine: Optional[str] = None
    tags: Optional[List[str]] = None
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    recipe_notes: Optional[str] = None
    starred: Optional[bool] = None
    rating: Optional[int] = None
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None


class RecipeResponse(BaseModel):
    id: str
    name: str
    description: str
    category: Optional[str]
    ingredients: List[Dict[str, Any]]
    instructions: str
    prep_time_minutes: Optional[int]
    cook_time_minutes: Optional[int]
    servings: int
    meal_type: Optional[str]
    cuisine: Optional[str]
    tags: List[str]
    source_url: Optional[str]
    source_name: Optional[str]
    recipe_notes: str
    starred: bool
    rating: Optional[int]
    calories: Optional[float]
    protein: Optional[float]
    carbs: Optional[float]
    fats: Optional[float]
    last_made_at: Optional[str]
    times_made: int
    created_at: str
    updated_at: str
