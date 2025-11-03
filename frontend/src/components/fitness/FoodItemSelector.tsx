import React, { useState, useEffect, useRef } from 'react'
import { Search, Plus, X } from 'lucide-react'
import apiClient from '../../api/client'

interface Food {
  id: string
  name: string
  brand?: string
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
}

interface SelectedFoodItem extends Food {
  quantity: number
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
  const [recentFoods, setRecentFoods] = useState<Food[]>([])
  const [recipes, setRecipes] = useState<any[]>([])
  const [selectedFoods, setSelectedFoods] = useState<SelectedFoodItem[]>(initialFoods)
  const [isSearching, setIsSearching] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const [showCustomForm, setShowCustomForm] = useState(false)
  const searchTimeout = useRef<NodeJS.Timeout>()
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Load recent foods and recipes on mount
  useEffect(() => {
    loadRecentFoods()
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
        const results = await apiClient.searchFoods(searchQuery, 10)
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
      const foods = await apiClient.getRecentFoods(5)
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

  function calculateNutrition(food: Food, quantity: number): SelectedFoodItem {
    const multiplier = quantity / food.serving_size
    return {
      ...food,
      quantity,
      calculated_calories: food.calories ? food.calories * multiplier : undefined,
      calculated_protein: food.protein ? food.protein * multiplier : undefined,
      calculated_carbs: food.carbs ? food.carbs * multiplier : undefined,
      calculated_fats: food.fats ? food.fats * multiplier : undefined,
    }
  }

  function addFood(food: Food) {
    const selectedFood = calculateNutrition(food, food.serving_size)
    setSelectedFoods([...selectedFoods, selectedFood])
    setSearchQuery('')
    setShowDropdown(false)
  }

  function addRecipe(recipe: any) {
    // Convert recipe ingredients to food items (divided by servings for single serving)
    const servings = recipe.servings || 1
    const ingredientFoods: SelectedFoodItem[] = recipe.ingredients.map((ingredient: any) => {
      // Divide quantities and nutrition by number of servings, round to 2 decimal places for precision
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
    updatedFoods[index] = calculateNutrition(food, quantity)
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
          <div className="absolute z-10 w-full mt-2 bg-gray-800 border border-gray-700 rounded-lg shadow-lg max-h-64 overflow-y-auto">
            {searchResults.map((food) => (
              <button
                type="button"
                key={food.id}
                onClick={() => addFood(food)}
                className="w-full px-4 py-3 text-left hover:bg-gray-700 transition-colors border-b border-gray-700 last:border-b-0"
              >
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <div className="font-medium text-white">{food.name}</div>
                      {food.source === 'usda' && (
                        <span className="px-1.5 py-0.5 bg-blue-900/50 border border-blue-700/50 text-blue-300 text-[10px] rounded uppercase font-medium">
                          USDA
                        </span>
                      )}
                      {food.is_custom && (
                        <span className="px-1.5 py-0.5 bg-purple-900/50 border border-purple-700/50 text-purple-300 text-[10px] rounded uppercase font-medium">
                          Custom
                        </span>
                      )}
                    </div>
                    {food.brand && <div className="text-sm text-gray-400">{food.brand}</div>}
                    <div className="text-xs text-gray-500 mt-1">
                      {food.serving_size} {food.serving_unit}
                      {food.calories && ` • ${Math.round(food.calories)} cal`}
                      {food.protein && ` • ${Math.round(food.protein)}g protein`}
                    </div>
                  </div>
                  <Plus className="w-5 h-5 text-purple-400 flex-shrink-0 ml-2" />
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Recent Foods */}
      {searchQuery.length === 0 && recentFoods.length > 0 && (
        <div>
          <div className="text-sm text-gray-400 mb-2">Recent foods:</div>
          <div className="flex flex-wrap gap-2">
            {recentFoods.map((food) => (
              <button
                type="button"
                key={food.id}
                onClick={() => addFood(food)}
                className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded-full text-sm text-white hover:bg-gray-700 transition-colors flex items-center gap-2"
              >
                {food.name}
                <Plus className="w-3 h-3" />
              </button>
            ))}
          </div>
        </div>
      )}

      {/* My Recipes */}
      {searchQuery.length === 0 && recipes.length > 0 && (
        <div>
          <div className="text-sm text-gray-400 mb-2">My Recipes:</div>
          <div className="flex flex-wrap gap-2">
            {recipes.map((recipe) => (
              <button
                type="button"
                key={recipe.id}
                onClick={() => addRecipe(recipe)}
                className="px-3 py-1.5 bg-purple-900/30 border border-purple-700/50 rounded-full text-sm text-purple-300 hover:bg-purple-800/40 transition-colors flex items-center gap-2"
                title={`${recipe.ingredients?.length || 0} ingredients`}
              >
                {recipe.name}
                <Plus className="w-3 h-3" />
              </button>
            ))}
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
                    {food.source === 'usda' && (
                      <span className="px-1.5 py-0.5 bg-blue-900/50 border border-blue-700/50 text-blue-300 text-[10px] rounded uppercase font-medium">
                        USDA
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
                <span className="text-sm text-gray-400">{food.serving_unit}</span>
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
