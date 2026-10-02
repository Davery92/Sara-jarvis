/**
 * Fitness → Overview: the one place the coach's picture of today lives.
 *
 * FITNESS_COACH_IMPLEMENTATION_PLAN Step 18. Every number here comes from
 * `/api/fitness/coach/state`, which is the same projection the chat capsule,
 * the weekly report and the coach review read. Nothing on this page computes
 * a trend, an average or an adherence figure — a component that derives its
 * own number is how two screens come to disagree.
 *
 * Four rules the rendering follows:
 *
 * 1. **A metric with no value says why, and never renders as zero.** "0 kg
 *    lost" and "we can't tell yet" lead to opposite decisions.
 * 2. **Every number shows its coverage.** `81.2 kg` alone reads as settled;
 *    `81.2 kg · 3 of 7 days` reads as what it is.
 * 3. **A degraded state says so before anything else.** Fewer metrics
 *    because a query broke looks exactly like an athlete with less data.
 * 4. **Charts draw gaps as gaps.** `connectNulls` is off and the x-axis is
 *    real dates, so a week with two weigh-ins is not drawn as a smooth line
 *    through five points nobody recorded.
 */
import React, { useMemo } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AlertTriangle, Info, RefreshCw } from 'lucide-react'

import { useFitnessState } from '../../hooks/useFitnessCoach'
import type {
  FitnessState,
  Metric,
  MetricGroup,
  PainItem,
  StateSection,
} from '../../types/fitnessCoach'

const CARD =
  'rounded-xl border border-white/10 bg-white/[0.03] p-4 flex flex-col gap-2'
const SECTION = 'text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400'
const VALUE = 'text-2xl font-semibold text-slate-100 tabular-nums'
const SUB = 'text-xs text-slate-400'

const UNAVAILABLE_TEXT: Record<string, string> = {
  no_data: 'nothing recorded yet',
  insufficient_coverage: 'not enough recorded to say',
  no_target: 'no target recorded',
  unknown_unit: 'the unit was never recorded',
  not_comparable: 'the readings are not comparable',
  dependency_failed: 'could not be read',
  not_applicable: 'does not apply here',
}

/** What would actually help, phrased as the next thing to do. */
const NEXT_STEP: Record<string, string> = {
  no_data: 'Start logging it and this fills in.',
  insufficient_coverage: 'Keep logging — a few more days and this resolves.',
  no_target: 'Set a target and this becomes a comparison.',
  unknown_unit: 'Confirm the unit on those entries.',
  not_comparable: 'Measure the same way twice and this becomes a change.',
  dependency_failed: 'Nothing to do — this is a fault on our side.',
}

/**
 * Precision chosen per unit, not globally.
 *
 * A weekly rate gets two decimals: prescribed cuts are routinely 0.35 or
 * 0.25 kg/week, and one decimal rounds those to the same 0.3 — so the screen
 * would show the athlete hitting a target they are not hitting. Calories and
 * counts get none, because a tenth of a kcal is noise dressed as precision.
 */
function formatNumber(value: number, unit: string): string {
  let decimals = 1
  if (unit === 'kcal' || unit === 'count' || unit === 'g' || unit === 'ml') decimals = 0
  else if (unit === 'kg/week' || unit === '%/week') decimals = 2
  return value.toFixed(decimals).replace(/\.0+$/, '')
}

function unitLabel(unit: string): string {
  if (unit === 'count' || unit === 'unknown') return ''
  if (unit === 'score') return '/10'
  return ` ${unit}`
}

function coverage(metric: Metric): string | null {
  if (metric.observed_days == null || metric.expected_days == null) return null
  return `${metric.observed_days} of ${metric.expected_days} days`
}

/**
 * One metric. The unavailable branch is not an error state — it is the
 * ordinary case for a new athlete, and it has to read like an answer.
 */
function MetricTile({
  label,
  metric,
  signed = false,
}: {
  label: string
  metric: Metric | undefined
  signed?: boolean
}) {
  if (!metric) return null

  if (metric.value == null) {
    const reason = metric.unavailable_reason ?? 'no_data'
    return (
      <div className={CARD} data-testid={`metric-${metric.key}`}>
        <span className={SECTION}>{label}</span>
        <span className="text-base text-slate-400" data-testid="metric-unavailable">
          {UNAVAILABLE_TEXT[reason] ?? reason}
        </span>
        {metric.note ? <span className={SUB}>{metric.note}</span> : null}
        <span className="text-[11px] text-slate-500">{NEXT_STEP[reason] ?? ''}</span>
      </div>
    )
  }

  const rendered = formatNumber(metric.value, metric.unit)
  const withSign = signed && metric.value > 0 ? `+${rendered}` : rendered
  const cover = coverage(metric)

  return (
    <div className={CARD} data-testid={`metric-${metric.key}`}>
      <span className={SECTION}>{label}</span>
      <span className={VALUE}>
        {withSign}
        <span className="text-sm font-normal text-slate-400">
          {unitLabel(metric.unit)}
        </span>
      </span>
      {/* Coverage always, when the backend states it. A bare figure reads as
          settled, and that is how three days of data becomes a decision. */}
      {cover ? <span className={SUB} data-testid="metric-coverage">{cover}</span> : null}
      {metric.note ? <span className="text-[11px] text-slate-500">{metric.note}</span> : null}
      {metric.quality_flags.length > 0 ? (
        <span className="text-[11px] text-amber-300/80" data-testid="metric-flags">
          {metric.quality_flags.join(', ').replace(/_/g, ' ')}
        </span>
      ) : null}
    </div>
  )
}

function DegradedBanner({ state }: { state: FitnessState }) {
  if (state.freshness !== 'degraded') return null
  return (
    <div
      className="rounded-xl border border-amber-400/40 bg-amber-400/[0.06] p-3 flex items-start gap-2"
      data-testid="degraded-banner"
      role="status"
    >
      <AlertTriangle className="w-4 h-4 text-amber-300 mt-0.5 flex-shrink-0" />
      <div className="text-xs text-amber-200/90">
        <p className="font-medium">Some of this could not be read.</p>
        <p className="mt-0.5">
          {state.degraded_dependencies.join(', ')} failed to load. Treat what
          is below as incomplete rather than as all there is — this is a fault
          on our side, not a gap in your logging.
        </p>
      </div>
    </div>
  )
}

function GoalAndPhase({ state }: { state: FitnessState }) {
  const primary = state.goals.find((goal) => goal.is_primary)
  const phase = state.program?.phase
  const dayType = state.program?.day_type

  let rate: string | null = null
  if (primary?.rate_basis === 'absolute' && primary.target_rate_kg_week != null) {
    rate = `${primary.target_rate_kg_week} kg/week`
  } else if (primary?.rate_basis === 'percent' && primary.target_rate_percent_week != null) {
    rate = `${primary.target_rate_percent_week}%/week`
  }

  return (
    <div className={CARD} data-testid="goal-and-phase">
      <span className={SECTION}>Goal</span>
      {primary ? (
        <>
          <span className="text-lg text-slate-100 capitalize">{primary.kind}</span>
          {rate ? <span className={SUB}>Target rate {rate}</span> : null}
          <span className="text-[11px] text-slate-500">
            In force since {primary.valid_from}
          </span>
        </>
      ) : (
        <span className="text-base text-slate-400">
          No goal recorded. Everything below is description, not progress
          toward anything.
        </span>
      )}
      {phase?.name ? (
        <div className="pt-2 mt-1 border-t border-white/[0.06]">
          <span className={SECTION}>Block</span>
          <p className="text-sm text-slate-200">{phase.name}</p>
          <p className="text-[11px] text-slate-500">
            {phase.start_date ?? '?'} → {phase.end_date_inclusive ?? 'open'}
            {phase.deload_week ? ` · deload week ${phase.deload_week}` : ''}
          </p>
          {dayType ? (
            <p className={SUB} data-testid="day-type">
              Today is a {dayType} day
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function TargetsCard({ state }: { state: FitnessState }) {
  const targets = state.targets
  const nutrition = state.sections.nutrition
  return (
    <div className={CARD} data-testid="targets-card">
      <span className={SECTION}>Today's targets</span>
      {targets && targets.values.calories != null ? (
        <>
          <span className={VALUE}>
            {targets.values.calories}
            <span className="text-sm font-normal text-slate-400"> kcal</span>
          </span>
          <span className={SUB}>
            {targets.values.protein_g != null ? `${targets.values.protein_g} g protein` : 'protein not set'}
            {targets.values.carbs_g != null ? ` · ${targets.values.carbs_g} g carbs` : ''}
            {targets.values.fat_g != null ? ` · ${targets.values.fat_g} g fat` : ''}
          </span>
          {/* Provenance, not decoration: legacy targets come from a mutable
              column and cannot answer what the target was last month. */}
          {targets.provenance === 'legacy_phase' || targets.provenance === 'legacy_default' ? (
            <span className="text-[11px] text-amber-300/80" data-testid="target-provenance">
              No recorded history behind these — they describe today only.
            </span>
          ) : null}
          {targets.history_unknown ? (
            <span className="text-[11px] text-amber-300/80">
              A revision history exists but none covers this date.
            </span>
          ) : null}
        </>
      ) : (
        <span className="text-base text-slate-400" data-testid="no-target">
          No target recorded for today, so adherence cannot be computed.
        </span>
      )}
      {nutrition ? (
        <div className="pt-2 mt-1 border-t border-white/[0.06] flex flex-col gap-1">
          <span className={SECTION}>Logged</span>
          <InlineMetric label="Calories" metric={nutrition.metrics.calories_mean} />
          <InlineMetric label="Protein" metric={nutrition.metrics.protein_mean} />
          <span className="text-[11px] text-slate-500" data-testid="nutrition-coverage">
            {state.quality.nutrition_complete_days} fully logged ·{' '}
            {state.quality.nutrition_partial_days} partial ·{' '}
            {state.quality.nutrition_unknown_days} unknown
          </span>
        </div>
      ) : null}
    </div>
  )
}

function InlineMetric({ label, metric }: { label: string; metric: Metric | undefined }) {
  if (!metric) return null
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm">
      <span className="text-slate-400">{label}</span>
      {metric.value == null ? (
        <span className="text-slate-500 text-xs">
          {UNAVAILABLE_TEXT[metric.unavailable_reason ?? 'no_data']}
        </span>
      ) : (
        <span className="text-slate-100 tabular-nums">
          {formatNumber(metric.value, metric.unit)}
          {unitLabel(metric.unit)}
          {metric.observed_days != null ? (
            <span className="text-slate-500 text-xs"> · {metric.observed_days}d</span>
          ) : null}
        </span>
      )}
    </div>
  )
}

/**
 * The weight series.
 *
 * Points are plotted against real dates with `connectNulls` off, so a gap in
 * the log is a gap in the line. Interpolating would draw readings that were
 * never taken, and a plateau is exactly the kind of conclusion someone would
 * then draw from the invented segment.
 */
function WeightChart({ group }: { group: MetricGroup | undefined }) {
  const points = useMemo(() => {
    const items = (group?.items ?? []) as Array<{ date?: string; value?: number }>
    return items
      .filter((item) => typeof item.date === 'string')
      .map((item) => ({
        date: item.date as string,
        value: typeof item.value === 'number' ? item.value : null,
      }))
  }, [group])

  if (points.length === 0) {
    return (
      <p className={SUB} data-testid="weight-chart-empty">
        No weigh-ins in this window, so there is nothing to plot. One reading
        is a weight; a line needs several.
      </p>
    )
  }

  if (points.length === 1) {
    return (
      <p className={SUB} data-testid="weight-chart-single">
        One weigh-in ({points[0].date}). A single reading is a weight, not a
        trend — no line is drawn from it.
      </p>
    )
  }

  const unit = group?.metrics?.latest?.unit ?? ''
  return (
    <div data-testid="weight-chart">
      <ResponsiveContainer width="100%" height={160}>
        <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fill: '#64748b', fontSize: 10 }}
            stroke="rgba(255,255,255,0.08)"
          />
          <YAxis
            domain={['auto', 'auto']}
            tick={{ fill: '#64748b', fontSize: 10 }}
            stroke="rgba(255,255,255,0.08)"
            width={44}
          />
          <Tooltip
            contentStyle={{
              background: '#0b1220',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 8,
              fontSize: 12,
            }}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke="#2dd4bf"
            strokeWidth={2}
            dot={{ r: 2.5, fill: '#2dd4bf' }}
            /* Off on purpose: a gap in the log is a gap in the line. */
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="text-[11px] text-slate-500 mt-1" data-testid="weight-chart-coverage">
        {points.filter((p) => p.value != null).length} readings plotted
        {unit ? ` in ${unit}` : ''}. Gaps are days with no weigh-in, not flat
        stretches.
      </p>
    </div>
  )
}

function TrainingCard({ state }: { state: FitnessState }) {
  const group = state.sections.training
  if (!group) return null
  return (
    <div className={CARD} data-testid="training-card">
      <span className={SECTION}>Training</span>
      <InlineMetric label="Sessions" metric={group.metrics.sessions_completed} />
      <InlineMetric label="Working sets" metric={group.metrics.working_sets} />
      <InlineMetric label="Adherence" metric={group.metrics.session_adherence} />
      <InlineMetric label="Tonnage" metric={group.metrics.tonnage} />
      {group.limitations.map((note) => (
        <span key={note} className="text-[11px] text-slate-500">
          {note}
        </span>
      ))}
    </div>
  )
}

function RecoveryCard({ state }: { state: FitnessState }) {
  const sleep = state.sections.sleep
  const recovery = state.sections.recovery
  if (!sleep && !recovery) return null
  return (
    <div className={CARD} data-testid="recovery-card">
      <span className={SECTION}>Sleep &amp; recovery</span>
      {sleep ? (
        <>
          <InlineMetric label="Sleep" metric={sleep.metrics.mean_hours} />
          <InlineMetric label="Bedtime spread" metric={sleep.metrics.bedtime_consistency} />
          <span className="text-[11px] text-slate-500" data-testid="sleep-coverage">
            {state.quality.sleep_nights ?? 0} nights recorded
          </span>
        </>
      ) : null}
      {recovery
        ? Object.entries(recovery.metrics)
            .filter(([key]) => key.endsWith('_mean'))
            .map(([key, metric]) => (
              <InlineMetric
                key={key}
                label={key.replace('_mean', '').replace(/_/g, ' ')}
                metric={metric}
              />
            ))
        : null}
    </div>
  )
}

function PainCard({ state }: { state: FitnessState }) {
  const group = state.sections.pain
  const items = (group?.items ?? []) as unknown as PainItem[]
  if (items.length === 0) return null
  return (
    <div className={CARD} data-testid="pain-card">
      <span className={SECTION}>Reported pain</span>
      {items.slice(0, 4).map((item) => (
        <div key={`${item.exercise}-${item.exercise_library_id ?? ''}`} className="text-sm">
          <span className="text-slate-200">{item.exercise}</span>
          {/* The denominator is the claim. "4 reports" could all be one
              session; "4 of 6 sessions that were asked about" is a pattern. */}
          <span className="text-slate-500 text-xs">
            {' '}
            — {item.sessions_with_pain} of {item.sessions_with_report} sessions
            that were asked about
          </span>
        </div>
      ))}
      <span className="text-[11px] text-slate-500">
        What you reported, not a diagnosis. A session with no report is
        unknown, not pain-free.
      </span>
    </div>
  )
}

/**
 * One next step, chosen deterministically.
 *
 * One, because a list of eight is a list nobody reads. The order is: a fault
 * on our side, then a missing target (which makes every adherence figure
 * impossible), then the thinnest coverage. Nothing here is "overdue" unless
 * the athlete opted into that cadence.
 */
function priorityAction(state: FitnessState): { text: string; kind: string } | null {
  if (state.freshness === 'degraded') {
    return {
      kind: 'degraded',
      text: `We could not read ${state.degraded_dependencies.join(', ')}. Nothing for you to do — this is on us.`,
    }
  }
  if (state.goals.length === 0) {
    return {
      kind: 'no_goal',
      text: 'Set a primary goal. Without one there is nothing to measure progress against.',
    }
  }
  if (state.quality.no_effective_target) {
    return {
      kind: 'no_target',
      text: 'Record calorie and protein targets. Adherence cannot be computed without them.',
    }
  }
  const observed = state.quality.observed_weight_days
  const expected = state.quality.expected_weight_days
  if (observed != null && expected != null && observed < 3) {
    return {
      kind: 'weight_coverage',
      text: `Only ${observed} of ${expected} days have a weigh-in. Three is the minimum for a weekly rate.`,
    }
  }
  if (state.quality.nutrition_complete_days < 3) {
    return {
      kind: 'nutrition_coverage',
      text: `${state.quality.nutrition_complete_days} fully logged days this window. Confirming three makes the intake average meaningful.`,
    }
  }
  if (state.quality.overdue_cadences.length > 0) {
    return {
      kind: 'overdue',
      text: `Due on your own schedule: ${state.quality.overdue_cadences.join(', ')}.`,
    }
  }
  if (state.quality.unresolved_exercise_identities > 0) {
    return {
      kind: 'unresolved_exercises',
      text: `${state.quality.unresolved_exercise_identities} logged exercises are not linked to the library, so they are excluded from strength trends.`,
    }
  }
  return null
}

export default function CoachOverview() {
  const stateQuery = useFitnessState({ span: 7 })
  const state = stateQuery.data

  if (stateQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-400 py-8">
        <RefreshCw className="w-4 h-4 animate-spin" />
        Loading your state…
      </div>
    )
  }

  if (stateQuery.isError || !state) {
    return (
      <div
        className="rounded-xl border border-amber-400/40 bg-amber-400/[0.06] p-4 text-sm text-amber-200/90"
        data-testid="overview-error"
        role="alert"
      >
        Could not load your fitness state
        {stateQuery.error?.message ? `: ${stateQuery.error.message}` : '.'} This
        is a read failure, not an empty log — nothing has been lost.
      </div>
    )
  }

  const action = priorityAction(state)
  const weight = state.sections.weight

  return (
    <div className="flex flex-col gap-4" data-testid="coach-overview">
      <DegradedBanner state={state} />

      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-slate-200">Overview</h2>
        <span className="text-[11px] text-slate-500" data-testid="as-of">
          {state.athlete_local_date} · {state.timezone}
          {state.period ? ` · window ${state.period.start} → ${state.period.end}` : ''}
        </span>
      </div>

      {action ? (
        <div
          className="rounded-xl border border-teal-400/30 bg-teal-400/[0.06] p-3 flex items-start gap-2"
          data-testid="priority-action"
          data-kind={action.kind}
        >
          <Info className="w-4 h-4 text-teal-300 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-teal-100/90">{action.text}</p>
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <GoalAndPhase state={state} />
        <TargetsCard state={state} />
        <MetricTile label="Latest weight" metric={weight?.metrics?.latest} />
        <MetricTile
          label="Weekly change"
          metric={weight?.metrics?.velocity_weekly}
          signed
        />
        <TrainingCard state={state} />
        <RecoveryCard state={state} />
        <PainCard state={state} />
      </div>

      <div className={CARD}>
        <span className={SECTION}>Weight</span>
        <WeightChart group={weight} />
      </div>

      {state.quality.missing_fields.length > 0 ? (
        <details className={CARD} data-testid="missing-fields">
          <summary className="cursor-pointer text-xs text-slate-400">
            {state.quality.missing_fields.length} metrics unavailable — what
            would help
          </summary>
          <ul className="mt-2 flex flex-col gap-1">
            {state.quality.missing_fields.map((field) => {
              const [name, reason] = field.split(': ')
              return (
                <li key={field} className="text-[11px] text-slate-500">
                  <span className="text-slate-400">{name}</span> —{' '}
                  {UNAVAILABLE_TEXT[reason ?? ''] ?? reason}
                  {NEXT_STEP[reason ?? ''] ? ` ${NEXT_STEP[reason ?? '']}` : ''}
                </li>
              )
            })}
          </ul>
        </details>
      ) : null}
    </div>
  )
}
