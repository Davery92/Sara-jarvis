import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient, ScheduledJob, SchedulePatch } from '../api/client'

const CRON_PRESETS: { label: string; value: string }[] = [
  { label: 'Every minute', value: '* * * * *' },
  { label: 'Every 5 minutes', value: '*/5 * * * *' },
  { label: 'Every 15 minutes', value: '*/15 * * * *' },
  { label: 'Every 30 minutes', value: '*/30 * * * *' },
  { label: 'Hourly (top of hour)', value: '0 * * * *' },
  { label: 'Daily 5 AM', value: '0 5 * * *' },
  { label: 'Daily 6 AM', value: '0 6 * * *' },
  { label: 'Daily 7 AM', value: '0 7 * * *' },
  { label: 'Daily 9 AM', value: '0 9 * * *' },
  { label: 'Daily 11 PM', value: '0 23 * * *' },
  { label: 'Daily midnight', value: '0 0 * * *' },
  { label: 'Sundays 3 AM', value: '0 3 * * 0' },
]

function formatRelative(iso: string | null): string {
  if (!iso) return 'Never'
  const then = new Date(iso).getTime()
  const now = Date.now()
  const diff = Math.max(0, now - then)
  const sec = Math.floor(diff / 1000)
  if (sec < 60) return `${sec}s ago`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.floor(hr / 24)
  return `${day}d ago`
}

function StatusDot({ status }: { status: string | null }) {
  const color =
    status === 'success' ? 'bg-green-500'
      : status === 'error' ? 'bg-red-500'
        : 'bg-gray-600'
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} aria-label={status || 'never run'} />
}

function EditModal({
  job,
  onClose,
  onSave,
  saving,
  saveError,
}: {
  job: ScheduledJob
  onClose: () => void
  onSave: (patch: SchedulePatch) => void
  saving: boolean
  saveError: string | null
}) {
  const [kind, setKind] = useState<'cron' | 'interval'>(job.schedule_kind)
  const [cronExpr, setCronExpr] = useState(job.cron_expr ?? '')
  const [intervalSec, setIntervalSec] = useState(job.interval_seconds ?? 60)
  const [enabled, setEnabled] = useState(job.enabled)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const patch: SchedulePatch = { enabled, schedule_kind: kind }
    if (kind === 'cron') {
      patch.cron_expr = cronExpr.trim()
      patch.interval_seconds = null
    } else {
      patch.interval_seconds = Number(intervalSec)
      patch.cron_expr = null
    }
    onSave(patch)
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
      <form
        onSubmit={submit}
        className="bg-gray-900 border border-gray-700 rounded-xl p-6 max-w-lg w-full space-y-4 max-h-[90vh] overflow-y-auto"
      >
        <div>
          <h3 className="text-lg font-semibold text-white">{job.display_name}</h3>
          <p className="text-xs text-gray-500 font-mono">{job.task_name}</p>
          {job.description && (
            <p className="text-sm text-gray-400 mt-2">{job.description}</p>
          )}
        </div>

        {/* Enabled toggle */}
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="w-4 h-4"
          />
          <span className="text-sm text-gray-200">Enabled</span>
        </label>

        {/* Schedule kind */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">Schedule kind</label>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setKind('cron')}
              className={`px-3 py-1 rounded text-sm ${
                kind === 'cron'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-800 text-gray-300 border border-gray-700'
              }`}
            >
              Cron
            </button>
            <button
              type="button"
              onClick={() => setKind('interval')}
              className={`px-3 py-1 rounded text-sm ${
                kind === 'interval'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-800 text-gray-300 border border-gray-700'
              }`}
            >
              Interval
            </button>
          </div>
        </div>

        {/* Cron editor */}
        {kind === 'cron' && (
          <div className="space-y-2">
            <label className="block text-xs text-gray-400">
              Cron expression (5 fields: minute hour day month weekday)
            </label>
            <input
              type="text"
              value={cronExpr}
              onChange={(e) => setCronExpr(e.target.value)}
              placeholder="0 6 * * *"
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white font-mono text-sm"
            />
            <select
              onChange={(e) => e.target.value && setCronExpr(e.target.value)}
              value=""
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-gray-300 text-sm"
            >
              <option value="">— Pick a preset —</option>
              {CRON_PRESETS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}  ({p.value})
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-500">Times interpreted in {job.timezone}.</p>
          </div>
        )}

        {/* Interval editor */}
        {kind === 'interval' && (
          <div className="space-y-2">
            <label className="block text-xs text-gray-400">Interval (seconds)</label>
            <input
              type="number"
              min={1}
              value={intervalSec}
              onChange={(e) => setIntervalSec(Number(e.target.value))}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white font-mono text-sm"
            />
            <p className="text-xs text-gray-500">
              {intervalSec >= 3600
                ? `≈ ${(intervalSec / 3600).toFixed(2)} hours`
                : intervalSec >= 60
                  ? `≈ ${(intervalSec / 60).toFixed(1)} minutes`
                  : `${intervalSec} seconds`}
            </p>
          </div>
        )}

        {saveError && (
          <p className="text-sm text-red-300 bg-red-950/40 border border-red-800/60 rounded p-2">
            {saveError}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="px-4 py-2 text-sm text-gray-300 bg-gray-800 border border-gray-700 rounded hover:bg-gray-700"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="px-4 py-2 text-sm text-white bg-indigo-600 rounded hover:bg-indigo-500 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default function SchedulesSection() {
  const queryClient = useQueryClient()
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [showSystem, setShowSystem] = useState(false)
  const [expandedKey, setExpandedKey] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [runNowMessage, setRunNowMessage] = useState<string | null>(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['schedules'],
    queryFn: () => apiClient.listSchedules(),
    refetchInterval: 15000,
  })

  const updateMutation = useMutation({
    mutationFn: ({ key, patch }: { key: string; patch: SchedulePatch }) =>
      apiClient.updateSchedule(key, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] })
      setEditingKey(null)
      setSaveError(null)
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      setSaveError(typeof detail === 'string' ? detail : JSON.stringify(detail) || err.message)
    },
  })

  const runNowMutation = useMutation({
    mutationFn: (key: string) => apiClient.runScheduleNow(key),
    onSuccess: (res, key) => {
      setRunNowMessage(`Dispatched ${key} (task ${res.task_id.slice(0, 8)}…)`)
      setTimeout(() => setRunNowMessage(null), 5000)
    },
    onError: (err: any, key) => {
      const detail = err?.response?.data?.detail || err.message
      setRunNowMessage(`Failed to dispatch ${key}: ${detail}`)
      setTimeout(() => setRunNowMessage(null), 7000)
    },
  })

  const { grouped, systemHiddenCount } = useMemo(() => {
    if (!data) return { grouped: [], systemHiddenCount: 0 }
    const q = filter.trim().toLowerCase()
    const matchesFilter = (j: ScheduledJob) =>
      !q ||
      j.key.toLowerCase().includes(q) ||
      j.display_name.toLowerCase().includes(q) ||
      j.category.toLowerCase().includes(q) ||
      (j.description ?? '').toLowerCase().includes(q)

    let hiddenSystem = 0
    const visible: ScheduledJob[] = []
    for (const j of data) {
      if (!matchesFilter(j)) continue
      if (j.visibility === 'system' && !showSystem && !q) {
        hiddenSystem += 1
        continue
      }
      visible.push(j)
    }
    const byCat = new Map<string, ScheduledJob[]>()
    for (const j of visible) {
      if (!byCat.has(j.category)) byCat.set(j.category, [])
      byCat.get(j.category)!.push(j)
    }
    return {
      grouped: Array.from(byCat.entries()).sort(([a], [b]) => a.localeCompare(b)),
      systemHiddenCount: hiddenSystem,
    }
  }, [data, filter, showSystem])

  const editingJob = data?.find((j) => j.key === editingKey) ?? null

  return (
    <div className="mb-6 bg-card border border-card rounded-xl p-6">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 className="text-lg font-medium text-white mb-1">Scheduled Jobs</h2>
          <p className="text-sm text-gray-400">
            Edit when Sara's background tasks run. Changes take effect within ~60 seconds (next beat reload).
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="text-xs text-gray-400 hover:text-white px-2 py-1 border border-gray-700 rounded"
        >
          Refresh
        </button>
      </div>

      {runNowMessage && (
        <div className="mb-3 text-sm text-indigo-200 bg-indigo-950/40 border border-indigo-800/60 rounded p-2">
          {runNowMessage}
        </div>
      )}

      <input
        type="text"
        placeholder="Filter by name, key, category, or description…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="w-full mb-3 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white"
      />

      {isLoading && <p className="text-sm text-gray-500">Loading schedules…</p>}
      {error && <p className="text-sm text-red-300">Failed to load schedules.</p>}

      {systemHiddenCount > 0 && !showSystem && (
        <button
          onClick={() => setShowSystem(true)}
          className="mb-3 text-xs text-gray-400 hover:text-white underline"
        >
          Show {systemHiddenCount} internal/plumbing job{systemHiddenCount !== 1 ? 's' : ''} (watchers, pollers, heartbeats)
        </button>
      )}
      {showSystem && (
        <button
          onClick={() => setShowSystem(false)}
          className="mb-3 text-xs text-gray-400 hover:text-white underline"
        >
          Hide internal jobs
        </button>
      )}

      {grouped.map(([category, jobs]) => (
        <div key={category} className="mb-5">
          <h3 className="text-xs uppercase tracking-wider text-gray-500 mb-2">{category}</h3>
          <div className="space-y-1">
            {jobs.map((job) => {
              const isExpanded = expandedKey === job.key
              return (
                <div
                  key={job.key}
                  className={`rounded border ${
                    job.enabled
                      ? 'bg-gray-800/50 border-gray-700'
                      : 'bg-gray-900/50 border-gray-800 opacity-60'
                  }`}
                >
                  <div className="flex items-center justify-between gap-3 px-3 py-2">
                    <button
                      onClick={() => setExpandedKey(isExpanded ? null : job.key)}
                      className="flex-1 min-w-0 text-left"
                    >
                      <div className="flex items-center gap-2">
                        <StatusDot status={job.last_status} />
                        <span className="text-sm text-white truncate">{job.display_name}</span>
                        {job.visibility === 'system' && (
                          <span className="text-[10px] px-1.5 py-0.5 bg-gray-800 text-gray-500 border border-gray-700 rounded uppercase tracking-wide">
                            system
                          </span>
                        )}
                        {!job.enabled && (
                          <span className="text-xs px-1.5 py-0.5 bg-gray-700 text-gray-300 rounded">
                            disabled
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-gray-500 truncate">
                        {job.human_readable} · last run {formatRelative(job.last_run_at)}
                        {job.last_error && (
                          <span className="text-red-400"> · err: {job.last_error.slice(0, 60)}</span>
                        )}
                      </div>
                    </button>
                    <div className="flex gap-1 shrink-0">
                      <button
                        onClick={() => runNowMutation.mutate(job.key)}
                        disabled={runNowMutation.isPending}
                        className="text-xs px-2 py-1 text-indigo-200 bg-indigo-950/40 border border-indigo-800/60 rounded hover:bg-indigo-900/40"
                        title="Dispatch this task right now, bypassing the schedule"
                      >
                        Run now
                      </button>
                      <button
                        onClick={() => {
                          setSaveError(null)
                          setEditingKey(job.key)
                        }}
                        disabled={!job.editable}
                        className="text-xs px-2 py-1 text-gray-300 bg-gray-800 border border-gray-700 rounded hover:bg-gray-700 disabled:opacity-40"
                      >
                        Edit
                      </button>
                    </div>
                  </div>
                  {isExpanded && (
                    <div className="px-3 pb-3 pt-1 text-xs text-gray-400 border-t border-gray-800">
                      {job.description ? (
                        <p className="mb-1">{job.description}</p>
                      ) : (
                        <p className="italic text-gray-600 mb-1">No description.</p>
                      )}
                      <p className="font-mono text-gray-600">
                        {job.task_name}
                        {job.queue && <> · queue: {job.queue}</>}
                      </p>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}

      {editingJob && (
        <EditModal
          job={editingJob}
          saving={updateMutation.isPending}
          saveError={saveError}
          onClose={() => {
            setEditingKey(null)
            setSaveError(null)
          }}
          onSave={(patch) => updateMutation.mutate({ key: editingJob.key, patch })}
        />
      )}
    </div>
  )
}
