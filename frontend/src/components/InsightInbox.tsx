import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../config'

interface AutonomousInsight {
  id: string
  insight_type: string
  personality_mode: string
  sweep_type: string
  priority_score: number
  title: string
  message: string
  action_suggestion?: { primary?: string; secondary?: string }
  related_data?: any
  surfaced_at?: string
  user_action?: string
  feedback_score?: number
  generated_at: string
  expires_at?: string
}

interface InsightInboxProps {
  onToast?: (message: string, type?: string, isPersistent?: boolean, showSprite?: boolean) => void
  onNavigate?: (view: string) => void
}

export default function InsightInbox({ onToast, onNavigate }: InsightInboxProps) {
  const [insights, setInsights] = useState<AutonomousInsight[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<string>('all')

  const fetchInsights = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/autonomous/insights?limit=50`, {
        credentials: 'include'
      })
      
      if (response.ok) {
        const data = await response.json()
        setInsights(data)
      } else {
        onToast?.('Failed to load insights', 'error')
      }
    } catch (error) {
      console.error('Error fetching insights:', error)
      onToast?.('Failed to load insights', 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchInsights()
  }, [])

  const handleFeedback = async (insightId: string, score: number, action: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/autonomous/insights/${insightId}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          feedback_score: score,
          user_action: action
        })
      })
      
      if (response.ok) {
        // Update local state
        setInsights(prev => prev.map(insight => 
          insight.id === insightId 
            ? { ...insight, feedback_score: score, user_action: action, surfaced_at: new Date().toISOString() }
            : insight
        ))
        
        if (score > 0) {
          onToast?.('Thanks for the feedback!', 'success')
        }
      }
    } catch (error) {
      console.error('Error submitting feedback:', error)
      onToast?.('Failed to submit feedback', 'error')
    }
  }

  const getInsightIcon = (type: string) => {
    const icons: Record<string, string> = {
      'habit_salvage': '💪',
      'content_pattern': '🔍',
      'knowledge_connection': '🔗',
      'security_alert': '🛡️',
      'calendar_prep': '📅',
      'weekly_summary': '📊',
      'habit_performance': '📈',
      'emotional_check': '💝',
      'big_suggestion': '💡',
      'long_term_trend': '📈'
    }
    return icons[type] || '🤖'
  }

  const getModeColor = (mode: string) => {
    const colors: Record<string, string> = {
      'coach': 'text-blue-400 bg-blue-500/10',
      'analyst': 'text-purple-400 bg-purple-500/10', 
      'companion': 'text-pink-400 bg-pink-500/10',
      'guardian': 'text-blue-600 bg-blue-600/10',
      'concierge': 'text-teal-400 bg-teal-500/10',
      'librarian': 'text-green-400 bg-green-500/10'
    }
    return colors[mode] || 'text-gray-400 bg-gray-500/10'
  }

  const getSweepTypeLabel = (sweepType: string) => {
    const labels: Record<string, string> = {
      'quick_sweep': 'Quick Check',
      'standard_sweep': 'Analysis', 
      'digest_sweep': 'Deep Dive'
    }
    return labels[sweepType] || sweepType
  }

  const filteredInsights = insights.filter(insight => {
    if (filter === 'unread') return !insight.surfaced_at
    if (filter === 'acted_on') return insight.user_action === 'acted_on'
    return true
  })

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-400">Loading insights...</div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header - Fixed */}
      <div className="flex-shrink-0 mb-6">
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-2xl font-bold text-white">Sara's Insights</h1>
            <p className="text-gray-400">Autonomous findings from your personal AI assistant</p>
          </div>
          
          <div className="flex gap-2">
            {['all', 'unread', 'acted_on'].map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1 rounded-lg text-sm capitalize ${
                  filter === f 
                    ? 'bg-teal-500/20 text-teal-400' 
                    : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                }`}
              >
                {f.replace('_', ' ')}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Content - Scrollable */}
      <div className="flex-1 overflow-y-auto">
        {filteredInsights.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <div className="text-6xl mb-4">🤖</div>
              <h3 className="text-xl font-semibold text-white mb-2">No insights yet</h3>
              <p className="text-gray-400 mb-6">Sara is learning your patterns. Check back soon!</p>
              <p className="text-sm text-gray-500">
                Tip: Go to Settings → Autonomous Sweep Testing to generate some test insights
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-4 pb-4">
            {filteredInsights.map(insight => (
            <div key={insight.id} className="bg-card border border-card rounded-xl p-6 hover:bg-gray-800/50 transition-colors">
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{getInsightIcon(insight.insight_type)}</span>
                  <div>
                    <h3 className="font-semibold text-white">{insight.title}</h3>
                    <div className="flex items-center gap-2 mt-1">
                      <span className={`text-xs px-2 py-1 rounded-full ${getModeColor(insight.personality_mode)}`}>
                        {insight.personality_mode}
                      </span>
                      <span className="text-xs text-gray-500">{getSweepTypeLabel(insight.sweep_type)}</span>
                      <span className="text-xs text-gray-500">
                        {new Date(insight.generated_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                </div>
                
                <div className="flex items-center gap-2">
                  {insight.priority_score > 0.7 && (
                    <span className="text-yellow-400 text-sm">⭐</span>
                  )}
                  {!insight.surfaced_at && (
                    <span className="w-2 h-2 bg-blue-500 rounded-full"></span>
                  )}
                </div>
              </div>
              
              <p className="text-gray-300 mb-4">{insight.message}</p>
              
              {/* Memory Context Display */}
              {insight.related_data && (() => {
                try {
                  const data = typeof insight.related_data === 'string' 
                    ? JSON.parse(insight.related_data) 
                    : insight.related_data;
                  
                  if (data.memory_context?.related_memories?.length > 0) {
                    return (
                      <div className="mb-4 p-3 bg-gray-800/50 rounded-lg border border-gray-700">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="text-sm font-medium text-purple-400">🧠 Memory Context</span>
                        </div>
                        <p className="text-xs text-gray-400 mb-2">
                          {data.memory_context.context_summary}
                        </p>
                        <div className="max-h-24 overflow-y-auto space-y-1">
                          {data.memory_context.related_memories.slice(0, 3).map((memory, idx) => (
                            <div key={idx} className="text-xs text-gray-500 bg-gray-900/50 rounded px-2 py-1">
                              {memory.content?.substring(0, 120)}
                              {memory.content?.length > 120 ? '...' : ''}
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  }
                } catch (e) {
                  return null;
                }
                return null;
              })()}
              
              {insight.user_action !== 'acted_on' && (
                <div className="flex gap-2">
                  <button
                    onClick={() => handleFeedback(insight.id, 1, 'acted_on')}
                    className="px-4 py-2 bg-teal-600/20 text-teal-400 rounded-lg hover:bg-teal-600/30 text-sm"
                  >
                    ✓ Helpful
                  </button>
                  
                  <button
                    onClick={() => handleFeedback(insight.id, -1, 'dismissed')}
                    className="px-4 py-2 bg-gray-600/20 text-gray-400 rounded-lg hover:bg-gray-600/30 text-sm"
                  >
                    ✗ Not useful
                  </button>
                  
                  {insight.insight_type === 'habit_salvage' && (
                    <button
                      onClick={() => onNavigate?.('habits')}
                      className="px-4 py-2 bg-blue-600/20 text-blue-400 rounded-lg hover:bg-blue-600/30 text-sm"
                    >
                      View Habits
                    </button>
                  )}
                  
                  {insight.insight_type === 'knowledge_connection' && (
                    <button
                      onClick={() => onNavigate?.('notes')}
                      className="px-4 py-2 bg-purple-600/20 text-purple-400 rounded-lg hover:bg-purple-600/30 text-sm"
                    >
                      View Notes
                    </button>
                  )}
                  
                  {insight.insight_type === 'security_alert' && (
                    <button
                      onClick={() => onNavigate?.('vulnerability-watch')}
                      className="px-4 py-2 bg-red-600/20 text-red-400 rounded-lg hover:bg-red-600/30 text-sm"
                    >
                      View Security
                    </button>
                  )}
                </div>
              )}
              
              {insight.feedback_score !== undefined && (
                <div className="mt-3 text-sm text-gray-500">
                  {insight.feedback_score > 0 ? '✓ Marked as helpful' : '✗ Marked as not useful'}
                </div>
              )}
            </div>
          ))}
          </div>
        )}
      </div>
    </div>
  )
}