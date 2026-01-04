import React, { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { APP_CONFIG } from '../config'

interface HealthAlert {
  severity: string
  title: string
  body: string
  insightId?: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
}

interface HealthAlertChatProps {
  alert: HealthAlert
  onClose: () => void
}

export const HealthAlertChat: React.FC<HealthAlertChatProps> = ({ alert, onClose }) => {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [isMinimized, setIsMinimized] = useState(false)
  const hasStartedRef = useRef(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent])

  // Focus input when opened
  useEffect(() => {
    if (!isMinimized && inputRef.current) {
      inputRef.current.focus()
    }
  }, [isMinimized])

  // Auto-start conversation when component mounts
  // Using ref instead of state to prevent double-execution in React 18 StrictMode
  useEffect(() => {
    if (!hasStartedRef.current) {
      hasStartedRef.current = true
      startConversation()
    }
  }, [])

  const startConversation = async () => {
    // Send initial message asking Sara to explain the alert
    const initialMessage = `You just sent me a health alert: "${alert.title}". ${alert.body} - Can you explain what you noticed and what I should do about it?`
    await sendMessage(initialMessage, true)
  }

  const sendMessage = async (content: string, isInitial = false) => {
    if (!content.trim()) return

    // Add user message (hidden if it's the initial auto-message)
    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: content
    }

    if (!isInitial) {
      setMessages(prev => [...prev, userMessage])
    }
    setInput('')
    setIsStreaming(true)
    setStreamingContent('')

    try {
      // Build conversation for API
      const conversationMessages = isInitial
        ? [{ role: 'user', content }]
        : [...messages, userMessage].map(m => ({ role: m.role, content: m.content }))

      const response = await fetch(`${APP_CONFIG.apiUrl}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          messages: conversationMessages,
          context: isInitial ? `Health alert context: severity=${alert.severity}, insight_id=${alert.insightId}` : undefined
        })
      })

      if (!response.ok) throw new Error('Chat request failed')

      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let fullContent = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value)
        const lines = chunk.split('\n')

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            if (data === '[DONE]') continue

            try {
              const parsed = JSON.parse(data)
              // Handle different event types from streaming API
              if (parsed.type === 'text_chunk' && parsed.data?.content) {
                // Streaming text chunk
                fullContent += parsed.data.content
                setStreamingContent(fullContent)
              } else if (parsed.type === 'final_response' && parsed.data?.content) {
                // Final response - use this as the complete content
                fullContent = parsed.data.content
                setStreamingContent(fullContent)
              } else if (parsed.content) {
                // Legacy format support
                fullContent += parsed.content
                setStreamingContent(fullContent)
              }
              // Ignore heartbeat, done, error events
            } catch {
              // Non-JSON data, might be raw content
              if (data && data !== '[DONE]') {
                fullContent += data
                setStreamingContent(fullContent)
              }
            }
          }
        }
      }

      // Add assistant message
      const assistantMessage: Message = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: fullContent
      }
      setMessages(prev => [...prev, assistantMessage])

    } catch (error) {
      console.error('Health chat error:', error)
      const errorMessage: Message = {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: 'Sorry, I had trouble responding. Please try again.'
      }
      setMessages(prev => [...prev, errorMessage])
    } finally {
      setIsStreaming(false)
      setStreamingContent('')
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    sendMessage(input)
  }

  const severityColor = {
    urgent: 'red',
    warning: 'orange',
    caution: 'yellow',
    info: 'blue'
  }[alert.severity] || 'orange'

  // Minimized state
  if (isMinimized) {
    return (
      <button
        onClick={() => setIsMinimized(false)}
        className={`fixed bottom-20 right-4 md:bottom-4 z-50 p-3 bg-${severityColor}-500 rounded-full shadow-lg hover:bg-${severityColor}-400 transition-colors`}
        title="Health Alert Discussion"
      >
        <span className="material-icons text-white text-xl">favorite</span>
        <span className="absolute -top-1 -right-1 w-3 h-3 bg-red-500 rounded-full animate-ping" />
      </button>
    )
  }

  return (
    <div className="fixed bottom-20 right-4 md:bottom-4 z-50 w-96 h-[500px] max-h-[70vh] bg-gray-800 rounded-lg shadow-xl border border-orange-500/50 flex flex-col overflow-hidden">
      {/* Header */}
      <div className={`bg-${severityColor}-500/20 px-4 py-3 border-b border-${severityColor}-500/30 flex-shrink-0`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={`material-icons text-${severityColor}-400 text-lg`}>favorite</span>
            <div>
              <h3 className={`text-sm font-semibold text-${severityColor}-300`}>Health Alert</h3>
              <p className="text-xs text-gray-400 truncate max-w-[200px]">{alert.title}</p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setIsMinimized(true)}
              className="p-1 hover:bg-white/10 rounded text-gray-400 hover:text-white"
              title="Minimize"
            >
              <span className="material-icons text-sm">remove</span>
            </button>
            <button
              onClick={onClose}
              className="p-1 hover:bg-white/10 rounded text-gray-400 hover:text-white"
              title="Close"
            >
              <span className="material-icons text-sm">close</span>
            </button>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-200'
              }`}
            >
              {msg.role === 'assistant' ? (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    p: ({children}) => <p className="mb-2 last:mb-0">{children}</p>,
                    ul: ({children}) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
                    ol: ({children}) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
                    li: ({children}) => <li className="ml-2">{children}</li>,
                    strong: ({children}) => <strong className="font-semibold text-white">{children}</strong>,
                    em: ({children}) => <em className="italic">{children}</em>,
                    code: ({children}) => <code className="bg-gray-600 px-1 py-0.5 rounded text-xs">{children}</code>,
                    a: ({href, children}) => (
                      <a href={href} className="text-orange-400 hover:text-orange-300 underline" target="_blank" rel="noopener noreferrer">
                        {children}
                      </a>
                    ),
                    blockquote: ({children}) => (
                      <blockquote className="border-l-2 border-orange-500 pl-2 italic my-2 text-gray-300">
                        {children}
                      </blockquote>
                    ),
                    h1: ({children}) => <h1 className="text-base font-bold mb-1">{children}</h1>,
                    h2: ({children}) => <h2 className="text-sm font-bold mb-1">{children}</h2>,
                    h3: ({children}) => <h3 className="text-sm font-semibold mb-1">{children}</h3>,
                  }}
                >
                  {msg.content}
                </ReactMarkdown>
              ) : (
                msg.content
              )}
            </div>
          </div>
        ))}

        {isStreaming && streamingContent && (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-lg px-3 py-2 text-sm bg-gray-700 text-gray-200">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  p: ({children}) => <p className="mb-2 last:mb-0">{children}</p>,
                  ul: ({children}) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
                  ol: ({children}) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
                  li: ({children}) => <li className="ml-2">{children}</li>,
                  strong: ({children}) => <strong className="font-semibold text-white">{children}</strong>,
                  em: ({children}) => <em className="italic">{children}</em>,
                  code: ({children}) => <code className="bg-gray-600 px-1 py-0.5 rounded text-xs">{children}</code>,
                  a: ({href, children}) => (
                    <a href={href} className="text-orange-400 hover:text-orange-300 underline" target="_blank" rel="noopener noreferrer">
                      {children}
                    </a>
                  ),
                }}
              >
                {streamingContent}
              </ReactMarkdown>
              <span className="inline-block w-2 h-4 ml-1 bg-gray-400 animate-pulse" />
            </div>
          </div>
        )}

        {isStreaming && !streamingContent && (
          <div className="flex justify-start">
            <div className="bg-gray-700 rounded-lg px-3 py-2">
              <div className="flex gap-1">
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-3 border-t border-gray-700 flex-shrink-0">
        <div className="flex gap-2">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about this alert..."
            disabled={isStreaming}
            className="flex-1 px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm text-white placeholder-gray-400 focus:outline-none focus:border-orange-500"
          />
          <button
            type="submit"
            disabled={!input.trim() || isStreaming}
            className="px-4 py-2 bg-orange-500 hover:bg-orange-400 disabled:bg-gray-600 disabled:text-gray-400 text-white rounded-lg transition-colors"
          >
            <span className="material-icons text-sm">send</span>
          </button>
        </div>
      </form>
    </div>
  )
}

export default HealthAlertChat
