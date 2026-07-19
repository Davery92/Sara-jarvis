/**
 * MachinesDashboard — every machine David owns, at a glance (FLEET_DESIGN.md §7.1).
 *
 * Backed entirely by the /api/fleet/* user-facing endpoints. Overview grid of
 * host cards (status, CPU/mem/disk bars, alert badges), a detail drawer with the
 * full snapshot + 24h sparklines + a read-only diag console, and an "Add machine"
 * sheet that shows the install one-liner from GET /api/fleet/enroll-command so the
 * command is always findable in the app.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { APP_CONFIG } from '../../config'

type Alert = { rule: string; severity: string; detail: any; fired_at?: string }
type Headline = {
  cpu_pct?: number; mem_pct?: number; disk_max_pct?: number; load1?: number
  cpu_count?: number; temp_max_c?: number; uptime_seconds?: number; os?: string; arch?: string
}
type HostCard = {
  id: string; name: string; hostname: string; transport: string; has_agent: boolean
  online: boolean; last_report_seconds_ago?: number; agent_version?: string
  headline?: Headline | null; alerts: Alert[]
}
type Overview = { hosts: HostCard[]; summary: { total: number; online: number; alerts: number } }

const api = (path: string) => `${APP_CONFIG.apiUrl}/api/fleet${path}`

function timeAgo(secs?: number): string {
  if (secs == null) return 'never'
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`
  return `${Math.round(secs / 86400)}d ago`
}
function uptimeStr(secs?: number): string {
  if (!secs) return '—'
  const d = Math.floor(secs / 86400)
  const h = Math.floor((secs % 86400) / 3600)
  if (d > 0) return `${d}d ${h}h`
  const m = Math.floor((secs % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}
function fmtBytes(n?: number): string {
  if (n == null) return '—'
  const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  let i = 0
  let v = n
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${u[i]}`
}
function barColor(pct?: number): string {
  if (pct == null) return 'bg-gray-600'
  if (pct >= 95) return 'bg-red-500'
  if (pct >= 85) return 'bg-amber-500'
  if (pct >= 70) return 'bg-yellow-500'
  return 'bg-emerald-500'
}

function Bar({ label, pct }: { label: string; pct?: number }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-10 shrink-0 text-gray-400">{label}</span>
      <div className="h-1.5 flex-1 rounded-full bg-gray-700/60 overflow-hidden">
        <div className={`h-full ${barColor(pct)}`} style={{ width: `${Math.min(100, pct ?? 0)}%` }} />
      </div>
      <span className="w-9 shrink-0 text-right tabular-nums text-gray-300">
        {pct == null ? '—' : `${Math.round(pct)}%`}
      </span>
    </div>
  )
}

function StatusDot({ host }: { host: HostCard }) {
  if (!host.has_agent) return <span title="SSH-only (no agent)" className="text-gray-500">◌</span>
  if (host.online) return <span title="online" className="text-emerald-400">●</span>
  return <span title="offline" className="text-red-500">○</span>
}

function AlertBadge({ a }: { a: Alert }) {
  const critical = a.severity === 'high'
  const d = a.detail || {}
  let text = a.rule.replace(/_/g, ' ')
  if (a.rule.startsWith('disk')) text = `${d.mount || 'disk'} ${d.pct}%`
  else if (a.rule === 'mem_pressure') text = `mem ${d.pct}%`
  else if (a.rule === 'load_high') text = `load ${d.load1}`
  else if (a.rule === 'temp_high') text = `${d.temp_c}°C`
  else if (a.rule === 'unit_failed') text = `${d.count} failed unit(s)`
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
      critical ? 'bg-red-500/15 text-red-300' : 'bg-amber-500/15 text-amber-300'}`}>
      ⚠ {text}
    </span>
  )
}

function HostGridCard({ host, onOpen }: { host: HostCard; onOpen: () => void }) {
  const h = host.headline || {}
  return (
    <button onClick={onOpen}
      className="text-left rounded-xl border border-card bg-card p-4 hover:border-gray-500 transition-colors">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <StatusDot host={host} />
          <span className="font-semibold truncate">{host.name}</span>
        </div>
        <span className="text-[10px] text-gray-500">{timeAgo(host.last_report_seconds_ago)}</span>
      </div>
      <div className="mt-1 flex items-center gap-2 text-[11px] text-gray-400">
        {h.os && <span className="truncate">{h.os}</span>}
        {h.arch && <span className="rounded bg-gray-700/50 px-1">{h.arch}</span>}
      </div>
      {host.has_agent ? (
        <div className="mt-3 space-y-1.5">
          <Bar label="CPU" pct={h.cpu_pct} />
          <Bar label="MEM" pct={h.mem_pct} />
          <Bar label="DISK" pct={h.disk_max_pct} />
          <div className="flex items-center justify-between text-[11px] text-gray-400 pt-1">
            <span>load {h.load1 ?? '—'}{h.cpu_count ? ` / ${h.cpu_count}c` : ''}</span>
            <span>{h.temp_max_c ? `${Math.round(h.temp_max_c)}°C` : ''}</span>
            <span>up {uptimeStr(h.uptime_seconds)}</span>
          </div>
        </div>
      ) : (
        <div className="mt-3 text-[11px] text-gray-500">SSH-only — no fleet agent.</div>
      )}
      {host.alerts.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {host.alerts.map((a, i) => <AlertBadge key={i} a={a} />)}
        </div>
      )}
    </button>
  )
}

// --- Sparkline -------------------------------------------------------------
function Sparkline({ points, label, color }: { points: number[]; label: string; color: string }) {
  const w = 220, hgt = 40
  const clean = points.filter((p) => p != null && !isNaN(p))
  if (clean.length < 2) return <div className="text-[11px] text-gray-500">{label}: not enough data</div>
  const max = Math.max(...clean, 1)
  const min = Math.min(...clean, 0)
  const range = max - min || 1
  const step = w / (points.length - 1)
  const path = points.map((p, i) => {
    const y = hgt - ((p - min) / range) * hgt
    return `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${(isNaN(y) ? hgt : y).toFixed(1)}`
  }).join(' ')
  return (
    <div>
      <div className="flex items-center justify-between text-[11px] text-gray-400">
        <span>{label}</span>
        <span className="tabular-nums">{clean[clean.length - 1].toFixed(0)}</span>
      </div>
      <svg width="100%" viewBox={`0 0 ${w} ${hgt}`} preserveAspectRatio="none" className="mt-1">
        <path d={path} fill="none" stroke={color} strokeWidth="1.5" />
      </svg>
    </div>
  )
}

// --- Diag console ----------------------------------------------------------
const COMMON_COMMANDS = ['df -h', 'free -m', 'uptime', 'ps aux --sort -pcpu',
  'systemctl --failed', 'journalctl -n 100 --no-pager', 'du -sh /var/log', 'ip addr']

function DiagConsole({ hostName }: { hostName: string }) {
  const [cmd, setCmd] = useState('df -h')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<any>(null)

  const run = async () => {
    setRunning(true); setResult(null)
    try {
      const r = await fetch(api(`/hosts/${encodeURIComponent(hostName)}/diag`), {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: cmd, requested_by: 'web' }),
      })
      setResult(await r.json())
    } catch (e: any) {
      setResult({ status: 'error', stderr: String(e) })
    } finally { setRunning(false) }
  }

  return (
    <div>
      <div className="text-xs font-semibold text-gray-300 mb-2">Read-only diagnostics</div>
      <div className="flex flex-wrap gap-1 mb-2">
        {COMMON_COMMANDS.map((c) => (
          <button key={c} onClick={() => setCmd(c)}
            className="rounded bg-gray-700/50 px-1.5 py-0.5 text-[10px] text-gray-300 hover:bg-gray-600">
            {c}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <input value={cmd} onChange={(e) => setCmd(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !running && run()}
          className="flex-1 rounded border border-card bg-black/30 px-2 py-1 text-xs font-mono text-gray-200"
          placeholder="df -h" />
        <button onClick={run} disabled={running}
          className="rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50">
          {running ? 'Running…' : 'Run'}
        </button>
      </div>
      {result && (
        <div className="mt-2">
          {result.status === 'done' || result.stdout ? (
            <pre className="max-h-64 overflow-auto rounded bg-black/40 p-2 text-[11px] font-mono text-gray-300 whitespace-pre-wrap">
              {result.stdout || '(no output)'}
              {result.stderr ? `\n[stderr]\n${result.stderr}` : ''}
            </pre>
          ) : (
            <div className="rounded bg-red-500/10 p-2 text-[11px] text-red-300">
              {result.reason || result.denied_reason || result.message || `status: ${result.status}`}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// --- Detail drawer ---------------------------------------------------------
function DetailDrawer({ name, onClose }: { name: string; onClose: () => void }) {
  const [detail, setDetail] = useState<any>(null)
  const [metrics, setMetrics] = useState<any>(null)

  useEffect(() => {
    let alive = true
    Promise.all([
      fetch(api(`/hosts/${encodeURIComponent(name)}`), { credentials: 'include' }).then((r) => r.json()),
      fetch(api(`/hosts/${encodeURIComponent(name)}/metrics?hours=24`), { credentials: 'include' }).then((r) => r.json()),
    ]).then(([d, m]) => { if (alive) { setDetail(d); setMetrics(m) } }).catch(() => {})
    return () => { alive = false }
  }, [name])

  const snap = detail?.snapshot || {}
  const pts = metrics?.points || []
  const series = (k: string) => pts.map((p: any) => p[k])

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl h-full overflow-y-auto bg-[#0e0f13] border-l border-card p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-bold flex items-center gap-2">
              {detail && <StatusDot host={{ has_agent: true, online: detail.online } as HostCard} />}
              {name}
            </h2>
            <div className="text-xs text-gray-400">
              {snap.os} · {snap.arch} · report {timeAgo(detail?.last_report_seconds_ago)}
              {detail?.agent_version ? ` · agent v${detail.agent_version}` : ''}
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl">×</button>
        </div>

        {!detail ? <div className="text-sm text-gray-400">Loading…</div> : (
          <div className="space-y-5">
            {/* open alerts */}
            {detail.open_alerts?.length > 0 && (
              <section className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
                <div className="text-xs font-semibold text-amber-300 mb-1">Open alerts</div>
                {detail.open_alerts.map((a: Alert, i: number) => (
                  <div key={i} className="text-xs text-gray-300">• <AlertBadge a={a} /> since {a.fired_at ? new Date(a.fired_at).toLocaleString() : '?'}</div>
                ))}
              </section>
            )}

            {/* sparklines */}
            {pts.length > 1 && (
              <section className="grid grid-cols-2 gap-4 rounded-lg border border-card bg-card p-3">
                <Sparkline points={series('cpu_pct')} label="CPU %" color="#60a5fa" />
                <Sparkline points={series('mem_pct')} label="Memory %" color="#a78bfa" />
                <Sparkline points={series('load1')} label="Load" color="#34d399" />
                <Sparkline points={series('disk_max_pct')} label="Disk %" color="#fbbf24" />
              </section>
            )}

            {/* disks */}
            {snap.disks?.length > 0 && (
              <section className="rounded-lg border border-card bg-card p-3">
                <div className="text-xs font-semibold text-gray-300 mb-2">Disks</div>
                <table className="w-full text-[11px] text-gray-300">
                  <tbody>
                    {snap.disks.map((d: any, i: number) => (
                      <tr key={i} className="border-t border-gray-800">
                        <td className="py-1 font-mono">{d.mount}</td>
                        <td className="py-1 text-right">{fmtBytes(d.used)} / {fmtBytes(d.size)}</td>
                        <td className="py-1 pl-3 w-24"><Bar label="" pct={d.used_pct} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}

            {/* top processes + misc */}
            <section className="grid grid-cols-2 gap-4">
              <div className="rounded-lg border border-card bg-card p-3">
                <div className="text-xs font-semibold text-gray-300 mb-1">Top CPU</div>
                <pre className="text-[10px] font-mono text-gray-400 whitespace-pre-wrap">
                  {(snap.top_cpu || []).join('\n') || '—'}
                </pre>
              </div>
              <div className="rounded-lg border border-card bg-card p-3">
                <div className="text-xs font-semibold text-gray-300 mb-1">Network / sessions</div>
                <div className="text-[11px] text-gray-400 space-y-0.5">
                  <div>iface: {snap.net?.default_iface || '—'}</div>
                  <div>rx: {fmtBytes(snap.net_rx_bps)}/s · tx: {fmtBytes(snap.net_tx_bps)}/s</div>
                  <div>sessions: {snap.sessions ?? '—'}</div>
                  {snap.gpu?.length > 0 && <div>gpu: {snap.gpu[0].name} {snap.gpu[0].util_pct}%</div>}
                  {snap.reboot_required && <div className="text-amber-300">reboot required</div>}
                  {snap.updates_pending != null && <div>{snap.updates_pending} updates pending</div>}
                </div>
              </div>
            </section>

            {/* diag console */}
            <section className="rounded-lg border border-card bg-card p-3">
              <DiagConsole hostName={name} />
            </section>
          </div>
        )}
      </div>
    </div>
  )
}

// --- Add machine sheet -----------------------------------------------------
function AddMachineSheet({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<any>(null)
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    fetch(api('/enroll-command'), { credentials: 'include' })
      .then((r) => r.json()).then(setData).catch(() => setData({ error: true }))
  }, [])
  const copy = () => {
    if (data?.command) {
      navigator.clipboard.writeText(data.command)
      setCopied(true); setTimeout(() => setCopied(false), 1500)
    }
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
        className="w-full max-w-xl rounded-xl border border-card bg-[#0e0f13] p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-bold">Add a machine</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl">×</button>
        </div>
        <p className="text-xs text-gray-400 mb-3">
          Run this on any Linux box (as root). It installs the health agent, enrolls it, and starts reporting.
          The card appears here within a minute.
        </p>
        {!data ? <div className="text-sm text-gray-400">Loading…</div> : data.error ? (
          <div className="text-sm text-red-300">Couldn't load the enroll command.</div>
        ) : (
          <>
            {!data.configured && (
              <div className="mb-2 rounded bg-amber-500/10 p-2 text-[11px] text-amber-300">
                FLEET_ENROLL_SECRET isn't set in the backend .env yet — the command below is a template.
              </div>
            )}
            <div className="relative">
              <pre className="max-h-32 overflow-auto rounded bg-black/40 p-3 pr-16 text-[11px] font-mono text-gray-200 whitespace-pre-wrap break-all">
                {data.command}
              </pre>
              <button onClick={copy}
                className="absolute right-2 top-2 rounded bg-blue-600 px-2 py-1 text-[10px] font-medium text-white">
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
            <div className="mt-3 space-y-1 text-[11px] text-gray-400">
              <div>• <span className="font-mono">--name &lt;handle&gt;</span> — override the auto-detected hostname.</div>
              <div>• Uninstall: <span className="font-mono">… | sudo bash -s -- --uninstall</span></div>
              <div>• No passwordless sudo (e.g. Jetson)? Run it inside <span className="font-mono">sudo -i</span>.</div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// --- Root ------------------------------------------------------------------
export default function MachinesDashboard() {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [openHost, setOpenHost] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const timer = useRef<any>(null)

  const load = useCallback(async () => {
    try {
      const r = await fetch(api('/overview'), { credentials: 'include' })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setOverview(await r.json()); setError(null)
    } catch (e: any) { setError(String(e)) }
  }, [])

  useEffect(() => {
    load()
    timer.current = setInterval(load, 30000)
    return () => clearInterval(timer.current)
  }, [load])

  const s = overview?.summary
  const hosts = overview?.hosts || []

  return (
    <div className="flex-1 overflow-y-auto min-h-0 p-5">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="text-xl font-bold flex items-center gap-2">
              <span className="material-symbols-outlined text-blue-400">dns</span> Machines
            </h1>
            {s && (
              <div className="text-sm text-gray-400">
                {s.total} machine{s.total === 1 ? '' : 's'} · {s.online} online
                {s.alerts > 0 ? ` · ${s.alerts} alert${s.alerts === 1 ? '' : 's'}` : ' · all green'}
              </div>
            )}
          </div>
          <button onClick={() => setShowAdd(true)}
            className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-500">
            + Add machine
          </button>
        </div>

        {error && <div className="mb-4 rounded bg-red-500/10 p-3 text-sm text-red-300">Couldn't load fleet: {error}</div>}

        {hosts.length === 0 && !error ? (
          <div className="rounded-xl border border-dashed border-card p-10 text-center text-gray-400">
            <div className="text-3xl mb-2">🖥️</div>
            <div className="font-medium mb-1">No machines yet</div>
            <div className="text-sm mb-4">Install the fleet agent on a box to see it here.</div>
            <button onClick={() => setShowAdd(true)}
              className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white">+ Add machine</button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {hosts.map((h) => (
              <HostGridCard key={h.id} host={h} onOpen={() => setOpenHost(h.name)} />
            ))}
          </div>
        )}
      </div>

      {openHost && <DetailDrawer name={openHost} onClose={() => setOpenHost(null)} />}
      {showAdd && <AddMachineSheet onClose={() => setShowAdd(false)} />}
    </div>
  )
}
