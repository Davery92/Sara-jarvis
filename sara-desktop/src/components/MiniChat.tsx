import { useState, useRef, useEffect, useCallback } from 'react'
import { apiClient } from '../services/api'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

interface MiniChatProps {
  onClose: () => void
  isAuthenticated: boolean
  onNeedAuth: () => void
}

export default function MiniChat({ onClose, isAuthenticated, onNeedAuth }: MiniChatProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [activeTool, setActiveTool] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Check for new timers and show floating windows
  const checkForTimers = useCallback(async () => {
    console.log('[MiniChat] checkForTimers called')
    try {
      const timers = await apiClient.getActiveTimers()
      console.log('[MiniChat] Got timers:', timers.length)
      timers.forEach(timer => {
        console.log('[MiniChat] Showing timer:', timer.title, timer.remaining_seconds, 'seconds')
        window.electronAPI?.showTimer({
          id: timer.id,
          name: timer.title,
          remainingSeconds: timer.remaining_seconds
        })
      })
    } catch (e) {
      console.error('[MiniChat] Failed to check timers:', e)
    }
  }, [])

  // Try to find and show a note from the response
  const tryShowNote = useCallback(async (responseText: string) => {
    console.log('[MiniChat] tryShowNote called')

    // Extract the note title from response
    const titlePatterns = [
      /here's\s+(?:your\s+)?(?:the\s+)?(.+?)\s+note/i,
      /^#\s+(.+)$/m,
      /\*\*([^*]+)\*\*/,
    ]

    let noteTitle: string | null = null
    for (const pattern of titlePatterns) {
      const match = responseText.match(pattern)
      if (match) {
        noteTitle = match[1].trim()
        console.log('[MiniChat] Extracted note title from response:', noteTitle)
        break
      }
    }

    try {
      const allNotes = await apiClient.searchNotes('')
      console.log('[MiniChat] Got', allNotes.length, 'notes')

      if (allNotes.length === 0) {
        console.log('[MiniChat] No notes found')
        return
      }

      let noteToShow = allNotes[0]

      if (noteTitle) {
        const lowerTitle = noteTitle.toLowerCase()
        const matched = allNotes.find(n =>
          n.title.toLowerCase().includes(lowerTitle) ||
          lowerTitle.includes(n.title.toLowerCase())
        )
        if (matched) {
          noteToShow = matched
          console.log('[MiniChat] Found matching note:', matched.title)
        }
      }

      console.log('[MiniChat] Opening note popup:', noteToShow.title)
      window.electronAPI?.showNote({
        id: noteToShow.id,
        title: noteToShow.title,
        content: noteToShow.content
      })
    } catch (e) {
      console.error('[MiniChat] Failed to show note:', e)
    }
  }, [])

  // Format tool names for display
  const formatToolName = (tool: string): string => {
    const toolLabels: Record<string, string> = {
      'create_note': 'Creating note...',
      'search_notes': 'Searching notes...',
      'notes_search': 'Searching notes...',
      'note_search': 'Searching notes...',
      'update_note': 'Updating note...',
      'search_memory': 'Searching memory...',
      'create_reminder': 'Setting reminder...',
      'list_reminders': 'Checking reminders...',
      'cancel_reminder': 'Canceling reminder...',
      'start_timer': 'Starting timer...',
      'timers_start': 'Starting timer...',
      'timer_start': 'Starting timer...',
      'check_timer': 'Checking timer...',
      'timers_status': 'Checking timer...',
      'cancel_timer': 'Canceling timer...',
      'timers_cancel': 'Canceling timer...',
      'list_calendar_events': 'Checking calendar...',
      'create_calendar_event': 'Creating event...',
    }
    return toolLabels[tool] || `Using ${tool.replace(/_/g, ' ')}...`
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleSendWithText = useCallback(async (text: string) => {
    if (!text.trim() || isLoading) return

    if (!isAuthenticated) {
      onNeedAuth()
      return
    }

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text.trim(),
      timestamp: new Date(),
    }

    const userQuery = text.trim()
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)

    try {
      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: '',
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, assistantMessage])

      let fullResponse = ''
      const usedTools = new Set<string>()

      await apiClient.streamChat(
        userQuery,
        (chunk) => {
          setActiveTool(null)
          fullResponse += chunk
          setMessages(prev => {
            const updated = [...prev]
            const lastMsg = updated[updated.length - 1]
            if (lastMsg.role === 'assistant') {
              lastMsg.content += chunk
            }
            return updated
          })
        },
        async () => {
          console.log('[MiniChat] Stream complete. Tools used:', Array.from(usedTools))
          setIsLoading(false)
          setActiveTool(null)

          // Check for timers and notes after response
          if (usedTools.has('start_timer') || usedTools.has('timers_start') || usedTools.has('timer_start')) {
            await checkForTimers()
          }
          if (usedTools.has('create_note') || usedTools.has('search_notes') || usedTools.has('notes_search') || usedTools.has('note_search')) {
            await tryShowNote(fullResponse)
          }
        },
        (tool) => {
          console.log('[MiniChat] Tool activity detected:', tool)
          setActiveTool(tool)
          usedTools.add(tool)
        }
      )
    } catch (error) {
      console.error('Chat error:', error)
      setMessages(prev => {
        const updated = [...prev]
        const lastMsg = updated[updated.length - 1]
        if (lastMsg.role === 'assistant' && !lastMsg.content) {
          lastMsg.content = 'Sorry, I encountered an error. Please try again.'
        }
        return updated
      })
      setIsLoading(false)
    }
  }, [isLoading, isAuthenticated, onNeedAuth, checkForTimers, tryShowNote])

  const handleSend = useCallback(() => {
    handleSendWithText(input)
  }, [input, handleSendWithText])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="no-drag w-full h-screen bg-gray-900 rounded-2xl border border-gray-700 shadow-2xl flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700/50 bg-gray-800/50">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
            <span className="text-white text-sm font-bold">S</span>
          </div>
          <span className="text-white font-medium">Sara</span>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-white transition-colors p-1"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-gray-500 py-8">
            <p className="text-sm">Hi! How can I help you today?</p>
          </div>
        )}
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-2 ${
                message.role === 'user'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-800 text-gray-100'
              }`}
            >
              <p className="text-sm whitespace-pre-wrap">{message.content}</p>
            </div>
          </div>
        ))}
        {isLoading && messages[messages.length - 1]?.role === 'assistant' && !messages[messages.length - 1]?.content && (
          <div className="flex justify-start">
            <div className="bg-gray-800 rounded-2xl px-4 py-2">
              {activeTool ? (
                <div className="flex items-center gap-2 text-indigo-400">
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  <span className="text-sm">{formatToolName(activeTool)}</span>
                </div>
              ) : (
                <div className="flex gap-1">
                  <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              )}
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-3 border-t border-gray-700/50 bg-gray-800/30">
        {!isAuthenticated ? (
          <button
            onClick={onNeedAuth}
            className="w-full bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl px-4 py-3 text-sm font-medium transition-colors"
          >
            Log in to chat with Sara
          </button>
        ) : (
          <div className="flex gap-2">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a message..."
              disabled={isLoading}
              className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-4 py-2 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-indigo-500 disabled:opacity-50"
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || isLoading}
              className="bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:opacity-50 text-white rounded-xl px-4 py-2 transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
