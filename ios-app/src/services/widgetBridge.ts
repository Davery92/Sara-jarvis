/**
 * widgetBridge — pushes Sara's state into the App Group so WidgetKit can render
 * it on the home & lock screens (P3).
 *
 * Pulls emotional state + latest thought from /api/sara/status and the next
 * calendar event from /api/sara/brief, then hands them to the native module,
 * which writes the App Group defaults and reloads the widget timelines. No-ops
 * when the native module isn't present.
 */
import { apiClient } from './api'
import { setWidgetData, isAvailable, type WidgetData } from '../../modules/sara-native'

export async function refreshWidgetData(): Promise<void> {
  if (!isAvailable()) return
  try {
    const [statusRes, briefRes] = await Promise.allSettled([
      apiClient.get<any>('/api/sara/status'),
      apiClient.get<any>('/api/sara/brief'),
    ])

    const data: WidgetData = {}

    if (statusRes.status === 'fulfilled' && statusRes.value) {
      data.emotional_state = statusRes.value.emotional_state || 'neutral'
      if (statusRes.value.latest_thought) {
        data.latest_thought = String(statusRes.value.latest_thought).slice(0, 140)
      }
    }

    if (briefRes.status === 'fulfilled' && briefRes.value) {
      const sections = briefRes.value.brief_sections || []
      const calendar = sections.find((s: any) => s.type === 'calendar')
      const ev = calendar?.data?.events?.[0]
      if (ev) {
        data.next_event_title = ev.title || ''
        data.next_event_time = ev.start_time || ''
      }
    }

    setWidgetData(data)
  } catch (e) {
    console.warn('[widgetBridge] refresh failed:', e)
  }
}
