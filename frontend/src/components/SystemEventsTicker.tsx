import React, { useEffect, useMemo, useRef, useState } from 'react'
import { APP_CONFIG } from '../config'

// The narrator's broadcast channel. Wires to the backend WebSocket at
// /api/narrator/stream, which delivers an initial batch then forwards
// every new SYSTEM_NARRATION_EMITTED event live.
//
// Surfaces 1-2-3 in the spec: desktop popup (PR 3), iOS push (PR 4),
// this ticker (PR 6). All three consume the same underlying event.

type Severity =
  | 'roast'
  | 'observation'
  | 'achievement'
  | 'patch_note'
  | 'sponsored'
  | 'grudging'
  | 'deflected'

interface SystemEvent {
  id: string
  user_id: string
  type: string
  title: string
  body: string
  subtitle: string | null
  severity: Severity
  trigger_name: string
  trigger_context: Record<string, any>
  ttl_seconds: number
  sound: string | null
  delivered_to: string[]
  suppressed: boolean
  suppression_reason: string | null
  created_at: string
}

interface InitialLoadMsg {
  type: 'initial_load'
  events: SystemEvent[]
}
interface EventMsg {
  type: 'event'
  event: SystemEvent
}
type WSMsg = InitialLoadMsg | EventMsg

// Color stripes match the desktop popup so the surfaces feel like the
// same persona broadcasting at different volumes.
const SEVERITY_STYLES: Record<Severity, { stripe: string; label: string; pill: string }> = {
  roast:       { stripe: 'bg-red-400/70',    label: 'text-red-300',    pill: 'border-red-400/30 bg-red-500/10' },
  observation: { stripe: 'bg-slate-400/40',  label: 'text-slate-400',  pill: 'border-slate-400/20 bg-slate-500/10' },
  achievement: { stripe: 'bg-amber-300/80',  label: 'text-amber-200',  pill: 'border-amber-300/30 bg-amber-400/10' },
  patch_note:  { stripe: 'bg-sky-400/70',    label: 'text-sky-300',    pill: 'border-sky-400/30 bg-sky-500/10' },
  sponsored:   { stripe: 'bg-fuchsia-400/70', label: 'text-fuchsia-300', pill: 'border-fuchsia-400/30 bg-fuchsia-500/10' },
  grudging:    { stripe: 'bg-zinc-300/60',   label: 'text-zinc-300',   pill: 'border-zinc-400/20 bg-zinc-500/10' },
  deflected:   { stripe: 'bg-emerald-300/60', label: 'text-emerald-300', pill: 'border-emerald-400/20 bg-emerald-500/10' },
}

function relativeTime(iso: string): string {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000))
  if (sec < 45) return 'just now'
  if (sec < 90) return '1m ago'
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`
  return `${Math.round(sec / 86400)}d ago`
}

interface SystemEventsTickerProps {
  /** Maximum events to keep in memory. Older ones get dropped. */
  maxEvents?: number
  /** Show suppressed (silent) events by default. */
  defaultShowSuppressed?: boolean
}

export default function SystemEventsTicker({
  maxEvents = 200,
  defaultShowSuppressed = false,
}: SystemEventsTickerProps) {
  const [events, setEvents] = useState<SystemEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [showSuppressed, setShowSuppressed] = useState(defaultShowSuppressed)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<number | null>(null)

  useEffect(() => {
    let cancelled = false

    function connect() {
      if (cancelled) return
      const wsUrl = APP_CONFIG.apiUrl.replace(/^http/, 'ws') + '/api/narrator/stream'
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        if (cancelled) return
        setConnected(true)
        console.log('[Narrator] WS connected')
      }

      ws.onmessage = (msg) => {
        if (cancelled) return
        try {
          const data: WSMsg = JSON.parse(msg.data)
          if (data.type === 'initial_load') {
            setEvents(data.events.slice(0, maxEvents))
          } else if (data.type === 'event') {
            setEvents((prev) => {
              // Avoid dupes if the same event somehow arrives twice.
              if (prev.some((e) => e.id === data.event.id)) return prev
              return [data.event, ...prev].slice(0, maxEvents)
            })
          }
        } catch {
          // Ignore non-JSON keepalive frames.
        }
      }

      ws.onclose = () => {
        if (cancelled) return
        setConnected(false)
        // Reconnect after a short delay so transient blips don't drop the feed.
        reconnectTimerRef.current = window.setTimeout(connect, 4000)
      }

      ws.onerror = () => {
        // onclose will fire next; let it handle the reconnect.
      }
    }

    connect()
    return () => {
      cancelled = true
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [maxEvents])

  const visible = useMemo(() => {
    return showSuppressed ? events : events.filter((e) => !e.suppressed)
  }, [events, showSuppressed])

  const suppressedCount = useMemo(
    () => events.filter((e) => e.suppressed).length,
    [events]
  )

  return (
    <div className="assistant-panel-soft relative overflow-hidden rounded-2xl p-4">
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-white/10 via-white/5 to-transparent" />
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <h3 className="font-display text-base font-semibold text-white">System AI</h3>
          <p className="mt-0.5 text-xs leading-relaxed text-slate-500">
            Broadcasts from the narrator. {suppressedCount > 0 && !showSuppressed && (
              <span className="text-slate-600"> {suppressedCount} silent moment{suppressedCount === 1 ? '' : 's'} noted, not narrated.</span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full ${connected ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]' : 'bg-slate-600'}`}
            title={connected ? 'Live' : 'Reconnecting…'}
          />
          <button
            type="button"
            onClick={() => setShowSuppressed((v) => !v)}
            className="rounded-full border border-white/8 bg-white/[0.03] px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-slate-400 hover:text-slate-200 hover:border-white/15 transition"
          >
            {showSuppressed ? 'Hide silent' : 'Show silent'}
          </button>
        </div>
      </div>

      <div className="space-y-1.5 max-h-[28rem] overflow-y-auto pr-1">
        {visible.length === 0 ? (
          <div className="assistant-panel-muted rounded-2xl px-3 py-6 text-center text-xs text-slate-500">
            The System has nothing to broadcast yet.
          </div>
        ) : (
          visible.map((evt) => {
            const styles = SEVERITY_STYLES[evt.severity] || SEVERITY_STYLES.observation
            const isExpanded = expandedId === evt.id
            const titleClass = evt.suppressed
              ? 'truncate text-sm italic text-slate-500'
              : 'truncate text-sm font-medium text-slate-100'
            return (
              <button
                key={evt.id}
                type="button"
                onClick={() => setExpandedId(isExpanded ? null : evt.id)}
                className={`group relative w-full overflow-hidden rounded-xl border border-white/5 bg-white/[0.02] hover:bg-white/[0.045] px-3 py-2 text-left transition ${evt.suppressed ? 'opacity-60' : ''}`}
              >
                <span className={`absolute inset-y-2 left-0 w-0.5 rounded-r ${styles.stripe}`} />
                <div className="ml-2 flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className={`text-[9px] font-bold uppercase tracking-[0.18em] ${styles.label}`}>
                        {evt.severity}
                      </span>
                      <span className="text-[9px] uppercase tracking-wider text-slate-600">
                        {evt.trigger_name}
                      </span>
                      {evt.suppressed && (
                        <span className="rounded-full border border-slate-700 bg-slate-900/60 px-1.5 py-0 text-[9px] uppercase tracking-wider text-slate-500">
                          silent
                        </span>
                      )}
                    </div>
                    <p className={titleClass + ' mt-0.5'}>{evt.title}</p>
                    {!isExpanded && (
                      <p className="mt-0.5 line-clamp-2 text-xs leading-snug text-slate-400">
                        {evt.body}
                      </p>
                    )}
                  </div>
                  <span className="flex-shrink-0 text-[10px] text-slate-600">
                    {relativeTime(evt.created_at)}
                  </span>
                </div>
                {isExpanded && (
                  <div className="ml-2 mt-2 space-y-2 border-t border-white/5 pt-2">
                    <p className="text-xs leading-relaxed text-slate-300">{evt.body}</p>
                    {evt.subtitle && (
                      <p className="text-xs italic text-slate-500">{evt.subtitle}</p>
                    )}
                    {evt.suppression_reason && (
                      <p className="text-[10px] text-slate-500">
                        suppressed: {evt.suppression_reason}
                      </p>
                    )}
                    {Object.keys(evt.trigger_context).length > 0 && (
                      <details className="text-[10px] text-slate-500">
                        <summary className="cursor-pointer select-none text-slate-500 hover:text-slate-300">
                          trigger context
                        </summary>
                        <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded bg-black/30 p-2 font-mono text-[10px] text-slate-400">
                          {JSON.stringify(evt.trigger_context, null, 2)}
                        </pre>
                      </details>
                    )}
                    <div className="flex flex-wrap gap-1 text-[9px] uppercase tracking-wider text-slate-600">
                      <span className={`rounded-full border px-1.5 py-0 ${styles.pill} ${styles.label}`}>
                        {evt.severity}
                      </span>
                      {evt.delivered_to.map((d, i) => (
                        <span key={i} className="rounded-full border border-white/8 bg-white/[0.03] px-1.5 py-0">
                          {d}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}
