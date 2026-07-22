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
    const [statusRes, briefRes, mindRes] = await Promise.allSettled([
      apiClient.get<any>('/api/sara/status'),
      apiClient.get<any>('/api/sara/brief'),
      // The global workspace synthesis (§3.1) — what Sara is holding in mind
      // right now. This is the "she's alive" surface (§5.2.5): the widget shows
      // her live internal state (prediction violations, open loops, concern),
      // not a static thought.
      apiClient.get<any>('/api/mind/anything-i-should-know'),
    ])

    const data: WidgetData = {}

    // Sara's actual first-person thought (the daemon's journal voice) is the
    // best widget line — warm and conversational ("You just got home — quiet
    // evening, holding off until you're settled"). Keep it as primary.
    const GENERIC = /^(keeping an eye|here when you need|resting between)/i
    let thought = ''
    if (statusRes.status === 'fulfilled' && statusRes.value) {
      data.emotional_state = statusRes.value.emotional_state || 'neutral'
      if (statusRes.value.latest_thought) {
        thought = String(statusRes.value.latest_thought).trim()
      }
    }
    // Only fall back to the workspace synthesis when she has no real thought to
    // show (avoids replacing a warm line with mechanical "predictions violated"
    // plumbing).
    if ((!thought || GENERIC.test(thought)) && mindRes.status === 'fulfilled' && mindRes.value?.summary) {
      const s = String(mindRes.value.summary).trim()
      if (s && !/^nothing pressing/i.test(s)) thought = s
    }
    if (thought) data.latest_thought = thought.slice(0, 140)

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
