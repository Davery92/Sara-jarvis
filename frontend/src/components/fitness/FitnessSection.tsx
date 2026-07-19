import React, { useState, useEffect } from 'react'
import { Settings, X, RefreshCw, Target, TrendingUp, Trophy, Scale, ChevronDown, ChevronUp, Clock, Zap, Moon } from 'lucide-react'
import FoodLog from './FoodLog'
import WorkoutLog from './WorkoutLogEnhanced'
import FitnessNotes from './FitnessNotes'
import TemplateBuilder from './TemplateBuilder'
import RecoveryLog from './RecoveryLog'
import RecoveryTrendChart from './RecoveryTrendChart'
import PlanView from './PlanView'
import NutritionGuide from './NutritionGuide'
import PlanImporter from './PlanImporter'
import CardioSection from './CardioSection'
import { Upload } from 'lucide-react'
import { APP_CONFIG } from '../../config'

type FitnessView = 'dashboard' | 'food' | 'workout' | 'notes' | 'templates' | 'recovery' | 'programs' | 'plan' | 'nutrition' | 'cardio'

export default function FitnessSection() {
  const [currentView, setCurrentView] = useState<FitnessView>('dashboard')
  const [dashboardKey, setDashboardKey] = useState(0)
  const [nutritionKey, setNutritionKey] = useState(0)
  const [showImporter, setShowImporter] = useState(false)

  const handlePlanApplied = () => {
    // refresh the data-driven views so the new plan/guide shows immediately
    setDashboardKey(prev => prev + 1)
    setNutritionKey(prev => prev + 1)
    setCurrentView('plan')
  }

  // Refresh dashboard when switching to it
  const handleViewChange = (view: FitnessView) => {
    if (view === 'dashboard' && currentView !== 'dashboard') {
      setDashboardKey(prev => prev + 1) // Force dashboard refresh
    }
    setCurrentView(view)
  }

  const tabs = [
    { id: 'dashboard' as FitnessView, label: 'Dashboard' },
    { id: 'plan' as FitnessView, label: 'Plan' },
    { id: 'programs' as FitnessView, label: 'Programs' },
    { id: 'templates' as FitnessView, label: 'Templates' },
    { id: 'recovery' as FitnessView, label: 'Recovery' },
    { id: 'cardio' as FitnessView, label: 'Cardio' },
    { id: 'nutrition' as FitnessView, label: 'Nutrition' },
    { id: 'food' as FitnessView, label: 'Food Log' },
    { id: 'workout' as FitnessView, label: 'Workouts' },
    { id: 'notes' as FitnessView, label: 'Notes' },
  ]

  return (
    <div className="h-full flex flex-col text-white">
      {/* Header */}
      <div className="flex items-center gap-6 border-b border-white/5 px-6">
        <h1 className="font-display text-xl font-semibold text-white py-3 flex-shrink-0">Fitness</h1>

        {/* Tabs */}
        <div
          className="flex gap-5 -mb-px overflow-x-auto scrollbar-hidden scroll-snap-x md:overflow-visible"
          style={{
            overscrollBehaviorX: 'contain',
            WebkitOverflowScrolling: 'touch',
            touchAction: 'pan-x'
          }}
        >
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => handleViewChange(tab.id)}
              className={`border-b-2 px-1 py-3 text-sm transition-colors whitespace-nowrap flex-shrink-0 scroll-snap-center tap-target ${
                currentView === tab.id
                  ? 'text-white border-teal-300'
                  : 'text-slate-500 hover:text-slate-300 border-transparent'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Import plan */}
        <button
          onClick={() => setShowImporter(true)}
          className="ml-auto flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 my-2 bg-white/5 hover:bg-white/10 border border-white/10 hover:border-teal-400/40 rounded-lg text-sm text-slate-300 transition-colors"
          title="Upload a plan document and apply it"
        >
          <Upload className="w-4 h-4" />
          <span className="hidden sm:inline">Import Plan</span>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {currentView === 'dashboard' && <FitnessDashboard key={dashboardKey} />}
        {currentView === 'plan' && <PlanView />}
        {currentView === 'nutrition' && <NutritionGuide key={nutritionKey} />}
        {currentView === 'programs' && <ProgramManager />}
        {currentView === 'templates' && <TemplateBuilder />}
        {currentView === 'recovery' && (
          <div className="p-6 space-y-6">
            <RecoveryLog />
            <RecoveryTrendChart days={30} />
          </div>
        )}
        {currentView === 'cardio' && <CardioSection />}
        {currentView === 'food' && <FoodLog />}
        {currentView === 'workout' && <WorkoutLog />}
        {currentView === 'notes' && <FitnessNotes />}
      </div>

      {showImporter && (
        <PlanImporter onClose={() => setShowImporter(false)} onApplied={handlePlanApplied} />
      )}
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
  calories_training_day: number | null
  calories_rest_day: number | null
  carbs_training_day: number | null
  carbs_rest_day: number | null
  fat_training_day: number | null
  fat_rest_day: number | null
  training_days_per_week: number | null
  deload_week: number | null
  daily_steps_target: number | null
  status: string
}

interface TemplateExercise {
  name: string
  sets: number
  reps: string
  rest_seconds?: number
  notes?: string
  set_technique?: string
  is_per_side?: boolean
}

interface WorkoutTemplate {
  id: string
  name: string
  phase_id: string
  scheduled_days: string[]
  exercises: TemplateExercise[]
  notes?: string
  order_in_phase?: number
}

function ProgramManager() {
  const [programs, setPrograms] = useState<Program[]>([])
  const [activeProgram, setActiveProgram] = useState<Program | null>(null)
  const [activePhases, setActivePhases] = useState<Phase[]>([])
  const [templates, setTemplates] = useState<WorkoutTemplate[]>([])
  const [expandedPhases, setExpandedPhases] = useState<Set<string>>(new Set())
  const [expandedWorkouts, setExpandedWorkouts] = useState<Set<string>>(new Set())
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showPhaseModal, setShowPhaseModal] = useState(false)
  const [editingPhase, setEditingPhase] = useState<Phase | null>(null)
  const [showManageMode, setShowManageMode] = useState(false)
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
    fetchTemplates()
  }, [])

  // Auto-expand active phase
  useEffect(() => {
    const active = activePhases.find(p => p.status === 'active')
    if (active) setExpandedPhases(new Set([active.id]))
  }, [activePhases])

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

  const fetchTemplates = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/templates?active_only=false`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setTemplates(data.templates || [])
      }
    } catch (error) {
      console.error('Failed to fetch templates:', error)
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
        fetchTemplates()
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
        fetchActiveProgram()
        fetchTemplates()
      } else {
        alert(`Failed to activate phase: ${data.detail || 'Unknown error'}`)
      }
    } catch (error) {
      console.error('Failed to activate phase:', error)
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
        alert(`Failed to update phase: ${data.detail || 'Unknown error'}`)
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
        alert(`Failed to delete phase: ${data.detail || 'Unknown error'}`)
      }
    } catch (error) {
      console.error('Failed to delete phase:', error)
    }
  }

  const togglePhase = (phaseId: string) => {
    const next = new Set(expandedPhases)
    if (next.has(phaseId)) next.delete(phaseId)
    else next.add(phaseId)
    setExpandedPhases(next)
  }

  const toggleWorkout = (templateId: string) => {
    const next = new Set(expandedWorkouts)
    if (next.has(templateId)) next.delete(templateId)
    else next.add(templateId)
    setExpandedWorkouts(next)
  }

  const getPhaseTemplates = (phaseId: string) => {
    return templates
      .filter(t => t.phase_id === phaseId)
      .sort((a, b) => {
        // Sort by session order: Lower A, Upper A, Lower B, Upper B
        const order = ['lower a', 'upper a', 'lower b', 'upper b']
        const aIdx = order.findIndex(o => a.name.toLowerCase().includes(o))
        const bIdx = order.findIndex(o => b.name.toLowerCase().includes(o))
        if (aIdx !== -1 && bIdx !== -1) return aIdx - bIdx
        return (a.order_in_phase || 0) - (b.order_in_phase || 0)
      })
  }

  const goalColors: Record<string, string> = {
    cut: 'text-red-400 bg-red-400/10 border-red-500/30',
    bulk: 'text-green-400 bg-green-400/10 border-green-500/30',
    maintenance: 'text-blue-400 bg-blue-400/10 border-blue-500/30',
    recomp: 'text-purple-400 bg-purple-400/10 border-purple-500/30',
    strength: 'text-orange-400 bg-orange-400/10 border-orange-500/30'
  }

  const sessionLabels: Record<string, { icon: string; color: string }> = {
    'lower a': { icon: '🦵', color: 'text-amber-400' },
    'upper a': { icon: '💪', color: 'text-blue-400' },
    'lower b': { icon: '🦵', color: 'text-amber-400' },
    'upper b': { icon: '💪', color: 'text-blue-400' },
  }

  const getSessionMeta = (name: string) => {
    const lower = name.toLowerCase()
    for (const [key, meta] of Object.entries(sessionLabels)) {
      if (lower.includes(key)) return meta
    }
    return { icon: '', color: 'text-gray-400' }
  }

  return (
    <div className="p-4 sm:p-6 space-y-4">
      {/* Program Header */}
      {activeProgram ? (
        <div className="bg-gradient-to-br from-gray-800 to-gray-800/80 rounded-md p-5 border border-gray-700">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-3 flex-wrap">
                <h2 className="text-xl sm:text-2xl font-bold">{activeProgram.name}</h2>
                <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${goalColors[activeProgram.goal] || 'text-gray-400 bg-gray-700 border-gray-600'}`}>
                  {activeProgram.goal.charAt(0).toUpperCase() + activeProgram.goal.slice(1)}
                </span>
              </div>
              {activeProgram.notes && (
                <p className="text-sm text-gray-400 mt-2 line-clamp-2">{activeProgram.notes}</p>
              )}
              {activeProgram.start_date && (
                <div className="flex items-center gap-4 mt-3 text-sm text-gray-500">
                  <span>Started {new Date(activeProgram.start_date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</span>
                  <span>{activePhases.length} phases</span>
                  <span>{activePhases.find(p => p.status === 'active')?.training_days_per_week || 4} days/week</span>
                </div>
              )}
            </div>
            <button
              onClick={() => setShowManageMode(!showManageMode)}
              className={`p-2 rounded-lg transition-colors flex-shrink-0 ${showManageMode ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400 hover:text-white'}`}
            >
              <Settings className="w-5 h-5" />
            </button>
          </div>
        </div>
      ) : (
        <div className="bg-gray-800 rounded-md p-8 border border-gray-700 text-center">
          <Target className="w-10 h-10 text-gray-600 mx-auto mb-3" />
          <p className="text-gray-400 mb-4">No active program</p>
          <button
            onClick={() => setShowCreateModal(true)}
            className="px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-colors"
          >
            Create Program
          </button>
        </div>
      )}

      {/* Phase Timeline */}
      {activePhases.length > 0 && (
        <div className="space-y-3">
          {activePhases.map((phase, idx) => {
            const isActive = phase.status === 'active'
            const isExpanded = expandedPhases.has(phase.id)
            const phaseTemplates = getPhaseTemplates(phase.id)
            const hasCycling = phase.calories_training_day && phase.calories_rest_day

            return (
              <div
                key={phase.id}
                className={`rounded-md border overflow-hidden transition-all ${
                  isActive
                    ? 'bg-gray-800 border-blue-500/60 shadow-lg shadow-blue-500/5'
                    : 'bg-gray-800/60 border-gray-700'
                }`}
              >
                {/* Phase Header */}
                <button
                  onClick={() => togglePhase(phase.id)}
                  className="w-full p-4 flex items-center gap-3 text-left tap-target"
                >
                  <div className="flex-shrink-0">
                    {isExpanded ? (
                      <ChevronDown className="w-5 h-5 text-gray-400" />
                    ) : (
                      <ChevronUp className="w-5 h-5 text-gray-400 rotate-180" />
                    )}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-base truncate">{phase.name}</span>
                      {isActive && (
                        <span className="text-xs font-medium px-2 py-0.5 bg-green-500/20 text-green-400 rounded-full flex-shrink-0">
                          Active
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-sm text-gray-500 mt-0.5">
                      {phase.duration_weeks && <span>{phase.duration_weeks} weeks</span>}
                      <span>{phaseTemplates.length} workouts</span>
                      {phase.deload_week ? <span>Deload wk {phase.deload_week}</span> : null}
                    </div>
                  </div>

                  {/* Quick Nutrition Badge */}
                  {phase.protein_target && (
                    <div className="hidden sm:flex items-center gap-2 text-xs text-gray-500 flex-shrink-0">
                      <span>{phase.protein_target}P</span>
                      {hasCycling ? (
                        <>
                          <span className="text-green-400">{phase.calories_training_day}</span>
                          <span>/</span>
                          <span className="text-yellow-400">{phase.calories_rest_day}</span>
                          <span>cal</span>
                        </>
                      ) : (
                        <span>{phase.calories_target} cal</span>
                      )}
                    </div>
                  )}
                </button>

                {/* Expanded Phase Content */}
                {isExpanded && (
                  <div className="border-t border-gray-700">
                    {/* Nutrition Detail */}
                    {phase.protein_target && (
                      <div className="px-4 py-3 bg-gray-900/50">
                        {hasCycling ? (
                          <div className="grid grid-cols-2 gap-3">
                            <div className="bg-green-900/20 rounded-lg p-3 border border-green-500/20">
                              <div className="text-xs text-green-400 font-medium mb-1.5 flex items-center gap-1">
                                <Zap className="w-3 h-3" />
                                Training Day
                              </div>
                              <div className="grid grid-cols-3 gap-2 text-sm">
                                <div>
                                  <div className="text-gray-500 text-xs">Cal</div>
                                  <div className="font-semibold">{phase.calories_training_day}</div>
                                </div>
                                <div>
                                  <div className="text-gray-500 text-xs">Carbs</div>
                                  <div className="font-semibold">{phase.carbs_training_day}g</div>
                                </div>
                                <div>
                                  <div className="text-gray-500 text-xs">Fat</div>
                                  <div className="font-semibold">{phase.fat_training_day}g</div>
                                </div>
                              </div>
                            </div>
                            <div className="bg-yellow-900/20 rounded-lg p-3 border border-yellow-500/20">
                              <div className="text-xs text-yellow-400 font-medium mb-1.5 flex items-center gap-1">
                                <Clock className="w-3 h-3" />
                                Rest Day
                              </div>
                              <div className="grid grid-cols-3 gap-2 text-sm">
                                <div>
                                  <div className="text-gray-500 text-xs">Cal</div>
                                  <div className="font-semibold">{phase.calories_rest_day}</div>
                                </div>
                                <div>
                                  <div className="text-gray-500 text-xs">Carbs</div>
                                  <div className="font-semibold">{phase.carbs_rest_day}g</div>
                                </div>
                                <div>
                                  <div className="text-gray-500 text-xs">Fat</div>
                                  <div className="font-semibold">{phase.fat_rest_day}g</div>
                                </div>
                              </div>
                            </div>
                            <div className="col-span-2 flex items-center gap-4 text-sm text-gray-400 px-1">
                              <span>Protein: <span className="text-white font-medium">{phase.protein_target}g</span> daily</span>
                              {phase.daily_steps_target && (
                                <span>Steps: <span className="text-white font-medium">{phase.daily_steps_target?.toLocaleString()}</span></span>
                              )}
                            </div>
                          </div>
                        ) : (
                          <div className="grid grid-cols-4 gap-3 text-sm">
                            <div>
                              <div className="text-gray-500 text-xs">Calories</div>
                              <div className="font-semibold">{phase.calories_target}</div>
                            </div>
                            <div>
                              <div className="text-gray-500 text-xs">Protein</div>
                              <div className="font-semibold">{phase.protein_target}g</div>
                            </div>
                            <div>
                              <div className="text-gray-500 text-xs">Carbs</div>
                              <div className="font-semibold">{phase.carbs_target}g</div>
                            </div>
                            <div>
                              <div className="text-gray-500 text-xs">Fat</div>
                              <div className="font-semibold">{phase.fat_target}g</div>
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Workouts */}
                    <div className="p-3 space-y-2">
                      {phaseTemplates.length > 0 ? (
                        phaseTemplates.map((template, tIdx) => {
                          const isWExpanded = expandedWorkouts.has(template.id)
                          const meta = getSessionMeta(template.name)
                          // Extract session label (e.g., "Lower A — Squat Focus" from "P1 Lower A — Squat Focus")
                          const displayName = template.name.replace(/^P\d+\s+/, '')

                          return (
                            <div key={template.id} className="bg-gray-900/70 rounded-lg overflow-hidden">
                              <button
                                onClick={() => toggleWorkout(template.id)}
                                className="w-full px-4 py-3 flex items-center gap-3 text-left tap-target"
                              >
                                <span className="text-lg flex-shrink-0">{meta.icon}</span>
                                <div className="flex-1 min-w-0">
                                  <div className="font-medium text-sm truncate">{displayName}</div>
                                  <div className="text-xs text-gray-500">{template.exercises.length} exercises</div>
                                </div>
                                <div className="flex-shrink-0 text-xs text-gray-600">
                                  Session {tIdx + 1}
                                </div>
                                {isWExpanded ? (
                                  <ChevronDown className="w-4 h-4 text-gray-500 flex-shrink-0" />
                                ) : (
                                  <ChevronUp className="w-4 h-4 text-gray-500 flex-shrink-0 rotate-180" />
                                )}
                              </button>

                              {isWExpanded && (
                                <div className="px-4 pb-3 space-y-1">
                                  {template.exercises.map((ex, eIdx) => (
                                    <div key={eIdx} className="flex items-baseline justify-between py-1.5 border-b border-gray-800 last:border-0">
                                      <div className="min-w-0">
                                        <span className="text-sm">{ex.name}</span>
                                        {ex.notes && (
                                          <span className="text-xs text-gray-600 ml-2">{ex.notes}</span>
                                        )}
                                      </div>
                                      <div className="flex items-center gap-2 text-sm text-gray-400 flex-shrink-0 ml-3">
                                        <span className="font-mono">{ex.sets}x{ex.reps}</span>
                                        {ex.rest_seconds && (
                                          <span className="text-xs text-gray-600">{ex.rest_seconds >= 60 ? `${Math.floor(ex.rest_seconds / 60)}m` : `${ex.rest_seconds}s`}</span>
                                        )}
                                        {ex.set_technique && (
                                          <span className="text-xs px-1.5 py-0.5 bg-purple-500/20 text-purple-400 rounded">
                                            {ex.set_technique.replace('_', ' ')}
                                          </span>
                                        )}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          )
                        })
                      ) : (
                        <div className="text-center text-gray-500 text-sm py-4">
                          No workouts in this phase yet
                        </div>
                      )}
                    </div>

                    {/* Phase Actions (manage mode) */}
                    {showManageMode && (
                      <div className="px-4 pb-3 flex gap-2 border-t border-gray-700 pt-3">
                        <button
                          onClick={() => openEditPhase(phase)}
                          className="flex-1 py-2.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium transition-colors"
                        >
                          Edit Phase
                        </button>
                        {!isActive && (
                          <button
                            onClick={() => activatePhase(phase.id)}
                            className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition-colors"
                          >
                            Activate
                          </button>
                        )}
                        <button
                          onClick={() => deletePhase(phase.id)}
                          className="py-2.5 px-4 bg-red-600/20 hover:bg-red-600/30 text-red-400 rounded-lg text-sm font-medium transition-colors"
                        >
                          Delete
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}

          {/* Add Phase (manage mode) */}
          {showManageMode && (
            <button
              onClick={() => { setEditingPhase(null); setShowPhaseModal(true); }}
              className="w-full py-3 border-2 border-dashed border-gray-700 hover:border-gray-500 rounded-md text-gray-500 hover:text-gray-300 text-sm font-medium transition-colors"
            >
              + Add Phase
            </button>
          )}
        </div>
      )}

      {/* All Programs (manage mode) */}
      {showManageMode && programs.length > 0 && (
        <div className="bg-gray-800 rounded-md p-5 border border-gray-700">
          <h3 className="text-lg font-semibold mb-3">All Programs</h3>
          <div className="space-y-2">
            {programs.map(program => (
              <div
                key={program.id}
                className={`p-4 rounded-lg border flex items-center justify-between ${
                  program.is_active ? 'bg-blue-900/20 border-blue-500/50' : 'bg-gray-700/50 border-gray-600'
                }`}
              >
                <div>
                  <div className="font-medium">{program.name}</div>
                  <span className={`text-xs px-2 py-0.5 rounded ${goalColors[program.goal]?.split(' ').slice(0, 2).join(' ') || 'text-gray-400 bg-gray-700'}`}>
                    {program.goal}
                  </span>
                </div>
                {!program.is_active && (
                  <button
                    onClick={() => activateProgram(program.id)}
                    className="text-sm px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium"
                  >
                    Activate
                  </button>
                )}
              </div>
            ))}
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="mt-3 w-full py-3 border-2 border-dashed border-gray-700 hover:border-gray-500 rounded-lg text-gray-500 hover:text-gray-300 text-sm font-medium transition-colors"
          >
            + Create New Program
          </button>
        </div>
      )}

      {/* Create Program Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-md p-6 w-full max-w-md border border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xl font-semibold">Create Program</h3>
              <button onClick={() => setShowCreateModal(false)} className="p-2 hover:bg-gray-700 rounded-lg">
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
                  className="w-full px-3 py-3 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500 text-base"
                />
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">Goal</label>
                <select
                  value={newProgram.goal}
                  onChange={e => setNewProgram({ ...newProgram, goal: e.target.value })}
                  className="w-full px-3 py-3 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500 text-base"
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
                    className="w-full px-3 py-3 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">End Date</label>
                  <input
                    type="date"
                    value={newProgram.end_date}
                    onChange={e => setNewProgram({ ...newProgram, end_date: e.target.value })}
                    className="w-full px-3 py-3 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">Notes</label>
                <textarea
                  value={newProgram.notes}
                  onChange={e => setNewProgram({ ...newProgram, notes: e.target.value })}
                  rows={2}
                  className="w-full px-3 py-3 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setShowCreateModal(false)}
                className="flex-1 px-4 py-3 bg-gray-700 hover:bg-gray-600 rounded-lg font-medium"
              >
                Cancel
              </button>
              <button
                onClick={createProgram}
                disabled={!newProgram.name}
                className="flex-1 px-4 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium disabled:opacity-50"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create/Edit Phase Modal */}
      {showPhaseModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-md p-6 w-full max-w-md border border-gray-700 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xl font-semibold">{editingPhase ? 'Edit Phase' : 'Add Phase'}</h3>
              <button onClick={() => { setShowPhaseModal(false); setEditingPhase(null); }} className="p-2 hover:bg-gray-700 rounded-lg">
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
                  className="w-full px-3 py-3 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500 text-base"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Duration (weeks)</label>
                  <input
                    type="number"
                    value={newPhase.duration_weeks}
                    onChange={e => setNewPhase({ ...newPhase, duration_weeks: parseInt(e.target.value) || 0 })}
                    className="w-full px-3 py-3 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Training Days/Week</label>
                  <input
                    type="number"
                    value={newPhase.training_days_per_week}
                    onChange={e => setNewPhase({ ...newPhase, training_days_per_week: parseInt(e.target.value) || 0 })}
                    className="w-full px-3 py-3 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
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
                      className="w-full px-3 py-3 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">Protein (g)</label>
                    <input
                      type="number"
                      value={newPhase.protein_target}
                      onChange={e => setNewPhase({ ...newPhase, protein_target: parseInt(e.target.value) || 0 })}
                      className="w-full px-3 py-3 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">Carbs (g)</label>
                    <input
                      type="number"
                      value={newPhase.carbs_target}
                      onChange={e => setNewPhase({ ...newPhase, carbs_target: parseInt(e.target.value) || 0 })}
                      className="w-full px-3 py-3 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">Fat (g)</label>
                    <input
                      type="number"
                      value={newPhase.fat_target}
                      onChange={e => setNewPhase({ ...newPhase, fat_target: parseInt(e.target.value) || 0 })}
                      className="w-full px-3 py-3 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
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
                  className="w-full px-3 py-3 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => { setShowPhaseModal(false); setEditingPhase(null); }}
                className="flex-1 px-4 py-3 bg-gray-700 hover:bg-gray-600 rounded-lg font-medium"
              >
                Cancel
              </button>
              <button
                onClick={editingPhase ? updatePhase : createPhase}
                disabled={!newPhase.name}
                className="flex-1 px-4 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium disabled:opacity-50"
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
  const [isTrainingDay, setIsTrainingDay] = useState<boolean | null>(null)
  const [togglingTrainingDay, setTogglingTrainingDay] = useState(false)

  // Fetch everything on mount
  useEffect(() => {
    // Fetch goals first, then active phase (which may override goals)
    const initializeNutrition = async () => {
      await fetchGoals()
      await fetchActivePhase()
      await fetchTodayTarget()
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

  const fetchTodayTarget = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/today-target`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setIsTrainingDay(data.is_training_day)
        // If phase provides targets, use them
        if (data.target) {
          setGoals(prev => ({
            calories: data.target.calories || prev.calories,
            protein: data.target.protein || prev.protein,
            carbs: data.target.carbs || prev.carbs,
            fats: data.target.fat || prev.fats,
          }))
          setEditGoals(prev => ({
            calories: data.target.calories || prev.calories,
            protein: data.target.protein || prev.protein,
            carbs: data.target.carbs || prev.carbs,
            fats: data.target.fat || prev.fats,
          }))
        }
      }
    } catch (error) {
      console.error('Failed to fetch today target:', error)
    }
  }

  const toggleTrainingDay = async () => {
    setTogglingTrainingDay(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/toggle-training-day`, {
        method: 'POST',
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setIsTrainingDay(data.is_training_day)
        // Re-fetch targets since macros change with training day state
        await fetchTodayTarget()
      }
    } catch (error) {
      console.error('Failed to toggle training day:', error)
    } finally {
      setTogglingTrainingDay(false)
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
        <div className="assistant-panel rounded-xl p-4 bg-gradient-to-r from-teal-500/10 to-cyan-500/5">
          <div className="flex items-center justify-between">
            <div>
              <span className="assistant-kicker text-teal-300">Active Phase</span>
              <h3 className="font-display font-semibold text-lg mt-1">{activePhase.name}</h3>
            </div>
            {activePhase.duration_weeks && (
              <span className="text-sm text-slate-400">{activePhase.duration_weeks} weeks</span>
            )}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Nutrition Card */}
        <div className="assistant-panel rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="font-display font-semibold">Nutrition Today</h3>
              {activePhase && (
                <span className="text-xs text-teal-300">from {activePhase.name}</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {isTrainingDay !== null && (
                <button
                  onClick={toggleTrainingDay}
                  disabled={togglingTrainingDay}
                  className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors ${
                    isTrainingDay
                      ? 'bg-yellow-900/50 text-yellow-300 hover:bg-yellow-800/50 border border-yellow-700/50'
                      : 'bg-indigo-900/50 text-indigo-300 hover:bg-indigo-800/50 border border-indigo-700/50'
                  } disabled:opacity-50`}
                  title={isTrainingDay ? 'Switch to rest day' : 'Switch to training day'}
                >
                  {isTrainingDay ? <Zap className="w-3 h-3" /> : <Moon className="w-3 h-3" />}
                  {isTrainingDay ? 'Training' : 'Rest'}
                </button>
              )}
              <button
                onClick={handleManualRefresh}
                disabled={isRefreshing}
                className="p-1 hover:bg-white/10 rounded transition-colors disabled:opacity-50"
              >
                <RefreshCw className={`w-4 h-4 text-slate-400 ${isRefreshing ? 'animate-spin' : ''}`} />
              </button>
              {!activePhase && (
                <button onClick={() => setShowEditModal(true)} className="p-1 hover:bg-white/10 rounded">
                  <Settings className="w-4 h-4 text-slate-400" />
                </button>
              )}
            </div>
          </div>

          {/* Calorie Progress Bar */}
          <div className="mb-3">
            <div className="flex justify-between text-sm mb-1">
              <span className="text-slate-400">Calories</span>
              <span>{Math.round(todayNutrition.calories)} / {goals.calories}</span>
            </div>
            <div className="h-2 bg-white/10 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all ${caloriePercent > 100 ? 'bg-rose-500' : 'bg-teal-400'}`}
                style={{ width: `${Math.min(caloriePercent, 100)}%` }}
              />
            </div>
          </div>

          {/* Protein Progress Bar */}
          <div className="mb-3">
            <div className="flex justify-between text-sm mb-1">
              <span className="text-slate-400">Protein</span>
              <span>{todayNutrition.protein.toFixed(0)}g / {goals.protein}g</span>
            </div>
            <div className="h-2 bg-white/10 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all ${proteinPercent >= 100 ? 'bg-teal-400' : 'bg-cyan-400/70'}`}
                style={{ width: `${Math.min(proteinPercent, 100)}%` }}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-500">Carbs</span>
              <span>{todayNutrition.carbs.toFixed(0)}g</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Fat</span>
              <span>{todayNutrition.fats.toFixed(0)}g</span>
            </div>
          </div>
        </div>

        {/* Weight Card */}
        <div className="assistant-panel rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-display font-semibold flex items-center gap-2">
              <Scale className="w-4 h-4 text-teal-300" />
              Weight
            </h3>
            <button
              onClick={() => setShowWeightModal(true)}
              className="text-sm text-teal-300 hover:text-teal-200"
            >
              Log
            </button>
          </div>

          {latestWeight ? (
            <div>
              <div className="text-3xl font-bold">{latestWeight.raw_weight} lbs</div>
              <div className="text-sm text-slate-400 mt-1">
                Trend: {latestWeight.trend_weight} lbs
              </div>
              {latestWeight.weekly_delta !== null && (
                <div className={`text-sm mt-1 flex items-center gap-1 ${
                  latestWeight.weekly_delta < 0 ? 'text-green-400' : latestWeight.weekly_delta > 0 ? 'text-red-400' : 'text-slate-400'
                }`}>
                  {latestWeight.weekly_delta < 0 ? <TrendingUp className="w-4 h-4 rotate-180" /> : latestWeight.weekly_delta > 0 ? <TrendingUp className="w-4 h-4" /> : null}
                  {latestWeight.weekly_delta > 0 ? '+' : ''}{latestWeight.weekly_delta} lbs/week
                </div>
              )}
            </div>
          ) : (
            <div className="text-slate-400 text-sm">No weight logged yet</div>
          )}
        </div>

        {/* PRs Card */}
        <div className="assistant-panel rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-display font-semibold flex items-center gap-2">
              <Trophy className="w-4 h-4 text-amber-300" />
              Personal Records
            </h3>
          </div>

          {prs.length > 0 ? (
            <div className="space-y-2">
              {prs.slice(0, 3).map(pr => (
                <div key={pr.id} className="flex justify-between items-center text-sm">
                  <span className="text-slate-300 truncate">{pr.exercise_name}</span>
                  <span className="font-medium">{pr.weight}x{pr.reps}</span>
                </div>
              ))}
              {prs.length > 3 && (
                <div className="text-xs text-slate-500">+{prs.length - 3} more</div>
              )}
            </div>
          ) : (
            <div className="text-slate-400 text-sm">No PRs yet. Start lifting!</div>
          )}
        </div>

        {/* Quick Actions Card */}
        <div className="assistant-panel rounded-xl p-5">
          <h3 className="font-display font-semibold mb-3">Quick Actions</h3>
          <div className="space-y-2">
            <button className="w-full px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 hover:border-teal-400/40 rounded-lg text-sm font-medium text-slate-200 transition-colors">
              Log Meal
            </button>
            <button className="w-full px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 hover:border-teal-400/40 rounded-lg text-sm font-medium text-slate-200 transition-colors">
              Log Workout
            </button>
            <button
              onClick={() => setShowWeightModal(true)}
              className="w-full px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 hover:border-teal-400/40 rounded-lg text-sm font-medium text-slate-200 transition-colors"
            >
              Log Weight
            </button>
          </div>
        </div>
      </div>

      {/* Weight Trend Chart (simple) */}
      {weightTrend.length > 1 && (
        <div className="assistant-panel rounded-xl p-6">
          <h3 className="font-display font-semibold mb-4 flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-teal-300" />
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
                  className="flex-1 bg-teal-400/40 rounded-t hover:bg-teal-400/70 transition-colors"
                  style={{ height: `${Math.max(height, 5)}%` }}
                  title={`${entry.date}: ${entry.raw_weight} lbs`}
                />
              )
            })}
          </div>
          <div className="flex justify-between text-xs text-slate-500 mt-2">
            <span>{weightTrend[0]?.date}</span>
            <span>{weightTrend[weightTrend.length - 1]?.date}</span>
          </div>
        </div>
      )}

      {/* Edit Goals Modal */}
      {showEditModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="assistant-panel rounded-xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-display text-xl font-semibold">Edit Nutrition Goals</h3>
              <button onClick={() => setShowEditModal(false)} className="p-1 hover:bg-white/10 rounded">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-slate-400 mb-1">Daily Calories</label>
                <input
                  type="number"
                  value={editGoals.calories}
                  onChange={(e) => setEditGoals({ ...editGoals, calories: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg focus:outline-none focus:border-teal-400/60 focus:ring-1 focus:ring-teal-400/30 text-white"
                />
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">Protein (g)</label>
                <input
                  type="number"
                  value={editGoals.protein}
                  onChange={(e) => setEditGoals({ ...editGoals, protein: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg focus:outline-none focus:border-teal-400/60 focus:ring-1 focus:ring-teal-400/30 text-white"
                />
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">Carbs (g)</label>
                <input
                  type="number"
                  value={editGoals.carbs}
                  onChange={(e) => setEditGoals({ ...editGoals, carbs: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg focus:outline-none focus:border-teal-400/60 focus:ring-1 focus:ring-teal-400/30 text-white"
                />
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">Fats (g)</label>
                <input
                  type="number"
                  value={editGoals.fats}
                  onChange={(e) => setEditGoals({ ...editGoals, fats: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg focus:outline-none focus:border-teal-400/60 focus:ring-1 focus:ring-teal-400/30 text-white"
                />
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowEditModal(false)} className="flex-1 px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-slate-200 transition-colors">
                Cancel
              </button>
              <button onClick={saveGoals} className="flex-1 px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white rounded-lg transition-colors">
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Log Weight Modal */}
      {showWeightModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="assistant-panel rounded-xl p-6 w-full max-w-sm">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-display text-xl font-semibold">Log Weight</h3>
              <button onClick={() => setShowWeightModal(false)} className="p-1 hover:bg-white/10 rounded">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div>
              <label className="block text-sm text-slate-400 mb-1">Weight (lbs)</label>
              <input
                type="number"
                step="0.1"
                value={newWeight}
                onChange={(e) => setNewWeight(e.target.value)}
                placeholder="Enter weight"
                className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg focus:outline-none focus:border-teal-400/60 focus:ring-1 focus:ring-teal-400/30 text-white text-lg"
                autoFocus
              />
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowWeightModal(false)} className="flex-1 px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-slate-200 transition-colors">
                Cancel
              </button>
              <button
                onClick={logWeight}
                disabled={!newWeight}
                className="flex-1 px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white rounded-lg disabled:opacity-50 transition-colors"
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
