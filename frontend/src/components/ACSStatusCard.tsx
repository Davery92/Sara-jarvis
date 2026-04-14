import { useState, useEffect, useCallback, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import { APP_CONFIG } from '../config'

interface ACSDirective {
  id: string
  directive_type: string
  content: string
  priority: string
  status: string
  source: string
  response?: string
  created_at: string
}

interface ACSSnapshot {
  state: string
  emotional_state?: string
  daily_plan?: string
  directives?: ACSDirective[]
  latest_note?: {
    title: string
    preview: string
    created_at: string
    folder?: string
  }
  latest_journal?: {
    snippet: string
    updated_at: string
  }
  last_session?: {
    mode: string
    turns: number
    notes_created: number
    started_at: string
    ended_at: string
    end_reason: string
  }
  live_session?: {
    id: string
    mode: string
    turns: number
    notes_created: number
    elapsed_minutes: number
  }
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

const MODE_EMOJI: Record<string, string> = {
  exploration: '\uD83D\uDD2D',
  consolidation: '\uD83D\uDD17',
  reflection: '\uD83E\uDE9E',
  research: '\uD83D\uDCDA',
  learning: '\uD83C\uDF93',
}

const STATE_CONFIG: Record<string, { label: string; color: string; dot: string }> = {
  autonomous: { label: 'Active', color: 'text-emerald-400', dot: 'bg-emerald-400' },
  cooldown: { label: 'Resting', color: 'text-zinc-500', dot: 'bg-zinc-500' },
  conversational: { label: 'Chatting', color: 'text-blue-400', dot: 'bg-blue-400' },
  idle: { label: 'Idle', color: 'text-zinc-500', dot: 'bg-zinc-500' },
  paused: { label: 'Paused', color: 'text-amber-400', dot: 'bg-amber-400' },
}

function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return ''
  const now = new Date()
  const date = new Date(dateStr)
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  return `${Math.floor(diffHours / 24)}d ago`
}

function formatLiveEvent(event: LiveEvent): string {
  switch (event.type) {
    case 'turn_starting':
      return `\u25B6 Starting turn ${event.turn || '?'}`
    case 'turn_completed':
      return `\u2705 Turn ${event.turn || '?'} done${event.notes_created ? ` (${event.notes_created} notes)` : ''}`
    case 'tool_call':
      return `\uD83D\uDD27 Using ${event.tool || 'tool'}`
    case 'mode_selected':
      return `${MODE_EMOJI[event.mode || ''] || '\uD83C\uDFAF'} Mode: ${event.mode}`
    case 'session_ended':
      return `\u23F9 Session ended: ${event.summary || event.end_reason || ''}`
    case 'human_input_requested':
      return '\uD83D\uDE4B Waiting for your input'
    default:
      return event.type
  }
}

export default function ACSStatusCard() {
  const [snapshot, setSnapshot] = useState<ACSSnapshot | null>(null)
  const [liveEvents, setLiveEvents] = useState<LiveEvent[]>([])
  const [latestThought, setLatestThought] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [showPlan, setShowPlan] = useState(false)
  const [showDirectiveForm, setShowDirectiveForm] = useState(false)
  const [directiveType, setDirectiveType] = useState('focus')
  const [directiveContent, setDirectiveContent] = useState('')
  const [directiveSending, setDirectiveSending] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)

  const sendDirective = async () => {
    if (!directiveContent.trim()) return
    setDirectiveSending(true)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/directive`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          directive_type: directiveType,
          content: directiveContent.trim(),
          priority: directiveType === 'stop' ? 'urgent' : 'normal',
          source: 'frontend',
        }),
      })
      if (res.ok) {
        setDirectiveContent('')
        setShowDirectiveForm(false)
        fetchSnapshot()
      }
    } catch {
      // graceful degradation
    } finally {
      setDirectiveSending(false)
    }
  }

  const expireDirective = async (id: string) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/acs/directive/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      fetchSnapshot()
    } catch {
      // ignore
    }
  }

  const fetchSnapshot = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/snapshot`, { credentials: 'include' })
      if (res.ok) setSnapshot(await res.json())
    } catch {
      // graceful degradation
    }
  }, [])

  useEffect(() => {
    fetchSnapshot()
    const interval = setInterval(fetchSnapshot, 30_000)
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

    if (eventSourceRef.current) return // already connected

    const es = new EventSource(`${APP_CONFIG.apiUrl}/api/acs/live`, { withCredentials: true })
    eventSourceRef.current = es

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as LiveEvent
        if (event.type === 'thought' && event.text) {
          setLatestThought(event.text)
        } else if (event.type && event.type !== 'status' && event.type !== 'thought') {
          setLiveEvents(prev => [event, ...prev].slice(0, 10))
        }
      } catch {
        // ignore
      }
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

  if (!snapshot) return null

  const stateConfig = STATE_CONFIG[snapshot.state] || STATE_CONFIG.idle
  const isLive = !!snapshot.live_session

  return (
    <div
      className={`rounded-xl border px-4 py-3 cursor-pointer transition-all ${
        isLive
          ? 'border-emerald-500/30 bg-card'
          : 'border-card bg-card'
      } hover:bg-zinc-800`}
      onClick={() => setExpanded(e => !e)}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`h-2 w-2 rounded-full ${stateConfig.dot} ${isLive ? 'animate-pulse' : ''}`} />
          <span className={`text-xs font-bold ${stateConfig.color}`}>{stateConfig.label}</span>

          {isLive && snapshot.live_session && (
            <span className="text-[11px] text-emerald-400/80 bg-emerald-400/10 px-2 py-0.5 rounded-full">
              {MODE_EMOJI[snapshot.live_session.mode] || ''} {snapshot.live_session.mode} — turn {snapshot.live_session.turns}, {Math.round(snapshot.live_session.elapsed_minutes)}m
            </span>
          )}

          {!isLive && snapshot.last_session && (
            <span className="text-[11px] text-zinc-500">
              {MODE_EMOJI[snapshot.last_session.mode] || ''} {snapshot.last_session.mode} {timeAgo(snapshot.last_session.ended_at)}
            </span>
          )}
        </div>

        <span className="text-[10px] text-zinc-600">{expanded ? '\u25B2' : '\u25BC'}</span>
      </div>

      {/* Latest thought — always visible when live */}
      {isLive && latestThought && (
        <p className="text-xs text-zinc-300 italic leading-relaxed mt-1.5">
          {'\uD83D\uDCAD'} {latestThought}
        </p>
      )}

      {/* Latest note (always visible) */}
      {snapshot.latest_note && (
        <div className="flex items-center gap-2 mt-1.5">
          <span className="text-xs">{'\uD83D\uDDD2'}</span>
          <span className="text-xs font-medium text-zinc-300 truncate">{snapshot.latest_note.title}</span>
          <span className="text-[10px] text-zinc-600 whitespace-nowrap">
            {snapshot.latest_note.folder ? `${snapshot.latest_note.folder} \u00B7 ` : ''}
            {timeAgo(snapshot.latest_note.created_at)}
          </span>
        </div>
      )}

      {/* Daily Plan toggle — always visible if plan exists */}
      {snapshot.daily_plan && (
        <div className="mt-2">
          <button
            className="text-[11px] text-indigo-400 hover:text-indigo-300 font-medium"
            onClick={(e) => { e.stopPropagation(); setShowPlan(p => !p) }}
          >
            {showPlan ? '\u25B2' : '\uD83D\uDCCB'} Today's Plan
          </button>
          {showPlan && (
            <div className="mt-2 p-3 rounded-lg bg-zinc-800/50 border border-zinc-700/30 prose prose-invert prose-xs max-w-none prose-headings:text-zinc-200 prose-headings:mt-3 prose-headings:mb-1 prose-p:text-zinc-300 prose-p:my-1 prose-strong:text-zinc-200 prose-li:text-zinc-300 prose-li:my-0.5">
              <ReactMarkdown>{snapshot.daily_plan}</ReactMarkdown>
            </div>
          )}
        </div>
      )}

      {/* Expanded */}
      {expanded && (
        <div className="mt-3 pt-3 border-t border-zinc-700/50 space-y-3">
          {/* Note preview */}
          {snapshot.latest_note?.preview && (
            <p className="text-xs text-zinc-400 leading-relaxed">
              {snapshot.latest_note.preview}
            </p>
          )}

          {/* Journal */}
          {snapshot.latest_journal && (
            <div>
              <div className="text-[10px] font-bold text-zinc-600 uppercase tracking-wider mb-1">
                {'\uD83D\uDCD6'} Latest Journal
              </div>
              <p className="text-xs text-zinc-400 italic leading-relaxed">
                {snapshot.latest_journal.snippet}
              </p>
              <span className="text-[10px] text-zinc-600">{timeAgo(snapshot.latest_journal.updated_at)}</span>
            </div>
          )}

          {/* Live events */}
          {isLive && liveEvents.length > 0 && (
            <div>
              <div className="text-[10px] font-bold text-zinc-600 uppercase tracking-wider mb-1">
                {'\u26A1'} Live Activity
              </div>
              {liveEvents.slice(0, 5).map((event, i) => (
                <div key={i} className="text-[11px] text-zinc-400 py-0.5">{formatLiveEvent(event)}</div>
              ))}
            </div>
          )}

          {/* Directives */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <div className="text-[10px] font-bold text-zinc-600 uppercase tracking-wider">
                {'\uD83D\uDCE8'} Directives
              </div>
              <button
                className="text-[10px] text-indigo-400 hover:text-indigo-300"
                onClick={(e) => { e.stopPropagation(); setShowDirectiveForm(f => !f) }}
              >
                {showDirectiveForm ? 'Cancel' : '+ Send'}
              </button>
            </div>

            {showDirectiveForm && (
              <div className="space-y-2 p-2 rounded-lg bg-zinc-800/50 border border-zinc-700/30 mb-2" onClick={e => e.stopPropagation()}>
                <select
                  value={directiveType}
                  onChange={e => setDirectiveType(e.target.value)}
                  className="w-full text-xs bg-zinc-700 border border-zinc-600 rounded px-2 py-1 text-zinc-200"
                >
                  <option value="focus">Focus — prioritize this topic</option>
                  <option value="stop">Stop — stop doing this immediately</option>
                  <option value="redirect">Redirect — change course</option>
                  <option value="context">Context — FYI information</option>
                  <option value="question">Question — ask ACS something</option>
                </select>
                <textarea
                  value={directiveContent}
                  onChange={e => setDirectiveContent(e.target.value)}
                  placeholder="What do you want to tell the ACS?"
                  className="w-full text-xs bg-zinc-700 border border-zinc-600 rounded px-2 py-1.5 text-zinc-200 placeholder:text-zinc-500 resize-none"
                  rows={2}
                />
                <button
                  onClick={sendDirective}
                  disabled={directiveSending || !directiveContent.trim()}
                  className="text-xs bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-600 text-white px-3 py-1 rounded transition-colors"
                >
                  {directiveSending ? 'Sending...' : 'Send Directive'}
                </button>
              </div>
            )}

            {snapshot.directives && snapshot.directives.length > 0 ? (
              <div className="space-y-1">
                {snapshot.directives.map(d => (
                  <div key={d.id} className="flex items-start justify-between gap-2 text-[11px]">
                    <div className="min-w-0">
                      <span className={`font-bold ${
                        d.directive_type === 'stop' ? 'text-red-400' :
                        d.directive_type === 'focus' ? 'text-emerald-400' :
                        d.directive_type === 'redirect' ? 'text-amber-400' :
                        'text-zinc-400'
                      }`}>
                        [{d.directive_type.toUpperCase()}]
                      </span>
                      {' '}
                      <span className="text-zinc-300">{d.content}</span>
                      {d.status === 'acknowledged' && d.response && (
                        <span className="text-zinc-500 italic"> — {d.response}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <span className={`text-[9px] px-1 rounded ${
                        d.status === 'acknowledged' ? 'bg-emerald-900/30 text-emerald-400' :
                        'bg-amber-900/30 text-amber-400'
                      }`}>
                        {d.status}
                      </span>
                      <button
                        onClick={(e) => { e.stopPropagation(); expireDirective(d.id) }}
                        className="text-zinc-600 hover:text-red-400 text-[10px]"
                        title="Expire directive"
                      >
                        {'\u2715'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[11px] text-zinc-600">No active directives</div>
            )}
          </div>

          {/* Last session */}
          {!isLive && snapshot.last_session && (
            <div className="text-[11px] text-zinc-500">
              Last session: {snapshot.last_session.mode} {'\u00B7'} {snapshot.last_session.turns} turns {'\u00B7'} {snapshot.last_session.notes_created} notes {'\u00B7'} {snapshot.last_session.end_reason}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
