import React, { useState, useEffect } from 'react'
import { Dumbbell, Apple, FileText, Activity, Settings, X, Calendar, Heart, RefreshCw, Target, TrendingUp, Trophy, Scale, ChevronDown, ChevronUp } from 'lucide-react'
import FoodLog from './FoodLog'
import WorkoutLog from './WorkoutLogEnhanced'
import FitnessNotes from './FitnessNotes'
import TemplateBuilder from './TemplateBuilder'
import RecoveryLog from './RecoveryLog'
import RecoveryTrendChart from './RecoveryTrendChart'
import { APP_CONFIG } from '../../config'

type FitnessView = 'dashboard' | 'food' | 'workout' | 'notes' | 'templates' | 'recovery' | 'programs'

export default function FitnessSection() {
  const [currentView, setCurrentView] = useState<FitnessView>('dashboard')
  const [dashboardKey, setDashboardKey] = useState(0)

  // Refresh dashboard when switching to it
  const handleViewChange = (view: FitnessView) => {
    if (view === 'dashboard' && currentView !== 'dashboard') {
      setDashboardKey(prev => prev + 1) // Force dashboard refresh
    }
    setCurrentView(view)
  }

  const tabs = [
    { id: 'dashboard' as FitnessView, label: 'Dashboard', icon: Activity },
    { id: 'programs' as FitnessView, label: 'Programs', icon: Target },
    { id: 'templates' as FitnessView, label: 'Templates', icon: Calendar },
    { id: 'recovery' as FitnessView, label: 'Recovery', icon: Heart },
    { id: 'food' as FitnessView, label: 'Food Log', icon: Apple },
    { id: 'workout' as FitnessView, label: 'Workouts', icon: Dumbbell },
    { id: 'notes' as FitnessView, label: 'Notes', icon: FileText },
  ]

  return (
    <div className="h-full flex flex-col bg-gray-900 text-white">
      {/* Header */}
      <div className="border-b border-gray-700 bg-gray-800">
        <div className="px-6 py-4">
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Dumbbell className="w-6 h-6" />
            Fitness Tracker
          </h1>
          <p className="text-gray-400 text-sm mt-1">
            Track your nutrition, workouts, and fitness progress
          </p>
        </div>

        {/* Tabs */}
        <div
          className="flex gap-1 px-6 overflow-x-auto scrollbar-hidden scroll-snap-x md:overflow-visible"
          style={{
            overscrollBehaviorX: 'contain',
            WebkitOverflowScrolling: 'touch',
            touchAction: 'pan-x'
          }}
        >
          {tabs.map((tab) => {
            const Icon = tab.icon
            return (
              <button
                key={tab.id}
                onClick={() => handleViewChange(tab.id)}
                className={`
                  px-4 py-2 rounded-t-lg flex items-center gap-2 transition-colors
                  whitespace-nowrap flex-shrink-0 scroll-snap-center tap-target
                  ${
                    currentView === tab.id
                      ? 'bg-gray-900 text-white'
                      : 'text-gray-400 hover:text-white hover:bg-gray-700'
                  }
                `}
              >
                <Icon className="w-4 h-4" />
                <span className="hidden sm:inline">{tab.label}</span>
                <span className="sm:hidden text-xs">{tab.label.split(' ')[0]}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {currentView === 'dashboard' && <FitnessDashboard key={dashboardKey} />}
        {currentView === 'programs' && <ProgramManager />}
        {currentView === 'templates' && <TemplateBuilder />}
        {currentView === 'recovery' && (
          <div className="p-6 space-y-6">
            <RecoveryLog />
            <RecoveryTrendChart days={30} />
          </div>
        )}
        {currentView === 'food' && <FoodLog />}
        {currentView === 'workout' && <WorkoutLog />}
        {currentView === 'notes' && <FitnessNotes />}
      </div>
    </div>
  )
}

// ============================================
// PROGRAM MANAGER COMPONENT
// ============================================

interface Program {
  id: string
  name: string
  goal: string
  start_date: string | null
  end_date: string | null
  is_active: boolean
  notes: string | null
}

interface Phase {
  id: string
  name: string
  goal: string | null
  program_id: string | null
  order_index: number
  duration_weeks: number | null
  start_date: string | null
  end_date: string | null
  calories_target: number | null
  protein_target: number | null
  carbs_target: number | null
  fat_target: number | null
  training_days_per_week: number | null
  deload_week: number | null
  status: string
}

function ProgramManager() {
  const [programs, setPrograms] = useState<Program[]>([])
  const [activeProgram, setActiveProgram] = useState<Program | null>(null)
  const [activePhases, setActivePhases] = useState<Phase[]>([])
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showPhaseModal, setShowPhaseModal] = useState(false)
  const [editingPhase, setEditingPhase] = useState<Phase | null>(null)
  const [newProgram, setNewProgram] = useState({
    name: '',
    goal: 'maintenance',
    start_date: '',
    end_date: '',
    notes: ''
  })
  const [newPhase, setNewPhase] = useState({
    name: '',
    goal: '',
    duration_weeks: 4,
    calories_target: 2000,
    protein_target: 150,
    carbs_target: 200,
    fat_target: 70,
    training_days_per_week: 4,
    deload_week: 0
  })

  useEffect(() => {
    fetchPrograms()
    fetchActiveProgram()
  }, [])

  const fetchPrograms = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/programs`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setPrograms(data.programs || [])
      }
    } catch (error) {
      console.error('Failed to fetch programs:', error)
    }
  }

  const fetchActiveProgram = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/programs/active`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setActiveProgram(data.program)
        setActivePhases(data.phases || [])
      }
    } catch (error) {
      console.error('Failed to fetch active program:', error)
    }
  }

  const createProgram = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/programs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(newProgram)
      })
      if (response.ok) {
        setShowCreateModal(false)
        setNewProgram({ name: '', goal: 'maintenance', start_date: '', end_date: '', notes: '' })
        fetchPrograms()
      }
    } catch (error) {
      console.error('Failed to create program:', error)
    }
  }

  const activateProgram = async (programId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/programs/${programId}/activate`, {
        method: 'POST',
        credentials: 'include'
      })
      if (response.ok) {
        fetchPrograms()
        fetchActiveProgram()
      }
    } catch (error) {
      console.error('Failed to activate program:', error)
    }
  }

  const createPhase = async () => {
    if (!activeProgram) return
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/phases`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          ...newPhase,
          program_id: activeProgram.id,
          order_index: activePhases.length
        })
      })
      if (response.ok) {
        setShowPhaseModal(false)
        setNewPhase({
          name: '',
          goal: '',
          duration_weeks: 4,
          calories_target: 2000,
          protein_target: 150,
          carbs_target: 200,
          fat_target: 70,
          training_days_per_week: 4,
          deload_week: 0
        })
        fetchActiveProgram()
      }
    } catch (error) {
      console.error('Failed to create phase:', error)
    }
  }

  const activatePhase = async (phaseId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/phases/${phaseId}/activate`, {
        method: 'POST',
        credentials: 'include'
      })
      const data = await response.json()
      if (response.ok) {
        alert(`✅ ${data.message}\n\n${data.note}`)
        fetchActiveProgram()
      } else {
        alert(`❌ Failed to activate phase: ${data.detail || 'Unknown error'}`)
      }
    } catch (error) {
      console.error('Failed to activate phase:', error)
      alert('❌ Failed to activate phase. Check console for details.')
    }
  }

  const openEditPhase = (phase: Phase) => {
    setEditingPhase(phase)
    setNewPhase({
      name: phase.name,
      goal: phase.goal || '',
      duration_weeks: phase.duration_weeks || 4,
      calories_target: phase.calories_target || 2000,
      protein_target: phase.protein_target || 150,
      carbs_target: phase.carbs_target || 200,
      fat_target: phase.fat_target || 70,
      training_days_per_week: phase.training_days_per_week || 4,
      deload_week: phase.deload_week || 0
    })
    setShowPhaseModal(true)
  }

  const updatePhase = async () => {
    if (!editingPhase) return
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/phases/${editingPhase.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(newPhase)
      })
      if (response.ok) {
        setShowPhaseModal(false)
        setEditingPhase(null)
        setNewPhase({
          name: '',
          goal: '',
          duration_weeks: 4,
          calories_target: 2000,
          protein_target: 150,
          carbs_target: 200,
          fat_target: 70,
          training_days_per_week: 4,
          deload_week: 0
        })
        fetchActiveProgram()
      } else {
        const data = await response.json()
        alert(`❌ Failed to update phase: ${data.detail || 'Unknown error'}`)
      }
    } catch (error) {
      console.error('Failed to update phase:', error)
    }
  }

  const deletePhase = async (phaseId: string) => {
    if (!confirm('Are you sure you want to delete this phase?')) return
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/phases/${phaseId}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      if (response.ok) {
        fetchActiveProgram()
      } else {
        const data = await response.json()
        alert(`❌ Failed to delete phase: ${data.detail || 'Unknown error'}`)
      }
    } catch (error) {
      console.error('Failed to delete phase:', error)
    }
  }

  const goalColors: Record<string, string> = {
    cut: 'text-red-400 bg-red-400/10',
    bulk: 'text-green-400 bg-green-400/10',
    maintenance: 'text-blue-400 bg-blue-400/10',
    recomp: 'text-purple-400 bg-purple-400/10',
    strength: 'text-orange-400 bg-orange-400/10'
  }

  return (
    <div className="p-6 space-y-6">
      {/* Active Program Section */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold flex items-center gap-2">
            <Target className="w-5 h-5 text-blue-400" />
            Active Program
          </h2>
          {!activeProgram && (
            <button
              onClick={() => setShowCreateModal(true)}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition-colors"
            >
              Create Program
            </button>
          )}
        </div>

        {activeProgram ? (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-medium">{activeProgram.name}</h3>
                <span className={`text-sm px-2 py-1 rounded ${goalColors[activeProgram.goal] || 'text-gray-400 bg-gray-700'}`}>
                  {activeProgram.goal.charAt(0).toUpperCase() + activeProgram.goal.slice(1)}
                </span>
              </div>
              {activeProgram.start_date && activeProgram.end_date && (
                <div className="text-sm text-gray-400">
                  {new Date(activeProgram.start_date).toLocaleDateString()} - {new Date(activeProgram.end_date).toLocaleDateString()}
                </div>
              )}
            </div>

            {/* Phases */}
            <div className="mt-4">
              <div className="flex items-center justify-between mb-3">
                <h4 className="font-medium text-gray-300">Training Phases</h4>
                <button
                  onClick={() => setShowPhaseModal(true)}
                  className="text-sm text-blue-400 hover:text-blue-300"
                >
                  + Add Phase
                </button>
              </div>

              {activePhases.length > 0 ? (
                <div className="space-y-3">
                  {activePhases.map((phase, idx) => (
                    <div
                      key={phase.id}
                      className={`p-4 rounded-lg border ${
                        phase.status === 'active'
                          ? 'bg-blue-900/20 border-blue-500'
                          : 'bg-gray-700/50 border-gray-600'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <span className="text-gray-500 text-sm">#{idx + 1}</span>
                          <div>
                            <div className="font-medium">{phase.name}</div>
                            {phase.duration_weeks && (
                              <div className="text-sm text-gray-400">{phase.duration_weeks} weeks</div>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => openEditPhase(phase)}
                            className="text-xs px-2 py-1 bg-gray-600 hover:bg-gray-500 rounded"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => deletePhase(phase.id)}
                            className="text-xs px-2 py-1 bg-red-600/20 hover:bg-red-600/40 text-red-400 rounded"
                          >
                            Delete
                          </button>
                          {phase.status === 'active' ? (
                            <span className="text-xs px-2 py-1 bg-green-500/20 text-green-400 rounded">Active</span>
                          ) : (
                            <button
                              onClick={() => activatePhase(phase.id)}
                              className="text-xs px-2 py-1 bg-blue-600 hover:bg-blue-500 rounded"
                            >
                              Activate
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Nutrition Targets */}
                      {(phase.calories_target || phase.protein_target) && (
                        <div className="mt-3 pt-3 border-t border-gray-600 grid grid-cols-4 gap-2 text-sm">
                          <div>
                            <span className="text-gray-500">Calories</span>
                            <div className="font-medium">{phase.calories_target || '-'}</div>
                          </div>
                          <div>
                            <span className="text-gray-500">Protein</span>
                            <div className="font-medium">{phase.protein_target ? `${phase.protein_target}g` : '-'}</div>
                          </div>
                          <div>
                            <span className="text-gray-500">Carbs</span>
                            <div className="font-medium">{phase.carbs_target ? `${phase.carbs_target}g` : '-'}</div>
                          </div>
                          <div>
                            <span className="text-gray-500">Fat</span>
                            <div className="font-medium">{phase.fat_target ? `${phase.fat_target}g` : '-'}</div>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center text-gray-500 py-4">
                  No phases yet. Add phases to structure your training.
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="text-center text-gray-400 py-8">
            No active program. Create a program to start tracking your training.
          </div>
        )}
      </div>

      {/* All Programs */}
      {programs.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <h2 className="text-lg font-semibold mb-4">All Programs</h2>
          <div className="space-y-2">
            {programs.map(program => (
              <div
                key={program.id}
                className={`p-4 rounded-lg border flex items-center justify-between ${
                  program.is_active ? 'bg-blue-900/20 border-blue-500' : 'bg-gray-700/50 border-gray-600'
                }`}
              >
                <div>
                  <div className="font-medium">{program.name}</div>
                  <span className={`text-xs px-2 py-0.5 rounded ${goalColors[program.goal] || 'text-gray-400 bg-gray-700'}`}>
                    {program.goal}
                  </span>
                </div>
                {!program.is_active && (
                  <button
                    onClick={() => activateProgram(program.id)}
                    className="text-sm px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded"
                  >
                    Activate
                  </button>
                )}
              </div>
            ))}
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="mt-4 w-full px-4 py-2 border border-gray-600 hover:border-gray-500 rounded-lg text-gray-400 hover:text-white transition-colors"
          >
            + Create New Program
          </button>
        </div>
      )}

      {/* Create Program Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 w-full max-w-md border border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xl font-semibold">Create Program</h3>
              <button onClick={() => setShowCreateModal(false)} className="p-1 hover:bg-gray-700 rounded">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Program Name</label>
                <input
                  type="text"
                  value={newProgram.name}
                  onChange={e => setNewProgram({ ...newProgram, name: e.target.value })}
                  placeholder="e.g., 12-Week Cut"
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">Goal</label>
                <select
                  value={newProgram.goal}
                  onChange={e => setNewProgram({ ...newProgram, goal: e.target.value })}
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                >
                  <option value="cut">Cut (Fat Loss)</option>
                  <option value="bulk">Bulk (Muscle Gain)</option>
                  <option value="maintenance">Maintenance</option>
                  <option value="recomp">Recomposition</option>
                  <option value="strength">Strength</option>
                </select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Start Date</label>
                  <input
                    type="date"
                    value={newProgram.start_date}
                    onChange={e => setNewProgram({ ...newProgram, start_date: e.target.value })}
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">End Date</label>
                  <input
                    type="date"
                    value={newProgram.end_date}
                    onChange={e => setNewProgram({ ...newProgram, end_date: e.target.value })}
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">Notes</label>
                <textarea
                  value={newProgram.notes}
                  onChange={e => setNewProgram({ ...newProgram, notes: e.target.value })}
                  rows={2}
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setShowCreateModal(false)}
                className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={createProgram}
                disabled={!newProgram.name}
                className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg disabled:opacity-50"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create/Edit Phase Modal */}
      {showPhaseModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 w-full max-w-md border border-gray-700 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xl font-semibold">{editingPhase ? 'Edit Phase' : 'Add Phase'}</h3>
              <button onClick={() => { setShowPhaseModal(false); setEditingPhase(null); }} className="p-1 hover:bg-gray-700 rounded">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Phase Name</label>
                <input
                  type="text"
                  value={newPhase.name}
                  onChange={e => setNewPhase({ ...newPhase, name: e.target.value })}
                  placeholder="e.g., Week 1-4: Foundation"
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Duration (weeks)</label>
                  <input
                    type="number"
                    value={newPhase.duration_weeks}
                    onChange={e => setNewPhase({ ...newPhase, duration_weeks: parseInt(e.target.value) || 0 })}
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Training Days/Week</label>
                  <input
                    type="number"
                    value={newPhase.training_days_per_week}
                    onChange={e => setNewPhase({ ...newPhase, training_days_per_week: parseInt(e.target.value) || 0 })}
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              <div className="border-t border-gray-700 pt-4 mt-4">
                <h4 className="font-medium mb-3">Daily Nutrition Targets</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">Calories</label>
                    <input
                      type="number"
                      value={newPhase.calories_target}
                      onChange={e => setNewPhase({ ...newPhase, calories_target: parseInt(e.target.value) || 0 })}
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">Protein (g)</label>
                    <input
                      type="number"
                      value={newPhase.protein_target}
                      onChange={e => setNewPhase({ ...newPhase, protein_target: parseInt(e.target.value) || 0 })}
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">Carbs (g)</label>
                    <input
                      type="number"
                      value={newPhase.carbs_target}
                      onChange={e => setNewPhase({ ...newPhase, carbs_target: parseInt(e.target.value) || 0 })}
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">Fat (g)</label>
                    <input
                      type="number"
                      value={newPhase.fat_target}
                      onChange={e => setNewPhase({ ...newPhase, fat_target: parseInt(e.target.value) || 0 })}
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </div>
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">Deload Week (0 = none)</label>
                <input
                  type="number"
                  value={newPhase.deload_week}
                  onChange={e => setNewPhase({ ...newPhase, deload_week: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => { setShowPhaseModal(false); setEditingPhase(null); }}
                className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={editingPhase ? updatePhase : createPhase}
                disabled={!newPhase.name}
                className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg disabled:opacity-50"
              >
                {editingPhase ? 'Save Changes' : 'Add Phase'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ============================================
// FITNESS DASHBOARD COMPONENT
// ============================================

interface NutritionGoals {
  calories: number
  protein: number
  carbs: number
  fats: number
}

interface WeightEntry {
  date: string
  raw_weight: number
  trend_weight: number
  weekly_delta: number | null
}

interface PR {
  id: string
  exercise_name: string
  weight: number
  reps: number
  estimated_1rm: number
  achieved_at: string
}

function FitnessDashboard() {
  const [goals, setGoals] = useState<NutritionGoals>({
    calories: 2000,
    protein: 150,
    carbs: 200,
    fats: 70,
  })
  const [todayNutrition, setTodayNutrition] = useState<NutritionGoals>({
    calories: 0,
    protein: 0,
    carbs: 0,
    fats: 0,
  })
  const [showEditModal, setShowEditModal] = useState(false)
  const [editGoals, setEditGoals] = useState<NutritionGoals>(goals)
  const [isRefreshing, setIsRefreshing] = useState(false)

  // New state for weight and PRs
  const [latestWeight, setLatestWeight] = useState<WeightEntry | null>(null)
  const [weightTrend, setWeightTrend] = useState<WeightEntry[]>([])
  const [prs, setPRs] = useState<PR[]>([])
  const [showWeightModal, setShowWeightModal] = useState(false)
  const [newWeight, setNewWeight] = useState('')
  const [activePhase, setActivePhase] = useState<any>(null)

  // Fetch everything on mount
  useEffect(() => {
    // Fetch goals first, then active phase (which may override goals)
    const initializeNutrition = async () => {
      await fetchGoals()
      await fetchActivePhase()
    }
    initializeNutrition()

    fetchTodayNutrition()
    fetchLatestWeight()
    fetchWeightTrend()
    fetchPRs()

    // Auto-refresh nutrition data every 30 seconds
    const interval = setInterval(() => {
      fetchTodayNutrition()
    }, 30000)

    return () => clearInterval(interval)
  }, [])

  const fetchGoals = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/goals`, {
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        setGoals(data)
        setEditGoals(data)
      }
    } catch (error) {
      console.error('Failed to fetch nutrition goals:', error)
    }
  }

  const fetchActivePhase = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/phases/active`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        if (data.phases && data.phases.length > 0) {
          const phase = data.phases[0]
          setActivePhase(phase)
          // Use phase nutrition targets if set (override manual goals)
          setGoals(prev => ({
            calories: phase.calories_target || prev.calories,
            protein: phase.protein_target || prev.protein,
            carbs: phase.carbs_target || prev.carbs,
            fats: phase.fat_target || prev.fats
          }))
          setEditGoals(prev => ({
            calories: phase.calories_target || prev.calories,
            protein: phase.protein_target || prev.protein,
            carbs: phase.carbs_target || prev.carbs,
            fats: phase.fat_target || prev.fats
          }))
        }
      }
    } catch (error) {
      console.error('Failed to fetch active phase:', error)
    }
  }

  const saveGoals = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/goals`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(editGoals),
      })
      if (response.ok) {
        setGoals(editGoals)
        setShowEditModal(false)
      }
    } catch (error) {
      console.error('Failed to save nutrition goals:', error)
    }
  }

  const fetchTodayNutrition = async () => {
    try {
      setIsRefreshing(true)
      const today = new Date().toISOString().split('T')[0]
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/fitness/food-log/summary?start_date=${today}&end_date=${today}`,
        { credentials: 'include' }
      )
      if (response.ok) {
        const data = await response.json()
        const totals = data.statistics?.totals || {}
        setTodayNutrition({
          calories: totals.calories || 0,
          protein: totals.protein || 0,
          carbs: totals.carbs || 0,
          fats: totals.fats || 0,
        })
      }
    } catch (error) {
      console.error('Failed to fetch today nutrition:', error)
    } finally {
      setIsRefreshing(false)
    }
  }

  const fetchLatestWeight = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/weight/latest`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        if (data.raw_weight) {
          setLatestWeight(data)
        }
      }
    } catch (error) {
      console.error('Failed to fetch latest weight:', error)
    }
  }

  const fetchWeightTrend = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/weight/trend?days=30`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setWeightTrend(data.weights || [])
      }
    } catch (error) {
      console.error('Failed to fetch weight trend:', error)
    }
  }

  const fetchPRs = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/prs`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setPRs(data.prs || [])
      }
    } catch (error) {
      console.error('Failed to fetch PRs:', error)
    }
  }

  const logWeight = async () => {
    if (!newWeight) return
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/weight`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          date: new Date().toISOString().split('T')[0],
          raw_weight: parseFloat(newWeight)
        })
      })
      if (response.ok) {
        setShowWeightModal(false)
        setNewWeight('')
        fetchLatestWeight()
        fetchWeightTrend()
      }
    } catch (error) {
      console.error('Failed to log weight:', error)
    }
  }

  const handleManualRefresh = () => {
    fetchTodayNutrition()
    fetchLatestWeight()
    fetchPRs()
  }

  // Calculate progress percentages
  const caloriePercent = Math.min((todayNutrition.calories / goals.calories) * 100, 100)
  const proteinPercent = Math.min((todayNutrition.protein / goals.protein) * 100, 100)

  return (
    <div className="p-6 space-y-6">
      {/* Recovery Trends */}
      <RecoveryTrendChart days={14} compact={true} />

      {/* Active Phase Banner */}
      {activePhase && (
        <div className="bg-gradient-to-r from-blue-900/50 to-purple-900/50 rounded-lg p-4 border border-blue-500/30">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-sm text-blue-300">Active Phase</span>
              <h3 className="font-semibold text-lg">{activePhase.name}</h3>
            </div>
            {activePhase.duration_weeks && (
              <span className="text-sm text-gray-400">{activePhase.duration_weeks} weeks</span>
            )}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Nutrition Card */}
        <div className="bg-gray-800 rounded-lg p-5 border border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="font-semibold">Nutrition Today</h3>
              {activePhase && (
                <span className="text-xs text-blue-400">from {activePhase.name}</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handleManualRefresh}
                disabled={isRefreshing}
                className="p-1 hover:bg-gray-700 rounded transition-colors disabled:opacity-50"
              >
                <RefreshCw className={`w-4 h-4 text-gray-400 ${isRefreshing ? 'animate-spin' : ''}`} />
              </button>
              {!activePhase && (
                <button onClick={() => setShowEditModal(true)} className="p-1 hover:bg-gray-700 rounded">
                  <Settings className="w-4 h-4 text-gray-400" />
                </button>
              )}
            </div>
          </div>

          {/* Calorie Progress Bar */}
          <div className="mb-3">
            <div className="flex justify-between text-sm mb-1">
              <span className="text-gray-400">Calories</span>
              <span>{Math.round(todayNutrition.calories)} / {goals.calories}</span>
            </div>
            <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all ${caloriePercent > 100 ? 'bg-red-500' : 'bg-green-500'}`}
                style={{ width: `${Math.min(caloriePercent, 100)}%` }}
              />
            </div>
          </div>

          {/* Protein Progress Bar */}
          <div className="mb-3">
            <div className="flex justify-between text-sm mb-1">
              <span className="text-gray-400">Protein</span>
              <span>{todayNutrition.protein.toFixed(0)}g / {goals.protein}g</span>
            </div>
            <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all ${proteinPercent >= 100 ? 'bg-green-500' : 'bg-blue-500'}`}
                style={{ width: `${Math.min(proteinPercent, 100)}%` }}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-500">Carbs</span>
              <span>{todayNutrition.carbs.toFixed(0)}g</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Fat</span>
              <span>{todayNutrition.fats.toFixed(0)}g</span>
            </div>
          </div>
        </div>

        {/* Weight Card */}
        <div className="bg-gray-800 rounded-lg p-5 border border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold flex items-center gap-2">
              <Scale className="w-4 h-4 text-purple-400" />
              Weight
            </h3>
            <button
              onClick={() => setShowWeightModal(true)}
              className="text-sm text-blue-400 hover:text-blue-300"
            >
              Log
            </button>
          </div>

          {latestWeight ? (
            <div>
              <div className="text-3xl font-bold">{latestWeight.raw_weight} lbs</div>
              <div className="text-sm text-gray-400 mt-1">
                Trend: {latestWeight.trend_weight} lbs
              </div>
              {latestWeight.weekly_delta !== null && (
                <div className={`text-sm mt-1 flex items-center gap-1 ${
                  latestWeight.weekly_delta < 0 ? 'text-green-400' : latestWeight.weekly_delta > 0 ? 'text-red-400' : 'text-gray-400'
                }`}>
                  {latestWeight.weekly_delta < 0 ? <TrendingUp className="w-4 h-4 rotate-180" /> : latestWeight.weekly_delta > 0 ? <TrendingUp className="w-4 h-4" /> : null}
                  {latestWeight.weekly_delta > 0 ? '+' : ''}{latestWeight.weekly_delta} lbs/week
                </div>
              )}
            </div>
          ) : (
            <div className="text-gray-400 text-sm">No weight logged yet</div>
          )}
        </div>

        {/* PRs Card */}
        <div className="bg-gray-800 rounded-lg p-5 border border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold flex items-center gap-2">
              <Trophy className="w-4 h-4 text-yellow-400" />
              Personal Records
            </h3>
          </div>

          {prs.length > 0 ? (
            <div className="space-y-2">
              {prs.slice(0, 3).map(pr => (
                <div key={pr.id} className="flex justify-between items-center text-sm">
                  <span className="text-gray-300 truncate">{pr.exercise_name}</span>
                  <span className="font-medium">{pr.weight}x{pr.reps}</span>
                </div>
              ))}
              {prs.length > 3 && (
                <div className="text-xs text-gray-500">+{prs.length - 3} more</div>
              )}
            </div>
          ) : (
            <div className="text-gray-400 text-sm">No PRs yet. Start lifting!</div>
          )}
        </div>

        {/* Quick Actions Card */}
        <div className="bg-gray-800 rounded-lg p-5 border border-gray-700">
          <h3 className="font-semibold mb-3">Quick Actions</h3>
          <div className="space-y-2">
            <button className="w-full px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg text-sm font-medium transition-colors">
              Log Meal
            </button>
            <button className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition-colors">
              Log Workout
            </button>
            <button
              onClick={() => setShowWeightModal(true)}
              className="w-full px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-medium transition-colors"
            >
              Log Weight
            </button>
          </div>
        </div>
      </div>

      {/* Weight Trend Chart (simple) */}
      {weightTrend.length > 1 && (
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <h3 className="font-semibold mb-4 flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-purple-400" />
            Weight Trend (30 days)
          </h3>
          <div className="h-32 flex items-end gap-1">
            {weightTrend.map((entry, idx) => {
              const min = Math.min(...weightTrend.map(w => w.raw_weight))
              const max = Math.max(...weightTrend.map(w => w.raw_weight))
              const range = max - min || 1
              const height = ((entry.raw_weight - min) / range) * 100
              return (
                <div
                  key={idx}
                  className="flex-1 bg-purple-500/50 rounded-t hover:bg-purple-500/70 transition-colors"
                  style={{ height: `${Math.max(height, 5)}%` }}
                  title={`${entry.date}: ${entry.raw_weight} lbs`}
                />
              )
            })}
          </div>
          <div className="flex justify-between text-xs text-gray-500 mt-2">
            <span>{weightTrend[0]?.date}</span>
            <span>{weightTrend[weightTrend.length - 1]?.date}</span>
          </div>
        </div>
      )}

      {/* Edit Goals Modal */}
      {showEditModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 w-full max-w-md border border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xl font-semibold">Edit Nutrition Goals</h3>
              <button onClick={() => setShowEditModal(false)} className="p-1 hover:bg-gray-700 rounded">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Daily Calories</label>
                <input
                  type="number"
                  value={editGoals.calories}
                  onChange={(e) => setEditGoals({ ...editGoals, calories: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-green-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Protein (g)</label>
                <input
                  type="number"
                  value={editGoals.protein}
                  onChange={(e) => setEditGoals({ ...editGoals, protein: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-green-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Carbs (g)</label>
                <input
                  type="number"
                  value={editGoals.carbs}
                  onChange={(e) => setEditGoals({ ...editGoals, carbs: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-green-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Fats (g)</label>
                <input
                  type="number"
                  value={editGoals.fats}
                  onChange={(e) => setEditGoals({ ...editGoals, fats: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-green-500"
                />
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowEditModal(false)} className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg">
                Cancel
              </button>
              <button onClick={saveGoals} className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg">
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Log Weight Modal */}
      {showWeightModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 w-full max-w-sm border border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xl font-semibold">Log Weight</h3>
              <button onClick={() => setShowWeightModal(false)} className="p-1 hover:bg-gray-700 rounded">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-1">Weight (lbs)</label>
              <input
                type="number"
                step="0.1"
                value={newWeight}
                onChange={(e) => setNewWeight(e.target.value)}
                placeholder="Enter weight"
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-purple-500 text-lg"
                autoFocus
              />
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowWeightModal(false)} className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg">
                Cancel
              </button>
              <button
                onClick={logWeight}
                disabled={!newWeight}
                className="flex-1 px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg disabled:opacity-50"
              >
                Log
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
