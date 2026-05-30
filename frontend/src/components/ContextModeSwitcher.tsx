import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../config'

interface ContextMode {
  mode: string
  name: string
  description: string
  icon: string
  color: string
}

const CONTEXT_MODES: ContextMode[] = [
  {
    mode: 'full',
    name: 'Full Context',
    description: 'Complete access to all memories, notes, documents, and data. Best for deep discussions and complex tasks.',
    icon: '🧠',
    color: 'teal'
  },
  {
    mode: 'recent',
    name: 'Recent Only',
    description: 'Access only to recent conversations and current session. Faster responses with focused context.',
    icon: '⚡',
    color: 'blue'
  },
  {
    mode: 'minimal',
    name: 'Minimal Context',
    description: 'No memory retrieval, pure conversation. Ultra-fast responses for quick questions.',
    icon: '💬',
    color: 'gray'
  },
  {
    mode: 'fitness',
    name: 'Fitness Focus',
    description: 'Prioritizes workout logs, recovery data, and nutrition information.',
    icon: '💪',
    color: 'orange'
  },
  {
    mode: 'work',
    name: 'Work Mode',
    description: 'Focuses on productivity, calendar, tasks, and professional context.',
    icon: '💼',
    color: 'indigo'
  },
  {
    mode: 'learning',
    name: 'Learning Mode',
    description: 'Emphasizes notes, documents, and knowledge-building conversations.',
    icon: '📚',
    color: 'purple'
  }
]

export default function ContextModeSwitcher() {
  const [currentMode, setCurrentMode] = useState<string>('full')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [stats, setStats] = useState<any>(null)

  useEffect(() => {
    loadCurrentMode()
    loadContextStats()
  }, [])

  const loadCurrentMode = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/context/mode`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setCurrentMode(data.mode || 'full')
      }
    } catch (error) {
      console.error('Failed to load context mode:', error)
    } finally {
      setLoading(false)
    }
  }

  const loadContextStats = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/context/stats`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setStats(data)
      }
    } catch (error) {
      console.error('Failed to load context stats:', error)
    }
  }

  const switchMode = async (mode: string) => {
    setSaving(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/context/mode`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ mode })
      })
      if (response.ok) {
        setCurrentMode(mode)
        await loadContextStats()
      }
    } catch (error) {
      console.error('Failed to switch context mode:', error)
    } finally {
      setSaving(false)
    }
  }

  const getColorClasses = (color: string, isActive: boolean) => {
    const colors = {
      teal: isActive ? 'bg-teal-600 border-teal-500' : 'border-teal-500/30 hover:border-teal-500',
      blue: isActive ? 'bg-blue-600 border-blue-500' : 'border-blue-500/30 hover:border-blue-500',
      gray: isActive ? 'bg-gray-600 border-gray-500' : 'border-gray-500/30 hover:border-gray-500',
      orange: isActive ? 'bg-orange-600 border-orange-500' : 'border-orange-500/30 hover:border-orange-500',
      indigo: isActive ? 'bg-indigo-600 border-indigo-500' : 'border-indigo-500/30 hover:border-indigo-500',
      purple: isActive ? 'bg-purple-600 border-purple-500' : 'border-purple-500/30 hover:border-purple-500'
    }
    return colors[color as keyof typeof colors] || colors.gray
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-4 border-teal-500 border-t-transparent rounded-full"></div>
      </div>
    )
  }

  const activeMode = CONTEXT_MODES.find(m => m.mode === currentMode) || CONTEXT_MODES[0]

  return (
    <div className="space-y-6">
      {/* Header with current mode */}
      <div className="bg-card border border-card rounded-md p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-white">Context Mode</h2>
            <p className="text-gray-400 mt-1">Choose how Sara accesses your data</p>
          </div>
          <div className="flex items-center space-x-3 bg-gray-800 px-4 py-3 rounded-lg border border-gray-700">
            <span className="text-3xl">{activeMode.icon}</span>
            <div>
              <div className="text-sm text-gray-400">Current Mode</div>
              <div className="text-lg font-semibold text-white">{activeMode.name}</div>
            </div>
          </div>
        </div>
      </div>

      {/* Context Stats */}
      {stats && (
        <div className="bg-card border border-card rounded-md p-6">
          <h3 className="text-lg font-semibold text-white mb-4">Available Context</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-gray-800 rounded-lg p-4 text-center">
              <div className="text-3xl font-bold text-teal-400">{stats.total_episodes || 0}</div>
              <div className="text-sm text-gray-400 mt-1">Memories</div>
            </div>
            <div className="bg-gray-800 rounded-lg p-4 text-center">
              <div className="text-3xl font-bold text-blue-400">{stats.total_notes || 0}</div>
              <div className="text-sm text-gray-400 mt-1">Notes</div>
            </div>
            <div className="bg-gray-800 rounded-lg p-4 text-center">
              <div className="text-3xl font-bold text-purple-400">{stats.total_documents || 0}</div>
              <div className="text-sm text-gray-400 mt-1">Documents</div>
            </div>
            <div className="bg-gray-800 rounded-lg p-4 text-center">
              <div className="text-3xl font-bold text-orange-400">{stats.total_events || 0}</div>
              <div className="text-sm text-gray-400 mt-1">Events</div>
            </div>
          </div>
          <div className="mt-4 p-3 bg-gray-800 rounded-lg">
            <div className="flex justify-between items-center text-sm">
              <span className="text-gray-400">Total Context Size</span>
              <span className="text-white font-semibold">{stats.total_size || 'Unknown'}</span>
            </div>
          </div>
        </div>
      )}

      {/* Mode Selection Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {CONTEXT_MODES.map((mode) => {
          const isActive = currentMode === mode.mode
          return (
            <button
              key={mode.mode}
              onClick={() => switchMode(mode.mode)}
              disabled={saving}
              className={`text-left p-6 rounded-md border-2 transition-all ${getColorClasses(mode.color, isActive)} ${
                isActive ? 'ring-2 ring-white/20' : 'bg-gray-800'
              } ${saving ? 'opacity-50 cursor-not-allowed' : 'hover:scale-105'}`}
            >
              <div className="flex items-start justify-between mb-3">
                <span className="text-4xl">{mode.icon}</span>
                {isActive && (
                  <span className="material-icons text-white">check_circle</span>
                )}
              </div>
              <h3 className="text-xl font-semibold text-white mb-2">{mode.name}</h3>
              <p className="text-sm text-gray-300">{mode.description}</p>
            </button>
          )
        })}
      </div>

      {/* Mode Details */}
      <div className="bg-card border border-card rounded-md p-6">
        <h3 className="text-lg font-semibold text-white mb-4">What's Included in {activeMode.name}?</h3>
        <div className="space-y-3">
          {currentMode === 'full' && (
            <>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-teal-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Complete Memory Search</div>
                  <div className="text-sm text-gray-400">HYDRA retrieval across all episodes and conversations</div>
                </div>
              </div>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-teal-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Notes & Documents</div>
                  <div className="text-sm text-gray-400">Full access to your knowledge base</div>
                </div>
              </div>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-teal-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Health & Fitness Data</div>
                  <div className="text-sm text-gray-400">Workouts, nutrition, recovery tracking</div>
                </div>
              </div>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-teal-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Calendar & Tasks</div>
                  <div className="text-sm text-gray-400">Complete schedule and reminder context</div>
                </div>
              </div>
            </>
          )}
          {currentMode === 'recent' && (
            <>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-blue-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Last 7 Days of Conversations</div>
                  <div className="text-sm text-gray-400">Recent context for continuity</div>
                </div>
              </div>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-blue-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Current Session Memory</div>
                  <div className="text-sm text-gray-400">Maintains conversation flow</div>
                </div>
              </div>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-gray-500 mt-0.5">cancel</span>
                <div>
                  <div className="text-gray-400 font-medium">No Deep Memory Search</div>
                  <div className="text-sm text-gray-500">Historical data not accessed</div>
                </div>
              </div>
            </>
          )}
          {currentMode === 'minimal' && (
            <>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-gray-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Current Conversation Only</div>
                  <div className="text-sm text-gray-400">No memory retrieval for fastest responses</div>
                </div>
              </div>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-gray-500 mt-0.5">cancel</span>
                <div>
                  <div className="text-gray-400 font-medium">No Historical Context</div>
                  <div className="text-sm text-gray-500">Previous conversations not accessed</div>
                </div>
              </div>
            </>
          )}
          {currentMode === 'fitness' && (
            <>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-orange-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Workout Logs & Progress</div>
                  <div className="text-sm text-gray-400">Complete training history</div>
                </div>
              </div>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-orange-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Nutrition & Recovery Data</div>
                  <div className="text-sm text-gray-400">Food logs and recovery metrics</div>
                </div>
              </div>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-orange-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Recent Fitness Conversations</div>
                  <div className="text-sm text-gray-400">Training-related discussions</div>
                </div>
              </div>
            </>
          )}
          {currentMode === 'work' && (
            <>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-indigo-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Calendar & Events</div>
                  <div className="text-sm text-gray-400">Complete schedule access</div>
                </div>
              </div>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-indigo-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Work-Related Notes</div>
                  <div className="text-sm text-gray-400">Project notes and documents</div>
                </div>
              </div>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-indigo-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Professional Conversations</div>
                  <div className="text-sm text-gray-400">Work-focused memory retrieval</div>
                </div>
              </div>
            </>
          )}
          {currentMode === 'learning' && (
            <>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-purple-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Notes & Knowledge Base</div>
                  <div className="text-sm text-gray-400">Complete note collection</div>
                </div>
              </div>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-purple-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Documents & Articles</div>
                  <div className="text-sm text-gray-400">Uploaded learning materials</div>
                </div>
              </div>
              <div className="flex items-start space-x-3">
                <span className="material-icons text-purple-400 mt-0.5">check_circle</span>
                <div>
                  <div className="text-white font-medium">Educational Conversations</div>
                  <div className="text-sm text-gray-400">Learning-related discussions</div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
