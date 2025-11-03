import React, { useState, useEffect } from 'react'
import { Dumbbell, Plus, X, TrendingUp, Calendar, FileText, Edit } from 'lucide-react'
import { APP_CONFIG } from '../../config'

interface WorkoutSet {
  id: string
  workout_id: string
  exercise_id: string
  exercise_name?: string
  set_index: number
  weight: number
  reps: number
  rpe?: number
  notes?: string
  created_at: string
}

interface WorkoutSession {
  date: string
  sets: WorkoutSet[]
}

interface Template {
  id: string
  name: string
  scheduled_days: string[]
  exercises: Exercise[]
  notes?: string
}

interface Exercise {
  name: string
  sets: number
  reps: string
  rpe_target: number
}

type WorkoutType = 'select' | 'today' | 'template' | 'custom'

export default function WorkoutLog() {
  const [workoutHistory, setWorkoutHistory] = useState<WorkoutSession[]>([])
  const [showModal, setShowModal] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [workoutType, setWorkoutType] = useState<WorkoutType>('select')
  const [templates, setTemplates] = useState<Template[]>([])
  const [todayTemplate, setTodayTemplate] = useState<Template | null>(null)
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null)

  // Multi-exercise workout state (for templates)
  const [workoutExercises, setWorkoutExercises] = useState<Array<{
    name: string
    sets: Array<{ weight: number; reps: number; rpe: number }>
    completed: boolean
  }>>([])
  const [currentExerciseIndex, setCurrentExerciseIndex] = useState(0)

  // Form state (for custom single exercise)
  const [exerciseName, setExerciseName] = useState('')
  const [sets, setSets] = useState<Array<{ weight: number; reps: number; rpe: number }>>([
    { weight: 0, reps: 0, rpe: 7 }
  ])
  const [notes, setNotes] = useState('')

  useEffect(() => {
    fetchWorkoutHistory()
    fetchTemplates()
    fetchTodayWorkout()
  }, [])

  const fetchWorkoutHistory = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/workouts`, {
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        // Group workout logs by date
        const grouped: { [key: string]: WorkoutSet[] } = {}
        data.workouts?.forEach((set: WorkoutSet) => {
          const date = new Date(set.created_at).toLocaleDateString()
          if (!grouped[date]) grouped[date] = []
          grouped[date].push(set)
        })
        const sessions = Object.entries(grouped).map(([date, sets]) => ({
          date,
          sets: sets.sort((a, b) => a.set_index - b.set_index)
        }))
        setWorkoutHistory(sessions.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()))
      }
    } catch (error) {
      console.error('Failed to fetch workout history:', error)
    }
  }

  const fetchTemplates = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/templates`, {
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        setTemplates(data.templates || [])
      }
    } catch (error) {
      console.error('Failed to fetch templates:', error)
    }
  }

  const fetchTodayWorkout = async () => {
    try {
      const today = new Date().toLocaleDateString('en-US', { weekday: 'long' }).toLowerCase()
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/templates`, {
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        const todaysWorkout = data.templates?.find((t: Template) =>
          t.scheduled_days.includes(today)
        )
        setTodayTemplate(todaysWorkout || null)
      }
    } catch (error) {
      console.error('Failed to fetch today\'s workout:', error)
    }
  }

  const openLogModal = () => {
    setExerciseName('')
    setSets([{ weight: 0, reps: 0, rpe: 7 }])
    setNotes('')
    setShowModal(true)
  }

  const closeModal = () => {
    setShowModal(false)
    setExerciseName('')
    setSets([{ weight: 0, reps: 0, rpe: 7 }])
    setNotes('')
  }

  const addSet = () => {
    setSets([...sets, { weight: 0, reps: 0, rpe: 7 }])
  }

  const removeSet = (index: number) => {
    if (sets.length > 1) {
      setSets(sets.filter((_, i) => i !== index))
    }
  }

  const updateSet = (index: number, field: 'weight' | 'reps' | 'rpe', value: number) => {
    const newSets = [...sets]
    newSets[index][field] = value
    setSets(newSets)
  }

  const deleteWorkoutSession = async (sessionSets: WorkoutSet[]) => {
    if (!confirm(`Delete this entire workout session (${sessionSets.length} sets)?`)) {
      return
    }

    try {
      // Delete all sets in the session
      for (const set of sessionSets) {
        await fetch(`${APP_CONFIG.apiUrl}/api/fitness/workouts/${set.id}`, {
          method: 'DELETE',
          credentials: 'include'
        })
      }
      // Refresh the workout history
      await fetchWorkoutHistory()
    } catch (error) {
      console.error('Failed to delete workout session:', error)
      alert('Failed to delete workout session')
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!exerciseName.trim() || sets.some(s => s.weight <= 0 || s.reps <= 0)) {
      alert('Please fill in all exercise details')
      return
    }

    setIsLoading(true)
    try {
      // Log each set
      for (let i = 0; i < sets.length; i++) {
        const set = sets[i]
        await fetch(`${APP_CONFIG.apiUrl}/api/fitness/workout-log`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            exercise_name: exerciseName,
            set_index: i + 1,
            weight: set.weight,
            reps: set.reps,
            rpe: set.rpe,
            notes: i === 0 ? notes : undefined // Only add notes to first set
          })
        })
      }
      await fetchWorkoutHistory()
      closeModal()
    } catch (error) {
      console.error('Failed to log workout:', error)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-2xl font-bold">Workout Log</h2>
          <p className="text-gray-400 text-sm mt-1">Track your exercises and progress</p>
        </div>
        <button
          onClick={openLogModal}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg flex items-center gap-2 transition-colors"
        >
          <Plus className="w-4 h-4" />
          Log Workout
        </button>
      </div>

      {workoutHistory.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <Dumbbell className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>No workouts logged yet</p>
          <p className="text-sm mt-1">Click "Log Workout" to get started</p>
        </div>
      ) : (
        <div className="space-y-6">
          {workoutHistory.map((session, idx) => (
            <div key={idx} className="bg-gray-800 rounded-lg p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-semibold text-lg flex items-center gap-2">
                  <Dumbbell className="w-5 h-5 text-blue-400" />
                  {session.date}
                </h3>
                <button
                  onClick={() => deleteWorkoutSession(session.sets)}
                  className="px-3 py-1 text-sm bg-red-600/20 text-red-400 rounded hover:bg-red-600/30 transition-colors"
                >
                  Delete Session
                </button>
              </div>
              <div className="space-y-4">
                {Object.entries(
                  session.sets.reduce((acc, set) => {
                    const name = set.exercise_name || `Exercise ${set.exercise_id}`
                    if (!acc[name]) acc[name] = []
                    acc[name].push(set)
                    return acc
                  }, {} as { [key: string]: WorkoutSet[] })
                ).map(([exerciseName, exerciseSets]) => (
                  <div key={exerciseName} className="border-l-2 border-blue-600 pl-4">
                    <h4 className="font-medium mb-2">{exerciseName}</h4>
                    <div className="space-y-1">
                      {exerciseSets.map((set, setIdx) => (
                        <div key={set.id} className="text-sm text-gray-400 flex items-center gap-4">
                          <span className="text-gray-500">Set {set.set_index}:</span>
                          <span className="font-mono">{set.weight}lbs × {set.reps}</span>
                          {set.rpe && (
                            <span className="text-xs px-2 py-0.5 bg-purple-600/20 text-purple-400 rounded">
                              RPE {set.rpe}
                            </span>
                          )}
                          {set.notes && setIdx === 0 && (
                            <span className="text-xs text-gray-500">- {set.notes}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-xl font-bold">Log Workout</h3>
              <button onClick={closeModal} className="p-2 hover:bg-gray-700 rounded-lg">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSubmit}>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-2">Exercise Name</label>
                  <input
                    type="text"
                    value={exerciseName}
                    onChange={(e) => setExerciseName(e.target.value)}
                    className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-blue-500 focus:outline-none"
                    placeholder="e.g., Bench Press, Squats..."
                    required
                  />
                </div>

                <div>
                  <div className="flex justify-between items-center mb-2">
                    <label className="block text-sm font-medium">Sets</label>
                    <button
                      type="button"
                      onClick={addSet}
                      className="text-sm text-blue-400 hover:text-blue-300"
                    >
                      + Add Set
                    </button>
                  </div>
                  <div className="space-y-2">
                    {sets.map((set, index) => (
                      <div key={index} className="flex gap-2 items-center bg-gray-900 p-3 rounded-lg">
                        <span className="text-sm text-gray-500 w-12">Set {index + 1}</span>
                        <input
                          type="number"
                          value={set.weight || ''}
                          onChange={(e) => updateSet(index, 'weight', parseFloat(e.target.value) || 0)}
                          className="flex-1 px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
                          placeholder="Weight (lbs)"
                          step="2.5"
                          min="0"
                        />
                        <span className="text-gray-500">×</span>
                        <input
                          type="number"
                          value={set.reps || ''}
                          onChange={(e) => updateSet(index, 'reps', parseInt(e.target.value) || 0)}
                          className="flex-1 px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
                          placeholder="Reps"
                          min="0"
                        />
                        <label className="text-sm text-gray-500">RPE</label>
                        <input
                          type="number"
                          value={set.rpe || ''}
                          onChange={(e) => updateSet(index, 'rpe', parseInt(e.target.value) || 7)}
                          className="w-16 px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
                          min="1"
                          max="10"
                        />
                        {sets.length > 1 && (
                          <button
                            type="button"
                            onClick={() => removeSet(index)}
                            className="text-red-400 hover:text-red-300 p-2"
                          >
                            <X className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Notes (optional)</label>
                  <textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-blue-500 focus:outline-none"
                    placeholder="How did it feel? Any observations?"
                    rows={3}
                  />
                </div>
              </div>

              <div className="flex gap-3 mt-6">
                <button
                  type="submit"
                  disabled={isLoading}
                  className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isLoading ? 'Logging...' : 'Log Workout'}
                </button>
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg font-medium"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
