/**
 * Step 11 of FITNESS_COACH_IMPLEMENTATION_PLAN: Today logs part of a day
 * without fabricating the rest of it.
 *
 * The display defects being prevented are each a confident wrong statement
 * rather than a visible error:
 *
 * - Showing "Excellent — good to push it today" for a day with nothing
 *   logged. The underlying formula genuinely returns 100 for an empty input.
 * - Rendering an unlogged weight as `0 lb`.
 * - Resetting the form to server state after a failed save, so the athlete's
 *   typing is gone and they are not told why.
 * - Defaulting the date from `new Date()` rather than from the athlete's own
 *   timezone.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DailyCheckIn from '../DailyCheckIn'
import type { CheckIn, Metric } from '../../../types/fitnessCoach'

const ATHLETE = 'athlete-today'

vi.mock('../../../stores/authStore', () => ({
  useAuthStore: (selector: (s: unknown) => unknown) =>
    selector({ user: { id: ATHLETE, email: 'a@example.invalid' } }),
}))

function absent(key: string, reason: Metric['unavailable_reason'] = 'no_data'): Metric {
  return {
    key, value: null, unit: 'count', source_count: 0,
    unavailable_reason: reason, quality_flags: [], analytics_version: 1,
  }
}

function present(key: string, value: number, unit: Metric['unit'], extra?: Partial<Metric>): Metric {
  return {
    key, value, unit, source_count: 1, quality_flags: [],
    analytics_version: 1, ...extra,
  }
}

const emptyDay: CheckIn = {
  user_id: ATHLETE,
  log_date: '2026-10-01',
  bedtime_at: null,
  wake_at: null,
  sleep_quality: null,
  energy: null,
  fatigue: null,
  soreness_level: null,
  stress: null,
  motivation: null,
  subjective_readiness: null,
  notes: null,
  nutrition_status: 'unknown',
  nutrition_completed_at: null,
  row_version: 1,
  field_sources: {},
  weight: absent('checkin.weight'),
  sleep_duration: absent('checkin.sleep_duration'),
  steps: absent('checkin.steps'),
  water: absent('checkin.water'),
  hrv: absent('checkin.hrv'),
  resting_heart_rate: absent('checkin.resting_heart_rate'),
  computed_readiness: null,
  readiness_coverage: 'unknown',
}

type Json = Record<string, unknown>
interface Call { url: string; method: string; body: Json | null }

let calls: Call[] = []
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
        const { status, body: out } = handler.respond(body)
        return new Response(JSON.stringify(out), {
          status, headers: { 'Content-Type': 'application/json' },
        })
      }
    }
    return new Response(JSON.stringify(null), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }) as unknown as typeof fetch
}

function wrap(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const todayHandler = (localDate = '2026-10-01', tz = 'America/New_York') => ({
  match: (url: string, method: string) => url.endsWith('/coach/today') && method === 'GET',
  respond: () => ({
    status: 200,
    body: { athlete_local_date: localDate, timezone: tz },
  }),
})

const checkInHandler = (day: CheckIn) => ({
  match: (url: string, method: string) =>
    url.includes('/coach/check-ins/') && method === 'GET',
  respond: () => ({ status: 200, body: day as unknown as Json }),
})

const targetsHandler = (calories: number | null, extra?: Json) => ({
  match: (url: string, method: string) =>
    url.includes('/coach/targets') && method === 'GET',
  respond: () => ({
    status: 200,
    body: {
      user_id: ATHLETE, on_date: '2026-10-01', day_type: 'training',
      values: {
        calories, protein_g: null, carbs_g: null, fat_g: null,
        sleep_hours: null, water_ml: null, steps: null,
        calorie_tolerance_pct: 10, protein_tolerance_pct: 10,
      },
      provenance: calories === null ? 'unknown' : 'approved_revision',
      scope: 'default', phase_id: null, phase_name: null,
      revision_id: 'r1', revision_version: 1,
      effective_from: '2026-09-01', effective_until: null,
      history_unknown: false, ...extra,
    },
  }),
})

beforeEach(() => {
  calls = []
  handlers = []
  stubFetch()
})

describe('DailyCheckIn', () => {
  it('shows no readiness score for a day with nothing logged', async () => {
    handlers = [todayHandler(), checkInHandler(emptyDay), targetsHandler(null)]
    wrap(<DailyCheckIn />)

    await waitFor(() => expect(screen.getByText('Readiness')).toBeInTheDocument())
    expect(screen.getByText(/No score for this day/i)).toBeInTheDocument()
    expect(
      screen.getByText(/says nothing rather than assuming the day went well/i),
    ).toBeInTheDocument()

    // The specific wrong output: the formula's empty-input answer.
    expect(screen.queryByText('Excellent')).not.toBeInTheDocument()
    expect(screen.queryByText('100')).not.toBeInTheDocument()
  })

  it('renders an unlogged reading as "Not recorded", never as zero', async () => {
    handlers = [todayHandler(), checkInHandler(emptyDay), targetsHandler(null)]
    wrap(<DailyCheckIn />)

    await waitFor(() => expect(screen.getByText('Already recorded')).toBeInTheDocument())
    expect(screen.getAllByText('Not recorded').length).toBeGreaterThanOrEqual(6)
    // No rendered metric value at all, so nothing could have been a zero.
    expect(screen.queryAllByTestId('metric-value')).toHaveLength(0)
  })

  it('renders a genuine zero as zero', async () => {
    handlers = [
      todayHandler(),
      checkInHandler({ ...emptyDay, steps: present('checkin.steps', 0, 'count') }),
      targetsHandler(null),
    ]
    wrap(<DailyCheckIn />)

    await waitFor(() =>
      expect(screen.getAllByTestId('metric-value').length).toBeGreaterThan(0),
    )
    const values = screen.getAllByTestId('metric-value').map((n) => n.textContent)
    expect(values).toContain('0')
  })

  it('says a reading exists but its unit was never saved', async () => {
    handlers = [
      todayHandler(),
      checkInHandler({
        ...emptyDay,
        weight: absent('checkin.weight', 'unknown_unit'),
      }),
      targetsHandler(null),
    ]
    wrap(<DailyCheckIn />)
    await waitFor(() =>
      expect(screen.getByText(/Recorded, unit unknown/i)).toBeInTheDocument(),
    )
  })

  it('labels a partial readiness score and names what is missing', async () => {
    handlers = [
      todayHandler(),
      checkInHandler({
        ...emptyDay,
        soreness_level: 3,
        sleep_duration: present('checkin.sleep_duration', 7.5, 'h'),
        readiness_coverage: 'partial',
        computed_readiness: {
          score: 92, label: 'Excellent', status: 'Well recovered',
          color: 'success', factors: [],
          inputs_used: ['sleep_hours', 'soreness_level'],
          inputs_missing: ['hrv', 'heart_rate'],
          coverage: 'partial',
        },
      }),
      targetsHandler(null),
    ]
    wrap(<DailyCheckIn />)

    await waitFor(() => expect(screen.getByText('92')).toBeInTheDocument())
    expect(screen.getByText(/partial data/i)).toBeInTheDocument()
    expect(screen.getByText(/Computed without hrv, heart rate/i)).toBeInTheDocument()
  })

  it('shows the athletes own answer separately from the computed score', async () => {
    handlers = [
      todayHandler(),
      checkInHandler({
        ...emptyDay,
        subjective_readiness: 4,
        readiness_coverage: 'full',
        computed_readiness: {
          score: 88, label: 'Excellent', status: 'Well recovered',
          color: 'success', factors: [], inputs_used: ['sleep_hours'],
          inputs_missing: [], coverage: 'full',
        },
      }),
      targetsHandler(null),
    ]
    wrap(<DailyCheckIn />)

    await waitFor(() => expect(screen.getByText('88')).toBeInTheDocument())
    expect(screen.getByText(/you feel like a 4\/10/i)).toBeInTheDocument()
  })

  it('sends only the fields that changed, with the version', async () => {
    handlers = [
      todayHandler(),
      checkInHandler({ ...emptyDay, row_version: 3, soreness_level: 2 }),
      targetsHandler(null),
      {
        match: (url, method) => url.includes('/coach/check-ins/') && method === 'PATCH',
        respond: (body) => ({
          status: 200,
          body: { ...emptyDay, ...(body ?? {}), row_version: 4 } as unknown as Json,
        }),
      },
    ]
    wrap(<DailyCheckIn />)
    await waitFor(() => screen.getByLabelText(/^Energy$/i))

    await userEvent.type(screen.getByLabelText(/^Energy$/i), '7')
    await userEvent.click(screen.getByRole('button', { name: /^Save$/i }))

    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')
      expect(patch?.body).toEqual({ energy: 7, expected_version: 3 })
    })
    const patch = calls.find((c) => c.method === 'PATCH')!
    expect(Object.keys(patch.body!)).not.toContain('soreness_level')
    expect(Object.keys(patch.body!)).not.toContain('notes')
  })

  it('clears a scale with an explicit null when the box is emptied', async () => {
    handlers = [
      todayHandler(),
      checkInHandler({ ...emptyDay, fatigue: 6 }),
      targetsHandler(null),
      {
        match: (url, method) => url.includes('/coach/check-ins/') && method === 'PATCH',
        respond: (body) => ({
          status: 200,
          body: { ...emptyDay, ...(body ?? {}), row_version: 2 } as unknown as Json,
        }),
      },
    ]
    wrap(<DailyCheckIn />)
    const fatigue = (await waitFor(() =>
      screen.getByLabelText(/^Fatigue$/i),
    )) as HTMLInputElement
    // Wait for the loaded value, not just for the field to exist — the field
    // renders before the query resolves.
    await waitFor(() => expect(fatigue.value).toBe('6'))

    await userEvent.clear(fatigue)
    await userEvent.click(screen.getByRole('button', { name: /^Save$/i }))

    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')
      expect(patch!.body).toHaveProperty('fatigue', null)
    })
  })

  it('cannot save when nothing has changed', async () => {
    handlers = [todayHandler(), checkInHandler(emptyDay), targetsHandler(null)]
    wrap(<DailyCheckIn />)
    const save = await waitFor(() => screen.getByRole('button', { name: /^Save$/i }))
    expect(save).toBeDisabled()
  })

  it('keeps the entered values when the save fails on the network', async () => {
    handlers = [todayHandler(), checkInHandler(emptyDay), targetsHandler(null)]
    wrap(<DailyCheckIn />)
    await waitFor(() => screen.getByLabelText(/^Energy$/i))

    await userEvent.type(screen.getByLabelText(/^Energy$/i), '8')

    globalThis.fetch = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }) as unknown as typeof fetch

    await userEvent.click(screen.getByRole('button', { name: /^Save$/i }))
    await waitFor(() =>
      expect(screen.getByText(/has not been saved/i)).toBeInTheDocument(),
    )
    expect((screen.getByLabelText(/^Energy$/i) as HTMLInputElement).value).toBe('8')
  })

  it('surfaces a conflict with the current version and keeps the inputs', async () => {
    handlers = [
      todayHandler(),
      checkInHandler({ ...emptyDay, row_version: 2 }),
      targetsHandler(null),
      {
        match: (url, method) => url.includes('/coach/check-ins/') && method === 'PATCH',
        respond: () => ({
          status: 409,
          body: {
            detail: {
              code: 'version_conflict',
              message: 'This day was updated somewhere else.',
              current_version: 9,
            },
          },
        }),
      },
    ]
    wrap(<DailyCheckIn />)
    await waitFor(() => screen.getByLabelText(/^Stress$/i))

    await userEvent.type(screen.getByLabelText(/^Stress$/i), '5')
    await userEvent.click(screen.getByRole('button', { name: /^Save$/i }))

    await waitFor(() =>
      expect(screen.getByText(/now at version 9/i)).toBeInTheDocument(),
    )
    expect(screen.getByText(/Nothing you typed was saved/i)).toBeInTheDocument()
    expect((screen.getByLabelText(/^Stress$/i) as HTMLInputElement).value).toBe('5')
  })

  it('defaults the date to the athletes calendar day, not the browsers', async () => {
    // Deliberately not today in any timezone the runner is in.
    handlers = [
      todayHandler('2026-07-04', 'Pacific/Kiritimati'),
      checkInHandler({ ...emptyDay, log_date: '2026-07-04' }),
      targetsHandler(null),
    ]
    wrap(<DailyCheckIn />)

    const picker = (await waitFor(() => screen.getByLabelText(/^Day$/i))) as HTMLInputElement
    expect(picker.value).toBe('2026-07-04')
    // And the request asked for that day, not for the browser's.
    await waitFor(() =>
      expect(
        calls.some((c) => c.url.includes('/coach/check-ins/2026-07-04')),
      ).toBe(true),
    )
  })

  it('does not offer a day in the future', async () => {
    handlers = [todayHandler('2026-10-01'), checkInHandler(emptyDay), targetsHandler(null)]
    wrap(<DailyCheckIn />)
    const next = await waitFor(() => screen.getByRole('button', { name: /Next day/i }))
    expect(next).toBeDisabled()
    expect((screen.getByLabelText(/^Day$/i) as HTMLInputElement).max).toBe('2026-10-01')
  })

  it('discards unsaved edits when the day changes rather than carrying them over', async () => {
    handlers = [todayHandler(), checkInHandler(emptyDay), targetsHandler(null)]
    wrap(<DailyCheckIn />)
    await waitFor(() => screen.getByLabelText(/^Energy$/i))

    await userEvent.type(screen.getByLabelText(/^Energy$/i), '9')
    await userEvent.click(screen.getByRole('button', { name: /Previous day/i }))

    await waitFor(() =>
      expect((screen.getByLabelText(/^Energy$/i) as HTMLInputElement).value).toBe(''),
    )
    expect(screen.getByRole('button', { name: /^Save$/i })).toBeDisabled()
  })

  it('states the days calorie target and does not score against a missing one', async () => {
    handlers = [todayHandler(), checkInHandler(emptyDay), targetsHandler(3000)]
    wrap(<DailyCheckIn />)
    await waitFor(() =>
      expect(screen.getByText(/Target for this day: 3000 kcal/i)).toBeInTheDocument(),
    )
  })

  it('says so when no calorie target was recorded for the day', async () => {
    handlers = [todayHandler(), checkInHandler(emptyDay), targetsHandler(null)]
    wrap(<DailyCheckIn />)
    await waitFor(() =>
      expect(
        screen.getByText(/No calorie target recorded for this day/i),
      ).toBeInTheDocument(),
    )
  })

  it('flags a date that predates the recorded target history', async () => {
    handlers = [
      todayHandler(),
      checkInHandler(emptyDay),
      targetsHandler(2600, { history_unknown: true }),
    ]
    wrap(<DailyCheckIn />)
    await waitFor(() =>
      expect(
        screen.getByText(/predates your recorded targets/i),
      ).toBeInTheDocument(),
    )
  })

  it('makes marking nutrition finished a deliberate, separate action', async () => {
    handlers = [
      todayHandler(),
      checkInHandler(emptyDay),
      targetsHandler(3000),
      {
        match: (url, method) => url.includes('/coach/check-ins/') && method === 'PATCH',
        respond: (body) => ({
          status: 200,
          body: {
            ...emptyDay, ...(body ?? {}),
            nutrition_completed_at: '2026-10-01T18:00:00Z',
            row_version: 2,
          } as unknown as Json,
        }),
      },
    ]
    wrap(<DailyCheckIn />)
    await waitFor(() => screen.getByText('Food'))

    expect(
      screen.getByText(/never decides it from how many meals are there/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/Nothing said about this day yet/i)).toBeInTheDocument()

    await userEvent.click(
      screen.getByRole('button', { name: /That's everything I ate/i }),
    )
    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')
      expect(patch!.body).toEqual({ nutrition_status: 'complete' })
    })
  })

  it('lets a confirmed day be reopened', async () => {
    handlers = [
      todayHandler(),
      checkInHandler({
        ...emptyDay,
        nutrition_status: 'complete',
        nutrition_completed_at: '2026-10-01T18:00:00Z',
      }),
      targetsHandler(3000),
      {
        match: (url, method) => url.includes('/coach/check-ins/') && method === 'PATCH',
        respond: (body) => ({
          status: 200,
          body: { ...emptyDay, ...(body ?? {}) } as unknown as Json,
        }),
      },
    ]
    wrap(<DailyCheckIn />)
    await waitFor(() =>
      expect(screen.getByText(/You said this day is fully logged/i)).toBeInTheDocument(),
    )

    await userEvent.click(screen.getByRole('button', { name: /Actually, there's more/i }))
    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')
      expect(patch!.body).toEqual({ nutrition_status: 'partial' })
    })
  })

  it('surfaces when two sources disagree about a reading', async () => {
    handlers = [
      todayHandler(),
      checkInHandler({
        ...emptyDay,
        weight: present('checkin.weight', 181.2, 'lb', {
          source_count: 2,
          quality_flags: ['source_conflict'],
          note: 'source: apple_health',
        }),
      }),
      targetsHandler(null),
    ]
    wrap(<DailyCheckIn />)
    await waitFor(() => expect(screen.getByTestId('metric-value')).toHaveTextContent('181.2'))
    expect(screen.getByText(/sources disagree/i)).toBeInTheDocument()
    expect(screen.getByText(/2 readings/i)).toBeInTheDocument()
  })

  it('offers a skip without recording anything', async () => {
    handlers = [todayHandler(), checkInHandler(emptyDay), targetsHandler(null)]
    wrap(<DailyCheckIn />)
    await waitFor(() => screen.getByLabelText(/^Energy$/i))

    await userEvent.type(screen.getByLabelText(/^Energy$/i), '6')
    await userEvent.click(screen.getByRole('button', { name: /Skip for now/i }))

    expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(0)
    expect(screen.getByRole('button', { name: /^Save$/i })).toBeDisabled()
  })

  it('has a real label for every entry field', async () => {
    handlers = [todayHandler(), checkInHandler(emptyDay), targetsHandler(null)]
    wrap(<DailyCheckIn />)
    await waitFor(() => screen.getByText('How are you'))

    for (const label of [
      /^Sleep quality$/i, /^Energy$/i, /^Fatigue$/i, /^Soreness$/i,
      /^Stress$/i, /^Motivation$/i, /How ready you feel/i,
      /^Weight$/i, /Sleep, hours/i, /Anything else about today/i, /^Day$/i,
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument()
    }
  })
})
