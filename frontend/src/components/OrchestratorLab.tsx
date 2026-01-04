import { useState, useRef, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import { APP_CONFIG } from '../config'

interface Subtask {
  id: number
  description: string
  focus_areas?: string[]
}

interface ToolCallDetailed {
  id: string
  name: string
  arguments: Record<string, unknown>
}

interface ActivityEvent {
  timestamp: number
  phase: string
  message?: string
  model?: string
  worker_id?: number
  task?: string
  focus_areas?: string[]
  subtasks?: Subtask[]
  result_preview?: string
  result_full?: string
  result_length?: number
  duration_ms?: number
  error?: string
  raw_response?: string
  final_response?: string
  total_duration_ms?: number
  tool_calls?: string[]
  tool_calls_detailed?: ToolCallDetailed[]
  results_count?: number
  worker_prompt?: string
  // Worker tool call fields
  iteration?: number
  tool_name?: string
  tool_arguments?: Record<string, unknown>
  tool_result_preview?: string
  tool_result_full?: string
  tools_available?: string[]
  tool_calls_count?: number
  tool_calls_summary?: Array<{ tool: string; args: Record<string, unknown> }>
  iterations?: number
}

interface OrchestratorState {
  status: 'idle' | 'connecting' | 'running' | 'complete' | 'error'
  events: ActivityEvent[]
  finalResponse: string | null
  startTime: number | null
  error: string | null
  totalDuration: number | null
}

const initialState: OrchestratorState = {
  status: 'idle',
  events: [],
  finalResponse: null,
  startTime: null,
  error: null,
  totalDuration: null
}

export default function OrchestratorLab({ onBack }: { onBack: () => void }) {
  const [query, setQuery] = useState('')
  const [state, setState] = useState<OrchestratorState>(initialState)
  const [expandedEvents, setExpandedEvents] = useState<Set<number>>(new Set())
  const wsRef = useRef<WebSocket | null>(null)
  const eventsEndRef = useRef<HTMLDivElement>(null)

  const toggleEventExpanded = (idx: number) => {
    setExpandedEvents(prev => {
      const next = new Set(prev)
      if (next.has(idx)) {
        next.delete(idx)
      } else {
        next.add(idx)
      }
      return next
    })
  }

  // Auto-scroll to latest event
  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [state.events])

  // Cleanup WebSocket on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [])

  const formatElapsedTime = useCallback((startTime: number | null) => {
    if (!startTime) return '0:00'
    const elapsed = Math.floor((Date.now() - startTime) / 1000)
    const minutes = Math.floor(elapsed / 60)
    const seconds = elapsed % 60
    return `${minutes}:${seconds.toString().padStart(2, '0')}`
  }, [])

  const getStatusIcon = (phase: string) => {
    switch (phase) {
      case 'thinking':
        return <span className="animate-pulse">🧠</span>
      case 'spawning_workers':
        return <span>🚀</span>
      case 'workers_complete':
        return <span>📊</span>
      case 'worker_started':
        return <span className="animate-spin inline-block">⚙️</span>
      case 'worker_tool_call':
        return <span>🔧</span>
      case 'worker_complete':
        return <span>✅</span>
      case 'worker_error':
        return <span>❌</span>
      case 'complete':
        return <span>🎉</span>
      case 'error':
        return <span>⚠️</span>
      default:
        return <span>📌</span>
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim() || state.status === 'running') return

    // Reset state
    setState({
      ...initialState,
      status: 'connecting',
      startTime: Date.now()
    })

    // Create WebSocket connection
    const wsUrl = APP_CONFIG.apiUrl.replace('http', 'ws') + '/api/orchestrator/stream'
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      setState(prev => ({ ...prev, status: 'running' }))
      ws.send(JSON.stringify({ query: query.trim() }))
    }

    ws.onmessage = (event) => {
      const data: ActivityEvent = JSON.parse(event.data)
      data.timestamp = Date.now()

      setState(prev => {
        const newState = { ...prev }
        newState.events = [...prev.events, data]

        // Handle specific phases
        if (data.phase === 'complete') {
          newState.status = 'complete'
          if (data.final_response) {
            newState.finalResponse = data.final_response
          }
          if (data.total_duration_ms) {
            newState.totalDuration = data.total_duration_ms
          }
        }

        if (data.phase === 'error') {
          newState.status = 'error'
          newState.error = data.message || data.error || 'Unknown error'
        }

        return newState
      })
    }

    ws.onerror = () => {
      setState(prev => ({
        ...prev,
        status: 'error',
        error: 'WebSocket connection failed'
      }))
    }

    ws.onclose = () => {
      setState(prev => {
        if (prev.status === 'running') {
          return { ...prev, status: 'error', error: 'Connection closed unexpectedly' }
        }
        return prev
      })
    }
  }

  const handleReset = () => {
    if (wsRef.current) {
      wsRef.current.close()
    }
    setState(initialState)
    setExpandedEvents(new Set())
    setQuery('')
  }

  return (
    <div className="flex-1 flex flex-col h-full bg-gray-900">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-gray-700">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="p-2 hover:bg-gray-800 rounded-lg transition"
          >
            <svg className="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
          </button>
          <div>
            <h1 className="text-xl font-bold text-white flex items-center gap-2">
              <span>🧪</span> Orchestrator Lab
            </h1>
            <p className="text-sm text-gray-400">
              Test multi-agent task orchestration
            </p>
          </div>
        </div>

        {/* Model info */}
        <div className="text-right text-xs text-gray-500">
          <div>Orchestrator: <span className="text-teal-400">gpt-oss:20b</span></div>
          <div>Workers: <span className="text-purple-400">gpt-oss:20b</span></div>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-hidden flex flex-col p-4 gap-4">
        {/* Query input */}
        <form onSubmit={handleSubmit} className="flex gap-3">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Enter a research query (e.g., 'Research the best AI coding platforms')"
            className="flex-1 px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
            disabled={state.status === 'running' || state.status === 'connecting'}
          />
          <button
            type="submit"
            disabled={!query.trim() || state.status === 'running' || state.status === 'connecting'}
            className="px-6 py-3 bg-teal-600 text-white rounded-lg font-medium hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed transition flex items-center gap-2"
          >
            {state.status === 'running' || state.status === 'connecting' ? (
              <>
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                Running...
              </>
            ) : (
              <>
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Run Query
              </>
            )}
          </button>
          {state.status !== 'idle' && (
            <button
              type="button"
              onClick={handleReset}
              className="px-4 py-3 bg-gray-700 text-gray-300 rounded-lg hover:bg-gray-600 transition"
            >
              Reset
            </button>
          )}
        </form>

        {/* Activity Timeline */}
        {state.events.length > 0 && (
          <div className="flex-1 flex flex-col min-h-0">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">
                Activity Timeline
              </h2>
              {state.startTime && (
                <span className="text-sm text-gray-500">
                  Elapsed: {formatElapsedTime(state.startTime)}
                </span>
              )}
            </div>

            <div className="flex-1 overflow-y-auto bg-gray-800/50 rounded-lg border border-gray-700 p-3 space-y-2">
              {state.events.map((event, idx) => {
                const isExpanded = expandedEvents.has(idx)
                const hasDetails = event.tool_calls_detailed || event.worker_prompt || event.result_full || event.raw_response || event.tool_result_full || event.tool_calls_summary

                return (
                  <div
                    key={idx}
                    className={`rounded-lg ${
                      event.phase === 'error' || event.phase === 'worker_error'
                        ? 'bg-red-900/20 border border-red-500/30'
                        : event.phase === 'complete'
                        ? 'bg-green-900/20 border border-green-500/30'
                        : event.phase === 'worker_tool_call'
                        ? 'bg-blue-900/20 border border-blue-500/30 ml-6'
                        : 'bg-gray-700/30'
                    }`}
                  >
                    {/* Clickable Header */}
                    <div
                      className={`flex items-start gap-3 p-2 ${hasDetails ? 'cursor-pointer hover:bg-white/5' : ''}`}
                      onClick={() => hasDetails && toggleEventExpanded(idx)}
                    >
                      <span className="text-lg flex-shrink-0">{getStatusIcon(event.phase)}</span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 text-sm">
                          <span className="text-gray-400">
                            {state.startTime
                              ? formatElapsedTime(state.startTime - (Date.now() - event.timestamp))
                              : '0:00'}
                          </span>
                          <span className="font-medium text-white">
                            {event.worker_id !== undefined
                              ? `Worker ${event.worker_id}`
                              : 'Orchestrator'}
                          </span>
                          {event.model && (
                            <span className="text-xs px-2 py-0.5 bg-gray-700 rounded text-gray-400">
                              {event.model}
                            </span>
                          )}
                          {event.duration_ms !== undefined && (
                            <span className="text-xs text-gray-500">
                              ({(event.duration_ms / 1000).toFixed(1)}s)
                            </span>
                          )}
                          {hasDetails && (
                            <span className="text-xs text-gray-500 ml-auto">
                              {isExpanded ? '▼' : '▶'} Details
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-gray-300 mt-1">
                          {event.phase === 'worker_tool_call' ? (
                            <span>
                              <span className="text-blue-400 font-mono">{event.tool_name}</span>
                              <span className="text-gray-500 text-xs ml-2">(iter {event.iteration})</span>
                            </span>
                          ) : (
                            event.message || event.task || event.error || event.phase
                          )}
                        </p>
                        {event.focus_areas && event.focus_areas.length > 0 && (
                          <p className="text-xs text-blue-400 mt-1">
                            Focus: {event.focus_areas.join(', ')}
                          </p>
                        )}
                        {event.tool_calls && event.tool_calls.length > 0 && !isExpanded && (
                          <p className="text-xs text-purple-400 mt-1">
                            Tools: {event.tool_calls.join(', ')}
                          </p>
                        )}
                        {event.results_count !== undefined && (
                          <p className="text-xs text-green-400 mt-1">
                            Received {event.results_count} worker result(s)
                          </p>
                        )}
                        {!isExpanded && event.result_preview && (
                          <p className="text-xs text-gray-500 mt-1 truncate">
                            {event.result_preview}
                          </p>
                        )}
                        {/* Show tool arguments preview for worker tool calls */}
                        {event.phase === 'worker_tool_call' && event.tool_arguments && !isExpanded && (
                          <p className="text-xs text-gray-500 mt-1 font-mono truncate">
                            {JSON.stringify(event.tool_arguments)}
                          </p>
                        )}
                        {/* Show tools available for worker_started */}
                        {event.tools_available && event.tools_available.length > 0 && (
                          <p className="text-xs text-cyan-400 mt-1">
                            Tools: {event.tools_available.join(', ')}
                          </p>
                        )}
                        {/* Show iterations and tool call count for worker_complete */}
                        {event.phase === 'worker_complete' && event.iterations !== undefined && (
                          <p className="text-xs text-gray-400 mt-1">
                            {event.iterations} iterations, {event.tool_calls_count || 0} tool calls
                          </p>
                        )}
                      </div>
                    </div>

                    {/* Expanded Details Panel */}
                    {isExpanded && (
                      <div className="border-t border-gray-600 p-3 space-y-3 bg-gray-900/50">
                        {/* Tool Calls Details */}
                        {event.tool_calls_detailed && event.tool_calls_detailed.length > 0 && (
                          <div>
                            <h4 className="text-xs font-semibold text-purple-400 uppercase mb-2">Tool Calls</h4>
                            {event.tool_calls_detailed.map((tc, tcIdx) => (
                              <div key={tcIdx} className="mb-2 p-2 bg-gray-800 rounded">
                                <div className="flex items-center gap-2 mb-1">
                                  <span className="text-sm font-mono text-purple-300">{tc.name}</span>
                                  <span className="text-xs text-gray-500">ID: {tc.id}</span>
                                </div>
                                <pre className="text-xs text-gray-400 overflow-x-auto whitespace-pre-wrap">
                                  {JSON.stringify(tc.arguments, null, 2)}
                                </pre>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Worker Prompt */}
                        {event.worker_prompt && (
                          <div>
                            <h4 className="text-xs font-semibold text-yellow-400 uppercase mb-2">Worker Prompt</h4>
                            <pre className="p-2 bg-gray-800 rounded text-xs text-gray-300 overflow-x-auto whitespace-pre-wrap max-h-48 overflow-y-auto">
                              {event.worker_prompt}
                            </pre>
                          </div>
                        )}

                        {/* Full Result */}
                        {event.result_full && (
                          <div>
                            <h4 className="text-xs font-semibold text-green-400 uppercase mb-2">
                              Full Result ({event.result_length} chars)
                            </h4>
                            <pre className="p-2 bg-gray-800 rounded text-xs text-gray-300 overflow-x-auto whitespace-pre-wrap max-h-96 overflow-y-auto">
                              {event.result_full}
                            </pre>
                          </div>
                        )}

                        {/* Worker Tool Call Arguments */}
                        {event.phase === 'worker_tool_call' && event.tool_arguments && (
                          <div>
                            <h4 className="text-xs font-semibold text-blue-400 uppercase mb-2">Tool Arguments</h4>
                            <pre className="p-2 bg-gray-800 rounded text-xs text-gray-300 overflow-x-auto whitespace-pre-wrap">
                              {JSON.stringify(event.tool_arguments, null, 2)}
                            </pre>
                          </div>
                        )}

                        {/* Worker Tool Call Result */}
                        {event.tool_result_full && (
                          <div>
                            <h4 className="text-xs font-semibold text-cyan-400 uppercase mb-2">Tool Result</h4>
                            <pre className="p-2 bg-gray-800 rounded text-xs text-gray-300 overflow-x-auto whitespace-pre-wrap max-h-64 overflow-y-auto">
                              {event.tool_result_full}
                            </pre>
                          </div>
                        )}

                        {/* Tool Calls Summary (for worker_complete) */}
                        {event.tool_calls_summary && event.tool_calls_summary.length > 0 && (
                          <div>
                            <h4 className="text-xs font-semibold text-purple-400 uppercase mb-2">
                              All Tool Calls ({event.tool_calls_summary.length})
                            </h4>
                            <div className="space-y-2">
                              {event.tool_calls_summary.map((tc, tcIdx) => (
                                <div key={tcIdx} className="p-2 bg-gray-800 rounded">
                                  <span className="text-sm font-mono text-purple-300">{tc.tool}</span>
                                  <pre className="text-xs text-gray-400 mt-1 overflow-x-auto whitespace-pre-wrap">
                                    {JSON.stringify(tc.args, null, 2)}
                                  </pre>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Raw Response (for errors) */}
                        {event.raw_response && (
                          <div>
                            <h4 className="text-xs font-semibold text-red-400 uppercase mb-2">Raw Response</h4>
                            <pre className="p-2 bg-gray-800 rounded text-xs text-gray-400 overflow-x-auto whitespace-pre-wrap max-h-48 overflow-y-auto">
                              {event.raw_response}
                            </pre>
                          </div>
                        )}

                        {/* Full Event JSON */}
                        <details className="mt-2">
                          <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-400">
                            Show raw event JSON
                          </summary>
                          <pre className="mt-1 p-2 bg-gray-800 rounded text-xs text-gray-500 overflow-x-auto whitespace-pre-wrap max-h-48 overflow-y-auto">
                            {JSON.stringify(event, null, 2)}
                          </pre>
                        </details>
                      </div>
                    )}
                  </div>
                )
              })}
              <div ref={eventsEndRef} />
            </div>
          </div>
        )}

        {/* Final Response */}
        {state.finalResponse && (
          <div className="flex-1 flex flex-col min-h-0 mt-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">
                Orchestrator Response
              </h2>
              {state.totalDuration && (
                <span className="text-xs text-gray-500">
                  Total time: {(state.totalDuration / 1000).toFixed(1)}s
                </span>
              )}
            </div>
            <div className="flex-1 overflow-y-auto bg-gray-800 rounded-lg border border-gray-700 p-4">
              <div className="prose prose-invert prose-sm max-w-none">
                <ReactMarkdown>
                  {state.finalResponse}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        )}

        {/* Error state */}
        {state.status === 'error' && !state.finalResponse && (
          <div className="p-4 bg-red-900/20 border border-red-500/30 rounded-lg">
            <div className="flex items-center gap-2 text-red-400">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span className="font-medium">Error</span>
            </div>
            <p className="mt-2 text-gray-300">{state.error}</p>
          </div>
        )}

        {/* Idle state */}
        {state.status === 'idle' && (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center text-gray-500">
              <div className="text-6xl mb-4">🔬</div>
              <p className="text-lg">Enter a research query to test orchestration</p>
              <p className="text-sm mt-2">
                The orchestrator will decompose your query into subtasks,
                <br />
                execute them in parallel, and consolidate the results.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
