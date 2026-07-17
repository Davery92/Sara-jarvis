import React, { useState, useEffect, useRef, useMemo } from 'react'
import { Search, Plus, X, ChevronDown, Clock, Calendar } from 'lucide-react'
import apiClient from '../../api/client'

// Unit conversion constants
const UNIT_CONVERSIONS: Record<string, number> = {
  // Weight units (base: grams)
  'g': 1,
  'gram': 1,
  'grams': 1,
  'oz': 28.3495,
  'ounce': 28.3495,
  'ounces': 28.3495,
  'lb': 453.592,
  'lbs': 453.592,
  'pound': 453.592,
  'pounds': 453.592,
  // Volume units (base: ml)
  'ml': 1,
  'milliliter': 1,
  'milliliters': 1,
  'cup': 240,
  'cups': 240,
  'tbsp': 15,
  'tablespoon': 15,
  'tablespoons': 15,
  'tsp': 5,
  'teaspoon': 5,
  'teaspoons': 5,
  'fl oz': 29.5735,
  'fluid oz': 29.5735,
  'fluid ounce': 29.5735,
  'fluid ounces': 29.5735,
}

const WEIGHT_UNITS = ['g', 'gram', 'grams', 'oz', 'ounce', 'ounces', 'lb', 'lbs', 'pound', 'pounds']
const VOLUME_UNITS = ['ml', 'milliliter', 'milliliters', 'cup', 'cups', 'tbsp', 'tablespoon', 'tablespoons', 'tsp', 'teaspoon', 'teaspoons', 'fl oz', 'fluid oz', 'fluid ounce', 'fluid ounces']

const COMMON_UNITS = [
  'serving',
  'g',
  'oz',
  'cup',
  'tbsp',
  'tsp',
  'ml',
  'fl oz',
  'lb',
  'piece',
  'slice',
]

// Parse serving description like "292g", "1 cup (185g)", "100 ml" into { amount, unit }
function parseServingDescription(description: string): { amount: number; unit: string } | null {
  if (!description) return null

  const desc = description.toLowerCase().trim()

  // Pattern 1: "292g" or "100ml" (number directly followed by unit)
  const directMatch = desc.match(/^(\d+(?:\.\d+)?)\s*(g|gram|grams|oz|ounce|ounces|ml|cup|cups|tbsp|tsp|lb|lbs)$/i)
  if (directMatch) {
    return { amount: parseFloat(directMatch[1]), unit: directMatch[2] }
  }

  // Pattern 2: "1 cup (185g)" - extract the gram equivalent in parentheses
  const parenMatch = desc.match(/\((\d+(?:\.\d+)?)\s*(g|gram|grams|ml)\)/i)
  if (parenMatch) {
    return { amount: parseFloat(parenMatch[1]), unit: parenMatch[2] }
  }

  // Pattern 3: "100 g" or "8 oz" (number space unit)
  const spaceMatch = desc.match(/^(\d+(?:\.\d+)?)\s+(g|gram|grams|oz|ounce|ounces|ml|cup|cups|tbsp|tsp|lb|lbs|fl\s*oz)$/i)
  if (spaceMatch) {
    return { amount: parseFloat(spaceMatch[1]), unit: spaceMatch[2].replace(/\s+/g, ' ') }
  }

  return null
}

interface FoodServing {
  serving_id: string
  serving_description: string
  metric_serving_amount?: number
  metric_serving_unit?: string
  calories: number
  protein: number
  carbs: number
  fat: number
  fiber?: number
  sugar?: number
  sodium?: number
}

interface Food {
  id: string
  fatsecret_id?: string
  name: string
  brand?: string
  food_type?: string
  serving_size: number
  serving_unit: string
  calories?: number
  protein?: number
  carbs?: number
  fats?: number
  fiber?: number
  sugar?: number
  sodium?: number
  is_custom: boolean
  source: string
  servings?: FoodServing[]
}

export interface SelectedFoodItem extends Food {
  quantity: number
  selected_serving?: FoodServing
  selected_unit?: string  // User-selected unit for conversion
  base_nutrition?: {      // Original nutrition values from the food source
    calories: number
    protein: number
    carbs: number
    fats: number
    per_amount: number
    per_unit: string
  }
  calculated_calories?: number
  calculated_protein?: number
  calculated_carbs?: number
  calculated_fats?: number
}

interface FoodItemSelectorProps {
  onFoodsSelected: (foods: SelectedFoodItem[]) => void
  initialFoods?: SelectedFoodItem[]
}

export default function FoodItemSelector({ onFoodsSelected, initialFoods = [] }: FoodItemSelectorProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Food[]>([])
  const [recentFoods, setRecentFoods] = useState<any[]>([])
  const [yesterdayFoods, setYesterdayFoods] = useState<any[]>([])
  const [recipes, setRecipes] = useState<any[]>([])
  const [selectedFoods, setSelectedFoods] = useState<SelectedFoodItem[]>(initialFoods)
  const [isSearching, setIsSearching] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const [showCustomForm, setShowCustomForm] = useState(false)
  const [loadingDetails, setLoadingDetails] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'recent' | 'yesterday' | 'recipes'>('recent')
  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Load recent foods, yesterday's foods, and recipes on mount
  useEffect(() => {
    loadRecentFoods()
    loadYesterdayFoods()
    loadRecipes()
  }, [])

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Notify parent when selected foods change
  useEffect(() => {
    onFoodsSelected(selectedFoods)
  }, [selectedFoods, onFoodsSelected])

  // Debounced search
  useEffect(() => {
    if (searchTimeout.current) {
      clearTimeout(searchTimeout.current)
    }

    if (searchQuery.length < 2) {
      setSearchResults([])
      setShowDropdown(false)
      return
    }

    setIsSearching(true)
    searchTimeout.current = setTimeout(async () => {
      try {
        const results = await apiClient.searchFoods(searchQuery, 15)
        setSearchResults(results)
        setShowDropdown(true)
      } catch (error) {
        console.error('Search failed:', error)
      } finally {
        setIsSearching(false)
      }
    }, 300)

    return () => {
      if (searchTimeout.current) {
        clearTimeout(searchTimeout.current)
      }
    }
  }, [searchQuery])

  async function loadRecentFoods() {
    try {
      const foods = await apiClient.getRecentFoods(20)
      setRecentFoods(foods)
    } catch (error) {
      console.error('Failed to load recent foods:', error)
    }
  }

  async function loadRecipes() {
    try {
      const recipeList = await apiClient.getRecipes(5)
      setRecipes(recipeList)
    } catch (error) {
      console.error('Failed to load recipes:', error)
    }
  }

  async function loadYesterdayFoods() {
    try {
      const data = await apiClient.getYesterdayFoods()
      setYesterdayFoods(data.all_foods || [])
    } catch (error) {
      console.error('Failed to load yesterday foods:', error)
    }
  }

  function addRecentFood(food: any) {
    // Convert recent food format to SelectedFoodItem
    const selectedFood: SelectedFoodItem = {
      id: food.id || `recent-${Date.now()}`,
      fatsecret_id: food.fatsecret_id,
      name: food.name,
      brand: food.brand,
      serving_size: food.serving_size || 1,
      serving_unit: food.serving_unit || 'serving',
      calories: food.calories,
      protein: food.protein,
      carbs: food.carbs,
      fats: food.fats,
      is_custom: food.is_custom || false,
      source: food.source || 'recent',
      quantity: food.serving_size || 1,
      calculated_calories: food.calories,
      calculated_protein: food.protein,
      calculated_carbs: food.carbs,
      calculated_fats: food.fats,
    }
    setSelectedFoods([...selectedFoods, selectedFood])
  }

  function calculateNutrition(food: Food, quantity: number, serving?: FoodServing, selectedUnit?: string): SelectedFoodItem {
    if (serving) {
      // Parse the serving description to get the actual amount and unit
      // E.g., "292g" -> { amount: 292, unit: 'g' }
      const parsed = parseServingDescription(serving.serving_description)

      if (parsed && selectedUnit) {
        // User changed the unit - do unit conversion
        const targetUnit = selectedUnit.toLowerCase().trim()
        const sourceUnit = parsed.unit.toLowerCase().trim()

        const sourceIsWeight = WEIGHT_UNITS.includes(sourceUnit)
        const targetIsWeight = WEIGHT_UNITS.includes(targetUnit)
        const sourceIsVolume = VOLUME_UNITS.includes(sourceUnit)
        const targetIsVolume = VOLUME_UNITS.includes(targetUnit)

        let multiplier = quantity

        if (sourceIsWeight && targetIsWeight) {
          const targetInGrams = quantity * (UNIT_CONVERSIONS[targetUnit] || 1)
          const sourceInGrams = parsed.amount * (UNIT_CONVERSIONS[sourceUnit] || 1)
          multiplier = targetInGrams / sourceInGrams
        } else if (sourceIsVolume && targetIsVolume) {
          const targetInMl = quantity * (UNIT_CONVERSIONS[targetUnit] || 1)
          const sourceInMl = parsed.amount * (UNIT_CONVERSIONS[sourceUnit] || 1)
          multiplier = targetInMl / sourceInMl
        }

        return {
          ...food,
          quantity,
          selected_serving: serving,
          selected_unit: selectedUnit,
          base_nutrition: {
            calories: serving.calories,
            protein: serving.protein,
            carbs: serving.carbs,
            fats: serving.fat,
            per_amount: parsed.amount,
            per_unit: parsed.unit,
          },
          calculated_calories: Math.round(serving.calories * multiplier),
          calculated_protein: parseFloat((serving.protein * multiplier).toFixed(1)),
          calculated_carbs: parseFloat((serving.carbs * multiplier).toFixed(1)),
          calculated_fats: parseFloat((serving.fat * multiplier).toFixed(1)),
        }
      }

      // No unit conversion needed - just multiply by quantity
      return {
        ...food,
        quantity,
        selected_serving: serving,
        selected_unit: selectedUnit || (parsed ? parsed.unit : serving.serving_description),
        base_nutrition: {
          calories: serving.calories,
          protein: serving.protein,
          carbs: serving.carbs,
          fats: serving.fat,
          per_amount: parsed ? parsed.amount : 1,
          per_unit: parsed ? parsed.unit : serving.serving_description,
        },
        calculated_calories: serving.calories * quantity,
        calculated_protein: serving.protein * quantity,
        calculated_carbs: serving.carbs * quantity,
        calculated_fats: serving.fat * quantity,
      }
    }

    // For custom foods or foods without FatSecret serving data - support unit conversion
    // Try to parse the serving unit in case it's like "292g"
    const parsed = parseServingDescription(food.serving_unit || '')
    const baseUnit = parsed ? parsed.unit.toLowerCase().trim() : (food.serving_unit?.toLowerCase().trim() || 'serving')
    const baseAmount = parsed ? parsed.amount : (food.serving_size || 1)
    const targetUnit = (selectedUnit || baseUnit).toLowerCase().trim()

    // Store base nutrition for future recalculations
    const baseNutrition = {
      calories: food.calories || 0,
      protein: food.protein || 0,
      carbs: food.carbs || 0,
      fats: food.fats || 0,
      per_amount: baseAmount,
      per_unit: baseUnit,
    }

    // Calculate multiplier with unit conversion
    let multiplier = quantity

    const sourceIsWeight = WEIGHT_UNITS.includes(baseUnit)
    const targetIsWeight = WEIGHT_UNITS.includes(targetUnit)
    const sourceIsVolume = VOLUME_UNITS.includes(baseUnit)
    const targetIsVolume = VOLUME_UNITS.includes(targetUnit)

    if (sourceIsWeight && targetIsWeight) {
      // Both are weight units - convert
      const targetInGrams = quantity * (UNIT_CONVERSIONS[targetUnit] || 1)
      const sourceInGrams = baseAmount * (UNIT_CONVERSIONS[baseUnit] || 1)
      multiplier = targetInGrams / sourceInGrams
    } else if (sourceIsVolume && targetIsVolume) {
      // Both are volume units - convert
      const targetInMl = quantity * (UNIT_CONVERSIONS[targetUnit] || 1)
      const sourceInMl = baseAmount * (UNIT_CONVERSIONS[baseUnit] || 1)
      multiplier = targetInMl / sourceInMl
    }
    // If units are incompatible (e.g., serving, piece), just use quantity as multiplier

    return {
      ...food,
      quantity,
      selected_unit: selectedUnit || baseUnit,
      base_nutrition: baseNutrition,
      calculated_calories: food.calories ? Math.round(food.calories * multiplier) : undefined,
      calculated_protein: food.protein ? parseFloat((food.protein * multiplier).toFixed(1)) : undefined,
      calculated_carbs: food.carbs ? parseFloat((food.carbs * multiplier).toFixed(1)) : undefined,
      calculated_fats: food.fats ? parseFloat((food.fats * multiplier).toFixed(1)) : undefined,
    }
  }

  async function addFood(food: Food) {
    setLoadingDetails(food.id)

    try {
      // For FatSecret foods, fetch detailed serving info
      if (food.source === 'fatsecret' && food.id.startsWith('fs-')) {
        const details = await apiClient.getFoodDetails(food.id)
        const defaultServing = details.servings?.[0]

        const selectedFood = calculateNutrition(
          { ...food, servings: details.servings },
          1,
          defaultServing
        )
        setSelectedFoods([...selectedFoods, selectedFood])
      } else {
        // Custom foods - use existing nutrition
        const selectedFood = calculateNutrition(food, food.serving_size || 1)
        setSelectedFoods([...selectedFoods, selectedFood])
      }
    } catch (error) {
      console.error('Failed to get food details:', error)
      // Fallback to basic add
      const selectedFood = calculateNutrition(food, food.serving_size || 1)
      setSelectedFoods([...selectedFoods, selectedFood])
    } finally {
      setLoadingDetails(null)
      setSearchQuery('')
      setShowDropdown(false)
    }
  }

  function addRecipe(recipe: any) {
    const servings = recipe.servings || 1
    const ingredientFoods: SelectedFoodItem[] = recipe.ingredients.map((ingredient: any) => {
      const perServingQuantity = Math.round((ingredient.quantity / servings) * 100) / 100
      const perServingCalories = Math.round(((ingredient.calories || 0) / servings) * 100) / 100
      const perServingProtein = Math.round(((ingredient.protein || 0) / servings) * 100) / 100
      const perServingCarbs = Math.round(((ingredient.carbs || 0) / servings) * 100) / 100
      const perServingFats = Math.round(((ingredient.fats || 0) / servings) * 100) / 100

      return {
        id: `recipe-${recipe.id}-${ingredient.name}`,
        name: ingredient.name,
        brand: '',
        serving_size: perServingQuantity,
        serving_unit: ingredient.unit,
        calories: perServingCalories,
        protein: perServingProtein,
        carbs: perServingCarbs,
        fats: perServingFats,
        is_custom: false,
        source: 'recipe',
        quantity: perServingQuantity,
        calculated_calories: perServingCalories,
        calculated_protein: perServingProtein,
        calculated_carbs: perServingCarbs,
        calculated_fats: perServingFats,
      }
    })
    setSelectedFoods([...selectedFoods, ...ingredientFoods])
  }

  function removeFood(index: number) {
    setSelectedFoods(selectedFoods.filter((_, i) => i !== index))
  }

  function updateQuantity(index: number, quantity: number) {
    const updatedFoods = [...selectedFoods]
    const food = updatedFoods[index]
    updatedFoods[index] = calculateNutrition(food, quantity, food.selected_serving, food.selected_unit)
    setSelectedFoods(updatedFoods)
  }

  function updateServing(index: number, serving: FoodServing) {
    const updatedFoods = [...selectedFoods]
    const food = updatedFoods[index]
    updatedFoods[index] = calculateNutrition(food, food.quantity, serving, food.selected_unit)
    setSelectedFoods(updatedFoods)
  }

  function updateUnit(index: number, newUnit: string) {
    const updatedFoods = [...selectedFoods]
    const food = updatedFoods[index]
    updatedFoods[index] = calculateNutrition(food, food.quantity, food.selected_serving, newUnit)
    setSelectedFoods(updatedFoods)
  }

  async function createCustomFood(foodData: Partial<Food>) {
    try {
      const newFood = await apiClient.createFood({
        name: foodData.name,
        brand: foodData.brand,
        serving_size: foodData.serving_size || 1,
        serving_unit: foodData.serving_unit || 'serving',
        calories: foodData.calories,
        protein: foodData.protein,
        carbs: foodData.carbs,
        fats: foodData.fats,
        fiber: foodData.fiber,
        sugar: foodData.sugar,
        sodium: foodData.sodium,
      })
      addFood(newFood)
      setShowCustomForm(false)
      loadRecentFoods()
    } catch (error) {
      console.error('Failed to create custom food:', error)
    }
  }

  // Calculate totals
  const totals = selectedFoods.reduce(
    (acc, food) => ({
      calories: acc.calories + (food.calculated_calories || 0),
      protein: acc.protein + (food.calculated_protein || 0),
      carbs: acc.carbs + (food.calculated_carbs || 0),
      fats: acc.fats + (food.calculated_fats || 0),
    }),
    { calories: 0, protein: 0, carbs: 0, fats: 0 }
  )

  return (
    <div className="space-y-4">
      {/* Search Input */}
      <div className="relative" ref={dropdownRef}>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onFocus={() => {
              if (searchResults.length > 0) setShowDropdown(true)
            }}
            placeholder="Search foods..."
            className="w-full pl-10 pr-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
          />
          {isSearching && (
            <div className="absolute right-3 top-1/2 transform -translate-y-1/2">
              <div className="animate-spin w-5 h-5 border-2 border-purple-500 border-t-transparent rounded-full" />
            </div>
          )}
        </div>

        {/* Search Results Dropdown */}
        {showDropdown && searchResults.length > 0 && (
          <div className="absolute z-10 w-full mt-2 bg-gray-800 border border-gray-700 rounded-lg shadow-lg max-h-80 overflow-y-auto">
            {searchResults.map((food) => (
              <button
                type="button"
                key={food.id}
                onClick={() => addFood(food)}
                disabled={loadingDetails === food.id}
                className="w-full px-4 py-3 text-left hover:bg-gray-700 transition-colors border-b border-gray-700 last:border-b-0 disabled:opacity-50"
              >
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <div className="font-medium text-white">{food.name}</div>
                      {food.source === 'fatsecret' && (
                        <span className="px-1.5 py-0.5 bg-green-900/50 border border-green-700/50 text-green-300 text-[10px] rounded uppercase font-medium">
                          FatSecret
                        </span>
                      )}
                      {food.is_custom && (
                        <span className="px-1.5 py-0.5 bg-purple-900/50 border border-purple-700/50 text-purple-300 text-[10px] rounded uppercase font-medium">
                          Custom
                        </span>
                      )}
                      {food.food_type === 'Brand' && (
                        <span className="px-1.5 py-0.5 bg-blue-900/50 border border-blue-700/50 text-blue-300 text-[10px] rounded uppercase font-medium">
                          Brand
                        </span>
                      )}
                    </div>
                    {food.brand && <div className="text-sm text-gray-400">{food.brand}</div>}
                    <div className="text-xs text-gray-500 mt-1">
                      {food.serving_unit}
                      {food.calories && ` | ${Math.round(food.calories)} cal`}
                      {food.protein && ` | ${Math.round(food.protein)}g protein`}
                    </div>
                  </div>
                  {loadingDetails === food.id ? (
                    <div className="animate-spin w-5 h-5 border-2 border-purple-500 border-t-transparent rounded-full flex-shrink-0 ml-2" />
                  ) : (
                    <Plus className="w-5 h-5 text-purple-400 flex-shrink-0 ml-2" />
                  )}
                </div>
              </button>
            ))}
            {/* FatSecret Attribution */}
            <div className="px-4 py-2 text-center border-t border-gray-700 bg-gray-900/50">
              <a
                href="https://www.fatsecret.com"
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-gray-500 hover:text-gray-400"
              >
                Powered by FatSecret
              </a>
            </div>
          </div>
        )}
      </div>

      {/* Quick Add Tabs - Recent, Yesterday, Recipes */}
      {searchQuery.length === 0 && (recentFoods.length > 0 || yesterdayFoods.length > 0 || recipes.length > 0) && (
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg overflow-hidden">
          {/* Tab Headers */}
          <div className="flex border-b border-gray-700">
            <button
              type="button"
              onClick={() => setActiveTab('recent')}
              className={`flex-1 px-4 py-2 text-sm font-medium transition-colors flex items-center justify-center gap-2 ${
                activeTab === 'recent'
                  ? 'bg-gray-700 text-white border-b-2 border-purple-500'
                  : 'text-gray-400 hover:text-white hover:bg-gray-700/50'
              }`}
            >
              <Clock className="w-4 h-4" />
              Recent ({recentFoods.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('yesterday')}
              className={`flex-1 px-4 py-2 text-sm font-medium transition-colors flex items-center justify-center gap-2 ${
                activeTab === 'yesterday'
                  ? 'bg-gray-700 text-white border-b-2 border-purple-500'
                  : 'text-gray-400 hover:text-white hover:bg-gray-700/50'
              }`}
            >
              <Calendar className="w-4 h-4" />
              Yesterday ({yesterdayFoods.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('recipes')}
              className={`flex-1 px-4 py-2 text-sm font-medium transition-colors flex items-center justify-center gap-2 ${
                activeTab === 'recipes'
                  ? 'bg-gray-700 text-white border-b-2 border-purple-500'
                  : 'text-gray-400 hover:text-white hover:bg-gray-700/50'
              }`}
            >
              Recipes ({recipes.length})
            </button>
          </div>

          {/* Tab Content */}
          <div className="p-3 max-h-64 overflow-y-auto">
            {/* Recent Foods Tab */}
            {activeTab === 'recent' && (
              <div className="space-y-2">
                {recentFoods.length === 0 ? (
                  <div className="text-center text-gray-500 py-4 text-sm">
                    No recent foods. Start logging to see your frequently used items here.
                  </div>
                ) : (
                  recentFoods.map((food, idx) => (
                    <button
                      type="button"
                      key={`recent-${food.name}-${idx}`}
                      onClick={() => addRecentFood(food)}
                      className="w-full px-3 py-2 bg-gray-900/50 border border-gray-700 rounded-lg text-left hover:bg-gray-700 transition-colors group"
                    >
                      <div className="flex justify-between items-center">
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-white truncate">{food.name}</div>
                          <div className="text-xs text-gray-400 flex items-center gap-2">
                            <span>{food.serving_size} {food.serving_unit}</span>
                            {food.calories && <span>• {Math.round(food.calories)} cal</span>}
                            {food.protein && <span>• {Math.round(food.protein)}g protein</span>}
                          </div>
                          <div className="text-xs text-gray-500 mt-0.5">
                            Logged {food.count}x in last 30 days
                          </div>
                        </div>
                        <Plus className="w-5 h-5 text-gray-500 group-hover:text-purple-400 flex-shrink-0 ml-2" />
                      </div>
                    </button>
                  ))
                )}
              </div>
            )}

            {/* Yesterday Foods Tab */}
            {activeTab === 'yesterday' && (
              <div className="space-y-2">
                {yesterdayFoods.length === 0 ? (
                  <div className="text-center text-gray-500 py-4 text-sm">
                    No foods logged yesterday.
                  </div>
                ) : (
                  yesterdayFoods.map((food, idx) => (
                    <button
                      type="button"
                      key={`yesterday-${food.name}-${idx}`}
                      onClick={() => addRecentFood(food)}
                      className="w-full px-3 py-2 bg-gray-900/50 border border-gray-700 rounded-lg text-left hover:bg-gray-700 transition-colors group"
                    >
                      <div className="flex justify-between items-center">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-white truncate">{food.name}</span>
                            <span className="px-1.5 py-0.5 bg-gray-700 text-gray-300 text-[10px] rounded uppercase">
                              {food.meal_type}
                            </span>
                          </div>
                          <div className="text-xs text-gray-400 flex items-center gap-2">
                            <span>{food.serving_size} {food.serving_unit}</span>
                            {food.calories && <span>• {Math.round(food.calories)} cal</span>}
                            {food.protein && <span>• {Math.round(food.protein)}g protein</span>}
                          </div>
                        </div>
                        <Plus className="w-5 h-5 text-gray-500 group-hover:text-purple-400 flex-shrink-0 ml-2" />
                      </div>
                    </button>
                  ))
                )}
              </div>
            )}

            {/* Recipes Tab */}
            {activeTab === 'recipes' && (
              <div className="space-y-2">
                {recipes.length === 0 ? (
                  <div className="text-center text-gray-500 py-4 text-sm">
                    No recipes saved. Create recipes to quickly log meals.
                  </div>
                ) : (
                  recipes.map((recipe) => (
                    <button
                      type="button"
                      key={recipe.id}
                      onClick={() => addRecipe(recipe)}
                      className="w-full px-3 py-2 bg-purple-900/20 border border-purple-700/50 rounded-lg text-left hover:bg-purple-800/30 transition-colors group"
                    >
                      <div className="flex justify-between items-center">
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-purple-300 truncate">{recipe.name}</div>
                          <div className="text-xs text-gray-400">
                            {recipe.ingredients?.length || 0} ingredients
                            {recipe.total_calories && ` • ${Math.round(recipe.total_calories)} cal`}
                          </div>
                        </div>
                        <Plus className="w-5 h-5 text-purple-400/50 group-hover:text-purple-400 flex-shrink-0 ml-2" />
                      </div>
                    </button>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Add Custom Food Button */}
      <button
        type="button"
        onClick={() => setShowCustomForm(!showCustomForm)}
        className="w-full py-2 border-2 border-dashed border-gray-700 rounded-lg text-gray-400 hover:border-purple-500 hover:text-purple-400 transition-colors flex items-center justify-center gap-2"
      >
        <Plus className="w-4 h-4" />
        Add Custom Food
      </button>

      {/* Custom Food Form */}
      {showCustomForm && <CustomFoodForm onSubmit={createCustomFood} onCancel={() => setShowCustomForm(false)} />}

      {/* Selected Foods */}
      {selectedFoods.length > 0 && (
        <div className="space-y-2">
          <div className="text-sm font-medium text-gray-300 mb-2">Selected Foods:</div>
          {selectedFoods.map((food, index) => (
            <div key={index} className="bg-gray-800 border border-gray-700 rounded-lg p-3">
              <div className="flex justify-between items-start mb-2">
                <div className="flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="font-medium text-white">{food.name}</div>
                    {food.source === 'fatsecret' && (
                      <span className="px-1.5 py-0.5 bg-green-900/50 border border-green-700/50 text-green-300 text-[10px] rounded uppercase font-medium">
                        FatSecret
                      </span>
                    )}
                    {food.is_custom && (
                      <span className="px-1.5 py-0.5 bg-purple-900/50 border border-purple-700/50 text-purple-300 text-[10px] rounded uppercase font-medium">
                        Custom
                      </span>
                    )}
                  </div>
                  {food.brand && <div className="text-xs text-gray-400">{food.brand}</div>}
                </div>
                <button
                  type="button"
                  onClick={() => removeFood(index)}
                  className="text-gray-400 hover:text-red-400 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="flex items-center gap-3 mb-2">
                <input
                  type="number"
                  value={food.quantity}
                  onChange={(e) => updateQuantity(index, parseFloat(e.target.value) || 0)}
                  min="0"
                  step="0.01"
                  className="w-20 px-2 py-1 bg-gray-900 border border-gray-700 rounded text-white text-sm"
                />

                {/* Serving Size Selector for FatSecret foods */}
                {food.servings && food.servings.length > 1 ? (
                  <select
                    value={food.selected_serving?.serving_id || food.servings[0]?.serving_id}
                    onChange={(e) => {
                      const serving = food.servings?.find(s => s.serving_id === e.target.value)
                      if (serving) updateServing(index, serving)
                    }}
                    className="flex-1 px-2 py-1 bg-gray-900 border border-gray-700 rounded text-white text-sm"
                  >
                    {food.servings.map(serving => (
                      <option key={serving.serving_id} value={serving.serving_id}>
                        {serving.serving_description} ({Math.round(serving.calories)} cal)
                      </option>
                    ))}
                  </select>
                ) : (
                  <select
                    value={food.selected_unit || food.serving_unit || 'serving'}
                    onChange={(e) => updateUnit(index, e.target.value)}
                    className="flex-1 px-2 py-1 bg-gray-900 border border-gray-700 rounded text-white text-sm"
                  >
                    {/* Show current unit first if not in common units */}
                    {food.serving_unit && !COMMON_UNITS.includes(food.serving_unit.toLowerCase()) && (
                      <option value={food.serving_unit}>{food.serving_unit}</option>
                    )}
                    {COMMON_UNITS.map(unit => (
                      <option key={unit} value={unit}>{unit}</option>
                    ))}
                  </select>
                )}
              </div>

              <div className="grid grid-cols-4 gap-2 text-xs">
                {food.calculated_calories !== undefined && (
                  <div className="text-center">
                    <div className="text-gray-400">Cal</div>
                    <div className="text-white font-medium">{Math.round(food.calculated_calories)}</div>
                  </div>
                )}
                {food.calculated_protein !== undefined && (
                  <div className="text-center">
                    <div className="text-gray-400">Protein</div>
                    <div className="text-white font-medium">{Math.round(food.calculated_protein)}g</div>
                  </div>
                )}
                {food.calculated_carbs !== undefined && (
                  <div className="text-center">
                    <div className="text-gray-400">Carbs</div>
                    <div className="text-white font-medium">{Math.round(food.calculated_carbs)}g</div>
                  </div>
                )}
                {food.calculated_fats !== undefined && (
                  <div className="text-center">
                    <div className="text-gray-400">Fats</div>
                    <div className="text-white font-medium">{Math.round(food.calculated_fats)}g</div>
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* Totals */}
          <div className="bg-purple-900/20 border border-purple-500/30 rounded-lg p-3">
            <div className="text-sm font-medium text-purple-300 mb-2">Meal Totals:</div>
            <div className="grid grid-cols-4 gap-2 text-sm">
              <div className="text-center">
                <div className="text-gray-400">Calories</div>
                <div className="text-white font-bold">{Math.round(totals.calories)}</div>
              </div>
              <div className="text-center">
                <div className="text-gray-400">Protein</div>
                <div className="text-white font-bold">{Math.round(totals.protein)}g</div>
              </div>
              <div className="text-center">
                <div className="text-gray-400">Carbs</div>
                <div className="text-white font-bold">{Math.round(totals.carbs)}g</div>
              </div>
              <div className="text-center">
                <div className="text-gray-400">Fats</div>
                <div className="text-white font-bold">{Math.round(totals.fats)}g</div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// Custom Food Form Component
interface CustomFoodFormProps {
  onSubmit: (food: Partial<Food>) => void
  onCancel: () => void
}

function CustomFoodForm({ onSubmit, onCancel }: CustomFoodFormProps) {
  const [formData, setFormData] = useState({
    name: '',
    brand: '',
    serving_size: 1,
    serving_unit: 'serving',
    calories: '',
    protein: '',
    carbs: '',
    fats: '',
  })

  function handleSubmit() {
    if (!formData.name) return
    onSubmit({
      name: formData.name,
      brand: formData.brand || undefined,
      serving_size: formData.serving_size,
      serving_unit: formData.serving_unit,
      calories: formData.calories ? parseFloat(formData.calories) : undefined,
      protein: formData.protein ? parseFloat(formData.protein) : undefined,
      carbs: formData.carbs ? parseFloat(formData.carbs) : undefined,
      fats: formData.fats ? parseFloat(formData.fats) : undefined,
    })
  }

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-3">
      <div className="text-sm font-medium text-white mb-3">Create Custom Food</div>

      <input
        type="text"
        placeholder="Food name *"
        required
        value={formData.name}
        onChange={(e) => setFormData({ ...formData, name: e.target.value })}
        className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
      />

      <input
        type="text"
        placeholder="Brand (optional)"
        value={formData.brand}
        onChange={(e) => setFormData({ ...formData, brand: e.target.value })}
        className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
      />

      <div className="grid grid-cols-2 gap-3">
        <input
          type="number"
          placeholder="Serving size *"
          required
          min="0"
          step="0.01"
          value={formData.serving_size}
          onChange={(e) => setFormData({ ...formData, serving_size: parseFloat(e.target.value) })}
          className="px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
        />
        <input
          type="text"
          placeholder="Unit *"
          required
          value={formData.serving_unit}
          onChange={(e) => setFormData({ ...formData, serving_unit: e.target.value })}
          className="px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <input
          type="number"
          placeholder="Calories"
          min="0"
          step="0.01"
          value={formData.calories}
          onChange={(e) => setFormData({ ...formData, calories: e.target.value })}
          className="px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
        />
        <input
          type="number"
          placeholder="Protein (g)"
          min="0"
          step="0.01"
          value={formData.protein}
          onChange={(e) => setFormData({ ...formData, protein: e.target.value })}
          className="px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <input
          type="number"
          placeholder="Carbs (g)"
          min="0"
          step="0.01"
          value={formData.carbs}
          onChange={(e) => setFormData({ ...formData, carbs: e.target.value })}
          className="px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
        />
        <input
          type="number"
          placeholder="Fats (g)"
          min="0"
          step="0.01"
          value={formData.fats}
          onChange={(e) => setFormData({ ...formData, fats: e.target.value })}
          className="px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
        />
      </div>

      <div className="flex gap-2 pt-2">
        <button
          type="button"
          onClick={handleSubmit}
          className="flex-1 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors text-sm font-medium"
        >
          Add Food
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-600 transition-colors text-sm font-medium"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
