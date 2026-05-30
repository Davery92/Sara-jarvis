import { requireOptionalNativeModule } from 'expo-modules-core'

/**
 * SaraNative — local Expo module for iOS system integration (P3).
 *
 * Two jobs the JS layer can't do alone:
 *  1. Write widget data into the App Group so WidgetKit can read it.
 *  2. Start / update / end ActivityKit Live Activities (e.g. timers).
 *
 * `requireOptionalNativeModule` returns null when the native side isn't present
 * (Android, Expo Go, web), so callers degrade gracefully.
 */

export interface WidgetData {
  emotional_state?: string
  latest_thought?: string
  next_event_title?: string
  next_event_time?: string // ISO8601
}

interface SaraNativeModuleType {
  setWidgetData(data: Record<string, string>): void
  reloadWidgets(): void
  areActivitiesEnabled(): boolean
  /** Returns the ActivityKit activity id, or null on failure / unsupported. */
  startTimerActivity(timerId: string, title: string, endEpochMs: number): string | null
  endTimerActivity(timerId: string): void
  endAllActivities(): void
}

const SaraNative = requireOptionalNativeModule<SaraNativeModuleType>('SaraNative')

export function isAvailable(): boolean {
  return SaraNative != null
}

export function setWidgetData(data: WidgetData): void {
  if (!SaraNative) return
  // Native side stores strings; drop undefined keys.
  const flat: Record<string, string> = {}
  for (const [k, v] of Object.entries(data)) {
    if (v != null) flat[k] = String(v)
  }
  SaraNative.setWidgetData(flat)
}

export function areActivitiesEnabled(): boolean {
  return SaraNative?.areActivitiesEnabled() ?? false
}

export function startTimerActivity(timerId: string, title: string, endEpochMs: number): string | null {
  return SaraNative?.startTimerActivity(timerId, title, endEpochMs) ?? null
}

export function endTimerActivity(timerId: string): void {
  SaraNative?.endTimerActivity(timerId)
}

export function endAllActivities(): void {
  SaraNative?.endAllActivities()
}

export default SaraNative
