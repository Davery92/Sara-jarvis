import React, { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../config'
import AttentionInbox from './AttentionInbox'
import MissionPanel from './MissionPanel'

interface Activity {
  id: string
  timestamp: string
  type: 'heartbeat' | 'notification' | 'journal'
  summary: string
  details?: Record<string, any>
  agent_type?: string
}

interface SaraStatus {
  emotional_state: string
  watching_for: string | null
  latest_thought: string | null
  last_action: string | null
  pending_observations: number
  hours_since_last_chat: number | null
  david_energy: number | null
  david_mood: string | null
  pkg_facts_count: number
}

const TYPE_COLORS: Record<string, string> = {
  heartbeat: 'bg-blue-500',
  notification: 'bg-yellow-500',
  journal: 'bg-purple-500',
}

const TYPE_ICONS: Record<string, string> = {
  heartbeat: 'favorite',
  notification: 'notifications',
  journal: 'auto_stories',
}

const EMOTION_EMOJI: Record<string, string> = {
  curious: '🤔',
  calm: '😌',
  alert: '⚡',
  concerned: '😟',
  happy: '😊',
  focused: '🎯',
  neutral: '😐',
  reflective: '🪞',
  attentive: '👀',
}

function formatRelativeTime(timestamp: string): string {
  const now = new Date()
  const then = new Date(timestamp)
  const diffMs = now.getTime() - then.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  const diffHr = Math.floor(diffMin / 60)

  if (diffMin < 1) return 'Just now'
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffHr < 24) return `${diffHr}h ago`
  return then.toLocaleDateString()
}

function formatTime(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

type TabType = 'timeline' | 'attention' | 'missions' | 'traces'

export default function AutonomyTimeline() {
  const [tab, setTab] = useState<TabType>('timeline')
  const [activities, setActivities] = useState<Activity[]>([])
  const [status, setStatus] = useState<SaraStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [hours, setHours] = useState(24)
  const [filterType, setFilterType] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [attentionCount, setAttentionCount] = useState(0)

  const fetchActivities = useCallback(async () => {
    try {
      const params = new URLSearchParams({ hours: hours.toString(), limit: '100' })
      if (filterType) params.append('activity_type', filterType)
      const res = await fetch(`${APP_CONFIG.API_BASE_URL}/api/sara/activity?${params}`, {
        credentials: 'include'
      })
      if (res.ok) {
        const data = await res.json()
        setActivities(data.activities || [])
      }
    } catch (e) {
      console.error('Failed to fetch activities:', e)
    }
  }, [hours, filterType])

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.API_BASE_URL}/api/sara/status`, {
        credentials: 'include'
      })
      if (res.ok) {
        setStatus(await res.json())
      }
    } catch (e) {
      console.error('Failed to fetch status:', e)
    }
  }, [])

  const fetchAttentionCount = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.API_BASE_URL}/autonomy/attention/count`, {
        credentials: 'include',
      })
      if (res.ok) {
        const data = await res.json()
        setAttentionCount(data.unread || 0)
      }
    } catch {
      // Attention queue may not exist yet
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    Promise.all([fetchActivities(), fetchStatus(), fetchAttentionCount()]).finally(() => setLoading(false))
    const interval = setInterval(() => {
      fetchActivities()
      fetchStatus()
      fetchAttentionCount()
    }, 60000)
    return () => clearInterval(interval)
  }, [fetchActivities, fetchStatus, fetchAttentionCount])

  const tabs: { key: TabType; label: string; icon: string; badge?: number }[] = [
    { key: 'timeline', label: 'Timeline', icon: 'timeline' },
    { key: 'attention', label: 'Attention', icon: 'inbox', badge: attentionCount },
    { key: 'missions', label: 'Missions', icon: 'flag' },
    { key: 'traces', label: 'Traces', icon: 'track_changes' },
  ]

  return (
    <div className="max-w-4xl mx-auto p-4 space-y-6">
      {/* Tab bar */}
      <div className="flex gap-1 bg-white/5 rounded-lg p-1">
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-all ${
              tab === t.key
                ? 'bg-teal-500/20 text-teal-400'
                : 'text-gray-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <span className="material-icons text-sm">{t.icon}</span>
            {t.label}
            {t.badge !== undefined && t.badge > 0 && (
              <span className="px-1.5 py-0.5 text-xs rounded-full bg-teal-500 text-white">
                {t.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content: Attention */}
      {tab === 'attention' && <AttentionInbox />}

      {/* Tab content: Missions */}
      {tab === 'missions' && <MissionPanel />}

      {/* Tab content: Traces */}
      {tab === 'traces' && <TracesPanel />}

      {/* Tab content: Timeline (original content) */}
      {tab !== 'timeline' ? null : <>

      {/* Status Card */}
      {status && (
        <div className="bg-card border border-card rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-white">Sara's Inner World</h2>
            <span className="text-2xl">{EMOTION_EMOJI[status.emotional_state] || '🤖'}</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <div className="text-gray-400">State</div>
              <div className="text-white capitalize">{status.emotional_state}</div>
            </div>
            <div>
              <div className="text-gray-400">David's Energy</div>
              <div className="text-white">
                {status.david_energy != null ? `${(status.david_energy * 100).toFixed(0)}%` : '—'}
              </div>
            </div>
            <div>
              <div className="text-gray-400">David's Mood</div>
              <div className="text-white capitalize">{status.david_mood || '—'}</div>
            </div>
            <div>
              <div className="text-gray-400">PKG Facts</div>
              <div className="text-white">{status.pkg_facts_count}</div>
            </div>
          </div>
          {status.latest_thought && (
            <div className="mt-4 p-3 bg-gray-800 rounded-lg">
              <div className="text-gray-400 text-xs mb-1">Latest Thought</div>
              <div className="text-gray-300 text-sm italic">{status.latest_thought}</div>
            </div>
          )}
          {status.watching_for && (
            <div className="mt-2 text-sm text-gray-400">
              <span className="material-icons text-xs align-middle mr-1">visibility</span>
              {status.watching_for}
            </div>
          )}
        </div>
      )}

      {/* Controls */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Autonomy Timeline</h2>
        <div className="flex items-center gap-2">
          {/* Time range */}
          <select
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
            className="bg-gray-800 text-white rounded px-2 py-1 text-sm border border-gray-700"
          >
            <option value={6}>6h</option>
            <option value={12}>12h</option>
            <option value={24}>24h</option>
            <option value={48}>48h</option>
            <option value={168}>7d</option>
          </select>
          {/* Type filter */}
          <select
            value={filterType || ''}
            onChange={(e) => setFilterType(e.target.value || null)}
            className="bg-gray-800 text-white rounded px-2 py-1 text-sm border border-gray-700"
          >
            <option value="">All</option>
            <option value="heartbeat">Heartbeat</option>
            <option value="notification">Notifications</option>
            <option value="journal">Journal</option>
          </select>
        </div>
      </div>

      {/* Timeline */}
      {loading ? (
        <div className="text-center text-gray-400 py-8">Loading timeline...</div>
      ) : activities.length === 0 ? (
        <div className="text-center text-gray-400 py-8">No activity in this period</div>
      ) : (
        <div className="relative">
          {/* Timeline line */}
          <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-gray-700" />

          {activities.map((activity) => (
            <div key={activity.id} className="relative pl-10 pb-6">
              {/* Dot */}
              <div className={`absolute left-2.5 w-3 h-3 rounded-full ${TYPE_COLORS[activity.type] || 'bg-gray-500'} ring-2 ring-gray-900`} />

              {/* Card */}
              <div
                className="bg-card border border-card rounded-lg p-4 cursor-pointer hover:border-gray-600 transition-colors"
                onClick={() => setExpandedId(expandedId === activity.id ? null : activity.id)}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <span className="material-icons text-sm text-gray-400">
                      {TYPE_ICONS[activity.type] || 'circle'}
                    </span>
                    <span className="text-xs uppercase tracking-wider text-gray-500 font-medium">
                      {activity.type}
                    </span>
                    {activity.agent_type && (
                      <span className="text-xs text-gray-600">({activity.agent_type})</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    <span>{formatTime(activity.timestamp)}</span>
                    <span className="text-gray-600">{formatRelativeTime(activity.timestamp)}</span>
                  </div>
                </div>

                <p className="text-sm text-gray-300">{activity.summary}</p>

                {/* Expanded details */}
                {expandedId === activity.id && activity.details && (
                  <div className="mt-3 pt-3 border-t border-gray-700 text-xs space-y-2">
                    {activity.details.emotional_state && (
                      <div>
                        <span className="text-gray-500">Emotional state:</span>{' '}
                        <span className="text-gray-300 capitalize">{activity.details.emotional_state}</span>
                      </div>
                    )}
                    {activity.details.actions && (
                      <div>
                        <span className="text-gray-500">Actions:</span>{' '}
                        <span className="text-gray-300">{activity.details.actions}</span>
                      </div>
                    )}
                    {activity.details.tools_used && (
                      <div>
                        <span className="text-gray-500">Tools:</span>{' '}
                        <span className="text-gray-300">{activity.details.tools_used}</span>
                      </div>
                    )}
                    {activity.details.full_content && activity.details.full_content !== activity.summary && (
                      <div className="mt-2 p-2 bg-gray-800 rounded text-gray-400 whitespace-pre-wrap">
                        {activity.details.full_content}
                      </div>
                    )}
                    {activity.details.sent !== undefined && (
                      <div>
                        <span className="text-gray-500">Status:</span>{' '}
                        <span className={activity.details.sent ? 'text-green-400' : 'text-yellow-400'}>
                          {activity.details.sent ? 'Sent' : 'Deduped'}
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      </>}
    </div>
  )
}

/** Inline traces panel — shows recent action traces */
function TracesPanel() {
  const [traces, setTraces] = useState<any[]>([])
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [hours, setHours] = useState(24)

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const [tracesRes, statsRes] = await Promise.all([
          fetch(`${APP_CONFIG.API_BASE_URL}/autonomy/traces?hours=${hours}&limit=50`, { credentials: 'include' }),
          fetch(`${APP_CONFIG.API_BASE_URL}/autonomy/traces/stats?hours=${hours}`, { credentials: 'include' }),
        ])
        if (tracesRes.ok) setTraces((await tracesRes.json()).traces || [])
        if (statsRes.ok) setStats(await statsRes.json())
      } catch (e) {
        console.error('Failed to load traces:', e)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [hours])

  const tierLabel = (tier: number) => tier === 0 ? 'Read' : tier === 1 ? 'Write' : 'Irreversible'
  const tierColor = (tier: number) => tier === 0 ? 'text-green-400' : tier === 1 ? 'text-yellow-400' : 'text-red-400'

  if (loading) return <div className="p-4 text-gray-400">Loading traces...</div>

  return (
    <div className="space-y-4">
      {/* Stats summary */}
      {stats && (
        <div className="bg-white/5 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="material-icons text-teal-400 text-sm">track_changes</span>
            <h3 className="text-sm font-medium text-white">Last {hours}h</h3>
            <div className="flex gap-1 ml-auto">
              {[6, 24, 48].map(h => (
                <button
                  key={h}
                  onClick={() => setHours(h)}
                  className={`text-xs px-2 py-0.5 rounded ${hours === h ? 'bg-teal-500/20 text-teal-400' : 'text-gray-500'}`}
                >
                  {h}h
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-3 md:grid-cols-6 gap-3 text-center text-xs">
            <div><span className="text-lg font-bold text-white">{stats.total}</span><br /><span className="text-gray-500">Total</span></div>
            <div><span className="text-lg font-bold text-green-400">{stats.succeeded}</span><br /><span className="text-gray-500">OK</span></div>
            <div><span className="text-lg font-bold text-red-400">{stats.failed}</span><br /><span className="text-gray-500">Failed</span></div>
            <div><span className="text-lg font-bold text-blue-400">{stats.runs}</span><br /><span className="text-gray-500">Runs</span></div>
            <div><span className="text-lg font-bold text-purple-400">{stats.unique_actions}</span><br /><span className="text-gray-500">Actions</span></div>
            <div><span className="text-lg font-bold text-gray-300">{stats.avg_duration_ms ? `${Math.round(stats.avg_duration_ms)}ms` : '-'}</span><br /><span className="text-gray-500">Avg</span></div>
          </div>
        </div>
      )}

      {/* Trace list */}
      <div className="space-y-1">
        {traces.map((trace: any) => (
          <div key={trace.id} className="flex items-center gap-2 px-3 py-2 rounded bg-white/5 text-xs">
            <span className={`material-icons text-sm ${trace.success ? 'text-green-500' : 'text-red-500'}`}>
              {trace.success ? 'check' : 'close'}
            </span>
            <span className="text-white font-mono">{trace.action_name}</span>
            <span className={`${tierColor(trace.risk_tier)}`}>[T{trace.risk_tier}]</span>
            <span className="text-gray-500">{trace.source}</span>
            {trace.decision !== 'allow' && (
              <span className="px-1 py-0.5 rounded bg-yellow-500/20 text-yellow-400">{trace.decision}</span>
            )}
            {trace.duration_ms && (
              <span className="text-gray-600">{trace.duration_ms}ms</span>
            )}
            <span className="text-gray-600 ml-auto">
              {new Date(trace.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>
        ))}
        {traces.length === 0 && (
          <div className="text-center py-8 text-gray-500">No traces in this period</div>
        )}
      </div>
    </div>
  )
}
