import React, { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { APP_CONFIG } from '../config'

interface IntelligenceReport {
  id: string
  user_id: string
  report_type: 'weekly' | 'monthly' | 'quarterly'
  period_start: string
  period_end: string
  report_data: any
  summary?: string
  insights: string[]
  patterns: any[]
  recommendations: string[]
  generation_time_ms?: number
  created_at: string
  delivered_at?: string
}

interface ProactiveSuggestion {
  id: string
  user_id: string
  suggestion_type: string
  title: string
  description: string
  priority: 'low' | 'medium' | 'high'
  confidence: number
  status: 'pending' | 'accepted' | 'dismissed'
  action_url?: string
  expires_at?: string
  created_at: string
}

interface DetectedPattern {
  id: string
  user_id: string
  pattern_type: string
  title: string
  description: string
  confidence: number
  occurrences: number
  pattern_data: any
  first_detected: string
  last_updated: string
}

export default function SmartInsightsDashboard() {
  const [view, setView] = useState<'reports' | 'suggestions' | 'patterns'>('reports')
  const [reports, setReports] = useState<IntelligenceReport[]>([])
  const [suggestions, setSuggestions] = useState<ProactiveSuggestion[]>([])
  const [patterns, setPatterns] = useState<DetectedPattern[]>([])
  const [selectedReport, setSelectedReport] = useState<IntelligenceReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)

  useEffect(() => {
    loadAllData()
  }, [])

  const loadAllData = async () => {
    setLoading(true)
    await Promise.all([
      loadReports(),
      loadSuggestions(),
      loadPatterns()
    ])
    setLoading(false)
  }

  const loadReports = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/reports/list`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setReports(data)
        if (data.length > 0 && !selectedReport) {
          setSelectedReport(data[0])
        }
      }
    } catch (error) {
      console.error('Failed to load reports:', error)
    }
  }

  const loadSuggestions = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/suggestions`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setSuggestions(data)
      }
    } catch (error) {
      console.error('Failed to load suggestions:', error)
    }
  }

  const loadPatterns = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/patterns`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setPatterns(data)
      }
    } catch (error) {
      console.error('Failed to load patterns:', error)
    }
  }

  const generateReport = async (type: 'weekly' | 'monthly' | 'quarterly') => {
    setGenerating(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/reports/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ report_type: type })
      })
      if (response.ok) {
        const newReport = await response.json()
        setReports(prev => [newReport, ...prev])
        setSelectedReport(newReport)
      }
    } catch (error) {
      console.error('Failed to generate report:', error)
    } finally {
      setGenerating(false)
    }
  }

  const updateSuggestionStatus = async (suggestionId: string, status: 'accepted' | 'dismissed') => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/suggestions/${suggestionId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ status })
      })
      if (response.ok) {
        setSuggestions(prev => prev.map(s =>
          s.id === suggestionId ? { ...s, status } : s
        ))
      }
    } catch (error) {
      console.error('Failed to update suggestion:', error)
    }
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    })
  }

  const getPriorityColor = (priority: string) => {
    const colors = {
      high: 'text-red-400 bg-red-900/20 border-red-500',
      medium: 'text-yellow-400 bg-yellow-900/20 border-yellow-500',
      low: 'text-blue-400 bg-blue-900/20 border-blue-500'
    }
    return colors[priority as keyof typeof colors] || colors.low
  }

  const getReportIcon = (type: string) => {
    const icons = {
      weekly: '📅',
      monthly: '📊',
      quarterly: '📈'
    }
    return icons[type as keyof typeof icons] || '📄'
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
      {/* Header with View Switcher */}
      <div className="bg-card border border-card rounded-xl p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-white">Smart Insights</h2>
            <p className="text-gray-400 mt-1">Intelligence reports, patterns, and proactive suggestions</p>
          </div>
          <div className="flex items-center space-x-2 bg-gray-800 rounded-lg p-1">
            <button
              onClick={() => setView('reports')}
              className={`px-4 py-2 rounded-md font-medium transition-colors ${
                view === 'reports'
                  ? 'bg-teal-600 text-white'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              Reports
            </button>
            <button
              onClick={() => setView('suggestions')}
              className={`px-4 py-2 rounded-md font-medium transition-colors relative ${
                view === 'suggestions'
                  ? 'bg-teal-600 text-white'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              Suggestions
              {suggestions.filter(s => s.status === 'pending').length > 0 && (
                <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">
                  {suggestions.filter(s => s.status === 'pending').length}
                </span>
              )}
            </button>
            <button
              onClick={() => setView('patterns')}
              className={`px-4 py-2 rounded-md font-medium transition-colors ${
                view === 'patterns'
                  ? 'bg-teal-600 text-white'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              Patterns
            </button>
          </div>
        </div>
      </div>

      {/* Reports View */}
      {view === 'reports' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Reports List */}
          <div className="lg:col-span-1 space-y-4">
            <div className="bg-card border border-card rounded-xl p-4">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-white">Generate Report</h3>
              </div>
              <div className="space-y-2">
                <button
                  onClick={() => generateReport('weekly')}
                  disabled={generating}
                  className="w-full bg-blue-600 hover:bg-blue-700 text-white px-4 py-3 rounded-lg disabled:opacity-50 flex items-center justify-between"
                >
                  <div className="flex items-center space-x-2">
                    <span className="text-xl">📅</span>
                    <span>Weekly Report</span>
                  </div>
                  <span className="material-icons text-sm">arrow_forward</span>
                </button>
                <button
                  onClick={() => generateReport('monthly')}
                  disabled={generating}
                  className="w-full bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-3 rounded-lg disabled:opacity-50 flex items-center justify-between"
                >
                  <div className="flex items-center space-x-2">
                    <span className="text-xl">📊</span>
                    <span>Monthly Report</span>
                  </div>
                  <span className="material-icons text-sm">arrow_forward</span>
                </button>
                <button
                  onClick={() => generateReport('quarterly')}
                  disabled={generating}
                  className="w-full bg-purple-600 hover:bg-purple-700 text-white px-4 py-3 rounded-lg disabled:opacity-50 flex items-center justify-between"
                >
                  <div className="flex items-center space-x-2">
                    <span className="text-xl">📈</span>
                    <span>Quarterly Report</span>
                  </div>
                  <span className="material-icons text-sm">arrow_forward</span>
                </button>
              </div>
            </div>

            <div className="bg-card border border-card rounded-xl p-4">
              <h3 className="text-lg font-semibold text-white mb-4">Recent Reports</h3>
              {reports.length === 0 ? (
                <p className="text-gray-400 text-center py-8 text-sm">No reports yet</p>
              ) : (
                <div className="space-y-2">
                  {reports.map((report) => (
                    <button
                      key={report.id}
                      onClick={() => setSelectedReport(report)}
                      className={`w-full text-left p-3 rounded-lg transition-colors ${
                        selectedReport?.id === report.id
                          ? 'bg-teal-600/20 border border-teal-500'
                          : 'bg-gray-800 hover:bg-gray-700 border border-gray-700'
                      }`}
                    >
                      <div className="flex items-center space-x-2 mb-1">
                        <span className="text-xl">{getReportIcon(report.report_type)}</span>
                        <span className="text-sm text-white font-medium capitalize">
                          {report.report_type}
                        </span>
                      </div>
                      <div className="text-xs text-gray-400">
                        {formatDate(report.period_start)} - {formatDate(report.period_end)}
                      </div>
                      {report.generation_time_ms && (
                        <div className="text-xs text-gray-500 mt-1">
                          Generated in {(report.generation_time_ms / 1000).toFixed(1)}s
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Report Content */}
          <div className="lg:col-span-2 bg-card border border-card rounded-xl p-6">
            {selectedReport ? (
              <div>
                <div className="flex items-center justify-between mb-6 pb-4 border-b border-gray-700">
                  <div>
                    <h3 className="text-2xl font-bold text-white capitalize flex items-center space-x-2">
                      <span className="text-3xl">{getReportIcon(selectedReport.report_type)}</span>
                      <span>{selectedReport.report_type} Report</span>
                    </h3>
                    <p className="text-gray-400 mt-1">
                      {formatDate(selectedReport.period_start)} - {formatDate(selectedReport.period_end)}
                    </p>
                  </div>
                </div>

                {/* Summary */}
                {selectedReport.summary && (
                  <div className="mb-6 p-4 bg-teal-900/20 border border-teal-500 rounded-lg">
                    <h4 className="text-lg font-semibold text-teal-300 mb-2">Summary</h4>
                    <p className="text-gray-300">{selectedReport.summary}</p>
                  </div>
                )}

                {/* Insights */}
                {selectedReport.insights.length > 0 && (
                  <div className="mb-6">
                    <h4 className="text-lg font-semibold text-white mb-3">Key Insights</h4>
                    <div className="space-y-2">
                      {selectedReport.insights.map((insight, idx) => (
                        <div key={idx} className="flex items-start space-x-3 p-3 bg-gray-800 rounded-lg">
                          <span className="material-icons text-blue-400 text-sm mt-0.5">lightbulb</span>
                          <p className="text-gray-300 text-sm">{insight}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Patterns */}
                {selectedReport.patterns.length > 0 && (
                  <div className="mb-6">
                    <h4 className="text-lg font-semibold text-white mb-3">Patterns Detected</h4>
                    <div className="space-y-2">
                      {selectedReport.patterns.map((pattern, idx) => (
                        <div key={idx} className="p-3 bg-gray-800 rounded-lg">
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-white font-medium text-sm">{pattern.title || pattern.pattern_type}</span>
                            <span className="text-xs text-gray-400">
                              {pattern.confidence ? `${(pattern.confidence * 100).toFixed(0)}% confidence` : ''}
                            </span>
                          </div>
                          <p className="text-gray-400 text-sm">{pattern.description}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Recommendations */}
                {selectedReport.recommendations.length > 0 && (
                  <div className="mb-6">
                    <h4 className="text-lg font-semibold text-white mb-3">Recommendations</h4>
                    <div className="space-y-2">
                      {selectedReport.recommendations.map((rec, idx) => (
                        <div key={idx} className="flex items-start space-x-3 p-3 bg-green-900/20 border border-green-500 rounded-lg">
                          <span className="material-icons text-green-400 text-sm mt-0.5">check_circle</span>
                          <p className="text-gray-300 text-sm">{rec}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Report Data Stats */}
                {selectedReport.report_data && (
                  <div className="mt-6 p-4 bg-gray-800 rounded-lg">
                    <h4 className="text-md font-semibold text-white mb-3">Period Statistics</h4>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      {Object.entries(selectedReport.report_data).slice(0, 8).map(([key, value]) => (
                        <div key={key}>
                          <div className="text-xs text-gray-400 capitalize">{key.replace(/_/g, ' ')}</div>
                          <div className="text-lg font-semibold text-white">
                            {typeof value === 'number' ? value.toLocaleString() : String(value)}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-64 text-gray-400">
                <span className="material-icons text-6xl mb-4">assessment</span>
                <p>Generate or select a report to view</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Suggestions View */}
      {view === 'suggestions' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {suggestions.length === 0 ? (
            <div className="col-span-full bg-card border border-card rounded-xl p-12 text-center">
              <span className="material-icons text-6xl text-gray-600 mb-4">auto_awesome</span>
              <p className="text-gray-400">No suggestions at this time</p>
              <p className="text-sm text-gray-500 mt-2">Sara will proactively suggest actions based on your patterns</p>
            </div>
          ) : (
            suggestions.map((suggestion) => (
              <div
                key={suggestion.id}
                className={`bg-card border-2 rounded-xl p-6 ${
                  suggestion.status === 'pending' ? 'border-teal-500' : 'border-gray-700 opacity-60'
                }`}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className={`px-3 py-1 rounded-full text-xs font-medium border ${getPriorityColor(suggestion.priority)}`}>
                    {suggestion.priority.toUpperCase()}
                  </div>
                  <div className="text-xs text-gray-400">{formatDate(suggestion.created_at)}</div>
                </div>
                <h3 className="text-lg font-semibold text-white mb-2">{suggestion.title}</h3>
                <p className="text-sm text-gray-300 mb-4">{suggestion.description}</p>
                <div className="flex items-center justify-between">
                  <div className="text-xs text-gray-400">
                    {(suggestion.confidence * 100).toFixed(0)}% confident
                  </div>
                  {suggestion.status === 'pending' && (
                    <div className="flex space-x-2">
                      <button
                        onClick={() => updateSuggestionStatus(suggestion.id, 'accepted')}
                        className="bg-green-600 hover:bg-green-700 text-white px-3 py-1 rounded text-xs"
                      >
                        Accept
                      </button>
                      <button
                        onClick={() => updateSuggestionStatus(suggestion.id, 'dismissed')}
                        className="bg-gray-600 hover:bg-gray-700 text-white px-3 py-1 rounded text-xs"
                      >
                        Dismiss
                      </button>
                    </div>
                  )}
                  {suggestion.status !== 'pending' && (
                    <div className="text-xs text-gray-500 capitalize">{suggestion.status}</div>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Patterns View */}
      {view === 'patterns' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {patterns.length === 0 ? (
            <div className="col-span-full bg-card border border-card rounded-xl p-12 text-center">
              <span className="material-icons text-6xl text-gray-600 mb-4">pattern</span>
              <p className="text-gray-400">No patterns detected yet</p>
              <p className="text-sm text-gray-500 mt-2">Sara will identify behavioral patterns over time</p>
            </div>
          ) : (
            patterns.map((pattern) => (
              <div key={pattern.id} className="bg-card border border-card rounded-xl p-6">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center space-x-2">
                    <span className="material-icons text-purple-400">pattern</span>
                    <span className="text-xs text-gray-400 capitalize">{pattern.pattern_type}</span>
                  </div>
                  <div className="text-xs text-gray-400">{pattern.occurrences} occurrences</div>
                </div>
                <h3 className="text-lg font-semibold text-white mb-2">{pattern.title}</h3>
                <p className="text-sm text-gray-300 mb-4">{pattern.description}</p>
                <div className="flex items-center justify-between pt-3 border-t border-gray-700">
                  <div className="text-xs text-gray-400">
                    {(pattern.confidence * 100).toFixed(0)}% confidence
                  </div>
                  <div className="text-xs text-gray-400">
                    Last seen: {formatDate(pattern.last_updated)}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
