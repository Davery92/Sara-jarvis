import { useEffect, useMemo, useRef, useState } from 'react'
import { BookOpen, ExternalLink, FileText, GraduationCap, Library, Loader2, RefreshCw, Send } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { APP_CONFIG } from '../../config'
import { getToken } from '../../services/api'
import { useCanvasStore } from '../../store/canvasStore'
import type { LearningWindowData } from '../../types'

interface LearningContentProps {
  data: LearningWindowData
  windowId: string
}

interface LearningTopic {
  id: string
  title: string
  description?: string | null
}

interface LearningArtifact {
  id: string
  topic_id: string | null
  artifact_type: string
  title?: string | null
  content: Record<string, unknown>
  created_at: string
  updated_at: string
}

interface LearningMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
}

type LearningTab = 'chat' | 'library'
type ScratchpadSaveState = 'idle' | 'saving' | 'saved' | 'error'

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function artifactTypeLabel(artifactType: string): string {
  if (artifactType === 'lesson') return 'Lesson'
  if (artifactType === 'study_guide_pareto') return 'Pareto Guide'
  if (artifactType === 'study_guide_deep') return 'Deep Guide'
  return artifactType.replace(/_/g, ' ')
}

function artifactMarkdown(artifact: LearningArtifact): string {
  const content = artifact.content as Record<string, any>
  return content?.lesson_markdown || content?.guide_markdown || ''
}

function artifactWordCount(artifact: LearningArtifact): number {
  const content = artifact.content as Record<string, any>
  const fromMeta = Number(content?.word_count || 0)
  if (fromMeta > 0) return fromMeta
  const markdown = artifactMarkdown(artifact)
  return markdown ? markdown.split(/\s+/).filter(Boolean).length : 0
}

export default function LearningContent({ data, windowId: _windowId }: LearningContentProps) {
  const { openWindow } = useCanvasStore()

  const [topics, setTopics] = useState<LearningTopic[]>([])
  const [topicsLoading, setTopicsLoading] = useState(true)
  const [topicsError, setTopicsError] = useState<string | null>(null)
  const [selectedTopicId, setSelectedTopicId] = useState<string | null>(data.topicId || null)

  const [activeTab, setActiveTab] = useState<LearningTab>(data.initialTab || 'chat')
  const [showScratchpad, setShowScratchpad] = useState(true)

  const [artifacts, setArtifacts] = useState<LearningArtifact[]>([])
  const [artifactsLoading, setArtifactsLoading] = useState(false)
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null)

  const [messages, setMessages] = useState<LearningMessage[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [scratchpadContent, setScratchpadContent] = useState('')
  const [scratchpadLoading, setScratchpadLoading] = useState(false)
  const [scratchpadSaveState, setScratchpadSaveState] = useState<ScratchpadSaveState>('idle')

  const abortControllerRef = useRef<AbortController | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scratchpadSaveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const scratchpadStatusTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastSavedScratchpadRef = useRef('')

  const selectedTopic = useMemo(
    () => topics.find((topic) => topic.id === selectedTopicId) || null,
    [topics, selectedTopicId]
  )

  const selectedArtifact = useMemo(
    () => artifacts.find((artifact) => artifact.id === selectedArtifactId) || null,
    [artifacts, selectedArtifactId]
  )

  const loadTopics = async () => {
    setTopicsLoading(true)
    setTopicsError(null)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/topics?include_all=true`, {
        credentials: 'include',
        headers: {
          ...authHeaders(),
        },
      })
      if (!response.ok) {
        throw new Error(`Failed to load topics (${response.status})`)
      }
      const data = await response.json()
      const rows = Array.isArray(data) ? (data as LearningTopic[]) : []
      setTopics(rows)
      if (!selectedTopicId && rows.length > 0) {
        setSelectedTopicId(rows[0].id)
      }
      if (selectedTopicId && rows.every((topic) => topic.id !== selectedTopicId)) {
        setSelectedTopicId(rows[0]?.id || null)
      }
    } catch (error: any) {
      setTopicsError(error?.message || 'Unable to load learning topics')
      setTopics([])
    } finally {
      setTopicsLoading(false)
    }
  }

  const loadArtifacts = async (topicId: string) => {
    setArtifactsLoading(true)
    try {
      const artifactTypes = ['lesson', 'study_guide_pareto', 'study_guide_deep']
      const results = await Promise.all(
        artifactTypes.map(async (artifactType) => {
          const response = await fetch(
            `${APP_CONFIG.apiUrl}/api/learn/artifacts?topic_id=${topicId}&artifact_type=${artifactType}`,
            {
              credentials: 'include',
              headers: {
                ...authHeaders(),
              },
            }
          )
          if (!response.ok) return []
          const payload = await response.json()
          return Array.isArray(payload) ? payload : []
        })
      )
      const flattened = results.flat()
      setArtifacts(flattened)
      if (flattened.length === 0) {
        setSelectedArtifactId(null)
      } else if (!selectedArtifactId || flattened.every((artifact) => artifact.id !== selectedArtifactId)) {
        setSelectedArtifactId(flattened[0].id)
      }
    } catch {
      setArtifacts([])
      setSelectedArtifactId(null)
    } finally {
      setArtifactsLoading(false)
    }
  }

  const loadScratchpad = async (topicId: string) => {
    setScratchpadLoading(true)
    setScratchpadSaveState('idle')
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/topics/${topicId}/scratchpad`, {
        credentials: 'include',
        headers: {
          ...authHeaders(),
        },
      })
      if (!response.ok) {
        throw new Error(`Failed to load scratchpad (${response.status})`)
      }
      const payload = await response.json()
      const content = payload?.content || ''
      lastSavedScratchpadRef.current = content
      setScratchpadContent(content)
    } catch {
      setScratchpadContent('')
      lastSavedScratchpadRef.current = ''
      setScratchpadSaveState('error')
    } finally {
      setScratchpadLoading(false)
    }
  }

  const saveScratchpad = async (topicId: string, content: string) => {
    if (content === lastSavedScratchpadRef.current) return
    setScratchpadSaveState('saving')
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/topics/${topicId}/scratchpad`, {
        method: 'PUT',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
        },
        body: JSON.stringify({ content }),
      })
      if (!response.ok) {
        throw new Error(`Failed to save scratchpad (${response.status})`)
      }
      lastSavedScratchpadRef.current = content
      setScratchpadSaveState('saved')
      if (scratchpadStatusTimeoutRef.current) clearTimeout(scratchpadStatusTimeoutRef.current)
      scratchpadStatusTimeoutRef.current = setTimeout(() => setScratchpadSaveState('idle'), 1200)
    } catch {
      setScratchpadSaveState('error')
    }
  }

  const handleScratchpadChange = (next: string) => {
    setScratchpadContent(next)
    const topicId = selectedTopicId
    if (!topicId) return
    if (scratchpadSaveTimeoutRef.current) clearTimeout(scratchpadSaveTimeoutRef.current)
    scratchpadSaveTimeoutRef.current = setTimeout(() => {
      saveScratchpad(topicId, next)
    }, 700)
  }

  const scratchpadStatusLabel = useMemo(() => {
    if (!selectedTopicId) return 'No topic selected'
    if (scratchpadLoading) return 'Loading...'
    if (scratchpadSaveState === 'saving') return 'Saving...'
    if (scratchpadSaveState === 'saved') return 'Saved'
    if (scratchpadSaveState === 'error') return 'Save failed'
    return 'Auto-save on'
  }, [scratchpadLoading, scratchpadSaveState, selectedTopicId])

  useEffect(() => {
    loadTopics()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!selectedTopicId) {
      setArtifacts([])
      setSelectedArtifactId(null)
      setScratchpadContent('')
      lastSavedScratchpadRef.current = ''
      return
    }
    if (scratchpadSaveTimeoutRef.current) {
      clearTimeout(scratchpadSaveTimeoutRef.current)
      scratchpadSaveTimeoutRef.current = null
    }
    if (scratchpadStatusTimeoutRef.current) {
      clearTimeout(scratchpadStatusTimeoutRef.current)
      scratchpadStatusTimeoutRef.current = null
    }
    loadArtifacts(selectedTopicId)
    loadScratchpad(selectedTopicId)
    setMessages([])
    setStreamingContent('')
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTopicId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [messages, streamingContent])

  useEffect(() => {
    return () => {
      if (scratchpadSaveTimeoutRef.current) clearTimeout(scratchpadSaveTimeoutRef.current)
      if (scratchpadStatusTimeoutRef.current) clearTimeout(scratchpadStatusTimeoutRef.current)
      if (abortControllerRef.current) abortControllerRef.current.abort()
    }
  }, [])

  const handleSend = async () => {
    const message = input.trim()
    if (!message || isStreaming || !selectedTopicId) return

    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    const abortController = new AbortController()
    abortControllerRef.current = abortController

    const userMessage: LearningMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: message,
    }

    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setIsStreaming(true)
    setStreamingContent('')

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/chat/stream`, {
        method: 'POST',
        credentials: 'include',
        signal: abortController.signal,
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
        },
        body: JSON.stringify({
          message,
          topic_id: selectedTopicId,
          context: {},
        }),
      })

      if (!response.ok) {
        throw new Error(`Chat request failed (${response.status})`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('No stream available')
      }

      const decoder = new TextDecoder()
      let buffer = ''
      let assembled = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))
            switch (event.type) {
              case 'text_chunk': {
                const chunk = event.content || event.data?.content || ''
                assembled += chunk
                setStreamingContent(assembled)
                break
              }
              case 'tool_executing': {
                const toolName = event.tool || 'tool'
                setStreamingContent((prev) => `${prev}\n\n*Using ${toolName}...*\n\n`)
                break
              }
              case 'final_response': {
                const finalContent = event.data?.content || assembled
                setMessages((prev) => [
                  ...prev,
                  { id: `assistant-${Date.now()}`, role: 'assistant', content: finalContent },
                ])
                setStreamingContent('')
                assembled = ''
                break
              }
              case 'error': {
                const msg = event.message || 'Learning chat error'
                setMessages((prev) => [
                  ...prev,
                  { id: `assistant-${Date.now()}`, role: 'assistant', content: `Error: ${msg}` },
                ])
                break
              }
              default:
                break
            }
          } catch {
            // Ignore malformed lines from incomplete stream chunks.
          }
        }
      }
    } catch (error: any) {
      if (error?.name !== 'AbortError') {
        setMessages((prev) => [
          ...prev,
          {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: 'I hit an error while generating a learning response. Please try again.',
          },
        ])
      }
    } finally {
      setIsStreaming(false)
      setStreamingContent('')
      abortControllerRef.current = null
    }
  }

  const openArtifactInDetachedWindow = (artifact: LearningArtifact) => {
    const markdown = artifactMarkdown(artifact)
    openWindow(
      'report',
      {
        title: artifact.title || artifactTypeLabel(artifact.artifact_type),
        content: markdown || '_No content available._',
      },
      {
        title: artifact.title || artifactTypeLabel(artifact.artifact_type),
        width: 900,
        height: 700,
      }
    )
  }

  const openDetachedLearningChat = () => {
    openWindow(
      'learning',
      {
        topicId: selectedTopicId || undefined,
        initialTab: 'chat',
      },
      {
        title: selectedTopic ? `Learning Chat · ${selectedTopic.title}` : 'Learning Chat',
        width: 700,
        height: 680,
      }
    )
  }

  const openDetachedScratchpad = () => {
    openWindow(
      'learning',
      {
        topicId: selectedTopicId || undefined,
        initialTab: activeTab,
      },
      {
        title: selectedTopic ? `Learning Notes · ${selectedTopic.title}` : 'Learning Notes',
        width: 840,
        height: 680,
      }
    )
  }

  return (
    <div className="flex flex-col h-full bg-canvas-bg">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-canvas-border bg-canvas-surface/70">
        <GraduationCap size={16} className="text-indigo-400" />
        <span className="text-sm text-white font-medium">Learning</span>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={loadTopics}
            className="p-1.5 rounded hover:bg-canvas-elevated text-canvas-muted hover:text-white transition-colors"
            title="Refresh topics"
          >
            <RefreshCw size={14} />
          </button>
          <button
            onClick={openDetachedLearningChat}
            disabled={!selectedTopicId}
            className="px-2.5 py-1.5 text-xs bg-canvas-elevated hover:bg-canvas-border disabled:opacity-40 rounded text-white transition-colors"
            title="Open this topic in another learning chat window"
          >
            Detached Chat
          </button>
          <button
            onClick={openDetachedScratchpad}
            disabled={!selectedTopicId}
            className="px-2.5 py-1.5 text-xs bg-canvas-elevated hover:bg-canvas-border disabled:opacity-40 rounded text-white transition-colors"
            title="Open this topic with scratchpad in a detached window"
          >
            Detached Notes
          </button>
          <button
            onClick={() => setShowScratchpad((prev) => !prev)}
            className={`px-2.5 py-1.5 text-xs rounded text-white transition-colors ${
              showScratchpad
                ? 'bg-indigo-600 hover:bg-indigo-700'
                : 'bg-canvas-elevated hover:bg-canvas-border'
            }`}
            title={showScratchpad ? 'Hide scratchpad' : 'Show scratchpad'}
          >
            Scratchpad
          </button>
        </div>
      </div>

      <div className="px-3 py-2 border-b border-canvas-border flex items-center gap-2">
        <label className="text-xs text-canvas-muted">Topic</label>
        <select
          value={selectedTopicId || ''}
          onChange={(event) => setSelectedTopicId(event.target.value || null)}
          className="flex-1 bg-canvas-surface border border-canvas-border rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-indigo-500"
          disabled={topicsLoading || topics.length === 0}
        >
          {topics.length === 0 ? (
            <option value="">No topics yet</option>
          ) : (
            topics.map((topic) => (
              <option key={topic.id} value={topic.id}>
                {topic.title}
              </option>
            ))
          )}
        </select>
      </div>

      {topicsLoading && (
        <div className="flex-1 flex items-center justify-center text-canvas-muted">
          <Loader2 size={18} className="animate-spin mr-2" />
          Loading learning topics...
        </div>
      )}

      {!topicsLoading && topicsError && (
        <div className="flex-1 flex items-center justify-center text-red-400 px-4 text-sm text-center">
          {topicsError}
        </div>
      )}

      {!topicsLoading && !topicsError && (
        <div className="flex-1 min-h-0 flex">
          <div className={`${showScratchpad ? 'flex-1' : 'w-full'} min-w-0 flex flex-col`}>
            <div className="flex border-b border-canvas-border">
              <button
                onClick={() => setActiveTab('chat')}
                className={`flex-1 px-3 py-2 text-sm font-medium transition-colors ${
                  activeTab === 'chat'
                    ? 'text-white bg-canvas-surface/60 border-b-2 border-indigo-500'
                    : 'text-canvas-muted hover:text-white hover:bg-canvas-surface/30'
                }`}
              >
                <span className="inline-flex items-center gap-1.5">
                  <BookOpen size={14} />
                  Chat
                </span>
              </button>
              <button
                onClick={() => setActiveTab('library')}
                className={`flex-1 px-3 py-2 text-sm font-medium transition-colors ${
                  activeTab === 'library'
                    ? 'text-white bg-canvas-surface/60 border-b-2 border-indigo-500'
                    : 'text-canvas-muted hover:text-white hover:bg-canvas-surface/30'
                }`}
              >
                <span className="inline-flex items-center gap-1.5">
                  <Library size={14} />
                  Guides & Lessons
                </span>
              </button>
            </div>

            {activeTab === 'chat' && (
              <div className="flex-1 flex flex-col min-h-0">
                <div className="flex-1 overflow-y-auto custom-scrollbar p-3 space-y-3">
                  {messages.length === 0 && !streamingContent && (
                    <div className="h-full flex items-center justify-center text-center px-6">
                      <div>
                        <GraduationCap size={34} className="mx-auto mb-3 text-indigo-400" />
                        <p className="text-sm text-white mb-1">
                          {selectedTopic ? `Start learning: ${selectedTopic.title}` : 'Select a topic to begin'}
                        </p>
                        <p className="text-xs text-canvas-muted">
                          Ask for explanations, drills, or comprehension checks.
                        </p>
                      </div>
                    </div>
                  )}

                  {messages.map((message) => (
                    <div key={message.id} className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                      <div
                        className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                          message.role === 'user'
                            ? 'bg-indigo-600 text-white'
                            : 'bg-canvas-surface border border-canvas-border text-gray-100'
                        }`}
                      >
                        {message.role === 'assistant' ? (
                          <div className="prose prose-invert prose-sm max-w-none">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                          </div>
                        ) : (
                          <p className="whitespace-pre-wrap">{message.content}</p>
                        )}
                      </div>
                    </div>
                  ))}

                  {streamingContent && (
                    <div className="flex justify-start">
                      <div className="max-w-[85%] rounded-lg px-3 py-2 text-sm bg-canvas-surface border border-canvas-border text-gray-100">
                        <div className="prose prose-invert prose-sm max-w-none">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamingContent}</ReactMarkdown>
                        </div>
                      </div>
                    </div>
                  )}

                  <div ref={messagesEndRef} />
                </div>

                <div className="p-3 border-t border-canvas-border">
                  <div className="flex gap-2">
                    <textarea
                      value={input}
                      onChange={(event) => setInput(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' && !event.shiftKey) {
                          event.preventDefault()
                          handleSend()
                        }
                      }}
                      rows={1}
                      placeholder={selectedTopic ? `Ask about ${selectedTopic.title}...` : 'Select a topic first'}
                      className="flex-1 resize-none bg-canvas-surface border border-canvas-border rounded px-3 py-2 text-sm text-white placeholder-canvas-muted focus:outline-none focus:border-indigo-500 disabled:opacity-50"
                      disabled={!selectedTopicId || isStreaming}
                    />
                    <button
                      onClick={handleSend}
                      disabled={!selectedTopicId || !input.trim() || isStreaming}
                      className="px-3 py-2 rounded bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white transition-colors"
                      title="Send"
                    >
                      {isStreaming ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                    </button>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'library' && (
              <div className="flex-1 min-h-0 flex">
                <div className="w-72 border-r border-canvas-border overflow-y-auto custom-scrollbar">
                  {artifactsLoading ? (
                    <div className="p-4 text-sm text-canvas-muted flex items-center">
                      <Loader2 size={14} className="animate-spin mr-2" />
                      Loading artifacts...
                    </div>
                  ) : artifacts.length === 0 ? (
                    <div className="p-4 text-sm text-canvas-muted">
                      No guides or lessons for this topic yet.
                    </div>
                  ) : (
                    <div className="p-2 space-y-2">
                      {artifacts.map((artifact) => (
                        <button
                          key={artifact.id}
                          onClick={() => setSelectedArtifactId(artifact.id)}
                          className={`w-full text-left p-2.5 rounded border transition-colors ${
                            selectedArtifactId === artifact.id
                              ? 'bg-canvas-elevated border-indigo-500'
                              : 'bg-canvas-surface border-canvas-border hover:border-indigo-500/50'
                          }`}
                        >
                          <div className="text-xs text-indigo-300 mb-1">{artifactTypeLabel(artifact.artifact_type)}</div>
                          <div className="text-sm text-white line-clamp-2">{artifact.title || 'Untitled'}</div>
                          <div className="text-[11px] text-canvas-muted mt-1">
                            {artifactWordCount(artifact).toLocaleString()} words
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                <div className="flex-1 min-w-0 flex flex-col">
                  {selectedArtifact ? (
                    <>
                      <div className="px-3 py-2 border-b border-canvas-border flex items-center gap-2">
                        <div className="min-w-0">
                          <div className="text-sm text-white font-medium truncate">
                            {selectedArtifact.title || artifactTypeLabel(selectedArtifact.artifact_type)}
                          </div>
                          <div className="text-xs text-canvas-muted">
                            {artifactTypeLabel(selectedArtifact.artifact_type)}
                          </div>
                        </div>
                        <button
                          onClick={() => openArtifactInDetachedWindow(selectedArtifact)}
                          className="ml-auto px-2.5 py-1.5 text-xs rounded bg-canvas-elevated hover:bg-canvas-border text-white transition-colors inline-flex items-center gap-1.5"
                          title="Open in a detached window"
                        >
                          <ExternalLink size={12} />
                          Open Detached
                        </button>
                      </div>
                      <div className="flex-1 overflow-y-auto custom-scrollbar p-3">
                        <div className="markdown-content prose prose-invert prose-sm max-w-none">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {artifactMarkdown(selectedArtifact) || '_No content available._'}
                          </ReactMarkdown>
                        </div>
                      </div>
                    </>
                  ) : (
                    <div className="flex-1 flex items-center justify-center text-canvas-muted text-sm">
                      Select a guide or lesson to read.
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {showScratchpad && (
            <div className="w-80 border-l border-canvas-border bg-canvas-surface/35 flex flex-col">
              <div className="px-3 py-2 border-b border-canvas-border flex items-center gap-2">
                <FileText size={14} className="text-indigo-300" />
                <span className="text-sm text-white font-medium">Topic Scratchpad</span>
                <span className={`ml-auto text-[11px] ${
                  scratchpadSaveState === 'error' ? 'text-red-400' : 'text-canvas-muted'
                }`}>
                  {scratchpadStatusLabel}
                </span>
              </div>
              {!selectedTopicId ? (
                <div className="flex-1 flex items-center justify-center px-4 text-sm text-canvas-muted text-center">
                  Select a topic to use the scratchpad.
                </div>
              ) : scratchpadLoading ? (
                <div className="flex-1 flex items-center justify-center text-canvas-muted text-sm">
                  <Loader2 size={14} className="animate-spin mr-2" />
                  Loading notes...
                </div>
              ) : (
                <>
                  <textarea
                    value={scratchpadContent}
                    onChange={(event) => handleScratchpadChange(event.target.value)}
                    placeholder="Capture key ideas, questions, and next steps for this topic..."
                    className="flex-1 w-full resize-none bg-transparent px-3 py-3 text-sm text-white placeholder-canvas-muted focus:outline-none"
                  />
                  <div className="px-3 py-2 border-t border-canvas-border text-[11px] text-canvas-muted">
                    {scratchpadContent.length.toLocaleString()} characters
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
