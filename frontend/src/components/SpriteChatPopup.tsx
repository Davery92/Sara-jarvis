import React, { useState, useRef, useEffect } from 'react'
import { X, Dumbbell, MessageCircle } from 'lucide-react'
import { APP_CONFIG } from '../config'
import { spriteBus } from '../state/spriteBus'
import MarkdownRenderer from './MarkdownRenderer'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

interface SpriteChatPopupProps {
  open: boolean
  onClose: () => void
}

export default function SpriteChatPopup({ open, onClose }: SpriteChatPopupProps) {
  const [mode, setMode] = useState<'sara' | 'fitness'>('sara')
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  // Initialize with appropriate greeting based on mode
  useEffect(() => {
    if (open && messages.length === 0) {
      const greeting: Message = {
        role: 'assistant',
        content: mode === 'sara'
          ? `Hello! I'm ${APP_CONFIG.assistantName}, your personal AI assistant. How can I help you today?`
          : 'Hi! I\'m Sara, your fitness expert. I can help you with nutrition advice, workout planning, form tips, and tracking your fitness goals. How can I assist you today?',
        timestamp: new Date()
      }
      setMessages([greeting])
    }
  }, [open, mode])

  // Reset messages when mode changes
  useEffect(() => {
    const greeting: Message = {
      role: 'assistant',
      content: mode === 'sara'
        ? `Hello! I'm ${APP_CONFIG.assistantName}, your personal AI assistant. How can I help you today?`
        : 'Hi! I\'m Sara, your fitness expert. I can help you with nutrition advice, workout planning, form tips, and tracking your fitness goals. How can I assist you today?',
      timestamp: new Date()
    }
    setMessages([greeting])
  }, [mode])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Focus input when popup opens
  useEffect(() => {
    if (open) {
      setTimeout(() => textareaRef.current?.focus(), 100)
    }
  }, [open])

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

    // Cancel any existing request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    abortControllerRef.current = new AbortController()

    // Update sprite state
    spriteBus.setBase('listening', 'spriteChatPopup:send')
    spriteBus.setTone('focused', 'spriteChatPopup:send')

    // Add placeholder assistant message for streaming
    const assistantMessage: Message = {
      role: 'assistant',
      content: '',
      timestamp: new Date()
    }
    setMessages(prev => [...prev, assistantMessage])

    try {
      const endpoint = mode === 'fitness'
        ? `${APP_CONFIG.apiUrl}/api/fitness/chat/stream`
        : `${APP_CONFIG.apiUrl}/chat/stream`

      const body = mode === 'fitness'
        ? { message: userInput }
        : {
            messages: [...messages, userMessage].map(m => ({
              role: m.role,
              content: m.content
            }))
          }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        signal: abortControllerRef.current.signal,
        body: JSON.stringify(body)
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
      let sseBuffer = ''
      let firstChunk = true

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value, { stream: true })

        if (mode === 'fitness') {
          // Fitness chat uses simpler SSE format
          const lines = chunk.split('\n')
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const data = line.slice(6)
              if (data === '[DONE]') continue

              try {
                const event = JSON.parse(data)
                if (event.type === 'text_chunk') {
                  streamedContent = event.data.full_content || (streamedContent + (event.data.content || ''))

                  if (firstChunk) {
                    spriteBus.setOverlay('speaking', { source: 'spriteChatPopup:first_chunk', autoClearMs: 900 })
                    spriteBus.setTone('playful', 'spriteChatPopup:first_chunk')
                    firstChunk = false
                  }

                  setMessages(prev => prev.map((msg, idx) =>
                    idx === prev.length - 1 && msg.role === 'assistant'
                      ? { ...msg, content: streamedContent }
                      : msg
                  ))
                } else if (event.type === 'final_response') {
                  streamedContent = event.data.content
                  setMessages(prev => prev.map((msg, idx) =>
                    idx === prev.length - 1 && msg.role === 'assistant'
                      ? { ...msg, content: streamedContent }
                      : msg
                  ))
                }
              } catch (e) {
                console.warn('Failed to parse fitness SSE data:', data)
              }
            }
          }
        } else {
          // Main Sara chat uses more complex SSE with event types
          sseBuffer += chunk
          const parts = sseBuffer.split('\n\n')
          sseBuffer = parts.pop() || ''

          for (const part of parts) {
            const dataLine = part.split('\n').find(l => l.startsWith('data: '))
            if (dataLine) {
              try {
                const eventData = JSON.parse(dataLine.slice(6))

                switch (eventData.type) {
                  case 'tool_calls_start':
                    spriteBus.setBase('thinking', 'spriteChatPopup:tools_start')
                    break
                  case 'tool_executing':
                    spriteBus.setBase('thinking', 'spriteChatPopup:tool_executing')
                    break
                  case 'thinking':
                    spriteBus.setBase('thinking', 'spriteChatPopup:thinking')
                    break
                  case 'text_chunk':
                    streamedContent = eventData.data.full_content || streamedContent

                    if (firstChunk) {
                      spriteBus.setOverlay('speaking', { source: 'spriteChatPopup:first_chunk', autoClearMs: 900 })
                      spriteBus.setTone('playful', 'spriteChatPopup:first_chunk')
                      firstChunk = false
                    }

                    setMessages(prev => prev.map((msg, idx) =>
                      idx === prev.length - 1 && msg.role === 'assistant'
                        ? { ...msg, content: streamedContent }
                        : msg
                    ))
                    break
                  case 'final_response':
                    streamedContent = eventData.data.content
                    setMessages(prev => prev.map((msg, idx) =>
                      idx === prev.length - 1 && msg.role === 'assistant'
                        ? { ...msg, content: streamedContent }
                        : msg
                    ))
                    break
                  case 'response_ready':
                    spriteBus.setBase('idle', 'spriteChatPopup:response_ready')
                    spriteBus.setTone(undefined, 'spriteChatPopup:response_ready')
                    break
                }
              } catch (e) {
                console.warn('Failed to parse SSE data:', dataLine)
              }
            }
          }
        }
      }
    } catch (error: any) {
      if (error.name === 'AbortError') {
        console.log('Chat request was cancelled')
        return
      }

      const errorMsg = 'Connection error. Please try again.'
      setMessages(prev => prev.map((msg, idx) =>
        idx === prev.length - 1 && msg.role === 'assistant'
          ? { ...msg, content: errorMsg }
          : msg
      ))
    } finally {
      setIsLoading(false)
      spriteBus.setBase('idle', 'spriteChatPopup:finally')
      spriteBus.setTone(undefined, 'spriteChatPopup:finally')
      abortControllerRef.current = null
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e as any)
    }
  }

  if (!open) return null

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black bg-opacity-50 z-40"
        onClick={onClose}
        onKeyDown={(e) => e.stopPropagation()}
      />

      {/* Popup Window */}
      <div className="fixed bottom-24 right-6 w-[600px] min-w-[600px] max-w-[600px] h-[750px] bg-gray-800 rounded-2xl shadow-2xl z-50 flex flex-col border border-gray-700" style={{ width: '600px' }}>
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <div className="flex items-center space-x-2">
            <div className="w-10 h-10 bg-teal-600 rounded-full flex items-center justify-center text-white font-semibold">
              S
            </div>
            <div>
              <h3 className="text-white font-semibold">
                {mode === 'sara' ? 'Sara' : 'Sara Fitness'}
              </h3>
              <p className="text-xs text-gray-400">
                {mode === 'sara' ? 'AI Assistant' : 'Fitness Expert'}
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors p-1"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Mode Toggle */}
        <div className="flex p-2 bg-gray-900 border-b border-gray-700">
          <button
            onClick={() => setMode('sara')}
            className={`flex-1 py-2 px-4 rounded-lg flex items-center justify-center space-x-2 transition-all ${
              mode === 'sara'
                ? 'bg-teal-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
            }`}
          >
            <MessageCircle className="w-4 h-4" />
            <span className="text-sm font-medium">Sara</span>
          </button>
          <button
            onClick={() => setMode('fitness')}
            className={`flex-1 py-2 px-4 rounded-lg flex items-center justify-center space-x-2 transition-all ml-2 ${
              mode === 'fitness'
                ? 'bg-teal-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
            }`}
          >
            <Dumbbell className="w-4 h-4" />
            <span className="text-sm font-medium">Fitness</span>
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.map((msg, idx) => (
            <div
              key={idx}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div className={`max-w-[85%] ${msg.role === 'user' ? 'order-2' : 'order-1'}`}>
                {msg.role === 'assistant' && (
                  <div className="flex items-center mb-1">
                    <div className="w-6 h-6 bg-teal-600 rounded-full flex items-center justify-center text-white text-xs font-medium mr-2">
                      S
                    </div>
                    <span className="text-xs text-gray-400">
                      {mode === 'sara' ? 'Sara' : 'Sara Fitness'}
                    </span>
                  </div>
                )}

                <div className={`rounded-lg px-3 py-2 text-sm ${
                  msg.role === 'user'
                    ? 'bg-teal-600 text-white ml-auto'
                    : 'bg-gray-700 text-gray-100'
                }`}>
                  {msg.role === 'assistant' ? (
                    <MarkdownRenderer content={msg.content} />
                  ) : (
                    <p>{msg.content}</p>
                  )}
                </div>

                <div className={`text-xs text-gray-500 mt-1 ${
                  msg.role === 'user' ? 'text-right' : 'text-left'
                }`}>
                  {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>
            </div>
          ))}

          {isLoading && messages[messages.length - 1]?.content === '' && (
            <div className="flex justify-start">
              <div className="bg-gray-700 rounded-lg px-3 py-2">
                <div className="flex space-x-1">
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{animationDelay: '0.1s'}}></div>
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{animationDelay: '0.2s'}}></div>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Area */}
        <div className="border-t border-gray-700 p-3">
          <form onSubmit={handleSubmit} className="flex space-x-2">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={`Ask ${mode === 'sara' ? 'Sara' : 'Sara Fitness'}...`}
              className="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 text-white placeholder-gray-400 resize-none"
              rows={2}
              disabled={isLoading}
            />
            <button
              type="submit"
              disabled={isLoading || !input.trim()}
              className="bg-teal-600 hover:bg-teal-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-4 rounded-lg transition-colors flex items-center justify-center"
            >
              <span className="material-icons text-lg">send</span>
            </button>
          </form>
        </div>
      </div>
    </>
  )
}
