import React, { useEffect, useState, useCallback } from 'react'
import { Activity, AlertTriangle, CheckCircle2, FileText } from 'lucide-react'
import { APP_CONFIG } from '../../config'

interface FailingTask {
  task_name: string
  error_class: string
  error_message?: string
  count_24h: number
  feature?: string | null
  event_id: string
  last_seen?: string | null
}

interface Overview {
  failing_tasks: FailingTask[]
  failing_task_count: number
  error_counts_by_service_24h: Record<string, number>
  queue_depths?: Record<string, number> | { error: string }
  backup?: { status?: string; note?: string }
}

/**
 * Phase-2 interoception vitals strip: Sara's own health at a glance —
 * failing background tasks (24h), error counts by service, queue depths, and
 * backup status. Read-only; data comes from /api/diagnostics/overview.
 */
const VitalsStrip: React.FC = () => {
  const [ov, setOv] = useState<Overview | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [reporting, setReporting] = useState(false)

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${APP_CONFIG.apiUrl}/api/diagnostics/overview`, { credentials: 'include' })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setOv(await r.json())
      setErr(null)
    } catch (e: any) {
      setErr(e.message || 'failed to load vitals')
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [load])

  const requestReport = async () => {
    setReporting(true)
    try {
      const r = await fetch(`${APP_CONFIG.apiUrl}/api/diagnostics/report`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: 'system health' }),
      })
      const j = await r.json()
      const blob = new Blob([j.markdown || ''], { type: 'text/markdown' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'sara-diagnostics-report.md'
      a.click()
      URL.revokeObjectURL(url)
    } catch { /* noop */ } finally { setReporting(false) }
  }

  const healthy = ov && ov.failing_task_count === 0
  const queues = ov?.queue_depths && !('error' in (ov.queue_depths as any))
    ? (ov.queue_depths as Record<string, number>) : null

  return (
    <div className="assistant-panel rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-teal-300" />
          <span className="text-xs uppercase tracking-wider text-slate-400">Vitals</span>
        </div>
        <button onClick={requestReport} disabled={reporting}
          className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50">
          <FileText className="w-3.5 h-3.5" /> {reporting ? 'compiling…' : 'handoff report'}
        </button>
      </div>

      {err && <div className="text-sm text-rose-300 flex items-center gap-2">
        <AlertTriangle className="w-4 h-4" /> {err}</div>}

      {!err && ov && (
        <>
          {healthy ? (
            <div className="flex items-center gap-2 text-sm text-emerald-300">
              <CheckCircle2 className="w-4 h-4" /> All background tasks healthy (last 24h).
            </div>
          ) : (
            <div className="space-y-1.5">
              {ov.failing_tasks.slice(0, 6).map(t => (
                <div key={t.event_id} className="flex items-start gap-2 rounded-lg bg-rose-500/10 border border-rose-400/20 p-2 text-sm">
                  <AlertTriangle className="w-4 h-4 text-rose-300 mt-0.5 shrink-0" />
                  <div className="min-w-0">
                    <div className="text-slate-100">
                      {t.task_name.split('.').pop()} · <span className="text-rose-300">{t.count_24h}×/24h</span>
                      <span className="text-slate-400"> · {t.error_class}</span>
                    </div>
                    {t.feature && <div className="text-xs text-slate-400 truncate">breaks: {t.feature}</div>}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
            <div className="rounded-lg bg-white/5 border border-white/10 p-3">
              <div className="text-xs text-slate-500">Failing tasks (24h)</div>
              <div className={`text-lg font-semibold mt-0.5 ${healthy ? 'text-emerald-300' : 'text-rose-300'}`}>
                {ov.failing_task_count}
              </div>
            </div>
            {queues && (
              <div className="rounded-lg bg-white/5 border border-white/10 p-3">
                <div className="text-xs text-slate-500">Max queue depth</div>
                <div className="text-lg font-semibold mt-0.5 text-slate-100">
                  {Math.max(0, ...Object.values(queues))}
                </div>
              </div>
            )}
            <div className="rounded-lg bg-white/5 border border-white/10 p-3">
              <div className="text-xs text-slate-500">Error services (24h)</div>
              <div className="text-lg font-semibold mt-0.5 text-slate-100">
                {Object.keys(ov.error_counts_by_service_24h || {}).length}
              </div>
            </div>
            <div className="rounded-lg bg-white/5 border border-white/10 p-3">
              <div className="text-xs text-slate-500">Backup</div>
              <div className="text-sm mt-1 text-amber-300/80 truncate" title={ov.backup?.note}>
                {ov.backup?.status === 'not_configured' ? 'not configured' : (ov.backup?.status ?? '—')}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

export default VitalsStrip
