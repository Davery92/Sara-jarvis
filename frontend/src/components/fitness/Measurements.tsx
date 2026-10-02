/**
 * Fitness → Progress → Measurements.
 *
 * FITNESS_COACH_IMPLEMENTATION_PLAN Step 11.
 *
 * Grouped by period, because three readings taken in one sitting are one
 * sitting — showing them as three unrelated points invites reading noise
 * between them as change.
 *
 * The chart is deliberately honest about gaps: a sparse series is drawn with
 * its real x-axis spacing and the point count stated, never as evenly spaced
 * points with an interpolated line implying readings that were never taken.
 * `connectNulls` is off for the same reason.
 *
 * A change figure is only shown when the backend says the readings are
 * comparable — same type, site, side, protocol and unit. A waist measured at
 * the navel and one at the narrowest point differ by centimetres, and that
 * difference is not a change in the athlete.
 */
import React, { useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AlertTriangle, Plus } from 'lucide-react'

import {
  useAthleteToday,
  useCreateMeasurementPeriod,
  useCreateMeasurementType,
  useLogMeasurement,
  useMeasurementPeriods,
  useMeasurementTypes,
  useMeasurements,
} from '../../hooks/useFitnessCoach'
import type { Measurement, MeasurementType, Side } from '../../types/fitnessCoach'

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

function ErrorNote({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 text-xs text-amber-300/90 border-l-2 border-amber-400/70 pl-3 py-1">
      <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
      <span>{message}</span>
    </div>
  )
}

function sideLabel(side: Side): string {
  return side === 'none' ? '' : side
}

export default function Measurements() {
  const todayQuery = useAthleteToday()
  const athleteToday = todayQuery.data?.athlete_local_date ?? ''

  const typesQuery = useMeasurementTypes()
  const periodsQuery = useMeasurementPeriods()
  const logMeasurement = useLogMeasurement()
  const createPeriod = useCreateMeasurementPeriod()
  const createType = useCreateMeasurementType()

  const [entryOpen, setEntryOpen] = useState(false)
  const [typeOpen, setTypeOpen] = useState(false)

  const types = typesQuery.data ?? []
  const periods = periodsQuery.data ?? []

  // The selection is *derived* until the athlete picks something, rather than
  // seeded by an effect. Seeding from an effect means the first render asks
  // for one key and the second asks for another, so the series briefly goes
  // empty after it had already loaded — which reads on screen as "no
  // readings" for a type that has them.
  //
  // Not defaulted to a hardcoded code either: an athlete whose catalog does
  // not include it would get an empty selector and no side control.
  const [chosenType, setChosenType] = useState<string | null>(null)
  const [chosenSide, setChosenSide] = useState<Side | null>(null)

  const defaultType = useMemo(
    () =>
      types.find((t) => t.code === 'waist_circumference') ?? types[0] ?? null,
    [types],
  )
  const chartType = chosenType ?? defaultType?.code ?? null
  const selectedType = types.find((t) => t.code === chartType)
  const chartSide: Side =
    chosenSide ?? (selectedType?.allows_side ? 'left' : 'none')

  const readings = useMeasurements(chartType ?? undefined)

  const series = useMemo(() => {
    // Only the selected side, so left and right never share a line — they
    // are different series and a shared line would show a 0.5cm zig-zag that
    // is just the athlete's asymmetry.
    const filtered = (readings.data ?? [])
      .filter((r) => r.side === chartSide)
      .slice()
      .sort((a, b) => a.logical_date.localeCompare(b.logical_date))
    return filtered.map((r) => ({
      date: r.logical_date,
      // Real day offsets, so a six-week gap looks like a six-week gap rather
      // than like the next reading.
      t: Date.parse(`${r.logical_date}T00:00:00Z`),
      value: r.value,
      unit: r.unit,
      protocol: r.protocol,
    }))
  }, [readings.data, chartSide])

  // Distinct protocols in the plotted window. If there is more than one, the
  // series is not internally comparable and saying so matters more than
  // drawing a smooth line through it.
  const protocols = useMemo(
    () => Array.from(new Set(series.map((p) => p.protocol ?? ''))).filter(Boolean),
    [series],
  )

  return (
    <div className="p-6 space-y-8 max-w-[740px]">
      <div className="flex items-baseline justify-between">
        <h2 className={SECTION}>Measurements</h2>
        <div className="flex gap-1">
          <button type="button" className={GHOST} onClick={() => setTypeOpen((v) => !v)}>
            {typeOpen ? 'Cancel' : 'New type'}
          </button>
          <button type="button" className={GHOST} onClick={() => setEntryOpen((v) => !v)}>
            {entryOpen ? 'Cancel' : 'Add readings'}
          </button>
        </div>
      </div>

      {typesQuery.isError && <ErrorNote message={typesQuery.error.message} />}
      {logMeasurement.isError && <ErrorNote message={logMeasurement.error.message} />}
      {createType.isError && <ErrorNote message={createType.error.message} />}
      {createPeriod.isError && <ErrorNote message={createPeriod.error.message} />}

      {typeOpen && (
        <NewTypeForm
          onDone={() => setTypeOpen(false)}
          createType={createType}
        />
      )}

      {entryOpen && (
        <PeriodEntryForm
          types={types}
          athleteToday={athleteToday}
          onDone={() => setEntryOpen(false)}
          createPeriod={createPeriod}
          logMeasurement={logMeasurement}
        />
      )}

      {/* ── Chart ─────────────────────────────────────────────────────── */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-1">
            <span className={LABEL}>Show</span>
            <select
              aria-label="Show"
              className={FIELD}
              value={chartType ?? ''}
              onChange={(e) => {
                setChosenType(e.target.value)
                // Reset the side so switching to a sided type does not keep
                // "none" and silently show nothing.
                setChosenSide(null)
              }}
            >
              {types.map((t) => (
                <option key={t.id} value={t.code}>{t.label}</option>
              ))}
            </select>
          </label>
          {selectedType?.allows_side && (
            <label className="space-y-1">
              <span className={LABEL}>Side</span>
              <select
                aria-label="Side"
                className={FIELD}
                value={chartSide}
                onChange={(e) => setChosenSide(e.target.value as Side)}
              >
                <option value="left">Left</option>
                <option value="right">Right</option>
              </select>
            </label>
          )}
        </div>

        {selectedType?.protocol_guidance && (
          <p className="text-xs text-slate-600">{selectedType.protocol_guidance}</p>
        )}

        {series.length === 0 ? (
          <p className="text-sm text-slate-500">
            No readings yet{selectedType ? ` for ${selectedType.label}` : ''}.
          </p>
        ) : series.length === 1 ? (
          <div className="space-y-1">
            <p className="text-[15px] text-slate-200">
              {series[0].value} {series[0].unit}
              <span className="text-xs text-slate-500 ml-2">{series[0].date}</span>
            </p>
            <p className="text-xs text-slate-600">
              One reading. Nothing to compare it against yet, so Sara will not
              describe a direction.
            </p>
          </div>
        ) : (
          <>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={series}>
                  <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
                  <XAxis
                    dataKey="t"
                    type="number"
                    scale="time"
                    domain={['dataMin', 'dataMax']}
                    tickFormatter={(t) => new Date(t).toISOString().slice(5, 10)}
                    tick={{ fill: '#64748b', fontSize: 11 }}
                    stroke="rgba(255,255,255,0.08)"
                  />
                  <YAxis
                    domain={['auto', 'auto']}
                    tick={{ fill: '#64748b', fontSize: 11 }}
                    stroke="rgba(255,255,255,0.08)"
                    width={38}
                  />
                  <Tooltip
                    contentStyle={{
                      background: '#08111f',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                    labelFormatter={(t) => new Date(Number(t)).toISOString().slice(0, 10)}
                  />
                  <Line
                    type="linear"
                    dataKey="value"
                    stroke="#5eead4"
                    strokeWidth={2}
                    dot={{ r: 3, fill: '#5eead4' }}
                    // Off deliberately: bridging a gap would draw a line
                    // through weeks with no reading, implying measurements
                    // that were never taken.
                    connectNulls={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="text-xs text-slate-600">
              {series.length} readings between {series[0].date} and{' '}
              {series[series.length - 1].date}
              {sideLabel(chartSide) && ` · ${sideLabel(chartSide)}`}
            </p>
            {protocols.length > 1 && (
              <ErrorNote
                message={
                  `These readings were taken ${protocols.length} different ways ` +
                  `(${protocols.join('; ')}). The differences between them are ` +
                  `not changes in you, so Sara will not report a trend across them.`
                }
              />
            )}
          </>
        )}
      </section>

      {/* ── By period ─────────────────────────────────────────────────── */}
      <section className="space-y-3">
        <h2 className={SECTION}>Sessions</h2>
        {periods.length === 0 && (
          <p className="text-sm text-slate-500">No measurement sessions yet.</p>
        )}
        {periods.map((period) => (
          <PeriodRow key={period.id} periodId={period.id}
                     measuredOn={period.measured_on}
                     protocol={period.protocol} />
        ))}
      </section>
    </div>
  )
}

function PeriodRow({
  periodId,
  measuredOn,
  protocol,
}: {
  periodId: string
  measuredOn: string
  protocol: string | null
}) {
  const all = useMeasurements()
  const mine = (all.data ?? []).filter((m) => m.period_id === periodId)
  return (
    <div className="py-2 px-2 -mx-2 rounded-lg hover:bg-white/[0.04] space-y-1">
      <div className="flex items-baseline gap-3">
        <span className="text-[15px] text-slate-200">{measuredOn}</span>
        <span className="text-xs text-slate-500">
          {mine.length} {mine.length === 1 ? 'reading' : 'readings'}
        </span>
      </div>
      {protocol && <div className="text-[11px] text-slate-600">{protocol}</div>}
      {mine.length > 0 && (
        <div className="text-xs text-slate-400">
          {mine
            .map((m) => `${m.label}${m.side !== 'none' ? ` (${m.side})` : ''} ${m.value}${m.unit}`)
            .join(' · ')}
        </div>
      )}
    </div>
  )
}

function NewTypeForm({
  onDone,
  createType,
}: {
  onDone: () => void
  createType: ReturnType<typeof useCreateMeasurementType>
}) {
  const [label, setLabel] = useState('')
  const [allowsSide, setAllowsSide] = useState(false)
  const [protocol, setProtocol] = useState('')

  return (
    <div className="space-y-3 border-l-2 border-teal-400/40 pl-4">
      <p className="text-xs text-slate-500">
        Anything you want to track with a tape. Write down how you measure it —
        that is what lets Sara compare two readings instead of treating a
        different method as a change.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="space-y-1">
          <span className={LABEL}>What is it called</span>
          <input
            className={FIELD}
            value={label}
            placeholder="Forearm (standing)"
            onChange={(e) => setLabel(e.target.value)}
          />
        </label>
        <label className="space-y-1 flex flex-col justify-end">
          <span className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={allowsSide}
              onChange={(e) => setAllowsSide(e.target.checked)}
            />
            Measured left and right separately
          </span>
        </label>
        <label className="space-y-1 sm:col-span-2">
          <span className={LABEL}>How you measure it</span>
          <input
            aria-label="How you measure it"
            className={FIELD}
            value={protocol}
            placeholder="Standing, arm hanging relaxed, tape at the widest point"
            onChange={(e) => setProtocol(e.target.value)}
          />
        </label>
      </div>
      <button
        type="button"
        className={PRIMARY}
        disabled={!label.trim() || createType.isPending}
        onClick={() =>
          createType.mutate(
            {
              code: label,
              label: label.trim(),
              quantity: 'length',
              canonical_unit: 'cm',
              allows_side: allowsSide,
              protocol_guidance: protocol.trim() || null,
            },
            { onSuccess: onDone },
          )
        }
      >
        {createType.isPending ? 'Saving…' : 'Add it'}
      </button>
    </div>
  )
}

function PeriodEntryForm({
  types,
  athleteToday,
  onDone,
  createPeriod,
  logMeasurement,
}: {
  types: MeasurementType[]
  athleteToday: string
  onDone: () => void
  createPeriod: ReturnType<typeof useCreateMeasurementPeriod>
  logMeasurement: ReturnType<typeof useLogMeasurement>
}) {
  const [measuredOn, setMeasuredOn] = useState(athleteToday)
  const [protocol, setProtocol] = useState('')
  // One entry row per type/side combination the athlete chooses to fill in.
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [failed, setFailed] = useState<string[]>([])

  React.useEffect(() => {
    if (athleteToday && !measuredOn) setMeasuredOn(athleteToday)
  }, [athleteToday, measuredOn])

  const rows = useMemo(() => {
    const out: Array<{ key: string; type: MeasurementType; side: Side }> = []
    for (const type of types) {
      if (type.allows_side) {
        out.push({ key: `${type.code}:left`, type, side: 'left' })
        out.push({ key: `${type.code}:right`, type, side: 'right' })
      } else {
        out.push({ key: `${type.code}:none`, type, side: 'none' })
      }
    }
    return out
  }, [types])

  const filled = rows.filter((r) => (values[r.key] ?? '').trim() !== '')

  const submit = async () => {
    if (!measuredOn || filled.length === 0) return
    setSaving(true)
    setFailed([])
    try {
      const period = await createPeriod.mutateAsync({
        measured_on: measuredOn,
        protocol: protocol.trim() || null,
      })
      const problems: string[] = []
      for (const row of filled) {
        const parsed = Number(values[row.key])
        if (!Number.isFinite(parsed) || parsed <= 0) {
          problems.push(`${row.type.label}: not a measurement`)
          continue
        }
        try {
          await logMeasurement.mutateAsync({
            type_code: row.type.code,
            value: parsed,
            unit: row.type.canonical_unit,
            measured_at: `${measuredOn}T07:00:00Z`,
            side: row.side,
            period_id: period.id,
          })
        } catch (error) {
          // One bad reading must not discard the others the athlete typed.
          problems.push(
            `${row.type.label}: ${
              error instanceof Error ? error.message : 'not saved'
            }`,
          )
        }
      }
      setFailed(problems)
      if (problems.length === 0) {
        setValues({})
        onDone()
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3 border-l-2 border-teal-400/40 pl-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="space-y-1">
          <span className={LABEL}>Measured on</span>
          <input
            className={FIELD}
            type="date"
            value={measuredOn}
            onChange={(e) => setMeasuredOn(e.target.value)}
          />
        </label>
        <label className="space-y-1">
          <span className={LABEL}>How you measured, this time</span>
          <input
            aria-label="How you measured, this time"
            className={FIELD}
            value={protocol}
            placeholder="Morning, fasted, before water"
            onChange={(e) => setProtocol(e.target.value)}
          />
          <span className="text-[11px] text-slate-600">
            Readings taken different ways are not compared against each other.
          </span>
        </label>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {rows.map(({ key, type, side }) => (
          <label key={key} className="space-y-1">
            <span className={LABEL}>
              {type.label}
              {side !== 'none' && ` (${side})`}
            </span>
            <input
              // Explicit: the unit hint below sits inside the same <label>,
              // so the accessible name would otherwise be "Waist cm".
              aria-label={`${type.label}${side !== 'none' ? ` (${side})` : ''}`}
              className={FIELD}
              type="number"
              step="0.1"
              inputMode="decimal"
              placeholder="—"
              value={values[key] ?? ''}
              onChange={(e) =>
                setValues((prev) => ({ ...prev, [key]: e.target.value }))
              }
            />
            <span className="text-[11px] text-slate-600">{type.canonical_unit}</span>
          </label>
        ))}
      </div>

      {failed.length > 0 && (
        <div className="space-y-1">
          {failed.map((message) => (
            <ErrorNote key={message} message={message} />
          ))}
          <p className="text-[11px] text-slate-600">
            The readings that did save are kept. Your remaining entries are
            still here.
          </p>
        </div>
      )}

      <button
        type="button"
        className={PRIMARY}
        disabled={saving || filled.length === 0 || !measuredOn}
        onClick={submit}
      >
        {saving
          ? 'Saving…'
          : `Save ${filled.length || ''} ${filled.length === 1 ? 'reading' : 'readings'}`.trim()}
      </button>
    </div>
  )
}
