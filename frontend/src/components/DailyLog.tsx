import { useCallback, useEffect, useMemo, useState } from 'react'
import { APP_CONFIG } from '../config'

/**
 * Daily Log — Sara's per-day diary (DAILY_LOG_DIARY_PLAN_2026_08_25 Phase 5).
 *
 * The prose is generated nightly by the 2 AM dream cycle and lives in
 * `day_replay_cache.summary`; the structured events behind it live in the same
 * row's `replay_data`. This view shows the prose first and the receipts under
 * a disclosure, so every claim in the entry can be checked against the facts
 * it was written from.
 */

interface LogListEntry {
  date: string
  weekday: string
  diary: string | null
  sections_summary: Record<string, number>
  total_events: number
  data_sources: string[]
  generated_at: string | null
}

interface ReplayEvent {
  timestamp: string
  source: string
  event_type: string
  summary: string
  details: Record<string, any>
  importance: number
}

interface LogDetail {
  date: string
  weekday: string
  diary: string | null
  sections: Record<string, ReplayEvent[]>
  sections_summary: Record<string, number>
  total_events: number
  data_sources: string[]
  generated_at: string | null
}

const SOURCE_LABELS: Record<string, string> = {
  episodes: 'Conversations',
  automations: 'Automations',
  fitness_workouts: 'Workouts',
  fitness_food: 'Nutrition',
  fitness_recovery: 'Recovery',
  calendar: 'Calendar',
  email: 'Email',
  research: 'Agent tasks',
  learning: 'Learning',
  timers: 'Timers',
  reminders: 'Reminders',
  home: 'Home',
}

const SOURCE_ICONS: Record<string, string> = {
  episodes: 'chat',
  automations: 'bolt',
  fitness_workouts: 'fitness_center',
  fitness_food: 'restaurant',
  fitness_recovery: 'bedtime',
  calendar: 'calendar_today',
  email: 'mail',
  research: 'smart_toy',
  learning: 'school',
  timers: 'timer',
  reminders: 'notifications',
  home: 'home',
}

// Home activity is per-entity transition noise — dozens of rows that say
// nothing on their own. Collapsed by default so the receipts stay readable.
const NOISY_SOURCES = new Set(['home'])

const SOURCE_ORDER = [
  'episodes', 'fitness_workouts', 'fitness_food', 'fitness_recovery',
  'calendar', 'research', 'learning', 'reminders', 'timers',
  'email', 'automations', 'home',
]

async function apiFetch(path: string, options?: RequestInit) {
  const res = await fetch(`${APP_CONFIG.apiUrl}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(detail || `Request failed (${res.status})`)
  }
  return res.json()
}

function formatDate(iso: string): string {
  // Parse as a plain calendar date — `new Date('2026-08-24')` is parsed as
  // UTC midnight and renders as the 23rd in Eastern time.
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    month: 'long', day: 'numeric', year: 'numeric',
  })
}

function formatEventTime(iso: string): string {
  // Replay timestamps are naive ET wall-clock; render them verbatim.
  const time = iso.split('T')[1]
  if (!time) return ''
  const [hRaw, min] = time.split(':')
  const hour = Number(hRaw)
  const suffix = hour >= 12 ? 'PM' : 'AM'
  const h12 = hour % 12 === 0 ? 12 : hour % 12
  return `${h12}:${min} ${suffix}`
}

function ReceiptsSection({ source, events }: { source: string; events: ReplayEvent[] }) {
  const [open, setOpen] = useState(!NOISY_SOURCES.has(source))
  const label = SOURCE_LABELS[source] || source
  const icon = SOURCE_ICONS[source] || 'circle'

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/40">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left text-sm text-gray-300 hover:text-white"
      >
        <span className="material-icons text-[16px] text-teal-300/70">{icon}</span>
        <span className="font-medium">{label}</span>
        <span className="text-xs text-gray-500">{events.length}</span>
        <span className="material-icons text-[18px] ml-auto text-gray-500">
          {open ? 'expand_less' : 'expand_more'}
        </span>
      </button>
      {open && (
        <ul className="px-3 pb-3 space-y-1">
          {events.map((event, i) => (
            <li key={i} className="flex gap-3 text-xs text-gray-400">
              <span className="shrink-0 tabular-nums text-gray-600 w-[68px]">
                {formatEventTime(event.timestamp)}
              </span>
              <span className="min-w-0">{event.summary}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function DailyLog() {
  const [entries, setEntries] = useState<LogListEntry[]>([])
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const [detail, setDetail] = useState<LogDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadList = useCallback(async () => {
    setLoading(true)
    try {
      const data = await apiFetch('/api/daily-log?limit=60')
      setEntries(data.entries || [])
      setError(null)
      setSelectedDate((current) => current || data.entries?.[0]?.date || null)
    } catch (e: any) {
      setError(e.message || 'Failed to load daily log')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadList() }, [loadList])

  const loadDetail = useCallback(async (date: string) => {
    setDetailLoading(true)
    try {
      setDetail(await apiFetch(`/api/daily-log/${date}`))
      setError(null)
    } catch (e: any) {
      setDetail(null)
      setError(e.message || 'Failed to load entry')
    } finally {
      setDetailLoading(false)
    }
  }, [])

  useEffect(() => {
    if (selectedDate) void loadDetail(selectedDate)
  }, [selectedDate, loadDetail])

  const regenerate = useCallback(async () => {
    if (!selectedDate) return
    setRegenerating(true)
    try {
      await apiFetch(`/api/daily-log/${selectedDate}/regenerate`, { method: 'POST' })
      await loadDetail(selectedDate)
      await loadList()
      setError(null)
    } catch (e: any) {
      setError(e.message || 'Regenerate failed')
    } finally {
      setRegenerating(false)
    }
  }, [selectedDate, loadDetail, loadList])

  const orderedSections = useMemo(() => {
    if (!detail) return []
    const keys = Object.keys(detail.sections)
    keys.sort((a, b) => {
      const ai = SOURCE_ORDER.indexOf(a)
      const bi = SOURCE_ORDER.indexOf(b)
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
    })
    return keys.map((key) => [key, detail.sections[key]] as [string, ReplayEvent[]])
  }, [detail])

  return (
    <div className="flex h-full min-h-0">
      {/* Date rail */}
      <aside className="w-56 shrink-0 border-r border-gray-800 overflow-y-auto">
        <div className="px-4 py-3 text-xs uppercase tracking-wide text-gray-500">
          Daily Log
        </div>
        {loading && <div className="px-4 py-2 text-sm text-gray-500">Loading…</div>}
        {!loading && entries.length === 0 && (
          <div className="px-4 py-2 text-sm text-gray-500">
            No entries yet. The first one is written tonight.
          </div>
        )}
        <ul>
          {entries.map((entry) => (
            <li key={entry.date}>
              <button
                onClick={() => setSelectedDate(entry.date)}
                className={[
                  'w-full text-left px-4 py-2 border-l-2 transition-colors',
                  selectedDate === entry.date
                    ? 'border-teal-400 bg-gray-800/60 text-white'
                    : 'border-transparent text-gray-400 hover:text-gray-200 hover:bg-gray-800/30',
                ].join(' ')}
              >
                <div className="text-sm">{formatDate(entry.date)}</div>
                <div className="flex items-center gap-2 text-[11px] text-gray-500">
                  <span>{entry.weekday}</span>
                  {!entry.diary && (
                    <span className="text-amber-500/80">no entry</span>
                  )}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      {/* Entry */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        {error && (
          <div className="m-4 rounded-md border border-red-900/60 bg-red-950/40 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        {!selectedDate && !loading && (
          <div className="p-8 text-gray-500">Pick a day.</div>
        )}

        {detailLoading && <div className="p-8 text-gray-500">Loading entry…</div>}

        {detail && !detailLoading && (
          <article className="max-w-3xl mx-auto px-6 py-6">
            <header className="flex items-start justify-between gap-4 mb-5">
              <div>
                <h1 className="text-xl text-white">{formatDate(detail.date)}</h1>
                <p className="text-xs text-gray-500 mt-0.5">
                  {detail.weekday} · {detail.total_events} recorded events
                  {detail.generated_at && ` · written ${new Date(detail.generated_at + 'Z').toLocaleString()}`}
                </p>
              </div>
              <button
                onClick={regenerate}
                disabled={regenerating}
                className="shrink-0 flex items-center gap-1.5 rounded-md border border-gray-700 px-3 py-1.5 text-xs text-gray-300 hover:text-white hover:border-gray-600 disabled:opacity-50"
              >
                <span className="material-icons text-[15px]">
                  {regenerating ? 'hourglass_top' : 'refresh'}
                </span>
                {regenerating ? 'Writing…' : 'Regenerate'}
              </button>
            </header>

            {detail.diary ? (
              <div className="space-y-4 text-[15px] leading-relaxed text-gray-200">
                {detail.diary.split(/\n\s*\n/).map((para, i) => (
                  <p key={i}>{para.trim()}</p>
                ))}
              </div>
            ) : (
              <div className="rounded-md border border-gray-800 bg-gray-900/40 px-4 py-3 text-sm text-gray-400">
                No entry was written for this day — the facts below were still
                recorded. Regenerate to write one.
              </div>
            )}

            {orderedSections.length > 0 && (
              <section className="mt-8">
                <h2 className="text-xs uppercase tracking-wide text-gray-500 mb-3">
                  What happened
                </h2>
                <div className="space-y-2">
                  {orderedSections.map(([source, events]) => (
                    <ReceiptsSection key={source} source={source} events={events} />
                  ))}
                </div>
              </section>
            )}
          </article>
        )}
      </div>
    </div>
  )
}
