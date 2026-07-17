import { useQuery } from '@tanstack/react-query'
import { apiClient, RhythmRow } from '../api/client'

const LABELS: Record<string, string> = {
  wake: 'Wake',
  leave_home: 'Leave home',
  work_start: 'Work starts',
  gym_window: 'Gym',
  lunch: 'Lunch',
  work_end: 'Work ends',
  return_home: 'Home',
  dinner: 'Dinner',
  winddown: 'Winddown',
  bedtime: 'Bedtime',
}

const CORE_ORDER = [
  'wake', 'leave_home', 'work_start', 'gym_window', 'lunch',
  'work_end', 'return_home', 'dinner', 'winddown', 'bedtime',
]

function ConfidenceBar({ confidence }: { confidence: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, confidence)) * 100)
  const color = pct >= 60 ? 'bg-teal-400' : pct >= 35 ? 'bg-amber-400' : 'bg-slate-500'
  return (
    <div className="h-1 w-full rounded-full bg-white/[0.06] overflow-hidden">
      <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

function RhythmRowItem({ label, row }: { label: string; row: RhythmRow | undefined }) {
  if (!row || !row.median_time) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-lg px-3 py-2 opacity-40">
        <span className="text-[15px] text-slate-400">{label}</span>
        <span className="text-xs text-slate-600">not enough data yet</span>
      </div>
    )
  }
  return (
    <div className="rounded-lg hover:bg-white/[0.04] transition-colors px-3 py-2">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[15px] text-slate-200">{label}</span>
        <span className="text-sm text-slate-300 tabular-nums">
          ~{row.median_time}
          {row.window_start && row.window_end && (
            <span className="text-xs text-slate-500"> ({row.window_start}–{row.window_end})</span>
          )}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <ConfidenceBar confidence={row.confidence} />
        <span className="text-[10px] text-slate-600 shrink-0">{row.sample_count} samples</span>
      </div>
    </div>
  )
}

export default function RhythmSection() {
  const { data, isLoading } = useQuery({
    queryKey: ['daily-rhythm'],
    queryFn: () => apiClient.getRhythm(),
  })

  if (isLoading) return null
  if (!data || (data.core.length === 0 && data.places.length === 0)) return null

  const weekday = new Map(data.core.filter((r) => r.day_scope === 'weekday').map((r) => [r.rhythm_key, r]))

  return (
    <div>
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
          Your rhythm
        </h2>
        {data.summary && <span className="text-xs text-slate-500 truncate">{data.summary}</span>}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4">
        {CORE_ORDER.map((key) => (
          <RhythmRowItem key={key} label={LABELS[key] || key} row={weekday.get(key)} />
        ))}
      </div>

      {data.places.length > 0 && (
        <div className="mt-6">
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 mb-1.5">
            Places
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4">
            {data.places
              .filter((r) => r.day_scope === 'weekday' && r.median_time)
              .map((r) => (
                <RhythmRowItem key={`${r.rhythm_key}-${r.day_scope}`} label={r.place_name || 'Place'} row={r} />
              ))}
          </div>
        </div>
      )}
    </div>
  )
}
