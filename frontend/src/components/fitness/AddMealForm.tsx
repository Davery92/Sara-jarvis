import React, { useState } from 'react'
import { X } from 'lucide-react'
import FoodItemSelector from './FoodItemSelector'
import type { SelectedFoodItem } from './FoodItemSelector'
import apiClient from '../../api/client'

interface AddMealFormProps {
  onClose: () => void
  onSuccess: () => void
  editEntry?: {
    id: string
    meal_type: string
    logged_at: string
    notes?: string
    detailed_items?: SelectedFoodItem[]
  }
}

// Format date as local datetime string for datetime-local input (YYYY-MM-DDTHH:mm)
function formatLocalDateTime(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${year}-${month}-${day}T${hours}:${minutes}`
}

export default function AddMealForm({ onClose, onSuccess, editEntry }: AddMealFormProps) {
  const [mealType, setMealType] = useState(editEntry?.meal_type || 'breakfast')
  const [loggedAt, setLoggedAt] = useState(
    editEntry?.logged_at
      ? formatLocalDateTime(new Date(editEntry.logged_at))
      : formatLocalDateTime(new Date())
  )
  const [notes, setNotes] = useState(editEntry?.notes || '')
  const [selectedFoods, setSelectedFoods] = useState<SelectedFoodItem[]>(editEntry?.detailed_items || [])
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Calculate totals from selected foods
  const totals = selectedFoods.reduce(
    (acc, food) => ({
      calories: acc.calories + (food.calculated_calories || 0),
      protein: acc.protein + (food.calculated_protein || 0),
      carbs: acc.carbs + (food.calculated_carbs || 0),
      fats: acc.fats + (food.calculated_fats || 0),
    }),
    { calories: 0, protein: 0, carbs: 0, fats: 0 }
  )

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()

    if (selectedFoods.length === 0) {
      alert('Please add at least one food item')
      return
    }

    setIsSubmitting(true)
    try {
      const payload = {
        meal_type: mealType,
        logged_at: loggedAt,
        calories: Math.round(totals.calories),
        protein: Math.round(totals.protein),
        carbs: Math.round(totals.carbs),
        fats: Math.round(totals.fats),
        notes: notes || undefined,
        food_items: selectedFoods.map((food) => ({
          name: food.name,
          quantity: food.quantity,
          unit: food.serving_unit,
        })),
        detailed_items: selectedFoods,
      }

      if (editEntry) {
        await apiClient.updateFoodLog(editEntry.id, payload)
      } else {
        await apiClient.logFood(payload)
      }

      onSuccess()
      onClose()
    } catch (error: any) {
      console.error('Failed to save meal:', error)
      const errorMessage = error?.response?.data?.detail || error?.message || 'Unknown error'
      alert(`Failed to save meal: ${typeof errorMessage === 'object' ? JSON.stringify(errorMessage) : errorMessage}`)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex justify-between items-center p-6 border-b border-gray-700">
          <h2 className="text-xl font-bold text-white">
            {editEntry ? 'Edit Meal' : 'Add Meal'}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-6">
          {/* Meal Type */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Meal Type
            </label>
            <select
              value={mealType}
              onChange={(e) => setMealType(e.target.value)}
              className="w-full px-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
            >
              <option value="breakfast">Breakfast</option>
              <option value="lunch">Lunch</option>
              <option value="dinner">Dinner</option>
              <option value="snack">Snack</option>
            </select>
          </div>

          {/* Date/Time */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Date & Time
            </label>
            <input
              type="datetime-local"
              value={loggedAt}
              onChange={(e) => setLoggedAt(e.target.value)}
              className="w-full px-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>

          {/* Food Items */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Food Items
            </label>
            <FoodItemSelector
              onFoodsSelected={setSelectedFoods}
              initialFoods={selectedFoods}
            />
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Notes (Optional)
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="Additional notes about this meal..."
              className="w-full px-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>

          {/* Summary */}
          {selectedFoods.length > 0 && (
            <div className="bg-purple-900/20 border border-purple-500/30 rounded-lg p-4">
              <div className="text-sm font-medium text-purple-300 mb-3">
                Meal Summary
              </div>
              <div className="space-y-2">
                <div className="grid grid-cols-4 gap-4 text-center">
                  <div>
                    <div className="text-2xl font-bold text-white">
                      {Math.round(totals.calories)}
                    </div>
                    <div className="text-xs text-gray-400">Calories</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-white">
                      {Math.round(totals.protein)}g
                    </div>
                    <div className="text-xs text-gray-400">Protein</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-white">
                      {Math.round(totals.carbs)}g
                    </div>
                    <div className="text-xs text-gray-400">Carbs</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-white">
                      {Math.round(totals.fats)}g
                    </div>
                    <div className="text-xs text-gray-400">Fats</div>
                  </div>
                </div>
                <div className="text-xs text-gray-400 text-center pt-2">
                  {selectedFoods.length} food item{selectedFoods.length !== 1 ? 's' : ''}
                </div>
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3 pt-4">
            <button
              type="submit"
              disabled={isSubmitting || selectedFoods.length === 0}
              className="flex-1 px-6 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSubmitting ? 'Saving...' : editEntry ? 'Update Meal' : 'Add Meal'}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="px-6 py-3 bg-gray-700 text-white rounded-lg hover:bg-gray-600 transition-colors font-medium"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
