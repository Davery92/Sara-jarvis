import { useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient, TunableSetting } from '../api/client'
import CalendarOwnershipSection from '../components/CalendarOwnershipSection'

// The Dial (Arc 6.3, work-order item 3): one page, few controls — the
// things only David sets by hand. Everything else lives in code (Identity)
// or moves through dreaming (Learned, read-only on Settings' Tunables
// list). See the settings-mapping artifact for the full 87-key breakdown.
const DIAL_KEYS = ['notification.quiet_hours.start', 'notification.quiet_hours.end', 'system.ungag.all']

function QuietHours({ tunables, onSave, saving }: {
  tunables: TunableSetting[]
  onSave: (key: string, value: number) => void
  saving: boolean
}) {
  const start = tunables.find((t) => t.key === 'notification.quiet_hours.start')
  const end = tunables.find((t) => t.key === 'notification.quiet_hours.end')
  if (!start || !end) return null

  const hourOptions = Array.from({ length: 24 }, (_, h) => h)
  const fmt = (h: number) => {
    const period = h < 12 ? 'AM' : 'PM'
    const display = h % 12 === 0 ? 12 : h % 12
    return `${display}:00 ${period}`
  }

  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <div className="text-[15px] text-slate-200">Quiet hours</div>
      <p className="text-xs text-slate-500 mt-0.5 mb-3">
        No push notifications between these hours, regardless of priority learning.
      </p>
      <div className="flex items-center gap-3">
        <select
          value={start.value}
          disabled={saving}
          onChange={(e) => onSave('notification.quiet_hours.start', parseInt(e.target.value, 10))}
          className="bg-white/[0.04] border border-white/10 rounded-xl focus:border-teal-300/30 outline-none px-3 py-1.5 text-sm text-white"
        >
          {hourOptions.map((h) => <option key={h} value={h}>{fmt(h)}</option>)}
        </select>
        <span className="text-slate-500 text-sm">until</span>
        <select
          value={end.value}
          disabled={saving}
          onChange={(e) => onSave('notification.quiet_hours.end', parseInt(e.target.value, 10))}
          className="bg-white/[0.04] border border-white/10 rounded-xl focus:border-teal-300/30 outline-none px-3 py-1.5 text-sm text-white"
        >
          {hourOptions.map((h) => <option key={h} value={h}>{fmt(h)}</option>)}
        </select>
      </div>
    </div>
  )
}

function UngagSwitch({ tunables, onSave, saving }: {
  tunables: TunableSetting[]
  onSave: (key: string, value: boolean) => void
  saving: boolean
}) {
  const ungag = tunables.find((t) => t.key === 'system.ungag.all')
  if (!ungag) return null
  const on = ungag.value === true

  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4 flex items-center justify-between gap-4">
      <div>
        <div className="text-[15px] text-slate-200">Ungag everything</div>
        <p className="text-xs text-slate-500 mt-0.5 max-w-md">
          The master override on notification gating. Off means the normal learned
          buzz-decisions and daily budget apply. On means every gated notification
          gets through — use it if Sara's being too quiet, not as a permanent setting.
        </p>
      </div>
      <button
        onClick={() => onSave('system.ungag.all', !on)}
        disabled={saving}
        role="switch"
        aria-checked={on}
        className={`relative shrink-0 w-12 h-7 rounded-full transition-colors ${on ? 'bg-teal-400/90' : 'bg-white/10'} disabled:opacity-50`}
      >
        <span className={`absolute top-1 left-1 w-5 h-5 rounded-full bg-slate-950 transition-transform ${on ? 'translate-x-5' : ''}`} />
      </button>
    </div>
  )
}

export default function Dial() {
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['tunables'],
    queryFn: () => apiClient.listTunables(),
  })

  const updateMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) =>
      apiClient.updateTunable(key, value),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tunables'] }),
    onError: (err: any) => {
      const detail = err?.response?.data?.detail || err.message
      alert(`Save failed: ${detail}`)
    },
  })

  const dialTunables = useMemo(
    () => (data || []).filter((t) => DIAL_KEYS.includes(t.key)),
    [data]
  )
  const learnedCount = useMemo(
    () => (data || []).filter((t) => !t.editable).length,
    [data]
  )

  return (
    <div className="flex-1 overflow-y-auto min-h-0">
      <div className="max-w-2xl mx-auto px-6 py-10">
        <h1 className="text-2xl font-semibold text-slate-100">The Dial</h1>
        <p className="text-sm text-slate-400 mt-2 max-w-lg">
          Everything Sara does that's actually your call, in one place. Her style and
          invariants are fixed in code. Everything else — anti-nag limits, ACS
          thresholds, brief tone — tunes itself through dreaming; you can see the
          current values on Settings, but they aren't edited by hand.
        </p>

        {isLoading && <p className="text-sm text-slate-500 mt-8">Loading…</p>}
        {error && <p className="text-sm text-slate-500 mt-8">Couldn't load the Dial's settings.</p>}

        {data && (
          <div className="mt-8 space-y-4">
            <QuietHours
              tunables={dialTunables}
              saving={updateMutation.isPending}
              onSave={(key, value) => updateMutation.mutate({ key, value })}
            />
            <UngagSwitch
              tunables={dialTunables}
              saving={updateMutation.isPending}
              onSave={(key, value) => updateMutation.mutate({ key, value })}
            />
          </div>
        )}

        <CalendarOwnershipSection />

        <div className="mt-12 pt-6 border-t border-white/10">
          <p className="text-xs text-slate-500">
            {learnedCount} more settings tune themselves through dreaming — see the full
            list with current values on{' '}
            <a href="/settings" className="text-teal-300 hover:underline">Settings</a>.
          </p>
        </div>
      </div>
    </div>
  )
}
