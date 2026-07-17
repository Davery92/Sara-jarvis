import { useEffect, useRef, useCallback } from 'react'
import { APP_CONFIG } from '../config'

export interface TaskChatMessage {
  content: string
  task_id: string
  note_id?: string
}

export interface TaskNotification {
  title: string
  message: string
  task_id: string
  note_id?: string
}

interface UseTaskEventStreamOptions {
  enabled: boolean
  onInjectChatMessage?: (data: TaskChatMessage) => void
  onShowNotification?: (data: TaskNotification) => void
}

/**
 * Connects to the task-events SSE endpoint and dispatches events.
 * Auto-reconnects on disconnect with a 5-second delay.
 */
export function useTaskEventStream({
  enabled,
  onInjectChatMessage,
  onShowNotification,
}: UseTaskEventStreamOptions) {
  const esRef = useRef<EventSource | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Store callbacks in refs so reconnect logic always has the latest
  const onInjectRef = useRef(onInjectChatMessage)
  const onNotifyRef = useRef(onShowNotification)
  onInjectRef.current = onInjectChatMessage
  onNotifyRef.current = onShowNotification

  const connect = useCallback(() => {
    if (esRef.current) {
      esRef.current.close()
    }

    const url = `${APP_CONFIG.apiUrl}/api/task-events/stream`
    const es = new EventSource(url, { withCredentials: true })
    esRef.current = es

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'inject_chat_message') {
          onInjectRef.current?.(data as TaskChatMessage)
        } else if (data.type === 'show_notification') {
          onNotifyRef.current?.(data as TaskNotification)
        }
        // 'connected' keepalive — ignore
      } catch {
        // ignore parse errors
      }
    }

    es.onerror = () => {
      es.close()
      esRef.current = null
      // Reconnect after 5 seconds
      reconnectTimer.current = setTimeout(() => {
        if (enabled) connect()
      }, 5000)
    }
  }, [enabled])

  useEffect(() => {
    if (!enabled) {
      esRef.current?.close()
      esRef.current = null
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      return
    }

    connect()

    return () => {
      esRef.current?.close()
      esRef.current = null
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    }
  }, [enabled, connect])
}
