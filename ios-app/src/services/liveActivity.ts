/**
 * liveActivity — thin JS wrapper over the SaraNative ActivityKit bridge (P3).
 *
 * Drives the timer Live Activity (lock screen + Dynamic Island). No-ops safely
 * when the native module or Live Activities aren't available (Android, Expo Go,
 * iOS < 16.2, or the user disabled them).
 */
import {
  isAvailable,
  areActivitiesEnabled,
  startTimerActivity,
  endTimerActivity,
  endAllActivities,
} from '../../modules/sara-native'

export function startTimerLiveActivity(
  timerId: string,
  title: string,
  endEpochMs: number
): string | null {
  const available = isAvailable()
  const enabled = available && areActivitiesEnabled()
  console.log(
    `[LiveActivity] start request: module=${available} enabled=${enabled} timer=${timerId} endsIn=${Math.round((endEpochMs - Date.now()) / 1000)}s`
  )
  if (!available) {
    console.warn('[LiveActivity] SaraNative module not present — skipping (needs the native build).')
    return null
  }
  if (!enabled) {
    console.warn('[LiveActivity] Live Activities not enabled (system/app setting off).')
    return null
  }
  try {
    const id = startTimerActivity(timerId, title || 'Timer', endEpochMs)
    console.log('[LiveActivity] started, activity id:', id)
    return id
  } catch (e) {
    console.warn('[LiveActivity] start failed:', e)
    return null
  }
}

export function endTimerLiveActivity(timerId: string): void {
  if (!isAvailable()) return
  try {
    endTimerActivity(timerId)
  } catch (e) {
    console.warn('[LiveActivity] end failed:', e)
  }
}

export function endAllTimerLiveActivities(): void {
  if (!isAvailable()) return
  try {
    endAllActivities()
  } catch {
    /* ignore */
  }
}
