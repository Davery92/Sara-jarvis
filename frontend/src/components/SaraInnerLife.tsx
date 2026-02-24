import React, { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../config'

// ── Types ────────────────────────────────────────────────────

interface WorkingMemory {
  activity_state?: string
  activity_confidence?: number
  room?: string
  interruptibility?: number
  mood?: string
  alertness?: string
  stress_load?: string
  circadian_phase?: string
  sara_focus?: string
  sara_emotional_tone?: string
  sara_curiosities?: string | string[]
  sara_last_deliberation_at?: string
  sara_deliberation_count_today?: number
  observation_count?: number
  salience_high_water?: number
  last_heartbeat_watching_for?: string
  quiet_mode?: boolean
  hours_since_last_chat?: number
  last_chat_at?: string
  next_event_title?: string
  next_event_minutes_away?: number
  notifications_sent_today?: number
  today_habit_status?: string
  recent_notes_summary?: string
  home_occupied?: boolean
  temperature_inside?: number
  temperature_outside?: number
  weather_condition?: string
  updated_at?: string
  error?: string
}

interface DeliberationEntry {
  source: string
  thought: string | null
  handoff_note: string | null
  watching_for: string | null
  actions_taken: any
  duration_seconds: number | null
  run_at: string | null
  created_at: string | null
}

interface Observation {
  id: string
  timestamp: string
  source: string
  description: string
  salience: number
  category: string
}

// ── Helpers ──────────────────────────────────────────────────

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return ''
  const now = new Date()
  const date = new Date(dateStr)
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins} min ago`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  return `${Math.floor(diffHours / 24)}d ago`
}

function emotionIndicator(tone: string | undefined): { color: string; label: string } {
  if (!tone) return { color: 'bg-gray-500', label: 'Unknown' }
  const lower = tone.toLowerCase()
  if (lower.includes('calm') || lower.includes('content') || lower.includes('peaceful'))
    return { color: 'bg-green-500', label: tone }
  if (lower.includes('curious') || lower.includes('engaged') || lower.includes('interested'))
    return { color: 'bg-blue-500', label: tone }
  if (lower.includes('concern') || lower.includes('worry') || lower.includes('anxious'))
    return { color: 'bg-yellow-500', label: tone }
  if (lower.includes('warm') || lower.includes('caring') || lower.includes('affection'))
    return { color: 'bg-pink-500', label: tone }
  if (lower.includes('focused') || lower.includes('alert'))
    return { color: 'bg-purple-500', label: tone }
  return { color: 'bg-teal-500', label: tone }
}

function formatActions(actions: any): string[] {
  if (!actions) return []
  if (typeof actions === 'string') {
    try {
      const parsed = JSON.parse(actions)
      if (Array.isArray(parsed)) return parsed.map(String)
      return [actions]
    } catch {
      return actions.split(',').map((s: string) => s.trim()).filter(Boolean)
    }
  }
  if (Array.isArray(actions)) return actions.map(String)
  return []
}

function salienceBar(salience: number): string {
  if (salience >= 0.8) return 'bg-red-500'
  if (salience >= 0.5) return 'bg-yellow-500'
  if (salience >= 0.3) return 'bg-blue-500'
  return 'bg-gray-500'
}

function hoursSince(dateStr?: string): number | null {
  if (!dateStr) return null
  const ts = Date.parse(dateStr)
  if (Number.isNaN(ts)) return null
  return (Date.now() - ts) / 3600000
}

// ── Component ────────────────────────────────────────────────

type TabType = 'overview' | 'thoughts' | 'observations'

export default function SaraInnerLife() {
  const [tab, setTab] = useState<TabType>('overview')
  const [memory, setMemory] = useState<WorkingMemory | null>(null)
  const [deliberations, setDeliberations] = useState<DeliberationEntry[]>([])
  const [observations, setObservations] = useState<Observation[]>([])
  const [accumulatedSalience, setAccumulatedSalience] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  const fetchJsonWithFallback = useCallback(async (paths: string[]) => {
    let lastError = ''

    for (const path of paths) {
      try {
        const response = await fetch(`${APP_CONFIG.apiUrl}${path}`, { credentials: 'include' })
        if (!response.ok) {
          lastError = `${path}: ${response.status}`
          continue
        }
        const data = await response.json()
        return { ok: true, data } as const
      } catch (err) {
        lastError = `${path}: ${err instanceof Error ? err.message : String(err)}`
      }
    }

    return { ok: false, error: lastError || 'request failed' } as const
  }, [])

  const fetchAll = useCallback(async () => {
    const [memoryResult, deliberationResult, observationResult] = await Promise.all([
      fetchJsonWithFallback(['/autonomy/working-memory', '/api/autonomy/working-memory']),
      fetchJsonWithFallback([
        '/autonomy/deliberation-history?hours=24&limit=15',
        '/api/autonomy/deliberation-history?hours=24&limit=15',
      ]),
      fetchJsonWithFallback(['/autonomy/observations?limit=20', '/api/autonomy/observations?limit=20']),
    ])

    if (memoryResult.ok) {
      setMemory(memoryResult.data)
    }

    if (deliberationResult.ok) {
      const safeEntries = Array.isArray(deliberationResult.data?.entries)
        ? deliberationResult.data.entries
        : []
      if (safeEntries.length > 0) {
        setDeliberations(safeEntries)
      } else {
        const fallbackDeliberation = await fetchJsonWithFallback([
          '/autonomy/deliberation-history?hours=168&limit=30',
          '/api/autonomy/deliberation-history?hours=168&limit=30',
        ])
        if (fallbackDeliberation.ok) {
          const fallbackEntries = Array.isArray(fallbackDeliberation.data?.entries)
            ? fallbackDeliberation.data.entries
            : []
          setDeliberations(fallbackEntries)
        } else {
          setDeliberations([])
        }
      }
    }

    if (observationResult.ok) {
      const safeObservations = Array.isArray(observationResult.data?.observations)
        ? observationResult.data.observations
        : []
      const safeSalience = typeof observationResult.data?.accumulated_salience === 'number'
        ? observationResult.data.accumulated_salience
        : 0
      setObservations(safeObservations)
      setAccumulatedSalience(safeSalience)
    }

    const failedEndpoints: string[] = []
    if (!memoryResult.ok) failedEndpoints.push(`working-memory (${memoryResult.error})`)
    if (!deliberationResult.ok) failedEndpoints.push(`deliberation-history (${deliberationResult.error})`)
    if (!observationResult.ok) failedEndpoints.push(`observations (${observationResult.error})`)

    if (failedEndpoints.length === 3) {
      setError('Unable to load Sara state right now. Please retry in a moment.')
      console.error('Failed to fetch Sara inner life data:', failedEndpoints)
    } else if (failedEndpoints.length > 0) {
      setError(`Some sections failed to refresh: ${failedEndpoints.join(', ')}`)
    } else {
      setError(null)
    }

    setLastUpdated(new Date())
    setLoading(false)
  }, [fetchJsonWithFallback])

  useEffect(() => {
    const fetchData = async () => {
      await fetchAll()
    }

    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [fetchAll])

  if (loading) {
    return (
      <div className="p-6 text-gray-400 flex items-center justify-center">
        <span className="material-icons animate-spin mr-2">autorenew</span>
        Loading Sara's inner state...
      </div>
    )
  }

  const lastDeliberationAgeHours = hoursSince(memory?.sara_last_deliberation_at)
  const isMindStateStale = lastDeliberationAgeHours != null && lastDeliberationAgeHours > 12
  const staleMindStateText = isMindStateStale && lastDeliberationAgeHours != null
    ? `Mind state is stale (${Math.floor(lastDeliberationAgeHours)}h since last deliberation).`
    : null

  const emotion = emotionIndicator(
    isMindStateStale ? undefined : memory?.sara_emotional_tone
  )
  const watchingFor = isMindStateStale ? null : memory?.last_heartbeat_watching_for
  const curiosities = Array.isArray(memory?.sara_curiosities)
    ? memory?.sara_curiosities.join(', ')
    : memory?.sara_curiosities
  const currentFocus = isMindStateStale ? null : memory?.sara_focus
  const memoryUpdatedAt = memory?.updated_at || null

  const tabs: { key: TabType; label: string; icon: string }[] = [
    { key: 'overview', label: 'Overview', icon: 'dashboard' },
    { key: 'thoughts', label: 'Thoughts', icon: 'psychology' },
    { key: 'observations', label: 'Observations', icon: 'visibility' },
  ]

  return (
    <div className="space-y-4 p-4 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="material-icons text-2xl text-purple-400">self_improvement</span>
          <h2 className="text-xl font-semibold text-white">Sara's Mind</h2>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          {memoryUpdatedAt && <span>State {timeAgo(memoryUpdatedAt)}</span>}
          {lastUpdated && <span>Fetched {timeAgo(lastUpdated.toISOString())}</span>}
          <button
            onClick={() => fetchAll()}
            className="inline-flex items-center gap-1 rounded border border-white/10 px-2 py-1 text-gray-300 hover:bg-white/5"
          >
            <span className="material-icons text-sm">refresh</span>
            Refresh
          </button>
          <span className="inline-flex items-center gap-1">
            <span className="material-icons text-sm">autorenew</span>
            30s auto-refresh
          </span>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-yellow-500/40 bg-yellow-500/10 px-3 py-2 text-sm text-yellow-200">
          {error}
        </div>
      )}

      {staleMindStateText && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
          {staleMindStateText}
        </div>
      )}

      {/* Tab bar */}
      <div className="flex gap-2">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${
              tab === t.key
                ? 'bg-purple-500/20 text-purple-400'
                : 'text-gray-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <span className="material-icons text-sm">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Overview Tab ───────────────────────────────────── */}
      {tab === 'overview' && (
        <div className="space-y-4">
          {/* Focus + Emotional State row */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Current Focus */}
            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
              <div className="flex items-center gap-2 mb-2">
                <span className="material-icons text-sm text-purple-400">center_focus_strong</span>
                <span className="text-xs uppercase tracking-wider text-gray-400 font-medium">Current Focus</span>
              </div>
              <p className="text-sm text-white leading-relaxed">
                {currentFocus || 'No active focus right now'}
              </p>
            </div>

            {/* Emotional State */}
            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
              <div className="flex items-center gap-2 mb-2">
                <span className="material-icons text-sm text-pink-400">mood</span>
                <span className="text-xs uppercase tracking-wider text-gray-400 font-medium">Emotional Tone</span>
              </div>
              <div className="flex items-center gap-3">
                <div className={`w-3 h-3 rounded-full ${emotion.color}`} />
                <span className="text-sm text-white">{emotion.label}</span>
              </div>
            </div>
          </div>

          {/* Watching For */}
          {watchingFor && (
            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
              <div className="flex items-center gap-2 mb-2">
                <span className="material-icons text-sm text-yellow-400">visibility</span>
                <span className="text-xs uppercase tracking-wider text-gray-400 font-medium">Watching For</span>
              </div>
              <p className="text-sm text-gray-300 leading-relaxed">{watchingFor}</p>
            </div>
          )}

          {/* Curiosities */}
          {curiosities && (
            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
              <div className="flex items-center gap-2 mb-2">
                <span className="material-icons text-sm text-blue-400">lightbulb</span>
                <span className="text-xs uppercase tracking-wider text-gray-400 font-medium">Curiosities</span>
              </div>
              <p className="text-sm text-gray-300 leading-relaxed">{curiosities}</p>
            </div>
          )}

          {/* Stats row */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard
              icon="psychology"
              label="Deliberations today"
              value={String(memory?.sara_deliberation_count_today ?? 0)}
              color="text-purple-400"
            />
            <StatCard
              icon="notifications"
              label="Notifications sent"
              value={String(memory?.notifications_sent_today ?? 0)}
              color="text-yellow-400"
            />
            <StatCard
              icon="visibility"
              label="Observations"
              value={String(memory?.observation_count ?? 0)}
              color="text-blue-400"
            />
            <StatCard
              icon="speed"
              label="Salience level"
              value={accumulatedSalience.toFixed(2)}
              color="text-teal-400"
            />
          </div>

          {/* Context Awareness */}
          <div className="rounded-xl border border-white/10 bg-white/5 p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="material-icons text-sm text-teal-400">sensors</span>
              <span className="text-xs uppercase tracking-wider text-gray-400 font-medium">Context Awareness</span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
              <ContextItem
                label="Activity"
                value={
                  memory?.activity_state
                    ? `${memory.activity_state}${memory.activity_confidence != null ? ` (${Math.round(memory.activity_confidence * 100)}%)` : ''}`
                    : 'unknown'
                }
              />
              <ContextItem label="Room" value={memory?.room || 'unknown'} />
              <ContextItem label="Interruptibility" value={memory?.interruptibility != null ? `${Math.round(memory.interruptibility * 100)}%` : '--'} />
              <ContextItem label="Last chat" value={memory?.hours_since_last_chat != null ? `${memory.hours_since_last_chat.toFixed(1)}h ago` : '--'} />
              <ContextItem label="Next event" value={memory?.next_event_title ? `${memory.next_event_title} (${memory.next_event_minutes_away}m)` : 'None'} />
              <ContextItem label="Quiet mode" value={memory?.quiet_mode ? 'On' : 'Off'} />
            </div>
          </div>

          {/* Recent Actions (last 3 deliberations with actions) */}
          <div className="rounded-xl border border-white/10 bg-white/5 p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="material-icons text-sm text-green-400">bolt</span>
              <span className="text-xs uppercase tracking-wider text-gray-400 font-medium">Recent Actions</span>
            </div>
            {deliberations.filter(d => {
              const actions = formatActions(d.actions_taken)
              return actions.length > 0
            }).length === 0 ? (
              <p className="text-sm text-gray-500">No actions taken recently</p>
            ) : (
              <div className="space-y-2">
                {deliberations
                  .filter(d => formatActions(d.actions_taken).length > 0)
                  .slice(0, 5)
                  .map((d, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <span className="text-xs text-gray-500 shrink-0 w-16 mt-0.5">
                        {timeAgo(d.created_at)}
                      </span>
                      <div className="space-y-0.5">
                        {formatActions(d.actions_taken).map((action, j) => (
                          <div key={j} className="flex items-center gap-1.5">
                            <span className="material-icons text-xs text-green-400">check_circle</span>
                            <span className="text-sm text-gray-300">{action}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Thoughts Tab ──────────────────────────────────── */}
      {tab === 'thoughts' && (
        <div className="space-y-3">
          {deliberations.length === 0 ? (
            <div className="text-center py-12 text-gray-500">
              <span className="material-icons text-4xl mb-2 block">psychology</span>
              No deliberations in the last 24 hours
            </div>
          ) : (
            deliberations.map((d, i) => {
              const isExpanded = expandedIdx === i
              const actions = formatActions(d.actions_taken)
              return (
                <div
                  key={i}
                  className="rounded-xl border border-white/10 bg-white/5 p-4 cursor-pointer transition-all hover:border-purple-500/30"
                  onClick={() => setExpandedIdx(isExpanded ? null : i)}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className={`text-xs px-1.5 py-0.5 rounded border ${
                          d.source === 'deliberation'
                            ? 'bg-purple-500/20 text-purple-400 border-purple-500/30'
                            : d.source === 'consolidation'
                            ? 'bg-blue-500/20 text-blue-400 border-blue-500/30'
                            : 'bg-gray-500/20 text-gray-400 border-gray-500/30'
                        }`}>
                          {d.source}
                        </span>
                        {actions.length > 0 && (
                          <span className="text-xs text-green-400 flex items-center gap-0.5">
                            <span className="material-icons text-xs">bolt</span>
                            {actions.length} action{actions.length > 1 ? 's' : ''}
                          </span>
                        )}
                        {d.duration_seconds != null && (
                          <span className="text-xs text-gray-500">
                            {d.duration_seconds.toFixed(1)}s
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-white leading-relaxed">
                        {isExpanded ? d.thought : (d.thought || '').slice(0, 200) + ((d.thought || '').length > 200 ? '...' : '')}
                      </p>
                    </div>
                    <span className="text-xs text-gray-500 shrink-0">
                      {timeAgo(d.created_at)}
                    </span>
                  </div>

                  {isExpanded && (
                    <div className="mt-3 pt-3 border-t border-white/10 space-y-2">
                      {d.handoff_note && (
                        <div>
                          <span className="text-xs text-gray-400 font-medium">Handoff note:</span>
                          <p className="text-sm text-gray-300 mt-0.5">{d.handoff_note}</p>
                        </div>
                      )}
                      {d.watching_for && (
                        <div>
                          <span className="text-xs text-gray-400 font-medium">Now watching for:</span>
                          <p className="text-sm text-gray-300 mt-0.5">{d.watching_for}</p>
                        </div>
                      )}
                      {actions.length > 0 && (
                        <div>
                          <span className="text-xs text-gray-400 font-medium">Actions taken:</span>
                          <div className="mt-1 space-y-1">
                            {actions.map((a, j) => (
                              <div key={j} className="flex items-center gap-1.5">
                                <span className="material-icons text-xs text-green-400">check_circle</span>
                                <span className="text-sm text-gray-300">{a}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      )}

      {/* ── Observations Tab ──────────────────────────────── */}
      {tab === 'observations' && (
        <div className="space-y-3">
          {/* Accumulated salience indicator */}
          <div className="rounded-xl border border-white/10 bg-white/5 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="material-icons text-sm text-teal-400">speed</span>
                <span className="text-xs uppercase tracking-wider text-gray-400 font-medium">
                  Accumulated Salience
                </span>
              </div>
              <span className="text-sm text-white font-mono">{accumulatedSalience.toFixed(2)} / 2.00</span>
            </div>
            <div className="mt-2 h-2 bg-gray-800 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  accumulatedSalience >= 2.0 ? 'bg-red-500' : accumulatedSalience >= 1.0 ? 'bg-yellow-500' : 'bg-teal-500'
                }`}
                style={{ width: `${Math.min(100, (accumulatedSalience / 2.0) * 100)}%` }}
              />
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Deliberation triggers at 2.0 accumulated salience
            </p>
          </div>

          {observations.length === 0 ? (
            <div className="text-center py-12 text-gray-500">
              <span className="material-icons text-4xl mb-2 block">visibility_off</span>
              No pending observations
            </div>
          ) : (
            observations.map((obs) => (
              <div
                key={obs.id}
                className="rounded-xl border border-white/10 bg-white/5 p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-xs px-1.5 py-0.5 rounded bg-gray-500/20 text-gray-400 border border-gray-500/30">
                        {obs.source}
                      </span>
                      {obs.category && (
                        <span className="text-xs text-gray-500">{obs.category}</span>
                      )}
                      <div className="flex items-center gap-1">
                        <div className={`w-2 h-2 rounded-full ${salienceBar(obs.salience)}`} />
                        <span className="text-xs text-gray-400 font-mono">{obs.salience.toFixed(2)}</span>
                      </div>
                    </div>
                    <p className="text-sm text-gray-300 leading-relaxed">{obs.description}</p>
                  </div>
                  <span className="text-xs text-gray-500 shrink-0">
                    {timeAgo(obs.timestamp)}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}

// ── Sub-components ───────────────────────────────────────────

function StatCard({ icon, label, value, color }: { icon: string; label: string; value: string; color: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-3 text-center">
      <span className={`material-icons text-lg ${color}`}>{icon}</span>
      <div className="text-lg font-semibold text-white mt-1">{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  )
}

function ContextItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-xs text-gray-500">{label}</span>
      <p className="text-sm text-gray-300">{value}</p>
    </div>
  )
}
