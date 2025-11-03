import React, { useState, useRef, useEffect } from 'react'
import { Send, Loader2, MessageCircle } from 'lucide-react'
import { APP_CONFIG } from '../../config'
import MarkdownRenderer from '../MarkdownRenderer'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

export default function FitnessChat() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content: 'Hi! I\'m Sara, your fitness expert. I can help you with nutrition advice, workout planning, form tips, and tracking your fitness goals. How can I assist you today?',
      timestamp: new Date()
    }
  ])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return

    const userMessage: Message = {
      role: 'user',
      content: input.trim(),
      timestamp: new Date()
    }

    setMessages(prev => [...prev, userMessage])
    const userInput = input.trim()
    setInput('')
    setIsLoading(true)

    // Add placeholder assistant message for streaming
    const assistantMessageId = Date.now()
    const assistantMessage: Message = {
      role: 'assistant',
      content: '',
      timestamp: new Date()
    }
    setMessages(prev => [...prev, assistantMessage])

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ message: userInput })
      })

      if (!response.ok) {
        throw new Error('Chat request failed')
      }

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()

      if (!reader) {
        throw new Error('No reader available')
      }

      let streamedContent = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split('\n')

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            if (data === '[DONE]') continue

            try {
              const event = JSON.parse(data)

              if (event.type === 'text_chunk') {
                // Use full_content if available, otherwise append content
                streamedContent = event.data.full_content || (streamedContent + (event.data.content || ''))
                // Update the assistant message with streaming content
                setMessages(prev => prev.map((msg, idx) =>
                  idx === prev.length - 1 && msg.role === 'assistant'
                    ? { ...msg, content: streamedContent }
                    : msg
                ))
              } else if (event.type === 'tool_executing' || event.type === 'tool_calls_start') {
                // Optionally show tool usage
                console.log('Tool executing:', event.data)
              } else if (event.type === 'final_response') {
                // Update with final cleaned response
                setMessages(prev => prev.map((msg, idx) =>
                  idx === prev.length - 1 && msg.role === 'assistant'
                    ? { ...msg, content: event.data.content }
                    : msg
                ))
                streamedContent = event.data.content
              }
            } catch (parseError) {
              console.warn('Failed to parse SSE data:', data)
            }
          }
        }
      }
    } catch (error) {
      console.error('Chat error:', error)
      // Update the last message with error
      setMessages(prev => prev.map((msg, idx) =>
        idx === prev.length - 1 && msg.role === 'assistant'
          ? { ...msg, content: 'Sorry, I encountered an error. Please try again.' }
          : msg
      ))
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <div className="h-full flex flex-col bg-gray-900">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {messages.map((message, idx) => (
          <div
            key={idx}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] rounded-lg p-4 ${
                message.role === 'user'
                  ? 'bg-green-600 text-white'
                  : 'bg-gray-800 text-gray-100'
              }`}
            >
              {message.role === 'assistant' && (
                <div className="flex items-center gap-2 mb-2 text-green-400">
                  <MessageCircle className="w-4 h-4" />
                  <span className="text-sm font-semibold">Sara - Fitness Expert</span>
                </div>
              )}
              {message.role === 'assistant' ? (
                <MarkdownRenderer content={message.content} className="text-gray-100" />
              ) : (
                <div className="whitespace-pre-wrap">{message.content}</div>
              )}
              <div className="text-xs opacity-60 mt-2">
                {message.timestamp.toLocaleTimeString()}
              </div>
            </div>
          </div>
        ))}
        {isLoading && messages.length > 0 && messages[messages.length - 1].role === 'assistant' && !messages[messages.length - 1].content && (
          <div className="flex justify-start">
            <div className="bg-gray-800 text-gray-100 rounded-lg p-4">
              <div className="flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Sara is thinking...</span>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-gray-700 bg-gray-800 p-4">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask Sara about fitness, nutrition, or workouts..."
            className="flex-1 px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-green-500 resize-none"
            rows={1}
            style={{
              minHeight: '44px',
              maxHeight: '200px',
              height: 'auto'
            }}
            onInput={(e) => {
              const target = e.target as HTMLTextAreaElement
              target.style.height = 'auto'
              target.style.height = `${Math.min(target.scrollHeight, 200)}px`
            }}
          />
          <button
            type="submit"
            disabled={!input.trim() || isLoading}
            className="px-6 py-3 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg text-white font-medium transition-colors flex items-center gap-2"
          >
            <Send className="w-4 h-4" />
            Send
          </button>
        </form>
        <div className="text-xs text-gray-400 mt-2">
          Press Enter to send, Shift+Enter for new line
        </div>
      </div>
    </div>
  )
}
