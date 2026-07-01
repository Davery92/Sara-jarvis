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

  const calculateStats = (metric: keyof RecoveryData) => {
    const values = recoveryData
      .map(d => d[metric] as number)
      .filter(v => v !== null && v !== undefined && !isNaN(v))

    if (values.length === 0) return { avg: 0, min: 0, max: 0, trend: 0 }

    const avg = values.reduce((a, b) => a + b, 0) / values.length
    const min = Math.min(...values)
    const max = Math.max(...values)

    // Calculate trend: compare first half vs second half
    const midpoint = Math.floor(values.length / 2)
    const firstHalf = values.slice(0, midpoint)
    const secondHalf = values.slice(midpoint)
    const firstAvg = firstHalf.reduce((a, b) => a + b, 0) / firstHalf.length
    const secondAvg = secondHalf.reduce((a, b) => a + b, 0) / secondHalf.length
    const trend = ((secondAvg - firstAvg) / firstAvg) * 100

    return { avg, min, max, trend }
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
            {/* Line */}
            <polyline
              points={recoveryData.map((d, i) => {
                const value = d[selectedMetric] as number
                if (value === null || value === undefined) return null
                const x = (i / (recoveryData.length - 1 || 1)) * 100
                const y = 100 - ((value - minValue) / range) * 100
                return `${x},${y}`
              }).filter(Boolean).join(' ')}
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className={getMetricColor(selectedMetric)}
              vectorEffect="non-scaling-stroke"
            />

          </svg>

          {/* Data point markers — rendered as HTML so they stay perfectly round
              regardless of the chart's width (SVG circles get stretched by
              preserveAspectRatio="none") */}
          {recoveryData.map((d, i) => {
            const value = d[selectedMetric] as number
            if (value === null || value === undefined) return null
            const x = (i / (recoveryData.length - 1 || 1)) * 100
            const y = 100 - ((value - minValue) / range) * 100
            return (
              <div
                key={i}
                className={`absolute w-1.5 h-1.5 rounded-full ring-2 ring-[#0f1a2c] ${getMetricBgColor(selectedMetric)}`}
                style={{ left: `${x}%`, top: `${y}%`, transform: 'translate(-50%, -50%)' }}
                title={`${new Date(d.log_date).toLocaleDateString()}: ${value}`}
              />
            )
          })}
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
                {stats.trend !== 0 && (
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
                  {stats.avg > 0 ? stats.avg.toFixed(1) : '--'}
                  <span className="text-xs font-normal ml-1">{metric.unit}</span>
                </div>
                {stats.avg > 0 && (
                  <div className="text-xs opacity-75 mt-1">
                    {stats.min.toFixed(0)}-{stats.max.toFixed(0)} {metric.unit}
                  </div>
                )}
              </div>
            </button>
          )
        })}
      </div>

      {/* Chart */}
      {renderChart()}

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
                {calculateStats('hrv').avg > 0 ? `${calculateStats('hrv').avg.toFixed(0)} ms` : '--'}
              </div>
            </div>
            <div>
              <div className="text-slate-400 mb-1">Avg Sleep</div>
              <div className="text-white font-semibold">
                {calculateStats('sleep_hours').avg > 0 ? `${calculateStats('sleep_hours').avg.toFixed(1)} hrs` : '--'}
              </div>
            </div>
            <div>
              <div className="text-slate-400 mb-1">Avg Soreness</div>
              <div className="text-white font-semibold">
                {calculateStats('soreness_level').avg > 0 ? `${calculateStats('soreness_level').avg.toFixed(1)}/10` : '--'}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default RecoveryTrendChart
