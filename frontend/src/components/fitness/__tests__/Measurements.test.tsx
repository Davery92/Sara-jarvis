/**
 * Step 11 of FITNESS_COACH_IMPLEMENTATION_PLAN: measurements are entered by
 * session and charted honestly.
 *
 * The two display claims being pinned:
 *
 * - **A sparse series is drawn with its real spacing**, with the reading
 *   count and date range stated. Evenly spaced points with a line through
 *   them imply measurements that were never taken.
 * - **Readings taken different ways are not trended against each other.** A
 *   waist at the navel and a waist at the narrowest point differ by
 *   centimetres, and that difference is not a change in the athlete.
 *
 * And one entry claim: a custom type needs no migration, and a partial
 * failure keeps the readings that did save plus whatever is still typed.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import Measurements from '../Measurements'
import type {
  Measurement,
  MeasurementPeriod,
  MeasurementType,
} from '../../../types/fitnessCoach'

const ATHLETE = 'athlete-measure'

vi.mock('../../../stores/authStore', () => ({
  useAuthStore: (selector: (s: unknown) => unknown) =>
    selector({ user: { id: ATHLETE, email: 'a@example.invalid' } }),
}))

// Recharts needs real layout; jsdom gives it none, so ResponsiveContainer
// renders nothing without a fixed size. Stubbing it keeps the test about the
// surrounding claims rather than about SVG geometry.
vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 400, height: 200 }}>{children}</div>
    ),
  }
})

const waistType: MeasurementType = {
  id: 't1', code: 'waist_circumference', label: 'Waist',
  quantity: 'length', canonical_unit: 'cm', allows_side: false,
  allowed_sites: [],
  protocol_guidance: 'At the navel, relaxed, at the end of a normal exhale.',
  owner_user_id: null, is_active: true,
}

const armType: MeasurementType = {
  id: 't2', code: 'upper_arm_circumference', label: 'Upper arm',
  quantity: 'length', canonical_unit: 'cm', allows_side: true,
  allowed_sites: [], protocol_guidance: 'At the widest point, arm relaxed.',
  owner_user_id: null, is_active: true,
}

function reading(
  id: string, date: string, value: number,
  extra?: Partial<Measurement>,
): Measurement {
  return {
    id, user_id: ATHLETE, type_code: 'waist_circumference', label: 'Waist',
    value, unit: 'cm', canonical_value: value, canonical_unit: 'cm',
    measured_at: `${date}T07:00:00Z`, logical_date: date,
    site: null, side: 'none', period_id: null, protocol: 'navel',
    source: 'manual', superseded_by_id: null, ...extra,
  }
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
    return new Response(JSON.stringify([]), {
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

const todayHandler = {
  match: (url: string, method: string) => url.endsWith('/coach/today') && method === 'GET',
  respond: () => ({
    status: 200,
    body: { athlete_local_date: '2026-10-01', timezone: 'America/New_York' },
  }),
}

const typesHandler = (types: MeasurementType[]) => ({
  match: (url: string, method: string) =>
    url.includes('/coach/measurement-types') && method === 'GET',
  respond: () => ({ status: 200, body: types as unknown as Json }),
})

const periodsHandler = (periods: MeasurementPeriod[]) => ({
  match: (url: string, method: string) =>
    url.includes('/coach/measurement-periods') && method === 'GET',
  respond: () => ({ status: 200, body: periods as unknown as Json }),
})

const measurementsHandler = (readings: Measurement[]) => ({
  match: (url: string, method: string) =>
    url.includes('/coach/measurements') && method === 'GET',
  respond: () => ({ status: 200, body: readings as unknown as Json }),
})

beforeEach(() => {
  calls = []
  handlers = []
  stubFetch()
})

describe('Measurements', () => {
  it('shows the protocol next to the series it governs', async () => {
    handlers = [
      todayHandler, typesHandler([waistType]), periodsHandler([]),
      measurementsHandler([]),
    ]
    wrap(<Measurements />)
    await waitFor(() =>
      expect(screen.getByText(/At the navel, relaxed/i)).toBeInTheDocument(),
    )
  })

  it('says one reading cannot show a direction', async () => {
    handlers = [
      todayHandler, typesHandler([waistType]), periodsHandler([]),
      measurementsHandler([reading('m1', '2026-10-01', 81.5)]),
    ]
    wrap(<Measurements />)
    await waitFor(() =>
      expect(screen.getByText(/81.5 cm/)).toBeInTheDocument(),
    )
    expect(
      screen.getByText(/Nothing to compare it against yet/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/will not describe a direction/i)).toBeInTheDocument()
  })

  it('states the reading count and real date range for a sparse series', async () => {
    handlers = [
      todayHandler, typesHandler([waistType]), periodsHandler([]),
      measurementsHandler([
        reading('m1', '2026-06-01', 85.0),
        reading('m2', '2026-08-15', 83.0),
        reading('m3', '2026-10-01', 81.5),
      ]),
    ]
    wrap(<Measurements />)
    await waitFor(() =>
      expect(
        screen.getByText(/3 readings between 2026-06-01 and 2026-10-01/i),
      ).toBeInTheDocument(),
    )
  })

  it('refuses to trend readings taken different ways', async () => {
    handlers = [
      todayHandler, typesHandler([waistType]), periodsHandler([]),
      measurementsHandler([
        reading('m1', '2026-09-01', 85.0, { protocol: 'at the navel' }),
        reading('m2', '2026-10-01', 79.0, { protocol: 'at the narrowest point' }),
      ]),
    ]
    wrap(<Measurements />)
    await waitFor(() =>
      expect(
        screen.getByText(/not changes in you/i),
      ).toBeInTheDocument(),
    )
    expect(screen.getByText(/2 different ways/i)).toBeInTheDocument()
    expect(screen.getByText(/will not report a trend across them/i)).toBeInTheDocument()
  })

  it('keeps left and right as separate series', async () => {
    handlers = [
      todayHandler, typesHandler([armType]), periodsHandler([]),
      measurementsHandler([
        { ...reading('l1', '2026-09-01', 38.0), type_code: 'upper_arm_circumference', label: 'Upper arm', side: 'left', protocol: 'relaxed' },
        { ...reading('l2', '2026-10-01', 38.6), type_code: 'upper_arm_circumference', label: 'Upper arm', side: 'left', protocol: 'relaxed' },
        { ...reading('r1', '2026-09-01', 38.8), type_code: 'upper_arm_circumference', label: 'Upper arm', side: 'right', protocol: 'relaxed' },
        { ...reading('r2', '2026-10-01', 39.0), type_code: 'upper_arm_circumference', label: 'Upper arm', side: 'right', protocol: 'relaxed' },
      ]),
    ]
    wrap(<Measurements />)

    // A sided type offers the side selector and defaults to one side, so the
    // two arms never share a line — a shared line would show a 0.5cm zig-zag
    // that is just the athlete's asymmetry.
    const sideSelect = (await waitFor(() =>
      screen.getByLabelText(/^Side$/i),
    )) as HTMLSelectElement
    expect(sideSelect.value).toBe('left')
    await waitFor(() =>
      expect(screen.getByText(/2 readings between .* · left/i)).toBeInTheDocument(),
    )

    await userEvent.selectOptions(sideSelect, 'right')
    await waitFor(() =>
      expect(screen.getByText(/2 readings between .* · right/i)).toBeInTheDocument(),
    )
  })

  it('offers no side selector for an unsided type', async () => {
    handlers = [
      todayHandler, typesHandler([waistType]), periodsHandler([]),
      measurementsHandler([]),
    ]
    wrap(<Measurements />)
    await waitFor(() => screen.getByLabelText(/^Show$/i))
    expect(screen.queryByLabelText(/^Side$/i)).not.toBeInTheDocument()
  })

  it('groups readings by the session they were taken in', async () => {
    handlers = [
      todayHandler, typesHandler([waistType, armType]),
      periodsHandler([{
        id: 'p1', user_id: ATHLETE, measured_on: '2026-10-01',
        measured_at: null, protocol: 'Morning, fasted, before water',
        notes: null, photo_period_label: null,
        created_at: '2026-10-01T07:00:00Z',
      }]),
      measurementsHandler([
        reading('m1', '2026-10-01', 81.5, { period_id: 'p1' }),
        {
          ...reading('m2', '2026-10-01', 38.5, { period_id: 'p1' }),
          type_code: 'upper_arm_circumference', label: 'Upper arm', side: 'left',
        },
      ]),
    ]
    wrap(<Measurements />)

    await waitFor(() =>
      expect(
        screen.getByText(/Morning, fasted, before water/i),
      ).toBeInTheDocument(),
    )
    expect(screen.getByText(/2 readings/)).toBeInTheDocument()
    // One sitting, rendered as one sitting.
    expect(
      screen.getByText(/Waist 81.5cm · Upper arm \(left\) 38.5cm/),
    ).toBeInTheDocument()
  })

  it('creates a custom type and sends the normalizable label as the code', async () => {
    handlers = [
      todayHandler, typesHandler([waistType]), periodsHandler([]),
      measurementsHandler([]),
      {
        match: (url, method) =>
          url.includes('/coach/measurement-types') && method === 'POST',
        respond: (body) => ({
          status: 201,
          body: {
            ...waistType, id: 't9', code: 'forearm_standing',
            label: (body?.label as string) ?? 'Forearm',
            owner_user_id: ATHLETE,
          } as unknown as Json,
        }),
      },
    ]
    wrap(<Measurements />)
    await userEvent.click(await waitFor(() =>
      screen.getByRole('button', { name: /New type/i }),
    ))

    expect(
      screen.getByText(/that is what lets Sara compare two readings/i),
    ).toBeInTheDocument()

    await userEvent.type(
      screen.getByLabelText(/What is it called/i), 'Forearm (standing)',
    )
    await userEvent.click(screen.getByLabelText(/Measured left and right separately/i))
    await userEvent.type(
      screen.getByLabelText(/How you measure it/i),
      'Standing, arm hanging relaxed',
    )
    await userEvent.click(screen.getByRole('button', { name: /Add it/i }))

    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === 'POST' && c.url.includes('measurement-types'),
      )
      expect(post?.body).toMatchObject({
        code: 'Forearm (standing)',
        label: 'Forearm (standing)',
        quantity: 'length',
        canonical_unit: 'cm',
        allows_side: true,
        protocol_guidance: 'Standing, arm hanging relaxed',
      })
    })
  })

  it('saves a whole session in one action', async () => {
    handlers = [
      todayHandler, typesHandler([waistType, armType]), periodsHandler([]),
      measurementsHandler([]),
      {
        match: (url, method) =>
          url.includes('/coach/measurement-periods') && method === 'POST',
        respond: () => ({
          status: 201,
          body: {
            id: 'p-new', user_id: ATHLETE, measured_on: '2026-10-01',
            measured_at: null, protocol: 'Morning, fasted',
            notes: null, photo_period_label: null,
            created_at: '2026-10-01T07:00:00Z',
          },
        }),
      },
      {
        match: (url, method) =>
          url.includes('/coach/measurements') && method === 'POST',
        respond: (body) => ({
          status: 201,
          body: { ...reading('new', '2026-10-01', Number(body?.value)) } as unknown as Json,
        }),
      },
    ]
    wrap(<Measurements />)
    await userEvent.click(await waitFor(() =>
      screen.getByRole('button', { name: /Add readings/i }),
    ))

    await waitFor(() => screen.getByLabelText(/^Waist$/i))
    await userEvent.type(screen.getByLabelText(/^Waist$/i), '81.5')
    await userEvent.type(screen.getByLabelText(/Upper arm \(left\)/i), '38.5')
    await userEvent.type(
      screen.getByLabelText(/How you measured, this time/i), 'Morning, fasted',
    )

    await userEvent.click(screen.getByRole('button', { name: /Save 2 readings/i }))

    await waitFor(() => {
      const posted = calls.filter(
        (c) => c.method === 'POST' && c.url.includes('/coach/measurements'),
      )
      expect(posted).toHaveLength(2)
    })

    const periodPost = calls.find(
      (c) => c.method === 'POST' && c.url.includes('measurement-periods'),
    )
    expect(periodPost?.body).toMatchObject({
      measured_on: '2026-10-01', protocol: 'Morning, fasted',
    })

    const posted = calls.filter(
      (c) => c.method === 'POST' && c.url.includes('/coach/measurements'),
    )
    // Every reading is attached to the one period, so they read as one
    // sitting rather than as unrelated points.
    for (const call of posted) {
      expect(call.body).toMatchObject({ period_id: 'p-new', unit: 'cm' })
    }
    expect(posted.map((c) => c.body?.side).sort()).toEqual(['left', 'none'])
  })

  it('defaults the session date to the athletes calendar day', async () => {
    handlers = [
      todayHandler, typesHandler([waistType]), periodsHandler([]),
      measurementsHandler([]),
    ]
    wrap(<Measurements />)
    await userEvent.click(await waitFor(() =>
      screen.getByRole('button', { name: /Add readings/i }),
    ))
    const picker = (await waitFor(() =>
      screen.getByLabelText(/Measured on/i),
    )) as HTMLInputElement
    expect(picker.value).toBe('2026-10-01')
  })

  it('cannot save an empty session', async () => {
    handlers = [
      todayHandler, typesHandler([waistType]), periodsHandler([]),
      measurementsHandler([]),
    ]
    wrap(<Measurements />)
    await userEvent.click(await waitFor(() =>
      screen.getByRole('button', { name: /Add readings/i }),
    ))
    await waitFor(() => screen.getByLabelText(/^Waist$/i))
    expect(screen.getByRole('button', { name: /^Save readings$/i })).toBeDisabled()
  })

  it('keeps the readings that saved when one of them fails', async () => {
    let attempt = 0
    handlers = [
      todayHandler, typesHandler([waistType, armType]), periodsHandler([]),
      measurementsHandler([]),
      {
        match: (url, method) =>
          url.includes('/coach/measurement-periods') && method === 'POST',
        respond: () => ({
          status: 201,
          body: {
            id: 'p-new', user_id: ATHLETE, measured_on: '2026-10-01',
            measured_at: null, protocol: null, notes: null,
            photo_period_label: null, created_at: '2026-10-01T07:00:00Z',
          },
        }),
      },
      {
        match: (url, method) =>
          url.includes('/coach/measurements') && method === 'POST',
        respond: (body) => {
          attempt += 1
          if (attempt === 2) {
            return {
              status: 422,
              body: {
                detail: 'Upper arm is measured per side; say which one',
              },
            }
          }
          return {
            status: 201,
            body: { ...reading('ok', '2026-10-01', Number(body?.value)) } as unknown as Json,
          }
        },
      },
    ]
    wrap(<Measurements />)
    await userEvent.click(await waitFor(() =>
      screen.getByRole('button', { name: /Add readings/i }),
    ))
    await waitFor(() => screen.getByLabelText(/^Waist$/i))
    await userEvent.type(screen.getByLabelText(/^Waist$/i), '81.5')
    await userEvent.type(screen.getByLabelText(/Upper arm \(left\)/i), '38.5')

    await userEvent.click(screen.getByRole('button', { name: /Save 2 readings/i }))

    // Two places say so: the per-reading note in the form, and the
    // mutation-level error banner above it.
    await waitFor(() =>
      expect(screen.getAllByText(/measured per side/i).length).toBeGreaterThan(0),
    )
    expect(
      screen.getByText(/readings that did save are kept/i),
    ).toBeInTheDocument()
    // The form stayed open with the entered values intact.
    expect((screen.getByLabelText(/^Waist$/i) as HTMLInputElement).value).toBe('81.5')
  })

  it('does not post a value that is not a measurement', async () => {
    handlers = [
      todayHandler, typesHandler([waistType]), periodsHandler([]),
      measurementsHandler([]),
      {
        match: (url, method) =>
          url.includes('/coach/measurement-periods') && method === 'POST',
        respond: () => ({
          status: 201,
          body: {
            id: 'p-new', user_id: ATHLETE, measured_on: '2026-10-01',
            measured_at: null, protocol: null, notes: null,
            photo_period_label: null, created_at: '2026-10-01T07:00:00Z',
          },
        }),
      },
    ]
    wrap(<Measurements />)
    await userEvent.click(await waitFor(() =>
      screen.getByRole('button', { name: /Add readings/i }),
    ))
    await waitFor(() => screen.getByLabelText(/^Waist$/i))
    await userEvent.type(screen.getByLabelText(/^Waist$/i), '-5')
    await userEvent.click(screen.getByRole('button', { name: /Save 1 reading/i }))

    await waitFor(() =>
      expect(screen.getByText(/not a measurement/i)).toBeInTheDocument(),
    )
    expect(
      calls.filter((c) => c.method === 'POST' && c.url.includes('/coach/measurements')),
    ).toHaveLength(0)
  })

  it('shows nothing rather than an empty chart when there are no readings', async () => {
    handlers = [
      todayHandler, typesHandler([waistType]), periodsHandler([]),
      measurementsHandler([]),
    ]
    wrap(<Measurements />)
    await waitFor(() =>
      expect(screen.getByText(/No readings yet for Waist/i)).toBeInTheDocument(),
    )
    expect(screen.getByText(/No measurement sessions yet/i)).toBeInTheDocument()
  })
})
