import React, { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { APP_CONFIG } from '../config'

interface DailyBriefing {
  id: string
  user_id: string
  briefing_type: 'morning' | 'evening'
  briefing_date: string
  content: string
  delivered: boolean
  delivered_at?: string
  read: boolean
  read_at?: string
  created_at: string
}

interface BriefingSettings {
  id: string
  user_id: string
  morning_enabled: boolean
  morning_time: string
  evening_enabled: boolean
  evening_time: string
  include_recovery: boolean
  include_schedule: boolean
  include_goals: boolean
  include_suggestions: boolean
  include_workout_rec: boolean
  include_accomplishments: boolean
  include_insights: boolean
  include_reflection: boolean
}

export default function DailyBriefings() {
  const [briefings, setBriefings] = useState<DailyBriefing[]>([])
  const [settings, setSettings] = useState<BriefingSettings | null>(null)
  const [selectedBriefing, setSelectedBriefing] = useState<DailyBriefing | null>(null)
  const [loading, setLoading] = useState(true)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [generating, setGenerating] = useState(false)

  useEffect(() => {
    loadBriefings()
    loadSettings()
  }, [])

  const loadBriefings = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/briefings`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setBriefings(data)
        // Auto-select today's morning briefing if available
        const today = new Date().toISOString().split('T')[0]
        const todayMorning = data.find((b: DailyBriefing) =>
          b.briefing_date === today && b.briefing_type === 'morning'
        )
        if (todayMorning && !selectedBriefing) {
          setSelectedBriefing(todayMorning)
          markAsRead(todayMorning.id)
        }
      }
    } catch (error) {
      console.error('Failed to load briefings:', error)
    } finally {
      setLoading(false)
    }
  }

  const loadSettings = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/briefings/settings`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setSettings(data)
      }
    } catch (error) {
      console.error('Failed to load settings:', error)
    }
  }

  const markAsRead = async (briefingId: string) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/briefings/${briefingId}/read`, {
        method: 'PATCH',
        credentials: 'include'
      })
      setBriefings(prev => prev.map(b =>
        b.id === briefingId ? { ...b, read: true, read_at: new Date().toISOString() } : b
      ))
    } catch (error) {
      console.error('Failed to mark as read:', error)
    }
  }

  const generateBriefing = async (type: 'morning' | 'evening') => {
    setGenerating(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/briefings/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ briefing_type: type })
      })
      if (response.ok) {
        const newBriefing = await response.json()
        setBriefings(prev => [newBriefing, ...prev])
        setSelectedBriefing(newBriefing)
      }
    } catch (error) {
      console.error('Failed to generate briefing:', error)
    } finally {
      setGenerating(false)
    }
  }

  const updateSettings = async (newSettings: Partial<BriefingSettings>) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/briefings/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(newSettings)
      })
      if (response.ok) {
        const updated = await response.json()
        setSettings(updated)
      }
    } catch (error) {
      console.error('Failed to update settings:', error)
    }
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleDateString('en-US', {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    })
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-4 border-teal-500 border-t-transparent rounded-full"></div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-card border border-card rounded-md p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold text-white">Daily Briefings</h2>
            <p className="text-gray-400 mt-1">Personalized morning and evening summaries</p>
          </div>
          <div className="flex space-x-2">
            <button
              onClick={() => generateBriefing('morning')}
              disabled={generating}
              className="bg-yellow-600 hover:bg-yellow-700 text-white px-4 py-2 rounded-lg disabled:opacity-50 flex items-center space-x-2"
            >
              <span className="text-xl">🌅</span>
              <span>Generate Morning</span>
            </button>
            <button
              onClick={() => generateBriefing('evening')}
              disabled={generating}
              className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg disabled:opacity-50 flex items-center space-x-2"
            >
              <span className="text-xl">🌙</span>
              <span>Generate Evening</span>
            </button>
            <button
              onClick={() => setSettingsOpen(!settingsOpen)}
              className="bg-gray-700 hover:bg-gray-600 text-white px-4 py-2 rounded-lg flex items-center space-x-2"
            >
              <span className="material-icons text-sm">settings</span>
              <span>Settings</span>
            </button>
          </div>
        </div>

        {/* Settings Panel */}
        {settingsOpen && settings && (
          <div className="bg-gray-800 rounded-lg p-4 mt-4 border border-gray-700">
            <h3 className="text-lg font-semibold text-white mb-4">Briefing Settings</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Morning Settings */}
              <div className="space-y-3">
                <h4 className="text-md font-medium text-teal-400">Morning Briefing</h4>
                <label className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    checked={settings.morning_enabled}
                    onChange={(e) => updateSettings({ morning_enabled: e.target.checked })}
                    className="w-4 h-4 text-teal-600 rounded"
                  />
                  <span className="text-gray-300">Enable morning briefings</span>
                </label>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Morning Time</label>
                  <input
                    type="time"
                    value={settings.morning_time}
                    onChange={(e) => updateSettings({ morning_time: e.target.value })}
                    className="bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white"
                  />
                </div>
                <div className="space-y-2 pt-2">
                  <label className="flex items-center space-x-2">
                    <input
                      type="checkbox"
                      checked={settings.include_recovery}
                      onChange={(e) => updateSettings({ include_recovery: e.target.checked })}
                      className="w-4 h-4 text-teal-600 rounded"
                    />
                    <span className="text-sm text-gray-300">Recovery status</span>
                  </label>
                  <label className="flex items-center space-x-2">
                    <input
                      type="checkbox"
                      checked={settings.include_schedule}
                      onChange={(e) => updateSettings({ include_schedule: e.target.checked })}
                      className="w-4 h-4 text-teal-600 rounded"
                    />
                    <span className="text-sm text-gray-300">Today's schedule</span>
                  </label>
                  <label className="flex items-center space-x-2">
                    <input
                      type="checkbox"
                      checked={settings.include_goals}
                      onChange={(e) => updateSettings({ include_goals: e.target.checked })}
                      className="w-4 h-4 text-teal-600 rounded"
                    />
                    <span className="text-sm text-gray-300">Active goals</span>
                  </label>
                  <label className="flex items-center space-x-2">
                    <input
                      type="checkbox"
                      checked={settings.include_suggestions}
                      onChange={(e) => updateSettings({ include_suggestions: e.target.checked })}
                      className="w-4 h-4 text-teal-600 rounded"
                    />
                    <span className="text-sm text-gray-300">Smart suggestions</span>
                  </label>
                  <label className="flex items-center space-x-2">
                    <input
                      type="checkbox"
                      checked={settings.include_workout_rec}
                      onChange={(e) => updateSettings({ include_workout_rec: e.target.checked })}
                      className="w-4 h-4 text-teal-600 rounded"
                    />
                    <span className="text-sm text-gray-300">Workout recommendation</span>
                  </label>
                </div>
              </div>

              {/* Evening Settings */}
              <div className="space-y-3">
                <h4 className="text-md font-medium text-indigo-400">Evening Briefing</h4>
                <label className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    checked={settings.evening_enabled}
                    onChange={(e) => updateSettings({ evening_enabled: e.target.checked })}
                    className="w-4 h-4 text-indigo-600 rounded"
                  />
                  <span className="text-gray-300">Enable evening briefings</span>
                </label>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Evening Time</label>
                  <input
                    type="time"
                    value={settings.evening_time}
                    onChange={(e) => updateSettings({ evening_time: e.target.value })}
                    className="bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white"
                  />
                </div>
                <div className="space-y-2 pt-2">
                  <label className="flex items-center space-x-2">
                    <input
                      type="checkbox"
                      checked={settings.include_accomplishments}
                      onChange={(e) => updateSettings({ include_accomplishments: e.target.checked })}
                      className="w-4 h-4 text-indigo-600 rounded"
                    />
                    <span className="text-sm text-gray-300">Today's accomplishments</span>
                  </label>
                  <label className="flex items-center space-x-2">
                    <input
                      type="checkbox"
                      checked={settings.include_insights}
                      onChange={(e) => updateSettings({ include_insights: e.target.checked })}
                      className="w-4 h-4 text-indigo-600 rounded"
                    />
                    <span className="text-sm text-gray-300">Daily insights</span>
                  </label>
                  <label className="flex items-center space-x-2">
                    <input
                      type="checkbox"
                      checked={settings.include_reflection}
                      onChange={(e) => updateSettings({ include_reflection: e.target.checked })}
                      className="w-4 h-4 text-indigo-600 rounded"
                    />
                    <span className="text-sm text-gray-300">Reflection prompt</span>
                  </label>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Briefings List */}
        <div className="lg:col-span-1 bg-card border border-card rounded-md p-4">
          <h3 className="text-lg font-semibold text-white mb-4">Recent Briefings</h3>
          {briefings.length === 0 ? (
            <p className="text-gray-400 text-center py-8">No briefings yet</p>
          ) : (
            <div className="space-y-2">
              {briefings.map((briefing) => (
                <button
                  key={briefing.id}
                  onClick={() => {
                    setSelectedBriefing(briefing)
                    if (!briefing.read) markAsRead(briefing.id)
                  }}
                  className={`w-full text-left p-3 rounded-lg transition-colors ${
                    selectedBriefing?.id === briefing.id
                      ? 'bg-teal-600/20 border border-teal-500'
                      : 'bg-gray-800 hover:bg-gray-700 border border-gray-700'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xl">
                      {briefing.briefing_type === 'morning' ? '🌅' : '🌙'}
                    </span>
                    {!briefing.read && (
                      <span className="w-2 h-2 bg-teal-500 rounded-full"></span>
                    )}
                  </div>
                  <div className="text-sm text-white font-medium capitalize">
                    {briefing.briefing_type} Briefing
                  </div>
                  <div className="text-xs text-gray-400 mt-1">
                    {formatDate(briefing.briefing_date)}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Briefing Content */}
        <div className="lg:col-span-2 bg-card border border-card rounded-md p-6">
          {selectedBriefing ? (
            <div>
              <div className="flex items-center justify-between mb-6 pb-4 border-b border-gray-700">
                <div>
                  <h3 className="text-2xl font-bold text-white capitalize flex items-center space-x-2">
                    <span className="text-3xl">
                      {selectedBriefing.briefing_type === 'morning' ? '🌅' : '🌙'}
                    </span>
                    <span>{selectedBriefing.briefing_type} Briefing</span>
                  </h3>
                  <p className="text-gray-400 mt-1">{formatDate(selectedBriefing.briefing_date)}</p>
                </div>
                {selectedBriefing.delivered && (
                  <div className="text-sm text-gray-400">
                    Delivered: {new Date(selectedBriefing.delivered_at!).toLocaleTimeString()}
                  </div>
                )}
              </div>
              <div className="prose prose-invert max-w-none">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    h1: ({ children }) => <h1 className="text-3xl font-bold text-white mb-4">{children}</h1>,
                    h2: ({ children }) => <h2 className="text-2xl font-semibold text-white mt-6 mb-3">{children}</h2>,
                    h3: ({ children }) => <h3 className="text-xl font-semibold text-white mt-4 mb-2">{children}</h3>,
                    p: ({ children }) => <p className="text-gray-300 mb-3 leading-relaxed">{children}</p>,
                    ul: ({ children }) => <ul className="list-disc list-inside text-gray-300 space-y-1 mb-4">{children}</ul>,
                    ol: ({ children }) => <ol className="list-decimal list-inside text-gray-300 space-y-1 mb-4">{children}</ol>,
                    li: ({ children }) => <li className="text-gray-300">{children}</li>,
                    strong: ({ children }) => <strong className="text-white font-semibold">{children}</strong>,
                    code: ({ children }) => <code className="bg-gray-700 px-1 py-0.5 rounded text-teal-300 text-sm">{children}</code>,
                    blockquote: ({ children }) => (
                      <blockquote className="border-l-4 border-teal-500 pl-4 italic text-gray-400 my-4">
                        {children}
                      </blockquote>
                    ),
                  }}
                >
                  {selectedBriefing.content}
                </ReactMarkdown>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-64 text-gray-400">
              <span className="material-icons text-6xl mb-4">event_note</span>
              <p>Select a briefing to view</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
