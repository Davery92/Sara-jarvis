/**
 * eventActivity — JS wrapper over the SaraNative generic Live Activity bridge.
 *
 * Powers the workout ("count-up") and background-task ("Sara is working on…")
 * Live Activities. No-ops safely when the native module / Live Activities aren't
 * available.
 */
import {
  isAvailable,
  areActivitiesEnabled,
  startEventActivity,
  updateEventActivity,
  endEventActivity,
} from '../../modules/sara-native'

export type EventKind = 'workout' | 'task'

export function startEvent(
  id: string,
  kind: EventKind,
  title: string,
  subtitle: string,
  startEpochMs: number
): void {
  if (!isAvailable() || !areActivitiesEnabled()) return
  try {
    startEventActivity(id, kind, title || (kind === 'workout' ? 'Workout' : 'Sara'), subtitle, startEpochMs)
  } catch (e) {
    console.warn('[EventActivity] start failed:', e)
  }
}

export function updateEvent(id: string, subtitle: string, startEpochMs = 0): void {
  if (!isAvailable()) return
  try {
    updateEventActivity(id, subtitle, startEpochMs)
  } catch {
    /* ignore */
  }
}

export function endEvent(id: string): void {
  if (!isAvailable()) return
  try {
    endEventActivity(id)
  } catch {
    /* ignore */
  }
}
