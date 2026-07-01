/**
 * SaraOverlayHost — Jarvis-style overlays summoned from chat.
 *
 * Listens for `sara:ui-command` window events (dispatched by ChatInterface
 * when the backend emits a `ui_command` SSE event for phrases like
 * "bring up my morning brief") and renders the requested surface as an
 * overlay on top of whatever view is active.
 */
import { useCallback, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { APP_CONFIG } from '../../config'

type OverlayKind = 'brief' | 'nutrition' | 'calendar' | 'tasks' | 'note'

interface UICommand {
  action: string
  overlay: OverlayKind
  payload: Record<string, any>
}

const TITLES: Record<OverlayKind, string> = {
  brief: 'Morning Brief',
  nutrition: "Today's Nutrition",
  calendar: "Today's Schedule",
  tasks: 'Background Tasks',
  note: 'Note',
}

const ICONS: Record<OverlayKind, string> = {
  brief: '☀️',
  nutrition: '🥗',
  calendar: '📅',
  tasks: '⚙️',
  note: '📝',
}

async function getJson(path: string): Promise<any> {
  const res = await fetch(`${APP_CONFIG.apiUrl}${path}`, { credentials: 'include' })
  if (!res.ok) throw new Error(`${res.status}`)
  return res.json()
}

function localDateStr(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// ── Per-surface content ────────────────────────────────────────────────────

function BriefContent() {
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    getJson('/api/morning-brief/today')
      .then((b) => setText(b.full_text || b.calendar_summary || 'No brief generated yet today.'))
      .catch(() => setError('Could not load the morning brief.'))
  }, [])
  if (error) return <p className="text-red-400">{error}</p>
  if (text === null) return <Loading />
  return (
    <div className="prose prose-invert prose-sm max-w-none">
      <ReactMarkdown>{text}</ReactMarkdown>
    </div>
  )
}

function MacroBar({ label, value, target }: { label: string; value: number; target?: number }) {
  const pct = target ? Math.min(100, Math.round((value / target) * 100)) : 0
  return (
    <div className="mb-3">
      <div className="flex justify-between text-sm text-gray-300 mb-1">
        <span>{label}</span>
        <span>
          {Math.round(value)}
          {target ? ` / ${Math.round(target)}` : ''}
        </span>
      </div>
      {target ? (
        <div className="h-2 bg-gray-700 rounded">
          <div className="h-2 bg-emerald-500 rounded" style={{ width: `${pct}%` }} />
        </div>
      ) : null}
    </div>
  )
}

function NutritionContent() {
  const [data, setData] = useState<{ totals: any; goals: any } | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const today = localDateStr()
    Promise.all([
      getJson(`/api/fitness/food-log/summary?start_date=${today}&end_date=${today}`).catch(() => null),
      getJson('/api/fitness/goals').catch(() => null),
    ])
      .then(([summary, goals]) => {
        const totals = summary?.statistics?.totals || summary?.totals || {}
        setData({ totals, goals: goals || {} })
      })
      .catch(() => setError("Could not load today's nutrition."))
  }, [])
  if (error) return <p className="text-red-400">{error}</p>
  if (!data) return <Loading />
  const { totals, goals } = data
  return (
    <div>
      <MacroBar label="Calories" value={totals.calories || 0} target={goals.calories} />
      <MacroBar label="Protein (g)" value={totals.protein || 0} target={goals.protein} />
      <MacroBar label="Carbs (g)" value={totals.carbs || 0} target={goals.carbs} />
      <MacroBar label="Fats (g)" value={totals.fats || totals.fat || 0} target={goals.fats} />
    </div>
  )
}

function CalendarContent() {
  const [events, setEvents] = useState<any[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const today = localDateStr()
    getJson(`/calendar/events?start_date=${today}T00:00:00&end_date=${today}T23:59:59`)
      .then(setEvents)
      .catch(() => setError('Could not load the calendar.'))
  }, [])
  if (error) return <p className="text-red-400">{error}</p>
  if (events === null) return <Loading />
  if (events.length === 0) return <p className="text-gray-400">Nothing scheduled today.</p>
  return (
    <ul className="space-y-2">
      {events.map((e) => (
        <li key={e.id} className="flex items-start gap-3 bg-gray-800/60 rounded-lg px-3 py-2">
          <span className="text-emerald-400 text-sm font-mono w-14 shrink-0">
            {e.all_day ? 'All day' : (e.start_time || '').slice(11, 16)}
          </span>
          <span className="text-gray-200 text-sm">
            {e.title}
            {e.location ? <span className="text-gray-400"> @ {e.location}</span> : null}
            {e.ios_calendar_name ? (
              <span className="ml-2 text-xs text-gray-500">[{e.ios_calendar_name}]</span>
            ) : null}
          </span>
        </li>
      ))}
    </ul>
  )
}

function TasksContent() {
  const [tasks, setTasks] = useState<any[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    Promise.all([
      getJson('/api/background-tasks/active').catch(() => []),
      getJson('/api/background-tasks/recent?limit=10').catch(() => []),
    ])
      .then(([active, recent]) => {
        const a = Array.isArray(active) ? active : active?.tasks || []
        const r = Array.isArray(recent) ? recent : recent?.tasks || []
        const seen = new Set<string>()
        const merged = [...a, ...r].filter((t) => {
          if (!t?.id || seen.has(t.id)) return false
          seen.add(t.id)
          return true
        })
        setTasks(merged)
      })
      .catch(() => setError('Could not load tasks.'))
  }, [])
  if (error) return <p className="text-red-400">{error}</p>
  if (tasks === null) return <Loading />
  if (tasks.length === 0) return <p className="text-gray-400">Nothing running right now.</p>
  const statusColor = (s: string) =>
    s === 'running' ? 'text-amber-400' : s === 'completed' ? 'text-emerald-400' : s === 'failed' ? 'text-red-400' : 'text-gray-400'
  return (
    <ul className="space-y-2">
      {tasks.map((t) => (
        <li key={t.id} className="bg-gray-800/60 rounded-lg px-3 py-2">
          <div className="flex justify-between gap-2">
            <span className="text-gray-200 text-sm truncate">
              {t.original_query || t.task_type || 'Task'}
            </span>
            <span className={`text-xs shrink-0 ${statusColor(t.status)}`}>{t.status}</span>
          </div>
          {t.status_label ? <div className="text-xs text-gray-500 mt-1">{t.status_label}</div> : null}
        </li>
      ))}
    </ul>
  )
}

function NoteContent({ payload }: { payload: Record<string, any> }) {
  const [noteId, setNoteId] = useState<string>(payload.note_id)
  const [note, setNote] = useState<any | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    setNote(null)
    getJson(`/notes/${noteId}`)
      .then(setNote)
      .catch(() => setError('Could not load that note.'))
  }, [noteId])
  if (error) return <p className="text-red-400">{error}</p>
  if (!note) return <Loading />
  const alternates: { id: string; title: string }[] = payload.alternates || []
  return (
    <div>
      <h3 className="text-lg font-semibold text-gray-100 mb-3">{note.title}</h3>
      <div className="prose prose-invert prose-sm max-w-none">
        <ReactMarkdown>{note.content || '*Empty note.*'}</ReactMarkdown>
      </div>
      {alternates.length > 0 && (
        <div className="mt-4 pt-3 border-t border-gray-700">
          <p className="text-xs text-gray-500 mb-1">Not the one? Also matched:</p>
          {alternates.map((a) => (
            <button
              key={a.id}
              onClick={() => setNoteId(a.id)}
              className="block text-sm text-emerald-400 hover:text-emerald-300 text-left"
            >
              {a.title}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Loading() {
  return <p className="text-gray-400 animate-pulse">Loading…</p>
}

// ── Host ───────────────────────────────────────────────────────────────────

export default function SaraOverlayHost() {
  const [command, setCommand] = useState<UICommand | null>(null)

  useEffect(() => {
    const onCommand = (e: Event) => {
      const detail = (e as CustomEvent).detail as UICommand
      if (detail?.action === 'open_overlay' && detail.overlay) {
        setCommand(detail)
      }
    }
    window.addEventListener('sara:ui-command', onCommand)
    return () => window.removeEventListener('sara:ui-command', onCommand)
  }, [])

  const close = useCallback(() => setCommand(null), [])

  useEffect(() => {
    if (!command) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [command, close])

  if (!command) return null
  const kind = command.overlay

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={close}
    >
      <div
        className="w-full max-w-2xl max-h-[80vh] mx-4 bg-gray-900 border border-gray-700 rounded-xl shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700">
          <h2 className="text-gray-100 font-semibold flex items-center gap-2">
            <span>{ICONS[kind]}</span>
            {kind === 'note' ? command.payload?.title || 'Note' : TITLES[kind]}
          </h2>
          <button
            onClick={close}
            className="text-gray-400 hover:text-gray-200 text-xl leading-none px-1"
            aria-label="Close overlay"
          >
            ×
          </button>
        </div>
        <div className="px-5 py-4 overflow-y-auto">
          {kind === 'brief' && <BriefContent />}
          {kind === 'nutrition' && <NutritionContent />}
          {kind === 'calendar' && <CalendarContent />}
          {kind === 'tasks' && <TasksContent />}
          {kind === 'note' && <NoteContent payload={command.payload || {}} />}
        </div>
      </div>
    </div>
  )
}
