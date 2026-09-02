import * as Device from 'expo-device'
import apiClient from './api'
import {
  subscribeToLiveActivityTokens,
  syncEventActivityTokens,
  type LiveActivityTokenEvent,
} from '../../modules/sara-native'

let unsubscribe: (() => void) | null = null

async function handleToken(event: LiveActivityTokenEvent): Promise<void> {
  try {
    if (event.action === 'ended') {
      await apiClient.delete(`/api/live-activities/${encodeURIComponent(event.activityId)}`)
      return
    }
    if (!event.pushToken) return
    await apiClient.post('/api/live-activities/register', {
      activity_id: event.activityId,
      logical_id: event.logicalId,
      kind: event.kind,
      push_token: event.pushToken,
      device_name: Device.deviceName || 'iPhone',
      environment: __DEV__ ? 'sandbox' : 'production',
    })
  } catch (error) {
    console.warn('[LiveActivityDelivery] token registration failed:', error)
  }
}

/** Install before any activity starts; also re-emits tokens for restored ones. */
export function activateLiveActivityDelivery(): void {
  if (unsubscribe) return
  unsubscribe = subscribeToLiveActivityTokens((event) => {
    void handleToken(event)
  })
  syncEventActivityTokens()
}

export function deactivateLiveActivityDelivery(): void {
  unsubscribe?.()
  unsubscribe = null
}
