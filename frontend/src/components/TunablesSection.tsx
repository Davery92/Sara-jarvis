import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient, TunableSetting } from '../api/client'

const CATEGORY_LABELS: Record<string, string> = {
  notifications: 'Notifications & Quiet Hours',
  acs: 'Autonomous Cognition Thresholds',
  morning_brief: 'Morning Brief',
}

function TunableRow({ tunable, onSave, onReset, saving }: {
  tunable: TunableSetting
  onSave: (value: any) => void
  onReset: () => void
  saving: boolean
}) {
  const [draft, setDraft] = useState<string>(String(tunable.value ?? ''))
  const dirty = draft !== String(tunable.value ?? '')
  const isDefault =
    JSON.stringify(tunable.value) === JSON.stringify(tunable.default_value)

  const handleSave = () => {
    let parsed: any = draft
    if (tunable.value_type === 'int') parsed = parseInt(draft, 10)
    else if (tunable.value_type === 'float') parsed = parseFloat(draft)
    else if (tunable.value_type === 'bool') parsed = draft === 'true'
    onSave(parsed)
  }

  const inputType =
    tunable.value_type === 'int' || tunable.value_type === 'float'
      ? 'number'
      : 'text'

  const step = tunable.value_type === 'float' ? '0.1' : '1'

  return (
    <div className="rounded-lg px-3 py-2.5 hover:bg-white/[0.04] transition-colors">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-[15px] text-slate-200">
            {tunable.display_name}
            {!isDefault && (
              <span className="ml-2 text-[10px] text-amber-400 uppercase tracking-wider">modified</span>
            )}
          </div>
          {tunable.description && (
            <div className="text-xs text-slate-500 mt-0.5">{tunable.description}</div>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 mt-2">
        {tunable.value_type === 'string' ? (
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="flex-1 bg-white/[0.04] border border-white/10 rounded-xl focus:border-teal-300/30 outline-none px-3 py-1.5 text-sm text-white"
          />
        ) : tunable.value_type === 'bool' ? (
          <select
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="flex-1 bg-white/[0.04] border border-white/10 rounded-xl focus:border-teal-300/30 outline-none px-3 py-1.5 text-sm text-white"
          >
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        ) : (
          <input
            type={inputType}
            step={step}
            min={tunable.min_value ?? undefined}
            max={tunable.max_value ?? undefined}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-32 bg-white/[0.04] border border-white/10 rounded-xl focus:border-teal-300/30 outline-none px-3 py-1.5 text-sm text-white font-mono"
          />
        )}
        {tunable.unit && (
          <span className="text-xs text-slate-500">{tunable.unit}</span>
        )}
        <button
          onClick={handleSave}
          disabled={!dirty || saving}
          className="rounded-xl border border-white/10 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/[0.06] hover:text-white disabled:opacity-30"
        >
          Save
        </button>
        {!isDefault && (
          <button
            onClick={onReset}
            disabled={saving}
            className="text-xs text-slate-500 hover:text-teal-300 transition-colors disabled:opacity-40 px-1.5 py-1.5"
            title={`Reset to default (${JSON.stringify(tunable.default_value)})`}
          >
            Reset
          </button>
        )}
      </div>
      {(tunable.min_value !== null || tunable.max_value !== null) && (
        <div className="text-[10px] text-slate-600 mt-1 font-mono">
          {tunable.min_value !== null && `min ${tunable.min_value}`}
          {tunable.min_value !== null && tunable.max_value !== null && ' · '}
          {tunable.max_value !== null && `max ${tunable.max_value}`}
          {' · default '}{JSON.stringify(tunable.default_value)}
        </div>
      )}
    </div>
  )
}

export default function TunablesSection() {
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['tunables'],
    queryFn: () => apiClient.listTunables(),
  })

  const updateMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: any }) =>
      apiClient.updateTunable(key, value),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tunables'] }),
    onError: (err: any) => {
      const detail = err?.response?.data?.detail || err.message
      alert(`Save failed: ${detail}`)
    },
  })

  const resetMutation = useMutation({
    mutationFn: (key: string) => apiClient.resetTunable(key),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tunables'] }),
  })

  const grouped = useMemo(() => {
    if (!data) return []
    const byCat = new Map<string, TunableSetting[]>()
    for (const t of data) {
      if (!byCat.has(t.category)) byCat.set(t.category, [])
      byCat.get(t.category)!.push(t)
    }
    return Array.from(byCat.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [data])

  return (
    <div>
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
          Behavior tunables
        </h2>
      </div>

      {isLoading && <p className="text-sm text-slate-500">Loading tunables…</p>}
      {error && <p className="text-sm text-slate-500">Failed to load tunables.</p>}

      {grouped.map(([category, tunables]) => (
        <div key={category} className="mb-6">
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 mb-1.5">
            {CATEGORY_LABELS[category] ?? category}
          </h3>
          {tunables.map((t) => (
            <TunableRow
              key={t.key}
              tunable={t}
              saving={updateMutation.isPending || resetMutation.isPending}
              onSave={(value) => updateMutation.mutate({ key: t.key, value })}
              onReset={() => resetMutation.mutate(t.key)}
            />
          ))}
        </div>
      ))}
    </div>
  )
}
