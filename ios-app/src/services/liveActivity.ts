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
  if (!isAvailable() || !areActivitiesEnabled()) return null
  try {
    return startTimerActivity(timerId, title || 'Timer', endEpochMs)
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
