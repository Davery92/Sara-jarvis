/**
 * Step 14 of FITNESS_COACH_IMPLEMENTATION_PLAN: the web as a reliable v2
 * controller.
 *
 * The one requirement everything else serves: **exactly one accepted record
 * per intent**, through a dropped connection, a double tap, or a second
 * device logging at the same moment.
 *
 * What the tests below actually pin:
 *
 * - A retry sends the **same** `command_id` and the **same** payload. A new
 *   id on retry is how one set becomes two; re-reading the form on retry
 *   sends whatever is on screen now rather than what was attempted.
 * - A 409 does not auto-retry. The server's stored result is for a different
 *   baseline, so a blind retry overwrites whatever moved.
 * - The command id is persisted **before** the request leaves, so a reload
 *   mid-flight can still resend the same one.
 * - Rest countdown comes from the server's start time, so two devices
 *   watching the same set agree.
 * - A model being down cannot stall logging: the acknowledgement is the
 *   commit.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useWorkoutCommands } from '../../../hooks/useWorkoutCommands'
import {
  buildEnvelope,
  isProjectionStale,
  restRemainingSeconds,
  WORKOUT_SCHEMA_VERSION,
  type WorkoutProjection,
} from '../../../types/workoutV2'

const ATHLETE = 'athlete-logging'

vi.mock('../../../stores/authStore', () => ({
  useAuthStore: (selector: (s: unknown) => unknown) =>
    selector({ user: { id: ATHLETE, email: 'a@example.invalid' } }),
}))

function projection(overrides: Partial<WorkoutProjection> = {}): WorkoutProjection {
  return {
    schema_version: WORKOUT_SCHEMA_VERSION,
    session_id: 'session-1',
    version: 4,
    status: 'active',
    started_at: '2026-10-01T16:00:00Z',
    origin_device: 'web',
    template: { id: 'tmpl-1', name: 'Push A', is_deload: false },
    cursor: { exercise_index: 0, set_index: 1 },
    progress: { completed_sets: 1, total_sets: 9, total_volume: 1125 },
    current_exercise: {
      name: 'Bench Press',
      variant: null,
      target_sets: 3,
      prescribed_sets: 3,
      target_reps: '5',
      target_rpe: 8,
      approved_weight: 225,
      calculated_suggestion: 230,
      completed_sets: 1,
      last_session: { weights: [225], reps: [5] },
      progression_note: null,
    },
    performed_sets: [
      {
        id: 'set-1', exercise: 'Bench Press', set_index: 1,
        weight: 225, reps: 5, rpe: 8, notes: null, is_pr: false,
        set_kind: 'working', parent_set_id: null, set_group_id: 'set-1',
        group_sequence: 0, counts_toward_target: true, voided: false,
        void_reason: null, revised_from_set_id: null,
        logged_at: '2026-10-01T16:05:00Z',
      },
    ],
    exercises: [],
    rest: { active: false, started_at: null, duration_seconds: null },
    pending_proposal: null,
    updated_at: '2026-10-01T16:05:00Z',
    ...overrides,
  }
}

type Json = Record<string, unknown>
interface Call { url: string; method: string; body: Json | null }

let calls: Call[] = []
let handlers: Array<{
  match: (url: string, method: string) => boolean
  respond: (body: Json | null) => { status: number; body: unknown } | Promise<{ status: number; body: unknown }>
}> = []

function stubFetch() {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    const body = init?.body ? (JSON.parse(String(init.body)) as Json) : null
    calls.push({ url, method, body })
    for (const handler of handlers) {
      if (handler.match(url, method)) {
        const { status, body: out } = await handler.respond(body)
        return new Response(JSON.stringify(out), {
          status, headers: { 'Content-Type': 'application/json' },
        })
      }
    }
    return new Response(JSON.stringify({ projection: null }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }) as unknown as typeof fetch
}

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

const activeHandler = (p: WorkoutProjection | null) => ({
  match: (url: string, method: string) => url.endsWith('/v2/active') && method === 'GET',
  respond: () => ({ status: 200, body: { projection: p } }),
})

function pendingStore(): Record<string, unknown> {
  const raw = window.sessionStorage.getItem(`sara.workout.pending.${ATHLETE}`)
  return raw ? (JSON.parse(raw) as Record<string, unknown>) : {}
}

beforeEach(() => {
  calls = []
  handlers = []
  window.sessionStorage.clear()
  stubFetch()
})

// ── Pure helpers ──────────────────────────────────────────────────────────

describe('workout v2 contract helpers', () => {
  it('builds an envelope with the id the caller already persisted', () => {
    const envelope = buildEnvelope('log_set', 'command-abc', {
      sessionId: 'session-1', expectedVersion: 4,
      payload: { weight: 225, reps: 5 },
    })
    expect(envelope).toMatchObject({
      schema_version: WORKOUT_SCHEMA_VERSION,
      command_id: 'command-abc',
      session_id: 'session-1',
      expected_version: 4,
      origin_device: 'web',
      kind: 'log_set',
      payload: { weight: 225, reps: 5 },
    })
    // The id is a parameter, not generated here: the caller has to persist it
    // before the first send so a retry can reuse it.
    expect(buildEnvelope('log_set', 'command-abc').command_id).toBe('command-abc')
  })

  it('computes rest from the servers start time, not the clients', () => {
    const started = '2026-10-01T16:00:00Z'
    const now = Date.parse('2026-10-01T16:00:40Z')
    expect(restRemainingSeconds(
      { active: true, started_at: started, duration_seconds: 120 }, now,
    )).toBe(80)
    // Inactive, missing start and missing duration all mean "no countdown",
    // not "zero seconds left".
    expect(restRemainingSeconds(
      { active: false, started_at: started, duration_seconds: 120 }, now,
    )).toBeNull()
    expect(restRemainingSeconds(
      { active: true, started_at: null, duration_seconds: 120 }, now,
    )).toBeNull()
    expect(restRemainingSeconds(
      { active: true, started_at: started, duration_seconds: null }, now,
    )).toBeNull()
    // Never negative.
    expect(restRemainingSeconds(
      { active: true, started_at: started, duration_seconds: 10 },
      Date.parse('2026-10-01T16:05:00Z'),
    )).toBe(0)
  })

  it('detects a projection that is behind the server', () => {
    const held = projection({ version: 4 })
    expect(isProjectionStale(held, 6)).toBe(true)
    expect(isProjectionStale(held, 4)).toBe(false)
    expect(isProjectionStale(null, 6)).toBe(false)
    expect(isProjectionStale(held, null)).toBe(false)
  })
})

// ── Logging ───────────────────────────────────────────────────────────────

describe('useWorkoutCommands', () => {
  it('logs a set with the session id and the current version', async () => {
    handlers = [
      activeHandler(projection()),
      {
        match: (url, method) => url.endsWith('/v2/commands') && method === 'POST',
        respond: (body) => ({
          status: 200,
          body: {
            status: 'accepted',
            logged: { id: 'set-2' },
            projection: projection({ version: 5 }),
          },
        }),
      },
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())

    await act(async () => {
      await result.current.logSet({ exerciseIndex: 0, weight: 225, reps: 5 })
    })

    const command = calls.find((c) => c.url.endsWith('/v2/commands'))!
    expect(command.body).toMatchObject({
      schema_version: WORKOUT_SCHEMA_VERSION,
      session_id: 'session-1',
      expected_version: 4,
      origin_device: 'web',
      kind: 'log_set',
      payload: { exercise_index: 0, weight: 225, reps: 5 },
    })
    expect(typeof command.body!.command_id).toBe('string')
    // The response's projection is adopted, so the next command carries the
    // new version rather than the stale one.
    await waitFor(() => expect(result.current.projection?.version).toBe(5))
  })

  it('sends a fractional load and effort when the athlete typed them', async () => {
    handlers = [
      activeHandler(projection()),
      {
        match: (url, method) => url.endsWith('/v2/commands') && method === 'POST',
        respond: () => ({
          status: 200,
          body: { status: 'accepted', logged: { id: 'set-2' }, projection: projection() },
        }),
      },
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())

    await act(async () => {
      await result.current.logSet({
        exerciseIndex: 0, weight: 227, reps: 5,
        loadValue: 227.5, loadUnit: 'lb', rir: 2, setRole: 'top',
      })
    })
    const command = calls.find((c) => c.url.endsWith('/v2/commands'))!
    expect(command.body!.payload).toEqual({
      exercise_index: 0, weight: 227, reps: 5,
      load_value: 227.5, load_unit: 'lb', rir: 2, set_role: 'top',
    })
  })

  it('omits fields the athlete did not supply', async () => {
    handlers = [
      activeHandler(projection()),
      {
        match: (url, method) => url.endsWith('/v2/commands') && method === 'POST',
        respond: () => ({
          status: 200,
          body: { status: 'accepted', projection: projection() },
        }),
      },
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())

    await act(async () => {
      await result.current.logSet({ weight: 225, reps: 5 })
    })
    const payload = calls.find((c) => c.url.endsWith('/v2/commands'))!.body!.payload as Json
    expect(Object.keys(payload).sort()).toEqual(['reps', 'weight'])
  })

  it('persists the command id before the request leaves', async () => {
    let seenPendingDuringRequest: Record<string, unknown> = {}
    handlers = [
      activeHandler(projection()),
      {
        match: (url, method) => url.endsWith('/v2/commands') && method === 'POST',
        respond: () => {
          // Read at the moment the server would be processing it: a reload
          // here has to be able to resend the same id.
          seenPendingDuringRequest = pendingStore()
          return {
            status: 200,
            body: { status: 'accepted', projection: projection({ version: 5 }) },
          }
        },
      },
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())

    await act(async () => {
      await result.current.logSet({ weight: 225, reps: 5 })
    })

    const ids = Object.keys(seenPendingDuringRequest)
    expect(ids).toHaveLength(1)
    const sent = calls.find((c) => c.url.endsWith('/v2/commands'))!.body!.command_id
    expect(ids[0]).toBe(sent)
    // Cleared once the outcome is known.
    expect(Object.keys(pendingStore())).toHaveLength(0)
  })

  // ── Retry ───────────────────────────────────────────────────────────────

  it('retries a dropped request with the same id and payload', async () => {
    // The acid test for "exactly one accepted record". The first attempt's
    // reply is lost, so the client cannot know whether it applied.
    let attempt = 0
    handlers = [
      activeHandler(projection()),
      {
        match: (url, method) => url.endsWith('/v2/commands') && method === 'POST',
        respond: () => {
          attempt += 1
          if (attempt === 1) throw new TypeError('Failed to fetch')
          return {
            status: 200,
            body: {
              // The server recognises the id and replays rather than
              // re-applying — which is why reusing it is safe.
              status: 'replayed',
              logged: { id: 'set-2' },
              projection: projection({ version: 5 }),
            },
          }
        },
      },
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())

    await act(async () => {
      await result.current
        .logSet({ exerciseIndex: 0, weight: 225, reps: 5 })
        .catch(() => undefined)
    })

    await waitFor(() => expect(result.current.unsentError).not.toBeNull())
    expect(result.current.unsentError!.kind).toBe('network')
    expect(result.current.unsentError!.message).toMatch(/will not log this twice/i)
    // The envelope is still on record, so the retry can be byte-identical.
    expect(Object.keys(pendingStore())).toHaveLength(1)

    await act(async () => {
      await result.current.retryPending()
    })

    const commands = calls.filter((c) => c.url.endsWith('/v2/commands'))
    expect(commands).toHaveLength(2)
    expect(commands[1].body!.command_id).toBe(commands[0].body!.command_id)
    expect(commands[1].body!.payload).toEqual(commands[0].body!.payload)
    await waitFor(() => expect(result.current.unsentError).toBeNull())
    expect(Object.keys(pendingStore())).toHaveLength(0)
  })

  it('never allocates a new command id merely because a retry happened', async () => {
    let attempt = 0
    handlers = [
      activeHandler(projection()),
      {
        match: (url, method) => url.endsWith('/v2/commands') && method === 'POST',
        respond: () => {
          attempt += 1
          if (attempt <= 2) throw new TypeError('Failed to fetch')
          return {
            status: 200,
            body: { status: 'replayed', projection: projection({ version: 5 }) },
          }
        },
      },
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())

    await act(async () => {
      await result.current.logSet({ weight: 225, reps: 5 }).catch(() => undefined)
    })
    await act(async () => {
      await result.current.retryPending().catch(() => undefined)
    })
    await act(async () => {
      await result.current.retryPending()
    })

    const ids = new Set(
      calls.filter((c) => c.url.endsWith('/v2/commands'))
        .map((c) => c.body!.command_id),
    )
    expect(ids.size).toBe(1)
  })

  it('a double tap sends two different commands, as two intents', async () => {
    // Two taps are two sets the athlete meant to log. Deduplicating them
    // would silently drop real work; the id guarantee is about *retries* of
    // one intent, not about collapsing distinct ones.
    handlers = [
      activeHandler(projection()),
      {
        match: (url, method) => url.endsWith('/v2/commands') && method === 'POST',
        respond: () => ({
          status: 200,
          body: { status: 'accepted', projection: projection({ version: 5 }) },
        }),
      },
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())

    await act(async () => {
      await result.current.logSet({ weight: 225, reps: 5 })
      await result.current.logSet({ weight: 225, reps: 5 })
    })
    const ids = new Set(
      calls.filter((c) => c.url.endsWith('/v2/commands'))
        .map((c) => c.body!.command_id),
    )
    expect(ids.size).toBe(2)
  })

  it('lets the athlete abandon a pending command without pretending it succeeded', async () => {
    handlers = [
      activeHandler(projection()),
      {
        match: (url, method) => url.endsWith('/v2/commands') && method === 'POST',
        respond: () => {
          throw new TypeError('Failed to fetch')
        },
      },
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())

    await act(async () => {
      await result.current.logSet({ weight: 225, reps: 5 }).catch(() => undefined)
    })
    await waitFor(() => expect(result.current.unsentError).not.toBeNull())

    act(() => result.current.dismissPending())
    expect(result.current.unsentError).toBeNull()
    expect(Object.keys(pendingStore())).toHaveLength(0)
  })

  // ── Conflicts ───────────────────────────────────────────────────────────

  it('adopts the servers state on a 409 and does not retry', async () => {
    const moved = projection({ version: 9, progress: {
      completed_sets: 3, total_sets: 9, total_volume: 3375,
    } })
    handlers = [
      activeHandler(projection()),
      {
        match: (url, method) => url.endsWith('/v2/commands') && method === 'POST',
        respond: () => ({
          status: 409,
          body: {
            detail: {
              code: 'version_conflict',
              message: 'This workout changed on another device.',
              projection: moved,
            },
          },
        }),
      },
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())

    let thrown: unknown = null
    await act(async () => {
      thrown = await result.current
        .logSet({ weight: 225, reps: 5 })
        .catch((error) => error)
    })

    expect((thrown as { kind: string }).kind).toBe('conflict')
    // Only one attempt. Retrying through a conflict would apply the command
    // against a baseline it was not computed for.
    expect(calls.filter((c) => c.url.endsWith('/v2/commands'))).toHaveLength(1)
    // The pending record is cleared: this command is finished, not retryable.
    expect(Object.keys(pendingStore())).toHaveLength(0)
    expect(result.current.unsentError).toBeNull()
    // And the real state is on screen instead of a stale one.
    await waitFor(() => expect(result.current.projection?.version).toBe(9))
    expect(result.current.projection?.progress.completed_sets).toBe(3)
  })

  it('treats a 404 as a stale reference rather than a conflict', async () => {
    handlers = [
      activeHandler(projection()),
      {
        match: (url, method) => url.endsWith('/v2/commands') && method === 'POST',
        respond: () => ({
          status: 404,
          body: {
            detail: {
              code: 'set_not_found',
              message: 'That set is no longer in this workout.',
              projection: null,
            },
          },
        }),
      },
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())

    let thrown: unknown = null
    await act(async () => {
      thrown = await result.current.voidSet('set-gone').catch((error) => error)
    })
    const error = thrown as { kind: string; code?: string }
    expect(error.kind).toBe('stale_reference')
    expect(error.code).toBe('set_not_found')
  })

  // ── Duplicate last set ──────────────────────────────────────────────────

  it('duplicates the last live working set', async () => {
    handlers = [
      activeHandler(projection()),
      {
        match: (url, method) => url.endsWith('/v2/commands') && method === 'POST',
        respond: () => ({
          status: 200,
          body: { status: 'accepted', projection: projection({ version: 5 }) },
        }),
      },
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())

    await act(async () => {
      await result.current.duplicateLastSet()
    })
    const payload = calls.find((c) => c.url.endsWith('/v2/commands'))!.body!.payload as Json
    expect(payload).toMatchObject({ weight: 225, reps: 5, rpe: 8 })
  })

  it('never duplicates a voided set', async () => {
    // A voided set is one the athlete said did not happen, so repeating it
    // would re-log work they just retracted.
    const withVoided = projection({
      performed_sets: [
        {
          id: 'set-1', exercise: 'Bench Press', set_index: 1,
          weight: 315, reps: 5, rpe: 9, notes: null, is_pr: false,
          set_kind: 'working', parent_set_id: null, set_group_id: 'set-1',
          group_sequence: 0, counts_toward_target: false, voided: true,
          void_reason: 'wrong bar', revised_from_set_id: null,
          logged_at: '2026-10-01T16:05:00Z',
        },
      ],
    })
    handlers = [activeHandler(withVoided)]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())

    let duplicated: unknown = 'not-run'
    await act(async () => {
      duplicated = await result.current.duplicateLastSet()
    })
    expect(duplicated).toBeNull()
    expect(calls.filter((c) => c.url.endsWith('/v2/commands'))).toHaveLength(0)
  })

  it('never duplicates a warm-up as a working set', async () => {
    const warmupOnly = projection({
      performed_sets: [
        {
          id: 'set-1', exercise: 'Bench Press', set_index: 1,
          weight: 135, reps: 10, rpe: null, notes: null, is_pr: false,
          set_kind: 'warmup', parent_set_id: null, set_group_id: 'set-1',
          group_sequence: 0, counts_toward_target: false, voided: false,
          void_reason: null, revised_from_set_id: null,
          logged_at: '2026-10-01T16:02:00Z',
        },
      ],
    })
    handlers = [activeHandler(warmupOnly)]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())

    let duplicated: unknown = 'not-run'
    await act(async () => {
      duplicated = await result.current.duplicateLastSet()
    })
    expect(duplicated).toBeNull()
  })

  // ── Start ───────────────────────────────────────────────────────────────

  it('starts with a persisted attempt id so a retry resumes', async () => {
    handlers = [
      activeHandler(null),
      {
        match: (url, method) => url.endsWith('/v2/start') && method === 'POST',
        respond: () => ({ status: 200, body: { projection: projection() } }),
      },
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    await act(async () => {
      await result.current.start('tmpl-1')
    })
    const start = calls.find((c) => c.url.endsWith('/v2/start'))!
    expect(start.body).toMatchObject({
      template_id: 'tmpl-1', origin_device: 'web',
    })
    expect(typeof start.body!.start_attempt_id).toBe('string')
    await waitFor(() => expect(result.current.projection?.session_id).toBe('session-1'))
  })

  // ── Independence from coaching prose ────────────────────────────────────

  it('acknowledges a set even when no coaching text comes back', async () => {
    // The durable acknowledgement is the commit. A model outage shows up as
    // a missing sentence later, never as a stalled logger.
    handlers = [
      activeHandler(projection()),
      {
        match: (url, method) => url.endsWith('/v2/commands') && method === 'POST',
        respond: () => ({
          status: 200,
          body: {
            status: 'accepted',
            logged: { id: 'set-2' },
            projection: projection({ version: 5 }),
            // No coaching_events, no proposal, no prose.
          },
        }),
      },
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())

    let outcome: unknown = null
    await act(async () => {
      outcome = await result.current.logSet({ weight: 225, reps: 5 })
    })
    expect((outcome as { logged?: { id: string } }).logged?.id).toBe('set-2')
    await waitFor(() => expect(result.current.projection?.version).toBe(5))
  })

  // ── Rest ────────────────────────────────────────────────────────────────

  it('reports rest remaining from the servers timestamps', async () => {
    const now = Date.now()
    handlers = [
      activeHandler(projection({
        rest: {
          active: true,
          started_at: new Date(now - 30_000).toISOString(),
          duration_seconds: 120,
        },
      })),
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())
    await waitFor(() => expect(result.current.restRemaining).not.toBeNull())
    expect(result.current.restRemaining).toBeGreaterThan(80)
    expect(result.current.restRemaining).toBeLessThanOrEqual(90)
  })

  it('has no countdown when no rest is running', async () => {
    handlers = [activeHandler(projection())]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())
    expect(result.current.restRemaining).toBeNull()
  })

  // ── Isolation ───────────────────────────────────────────────────────────

  it('fires nothing when nobody is signed in', async () => {
    vi.resetModules()
    vi.doMock('../../../stores/authStore', () => ({
      useAuthStore: (selector: (s: unknown) => unknown) => selector({ user: null }),
    }))
    const { useWorkoutCommands: anonymous } = await import(
      '../../../hooks/useWorkoutCommands'
    )
    handlers = [activeHandler(projection())]
    calls = []
    renderHook(() => anonymous(), { wrapper })
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(calls.filter((c) => c.url.includes('/v2/'))).toHaveLength(0)
    vi.doUnmock('../../../stores/authStore')
  })

  it('scopes the pending-command store to the athlete', async () => {
    // A shared key would let an account change replay the previous person's
    // command id, which the server would happily accept as theirs.
    handlers = [
      activeHandler(projection()),
      {
        match: (url, method) => url.endsWith('/v2/commands') && method === 'POST',
        respond: () => {
          throw new TypeError('Failed to fetch')
        },
      },
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.projection).not.toBeNull())
    await act(async () => {
      await result.current.logSet({ weight: 225, reps: 5 }).catch(() => undefined)
    })
    expect(
      window.sessionStorage.getItem(`sara.workout.pending.${ATHLETE}`),
    ).not.toBeNull()
    expect(window.sessionStorage.getItem('sara.workout.pending')).toBeNull()
  })

  it('survives sessionStorage being unavailable', async () => {
    // Private windows and blocked site data both throw on access. Losing the
    // replay record is survivable; crashing the logger is not.
    const original = window.sessionStorage.setItem
    window.sessionStorage.setItem = () => {
      throw new DOMException('denied')
    }
    handlers = [
      activeHandler(projection()),
      {
        match: (url, method) => url.endsWith('/v2/commands') && method === 'POST',
        respond: () => ({
          status: 200,
          body: { status: 'accepted', projection: projection({ version: 5 }) },
        }),
      },
    ]
    try {
      const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
      await waitFor(() => expect(result.current.projection).not.toBeNull())
      await act(async () => {
        await result.current.logSet({ weight: 225, reps: 5 })
      })
      expect(calls.filter((c) => c.url.endsWith('/v2/commands'))).toHaveLength(1)
    } finally {
      window.sessionStorage.setItem = original
    }
  })

  // ── Current-exercise view ───────────────────────────────────────────────

  it('lists the current exercises sets newest first, voided ones included', async () => {
    handlers = [
      activeHandler(projection({
        performed_sets: [
          {
            id: 'set-1', exercise: 'Bench Press', set_index: 1,
            weight: 225, reps: 5, rpe: 8, notes: null, is_pr: false,
            set_kind: 'working', parent_set_id: null, set_group_id: 'set-1',
            group_sequence: 0, counts_toward_target: true, voided: false,
            void_reason: null, revised_from_set_id: null,
            logged_at: '2026-10-01T16:05:00Z',
          },
          {
            id: 'set-2', exercise: 'Bench Press', set_index: 2,
            weight: 225, reps: 4, rpe: 9, notes: null, is_pr: false,
            set_kind: 'working', parent_set_id: null, set_group_id: 'set-2',
            group_sequence: 0, counts_toward_target: false, voided: true,
            void_reason: 'miscounted', revised_from_set_id: null,
            logged_at: '2026-10-01T16:09:00Z',
          },
          {
            id: 'row-1', exercise: 'Barbell Row', set_index: 1,
            weight: 185, reps: 10, rpe: 7, notes: null, is_pr: false,
            set_kind: 'working', parent_set_id: null, set_group_id: 'row-1',
            group_sequence: 0, counts_toward_target: true, voided: false,
            void_reason: null, revised_from_set_id: null,
            logged_at: '2026-10-01T16:15:00Z',
          },
        ],
      })),
    ]
    const { result } = renderHook(() => useWorkoutCommands(), { wrapper })
    await waitFor(() => expect(result.current.currentExerciseSets.length).toBe(2))

    const sets = result.current.currentExerciseSets
    expect(sets.map((s) => s.id)).toEqual(['set-2', 'set-1'])
    // A voided set is shown, struck — "this didn't happen" is information.
    expect(sets[0].voided).toBe(true)
    expect(sets[0].void_reason).toBe('miscounted')
  })
})
