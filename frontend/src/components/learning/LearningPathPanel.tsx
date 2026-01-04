import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../../config'

interface PathStep {
  topic_id: string
  topic_title: string
  priority_score: number
  current_mastery: number
  actions: Array<{
    type: string
    description: string
    suggestion?: string
    focus?: string
  }>
  estimated_time: string
  reason: string
}

interface Recommendation {
  type: string
  message: string
  priority: string
  affected_topics?: string[]
}

interface LearningPathData {
  path: PathStep[]
  summary: string
  recommendations: Recommendation[]
  stats: {
    total_topics: number
    avg_mastery: number
    topics_needing_review: number
    topics_with_gaps: number
  }
}

interface LearningPathPanelProps {
  onSelectTopic: (topicId: string) => void
  isVisible: boolean
  onClose: () => void
}

export default function LearningPathPanel({ onSelectTopic, isVisible, onClose }: LearningPathPanelProps) {
  const [pathData, setPathData] = useState<LearningPathData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (isVisible) {
      loadLearningPath()
    }
  }, [isVisible])

  const loadLearningPath = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/path?max_steps=5`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setPathData(data)
      } else {
        setError('Failed to load learning path')
      }
    } catch (err) {
      setError('Could not connect to server')
    } finally {
      setLoading(false)
    }
  }

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'high': return 'text-red-400 bg-red-500/10'
      case 'medium': return 'text-yellow-400 bg-yellow-500/10'
      case 'low': return 'text-green-400 bg-green-500/10'
      default: return 'text-gray-400 bg-gray-500/10'
    }
  }

  const getActionIcon = (type: string) => {
    switch (type) {
      case 'add_sources': return 'search'
      case 'fetch_sources': return 'download'
      case 'study': return 'menu_book'
      case 'practice': return 'edit_note'
      case 'review': return 'refresh'
      case 'quick_review': return 'timer'
      case 'connect': return 'hub'
      case 'teach': return 'school'
      case 'take_notes': return 'note_add'
      default: return 'play_arrow'
    }
  }

  const getMasteryColor = (mastery: number) => {
    if (mastery >= 0.85) return 'text-green-400'
    if (mastery >= 0.6) return 'text-teal-400'
    if (mastery >= 0.3) return 'text-yellow-400'
    return 'text-orange-400'
  }

  if (!isVisible) return null

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 rounded-xl border border-gray-700 w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-700 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="material-icons text-teal-400 text-2xl">route</span>
            <div>
              <h2 className="text-lg font-semibold text-white">Your Learning Path</h2>
              <p className="text-sm text-gray-400">Personalized study recommendations</p>
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <span className="material-icons">close</span>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-2 border-teal-500 border-t-transparent"></div>
            </div>
          ) : error ? (
            <div className="text-center py-12 text-gray-400">
              <span className="material-icons text-4xl mb-2">error_outline</span>
              <p>{error}</p>
              <button onClick={loadLearningPath} className="mt-4 text-teal-400 hover:text-teal-300">
                Try again
              </button>
            </div>
          ) : pathData ? (
            <div className="space-y-6">
              {/* Summary */}
              <div className="bg-gray-800/50 rounded-lg p-4">
                <p className="text-gray-300">{pathData.summary}</p>
                {pathData.stats && (
                  <div className="flex flex-wrap gap-4 mt-3 text-sm">
                    <span className="text-gray-500">
                      <span className="text-white font-medium">{pathData.stats.total_topics}</span> topics
                    </span>
                    <span className="text-gray-500">
                      <span className={getMasteryColor(pathData.stats.avg_mastery)}>
                        {Math.round(pathData.stats.avg_mastery * 100)}%
                      </span> avg mastery
                    </span>
                    {pathData.stats.topics_needing_review > 0 && (
                      <span className="text-yellow-400">
                        {pathData.stats.topics_needing_review} need review
                      </span>
                    )}
                    {pathData.stats.topics_with_gaps > 0 && (
                      <span className="text-orange-400">
                        {pathData.stats.topics_with_gaps} with gaps
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Path Steps */}
              {pathData.path.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">
                    Recommended Path
                  </h3>
                  <div className="space-y-3">
                    {pathData.path.map((step, index) => (
                      <div
                        key={step.topic_id}
                        className="bg-gray-800 rounded-lg p-4 border border-gray-700 hover:border-teal-500/50 transition-colors cursor-pointer"
                        onClick={() => {
                          onSelectTopic(step.topic_id)
                          onClose()
                        }}
                      >
                        <div className="flex items-start gap-3">
                          <div className="w-8 h-8 rounded-full bg-teal-500/20 flex items-center justify-center text-teal-400 font-medium flex-shrink-0">
                            {index + 1}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <h4 className="font-medium text-white truncate">{step.topic_title}</h4>
                              <span className={`text-xs ${getMasteryColor(step.current_mastery)}`}>
                                {Math.round(step.current_mastery * 100)}%
                              </span>
                            </div>
                            <p className="text-sm text-gray-400 mb-2">{step.reason}</p>
                            <div className="flex flex-wrap gap-2">
                              {step.actions.map((action, actionIndex) => (
                                <span
                                  key={actionIndex}
                                  className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-gray-700 text-gray-300"
                                >
                                  <span className="material-icons text-xs">{getActionIcon(action.type)}</span>
                                  {action.description.slice(0, 40)}{action.description.length > 40 ? '...' : ''}
                                </span>
                              ))}
                            </div>
                            <div className="mt-2 text-xs text-gray-500">
                              <span className="material-icons text-xs align-middle mr-1">schedule</span>
                              {step.estimated_time}
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Recommendations */}
              {pathData.recommendations.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3">
                    Recommendations
                  </h3>
                  <div className="space-y-2">
                    {pathData.recommendations.map((rec, index) => (
                      <div
                        key={index}
                        className={`rounded-lg p-3 ${getPriorityColor(rec.priority)}`}
                      >
                        <p className="text-sm">{rec.message}</p>
                        {rec.affected_topics && rec.affected_topics.length > 0 && (
                          <div className="mt-1 text-xs opacity-75">
                            Topics: {rec.affected_topics.join(', ')}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Empty state */}
              {pathData.path.length === 0 && pathData.recommendations.length === 0 && (
                <div className="text-center py-8 text-gray-400">
                  <span className="material-icons text-4xl mb-2">emoji_events</span>
                  <p>You're all caught up! Create new topics to expand your learning.</p>
                </div>
              )}
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-700 bg-gray-800/50 flex justify-between items-center">
          <button
            onClick={loadLearningPath}
            disabled={loading}
            className="text-sm text-gray-400 hover:text-white flex items-center gap-1"
          >
            <span className="material-icons text-sm">refresh</span>
            Refresh
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white text-sm rounded-lg transition-colors"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  )
}
