import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../hooks/useAuth'
import { apiClient, ChatMessage, Citation, ToolEffect } from '../api/client'
import { APP_CONFIG } from '../config'

export default function Chat() {
  const { user } = useAuth()
  const [message, setMessage] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const queryClient = useQueryClient()

  // Fetch chat history
  const { data: messages = [], isLoading } = useQuery({
    queryKey: ['chat', 'history'],
    queryFn: () => apiClient.getChatHistory(),
  })

  // Send message mutation
  const sendMessageMutation = useMutation({
    mutationFn: (content: string) => apiClient.sendMessage(content),
    onMutate: () => {
      setIsTyping(true)
    },
    onSuccess: (newMessage) => {
      queryClient.setQueryData(['chat', 'history'], (old: ChatMessage[] = []) => [...old, newMessage])
      setIsTyping(false)
    },
    onError: () => {
      setIsTyping(false)
    },
  })

  // Clear chat mutation
  const clearChatMutation = useMutation({
    mutationFn: () => apiClient.clearChatHistory(),
    onSuccess: () => {
      queryClient.setQueryData(['chat', 'history'], [])
    },
  })

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isTyping])

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`
    }
  }, [message])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!message.trim() || sendMessageMutation.isPending) return

    const userMessage = message.trim()
    setMessage('')

    // Optimistically add user message
    queryClient.setQueryData(['chat', 'history'], (old: ChatMessage[] = []) => [
      ...old,
      {
        id: Date.now().toString(),
        content: userMessage,
        role: 'user' as const,
        timestamp: new Date(),
      }
    ])

    try {
      await sendMessageMutation.mutateAsync(userMessage)
    } catch (error) {
      console.error('Failed to send message:', error)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  const formatTime = (date: Date) => {
    return new Date(date).toLocaleTimeString('en-US', { 
      hour: 'numeric', 
      minute: '2-digit',
      hour12: true 
    })
  }

  const handleClearChat = () => {
    if (window.confirm('Are you sure you want to clear the chat history?')) {
      clearChatMutation.mutate()
    }
  }

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading chat...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-4 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">
              Chat with {APP_CONFIG.assistantName}
            </h1>
            <p className="text-sm text-gray-500">
              Ask questions, get help, or have a conversation
            </p>
          </div>
          {messages.length > 0 && (
            <button
              onClick={handleClearChat}
              disabled={clearChatMutation.isPending}
              className="text-sm text-gray-500 hover:text-gray-700 px-3 py-2 rounded-md hover:bg-gray-100 transition-colors duration-200"
            >
              Clear Chat
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        <div className="max-w-4xl mx-auto space-y-6">
          {messages.length === 0 ? (
            <div className="text-center py-12">
              <div className="w-16 h-16 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-full flex items-center justify-center mx-auto mb-4">
                <span className="text-white font-bold text-xl">{APP_CONFIG.assistantName.charAt(0)}</span>
              </div>
              <h2 className="text-xl font-semibold text-gray-900 mb-2">
                Start a conversation with {APP_CONFIG.assistantName}
              </h2>
              <p className="text-gray-500 mb-6 max-w-md mx-auto">
                I can help you with notes, reminders, calendar events, and answer questions using your knowledge base.
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-w-lg mx-auto">
                {[
                  "What's on my schedule today?",
                  "Help me write a note about...",
                  "Set a reminder for...",
                  "Find information about..."
                ].map((suggestion, index) => (
                  <button
                    key={index}
                    onClick={() => setMessage(suggestion)}
                    className="text-left p-3 bg-white border border-gray-200 rounded-lg hover:border-indigo-300 hover:bg-indigo-50 transition-colors duration-200"
                  >
                    <span className="text-sm text-gray-700">{suggestion}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))
          )}

          {/* Typing indicator */}
          {isTyping && (
            <div className="flex items-start space-x-3">
              <div className="w-8 h-8 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-full flex items-center justify-center flex-shrink-0">
                <span className="text-white font-medium text-sm">{APP_CONFIG.assistantName.charAt(0)}</span>
              </div>
              <div className="bg-white rounded-lg px-4 py-3 shadow-sm border border-gray-200">
                <div className="flex space-x-1">
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></div>
                  <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div className="bg-white border-t border-gray-200 px-4 py-4">
        <div className="max-w-4xl mx-auto">
          <form onSubmit={handleSubmit} className="flex space-x-3">
            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={APP_CONFIG.ui.chatPlaceholder}
                rows={1}
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 resize-none"
                disabled={sendMessageMutation.isPending}
              />
            </div>
            <button
              type="submit"
              disabled={!message.trim() || sendMessageMutation.isPending}
              className="px-6 py-3 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200"
            >
              {sendMessageMutation.isPending ? (
                <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}

interface MessageBubbleProps {
  message: ChatMessage
}

function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user'

  const formatTime = (date: Date) => {
    return new Date(date).toLocaleTimeString('en-US', { 
      hour: 'numeric', 
      minute: '2-digit',
      hour12: true 
    })
  }

  return (
    <div className={`flex items-start space-x-3 ${isUser ? 'flex-row-reverse space-x-reverse' : ''}`}>
      {/* Avatar */}
      <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
        isUser 
          ? 'bg-gray-200 text-gray-700' 
          : 'bg-gradient-to-br from-indigo-500 to-purple-600 text-white'
      }`}>
        <span className="font-medium text-sm">
          {isUser ? message.content.charAt(0).toUpperCase() : APP_CONFIG.assistantName.charAt(0)}
        </span>
      </div>

      {/* Message content */}
      <div className={`max-w-3xl ${isUser ? 'items-end' : 'items-start'}`}>
        <div className={`rounded-lg px-4 py-3 shadow-sm border ${
          isUser 
            ? 'bg-indigo-600 text-white border-indigo-600' 
            : 'bg-white text-gray-900 border-gray-200'
        }`}>
          <div className="whitespace-pre-wrap">{message.content}</div>
        </div>

        {/* Citations */}
        {message.citations && message.citations.length > 0 && (
          <div className="mt-2 space-y-2">
            <p className="text-xs text-gray-500 font-medium">Sources:</p>
            {message.citations.map((citation, index) => (
              <div key={index} className="bg-gray-50 border border-gray-200 rounded-lg p-3">
                <div className="flex items-center space-x-2 mb-1">
                  <span className="text-xs font-medium text-gray-700">
                    {citation.type === 'memory' ? '🧠' : citation.type === 'document' ? '📄' : '📝'} {citation.source}
                  </span>
                </div>
                <p className="text-sm text-gray-600">{citation.content}</p>
              </div>
            ))}
          </div>
        )}

        {/* Tool Effects */}
        {message.tool_effects && message.tool_effects.length > 0 && (
          <div className="mt-2 space-y-2">
            {message.tool_effects.map((effect, index) => (
              <div key={index} className="bg-blue-50 border border-blue-200 rounded-lg p-3">
                <div className="flex items-center space-x-2 mb-1">
                  <span className="text-xs font-medium text-blue-700">
                    🔧 {effect.tool}: {effect.action}
                  </span>
                </div>
                <p className="text-sm text-blue-600">{effect.result}</p>
              </div>
            ))}
          </div>
        )}

        {/* Timestamp */}
        <p className={`text-xs text-gray-500 mt-1 ${isUser ? 'text-right' : 'text-left'}`}>
          {formatTime(message.timestamp)}
        </p>
      </div>
    </div>
  )
}
export default Chat
