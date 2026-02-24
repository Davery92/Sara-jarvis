import React, { useState, useRef, useEffect } from 'react'
import { APP_CONFIG } from '../../config'
import MarkdownRenderer from '../MarkdownRenderer'

interface LearningChatProps {
  topicId: string | null
  topicTitle?: string
}

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

export default function LearningChat({ topicId, topicTitle }: LearningChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Reset chat when topic changes
  useEffect(() => {
    setMessages([])
    setStreamingContent('')
  }, [topicId])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const message = inputValue.trim()
    if (!message || isStreaming) return

    // Cancel any existing request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    abortControllerRef.current = new AbortController()

    // Add user message
    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: message,
      timestamp: new Date()
    }
    setMessages(prev => [...prev, userMessage])
    setInputValue('')
    setIsStreaming(true)
    setStreamingContent('')

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        signal: abortControllerRef.current.signal,
        body: JSON.stringify({
          message,
          topic_id: topicId,
          context: {}
        })
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      let accumulatedContent = ''

      if (reader) {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          const chunk = decoder.decode(value, { stream: true })
          const lines = chunk.split('\n')

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const eventData = JSON.parse(line.slice(6))

                switch (eventData.type) {
                  case 'text_chunk':
                    accumulatedContent += eventData.content || eventData.data?.content || ''
                    setStreamingContent(accumulatedContent)
                    break

                  case 'final_response':
                    const finalContent = eventData.data?.content || accumulatedContent
                    setMessages(prev => [...prev, {
                      id: Date.now().toString(),
                      role: 'assistant',
                      content: finalContent,
                      timestamp: new Date()
                    }])
                    setStreamingContent('')
                    break

                  case 'tool_executing':
                    // Show tool execution in streaming content
                    setStreamingContent(prev => prev + `\n\n*Using ${eventData.tool || 'tool'}...*\n\n`)
                    break

                  case 'error':
                    console.error('Stream error:', eventData.message)
                    break

                  case 'heartbeat':
                    // Ignore heartbeats
                    break
                }
              } catch (parseError) {
                // Ignore parse errors for incomplete JSON
              }
            }
          }
        }
      }
    } catch (error: unknown) {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('Request aborted')
      } else {
        console.error('Chat error:', error)
        setMessages(prev => [...prev, {
          id: Date.now().toString(),
          role: 'assistant',
          content: 'Sorry, I encountered an error. Please try again.',
          timestamp: new Date()
        }])
      }
    } finally {
      setIsStreaming(false)
      setStreamingContent('')
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <div className="flex flex-col h-full bg-gray-900">
      {/* Welcome Message if no messages */}
      {messages.length === 0 && !streamingContent && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="text-center max-w-md">
            <span className="material-icons text-5xl text-teal-400 mb-4">psychology</span>
            <h3 className="text-xl font-semibold text-white mb-2">
              {topicTitle ? `Learning: ${topicTitle}` : 'Ready to Learn'}
            </h3>
            <p className="text-gray-400 mb-4">
              {topicTitle
                ? "I'm here as your Socratic tutor. Ask me questions, explain your understanding, or let's explore concepts together."
                : 'Select a topic from the sidebar to start learning, or create a new one.'
              }
            </p>
            <div className="text-sm text-gray-500 space-y-1">
              <p>Try asking:</p>
              <p className="text-teal-400">"What should I understand first?"</p>
              <p className="text-teal-400">"Can you explain this concept?"</p>
              <p className="text-teal-400">"Test my understanding"</p>
            </div>
          </div>
        </div>
      )}

      {/* Messages */}
      {(messages.length > 0 || streamingContent) && (
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.map(message => (
            <div
              key={message.id}
              className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[80%] rounded-xl px-4 py-3 ${
                  message.role === 'user'
                    ? 'bg-teal-600 text-white'
                    : 'bg-gray-800 text-gray-100'
                }`}
              >
                {message.role === 'assistant' ? (
                  <MarkdownRenderer
                    content={message.content}
                    className="prose prose-invert prose-sm max-w-none"
                  />
                ) : (
                  <p className="whitespace-pre-wrap">{message.content}</p>
                )}
              </div>
            </div>
          ))}

          {/* Streaming Message */}
          {streamingContent && (
            <div className="flex justify-start">
              <div className="max-w-[80%] rounded-xl px-4 py-3 bg-gray-800 text-gray-100">
                <MarkdownRenderer
                  content={streamingContent}
                  className="prose prose-invert prose-sm max-w-none"
                />
                <span className="inline-block w-2 h-4 bg-teal-400 animate-pulse ml-1" />
              </div>
            </div>
          )}

          {/* Typing Indicator */}
          {isStreaming && !streamingContent && (
            <div className="flex justify-start">
              <div className="bg-gray-800 rounded-xl px-4 py-3">
                <div className="flex gap-1">
                  <span className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      )}

      {/* Input Area */}
      <div className="border-t border-gray-700 p-4">
        <form onSubmit={handleSubmit} className="flex gap-3">
          <textarea
            ref={inputRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={topicTitle ? `Ask about ${topicTitle}...` : 'Select a topic to start learning...'}
            disabled={isStreaming}
            className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-white placeholder-gray-500 resize-none focus:outline-none focus:border-teal-500 disabled:opacity-50"
            rows={1}
            style={{ minHeight: '48px', maxHeight: '120px' }}
          />
          <button
            type="submit"
            disabled={!inputValue.trim() || isStreaming}
            className="bg-teal-600 hover:bg-teal-700 disabled:bg-gray-700 disabled:text-gray-500 text-white px-6 py-3 rounded-xl transition-colors"
          >
            <span className="material-icons">send</span>
          </button>
        </form>
      </div>
    </div>
  )
}
