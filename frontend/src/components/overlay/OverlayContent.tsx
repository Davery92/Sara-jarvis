/**
 * Overlay content components — shared between the in-context modal
 * (SaraOverlayHost, summoned over the main app) and the standalone
 * /overlay/:kind route (rendered chrome-less in an Electron BrowserWindow).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { APP_CONFIG } from '../../config'

export type OverlayKind =
  | 'brief'
  | 'nutrition'
  | 'calendar'
  | 'tasks'
  | 'note'
  | 'blank-note'
  | 'report'
  | 'timers'
  | 'inbox'
  | 'recipes'
  | 'patterns'

export const OVERLAY_TITLES: Record<OverlayKind, string> = {
  brief: 'Morning Brief',
  nutrition: "Today's Nutrition",
  calendar: "Today's Schedule",
  tasks: 'Background Tasks',
  note: 'Note',
  'blank-note': 'New Note',
  report: 'Report',
  timers: 'Timers',
  inbox: 'Inbox',
  recipes: 'Recipes',
  patterns: "Sara's Model of You",
}

export const OVERLAY_ICONS: Record<OverlayKind, string> = {
  brief: '☀️',
  nutrition: '🥗',
  calendar: '📅',
  tasks: '⚙️',
  note: '📝',
  'blank-note': '📝',
  report: '📊',
  timers: '⏱️',
  inbox: '📥',
  recipes: '🍳',
  patterns: '🧠',
}

export async function getJson(path: string): Promise<any> {
  const res = await fetch(`${APP_CONFIG.apiUrl}${path}`, { credentials: 'include' })
  if (!res.ok) throw new Error(`${res.status}`)
  return res.json()
}

export async function postJson(path: string, body: any): Promise<any> {
  const res = await fetch(`${APP_CONFIG.apiUrl}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status}`)
  return res.json()
}

async function putJson(path: string, body: any): Promise<any> {
  const res = await fetch(`${APP_CONFIG.apiUrl}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status}`)
  return res.json()
}

function localDateStr(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function Loading() {
  return <p className="text-gray-400 animate-pulse">Loading…</p>
}

// ── Existing surfaces ────────────────────────────────────────────────────

export function BriefContent() {
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

export function NutritionContent() {
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

export function CalendarContent() {
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

export function TasksContent() {
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

// ── Note editor (full editor, not read-only — A2) ───────────────────────

function useDebouncedSave(save: (title: string, content: string) => Promise<void>, delayMs = 1200) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  return useCallback(
    (title: string, content: string) => {
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => {
        save(title, content)
      }, delayMs)
    },
    [save]
  )
}

export function NoteEditorContent({ payload }: { payload: Record<string, any> }) {
  const [noteId, setNoteId] = useState<string | undefined>(payload.note_id)
  const [title, setTitle] = useState<string>(payload.title || '')
  const [content, setContent] = useState<string>(payload.content || '')
  const [loading, setLoading] = useState<boolean>(!!payload.note_id && !payload.content)
  const [error, setError] = useState<string | null>(null)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved'>('idle')
  const alternates: { id: string; title: string }[] = payload.alternates || []

  useEffect(() => {
    if (!noteId || payload.content) return
    setLoading(true)
    getJson(`/notes/${noteId}`)
      .then((n: any) => {
        setTitle(n.title || '')
        setContent(n.content || '')
        setLoading(false)
      })
      .catch(() => {
        setError('Could not load that note.')
        setLoading(false)
      })
  }, [noteId]) // eslint-disable-line react-hooks/exhaustive-deps

  const persist = useCallback(
    async (t: string, c: string) => {
      setSaveState('saving')
      try {
        if (noteId && !noteId.startsWith('quick-')) {
          await putJson(`/notes/${noteId}`, { title: t, content: c })
        } else {
          const created = await postJson('/notes', { title: t || 'Untitled', content: c })
          setNoteId(created.id)
        }
        setSaveState('saved')
      } catch {
        setSaveState('idle')
      }
    },
    [noteId]
  )
  const debouncedSave = useDebouncedSave(persist)

  if (error) return <p className="text-red-400">{error}</p>
  if (loading) return <Loading />

  return (
    <div className="flex flex-col h-full">
      <input
        className="bg-transparent text-lg font-semibold text-gray-100 mb-2 outline-none border-b border-gray-800 pb-2"
        value={title}
        placeholder="Untitled"
        onChange={(e) => {
          setTitle(e.target.value)
          debouncedSave(e.target.value, content)
        }}
      />
      <textarea
        className="flex-1 min-h-[240px] bg-transparent text-gray-200 text-sm outline-none resize-none leading-relaxed"
        value={content}
        placeholder="Start writing… ([[Note Title]] links auto-connect on save)"
        onChange={(e) => {
          setContent(e.target.value)
          debouncedSave(title, e.target.value)
        }}
      />
      <div className="mt-2 text-xs text-gray-500 h-4">
        {saveState === 'saving' ? 'Saving…' : saveState === 'saved' ? 'Saved' : ''}
      </div>
      {alternates.length > 0 && (
        <div className="mt-2 pt-3 border-t border-gray-700">
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

// ── report (research brief / intelligence / health / finished task) ────

export function ReportContent({ payload }: { payload: Record<string, any> }) {
  const [report, setReport] = useState<any | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const type = payload.report_type
    const qs = type ? `?type=${encodeURIComponent(type)}` : ''
    getJson(`/api/overlay/report/latest${qs}`)
      .then(setReport)
      .catch(() => setError('No reports found.'))
  }, [payload.report_type])
  if (error) return <p className="text-red-400">{error}</p>
  if (!report) return <Loading />
  if (report.report_type === 'task' && report.note_id) {
    return <NoteEditorContent payload={{ note_id: report.note_id }} />
  }
  return (
    <div>
      <h3 className="text-lg font-semibold text-gray-100 mb-1">{report.title}</h3>
      {report.generated_at && (
        <p className="text-xs text-gray-500 mb-3">{new Date(report.generated_at).toLocaleString()}</p>
      )}
      <div className="prose prose-invert prose-sm max-w-none">
        <ReactMarkdown>{report.content_markdown || '*No content.*'}</ReactMarkdown>
      </div>
    </div>
  )
}

// ── timers ───────────────────────────────────────────────────────────────

export function TimersContent() {
  const [timers, setTimers] = useState<any[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    getJson('/timers')
      .then(setTimers)
      .catch(() => setError('Could not load timers.'))
  }, [])
  if (error) return <p className="text-red-400">{error}</p>
  if (timers === null) return <Loading />
  const active = timers.filter((t) => t.is_active && !t.is_completed)
  if (active.length === 0) return <p className="text-gray-400">No active timers.</p>
  return (
    <ul className="space-y-2">
      {active.map((t) => (
        <li key={t.id} className="flex items-center justify-between bg-gray-800/60 rounded-lg px-3 py-2">
          <span className="text-gray-200 text-sm">{t.title}</span>
          <span className="text-emerald-400 text-sm font-mono">
            {new Date(t.end_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
        </li>
      ))}
    </ul>
  )
}

// ── inbox (assistant inbox triage) ──────────────────────────────────────

export function InboxContent() {
  const [data, setData] = useState<{ needs_you: any[]; fyi: any[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    getJson('/api/assistant-inbox/unified')
      .then(setData)
      .catch(() => setError('Could not load your inbox.'))
  }, [])
  if (error) return <p className="text-red-400">{error}</p>
  if (!data) return <Loading />
  const { needs_you, fyi } = data
  if (needs_you.length === 0 && fyi.length === 0) {
    return <p className="text-gray-400">Nothing new — you're caught up.</p>
  }
  return (
    <div className="space-y-4">
      {needs_you.length > 0 && (
        <div>
          <p className="text-xs uppercase tracking-wide text-amber-400 mb-2">Needs you</p>
          <ul className="space-y-2">
            {needs_you.map((item) => (
              <li key={item.id} className="bg-gray-800/60 rounded-lg px-3 py-2">
                <div className="text-gray-200 text-sm">{item.title}</div>
                {item.body && <div className="text-gray-400 text-xs mt-1">{item.body}</div>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {fyi.length > 0 && (
        <div>
          <p className="text-xs uppercase tracking-wide text-gray-500 mb-2">FYI</p>
          <ul className="space-y-2">
            {fyi.map((item) => (
              <li key={item.id} className="bg-gray-800/40 rounded-lg px-3 py-2">
                <div className="text-gray-300 text-sm">{item.title}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ── recipes ──────────────────────────────────────────────────────────────

export function RecipesContent() {
  const [recipes, setRecipes] = useState<any[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    getJson('/api/fitness/recipes')
      .then(setRecipes)
      .catch(() => setError('Could not load recipes.'))
  }, [])
  if (error) return <p className="text-red-400">{error}</p>
  if (recipes === null) return <Loading />
  if (recipes.length === 0) return <p className="text-gray-400">No recipes saved yet.</p>
  return (
    <ul className="space-y-2">
      {recipes.map((r) => (
        <li key={r.id} className="bg-gray-800/60 rounded-lg px-3 py-2">
          <div className="flex justify-between gap-2">
            <span className="text-gray-200 text-sm">{r.name}</span>
            {r.calories ? <span className="text-xs text-gray-500 shrink-0">{Math.round(r.calories)} cal</span> : null}
          </div>
          {r.description && <div className="text-gray-400 text-xs mt-1 line-clamp-2">{r.description}</div>}
        </li>
      ))}
    </ul>
  )
}

// "Sara's model of you" — C4 visibility + correction panel. Shared between
// the Settings > Intelligence section and overlay kind `patterns`.
export function PatternsContent() {
  const [data, setData] = useState<any | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = useCallback(() => {
    getJson('/api/model-of-you')
      .then(setData)
      .catch(() => setError('Could not load your model.'))
  }, [])

  useEffect(() => { load() }, [load])

  const submitFeedback = useCallback(async (patternId: string, action: 'confirm' | 'wrong' | 'stop') => {
    setBusyId(patternId)
    try {
      await postJson(`/api/model-of-you/patterns/${patternId}/feedback`, { action })
      await load()
    } catch {
      setError('Could not record feedback.')
    } finally {
      setBusyId(null)
    }
  }, [load])

  if (error) return <p className="text-red-400">{error}</p>
  if (data === null) return <Loading />

  return (
    <div className="space-y-5">
      <div>
        <div className="text-sm font-semibold text-gray-300 mb-2">Learned patterns</div>
        {data.patterns.length === 0 && <p className="text-gray-500 text-sm">Nothing learned yet.</p>}
        <ul className="space-y-2">
          {data.patterns.map((p: any) => (
            <li key={p.id} className="bg-gray-800/60 rounded-lg px-3 py-2">
              <div className="flex justify-between gap-2 items-start">
                <span className="text-gray-200 text-sm">{p.description}</span>
                <span className="text-xs text-gray-500 shrink-0">{Math.round((p.confidence || 0) * 100)}%</span>
              </div>
              <div className="mt-2 flex gap-2">
                <button
                  disabled={busyId === p.id}
                  onClick={() => submitFeedback(p.id, 'confirm')}
                  className="text-xs px-2 py-1 rounded bg-green-700/40 text-green-300 hover:bg-green-700/60 disabled:opacity-50"
                >
                  Confirm
                </button>
                <button
                  disabled={busyId === p.id}
                  onClick={() => submitFeedback(p.id, 'wrong')}
                  className="text-xs px-2 py-1 rounded bg-yellow-700/40 text-yellow-300 hover:bg-yellow-700/60 disabled:opacity-50"
                >
                  Wrong
                </button>
                <button
                  disabled={busyId === p.id}
                  onClick={() => submitFeedback(p.id, 'stop')}
                  className="text-xs px-2 py-1 rounded bg-red-700/40 text-red-300 hover:bg-red-700/60 disabled:opacity-50"
                >
                  Stop using this
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div>
        <div className="text-sm font-semibold text-gray-300 mb-2">Rhythm windows</div>
        {data.rhythm_windows.length === 0 && <p className="text-gray-500 text-sm">Still learning your rhythm.</p>}
        <ul className="space-y-1">
          {data.rhythm_windows.map((r: any) => (
            <li key={`${r.rhythm_key}-${r.day_scope}`} className="text-xs text-gray-400 flex justify-between">
              <span>{r.rhythm_key} ({r.day_scope})</span>
              <span>{r.median_time || '—'} · {Math.round((r.confidence || 0) * 100)}%</span>
            </li>
          ))}
        </ul>
      </div>

      <div>
        <div className="text-sm font-semibold text-gray-300 mb-2">Models</div>
        <ul className="space-y-1">
          {Object.entries(data.models || {}).map(([family, info]: [string, any]) => (
            <li key={family} className="text-xs text-gray-400 flex justify-between">
              <span>{family}</span>
              <span>{info.active_version || 'not trained yet'}{info.candidate_count ? ` · ${info.candidate_count} candidate(s)` : ''}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

export function renderOverlayContent(kind: OverlayKind, payload: Record<string, any>) {
  switch (kind) {
    case 'brief':
      return <BriefContent />
    case 'nutrition':
      return <NutritionContent />
    case 'calendar':
      return <CalendarContent />
    case 'tasks':
      return <TasksContent />
    case 'note':
      return <NoteEditorContent payload={payload} />
    case 'blank-note':
      return <NoteEditorContent payload={{}} />
    case 'report':
      return <ReportContent payload={payload} />
    case 'timers':
      return <TimersContent />
    case 'inbox':
      return <InboxContent />
    case 'recipes':
      return <RecipesContent />
    case 'patterns':
      return <PatternsContent />
    default:
      return <p className="text-gray-400">Unknown overlay: {kind}</p>
  }
}
