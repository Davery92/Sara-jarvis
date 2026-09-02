import React, { useState, useEffect } from 'react'
import { Calendar, Plus, X, Edit2, Trash2, Play, Pause, CheckCircle, Rocket, Scissors } from 'lucide-react'
import { APP_CONFIG } from '../../config'

interface Phase {
  id: string
  name: string
  goal: string
  parent_phase_id?: string
  start_date?: string
  end_date?: string
  status: string
  notes?: string
  created_at: string
  updated_at: string
  // Nutrition single (weekly average / fallback)
  calories_target?: number | null
  protein_target?: number | null
  carbs_target?: number | null
  fat_target?: number | null
  // Calorie cycling
  calories_training_day?: number | null
  calories_rest_day?: number | null
  carbs_training_day?: number | null
  carbs_rest_day?: number | null
  fat_training_day?: number | null
  fat_rest_day?: number | null
  // Daily targets + periodization
  daily_steps_target?: number | null
  training_days_per_week?: number | null
  duration_weeks?: number | null
  deload_week?: number | null
}

const numOrNull = (s: string): number | null => {
  if (s === '' || s == null) return null
  const n = parseInt(s, 10)
  return isNaN(n) ? null : n
}

interface BlockSummary {
  name: string
  start_date: string
  end_date: string
  mode: string
  trimmed_phases: { id: string; name: string }[]
  shifted_phases: { id: string; name: string }[]
  shelved_phases: { id: string; name: string }[]
  templates_copied: number
}

export default function PhaseManager() {
  const [phases, setPhases] = useState<Phase[]>([])
  const [showModal, setShowModal] = useState(false)
  const [editingPhase, setEditingPhase] = useState<Phase | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  // Insert-block modal state
  const [showBlockModal, setShowBlockModal] = useState(false)
  const [blockLoading, setBlockLoading] = useState(false)
  const [blockName, setBlockName] = useState('')
  const [blockGoal, setBlockGoal] = useState('cut')
  const [blockStartDate, setBlockStartDate] = useState('')
  const [blockDurationWeeks, setBlockDurationWeeks] = useState('3')
  const [blockMode, setBlockMode] = useState<'overlay' | 'push'>('overlay')
  const [blockCaloriesTrainingDay, setBlockCaloriesTrainingDay] = useState('')
  const [blockCaloriesRestDay, setBlockCaloriesRestDay] = useState('')
  const [blockCarbsTrainingDay, setBlockCarbsTrainingDay] = useState('')
  const [blockCarbsRestDay, setBlockCarbsRestDay] = useState('')
  const [blockFatTrainingDay, setBlockFatTrainingDay] = useState('')
  const [blockFatRestDay, setBlockFatRestDay] = useState('')
  const [blockProteinTarget, setBlockProteinTarget] = useState('')
  const [blockNotes, setBlockNotes] = useState('')
  const [toast, setToast] = useState<{ message: string; error?: boolean } | null>(null)

  // Form state
  const [name, setName] = useState('')
  const [goal, setGoal] = useState('hypertrophy')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [notes, setNotes] = useState('')
  // Nutrition + periodization
  const [proteinTarget, setProteinTarget] = useState('')
  const [caloriesTrainingDay, setCaloriesTrainingDay] = useState('')
  const [caloriesRestDay, setCaloriesRestDay] = useState('')
  const [carbsTrainingDay, setCarbsTrainingDay] = useState('')
  const [carbsRestDay, setCarbsRestDay] = useState('')
  const [fatTrainingDay, setFatTrainingDay] = useState('')
  const [fatRestDay, setFatRestDay] = useState('')
  const [dailyStepsTarget, setDailyStepsTarget] = useState('')
  const [trainingDaysPerWeek, setTrainingDaysPerWeek] = useState('')
  const [durationWeeks, setDurationWeeks] = useState('')
  const [deloadWeek, setDeloadWeek] = useState('')

  const resetNutritionForm = () => {
    setProteinTarget('')
    setCaloriesTrainingDay('')
    setCaloriesRestDay('')
    setCarbsTrainingDay('')
    setCarbsRestDay('')
    setFatTrainingDay('')
    setFatRestDay('')
    setDailyStepsTarget('')
    setTrainingDaysPerWeek('')
    setDurationWeeks('')
    setDeloadWeek('')
  }

  useEffect(() => {
    fetchPhases()
  }, [])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 8000)
    return () => clearTimeout(t)
  }, [toast])

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

  const openNewPhaseModal = () => {
    setEditingPhase(null)
    setName('')
    setGoal('hypertrophy')
    setStartDate('')
    setEndDate('')
    setNotes('')
    resetNutritionForm()
    setShowModal(true)
  }

  const openEditModal = (phase: Phase) => {
    setEditingPhase(phase)
    setName(phase.name)
    setGoal(phase.goal || 'hypertrophy')
    setStartDate(phase.start_date || '')
    setEndDate(phase.end_date || '')
    setNotes(phase.notes || '')
    setProteinTarget(phase.protein_target?.toString() || '')
    setCaloriesTrainingDay(phase.calories_training_day?.toString() || '')
    setCaloriesRestDay(phase.calories_rest_day?.toString() || '')
    setCarbsTrainingDay(phase.carbs_training_day?.toString() || '')
    setCarbsRestDay(phase.carbs_rest_day?.toString() || '')
    setFatTrainingDay(phase.fat_training_day?.toString() || '')
    setFatRestDay(phase.fat_rest_day?.toString() || '')
    setDailyStepsTarget(phase.daily_steps_target?.toString() || '')
    setTrainingDaysPerWeek(phase.training_days_per_week?.toString() || '')
    setDurationWeeks(phase.duration_weeks?.toString() || '')
    setDeloadWeek(phase.deload_week?.toString() || '')
    setShowModal(true)
  }

  const closeModal = () => {
    setShowModal(false)
    setEditingPhase(null)
    setName('')
    setGoal('hypertrophy')
    setStartDate('')
    setEndDate('')
    setNotes('')
    resetNutritionForm()
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return

    setIsLoading(true)
    try {
      const payload = {
        name,
        goal,
        start_date: startDate || null,
        end_date: endDate || null,
        notes,
        protein_target: numOrNull(proteinTarget),
        calories_training_day: numOrNull(caloriesTrainingDay),
        calories_rest_day: numOrNull(caloriesRestDay),
        carbs_training_day: numOrNull(carbsTrainingDay),
        carbs_rest_day: numOrNull(carbsRestDay),
        fat_training_day: numOrNull(fatTrainingDay),
        fat_rest_day: numOrNull(fatRestDay),
        daily_steps_target: numOrNull(dailyStepsTarget),
        training_days_per_week: numOrNull(trainingDaysPerWeek),
        duration_weeks: numOrNull(durationWeeks),
        deload_week: numOrNull(deloadWeek),
      }

      const url = editingPhase
        ? `${APP_CONFIG.apiUrl}/api/fitness/phases/${editingPhase.id}`
        : `${APP_CONFIG.apiUrl}/api/fitness/phases`
      const method = editingPhase ? 'PATCH' : 'POST'

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload),
      })
      if (response.ok) {
        await fetchPhases()
        closeModal()
      } else {
        const err = await response.text()
        alert(`Failed to save phase: ${err.slice(0, 200)}`)
      }
    } catch (error) {
      console.error('Failed to save phase:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleDelete = async (phaseId: string) => {
    if (!confirm('Delete this phase? This will also delete associated templates.')) return

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/phases/${phaseId}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (response.ok) {
        await fetchPhases()
      }
    } catch (error) {
      console.error('Failed to delete phase:', error)
    }
  }

  const handleStatusChange = async (phaseId: string, newStatus: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/phases/${phaseId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ status: newStatus })
      })
      if (response.ok) {
        await fetchPhases()
      }
    } catch (error) {
      console.error('Failed to update status:', error)
    }
  }

  const handleActivatePhase = async (phaseId: string, phaseName: string) => {
    if (!confirm(`Activate phase "${phaseName}"?\n\nThis will create calendar events for all workout templates assigned to this phase.`)) {
      return
    }

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/phases/${phaseId}/activate`, {
        method: 'POST',
        credentials: 'include',
      })

      if (response.ok) {
        const data = await response.json()
        alert(
          `✅ Phase Activated!\n\n` +
          `Created ${data.summary.events_created} calendar events\n` +
          `Created ${data.summary.sessions_created} workout sessions\n\n` +
          `Check your calendar to see scheduled workouts.`
        )
        await fetchPhases()
      } else {
        const errorData = await response.json()
        alert(`❌ Failed to activate phase:\n${errorData.detail || 'Unknown error'}`)
      }
    } catch (error) {
      console.error('Failed to activate phase:', error)
      alert('❌ Failed to activate phase. Check console for details.')
    }
  }

  const openBlockModal = () => {
    setBlockName('')
    setBlockGoal('cut')
    setBlockStartDate('')
    setBlockDurationWeeks('3')
    setBlockMode('overlay')
    setBlockCaloriesTrainingDay('')
    setBlockCaloriesRestDay('')
    setBlockCarbsTrainingDay('')
    setBlockCarbsRestDay('')
    setBlockFatTrainingDay('')
    setBlockFatRestDay('')
    setBlockProteinTarget('')
    setBlockNotes('')
    setShowBlockModal(true)
  }

  const closeBlockModal = () => setShowBlockModal(false)

  const handleInsertBlock = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!blockName.trim()) return

    setBlockLoading(true)
    try {
      const payload = {
        name: blockName,
        goal: blockGoal,
        start_date: blockStartDate || null,
        duration_weeks: numOrNull(blockDurationWeeks),
        mode: blockMode,
        protein_target: numOrNull(blockProteinTarget),
        calories_training_day: numOrNull(blockCaloriesTrainingDay),
        calories_rest_day: numOrNull(blockCaloriesRestDay),
        carbs_training_day: numOrNull(blockCarbsTrainingDay),
        carbs_rest_day: numOrNull(blockCarbsRestDay),
        fat_training_day: numOrNull(blockFatTrainingDay),
        fat_rest_day: numOrNull(blockFatRestDay),
        notes: blockNotes || null,
      }

      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/phases/insert-block`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload),
      })

      if (response.ok) {
        const data: BlockSummary = await response.json()
        const parts = [`"${data.name}" runs ${data.start_date} → ${data.end_date}.`]
        if (data.trimmed_phases?.length) parts.push(`Trimmed ${data.trimmed_phases.length} phase(s).`)
        if (data.shifted_phases?.length) parts.push(`Shifted ${data.shifted_phases.length} phase(s).`)
        if (data.shelved_phases?.length) parts.push(`Shelved ${data.shelved_phases.length} phase(s).`)
        if (data.templates_copied) parts.push(`Copied ${data.templates_copied} workout(s).`)
        setToast({ message: parts.join(' ') })
        await fetchPhases()
        closeBlockModal()
      } else {
        const err = await response.json().catch(() => null)
        setToast({ message: `Failed to start block: ${err?.detail || 'Unknown error'}`, error: true })
      }
    } catch (error) {
      console.error('Failed to insert phase block:', error)
      setToast({ message: 'Failed to start block. Check console for details.', error: true })
    } finally {
      setBlockLoading(false)
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'bg-green-600/20 text-green-400 border-green-600'
      case 'completed': return 'bg-blue-600/20 text-blue-400 border-blue-600'
      case 'paused': return 'bg-yellow-600/20 text-yellow-400 border-yellow-600'
      default: return 'bg-gray-600/20 text-gray-400 border-gray-600'
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'active': return <Play className="w-4 h-4" />
      case 'completed': return <CheckCircle className="w-4 h-4" />
      case 'paused': return <Pause className="w-4 h-4" />
      default: return <Calendar className="w-4 h-4" />
    }
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-2xl font-bold">Training Phases</h2>
          <p className="text-gray-400 text-sm mt-1">Organize your training into structured phases</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={openBlockModal}
            className="px-4 py-2 bg-amber-600 hover:bg-amber-700 rounded-lg flex items-center gap-2 transition-colors"
            title="Insert a dated cut/bulk/maintenance block into the active program"
          >
            <Scissors className="w-4 h-4" />
            Insert Block
          </button>
          <button
            onClick={openNewPhaseModal}
            className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg flex items-center gap-2 transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Phase
          </button>
        </div>
      </div>

      {toast && (
        <div
          className={`fixed bottom-6 right-6 z-[60] max-w-sm px-4 py-3 rounded-lg shadow-lg border text-sm ${
            toast.error
              ? 'bg-red-900/90 border-red-600 text-red-100'
              : 'bg-emerald-900/90 border-emerald-600 text-emerald-100'
          }`}
        >
          <div className="flex justify-between items-start gap-3">
            <span>{toast.message}</span>
            <button onClick={() => setToast(null)} className="opacity-70 hover:opacity-100">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {phases.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <Calendar className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>No training phases yet</p>
          <p className="text-sm mt-1">Create your first phase to start organizing your training</p>
        </div>
      ) : (
        <div className="grid gap-4">
          {phases.map((phase) => (
            <div key={phase.id} className="bg-gray-800 rounded-lg p-5 hover:bg-gray-750 transition-colors">
              <div className="flex justify-between items-start">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <h3 className="text-xl font-semibold">{phase.name}</h3>
                    <div className={`px-3 py-1 rounded-full text-xs font-medium border flex items-center gap-1 ${getStatusColor(phase.status)}`}>
                      {getStatusIcon(phase.status)}
                      {phase.status}
                    </div>
                  </div>

                  {phase.goal && (
                    <p className="text-sm text-gray-400 mb-2">
                      <span className="font-medium text-purple-400">Goal:</span> {phase.goal}
                    </p>
                  )}

                  {(phase.start_date || phase.end_date) && (
                    <div className="flex items-center gap-4 text-sm text-gray-400 mb-2">
                      {phase.start_date && (
                        <span className="flex items-center gap-1">
                          <Calendar className="w-4 h-4" />
                          {new Date(phase.start_date).toLocaleDateString()}
                        </span>
                      )}
                      {phase.end_date && (
                        <span>→ {new Date(phase.end_date).toLocaleDateString()}</span>
                      )}
                      {phase.duration_weeks && <span>· {phase.duration_weeks}w</span>}
                      {phase.training_days_per_week && <span>· {phase.training_days_per_week}d/wk</span>}
                      {phase.deload_week && <span className="text-amber-400">· deload wk {phase.deload_week}</span>}
                    </div>
                  )}

                  {/* Cycling + steps chips */}
                  {(phase.calories_training_day || phase.calories_rest_day || phase.daily_steps_target || phase.protein_target) && (
                    <div className="flex flex-wrap gap-2 mt-2">
                      {phase.calories_training_day && (
                        <span className="px-2 py-0.5 text-xs rounded bg-purple-600/20 text-purple-300">
                          Train: {phase.calories_training_day}kcal
                          {phase.carbs_training_day != null && ` · ${phase.carbs_training_day}C`}
                          {phase.fat_training_day != null && ` · ${phase.fat_training_day}F`}
                        </span>
                      )}
                      {phase.calories_rest_day && (
                        <span className="px-2 py-0.5 text-xs rounded bg-blue-600/20 text-blue-300">
                          Rest: {phase.calories_rest_day}kcal
                          {phase.carbs_rest_day != null && ` · ${phase.carbs_rest_day}C`}
                          {phase.fat_rest_day != null && ` · ${phase.fat_rest_day}F`}
                        </span>
                      )}
                      {phase.protein_target && (
                        <span className="px-2 py-0.5 text-xs rounded bg-pink-600/20 text-pink-300">
                          {phase.protein_target}g protein/day
                        </span>
                      )}
                      {phase.daily_steps_target && (
                        <span className="px-2 py-0.5 text-xs rounded bg-emerald-600/20 text-emerald-300">
                          {phase.daily_steps_target.toLocaleString()} steps/day
                        </span>
                      )}
                    </div>
                  )}

                  {phase.notes && (
                    <p className="text-sm text-gray-500 mt-2">{phase.notes}</p>
                  )}
                </div>

                <div className="flex gap-2 ml-4">
                  {/* Activate button - creates calendar events */}
                  {phase.status === 'planned' && phase.start_date && phase.end_date && (
                    <button
                      onClick={() => handleActivatePhase(phase.id, phase.name)}
                      className="px-3 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg transition-colors text-white flex items-center gap-1 font-medium text-sm"
                      title="Activate Phase & Schedule Workouts"
                    >
                      <Rocket className="w-4 h-4" />
                      Activate
                    </button>
                  )}
                  {/* Status buttons */}
                  {phase.status === 'active' && (
                    <button
                      onClick={() => handleStatusChange(phase.id, 'completed')}
                      className="p-2 hover:bg-gray-700 rounded-lg transition-colors text-blue-400"
                      title="Complete"
                    >
                      <CheckCircle className="w-4 h-4" />
                    </button>
                  )}
                  <button
                    onClick={() => openEditModal(phase)}
                    className="p-2 hover:bg-gray-700 rounded-lg transition-colors"
                    title="Edit"
                  >
                    <Edit2 className="w-4 h-4 text-gray-400" />
                  </button>
                  <button
                    onClick={() => handleDelete(phase.id)}
                    className="p-2 hover:bg-gray-700 rounded-lg transition-colors"
                    title="Delete"
                  >
                    <Trash2 className="w-4 h-4 text-red-400" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg max-w-2xl w-full p-6">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-xl font-bold">
                {editingPhase ? 'Edit Phase' : 'New Training Phase'}
              </h3>
              <button onClick={closeModal} className="p-2 hover:bg-gray-700 rounded-lg">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSubmit}>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-2">Phase Name</label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-purple-500 focus:outline-none"
                    placeholder="e.g., Hypertrophy Block 1, Strength Phase"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Goal</label>
                  <select
                    value={goal}
                    onChange={(e) => setGoal(e.target.value)}
                    className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-purple-500 focus:outline-none"
                  >
                    <option value="hypertrophy">Hypertrophy (Muscle Growth)</option>
                    <option value="strength">Strength</option>
                    <option value="power">Power</option>
                    <option value="endurance">Endurance</option>
                    <option value="deload">Deload/Recovery</option>
                    <option value="cutting">Cutting (Fat Loss)</option>
                    <option value="maintenance">Maintenance</option>
                  </select>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-2">Start Date</label>
                    <input
                      type="date"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                      className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-purple-500 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-2">End Date</label>
                    <input
                      type="date"
                      value={endDate}
                      onChange={(e) => setEndDate(e.target.value)}
                      className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-purple-500 focus:outline-none"
                    />
                  </div>
                </div>

                {/* Periodization */}
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-2">Duration (weeks)</label>
                    <input
                      type="number"
                      value={durationWeeks}
                      onChange={(e) => setDurationWeeks(e.target.value)}
                      className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-purple-500 focus:outline-none"
                      placeholder="8"
                      min="1"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-2">Training days/wk</label>
                    <input
                      type="number"
                      value={trainingDaysPerWeek}
                      onChange={(e) => setTrainingDaysPerWeek(e.target.value)}
                      className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-purple-500 focus:outline-none"
                      placeholder="4"
                      min="1"
                      max="7"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-2">Deload week</label>
                    <input
                      type="number"
                      value={deloadWeek}
                      onChange={(e) => setDeloadWeek(e.target.value)}
                      className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-purple-500 focus:outline-none"
                      placeholder="(none)"
                      min="1"
                    />
                  </div>
                </div>

                {/* Calorie cycling */}
                <div className="border border-gray-700 rounded-lg p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-semibold text-purple-300">Calorie Cycling</h4>
                    <span className="text-xs text-gray-500">Training days fuel work, rest days recover</span>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Protein (g/day, constant)</label>
                    <input
                      type="number"
                      value={proteinTarget}
                      onChange={(e) => setProteinTarget(e.target.value)}
                      className="w-full px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-purple-500 focus:outline-none"
                      placeholder="230"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs text-purple-400 mb-1">Training day kcal</label>
                      <input
                        type="number"
                        value={caloriesTrainingDay}
                        onChange={(e) => setCaloriesTrainingDay(e.target.value)}
                        className="w-full px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-purple-500 focus:outline-none"
                        placeholder="2650"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-blue-400 mb-1">Rest day kcal</label>
                      <input
                        type="number"
                        value={caloriesRestDay}
                        onChange={(e) => setCaloriesRestDay(e.target.value)}
                        className="w-full px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-purple-500 focus:outline-none"
                        placeholder="2200"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-purple-400 mb-1">Training day carbs (g)</label>
                      <input
                        type="number"
                        value={carbsTrainingDay}
                        onChange={(e) => setCarbsTrainingDay(e.target.value)}
                        className="w-full px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-purple-500 focus:outline-none"
                        placeholder="250"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-blue-400 mb-1">Rest day carbs (g)</label>
                      <input
                        type="number"
                        value={carbsRestDay}
                        onChange={(e) => setCarbsRestDay(e.target.value)}
                        className="w-full px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-purple-500 focus:outline-none"
                        placeholder="130"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-purple-400 mb-1">Training day fat (g)</label>
                      <input
                        type="number"
                        value={fatTrainingDay}
                        onChange={(e) => setFatTrainingDay(e.target.value)}
                        className="w-full px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-purple-500 focus:outline-none"
                        placeholder="80"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-blue-400 mb-1">Rest day fat (g)</label>
                      <input
                        type="number"
                        value={fatRestDay}
                        onChange={(e) => setFatRestDay(e.target.value)}
                        className="w-full px-3 py-2 bg-gray-800 rounded border border-gray-700 focus:border-purple-500 focus:outline-none"
                        placeholder="95"
                      />
                    </div>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Daily steps target</label>
                  <input
                    type="number"
                    value={dailyStepsTarget}
                    onChange={(e) => setDailyStepsTarget(e.target.value)}
                    className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-purple-500 focus:outline-none"
                    placeholder="9000"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Notes</label>
                  <textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-purple-500 focus:outline-none"
                    rows={3}
                    placeholder="Phase details, goals, reminders..."
                  />
                </div>
              </div>

              <div className="flex gap-3 mt-6">
                <button
                  type="submit"
                  disabled={isLoading}
                  className="flex-1 px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg font-medium disabled:opacity-50"
                >
                  {isLoading ? 'Saving...' : editingPhase ? 'Update Phase' : 'Create Phase'}
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

      {/* Insert Block modal */}
      {showBlockModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg max-w-2xl w-full p-6">
            <div className="flex justify-between items-center mb-4">
              <div>
                <h3 className="text-xl font-bold">Insert Block</h3>
                <p className="text-xs text-gray-400 mt-1">
                  Drops a dated cut/bulk/maintenance block into the active program — surrounding
                  phases are trimmed or shifted automatically.
                </p>
              </div>
              <button onClick={closeBlockModal} className="p-2 hover:bg-gray-700 rounded-lg">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleInsertBlock}>
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-2">Block Name</label>
                    <input
                      type="text"
                      value={blockName}
                      onChange={(e) => setBlockName(e.target.value)}
                      className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-amber-500 focus:outline-none"
                      placeholder="e.g., Cut, 3-Week Cut"
                      required
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-2">Goal</label>
                    <select
                      value={blockGoal}
                      onChange={(e) => setBlockGoal(e.target.value)}
                      className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-amber-500 focus:outline-none"
                    >
                      <option value="cut">Cut (Fat Loss)</option>
                      <option value="bulk">Bulk</option>
                      <option value="maintenance">Maintenance</option>
                      <option value="recomp">Recomp</option>
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-2">Start Date</label>
                    <input
                      type="date"
                      value={blockStartDate}
                      onChange={(e) => setBlockStartDate(e.target.value)}
                      className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-amber-500 focus:outline-none"
                    />
                    <p className="text-xs text-gray-500 mt-1">Defaults to next Monday</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-2">Duration (weeks)</label>
                    <input
                      type="number"
                      value={blockDurationWeeks}
                      onChange={(e) => setBlockDurationWeeks(e.target.value)}
                      className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-amber-500 focus:outline-none"
                      min="1"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-2">Collision mode</label>
                    <select
                      value={blockMode}
                      onChange={(e) => setBlockMode(e.target.value as 'overlay' | 'push')}
                      className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-amber-500 focus:outline-none"
                    >
                      <option value="overlay">Overlay (trim/split)</option>
                      <option value="push">Push (shift later phases)</option>
                    </select>
                  </div>
                </div>

                <div className="border border-gray-700 rounded-lg p-4 space-y-3">
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Protein (g/day, constant)</label>
                    <input
                      type="number"
                      value={blockProteinTarget}
                      onChange={(e) => setBlockProteinTarget(e.target.value)}
                      className="w-full px-3 py-2 bg-gray-900 rounded border border-gray-700 focus:border-amber-500 focus:outline-none"
                      placeholder="230"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs text-amber-400 mb-1">Training day kcal</label>
                      <input
                        type="number"
                        value={blockCaloriesTrainingDay}
                        onChange={(e) => setBlockCaloriesTrainingDay(e.target.value)}
                        className="w-full px-3 py-2 bg-gray-900 rounded border border-gray-700 focus:border-amber-500 focus:outline-none"
                        placeholder="2300"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-blue-400 mb-1">Rest day kcal</label>
                      <input
                        type="number"
                        value={blockCaloriesRestDay}
                        onChange={(e) => setBlockCaloriesRestDay(e.target.value)}
                        className="w-full px-3 py-2 bg-gray-900 rounded border border-gray-700 focus:border-amber-500 focus:outline-none"
                        placeholder="1900"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-amber-400 mb-1">Training day carbs (g)</label>
                      <input
                        type="number"
                        value={blockCarbsTrainingDay}
                        onChange={(e) => setBlockCarbsTrainingDay(e.target.value)}
                        className="w-full px-3 py-2 bg-gray-900 rounded border border-gray-700 focus:border-amber-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-blue-400 mb-1">Rest day carbs (g)</label>
                      <input
                        type="number"
                        value={blockCarbsRestDay}
                        onChange={(e) => setBlockCarbsRestDay(e.target.value)}
                        className="w-full px-3 py-2 bg-gray-900 rounded border border-gray-700 focus:border-amber-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-amber-400 mb-1">Training day fat (g)</label>
                      <input
                        type="number"
                        value={blockFatTrainingDay}
                        onChange={(e) => setBlockFatTrainingDay(e.target.value)}
                        className="w-full px-3 py-2 bg-gray-900 rounded border border-gray-700 focus:border-amber-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-blue-400 mb-1">Rest day fat (g)</label>
                      <input
                        type="number"
                        value={blockFatRestDay}
                        onChange={(e) => setBlockFatRestDay(e.target.value)}
                        className="w-full px-3 py-2 bg-gray-900 rounded border border-gray-700 focus:border-amber-500 focus:outline-none"
                      />
                    </div>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Notes</label>
                  <textarea
                    value={blockNotes}
                    onChange={(e) => setBlockNotes(e.target.value)}
                    className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-amber-500 focus:outline-none"
                    rows={2}
                    placeholder="Optional notes about this block..."
                  />
                </div>
              </div>

              <div className="flex gap-3 mt-6">
                <button
                  type="submit"
                  disabled={blockLoading}
                  className="flex-1 px-4 py-2 bg-amber-600 hover:bg-amber-700 rounded-lg font-medium disabled:opacity-50"
                >
                  {blockLoading ? 'Starting...' : 'Start Block'}
                </button>
                <button
                  type="button"
                  onClick={closeBlockModal}
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
