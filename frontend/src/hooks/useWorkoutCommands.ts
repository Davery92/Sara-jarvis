/**
 * The web as a workout v2 controller.
 *
 * FITNESS_COACH_IMPLEMENTATION_PLAN Step 14. The hard requirement is
 * **exactly one accepted record per intent**, through a dropped connection,
 * a double tap, or a second device logging at the same moment.
 *
 * Three rules make that true, and all three are easy to get subtly wrong:
 *
 * 1. **One `command_id` per attempt, minted and persisted before the first
 *    send.** The server replays a known `command_id` and returns the stored
 *    result, so a retry of the *same* id is a no-op. A new id on retry is
 *    exactly how one set becomes two, which is why the id is stored in
 *    `sessionStorage` before `fetch` is called rather than generated inside
 *    the request.
 * 2. **A retry replays the byte-identical payload.** Re-reading the form
 *    would send whatever is on screen now, which may have changed.
 * 3. **A 409 never auto-retries.** The state moved, so the stored result is
 *    for a different baseline; the response carries the current projection
 *    and the athlete decides. Retrying through a conflict is how an edit
 *    gets silently overwritten.
 *
 * A durable acknowledgement is also independent of coaching prose: `logSet`
 * resolves when the set is committed. Any LLM-generated sentence arrives
 * later through the projection, so a model outage cannot stall logging.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'

import { APP_CONFIG } from '../config'
import { useAuthStore } from '../stores/authStore'
import {
  buildEnvelope,
  restRemainingSeconds,
  type CommandEnvelope,
  type PerformedSet,
  type WorkoutCommandKind,
  type WorkoutError,
  type WorkoutErrorKind,
  type WorkoutProjection,
} from '../types/workoutV2'

const BASE = `${APP_CONFIG.apiUrl}/api/fitness/workout-session/v2`

/**
 * Where in-flight command ids live.
 *
 * `sessionStorage`, not React state: a reload mid-request must reuse the
 * same id, and state does not survive one. Scoped per athlete so an account
 * change cannot replay someone else's command id.
 */
const PENDING_KEY = (userId: string) => `sara.workout.pending.${userId}`

interface PendingCommand {
  commandId: string
  kind: WorkoutCommandKind
  payload: Record<string, unknown>
  sessionId: string | null
  expectedVersion: number | null
  attempts: number
}

function readPending(userId: string): Record<string, PendingCommand> {
  try {
    const raw = window.sessionStorage.getItem(PENDING_KEY(userId))
    return raw ? (JSON.parse(raw) as Record<string, PendingCommand>) : {}
  } catch {
    // Private windows and blocked site data both throw here. Losing the
    // replay record is survivable (the worst case is a refused duplicate);
    // crashing the logger is not.
    return {}
  }
}

function writePending(userId: string, pending: Record<string, PendingCommand>): void {
  try {
    window.sessionStorage.setItem(PENDING_KEY(userId), JSON.stringify(pending))
  } catch {
    /* see readPending */
  }
}

export class WorkoutCommandError extends Error implements WorkoutError {
  kind: WorkoutErrorKind
  code?: string
  projection?: WorkoutProjection | null
  status?: number
  /** The envelope that failed, so the caller can retry it unchanged. */
  envelope?: CommandEnvelope

  constructor(error: WorkoutError & { envelope?: CommandEnvelope }) {
    super(error.message)
    this.name = 'WorkoutCommandError'
    this.kind = error.kind
    this.code = error.code
    this.projection = error.projection
    this.status = error.status
    this.envelope = error.envelope
  }
}

async function normalize(
  response: Response,
  envelope?: CommandEnvelope,
): Promise<WorkoutCommandError> {
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    /* a proxy's HTML error page must not become the message shown */
  }
  const detail = (body as { detail?: unknown } | null)?.detail

  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const d = detail as Record<string, unknown>
    // 404 and 409 mean different things and the UI branches on them: one is
    // a stale reference to drop, the other is state to reconcile.
    const kind: WorkoutErrorKind =
      response.status === 404 ? 'stale_reference'
      : response.status === 409 ? 'conflict'
      : response.status === 401 ? 'unauthenticated'
      : 'server'
    return new WorkoutCommandError({
      kind,
      status: response.status,
      code: typeof d.code === 'string' ? d.code : undefined,
      message: typeof d.message === 'string'
        ? d.message
        : 'That could not be applied.',
      projection: (d.projection as WorkoutProjection | null) ?? null,
      envelope,
    })
  }

  const messages: Record<WorkoutErrorKind, string> = {
    stale_reference: 'That is no longer part of this workout.',
    conflict: 'This workout changed on another device.',
    unauthenticated: 'You need to sign in again.',
    validation: 'That value was not accepted.',
    server: 'Sara could not record that. Nothing was saved.',
    network: 'Could not reach Sara.',
  }
  const kind: WorkoutErrorKind =
    response.status === 401 ? 'unauthenticated'
    : response.status === 404 ? 'stale_reference'
    : response.status === 409 ? 'conflict'
    : response.status === 400 || response.status === 422 ? 'validation'
    : 'server'
  return new WorkoutCommandError({
    kind,
    status: response.status,
    message: typeof detail === 'string' ? detail : messages[kind],
    envelope,
  })
}

async function post<T>(
  path: string,
  body: unknown,
  envelope?: CommandEnvelope,
): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    // A failed fetch is NOT a failed command: the request may well have been
    // applied and only the response lost. The caller retries the same
    // `command_id`, which the server replays rather than re-applying.
    throw new WorkoutCommandError({
      kind: 'network',
      message: 'Could not reach Sara. Retrying will not log this twice.',
      envelope,
    })
  }
  if (!response.ok) throw await normalize(response, envelope)
  return (await response.json()) as T
}

async function get<T>(path: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, { credentials: 'include' })
  } catch {
    throw new WorkoutCommandError({
      kind: 'network',
      message: 'Could not reach Sara.',
    })
  }
  if (!response.ok) throw await normalize(response)
  return (await response.json()) as T
}

export const workoutKeys = {
  active: (userId: string) => ['workout-v2', userId, 'active'] as const,
}

export interface UseWorkoutCommandsResult {
  projection: WorkoutProjection | null
  isLoading: boolean
  error: WorkoutCommandError | null
  /** A command whose outcome is unknown, so the UI can offer a retry. */
  unsentError: WorkoutCommandError | null
  isSending: boolean
  start: (templateId: string) => Promise<WorkoutProjection | null>
  logSet: (input: LogSetInput) => Promise<CommandResult>
  logDropSegment: (input: LogSetInput) => Promise<CommandResult>
  duplicateLastSet: () => Promise<CommandResult | null>
  voidSet: (setId: string, reason?: string) => Promise<CommandResult>
  reviseSet: (setId: string, input: LogSetInput) => Promise<CommandResult>
  selectExercise: (index: number) => Promise<CommandResult>
  addSet: (index?: number) => Promise<CommandResult>
  restStart: (seconds?: number) => Promise<CommandResult>
  restStop: () => Promise<CommandResult>
  finish: () => Promise<CommandResult>
  /** Resend the pending command, with its original id and payload. */
  retryPending: () => Promise<CommandResult | null>
  /** Give up on it, without pretending it did not happen. */
  dismissPending: () => void
  refresh: () => Promise<void>
  restRemaining: number | null
  /** Sets of the current exercise, newest first. Voided ones included. */
  currentExerciseSets: PerformedSet[]
}

export interface LogSetInput {
  exerciseIndex?: number
  /** Integer, for the legacy contract every client speaks. */
  weight?: number
  reps?: number
  /** The real load, where the athlete typed a fraction. */
  loadValue?: number
  loadUnit?: 'kg' | 'lb'
  rir?: number
  rpeDecimal?: number
  setRole?: 'top' | 'backoff' | 'amrap' | 'myo' | 'cluster' | 'straight'
  isFailure?: boolean
  setKind?: 'working' | 'warmup'
  notes?: string
  /** Start a second block of this exercise rather than extending the first. */
  newExerciseBlock?: boolean
}

export interface CommandResult {
  status?: string
  projection?: WorkoutProjection | null
  logged?: { id: string; [key: string]: unknown }
  [key: string]: unknown
}

function toPayload(input: LogSetInput): Record<string, unknown> {
  const payload: Record<string, unknown> = {}
  if (input.exerciseIndex !== undefined) payload.exercise_index = input.exerciseIndex
  if (input.weight !== undefined) payload.weight = input.weight
  if (input.reps !== undefined) payload.reps = input.reps
  if (input.loadValue !== undefined) payload.load_value = input.loadValue
  if (input.loadUnit !== undefined) payload.load_unit = input.loadUnit
  if (input.rir !== undefined) payload.rir = input.rir
  if (input.rpeDecimal !== undefined) payload.rpe_decimal = input.rpeDecimal
  if (input.setRole !== undefined) payload.set_role = input.setRole
  if (input.isFailure !== undefined) payload.is_failure = input.isFailure
  if (input.setKind !== undefined) payload.set_kind = input.setKind
  if (input.notes !== undefined) payload.notes = input.notes
  if (input.newExerciseBlock) payload.new_exercise_block = true
  return payload
}

export function useWorkoutCommands(): UseWorkoutCommandsResult {
  const userId = useAuthStore((state) => state.user?.id ?? null)
  const client = useQueryClient()
  const [unsentError, setUnsentError] = useState<WorkoutCommandError | null>(null)
  const [isSending, setIsSending] = useState(false)
  // The version is tracked in a ref as well as in the query data: two
  // commands issued in the same tick must not both send the stale version
  // from the last render.
  const versionRef = useRef<number | null>(null)

  const activeQuery: UseQueryResult<
    { projection: WorkoutProjection | null },
    WorkoutCommandError
  > = useQuery({
    queryKey: workoutKeys.active(userId ?? 'anonymous'),
    queryFn: () => get<{ projection: WorkoutProjection | null }>('/active'),
    enabled: Boolean(userId),
    // A second device can log at any moment, so the projection is refetched
    // on focus. Not polled: during a set the athlete is holding a bar, and
    // a background refetch that clobbered their typing would be worse than
    // a slightly stale read.
    refetchOnWindowFocus: true,
    staleTime: 5_000,
  })

  const projection = activeQuery.data?.projection ?? null
  useEffect(() => {
    if (projection) versionRef.current = projection.version
  }, [projection])

  const applyProjection = useCallback(
    (next: WorkoutProjection | null | undefined) => {
      if (!userId || next === undefined) return
      if (next) versionRef.current = next.version
      client.setQueryData(workoutKeys.active(userId), { projection: next ?? null })
    },
    [client, userId],
  )

  const refresh = useCallback(async () => {
    if (!userId) return
    const fresh = await get<{ projection: WorkoutProjection | null }>('/active')
    applyProjection(fresh.projection)
  }, [applyProjection, userId])

  /**
   * Send one command, with a durable id.
   *
   * The id is written to `sessionStorage` before the request leaves, so a
   * reload or a dropped connection mid-flight can resend exactly this
   * command. On success it is removed. On a network failure it stays, and
   * `retryPending` resends the identical envelope.
   */
  const send = useCallback(
    async (
      kind: WorkoutCommandKind,
      payload: Record<string, unknown>,
      options: { commandId?: string } = {},
    ): Promise<CommandResult> => {
      if (!userId) {
        throw new WorkoutCommandError({
          kind: 'unauthenticated',
          message: 'You need to sign in again.',
        })
      }

      const commandId = options.commandId ?? crypto.randomUUID()
      const sessionId = projection?.session_id ?? null
      const expectedVersion = versionRef.current

      const pending = readPending(userId)
      const record: PendingCommand = {
        commandId,
        kind,
        payload,
        sessionId,
        expectedVersion,
        attempts: (pending[commandId]?.attempts ?? 0) + 1,
      }
      pending[commandId] = record
      writePending(userId, pending)

      const envelope = buildEnvelope(kind, commandId, {
        sessionId,
        expectedVersion,
        payload,
      })

      setIsSending(true)
      try {
        const result = await post<CommandResult>('/commands', envelope, envelope)
        applyProjection(result.projection as WorkoutProjection | null | undefined)
        const after = readPending(userId)
        delete after[commandId]
        writePending(userId, after)
        setUnsentError(null)
        return result
      } catch (error) {
        const failure = error as WorkoutCommandError

        if (failure.kind === 'conflict' || failure.kind === 'stale_reference') {
          // The state moved. The stored result would be for a different
          // baseline, so this command is finished — not retryable. Adopt the
          // projection the server sent so the athlete sees the real state
          // rather than a blind retry overwriting someone's edit.
          const resolved = readPending(userId)
          delete resolved[commandId]
          writePending(userId, resolved)
          if (failure.projection) applyProjection(failure.projection)
          else await refresh().catch(() => undefined)
          setUnsentError(null)
          throw failure
        }

        if (failure.kind === 'network') {
          // The outcome is genuinely unknown: the command may have applied
          // and only the reply been lost. Keep the envelope so a retry
          // resends the same id, which the server replays instead of
          // re-applying.
          setUnsentError(failure)
          throw failure
        }

        const dropped = readPending(userId)
        delete dropped[commandId]
        writePending(userId, dropped)
        throw failure
      } finally {
        setIsSending(false)
      }
    },
    [applyProjection, projection, refresh, userId],
  )

  const retryPending = useCallback(async (): Promise<CommandResult | null> => {
    if (!userId) return null
    const envelope = unsentError?.envelope
    if (!envelope) return null
    // The SAME id and the SAME payload. Re-reading the form would send what
    // is on screen now, which may have changed since the attempt.
    return send(envelope.kind, envelope.payload, { commandId: envelope.command_id })
  }, [send, unsentError, userId])

  const dismissPending = useCallback(() => {
    if (userId && unsentError?.envelope) {
      const pending = readPending(userId)
      delete pending[unsentError.envelope.command_id]
      writePending(userId, pending)
    }
    setUnsentError(null)
  }, [unsentError, userId])

  const startMutation = useMutation({
    mutationFn: async (templateId: string) => {
      // `start_attempt_id` is the same idea as `command_id`: a retry through
      // a dropped link must resume rather than create a second workout.
      const attemptId = crypto.randomUUID()
      return post<{ projection: WorkoutProjection | null }>('/start', {
        template_id: templateId,
        start_attempt_id: attemptId,
        origin_device: 'web',
      })
    },
    onSuccess: (result) => applyProjection(result.projection),
    retry: false,
  })

  const currentExerciseSets = useMemo(() => {
    if (!projection?.current_exercise) return []
    const name = projection.current_exercise.variant
      || projection.current_exercise.name
    if (!name) return []
    return projection.performed_sets
      .filter((set) => set.exercise === name)
      .slice()
      .reverse()
  }, [projection])

  const duplicateLastSet = useCallback(async (): Promise<CommandResult | null> => {
    // The last LIVE working set of this exercise. A voided set is one the
    // athlete said did not happen, so repeating it would re-log work they
    // just retracted.
    const last = currentExerciseSets.find(
      (set) => !set.voided && set.set_kind === 'working',
    )
    if (!last) return null
    return send('log_set', {
      exercise_index: projection?.cursor.exercise_index ?? 0,
      weight: last.weight,
      reps: last.reps,
      ...(last.rpe !== null ? { rpe: last.rpe } : {}),
    })
  }, [currentExerciseSets, projection, send])

  const [restNow, setRestNow] = useState(() => Date.now())
  useEffect(() => {
    if (!projection?.rest.active) return
    const timer = window.setInterval(() => setRestNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [projection?.rest.active])

  const restRemaining = projection
    // From the SERVER's start time. A locally derived start makes the timer
    // disagree between two devices watching the same set.
    ? restRemainingSeconds(projection.rest, restNow)
    : null

  return {
    projection,
    isLoading: activeQuery.isLoading,
    error: (activeQuery.error as WorkoutCommandError | null) ?? null,
    unsentError,
    isSending,
    start: async (templateId: string) => {
      const result = await startMutation.mutateAsync(templateId)
      return result.projection
    },
    logSet: (input: LogSetInput) => send('log_set', toPayload(input)),
    logDropSegment: (input: LogSetInput) =>
      send('log_drop_segment', toPayload(input)),
    duplicateLastSet,
    voidSet: (setId: string, reason?: string) =>
      send('void_set', { set_id: setId, ...(reason ? { reason } : {}) }),
    reviseSet: (setId: string, input: LogSetInput) =>
      send('revise_set', { set_id: setId, ...toPayload(input) }),
    selectExercise: (index: number) =>
      send('select_exercise', { exercise_index: index }),
    addSet: (index?: number) =>
      send('add_set', index === undefined ? {} : { exercise_index: index }),
    restStart: (seconds?: number) =>
      send('rest_start', seconds === undefined ? {} : { duration_seconds: seconds }),
    restStop: () => send('rest_stop', {}),
    finish: () => send('complete', {}),
    retryPending,
    dismissPending,
    refresh,
    restRemaining,
    currentExerciseSets,
  }
}
