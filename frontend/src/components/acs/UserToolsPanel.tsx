import { useEffect, useState, useCallback } from 'react'
import { APP_CONFIG } from '../../config'

interface ToolVersion {
  id: string
  version: number
  notes: string | null
  created_at: string
}

interface Tool {
  id: string
  name: string
  description: string
  args_schema: Record<string, unknown>
  enabled: boolean
  active_version: ToolVersion | null
  latest_version: ToolVersion | null
  invocation_count_24h: number
  last_invocation_at: string | null
  created_at: string
  updated_at: string
}

interface ToolVersionFull extends ToolVersion {
  code: string
}

interface Invocation {
  id: string
  tool_id: string
  version_id: string
  args: Record<string, unknown>
  result: unknown
  error: string | null
  duration_ms: number | null
  started_at: string
  completed_at: string | null
}

function timeAgo(iso: string | null): string {
  if (!iso) return 'never'
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 0) return 'just now'
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h`
  return `${Math.floor(h / 24)}d`
}

export default function UserToolsPanel() {
  const [tools, setTools] = useState<Tool[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [versions, setVersions] = useState<Record<string, ToolVersionFull[]>>({})
  const [invocations, setInvocations] = useState<Record<string, Invocation[]>>({})
  const [busy, setBusy] = useState<string | null>(null)

  const fetchTools = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/user_tools`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setTools(await res.json())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchTools()
    const refresh = setInterval(fetchTools, 15000)
    return () => clearInterval(refresh)
  }, [fetchTools])

  const fetchDetails = useCallback(async (name: string) => {
    try {
      const [vRes, iRes] = await Promise.all([
        fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/user_tools/${name}/versions`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/user_tools/${name}/invocations?limit=10`, { credentials: 'include' }),
      ])
      if (vRes.ok) {
        const v = await vRes.json()
        setVersions((p) => ({ ...p, [name]: v }))
      }
      if (iRes.ok) {
        const i = await iRes.json()
        setInvocations((p) => ({ ...p, [name]: i }))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load details')
    }
  }, [])

  const toggle = (name: string) => {
    if (expanded === name) {
      setExpanded(null)
    } else {
      setExpanded(name)
      if (!versions[name]) fetchDetails(name)
    }
  }

  const action = async (name: string, path: string, method = 'POST') => {
    setBusy(name)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/user_tools/${name}${path}`, {
        method, credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      await fetchTools()
      if (expanded === name) await fetchDetails(name)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'action failed')
    } finally {
      setBusy(null)
    }
  }

  const enable = (n: string) => action(n, '/enable')
  const disable = (n: string) => action(n, '/disable')
  const remove = (n: string) => {
    if (!confirm(`Delete tool "${n}"? This removes all versions and the invocation log.`)) return
    return action(n, '', 'DELETE')
  }

  const pending = tools.filter((t) => !t.enabled)
  const active = tools.filter((t) => t.enabled)

  const renderTool = (t: Tool) => {
    const v = versions[t.name] || []
    const inv = invocations[t.name] || []
    const isExpanded = expanded === t.name
    const isPending = !t.enabled
    const activeVersion = t.active_version?.version
    return (
      <li key={t.id} className={isPending ? 'border-l-2 border-amber-400/70 pl-3' : ''}>
        <div className="group flex items-start gap-3 rounded-md px-2 py-2 transition-colors hover:bg-white/[0.04]">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="font-mono text-sm text-slate-200">{t.name}</span>
              <span className="font-mono text-xs text-slate-500">v{activeVersion ?? '?'}</span>
              {t.latest_version && t.latest_version.version !== activeVersion && (
                <span className="text-xs text-amber-300/80">
                  latest v{t.latest_version.version} not active
                </span>
              )}
              <span className="ml-auto text-xs text-slate-500">
                {t.invocation_count_24h} calls/24h
              </span>
            </div>
            <div className="mt-0.5 text-xs text-slate-500">{t.description}</div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {isPending ? (
              <button
                onClick={() => enable(t.name)}
                disabled={busy === t.name}
                className="rounded-lg border border-white/10 px-2 py-1 text-xs text-teal-300 transition-colors hover:bg-white/[0.06] disabled:opacity-40"
              >
                Enable
              </button>
            ) : (
              <button
                onClick={() => disable(t.name)}
                disabled={busy === t.name}
                className="text-xs text-slate-500 transition-colors hover:text-slate-300 disabled:opacity-40"
              >
                Disable
              </button>
            )}
            <button
              onClick={() => toggle(t.name)}
              className="text-xs text-slate-500 transition-colors hover:text-slate-300"
            >
              {isExpanded ? '▾' : '▸'}
            </button>
            <button
              onClick={() => remove(t.name)}
              className="text-xs text-slate-600 transition-colors hover:text-rose-400"
              title="Delete"
            >
              ✕
            </button>
          </div>
        </div>

        {isExpanded && (
          <div className="ml-2 mt-1 space-y-4 border-l border-white/8 py-1 pl-4">
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Args schema</div>
              <pre className="overflow-x-auto rounded-lg bg-black/30 p-2 font-mono text-[11px] text-slate-400">
                {JSON.stringify(t.args_schema, null, 2)}
              </pre>
            </div>

            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                Versions ({v.length})
              </div>
              <ul className="space-y-2">
                {v.map((ver) => (
                  <li key={ver.id}>
                    <div className="flex items-baseline gap-2 text-xs">
                      <span className="font-mono text-slate-200">v{ver.version}</span>
                      {ver.version === activeVersion && (
                        <span className="font-mono text-[10px] uppercase tracking-wide text-emerald-300">active</span>
                      )}
                      <span className="text-slate-500">
                        {timeAgo(ver.created_at)} ago
                      </span>
                      {ver.notes && (
                        <span className="ml-auto truncate text-slate-500">
                          “{ver.notes}”
                        </span>
                      )}
                    </div>
                    <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-black/30 p-2 font-mono text-[11px] text-slate-400">
                      {ver.code}
                    </pre>
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                Recent invocations ({inv.length})
              </div>
              {inv.length === 0 ? (
                <div className="text-xs text-slate-500">No calls yet.</div>
              ) : (
                <ul className="space-y-2">
                  {inv.map((iv) => (
                    <li key={iv.id} className={`text-xs ${iv.error ? 'border-l-2 border-rose-400/70 pl-2' : ''}`}>
                      <div className="flex items-baseline gap-2">
                        <span className={`rounded border px-1 font-mono text-[10px] uppercase tracking-wide ${
                          iv.error
                            ? 'border-rose-400/40 text-rose-300'
                            : 'border-emerald-400/30 text-emerald-300'
                        }`}>
                          {iv.error ? 'error' : 'ok'}
                        </span>
                        <span className="text-slate-500">{timeAgo(iv.started_at)} ago</span>
                        {iv.duration_ms !== null && (
                          <span className="ml-auto tabular-nums text-slate-500">{iv.duration_ms}ms</span>
                        )}
                      </div>
                      <pre className="mt-1 whitespace-pre-wrap break-all font-mono text-[11px] text-slate-500">
                        args: {JSON.stringify(iv.args)}
                      </pre>
                      {iv.error && (
                        <pre className="mt-1 whitespace-pre-wrap break-all font-mono text-[11px] text-rose-300/80">
                          {iv.error}
                        </pre>
                      )}
                      {iv.result !== null && iv.result !== undefined && (
                        <pre className="mt-1 whitespace-pre-wrap break-all font-mono text-[11px] text-slate-400">
                          → {JSON.stringify(iv.result)}
                        </pre>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </li>
    )
  }

  return (
    <section className="pt-6">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Tools</h2>
        <span className="text-xs text-slate-500">
          {active.length} active{pending.length > 0 ? ` · ${pending.length} pending review` : ''}
        </span>
      </div>

      {loading && <p className="text-sm text-slate-500">Loading…</p>}
      {error && <p className="mb-2 text-sm text-rose-400">{error}</p>}

      {pending.length > 0 && (
        <div className="mb-4">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-300/80">
            Pending review
          </div>
          <ul className="space-y-1">{pending.map(renderTool)}</ul>
        </div>
      )}

      {active.length > 0 && (
        <div>
          {pending.length > 0 && (
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
              Active
            </div>
          )}
          <ul className="space-y-1">{active.map(renderTool)}</ul>
        </div>
      )}

      {!loading && tools.length === 0 && !error && (
        <p className="text-sm text-slate-500">No user tools yet — Sara will propose these as she works.</p>
      )}
    </section>
  )
}
