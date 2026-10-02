/**
 * Step 24 of FITNESS_COACH_IMPLEMENTATION_PLAN, at the UI: cadences are
 * opt-in, per kind, and the two switches mean different things.
 *
 * The claims being pinned:
 *
 * - **Everything starts off.** Opening the settings screen must not enrol
 *   anybody in anything.
 * - **"On" and "may contact me" are separate.** One toggle would make
 *   "stop messaging me" also mean "stop computing", which is not what
 *   anyone means — and it would make a weigh-in nudge and a weekly minute
 *   of GPU time the same decision.
 * - **A multi-day cadence shows what it counts from.** "Every 14 days from
 *   2026-01-01" is a different statement from "the 1st and the 15th".
 * - **Dispatch and completion are shown separately**, because a green
 *   scheduled row proves a dispatch and nothing about the work.
 * - **A suppression says why.** Without the reason, "why didn't Sara say
 *   anything" has no answer.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AthleteSettings from '../AthleteSettings'
import type {
  AthleteProfile, CadenceKind, CoachingCadence, CoachingRun,
} from '../../../types/fitnessCoach'

const ATHLETE = 'athlete-cadence'

vi.mock('../../../stores/authStore', () => ({
  useAuthStore: (selector: (s: unknown) => unknown) =>
    selector({ user: { id: ATHLETE, email: 'a@example.invalid' } }),
}))

const profile: AthleteProfile = {
  user_id: ATHLETE, height_cm: null, date_of_birth: null,
  calculation_sex: 'unknown', training_experience_years: null,
  training_level: 'unknown', timezone: 'America/New_York',
  weight_unit: 'lb', length_unit: 'in', available_days: [],
  preferred_duration_minutes: null, equipment: [],
  preferred_exercise_ids: [], excluded_exercise_ids: [],
  dietary_restrictions: [], dietary_preferences: [], supplements: [],
  coaching_style: 'unset', monitoring_consent: false,
  row_version: 1, latest_weight: {
    key: 'weight.latest', value: null, unit: 'lb', source_count: 0,
    quality_flags: [], analytics_version: 1, unavailable_reason: 'no_data',
  },
  created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
} as unknown as AthleteProfile

const KINDS: CadenceKind[] = [
  'daily_checkin', 'weekly_review', 'biweekly_review', 'monthly_review',
  'tape_measurement', 'progress_photo',
]

function cadence(kind: CadenceKind, over: Partial<CoachingCadence> = {}): CoachingCadence {
  return {
    kind, enabled: false, consented: false, consented_at: null,
    local_time: '07:00', timezone: 'America/New_York', weekdays: [],
    cadence_days: null, anchor_date: null, next_due_at: null,
    last_evaluated_at: null, last_completed_at: null, snoozed_until: null,
    version: 0, ...over,
  }
}

interface Call { url: string; method: string; body: unknown }

let calls: Call[] = []
let cadences: CoachingCadence[] = []
let runs: CoachingRun[] = []
let patchStatus = 200
let patchBody: unknown = null

function stubFetch() {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    const body = init?.body ? JSON.parse(String(init.body)) : null
    calls.push({ url, method, body })
    const json = (status: number, payload: unknown) =>
      new Response(JSON.stringify(payload), {
        status, headers: { 'Content-Type': 'application/json' },
      })

    if (url.includes('/coach/profile')) return json(200, profile)
    if (url.includes('/coach/today')) {
      return json(200, {
        athlete_local_date: '2026-10-02', timezone: 'America/New_York',
      })
    }
    if (url.match(/\/cadences\/[^/]+\/runs/)) return json(200, runs)
    if (url.match(/\/cadences\/[^/]+\/snooze/)) {
      return json(200, cadence('daily_checkin', {
        enabled: true, consented: true, version: 3,
        snoozed_until: '2099-01-01T12:00:00Z',
      }))
    }
    if (url.includes('/cadences') && method === 'PATCH') {
      return json(patchStatus, patchBody ?? cadence('daily_checkin', {
        enabled: true, version: 1, ...(body as object),
      }))
    }
    if (url.includes('/cadences')) return json(200, cadences)
    return json(200, [])
  }) as unknown as typeof fetch
}

function wrap(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  calls = []
  cadences = KINDS.map((kind) => cadence(kind))
  runs = []
  patchStatus = 200
  patchBody = null
  stubFetch()
})

// ── Opt-in ────────────────────────────────────────────────────────────────

describe('opt-in', () => {
  it('shows every cadence, all switched off', async () => {
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-daily_checkin-enabled')).toBeTruthy(),
    )
    for (const kind of KINDS) {
      const toggle = screen.getByTestId(`cadence-${kind}-enabled`) as HTMLInputElement
      expect(toggle.checked).toBe(false)
    }
  })

  it('writes nothing when the screen just opens', async () => {
    wrap(<AthleteSettings />)
    await waitFor(() => expect(screen.getByTestId('cadence-section')).toBeTruthy())
    expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(0)
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0)
  })

  it('says plainly that everything is off until turned on', async () => {
    wrap(<AthleteSettings />)
    await waitFor(() => expect(screen.getByTestId('cadence-section')).toBeTruthy())
    expect(screen.getByTestId('cadence-section').textContent).toContain(
      'off until you turn it on',
    )
  })

  it('hides the detail of a cadence that is off', async () => {
    wrap(<AthleteSettings />)
    await waitFor(() => expect(screen.getByTestId('cadence-section')).toBeTruthy())
    expect(screen.queryByTestId('cadence-daily_checkin-consent')).toBeNull()
    expect(screen.queryByTestId('cadence-daily_checkin-time')).toBeNull()
  })

  it('enables one cadence without touching the others', async () => {
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-weekly_review-enabled')).toBeTruthy(),
    )
    await userEvent.click(screen.getByTestId('cadence-weekly_review-enabled'))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'PATCH')).toBe(true),
    )
    const patches = calls.filter((c) => c.method === 'PATCH')
    expect(patches).toHaveLength(1)
    expect(patches[0].url).toContain('weekly_review')
    expect(patches[0].body).toMatchObject({ enabled: true })
  })
})

// ── The two switches ──────────────────────────────────────────────────────

describe('consent is separate from enabled', () => {
  beforeEach(() => {
    cadences = KINDS.map((kind) =>
      kind === 'daily_checkin'
        ? cadence(kind, { enabled: true, version: 1 })
        : cadence(kind),
    )
  })

  it('shows the consent switch only once a cadence is on', async () => {
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-daily_checkin-consent')).toBeTruthy(),
    )
    expect(screen.queryByTestId('cadence-weekly_review-consent')).toBeNull()
  })

  it('warns that nothing runs while consent is off', async () => {
    // An enabled-but-unconsented cadence has no due time at all, and a UI
    // that did not say so would look broken.
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-daily_checkin')).toBeTruthy(),
    )
    expect(screen.getByTestId('cadence-daily_checkin').textContent).toContain(
      'nothing will be sent, and nothing will run',
    )
  })

  it('sends consent as its own field', async () => {
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-daily_checkin-consent')).toBeTruthy(),
    )
    await userEvent.click(screen.getByTestId('cadence-daily_checkin-consent'))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'PATCH')).toBe(true),
    )
    const patch = calls.filter((c) => c.method === 'PATCH').at(-1)
    expect(patch?.body).toMatchObject({ consented: true })
    expect((patch?.body as Record<string, unknown>).enabled).toBeUndefined()
  })

  it('carries the version so a concurrent edit is detected', async () => {
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-daily_checkin-consent')).toBeTruthy(),
    )
    await userEvent.click(screen.getByTestId('cadence-daily_checkin-consent'))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'PATCH')).toBe(true),
    )
    const patch = calls.filter((c) => c.method === 'PATCH').at(-1)
    expect((patch?.body as Record<string, unknown>).expected_version).toBe(1)
  })

  it('surfaces a version conflict rather than silently retrying', async () => {
    patchStatus = 409
    patchBody = {
      detail: {
        code: 'cadence_conflict',
        message: 'someone else changed this cadence while you were editing it',
        current_version: 4,
      },
    }
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-daily_checkin-consent')).toBeTruthy(),
    )
    await userEvent.click(screen.getByTestId('cadence-daily_checkin-consent'))
    await waitFor(() =>
      expect(screen.getByTestId('cadence-daily_checkin').textContent)
        .toContain('changed this cadence'),
    )
  })
})

// ── The arithmetic is visible ─────────────────────────────────────────────

describe('multi-day cadences', () => {
  it('shows the day count and what it counts from', async () => {
    // "Every 14 days from 2026-01-01" is a different statement from "the
    // 1st and the 15th", and a cron would have meant the second.
    cadences = KINDS.map((kind) =>
      kind === 'biweekly_review'
        ? cadence(kind, {
            enabled: true, consented: true, version: 2,
            cadence_days: 14, anchor_date: '2026-01-01',
            next_due_at: '2026-10-08T11:00:00Z',
          })
        : cadence(kind),
    )
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-biweekly_review-days')).toBeTruthy(),
    )
    const row = screen.getByTestId('cadence-biweekly_review')
    expect(row.textContent).toContain('counted from 2026-01-01')
    expect(
      (screen.getByTestId('cadence-biweekly_review-days') as HTMLInputElement).value,
    ).toBe('14')
  })

  it('offers weekdays for a weekly cadence and not for an anchored one', async () => {
    cadences = KINDS.map((kind) =>
      kind === 'weekly_review' || kind === 'monthly_review'
        ? cadence(kind, { enabled: true, consented: true, version: 1 })
        : cadence(kind),
    )
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-weekly_review-weekdays')).toBeTruthy(),
    )
    expect(screen.queryByTestId('cadence-monthly_review-weekdays')).toBeNull()
    expect(screen.getByTestId('cadence-monthly_review-days')).toBeTruthy()
  })

  it('does not offer weekdays for the daily check-in', async () => {
    cadences = KINDS.map((kind) =>
      kind === 'daily_checkin'
        ? cadence(kind, { enabled: true, consented: true, version: 1 })
        : cadence(kind),
    )
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-daily_checkin-time')).toBeTruthy(),
    )
    expect(screen.queryByTestId('cadence-daily_checkin-weekdays')).toBeNull()
  })
})

// ── Dispatch is not completion ────────────────────────────────────────────

describe('what it has done', () => {
  it('distinguishes checked from ran', async () => {
    // A green scheduled row proves a dispatch and nothing about the work.
    // Showing one as the other is the mistake this whole subsystem avoids.
    cadences = KINDS.map((kind) =>
      kind === 'daily_checkin'
        ? cadence(kind, {
            enabled: true, consented: true, version: 1,
            last_evaluated_at: '2026-10-02T11:00:00Z',
            last_completed_at: null,
          })
        : cadence(kind),
    )
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-daily_checkin-evaluated')).toBeTruthy(),
    )
    expect(screen.getByTestId('cadence-daily_checkin-evaluated').textContent)
      .toContain('nothing has run yet')
    expect(screen.queryByTestId('cadence-daily_checkin-completed')).toBeNull()
  })

  it('shows the last completed run when there is one', async () => {
    cadences = KINDS.map((kind) =>
      kind === 'weekly_review'
        ? cadence(kind, {
            enabled: true, consented: true, version: 1,
            last_evaluated_at: '2026-10-02T11:00:00Z',
            last_completed_at: '2026-09-29T11:00:00Z',
          })
        : cadence(kind),
    )
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-weekly_review-completed')).toBeTruthy(),
    )
    expect(screen.getByTestId('cadence-weekly_review-completed').textContent)
      .toContain('2026-09-29')
  })

  it('shows why an occurrence did nothing', async () => {
    // Without the reason, "why didn't Sara say anything" has no answer, and
    // a suppression is indistinguishable from a bug.
    cadences = KINDS.map((kind) =>
      kind === 'daily_checkin'
        ? cadence(kind, { enabled: true, consented: true, version: 1 })
        : cadence(kind),
    )
    runs = [
      {
        id: 'run-1', kind: 'daily_checkin',
        occurrence_at: '2026-10-02T11:00:00Z', status: 'noop', attempts: 1,
        review_id: null, error_category: null,
        noop_reason: 'nothing_missing', completed_at: '2026-10-02T11:00:05Z',
      },
      {
        id: 'run-2', kind: 'daily_checkin',
        occurrence_at: '2026-10-01T11:00:00Z', status: 'completed',
        attempts: 1, review_id: null, error_category: null,
        noop_reason: null, completed_at: '2026-10-01T11:00:05Z',
      },
    ]
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-daily_checkin-history')).toBeTruthy(),
    )
    await userEvent.click(screen.getByTestId('cadence-daily_checkin-history'))
    await waitFor(() =>
      expect(screen.getByTestId('cadence-daily_checkin-runs')).toBeTruthy(),
    )
    const history = screen.getByTestId('cadence-daily_checkin-runs')
    expect(history.textContent).toContain('nothing missing')
    expect(history.textContent).toContain('completed')
  })

  it('does not fetch the history until asked', async () => {
    cadences = KINDS.map((kind) =>
      kind === 'daily_checkin'
        ? cadence(kind, { enabled: true, consented: true, version: 1 })
        : cadence(kind),
    )
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-daily_checkin-history')).toBeTruthy(),
    )
    expect(calls.some((c) => c.url.includes('/runs'))).toBe(false)
  })
})

// ── Snooze ────────────────────────────────────────────────────────────────

describe('snooze', () => {
  beforeEach(() => {
    cadences = KINDS.map((kind) =>
      kind === 'daily_checkin'
        ? cadence(kind, {
            enabled: true, consented: true, version: 2,
            next_due_at: '2026-10-03T11:00:00Z',
          })
        : cadence(kind),
    )
  })

  it('pauses without switching the cadence off', async () => {
    // "Not this week" and "stop asking" are different statements. Collapsing
    // them means someone who wanted a week's quiet has to re-enable from
    // scratch.
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-daily_checkin-snooze')).toBeTruthy(),
    )
    await userEvent.click(screen.getByTestId('cadence-daily_checkin-snooze'))

    await waitFor(() =>
      expect(calls.some((c) => c.url.includes('/snooze'))).toBe(true),
    )
    // Not a disable.
    expect(
      calls.some((c) => c.method === 'PATCH' &&
        (c.body as Record<string, unknown>)?.enabled === false),
    ).toBe(false)
  })

  it('shows the snooze instead of the next due time', async () => {
    cadences = KINDS.map((kind) =>
      kind === 'daily_checkin'
        ? cadence(kind, {
            enabled: true, consented: true, version: 2,
            next_due_at: '2026-10-03T11:00:00Z',
            snoozed_until: '2099-01-01T12:00:00Z',
          })
        : cadence(kind),
    )
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-daily_checkin-snoozed')).toBeTruthy(),
    )
    expect(screen.queryByTestId('cadence-daily_checkin-next')).toBeNull()
  })

  it('ignores a snooze that has already passed', async () => {
    cadences = KINDS.map((kind) =>
      kind === 'daily_checkin'
        ? cadence(kind, {
            enabled: true, consented: true, version: 2,
            next_due_at: '2099-01-01T11:00:00Z',
            snoozed_until: '2020-01-01T12:00:00Z',
          })
        : cadence(kind),
    )
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-daily_checkin-next')).toBeTruthy(),
    )
    expect(screen.queryByTestId('cadence-daily_checkin-snoozed')).toBeNull()
  })
})

// ── The global sweep is not reachable from here ───────────────────────────

describe('the global sweep', () => {
  it('sends no task name, queue or owner', async () => {
    // Global schedule configuration cannot be hijacked through athlete
    // settings. The structural half is the backend's `extra="forbid"`; this is
    // the half that proves the UI never tries.
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-weekly_review-enabled')).toBeTruthy(),
    )
    await userEvent.click(screen.getByTestId('cadence-weekly_review-enabled'))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'PATCH')).toBe(true),
    )

    for (const call of calls) {
      if (!call.body || typeof call.body !== 'object') continue
      const keys = Object.keys(call.body as object)
      for (const forbidden of ['task_name', 'queue', 'kwargs', 'args',
                               'user_id', 'cron_expr', 'interval_seconds']) {
        expect(keys).not.toContain(forbidden)
      }
    }
  })

  it("only ever writes to the athlete's own cadence path", async () => {
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByTestId('cadence-weekly_review-enabled')).toBeTruthy(),
    )
    await userEvent.click(screen.getByTestId('cadence-weekly_review-enabled'))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'PATCH')).toBe(true),
    )
    for (const call of calls) {
      if (call.method === 'GET') continue
      expect(call.url).toMatch(/\/coach\//)
      expect(call.url).not.toContain('/schedules')
      expect(call.url).not.toContain('scheduled_job')
    }
  })
})
