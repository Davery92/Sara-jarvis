import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../../config'

interface CorrelationData {
  metrics: string[]
  matrix: Record<string, Record<string, number>>
  days_analyzed: number
}

export default function CorrelationMatrix() {
  const [data, setData] = useState<CorrelationData | null>(null)
  const [loading, setLoading] = useState(true)
  const [days, setDays] = useState(30)
  const [hoveredCell, setHoveredCell] = useState<{ row: string; col: string } | null>(null)

  useEffect(() => {
    loadMatrix()
  }, [days])

  const loadMatrix = async () => {
    setLoading(true)
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/patterns/correlations?days=${days}`,
        { credentials: 'include' }
      )
      if (response.ok) {
        const result = await response.json()
        setData(result)
      }
    } catch (error) {
      console.error('Failed to load correlation matrix:', error)
    } finally {
      setLoading(false)
    }
  }

  const getCorrelationColor = (r: number | undefined) => {
    if (r === undefined || r === null) return 'bg-gray-800'

    const abs = Math.abs(r)
    if (abs < 0.1) return 'bg-gray-700'

    // Positive correlations: green
    if (r > 0) {
      if (abs >= 0.7) return 'bg-green-600'
      if (abs >= 0.5) return 'bg-green-700'
      if (abs >= 0.3) return 'bg-green-800'
      return 'bg-green-900'
    }

    // Negative correlations: red
    if (abs >= 0.7) return 'bg-red-600'
    if (abs >= 0.5) return 'bg-red-700'
    if (abs >= 0.3) return 'bg-red-800'
    return 'bg-red-900'
  }

  const formatMetricLabel = (metric: string) => {
    const [domain, field] = metric.split('.')
    const shortField = field?.replace(/_/g, ' ').substring(0, 12) || ''
    return (
      <div className="text-xs">
        <div className="text-gray-500 text-[10px]">{domain}</div>
        <div className="text-gray-300 truncate" title={field}>{shortField}</div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-teal-400"></div>
      </div>
    )
  }

  if (!data || data.metrics.length === 0) {
    return (
      <div className="text-center p-12 bg-gray-800 rounded-lg border border-gray-700">
        <div className="text-4xl mb-4">📈</div>
        <h3 className="text-lg font-medium text-white mb-2">No correlation data available</h3>
        <p className="text-gray-400 text-sm max-w-md mx-auto">
          Backfill temporal bins and run discovery to generate correlation data.
        </p>
      </div>
    )
  }

  const metrics = data.metrics

  return (
    <div>
      {/* Controls */}
      <div className="flex items-center justify-between mb-4">
        <div className="text-sm text-gray-400">
          Analyzing {data.days_analyzed} days of data across {metrics.length} metrics
        </div>
        <select
          value={days}
          onChange={(e) => setDays(parseInt(e.target.value))}
          className="bg-gray-700 border border-gray-600 text-white text-sm rounded px-3 py-1"
        >
          <option value={14}>14 days</option>
          <option value={30}>30 days</option>
          <option value={60}>60 days</option>
          <option value={90}>90 days</option>
        </select>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 mb-4 text-xs">
        <span className="text-gray-500">Correlation strength:</span>
        <div className="flex items-center gap-1">
          <div className="w-4 h-4 bg-red-600 rounded"></div>
          <span className="text-gray-400">Strong -</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-4 h-4 bg-red-900 rounded"></div>
          <span className="text-gray-400">Weak -</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-4 h-4 bg-gray-700 rounded"></div>
          <span className="text-gray-400">None</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-4 h-4 bg-green-900 rounded"></div>
          <span className="text-gray-400">Weak +</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-4 h-4 bg-green-600 rounded"></div>
          <span className="text-gray-400">Strong +</span>
        </div>
      </div>

      {/* Hovered Cell Info */}
      {hoveredCell && hoveredCell.row !== hoveredCell.col && data.matrix[hoveredCell.row]?.[hoveredCell.col] != null && (
        <div className="mb-4 p-3 bg-gray-800 rounded-lg border border-gray-700">
          <div className="text-sm text-white">
            <span className="text-gray-400">{hoveredCell.row}</span>
            <span className="mx-2">→</span>
            <span className="text-gray-400">{hoveredCell.col}</span>
          </div>
          <div className="text-2xl font-bold mt-1">
            {(data.matrix[hoveredCell.row][hoveredCell.col] * 100).toFixed(1)}%
          </div>
        </div>
      )}

      {/* Matrix Grid */}
      <div className="overflow-x-auto">
        <div className="inline-block min-w-full">
          <table className="border-collapse">
            <thead>
              <tr>
                <th className="w-24"></th>
                {metrics.map((metric) => (
                  <th
                    key={metric}
                    className="w-16 h-20 p-1 text-center align-bottom"
                    style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}
                  >
                    {formatMetricLabel(metric)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {metrics.map((rowMetric) => (
                <tr key={rowMetric}>
                  <td className="w-24 p-1 text-right pr-2">
                    {formatMetricLabel(rowMetric)}
                  </td>
                  {metrics.map((colMetric) => {
                    const value = data.matrix[rowMetric]?.[colMetric]
                    const isSame = rowMetric === colMetric
                    const isHovered = hoveredCell?.row === rowMetric && hoveredCell?.col === colMetric

                    return (
                      <td
                        key={colMetric}
                        className={`w-16 h-12 p-0.5 cursor-pointer transition-all ${
                          isHovered ? 'ring-2 ring-teal-400' : ''
                        }`}
                        onMouseEnter={() => setHoveredCell({ row: rowMetric, col: colMetric })}
                        onMouseLeave={() => setHoveredCell(null)}
                      >
                        <div
                          className={`w-full h-full rounded flex items-center justify-center text-xs font-medium ${
                            isSame ? 'bg-gray-600 text-gray-400' : getCorrelationColor(value)
                          } ${value != null && Math.abs(value) >= 0.3 ? 'text-white' : 'text-gray-400'}`}
                        >
                          {isSame ? '1.0' : value != null ? value.toFixed(2) : '-'}
                        </div>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
