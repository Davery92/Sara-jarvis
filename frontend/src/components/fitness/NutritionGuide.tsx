import React, { useEffect, useState } from 'react'
import { Beef, Wheat, Droplet, Flame, Target, Clock, CheckCircle2, AlertTriangle, Loader2, Pencil, Save, X } from 'lucide-react'
import { APP_CONFIG } from '../../config'

/**
 * The Forge — Recomp Nutrition Guide.
 * Data-driven: fetches the structured guide stored on the active program
 * (set by the Plan Importer). Falls back to the built-in default below when
 * no guide has been imported yet.
 */

interface Macro { label: string; training: string; rest: string }
interface Rule { title: string; body: string }
interface CarbTiming { days?: string; pre?: string; post?: string; note?: string }
interface Staples { carbs?: string; protein?: string; watch_out?: string }
interface Guide {
  goal?: string
  how_it_works?: string
  weekly_average?: string
  macros?: Macro[]
  rules?: Rule[]
  carb_timing?: CarbTiming | null
  staples?: Staples | null
  self_check?: string[]
}

const DEFAULT_GUIDE: Guide = {
  goal: 'recomp at a flat ~240 lbs — grow the chest, lean out elsewhere, hold strength.',
  how_it_works:
    'eat at maintenance on average (not a deficit), keep protein high, cycle carbs around training. Bodyweight stays steady while composition shifts.',
  weekly_average: '~2,630 cal/day — right around maintenance, so the scale holds flat.',
  macros: [
    { label: 'Calories', training: '~2,800', rest: '~2,400' },
    { label: 'Protein', training: '~240g', rest: '~240g' },
    { label: 'Carbs', training: '~280–300g', rest: '~150g' },
    { label: 'Fat', training: '~70g', rest: '~95g' },
  ],
  rules: [
    { title: 'Protein is the anchor — 240g every single day.', body: 'Training or rest, no exceptions. This is what lets you build chest tissue without gaining fat. (~960 cal/day from protein.)' },
    { title: 'Carbs cycle, fat fills the gap.', body: 'Training days go carb-heavy to fuel pressing volume; rest days drop carbs and let fat take over.' },
    { title: 'Eat at maintenance, not under.', body: 'A deficit would blunt the chest growth you are chasing. Hold the line at ~240 and let composition do the work.' },
  ],
  carb_timing: {
    days: 'Mon/Thu',
    pre: 'Oats or rice',
    post: 'A rice-heavy meal',
    note: 'Glycogen going in, a recovery window coming out — exactly when the pre-exhaust pec volume creates the most growth stimulus.',
  },
  staples: {
    carbs: 'jasmine rice, golf-ball potatoes, oats',
    protein: 'rotisserie chicken, chuck roast, 83% ground beef',
    watch_out: '83% beef runs fat-heavy — drain it well, keep portions ~5 oz so the rest-day fat budget does not blow out. On training days the extra fat matters less; on rest days, lean harder on chicken.',
  },
  self_check: [
    'Did I hit ~240g protein? (the one that matters most)',
    'Training day → more rice, less fat. Rest day → less rice, more fat.',
    'Are most of my carbs landing around the training sessions?',
    'Is the scale roughly flat week to week? (That means it is working — composition is moving underneath.)',
  ],
}

const macroIcon = (label: string): React.ReactNode => {
  const l = label.toLowerCase()
  if (l.includes('cal')) return <Flame className="w-4 h-4 text-amber-300" />
  if (l.includes('protein')) return <Beef className="w-4 h-4 text-rose-300" />
  if (l.includes('carb')) return <Wheat className="w-4 h-4 text-teal-300" />
  if (l.includes('fat')) return <Droplet className="w-4 h-4 text-cyan-300" />
  return <Target className="w-4 h-4 text-slate-300" />
}

const Eyebrow: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span className="assistant-kicker text-teal-300">{children}</span>
)

const NutritionGuide: React.FC = () => {
  const [guide, setGuide] = useState<Guide>(DEFAULT_GUIDE)
  const [loading, setLoading] = useState(true)
  const [imported, setImported] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const resp = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/nutrition-guide`, { credentials: 'include' })
        if (resp.ok) {
          const data = await resp.json()
          if (active && data.guide) {
            setGuide({ ...DEFAULT_GUIDE, ...data.guide })
            setImported(true)
          }
        }
      } catch {
        /* keep default */
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => { active = false }
  }, [])

  const startEditing = () => {
    setDraft(JSON.stringify(guide, null, 2))
    setSaveError(null)
    setEditing(true)
  }

  const cancelEditing = () => {
    setEditing(false)
    setSaveError(null)
  }

  const saveEditing = async () => {
    let parsed: Guide
    try {
      parsed = JSON.parse(draft)
    } catch {
      setSaveError('Not valid JSON — check for a trailing comma or missing quote.')
      return
    }
    setSaving(true)
    setSaveError(null)
    try {
      const resp = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/nutrition-guide`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ guide: parsed }),
      })
      if (resp.ok) {
        setGuide({ ...DEFAULT_GUIDE, ...parsed })
        setImported(true)
        setEditing(false)
      } else {
        const err = await resp.json().catch(() => null)
        setSaveError(err?.detail || 'Failed to save.')
      }
    } catch {
      setSaveError('Failed to save. Check your connection.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400">
        <Loader2 className="w-6 h-6 animate-spin text-teal-300" />
      </div>
    )
  }

  const g = guide
  const macros = g.macros?.length ? g.macros : DEFAULT_GUIDE.macros!
  const rules = g.rules?.length ? g.rules : []
  const checks = g.self_check?.length ? g.self_check : []

  return (
    <div className="p-6 space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div>
        <div className="flex items-start justify-between gap-3">
          <h1 className="font-display text-2xl font-bold text-white">Recomp Nutrition Guide</h1>
          {!editing && (
            <button
              onClick={startEditing}
              className="flex-shrink-0 flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300"
            >
              <Pencil className="w-3.5 h-3.5" />
              Edit
            </button>
          )}
        </div>
        {g.goal && (
          <p className="text-slate-400 text-sm mt-2">
            <span className="text-slate-200 font-medium">Goal:</span> {g.goal}
          </p>
        )}
        {g.how_it_works && (
          <p className="text-slate-400 text-sm mt-1">
            <span className="text-slate-200 font-medium">How it works:</span> {g.how_it_works}
          </p>
        )}
        {!imported && (
          <p className="text-xs text-slate-500 mt-2 italic">
            Showing the built-in guide. Use “Import Plan” to replace this from a document.
          </p>
        )}
      </div>

      {editing && (
        <div className="assistant-panel rounded-xl p-5 space-y-3">
          <Eyebrow>Edit Guide JSON</Eyebrow>
          <p className="text-xs text-slate-500">
            Fields: goal, how_it_works, weekly_average, macros (list of {'{label, training, rest}'}),
            rules (list of {'{title, body}'}), carb_timing, staples, self_check.
          </p>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            spellCheck={false}
            className="w-full h-96 font-mono text-xs bg-black/30 border border-white/10 rounded-lg p-3 text-slate-200 focus:outline-none focus:border-teal-400/50"
          />
          {saveError && <p className="text-xs text-rose-400">{saveError}</p>}
          <div className="flex gap-2">
            <button
              onClick={saveEditing}
              disabled={saving}
              className="flex items-center gap-1.5 text-sm font-medium px-4 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white disabled:opacity-50"
            >
              <Save className="w-4 h-4" />
              {saving ? 'Saving...' : 'Save'}
            </button>
            <button
              onClick={cancelEditing}
              className="flex items-center gap-1.5 text-sm font-medium px-4 py-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300"
            >
              <X className="w-4 h-4" />
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Daily Targets */}
      <div className="assistant-panel rounded-xl p-5">
        <Eyebrow>Daily Targets</Eyebrow>
        <div className="mt-3 overflow-hidden rounded-lg border border-white/10">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-white/5 text-left">
                <th className="px-4 py-2.5 font-medium text-slate-400"></th>
                <th className="px-4 py-2.5 font-medium text-teal-300">Training Days</th>
                <th className="px-4 py-2.5 font-medium text-slate-300">Rest Days</th>
              </tr>
            </thead>
            <tbody>
              {macros.map((m, i) => (
                <tr key={m.label} className={i % 2 ? 'bg-white/[0.02]' : ''}>
                  <td className="px-4 py-2.5">
                    <span className="flex items-center gap-2 font-medium text-slate-200">{macroIcon(m.label)}{m.label}</span>
                  </td>
                  <td className="px-4 py-2.5 text-white tabular-nums">{m.training}</td>
                  <td className="px-4 py-2.5 text-slate-300 tabular-nums">{m.rest}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {g.weekly_average && (
          <p className="text-xs text-slate-400 mt-3">
            <span className="text-slate-200 font-medium">Weekly average:</span> {g.weekly_average}
          </p>
        )}
      </div>

      {/* The Rules */}
      {rules.length > 0 && (
        <div className="assistant-panel rounded-xl p-5">
          <Eyebrow>The Rules</Eyebrow>
          <div className="mt-4 space-y-4">
            {rules.map((r, i) => (
              <div key={i} className="flex gap-3">
                <div className="flex-shrink-0 w-7 h-7 rounded-full bg-teal-500/15 border border-teal-400/30 flex items-center justify-center text-teal-300 font-semibold text-sm">
                  {i + 1}
                </div>
                <div>
                  <div className="font-medium text-white">{r.title}</div>
                  {r.body && <div className="text-sm text-slate-400 mt-0.5">{r.body}</div>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Carb Timing */}
      {g.carb_timing && (g.carb_timing.pre || g.carb_timing.post) && (
        <div className="assistant-panel rounded-xl p-5">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-teal-300" />
            <Eyebrow>Carb Timing</Eyebrow>
          </div>
          {g.carb_timing.days && (
            <p className="text-sm text-slate-400 mt-3">
              On training days <span className="text-slate-200 font-medium">({g.carb_timing.days})</span>, put the bulk of
              carbs around the session:
            </p>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
            {g.carb_timing.pre && (
              <div className="rounded-lg bg-white/5 border border-white/10 p-4">
                <div className="text-xs uppercase tracking-wide text-teal-300 font-semibold">Pre-workout</div>
                <div className="text-sm text-slate-200 mt-1">{g.carb_timing.pre}</div>
              </div>
            )}
            {g.carb_timing.post && (
              <div className="rounded-lg bg-white/5 border border-white/10 p-4">
                <div className="text-xs uppercase tracking-wide text-teal-300 font-semibold">Post-workout</div>
                <div className="text-sm text-slate-200 mt-1">{g.carb_timing.post}</div>
              </div>
            )}
          </div>
          {g.carb_timing.note && <p className="text-xs text-slate-500 mt-3">{g.carb_timing.note}</p>}
        </div>
      )}

      {/* Staples → Macros */}
      {g.staples && (g.staples.carbs || g.staples.protein || g.staples.watch_out) && (
        <div className="assistant-panel rounded-xl p-5">
          <Eyebrow>Staples → Macros</Eyebrow>
          <div className="mt-4 space-y-3 text-sm">
            {g.staples.carbs && (
              <div className="flex items-start gap-2">
                <Wheat className="w-4 h-4 text-teal-300 mt-0.5 flex-shrink-0" />
                <div><span className="font-medium text-slate-200">Carbs:</span> <span className="text-slate-400">{g.staples.carbs}</span></div>
              </div>
            )}
            {g.staples.protein && (
              <div className="flex items-start gap-2">
                <Beef className="w-4 h-4 text-rose-300 mt-0.5 flex-shrink-0" />
                <div><span className="font-medium text-slate-200">Protein:</span> <span className="text-slate-400">{g.staples.protein}</span></div>
              </div>
            )}
            {g.staples.watch_out && (
              <div className="flex items-start gap-2 rounded-lg bg-amber-500/5 border border-amber-400/20 p-3">
                <AlertTriangle className="w-4 h-4 text-amber-300 mt-0.5 flex-shrink-0" />
                <div><span className="font-medium text-amber-200">Watch-out:</span> <span className="text-slate-300">{g.staples.watch_out}</span></div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Quick Self-Check */}
      {checks.length > 0 && (
        <div className="assistant-panel rounded-xl p-5">
          <div className="flex items-center gap-2">
            <Target className="w-4 h-4 text-teal-300" />
            <Eyebrow>Quick Self-Check</Eyebrow>
          </div>
          <ul className="mt-4 space-y-2.5">
            {checks.map((c, i) => (
              <li key={i} className="flex items-start gap-2.5 text-sm text-slate-300">
                <CheckCircle2 className="w-4 h-4 text-teal-400 mt-0.5 flex-shrink-0" />
                <span>{c}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default NutritionGuide
