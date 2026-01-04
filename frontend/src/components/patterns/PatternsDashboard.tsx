import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../../config'
import PatternList from './PatternList'
import CorrelationMatrix from './CorrelationMatrix'
import PatternTimeSeries from './PatternTimeSeries'

interface PatternsDashboardProps {
  onBack?: () => void
}

type ViewMode = 'patterns' | 'matrix' | 'timeseries'

export default function PatternsDashboard({ onBack }: PatternsDashboardProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('patterns')
  const [discoveryStatus, setDiscoveryStatus] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [runningDiscovery, setRunningDiscovery] = useState(false)
  const [backfillResult, setBackfillResult] = useState<any>(null)

  useEffect(() => {
    loadDiscoveryStatus()
  }, [])

  const loadDiscoveryStatus = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/patterns/discovery-status`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setDiscoveryStatus(data)
      }
    } catch (error) {
      console.error('Failed to load discovery status:', error)
    }
  }

  const triggerDiscovery = async () => {
    setRunningDiscovery(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/patterns/discover?days=30`, {
        method: 'POST',
        credentials: 'include'
      })
      if (response.ok) {
        const result = await response.json()
        console.log('Discovery result:', result)
        await loadDiscoveryStatus()
      }
    } catch (error) {
      console.error('Discovery failed:', error)
    } finally {
      setRunningDiscovery(false)
    }
  }

  const triggerBackfill = async () => {
    setLoading(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/patterns/backfill?days=30`, {
        method: 'POST',
        credentials: 'include'
      })
      if (response.ok) {
        const result = await response.json()
        setBackfillResult(result)
      }
    } catch (error) {
      console.error('Backfill failed:', error)
    } finally {
      setLoading(false)
    }
  }

  const latestRun = discoveryStatus?.runs?.[0]

  return (
    <div className="p-4 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Pattern Correlation Engine</h1>
          <p className="text-gray-400 text-sm mt-1">
            Cross-domain patterns discovered from your data
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={triggerBackfill}
            disabled={loading}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-sm disabled:opacity-50"
          >
            {loading ? 'Backfilling...' : 'Backfill Data'}
          </button>
          <button
            onClick={triggerDiscovery}
            disabled={runningDiscovery}
            className="px-4 py-2 bg-teal-600 hover:bg-teal-500 text-white rounded-lg text-sm disabled:opacity-50"
          >
            {runningDiscovery ? 'Running...' : 'Run Discovery'}
          </button>
        </div>
      </div>

      {/* Backfill Result */}
      {backfillResult && (
        <div className="mb-4 p-3 bg-green-900/30 border border-green-700 rounded-lg text-green-300 text-sm">
          Backfill complete: {backfillResult.bins_created} bins created, {backfillResult.bins_updated} updated
          <button onClick={() => setBackfillResult(null)} className="ml-2 text-green-400 hover:text-green-200">
            &times;
          </button>
        </div>
      )}

      {/* Discovery Status Card */}
      {latestRun && (
        <div className="mb-6 p-4 bg-gray-800 rounded-lg border border-gray-700">
          <h3 className="text-sm font-medium text-gray-400 mb-2">Last Discovery Run</h3>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div>
              <div className="text-xs text-gray-500">Status</div>
              <div className={`text-sm font-medium ${
                latestRun.status === 'completed' ? 'text-green-400' :
                latestRun.status === 'running' ? 'text-yellow-400' : 'text-red-400'
              }`}>
                {latestRun.status}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-500">Patterns Found</div>
              <div className="text-sm font-medium text-white">{latestRun.patterns_discovered || 0}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500">Validated</div>
              <div className="text-sm font-medium text-green-400">{latestRun.patterns_validated || 0}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500">Invalidated</div>
              <div className="text-sm font-medium text-red-400">{latestRun.patterns_invalidated || 0}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500">Last Run</div>
              <div className="text-sm font-medium text-gray-300">
                {latestRun.completed_at ? new Date(latestRun.completed_at).toLocaleString() : 'In progress...'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* View Mode Tabs */}
      <div className="flex gap-2 mb-6 border-b border-gray-700 pb-2">
        <button
          onClick={() => setViewMode('patterns')}
          className={`px-4 py-2 rounded-t-lg text-sm font-medium transition-colors ${
            viewMode === 'patterns'
              ? 'bg-teal-600 text-white'
              : 'text-gray-400 hover:text-white hover:bg-gray-700'
          }`}
        >
          Discovered Patterns
        </button>
        <button
          onClick={() => setViewMode('matrix')}
          className={`px-4 py-2 rounded-t-lg text-sm font-medium transition-colors ${
            viewMode === 'matrix'
              ? 'bg-teal-600 text-white'
              : 'text-gray-400 hover:text-white hover:bg-gray-700'
          }`}
        >
          Correlation Matrix
        </button>
        <button
          onClick={() => setViewMode('timeseries')}
          className={`px-4 py-2 rounded-t-lg text-sm font-medium transition-colors ${
            viewMode === 'timeseries'
              ? 'bg-teal-600 text-white'
              : 'text-gray-400 hover:text-white hover:bg-gray-700'
          }`}
        >
          Time Series
        </button>
      </div>

      {/* Content */}
      <div className="min-h-[500px]">
        {viewMode === 'patterns' && <PatternList />}
        {viewMode === 'matrix' && <CorrelationMatrix />}
        {viewMode === 'timeseries' && <PatternTimeSeries />}
      </div>
    </div>
  )
}
