import React, { useState, useEffect, useCallback, useRef } from 'react'
import { APP_CONFIG } from '../config'

interface BackgroundTask {
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'needs_clarification'
  task_type: string
  original_query: string
  result_note_id: string | null
  workspace_folder_id: string | null
  clarification_question: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  updated_at: string | null
}

interface MiniChatOverlayProps {
  onClose?: () => void
}

// Max age (4 hours) before a needs_clarification task is considered expired
const TASK_EXPIRY_MS = 4 * 60 * 60 * 1000

// Validate that a task has the minimum required fields and is not expired
const isValidTask = (task: any): task is BackgroundTask => {
  if (
    !task ||
    typeof task.id !== 'string' ||
    task.id.length === 0 ||
    task.status !== 'needs_clarification' ||
    typeof task.original_query !== 'string' ||
    typeof task.clarification_question !== 'string' ||
    task.clarification_question.length === 0
  ) {
    return false
  }

  // Ignore tasks that have been stuck for > 4 hours
  const updatedAt = task.updated_at || task.created_at
  if (updatedAt) {
    const age = Date.now() - new Date(updatedAt).getTime()
    if (age > TASK_EXPIRY_MS) {
      return false
    }
  }

  return true
}

export const MiniChatOverlay: React.FC<MiniChatOverlayProps> = ({ onClose }) => {
  const [pendingClarification, setPendingClarification] = useState<BackgroundTask | null>(null)
  const [response, setResponse] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isMinimized, setIsMinimized] = useState(false)
  const [isDismissed, setIsDismissed] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // Poll for tasks needing clarification
  const checkForClarifications = useCallback(async () => {
    if (isDismissed) return

    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/background-tasks/active`, {
        credentials: 'include'
      })

      if (!res.ok) {
        // API error - don't change state
        return
      }

      const data = await res.json()

      // Validate response structure
      if (!data || !Array.isArray(data.tasks)) {
        return
      }

      const tasks: BackgroundTask[] = data.tasks

      // Find task needing clarification WITH a valid question
      const needsClarification = tasks.find(t => isValidTask(t))

      if (needsClarification && (!pendingClarification || needsClarification.id !== pendingClarification.id)) {
        setPendingClarification(needsClarification)
        setIsMinimized(false)
        setIsDismissed(false)
      } else if (!needsClarification && pendingClarification) {
        // Clarification was handled elsewhere or task completed
        setPendingClarification(null)
      }
    } catch (error) {
      // Network error - silently ignore, don't render anything
      console.error('Failed to check for clarifications:', error)
    }
  }, [pendingClarification, isDismissed])

  // Poll every 5 seconds
  useEffect(() => {
    checkForClarifications()
    const interval = setInterval(checkForClarifications, 5000)
    return () => clearInterval(interval)
  }, [checkForClarifications])

  // Focus input when overlay opens
  useEffect(() => {
    if (pendingClarification && !isMinimized && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [pendingClarification, isMinimized])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!pendingClarification || !response.trim()) return

    setIsSubmitting(true)

    try {
      const res = await fetch(
        `${APP_CONFIG.apiUrl}/api/background-tasks/${pendingClarification.id}/clarify`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ response: response.trim() })
        }
      )

      if (res.ok) {
        setResponse('')
        setPendingClarification(null)
      } else {
        console.error('Failed to submit clarification')
      }
    } catch (error) {
      console.error('Error submitting clarification:', error)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDismiss = () => {
    setIsDismissed(true)
    setPendingClarification(null)
    onClose?.()
  }

  // Don't render if no valid clarification needed
  if (!pendingClarification || !isValidTask(pendingClarification)) {
    return null
  }

  // Minimized state - just a small indicator
  if (isMinimized) {
    return (
      <button
        onClick={() => setIsMinimized(false)}
        className="fixed bottom-20 right-4 md:bottom-4 z-50 p-3 bg-orange-500 rounded-full shadow-lg hover:bg-orange-400 transition-colors animate-pulse"
        title="Agent needs your input"
      >
        <span className="material-icons text-white text-xl">help_outline</span>
        <span className="absolute -top-1 -right-1 w-3 h-3 bg-red-500 rounded-full animate-ping" />
      </button>
    )
  }

  const queryPreview = pendingClarification.original_query.length > 80
    ? pendingClarification.original_query.substring(0, 80) + '...'
    : pendingClarification.original_query

  return (
    <div className="fixed bottom-20 right-4 md:bottom-4 z-50 w-80 min-w-[320px] bg-gray-800 rounded-lg shadow-xl border border-orange-500/50 overflow-hidden">
      {/* Header */}
      <div className="bg-orange-500/20 px-4 py-3 border-b border-orange-500/30">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="material-icons text-orange-400 text-lg animate-pulse">help_outline</span>
            <h3 className="text-sm font-semibold text-orange-300">Agent Needs Input</h3>
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
              onClick={handleDismiss}
              className="p-1 hover:bg-white/10 rounded text-gray-400 hover:text-white"
              title="Dismiss"
            >
              <span className="material-icons text-sm">close</span>
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="p-4 space-y-3">
        {/* Task Context */}
        <div className="text-xs text-gray-400 bg-gray-700/50 rounded p-2">
          <span className="text-gray-500">Task: </span>
          {queryPreview}
        </div>

        {/* Question */}
        <div className="bg-gray-700/30 rounded-lg p-3 border-l-2 border-orange-500">
          <p className="text-sm text-gray-200">
            {pendingClarification.clarification_question}
          </p>
        </div>

        {/* Response Input */}
        <form onSubmit={handleSubmit} className="space-y-2">
          <input
            ref={inputRef}
            type="text"
            value={response}
            onChange={(e) => setResponse(e.target.value)}
            placeholder="Type your response..."
            disabled={isSubmitting}
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm text-white placeholder-gray-400 focus:outline-none focus:border-orange-500"
          />
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleDismiss}
              className="flex-1 px-3 py-2 text-sm text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition-colors"
            >
              Skip
            </button>
            <button
              type="submit"
              disabled={!response.trim() || isSubmitting}
              className="flex-1 px-3 py-2 text-sm bg-orange-500 hover:bg-orange-400 disabled:bg-gray-600 disabled:text-gray-400 text-white rounded-lg transition-colors flex items-center justify-center gap-1"
            >
              {isSubmitting ? (
                <>
                  <span className="material-icons text-sm animate-spin">sync</span>
                  Sending...
                </>
              ) : (
                <>
                  <span className="material-icons text-sm">send</span>
                  Send
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default MiniChatOverlay
