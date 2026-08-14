import React from 'react'

/**
 * HeaderBand — replaces the old greeting hero (mission-control redesign §4.0).
 * One row: greeting + date on the left, weather + presence/degraded chips
 * below-left, inline weather read on the right. No card box, no display type.
 */
export default function HeaderBand({
  greeting,
  dateLine,
  weather,
  weatherEmoji,
  emotionalState,
  kernelState,
  degraded,
  onOpenDiagnostics,
}: {
  greeting: string
  dateLine: string
  weather: any
  weatherEmoji: Record<string, string>
  emotionalState: string | null
  kernelState: string | null
  degraded: { name: string }[] | null
  onOpenDiagnostics: () => void
}) {
  const cur = weather?.current || weather
  const temp = cur ? Math.round(cur.temperature ?? cur.temp ?? 0) : null
  const emoji = cur ? weatherEmoji[cur.icon || weather?.icon] || '🌡' : null
  const hi = weather?.forecast?.[0]?.temp_high
  const lo = weather?.forecast?.[0]?.temp_low
  const pop = weather?.forecast?.[0]?.pop
  const rainNote = typeof pop === 'number' && pop > 0.3 ? `${Math.round(pop * 100)}% rain` : null

  return (
    <header className="flex flex-wrap items-center justify-between gap-3 py-2">
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
        <h1 className="text-xl font-semibold leading-tight text-white">{greeting}, David</h1>
        <span className="text-sm text-slate-400">· {dateLine}</span>
        {(emotionalState || kernelState) && (
          <span className="ml-2 inline-flex items-center gap-1.5 rounded-full border border-teal-400/25 bg-teal-400/[0.06] px-2.5 py-0.5 text-[11px] text-teal-200">
            <span className="h-1.5 w-1.5 rounded-full bg-teal-400" />
            {[kernelState, emotionalState].filter(Boolean).join(' · ')}
          </span>
        )}
        {degraded && degraded.length > 0 && (
          <button
            onClick={onOpenDiagnostics}
            className="ml-1 inline-flex items-center gap-1 rounded-full border border-amber-400/30 bg-amber-400/10 px-2.5 py-0.5 text-[11px] text-amber-200 transition-colors hover:border-amber-300/50"
          >
            ⚠ degraded: {degraded.map((d) => d.name).join(', ')}
          </button>
        )}
      </div>
      {cur && (
        <div className="flex flex-shrink-0 items-baseline gap-2 text-sm">
          <span className="text-lg leading-none">{emoji}</span>
          <span className="text-lg font-semibold text-white">{temp}°</span>
          {(hi != null || lo != null) && (
            <span className="text-slate-500">
              {hi != null ? `${Math.round(hi)}°` : ''}
              {hi != null && lo != null ? '/' : ''}
              {lo != null ? `${Math.round(lo)}°` : ''}
            </span>
          )}
          {rainNote && <span className="text-slate-400">· {rainNote}</span>}
        </div>
      )}
    </header>
  )
}
