import { useState, useRef, useEffect, useCallback } from 'react'
import { Search, Send, Loader2, StopCircle, ChevronDown, Save, ExternalLink, ChevronRight, Zap, FileText, Users, Wrench } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useQuery } from '@tanstack/react-query'
import { chatApi, researchApi, type ChatModel, type ResearchSource, type ResearchEvent } from '../../services/api'
import { useCanvasStore } from '../../store/canvasStore'
import { APP_CONFIG } from '../../config'
import type { ResearchWindowData } from '../../types'

interface ResearchContentProps {
  data: ResearchWindowData
  windowId: string
}

interface SearchResult {
  query: string
  sources: ResearchSource[]
  summary: string
  savedNoteId?: string
}

type ResearchMode = 'simple' | 'deep'

interface WorkerActivity {
  id: string
  task: string
  status: 'pending' | 'running' | 'complete' | 'error'
  toolCalls: { tool: string; status: 'running' | 'done' }[]
  result?: string
}

interface DeepResearchState {
  phase: string
  workers: WorkerActivity[]
  finalReport?: string
}

export default function ResearchContent({ data }: ResearchContentProps) {
  const { openWindow } = useCanvasStore()
  const [query, setQuery] = useState(data.initialQuery || '')
  const [mode, setMode] = useState<ResearchMode>(data.mode || 'simple')
  const [isSearching, setIsSearching] = useState(false)
  const [selectedModel, setSelectedModel] = useState<string>('gpt-oss:120b')
  const [showModelDropdown, setShowModelDropdown] = useState(false)
  const [currentResult, setCurrentResult] = useState<SearchResult | null>(null)
  const [streamingContent, setStreamingContent] = useState('')
  const [sources, setSources] = useState<ResearchSource[]>([])
  const [showSources, setShowSources] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [searchHistory, setSearchHistory] = useState<SearchResult[]>([])

  // Deep research state
  const [deepState, setDeepState] = useState<DeepResearchState>({ phase: '', workers: [] })
  const [showActivityFeed, setShowActivityFeed] = useState(true)

  const abortControllerRef = useRef<AbortController | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const resultRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Fetch available models
  const { data: modelsData } = useQuery({
    queryKey: ['chat-models'],
    queryFn: chatApi.getModels,
    staleTime: 5 * 60 * 1000,
  })

  // Set default model when loaded
  useEffect(() => {
    if (modelsData?.default && selectedModel === 'gpt-oss:120b') {
      setSelectedModel(modelsData.default)
    }
  }, [modelsData])

  // Group models by provider
  const groupedModels = modelsData?.models?.reduce((acc, model) => {
    if (!acc[model.provider]) acc[model.provider] = []
    acc[model.provider].push(model)
    return acc
  }, {} as Record<string, ChatModel[]>) || {}

  // Auto-scroll to bottom on new content
  useEffect(() => {
    resultRef.current?.scrollTo({ top: resultRef.current.scrollHeight, behavior: 'smooth' })
  }, [streamingContent, deepState])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Cleanup WebSocket on unmount
  useEffect(() => {
    return () => {
      wsRef.current?.close()
    }
  }, [])

  // Simple search handler
  const handleSimpleSearch = async () => {
    setIsSearching(true)
    setStreamingContent('')
    setSources([])
    setCurrentResult(null)

    abortControllerRef.current = new AbortController()

    try {
      await researchApi.search(
        query.trim(),
        selectedModel,
        (event: ResearchEvent) => {
          switch (event.type) {
            case 'sources':
              if (Array.isArray(event.data)) {
                setSources(event.data as ResearchSource[])
              }
              break
            case 'content':
              if (typeof event.data === 'string') {
                setStreamingContent((prev) => prev + event.data)
              }
              break
            case 'done':
              setCurrentResult({
                query: query.trim(),
                sources: sources,
                summary: streamingContent,
              })
              break
            case 'error':
              const errorMsg = typeof event.data === 'object' && event.data && 'message' in event.data
                ? event.data.message
                : 'An error occurred'
              setStreamingContent((prev) => prev + `\n\nError: ${errorMsg}`)
              break
          }
        },
        abortControllerRef.current.signal
      )
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setStreamingContent('Failed to complete search. Please try again.')
      }
    } finally {
      setIsSearching(false)
      abortControllerRef.current = null
    }
  }

  // Deep research handler
  const handleDeepSearch = useCallback(() => {
    setIsSearching(true)
    setStreamingContent('')
    setSources([])
    setCurrentResult(null)
    setDeepState({ phase: 'connecting', workers: [] })

    // Build WebSocket URL
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const apiHost = new URL(APP_CONFIG.apiUrl).host
    const wsUrl = `${wsProtocol}//${apiHost}/api/orchestrator/stream`

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      console.log('[DeepResearch] WebSocket connected')
      ws.send(JSON.stringify({ query: query.trim() }))
      setDeepState((prev) => ({ ...prev, phase: 'decomposing' }))
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        console.log('[DeepResearch] Event:', data.phase, data)

        switch (data.phase) {
          case 'decomposing':
            setDeepState((prev) => ({ ...prev, phase: 'Analyzing task...' }))
            break

          case 'decomposed':
            // Create worker entries from subtasks
            const workers = (data.subtasks || []).map((task: string, i: number) => ({
              id: `worker-${i}`,
              task,
              status: 'pending' as const,
              toolCalls: [],
            }))
            setDeepState((prev) => ({ ...prev, phase: 'Researching...', workers }))
            break

          case 'worker_started':
            setDeepState((prev) => ({
              ...prev,
              workers: prev.workers.map((w) =>
                w.task === data.task ? { ...w, status: 'running' as const } : w
              ),
            }))
            break

          case 'worker_tool_call':
            setDeepState((prev) => ({
              ...prev,
              workers: prev.workers.map((w) =>
                w.task === data.task
                  ? { ...w, toolCalls: [...w.toolCalls, { tool: data.tool, status: 'running' as const }] }
                  : w
              ),
            }))
            break

          case 'worker_tool_result':
            setDeepState((prev) => ({
              ...prev,
              workers: prev.workers.map((w) =>
                w.task === data.task
                  ? {
                      ...w,
                      toolCalls: w.toolCalls.map((tc) =>
                        tc.tool === data.tool ? { ...tc, status: 'done' as const } : tc
                      ),
                    }
                  : w
              ),
            }))
            break

          case 'worker_complete':
            setDeepState((prev) => ({
              ...prev,
              workers: prev.workers.map((w) =>
                w.task === data.task ? { ...w, status: 'complete' as const, result: data.result } : w
              ),
            }))
            break

          case 'worker_error':
            setDeepState((prev) => ({
              ...prev,
              workers: prev.workers.map((w) =>
                w.task === data.task ? { ...w, status: 'error' as const } : w
              ),
            }))
            break

          case 'consolidating':
            setDeepState((prev) => ({ ...prev, phase: 'Synthesizing report...' }))
            break

          case 'complete':
            setDeepState((prev) => ({
              ...prev,
              phase: 'Complete',
              finalReport: data.report,
            }))
            setStreamingContent(data.report || '')
            setIsSearching(false)
            break

          case 'error':
            setDeepState((prev) => ({ ...prev, phase: `Error: ${data.message}` }))
            setStreamingContent(`Error: ${data.message}`)
            setIsSearching(false)
            break
        }
      } catch (e) {
        console.error('[DeepResearch] Parse error:', e)
      }
    }

    ws.onerror = (error) => {
      console.error('[DeepResearch] WebSocket error:', error)
      setDeepState((prev) => ({ ...prev, phase: 'Connection error' }))
      setIsSearching(false)
    }

    ws.onclose = () => {
      console.log('[DeepResearch] WebSocket closed')
      if (isSearching) {
        setIsSearching(false)
      }
    }
  }, [query, isSearching])

  const handleSearch = () => {
    if (!query.trim() || isSearching) return

    if (mode === 'simple') {
      handleSimpleSearch()
    } else {
      handleDeepSearch()
    }
  }

  const handleStop = () => {
    if (mode === 'simple') {
      abortControllerRef.current?.abort()
    } else {
      wsRef.current?.close()
    }
    setIsSearching(false)
  }

  const handleSave = async () => {
    if (!streamingContent || isSaving) return

    setIsSaving(true)
    try {
      const result = await researchApi.save(query, streamingContent, sources)
      setCurrentResult((prev) => prev ? { ...prev, savedNoteId: result.note_id } : null)
      setSearchHistory((prev) => [
        { query, sources, summary: streamingContent, savedNoteId: result.note_id },
        ...prev.slice(0, 9),
      ])
    } catch (err) {
      console.error('Failed to save research:', err)
    } finally {
      setIsSaving(false)
    }
  }

  // Detach research as a separate report window
  const handleDetach = () => {
    if (!streamingContent) return

    // Build content with sources if available
    let content = streamingContent
    if (sources.length > 0) {
      content += '\n\n---\n\n## Sources\n\n'
      sources.forEach((source, i) => {
        content += `${i + 1}. [${source.title || 'Untitled'}](${source.url})\n`
      })
    }

    // Truncate query for title
    const titleQuery = query.length > 40 ? query.slice(0, 40) + '...' : query
    const title = `Research: ${titleQuery}`

    // Open as a report window (read-only display)
    openWindow('report', {
      title,
      content,
    }, {
      title,
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSearch()
    }
  }

  const selectedModelName = modelsData?.models?.find((m) => m.id === selectedModel)?.name || selectedModel

  return (
    <div className="flex flex-col h-full bg-canvas-bg">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-canvas-border">
        <div className="flex items-center gap-3">
          <Search size={18} className="text-purple-500" />

          {/* Model Selector Dropdown */}
          <div className="relative">
            <button
              onClick={() => setShowModelDropdown(!showModelDropdown)}
              className="flex items-center gap-1.5 px-2 py-1 bg-canvas-surface hover:bg-canvas-elevated rounded text-sm text-white transition-colors"
            >
              <span className="max-w-[100px] truncate">{selectedModelName}</span>
              <ChevronDown
                size={14}
                className={`text-canvas-muted transition-transform ${showModelDropdown ? 'rotate-180' : ''}`}
              />
            </button>

            {showModelDropdown && (
              <div className="absolute top-full left-0 mt-1 w-48 bg-canvas-surface border border-canvas-border rounded-lg shadow-xl z-50 py-1 max-h-64 overflow-y-auto custom-scrollbar">
                {Object.entries(groupedModels).map(([provider, models]) => (
                  <div key={provider}>
                    <div className="px-3 py-1 text-xs text-canvas-muted uppercase tracking-wider">
                      {provider === 'anthropic' ? 'Claude' : provider === 'google' ? 'Gemini' : 'Local'}
                    </div>
                    {models.map((model) => (
                      <button
                        key={model.id}
                        onClick={() => {
                          setSelectedModel(model.id)
                          setShowModelDropdown(false)
                        }}
                        className={`w-full px-3 py-1.5 text-left text-sm hover:bg-canvas-elevated transition-colors ${
                          model.id === selectedModel ? 'text-purple-400 bg-canvas-elevated' : 'text-white'
                        }`}
                      >
                        {model.name}
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Mode Toggle */}
          <div className="flex items-center bg-canvas-surface rounded-lg p-0.5">
            <button
              onClick={() => setMode('simple')}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${
                mode === 'simple' ? 'bg-purple-500 text-white' : 'text-canvas-muted hover:text-white'
              }`}
              title="Quick search with AI summary"
            >
              <Zap size={12} />
              Simple
            </button>
            <button
              onClick={() => setMode('deep')}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${
                mode === 'deep' ? 'bg-purple-500 text-white' : 'text-canvas-muted hover:text-white'
              }`}
              title="Multi-agent deep research"
            >
              <Users size={12} />
              Deep
            </button>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-2">
          {/* Detach as Note */}
          {streamingContent && !isSearching && (
            <button
              onClick={handleDetach}
              className="flex items-center gap-1.5 px-2 py-1.5 rounded text-sm bg-canvas-surface hover:bg-canvas-elevated text-white transition-colors"
              title="Open as separate note"
            >
              <FileText size={14} />
            </button>
          )}

          {/* Save button */}
          {streamingContent && !isSearching && (
            <button
              onClick={handleSave}
              disabled={isSaving || currentResult?.savedNoteId !== undefined}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm transition-colors ${
                currentResult?.savedNoteId
                  ? 'bg-green-500/20 text-green-400'
                  : 'bg-canvas-surface hover:bg-canvas-elevated text-white'
              }`}
              title={currentResult?.savedNoteId ? 'Saved to Research folder' : 'Save to notes'}
            >
              {isSaving ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Save size={14} />
              )}
              {currentResult?.savedNoteId ? 'Saved' : 'Save'}
            </button>
          )}
        </div>
      </div>

      {/* Search Input */}
      <div className="p-4 border-b border-canvas-border">
        <div className="flex gap-2">
          <textarea
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={mode === 'simple' ? 'What would you like to research?' : 'Describe your research task...'}
            rows={2}
            className="flex-1 px-4 py-2.5 bg-canvas-surface rounded-lg border border-canvas-border text-white placeholder-canvas-muted resize-none focus:outline-none focus:border-purple-500"
            disabled={isSearching}
          />
          {isSearching ? (
            <button
              onClick={handleStop}
              className="px-4 py-2 bg-red-500 hover:bg-red-600 rounded-lg transition-colors self-end"
              title="Stop"
            >
              <StopCircle size={20} className="text-white" />
            </button>
          ) : (
            <button
              onClick={handleSearch}
              disabled={!query.trim()}
              className="px-4 py-2 bg-purple-500 hover:bg-purple-600 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors self-end"
              title={mode === 'simple' ? 'Search' : 'Start Research'}
            >
              <Send size={20} className="text-white" />
            </button>
          )}
        </div>
      </div>

      {/* Results Area */}
      <div ref={resultRef} className="flex-1 overflow-y-auto custom-scrollbar p-4">
        {/* Deep Mode: Activity Feed */}
        {mode === 'deep' && (isSearching || deepState.workers.length > 0) && (
          <div className="mb-4">
            <button
              onClick={() => setShowActivityFeed(!showActivityFeed)}
              className="flex items-center gap-2 text-sm text-canvas-muted hover:text-white transition-colors mb-2"
            >
              <ChevronRight
                size={16}
                className={`transition-transform ${showActivityFeed ? 'rotate-90' : ''}`}
              />
              Activity ({deepState.phase})
            </button>

            {showActivityFeed && (
              <div className="space-y-2">
                {deepState.workers.map((worker) => (
                  <div
                    key={worker.id}
                    className={`p-3 rounded-lg border ${
                      worker.status === 'running'
                        ? 'border-purple-500/50 bg-purple-500/10'
                        : worker.status === 'complete'
                        ? 'border-green-500/50 bg-green-500/10'
                        : worker.status === 'error'
                        ? 'border-red-500/50 bg-red-500/10'
                        : 'border-canvas-border bg-canvas-surface'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      {worker.status === 'running' ? (
                        <Loader2 size={14} className="animate-spin text-purple-400" />
                      ) : worker.status === 'complete' ? (
                        <div className="w-3.5 h-3.5 rounded-full bg-green-500" />
                      ) : worker.status === 'error' ? (
                        <div className="w-3.5 h-3.5 rounded-full bg-red-500" />
                      ) : (
                        <div className="w-3.5 h-3.5 rounded-full bg-canvas-muted" />
                      )}
                      <span className="text-sm text-white font-medium truncate">{worker.task}</span>
                    </div>

                    {/* Tool calls */}
                    {worker.toolCalls.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-2">
                        {worker.toolCalls.map((tc, i) => (
                          <div
                            key={i}
                            className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-xs ${
                              tc.status === 'running'
                                ? 'bg-yellow-500/20 text-yellow-400'
                                : 'bg-green-500/20 text-green-400'
                            }`}
                          >
                            <Wrench size={10} />
                            {tc.tool}
                            {tc.status === 'running' && (
                              <Loader2 size={10} className="animate-spin" />
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Simple Mode: Sources Section */}
        {mode === 'simple' && sources.length > 0 && (
          <div className="mb-4">
            <button
              onClick={() => setShowSources(!showSources)}
              className="flex items-center gap-2 text-sm text-canvas-muted hover:text-white transition-colors mb-2"
            >
              <ChevronRight
                size={16}
                className={`transition-transform ${showSources ? 'rotate-90' : ''}`}
              />
              Sources ({sources.length})
            </button>

            {showSources && (
              <div className="grid gap-2">
                {sources.map((source, i) => (
                  <a
                    key={i}
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-start gap-2 p-2 bg-canvas-surface rounded-lg hover:bg-canvas-elevated transition-colors group"
                  >
                    <span className="text-purple-400 text-xs font-mono">[{i + 1}]</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1">
                        <span className="text-white text-sm truncate">{source.title || 'Untitled'}</span>
                        <ExternalLink size={12} className="text-canvas-muted opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
                      </div>
                      {source.snippet && (
                        <p className="text-canvas-muted text-xs line-clamp-2 mt-0.5">{source.snippet}</p>
                      )}
                    </div>
                  </a>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Summary Content */}
        {(streamingContent || (isSearching && mode === 'simple')) && (
          <div className="markdown-content prose prose-invert prose-sm max-w-none">
            {isSearching && !streamingContent && mode === 'simple' && (
              <div className="flex items-center gap-2 text-canvas-muted">
                <Loader2 size={16} className="animate-spin" />
                Searching and analyzing...
              </div>
            )}
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamingContent || ''}</ReactMarkdown>
            {isSearching && streamingContent && (
              <span className="inline-block w-2 h-4 bg-purple-500 animate-pulse ml-1" />
            )}
          </div>
        )}

        {/* Empty State */}
        {!streamingContent && !isSearching && deepState.workers.length === 0 && (
          <div className="text-center text-canvas-muted py-12">
            <Search size={48} className="mx-auto mb-4 opacity-30" />
            <p className="text-lg">Web Research</p>
            <p className="text-sm mt-1">
              {mode === 'simple'
                ? 'Quick search with AI-powered summary'
                : 'Multi-agent deep research with live activity'}
            </p>
          </div>
        )}
      </div>

      {/* Search History */}
      {searchHistory.length > 0 && !streamingContent && deepState.workers.length === 0 && (
        <div className="border-t border-canvas-border p-3">
          <div className="text-xs text-canvas-muted mb-2">Recent Searches</div>
          <div className="flex flex-wrap gap-2">
            {searchHistory.slice(0, 5).map((item, i) => (
              <button
                key={i}
                onClick={() => setQuery(item.query)}
                className="px-2 py-1 bg-canvas-surface hover:bg-canvas-elevated rounded text-xs text-white truncate max-w-[150px] transition-colors"
                title={item.query}
              >
                {item.query}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
