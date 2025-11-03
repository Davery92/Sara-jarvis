import React, { useState, useEffect } from 'react'
import { Dumbbell, Plus, X, TrendingUp, Calendar, FileText, Edit, ChevronRight, ChevronDown, Save, Trash2 } from 'lucide-react'
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
  const [expandedSessions, setExpandedSessions] = useState<Set<number>>(new Set())
  const [editingSet, setEditingSet] = useState<string | null>(null)
  const [editValues, setEditValues] = useState<{weight: number, reps: number, rpe: number}>({weight: 0, reps: 0, rpe: 7})
  const [editingSessionDate, setEditingSessionDate] = useState<number | null>(null)
  const [newSessionDate, setNewSessionDate] = useState<string>('')

  // Multi-exercise workout state (for templates)
  const [workoutExercises, setWorkoutExercises] = useState<Array<{
    name: string
    targetSets: number
    targetReps: string
    targetRpe: number
    sets: Array<{ weight: number; reps: number; rpe: number }>
    completed: boolean
    suggestedWeight?: number
    weightReasoning?: string
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

  const toggleSession = (index: number) => {
    const newExpanded = new Set(expandedSessions)
    if (newExpanded.has(index)) {
      newExpanded.delete(index)
    } else {
      newExpanded.add(index)
    }
    setExpandedSessions(newExpanded)
  }

  const startEditingSet = (set: WorkoutSet) => {
    setEditingSet(set.id)
    setEditValues({ weight: set.weight, reps: set.reps, rpe: set.rpe || 7 })
  }

  const saveEditedSet = async (setId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/workouts/${setId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(editValues)
      })

      if (response.ok) {
        await fetchWorkoutHistory()
        setEditingSet(null)
      }
    } catch (error) {
      console.error('Failed to update set:', error)
      alert('Failed to update set')
    }
  }

  const deleteSet = async (setId: string) => {
    if (!confirm('Delete this set?')) return

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/workouts/${setId}`, {
        method: 'DELETE',
        credentials: 'include'
      })

      if (response.ok) {
        await fetchWorkoutHistory()
      }
    } catch (error) {
      console.error('Failed to delete set:', error)
      alert('Failed to delete set')
    }
  }

  const openLogModal = () => {
    setWorkoutType('select')
    setShowModal(true)
  }

  const selectTodayWorkout = () => {
    if (!todayTemplate) return
    loadTemplateExercises(todayTemplate)
    setWorkoutType('today')
  }

  const selectTemplate = (template: Template) => {
    setSelectedTemplate(template)
    loadTemplateExercises(template)
    setWorkoutType('template')
  }

  const selectCustom = () => {
    setExerciseName('')
    setSets([{ weight: 0, reps: 0, rpe: 7 }])
    setNotes('')
    setWorkoutType('custom')
  }

  const loadTemplateExercises = async (template: Template) => {
    setIsLoading(true)
    const exercises = await Promise.all(
      template.exercises.map(async (ex) => {
        const targetReps = ex.reps.includes('-')
          ? parseInt(ex.reps.split('-')[0])
          : parseInt(ex.reps)

        let suggestedWeight = 0
        let weightReasoning = "No suggestion available"

        try {
          const params = new URLSearchParams({
            exercise_name: ex.name,
            template_id: template.id,
            target_reps: targetReps.toString()
          })

          const url = `${APP_CONFIG.apiUrl}/api/fitness/weight-suggestion?${params}`
          const response = await fetch(url, { credentials: 'include' })

          if (response.ok) {
            const suggestion = await response.json()
            suggestedWeight = suggestion.suggested_weight || 0
            weightReasoning = suggestion.reasoning || "AI suggestion"
          }
        } catch (error) {
          console.error(`Failed to fetch weight suggestion for ${ex.name}:`, error)
        }

        return {
          name: ex.name,
          targetSets: ex.sets,
          targetReps: ex.reps,
          targetRpe: ex.rpe_target,
          sets: Array(ex.sets).fill(null).map(() => ({
            weight: suggestedWeight,
            reps: targetReps,
            rpe: ex.rpe_target
          })),
          completed: false,
          suggestedWeight,
          weightReasoning
        }
      })
    )

    setWorkoutExercises(exercises)
    setCurrentExerciseIndex(0)
    setIsLoading(false)
  }

  const closeModal = () => {
    setShowModal(false)
    setWorkoutType('select')
    setExerciseName('')
    setSets([{ weight: 0, reps: 0, rpe: 7 }])
    setNotes('')
    setWorkoutExercises([])
    setCurrentExerciseIndex(0)
    setSelectedTemplate(null)
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

  const updateExerciseSet = (exerciseIndex: number, setIndex: number, field: 'weight' | 'reps' | 'rpe', value: number) => {
    const newExercises = [...workoutExercises]
    newExercises[exerciseIndex].sets[setIndex][field] = value
    setWorkoutExercises(newExercises)
  }

  const deleteWorkoutSession = async (sessionSets: WorkoutSet[]) => {
    if (!confirm(`Delete this entire workout session (${sessionSets.length} sets)?`)) {
      return
    }

    try {
      for (const set of sessionSets) {
        await fetch(`${APP_CONFIG.apiUrl}/api/fitness/workouts/${set.id}`, {
          method: 'DELETE',
          credentials: 'include'
        })
      }
      await fetchWorkoutHistory()
    } catch (error) {
      console.error('Failed to delete workout session:', error)
      alert('Failed to delete workout session')
    }
  }

  const startEditingDate = (sessionIndex: number, currentDate: string) => {
    setEditingSessionDate(sessionIndex)
    const date = new Date(currentDate)
    const formatted = date.toISOString().split('T')[0]
    setNewSessionDate(formatted)
  }

  const saveSessionDate = async (sessionSets: WorkoutSet[]) => {
    if (!newSessionDate) return

    try {
      // Set time to noon UTC to avoid timezone boundary issues
      const dateWithTime = `${newSessionDate}T12:00:00.000Z`

      for (const set of sessionSets) {
        await fetch(`${APP_CONFIG.apiUrl}/api/fitness/workouts/${set.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ created_at: dateWithTime })
        })
      }
      setEditingSessionDate(null)
      setNewSessionDate('')
      await fetchWorkoutHistory()
    } catch (error) {
      console.error('Failed to update session date:', error)
      alert('Failed to update session date')
    }
  }

  const completeExercise = () => {
    const newExercises = [...workoutExercises]
    newExercises[currentExerciseIndex].completed = true
    setWorkoutExercises(newExercises)

    if (currentExerciseIndex < workoutExercises.length - 1) {
      setCurrentExerciseIndex(currentExerciseIndex + 1)
    }
  }

  const handleCustomSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!exerciseName.trim() || sets.some(s => s.weight <= 0 || s.reps <= 0)) {
      alert('Please fill in all exercise details')
      return
    }

    setIsLoading(true)
    try {
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
            notes: i === 0 ? notes : undefined
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

  const handleTemplateSubmit = async () => {
    setIsLoading(true)
    try {
      for (const exercise of workoutExercises) {
        for (let i = 0; i < exercise.sets.length; i++) {
          const set = exercise.sets[i]
          if (set.weight > 0 && set.reps > 0) {
            await fetch(`${APP_CONFIG.apiUrl}/api/fitness/workout-log`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              credentials: 'include',
              body: JSON.stringify({
                exercise_name: exercise.name,
                set_index: i + 1,
                weight: set.weight,
                reps: set.reps,
                rpe: set.rpe
              })
            })
          }
        }
      }
      await fetchWorkoutHistory()
      closeModal()
    } catch (error) {
      console.error('Failed to log workout:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const currentExercise = workoutExercises[currentExerciseIndex]

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
        <div className="space-y-4">
          {workoutHistory.map((session, idx) => (
            <div key={idx} className="bg-gray-800 rounded-lg overflow-hidden">
              <div
                className="p-4 flex items-center justify-between cursor-pointer hover:bg-gray-750"
                onClick={() => toggleSession(idx)}
              >
                <div className="flex items-center gap-2">
                  {expandedSessions.has(idx) ? (
                    <ChevronDown className="w-5 h-5 text-gray-400" />
                  ) : (
                    <ChevronRight className="w-5 h-5 text-gray-400" />
                  )}
                  <Dumbbell className="w-5 h-5 text-blue-400" />
                  {editingSessionDate === idx ? (
                    <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="date"
                        value={newSessionDate}
                        onChange={(e) => setNewSessionDate(e.target.value)}
                        className="px-2 py-1 bg-gray-900 border border-blue-500 rounded text-sm"
                      />
                      <button
                        onClick={() => saveSessionDate(session.sets)}
                        className="p-1 text-green-400 hover:text-green-300"
                        title="Save date"
                      >
                        <Save className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => setEditingSessionDate(null)}
                        className="p-1 text-gray-400 hover:text-gray-300"
                        title="Cancel"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  ) : (
                    <>
                      <h3 className="font-semibold text-lg">{session.date}</h3>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          startEditingDate(idx, session.date)
                        }}
                        className="p-1 text-gray-400 hover:text-blue-400 transition-colors"
                        title="Edit date"
                      >
                        <Calendar className="w-4 h-4" />
                      </button>
                    </>
                  )}
                  <span className="text-sm text-gray-400">({session.sets.length} sets)</span>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    deleteWorkoutSession(session.sets)
                  }}
                  className="px-3 py-1 text-sm bg-red-600/20 text-red-400 rounded hover:bg-red-600/30 transition-colors"
                >
                  Delete Session
                </button>
              </div>

              {expandedSessions.has(idx) && (
                <div className="px-4 pb-4 space-y-4">
                  {Object.entries(
                    session.sets.reduce((acc, set) => {
                      const name = set.exercise_id || `Exercise ${set.exercise_id}`
                      if (!acc[name]) acc[name] = []
                      acc[name].push(set)
                      return acc
                    }, {} as { [key: string]: WorkoutSet[] })
                  ).map(([exerciseName, exerciseSets]) => (
                    <div key={exerciseName} className="border-l-2 border-blue-600 pl-4">
                      <h4 className="font-medium mb-3">{exerciseName}</h4>
                      <div className="space-y-2">
                        {exerciseSets.map((set) => (
                          <div key={set.id} className="bg-gray-900 rounded p-3">
                            {editingSet === set.id ? (
                              <div className="flex items-center gap-2">
                                <span className="text-sm text-gray-500 w-12">Set {set.set_index}:</span>
                                <input
                                  type="number"
                                  value={editValues.weight}
                                  onChange={(e) => setEditValues({...editValues, weight: parseInt(e.target.value) || 0})}
                                  className="w-20 px-2 py-1 bg-gray-800 rounded border border-gray-700 text-sm"
                                  placeholder="lbs"
                                />
                                <span className="text-gray-500">×</span>
                                <input
                                  type="number"
                                  value={editValues.reps}
                                  onChange={(e) => setEditValues({...editValues, reps: parseInt(e.target.value) || 0})}
                                  className="w-16 px-2 py-1 bg-gray-800 rounded border border-gray-700 text-sm"
                                  placeholder="reps"
                                />
                                <span className="text-xs text-gray-500">RPE</span>
                                <input
                                  type="number"
                                  value={editValues.rpe}
                                  onChange={(e) => setEditValues({...editValues, rpe: parseInt(e.target.value) || 7})}
                                  className="w-12 px-2 py-1 bg-gray-800 rounded border border-gray-700 text-sm"
                                  min="1"
                                  max="10"
                                />
                                <button
                                  onClick={() => saveEditedSet(set.id)}
                                  className="ml-auto p-1 text-green-400 hover:text-green-300"
                                  title="Save"
                                >
                                  <Save className="w-4 h-4" />
                                </button>
                                <button
                                  onClick={() => setEditingSet(null)}
                                  className="p-1 text-gray-400 hover:text-gray-300"
                                  title="Cancel"
                                >
                                  <X className="w-4 h-4" />
                                </button>
                              </div>
                            ) : (
                              <div className="flex items-center gap-4">
                                <span className="text-sm text-gray-500">Set {set.set_index}:</span>
                                <span className="font-mono">{set.weight}lbs × {set.reps}</span>
                                {set.rpe && (
                                  <span className="text-xs px-2 py-0.5 bg-purple-600/20 text-purple-400 rounded">
                                    RPE {set.rpe}
                                  </span>
                                )}
                                {set.notes && (
                                  <span className="text-xs text-gray-500">- {set.notes}</span>
                                )}
                                <div className="ml-auto flex gap-1">
                                  <button
                                    onClick={() => startEditingSet(set)}
                                    className="p-1 text-blue-400 hover:text-blue-300"
                                    title="Edit"
                                  >
                                    <Edit className="w-4 h-4" />
                                  </button>
                                  <button
                                    onClick={() => deleteSet(set.id)}
                                    className="p-1 text-red-400 hover:text-red-300"
                                    title="Delete"
                                  >
                                    <Trash2 className="w-4 h-4" />
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Modal - keeping existing modal code */}
      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-xl font-bold">Log Workout</h3>
              <button onClick={closeModal} className="p-2 hover:bg-gray-700 rounded-lg">
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Selection Screen */}
            {workoutType === 'select' && (
              <div className="space-y-3">
                {todayTemplate && (
                  <button
                    onClick={selectTodayWorkout}
                    className="w-full p-4 bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-700 hover:to-blue-700 rounded-lg text-left transition-all flex items-center justify-between"
                  >
                    <div className="flex items-center gap-3">
                      <Calendar className="w-5 h-5" />
                      <div>
                        <div className="font-semibold">Today's Workout</div>
                        <div className="text-sm opacity-90">{todayTemplate.name}</div>
                      </div>
                    </div>
                    <ChevronRight className="w-5 h-5" />
                  </button>
                )}

                <div className="relative">
                  <div className="absolute inset-0 flex items-center">
                    <div className="w-full border-t border-gray-700"></div>
                  </div>
                  <div className="relative flex justify-center text-sm">
                    <span className="px-2 bg-gray-800 text-gray-400">or choose</span>
                  </div>
                </div>

                {templates.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-gray-400 mb-2">Choose Template</h4>
                    <div className="space-y-2 max-h-64 overflow-y-auto">
                      {templates.map(template => (
                        <button
                          key={template.id}
                          onClick={() => selectTemplate(template)}
                          className="w-full p-3 bg-gray-700 hover:bg-gray-600 rounded-lg text-left transition-colors flex items-center justify-between"
                        >
                          <div className="flex items-center gap-3">
                            <FileText className="w-4 h-4" />
                            <div>
                              <div className="font-medium">{template.name}</div>
                              <div className="text-xs text-gray-400">{template.exercises.length} exercises</div>
                            </div>
                          </div>
                          <ChevronRight className="w-4 h-4" />
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <button
                  onClick={selectCustom}
                  className="w-full p-4 bg-gray-700 hover:bg-gray-600 rounded-lg text-left transition-colors flex items-center justify-between"
                >
                  <div className="flex items-center gap-3">
                    <Edit className="w-5 h-5" />
                    <div>
                      <div className="font-semibold">Custom Exercise</div>
                      <div className="text-sm text-gray-400">Create as you go</div>
                    </div>
                  </div>
                  <ChevronRight className="w-5 h-5" />
                </button>
              </div>
            )}

            {/* Custom Exercise Form */}
            {workoutType === 'custom' && (
              <form onSubmit={handleCustomSubmit}>
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
                    onClick={() => setWorkoutType('select')}
                    className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg font-medium"
                  >
                    Back
                  </button>
                </div>
              </form>
            )}

            {/* Template Workout Form */}
            {(workoutType === 'today' || workoutType === 'template') && currentExercise && (
              <div>
                <div className="mb-4 bg-gray-900 p-4 rounded-lg">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="font-semibold">{currentExercise.name}</h4>
                    <span className="text-sm text-gray-400">
                      Exercise {currentExerciseIndex + 1} of {workoutExercises.length}
                    </span>
                  </div>
                  <div className="text-sm text-gray-400">
                    Target: {currentExercise.targetSets} sets × {currentExercise.targetReps} reps @ RPE {currentExercise.targetRpe}
                  </div>

                {currentExercise.suggestedWeight && currentExercise.suggestedWeight > 0 && (
                  <div className="mb-3 p-2 bg-blue-900/30 border border-blue-600/50 rounded text-sm">
                    <div className="flex items-center gap-2">
                      <TrendingUp className="w-4 h-4 text-blue-400" />
                      <span className="font-medium text-blue-300">AI Suggestion: {currentExercise.suggestedWeight}lbs</span>
                    </div>
                    <div className="text-xs text-gray-400 mt-1">{currentExercise.weightReasoning}</div>
                  </div>
                )}

                </div>

                <div className="space-y-2 mb-6">
                  {currentExercise.sets.map((set, idx) => (
                    <div key={idx} className="flex gap-2 items-center bg-gray-900 p-3 rounded-lg">
                      <span className="text-sm text-gray-500 w-12">Set {idx + 1}</span>
                      <input
                        type="number"
                        value={set.weight || ''}
                        onChange={(e) => updateExerciseSet(currentExerciseIndex, idx, 'weight', parseFloat(e.target.value) || 0)}
                        className="flex-1 px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
                        placeholder="Weight (lbs)"
                        step="2.5"
                        min="0"
                      />
                      <span className="text-gray-500">×</span>
                      <input
                        type="number"
                        value={set.reps || ''}
                        onChange={(e) => updateExerciseSet(currentExerciseIndex, idx, 'reps', parseInt(e.target.value) || 0)}
                        className="flex-1 px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
                        placeholder="Reps"
                        min="0"
                      />
                      <label className="text-sm text-gray-500">RPE</label>
                      <input
                        type="number"
                        value={set.rpe || ''}
                        onChange={(e) => updateExerciseSet(currentExerciseIndex, idx, 'rpe', parseInt(e.target.value) || currentExercise.targetRpe)}
                        className="w-16 px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
                        min="1"
                        max="10"
                      />
                    </div>
                  ))}
                </div>

                {/* Exercise Progress */}
                <div className="mb-6">
                  <div className="flex gap-1">
                    {workoutExercises.map((ex, idx) => (
                      <div
                        key={idx}
                        className={`flex-1 h-2 rounded ${
                          ex.completed ? 'bg-green-600' : idx === currentExerciseIndex ? 'bg-blue-600' : 'bg-gray-700'
                        }`}
                      />
                    ))}
                  </div>
                </div>

                <div className="flex gap-3">
                  {currentExerciseIndex < workoutExercises.length - 1 ? (
                    <>
                      <button
                        onClick={completeExercise}
                        className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium"
                      >
                        Next Exercise
                      </button>
                      <button
                        onClick={() => setWorkoutType('select')}
                        className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg font-medium"
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={handleTemplateSubmit}
                        disabled={isLoading}
                        className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg font-medium disabled:opacity-50"
                      >
                        {isLoading ? 'Saving...' : 'Finish Workout'}
                      </button>
                      <button
                        onClick={() => setWorkoutType('select')}
                        disabled={isLoading}
                        className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg font-medium"
                      >
                        Cancel
                      </button>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
