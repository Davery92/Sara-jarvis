"""
Canonical food item v2 (SARA_INTELLIGENT_FOOD_LOGGING_PLAN_2026_08_16 §3.1).

One line-item shape every capture mode (search, recents, saved meal, repeat,
barcode, voice/text, photo, label) converges on. Mirrored in TypeScript —
`ios-app/src/services/foodContracts.ts` and `frontend/src/types/foodContracts.ts`
— with parity checked by `ios-app/scripts/check-food-contract-parity.mjs`
(same discipline as the workout wire contract's
`check-workout-contract-parity.mjs`). Change a field here, change it in both
TypeScript copies and the fixtures file, or the parity script fails.

v1 rows (the informal shape documented above `FoodLogCreate` in
app/routes/fitness.py — food_id/name/source/serving_id/serving_description/
quantity/unit/calories/protein/carbs/fats, no schema_version) are NOT
rewritten. `nutrition_basis="stored_snapshot"` plus all v2-only fields
defaulting to None/null is how a v1 row reads as valid v2 — the "legacy_ios"
and "legacy_web" fixtures below are what that read looks like. Existing
food-log endpoints keep accepting untyped v1 dicts; this schema is additive,
not yet enforced on write.
"""
from typing import Optional

from pydantic import BaseModel, Field

FOOD_ITEM_SCHEMA_VERSION = 2


class CanonicalFoodItemV2(BaseModel):
    schema_version: int = FOOD_ITEM_SCHEMA_VERSION
    line_id: str  # client-or-server UUID, unique within one MealDraft/meal
    food_id: Optional[str] = None  # "fs-123" | custom UUID | "recipe-<uuid>" | null
    name: str
    brand: Optional[str] = None
    source: str  # fatsecret | user | recipe | manual | photo | label
    serving_id: Optional[str] = None  # source serving ID or null
    serving_description: Optional[str] = None  # "3 oz"
    quantity: float
    unit: str
    base_amount: float = 1
    base_unit: str = "serving"
    # Scaled line totals (quantity * base-serving macros), not per-100g.
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None
    # resolved_serving: matched a real FatSecret/custom-food serving.
    # stored_snapshot: read back from a v1 row with no serving provenance.
    # estimated: AI-guessed (photo/label OCR low-confidence, generic fallback).
    nutrition_basis: str = "resolved_serving"
    resolution_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    estimate_notes: Optional[str] = None
