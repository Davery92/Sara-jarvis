import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../../config'
import { TrendingUp, TrendingDown, Activity, Heart, Moon, Zap, Weight } from 'lucide-react'

interface RecoveryData {
  id: string
  log_date: string
  hrv?: number | null
  heart_rate?: number | null
  sleep_hours?: number | null
  soreness_level?: number | null
  body_weight?: number | null
  weight_unit?: string
  notes?: string
}

interface RecoveryTrendChartProps {
  days?: number
  compact?: boolean
}

const RecoveryTrendChart: React.FC<RecoveryTrendChartProps> = ({ days = 30, compact = false }) => {
  const [recoveryData, setRecoveryData] = useState<RecoveryData[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedMetric, setSelectedMetric] = useState<'hrv' | 'heart_rate' | 'sleep_hours' | 'soreness_level' | 'body_weight'>('hrv')

  useEffect(() => {
    fetchRecoveryData()
  }, [days])

  const fetchRecoveryData = async () => {
    try {
      setLoading(true)
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/recovery/recent/list?days=${days}`, {
        credentials: 'include'
      })

      if (response.ok) {
        const data = await response.json()
        // Reverse to show oldest to newest
        setRecoveryData(data.reverse())
      }
    } catch (error) {
      console.error('Failed to fetch recovery data:', error)
    } finally {
      setLoading(false)
    }
  }

  /**
   * Minimum readings before a first-half/second-half comparison is called a
   * trend. Four readings means two per half, and two numbers differing is
   * not a direction — it is the gap between two days.
   */
  const MIN_READINGS_FOR_TREND = 6

  /**
   * Stats, with `null` for "not recorded" rather than 0.
   *
   * Returning `{avg: 0}` and rendering it through `avg > 0 ? … : '--'` worked
   * by accident: it also hides a genuine zero, and `trend: 0` made the arrow
   * vanish for a metric that really had not moved, which is a different
   * statement from having no data.
   */
  const calculateStats = (metric: keyof RecoveryData) => {
    const values = recoveryData
      .map(d => d[metric] as number)
      .filter(v => v !== null && v !== undefined && !isNaN(v))

    const observed = values.length
    const expected = recoveryData.length
    if (observed === 0) {
      return { avg: null, min: null, max: null, trend: null, observed, expected }
    }

    const avg = values.reduce((a, b) => a + b, 0) / observed
    const min = Math.min(...values)
    const max = Math.max(...values)

    if (observed < MIN_READINGS_FOR_TREND) {
      return { avg, min, max, trend: null, observed, expected }
    }

    const midpoint = Math.floor(observed / 2)
    const firstHalf = values.slice(0, midpoint)
    const secondHalf = values.slice(midpoint)
    const firstAvg = firstHalf.reduce((a, b) => a + b, 0) / firstHalf.length
    const secondAvg = secondHalf.reduce((a, b) => a + b, 0) / secondHalf.length
    const trend = firstAvg === 0 ? null : ((secondAvg - firstAvg) / firstAvg) * 100

    return { avg, min, max, trend, observed, expected }
  }

  const getMetricColor = (metric: string) => {
    switch (metric) {
      case 'hrv': return 'text-teal-400'
      case 'heart_rate': return 'text-red-400'
      case 'sleep_hours': return 'text-blue-400'
      case 'soreness_level': return 'text-orange-400'
      case 'body_weight': return 'text-purple-400'
      default: return 'text-gray-400'
    }
  }

  const getMetricBgColor = (metric: string) => {
    switch (metric) {
      case 'hrv': return 'bg-teal-500'
      case 'heart_rate': return 'bg-red-500'
      case 'sleep_hours': return 'bg-blue-500'
      case 'soreness_level': return 'bg-orange-500'
      case 'body_weight': return 'bg-purple-500'
      default: return 'bg-gray-500'
    }
  }

  const renderChart = () => {
    if (recoveryData.length === 0) {
      return (
        <div className="flex items-center justify-center h-64 text-slate-400">
          No recovery data available. Start logging your daily metrics!
        </div>
      )
    }

    const values = recoveryData.map(d => d[selectedMetric] as number).filter(v => v !== null && v !== undefined)
    if (values.length === 0) {
      return (
        <div className="flex items-center justify-center h-64 text-slate-400">
          No {selectedMetric.replace('_', ' ')} data logged yet
        </div>
      )
    }

    const maxValue = Math.max(...values)
    const minValue = Math.min(...values)
    const range = maxValue - minValue || 1

    // x is placed by DATE, not by row index. Index spacing drew a reading on
    // the 1st, the 2nd and the 29th as three evenly spaced points, so the
    // three-week gap vanished and the line read as a steady trend.
    const times = recoveryData
      .map(d => new Date(d.log_date).getTime())
      .filter(t => !isNaN(t))
    const firstTime = times.length ? Math.min(...times) : 0
    const lastTime = times.length ? Math.max(...times) : 0
    const timeSpan = lastTime - firstTime || 1

    const points = recoveryData.map(d => {
      const value = d[selectedMetric] as number
      const time = new Date(d.log_date).getTime()
      if (value === null || value === undefined || isNaN(value) || isNaN(time)) {
        return null
      }
      return {
        log_date: d.log_date,
        value,
        x: ((time - firstTime) / timeSpan) * 100,
        y: 100 - ((value - minValue) / range) * 100,
      }
    })

    // Contiguous runs, so the line BREAKS at a gap. Filtering the missing
    // rows out of one polyline joined the readings either side of a gap and
    // drew a segment through days nobody logged — the same invented data a
    // Recharts `connectNulls={true}` produces.
    const runs: Array<Array<{ x: number; y: number }>> = []
    let run: Array<{ x: number; y: number }> = []
    for (const point of points) {
      if (point === null) {
        if (run.length) runs.push(run)
        run = []
        continue
      }
      run.push({ x: point.x, y: point.y })
    }
    if (run.length) runs.push(run)

    const plotted = points.filter(Boolean) as Array<{
      log_date: string; value: number; x: number; y: number
    }>

    return (
      <div className="relative h-64">
        {/* Y-axis labels */}
        <div className="absolute left-0 top-0 bottom-8 w-12 flex flex-col justify-between text-xs text-slate-500">
          <span>{maxValue.toFixed(1)}</span>
          <span>{((maxValue + minValue) / 2).toFixed(1)}</span>
          <span>{minValue.toFixed(1)}</span>
        </div>

        {/* Chart area */}
        <div className="absolute left-12 right-0 top-0 bottom-8 border-l border-b border-white/10">
          {/* Grid lines */}
          <div className="absolute inset-0 flex flex-col justify-between">
            <div className="border-t border-white/5"></div>
            <div className="border-t border-white/5"></div>
            <div className="border-t border-white/5"></div>
          </div>

          {/* Data points and line */}
          <svg className="absolute inset-0 w-full h-full" viewBox="0 0 100 100" preserveAspectRatio="none">
            {/* One polyline per contiguous run. A gap in the log is a gap in
                the line, not a straight segment across it. */}
            {runs.map((segment, index) => (
              <polyline
                key={index}
                points={segment.map(p => `${p.x},${p.y}`).join(' ')}
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className={getMetricColor(selectedMetric)}
                vectorEffect="non-scaling-stroke"
              />
            ))}
          </svg>

          {/* Data point markers — rendered as HTML so they stay perfectly round
              regardless of the chart's width (SVG circles get stretched by
              preserveAspectRatio="none") */}
          {plotted.map((point) => (
            <div
              key={point.log_date}
              className={`absolute w-1.5 h-1.5 rounded-full ring-2 ring-[#0f1a2c] ${getMetricBgColor(selectedMetric)}`}
              style={{
                left: `${point.x}%`, top: `${point.y}%`,
                transform: 'translate(-50%, -50%)',
              }}
              title={`${new Date(point.log_date).toLocaleDateString()}: ${point.value}`}
            />
          ))}
        </div>

        {/* X-axis labels (dates) */}
        <div className="absolute left-12 right-0 bottom-0 h-8 flex justify-between text-xs text-slate-500">
          {recoveryData.length > 0 && (
            <>
              <span>{new Date(recoveryData[0].log_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
              {recoveryData.length > 1 && (
                <span>{new Date(recoveryData[recoveryData.length - 1].log_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
              )}
            </>
          )}
        </div>
      </div>
    )
  }

  /** Coverage for whatever the chart is currently showing. */
  const renderCoverage = () => {
    const stats = calculateStats(selectedMetric)
    if (stats.observed === 0) return null
    return (
      <p className="text-[11px] text-slate-500 mt-2" data-testid="recovery-coverage">
        {stats.observed} of the last {days} days have a
        {' '}{selectedMetric.replace(/_/g, ' ')} reading. Points sit on their
        real dates and the line breaks where nothing was logged — a flat
        stretch means flat, not missing.
      </p>
    )
  }

  const metrics = [
    { key: 'hrv' as const, label: 'HRV', icon: Zap, unit: 'ms' },
    { key: 'heart_rate' as const, label: 'Resting HR', icon: Heart, unit: 'bpm' },
    { key: 'sleep_hours' as const, label: 'Sleep', icon: Moon, unit: 'hrs' },
    { key: 'soreness_level' as const, label: 'Soreness', icon: Activity, unit: '/10' },
    { key: 'body_weight' as const, label: 'Weight', icon: Weight, unit: 'lbs' },
  ]

  if (loading) {
    return (
      <div className="assistant-panel rounded-xl p-6">
        <div className="flex items-center justify-center h-64 text-slate-400">
          Loading recovery trends...
        </div>
      </div>
    )
  }

  return (
    <div className="assistant-panel rounded-xl p-6">
      {!compact && (
        <h2 className="font-display text-2xl font-bold text-white mb-4">Recovery Trends ({days} days)</h2>
      )}

      {/* Metric selector */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-6">
        {metrics.map(metric => {
          const stats = calculateStats(metric.key)
          const Icon = metric.icon
          const isSelected = selectedMetric === metric.key

          return (
            <button
              key={metric.key}
              onClick={() => setSelectedMetric(metric.key)}
              className={`p-4 rounded-lg border transition-all ${
                isSelected
                  ? `${getMetricBgColor(metric.key)} border-transparent text-white`
                  : 'bg-white/5 border-white/10 text-slate-400 hover:border-white/20'
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <Icon className="w-5 h-5" />
                {/* No arrow without enough readings to call it a direction.
                    Two numbers differing is the gap between two days. */}
                {stats.trend !== null && stats.trend !== 0 && (
                  stats.trend > 0 ? (
                    <TrendingUp className="w-4 h-4 text-green-400" />
                  ) : (
                    <TrendingDown className="w-4 h-4 text-red-400" />
                  )
                )}
              </div>
              <div className="text-left">
                <div className="text-xs font-medium mb-1">{metric.label}</div>
                <div className="text-lg font-bold">
                  {stats.avg !== null ? stats.avg.toFixed(1) : '--'}
                  <span className="text-xs font-normal ml-1">{metric.unit}</span>
                </div>
                {stats.avg !== null && stats.min !== null && stats.max !== null && (
                  <div className="text-xs opacity-75 mt-1">
                    {stats.min.toFixed(0)}-{stats.max.toFixed(0)} {metric.unit}
                    {/* The denominator, so a mean of two days does not read
                        like a mean of thirty. */}
                    <span className="ml-1">· {stats.observed}d</span>
                  </div>
                )}
              </div>
            </button>
          )
        })}
      </div>

      {/* Chart */}
      {renderChart()}
      {renderCoverage()}

      {/* Stats summary */}
      {recoveryData.length > 0 && (
        <div className="mt-6 pt-6 border-t border-white/10">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center text-sm">
            <div>
              <div className="text-slate-400 mb-1">Logs</div>
              <div className="text-white font-semibold">{recoveryData.length}</div>
            </div>
            <div>
              <div className="text-slate-400 mb-1">Avg HRV</div>
              <div className="text-white font-semibold">
                {(() => {
                  const s = calculateStats('hrv')
                  return s.avg !== null ? `${s.avg.toFixed(0)} ms · ${s.observed}d` : '--'
                })()}
              </div>
            </div>
            <div>
              <div className="text-slate-400 mb-1">Avg Sleep</div>
              <div className="text-white font-semibold">
                {(() => {
                  const s = calculateStats('sleep_hours')
                  return s.avg !== null ? `${s.avg.toFixed(1)} hrs · ${s.observed}d` : '--'
                })()}
              </div>
            </div>
            <div>
              <div className="text-slate-400 mb-1">Avg Soreness</div>
              <div className="text-white font-semibold">
                {(() => {
                  const s = calculateStats('soreness_level')
                  return s.avg !== null ? `${s.avg.toFixed(1)}/10 · ${s.observed}d` : '--'
                })()}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default RecoveryTrendChart
