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
  /** Reads & clears the prompt left by the "Ask Sara" Siri App Intent. */
  consumePendingSiriPrompt(): string | null
  areActivitiesEnabled(): boolean
  /** Returns the ActivityKit activity id, or null on failure / unsupported. */
  startTimerActivity(timerId: string, title: string, endEpochMs: number): string | null
  endTimerActivity(timerId: string): void
  endAllActivities(): void
  // Generic ongoing-event activities (workouts, background tasks)
  startEventActivity(id: string, kind: string, title: string, subtitle: string, startEpochMs: number): string | null
  updateEventActivity(id: string, subtitle: string, startEpochMs: number): void
  endEventActivity(id: string): void
  /** Ends every event activity of the given kind ('' = all kinds). */
  endAllEventActivities(kind: string): void
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

export function consumePendingSiriPrompt(): string | null {
  return SaraNative?.consumePendingSiriPrompt() ?? null
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

export function startEventActivity(
  id: string,
  kind: 'workout' | 'task',
  title: string,
  subtitle: string,
  startEpochMs: number
): string | null {
  return SaraNative?.startEventActivity(id, kind, title, subtitle, startEpochMs) ?? null
}

export function updateEventActivity(id: string, subtitle: string, startEpochMs: number): void {
  SaraNative?.updateEventActivity(id, subtitle, startEpochMs)
}

export function endEventActivity(id: string): void {
  SaraNative?.endEventActivity(id)
}

export function endAllEventActivities(kind: 'workout' | 'task' | ''): void {
  SaraNative?.endAllEventActivities(kind)
}

export default SaraNative
