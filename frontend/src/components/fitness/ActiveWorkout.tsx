import React, { useState, useEffect } from 'react'
import { X, Check, PlayCircle, ChevronLeft, ChevronRight, Trophy, Timer, TrendingUp } from 'lucide-react'
import { APP_CONFIG } from '../../config'
import { formatSleepHours } from '../../utils/formatters'

interface Exercise {
  name: string
  sets: number
  sets_original?: number          // pre-deload set count, when deload is active
  reps: string
  rpe_target?: number
  rest_seconds?: number
  notes?: string
  // Advanced execution markers
  metric_type?: 'reps' | 'time_seconds'
  is_per_side?: boolean
  superset_group?: string | null
  set_technique?: 'drop_set' | 'rest_pause' | 'amrap' | 'myo_reps' | null
  weight_suggestion?: {
    suggested_weight: number | null
    confidence: string
    reasoning: string
    ask_user: boolean
    history_data?: {
      previous_avg: number | null
      last_rpe: number | null
      trend: string
    }
  }
}

interface PhaseNutrition {
  calories_target?: number | null
  protein_target?: number | null
  carbs_target?: number | null
  fat_target?: number | null
  calories_training_day?: number | null
  calories_rest_day?: number | null
  carbs_training_day?: number | null
  carbs_rest_day?: number | null
  fat_training_day?: number | null
  fat_rest_day?: number | null
  daily_steps_target?: number | null
}

const SET_TECHNIQUE_LABEL: Record<string, string> = {
  drop_set: 'Drop set on last',
  rest_pause: 'Rest-pause on last',
  amrap: 'AMRAP on last',
  myo_reps: 'Myo-reps on last',
}

interface LoggedSet {
  id: string
  exercise_id: string
  set_index: number
  weight?: number
  reps?: number
  rpe?: number
  notes?: string
  logged_at: string
}

interface WorkoutSession {
  id: string
  template_id: string
  template_name: string
  session_date: string
  status: string
  started_at?: string
  exercises: Exercise[]
  logged_sets: LoggedSet[]
  is_deload?: boolean
  week_of_phase?: number | null
  deload_week?: number | null
  phase_name?: string | null
  phase_nutrition?: PhaseNutrition | null
  recovery_data?: {
    hrv?: number
    heart_rate?: number
    sleep_hours?: number
    soreness_level?: number
  }
}

interface ActiveWorkoutProps {
  sessionId: string
  onClose: () => void
}

export default function ActiveWorkout({ sessionId, onClose }: ActiveWorkoutProps) {
  const [session, setSession] = useState<WorkoutSession | null>(null)
  const [currentExerciseIndex, setCurrentExerciseIndex] = useState(0)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  // Set logging form state
  const [weight, setWeight] = useState('')
  const [reps, setReps] = useState('')
  const [rpe, setRpe] = useState('')
  const [setNotes, setSetNotes] = useState('')

  useEffect(() => {
    fetchSession()
  }, [sessionId])

  const fetchSession = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/sessions/${sessionId}`, {
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        setSession(data)
      }
    } catch (error) {
      console.error('Failed to fetch workout session:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleStartSession = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/sessions/${sessionId}/start`, {
        method: 'POST',
        credentials: 'include',
      })
      if (response.ok) {
        fetchSession()
      }
    } catch (error) {
      console.error('Failed to start session:', error)
    }
  }

  const handleLogSet = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!session || !session.exercises[currentExerciseIndex]) return

    setSubmitting(true)
    try {
      const currentExercise = session.exercises[currentExerciseIndex]
      const currentSets = session.logged_sets.filter(
        (set) => set.exercise_id === currentExercise.name
      )
      const setNumber = currentSets.length + 1

      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/sessions/${sessionId}/log-set`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          exercise_name: currentExercise.name,
          set_number: setNumber,
          weight: weight ? parseFloat(weight) : null,
          reps: reps ? parseInt(reps) : null,
          rpe: rpe ? parseInt(rpe) : null,
          notes: setNotes.trim() || ''
        })
      })

      if (response.ok) {
        // Clear form
        setWeight('')
        setReps('')
        setRpe('')
        setSetNotes('')

        // Refresh session
        await fetchSession()
      }
    } catch (error) {
      console.error('Failed to log set:', error)
    } finally {
      setSubmitting(false)
    }
  }

  const handleCompleteSession = async () => {
    if (!confirm('Complete this workout session?')) return

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/sessions/${sessionId}/complete`, {
        method: 'POST',
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        alert(
          `✅ Workout Completed!\n\n` +
          `Exercises: ${data.summary.exercises_completed}\n` +
          `Total Sets: ${data.summary.total_sets}\n` +
          `Total Volume: ${Math.round(data.summary.total_volume || 0)} lbs`
        )
        onClose()
      }
    } catch (error) {
      console.error('Failed to complete session:', error)
    }
  }

  if (loading) {
    return (
      <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
        <div className="text-white text-lg">Loading workout session...</div>
      </div>
    )
  }

  if (!session) {
    return (
      <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
        <div className="bg-gray-800 rounded-lg p-6 text-white">
          <p>Workout session not found</p>
          <button onClick={onClose} className="mt-4 px-4 py-2 bg-gray-700 rounded-lg">
            Close
          </button>
        </div>
      </div>
    )
  }

  const currentExercise = session.exercises[currentExerciseIndex]
  const completedSetsForExercise = session.logged_sets.filter(
    (set) => set.exercise_id === currentExercise?.name
  )
  const totalSetsLogged = session.logged_sets.length
  const totalSetsTarget = session.exercises.reduce((sum, ex) => sum + ex.sets, 0)
  const isWorkoutStarted = session.status === 'in_progress'

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 rounded-lg max-w-4xl w-full max-h-[95vh] overflow-auto border border-gray-700">
        {/* Header */}
        <div className="sticky top-0 bg-gray-800 border-b border-gray-700 p-6 z-10">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-2xl font-bold text-white flex items-center gap-2">
                🏋️ {session.template_name}
              </h2>
              <p className="text-sm text-gray-400 mt-1">
                {new Date(session.session_date).toLocaleDateString()} • {session.status}
              </p>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-gray-700 rounded-lg transition-colors"
            >
              <X className="w-6 h-6 text-gray-400" />
            </button>
          </div>

          {/* Progress Bar */}
          <div className="mb-4">
            <div className="flex justify-between text-sm text-gray-400 mb-2">
              <span>Progress</span>
              <span>{totalSetsLogged} / {totalSetsTarget} sets</span>
            </div>
            <div className="w-full h-2 bg-gray-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-purple-600 transition-all duration-300"
                style={{ width: `${(totalSetsLogged / totalSetsTarget) * 100}%` }}
              />
            </div>
          </div>

          {/* Deload banner */}
          {session.is_deload && (
            <div className="mb-3 px-4 py-3 rounded-lg bg-amber-900/40 border border-amber-600/60 text-amber-200 text-sm font-medium">
              ⚠ DELOAD WEEK · {session.phase_name} · week {session.week_of_phase} of phase
              <div className="text-xs text-amber-300/80 mt-1 font-normal">
                Working weights cut to 60%, sets halved. Recover, don't grind.
              </div>
            </div>
          )}

          {/* Recovery Badge + nutrition targets */}
          <div className="flex gap-2 text-xs flex-wrap">
            {session.recovery_data?.soreness_level && (
              <div className={`px-2 py-1 rounded ${
                session.recovery_data.soreness_level <= 3 ? 'bg-green-600/20 text-green-400' :
                session.recovery_data.soreness_level <= 6 ? 'bg-yellow-600/20 text-yellow-400' :
                'bg-red-600/20 text-red-400'
              }`}>
                Soreness: {session.recovery_data.soreness_level}/10
              </div>
            )}
            {session.recovery_data?.sleep_hours && (
              <div className="px-2 py-1 rounded bg-blue-600/20 text-blue-400">
                Sleep: {formatSleepHours(session.recovery_data.sleep_hours)}
              </div>
            )}
            {/* Today is a training day — show training-day macros if cycling is configured */}
            {session.phase_nutrition?.calories_training_day && (
              <div className="px-2 py-1 rounded bg-purple-600/20 text-purple-300">
                Training-day target: {session.phase_nutrition.calories_training_day} kcal
                {session.phase_nutrition.carbs_training_day != null && (
                  <span> · {session.phase_nutrition.carbs_training_day}C</span>
                )}
                {session.phase_nutrition.fat_training_day != null && (
                  <span> · {session.phase_nutrition.fat_training_day}F</span>
                )}
                {session.phase_nutrition.protein_target != null && (
                  <span> · {session.phase_nutrition.protein_target}P</span>
                )}
              </div>
            )}
            {session.phase_nutrition?.daily_steps_target && (
              <div className="px-2 py-1 rounded bg-emerald-600/20 text-emerald-300">
                Steps target: {session.phase_nutrition.daily_steps_target.toLocaleString()}
              </div>
            )}
          </div>

          {/* Start Button */}
          {!isWorkoutStarted && (
            <button
              onClick={handleStartSession}
              className="mt-4 w-full px-4 py-3 bg-purple-600 hover:bg-purple-700 text-white rounded-lg font-medium flex items-center justify-center gap-2 transition-colors"
            >
              <PlayCircle className="w-5 h-5" />
              Start Workout
            </button>
          )}
        </div>

        {/* Main Content */}
        <div className="p-6">
          {!isWorkoutStarted ? (
            <div className="text-center py-12 text-gray-400">
              <p className="text-lg">Click "Start Workout" to begin tracking</p>
            </div>
          ) : (
            <>
              {/* Exercise Navigation */}
              {session.exercises.length > 1 && (
                <div className="flex items-center justify-between mb-6 bg-gray-900 p-4 rounded-lg">
                  <button
                    onClick={() => setCurrentExerciseIndex(Math.max(0, currentExerciseIndex - 1))}
                    disabled={currentExerciseIndex === 0}
                    className="p-2 hover:bg-gray-700 rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    <ChevronLeft className="w-5 h-5" />
                  </button>
                  <div className="text-center">
                    <p className="text-sm text-gray-400">Exercise {currentExerciseIndex + 1} of {session.exercises.length}</p>
                    <p className="text-lg font-semibold text-white">{currentExercise.name}</p>
                  </div>
                  <button
                    onClick={() => setCurrentExerciseIndex(Math.min(session.exercises.length - 1, currentExerciseIndex + 1))}
                    disabled={currentExerciseIndex === session.exercises.length - 1}
                    className="p-2 hover:bg-gray-700 rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    <ChevronRight className="w-5 h-5" />
                  </button>
                </div>
              )}

              {/* Exercise Details */}
              {currentExercise && (
                <div className="bg-gray-900 rounded-lg p-6 mb-6">
                  <div className="flex items-start justify-between gap-3 mb-4">
                    <h3 className="text-xl font-bold text-white">{currentExercise.name}</h3>
                    <div className="flex gap-1.5 flex-wrap justify-end">
                      {currentExercise.is_per_side && (
                        <span className="px-2 py-0.5 rounded text-xs font-medium bg-cyan-600/20 text-cyan-300 border border-cyan-700/40">
                          per side
                        </span>
                      )}
                      {currentExercise.metric_type === 'time_seconds' && (
                        <span className="px-2 py-0.5 rounded text-xs font-medium bg-indigo-600/20 text-indigo-300 border border-indigo-700/40">
                          hold (seconds)
                        </span>
                      )}
                      {currentExercise.superset_group && (
                        <span className="px-2 py-0.5 rounded text-xs font-medium bg-pink-600/20 text-pink-300 border border-pink-700/40">
                          Superset {currentExercise.superset_group}
                        </span>
                      )}
                      {currentExercise.set_technique && (
                        <span className="px-2 py-0.5 rounded text-xs font-medium bg-orange-600/20 text-orange-300 border border-orange-700/40">
                          {SET_TECHNIQUE_LABEL[currentExercise.set_technique] || currentExercise.set_technique}
                        </span>
                      )}
                      {currentExercise.sets_original && currentExercise.sets_original !== currentExercise.sets && (
                        <span className="px-2 py-0.5 rounded text-xs font-medium bg-amber-600/20 text-amber-300 border border-amber-700/40">
                          deload {currentExercise.sets}/{currentExercise.sets_original} sets
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-4 mb-4">
                    <div className="text-center">
                      <div className="text-2xl font-bold text-purple-400">{currentExercise.sets}</div>
                      <div className="text-sm text-gray-400">Target Sets</div>
                    </div>
                    <div className="text-center">
                      <div className="text-2xl font-bold text-blue-400">{currentExercise.reps}</div>
                      <div className="text-sm text-gray-400">
                        {currentExercise.metric_type === 'time_seconds' ? 'Seconds' : 'Reps'}
                        {currentExercise.is_per_side ? ' / side' : ''}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-2xl font-bold text-green-400">{currentExercise.rpe_target || '-'}</div>
                      <div className="text-sm text-gray-400">Target RPE</div>
                    </div>
                  </div>

                  {currentExercise.notes && (
                    <p className="text-sm text-gray-400 mt-2 border-t border-gray-700 pt-2">
                      📝 {currentExercise.notes}
                    </p>
                  )}

                  {/* AI Weight Suggestion */}
                  {currentExercise.weight_suggestion && !currentExercise.weight_suggestion.ask_user && (
                    <div className="mt-4 bg-gradient-to-r from-purple-900/30 to-blue-900/30 border border-purple-700/50 rounded-lg p-4">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <TrendingUp className="w-4 h-4 text-purple-400" />
                          <span className="text-sm font-semibold text-purple-300">AI Suggestion</span>
                        </div>
                        {currentExercise.weight_suggestion.confidence && (
                          <span className={`text-xs px-2 py-1 rounded ${
                            currentExercise.weight_suggestion.confidence === 'high' ? 'bg-green-600/20 text-green-400' :
                            currentExercise.weight_suggestion.confidence === 'medium' ? 'bg-yellow-600/20 text-yellow-400' :
                            'bg-gray-600/20 text-gray-400'
                          }`}>
                            {currentExercise.weight_suggestion.confidence} confidence
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 mb-2">
                        <div className="text-2xl font-bold text-white">
                          {currentExercise.weight_suggestion.suggested_weight} lbs
                        </div>
                        <button
                          type="button"
                          onClick={() => setWeight(currentExercise.weight_suggestion!.suggested_weight!.toString())}
                          className="px-3 py-1 bg-purple-600 hover:bg-purple-700 text-white text-sm rounded transition-colors"
                        >
                          Use This
                        </button>
                      </div>
                      <p className="text-xs text-gray-400">{currentExercise.weight_suggestion.reasoning}</p>
                    </div>
                  )}

                  {/* Completed Sets */}
                  <div className="mt-4">
                    <h4 className="text-sm font-semibold text-gray-300 mb-2">
                      Completed Sets ({completedSetsForExercise.length} / {currentExercise.sets})
                    </h4>
                    {completedSetsForExercise.length > 0 ? (
                      <div className="space-y-1">
                        {completedSetsForExercise.map((set, idx) => (
                          <div key={set.id} className="flex items-center gap-3 text-sm bg-gray-800 p-2 rounded">
                            <Check className="w-4 h-4 text-green-400" />
                            <span className="text-gray-400">Set {idx + 1}:</span>
                            <span className="text-white">{set.weight || '-'}lbs × {set.reps || '-'} reps</span>
                            {set.rpe && <span className="text-gray-400">RPE {set.rpe}</span>}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-gray-500">No sets completed yet</p>
                    )}
                  </div>
                </div>
              )}

              {/* Set Logging Form */}
              <div className="bg-gray-900 rounded-lg p-6 mb-6">
                <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
                  <TrendingUp className="w-5 h-5 text-purple-400" />
                  Log Set #{completedSetsForExercise.length + 1}
                </h3>

                <form onSubmit={handleLogSet}>
                  <div className="grid grid-cols-3 gap-4 mb-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-300 mb-2">
                        Weight (lbs)
                      </label>
                      <input
                        type="number"
                        step="0.1"
                        value={weight}
                        onChange={(e) => setWeight(e.target.value)}
                        placeholder="135"
                        className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-purple-500"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-300 mb-2">
                        {currentExercise?.metric_type === 'time_seconds' ? 'Seconds held' : 'Reps'}
                        {currentExercise?.is_per_side ? ' (per side)' : ''}
                      </label>
                      <input
                        type="number"
                        value={reps}
                        onChange={(e) => setReps(e.target.value)}
                        placeholder={currentExercise?.metric_type === 'time_seconds' ? '45' : '10'}
                        className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-purple-500"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-300 mb-2">
                        RPE (1-10)
                      </label>
                      <input
                        type="number"
                        min="1"
                        max="10"
                        value={rpe}
                        onChange={(e) => setRpe(e.target.value)}
                        placeholder="7"
                        className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-purple-500"
                      />
                    </div>
                  </div>

                  <div className="mb-4">
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      Notes (Optional)
                    </label>
                    <input
                      type="text"
                      value={setNotes}
                      onChange={(e) => setSetNotes(e.target.value)}
                      placeholder="Felt great, good form"
                      className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-purple-500"
                    />
                  </div>

                  <button
                    type="submit"
                    disabled={submitting}
                    className="w-full px-4 py-3 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-600 text-white rounded-lg font-medium transition-colors"
                  >
                    {submitting ? 'Logging...' : 'Log Set'}
                  </button>
                </form>
              </div>

              {/* Complete Workout Button */}
              {totalSetsLogged > 0 && (
                <button
                  onClick={handleCompleteSession}
                  className="w-full px-4 py-3 bg-green-600 hover:bg-green-700 text-white rounded-lg font-medium flex items-center justify-center gap-2 transition-colors"
                >
                  <Trophy className="w-5 h-5" />
                  Complete Workout
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
