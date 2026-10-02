/**
 * Step 18 of FITNESS_COACH_IMPLEMENTATION_PLAN: the Overview works with
 * full, partial and no data, and never dresses an absence as a number.
 *
 * The display claims being pinned:
 *
 * - **An unavailable metric renders its reason, never zero.** "0 kg lost"
 *   and "we can't tell yet" lead to opposite decisions about a cut.
 * - **Every number shows its coverage.** `81.2 kg` alone reads as settled.
 * - **One weigh-in draws no line.** A single reading is a weight, not a
 *   trend, and a two-point chart through a gap invites reading a plateau
 *   that nobody measured.
 * - **A degraded state says so first.** Fewer metrics because a query broke
 *   looks exactly like an athlete who logged less.
 * - **Exactly one priority action**, chosen deterministically — a list of
 *   eight is a list nobody reads.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CoachOverview from '../CoachOverview'
import type {
  AthleteGoal,
  DataQuality,
  FitnessState,
  Metric,
  MetricGroup,
} from '../../../types/fitnessCoach'

const ATHLETE = 'athlete-overview'

vi.mock('../../../stores/authStore', () => ({
  useAuthStore: (selector: (s: unknown) => unknown) =>
    selector({ user: { id: ATHLETE, email: 'a@example.invalid' } }),
}))

// Recharts needs real layout; jsdom gives it none, so ResponsiveContainer
// renders nothing without a fixed size. Stubbing it keeps these tests about
// the surrounding claims rather than about SVG geometry.
vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 400, height: 200 }}>{children}</div>
    ),
  }
})

function metric(key: string, over: Partial<Metric> = {}): Metric {
  return {
    key, value: null, unit: 'count', source_count: 0,
    quality_flags: [], analytics_version: 1, ...over,
  }
}

function quality(over: Partial<DataQuality> = {}): DataQuality {
  return {
    observed_weight_days: null, expected_weight_days: null, sleep_nights: null,
    nutrition_complete_days: 0, nutrition_partial_days: 0,
    nutrition_unknown_days: 0, missing_fields: [], unresolved_units: 0,
    unresolved_exercise_identities: 0, source_conflicts: 0,
    incomplete_workouts: 0, overdue_cadences: [], stale_profile: false,
    no_effective_target: false, insufficient_comparable_exposures: [],
    notes: [], ...over,
  }
}

const goal: AthleteGoal = {
  id: 'g1', user_id: ATHLETE, recorded_at: '2026-09-01T12:00:00Z',
  kind: 'cut', is_primary: true, priority: 1, rationale: null,
  target_weight_kg: null, rate_basis: 'absolute',
  target_rate_kg_week: -0.4, target_rate_percent_week: null,
  strength_targets: {}, valid_from: '2026-09-01', valid_until: null,
  source: 'user', supersedes_id: null, approved_at: null,
}

function weightGroup(over: Partial<MetricGroup> = {}): MetricGroup {
  return {
    section: 'weight',
    metrics: {
      latest: metric('weight.latest', {
        value: 81.2, unit: 'kg', observed_days: 1, expected_days: 1,
        note: 'measured 2026-09-30',
      }),
      velocity_weekly: metric('weight.velocity_weekly', {
        value: -0.35, unit: 'kg/week', observed_days: 5, expected_days: 7,
      }),
    },
    items: [
      { date: '2026-09-25', value: 81.6, unit: 'kg' },
      { date: '2026-09-27', value: 81.4, unit: 'kg' },
      { date: '2026-09-30', value: 81.2, unit: 'kg' },
    ],
    limitations: [],
    ...over,
  }
}

function state(over: Partial<FitnessState> = {}): FitnessState {
  return {
    schema_version: 1, analytics_version: 1, user_id: ATHLETE,
    as_of: '2026-10-01T12:00:00Z', athlete_local_date: '2026-10-01',
    timezone: 'America/New_York',
    period: { start: '2026-09-24', end: '2026-10-01' },
    freshness: 'fresh', data_revision: 'rev-1',
    profile: null, goals: [goal], limitations: [], targets: null,
    program: {}, sections: {}, quality: quality(),
    recent_changes: [], evidence_refs: [], degraded_dependencies: [],
    ...over,
  }
}

let served: FitnessState | null = null
let status = 200

function stubFetch() {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/coach/state')) {
      return new Response(JSON.stringify(served ?? {}), {
        status, headers: { 'Content-Type': 'application/json' },
      })
    }
    return new Response(JSON.stringify({}), {
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

beforeEach(() => {
  served = state()
  status = 200
  stubFetch()
})

// ── Full data ─────────────────────────────────────────────────────────────

describe('with data', () => {
  it('shows the latest weight with the date it was measured', async () => {
    served = state({ sections: { weight: weightGroup() } })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('coach-overview')).toBeTruthy())

    const tile = screen.getByTestId('metric-weight.latest')
    expect(tile.textContent).toContain('81.2')
    expect(tile.textContent).toContain('kg')
    expect(tile.textContent).toContain('measured 2026-09-30')
  })

  it('attaches coverage to the weekly change', async () => {
    served = state({ sections: { weight: weightGroup() } })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('metric-weight.velocity_weekly')).toBeTruthy())

    const tile = screen.getByTestId('metric-weight.velocity_weekly')
    expect(tile.textContent).toContain('-0.35')
    expect(tile.textContent).toContain('5 of 7 days')
  })

  it('signs a positive change so direction is unambiguous', async () => {
    const group = weightGroup()
    group.metrics.velocity_weekly = metric('weight.velocity_weekly', {
      value: 0.3, unit: 'kg/week', observed_days: 6, expected_days: 7,
    })
    served = state({ sections: { weight: group } })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('metric-weight.velocity_weekly')).toBeTruthy())
    expect(screen.getByTestId('metric-weight.velocity_weekly').textContent).toContain('+0.3')
  })

  it('states the goal and its target rate', async () => {
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('goal-and-phase')).toBeTruthy())
    const card = screen.getByTestId('goal-and-phase')
    expect(card.textContent).toContain('cut')
    expect(card.textContent).toContain('-0.4 kg/week')
    expect(card.textContent).toContain('since 2026-09-01')
  })

  it('shows the block and whether today is a training day', async () => {
    served = state({
      program: {
        phase: {
          id: 'p1', name: 'Hypertrophy Block 2', start_date: '2026-09-01',
          end_date_inclusive: '2026-10-26', deload_week: 4,
        },
        day_type: 'training',
      },
    })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('goal-and-phase')).toBeTruthy())
    const card = screen.getByTestId('goal-and-phase')
    expect(card.textContent).toContain('Hypertrophy Block 2')
    // The INCLUSIVE end date, as stored. Showing the converted half-open
    // value here would make this screen and the plan view disagree by a day.
    expect(card.textContent).toContain('2026-10-26')
    expect(screen.getByTestId('day-type').textContent).toContain('training')
  })

  it('plots the weight series and says gaps are gaps', async () => {
    served = state({ sections: { weight: weightGroup() } })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('weight-chart')).toBeTruthy())
    expect(screen.getByTestId('weight-chart-coverage').textContent).toContain('3 readings')
    expect(screen.getByTestId('weight-chart-coverage').textContent).toContain(
      'not flat stretches',
    )
  })
})

// ── Partial data ──────────────────────────────────────────────────────────

describe('with partial data', () => {
  it('renders an unavailable metric as a reason, not as zero', async () => {
    const group = weightGroup({
      metrics: {
        latest: metric('weight.latest', {
          value: 81.2, unit: 'kg', note: 'measured 2026-09-30',
        }),
        velocity_weekly: metric('weight.velocity_weekly', {
          unit: 'kg/week', unavailable_reason: 'insufficient_coverage',
          observed_days: 2, expected_days: 7,
          note: 'two weigh-ins cannot establish a weekly rate',
        }),
      },
    })
    served = state({ sections: { weight: group } })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('metric-weight.velocity_weekly')).toBeTruthy())

    const tile = screen.getByTestId('metric-weight.velocity_weekly')
    expect(tile.textContent).toContain('not enough recorded to say')
    expect(tile.textContent).toContain('cannot establish a weekly rate')
    expect(tile.textContent).toContain('Keep logging')
    // The thing this test exists for.
    expect(tile.textContent).not.toMatch(/\b0\b/)
  })

  it('draws no line from a single weigh-in', async () => {
    served = state({
      sections: {
        weight: weightGroup({ items: [{ date: '2026-09-30', value: 81.2, unit: 'kg' }] }),
      },
    })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('weight-chart-single')).toBeTruthy())
    expect(screen.getByTestId('weight-chart-single').textContent).toContain(
      'a weight, not a trend',
    )
    expect(screen.queryByTestId('weight-chart')).toBeNull()
  })

  it('says so when no weigh-in falls in the window at all', async () => {
    served = state({ sections: { weight: weightGroup({ items: [] }) } })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('weight-chart-empty')).toBeTruthy())
    expect(screen.queryByTestId('weight-chart')).toBeNull()
  })

  it('reports the three nutrition day counts separately', async () => {
    served = state({
      sections: {
        nutrition: {
          section: 'nutrition',
          metrics: {
            calories_mean: metric('nutrition.calories_mean', {
              value: 3010, unit: 'kcal', observed_days: 3, expected_days: 7,
            }),
          },
          items: [], limitations: [],
        },
      },
      quality: quality({
        nutrition_complete_days: 3, nutrition_partial_days: 2,
        nutrition_unknown_days: 2,
      }),
    })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('nutrition-coverage')).toBeTruthy())
    const text = screen.getByTestId('nutrition-coverage').textContent ?? ''
    expect(text).toContain('3 fully logged')
    expect(text).toContain('2 partial')
    expect(text).toContain('2 unknown')
  })

  it('flags targets that have no recorded history behind them', async () => {
    served = state({
      targets: {
        user_id: ATHLETE, on_date: '2026-10-01', day_type: 'training',
        values: {
          calories: 3000, protein_g: 200, carbs_g: null, fat_g: null,
          sleep_hours: null, water_ml: null, steps: null,
          calorie_tolerance_pct: 10, protein_tolerance_pct: 10,
        },
        provenance: 'legacy_phase', scope: null, phase_id: null,
        phase_name: null, revision_id: null, revision_version: null,
        effective_from: null, effective_until: null, history_unknown: false,
      },
    })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('target-provenance')).toBeTruthy())
    expect(screen.getByTestId('target-provenance').textContent).toContain(
      'describe today only',
    )
  })

  it('keeps the pain denominator with the count', async () => {
    served = state({
      sections: {
        pain: {
          section: 'pain',
          metrics: {},
          items: [
            {
              exercise: 'Barbell Curl', exercise_library_id: 'e1',
              sessions_with_pain: 4, sessions_with_report: 6,
              sessions_total: 9, reporting_coverage: 0.67,
              max_severity: 5, locations: ['elbow'], sides: ['left'],
            },
          ],
          limitations: [],
        },
      },
    })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('pain-card')).toBeTruthy())
    const card = screen.getByTestId('pain-card')
    expect(card.textContent).toContain('4 of 6 sessions')
    expect(card.textContent).toContain('not a diagnosis')
  })

  it('lists what would help for each unavailable metric', async () => {
    served = state({
      quality: quality({
        missing_fields: [
          'weight.velocity_weekly: insufficient_coverage',
          'nutrition.calorie_adherence: no_target',
        ],
      }),
    })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('missing-fields')).toBeTruthy())
    const block = screen.getByTestId('missing-fields')
    expect(block.textContent).toContain('weight.velocity_weekly')
    expect(block.textContent).toContain('Keep logging')
    expect(block.textContent).toContain('Set a target')
  })
})

// ── No data ───────────────────────────────────────────────────────────────

describe('with no data', () => {
  it('renders without a goal and says what that means', async () => {
    served = state({ goals: [] })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('goal-and-phase')).toBeTruthy())
    expect(screen.getByTestId('goal-and-phase').textContent).toContain(
      'No goal recorded',
    )
  })

  it('says adherence is impossible with no target rather than showing 0%', async () => {
    served = state({ targets: null })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('no-target')).toBeTruthy())
    expect(screen.getByTestId('no-target').textContent).toContain(
      'adherence cannot be computed',
    )
  })

  it('omits sections the backend did not compute instead of rendering empties', async () => {
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('coach-overview')).toBeTruthy())
    expect(screen.queryByTestId('training-card')).toBeNull()
    expect(screen.queryByTestId('recovery-card')).toBeNull()
    expect(screen.queryByTestId('pain-card')).toBeNull()
  })
})

// ── Degraded and failed ───────────────────────────────────────────────────

describe('degradation', () => {
  it('leads with the banner and names what failed', async () => {
    served = state({
      freshness: 'degraded',
      degraded_dependencies: ['training', 'pain'],
      sections: { weight: weightGroup() },
    })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('degraded-banner')).toBeTruthy())

    const banner = screen.getByTestId('degraded-banner')
    expect(banner.textContent).toContain('training, pain')
    expect(banner.textContent).toContain('incomplete rather than as all there is')
    // And it says whose fault it is, so nobody goes looking for a logging gap.
    expect(banner.textContent).toContain('not a gap in your logging')
    // The sections that worked are still shown.
    expect(screen.getByTestId('metric-weight.latest').textContent).toContain('81.2')
  })

  it('makes the degradation the priority action', async () => {
    served = state({
      freshness: 'degraded', degraded_dependencies: ['sleep'],
    })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('priority-action')).toBeTruthy())
    expect(screen.getByTestId('priority-action').dataset.kind).toBe('degraded')
  })

  it('distinguishes a failed read from an empty log', async () => {
    status = 500
    served = null
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('overview-error')).toBeTruthy())
    expect(screen.getByTestId('overview-error').textContent).toContain(
      'not an empty log',
    )
  })
})

// ── The single next step ──────────────────────────────────────────────────

describe('priority action', () => {
  it('shows exactly one', async () => {
    served = state({
      goals: [],
      quality: quality({
        no_effective_target: true, observed_weight_days: 0,
        expected_weight_days: 7, unresolved_exercise_identities: 11,
      }),
    })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('priority-action')).toBeTruthy())
    expect(screen.getAllByTestId('priority-action')).toHaveLength(1)
  })

  it('ranks a missing goal above thin coverage', async () => {
    served = state({
      goals: [],
      quality: quality({ observed_weight_days: 1, expected_weight_days: 7 }),
    })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('priority-action')).toBeTruthy())
    expect(screen.getByTestId('priority-action').dataset.kind).toBe('no_goal')
  })

  it('ranks a missing target above thin coverage', async () => {
    served = state({
      quality: quality({
        no_effective_target: true, observed_weight_days: 1,
        expected_weight_days: 7,
      }),
    })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('priority-action')).toBeTruthy())
    expect(screen.getByTestId('priority-action').dataset.kind).toBe('no_target')
  })

  it('never invents an overdue cadence the athlete did not ask for', async () => {
    served = state({
      quality: quality({
        observed_weight_days: 7, expected_weight_days: 7,
        nutrition_complete_days: 7, overdue_cadences: [],
      }),
    })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('coach-overview')).toBeTruthy())
    expect(screen.queryByTestId('priority-action')).toBeNull()
  })

  it('surfaces a cadence the athlete DID opt into', async () => {
    served = state({
      quality: quality({
        observed_weight_days: 7, expected_weight_days: 7,
        nutrition_complete_days: 7, overdue_cadences: ['tape measurements'],
      }),
    })
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('priority-action')).toBeTruthy())
    const action = screen.getByTestId('priority-action')
    expect(action.dataset.kind).toBe('overdue')
    expect(action.textContent).toContain('your own schedule')
  })
})

// ── Owner scope and bounds ────────────────────────────────────────────────

describe('the request', () => {
  it('asks for a bounded window', async () => {
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('coach-overview')).toBeTruthy())
    const urls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock
      .calls.map((call) => String(call[0]))
    const stateCall = urls.find((url) => url.includes('/coach/state'))
    expect(stateCall).toBeTruthy()
    expect(stateCall).toContain('span=7')
  })

  it('shows the athlete-local date and the window, not the browser clock', async () => {
    wrap(<CoachOverview />)
    await waitFor(() => expect(screen.getByTestId('as-of')).toBeTruthy())
    const text = screen.getByTestId('as-of').textContent ?? ''
    expect(text).toContain('2026-10-01')
    expect(text).toContain('America/New_York')
    expect(text).toContain('2026-09-24')
  })
})
