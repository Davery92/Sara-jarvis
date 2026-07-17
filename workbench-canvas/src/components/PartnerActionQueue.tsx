import { useEffect, useMemo, useState } from 'react'
import { Sparkles, Check, X } from 'lucide-react'
import { useCanvasStore } from '../store/canvasStore'
import { executeWorkspaceCommand } from '../services/workspaceCommands'
import { APP_CONFIG } from '../config'

interface QueueAction {
  id: string
  label: string
  description: string
  command: any
}

interface EmailStats {
  total_emails: number
  unread_count: number
  important: number
  action_required_count: number
}

interface ActionMemory {
  acceptedAt?: number
  dismissedAt?: number
}

const ACTION_MEMORY_KEY = 'partner_action_queue_memory_v1'
const ACCEPT_COOLDOWN_MS: Record<string, number> = {
  'open-email-triage': 2 * 60 * 60 * 1000,
  'open-notes-search': 60 * 60 * 1000,
  'open-docs-search': 60 * 60 * 1000,
}
const DISMISS_COOLDOWN_MS: Record<string, number> = {
  'open-email-triage': 6 * 60 * 60 * 1000,
  'open-notes-search': 4 * 60 * 60 * 1000,
  'open-docs-search': 4 * 60 * 60 * 1000,
}

export default function PartnerActionQueue() {
  const windows = useCanvasStore((s) => s.windows)
  const [emailStats, setEmailStats] = useState<EmailStats | null>(null)
  const [memory, setMemory] = useState<Record<string, ActionMemory>>(() => {
    try {
      const raw = localStorage.getItem(ACTION_MEMORY_KEY)
      return raw ? JSON.parse(raw) : {}
    } catch {
      return {}
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(ACTION_MEMORY_KEY, JSON.stringify(memory))
    } catch {
      // ignore storage failures
    }
  }, [memory])

  useEffect(() => {
    let cancelled = false
    const fetchStats = async () => {
      try {
        const response = await fetch(`${APP_CONFIG.apiUrl}/api/email/stats`, {
          credentials: 'include',
        })
        if (!response.ok) return
        const data = await response.json()
        if (!cancelled) {
          setEmailStats(data)
        }
      } catch {
        // ignore transient fetch failures
      }
    }

    fetchStats()
    const interval = setInterval(fetchStats, 45_000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  const isSuppressed = (actionId: string): boolean => {
    const now = Date.now()
    const rec = memory[actionId]
    if (!rec) return false
    const acceptTtl = ACCEPT_COOLDOWN_MS[actionId] ?? 60 * 60 * 1000
    const dismissTtl = DISMISS_COOLDOWN_MS[actionId] ?? 4 * 60 * 60 * 1000
    if (rec.acceptedAt && now - rec.acceptedAt < acceptTtl) return true
    if (rec.dismissedAt && now - rec.dismissedAt < dismissTtl) return true
    return false
  }

  const actions = useMemo<QueueAction[]>(() => {
    const hasEmail = windows.some((w) => w.type === 'email')
    const hasDocs = windows.some((w) => w.type === 'documents')
    const hasNotes = windows.some((w) => w.type === 'note')
    const hasInboxWork = !!emailStats && ((emailStats.unread_count || 0) > 0 || (emailStats.action_required_count || 0) > 0)

    const next: QueueAction[] = []
    if (!hasEmail && hasInboxWork) {
      next.push({
        id: 'open-email-triage',
        label: 'Triage Inbox',
        description: 'Open email and filter for actionable messages.',
        command: {
          workspace_command: 'open_window',
          window_type: 'email',
          title: 'Email: action required',
          data: { initialQuery: 'action required' },
        },
      })
    }
    if (!hasNotes) {
      next.push({
        id: 'open-notes-search',
        label: 'Find Active Notes',
        description: 'Open notes and search for current project context.',
        command: {
          workspace_command: 'open_window',
          window_type: 'notes',
          title: 'Notes: project',
          data: { initialQuery: 'project' },
        },
      })
    }
    if (!hasDocs) {
      next.push({
        id: 'open-docs-search',
        label: 'Search Documents',
        description: 'Open a documents window and search uploaded files.',
        command: {
          workspace_command: 'open_window',
          window_type: 'documents',
          title: 'Documents',
          data: {},
        },
      })
    }
    return next.slice(0, 3)
  }, [windows, emailStats])

  const visibleActions = actions.filter((a) => !isSuppressed(a.id))
  if (visibleActions.length === 0) return null

  return (
    <div className="fixed bottom-6 right-6 z-[60] w-[380px] max-w-[calc(100vw-2rem)] pointer-events-none">
      <div className="bg-canvas-surface/85 backdrop-blur-md border border-canvas-border rounded-xl shadow-xl p-3 pointer-events-auto">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-canvas-muted mb-2">
          <Sparkles size={14} className="text-teal-400" />
          Sara Action Queue
        </div>
        <div className="space-y-2">
          {visibleActions.map((action) => (
            <div key={action.id} className="rounded-lg border border-canvas-border bg-canvas-bg/70 p-2.5">
              <div className="text-sm text-white font-medium">{action.label}</div>
              <div className="text-xs text-canvas-muted mt-0.5">{action.description}</div>
              <div className="mt-2 flex items-center gap-2">
                <button
                  onClick={() => {
                    executeWorkspaceCommand(action.command, 'partner_queue')
                    setMemory((prev) => ({
                      ...prev,
                      [action.id]: { ...(prev[action.id] || {}), acceptedAt: Date.now() },
                    }))
                  }}
                  className="px-2.5 py-1.5 rounded bg-teal-600 hover:bg-teal-500 text-white text-xs flex items-center gap-1"
                >
                  <Check size={12} />
                  Accept
                </button>
                <button
                  onClick={() => setMemory((prev) => ({
                    ...prev,
                    [action.id]: { ...(prev[action.id] || {}), dismissedAt: Date.now() },
                  }))}
                  className="px-2.5 py-1.5 rounded bg-canvas-elevated hover:bg-canvas-surface text-canvas-muted text-xs flex items-center gap-1"
                >
                  <X size={12} />
                  Dismiss
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
