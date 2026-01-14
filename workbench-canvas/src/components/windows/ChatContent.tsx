import { useState, useRef, useEffect } from 'react'
import { MessageSquare, Send, Loader2, StopCircle, Wrench, Trash2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { chatApi, type ChatMessage, type StreamEvent } from '../../services/api'
import type { ChatWindowData } from '../../types'

interface ChatContentProps {
  data: ChatWindowData
  windowId: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  toolActivity?: { tool: string; status: 'running' | 'done'; result?: string }[]
}

export default function ChatContent({ data }: ChatContentProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [currentToolActivity, setCurrentToolActivity] = useState<{ tool: string; status: 'running' | 'done' }[]>([])
  const abortControllerRef = useRef<AbortController | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, currentToolActivity])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleSend = async () => {
    if (!input.trim() || isStreaming) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setIsStreaming(true)
    setCurrentToolActivity([])

    // Prepare messages for API
    const apiMessages: ChatMessage[] = [
      ...messages.map((m) => ({ role: m.role, content: m.content })),
      { role: 'user', content: userMessage.content },
    ]

    // Create abort controller
    abortControllerRef.current = new AbortController()

    // Create assistant message placeholder
    const assistantId = (Date.now() + 1).toString()
    setMessages((prev) => [
      ...prev,
      { id: assistantId, role: 'assistant', content: '' },
    ])

    try {
      await chatApi.sendMessage(
        apiMessages,
        (event: StreamEvent) => {
          switch (event.type) {
            case 'content':
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: m.content + (event.content || '') }
                    : m
                )
              )
              break

            case 'tool_start':
              setCurrentToolActivity((prev) => [
                ...prev,
                { tool: event.tool || 'unknown', status: 'running' },
              ])
              break

            case 'tool_end':
              setCurrentToolActivity((prev) =>
                prev.map((t) =>
                  t.tool === event.tool ? { ...t, status: 'done' } : t
                )
              )
              break

            case 'done':
              // Attach tool activity to the message
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, toolActivity: currentToolActivity }
                    : m
                )
              )
              break

            case 'error':
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: m.content + `\n\nError: ${event.error}` }
                    : m
                )
              )
              break
          }
        },
        abortControllerRef.current.signal
      )
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: m.content || 'Failed to get response. Please try again.' }
              : m
          )
        )
      }
    } finally {
      setIsStreaming(false)
      setCurrentToolActivity([])
      abortControllerRef.current = null
    }
  }

  const handleStop = () => {
    abortControllerRef.current?.abort()
  }

  const handleClear = () => {
    setMessages([])
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-full bg-canvas-bg">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-canvas-border">
        <div className="flex items-center gap-2">
          <MessageSquare size={18} className="text-teal-500" />
          <span className="font-medium text-white">Chat with Sara</span>
        </div>
        {messages.length > 0 && (
          <button
            onClick={handleClear}
            className="p-1.5 text-canvas-muted hover:text-red-400 hover:bg-canvas-surface rounded transition-colors"
            title="Clear chat"
          >
            <Trash2 size={16} />
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-canvas-muted py-12">
            <MessageSquare size={48} className="mx-auto mb-4 opacity-30" />
            <p className="text-lg">Start a conversation</p>
            <p className="text-sm mt-1">Ask Sara anything</p>
          </div>
        )}

        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {/* Tool activity during streaming */}
        {isStreaming && currentToolActivity.length > 0 && (
          <div className="flex flex-wrap gap-2 px-2">
            {currentToolActivity.map((activity, i) => (
              <div
                key={i}
                className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${
                  activity.status === 'running'
                    ? 'bg-yellow-500/20 text-yellow-400'
                    : 'bg-green-500/20 text-green-400'
                }`}
              >
                <Wrench size={12} />
                {activity.tool}
                {activity.status === 'running' && (
                  <Loader2 size={10} className="animate-spin" />
                )}
              </div>
            ))}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-canvas-border">
        <div className="flex gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message Sara..."
            rows={1}
            className="flex-1 px-4 py-2.5 bg-canvas-surface rounded-lg border border-canvas-border text-white placeholder-canvas-muted resize-none focus:outline-none focus:border-teal-500"
            disabled={isStreaming}
          />
          {isStreaming ? (
            <button
              onClick={handleStop}
              className="px-4 py-2 bg-red-500 hover:bg-red-600 rounded-lg transition-colors"
              title="Stop"
            >
              <StopCircle size={20} className="text-white" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="px-4 py-2 bg-teal-500 hover:bg-teal-600 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
              title="Send"
            >
              <Send size={20} className="text-white" />
            </button>
          )}
        </div>
        <div className="mt-2 text-xs text-canvas-muted text-center">
          Press Enter to send, Shift+Enter for new line
        </div>
      </div>
    </div>
  )
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 ${
          isUser
            ? 'bg-teal-600 text-white rounded-br-md'
            : 'bg-canvas-surface text-white rounded-bl-md'
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="markdown-content prose prose-invert prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content || '...'}
            </ReactMarkdown>
          </div>
        )}

        {/* Tool activity badges */}
        {message.toolActivity && message.toolActivity.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2 pt-2 border-t border-white/10">
            {message.toolActivity.map((activity, i) => (
              <div
                key={i}
                className="flex items-center gap-1 px-1.5 py-0.5 bg-white/10 rounded text-xs text-white/70"
              >
                <Wrench size={10} />
                {activity.tool}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
