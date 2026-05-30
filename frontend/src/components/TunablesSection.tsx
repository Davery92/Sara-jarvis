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
    <div className="bg-gray-800/50 border border-gray-700 rounded p-3 mb-2">
      <div className="flex items-baseline justify-between gap-3 mb-1">
        <div className="flex-1 min-w-0">
          <div className="text-sm text-white font-medium">
            {tunable.display_name}
            {!isDefault && (
              <span className="ml-2 text-[10px] text-amber-400 uppercase tracking-wider">modified</span>
            )}
          </div>
          {tunable.description && (
            <div className="text-xs text-gray-500 mt-0.5">{tunable.description}</div>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 mt-2">
        {tunable.value_type === 'string' ? (
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="flex-1 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-white"
          />
        ) : tunable.value_type === 'bool' ? (
          <select
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="flex-1 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-white"
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
            className="w-32 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-white font-mono"
          />
        )}
        {tunable.unit && (
          <span className="text-xs text-gray-500">{tunable.unit}</span>
        )}
        <button
          onClick={handleSave}
          disabled={!dirty || saving}
          className="text-xs px-2 py-1 text-white bg-indigo-600 rounded disabled:opacity-30 hover:bg-indigo-500"
        >
          Save
        </button>
        {!isDefault && (
          <button
            onClick={onReset}
            disabled={saving}
            className="text-xs px-2 py-1 text-gray-300 bg-gray-800 border border-gray-700 rounded hover:bg-gray-700"
            title={`Reset to default (${JSON.stringify(tunable.default_value)})`}
          >
            Reset
          </button>
        )}
      </div>
      {(tunable.min_value !== null || tunable.max_value !== null) && (
        <div className="text-[10px] text-gray-600 mt-1 font-mono">
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
    <div className="mb-6 bg-card border border-card rounded-md p-6">
      <div className="mb-4">
        <h2 className="text-lg font-medium text-white mb-1">Behavior Tunables</h2>
        <p className="text-sm text-gray-400">
          Edit how Sara behaves: notification cooldowns, quiet hours, ACS deliberation thresholds, morning brief tone & length. Changes take effect within ~60 seconds.
        </p>
      </div>

      {isLoading && <p className="text-sm text-gray-500">Loading tunables…</p>}
      {error && <p className="text-sm text-red-300">Failed to load tunables.</p>}

      {grouped.map(([category, tunables]) => (
        <div key={category} className="mb-5">
          <h3 className="text-xs uppercase tracking-wider text-gray-500 mb-2">
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
