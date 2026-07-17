import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Lightbulb, Brain, Eye, Zap, ChevronDown, ChevronUp } from 'lucide-react'
import { workspaceApi, type WorkspacePartnerAction, type WorkspacePartnerContextUpdate } from '../services/api'
import { APP_CONFIG } from '../config'
import { useCanvasStore } from '../store/canvasStore'

const CLIENT_ACTIVE_WINDOW_MS = 45_000
const ACTIVE_TICK_MS = 5_000
const CONTEXT_PUSH_INTERVAL_MS = 10_000
const MAX_RECENT_ACTIONS = 12

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

interface ObservationEntry {
  id: string
  timestamp: string
  source: string
  description: string
  salience: number
  category: string
}

interface WorkingMemoryData {
  sara_focus?: string
  sara_emotional_tone?: string
  sara_curiosities?: string
  last_heartbeat_watching_for?: string
  sara_deliberation_count_today?: number
  observation_count?: number
  error?: string
}

function getSessionId(): string {
  const key = 'workspace_partner_session_id'
  const existing = localStorage.getItem(key)
  if (existing) return existing
  const generated = `wps-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  localStorage.setItem(key, generated)
  return generated
}

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return ''
  const now = new Date()
  const date = new Date(dateStr)
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 1) return 'now'
  if (diffMins < 60) return `${diffMins}m`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h`
  return `${Math.floor(diffHours / 24)}d`
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

async function fetchDeliberations(): Promise<DeliberationEntry[]> {
  try {
    const res = await fetch(`${APP_CONFIG.apiUrl}/autonomy/deliberation-history?hours=12&limit=5`, {
      credentials: 'include',
    })
    if (!res.ok) return []
    const data = await res.json()
    return data.entries || []
  } catch {
    return []
  }
}

async function fetchObservations(): Promise<{ observations: ObservationEntry[]; accumulated: number }> {
  try {
    const res = await fetch(`${APP_CONFIG.apiUrl}/autonomy/observations?limit=5&min_salience=0.3`, {
      credentials: 'include',
    })
    if (!res.ok) return { observations: [], accumulated: 0 }
    const data = await res.json()
    return {
      observations: data.observations || [],
      accumulated: data.accumulated_salience || 0,
    }
  } catch {
    return { observations: [], accumulated: 0 }
  }
}

async function fetchWorkingMemory(): Promise<WorkingMemoryData | null> {
  try {
    const res = await fetch(`${APP_CONFIG.apiUrl}/autonomy/working-memory`, {
      credentials: 'include',
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export default function PartnerThoughts() {
  const windows = useCanvasStore((s) => s.windows)
  const maps = useCanvasStore((s) => s.maps)
  const transform = useCanvasStore((s) => s.transform)
  const activeSceneId = useCanvasStore((s) => s.activeSceneId)

  const sessionIdRef = useRef<string>(getSessionId())
  const lastInteractionAtRef = useRef<number>(Date.now())
  const recentActionsRef = useRef<WorkspacePartnerAction[]>([])
  const payloadRef = useRef<WorkspacePartnerContextUpdate | null>(null)
  const previousWindowIdsRef = useRef<string[]>([])
  const previousSceneIdRef = useRef<string | null>(null)

  const [isVisible, setIsVisible] = useState<boolean>(document.visibilityState === 'visible')
  const [isFocused, setIsFocused] = useState<boolean>(document.hasFocus())
  const [activityTick, setActivityTick] = useState<number>(Date.now())
  const [isExpanded, setIsExpanded] = useState(false)

  const recordAction = useCallback((action: WorkspacePartnerAction) => {
    const withTimestamp: WorkspacePartnerAction = {
      ...action,
      at: action.at || new Date().toISOString(),
    }
    const next = [...recentActionsRef.current, withTimestamp]
    recentActionsRef.current = next.slice(-MAX_RECENT_ACTIONS)
  }, [])

  useEffect(() => {
    const handleVisibility = () => setIsVisible(document.visibilityState === 'visible')
    const handleFocus = () => setIsFocused(true)
    const handleBlur = () => setIsFocused(false)
    const markInteraction = () => {
      lastInteractionAtRef.current = Date.now()
    }

    document.addEventListener('visibilitychange', handleVisibility)
    window.addEventListener('focus', handleFocus)
    window.addEventListener('blur', handleBlur)
    window.addEventListener('pointerdown', markInteraction, { passive: true })
    window.addEventListener('keydown', markInteraction)
    window.addEventListener('wheel', markInteraction, { passive: true })
    window.addEventListener('touchstart', markInteraction, { passive: true })

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility)
      window.removeEventListener('focus', handleFocus)
      window.removeEventListener('blur', handleBlur)
      window.removeEventListener('pointerdown', markInteraction)
      window.removeEventListener('keydown', markInteraction)
      window.removeEventListener('wheel', markInteraction)
      window.removeEventListener('touchstart', markInteraction)
    }
  }, [])

  useEffect(() => {
    const interval = setInterval(() => setActivityTick(Date.now()), ACTIVE_TICK_MS)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    const currentIds = windows.map((w) => w.id)
    const previousIds = previousWindowIdsRef.current
    const previousSet = new Set(previousIds)
    const currentSet = new Set(currentIds)

    for (const id of currentIds) {
      if (!previousSet.has(id)) {
        const win = windows.find((w) => w.id === id)
        if (win) {
          recordAction({ type: 'window_opened', window_type: win.type, target: win.title })
        }
      }
    }

    for (const id of previousIds) {
      if (!currentSet.has(id)) {
        recordAction({ type: 'window_closed', target: id })
      }
    }

    previousWindowIdsRef.current = currentIds
  }, [windows, recordAction])

  useEffect(() => {
    if (activeSceneId !== previousSceneIdRef.current && activeSceneId) {
      recordAction({ type: 'scene_changed', target: activeSceneId })
    }
    previousSceneIdRef.current = activeSceneId
  }, [activeSceneId, recordAction])

  const focusedWindow = useMemo(() => {
    if (!windows.length) return null
    return [...windows].sort((a, b) => b.zIndex - a.zIndex)[0]
  }, [windows])

  const isActive = useMemo(() => {
    const recentlyActive = activityTick - lastInteractionAtRef.current < CLIENT_ACTIVE_WINDOW_MS
    return isVisible && isFocused && recentlyActive
  }, [activityTick, isFocused, isVisible])

  const contextPayload = useMemo<WorkspacePartnerContextUpdate>(() => ({
    session_id: sessionIdRef.current,
    active: isActive,
    focused_window_id: focusedWindow?.id,
    focused_window_type: focusedWindow?.type,
    active_scene_id: activeSceneId,
    windows: windows.slice(0, 24).map((w) => ({
      id: w.id,
      type: w.type,
      title: w.title,
      z_index: w.zIndex,
      data: {
        emailId: (w.data as any)?.emailId,
        noteId: (w.data as any)?.noteId || (w.data as any)?.note_id,
        initialQuery: (w.data as any)?.initialQuery,
      },
    })),
    map_count: maps.length,
    recent_actions: recentActionsRef.current.slice(-MAX_RECENT_ACTIONS),
    transform: {
      x: transform.x,
      y: transform.y,
      scale: transform.scale,
    },
    client_timestamp: new Date().toISOString(),
  }), [activeSceneId, focusedWindow?.id, focusedWindow?.type, isActive, maps.length, transform.scale, transform.x, transform.y, windows])

  payloadRef.current = contextPayload

  const pushContext = useCallback(async () => {
    const payload = payloadRef.current
    if (!payload) return
    try {
      await workspaceApi.updatePartnerContext(payload)
    } catch {
      // intentionally silent
    }
  }, [])

  useEffect(() => {
    const timeout = setTimeout(() => {
      pushContext()
    }, 250)
    return () => clearTimeout(timeout)
  }, [contextPayload, pushContext])

  useEffect(() => {
    const interval = setInterval(() => {
      pushContext()
    }, CONTEXT_PUSH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [pushContext])

  // Original partner thoughts
  const { data: thoughtResponse } = useQuery({
    queryKey: ['workspace-partner-thoughts'],
    queryFn: workspaceApi.getPartnerThoughts,
    refetchInterval: isActive ? 10_000 : false,
    retry: 1,
  })

  // Deliberation history
  const { data: deliberations = [] } = useQuery({
    queryKey: ['workspace-deliberations'],
    queryFn: fetchDeliberations,
    refetchInterval: isActive ? 30_000 : false,
    retry: 1,
  })

  // Observations
  const { data: obsData } = useQuery({
    queryKey: ['workspace-observations'],
    queryFn: fetchObservations,
    refetchInterval: isActive ? 30_000 : false,
    retry: 1,
  })

  // Working memory
  const { data: workingMemory } = useQuery({
    queryKey: ['workspace-working-memory'],
    queryFn: fetchWorkingMemory,
    refetchInterval: isActive ? 30_000 : false,
    retry: 1,
  })

  const thoughts = useMemo(() => {
    if (!isActive) return []
    if (!thoughtResponse?.active || !Array.isArray(thoughtResponse.thoughts)) return []
    return thoughtResponse.thoughts
      .map((t) => (typeof t?.text === 'string' ? t.text.trim() : ''))
      .filter(Boolean)
      .slice(0, 6)
  }, [isActive, thoughtResponse])

  const recentActions = useMemo(() => {
    return deliberations
      .filter((d) => formatActions(d.actions_taken).length > 0)
      .slice(0, 3)
      .flatMap((d) =>
        formatActions(d.actions_taken).map((action) => ({
          action,
          time: d.created_at,
        }))
      )
      .slice(0, 5)
  }, [deliberations])

  const latestThought = deliberations.length > 0 ? deliberations[0] : null

  const hasContent = thoughts.length > 0 || latestThought || (workingMemory && !workingMemory.error)
  if (!isActive || !hasContent) return null

  return (
    <div className="fixed bottom-6 left-6 z-40 w-[420px] max-w-[calc(100vw-2rem)] pointer-events-none">
      <div className="bg-canvas-surface/90 backdrop-blur-md border border-canvas-border rounded-xl shadow-xl pointer-events-auto">
        {/* Header with expand toggle */}
        <button
          className="w-full flex items-center justify-between gap-2 p-3 text-left"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-canvas-muted">
            <Lightbulb size={14} className="text-amber-400" />
            Sara's Inner Life
            {workingMemory?.sara_emotional_tone && (
              <span className="normal-case text-gray-400 tracking-normal">
                &middot; {workingMemory.sara_emotional_tone}
              </span>
            )}
          </div>
          {isExpanded ? <ChevronDown size={14} className="text-canvas-muted" /> : <ChevronUp size={14} className="text-canvas-muted" />}
        </button>

        <div className="px-3 pb-3">
          {/* Partner thoughts (always visible) */}
          {thoughts.length > 0 && (
            <div className="space-y-1 mb-2">
              {thoughts.map((thought, idx) => (
                <div key={`${idx}-${String(thought).slice(0, 24)}`} className="text-sm text-gray-200 leading-snug">
                  {thought}
                </div>
              ))}
            </div>
          )}

          {/* Compact: latest deliberation thought */}
          {!isExpanded && latestThought?.thought && thoughts.length === 0 && (
            <p className="text-sm text-gray-300 leading-snug line-clamp-2">
              {latestThought.thought.slice(0, 150)}
              {(latestThought.thought.length > 150) ? '...' : ''}
            </p>
          )}

          {/* Expanded view */}
          {isExpanded && (
            <div className="space-y-3 mt-2 border-t border-canvas-border pt-3">
              {/* Focus */}
              {workingMemory?.sara_focus && (
                <div>
                  <div className="flex items-center gap-1.5 text-xs text-purple-400 mb-1">
                    <Brain size={12} />
                    Focus
                  </div>
                  <p className="text-sm text-gray-300 leading-snug">{workingMemory.sara_focus}</p>
                </div>
              )}

              {/* Watching For */}
              {workingMemory?.last_heartbeat_watching_for && (
                <div>
                  <div className="flex items-center gap-1.5 text-xs text-yellow-400 mb-1">
                    <Eye size={12} />
                    Watching For
                  </div>
                  <p className="text-sm text-gray-300 leading-snug">{workingMemory.last_heartbeat_watching_for}</p>
                </div>
              )}

              {/* Recent deliberation thoughts */}
              {deliberations.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 text-xs text-purple-400 mb-1">
                    <Brain size={12} />
                    Recent Thoughts
                  </div>
                  <div className="space-y-1.5">
                    {deliberations.slice(0, 3).map((d, i) => (
                      <div key={i} className="text-sm text-gray-300 leading-snug">
                        <span className="text-gray-500 text-xs mr-1">{timeAgo(d.created_at)}</span>
                        {(d.thought || '').slice(0, 120)}{(d.thought || '').length > 120 ? '...' : ''}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Actions taken */}
              {recentActions.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 text-xs text-green-400 mb-1">
                    <Zap size={12} />
                    Actions Taken
                  </div>
                  <div className="space-y-1">
                    {recentActions.map((a, i) => (
                      <div key={i} className="flex items-center gap-1.5 text-sm text-gray-300">
                        <span className="text-gray-500 text-xs">{timeAgo(a.time)}</span>
                        {a.action}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Observations */}
              {obsData && obsData.observations.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 text-xs text-teal-400 mb-1">
                    <Eye size={12} />
                    Observations
                    <span className="text-gray-500 ml-1">
                      (salience: {obsData.accumulated.toFixed(1)}/2.0)
                    </span>
                  </div>
                  <div className="space-y-1">
                    {obsData.observations.slice(0, 3).map((obs) => (
                      <div key={obs.id} className="flex items-start gap-1.5 text-sm text-gray-300">
                        <div
                          className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${
                            obs.salience >= 0.7 ? 'bg-red-400' : obs.salience >= 0.4 ? 'bg-yellow-400' : 'bg-gray-400'
                          }`}
                        />
                        <span className="leading-snug">{obs.description.slice(0, 100)}{obs.description.length > 100 ? '...' : ''}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
