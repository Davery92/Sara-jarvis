import React, { useState, useEffect, useMemo } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend
} from 'recharts'
import { APP_CONFIG } from '../../config'

const AVAILABLE_METRICS = [
  { value: 'health.sleep_hours', label: 'Sleep Hours', domain: 'health', color: '#60a5fa' },
  { value: 'health.hrv', label: 'HRV', domain: 'health', color: '#34d399' },
  { value: 'health.resting_hr', label: 'Resting HR', domain: 'health', color: '#f87171' },
  { value: 'health.steps', label: 'Steps', domain: 'health', color: '#fbbf24' },
  { value: 'health.active_energy', label: 'Active Energy', domain: 'health', color: '#a78bfa' },
  { value: 'git.commit_count', label: 'Commits', domain: 'git', color: '#fb923c' },
  { value: 'git.additions', label: 'Lines Added', domain: 'git', color: '#22d3ee' },
  { value: 'git.late_commits', label: 'Late Commits', domain: 'git', color: '#e879f9' },
  { value: 'food.total_calories', label: 'Calories', domain: 'food', color: '#4ade80' },
  { value: 'food.protein_g', label: 'Protein (g)', domain: 'food', color: '#f472b6' },
  { value: 'mood.avg_sentiment', label: 'Sentiment', domain: 'mood', color: '#fcd34d' },
  { value: 'mood.avg_energy', label: 'Energy Level', domain: 'mood', color: '#6ee7b7' },
]

interface TimeSeriesData {
  series: Record<string, Array<{ date: string; value: number | null; day_of_week: number }>>
  days: number
  data_points: number
}

export default function PatternTimeSeries() {
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>([
    'health.sleep_hours',
    'git.commit_count'
  ])
  const [data, setData] = useState<TimeSeriesData | null>(null)
  const [loading, setLoading] = useState(false)
  const [days, setDays] = useState(30)

  useEffect(() => {
    if (selectedMetrics.length > 0) {
      loadTimeSeries()
    }
  }, [selectedMetrics, days])

  const loadTimeSeries = async () => {
    setLoading(true)
    try {
      const metricsParam = selectedMetrics.join(',')
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/patterns/timeseries?metrics=${metricsParam}&days=${days}`,
        { credentials: 'include' }
      )
      if (response.ok) {
        const result = await response.json()
        setData(result)
      }
    } catch (error) {
      console.error('Failed to load time series:', error)
    } finally {
      setLoading(false)
    }
  }

  const toggleMetric = (metric: string) => {
    if (selectedMetrics.includes(metric)) {
      setSelectedMetrics(selectedMetrics.filter(m => m !== metric))
    } else if (selectedMetrics.length < 4) {
      setSelectedMetrics([...selectedMetrics, metric])
    }
  }

  const chartData = useMemo(() => {
    if (!data?.series) return []

    // Merge all series into single data points by date
    const dateMap = new Map<string, Record<string, any>>()

    for (const [metric, points] of Object.entries(data.series)) {
      for (const point of points) {
        if (!dateMap.has(point.date)) {
          dateMap.set(point.date, { date: point.date })
        }
        const entry = dateMap.get(point.date)!
        entry[metric] = point.value
      }
    }

    return Array.from(dateMap.values()).sort((a, b) => a.date.localeCompare(b.date))
  }, [data])

  const getMetricInfo = (metric: string) => {
    return AVAILABLE_METRICS.find(m => m.value === metric)
  }

  // Group metrics by domain
  const metricsByDomain = useMemo(() => {
    const grouped: Record<string, typeof AVAILABLE_METRICS> = {}
    for (const metric of AVAILABLE_METRICS) {
      if (!grouped[metric.domain]) {
        grouped[metric.domain] = []
      }
      grouped[metric.domain].push(metric)
    }
    return grouped
  }, [])

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }

  return (
    <div>
      {/* Metric Selector */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <div className="text-sm text-gray-400">
            Select up to 4 metrics to compare ({selectedMetrics.length}/4 selected)
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

        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2">
          {Object.entries(metricsByDomain).map(([domain, metrics]) => (
            <div key={domain} className="space-y-1">
              <div className="text-xs text-gray-500 uppercase tracking-wide">{domain}</div>
              {metrics.map((metric) => {
                const isSelected = selectedMetrics.includes(metric.value)
                return (
                  <button
                    key={metric.value}
                    onClick={() => toggleMetric(metric.value)}
                    disabled={!isSelected && selectedMetrics.length >= 4}
                    className={`w-full px-2 py-1.5 rounded text-xs text-left transition-colors ${
                      isSelected
                        ? 'bg-teal-600 text-white'
                        : 'bg-gray-700 text-gray-300 hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed'
                    }`}
                    style={isSelected ? { backgroundColor: metric.color } : undefined}
                  >
                    {metric.label}
                  </button>
                )
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Chart */}
      {loading ? (
        <div className="flex items-center justify-center h-80">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-teal-400"></div>
        </div>
      ) : chartData.length === 0 ? (
        <div className="text-center p-12 bg-gray-800 rounded-lg border border-gray-700">
          <div className="text-4xl mb-4">📉</div>
          <h3 className="text-lg font-medium text-white mb-2">No time series data</h3>
          <p className="text-gray-400 text-sm">
            Select metrics and ensure temporal bins have been backfilled.
          </p>
        </div>
      ) : (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 overflow-x-auto">
          <LineChart width={800} height={400} data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="date"
              stroke="#9ca3af"
              tickFormatter={formatDate}
              fontSize={12}
            />
            <YAxis stroke="#9ca3af" fontSize={12} />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1f2937',
                border: '1px solid #374151',
                borderRadius: '8px'
              }}
              labelFormatter={(label) => formatDate(label as string)}
            />
            <Legend />
            {selectedMetrics.map((metric) => {
              const info = getMetricInfo(metric)
              return (
                <Line
                  key={metric}
                  type="monotone"
                  dataKey={metric}
                  name={info?.label || metric}
                  stroke={info?.color || '#8884d8'}
                  strokeWidth={2}
                  connectNulls={true}
                  dot={{ r: 3, fill: info?.color || '#8884d8' }}
                />
              )
            })}
          </LineChart>
        </div>
      )}

      {/* Data Stats */}
      {data && (
        <div className="mt-4 text-sm text-gray-500 text-center">
          Showing {data.data_points} data points over {data.days} days
        </div>
      )}
    </div>
  )
}
