/**
 * Fitness → Today: one day's check-in.
 *
 * FITNESS_COACH_IMPLEMENTATION_PLAN Step 11.
 *
 * What this screen is careful about, in order of how badly getting it wrong
 * would mislead someone:
 *
 * 1. **An empty day shows no readiness score.** The underlying formula
 *    returns 100/"Excellent — good to push it today" for an empty input, and
 *    that has been displayed to someone who logged nothing. Here, no
 *    eligible inputs means the score is absent and the screen says what is
 *    missing.
 * 2. **Zero and unknown render differently.** An unlogged weight is
 *    "Not recorded", never `0 lb`. A genuine zero (an explicit 0-step rest
 *    day) renders as `0`.
 * 3. **One save per form, and only what changed goes up.** A PATCH that
 *    echoed the whole day back would overwrite the wearable's morning
 *    reading with whatever the form happened to hold.
 * 4. **Inputs survive a failed save.** The entered values stay on screen
 *    with an explicit "not saved" note, rather than being silently reset to
 *    server state.
 * 5. **The date comes from the server.** The browser's local date is not
 *    authoritative for a travelling athlete.
 */
import React, { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Check, ChevronLeft, ChevronRight, Utensils } from 'lucide-react'

import {
  useAthleteToday,
  useCheckIn,
  usePatchCheckIn,
  useResolvedTargets,
} from '../../hooks/useFitnessCoach'
import type { CheckInPatch, Metric } from '../../types/fitnessCoach'

const SECTION = 'text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400'
const LABEL = 'text-xs text-slate-400'
const FIELD =
  'w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-[15px] ' +
  'text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-teal-400/50'
const PRIMARY =
  'px-4 py-2 rounded-lg bg-teal-500/90 hover:bg-teal-400 text-slate-950 ' +
  'text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed'
const GHOST =
  'px-3 py-1.5 rounded-lg text-sm text-slate-400 hover:text-slate-200 ' +
  'hover:bg-white/[0.04] disabled:opacity-40'

/** 1-10 subjective fields, with the direction spelled out for the athlete. */
const SCALES: Array<{ field: keyof CheckInPatch; label: string; hint: string }> = [
  { field: 'sleep_quality', label: 'Sleep quality', hint: '10 = slept great' },
  { field: 'energy', label: 'Energy', hint: '10 = full of it' },
  { field: 'fatigue', label: 'Fatigue', hint: '10 = wiped out' },
  { field: 'soreness_level', label: 'Soreness', hint: '10 = very sore' },
  { field: 'stress', label: 'Stress', hint: '10 = very stressed' },
  { field: 'motivation', label: 'Motivation', hint: '10 = keen to train' },
  {
    field: 'subjective_readiness',
    label: 'How ready you feel',
    hint: 'your own call, separate from the score below',
  },
]

function shiftDate(iso: string, days: number): string {
  const [y, m, d] = iso.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d))
  dt.setUTCDate(dt.getUTCDate() + days)
  return dt.toISOString().slice(0, 10)
}

/**
 * Render a metric so that nothing is inventable from the output.
 *
 * `0` is a value and prints as `0`. `null` prints the reason it is absent.
 */
function MetricValue({ metric }: { metric: Metric | null | undefined }) {
  if (!metric || metric.value === null) {
    const reason = metric?.unavailable_reason
    const text =
      reason === 'unknown_unit' ? 'Recorded, unit unknown'
      : reason === 'insufficient_coverage' ? 'Not enough readings'
      : 'Not recorded'
    return <span className="text-[15px] text-slate-600">{text}</span>
  }
  return (
    <span className="text-[15px] text-slate-200">
      <span data-testid="metric-value">{metric.value}</span>
      <span className="text-xs text-slate-500 ml-1">{metric.unit}</span>
    </span>
  )
}

function SourceTag({ metric }: { metric: Metric | null | undefined }) {
  if (!metric || metric.value === null) return null
  const bits: string[] = []
  const source = metric.note?.replace(/^source:\s*/, '')
  if (source) bits.push(source === 'manual' ? 'you' : source)
  if (metric.source_count > 1) bits.push(`${metric.source_count} readings`)
  if (metric.quality_flags.includes('source_conflict')) bits.push('sources disagree')
  if (!bits.length) return null
  return <span className="text-[11px] text-slate-600">{bits.join(' · ')}</span>
}

function ErrorNote({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 text-xs text-amber-300/90 border-l-2 border-amber-400/70 pl-3 py-1">
      <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
      <span>{message}</span>
    </div>
  )
}

export default function DailyCheckIn({
  onOpenFoodLog,
}: {
  onOpenFoodLog?: () => void
}) {
  const todayQuery = useAthleteToday()
  const athleteToday = todayQuery.data?.athlete_local_date

  const [selectedDate, setSelectedDate] = useState<string | undefined>()
  useEffect(() => {
    // The server's athlete-local date, not `new Date()`. For a traveling
    // athlete those differ, and the server decides which day a log belongs to.
    if (athleteToday && !selectedDate) setSelectedDate(athleteToday)
  }, [athleteToday, selectedDate])

  const checkIn = useCheckIn(selectedDate)
  const patch = usePatchCheckIn(selectedDate)
  const targets = useResolvedTargets(
    selectedDate ? { onDate: selectedDate } : undefined,
  )

  const [edits, setEdits] = useState<CheckInPatch>({})
  const dirty = Object.keys(edits).length > 0

  // Switching day discards unsaved edits for the previous one rather than
  // carrying them across — applying Tuesday's answers to Wednesday would be
  // worse than losing them.
  useEffect(() => {
    setEdits({})
    patch.reset()
  }, [selectedDate])

  useEffect(() => {
    if (patch.isSuccess) setEdits({})
  }, [patch.isSuccess])

  const set = <K extends keyof CheckInPatch>(key: K, value: CheckInPatch[K]) =>
    setEdits((prev) => ({ ...prev, [key]: value }))

  const scaleValue = (field: keyof CheckInPatch): string => {
    if (field in edits) {
      const value = edits[field]
      return value === null || value === undefined ? '' : String(value)
    }
    const stored = checkIn.data?.[field as keyof typeof checkIn.data]
    return stored === null || stored === undefined ? '' : String(stored)
  }

  const onScaleChange = (field: keyof CheckInPatch) => (raw: string) => {
    if (raw === '') {
      set(field, null as never)
      return
    }
    const parsed = Number(raw)
    if (!Number.isFinite(parsed)) return
    set(field, parsed as never)
  }

  const save = () => {
    if (!dirty || !selectedDate) return
    patch.mutate({ ...edits, expected_version: checkIn.data?.row_version })
  }

  const conflict = patch.error?.kind === 'conflict'
  const readiness = checkIn.data?.computed_readiness ?? null
  const coverage = checkIn.data?.readiness_coverage ?? 'unknown'

  const remaining = useMemo(() => {
    // Display-only arithmetic on two server-supplied numbers. Nothing here
    // derives a target, an average or an adherence figure.
    const target = targets.data?.values.calories
    if (target === null || target === undefined) return null
    return { target }
  }, [targets.data])

  if (!selectedDate) {
    return <div className="p-6 text-sm text-slate-500">Loading your day…</div>
  }

  return (
    <div className="p-6 space-y-8 max-w-[740px]">
      {/* Date */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          aria-label="Previous day"
          className={GHOST}
          onClick={() => setSelectedDate(shiftDate(selectedDate, -1))}
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <input
          aria-label="Day"
          type="date"
          className={`${FIELD} max-w-[180px]`}
          value={selectedDate}
          max={athleteToday}
          onChange={(e) => e.target.value && setSelectedDate(e.target.value)}
        />
        <button
          type="button"
          aria-label="Next day"
          className={GHOST}
          disabled={Boolean(athleteToday) && selectedDate >= (athleteToday as string)}
          onClick={() => setSelectedDate(shiftDate(selectedDate, 1))}
        >
          <ChevronRight className="w-4 h-4" />
        </button>
        {selectedDate === athleteToday && (
          <span className="text-xs text-slate-500">Today</span>
        )}
      </div>

      {checkIn.isError && <ErrorNote message={checkIn.error.message} />}
      {conflict && (
        <ErrorNote
          message={
            'This day was updated somewhere else while this form was open' +
            (patch.error?.currentVersion
              ? ` (now at version ${patch.error.currentVersion})` : '') +
            '. Nothing you typed was saved — your entries are still below.'
          }
        />
      )}
      {patch.isError && !conflict && <ErrorNote message={patch.error.message} />}

      {/* ── What's already known ──────────────────────────────────────── */}
      <section className="space-y-3">
        <h2 className={SECTION}>Already recorded</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          {([
            ['Weight', checkIn.data?.weight],
            ['Sleep', checkIn.data?.sleep_duration],
            ['Steps', checkIn.data?.steps],
            ['HRV', checkIn.data?.hrv],
            ['Resting HR', checkIn.data?.resting_heart_rate],
            ['Water', checkIn.data?.water],
          ] as const).map(([label, metric]) => (
            <div key={label} className="space-y-0.5">
              <div className={LABEL}>{label}</div>
              <MetricValue metric={metric} />
              <div><SourceTag metric={metric} /></div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Readiness ─────────────────────────────────────────────────── */}
      <section className="space-y-2">
        <h2 className={SECTION}>Readiness</h2>
        {readiness === null ? (
          <div className="space-y-1">
            <p className="text-[15px] text-slate-400">No score for this day</p>
            <p className="text-xs text-slate-600">
              Sara needs at least one of sleep, HRV, resting heart rate or
              soreness to say anything. With none of them she says nothing
              rather than assuming the day went well.
            </p>
          </div>
        ) : (
          <div className="space-y-1">
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-display text-white">{readiness.score}</span>
              <span className="text-[15px] text-slate-300">{readiness.label}</span>
              {coverage === 'partial' && (
                <span className="text-[11px] text-amber-300/80">
                  partial data
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500">{readiness.status}</p>
            {readiness.inputs_missing.length > 0 && (
              <p className="text-[11px] text-slate-600">
                Computed without {readiness.inputs_missing
                  .map((f) => f.replace(/_/g, ' '))
                  .join(', ')}.
              </p>
            )}
            {readiness.factors.length > 0 && (
              <ul className="text-[11px] text-slate-600 list-none space-y-0.5">
                {readiness.factors.map((factor) => (
                  <li key={factor}>· {factor}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        {checkIn.data?.subjective_readiness != null && (
          <p className="text-xs text-slate-500">
            You said you feel like a {checkIn.data.subjective_readiness}/10.
          </p>
        )}
      </section>

      {/* ── Today's answers ───────────────────────────────────────────── */}
      <section className="space-y-4">
        <h2 className={SECTION}>How are you</h2>
        <p className="text-xs text-slate-500">
          Answer what you want to. Leave anything blank and it stays unrecorded —
          Sara does not fill it in.
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          {SCALES.map(({ field, label, hint }) => (
            <label key={String(field)} className="space-y-1">
              <span className={LABEL}>{label}</span>
              <input
                // Explicit aria-label: the hint below is inside the same
                // <label>, so without this the accessible name would be
                // "Energy 10 = full of it" — fine to read, wrong to address.
                aria-label={label}
                className={FIELD}
                type="number"
                min={1}
                max={10}
                inputMode="numeric"
                placeholder="—"
                value={scaleValue(field)}
                onChange={(e) => onScaleChange(field)(e.target.value)}
              />
              <span className="text-[11px] text-slate-600">{hint}</span>
            </label>
          ))}
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          <label className="space-y-1">
            <span className={LABEL}>Weight</span>
            <input
              aria-label="Weight"
              className={FIELD}
              type="number"
              step="0.1"
              inputMode="decimal"
              placeholder="—"
              value={edits.body_weight ?? ''}
              onChange={(e) => {
                const raw = e.target.value
                if (raw === '') {
                  setEdits(({ body_weight, ...rest }) => rest)
                  return
                }
                const parsed = Number(raw)
                if (Number.isFinite(parsed)) set('body_weight', parsed)
              }}
            />
            <span className="text-[11px] text-slate-600">
              Pounds. Saved as a weigh-in, not just on this day's note.
            </span>
          </label>
          <label className="space-y-1">
            <span className={LABEL}>Sleep, hours</span>
            <input
              aria-label="Sleep, hours"
              className={FIELD}
              type="number"
              step="0.25"
              inputMode="decimal"
              placeholder="—"
              value={edits.sleep_hours ?? ''}
              onChange={(e) => {
                const raw = e.target.value
                if (raw === '') {
                  setEdits(({ sleep_hours, ...rest }) => rest)
                  return
                }
                const parsed = Number(raw)
                if (Number.isFinite(parsed)) set('sleep_hours', parsed)
              }}
            />
          </label>
        </div>

        <label className="space-y-1 block">
          <span className={LABEL}>Anything else about today</span>
          <input
            aria-label="Anything else about today"
            className={FIELD}
            placeholder="—"
            value={
              'notes' in edits
                ? (edits.notes ?? '')
                : (checkIn.data?.notes ?? '')
            }
            onChange={(e) => set('notes', e.target.value === '' ? null : e.target.value)}
          />
        </label>

        <div className="flex items-center gap-3">
          <button
            type="button"
            className={PRIMARY}
            disabled={!dirty || patch.isPending}
            onClick={save}
          >
            {patch.isPending ? 'Saving…' : 'Save'}
          </button>
          {dirty && (
            <button type="button" className={GHOST} onClick={() => setEdits({})}>
              Discard
            </button>
          )}
          {!dirty && patch.isSuccess && (
            <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
              <Check className="w-3.5 h-3.5" /> Saved
            </span>
          )}
          <button
            type="button"
            className={`${GHOST} ml-auto`}
            onClick={() => setEdits({})}
            title="Skip this for now; nothing is recorded"
          >
            Skip for now
          </button>
        </div>
      </section>

      {/* ── Nutrition ─────────────────────────────────────────────────── */}
      <section className="space-y-3">
        <h2 className={SECTION}>Food</h2>
        <div className="flex items-baseline gap-3">
          <div className="text-[15px] text-slate-200">
            {checkIn.data?.nutrition_status === 'complete'
              ? 'You said this day is fully logged'
              : checkIn.data?.nutrition_status === 'partial'
                ? 'Partly logged'
                : 'Nothing said about this day yet'}
          </div>
          {checkIn.data?.nutrition_completed_at && (
            <span className="text-[11px] text-slate-600">
              confirmed {new Date(checkIn.data.nutrition_completed_at).toLocaleString()}
            </span>
          )}
        </div>
        {remaining?.target != null && (
          <p className="text-xs text-slate-500">
            Target for this day: {remaining.target} kcal
            {targets.data?.provenance === 'unknown' && ' — not recorded'}
            {targets.data?.history_unknown &&
              targets.data?.provenance !== 'unknown' &&
              ' (this date predates your recorded targets)'}
          </p>
        )}
        {targets.data && targets.data.values.calories === null && (
          <p className="text-xs text-slate-600">
            No calorie target recorded for this day, so Sara will not score the
            day against one.
          </p>
        )}
        <p className="text-xs text-slate-600">
          Add meals in the Food Log. Marking the day finished is a separate,
          deliberate step — Sara never decides it from how many meals are
          there, because "fully logged" days are what her averages are built
          from.
        </p>
        <div className="flex items-center gap-2">
          {onOpenFoodLog && (
            <button type="button" className={GHOST} onClick={onOpenFoodLog}>
              <Utensils className="w-3.5 h-3.5 inline mr-1.5" />
              Open Food Log
            </button>
          )}
          {checkIn.data?.nutrition_status !== 'complete' ? (
            <button
              type="button"
              className={PRIMARY}
              disabled={patch.isPending}
              onClick={() => patch.mutate({ nutrition_status: 'complete' })}
            >
              That's everything I ate
            </button>
          ) : (
            <button
              type="button"
              className={GHOST}
              disabled={patch.isPending}
              onClick={() => patch.mutate({ nutrition_status: 'partial' })}
            >
              Actually, there's more
            </button>
          )}
        </div>
      </section>
    </div>
  )
}
