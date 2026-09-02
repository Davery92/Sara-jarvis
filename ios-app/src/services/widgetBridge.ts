/**
 * widgetBridge — pushes Sara's state into the App Group so WidgetKit can render
 * it on the home & lock screens (P3).
 *
 * Pulls a revisioned, expiring presence projection maintained by the server.
 * A widget cache is a delivery surface, never the source of Sara's state.
 */
import { apiClient } from './api'
import { setWidgetData, isAvailable, type WidgetData } from '../../modules/sara-native'

export async function refreshWidgetData(): Promise<void> {
  if (!isAvailable()) return
  try {
    const [presenceRes, briefRes] = await Promise.allSettled([
      apiClient.get<any>('/api/world-state/presence'),
      apiClient.get<any>('/api/sara/brief'),
    ])

    // Send every field, including empty strings, so old cached values are
    // cleared instead of surviving forever after the server omits a field.
    const data: WidgetData = {
      presence_state: 'resting', presence_headline: 'Available', presence_detail: '',
      presence_revision: '0', presence_updated_at: new Date().toISOString(),
      presence_valid_until: new Date(Date.now() + 5 * 60_000).toISOString(),
      next_event_title: '', next_event_time: '',
    }
    if (presenceRes.status === 'fulfilled' && presenceRes.value) {
      const presence = presenceRes.value
      data.presence_state = String(presence.state || 'resting')
      data.presence_headline = String(presence.headline || 'Available').slice(0, 160)
      data.presence_detail = String(presence.detail || '').slice(0, 240)
      data.presence_revision = String(presence.revision || 0)
      data.presence_updated_at = String(presence.updated_at || new Date().toISOString())
      data.presence_valid_until = String(presence.valid_until || data.presence_valid_until)
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
