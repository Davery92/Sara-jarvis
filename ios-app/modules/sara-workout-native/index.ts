import { requireOptionalNativeModule } from 'expo-modules-core'
import { EventSubscription } from 'expo-modules-core'

/**
 * SaraWorkoutNative — the iPhone side of the multidevice workout (plan §7.2).
 *
 * Two things JS cannot do for itself:
 *
 *  1. Own the mirrored `HKWorkoutSession`. A workout started on the Watch
 *     arrives through a HealthKit handler that fires whether or not the React
 *     tree is alive, so registering it has to happen in native code.
 *  2. Duck other audio for a spoken prompt. Coaching has to work with the phone
 *     locked or showing YouTube Music, where the JS runtime is not scheduled.
 *
 * `requireOptionalNativeModule` returns null on Android / Expo Go / web, so
 * every export here degrades to a no-op rather than throwing — the phone
 * workout must keep working without any of this (§16.2).
 */

export interface NativeWorkoutState {
  mirroring: boolean
  state: 'none' | 'notStarted' | 'prepared' | 'running' | 'paused' | 'stopped' | 'ended' | 'failed' | 'unsupported' | 'unknown'
  activityType?: number
  startDate?: number
  pendingMessages?: number
  error?: string
}

export interface WorkoutMessageEvent {
  /** Raw JSON envelope. Parsed by `workoutContracts`, never here. */
  envelope: string
  kind: string
  sessionId?: string | null
  schemaVersion: number
  /** False when the peer is on a newer contract — drop, don't guess (§5.3). */
  supported: boolean
}

export interface LiveMetricsEvent {
  envelope: string
}

export interface MirrorStateEvent extends NativeWorkoutState {
  changedAt?: number
}

export interface CoachingPlaybackEvent {
  eventId: string
  state: 'started' | 'finished' | 'failed' | 'dropped' | 'restore_failed'
  error?: string | null
}

interface SaraWorkoutNativeModuleType {
  activate(): boolean
  isSupported(): boolean
  startWorkoutOnWatch(activityType: number, locationType: number): Promise<{ requested: boolean }>
  sendWorkoutMessage(envelopeJSON: string): Promise<boolean>
  getMirroredWorkoutState(): NativeWorkoutState
  endMirroredWorkout(reason: string): Promise<boolean>
  setWorkoutAudioPolicy(enabled: boolean): boolean
  speakCoaching(
    eventId: string,
    text: string,
    priority: string,
    expiresAtEpochMs: number | null,
    proposalId: string | null,
    audioBase64: string | null
  ): boolean
  suppressCoachingForProposal(proposalId: string): void
  cancelCoaching(reason: string): void
  addListener(event: string, listener: (payload: any) => void): EventSubscription
}

const SaraWorkoutNative = requireOptionalNativeModule<SaraWorkoutNativeModuleType>('SaraWorkoutNative')

/** HKWorkoutActivityType raw values, so callers don't hardcode magic numbers. */
export const HKActivityType = {
  traditionalStrengthTraining: 50,
  functionalStrengthTraining: 20,
  highIntensityIntervalTraining: 63,
  running: 37,
  cycling: 13,
  rowing: 35,
  walking: 52,
} as const

/** HKWorkoutSessionLocationType. Indoor is right for a gym. */
export const HKLocationType = { unknown: 1, indoor: 2, outdoor: 3 } as const

export function isAvailable(): boolean {
  return SaraWorkoutNative != null && SaraWorkoutNative.isSupported()
}

/**
 * Install the mirror handler. Call once, as early after auth as possible.
 *
 * If this has not run, a workout David starts on his Watch is invisible to the
 * phone until the app is next opened — which is the exact failure the whole
 * feature exists to remove.
 */
export function activate(): boolean {
  return SaraWorkoutNative?.activate() ?? false
}

/**
 * Ask the Watch to begin the primary workout session.
 *
 * Resolves when the Watch has been *asked*, not when it is tracking. Tracking
 * is confirmed by a `mirrorStateChanged` event; conflating the two is what
 * §4.3's partial-success handling exists to prevent.
 */
export async function startWorkoutOnWatch(
  activityType: number = HKActivityType.traditionalStrengthTraining,
  locationType: number = HKLocationType.indoor
): Promise<{ requested: boolean }> {
  if (!SaraWorkoutNative) return { requested: false }
  return SaraWorkoutNative.startWorkoutOnWatch(activityType, locationType)
}

export async function sendWorkoutMessage(envelope: unknown): Promise<boolean> {
  if (!SaraWorkoutNative) return false
  return SaraWorkoutNative.sendWorkoutMessage(JSON.stringify(envelope))
}

export function getMirroredWorkoutState(): NativeWorkoutState {
  return SaraWorkoutNative?.getMirroredWorkoutState() ?? { mirroring: false, state: 'unsupported' }
}

export async function endMirroredWorkout(reason: string): Promise<boolean> {
  if (!SaraWorkoutNative) return false
  return SaraWorkoutNative.endMirroredWorkout(reason)
}

// ── Coaching audio (§10) ──────────────────────────────────────────────────

export function setWorkoutAudioPolicy(enabled: boolean): boolean {
  return SaraWorkoutNative?.setWorkoutAudioPolicy(enabled) ?? false
}

/**
 * Queue one short spoken prompt. Returns immediately — speech must never gate
 * a logged set (§6.7).
 *
 * `audioBase64` is pre-fetched Sara/Kokoro audio so coaching sounds like the
 * same Sara as chat; without it the on-device voice reads `text`.
 */
export function speakCoaching(opts: {
  eventId: string
  text: string
  priority?: string
  expiresAt?: string | null
  /** Set when this prompt asks for a decision, so it can be dropped once answered. */
  proposalId?: string | null
  audioBase64?: string | null
}): boolean {
  if (!SaraWorkoutNative) return false
  const expiresMs = opts.expiresAt ? Date.parse(opts.expiresAt) : NaN
  return SaraWorkoutNative.speakCoaching(
    opts.eventId,
    opts.text,
    opts.priority ?? 'normal',
    Number.isFinite(expiresMs) ? expiresMs : null,
    opts.proposalId ?? null,
    opts.audioBase64 ?? null
  )
}

/** Stop speaking about a proposal David has already answered (§10.4). */
export function suppressCoachingForProposal(proposalId: string): void {
  SaraWorkoutNative?.suppressCoachingForProposal(proposalId)
}

export function cancelCoaching(reason: string): void {
  SaraWorkoutNative?.cancelCoaching(reason)
}

// ── Events ────────────────────────────────────────────────────────────────

function subscribe<T>(event: string, handler: (payload: T) => void): () => void {
  const sub = SaraWorkoutNative?.addListener(event, handler)
  return () => sub?.remove()
}

export const addWorkoutMessageListener = (h: (e: WorkoutMessageEvent) => void) =>
  subscribe('workoutMessage', h)

export const addLiveMetricsListener = (h: (e: LiveMetricsEvent) => void) =>
  subscribe('liveMetrics', h)

export const addMirrorStateListener = (h: (e: MirrorStateEvent) => void) =>
  subscribe('mirrorStateChanged', h)

export const addCoachingPlaybackListener = (h: (e: CoachingPlaybackEvent) => void) =>
  subscribe('coachingPlaybackChanged', h)
