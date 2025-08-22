import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../hooks/useAuth'
import { apiClient, ChatMessage } from '../api/client'
import { APP_CONFIG } from '../config'
import MarkdownRenderer from '../components/MarkdownRenderer'
import ErrorBoundary from '../components/ErrorBoundary'

export default function Chat() {
  const {} = useAuth()
  const [message, setMessage] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const [toolActivity, setToolActivity] = useState<{
    isUsingTools: boolean
    currentTool?: string
    round?: number
    tools?: string[]
  }>({ isUsingTools: false })
  const [streamingContent, setStreamingContent] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const queryClient = useQueryClient()

  // Scroll to bottom helper function
  const scrollToBottom = (delay = 100) => {
    setTimeout(() => {
      if (messagesEndRef.current) {
        // Primary method: scrollIntoView
        messagesEndRef.current.scrollIntoView({ 
          behavior: 'smooth',
          block: 'end',
          inline: 'nearest'
        })
      } else {
        // Fallback: scroll the container directly
        const messagesContainer = document.querySelector('.overflow-y-auto')
        if (messagesContainer) {
          messagesContainer.scrollTop = messagesContainer.scrollHeight
        }
      }
    }, delay)
  }

  // Fetch chat history
  const { data: messages = [], isLoading } = useQuery({
    queryKey: ['chat', 'history'],
    queryFn: () => apiClient.getChatHistory(),
  })

  // Send message with streaming
  const sendMessageMutation = useMutation({
    mutationFn: async (content: string) => {
      setIsTyping(true)
      setToolActivity({ isUsingTools: false })
      setStreamingContent('')
      
      let finalMessage: ChatMessage | null = null
      
      await apiClient.sendMessageStream(content, (event) => {
        switch (event.type) {
          case 'tool_calls_start':
            setToolActivity({
              isUsingTools: true,
              tools: event.data.tools,
              round: event.data.round
            })
            break
            
          case 'tool_executing':
            setToolActivity(prev => ({
              ...prev,
              currentTool: event.data.tool,
              round: event.data.round
            }))
            break
            
          case 'tool_completed':
            // Keep showing tools activity until all are done
            break
            
          case 'thinking':
            setToolActivity(prev => ({
              ...prev,
              currentTool: 'processing results...'
            }))
            break
            
          case 'text_chunk':
            setStreamingContent(event.data.full_content)
            break
            
          case 'final_response':
            finalMessage = {
              id: Date.now().toString(),
              content: event.data.content,
              role: 'assistant',
              timestamp: new Date()
            }
            setStreamingContent('')
            break
            
          case 'response_ready':
            setToolActivity({ isUsingTools: false })
            setIsTyping(false)
            setStreamingContent('')
            break
            
          case 'error':
            console.error('Streaming error:', event.message)
            setIsTyping(false)
            setToolActivity({ isUsingTools: false })
            setStreamingContent('')
            break
        }
      })
      
      return finalMessage
    },
    onSuccess: (newMessage) => {
      if (newMessage) {
        queryClient.setQueryData(['chat', 'history'], (old: ChatMessage[] = []) => [...old, newMessage])
      }
      setIsTyping(false)
      setToolActivity({ isUsingTools: false })
      scrollToBottom(150)
    },
    onError: () => {
      setIsTyping(false)
      setToolActivity({ isUsingTools: false })
    },
  })

  // Clear chat mutation
  const clearChatMutation = useMutation({
    mutationFn: () => apiClient.clearChatHistory(),
    onSuccess: () => {
      queryClient.setQueryData(['chat', 'history'], [])
    },
  })

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    scrollToBottom(100)
  }, [messages, isTyping, streamingContent])

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

    // Scroll to bottom after adding user message
    scrollToBottom(50)

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

          {/* Streaming content bubble */}
          {streamingContent && (
            <div className="flex items-start space-x-3">
              <div className="w-8 h-8 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-full flex items-center justify-center flex-shrink-0">
                <span className="text-white font-medium text-sm">{APP_CONFIG.assistantName.charAt(0)}</span>
              </div>
              <div className="max-w-3xl items-start">
                <div className="rounded-lg px-4 py-3 shadow-sm border bg-white text-gray-900 border-gray-200">
                  <ErrorBoundary>
                    <MarkdownRenderer content={streamingContent} />
                  </ErrorBoundary>
                  <div className="inline-block w-2 h-4 bg-indigo-500 animate-pulse ml-1"></div>
                </div>
                <p className="text-xs text-gray-500 mt-1 text-left">
                  {formatTime(new Date())}
                </p>
              </div>
            </div>
          )}

          {/* Enhanced typing indicator with real-time tool usage */}
          {isTyping && (
            <div className="flex items-start space-x-3">
              <div className="w-8 h-8 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-full flex items-center justify-center flex-shrink-0">
                <span className="text-white font-medium text-sm">{APP_CONFIG.assistantName.charAt(0)}</span>
              </div>
              <div className="bg-white rounded-lg px-4 py-3 shadow-sm border border-gray-200 min-w-0 flex-1 max-w-md">
                <div className="flex items-center space-x-3">
                  <div className="flex space-x-1 flex-shrink-0">
                    <div className="w-2 h-2 bg-indigo-500 rounded-full animate-bounce"></div>
                    <div className="w-2 h-2 bg-indigo-500 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></div>
                    <div className="w-2 h-2 bg-indigo-500 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                  </div>
                  <div className="flex items-center space-x-2 text-sm text-gray-600 min-w-0">
                    <svg className="w-4 h-4 animate-spin flex-shrink-0" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="m4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <div className="min-w-0">
                      {toolActivity.isUsingTools ? (
                        <div className="space-y-1">
                          <div className="flex items-center space-x-2">
                            <span className="text-amber-600 font-medium">🔧 Using Tools</span>
                            {toolActivity.round && <span className="text-xs text-gray-400">(Round {toolActivity.round})</span>}
                          </div>
                          {toolActivity.currentTool && (
                            <div className="text-xs text-gray-500">
                              → {toolActivity.currentTool}
                            </div>
                          )}
                          {toolActivity.tools && toolActivity.tools.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-1">
                              {toolActivity.tools.map((tool, index) => (
                                <span key={index} className="text-xs bg-amber-100 text-amber-700 px-2 py-1 rounded-md">
                                  {tool}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span>Thinking...</span>
                      )}
                    </div>
                  </div>
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
          {isUser ? (
            <div className="whitespace-pre-wrap">{message.content}</div>
          ) : (
            <ErrorBoundary>
              <MarkdownRenderer content={message.content} />
            </ErrorBoundary>
          )}
        </div>

        {/* Sources list (compact, clickable) */}
        {Array.isArray((message as any).citations) && (message as any).citations.length > 0 && (
          <div className="mt-2 space-y-1">
            <p className="text-xs text-gray-500 font-medium">Sources:</p>
            <ul className="space-y-1">
              {(message as any).citations.slice(0,5).map((c: any, i: number) => (
                <li key={i} className="text-xs text-gray-600 truncate">
                  <a
                    href={typeof c === 'string' ? c : c.url}
                    target="_blank"
                    rel="noreferrer"
                    className="hover:underline"
                  >
                    {typeof c === 'string' ? c : (c.title || c.url)}
                  </a>
                </li>
              ))}
            </ul>
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
