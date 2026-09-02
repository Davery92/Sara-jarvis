import { requireOptionalNativeModule, type EventSubscription } from 'expo-modules-core'

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
  presence_state?: string
  presence_headline?: string
  presence_detail?: string
  presence_revision?: string
  presence_updated_at?: string
  presence_valid_until?: string
  next_event_title?: string
  next_event_time?: string // ISO8601
}

export interface LiveActivityTokenEvent {
  action: 'registered' | 'ended'
  activityId: string
  logicalId: string
  kind: 'task' | 'workout' | 'presence'
  pushToken?: string
}

export interface PendingShare {
  type: 'url' | 'text' | 'image'
  content: string // URL string, plain text, or (image) a container-relative path — consumed already, ignore
  content_base64?: string // present only for type 'image'
  note: string
  queued_at: string // ISO8601
}

interface SaraNativeModuleType {
  setWidgetData(data: Record<string, string>): void
  reloadWidgets(): void
  /** Reads & clears the prompt left by the "Ask Sara" Siri App Intent. */
  consumePendingSiriPrompt(): string | null
  /** Reads & clears whatever the share extension queued since last consumed. */
  consumePendingShares(): PendingShare[]
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
  syncEventActivityTokens(): void
  addListener(event: 'liveActivityToken', listener: (payload: LiveActivityTokenEvent) => void): EventSubscription
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

export function consumePendingShares(): PendingShare[] {
  return SaraNative?.consumePendingShares() ?? []
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

export function syncEventActivityTokens(): void {
  SaraNative?.syncEventActivityTokens()
}

export function subscribeToLiveActivityTokens(
  listener: (event: LiveActivityTokenEvent) => void
): () => void {
  const subscription = SaraNative?.addListener('liveActivityToken', listener)
  return () => subscription?.remove()
}

export default SaraNative
