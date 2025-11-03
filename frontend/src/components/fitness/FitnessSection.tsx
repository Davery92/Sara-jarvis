import React, { useState, useEffect } from 'react'
import { Dumbbell, Apple, FileText, Mic, Activity, Settings, X, MessageCircle, Calendar, Heart, RefreshCw } from 'lucide-react'
import FoodLog from './FoodLog'
import WorkoutLog from './WorkoutLogEnhanced'
import FitnessNotes from './FitnessNotes'
import FitnessVoice from './FitnessVoice'
import FitnessChat from './FitnessChat'
import PhaseManager from './PhaseManager'
import TemplateBuilder from './TemplateBuilder'
import RecoveryLog from './RecoveryLog'
import RecoveryTrendChart from './RecoveryTrendChart'
import { APP_CONFIG } from '../../config'

type FitnessView = 'dashboard' | 'food' | 'workout' | 'notes' | 'voice' | 'chat' | 'templates' | 'recovery'

export default function FitnessSection() {
  const [currentView, setCurrentView] = useState<FitnessView>('dashboard')
  const [templatesSubView, setTemplatesSubView] = useState<'phases' | 'templates'>('templates')
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
    { id: 'chat' as FitnessView, label: 'Chat', icon: MessageCircle },
    { id: 'templates' as FitnessView, label: 'Templates', icon: Calendar },
    { id: 'recovery' as FitnessView, label: 'Recovery', icon: Heart },
    { id: 'food' as FitnessView, label: 'Food Log', icon: Apple },
    { id: 'workout' as FitnessView, label: 'Workouts', icon: Dumbbell },
    { id: 'notes' as FitnessView, label: 'Notes', icon: FileText },
    { id: 'voice' as FitnessView, label: 'Voice', icon: Mic },
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
        {currentView === 'chat' && <FitnessChat />}
        {currentView === 'templates' && (
          <div className="h-full flex flex-col">
            <div className="flex gap-2 p-4 border-b border-gray-700 bg-gray-800">
              <button
                onClick={() => setTemplatesSubView('templates')}
                className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                  templatesSubView === 'templates'
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-700 text-gray-400 hover:bg-gray-600 hover:text-white'
                }`}
              >
                Workout Templates
              </button>
              <button
                onClick={() => setTemplatesSubView('phases')}
                className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                  templatesSubView === 'phases'
                    ? 'bg-purple-600 text-white'
                    : 'bg-gray-700 text-gray-400 hover:bg-gray-600 hover:text-white'
                }`}
              >
                Training Phases
              </button>
            </div>
            <div className="flex-1 overflow-auto">
              {templatesSubView === 'templates' ? <TemplateBuilder /> : <PhaseManager />}
            </div>
          </div>
        )}
        {currentView === 'recovery' && (
          <div className="p-6 space-y-6">
            <RecoveryLog />
            <RecoveryTrendChart days={30} />
          </div>
        )}
        {currentView === 'food' && <FoodLog />}
        {currentView === 'workout' && <WorkoutLog />}
        {currentView === 'notes' && <FitnessNotes />}
        {currentView === 'voice' && <FitnessVoice />}
      </div>
    </div>
  )
}

interface NutritionGoals {
  calories: number
  protein: number
  carbs: number
  fats: number
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

  // Fetch nutrition goals and today's summary on mount and refresh every 30 seconds
  useEffect(() => {
    fetchGoals()
    fetchTodayNutrition()

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
        console.log('Dashboard nutrition data:', data)
        // Backend returns nested structure: data.statistics.totals
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

  const handleManualRefresh = () => {
    fetchTodayNutrition()
  }

  return (
    <div className="p-6 space-y-6">
      {/* Recovery Trends */}
      <RecoveryTrendChart days={14} compact={true} />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* Nutrition Card */}
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold">Nutrition Today</h3>
            <div className="flex items-center gap-2">
              <button
                onClick={handleManualRefresh}
                disabled={isRefreshing}
                className="p-1 hover:bg-gray-700 rounded transition-colors disabled:opacity-50"
                title="Refresh nutrition data"
              >
                <RefreshCw className={`w-4 h-4 text-gray-400 hover:text-white ${isRefreshing ? 'animate-spin' : ''}`} />
              </button>
              <button
                onClick={() => setShowEditModal(true)}
                className="p-1 hover:bg-gray-700 rounded transition-colors"
                title="Edit nutrition goals"
              >
                <Settings className="w-4 h-4 text-gray-400 hover:text-white" />
              </button>
              <Apple className="w-5 h-5 text-green-400" />
            </div>
          </div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-400">Calories</span>
              <span className="font-medium">{Math.round(todayNutrition.calories)} / {goals.calories}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Protein</span>
              <span className="font-medium">{todayNutrition.protein.toFixed(1)}g / {goals.protein}g</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Carbs</span>
              <span className="font-medium">{todayNutrition.carbs.toFixed(1)}g / {goals.carbs}g</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Fats</span>
              <span className="font-medium">{todayNutrition.fats.toFixed(1)}g / {goals.fats}g</span>
            </div>
          </div>
        </div>

        {/* Workout Card */}
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold">Workouts This Week</h3>
            <Dumbbell className="w-5 h-5 text-blue-400" />
          </div>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-400">Total Workouts</span>
              <span className="font-medium">0</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Total Sets</span>
              <span className="font-medium">0</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Total Volume</span>
              <span className="font-medium">0 lbs</span>
            </div>
          </div>
        </div>

        {/* Quick Actions Card */}
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <h3 className="text-lg font-semibold mb-4">Quick Actions</h3>
          <div className="space-y-2">
            <button className="w-full px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg text-sm font-medium transition-colors">
              Log Meal
            </button>
            <button className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition-colors">
              Log Workout
            </button>
            <button className="w-full px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-medium transition-colors">
              Add Note
            </button>
          </div>
        </div>
      </div>

      {/* Recent Activity */}
      <div className="mt-6 bg-gray-800 rounded-lg p-6 border border-gray-700">
        <h3 className="text-lg font-semibold mb-4">Recent Activity</h3>
        <div className="text-center text-gray-400 py-8">
          No recent activity. Start logging your meals and workouts!
        </div>
      </div>

      {/* Edit Goals Modal */}
      {showEditModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 w-full max-w-md border border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xl font-semibold">Edit Nutrition Goals</h3>
              <button
                onClick={() => setShowEditModal(false)}
                className="p-1 hover:bg-gray-700 rounded transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  Daily Calories
                </label>
                <input
                  type="number"
                  value={editGoals.calories}
                  onChange={(e) =>
                    setEditGoals({ ...editGoals, calories: parseInt(e.target.value) || 0 })
                  }
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white focus:outline-none focus:border-green-500"
                />
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  Protein (g)
                </label>
                <input
                  type="number"
                  value={editGoals.protein}
                  onChange={(e) =>
                    setEditGoals({ ...editGoals, protein: parseInt(e.target.value) || 0 })
                  }
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white focus:outline-none focus:border-green-500"
                />
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  Carbs (g)
                </label>
                <input
                  type="number"
                  value={editGoals.carbs}
                  onChange={(e) =>
                    setEditGoals({ ...editGoals, carbs: parseInt(e.target.value) || 0 })
                  }
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white focus:outline-none focus:border-green-500"
                />
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  Fats (g)
                </label>
                <input
                  type="number"
                  value={editGoals.fats}
                  onChange={(e) =>
                    setEditGoals({ ...editGoals, fats: parseInt(e.target.value) || 0 })
                  }
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white focus:outline-none focus:border-green-500"
                />
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setShowEditModal(false)}
                className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={saveGoals}
                className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg text-sm font-medium transition-colors"
              >
                Save Goals
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
