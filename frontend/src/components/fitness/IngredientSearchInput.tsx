import React, { useState, useEffect, useRef } from 'react'
import { Search, Trash2, ChevronDown, ChevronRight, Check } from 'lucide-react'
import apiClient from '../../api/client'

/**
 * IngredientSearchInput — a single ingredient row with live FatSecret lookup.
 *
 * Ports the typeahead + serving-selection pattern from FoodItemSelector into an
 * inline row so recipe macros are accurate (resolved against FatSecret) rather
 * than guessed by the old hardcoded table. Free-text is still allowed: an
 * unresolved row is sent with no macros and the backend estimates it on save.
 */

export interface FoodServing {
  serving_id: string
  serving_description: string
  calories: number
  protein: number
  carbs: number
  fat: number
}

export interface IngredientRowValue {
  name: string
  quantity: string
  unit: string
  // Per-ingredient-total macros (from a live pick or manual entry)
  calories?: string
  protein?: string
  carbs?: string
  fats?: string
  // Provenance (R1)
  food_id?: string
  source?: 'fatsecret' | 'user' | 'manual'
  serving_description?: string
  // Client-only: available servings for re-pick, and UI toggles
  servings?: FoodServing[]
  selected_serving_id?: string
  showNutrition?: boolean
}

interface FoodResult {
  id: string
  name: string
  brand?: string
  source?: string
  food_type?: string
  calories?: number
  protein?: number
  serving_unit?: string
}

interface Props {
  value: IngredientRowValue
  onChange: (next: IngredientRowValue) => void
  onRemove: () => void
  canRemove: boolean
  units: string[]
}

function round1(n: number): number {
  return Math.round(n * 10) / 10
}

/** Scale a serving's macros by a quantity multiplier and write them onto a row. */
function applyServing(
  row: IngredientRowValue,
  serving: FoodServing,
  quantity: number,
): IngredientRowValue {
  const q = quantity || 0
  return {
    ...row,
    quantity: String(quantity),
    unit: serving.serving_description,
    serving_description: serving.serving_description,
    selected_serving_id: serving.serving_id,
    calories: String(round1((serving.calories || 0) * q)),
    protein: String(round1((serving.protein || 0) * q)),
    carbs: String(round1((serving.carbs || 0) * q)),
    fats: String(round1((serving.fat || 0) * q)),
  }
}

export default function IngredientSearchInput({ value, onChange, onRemove, canRemove, units }: Props) {
  const [results, setResults] = useState<FoodResult[]>([])
  const [searching, setSearching] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const [loadingId, setLoadingId] = useState<string | null>(null)
  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)

  const isResolved = value.source === 'fatsecret' && !!value.food_id

  // Close dropdown on outside click
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  // Debounced search on the name field (only while unresolved / typing)
  useEffect(() => {
    if (searchTimeout.current) clearTimeout(searchTimeout.current)
    if (isResolved) {
      setResults([])
      setShowDropdown(false)
      return
    }
    if ((value.name || '').trim().length < 2) {
      setResults([])
      setShowDropdown(false)
      return
    }
    setSearching(true)
    searchTimeout.current = setTimeout(async () => {
      try {
        const found = await apiClient.searchFoods(value.name.trim(), 12)
        setResults(found)
        setShowDropdown(true)
      } catch (err) {
        console.error('Ingredient search failed:', err)
      } finally {
        setSearching(false)
      }
    }, 300)
    return () => {
      if (searchTimeout.current) clearTimeout(searchTimeout.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.name, isResolved])

  const handleNameChange = (name: string) => {
    // Typing over a resolved ingredient turns it back into free text
    onChange({
      ...value,
      name,
      source: undefined,
      food_id: undefined,
      servings: undefined,
      selected_serving_id: undefined,
      serving_description: undefined,
      calories: undefined,
      protein: undefined,
      carbs: undefined,
      fats: undefined,
    })
  }

  const selectFood = async (food: FoodResult) => {
    setLoadingId(food.id)
    try {
      let servings: FoodServing[] = []
      if (food.source === 'fatsecret' && food.id.startsWith('fs-')) {
        const details = await apiClient.getFoodDetails(food.id)
        servings = details.servings || []
      }
      const serving = servings[0]
      const base: IngredientRowValue = {
        ...value,
        name: food.name,
        food_id: food.id,
        source: 'fatsecret',
        servings,
      }
      if (serving) {
        onChange(applyServing(base, serving, 1))
      } else {
        // No serving detail available — keep as resolved name, macros left for
        // the server to estimate (rare fallback).
        onChange({ ...base, source: 'fatsecret', quantity: value.quantity || '1' })
      }
    } catch (err) {
      console.error('Failed to load food details:', err)
      onChange({ ...value, name: food.name })
    } finally {
      setLoadingId(null)
      setShowDropdown(false)
    }
  }

  const changeQuantity = (qtyStr: string) => {
    const qty = parseFloat(qtyStr)
    if (isResolved && value.servings && value.selected_serving_id) {
      const serving = value.servings.find(s => s.serving_id === value.selected_serving_id)
      if (serving && !Number.isNaN(qty)) {
        onChange(applyServing(value, serving, qty))
        return
      }
    }
    onChange({ ...value, quantity: qtyStr })
  }

  const changeServing = (servingId: string) => {
    const serving = value.servings?.find(s => s.serving_id === servingId)
    if (serving) {
      onChange(applyServing(value, serving, parseFloat(value.quantity) || 1))
    }
  }

  const toggleManual = () => onChange({ ...value, showNutrition: !value.showNutrition })

  const setManual = (field: 'calories' | 'protein' | 'carbs' | 'fats', v: string) => {
    onChange({ ...value, [field]: v, source: value.source === 'fatsecret' ? 'manual' : (value.source || 'manual') })
  }

  return (
    <div className="border border-gray-600 rounded-lg p-3 bg-gray-750">
      <div className="flex gap-2">
        {/* Name typeahead */}
        <div className="relative flex-1" ref={boxRef}>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
            <input
              type="text"
              value={value.name}
              onChange={(e) => handleNameChange(e.target.value)}
              onFocus={() => { if (results.length > 0 && !isResolved) setShowDropdown(true) }}
              placeholder="Search or type an ingredient…"
              className="w-full pl-8 pr-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-teal-500"
            />
            {searching && (
              <div className="absolute right-2.5 top-1/2 -translate-y-1/2">
                <div className="animate-spin w-4 h-4 border-2 border-teal-500 border-t-transparent rounded-full" />
              </div>
            )}
          </div>

          {showDropdown && results.length > 0 && (
            <div className="absolute z-20 w-full mt-1 bg-gray-800 border border-gray-700 rounded-lg shadow-lg max-h-72 overflow-y-auto">
              {results.map((food) => (
                <button
                  type="button"
                  key={food.id}
                  onClick={() => selectFood(food)}
                  disabled={loadingId === food.id}
                  className="w-full px-3 py-2 text-left hover:bg-gray-700 transition-colors border-b border-gray-700 last:border-b-0 disabled:opacity-50"
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-white text-sm">{food.name}</span>
                    {food.source === 'fatsecret' && (
                      <span className="px-1.5 py-0.5 bg-green-900/50 border border-green-700/50 text-green-300 text-[10px] rounded uppercase font-medium">
                        FatSecret
                      </span>
                    )}
                    {food.food_type === 'Brand' && (
                      <span className="px-1.5 py-0.5 bg-blue-900/50 border border-blue-700/50 text-blue-300 text-[10px] rounded uppercase font-medium">
                        Brand
                      </span>
                    )}
                  </div>
                  {food.brand && <div className="text-xs text-gray-400">{food.brand}</div>}
                  <div className="text-xs text-gray-500">
                    {food.serving_unit}
                    {food.calories ? ` | ${Math.round(food.calories)} cal` : ''}
                    {food.protein ? ` | ${Math.round(food.protein)}g protein` : ''}
                  </div>
                </button>
              ))}
              <div className="px-3 py-1.5 text-center border-t border-gray-700 bg-gray-900/50">
                <span className="text-[10px] text-gray-500">Powered by FatSecret</span>
              </div>
            </div>
          )}
        </div>

        {/* Quantity */}
        <input
          type="number"
          value={value.quantity}
          onChange={(e) => changeQuantity(e.target.value)}
          placeholder="Qty"
          step="0.01"
          min="0"
          className="w-20 px-2 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-teal-500"
        />

        {/* Serving picker (resolved) or unit select (free-text) */}
        {isResolved && value.servings && value.servings.length > 0 ? (
          <select
            value={value.selected_serving_id || value.servings[0]?.serving_id}
            onChange={(e) => changeServing(e.target.value)}
            className="w-40 px-2 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white text-sm focus:outline-none focus:border-teal-500"
          >
            {value.servings.map((s) => (
              <option key={s.serving_id} value={s.serving_id}>
                {s.serving_description} ({Math.round(s.calories)} cal)
              </option>
            ))}
          </select>
        ) : (
          <select
            value={value.unit}
            onChange={(e) => onChange({ ...value, unit: e.target.value })}
            className="w-24 px-2 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white focus:outline-none focus:border-teal-500"
          >
            {units.map((unit) => (
              <option key={unit} value={unit}>{unit}</option>
            ))}
          </select>
        )}

        <button
          type="button"
          onClick={toggleManual}
          className="px-3 py-2 bg-gray-600 hover:bg-gray-500 text-white rounded transition-colors"
          title="Toggle manual nutrition"
        >
          {value.showNutrition ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </button>
        <button
          type="button"
          onClick={onRemove}
          disabled={!canRemove}
          className="px-3 py-2 bg-red-600 hover:bg-red-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white rounded transition-colors"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {/* Resolved macro summary + source badge */}
      {(isResolved || value.calories) && (
        <div className="mt-2 flex items-center gap-2 flex-wrap text-xs">
          {value.source === 'fatsecret' && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-green-900/40 border border-green-700/50 text-green-300 rounded">
              <Check className="w-3 h-3" /> FatSecret
            </span>
          )}
          {value.source === 'manual' && (
            <span className="px-1.5 py-0.5 bg-amber-900/40 border border-amber-700/50 text-amber-300 rounded">manual</span>
          )}
          {value.calories !== undefined && value.calories !== '' && (
            <span className="text-gray-300">
              {Math.round(parseFloat(value.calories) || 0)} cal · {round1(parseFloat(value.protein || '0'))}p ·{' '}
              {round1(parseFloat(value.carbs || '0'))}c · {round1(parseFloat(value.fats || '0'))}f
            </span>
          )}
        </div>
      )}

      {/* Collapsible manual nutrition */}
      {value.showNutrition && (
        <div className="mt-3 pt-3 border-t border-gray-600 grid grid-cols-2 md:grid-cols-4 gap-2">
          {(['calories', 'protein', 'carbs', 'fats'] as const).map((field) => (
            <div key={field}>
              <label className="block text-xs text-gray-400 mb-1 capitalize">
                {field === 'calories' ? 'Calories' : `${field} (g)`}
              </label>
              <input
                type="number"
                value={value[field] || ''}
                onChange={(e) => setManual(field, e.target.value)}
                placeholder="Optional"
                step="0.1"
                min="0"
                className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white text-sm placeholder-gray-500 focus:outline-none focus:border-teal-500"
              />
            </div>
          ))}
          <div className="col-span-2 md:col-span-4">
            <p className="text-xs text-gray-500 italic">
              Leave blank to resolve against FatSecret on save. Enter values to override with exact nutrition.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
