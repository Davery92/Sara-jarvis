import React from 'react'

function Meter({ label, value, goal, unit = '' }: { label: string; value: number; goal: number | null; unit?: string }) {
  const pct = goal ? Math.min(100, Math.round((value / goal) * 100)) : 0
  const overGoal = goal != null && value > goal
  const fillClass = overGoal ? 'bg-amber-400' : 'bg-teal-400'
  const trackClass = overGoal ? 'bg-amber-400/15' : 'bg-teal-400/15'
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-slate-500">{label}</span>
        <span className="tabular-nums text-slate-200">
          {value.toLocaleString()}
          {unit}
          {goal != null && ` / ${goal.toLocaleString()}${unit}`}
        </span>
      </div>
      {/* No daily target is wired for this metric yet — a 0%-filled bar
          would read as "behind goal" rather than "no goal set", so the
          track renders without a fill instead of faking progress. */}
      {goal != null && (
        <div className={`h-2 w-full overflow-hidden rounded-full ${trackClass}`}>
          <div className={`h-full rounded-full ${fillClass}`} style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  )
}

function WeightSparkline({ points }: { points: { date: string; value: number }[] }) {
  if (points.length < 3) {
    const latest = points[points.length - 1]
    return latest ? <span className="text-sm tabular-nums text-slate-300">{latest.value.toFixed(1)}</span> : null
  }

  const width = 200
  const height = 36
  const padY = 6
  const values = points.map((p) => p.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1

  const coords = points.map((p, i) => {
    const x = (i / (points.length - 1)) * (width - 40)
    const y = padY + (1 - (p.value - min) / range) * (height - padY * 2)
    return { x, y }
  })
  const path = coords.map((c, i) => `${i === 0 ? 'M' : 'L'} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(' ')
  const last = coords[coords.length - 1]
  const lastValue = points[points.length - 1].value

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      <path d={path} fill="none" stroke="rgb(100 116 139)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={last.x} cy={last.y} r={5} fill="rgb(45 212 191)" stroke="#0c1626" strokeWidth={2} />
      <text x={last.x + 9} y={last.y + 4} fontSize={12} fill="rgb(226 232 240)" className="tabular-nums">
        {lastValue.toFixed(1)}
      </text>
    </svg>
  )
}

/**
 * Card E — Body & training (mission-control redesign §4.6). Calorie/protein
 * meters, training line, last meal, weight sparkline. The only chart on the
 * page — nothing else here should grow a gauge, ring, or pie.
 */
export default function BodyCard({
  fitness,
  todayTemplate,
  activeWorkout,
  weightTrend,
  onNavigate,
}: {
  fitness: { calories_today?: number; protein_today?: number; goal?: number | null; last_meal_ago_hours?: number | null } | null
  todayTemplate: any
  activeWorkout: any
  weightTrend: any[]
  onNavigate: (view: any) => void
}) {
  const calories = fitness?.calories_today ?? 0
  const protein = fitness?.protein_today ?? 0
  const goal = fitness?.goal ?? null
  const lastMealHours = fitness?.last_meal_ago_hours

  const sparkPoints = weightTrend
    .slice(-12)
    .map((w) => ({ date: w.date, value: Number(w.trend_weight ?? w.raw_weight) }))
    .filter((p) => Number.isFinite(p.value))

  const exerciseCount = Array.isArray(todayTemplate?.exercises) ? todayTemplate.exercises.length : null

  return (
    <div className="space-y-4 rounded-xl border border-white/8 bg-white/[0.02] p-4">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Body & training</h2>

      <Meter label="Calories" value={calories} goal={goal} />
      <Meter label="Protein" value={protein} goal={null} unit="g" />

      <button
        onClick={() => onNavigate('fitness')}
        className="flex w-full items-center justify-between rounded-lg px-0 py-1 text-left transition-colors hover:text-teal-200"
      >
        {activeWorkout ? (
          <span className="text-sm font-medium text-teal-300">
            {activeWorkout.workout_snapshot?.template_name || 'Workout'} in progress →
          </span>
        ) : todayTemplate ? (
          <span className="text-sm text-slate-300">
            {todayTemplate.name}
            {exerciseCount != null ? ` · ${exerciseCount} exercises` : ''}
          </span>
        ) : (
          <span className="text-sm text-slate-500">Rest day</span>
        )}
      </button>

      {lastMealHours != null && (
        <p className="text-xs text-slate-500">Last ate {Math.round(lastMealHours)}h ago</p>
      )}

      {sparkPoints.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] text-slate-500">Weight</div>
          <WeightSparkline points={sparkPoints} />
        </div>
      )}
    </div>
  )
}
