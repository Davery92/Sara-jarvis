import React, { useState, useEffect } from 'react'
import { Dumbbell, Plus, X, Edit2, Trash2, Calendar as CalendarIcon, ChevronDown, ChevronRight } from 'lucide-react'
import { APP_CONFIG } from '../../config'

interface Template {
  id: string
  phase_id?: string
  name: string
  scheduled_days: string[]
  exercises: Exercise[]
  notes?: string
  created_at: string
  updated_at: string
}

interface Exercise {
  name: string
  sets: number
  reps: string
  rpe_target: number
  starting_weight?: number
}

interface Phase {
  id: string
  name: string
  status?: string
}

const DAYS_OF_WEEK = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

export default function TemplateBuilder() {
  const [templates, setTemplates] = useState<Template[]>([])
  const [phases, setPhases] = useState<Phase[]>([])
  const [showModal, setShowModal] = useState(false)
  const [editingTemplate, setEditingTemplate] = useState<Template | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [expandedTemplates, setExpandedTemplates] = useState<Set<string>>(new Set())

  // Form state
  const [name, setName] = useState('')
  const [phaseId, setPhaseId] = useState('')
  const [scheduledDays, setScheduledDays] = useState<string[]>([])
  const [exercises, setExercises] = useState<Exercise[]>([
    { name: '', sets: 3, reps: '8-10', rpe_target: 7, starting_weight: undefined }
  ])
  const [notes, setNotes] = useState('')

  useEffect(() => {
    fetchTemplates()
    fetchPhases()
  }, [])

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

  const fetchPhases = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/phases`, {
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        setPhases(data.phases || [])
      }
    } catch (error) {
      console.error('Failed to fetch phases:', error)
    }
  }

  const openNewTemplateModal = () => {
    setEditingTemplate(null)
    setName('')
    setPhaseId('')
    setScheduledDays([])
    setExercises([{ name: '', sets: 3, reps: '8-10', rpe_target: 7, starting_weight: undefined }])
    setNotes('')
    setShowModal(true)
  }

  const openEditModal = (template: Template) => {
    setEditingTemplate(template)
    setName(template.name)
    setPhaseId(template.phase_id || '')
    setScheduledDays(template.scheduled_days)
    setExercises(template.exercises.length > 0 ? template.exercises : [{ name: '', sets: 3, reps: '8-10', rpe_target: 7, starting_weight: undefined }])
    setNotes(template.notes || '')
    setShowModal(true)
  }

  const closeModal = () => {
    setShowModal(false)
    setEditingTemplate(null)
  }

  const toggleDay = (day: string) => {
    if (scheduledDays.includes(day)) {
      setScheduledDays(scheduledDays.filter(d => d !== day))
    } else {
      setScheduledDays([...scheduledDays, day])
    }
  }

  const addExercise = () => {
    setExercises([...exercises, { name: '', sets: 3, reps: '8-10', rpe_target: 7, starting_weight: undefined }])
  }

  const removeExercise = (index: number) => {
    if (exercises.length > 1) {
      setExercises(exercises.filter((_, i) => i !== index))
    }
  }

  const updateExercise = (index: number, field: keyof Exercise, value: any) => {
    const newExercises = [...exercises]
    newExercises[index] = { ...newExercises[index], [field]: value }
    setExercises(newExercises)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim() || scheduledDays.length === 0 || exercises.some(ex => !ex.name.trim())) {
      alert('Please fill in template name, select days, and name all exercises')
      return
    }

    setIsLoading(true)
    try {
      // Build starting_weights object from exercises
      const starting_weights: { [key: string]: number } = {}
      exercises.forEach(ex => {
        if (ex.name && ex.starting_weight !== undefined && ex.starting_weight > 0) {
          starting_weights[ex.name] = ex.starting_weight
        }
      })

      const payload = {
        name,
        phase_id: phaseId || null,
        scheduled_days: scheduledDays,
        exercises,
        notes,
        starting_weights: Object.keys(starting_weights).length > 0 ? starting_weights : null
      }

      if (editingTemplate) {
        const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/templates/${editingTemplate.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(payload)
        })
        if (response.ok) {
          await fetchTemplates()
          closeModal()
        }
      } else {
        const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/templates`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(payload)
        })
        if (response.ok) {
          await fetchTemplates()
          closeModal()
        }
      }
    } catch (error) {
      console.error('Failed to save template:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleDelete = async (templateId: string) => {
    if (!confirm('Delete this template?')) return

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/templates/${templateId}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (response.ok) {
        await fetchTemplates()
      }
    } catch (error) {
      console.error('Failed to delete template:', error)
    }
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-2xl font-bold">Workout Templates</h2>
          <p className="text-gray-400 text-sm mt-1">Create and manage your workout templates</p>
        </div>
        <button
          onClick={openNewTemplateModal}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg flex items-center gap-2 transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Template
        </button>
      </div>

      {templates.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <Dumbbell className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>No workout templates yet</p>
          <p className="text-sm mt-1">Create your first template to start scheduling workouts</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {templates.map((template) => {
            const isExpanded = expandedTemplates.has(template.id)
            return (
              <div key={template.id} className="bg-gray-800 rounded-lg overflow-hidden">
                {/* Collapsed Header - Always Visible */}
                <div
                  className="p-4 flex items-center justify-between cursor-pointer hover:bg-gray-750 transition-colors"
                  onClick={() => {
                    const next = new Set(expandedTemplates)
                    if (isExpanded) next.delete(template.id)
                    else next.add(template.id)
                    setExpandedTemplates(next)
                  }}
                >
                  <div className="flex items-center gap-3">
                    {isExpanded ? (
                      <ChevronDown className="w-5 h-5 text-gray-400" />
                    ) : (
                      <ChevronRight className="w-5 h-5 text-gray-400" />
                    )}
                    <div>
                      <h3 className="font-semibold">{template.name}</h3>
                      <div className="flex items-center gap-2 text-sm text-gray-400">
                        <span>{template.exercises.length} exercises</span>
                        <span>•</span>
                        <div className="flex gap-1">
                          {template.scheduled_days.map(day => (
                            <span key={day} className="text-blue-400 capitalize">
                              {day.slice(0, 2)}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => openEditModal(template)}
                      className="p-2 hover:bg-gray-700 rounded-lg transition-colors"
                    >
                      <Edit2 className="w-4 h-4 text-gray-400" />
                    </button>
                    <button
                      onClick={() => handleDelete(template.id)}
                      className="p-2 hover:bg-gray-700 rounded-lg transition-colors"
                    >
                      <Trash2 className="w-4 h-4 text-red-400" />
                    </button>
                  </div>
                </div>

                {/* Expanded Content */}
                {isExpanded && (
                  <div className="px-4 pb-4 border-t border-gray-700">
                    {template.notes && (
                      <p className="text-sm text-gray-500 mt-3 mb-3">{template.notes}</p>
                    )}
                    <div className="space-y-2 mt-3">
                      {template.exercises.map((ex, idx) => (
                        <div key={idx} className="flex items-center justify-between bg-gray-900 p-3 rounded">
                          <span className="font-medium">{ex.name}</span>
                          <div className="flex items-center gap-4 text-sm text-gray-400">
                            <span>{ex.sets} × {ex.reps}</span>
                            <span className="px-2 py-1 bg-purple-600/20 text-purple-400 rounded text-xs">
                              RPE {ex.rpe_target}
                            </span>
                            {ex.starting_weight && (
                              <span className="text-green-400">{ex.starting_weight}lbs</span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4 overflow-y-auto">
          <div className="bg-gray-800 rounded-lg max-w-4xl w-full p-6 my-8">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-xl font-bold">
                {editingTemplate ? 'Edit Template' : 'New Workout Template'}
              </h3>
              <button onClick={closeModal} className="p-2 hover:bg-gray-700 rounded-lg">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSubmit}>
              <div className="space-y-6">
                <div>
                  <label className="block text-sm font-medium mb-2">Template Name</label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-blue-500 focus:outline-none"
                    placeholder="e.g., Push Day A, Pull Day B"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Training Phase (Optional)</label>
                  <select
                    value={phaseId}
                    onChange={(e) => setPhaseId(e.target.value)}
                    className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-blue-500 focus:outline-none"
                  >
                    <option value="">No phase</option>
                    {phases.map(phase => (
                      <option key={phase.id} value={phase.id}>
                        {phase.name}{phase.status !== 'active' ? ` (${phase.status})` : ''}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Scheduled Days</label>
                  <div className="flex flex-wrap gap-2">
                    {DAYS_OF_WEEK.map(day => (
                      <button
                        key={day}
                        type="button"
                        onClick={() => toggleDay(day)}
                        className={`px-4 py-2 rounded-lg capitalize transition-colors ${
                          scheduledDays.includes(day)
                            ? 'bg-blue-600 text-white'
                            : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                        }`}
                      >
                        {day}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="flex justify-between items-center mb-3">
                    <label className="block text-sm font-medium">Exercises</label>
                    <button
                      type="button"
                      onClick={addExercise}
                      className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-1"
                    >
                      <Plus className="w-4 h-4" />
                      Add Exercise
                    </button>
                  </div>
                  <div className="space-y-3">
                    {exercises.map((ex, idx) => (
                      <div key={idx} className="bg-gray-900 p-4 rounded-lg">
                        <div className="flex gap-3 items-start">
                          <div className="flex-1">
                            <input
                              type="text"
                              value={ex.name}
                              onChange={(e) => updateExercise(idx, 'name', e.target.value)}
                              className="w-full px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-blue-500 focus:outline-none mb-3"
                              placeholder="Exercise name (e.g., Bench Press)"
                              required
                            />
                            <div className="grid grid-cols-4 gap-3">
                              <div>
                                <label className="block text-xs text-gray-400 mb-1">Sets</label>
                                <input
                                  type="number"
                                  value={ex.sets}
                                  onChange={(e) => updateExercise(idx, 'sets', parseInt(e.target.value))}
                                  className="w-full px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
                                  min="1"
                                />
                              </div>
                              <div>
                                <label className="block text-xs text-gray-400 mb-1">Reps</label>
                                <input
                                  type="text"
                                  value={ex.reps}
                                  onChange={(e) => updateExercise(idx, 'reps', e.target.value)}
                                  className="w-full px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
                                  placeholder="8-10"
                                />
                              </div>
                              <div>
                                <label className="block text-xs text-gray-400 mb-1">RPE Target</label>
                                <input
                                  type="number"
                                  value={ex.rpe_target}
                                  onChange={(e) => updateExercise(idx, 'rpe_target', parseInt(e.target.value))}
                                  className="w-full px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
                                  min="1"
                                  max="10"
                                />
                              </div>
                              <div>
                                <label className="block text-xs text-gray-400 mb-1">Starting Weight (lbs)</label>
                                <input
                                  type="number"
                                  value={ex.starting_weight || ''}
                                  onChange={(e) => updateExercise(idx, 'starting_weight', e.target.value ? parseFloat(e.target.value) : undefined)}
                                  className="w-full px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
                                  placeholder="Optional"
                                  step="2.5"
                                  min="0"
                                />
                              </div>
                            </div>
                          </div>
                          {exercises.length > 1 && (
                            <button
                              type="button"
                              onClick={() => removeExercise(idx)}
                              className="p-2 text-red-400 hover:bg-gray-800 rounded"
                            >
                              <X className="w-5 h-5" />
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Notes</label>
                  <textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-blue-500 focus:outline-none"
                    rows={2}
                    placeholder="Template notes, progression instructions..."
                  />
                </div>
              </div>

              <div className="flex gap-3 mt-6">
                <button
                  type="submit"
                  disabled={isLoading}
                  className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium disabled:opacity-50"
                >
                  {isLoading ? 'Saving...' : editingTemplate ? 'Update Template' : 'Create Template'}
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
