import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Dumbbell, Apple, Activity, Moon, Calendar, Loader2, Plus, Trash2 } from 'lucide-react'
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
  const today = new Date().toISOString().split('T')[0]

  const { data: logs = [], isLoading, error } = useQuery({
    queryKey: ['fitness', 'food', today],
    queryFn: () => fitnessApi.getFoodLogs(today),
  })

  const deleteMutation = useMutation({
    mutationFn: fitnessApi.deleteFoodLog,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['fitness', 'food'] }),
  })

  if (isLoading) return <LoadingState message="Loading food log..." />
  if (error) return <ErrorState message="Failed to load food log" />

  const totalCalories = logs.reduce((sum, log) => sum + (log.calories || 0), 0)
  const totalProtein = logs.reduce((sum, log) => sum + (log.protein || 0), 0)

  const mealGroups = {
    breakfast: logs.filter(l => l.meal_type === 'breakfast'),
    lunch: logs.filter(l => l.meal_type === 'lunch'),
    dinner: logs.filter(l => l.meal_type === 'dinner'),
    snack: logs.filter(l => l.meal_type === 'snack'),
  }

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="flex gap-4 p-3 bg-canvas-surface rounded-lg">
        <div>
          <div className="text-xl font-bold text-white">{totalCalories}</div>
          <div className="text-xs text-canvas-muted">calories</div>
        </div>
        <div>
          <div className="text-xl font-bold text-white">{totalProtein.toFixed(0)}g</div>
          <div className="text-xs text-canvas-muted">protein</div>
        </div>
      </div>

      {/* Meals */}
      {Object.entries(mealGroups).map(([mealType, items]) => (
        <div key={mealType}>
          <h4 className="text-sm font-medium text-canvas-muted capitalize mb-2">{mealType}</h4>
          {items.length === 0 ? (
            <div className="text-sm text-canvas-muted/50 py-2">No items logged</div>
          ) : (
            <div className="space-y-1">
              {items.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center justify-between p-2 bg-canvas-surface rounded"
                >
                  <div>
                    <span className="text-white">{item.food_name}</span>
                    <span className="text-canvas-muted text-sm ml-2">
                      {item.servings}x
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-sm text-canvas-muted">{item.calories} cal</span>
                    <button
                      onClick={() => deleteMutation.mutate(item.id)}
                      className="p-1 text-red-400 hover:bg-canvas-elevated rounded"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
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
