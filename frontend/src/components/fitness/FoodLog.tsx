import React, { useState, useEffect } from 'react'
import { Plus, Calendar, Trash2, ChevronDown, ChevronRight } from 'lucide-react'
import { APP_CONFIG } from '../../config'
import AddMealForm from './AddMealForm'
import type { SelectedFoodItem } from './FoodItemSelector'

interface FoodItem {
  name: string
  quantity: number
  unit: string
}

interface FoodLogEntry {
  log_id: string
  meal_type: string
  food_items: FoodItem[] | string
  detailed_items?: SelectedFoodItem[]
  calories?: number
  protein?: number
  carbs?: number
  fats?: number
  notes?: string
  logged_at: string
}

interface TodayTarget {
  date: string
  is_training_day: boolean
  is_deload: boolean
  phase: { id: string; name: string; daily_steps_target?: number | null } | null
  target: {
    calories?: number | null
    protein?: number | null
    carbs?: number | null
    fat?: number | null
  } | null
}

export default function FoodLog() {
  const [showAddForm, setShowAddForm] = useState(false)
  const [entries, setEntries] = useState<FoodLogEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [editingEntry, setEditingEntry] = useState<FoodLogEntry | null>(null)
  const [expandedDays, setExpandedDays] = useState<Set<string>>(new Set())
  const [todayTarget, setTodayTarget] = useState<TodayTarget | null>(null)
  const [togglingTrainingDay, setTogglingTrainingDay] = useState(false)

  const toggleTrainingDay = async () => {
    setTogglingTrainingDay(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/toggle-training-day`, {
        method: 'POST',
        credentials: 'include'
      })
      if (response.ok) {
        // Re-fetch to get updated macros
        await fetchTodayTarget()
      }
    } catch (e) {
      console.error('Failed to toggle training day:', e)
    } finally {
      setTogglingTrainingDay(false)
    }
  }

  const toggleDay = (date: string) => {
    const newExpanded = new Set(expandedDays)
    if (newExpanded.has(date)) {
      newExpanded.delete(date)
    } else {
      newExpanded.add(date)
    }
    setExpandedDays(newExpanded)
  }

  // Load entries + today's target on component mount
  useEffect(() => {
    fetchEntries()
    fetchTodayTarget()
  }, [])

  const fetchTodayTarget = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/today-target`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setTodayTarget(data)
      }
    } catch (e) {
      console.warn('Failed to fetch today target:', e)
    }
  }

  const fetchEntries = async () => {
    try {
      setLoading(true)
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/food-log`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setEntries(data)
      }
    } catch (error) {
      console.error('Failed to fetch food log entries:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (logId: string) => {
    if (!confirm('Delete this food log entry?')) return

    try {
      setLoading(true)
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/food-log/${logId}`, {
        method: 'DELETE',
        credentials: 'include'
      })

      if (response.ok) {
        await fetchEntries()
      } else {
        alert('⚠️ Failed to delete entry')
      }
    } catch (error) {
      console.error('Failed to delete entry:', error)
      alert('❌ Error deleting entry')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-2xl font-bold">Food Log</h2>
          <p className="text-gray-400 text-sm mt-1">Track your meals and nutrition</p>
        </div>
        <button
          onClick={() => setShowAddForm(true)}
          className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg flex items-center gap-2 transition-colors"
        >
          <Plus className="w-4 h-4" />
          Log Meal
        </button>
      </div>

      {/* Today's target banner — pulled from active phase + cycling */}
      {todayTarget?.target && (
        <div className={`mb-6 rounded-lg p-4 border ${
          todayTarget.is_training_day
            ? 'bg-purple-900/20 border-purple-700/40'
            : 'bg-blue-900/20 border-blue-700/40'
        }`}>
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <div className="text-sm font-semibold text-gray-200 flex items-center gap-1">
                Today's target ·{' '}
                <button
                  onClick={toggleTrainingDay}
                  disabled={togglingTrainingDay}
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold transition-colors cursor-pointer disabled:opacity-50 ${
                    todayTarget.is_training_day
                      ? 'bg-purple-800/40 text-purple-300 hover:bg-purple-700/50 border border-purple-600/40'
                      : 'bg-blue-800/40 text-blue-300 hover:bg-blue-700/50 border border-blue-600/40'
                  }`}
                  title={todayTarget.is_training_day ? 'Click to switch to rest day' : 'Click to switch to training day'}
                >
                  {todayTarget.is_training_day ? 'TRAINING DAY' : 'REST DAY'}
                  <span className="text-[10px] opacity-60">↔</span>
                </button>
                {todayTarget.is_deload && (
                  <span className="ml-2 px-2 py-0.5 text-xs rounded bg-amber-600/20 text-amber-300">
                    DELOAD
                  </span>
                )}
              </div>
              {todayTarget.phase && (
                <div className="text-xs text-gray-500 mt-0.5">{todayTarget.phase.name}</div>
              )}
            </div>
            <div className="flex gap-4 text-sm">
              {todayTarget.target.calories != null && (
                <span className="text-gray-300">
                  <span className="font-semibold text-white">{todayTarget.target.calories}</span> kcal
                </span>
              )}
              {todayTarget.target.protein != null && (
                <span className="text-gray-300">
                  P: <span className="font-semibold text-white">{todayTarget.target.protein}g</span>
                </span>
              )}
              {todayTarget.target.carbs != null && (
                <span className="text-gray-300">
                  C: <span className="font-semibold text-white">{todayTarget.target.carbs}g</span>
                </span>
              )}
              {todayTarget.target.fat != null && (
                <span className="text-gray-300">
                  F: <span className="font-semibold text-white">{todayTarget.target.fat}g</span>
                </span>
              )}
              {todayTarget.phase?.daily_steps_target && (
                <span className="text-emerald-400">
                  {todayTarget.phase.daily_steps_target.toLocaleString()} steps
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Add Meal Form Modal */}
      {showAddForm && (
        <AddMealForm
          onClose={() => setShowAddForm(false)}
          onSuccess={fetchEntries}
        />
      )}

      {/* Entries List - Grouped by Day */}
      <div className="space-y-6">
        {entries.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            <Calendar className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>No meals logged yet</p>
            <p className="text-sm mt-1">Click "Log Meal" to get started</p>
          </div>
        ) : (
          (() => {
            // Group entries by date
            const groupedEntries: Record<string, FoodLogEntry[]> = {}
            entries.forEach(entry => {
              const date = new Date(entry.logged_at).toLocaleDateString('en-US', {
                weekday: 'long',
                year: 'numeric',
                month: 'long',
                day: 'numeric'
              })
              if (!groupedEntries[date]) {
                groupedEntries[date] = []
              }
              groupedEntries[date].push(entry)
            })

            // Calculate daily totals
            const dailyTotals: Record<string, { calories: number; protein: number; carbs: number; fats: number }> = {}
            Object.keys(groupedEntries).forEach(date => {
              dailyTotals[date] = groupedEntries[date].reduce((acc, entry) => ({
                calories: acc.calories + (entry.calories || 0),
                protein: acc.protein + (entry.protein || 0),
                carbs: acc.carbs + (entry.carbs || 0),
                fats: acc.fats + (entry.fats || 0)
              }), { calories: 0, protein: 0, carbs: 0, fats: 0 })
            })

            return Object.keys(groupedEntries).map(date => {
              const isExpanded = expandedDays.has(date)
              return (
              <div key={date} className="space-y-3">
                {/* Date Header with Daily Totals - Clickable */}
                <button
                  type="button"
                  onClick={() => toggleDay(date)}
                  className="w-full flex items-center justify-between bg-gray-800/50 rounded-lg p-3 border border-gray-700 hover:border-green-500/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    {isExpanded ? (
                      <ChevronDown className="w-5 h-5 text-gray-400" />
                    ) : (
                      <ChevronRight className="w-5 h-5 text-gray-400" />
                    )}
                    <h3 className="font-semibold text-lg">{date}</h3>
                  </div>
                  <div className="flex gap-4 text-sm">
                    <span className="text-gray-400">
                      Total: <span className="text-white font-semibold">{Math.round(dailyTotals[date].calories)}</span> cal
                    </span>
                    {dailyTotals[date].protein > 0 && (
                      <span className="text-gray-400">
                        P: <span className="text-white">{Math.round(dailyTotals[date].protein)}g</span>
                      </span>
                    )}
                    {dailyTotals[date].carbs > 0 && (
                      <span className="text-gray-400">
                        C: <span className="text-white">{Math.round(dailyTotals[date].carbs)}g</span>
                      </span>
                    )}
                    {dailyTotals[date].fats > 0 && (
                      <span className="text-gray-400">
                        F: <span className="text-white">{Math.round(dailyTotals[date].fats)}g</span>
                      </span>
                    )}
                  </div>
                </button>

                {/* Meals for this day - Collapsible */}
                {isExpanded && (
                <div className="space-y-2 pl-4">
                  {groupedEntries[date].map((entry) => (
            <div
              key={entry.log_id}
              onClick={() => setEditingEntry(entry)}
              className="bg-gray-800 rounded-lg p-4 border border-gray-700 hover:border-green-500/50 cursor-pointer transition-colors"
            >
              <div className="flex justify-between items-start mb-3">
                <div>
                  <h4 className="font-medium capitalize">{entry.meal_type}</h4>
                  <p className="text-sm text-gray-400">
                    {new Date(entry.logged_at).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  {entry.calories && (
                    <div className="text-right">
                      <div className="text-lg font-semibold">{entry.calories}</div>
                      <div className="text-xs text-gray-400">calories</div>
                    </div>
                  )}
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDelete(entry.log_id)
                    }}
                    className="p-2 text-red-400 hover:text-red-300 hover:bg-red-900/20 rounded transition-colors"
                    title="Delete entry"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* Food Items */}
              <div className="mb-3">
                {(() => {
                  // Handle both array and string formats
                  let foodItems = entry.food_items;
                  if (typeof foodItems === 'string') {
                    try {
                      foodItems = JSON.parse(foodItems);
                    } catch {
                      // If parsing fails, treat as single item description
                      const fallbackText = typeof foodItems === 'string' ? foodItems : 'Food item';
                      foodItems = [{ name: fallbackText, quantity: 1, unit: 'serving' }];
                    }
                  }

                  // Ensure it's an array
                  if (!Array.isArray(foodItems)) {
                    foodItems = [];
                  }

                  return foodItems.map((item, idx) => (
                    <div key={idx} className="text-sm text-gray-300">
                      • {item.quantity} {item.unit} {item.name}
                    </div>
                  ));
                })()}
              </div>

              {/* Macros */}
              {(entry.protein || entry.carbs || entry.fats) && (
                <div className="flex gap-4 text-sm">
                  {entry.protein && (
                    <span className="text-gray-400">
                      Protein: <span className="text-white">{entry.protein}g</span>
                    </span>
                  )}
                  {entry.carbs && (
                    <span className="text-gray-400">
                      Carbs: <span className="text-white">{entry.carbs}g</span>
                    </span>
                  )}
                  {entry.fats && (
                    <span className="text-gray-400">
                      Fats: <span className="text-white">{entry.fats}g</span>
                    </span>
                  )}
                </div>
              )}

              {entry.notes && (
                <div className="mt-2 text-sm text-gray-400 italic">{entry.notes}</div>
              )}
            </div>
                  ))}
                </div>
                )}
              </div>
              )
            })
          })()
        )}
      </div>

      {/* Edit Modal */}
      {editingEntry && (
        <AddMealForm
          onClose={() => setEditingEntry(null)}
          onSuccess={() => {
            fetchEntries()
            setEditingEntry(null)
          }}
          editEntry={{
            id: editingEntry.log_id,
            meal_type: editingEntry.meal_type,
            logged_at: editingEntry.logged_at,
            notes: editingEntry.notes,
            detailed_items: editingEntry.detailed_items
          }}
        />
      )}
    </div>
  )
}
