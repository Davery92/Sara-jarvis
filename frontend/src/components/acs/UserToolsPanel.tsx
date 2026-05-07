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
      <li key={t.id} className="bg-gray-900/40 rounded border border-gray-800">
        <div className="px-3 py-2 flex items-start gap-3">
          <span
            className={`mt-1 h-2 w-2 rounded-full shrink-0 ${
              t.enabled ? 'bg-emerald-400' : 'bg-amber-400 animate-pulse'
            }`}
            title={t.enabled ? 'enabled' : 'pending review'}
          />
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-sm font-mono text-zinc-100">{t.name}</span>
              <span className="text-[10px] text-zinc-500">v{activeVersion ?? '?'}</span>
              {t.latest_version && t.latest_version.version !== activeVersion && (
                <span className="text-[10px] text-amber-400">
                  (latest v{t.latest_version.version} not active)
                </span>
              )}
              <span className="text-[10px] text-zinc-500 ml-auto">
                {t.invocation_count_24h} calls/24h
              </span>
            </div>
            <div className="text-xs text-zinc-400 mt-0.5">{t.description}</div>
          </div>
          <div className="flex gap-1 shrink-0">
            {isPending ? (
              <button
                onClick={() => enable(t.name)}
                disabled={busy === t.name}
                className="text-xs px-2 py-1 bg-emerald-600/80 hover:bg-emerald-500 disabled:bg-gray-700 text-white rounded"
              >
                Enable
              </button>
            ) : (
              <button
                onClick={() => disable(t.name)}
                disabled={busy === t.name}
                className="text-xs px-2 py-1 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 text-zinc-200 rounded"
              >
                Disable
              </button>
            )}
            <button
              onClick={() => toggle(t.name)}
              className="text-xs px-2 py-1 text-zinc-400 hover:text-zinc-200"
            >
              {isExpanded ? '▾' : '▸'}
            </button>
            <button
              onClick={() => remove(t.name)}
              className="text-xs px-2 py-1 text-zinc-600 hover:text-red-400"
              title="Delete"
            >
              ✕
            </button>
          </div>
        </div>

        {isExpanded && (
          <div className="border-t border-gray-800 px-3 py-2 space-y-3">
            <div>
              <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">Args schema</div>
              <pre className="text-[11px] bg-black/40 rounded p-2 text-zinc-300 overflow-x-auto">
                {JSON.stringify(t.args_schema, null, 2)}
              </pre>
            </div>

            <div>
              <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">
                Versions ({v.length})
              </div>
              <ul className="space-y-1">
                {v.map((ver) => (
                  <li key={ver.id} className="bg-black/30 rounded p-2">
                    <div className="flex items-baseline gap-2 text-xs">
                      <span className="font-mono text-zinc-200">v{ver.version}</span>
                      {ver.version === activeVersion && (
                        <span className="text-[10px] text-emerald-400 uppercase">active</span>
                      )}
                      <span className="text-[10px] text-zinc-500">
                        {timeAgo(ver.created_at)} ago
                      </span>
                      {ver.notes && (
                        <span className="text-[10px] text-zinc-400 italic ml-auto truncate">
                          “{ver.notes}”
                        </span>
                      )}
                    </div>
                    <pre className="text-[11px] mt-1 bg-black/60 rounded p-2 text-zinc-300 overflow-x-auto whitespace-pre-wrap break-all">
                      {ver.code}
                    </pre>
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">
                Recent invocations ({inv.length})
              </div>
              {inv.length === 0 ? (
                <div className="text-xs text-zinc-500 italic">no calls yet</div>
              ) : (
                <ul className="space-y-1">
                  {inv.map((iv) => (
                    <li key={iv.id} className="bg-black/30 rounded p-2 text-xs">
                      <div className="flex items-baseline gap-2">
                        <span
                          className={`text-[10px] uppercase tracking-wide px-1 rounded border ${
                            iv.error
                              ? 'bg-red-500/15 text-red-300 border-red-500/30'
                              : 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                          }`}
                        >
                          {iv.error ? 'error' : 'ok'}
                        </span>
                        <span className="text-zinc-500">{timeAgo(iv.started_at)} ago</span>
                        {iv.duration_ms !== null && (
                          <span className="text-zinc-500 ml-auto">{iv.duration_ms}ms</span>
                        )}
                      </div>
                      <pre className="text-[11px] mt-1 text-zinc-400 whitespace-pre-wrap break-all">
                        args: {JSON.stringify(iv.args)}
                      </pre>
                      {iv.error && (
                        <pre className="text-[11px] mt-1 text-red-300 whitespace-pre-wrap break-all">
                          {iv.error}
                        </pre>
                      )}
                      {iv.result !== null && iv.result !== undefined && (
                        <pre className="text-[11px] mt-1 text-zinc-300 whitespace-pre-wrap break-all">
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
    <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-200">Tools</h3>
        <span className="text-xs text-zinc-500">
          {active.length} active{pending.length > 0 ? ` · ${pending.length} pending review` : ''}
        </span>
      </div>

      {loading && <div className="text-zinc-500 text-sm italic">Loading…</div>}
      {error && <div className="text-red-400 text-sm mb-2">{error}</div>}

      {pending.length > 0 && (
        <div className="mb-3">
          <div className="text-[10px] uppercase tracking-wide text-amber-400 mb-1">
            Pending review
          </div>
          <ul className="space-y-2">{pending.map(renderTool)}</ul>
        </div>
      )}

      {active.length > 0 && (
        <div>
          {pending.length > 0 && (
            <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">
              Active
            </div>
          )}
          <ul className="space-y-2">{active.map(renderTool)}</ul>
        </div>
      )}

      {!loading && tools.length === 0 && !error && (
        <div className="text-zinc-500 text-sm italic">
          no user tools yet — Sara will propose these as she works
        </div>
      )}
    </div>
  )
}
