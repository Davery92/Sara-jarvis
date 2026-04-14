import { useState, useEffect, useCallback, useRef } from 'react'
import { APP_CONFIG } from '../../config'

interface LiveSession {
  id: string
  mode: string
  turns: number
  notes_created: number
  elapsed_minutes: number
}

interface LastSession {
  mode: string
  turns: number
  notes_created: number
  started_at: string
  ended_at: string
  end_reason: string
}

interface Snapshot {
  state: string
  emotional_state?: string
  live_session?: LiveSession
  last_session?: LastSession
}

interface LiveEvent {
  type: string
  mode?: string
  turn?: number
  tool?: string
  text?: string
  notes_created?: number
  summary?: string
  end_reason?: string
}

const STATE_CONFIG: Record<string, { label: string; color: string; dot: string }> = {
  autonomous: { label: 'Active', color: 'text-emerald-400', dot: 'bg-emerald-400' },
  cooldown: { label: 'Resting', color: 'text-zinc-500', dot: 'bg-zinc-500' },
  conversational: { label: 'Chatting', color: 'text-blue-400', dot: 'bg-blue-400' },
  idle: { label: 'Idle', color: 'text-zinc-500', dot: 'bg-zinc-500' },
  pausing: { label: 'Pausing', color: 'text-amber-400', dot: 'bg-amber-400' },
  paused: { label: 'Paused', color: 'text-amber-400', dot: 'bg-amber-400' },
}

export default function ACSStatusSection() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [liveEvents, setLiveEvents] = useState<LiveEvent[]>([])
  const [latestThought, setLatestThought] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)

  const fetchSnapshot = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/snapshot`, { credentials: 'include' })
      if (res.ok) {
        setSnapshot(await res.json())
        setError(null)
      } else {
        setError('Failed to load status')
      }
    } catch {
      setError('Failed to load status')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSnapshot()
    const interval = setInterval(fetchSnapshot, 15_000)
    return () => clearInterval(interval)
  }, [fetchSnapshot])

  // SSE for live session
  useEffect(() => {
    if (!snapshot?.live_session) {
      setLiveEvents([])
      setLatestThought(null)
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
      return
    }
    if (eventSourceRef.current) return

    const es = new EventSource(`${APP_CONFIG.apiUrl}/api/acs/live`, { withCredentials: true })
    eventSourceRef.current = es

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as LiveEvent
        if (event.type === 'thought' && event.text) {
          setLatestThought(event.text)
        } else if (event.type && event.type !== 'status' && event.type !== 'thought') {
          setLiveEvents(prev => [event, ...prev].slice(0, 20))
        }
      } catch { /* ignore */ }
    }

    es.onerror = () => {
      es.close()
      eventSourceRef.current = null
    }

    return () => {
      es.close()
      eventSourceRef.current = null
    }
  }, [snapshot?.live_session?.id])

  const sendAction = async (action: 'start' | 'pause' | 'resume' | 'stop') => {
    setActionLoading(true)
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/acs/${action}`, {
        method: 'POST',
        credentials: 'include',
      })
      await fetchSnapshot()
    } catch { /* ignore */ }
    finally { setActionLoading(false) }
  }

  if (loading) return <div className="text-gray-400 p-4">Loading...</div>
  if (error) return <div className="text-red-400 p-4">{error}</div>
  if (!snapshot) return null

  const stateConfig = STATE_CONFIG[snapshot.state] || STATE_CONFIG.idle
  const isLive = !!snapshot.live_session

  return (
    <div className="space-y-4">
      {/* State + Controls */}
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <span className={`h-3 w-3 rounded-full ${stateConfig.dot} ${isLive ? 'animate-pulse' : ''}`} />
            <span className={`text-lg font-semibold ${stateConfig.color}`}>{stateConfig.label}</span>
            {snapshot.emotional_state && (
              <span className="text-sm text-gray-400">({snapshot.emotional_state})</span>
            )}
          </div>
          <div className="flex gap-2">
            {snapshot.state === 'idle' && (
              <button onClick={() => sendAction('start')} disabled={actionLoading}
                className="px-3 py-1.5 text-sm bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-600 text-white rounded transition-colors">
                Start
              </button>
            )}
            {(snapshot.state === 'cooldown' || snapshot.state === 'conversational') && (
              <button onClick={() => sendAction('resume')} disabled={actionLoading}
                className="px-3 py-1.5 text-sm bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-600 text-white rounded transition-colors">
                Resume
              </button>
            )}
            {snapshot.state === 'autonomous' && (
              <>
                <button onClick={() => sendAction('pause')} disabled={actionLoading}
                  className="px-3 py-1.5 text-sm bg-amber-600 hover:bg-amber-500 disabled:bg-gray-600 text-white rounded transition-colors">
                  Pause
                </button>
                <button onClick={() => { if (confirm('Force-stop the current ACS session?')) sendAction('stop') }} disabled={actionLoading}
                  className="px-3 py-1.5 text-sm bg-red-600 hover:bg-red-500 disabled:bg-gray-600 text-white rounded transition-colors">
                  Stop
                </button>
              </>
            )}
            {(snapshot.state === 'pausing' || snapshot.state === 'paused') && (
              <>
                <button onClick={() => sendAction('resume')} disabled={actionLoading}
                  className="px-3 py-1.5 text-sm bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-600 text-white rounded transition-colors">
                  Resume
                </button>
                <button onClick={() => { if (confirm('Force-stop the current ACS session?')) sendAction('stop') }} disabled={actionLoading}
                  className="px-3 py-1.5 text-sm bg-red-600 hover:bg-red-500 disabled:bg-gray-600 text-white rounded transition-colors">
                  Stop
                </button>
              </>
            )}
          </div>
        </div>

        {/* Live session info */}
        {isLive && snapshot.live_session && (
          <div className="grid grid-cols-4 gap-3 text-sm">
            <div className="bg-gray-900/50 rounded p-2">
              <div className="text-gray-500 text-xs">Mode</div>
              <div className="text-white font-medium">{snapshot.live_session.mode}</div>
            </div>
            <div className="bg-gray-900/50 rounded p-2">
              <div className="text-gray-500 text-xs">Turns</div>
              <div className="text-white font-medium">{snapshot.live_session.turns}</div>
            </div>
            <div className="bg-gray-900/50 rounded p-2">
              <div className="text-gray-500 text-xs">Notes</div>
              <div className="text-white font-medium">{snapshot.live_session.notes_created}</div>
            </div>
            <div className="bg-gray-900/50 rounded p-2">
              <div className="text-gray-500 text-xs">Elapsed</div>
              <div className="text-white font-medium">{Math.round(snapshot.live_session.elapsed_minutes)}m</div>
            </div>
          </div>
        )}

        {/* Last session summary */}
        {!isLive && snapshot.last_session && (
          <div className="text-sm text-gray-400">
            Last: {snapshot.last_session.mode} - {snapshot.last_session.turns} turns, {snapshot.last_session.notes_created} notes ({snapshot.last_session.end_reason})
          </div>
        )}
      </div>

      {/* Latest thought */}
      {latestThought && (
        <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
          <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Latest Thought</div>
          <p className="text-gray-300 italic">{latestThought}</p>
        </div>
      )}

      {/* Live event feed */}
      {liveEvents.length > 0 && (
        <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
          <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Live Events</div>
          <div className="space-y-1 max-h-64 overflow-y-auto">
            {liveEvents.map((event, i) => (
              <div key={i} className="text-sm text-gray-400 py-0.5">
                <span className="text-gray-500">{event.type}</span>
                {event.mode && <span className="ml-2 text-gray-300">{event.mode}</span>}
                {event.turn !== undefined && <span className="ml-2">turn {event.turn}</span>}
                {event.tool && <span className="ml-2 text-indigo-400">{event.tool}</span>}
                {event.text && <span className="ml-2 text-gray-300">{event.text}</span>}
                {event.summary && <span className="ml-2 text-gray-300">{event.summary}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
