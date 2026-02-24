import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Dumbbell, Apple, Activity, Moon, Calendar, Loader2, Plus, Trash2, ChevronLeft, ChevronRight, X } from 'lucide-react'
import { fitnessApi } from '../../services/api'
import type { FitnessWindowData } from '../../types'

interface FitnessContentProps {
  data: FitnessWindowData
  windowId: string
}

type Tab = 'dashboard' | 'food' | 'workout' | 'recovery' | 'programs'

export default function FitnessContent({ data }: FitnessContentProps) {
  const [activeTab, setActiveTab] = useState<Tab>(data.initialView || 'dashboard')

  const tabs: { id: Tab; label: string; icon: typeof Dumbbell }[] = [
    { id: 'dashboard', label: 'Dashboard', icon: Activity },
    { id: 'food', label: 'Food', icon: Apple },
    { id: 'workout', label: 'Workout', icon: Dumbbell },
    { id: 'recovery', label: 'Recovery', icon: Moon },
    { id: 'programs', label: 'Programs', icon: Calendar },
  ]

  return (
    <div className="flex flex-col h-full bg-canvas-bg">
      {/* Tabs */}
      <div className="flex overflow-x-auto border-b border-canvas-border">
        {tabs.map((tab) => {
          const Icon = tab.icon
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-shrink-0 px-4 py-3 flex items-center gap-2 text-sm font-medium transition-colors whitespace-nowrap ${
                activeTab === tab.id
                  ? 'text-white border-b-2 border-green-500 bg-canvas-surface/50'
                  : 'text-canvas-muted hover:text-white hover:bg-canvas-surface/30'
              }`}
            >
              <Icon size={16} />
              {tab.label}
            </button>
          )
        })}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-4">
        {activeTab === 'dashboard' && <DashboardTab />}
        {activeTab === 'food' && <FoodTab />}
        {activeTab === 'workout' && <WorkoutTab />}
        {activeTab === 'recovery' && <RecoveryTab />}
        {activeTab === 'programs' && <ProgramsTab />}
      </div>
    </div>
  )
}

function DashboardTab() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['fitness', 'dashboard'],
    queryFn: fitnessApi.getDashboard,
  })

  if (isLoading) return <LoadingState message="Loading dashboard..." />
  if (error) return <ErrorState message="Failed to load dashboard" />

  // Extract daily averages from the nested nutrition data structure
  const dailyAvg = data?.nutrition?.statistics?.daily_averages || {}
  const daysLogged = data?.nutrition?.statistics?.days_logged || 0

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-white">Weekly Summary</h3>

      <div className="grid grid-cols-2 gap-3">
        <StatCard
          icon={<Apple size={20} className="text-red-400" />}
          label="Avg Calories"
          value={Math.round(dailyAvg.calories || 0).toLocaleString()}
          subtitle="kcal/day"
        />
        <StatCard
          icon={<Dumbbell size={20} className="text-green-400" />}
          label="Avg Protein"
          value={Math.round(dailyAvg.protein || 0).toString()}
          subtitle="g/day"
        />
        <StatCard
          icon={<Activity size={20} className="text-blue-400" />}
          label="Days Logged"
          value={daysLogged.toString()}
          subtitle="this week"
        />
        <StatCard
          icon={<Moon size={20} className="text-purple-400" />}
          label="Avg Carbs"
          value={Math.round(dailyAvg.carbs || 0).toString()}
          subtitle="g/day"
        />
      </div>

      {data?.nutrition?.statistics?.totals && (
        <div className="p-4 bg-canvas-surface rounded-lg border border-canvas-border">
          <div className="text-lg font-bold text-white">Week Totals</div>
          <div className="grid grid-cols-3 gap-2 mt-2 text-sm">
            <div>
              <span className="text-canvas-muted">Calories:</span>{' '}
              <span className="text-white">{Math.round(data.nutrition.statistics.totals.calories).toLocaleString()}</span>
            </div>
            <div>
              <span className="text-canvas-muted">Protein:</span>{' '}
              <span className="text-white">{Math.round(data.nutrition.statistics.totals.protein)}g</span>
            </div>
            <div>
              <span className="text-canvas-muted">Entries:</span>{' '}
              <span className="text-white">{data.nutrition.statistics.total_entries}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function FoodTab() {
  const queryClient = useQueryClient()
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split('T')[0])
  const [addingMealType, setAddingMealType] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<any[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [selectedFoods, setSelectedFoods] = useState<{ name: string; quantity: number; unit: string; calories: number; protein: number; carbs: number; fats: number }[]>([])
  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null)

  const { data: logs = [], isLoading, error } = useQuery({
    queryKey: ['fitness', 'food', selectedDate],
    queryFn: () => fitnessApi.getFoodLogs(selectedDate),
  })

  const { data: recentFoods = [] } = useQuery({
    queryKey: ['fitness', 'recent-foods'],
    queryFn: () => fitnessApi.getRecentFoods(15),
    staleTime: 5 * 60 * 1000,
  })

  const deleteMutation = useMutation({
    mutationFn: fitnessApi.deleteFoodLog,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['fitness', 'food'] }),
  })

  const logMutation = useMutation({
    mutationFn: fitnessApi.logFood,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fitness', 'food'] })
      queryClient.invalidateQueries({ queryKey: ['fitness', 'recent-foods'] })
      queryClient.invalidateQueries({ queryKey: ['fitness', 'dashboard'] })
      setAddingMealType(null)
      setSelectedFoods([])
      setSearchQuery('')
      setSearchResults([])
    },
  })

  const navigateDate = (delta: number) => {
    const d = new Date(selectedDate)
    d.setDate(d.getDate() + delta)
    setSelectedDate(d.toISOString().split('T')[0])
  }

  const isToday = selectedDate === new Date().toISOString().split('T')[0]

  const handleSearch = (query: string) => {
    setSearchQuery(query)
    if (searchTimeout.current) clearTimeout(searchTimeout.current)
    if (!query.trim()) {
      setSearchResults([])
      return
    }
    searchTimeout.current = setTimeout(async () => {
      setIsSearching(true)
      try {
        const results = await fitnessApi.searchFoods(query)
        setSearchResults(results)
      } catch {
        setSearchResults([])
      }
      setIsSearching(false)
    }, 300)
  }

  const addFoodItem = (food: any) => {
    const defaultUnit = food.unit || food.serving_unit || 'serving'
    const defaultQuantityRaw = Number(food.quantity ?? food.serving_qty ?? food.serving_size ?? 1)
    const defaultQuantity = Number.isFinite(defaultQuantityRaw) && defaultQuantityRaw > 0 ? defaultQuantityRaw : 1
    setSelectedFoods(prev => [...prev, {
      name: food.name || food.food_name || food.description || 'Unknown',
      quantity: defaultQuantity,
      unit: defaultUnit,
      calories: food.calories || food.nf_calories || 0,
      protein: food.protein || food.nf_protein || 0,
      carbs: food.carbs || food.nf_total_carbohydrate || 0,
      fats: food.fats || food.fat || food.nf_total_fat || 0,
    }])
    setSearchQuery('')
    setSearchResults([])
  }

  const updateQuantity = (index: number, quantity: number) => {
    if (!Number.isFinite(quantity) || quantity <= 0) return
    setSelectedFoods(prev => prev.map((f, i) => i === index ? { ...f, quantity } : f))
  }

  const updateUnit = (index: number, unit: string) => {
    const nextUnit = unit.trim() || 'serving'
    setSelectedFoods(prev => prev.map((f, i) => i === index ? { ...f, unit: nextUnit } : f))
  }

  const removeSelectedFood = (index: number) => {
    setSelectedFoods(prev => prev.filter((_, i) => i !== index))
  }

  const handleSubmit = () => {
    if (!addingMealType || selectedFoods.length === 0) return
    const totalCals = selectedFoods.reduce((s, f) => s + f.calories * f.quantity, 0)
    const totalProtein = selectedFoods.reduce((s, f) => s + f.protein * f.quantity, 0)
    const totalCarbs = selectedFoods.reduce((s, f) => s + f.carbs * f.quantity, 0)
    const totalFats = selectedFoods.reduce((s, f) => s + f.fats * f.quantity, 0)

    logMutation.mutate({
      meal_type: addingMealType,
      food_items: selectedFoods.map(f => ({ name: f.name, quantity: f.quantity, unit: f.unit })),
      calories: Math.round(totalCals),
      protein: Math.round(totalProtein),
      carbs: Math.round(totalCarbs),
      fats: Math.round(totalFats),
      logged_at: selectedDate !== new Date().toISOString().split('T')[0] ? `${selectedDate}T12:00:00` : undefined,
    })
  }

  if (isLoading) return <LoadingState message="Loading food log..." />
  if (error) return <ErrorState message="Failed to load food log" />

  const totalCalories = logs.reduce((sum, log) => sum + (log.calories || 0), 0)
  const totalProtein = logs.reduce((sum, log) => sum + (log.protein || 0), 0)
  const totalCarbs = logs.reduce((sum, log) => sum + (log.carbs || 0), 0)
  const totalFat = logs.reduce((sum, log) => sum + (log.fat || 0), 0)

  const mealTypes = ['breakfast', 'lunch', 'dinner', 'snack'] as const
  const mealGroups = Object.fromEntries(mealTypes.map(m => [m, logs.filter(l => l.meal_type === m)]))

  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr + 'T00:00:00')
    return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
  }

  return (
    <div className="space-y-3">
      {/* Date Navigation */}
      <div className="flex items-center justify-between">
        <button onClick={() => navigateDate(-1)} className="p-1.5 hover:bg-canvas-surface rounded text-canvas-muted hover:text-white">
          <ChevronLeft size={18} />
        </button>
        <div className="flex items-center gap-2">
          <span className="text-white font-medium text-sm">{formatDate(selectedDate)}</span>
          {!isToday && (
            <button onClick={() => setSelectedDate(new Date().toISOString().split('T')[0])} className="text-xs px-2 py-0.5 bg-green-500/20 text-green-400 rounded hover:bg-green-500/30">
              Today
            </button>
          )}
        </div>
        <button onClick={() => navigateDate(1)} className="p-1.5 hover:bg-canvas-surface rounded text-canvas-muted hover:text-white">
          <ChevronRight size={18} />
        </button>
      </div>

      {/* Macro Summary */}
      <div className="grid grid-cols-4 gap-2">
        <div className="p-2 bg-canvas-surface rounded-lg text-center">
          <div className="text-lg font-bold text-white">{totalCalories}</div>
          <div className="text-[10px] text-canvas-muted">calories</div>
        </div>
        <div className="p-2 bg-canvas-surface rounded-lg text-center">
          <div className="text-lg font-bold text-blue-400">{totalProtein.toFixed(0)}g</div>
          <div className="text-[10px] text-canvas-muted">protein</div>
        </div>
        <div className="p-2 bg-canvas-surface rounded-lg text-center">
          <div className="text-lg font-bold text-yellow-400">{totalCarbs.toFixed(0)}g</div>
          <div className="text-[10px] text-canvas-muted">carbs</div>
        </div>
        <div className="p-2 bg-canvas-surface rounded-lg text-center">
          <div className="text-lg font-bold text-orange-400">{totalFat.toFixed(0)}g</div>
          <div className="text-[10px] text-canvas-muted">fat</div>
        </div>
      </div>

      {/* Meals */}
      {mealTypes.map((mealType) => {
        const items = mealGroups[mealType] || []
        const isAdding = addingMealType === mealType

        return (
          <div key={mealType}>
            <div className="flex items-center justify-between mb-1.5">
              <h4 className="text-sm font-medium text-canvas-muted capitalize">{mealType}</h4>
              <button
                onClick={() => {
                  setAddingMealType(isAdding ? null : mealType)
                  setSelectedFoods([])
                  setSearchQuery('')
                  setSearchResults([])
                }}
                className={`p-1 rounded transition-colors ${isAdding ? 'bg-red-500/20 text-red-400' : 'hover:bg-canvas-surface text-canvas-muted hover:text-green-400'}`}
              >
                {isAdding ? <X size={14} /> : <Plus size={14} />}
              </button>
            </div>

            {/* Inline Add Form */}
            {isAdding && (
              <div className="mb-2 p-3 bg-canvas-surface/80 rounded-lg border border-canvas-border space-y-2">
                {/* Search */}
                <div className="relative">
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => handleSearch(e.target.value)}
                    onKeyDown={(e) => e.stopPropagation()}
                    placeholder="Search foods..."
                    className="w-full px-3 py-2 bg-canvas-bg rounded border border-canvas-border text-white text-sm placeholder-canvas-muted focus:outline-none focus:border-green-500"
                    autoFocus
                  />
                  {isSearching && <Loader2 size={14} className="absolute right-3 top-2.5 animate-spin text-canvas-muted" />}

                  {/* Search Results Dropdown */}
                  {searchResults.length > 0 && (
                    <div className="absolute z-20 top-full left-0 right-0 mt-1 bg-canvas-surface border border-canvas-border rounded-lg shadow-xl max-h-48 overflow-y-auto custom-scrollbar">
                      {searchResults.slice(0, 10).map((food, i) => (
                        <button
                          key={i}
                          onClick={() => addFoodItem(food)}
                          className="w-full text-left px-3 py-2 hover:bg-canvas-elevated text-sm transition-colors"
                        >
                          <div className="text-white">{food.name || food.food_name || food.description}</div>
                          <div className="text-xs text-canvas-muted">
                            {food.calories || food.nf_calories || 0} cal
                            {' / '}
                            {food.protein || food.nf_protein || 0}g P
                            {' / '}
                            {food.serving_unit || food.unit || 'serving'}
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Recent Foods (show when search is empty) */}
                {!searchQuery && selectedFoods.length === 0 && recentFoods.length > 0 && (
                  <div>
                    <div className="text-xs text-canvas-muted mb-1">Recently logged</div>
                    <div className="flex flex-wrap gap-1">
                      {recentFoods.slice(0, 8).map((food: any, i: number) => (
                        <button
                          key={i}
                          onClick={() => addFoodItem(food)}
                          className="px-2 py-1 bg-canvas-bg rounded text-xs text-white hover:bg-canvas-elevated transition-colors"
                        >
                          {food.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Selected Foods */}
                {selectedFoods.length > 0 && (
                  <div className="space-y-1.5">
                    {selectedFoods.map((food, i) => (
                      <div key={i} className="flex items-center gap-2 p-2 bg-canvas-bg rounded">
                        <div className="flex-1 min-w-0">
                          <div className="text-sm text-white truncate">{food.name}</div>
                          <div className="text-xs text-canvas-muted">
                            {Math.round(food.calories * food.quantity)} cal / {Math.round(food.protein * food.quantity)}g P
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          <button onClick={() => updateQuantity(i, Math.max(0.25, Number((food.quantity - 0.25).toFixed(2))))} className="w-6 h-6 flex items-center justify-center bg-canvas-surface rounded text-white hover:bg-canvas-elevated">-</button>
                          <input
                            type="number"
                            min={0.25}
                            step={0.25}
                            value={food.quantity}
                            onChange={(e) => updateQuantity(i, Number(e.target.value))}
                            className="w-14 px-1 py-0.5 text-xs text-center bg-canvas-surface border border-canvas-border rounded text-white"
                          />
                          <button onClick={() => updateQuantity(i, Number((food.quantity + 0.25).toFixed(2)))} className="w-6 h-6 flex items-center justify-center bg-canvas-surface rounded text-white hover:bg-canvas-elevated">+</button>
                          <input
                            type="text"
                            value={food.unit}
                            onChange={(e) => updateUnit(i, e.target.value)}
                            placeholder="unit"
                            className="w-20 px-1.5 py-0.5 text-xs bg-canvas-surface border border-canvas-border rounded text-white"
                          />
                        </div>
                        <button onClick={() => removeSelectedFood(i)} className="p-1 text-red-400 hover:bg-canvas-surface rounded">
                          <X size={12} />
                        </button>
                      </div>
                    ))}

                    {/* Totals + Submit */}
                    <div className="flex items-center justify-between pt-2 border-t border-canvas-border">
                      <div className="text-xs text-canvas-muted">
                        {Math.round(selectedFoods.reduce((s, f) => s + f.calories * f.quantity, 0))} cal
                        {' / '}
                        {Math.round(selectedFoods.reduce((s, f) => s + f.protein * f.quantity, 0))}g P
                        {' / '}
                        {Math.round(selectedFoods.reduce((s, f) => s + f.carbs * f.quantity, 0))}g C
                        {' / '}
                        {Math.round(selectedFoods.reduce((s, f) => s + f.fats * f.quantity, 0))}g F
                      </div>
                      <button
                        onClick={handleSubmit}
                        disabled={logMutation.isPending}
                        className="px-3 py-1.5 bg-green-500 hover:bg-green-600 disabled:opacity-50 rounded text-sm text-white font-medium transition-colors"
                      >
                        {logMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : 'Log'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Existing items */}
            {items.length === 0 && !isAdding ? (
              <div className="text-sm text-canvas-muted/50 py-1">No items logged</div>
            ) : (
              <div className="space-y-1">
                {items.map((item) => (
                  <div key={item.id} className="flex items-center justify-between p-2 bg-canvas-surface rounded">
                    <div className="min-w-0 flex-1">
                      <span className="text-white text-sm">{item.food_name}</span>
                      <span className="text-canvas-muted text-xs ml-2">
                        {item.servings} {item.serving_unit || 'serving'}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <span className="text-xs text-canvas-muted">{item.calories} cal</span>
                      <span className="text-xs text-blue-400">{item.protein}g P</span>
                      <button
                        onClick={() => deleteMutation.mutate(item.id)}
                        className="p-1 text-red-400 hover:bg-canvas-elevated rounded"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function WorkoutTab() {
  const today = new Date().toISOString().split('T')[0]

  const { data: workouts = [], isLoading, error } = useQuery({
    queryKey: ['fitness', 'workouts', today],
    queryFn: () => fitnessApi.getWorkouts(today),
  })

  if (isLoading) return <LoadingState message="Loading workouts..." />
  if (error) return <ErrorState message="Failed to load workouts" />

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-white">Today's Workouts</h3>
      </div>

      {workouts.length === 0 ? (
        <div className="text-center text-canvas-muted py-8">
          <Dumbbell size={48} className="mx-auto mb-4 opacity-30" />
          <p>No workouts logged today</p>
        </div>
      ) : (
        <div className="space-y-3">
          {workouts.map((workout) => (
            <div
              key={workout.id}
              className="p-4 bg-canvas-surface rounded-lg border border-canvas-border"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="font-medium text-white capitalize">
                  {workout.workout_type}
                </span>
                <span className="text-sm text-canvas-muted">
                  {workout.duration_minutes} min
                </span>
              </div>
              {workout.notes && (
                <p className="text-sm text-canvas-muted">{workout.notes}</p>
              )}
              {workout.exercises && workout.exercises.length > 0 && (
                <div className="mt-2 pt-2 border-t border-canvas-border">
                  <span className="text-xs text-canvas-muted">
                    {workout.exercises.length} exercises
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function RecoveryTab() {
  const { data: logs = [], isLoading, error } = useQuery({
    queryKey: ['fitness', 'recovery'],
    queryFn: () => fitnessApi.getRecoveryLogs(7),
  })

  if (isLoading) return <LoadingState message="Loading recovery data..." />
  if (error) return <ErrorState message="Failed to load recovery data" />

  const latestLog = logs[0]

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-white">Recovery Metrics</h3>

      {latestLog ? (
        <>
          <div className="grid grid-cols-2 gap-3">
            <MetricCard label="Sleep" value={`${latestLog.sleep_hours}h`} color="purple" />
            <MetricCard label="Quality" value={`${latestLog.sleep_quality}/10`} color="blue" />
            <MetricCard label="Energy" value={`${latestLog.energy_level}/10`} color="green" />
            <MetricCard label="Soreness" value={`${latestLog.soreness_level}/10`} color="orange" />
          </div>

          {latestLog.notes && (
            <div className="p-3 bg-canvas-surface rounded-lg">
              <div className="text-sm text-canvas-muted">Notes</div>
              <div className="text-white mt-1">{latestLog.notes}</div>
            </div>
          )}

          <div className="text-xs text-canvas-muted">
            Last updated: {new Date(latestLog.logged_at).toLocaleString()}
          </div>
        </>
      ) : (
        <div className="text-center text-canvas-muted py-8">
          <Moon size={48} className="mx-auto mb-4 opacity-30" />
          <p>No recovery data logged</p>
        </div>
      )}
    </div>
  )
}

function ProgramsTab() {
  const { data: programs = [], isLoading, error } = useQuery({
    queryKey: ['fitness', 'programs'],
    queryFn: fitnessApi.getPrograms,
  })

  if (isLoading) return <LoadingState message="Loading programs..." />
  if (error) return <ErrorState message="Failed to load programs" />

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-white">Training Programs</h3>

      {programs.length === 0 ? (
        <div className="text-center text-canvas-muted py-8">
          <Calendar size={48} className="mx-auto mb-4 opacity-30" />
          <p>No programs created</p>
        </div>
      ) : (
        <div className="space-y-3">
          {programs.map((program: any) => (
            <div
              key={program.id}
              className="p-4 bg-canvas-surface rounded-lg border border-canvas-border"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="font-medium text-white">{program.name}</span>
                <span
                  className={`px-2 py-0.5 rounded text-xs ${
                    program.is_active
                      ? 'bg-green-500/20 text-green-400'
                      : 'bg-canvas-elevated text-canvas-muted'
                  }`}
                >
                  {program.is_active ? 'active' : 'inactive'}
                </span>
              </div>
              {program.notes && (
                <p className="text-sm text-canvas-muted">{program.notes}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function StatCard({
  icon,
  label,
  value,
  subtitle,
}: {
  icon: React.ReactNode
  label: string
  value: string
  subtitle: string
}) {
  return (
    <div className="p-4 bg-canvas-surface rounded-lg border border-canvas-border">
      <div className="flex items-center gap-2 mb-2">
        {icon}
        <span className="text-sm text-canvas-muted">{label}</span>
      </div>
      <div className="text-2xl font-bold text-white">{value}</div>
      <div className="text-xs text-canvas-muted">{subtitle}</div>
    </div>
  )
}

function MetricCard({ label, value, color }: { label: string; value: string; color: string }) {
  const colorClasses: Record<string, string> = {
    purple: 'text-purple-400',
    blue: 'text-blue-400',
    green: 'text-green-400',
    orange: 'text-orange-400',
  }

  return (
    <div className="p-3 bg-canvas-surface rounded-lg border border-canvas-border">
      <div className="text-sm text-canvas-muted">{label}</div>
      <div className={`text-xl font-bold ${colorClasses[color]}`}>{value}</div>
    </div>
  )
}

function LoadingState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-full text-canvas-muted">
      <Loader2 className="animate-spin mr-2" size={20} />
      {message}
    </div>
  )
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-full text-red-400">
      {message}
    </div>
  )
}
