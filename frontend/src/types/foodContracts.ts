/**
 * Canonical food item v2 (SARA_INTELLIGENT_FOOD_LOGGING_PLAN_2026_08_16 §3.1).
 *
 * Mirrors backend/app/schemas/food_item.py and
 * ios-app/src/services/foodContracts.ts. Field-name parity across all three
 * is checked by ios-app/scripts/check-food-contract-parity.mjs - change a
 * field here, change it in both other copies and the fixtures file, or the
 * parity script fails.
 *
 * v1 rows (the informal shape documented above `FoodLogCreate` in
 * backend/app/routes/fitness.py) are NOT rewritten. This is additive:
 * existing endpoints keep accepting untyped v1 dicts.
 */

export const FOOD_ITEM_SCHEMA_VERSION = 2

export type FoodItemSource = 'fatsecret' | 'user' | 'recipe' | 'manual' | 'photo' | 'label'

// resolved_serving: matched a real FatSecret/custom-food serving.
// stored_snapshot: read back from a v1 row with no serving provenance.
// estimated: AI-guessed (photo/label OCR low-confidence, generic fallback).
export type NutritionBasis = 'resolved_serving' | 'stored_snapshot' | 'estimated'

export interface CanonicalFoodItemV2 {
  schema_version: number
  line_id: string // client-or-server UUID, unique within one MealDraft/meal
  food_id: string | null // "fs-123" | custom UUID | "recipe-<uuid>" | null
  name: string
  brand: string | null
  source: FoodItemSource
  serving_id: string | null // source serving ID or null
  serving_description: string | null // "3 oz"
  quantity: number
  unit: string
  base_amount: number
  base_unit: string
  // Scaled line totals (quantity * base-serving macros), not per-100g.
  calories: number | null
  protein: number | null
  carbs: number | null
  fats: number | null
  nutrition_basis: NutritionBasis
  resolution_confidence: number
  estimate_notes: string | null
}
