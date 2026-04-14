import React, { useState, useEffect, useRef, useCallback } from 'react'
import { APP_CONFIG } from '../config'

/**
 * Slide-in drawer that follows a background task's live execution log.
 *
 * Backend wiring:
 *   - GET  /api/agents/tasks/{id}        → snapshot incl. execution_log
 *   - GET  /api/agents/tasks/{id}/stream → SSE of new dispatch events
 *
 * The SSE channel publishes one JSON event per LLM response and per tool call
 * via Redis pub/sub `sara:dispatch:live:{task_id}`. Events match the
 * execution_log entry shape so we can splice them in directly.
 */

interface ExecutionEntry {
  type: 'tool_call' | 'llm_response' | 'connected'
  ts?: string
  round?: number
  tool?: string
  args?: Record<string, unknown>
  result?: string
  duration_ms?: number
  content?: string
}

interface TaskDetail {
  id: string
  status: string
  query: string
  mode: string
  created_at: string | null
  completed_at: string | null
  result_note_id: string | null
  output?: string
  error?: string | null
  execution_log: ExecutionEntry[]
  clarification_question?: string | null
}

interface BackgroundTaskDetailDrawerProps {
  taskId: string
  onClose: () => void
  onOpenNote?: (noteId: string) => void
}

// Backend timestamps come in two flavors:
//   - vm_claude dispatch entries:  `2026-04-09T09:04:13.986016-04:00` (ET-aware via local_now)
//   - DB-server defaults:          `2026-04-09T13:04:13.908493`        (naive UTC from func.now())
// Only append 'Z' when there's no timezone marker at all — otherwise we'd
// produce invalid strings like `...986016-04:00Z` and JavaScript returns
// Invalid Date.
function utc(dateStr: string | null | undefined): Date | null {
  if (!dateStr) return null
  const hasTz = /Z$|[+-]\d{2}:?\d{2}$/.test(dateStr)
  return new Date(hasTz ? dateStr : dateStr + 'Z')
}

function timeAgo(dateStr: string | null | undefined): string {
  const d = utc(dateStr)
  if (!d) return ''
  const diff = Date.now() - d.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function formatDuration(start: string | null | undefined, end: string | null | undefined): string {
  const s = utc(start)
  if (!s) return ''
  const e = utc(end) ?? new Date()
  const secs = Math.floor((e.getTime() - s.getTime()) / 1000)
  if (secs < 60) return `${secs}s`
  const mins = Math.floor(secs / 60)
  const remSecs = secs % 60
  if (mins < 60) return `${mins}m ${remSecs}s`
  return `${Math.floor(mins / 60)}h ${mins % 60}m`
}

const STATUS_CONFIG: Record<string, { dot: string; label: string; bg: string }> = {
  running: { dot: 'bg-blue-400 animate-pulse', label: 'Running', bg: 'bg-blue-500/20 text-blue-300' },
  completed: { dot: 'bg-emerald-400', label: 'Done', bg: 'bg-emerald-500/20 text-emerald-300' },
  failed: { dot: 'bg-red-400', label: 'Failed', bg: 'bg-red-500/20 text-red-300' },
  pending: { dot: 'bg-yellow-400', label: 'Pending', bg: 'bg-yellow-500/20 text-yellow-300' },
  needs_clarification: { dot: 'bg-amber-400', label: 'Needs Input', bg: 'bg-amber-500/20 text-amber-300' },
  cancelled: { dot: 'bg-gray-400', label: 'Cancelled', bg: 'bg-gray-500/20 text-gray-300' },
}

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] || { dot: 'bg-gray-400', label: status, bg: 'bg-gray-500/20 text-gray-300' }
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${cfg.bg}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  )
}

function CollapsibleSection({ title, defaultOpen = false, children }: {
  title: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="text-xs text-gray-400 hover:text-gray-200 flex items-center gap-1"
      >
        <span className="material-icons text-sm">{open ? 'expand_less' : 'expand_more'}</span>
        {title}
      </button>
      {open && <div className="mt-1">{children}</div>}
    </div>
  )
}

function ToolCallEntry({ entry }: { entry: ExecutionEntry }) {
  const result = entry.result || ''
  const lower = result.toLowerCase()
  const hasError =
    lower.includes('traceback') ||
    lower.startsWith('error') ||
    lower.includes('\nerror') ||
    lower.includes('exit code') && !lower.includes('exit code 0')

  return (
    <div className={`border rounded-lg p-3 space-y-2 ${hasError ? 'border-red-500/30 bg-red-500/5' : 'border-gray-700 bg-gray-800/50'}`}>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 rounded bg-teal-500/20 text-teal-300 text-xs font-mono font-medium">
            {entry.tool}
          </span>
          {entry.round != null && (
            <span className="text-xs text-gray-500">Round {entry.round}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {entry.duration_ms != null && (
            <span className="text-xs text-gray-400 bg-gray-700/50 px-1.5 py-0.5 rounded">
              {entry.duration_ms > 1000 ? `${(entry.duration_ms / 1000).toFixed(1)}s` : `${entry.duration_ms}ms`}
            </span>
          )}
          {entry.ts && (
            <span className="text-xs text-gray-500">
              {utc(entry.ts)?.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {entry.args && Object.keys(entry.args).length > 0 && (
        <CollapsibleSection title="Arguments">
          <pre className="text-xs text-gray-300 bg-gray-900 rounded p-2 overflow-x-auto max-h-40 overflow-y-auto font-mono whitespace-pre-wrap break-all">
            {JSON.stringify(entry.args, null, 2)}
          </pre>
        </CollapsibleSection>
      )}

      {result && (
        <CollapsibleSection title="Result" defaultOpen={result.length < 500}>
          <pre className="text-xs text-gray-300 bg-gray-900 rounded p-2 overflow-x-auto max-h-60 overflow-y-auto font-mono whitespace-pre-wrap break-all">
            {result}
          </pre>
        </CollapsibleSection>
      )}
    </div>
  )
}

function LlmResponseEntry({ entry }: { entry: ExecutionEntry }) {
  return (
    <div className="border border-gray-700/50 rounded-lg p-3 bg-gray-800/30">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 text-xs font-medium">
            LLM Response
          </span>
          {entry.round != null && (
            <span className="text-xs text-gray-500">Round {entry.round}</span>
          )}
        </div>
        {entry.ts && (
          <span className="text-xs text-gray-500">
            {utc(entry.ts)?.toLocaleTimeString()}
          </span>
        )}
      </div>
      <p className="text-sm text-gray-300 whitespace-pre-wrap">{entry.content}</p>
    </div>
  )
}

export const BackgroundTaskDetailDrawer: React.FC<BackgroundTaskDetailDrawerProps> = ({
  taskId,
  onClose,
  onOpenNote,
}) => {
  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [entries, setEntries] = useState<ExecutionEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [streamConnected, setStreamConnected] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)
  const logEndRef = useRef<HTMLDivElement>(null)
  const autoScrollRef = useRef(true)

  // Initial detail fetch (snapshot)
  const fetchDetail = useCallback(async () => {
    try {
      const resp = await fetch(`${APP_CONFIG.apiUrl}/api/agents/tasks/${taskId}`, {
        credentials: 'include',
      })
      if (resp.ok) {
        const data: TaskDetail = await resp.json()
        setDetail(data)
        setEntries(data.execution_log || [])
      } else if (resp.status === 404) {
        // Some background tasks (older orchestrator pipeline) aren't visible
        // through the agents endpoint. Fall back gracefully.
        setDetail(null)
      }
    } catch (e) {
      console.error('Failed to fetch task detail:', e)
    } finally {
      setLoading(false)
    }
  }, [taskId])

  useEffect(() => {
    setLoading(true)
    setEntries([])
    setDetail(null)
    fetchDetail()
  }, [taskId, fetchDetail])

  // Live SSE stream (only while running)
  useEffect(() => {
    if (!detail || detail.status !== 'running') {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
      setStreamConnected(false)
      return
    }

    const es = new EventSource(
      `${APP_CONFIG.apiUrl}/api/agents/tasks/${taskId}/stream`,
      { withCredentials: true }
    )
    eventSourceRef.current = es

    es.onopen = () => setStreamConnected(true)

    es.onmessage = (event) => {
      try {
        const entry: ExecutionEntry = JSON.parse(event.data)
        if (entry.type === 'connected') {
          setStreamConnected(true)
          return
        }
        setEntries(prev => [...prev, entry])
      } catch {
        // Ignore parse errors
      }
    }

    es.onerror = () => {
      setStreamConnected(false)
      // Refetch detail in case the task moved to completed/failed
      setTimeout(fetchDetail, 1500)
    }

    return () => {
      es.close()
      eventSourceRef.current = null
      setStreamConnected(false)
    }
  }, [taskId, detail?.status, fetchDetail])

  // Periodic poll for status changes (covers SSE drops + completed-state output)
  useEffect(() => {
    if (!detail || detail.status === 'completed' || detail.status === 'failed') return
    const interval = setInterval(fetchDetail, 8000)
    return () => clearInterval(interval)
  }, [detail?.status, fetchDetail])

  // Auto-scroll to newest entry, unless user has scrolled up
  useEffect(() => {
    if (autoScrollRef.current) {
      logEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [entries.length])

  // ESC to close
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // Detect manual scroll-up to disable auto-scroll
  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    autoScrollRef.current = nearBottom
  }

  const isRunning = detail?.status === 'running' || detail?.status === 'pending'

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-[60]"
        onClick={onClose}
        aria-hidden
      />

      {/* Drawer */}
      <div
        className="fixed top-0 right-0 h-full w-full sm:w-[640px] bg-gray-900 border-l border-gray-700 shadow-2xl z-[70] flex flex-col"
        role="dialog"
        aria-label="Background task detail"
      >
        {/* Header */}
        <div className="px-5 py-4 border-b border-gray-700 bg-gray-850 flex-shrink-0">
          <div className="flex items-start justify-between gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                {detail && <StatusBadge status={detail.status} />}
                {streamConnected && (
                  <span className="inline-flex items-center gap-1 text-xs text-blue-300">
                    <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                    live
                  </span>
                )}
                {detail?.mode && (
                  <span className="text-xs text-gray-500 bg-gray-800 px-1.5 py-0.5 rounded font-mono">
                    {detail.mode}
                  </span>
                )}
              </div>
              <h2 className="text-sm font-medium text-gray-100 line-clamp-2">
                {detail?.query || 'Loading…'}
              </h2>
              {detail && (
                <p className="text-xs text-gray-500 mt-1">
                  {detail.status === 'completed' || detail.status === 'failed'
                    ? `Ran for ${formatDuration(detail.created_at, detail.completed_at)} · ${timeAgo(detail.completed_at)}`
                    : `Started ${timeAgo(detail.created_at)} · running ${formatDuration(detail.created_at, null)}`}
                </p>
              )}
            </div>
            <button
              onClick={onClose}
              className="p-1 -m-1 text-gray-400 hover:text-gray-200 rounded"
              aria-label="Close"
            >
              <span className="material-icons">close</span>
            </button>
          </div>
        </div>

        {/* Body */}
        <div
          className="flex-1 overflow-y-auto px-5 py-4 space-y-2"
          onScroll={handleScroll}
        >
          {loading && (
            <div className="text-center text-gray-500 text-sm py-8">Loading…</div>
          )}

          {!loading && !detail && (
            <div className="text-center text-gray-500 text-sm py-8">
              Task not found in the agent dispatch log.<br/>
              <span className="text-xs text-gray-600">
                It may belong to an older background task pipeline.
              </span>
            </div>
          )}

          {!loading && detail && entries.length === 0 && (
            <div className="text-center text-gray-500 text-sm py-8">
              {isRunning
                ? 'Waiting for first agent action…'
                : 'No execution log recorded.'}
            </div>
          )}

          {entries.map((entry, idx) => {
            if (entry.type === 'tool_call') {
              return <ToolCallEntry key={`${entry.ts}-${idx}`} entry={entry} />
            }
            if (entry.type === 'llm_response') {
              return <LlmResponseEntry key={`${entry.ts}-${idx}`} entry={entry} />
            }
            return null
          })}

          {detail?.error && (
            <div className="border border-red-500/40 bg-red-500/10 rounded-lg p-3 mt-3">
              <p className="text-xs text-red-300 font-semibold mb-1">Error</p>
              <pre className="text-xs text-red-200 whitespace-pre-wrap font-mono">
                {detail.error}
              </pre>
            </div>
          )}

          <div ref={logEndRef} />
        </div>

        {/* Footer */}
        {detail && (
          <div className="px-5 py-3 border-t border-gray-700 bg-gray-850 flex-shrink-0 flex items-center justify-between gap-3">
            <div className="text-xs text-gray-500">
              {entries.length} {entries.length === 1 ? 'event' : 'events'}
            </div>
            <div className="flex items-center gap-2">
              {detail.result_note_id && onOpenNote && (
                <button
                  onClick={() => {
                    onOpenNote(detail.result_note_id!)
                    onClose()
                  }}
                  className="text-xs px-3 py-1.5 rounded bg-blue-500/20 text-blue-300 hover:bg-blue-500/30 flex items-center gap-1"
                >
                  <span className="material-icons text-sm">description</span>
                  View result note
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  )
}

export default BackgroundTaskDetailDrawer
