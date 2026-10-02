/**
 * Step 7 of FITNESS_COACH_IMPLEMENTATION_PLAN: the athlete can set up their
 * profile, goals and targets with no model running, and the screen never
 * invents a number.
 *
 * What is actually being pinned here:
 *
 * - An unset value renders as "Not set", never as `0`. Those are different
 *   facts and a form that shows one as the other turns "I never gave my
 *   height" into "my height is zero".
 * - A PATCH carries **only the fields that changed**. Echoing the whole
 *   profile back would make every untouched field an assertion and would
 *   overwrite whatever another device changed in the meantime.
 * - Clearing a field sends an explicit `null`, which is a different request
 *   from omitting it.
 * - A 409 shows the current version and does not silently retry.
 * - Query keys are per-athlete, so an account change cannot serve the
 *   previous person's bodyweight out of the cache.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AthleteSettings from '../AthleteSettings'
import { fitnessKeys } from '../../../hooks/useFitnessCoach'
import type { AthleteProfile } from '../../../types/fitnessCoach'

const ATHLETE = 'athlete-under-test'

vi.mock('../../../stores/authStore', () => ({
  useAuthStore: (selector: (s: unknown) => unknown) =>
    selector({ user: { id: ATHLETE, email: 'a@example.invalid' } }),
}))

const emptyProfile: AthleteProfile = {
  user_id: ATHLETE,
  height_cm: null,
  date_of_birth: null,
  calculation_sex: 'unknown',
  training_experience_years: null,
  training_level: 'unknown',
  timezone: 'America/New_York',
  weight_unit: 'lb',
  length_unit: 'in',
  available_days: [],
  preferred_duration_minutes: null,
  equipment: [],
  preferred_exercise_ids: [],
  excluded_exercise_ids: [],
  dietary_restrictions: [],
  dietary_preferences: [],
  supplements: [],
  coaching_style: 'unset',
  monitoring_consent: false,
  row_version: 1,
  created_at: null,
  updated_at: null,
  current_weight: {
    key: 'profile.current_weight',
    value: null,
    unit: 'count',
    source_count: 0,
    unavailable_reason: 'no_data',
    quality_flags: [],
    analytics_version: 1,
  },
}

type Json = Record<string, unknown>

interface FetchCall {
  url: string
  method: string
  body: Json | null
}

let calls: FetchCall[] = []
let handlers: Array<{
  match: (url: string, method: string) => boolean
  respond: (body: Json | null) => { status: number; body: unknown }
}> = []

function stubFetch() {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    const body = init?.body ? (JSON.parse(String(init.body)) as Json) : null
    calls.push({ url, method, body })

    for (const handler of handlers) {
      if (handler.match(url, method)) {
        const { status, body: responseBody } = handler.respond(body)
        return new Response(JSON.stringify(responseBody), {
          status,
          headers: { 'Content-Type': 'application/json' },
        })
      }
    }
    return new Response(JSON.stringify([]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }) as unknown as typeof fetch
}

function wrap(ui: React.ReactElement, client?: QueryClient) {
  const queryClient =
    client ??
    new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
  return {
    queryClient,
    ...render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>),
  }
}

function profileHandler(profile: AthleteProfile) {
  return {
    match: (url: string, method: string) =>
      url.endsWith('/coach/profile') && method === 'GET',
    respond: () => ({ status: 200, body: profile as unknown as Json }),
  }
}

const todayHandler = {
  match: (url: string, method: string) =>
    url.endsWith('/coach/today') && method === 'GET',
  respond: () => ({
    status: 200,
    body: { athlete_local_date: '2026-10-02', timezone: 'America/New_York' },
  }),
}

beforeEach(() => {
  calls = []
  handlers = []
  stubFetch()
})

describe('AthleteSettings', () => {
  it('renders an unconfigured profile as "Not set", never as zero', async () => {
    handlers = [profileHandler(emptyProfile), todayHandler]
    wrap(<AthleteSettings />)

    await waitFor(() => expect(screen.getByText(/About you/i)).toBeInTheDocument())

    const height = screen.getByLabelText(/Height, in centimetres/i) as HTMLInputElement
    expect(height.value).toBe('')
    expect(height.placeholder).toBe('Not set')

    // The weight row is read-only text resolved from observations.
    expect(screen.getByText('Not recorded')).toBeInTheDocument()
    expect(screen.queryByText(/^0 /)).not.toBeInTheDocument()
  })

  it('says a weight exists but has no recorded unit, rather than guessing one', async () => {
    handlers = [
      profileHandler({
        ...emptyProfile,
        current_weight: {
          ...emptyProfile.current_weight!,
          value: null,
          unavailable_reason: 'unknown_unit',
        },
      }),
      todayHandler,
    ]
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(
        screen.getByText(/its unit was never saved/i),
      ).toBeInTheDocument(),
    )
  })

  it('shows a declined calculation sex as a real answer', async () => {
    handlers = [
      profileHandler({ ...emptyProfile, calculation_sex: 'prefer_not_to_say' }),
      todayHandler,
    ]
    wrap(<AthleteSettings />)
    const select = (await waitFor(() =>
      screen.getByLabelText(/Sex, for formulas/i),
    )) as HTMLSelectElement
    expect(select.value).toBe('prefer_not_to_say')
    expect(screen.getByText(/will not ask again/i)).toBeInTheDocument()
  })

  it('sends only the fields that changed', async () => {
    handlers = [
      profileHandler(emptyProfile),
      todayHandler,
      {
        match: (url, method) => url.endsWith('/coach/profile') && method === 'PATCH',
        respond: (body) => ({
          status: 200,
          body: { ...emptyProfile, ...(body ?? {}), row_version: 2 } as unknown as Json,
        }),
      },
    ]
    wrap(<AthleteSettings />)
    await waitFor(() => screen.getByLabelText(/Height, in centimetres/i))

    await userEvent.type(screen.getByLabelText(/Height, in centimetres/i), '182')
    await userEvent.click(screen.getByRole('button', { name: /Save changes/i }))

    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')
      expect(patch).toBeDefined()
      expect(patch!.body).toEqual({ height_cm: 182, expected_version: 1 })
    })

    const patch = calls.find((c) => c.method === 'PATCH')!
    // Nothing untouched was echoed back — that is the whole point.
    expect(Object.keys(patch.body!)).not.toContain('timezone')
    expect(Object.keys(patch.body!)).not.toContain('equipment')
    expect(Object.keys(patch.body!)).not.toContain('date_of_birth')
  })

  it('distinguishes clearing a field from leaving it alone', async () => {
    handlers = [
      profileHandler({ ...emptyProfile, preferred_duration_minutes: 75 }),
      todayHandler,
      {
        match: (url, method) => url.endsWith('/coach/profile') && method === 'PATCH',
        respond: (body) => ({
          status: 200,
          body: { ...emptyProfile, ...(body ?? {}), row_version: 2 } as unknown as Json,
        }),
      },
    ]
    wrap(<AthleteSettings />)
    const input = (await waitFor(() =>
      screen.getByLabelText(/Usual session length/i),
    )) as HTMLInputElement
    expect(input.value).toBe('75')

    await userEvent.clear(input)
    await userEvent.click(screen.getByRole('button', { name: /Save changes/i }))

    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')
      expect(patch!.body).toHaveProperty('preferred_duration_minutes', null)
    })
  })

  it('cannot save when nothing has changed', async () => {
    handlers = [profileHandler(emptyProfile), todayHandler]
    wrap(<AthleteSettings />)
    const save = await waitFor(() =>
      screen.getByRole('button', { name: /Save changes/i }),
    )
    expect(save).toBeDisabled()
  })

  it('surfaces a version conflict with the current version and does not retry', async () => {
    handlers = [
      profileHandler(emptyProfile),
      todayHandler,
      {
        match: (url, method) => url.endsWith('/coach/profile') && method === 'PATCH',
        respond: () => ({
          status: 409,
          body: {
            detail: {
              code: 'version_conflict',
              message: 'Someone else changed this while you were editing it.',
              current_version: 7,
            },
          },
        }),
      },
    ]
    wrap(<AthleteSettings />)
    await waitFor(() => screen.getByLabelText(/Height, in centimetres/i))

    await userEvent.type(screen.getByLabelText(/Height, in centimetres/i), '175')
    await userEvent.click(screen.getByRole('button', { name: /Save changes/i }))

    await waitFor(() =>
      expect(screen.getByText(/now at version 7/i)).toBeInTheDocument(),
    )
    expect(screen.getByText(/were not saved/i)).toBeInTheDocument()

    const patches = calls.filter((c) => c.method === 'PATCH')
    expect(patches).toHaveLength(1)
  })

  it('renders a 422 as readable field wording, not a Pydantic location array', async () => {
    handlers = [
      profileHandler(emptyProfile),
      todayHandler,
      {
        match: (url, method) => url.endsWith('/coach/profile') && method === 'PATCH',
        respond: () => ({
          status: 422,
          body: {
            detail: [
              {
                type: 'value_error',
                loc: ['body', 'height_cm'],
                msg: 'height_cm outside a plausible human range',
              },
            ],
          },
        }),
      },
    ]
    wrap(<AthleteSettings />)
    await waitFor(() => screen.getByLabelText(/Height, in centimetres/i))

    await userEvent.type(screen.getByLabelText(/Height, in centimetres/i), '12')
    await userEvent.click(screen.getByRole('button', { name: /Save changes/i }))

    await waitFor(() =>
      expect(screen.getByText(/Height Cm: height_cm outside/i)).toBeInTheDocument(),
    )
    expect(screen.queryByText(/\["body"/)).not.toBeInTheDocument()
  })

  it('keeps the entered values when the network fails', async () => {
    handlers = [profileHandler(emptyProfile), todayHandler]
    wrap(<AthleteSettings />)
    await waitFor(() => screen.getByLabelText(/Height, in centimetres/i))

    await userEvent.type(screen.getByLabelText(/Height, in centimetres/i), '183')

    // Only the PATCH fails, after the form was filled in.
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }) as unknown as typeof fetch

    await userEvent.click(screen.getByRole('button', { name: /Save changes/i }))

    await waitFor(() =>
      expect(screen.getByText(/has not been saved/i)).toBeInTheDocument(),
    )
    const height = screen.getByLabelText(/Height, in centimetres/i) as HTMLInputElement
    expect(height.value).toBe('183')
  })

  it('shows goal history with its real dates, including superseded goals', async () => {
    handlers = [
      profileHandler(emptyProfile),
      todayHandler,
      {
        match: (url, method) => url.includes('/coach/goals') && method === 'GET',
        respond: () => ({
          status: 200,
          body: [
            {
              id: 'g2', user_id: ATHLETE, kind: 'cut', is_primary: true, priority: 1,
              rationale: null, target_weight_kg: null, rate_basis: 'absolute',
              target_rate_kg_week: -0.4, target_rate_percent_week: null,
              strength_targets: {}, valid_from: '2026-03-01', valid_until: null,
              recorded_at: '2026-03-01T00:00:00Z', supersedes_id: 'g1',
              approved_at: '2026-03-01T00:00:00Z',
            },
            {
              id: 'g1', user_id: ATHLETE, kind: 'hypertrophy', is_primary: true,
              priority: 1, rationale: 'upper-body thickness', target_weight_kg: null,
              rate_basis: 'none', target_rate_kg_week: null,
              target_rate_percent_week: null, strength_targets: {},
              valid_from: '2026-01-01', valid_until: '2026-03-01',
              recorded_at: '2026-01-01T00:00:00Z', supersedes_id: null,
              approved_at: '2026-01-01T00:00:00Z',
            },
          ],
        }),
      },
    ]
    wrap(<AthleteSettings />)

    await waitFor(() => expect(screen.getByText('cut')).toBeInTheDocument())
    // The superseded goal survives with its closed interval, so Sara can
    // still explain what January was for.
    expect(screen.getByText('hypertrophy')).toBeInTheDocument()
    expect(screen.getByText(/2026-01-01 → 2026-03-01/)).toBeInTheDocument()
    expect(screen.getByText(/2026-03-01 → now/)).toBeInTheDocument()
    expect(screen.getByText('upper-body thickness')).toBeInTheDocument()
    expect(screen.getByText(/-0.4 kg\/week/)).toBeInTheDocument()
  })

  it('defaults date inputs to the athletes own calendar date, not the browsers', async () => {
    handlers = [
      profileHandler(emptyProfile),
      {
        match: (url, method) => url.endsWith('/coach/today') && method === 'GET',
        respond: () => ({
          status: 200,
          // Deliberately not "today" in any timezone the test runner is in.
          body: { athlete_local_date: '2026-07-04', timezone: 'Pacific/Kiritimati' },
        }),
      },
    ]
    wrap(<AthleteSettings />)

    await waitFor(() =>
      expect(screen.getByText(/Your date: 2026-07-04/)).toBeInTheDocument(),
    )

    await userEvent.click(screen.getByRole('button', { name: /Add a goal/i }))
    const starts = (await waitFor(() =>
      screen.getByLabelText(/Starts on/i),
    )) as HTMLInputElement
    expect(starts.value).toBe('2026-07-04')
  })

  it('explains that target history exists rather than showing a bare empty list', async () => {
    handlers = [
      profileHandler(emptyProfile),
      todayHandler,
      {
        match: (url, method) =>
          url.includes('/coach/targets/history') && method === 'GET',
        respond: () => ({ status: 200, body: [] }),
      },
    ]
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(
        screen.getByText(/will say "not recorded" rather than guess/i),
      ).toBeInTheDocument(),
    )
  })

  it('shows target revisions with the dates they applied', async () => {
    handlers = [
      profileHandler(emptyProfile),
      todayHandler,
      {
        match: (url, method) =>
          url.includes('/coach/targets/history') && method === 'GET',
        respond: () => ({
          status: 200,
          body: [
            {
              id: 'r2', user_id: ATHLETE, scope: 'default', phase_id: null, version: 2,
              valid_from: '2026-09-15', valid_until: null,
              training: {
                calories: 2700, protein_g: 195, carbs_g: null, fat_g: null,
                sleep_hours: null, water_ml: null, steps: null,
                calorie_tolerance_pct: 10, protein_tolerance_pct: 10,
              },
              rest: null, source: 'user', review_recommendation_id: null,
              approved_at: '2026-09-15T00:00:00Z', approved_by: ATHLETE,
              created_at: '2026-09-15T00:00:00Z',
            },
          ],
        }),
      },
    ]
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByText(/2700 kcal · 195 g protein/)).toBeInTheDocument(),
    )
    expect(screen.getByText(/2026-09-15 → now · default · v2/)).toBeInTheDocument()
  })

  it('renders a target revision with no protein as "Not set", not 0 g', async () => {
    handlers = [
      profileHandler(emptyProfile),
      todayHandler,
      {
        match: (url, method) =>
          url.includes('/coach/targets/history') && method === 'GET',
        respond: () => ({
          status: 200,
          body: [
            {
              id: 'r1', user_id: ATHLETE, scope: 'default', phase_id: null, version: 1,
              valid_from: '2026-09-01', valid_until: null,
              training: {
                calories: 2600, protein_g: null, carbs_g: null, fat_g: null,
                sleep_hours: null, water_ml: null, steps: null,
                calorie_tolerance_pct: 10, protein_tolerance_pct: 10,
              },
              rest: null, source: 'user', review_recommendation_id: null,
              approved_at: '2026-09-01T00:00:00Z', approved_by: ATHLETE,
              created_at: '2026-09-01T00:00:00Z',
            },
          ],
        }),
      },
    ]
    wrap(<AthleteSettings />)
    await waitFor(() =>
      expect(screen.getByText(/2600 kcal · Not set/)).toBeInTheDocument(),
    )
    expect(screen.queryByText(/0 g protein/)).not.toBeInTheDocument()
  })

  it('offers no diagnosis field when recording something to work around', async () => {
    handlers = [profileHandler(emptyProfile), todayHandler]
    wrap(<AthleteSettings />)
    await waitFor(() => screen.getByText(/Things to work around/i))

    expect(
      screen.getByText(/not as a diagnosis, and will not name a condition/i),
    ).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Add one/i }))
    expect(screen.queryByLabelText(/diagnosis/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/condition/i)).not.toBeInTheDocument()
    expect(screen.getByLabelText(/Where/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/What happens/i)).toBeInTheDocument()
  })

  it('uses forms that are reachable from the keyboard', async () => {
    handlers = [profileHandler(emptyProfile), todayHandler]
    wrap(<AthleteSettings />)
    const height = (await waitFor(() =>
      screen.getByLabelText(/Height, in centimetres/i),
    )) as HTMLInputElement

    height.focus()
    expect(document.activeElement).toBe(height)
    await userEvent.keyboard('180')
    expect(height.value).toBe('180')

    // Every field has a real label association, not a placeholder standing in
    // for one.
    for (const label of [
      /Height, in centimetres/i,
      /Date of birth/i,
      /Sex, for formulas/i,
      /Training level/i,
      /Years training/i,
      /Your timezone/i,
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument()
    }
  })

  it('never fires a request when nobody is signed in', async () => {
    vi.resetModules()
    vi.doMock('../../../stores/authStore', () => ({
      useAuthStore: (selector: (s: unknown) => unknown) => selector({ user: null }),
    }))
    const { default: Anonymous } = await import('../AthleteSettings')
    handlers = [profileHandler(emptyProfile), todayHandler]
    calls = []
    wrap(<Anonymous />)
    // No owner means no query: a fitness read without an athlete is the bug
    // Step 2 existed to remove.
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(calls.filter((c) => c.url.includes('/coach/'))).toHaveLength(0)
    vi.doUnmock('../../../stores/authStore')
  })
})

describe('fitness query keys', () => {
  it('scope every key to one athlete so an account change cannot leak', () => {
    const alice = fitnessKeys.profile('alice')
    const bob = fitnessKeys.profile('bob')
    expect(alice).not.toEqual(bob)
    expect(alice).toContain('alice')
    expect(fitnessKeys.all('alice')).toEqual(['fitness-coach', 'alice'])
    // Every specific key must live under that athlete's subtree, so
    // removeQueries on logout actually removes all of it.
    for (const key of [
      fitnessKeys.profile('alice'),
      fitnessKeys.goals('alice'),
      fitnessKeys.limitations('alice'),
      fitnessKeys.targets('alice'),
      fitnessKeys.targetHistory('alice'),
      fitnessKeys.today('alice'),
    ]) {
      expect(key.slice(0, 2)).toEqual(['fitness-coach', 'alice'])
    }
  })

  it('separates as-of views so one date does not overwrite another in the cache', () => {
    expect(fitnessKeys.targets('alice', '2026-09-01')).not.toEqual(
      fitnessKeys.targets('alice', '2026-10-01'),
    )
    expect(fitnessKeys.goals('alice', undefined, true)).not.toEqual(
      fitnessKeys.goals('alice', undefined, false),
    )
  })
})
