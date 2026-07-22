import React, { useEffect, useState, useCallback } from 'react'
import { Brain, RefreshCw, AlertTriangle, CheckCircle2, ShieldCheck, Sparkles, GitBranch } from 'lucide-react'
import { APP_CONFIG } from '../../config'

/**
 * The Mind — the window into Sara's cognition (§7.1 + §7.4 + §7.3).
 * Renders the global workspace (what she's holding in mind now), the self-model
 * (her honest health/calibration/deploy state — the continuous audit), and the
 * graduated-autonomy trust matrix. David should never need to re-run the audit
 * by hand — this page IS the audit, live.
 */

interface Workspace {
  generated_at: string
  open_loops: { topic: string }[]
  predictions_today: { confirmed: number; violated: number; pending: number; notable: { what: string; status: string }[] }
  concern: { level: string; drivers: string[] }
  inflight_work: { kind: string; status: string }[]
  todays_plan: { title: string; at: string }[]
  david_state: { asleep?: boolean; sleep_source?: string; readiness?: number }
}

interface SelfModel {
  health: { ok: boolean; issue_count: number; issues: { what: string; severity: string; detail?: string; since?: string }[] }
  calibration: { overall_by_bucket?: Record<string, { n: number; hit_rate: number | null }> }
  capabilities: Record<string, any>
  deploy: { acs_daemon?: { alive: boolean; version?: string; state?: string; heartbeat_minutes_ago?: number } }
  summary: string
}

interface TrustClass {
  action_class: string
  granted_level: number
  executions: number
  failures: number
  acceptance_rate: number
  promotion_eligible: boolean
}

const LEVELS = ['Observe', 'Suggest', 'Act & tell', 'Act silently']

const LADDER_ORDER = ['observed', 'believed', 'predictive', 'actionable', 'automated']
const LADDER_COLOR: Record<string, string> = {
  observed: 'bg-slate-400', believed: 'bg-sky-400', predictive: 'bg-violet-400',
  actionable: 'bg-amber-400', automated: 'bg-emerald-500',
}

interface Belief {
  id: string; statement: string; confidence: number; evidence_count: number
  ladder_status: string; times_suggested: number; times_accepted: number
}

function Card({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-200/60 dark:border-slate-700/60 bg-white/70 dark:bg-slate-800/50 p-5 shadow-sm">
      <div className="flex items-center gap-2 mb-3 text-slate-700 dark:text-slate-200">
        {icon}<h3 className="font-semibold">{title}</h3>
      </div>
      {children}
    </div>
  )
}

export default function MindDashboard() {
  const [ws, setWs] = useState<Workspace | null>(null)
  const [self, setSelf] = useState<SelfModel | null>(null)
  const [trust, setTrust] = useState<TrustClass[]>([])
  const [beliefs, setBeliefs] = useState<Belief[]>([])
  const [contradictions, setContradictions] = useState(0)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [w, s, t, b] = await Promise.all([
        fetch(`${APP_CONFIG.apiUrl}/api/mind/workspace`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/api/mind/self`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/api/mind/trust`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/api/mind/beliefs`, { credentials: 'include' }),
      ])
      if (w.ok) setWs(await w.json())
      if (s.ok) setSelf(await s.json())
      if (t.ok) setTrust((await t.json()).classes || [])
      if (b.ok) { const bj = await b.json(); setBeliefs(bj.beliefs || []); setContradictions(bj.open_contradictions || 0) }
    } catch (e) {
      console.error('[Mind] load failed', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const setGrant = async (action_class: string, level: number) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/mind/trust/grant`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_class, level }),
      })
      load()
    } catch (e) { console.error(e) }
  }

  return (
    <div className="flex-1 overflow-y-auto min-h-0 p-4 md:p-6 space-y-5 max-w-5xl mx-auto w-full">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="w-6 h-6 text-violet-500" />
          <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100">The Mind</h1>
        </div>
        <button onClick={load} className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-500">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Workspace strip — what she's holding in mind now */}
      <Card title="Holding in mind right now" icon={<Sparkles className="w-4 h-4 text-amber-500" />}>
        {ws ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <Stat label="David" value={ws.david_state?.asleep ? 'Asleep' : 'Awake'}
              sub={ws.david_state?.readiness != null ? `readiness ${ws.david_state.readiness}` : ws.david_state?.sleep_source} />
            <Stat label="Predictions" value={`${ws.predictions_today?.confirmed ?? 0}✓ / ${ws.predictions_today?.violated ?? 0}✗`}
              sub={`${ws.predictions_today?.pending ?? 0} pending`} />
            <Stat label="Open loops" value={String(ws.open_loops?.length ?? 0)}
              sub={ws.open_loops?.[0]?.topic?.slice(0, 24)} />
            <Stat label="In-flight" value={String(ws.inflight_work?.length ?? 0)}
              sub={ws.concern?.level && ws.concern.level !== 'calm' ? `concern: ${ws.concern.level}` : 'calm'} />
            {ws.todays_plan?.[0] && (
              <div className="col-span-2 md:col-span-4 text-slate-600 dark:text-slate-300">
                <span className="text-slate-400">Next:</span> {ws.todays_plan[0].title}
              </div>
            )}
            {ws.concern?.drivers?.[0] && (
              <div className="col-span-2 md:col-span-4 text-amber-600 dark:text-amber-400 text-xs">
                On my mind: {ws.concern.drivers[0]}
              </div>
            )}
          </div>
        ) : <Empty loading={loading} />}
      </Card>

      {/* Self-model — honest health */}
      <Card title="How I'm actually doing (self-model)"
        icon={self?.health?.ok ? <CheckCircle2 className="w-4 h-4 text-emerald-500" /> : <AlertTriangle className="w-4 h-4 text-rose-500" />}>
        {self ? (
          <div className="space-y-3">
            <div className={`text-sm ${self.health.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}>
              {self.summary}
            </div>
            {self.health.issues?.length > 0 && (
              <ul className="space-y-1 text-sm">
                {self.health.issues.map((iss, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className={`mt-1 w-2 h-2 rounded-full ${iss.severity === 'error' ? 'bg-rose-500' : 'bg-amber-500'}`} />
                    <span className="text-slate-600 dark:text-slate-300">{iss.what}</span>
                  </li>
                ))}
              </ul>
            )}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3 pt-2 border-t border-slate-200/60 dark:border-slate-700/60 text-xs">
              {self.deploy?.acs_daemon && (
                <Stat label="ACS daemon" value={self.deploy.acs_daemon.alive ? 'alive' : 'down'}
                  sub={`${self.deploy.acs_daemon.version || ''} · ${self.deploy.acs_daemon.heartbeat_minutes_ago ?? '?'}m ago`} />
              )}
              {self.capabilities?.notification_value_model && (
                <Stat label="Value model" value={self.capabilities.notification_value_model.trained ? 'trained' : 'none'}
                  sub={self.capabilities.notification_value_model.version} />
              )}
              {self.calibration?.overall_by_bucket && (
                <Stat label="Calibration (0.9–1.0)"
                  value={self.calibration.overall_by_bucket['0.9-1.0'] ? `${Math.round((self.calibration.overall_by_bucket['0.9-1.0'].hit_rate || 0) * 100)}%` : '—'}
                  sub="stated vs actual" />
              )}
            </div>
          </div>
        ) : <Empty loading={loading} />}
      </Card>

      {/* Trust matrix */}
      <Card title="Autonomy trust matrix" icon={<ShieldCheck className="w-4 h-4 text-sky-500" />}>
        {trust.length > 0 ? (
          <div className="space-y-2">
            {trust.map((c) => (
              <div key={c.action_class} className="flex items-center justify-between gap-3 text-sm">
                <div className="min-w-0">
                  <div className="text-slate-700 dark:text-slate-200 truncate">{c.action_class.replace(/_/g, ' ')}</div>
                  <div className="text-xs text-slate-400">
                    {c.executions} runs · {c.failures} fails · {Math.round(c.acceptance_rate * 100)}% accepted
                    {c.promotion_eligible && <span className="text-emerald-500 ml-1">· eligible ↑</span>}
                  </div>
                </div>
                <div className="flex gap-1 flex-shrink-0">
                  {LEVELS.map((lbl, lvl) => (
                    <button key={lvl} onClick={() => setGrant(c.action_class, lvl)}
                      title={lbl}
                      className={`px-2 py-1 rounded text-xs font-medium transition ${
                        c.granted_level === lvl
                          ? 'bg-sky-500 text-white'
                          : 'bg-slate-100 dark:bg-slate-700 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-600'
                      }`}>
                      L{lvl}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            <p className="text-xs text-slate-400 pt-1">L0 observe · L1 suggest · L2 act &amp; tell · L3 act silently. Failures auto-demote.</p>
          </div>
        ) : <Empty loading={loading} />}
      </Card>

      {/* Belief ladder */}
      <Card title="Beliefs" icon={<GitBranch className="w-4 h-4 text-violet-500" />}>
        {beliefs.length > 0 ? (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2 text-xs">
              {LADDER_ORDER.map((st) => {
                const n = beliefs.filter((b) => b.ladder_status === st).length
                if (!n) return null
                return (
                  <span key={st} className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-slate-100 dark:bg-slate-700">
                    <span className={`w-2 h-2 rounded-full ${LADDER_COLOR[st] || 'bg-slate-400'}`} />
                    {st} {n}
                  </span>
                )
              })}
              {contradictions > 0 && (
                <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-rose-100 dark:bg-rose-900/40 text-rose-600 dark:text-rose-300">
                  <AlertTriangle className="w-3 h-3" /> {contradictions} contradiction{contradictions !== 1 ? 's' : ''}
                </span>
              )}
            </div>
            <ul className="space-y-1.5">
              {beliefs.slice(0, 12).map((b) => (
                <li key={b.id} className="flex items-center gap-2 text-sm">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${LADDER_COLOR[b.ladder_status] || 'bg-slate-400'}`} title={b.ladder_status} />
                  <span className="text-slate-600 dark:text-slate-300 truncate flex-1">{b.statement}</span>
                  <span className="text-xs text-slate-400 flex-shrink-0">{Math.round((b.confidence || 0) * 100)}% · {b.evidence_count}d</span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-slate-400">observed → believed → predictive → actionable → automated. Confirmed patterns become automations with your consent.</p>
          </div>
        ) : <Empty loading={loading} />}
      </Card>
    </div>
  )
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-xs text-slate-400">{label}</div>
      <div className="font-semibold text-slate-700 dark:text-slate-100">{value}</div>
      {sub && <div className="text-xs text-slate-400 truncate">{sub}</div>}
    </div>
  )
}

function Empty({ loading }: { loading: boolean }) {
  return <div className="text-sm text-slate-400">{loading ? 'Loading…' : 'No data yet.'}</div>
}
