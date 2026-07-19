import { useEffect, useState, useCallback } from 'react'
import {
  Footprints, Timer, Plus, Minus, Play, Pencil, Trash2, X, Activity,
} from 'lucide-react'
import {
  LineChart, Line, ResponsiveContainer, YAxis, Tooltip,
} from 'recharts'
import { APP_CONFIG } from '../../config'
import TabataTimer, { TabataConfig, totalSeconds } from './TabataTimer'

// ---- types ----
interface CardioLog {
  id: string; activity_type: string; title: string; duration_minutes: number;
  distance_miles?: number | null; zone?: string | null; source: string; session_date: string;
}
interface MenuItem { key: string; label: string; typical_minutes: number; worth_minutes: number; note: string }
interface Settings { weekly_min_minutes: number; weekly_max_minutes: number; steps_floor: number; menu: MenuItem[] }
interface ByActivity { activity_type: string; minutes: number; count: number }
interface Stats {
  week_start: string; week_end: string; target_min: number; target_max: number;
  total_minutes: number; pct_of_min: number; session_count: number;
  steps_today: number | null; steps_floor: number; by_activity: ByActivity[];
  trend: { week_start: string; minutes: number }[];
}
interface Preset extends TabataConfig { is_built_in: boolean; sort_order: number }

const ACT: Record<string, { label: string; color: string }> = {
  walk: { label: 'Walk', color: '#34d399' }, ruck: { label: 'Ruck', color: '#f59e0b' },
  kb_swings: { label: 'KB Swings', color: '#fb923c' }, coaching: { label: 'Coaching', color: '#38bdf8' },
  commute: { label: 'Commute', color: '#a78bfa' }, run: { label: 'Run', color: '#22d3ee' },
  row: { label: 'Row', color: '#22d3ee' }, bike: { label: 'Bike', color: '#22d3ee' },
  tabata: { label: 'Tabata', color: '#ef4444' }, other: { label: 'Cardio', color: '#94a3b8' },
}
const meta = (k: string) => ACT[k] || ACT.other
const BASE = `${APP_CONFIG.apiUrl}/api/fitness/cardio`
const getJSON = (u: string) => fetch(u, { credentials: 'include' }).then(r => r.json())

type Tab = 'dashboard' | 'log' | 'timers'

export default function CardioSection() {
  const [tab, setTab] = useState<Tab>('dashboard')
  const [stats, setStats] = useState<Stats | null>(null)
  const [settings, setSettings] = useState<Settings | null>(null)
  const [logs, setLogs] = useState<CardioLog[]>([])
  const [presets, setPresets] = useState<Preset[]>([])
  const [running, setRunning] = useState<TabataConfig | null>(null)
  const [logModal, setLogModal] = useState<{ activity: string; minutes: number; title: string } | null>(null)
  const [editor, setEditor] = useState<{ preset: Preset | null } | null>(null)

  const load = useCallback(async () => {
    try {
      const [s, cfg, l, p] = await Promise.all([
        getJSON(`${BASE}/stats?week_offset=0`), getJSON(`${BASE}/settings`),
        getJSON(`${BASE}/logs`), getJSON(`${BASE}/tabata-presets`),
      ])
      setStats(s); setSettings(cfg); setLogs(l.logs || []); setPresets(p.presets || [])
    } catch { /* ignore */ }
  }, [])
  useEffect(() => { load() }, [load])

  const deleteLog = async (id: string) => {
    await fetch(`${BASE}/log/${id}`, { method: 'DELETE', credentials: 'include' })
    load()
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'dashboard', label: 'This Week' }, { id: 'log', label: 'Log' }, { id: 'timers', label: 'Tabata' },
  ]

  return (
    <div className="p-6 space-y-6">
      {/* inner tabs */}
      <div className="flex gap-2">
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              tab === t.id ? 'bg-teal-300 text-slate-900' : 'bg-white/5 text-slate-400 hover:text-slate-200'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'dashboard' && stats && <Dashboard stats={stats} logs={logs} onDelete={deleteLog} />}
      {tab === 'log' && settings && (
        <LogTab settings={settings}
          onPick={(activity, minutes, title) => setLogModal({ activity, minutes, title })}
          onCustom={() => setLogModal({ activity: 'walk', minutes: 30, title: '' })} />
      )}
      {tab === 'timers' && (
        <TimersTab presets={presets}
          onStart={(p) => setRunning(p)}
          onEdit={(p) => setEditor({ preset: p })}
          onNew={() => setEditor({ preset: null })} />
      )}

      {running && <TabataTimer preset={running} onClose={() => { setRunning(null); load() }} onLogged={load} />}
      {logModal && (
        <LogModal initial={logModal} onClose={() => setLogModal(null)} onSaved={() => { setLogModal(null); load() }} />
      )}
      {editor && (
        <PresetEditor preset={editor.preset}
          onClose={() => setEditor(null)}
          onSaved={() => { setEditor(null); load() }}
          onStart={(cfg) => { setEditor(null); setRunning(cfg) }} />
      )}
    </div>
  )
}

// ---- dashboard ----
function Dashboard({ stats, logs, onDelete }: { stats: Stats; logs: CardioLog[]; onDelete: (id: string) => void }) {
  const pct = Math.min(stats.total_minutes / (stats.target_min || 1), 1)
  const maxAct = Math.max(1, ...stats.by_activity.map(a => a.minutes))
  const stepsPct = stats.steps_today != null && stats.steps_floor ? Math.min(stats.steps_today / stats.steps_floor, 1) : 0
  const R = 54, C = 2 * Math.PI * R
  const hit = stats.total_minutes >= stats.target_min

  return (
    <div className="space-y-5">
      {/* hero */}
      <div className="flex items-center gap-6 p-5 bg-white/5 border border-white/10 rounded-xl">
        <svg width={140} height={140} viewBox="0 0 140 140">
          <circle cx={70} cy={70} r={R} stroke="rgba(94,234,212,0.14)" strokeWidth={12} fill="none" />
          <circle cx={70} cy={70} r={R} stroke="#5eead4" strokeWidth={12} fill="none" strokeLinecap="round"
            strokeDasharray={C} strokeDashoffset={C * (1 - pct)} transform="rotate(-90 70 70)" />
          <text x={70} y={64} textAnchor="middle" fontSize={30} fontWeight={800} fill="#f1f5f9" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {Math.round(stats.total_minutes)}
          </text>
          <text x={70} y={88} textAnchor="middle" fontSize={12} fill="#64748b">min</text>
        </svg>
        <div className="space-y-1">
          <div className="text-white font-bold">Target {stats.target_min}–{stats.target_max} min/wk</div>
          <div className="text-sm font-semibold text-teal-300">
            {hit ? '✓ Weekly dose hit — nice.' : `${Math.max(0, Math.round(stats.target_min - stats.total_minutes))} min to the floor`}
          </div>
          <div className="text-sm text-slate-400">{stats.session_count} session{stats.session_count === 1 ? '' : 's'} logged</div>
        </div>
      </div>

      {/* steps */}
      <div className="p-4 bg-white/5 border border-white/10 rounded-xl">
        <div className="flex items-center gap-2 text-slate-400 text-sm"><Footprints className="w-4 h-4 text-emerald-400" /> Steps today</div>
        <div className="text-xl font-extrabold text-white tabular-nums mt-1">
          {stats.steps_today != null ? stats.steps_today.toLocaleString() : '—'}
          <span className="text-sm text-slate-500 font-normal"> / {stats.steps_floor.toLocaleString()}</span>
        </div>
        <div className="h-1.5 rounded-full bg-white/10 mt-2 overflow-hidden">
          <div className="h-full rounded-full" style={{ width: `${stepsPct * 100}%`, background: stepsPct >= 1 ? '#34d399' : '#10b981' }} />
        </div>
      </div>

      {/* by activity */}
      {stats.by_activity.length > 0 && (
        <div className="p-4 bg-white/5 border border-white/10 rounded-xl space-y-2">
          <div className="text-white font-bold mb-1">By activity</div>
          {stats.by_activity.map(a => (
            <div key={a.activity_type} className="flex items-center gap-3">
              <span className="text-sm text-slate-400 w-20">{meta(a.activity_type).label}</span>
              <div className="flex-1 h-2 rounded-full bg-white/5 overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${(a.minutes / maxAct) * 100}%`, background: meta(a.activity_type).color }} />
              </div>
              <span className="text-sm text-white font-semibold w-10 text-right tabular-nums">{Math.round(a.minutes)}m</span>
            </div>
          ))}
        </div>
      )}

      {/* trend */}
      {stats.trend.some(t => t.minutes > 0) && (
        <div className="p-4 bg-white/5 border border-white/10 rounded-xl">
          <div className="text-white font-bold mb-2">8-week trend</div>
          <ResponsiveContainer width="100%" height={130}>
            <LineChart data={stats.trend.map(t => ({ ...t, wk: t.week_start.slice(5) }))}>
              <YAxis hide domain={[0, 'dataMax + 20']} />
              <Tooltip contentStyle={{ background: '#0c1626', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8 }}
                labelStyle={{ color: '#94a3b8' }} formatter={(v: any) => [`${Math.round(v)} min`, 'Cardio']} labelFormatter={(l) => `Week of ${l}`} />
              <Line type="monotone" dataKey="minutes" stroke="#5eead4" strokeWidth={2} dot={{ r: 2 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* recent */}
      <div className="p-4 bg-white/5 border border-white/10 rounded-xl">
        <div className="text-white font-bold mb-2">This week</div>
        {logs.length === 0 ? (
          <div className="text-sm text-slate-500">No sessions yet. Log one from the Log tab.</div>
        ) : (
          <div className="space-y-1">
            {logs.map(l => (
              <div key={l.id} className="flex items-center gap-3 py-1.5 group">
                <div className="w-8 h-8 rounded-full flex items-center justify-center" style={{ background: `${meta(l.activity_type).color}1A` }}>
                  <Activity className="w-4 h-4" style={{ color: meta(l.activity_type).color }} />
                </div>
                <div className="flex-1">
                  <div className="text-sm text-white font-medium">{l.title || meta(l.activity_type).label}</div>
                  <div className="text-xs text-slate-500">{l.session_date}{l.zone ? ` · ${l.zone}` : ''}{l.source === 'tabata' ? ' · tabata' : ''}</div>
                </div>
                <span className="text-white font-bold tabular-nums">{Math.round(l.duration_minutes)}m</span>
                <button onClick={() => onDelete(l.id)} className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-rose-400">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ---- log tab ----
function LogTab({ settings, onPick, onCustom }: {
  settings: Settings; onPick: (a: string, m: number, t: string) => void; onCustom: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="text-sm text-slate-400">The density-engine menu — click to log. Fragments count fully.</div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {settings.menu.map(item => (
          <button key={item.key} onClick={() => onPick(item.key, item.worth_minutes, item.label)}
            className="text-left p-4 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl transition-colors">
            <div className="text-white font-bold">{item.label}</div>
            <div className="text-sm font-semibold" style={{ color: meta(item.key).color }}>{item.worth_minutes} min</div>
            <div className="text-xs text-slate-500 mt-1 line-clamp-2">{item.note}</div>
          </button>
        ))}
      </div>
      <button onClick={onCustom}
        className="w-full flex items-center justify-center gap-2 py-3 rounded-lg border border-teal-400/40 bg-teal-400/10 text-teal-300 font-semibold hover:bg-teal-400/20">
        <Pencil className="w-4 h-4" /> Custom entry
      </button>
    </div>
  )
}

// ---- timers tab ----
function TimersTab({ presets, onStart, onEdit, onNew }: {
  presets: Preset[]; onStart: (p: Preset) => void; onEdit: (p: Preset) => void; onNew: () => void;
}) {
  return (
    <div className="space-y-3">
      <button onClick={onNew} className="w-full flex items-center justify-center gap-2 py-3 rounded-full bg-teal-300 text-slate-900 font-bold">
        <Plus className="w-5 h-5" /> New interval timer
      </button>
      <div className="text-sm text-slate-400">Fully adjustable — set any work/rest, rounds, sets. E.g. 1-minute work intervals.</div>
      {presets.map(p => {
        const total = Math.round(totalSeconds(p) / 60)
        const color = p.color || '#5eead4'
        return (
          <div key={p.id} className="flex items-center gap-3 p-4 bg-white/5 border border-white/10 rounded-xl border-l-4" style={{ borderLeftColor: color }}>
            <button onClick={() => onStart(p)} className="flex-1 text-left">
              <div className="text-white font-bold">{p.name}</div>
              <div className="text-sm text-slate-400">
                {p.sets > 1 ? `${p.sets}× ` : ''}{p.rounds} rounds · {p.work_seconds}s / {p.rest_seconds}s · ~{total} min
              </div>
            </button>
            <button onClick={() => onEdit(p)} className="p-2 text-slate-400 hover:text-slate-200"><Pencil className="w-5 h-5" /></button>
            <button onClick={() => onStart(p)} className="w-10 h-10 rounded-full flex items-center justify-center text-slate-900" style={{ background: color }}>
              <Play className="w-5 h-5" />
            </button>
          </div>
        )
      })}
    </div>
  )
}

// ---- log modal ----
function LogModal({ initial, onClose, onSaved }: {
  initial: { activity: string; minutes: number; title: string }; onClose: () => void; onSaved: () => void;
}) {
  const [activity, setActivity] = useState(initial.activity)
  const [duration, setDuration] = useState(initial.minutes)
  const [distance, setDistance] = useState('')
  const [avgHr, setAvgHr] = useState('')
  const [zone, setZone] = useState<string | null>(null)
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const keys = ['walk', 'ruck', 'kb_swings', 'coaching', 'commute', 'run', 'row', 'bike', 'other']

  const save = async () => {
    setSaving(true)
    try {
      await fetch(`${BASE}/log`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({
          activity_type: activity, title: initial.title, duration_minutes: duration,
          distance_miles: distance ? parseFloat(distance) : null, avg_hr: avgHr ? parseInt(avgHr) : null,
          zone, notes, source: 'manual',
        }),
      })
      onSaved()
    } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="w-full max-w-md bg-[#0c1626] border border-white/10 rounded-2xl p-5 space-y-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="text-white font-bold text-lg">Log cardio</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-teal-300 font-bold mb-2">Activity</div>
          <div className="flex flex-wrap gap-2">
            {keys.map(k => (
              <button key={k} onClick={() => setActivity(k)}
                className={`px-3 py-1.5 rounded-full text-sm border ${activity === k ? 'text-slate-900 font-semibold' : 'bg-white/5 text-slate-400 border-white/10'}`}
                style={activity === k ? { background: meta(k).color, borderColor: meta(k).color } : {}}>
                {meta(k).label}
              </button>
            ))}
          </div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-teal-300 font-bold mb-2">Duration (min)</div>
          <div className="flex items-center justify-center gap-6">
            <button onClick={() => setDuration(d => Math.max(1, d - 5))} className="w-11 h-11 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center text-white"><Minus className="w-5 h-5" /></button>
            <span className="text-4xl font-extrabold text-white tabular-nums w-20 text-center">{duration}</span>
            <button onClick={() => setDuration(d => d + 5)} className="w-11 h-11 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center text-white"><Plus className="w-5 h-5" /></button>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="text-xs uppercase tracking-wide text-teal-300 font-bold mb-1">Distance (mi)</div>
            <input value={distance} onChange={e => setDistance(e.target.value)} inputMode="decimal"
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white" placeholder="—" />
          </div>
          <div>
            <div className="text-xs uppercase tracking-wide text-teal-300 font-bold mb-1">Avg HR</div>
            <input value={avgHr} onChange={e => setAvgHr(e.target.value)} inputMode="numeric"
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white" placeholder="—" />
          </div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-teal-300 font-bold mb-2">Zone</div>
          <div className="flex gap-2">
            {['zone2', 'mixed', 'hard'].map(z => (
              <button key={z} onClick={() => setZone(zone === z ? null : z)}
                className={`px-3 py-1.5 rounded-full text-sm border ${zone === z ? 'bg-teal-400/20 text-teal-300 border-teal-400' : 'bg-white/5 text-slate-400 border-white/10'}`}>
                {z === 'zone2' ? 'Zone 2' : z[0].toUpperCase() + z.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <input value={notes} onChange={e => setNotes(e.target.value)} placeholder="Notes (optional)"
          className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white" />
        <button onClick={save} disabled={saving}
          className="w-full py-3 rounded-lg bg-teal-300 text-slate-900 font-bold disabled:opacity-50">Save</button>
      </div>
    </div>
  )
}

// ---- preset editor ----
function Stepper({ label, value, set, min, max, step, quick, unit }: {
  label: string; value: number; set: (v: number) => void; min: number; max: number; step: number; quick?: number[]; unit?: string;
}) {
  const clamp = (v: number) => set(Math.max(min, Math.min(max, v)))
  const fmtV = (v: number) => (unit === 'sec' && v >= 60 ? `${Math.floor(v / 60)}:${(v % 60).toString().padStart(2, '0')}` : `${v}`)
  return (
    <div className="mb-3">
      <div className="flex justify-between items-baseline mb-1">
        <span className="text-white font-semibold">{label}</span>
        <span className="text-lg font-bold text-white tabular-nums">{fmtV(value)}<span className="text-sm text-slate-500 font-normal">{unit ? ` ${unit}` : ''}</span></span>
      </div>
      <div className="flex items-center gap-2">
        <button onClick={() => clamp(value - step)} className="w-10 h-10 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center text-white"><Minus className="w-4 h-4" /></button>
        <div className="flex-1 flex justify-center gap-1.5 flex-wrap">
          {(quick ?? []).map(q => (
            <button key={q} onClick={() => clamp(q)}
              className={`px-2.5 py-1 rounded text-sm tabular-nums border ${value === q ? 'bg-teal-400/20 text-teal-300 border-teal-400' : 'bg-white/5 text-slate-400 border-white/10'}`}>
              {fmtV(q)}
            </button>
          ))}
        </div>
        <button onClick={() => clamp(value + step)} className="w-10 h-10 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center text-white"><Plus className="w-4 h-4" /></button>
      </div>
    </div>
  )
}

const SWATCHES = ['#ef4444', '#f59e0b', '#06b6d4', '#8b5cf6', '#34d399', '#38bdf8', '#fb7185']
const ACTS = [{ key: 'tabata', label: 'Tabata' }, { key: 'kb_swings', label: 'KB swings' }, { key: 'run', label: 'Run/row/bike' }, { key: 'other', label: 'Other' }]

function PresetEditor({ preset, onClose, onSaved, onStart }: {
  preset: Preset | null; onClose: () => void; onSaved: () => void; onStart: (cfg: TabataConfig) => void;
}) {
  const [name, setName] = useState(preset?.name ?? 'Custom timer')
  const [activity, setActivity] = useState(preset?.activity_type ?? 'tabata')
  const [color, setColor] = useState(preset?.color ?? SWATCHES[0])
  const [prepare, setPrepare] = useState(preset?.prepare_seconds ?? 10)
  const [work, setWork] = useState(preset?.work_seconds ?? 20)
  const [rest, setRest] = useState(preset?.rest_seconds ?? 10)
  const [rounds, setRounds] = useState(preset?.rounds ?? 8)
  const [sets, setSets] = useState(preset?.sets ?? 1)
  const [restSet, setRestSet] = useState(preset?.rest_between_sets_seconds ?? 60)
  const [saving, setSaving] = useState(false)

  const cfg: TabataConfig = {
    id: preset?.id, name: name.trim() || 'Custom timer', activity_type: activity, color,
    prepare_seconds: prepare, work_seconds: work, rest_seconds: rest, rounds, sets, rest_between_sets_seconds: restSet,
  }
  const totalMin = Math.round((totalSeconds(cfg) / 60) * 10) / 10
  const isEdit = !!preset

  const save = async () => {
    setSaving(true)
    try {
      const body = {
        name: cfg.name, activity_type: activity, color, prepare_seconds: prepare, work_seconds: work,
        rest_seconds: rest, rounds, sets, rest_between_sets_seconds: restSet,
      }
      await fetch(isEdit ? `${BASE}/tabata-presets/${preset!.id}` : `${BASE}/tabata-presets`, {
        method: isEdit ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify(body),
      })
      onSaved()
    } finally { setSaving(false) }
  }

  const remove = async () => {
    if (!preset) return
    if (!confirm(`Delete "${preset.name}"?`)) return
    await fetch(`${BASE}/tabata-presets/${preset.id}`, { method: 'DELETE', credentials: 'include' })
    onSaved()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="w-full max-w-md max-h-[90vh] overflow-auto bg-[#0c1626] border border-white/10 rounded-2xl p-5 space-y-3" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="text-white font-bold text-lg">{isEdit ? 'Edit timer' : 'New timer'}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <input value={name} onChange={e => setName(e.target.value)}
          className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2.5 text-white" placeholder="Timer name" />
        <div className="flex flex-wrap gap-2">
          {ACTS.map(a => (
            <button key={a.key} onClick={() => setActivity(a.key)}
              className={`px-3 py-1.5 rounded-full text-sm border ${activity === a.key ? 'bg-teal-400/20 text-teal-300 border-teal-400' : 'bg-white/5 text-slate-400 border-white/10'}`}>
              {a.label}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          {SWATCHES.map(c => (
            <button key={c} onClick={() => setColor(c)} className="w-8 h-8 rounded-full border-2" style={{ background: c, borderColor: color === c ? '#f1f5f9' : 'transparent' }} />
          ))}
        </div>
        <div className="h-px bg-white/10 my-2" />
        <Stepper label="Prepare" value={prepare} set={setPrepare} min={0} max={60} step={5} quick={[0, 5, 10, 15]} unit="sec" />
        <Stepper label="Work" value={work} set={setWork} min={5} max={600} step={5} quick={[20, 30, 45, 60]} unit="sec" />
        <Stepper label="Rest" value={rest} set={setRest} min={0} max={600} step={5} quick={[10, 15, 30, 60]} unit="sec" />
        <Stepper label="Rounds" value={rounds} set={setRounds} min={1} max={50} step={1} quick={[6, 8, 10, 12]} />
        <Stepper label="Sets" value={sets} set={setSets} min={1} max={20} step={1} quick={[1, 2, 3, 4]} />
        {sets > 1 && <Stepper label="Rest between sets" value={restSet} set={setRestSet} min={0} max={600} step={10} quick={[30, 60, 90, 120]} unit="sec" />}
        <div className="text-center p-3 rounded-lg border" style={{ borderColor: `${color}55` }}>
          <div className="text-sm text-slate-400">{sets > 1 ? `${sets} sets × ` : ''}{rounds} rounds · {work}s work / {rest}s rest</div>
          <div className="text-lg font-extrabold" style={{ color }}>≈ {totalMin} min total</div>
        </div>
        <div className="flex gap-2">
          <button onClick={() => onStart(cfg)} className="flex-1 flex items-center justify-center gap-2 py-3 rounded-full font-bold text-slate-900" style={{ background: color }}>
            <Play className="w-4 h-4" /> Start now
          </button>
          <button onClick={save} disabled={saving} className="px-5 py-3 rounded-full bg-white/10 text-white font-bold disabled:opacity-50">Save</button>
          {isEdit && <button onClick={remove} className="w-12 rounded-full bg-rose-500/15 border border-rose-500 flex items-center justify-center text-rose-400"><Trash2 className="w-5 h-5" /></button>}
        </div>
      </div>
    </div>
  )
}
