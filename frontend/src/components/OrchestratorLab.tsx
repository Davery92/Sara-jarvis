import { useState, useRef, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import { APP_CONFIG } from '../config'

// Types for Model Selection
interface OllamaModel {
  name: string
  size: string
  modified_at: string
  details: Record<string, unknown>
}

// Types for Automation Tab
interface AutomationTask {
  id: string
  name: string
  original_intent: string
  description: string | null
  status: string
  schedule_type: string
  next_wake_at: string | null
  execution_count: number
  max_executions: number | null
  expires_at: string | null
  last_executed_at: string | null
  created_at: string
  consecutive_errors: number
  last_error: string | null
}

interface ExecutionLog {
  id: number
  started_at: string
  completed_at: string | null
  step_executed: number
  action_primitive: string
  status: string
  result: Record<string, unknown> | null
  error_message: string | null
}

interface AutomationTestResult {
  success: boolean
  name: string
  description: string
  schedule_type: string
  schedule_definition: Record<string, unknown>
  actions: Record<string, unknown>[]
  conditions: Record<string, unknown>[]
  expires_at: string | null
  max_executions: number | null
  confirmation_summary: string
  human_readable_summary: string
  parse_confidence: number
  warnings: string[]
  validation_errors: string[]
}

type TabType = 'research' | 'automations'

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
  // Tab state
  const [activeTab, setActiveTab] = useState<TabType>('research')

  // Model selection state
  const [availableModels, setAvailableModels] = useState<OllamaModel[]>([])
  const [selectedModel, setSelectedModel] = useState<string>('gpt-oss:20b')
  const [modelsLoading, setModelsLoading] = useState(true)
  const [modelsError, setModelsError] = useState<string | null>(null)

  // Research tab state
  const [query, setQuery] = useState('')
  const [state, setState] = useState<OrchestratorState>(initialState)
  const [expandedEvents, setExpandedEvents] = useState<Set<number>>(new Set())
  const wsRef = useRef<WebSocket | null>(null)
  const eventsEndRef = useRef<HTMLDivElement>(null)

  // Automation tab state
  const [automationTasks, setAutomationTasks] = useState<AutomationTask[]>([])
  const [selectedTask, setSelectedTask] = useState<AutomationTask | null>(null)
  const [executionLogs, setExecutionLogs] = useState<ExecutionLog[]>([])
  const [automationLoading, setAutomationLoading] = useState(false)
  const [automationIntent, setAutomationIntent] = useState('')

  // Automation test state
  const [testIntent, setTestIntent] = useState('')
  const [testResult, setTestResult] = useState<AutomationTestResult | null>(null)
  const [testLoading, setTestLoading] = useState(false)
  const [testError, setTestError] = useState<string | null>(null)

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

  // Fetch available models on mount
  const fetchModels = useCallback(async () => {
    setModelsLoading(true)
    setModelsError(null)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/orchestrator/models`)
      if (response.ok) {
        const data = await response.json()
        if (data.error) {
          setModelsError(data.error)
        } else {
          setAvailableModels(data.models || [])
          // Set default model if available
          if (data.models?.length > 0 && !data.models.find((m: OllamaModel) => m.name === selectedModel)) {
            setSelectedModel(data.models[0].name)
          }
        }
      }
    } catch (error) {
      console.error('Failed to fetch models:', error)
      setModelsError('Failed to connect to Ollama server')
    } finally {
      setModelsLoading(false)
    }
  }, [selectedModel])

  useEffect(() => {
    fetchModels()
  }, [])

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
      ws.send(JSON.stringify({
        query: query.trim(),
        orchestrator_model: selectedModel,
        worker_model: selectedModel  // Use same model for both
      }))
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

  // Automation Tab Functions
  const fetchAutomationTasks = useCallback(async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/automation/tasks`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setAutomationTasks(data || [])
      }
    } catch (error) {
      console.error('Failed to fetch automation tasks:', error)
    }
  }, [])

  const fetchExecutionLogs = async (taskId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/automation/tasks/${taskId}/logs`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setExecutionLogs(data || [])
      }
    } catch (error) {
      console.error('Failed to fetch execution logs:', error)
    }
  }

  const handleAutomationAction = async (taskId: string, action: 'pause' | 'resume' | 'cancel') => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/automation/tasks/${taskId}/${action}`, {
        method: 'POST',
        credentials: 'include'
      })
      if (response.ok) {
        fetchAutomationTasks()
        if (selectedTask?.id === taskId) {
          setSelectedTask(null)
        }
      }
    } catch (error) {
      console.error(`Failed to ${action} automation:`, error)
    }
  }

  // Test automation intent (dry run)
  const testAutomationIntent = async () => {
    if (!testIntent.trim() || testLoading) return

    setTestLoading(true)
    setTestError(null)
    setTestResult(null)

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/automation/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          intent: testIntent.trim(),
          model: selectedModel  // Use the same model as research
        })
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const data = await response.json()
      setTestResult(data)
    } catch (error) {
      console.error('Failed to test automation:', error)
      setTestError(error instanceof Error ? error.message : 'Unknown error')
    } finally {
      setTestLoading(false)
    }
  }

  const clearTestResult = () => {
    setTestResult(null)
    setTestError(null)
  }

  // Fetch automations when tab changes
  useEffect(() => {
    if (activeTab === 'automations') {
      fetchAutomationTasks()
      const interval = setInterval(fetchAutomationTasks, 10000)
      return () => clearInterval(interval)
    }
  }, [activeTab, fetchAutomationTasks])

  const getStatusBadge = (status: string) => {
    const config: Record<string, { bg: string; text: string; icon: string }> = {
      active: { bg: 'bg-green-500/20', text: 'text-green-400', icon: 'play_circle' },
      pending_confirmation: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', icon: 'pending' },
      paused: { bg: 'bg-orange-500/20', text: 'text-orange-400', icon: 'pause_circle' },
      completed: { bg: 'bg-gray-500/20', text: 'text-gray-400', icon: 'check_circle' },
      failed: { bg: 'bg-red-500/20', text: 'text-red-400', icon: 'error' },
      cancelled: { bg: 'bg-gray-600/20', text: 'text-gray-500', icon: 'cancel' }
    }
    const c = config[status] || config.completed
    return (
      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${c.bg} ${c.text}`}>
        <span className="material-icons text-sm">{c.icon}</span>
        {status.replace('_', ' ')}
      </span>
    )
  }

  const formatRelativeTime = (dateStr: string | null) => {
    if (!dateStr) return '-'
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    if (diffMins < 0) return 'in ' + Math.abs(diffMins) + 'm'
    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`
    return date.toLocaleDateString()
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
              {activeTab === 'research' ? 'Test multi-agent task orchestration' : 'Manage natural language automations'}
            </p>
          </div>
        </div>

        {/* Model selector - show for both tabs */}
        {(activeTab === 'research' || activeTab === 'automations') && (
          <div className="flex items-center gap-3">
            <div className="text-right">
              <label className="text-xs text-gray-500 block mb-1">Model</label>
              {modelsLoading ? (
                <div className="flex items-center gap-2 text-sm text-gray-400">
                  <div className="w-4 h-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin"></div>
                  Loading...
                </div>
              ) : modelsError ? (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-red-400">{modelsError}</span>
                  <button
                    onClick={fetchModels}
                    className="text-xs text-blue-400 hover:text-blue-300"
                  >
                    Retry
                  </button>
                </div>
              ) : (
                <select
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  disabled={state.status === 'running' || state.status === 'connecting'}
                  className="bg-gray-800 border border-gray-600 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:opacity-50 min-w-[200px]"
                >
                  {availableModels.map((model) => (
                    <option key={model.name} value={model.name}>
                      {model.name} ({model.size})
                    </option>
                  ))}
                </select>
              )}
            </div>
            <button
              onClick={fetchModels}
              className="p-2 hover:bg-gray-700 rounded-lg transition text-gray-400 hover:text-white"
              title="Refresh models"
            >
              <span className="material-icons text-lg">refresh</span>
            </button>
          </div>
        )}
      </div>

      {/* Tab Bar */}
      <div className="flex border-b border-gray-700 px-4">
        <button
          onClick={() => setActiveTab('research')}
          className={`px-4 py-3 text-sm font-medium transition-colors relative ${
            activeTab === 'research'
              ? 'text-teal-400'
              : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          <span className="flex items-center gap-2">
            <span className="material-icons text-lg">science</span>
            Research
          </span>
          {activeTab === 'research' && (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-teal-400" />
          )}
        </button>
        <button
          onClick={() => setActiveTab('automations')}
          className={`px-4 py-3 text-sm font-medium transition-colors relative ${
            activeTab === 'automations'
              ? 'text-green-400'
              : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          <span className="flex items-center gap-2">
            <span className="material-icons text-lg">auto_mode</span>
            Automations
            {automationTasks.filter(t => t.status === 'active').length > 0 && (
              <span className="ml-1 w-5 h-5 bg-green-500 rounded-full text-white text-xs font-bold flex items-center justify-center">
                {automationTasks.filter(t => t.status === 'active').length}
              </span>
            )}
          </span>
          {activeTab === 'automations' && (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-green-400" />
          )}
        </button>
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-hidden flex flex-col p-4 gap-4">
        {/* Research Tab Content */}
        {activeTab === 'research' && (
          <>
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
          </>
        )}

        {/* Automations Tab Content */}
        {activeTab === 'automations' && (
          <div className="flex-1 flex flex-col gap-4 min-h-0">
            {/* Test Automation Panel */}
            <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
              <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-2">
                <span className="material-icons text-lg text-purple-400">science</span>
                Test Automation (Dry Run)
              </h2>
              <div className="flex gap-3">
                <input
                  type="text"
                  value={testIntent}
                  onChange={(e) => setTestIntent(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && testAutomationIntent()}
                  placeholder="e.g., Turn on the heat for an hour every two hours"
                  className="flex-1 px-4 py-2.5 bg-gray-900 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent text-sm"
                  disabled={testLoading}
                />
                <button
                  onClick={testAutomationIntent}
                  disabled={!testIntent.trim() || testLoading}
                  className="px-5 py-2.5 bg-purple-600 text-white rounded-lg font-medium hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition flex items-center gap-2 text-sm"
                >
                  {testLoading ? (
                    <>
                      <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                      Parsing...
                    </>
                  ) : (
                    <>
                      <span className="material-icons text-sm">play_arrow</span>
                      Test
                    </>
                  )}
                </button>
              </div>

              {/* Test Error */}
              {testError && (
                <div className="mt-3 p-3 bg-red-900/20 border border-red-500/30 rounded-lg">
                  <div className="flex items-center gap-2 text-red-400">
                    <span className="material-icons text-sm">error</span>
                    <span className="font-medium text-sm">Error</span>
                  </div>
                  <p className="mt-1 text-sm text-gray-300">{testError}</p>
                </div>
              )}

              {/* Test Results */}
              {testResult && (
                <div className="mt-4 border-t border-gray-700 pt-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      {testResult.success ? (
                        <span className="flex items-center gap-1 text-green-400 text-sm">
                          <span className="material-icons text-sm">check_circle</span>
                          Valid
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-red-400 text-sm">
                          <span className="material-icons text-sm">error</span>
                          Invalid
                        </span>
                      )}
                      <span className="text-xs text-gray-500">
                        Confidence: {(testResult.parse_confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    <button
                      onClick={clearTestResult}
                      className="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1"
                    >
                      <span className="material-icons text-xs">close</span>
                      Clear
                    </button>
                  </div>

                  {/* Summary */}
                  <div className="bg-gray-900/50 rounded-lg p-3 mb-3">
                    <h4 className="text-sm font-medium text-white mb-1">{testResult.name}</h4>
                    <p className="text-sm text-gray-400">{testResult.description}</p>
                  </div>

                  {/* Human Readable Summary */}
                  <div className="bg-gray-900/50 rounded-lg p-3 mb-3">
                    <h4 className="text-xs font-medium text-gray-500 uppercase mb-2">What This Will Do</h4>
                    <pre className="text-sm text-gray-300 whitespace-pre-wrap font-sans">{testResult.human_readable_summary}</pre>
                  </div>

                  {/* Warnings */}
                  {testResult.warnings.length > 0 && (
                    <div className="bg-yellow-900/20 border border-yellow-500/30 rounded-lg p-3 mb-3">
                      <h4 className="text-xs font-medium text-yellow-400 uppercase mb-2 flex items-center gap-1">
                        <span className="material-icons text-xs">warning</span>
                        Warnings
                      </h4>
                      <ul className="text-sm text-gray-300 space-y-1">
                        {testResult.warnings.map((w, i) => (
                          <li key={i} className="flex items-start gap-2">
                            <span className="text-yellow-400">•</span>
                            {w}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Validation Errors */}
                  {testResult.validation_errors.length > 0 && (
                    <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-3 mb-3">
                      <h4 className="text-xs font-medium text-red-400 uppercase mb-2 flex items-center gap-1">
                        <span className="material-icons text-xs">error</span>
                        Validation Errors
                      </h4>
                      <ul className="text-sm text-gray-300 space-y-1">
                        {testResult.validation_errors.map((e, i) => (
                          <li key={i} className="flex items-start gap-2">
                            <span className="text-red-400">•</span>
                            {e}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Technical Details (collapsible) */}
                  <details className="mt-3">
                    <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-400">
                      Show technical details
                    </summary>
                    <div className="mt-2 space-y-2">
                      {/* Schedule */}
                      <div className="bg-gray-900/50 rounded p-2">
                        <h5 className="text-xs text-gray-500 uppercase mb-1">Schedule ({testResult.schedule_type})</h5>
                        <pre className="text-xs text-gray-400 overflow-x-auto">
                          {JSON.stringify(testResult.schedule_definition, null, 2)}
                        </pre>
                      </div>

                      {/* Actions */}
                      <div className="bg-gray-900/50 rounded p-2">
                        <h5 className="text-xs text-gray-500 uppercase mb-1">Actions ({testResult.actions.length})</h5>
                        <pre className="text-xs text-gray-400 overflow-x-auto max-h-48">
                          {JSON.stringify(testResult.actions, null, 2)}
                        </pre>
                      </div>

                      {/* Conditions */}
                      {testResult.conditions.length > 0 && (
                        <div className="bg-gray-900/50 rounded p-2">
                          <h5 className="text-xs text-gray-500 uppercase mb-1">Conditions ({testResult.conditions.length})</h5>
                          <pre className="text-xs text-gray-400 overflow-x-auto">
                            {JSON.stringify(testResult.conditions, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  </details>
                </div>
              )}
            </div>

            {/* Existing Automations Section */}
            <div className="flex-1 flex flex-col md:flex-row gap-4 min-h-0">
              {/* Task List */}
              <div className="w-full md:w-1/2 lg:w-2/5 flex flex-col min-h-0">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">
                    Your Automations
                  </h2>
                  <button
                    onClick={fetchAutomationTasks}
                    className="p-1.5 hover:bg-gray-700 rounded transition"
                    title="Refresh"
                  >
                    <span className="material-icons text-gray-400 text-sm">refresh</span>
                  </button>
                </div>

              <div className="flex-1 overflow-y-auto bg-gray-800/50 rounded-lg border border-gray-700">
                {automationTasks.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full py-12 text-center">
                    <span className="material-icons text-5xl text-gray-600 mb-3">auto_mode</span>
                    <p className="text-gray-400">No automations yet</p>
                    <p className="text-sm text-gray-500 mt-1 max-w-xs">
                      Ask Sara to create one, like "turn on the heat every 2 hours" or "alert me if the garage opens at night"
                    </p>
                  </div>
                ) : (
                  <div className="divide-y divide-gray-700/50">
                    {automationTasks.map((task) => (
                      <div
                        key={task.id}
                        onClick={() => {
                          setSelectedTask(task)
                          fetchExecutionLogs(task.id)
                        }}
                        className={`p-3 cursor-pointer transition ${
                          selectedTask?.id === task.id
                            ? 'bg-gray-700/50'
                            : 'hover:bg-gray-700/30'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-gray-200 truncate">
                              {task.name}
                            </p>
                            <p className="text-xs text-gray-500 mt-0.5 truncate">
                              {task.original_intent}
                            </p>
                          </div>
                          {getStatusBadge(task.status)}
                        </div>
                        <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
                          <span className="flex items-center gap-1">
                            <span className="material-icons text-xs">sync</span>
                            {task.execution_count} runs
                          </span>
                          {task.next_wake_at && task.status === 'active' && (
                            <span className="flex items-center gap-1 text-blue-400">
                              <span className="material-icons text-xs">schedule</span>
                              Next: {formatRelativeTime(task.next_wake_at)}
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Task Details Panel */}
            <div className="flex-1 flex flex-col min-h-0">
              {selectedTask ? (
                <>
                  <div className="flex items-center justify-between mb-3">
                    <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">
                      Task Details
                    </h2>
                    <button
                      onClick={() => setSelectedTask(null)}
                      className="p-1.5 hover:bg-gray-700 rounded transition md:hidden"
                    >
                      <span className="material-icons text-gray-400 text-sm">close</span>
                    </button>
                  </div>

                  <div className="flex-1 overflow-y-auto bg-gray-800/50 rounded-lg border border-gray-700 p-4">
                    {/* Task Header */}
                    <div className="flex items-start justify-between gap-3 mb-4">
                      <div>
                        <h3 className="text-lg font-semibold text-white">{selectedTask.name}</h3>
                        <p className="text-sm text-gray-400 mt-1">{selectedTask.original_intent}</p>
                      </div>
                      {getStatusBadge(selectedTask.status)}
                    </div>

                    {/* Quick Actions */}
                    <div className="flex gap-2 mb-4">
                      {selectedTask.status === 'active' && (
                        <button
                          onClick={() => handleAutomationAction(selectedTask.id, 'pause')}
                          className="px-3 py-1.5 bg-orange-600/20 text-orange-400 rounded-lg text-sm hover:bg-orange-600/30 transition flex items-center gap-1"
                        >
                          <span className="material-icons text-sm">pause</span>
                          Pause
                        </button>
                      )}
                      {(selectedTask.status === 'paused' || selectedTask.status === 'failed') && (
                        <button
                          onClick={() => handleAutomationAction(selectedTask.id, 'resume')}
                          className="px-3 py-1.5 bg-green-600/20 text-green-400 rounded-lg text-sm hover:bg-green-600/30 transition flex items-center gap-1"
                        >
                          <span className="material-icons text-sm">play_arrow</span>
                          Resume
                        </button>
                      )}
                      {selectedTask.status !== 'completed' && selectedTask.status !== 'cancelled' && (
                        <button
                          onClick={() => handleAutomationAction(selectedTask.id, 'cancel')}
                          className="px-3 py-1.5 bg-red-600/20 text-red-400 rounded-lg text-sm hover:bg-red-600/30 transition flex items-center gap-1"
                        >
                          <span className="material-icons text-sm">cancel</span>
                          Cancel
                        </button>
                      )}
                    </div>

                    {/* Stats */}
                    <div className="grid grid-cols-2 gap-4 mb-4">
                      <div className="bg-gray-700/30 rounded-lg p-3">
                        <p className="text-xs text-gray-500 uppercase">Executions</p>
                        <p className="text-xl font-semibold text-white mt-1">
                          {selectedTask.execution_count}
                          {selectedTask.max_executions && (
                            <span className="text-sm text-gray-400">/{selectedTask.max_executions}</span>
                          )}
                        </p>
                      </div>
                      <div className="bg-gray-700/30 rounded-lg p-3">
                        <p className="text-xs text-gray-500 uppercase">Schedule</p>
                        <p className="text-sm font-medium text-white mt-1 capitalize">
                          {selectedTask.schedule_type.replace('_', ' ')}
                        </p>
                      </div>
                    </div>

                    {/* Error Display */}
                    {selectedTask.last_error && (
                      <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-3 mb-4">
                        <p className="text-xs text-red-400 uppercase font-medium mb-1">Last Error</p>
                        <p className="text-sm text-gray-300">{selectedTask.last_error}</p>
                      </div>
                    )}

                    {/* Execution History */}
                    <div className="mt-4">
                      <h4 className="text-sm font-medium text-gray-400 mb-2">Execution History</h4>
                      {executionLogs.length === 0 ? (
                        <p className="text-sm text-gray-500">No executions yet</p>
                      ) : (
                        <div className="space-y-2">
                          {executionLogs.slice(0, 10).map((log) => (
                            <div
                              key={log.id}
                              className="flex items-start gap-2 p-2 bg-gray-700/30 rounded-lg text-sm"
                            >
                              <span className={`material-icons text-sm mt-0.5 ${
                                log.status === 'success' ? 'text-green-400' :
                                log.status === 'failed' ? 'text-red-400' :
                                'text-gray-400'
                              }`}>
                                {log.status === 'success' ? 'check_circle' :
                                 log.status === 'failed' ? 'error' : 'pending'}
                              </span>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="text-gray-300 font-medium">
                                    {log.action_primitive}
                                  </span>
                                  <span className="text-xs text-gray-500">
                                    Step {log.step_executed + 1}
                                  </span>
                                </div>
                                <p className="text-xs text-gray-500 mt-0.5">
                                  {formatRelativeTime(log.started_at)}
                                </p>
                                {log.error_message && (
                                  <p className="text-xs text-red-400 mt-1 truncate">
                                    {log.error_message}
                                  </p>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center bg-gray-800/50 rounded-lg border border-gray-700">
                  <div className="text-center text-gray-500">
                    <span className="material-icons text-4xl mb-2">touch_app</span>
                    <p>Select an automation to view details</p>
                  </div>
                </div>
              )}
            </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
