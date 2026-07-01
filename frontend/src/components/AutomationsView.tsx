import React, { useState, useEffect, useRef, useCallback } from 'react'
import { APP_CONFIG } from '../config'

interface TaskSummary {
  id: string
  status: string
  task_type: string
  query: string
  mode: string
  created_at: string | null
  completed_at: string | null
  updated_at: string | null
}

interface ExecutionEntry {
  type: 'tool_call' | 'llm_response'
  ts: string
  round: number
  tool?: string
  args?: Record<string, unknown>
  result?: string
  duration_ms?: number
  content?: string
}

interface TaskDetail extends TaskSummary {
  output: string
  error: string | null
  execution_log: ExecutionEntry[]
  working_directory?: string
  exit_code?: number
  found_items?: unknown[]
}

/** Backend timestamps come in two flavors: naive UTC (DB defaults like
 * `2026-04-09T13:04:13.908493`) and tz-aware ET from `local_now()`
 * (`2026-04-09T09:04:13.986016-04:00`). Only append 'Z' when there's no
 * timezone marker — appending to a tz-aware string produces invalid input. */
function utc(dateStr: string): Date {
  const hasTz = /Z$|[+-]\d{2}:?\d{2}$/.test(dateStr)
  return new Date(hasTz ? dateStr : dateStr + 'Z')
}

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return ''
  const diff = Date.now() - utc(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function formatDuration(start: string | null, end: string | null): string {
  if (!start) return ''
  const s = utc(start).getTime()
  const e = end ? utc(end).getTime() : Date.now()
  const secs = Math.floor((e - s) / 1000)
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
  superseded: { dot: 'bg-gray-400', label: 'Superseded', bg: 'bg-gray-500/20 text-gray-300' },
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
  const hasError = entry.result && (
    entry.result.toLowerCase().includes('error') ||
    entry.result.toLowerCase().includes('traceback') ||
    entry.result.toLowerCase().includes('failed')
  )

  return (
    <div className={`border rounded-lg p-3 space-y-2 ${hasError ? 'border-red-500/30 bg-red-500/5' : 'border-gray-700 bg-gray-800/50'}`}>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 rounded bg-teal-500/20 text-teal-300 text-xs font-mono font-medium">
            {entry.tool}
          </span>
          <span className="text-xs text-gray-500">
            Round {entry.round}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {entry.duration_ms != null && (
            <span className="text-xs text-gray-400 bg-gray-700/50 px-1.5 py-0.5 rounded">
              {entry.duration_ms > 1000 ? `${(entry.duration_ms / 1000).toFixed(1)}s` : `${entry.duration_ms}ms`}
            </span>
          )}
          <span className="text-xs text-gray-500">
            {utc(entry.ts).toLocaleTimeString()}
          </span>
        </div>
      </div>

      {entry.args && Object.keys(entry.args).length > 0 && (
        <CollapsibleSection title="Arguments">
          <pre className="text-xs text-gray-300 bg-gray-900 rounded p-2 overflow-x-auto max-h-40 overflow-y-auto font-mono whitespace-pre-wrap break-all">
            {JSON.stringify(entry.args, null, 2)}
          </pre>
        </CollapsibleSection>
      )}

      {entry.result && (
        <CollapsibleSection title="Result" defaultOpen={entry.result.length < 500}>
          <pre className="text-xs text-gray-300 bg-gray-900 rounded p-2 overflow-x-auto max-h-60 overflow-y-auto font-mono whitespace-pre-wrap break-all">
            {entry.result}
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
          <span className="text-xs text-gray-500">Round {entry.round}</span>
        </div>
        <span className="text-xs text-gray-500">
          {utc(entry.ts).toLocaleTimeString()}
        </span>
      </div>
      <p className="text-sm text-gray-300 whitespace-pre-wrap">{entry.content}</p>
    </div>
  )
}

export default function AutomationsView() {
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [liveEntries, setLiveEntries] = useState<ExecutionEntry[]>([])
  const [loading, setLoading] = useState(true)
  const logEndRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  // Fetch task list
  const fetchTasks = useCallback(async () => {
    try {
      const resp = await fetch(`${APP_CONFIG.apiUrl}/api/agents/tasks?limit=30`, {
        credentials: 'include',
      })
      if (resp.ok) {
        const data = await resp.json()
        setTasks(data.tasks || [])
      }
    } catch (e) {
      console.error('Failed to fetch tasks:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchTasks()
    const interval = setInterval(fetchTasks, 5000)
    return () => clearInterval(interval)
  }, [fetchTasks])

  // Fetch task detail
  const fetchDetail = useCallback(async (taskId: string) => {
    try {
      const resp = await fetch(`${APP_CONFIG.apiUrl}/api/agents/tasks/${taskId}`, {
        credentials: 'include',
      })
      if (resp.ok) {
        const data: TaskDetail = await resp.json()
        setDetail(data)
        setLiveEntries(data.execution_log || [])
      }
    } catch (e) {
      console.error('Failed to fetch task detail:', e)
    }
  }, [])

  // Select task
  useEffect(() => {
    if (selectedId) {
      fetchDetail(selectedId)
    } else {
      setDetail(null)
      setLiveEntries([])
    }
  }, [selectedId, fetchDetail])

  // SSE stream for running tasks
  useEffect(() => {
    if (!selectedId || !detail) return

    // Only stream for running tasks
    if (detail.status !== 'running') {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
      return
    }

    const es = new EventSource(
      `${APP_CONFIG.apiUrl}/api/agents/tasks/${selectedId}/stream`,
      { withCredentials: true }
    )
    eventSourceRef.current = es

    es.onmessage = (event) => {
      try {
        const entry = JSON.parse(event.data)
        if (entry.type === 'connected') return
        setLiveEntries(prev => [...prev, entry])
      } catch {
        // ignore parse errors
      }
    }

    es.onerror = () => {
      // Reconnect handled by EventSource, or task finished
      setTimeout(() => {
        if (selectedId) fetchDetail(selectedId)
      }, 2000)
    }

    return () => {
      es.close()
      eventSourceRef.current = null
    }
  }, [selectedId, detail?.status, fetchDetail])

  // Auto-scroll log
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [liveEntries])

  // Refresh detail when task status changes in the list
  useEffect(() => {
    if (!selectedId) return
    const task = tasks.find(t => t.id === selectedId)
    if (task && detail && task.status !== detail.status) {
      fetchDetail(selectedId)
    }
  }, [tasks, selectedId, detail, fetchDetail])

  const handleRetry = async (taskId: string) => {
    try {
      const resp = await fetch(`${APP_CONFIG.apiUrl}/api/agents/tasks/${taskId}/retry`, {
        method: 'POST',
        credentials: 'include',
      })
      if (resp.ok) {
        fetchTasks()
        setSelectedId(null)
      }
    } catch (e) {
      console.error('Retry failed:', e)
    }
  }

  const handleCancel = async (taskId: string) => {
    try {
      const resp = await fetch(`${APP_CONFIG.apiUrl}/api/agents/tasks/${taskId}/cancel`, {
        method: 'POST',
        credentials: 'include',
      })
      if (resp.ok) {
        fetchTasks()
        fetchDetail(taskId)
      }
    } catch (e) {
      console.error('Cancel failed:', e)
    }
  }

  return (
    <div className="flex h-full min-h-0">
      {/* Task List */}
      <div className="w-80 flex-shrink-0 border-r border-gray-700 flex flex-col bg-card">
        <div className="p-4 border-b border-gray-700">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-2">
            <span className="material-icons text-base">bolt</span>
            Agent Tasks
          </h2>
          <p className="text-xs text-gray-500 mt-1">
            {tasks.filter(t => t.status === 'running').length} running
          </p>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="p-4 text-center text-gray-500 text-sm">Loading...</div>
          ) : tasks.length === 0 ? (
            <div className="p-4 text-center text-gray-500 text-sm">
              No agent tasks yet. Dispatch tasks via chat.
            </div>
          ) : (
            tasks.map(task => (
              <button
                key={task.id}
                onClick={() => setSelectedId(task.id)}
                className={`w-full text-left p-3 border-b border-gray-800 hover:bg-gray-800/50 transition-colors ${
                  selectedId === task.id ? 'bg-gray-800 border-l-2 border-l-teal-400' : ''
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm text-gray-200 line-clamp-2 flex-1">
                    {task.query || 'Untitled task'}
                  </p>
                  <StatusBadge status={task.status} />
                </div>
                <div className="flex items-center gap-2 mt-1.5">
                  <span className="text-xs text-gray-500">
                    {timeAgo(task.created_at)}
                  </span>
                  <span className="text-xs text-gray-600 bg-gray-800 px-1.5 py-0.5 rounded">
                    {task.mode}
                  </span>
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Task Detail */}
      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        {!selectedId || !detail ? (
          <div className="flex-1 flex items-center justify-center text-gray-500">
            <div className="text-center">
              <span className="material-icons text-4xl mb-2 block text-gray-600">bolt</span>
              <p className="text-sm">Select a task to view execution details</p>
            </div>
          </div>
        ) : (
          <>
            {/* Detail Header */}
            <div className="p-4 border-b border-gray-700 flex-shrink-0">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-base text-gray-100 font-medium">
                    {detail.query || 'Untitled task'}
                  </p>
                  <div className="flex items-center gap-3 mt-2 flex-wrap">
                    <StatusBadge status={detail.status} />
                    <span className="text-xs text-gray-500">
                      {detail.created_at && utc(detail.created_at).toLocaleString()}
                    </span>
                    {detail.created_at && (
                      <span className="text-xs text-gray-400 bg-gray-800 px-1.5 py-0.5 rounded">
                        {formatDuration(detail.created_at, detail.completed_at)}
                      </span>
                    )}
                    <span className="text-xs text-gray-600 bg-gray-800 px-1.5 py-0.5 rounded">
                      {detail.mode}
                    </span>
                  </div>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  {(detail.status === 'running' || detail.status === 'pending') && (
                    <button
                      onClick={() => handleCancel(detail.id)}
                      className="px-3 py-1.5 text-xs bg-red-500/20 text-red-300 rounded-md hover:bg-red-500/30 transition-colors flex items-center gap-1"
                    >
                      <span className="material-icons text-sm">cancel</span>
                      Cancel
                    </button>
                  )}
                  {detail.status === 'failed' && (
                    <button
                      onClick={() => handleRetry(detail.id)}
                      className="px-3 py-1.5 text-xs bg-teal-500/20 text-teal-300 rounded-md hover:bg-teal-500/30 transition-colors flex items-center gap-1"
                    >
                      <span className="material-icons text-sm">replay</span>
                      Retry
                    </button>
                  )}
                </div>
              </div>

              {detail.error && (
                <div className="mt-3 p-2 bg-red-500/10 border border-red-500/20 rounded text-xs text-red-300 font-mono">
                  {detail.error}
                </div>
              )}

              {detail.output && detail.status === 'completed' && (
                <CollapsibleSection title="Output" defaultOpen={false}>
                  <div className="mt-1 p-2 bg-gray-800 rounded text-sm text-gray-300 whitespace-pre-wrap max-h-40 overflow-y-auto">
                    {detail.output}
                  </div>
                </CollapsibleSection>
              )}
            </div>

            {/* Execution Timeline */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                Execution Timeline
                {liveEntries.length > 0 && (
                  <span className="ml-2 text-gray-500 font-normal normal-case">
                    ({liveEntries.length} events)
                  </span>
                )}
              </h3>

              {liveEntries.length === 0 ? (
                <div className="text-center text-gray-500 text-sm py-8">
                  {detail.status === 'running' ? (
                    <div className="flex items-center justify-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
                      Waiting for execution events...
                    </div>
                  ) : (
                    'No execution trace available'
                  )}
                </div>
              ) : (
                liveEntries.map((entry, i) => (
                  <div key={i} className="animate-fadeIn">
                    {entry.type === 'tool_call' ? (
                      <ToolCallEntry entry={entry} />
                    ) : (
                      <LlmResponseEntry entry={entry} />
                    )}
                  </div>
                ))
              )}

              {detail.status === 'running' && liveEntries.length > 0 && (
                <div className="flex items-center gap-2 text-xs text-blue-400 py-2">
                  <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
                  Task is running...
                </div>
              )}

              <div ref={logEndRef} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
