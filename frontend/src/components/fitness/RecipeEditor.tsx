import React, { useState, useEffect } from 'react'
import { X, Plus, Save } from 'lucide-react'
import { APP_CONFIG } from '../../config'
import type { Recipe } from './RecipesSection'
import IngredientSearchInput, { IngredientRowValue } from './IngredientSearchInput'

interface RecipeEditorProps {
  recipe: Recipe | null
  onClose: () => void
  onSave: () => void
}

type IngredientRow = IngredientRowValue

export default function RecipeEditor({ recipe, onClose, onSave }: RecipeEditorProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('')
  const [ingredients, setIngredients] = useState<IngredientRow[]>([
    { name: '', quantity: '', unit: 'g' }
  ])
  const [instructions, setInstructions] = useState('')
  const [prepTime, setPrepTime] = useState('')
  const [servings, setServings] = useState('1')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const categories = ['breakfast', 'lunch', 'dinner', 'snack', 'dessert']
  const units = ['g', 'oz', 'lb', 'cup', 'tbsp', 'tsp', 'piece', 'whole']

  useEffect(() => {
    if (recipe) {
      setName(recipe.name)
      setDescription(recipe.description || '')
      setCategory(recipe.category || '')
      setIngredients(recipe.ingredients.map((ing: any) => ({
        name: ing.name,
        quantity: ing.quantity?.toString() ?? '',
        unit: ing.unit || 'g',
        calories: ing.calories?.toString() || '',
        protein: ing.protein?.toString() || '',
        carbs: ing.carbs?.toString() || '',
        fats: ing.fats?.toString() || '',
        food_id: ing.food_id || undefined,
        source: ing.source || undefined,
        serving_description: ing.serving_description || undefined,
        showNutrition: false
      })))
      setInstructions(recipe.instructions)
      setPrepTime(recipe.prep_time_minutes?.toString() || '')
      setServings(recipe.servings.toString())
    }
  }, [recipe])

  const handleAddIngredient = () => {
    setIngredients([...ingredients, { name: '', quantity: '', unit: 'g' }])
  }

  const handleRemoveIngredient = (index: number) => {
    if (ingredients.length > 1) {
      setIngredients(ingredients.filter((_, i) => i !== index))
    }
  }

  const handleRowChange = (index: number, next: IngredientRow) => {
    const updated = [...ingredients]
    updated[index] = next
    setIngredients(updated)
  }

  // Live running totals from resolved ingredients (per-recipe + per-serving).
  const resolvedRows = ingredients.filter(
    ing => ing.name.trim() && ing.calories !== undefined && ing.calories !== '',
  )
  const unresolvedCount = ingredients.filter(
    ing => ing.name.trim() && (ing.calories === undefined || ing.calories === ''),
  ).length
  const totals = resolvedRows.reduce(
    (acc, ing) => ({
      calories: acc.calories + (parseFloat(ing.calories || '0') || 0),
      protein: acc.protein + (parseFloat(ing.protein || '0') || 0),
      carbs: acc.carbs + (parseFloat(ing.carbs || '0') || 0),
      fats: acc.fats + (parseFloat(ing.fats || '0') || 0),
    }),
    { calories: 0, protein: 0, carbs: 0, fats: 0 },
  )
  const servingsNum = Math.max(1, parseInt(servings) || 1)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    // Validation
    if (!name.trim()) {
      setError('Recipe name is required')
      return
    }

    if (!instructions.trim()) {
      setError('Instructions are required')
      return
    }

    const validIngredients = ingredients.filter(ing => ing.name.trim() && ing.quantity.trim())
    if (validIngredients.length === 0) {
      setError('At least one ingredient is required')
      return
    }

    const parsedServings = parseInt(servings) || 1
    if (parsedServings < 1) {
      setError('Servings must be at least 1')
      return
    }

    setSaving(true)

    try {
      const payload = {
        name: name.trim(),
        description: description.trim() || undefined,
        category: category || undefined,
        ingredients: validIngredients.map(ing => ({
          name: ing.name.trim(),
          quantity: ing.quantity ? parseFloat(ing.quantity) : undefined,
          unit: ing.unit,
          // Per-ingredient macros (from a live FatSecret pick or manual entry).
          // Present values win server-side; unresolved rows are estimated on save.
          calories: ing.calories ? parseFloat(ing.calories) : undefined,
          protein: ing.protein ? parseFloat(ing.protein) : undefined,
          carbs: ing.carbs ? parseFloat(ing.carbs) : undefined,
          fats: ing.fats ? parseFloat(ing.fats) : undefined,
          food_id: ing.food_id,
          source: ing.source,
          serving_description: ing.serving_description,
        })),
        instructions: instructions.trim(),
        prep_time_minutes: prepTime ? parseInt(prepTime) : undefined,
        servings: parsedServings
      }

      const url = recipe
        ? `${APP_CONFIG.apiUrl}/api/fitness/recipes/${recipe.id}`
        : `${APP_CONFIG.apiUrl}/api/fitness/recipes`

      const response = await fetch(url, {
        method: recipe ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload)
      })

      if (response.ok) {
        onSave()
      } else {
        const errorData = await response.json()
        setError(errorData.detail || 'Failed to save recipe')
      }
    } catch (error) {
      console.error('Failed to save recipe:', error)
      setError('Failed to save recipe')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 rounded-lg max-w-4xl w-full max-h-[90vh] overflow-auto border border-gray-700">
        {/* Header */}
        <div className="sticky top-0 bg-gray-800 border-b border-gray-700 p-6 flex items-center justify-between z-10">
          <h2 className="text-2xl font-bold text-white">
            {recipe ? 'Edit Recipe' : 'New Recipe'}
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-700 rounded transition-colors"
          >
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-6">
          {/* Error Message */}
          {error && (
            <div className="p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-400 text-sm">
              {error}
            </div>
          )}

          {/* Basic Info */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Recipe Name *
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Grilled Chicken & Rice"
                className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-teal-500"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Category
              </label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white focus:outline-none focus:border-teal-500"
              >
                <option value="">Select category...</option>
                {categories.map(cat => (
                  <option key={cat} value={cat}>
                    {cat.charAt(0).toUpperCase() + cat.slice(1)}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Prep Time (minutes)
              </label>
              <input
                type="number"
                value={prepTime}
                onChange={(e) => setPrepTime(e.target.value)}
                placeholder="30"
                min="1"
                className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-teal-500"
              />
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of the recipe..."
                rows={2}
                className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-teal-500 resize-none"
              />
            </div>
          </div>

          {/* Ingredients */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <label className="text-sm font-medium text-gray-300">Ingredients *</label>
              <button
                type="button"
                onClick={handleAddIngredient}
                className="px-3 py-1 bg-teal-600 hover:bg-teal-700 text-white rounded text-sm flex items-center gap-1 transition-colors"
              >
                <Plus className="w-4 h-4" />
                Add Ingredient
              </button>
            </div>

            <div className="space-y-3">
              {ingredients.map((ing, idx) => (
                <IngredientSearchInput
                  key={idx}
                  value={ing}
                  onChange={(next) => handleRowChange(idx, next)}
                  onRemove={() => handleRemoveIngredient(idx)}
                  canRemove={ingredients.length > 1}
                  units={units}
                />
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-2">
              Search to pull accurate macros from FatSecret, or type a freeform line
              (e.g. “2 cups flour”) — unresolved ingredients are estimated on save.
            </p>

            {/* Live running totals */}
            {(resolvedRows.length > 0 || unresolvedCount > 0) && (
              <div className="mt-3 bg-teal-900/20 border border-teal-500/30 rounded-lg p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-teal-300">Running Totals</span>
                  {unresolvedCount > 0 && (
                    <span className="text-xs text-amber-300">
                      {unresolvedCount} unresolved ingredient{unresolvedCount === 1 ? '' : 's'} will be estimated on save
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-4 gap-2 text-center">
                  {[
                    { label: 'Calories', total: totals.calories, unit: '' },
                    { label: 'Protein', total: totals.protein, unit: 'g' },
                    { label: 'Carbs', total: totals.carbs, unit: 'g' },
                    { label: 'Fats', total: totals.fats, unit: 'g' },
                  ].map((m) => (
                    <div key={m.label}>
                      <div className="text-xs text-gray-400">{m.label}</div>
                      <div className="text-white font-bold">{Math.round(m.total)}{m.unit}</div>
                      <div className="text-[11px] text-gray-500">
                        {Math.round(m.total / servingsNum)}{m.unit}/serving
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Instructions */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Instructions *
            </label>
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="1. Preheat oven to 375°F...&#10;2. Season the chicken...&#10;3. Bake for 25 minutes..."
              rows={8}
              className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-teal-500 resize-none font-mono text-sm"
              required
            />
          </div>

          {/* Servings */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Servings *
            </label>
            <input
              type="number"
              value={servings}
              onChange={(e) => setServings(e.target.value)}
              min="1"
              className="w-32 px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white focus:outline-none focus:border-teal-500"
              required
            />
            <p className="text-xs text-gray-400 mt-1">
              Nutrition will be calculated per serving
            </p>
          </div>

          {/* Actions */}
          <div className="flex gap-3 pt-4 border-t border-gray-700">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex-1 px-4 py-2 bg-teal-600 hover:bg-teal-700 disabled:bg-gray-600 text-white rounded-lg font-medium transition-colors flex items-center justify-center gap-2"
            >
              <Save className="w-4 h-4" />
              {saving ? 'Saving...' : recipe ? 'Update Recipe' : 'Create Recipe'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
