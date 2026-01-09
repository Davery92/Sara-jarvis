import { useState, useRef, useEffect, useCallback } from 'react'
import { apiClient } from '../services/api'
import { voiceService } from '../services/voice'

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
  autoStartVoice?: boolean
}

export default function MiniChat({ onClose, isAuthenticated, onNeedAuth, autoStartVoice }: MiniChatProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [activeTool, setActiveTool] = useState<string | null>(null)
  const [toolsUsed, setToolsUsed] = useState<Set<string>>(new Set())
  const [isRecording, setIsRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const voiceStartedRef = useRef(false)

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
  const tryShowNote = useCallback(async (responseText: string, _userQuery: string) => {
    console.log('[MiniChat] tryShowNote called')
    console.log('[MiniChat] Response text:', responseText.substring(0, 300))

    // Sara already found and displayed the note in her response
    // Extract the note title from her response - look for patterns like:
    // "Here's your AMS360 Integration note" or "# AMS360 Integration" or "**AMS360 Integration**"
    const titlePatterns = [
      /here's\s+(?:your\s+)?(?:the\s+)?(.+?)\s+note/i,
      /^#\s+(.+)$/m,  // Markdown H1
      /\*\*([^*]+)\*\*/,  // Bold text (often the title)
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
      // Get all notes and find the matching one
      const allNotes = await apiClient.searchNotes('')
      console.log('[MiniChat] Got', allNotes.length, 'notes')

      if (allNotes.length === 0) {
        console.log('[MiniChat] No notes found')
        return
      }

      let noteToShow = allNotes[0] // Default to first/most recent

      // If we extracted a title, find that specific note
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
      'get_fitness_summary': 'Getting fitness data...',
      'log_food': 'Logging food...',
      'search_food': 'Searching food...',
    }
    return toolLabels[tool] || `Using ${tool.replace(/_/g, ' ')}...`
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Voice recording functions
  const startVoiceRecording = useCallback(async () => {
    if (isRecording || isLoading) return

    console.log('[MiniChat] Starting voice recording...')
    setIsRecording(true)

    try {
      await voiceService.startContinuousRecording(async () => {
        // Called when silence is detected
        console.log('[MiniChat] Silence detected, stopping recording')
        await stopVoiceRecording()
      })
    } catch (error) {
      console.error('[MiniChat] Voice recording error:', error)
      setIsRecording(false)
    }
  }, [isRecording, isLoading])

  const stopVoiceRecording = useCallback(async () => {
    if (!isRecording) return

    console.log('[MiniChat] Stopping voice recording...')
    setIsRecording(false)
    setIsTranscribing(true)

    try {
      const audioBlob = await voiceService.stopRecording()
      if (audioBlob && audioBlob.size > 0) {
        console.log('[MiniChat] Transcribing audio...')
        const transcription = await voiceService.transcribe(audioBlob)

        if (transcription && transcription.trim()) {
          console.log('[MiniChat] Transcription:', transcription)
          setInput(transcription)
          // Auto-send after transcription
          setIsTranscribing(false)
          // Need to send manually since setInput is async
          handleSendWithText(transcription)
        } else {
          console.log('[MiniChat] Empty transcription')
          setIsTranscribing(false)
        }
      } else {
        console.log('[MiniChat] No audio recorded')
        setIsTranscribing(false)
      }
    } catch (error) {
      console.error('[MiniChat] Transcription error:', error)
      setIsTranscribing(false)
    }
  }, [isRecording])

  // Auto-start voice when opened via wake word
  useEffect(() => {
    if (autoStartVoice && isAuthenticated && !voiceStartedRef.current) {
      voiceStartedRef.current = true
      console.log('[MiniChat] Auto-starting voice recording (wake word triggered)')
      // Small delay to ensure component is ready
      setTimeout(() => {
        startVoiceRecording()
      }, 500)
    }
  }, [autoStartVoice, isAuthenticated, startVoiceRecording])

  // Listen for start-voice event (when chat is already open and wake word detected)
  useEffect(() => {
    if (window.electronAPI?.onStartVoice) {
      window.electronAPI.onStartVoice(() => {
        console.log('[MiniChat] Received start-voice event from main process')
        if (isAuthenticated && !isRecording && !isTranscribing) {
          startVoiceRecording()
        }
      })
    }
  }, [isAuthenticated, isRecording, isTranscribing, startVoiceRecording])

  // Cleanup voice on unmount
  useEffect(() => {
    return () => {
      voiceService.cleanup()
    }
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
    setToolsUsed(new Set()) // Reset tools used for this response

    try {
      // Create assistant message placeholder
      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: '',
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, assistantMessage])

      // Track response content for note detection
      let fullResponse = ''
      const usedTools = new Set<string>()

      // Stream the response
      await apiClient.streamChat(
        userQuery,
        (chunk) => {
          setActiveTool(null) // Clear tool indicator when text comes in
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

          // After response completes, check for timers and notes
          if (usedTools.has('start_timer') || usedTools.has('timers_start') || usedTools.has('timer_start')) {
            console.log('[MiniChat] Timer tool detected, checking for timers')
            await checkForTimers()
          }
          if (usedTools.has('create_note') || usedTools.has('search_notes') || usedTools.has('notes_search') || usedTools.has('note_search')) {
            console.log('[MiniChat] Note tool detected, attempting to show note popup')
            await tryShowNote(fullResponse, userQuery)
          } else {
            console.log('[MiniChat] No note tools detected in usedTools set')
          }
        },
        (tool) => {
          console.log('[MiniChat] Tool activity detected:', tool)
          setActiveTool(tool)
          usedTools.add(tool)
          setToolsUsed(prev => new Set([...prev, tool]))
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

  // Wrapper for text input send
  const handleSend = useCallback(() => {
    handleSendWithText(input)
  }, [input, handleSendWithText])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Toggle voice recording
  const toggleVoice = useCallback(() => {
    if (isRecording) {
      stopVoiceRecording()
    } else {
      startVoiceRecording()
    }
  }, [isRecording, startVoiceRecording, stopVoiceRecording])

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
        ) : isRecording ? (
          <div className="flex items-center justify-center gap-3 py-2">
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 bg-red-500 rounded-full animate-pulse" />
              <span className="text-white text-sm">Listening...</span>
            </div>
            <button
              onClick={toggleVoice}
              className="bg-red-600 hover:bg-red-500 text-white rounded-xl px-4 py-2 transition-colors"
            >
              Stop
            </button>
          </div>
        ) : isTranscribing ? (
          <div className="flex items-center justify-center gap-2 py-2">
            <svg className="w-5 h-5 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            <span className="text-gray-400 text-sm">Processing speech...</span>
          </div>
        ) : (
          <div className="flex gap-2">
            <button
              onClick={toggleVoice}
              disabled={isLoading}
              className="bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-white rounded-xl px-3 py-2 transition-colors border border-gray-700"
              title="Voice input"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            </button>
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
