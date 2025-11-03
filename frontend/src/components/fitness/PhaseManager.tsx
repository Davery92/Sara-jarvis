import React, { useState, useEffect } from 'react'
import { Calendar, Plus, X, Edit2, Trash2, Play, Pause, CheckCircle, Rocket } from 'lucide-react'
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
}

export default function PhaseManager() {
  const [phases, setPhases] = useState<Phase[]>([])
  const [showModal, setShowModal] = useState(false)
  const [editingPhase, setEditingPhase] = useState<Phase | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  // Form state
  const [name, setName] = useState('')
  const [goal, setGoal] = useState('hypertrophy')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [notes, setNotes] = useState('')

  useEffect(() => {
    fetchPhases()
  }, [])

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
    setShowModal(true)
  }

  const openEditModal = (phase: Phase) => {
    setEditingPhase(phase)
    setName(phase.name)
    setGoal(phase.goal || 'hypertrophy')
    setStartDate(phase.start_date || '')
    setEndDate(phase.end_date || '')
    setNotes(phase.notes || '')
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
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return

    setIsLoading(true)
    try {
      if (editingPhase) {
        // Update
        const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/phases/${editingPhase.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            name,
            goal,
            start_date: startDate || null,
            end_date: endDate || null,
            notes
          })
        })
        if (response.ok) {
          await fetchPhases()
          closeModal()
        }
      } else {
        // Create
        const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/phases`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            name,
            goal,
            start_date: startDate || null,
            end_date: endDate || null,
            notes
          })
        })
        if (response.ok) {
          await fetchPhases()
          closeModal()
        }
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
        <button
          onClick={openNewPhaseModal}
          className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg flex items-center gap-2 transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Phase
        </button>
      </div>

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
    </div>
  )
}
