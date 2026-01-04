import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../../config'

interface Pattern {
  id: string
  title: string
  description: string | null
  narrative: string | null
  category: string
  metric_a: string
  metric_b: string
  correlation: number
  confidence: number
  sample_size: number
  p_value: number | null
  status: string
  lag_hours: number | null
  validations: number
  invalidations: number
  first_detected: string | null
  last_validated: string | null
  surfaced_count: number
}

export default function PatternList() {
  const [patterns, setPatterns] = useState<Pattern[]>([])
  const [loading, setLoading] = useState(true)
  const [includeEmerging, setIncludeEmerging] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => {
    loadPatterns()
  }, [includeEmerging])

  const loadPatterns = async () => {
    setLoading(true)
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/patterns?include_emerging=${includeEmerging}`,
        { credentials: 'include' }
      )
      if (response.ok) {
        const data = await response.json()
        setPatterns(data)
      }
    } catch (error) {
      console.error('Failed to load patterns:', error)
    } finally {
      setLoading(false)
    }
  }

  const getCorrelationColor = (r: number) => {
    const abs = Math.abs(r)
    if (abs >= 0.7) return r > 0 ? 'text-green-400' : 'text-red-400'
    if (abs >= 0.4) return r > 0 ? 'text-green-300' : 'text-red-300'
    return 'text-gray-400'
  }

  const getConfidenceWidth = (confidence: number) => {
    return `${Math.round(confidence * 100)}%`
  }

  const getStatusBadge = (status: string) => {
    const styles: Record<string, string> = {
      confirmed: 'bg-green-900/50 text-green-300 border-green-700',
      emerging: 'bg-yellow-900/50 text-yellow-300 border-yellow-700',
      stale: 'bg-gray-900/50 text-gray-400 border-gray-600',
      invalidated: 'bg-red-900/50 text-red-300 border-red-700'
    }
    return styles[status] || styles.emerging
  }

  const formatMetric = (metric: string) => {
    const [domain, field] = metric.split('.')
    return (
      <span>
        <span className="text-gray-500">{domain}.</span>
        <span className="text-white">{field?.replace(/_/g, ' ')}</span>
      </span>
    )
  }

  const submitFeedback = async (patternId: string, feedback: string) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/patterns/${patternId}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ feedback })
      })
      loadPatterns()
    } catch (error) {
      console.error('Failed to submit feedback:', error)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-teal-400"></div>
      </div>
    )
  }

  return (
    <div>
      {/* Filter Toggle */}
      <div className="flex items-center justify-between mb-4">
        <div className="text-sm text-gray-400">
          {patterns.length} pattern{patterns.length !== 1 ? 's' : ''} found
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
          <input
            type="checkbox"
            checked={includeEmerging}
            onChange={(e) => setIncludeEmerging(e.target.checked)}
            className="rounded border-gray-600 bg-gray-700 text-teal-500 focus:ring-teal-500"
          />
          Include emerging patterns
        </label>
      </div>

      {patterns.length === 0 ? (
        <div className="text-center p-12 bg-gray-800 rounded-lg border border-gray-700">
          <div className="text-4xl mb-4">📊</div>
          <h3 className="text-lg font-medium text-white mb-2">No patterns discovered yet</h3>
          <p className="text-gray-400 text-sm max-w-md mx-auto">
            Patterns are discovered automatically as you accumulate data across domains
            (health, food, git activity, home, mood). Click "Run Discovery" to analyze your data.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {patterns.map((pattern) => (
            <div
              key={pattern.id}
              className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden"
            >
              {/* Pattern Header */}
              <div
                className="p-4 cursor-pointer hover:bg-gray-750"
                onClick={() => setExpandedId(expandedId === pattern.id ? null : pattern.id)}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`px-2 py-0.5 text-xs rounded border ${getStatusBadge(pattern.status)}`}>
                        {pattern.status}
                      </span>
                      <span className="text-xs text-gray-500">{pattern.category}</span>
                    </div>
                    <h3 className="text-white font-medium">{pattern.title}</h3>
                    {pattern.narrative && (
                      <p className="text-gray-400 text-sm mt-1 line-clamp-2">{pattern.narrative}</p>
                    )}
                  </div>

                  {/* Correlation Badge */}
                  <div className="text-right ml-4">
                    <div className={`text-2xl font-bold ${getCorrelationColor(pattern.correlation)}`}>
                      {pattern.correlation > 0 ? '+' : ''}{(pattern.correlation * 100).toFixed(0)}%
                    </div>
                    <div className="text-xs text-gray-500">correlation</div>
                  </div>
                </div>

                {/* Metrics Row */}
                <div className="mt-3 flex items-center gap-2 text-sm">
                  {formatMetric(pattern.metric_a)}
                  <span className="text-gray-500">→</span>
                  {formatMetric(pattern.metric_b)}
                  {pattern.lag_hours && (
                    <span className="text-xs text-gray-500 ml-2">
                      ({pattern.lag_hours}h lag)
                    </span>
                  )}
                </div>

                {/* Confidence Bar */}
                <div className="mt-3">
                  <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
                    <span>Confidence</span>
                    <span>{(pattern.confidence * 100).toFixed(0)}%</span>
                  </div>
                  <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-teal-500 rounded-full transition-all"
                      style={{ width: getConfidenceWidth(pattern.confidence) }}
                    />
                  </div>
                </div>
              </div>

              {/* Expanded Details */}
              {expandedId === pattern.id && (
                <div className="px-4 pb-4 pt-2 border-t border-gray-700 bg-gray-850">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                    <div>
                      <div className="text-xs text-gray-500">Sample Size</div>
                      <div className="text-white font-medium">{pattern.sample_size} days</div>
                    </div>
                    <div>
                      <div className="text-xs text-gray-500">P-Value</div>
                      <div className={`font-medium ${pattern.p_value && pattern.p_value < 0.05 ? 'text-green-400' : 'text-gray-400'}`}>
                        {pattern.p_value ? pattern.p_value.toFixed(4) : 'N/A'}
                        {pattern.p_value && pattern.p_value < 0.05 && ' (significant)'}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-gray-500">Validations</div>
                      <div className="text-green-400 font-medium">
                        {pattern.validations} / {pattern.validations + pattern.invalidations}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-gray-500">First Detected</div>
                      <div className="text-gray-300 text-sm">
                        {pattern.first_detected
                          ? new Date(pattern.first_detected).toLocaleDateString()
                          : 'Unknown'}
                      </div>
                    </div>
                  </div>

                  {pattern.description && (
                    <p className="text-gray-300 text-sm mb-4">{pattern.description}</p>
                  )}

                  {/* Feedback Buttons */}
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-500">Was this helpful?</span>
                    <button
                      onClick={(e) => { e.stopPropagation(); submitFeedback(pattern.id, 'helpful'); }}
                      className="px-3 py-1 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded"
                    >
                      👍 Yes
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); submitFeedback(pattern.id, 'not_helpful'); }}
                      className="px-3 py-1 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded"
                    >
                      👎 No
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); submitFeedback(pattern.id, 'dismissed'); }}
                      className="px-3 py-1 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded"
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
