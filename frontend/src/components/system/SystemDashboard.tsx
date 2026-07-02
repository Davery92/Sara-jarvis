import React, { useEffect, useState, useCallback } from 'react'
import { Activity, Brain, Eye, Gauge, RefreshCw, AlertTriangle, Radio, Sparkles, Mail, Users, Undo2, BookOpen, ThumbsUp, MessageCircle } from 'lucide-react'
import { APP_CONFIG } from '../../config'

/**
 * THE SYSTEM — god-view dashboard (Phase 0 + 1).
 * Makes Sara's existing-but-invisible cognition visible: current world state,
 * attention-balance meter, and her live thought stream.
 */

const DOMAIN_COLOR: Record<string, string> = {
  work: 'bg-teal-400', comms: 'bg-cyan-400', calendar: 'bg-sky-400',
  health: 'bg-rose-400', home: 'bg-amber-400', goals: 'bg-violet-400',
  people: 'bg-pink-400', learning: 'bg-emerald-400', meta: 'bg-slate-500',
}

function timeAgo(iso?: string | null): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (isNaN(t)) return ''
  const s = Math.floor((Date.now() - t) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

const Eyebrow: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span className="assistant-kicker text-teal-300">{children}</span>
)

const Stat: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="rounded-lg bg-white/5 border border-white/10 p-3">
    <div className="text-xs text-slate-500">{label}</div>
    <div className="text-sm text-slate-100 mt-0.5 truncate">{value ?? '—'}</div>
  </div>
)

const SystemDashboard: React.FC = () => {
  const [data, setData] = useState<any>(null)
  const [digest, setDigest] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async () => {
    try {
      setRefreshing(true)
      const [overviewRes, digestRes] = await Promise.all([
        fetch(`${APP_CONFIG.apiUrl}/api/system/overview`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/api/system/digest/latest`, { credentials: 'include' }),
      ])
      if (!overviewRes.ok) throw new Error(`HTTP ${overviewRes.status}`)
      setData(await overviewRes.json())
      if (digestRes.ok) setDigest((await digestRes.json()).digest)
      setErr(null)
    } catch (e: any) {
      setErr(e.message || 'failed to load')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [load])

  const undoAction = useCallback(async (ledgerId: number) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/system/actions/undo`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ ledger_id: ledgerId }),
      })
      load()
    } catch (e) {
      // best-effort; the next poll will reconcile state either way
    }
  }, [load])

  const correctDigestLine = useCallback(async (domain: string, context: string, action: string) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/system/digest/correct`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ domain, context, action }),
      })
      load()
    } catch (e) {
      // best-effort
    }
  }, [load])

  if (loading) {
    return <div className="flex items-center justify-center h-64 text-slate-400">
      <RefreshCw className="w-6 h-6 animate-spin text-teal-300" /></div>
  }

  const fg = data?.world?.foreground || {}
  const world = data?.world?.world || {}
  const bg = world.background || {}
  const activeWork = world.foreground?.active_work || []
  const nextEvent = world.foreground?.next_event
  const commsUnhandled = world.foreground?.comms_unhandled || []
  const peopleRecent = world.foreground?.people_recent || []
  const peopleOverdue = world.foreground?.people_overdue || []
  const balance = data?.balance || {}
  const stream = data?.stream?.items || []
  const promotions = data?.promotions?.items || []
  const actions = data?.actions?.items || []
  const dist = (balance.distribution || []).filter((d: any) => d.count > 0)
  const maxPct = Math.max(1, ...dist.map((d: any) => d.pct))

  return (
    <div className="h-full flex flex-col text-white">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/5 px-6 py-3">
        <div className="flex items-center gap-2">
          <Radio className="w-5 h-5 text-teal-300" />
          <h1 className="font-display text-xl font-semibold">The System</h1>
        </div>
        <button onClick={load} disabled={refreshing}
          className="p-1.5 hover:bg-white/10 rounded transition-colors disabled:opacity-50" title="Refresh">
          <RefreshCw className={`w-4 h-4 text-slate-400 ${refreshing ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="flex-1 overflow-auto p-6 space-y-6 max-w-5xl mx-auto w-full">
        {err && (
          <div className="flex items-center gap-2 rounded-lg bg-rose-500/10 border border-rose-400/30 p-3 text-sm text-rose-200">
            <AlertTriangle className="w-4 h-4" /> {err}
          </div>
        )}

        {/* WORLD — what she perceives right now */}
        <div className="assistant-panel rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3"><Eye className="w-4 h-4 text-teal-300" /><Eyebrow>Right Now</Eyebrow></div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat label="Activity" value={fg.activity_state} />
            <Stat label="Interruptibility" value={fg.interruptibility != null ? `${Math.round(fg.interruptibility * 100)}%` : null} />
            <Stat label="Last chat" value={fg.hours_since_last_chat != null ? `${Math.round(fg.hours_since_last_chat)}h ago` : null} />
            <Stat label="Next event" value={nextEvent ? `${nextEvent.title}${nextEvent.in_minutes != null ? ` · ${nextEvent.in_minutes}m` : ''}` : null} />
            <Stat label="Home" value={fg.home_occupied != null ? (fg.home_occupied ? 'occupied' : 'empty') : null} />
            <Stat label="Open threads" value={fg.open_thread_count} />
            <Stat label="Observations" value={fg.observation_count} />
            <Stat label="Deliberations today" value={fg.sara_deliberation_count_today} />
          </div>
        </div>

        {/* SARA'S MIND — internal state, finally visible */}
        <div className="assistant-panel rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3"><Brain className="w-4 h-4 text-teal-300" /><Eyebrow>Sara's Mind</Eyebrow></div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Stat label="Focus" value={fg.sara_focus} />
            <Stat label="Mood" value={fg.sara_emotional_tone
              ? `${fg.sara_emotional_tone}${fg.sara_emotional_intensity != null ? ` · ${Math.round(fg.sara_emotional_intensity * 100)}%` : ''}` : null} />
            <Stat label="Watching for" value={fg.last_heartbeat_watching_for} />
          </div>
          {Array.isArray(fg.sara_curiosities) && fg.sara_curiosities.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {fg.sara_curiosities.map((c: string, i: number) => (
                <span key={i} className="inline-flex items-center gap-1 rounded-full bg-teal-500/10 border border-teal-400/30 px-2.5 py-1 text-xs text-teal-200">
                  <Sparkles className="w-3 h-3" />{c}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* ACTIVE WORK (foreground, domain: work) */}
        {activeWork.length > 0 && (
          <div className="assistant-panel rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3"><Sparkles className="w-4 h-4 text-teal-300" /><Eyebrow>Active Work</Eyebrow></div>
            <div className="space-y-1.5">
              {activeWork.map((w: any, i: number) => (
                <div key={i} className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-slate-200 truncate">{w.summary}</span>
                  <span className="text-xs text-slate-500 flex-shrink-0">{w.branch || ''} · {timeAgo(w.at)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* UNHANDLED IMPORTANT EMAIL (foreground, domain: comms) */}
        {commsUnhandled.length > 0 && (
          <div className="assistant-panel rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3"><Mail className="w-4 h-4 text-cyan-300" /><Eyebrow>Unhandled Important Email</Eyebrow></div>
            <div className="space-y-1.5">
              {commsUnhandled.map((e: any, i: number) => (
                <div key={i} className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-slate-200 truncate">{e.sender} — {e.subject}</span>
                  <span className="text-xs text-slate-500 flex-shrink-0">{e.age_hours != null ? `${e.age_hours}h ago` : ''}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* PEOPLE (foreground, domain: people) */}
        {(peopleRecent.length > 0 || peopleOverdue.length > 0) && (
          <div className="assistant-panel rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3"><Users className="w-4 h-4 text-pink-300" /><Eyebrow>People</Eyebrow></div>
            {peopleOverdue.length > 0 && (
              <div className="mb-3">
                <div className="text-xs text-slate-500 mb-1.5">Overdue for reconnect</div>
                <div className="space-y-1.5">
                  {peopleOverdue.map((p: any, i: number) => (
                    <div key={i} className="flex items-center justify-between gap-3 text-sm">
                      <span className="text-slate-200 truncate">{p.name}</span>
                      <span className="text-xs text-amber-300 flex-shrink-0">{p.days_since}d</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {peopleRecent.length > 0 && (
              <div>
                <div className="text-xs text-slate-500 mb-1.5">Recent</div>
                <div className="space-y-1.5">
                  {peopleRecent.map((p: any, i: number) => (
                    <div key={i} className="flex items-center justify-between gap-3 text-sm">
                      <span className="text-slate-200 truncate">{p.name}</span>
                      <span className="text-xs text-slate-500 flex-shrink-0">{p.kind} · {p.age_hours != null ? `${p.age_hours}h ago` : ''}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* BACKGROUND — the subconscious hum (stored, not pushed) */}
        <div className="assistant-panel-soft rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3"><Radio className="w-4 h-4 text-slate-400" /><Eyebrow>Background · subconscious</Eyebrow></div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat label="Home events / 24h" value={bg.home?.events_24h} />
            <Stat label="Health metrics / 24h" value={bg.health?.metrics_24h} />
            <Stat label="Resting HR" value={bg.health?.latest?.resting_hr ? `${bg.health.latest.resting_hr} bpm` : null} />
            <Stat label="Sleep" value={bg.health?.latest?.sleep_hours != null ? `${bg.health.latest.sleep_hours}h` : null} />
          </div>
          <p className="text-xs text-slate-500 mt-3">
            {(bg.ambient_event_rate_24h ?? 0).toLocaleString()} ambient signals in 24h — absorbed and baselined, surfaced to attention only on anomaly. (Tier 0 promotion arrives in Phase 2.)
          </p>
        </div>

        {/* ATTENTION BALANCE METER */}
        <div className="assistant-panel rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2"><Gauge className="w-4 h-4 text-teal-300" /><Eyebrow>Attention Balance · last 7 days</Eyebrow></div>
            <span className="text-xs text-slate-500">{balance.total_surfaced ?? 0} surfaced</span>
          </div>
          {balance.skew_warning && (
            <div className="mb-3 flex items-center gap-2 rounded-lg bg-amber-500/5 border border-amber-400/20 p-2.5 text-xs text-amber-200">
              <AlertTriangle className="w-3.5 h-3.5" /> Lopsided — <span className="font-medium">{balance.top_domain}</span> is over half of what reached you.
            </div>
          )}
          <div className="space-y-2">
            {dist.length === 0 && <div className="text-sm text-slate-500">Nothing surfaced in this window.</div>}
            {dist.map((d: any) => (
              <div key={d.domain} className="flex items-center gap-3">
                <div className="w-20 text-xs text-slate-400 text-right capitalize">{d.domain}</div>
                <div className="flex-1 h-3 bg-white/5 rounded-full overflow-hidden">
                  <div className={`h-full ${DOMAIN_COLOR[d.domain] || 'bg-slate-500'} transition-all`}
                    style={{ width: `${(d.pct / maxPct) * 100}%` }} />
                </div>
                <div className="w-14 text-xs text-slate-400 tabular-nums">{d.pct}%</div>
              </div>
            ))}
          </div>
          <p className="text-xs text-slate-500 mt-3">
            What actually reached you, by life-domain. The goal is balance — no single domain dominating — not equal volume.
          </p>
        </div>

        {/* LEARNING — weekly digest + per-line corrections (Phase 6) */}
        {digest && (
          <div className="assistant-panel rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3"><BookOpen className="w-4 h-4 text-teal-300" /><Eyebrow>What I've Learned</Eyebrow></div>
            <p className="text-sm text-slate-200 mb-3">{digest.content}</p>
            {Array.isArray(digest.moves) && digest.moves.length > 0 && (
              <div className="space-y-2">
                {digest.moves.map((m: any, i: number) => (
                  <div key={i} className="flex items-center justify-between gap-3 text-xs bg-white/5 rounded-lg px-3 py-2">
                    <span className="text-slate-300 capitalize">{m.domain} · {m.context} — {m.direction} ({m.delta > 0 ? '+' : ''}{m.delta})</span>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <button onClick={() => correctDigestLine(m.domain, m.context, 'keep_telling_me')}
                        className="flex items-center gap-1 text-teal-300 hover:text-teal-200">
                        <MessageCircle className="w-3 h-3" /> Keep telling me
                      </button>
                      <button onClick={() => correctDigestLine(m.domain, m.context, 'good_call')}
                        className="flex items-center gap-1 text-slate-400 hover:text-slate-300">
                        <ThumbsUp className="w-3 h-3" /> Good call
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ACTIONS — what Sara actually did, autonomously (Phase 4) */}
        {actions.length > 0 && (
          <div className="assistant-panel rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3"><Sparkles className="w-4 h-4 text-teal-300" /><Eyebrow>Actions</Eyebrow></div>
            <div className="space-y-1.5">
              {actions.slice(0, 10).map((a: any, i: number) => (
                <div key={a.id ?? i} className="flex items-center justify-between gap-3 text-sm">
                  <div className="min-w-0">
                    <span className="text-slate-200 truncate">{a.description}</span>
                    <span className="text-xs text-slate-500 ml-2">{a.action_type} · {timeAgo(a.at)}</span>
                  </div>
                  {a.undone ? (
                    <span className="text-xs text-slate-500 flex-shrink-0">undone</span>
                  ) : a.can_undo ? (
                    <button onClick={() => undoAction(a.id)}
                      className="flex items-center gap-1 text-xs text-teal-300 hover:text-teal-200 flex-shrink-0">
                      <Undo2 className="w-3 h-3" /> Undo
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* PROMOTED TO ATTENTION (Tier 0 output) */}
        {promotions.length > 0 && (
          <div className="assistant-panel rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3"><Gauge className="w-4 h-4 text-teal-300" /><Eyebrow>Promoted to Attention · subconscious → conscious</Eyebrow></div>
            <div className="space-y-1.5">
              {promotions.slice(0, 10).map((p: any, i: number) => (
                <div key={i} className="flex items-center justify-between gap-3 text-sm">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${DOMAIN_COLOR[p.domain] || 'bg-slate-500'}`} />
                    <span className="text-slate-200 truncate">{p.description}</span>
                  </div>
                  <span className="text-xs flex-shrink-0">
                    <span className={p.reason === 'override' ? 'text-rose-300' : p.reason === 'exploration' ? 'text-violet-300' : 'text-teal-300'}>{p.reason}</span>
                    <span className="text-slate-500"> · {p.context} · {timeAgo(p.at)}</span>
                  </span>
                </div>
              ))}
            </div>
            <p className="text-xs text-slate-500 mt-3">What Tier 0 judged worth your attention. Everything else was baselined and stayed silent.</p>
          </div>
        )}

        {/* THOUGHT STREAM */}
        <div className="assistant-panel rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3"><Activity className="w-4 h-4 text-teal-300" /><Eyebrow>Thought Stream</Eyebrow></div>
          <div className="space-y-3">
            {stream.length === 0 && <div className="text-sm text-slate-500">No recent thoughts.</div>}
            {stream.map((it: any) => (
              <div key={`${it.kind}-${it.id}`} className="border-l-2 border-teal-400/30 pl-3">
                <div className="flex items-center gap-2 text-xs text-slate-500 mb-0.5">
                  <span className="uppercase tracking-wide text-teal-300/80">{it.subtype || it.kind}</span>
                  <span>·</span>
                  <span>{timeAgo(it.at)}</span>
                  {it.notifications_sent ? <span className="text-amber-300/80">· {it.notifications_sent} notified</span> : null}
                </div>
                <div className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">{it.text}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default SystemDashboard
