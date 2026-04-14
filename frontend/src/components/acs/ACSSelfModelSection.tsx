import { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../../config'

interface SelfModelVersion {
  version: number
  content: Record<string, unknown>
  created_at: string
}

function renderValue(value: unknown, depth: number = 0): JSX.Element {
  if (value === null || value === undefined) {
    return <span className="text-gray-500">null</span>
  }
  if (depth > 6) {
    return <span className="text-gray-500 text-xs">{JSON.stringify(value)}</span>
  }
  if (typeof value === 'string') {
    // Top-level strings in lists don't need quotes
    if (depth > 0) return <span className="text-emerald-400">{value}</span>
    return <span className="text-emerald-400">"{value}"</span>
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return <span className="text-amber-400">{String(value)}</span>
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-gray-500">[]</span>
    return (
      <div className={depth > 0 ? 'ml-3' : ''}>
        {value.map((item, i) => (
          <div key={i} className="flex items-start gap-1">
            <span className="text-gray-600 shrink-0">•</span>
            <div className="min-w-0 break-words">{renderValue(item, depth + 1)}</div>
          </div>
        ))}
      </div>
    )
  }
  if (typeof value === 'object') {
    try {
      const entries = Object.entries(value as Record<string, unknown>)
      if (entries.length === 0) return <span className="text-gray-500">{'{}'}</span>
      return (
        <div className={depth > 0 ? 'ml-3' : ''}>
          {entries.map(([k, v]) => (
            <div key={k} className="flex items-start gap-2 py-0.5">
              <span className="text-indigo-400 font-medium shrink-0">{k}:</span>
              <div className="min-w-0 break-words">{renderValue(v, depth + 1)}</div>
            </div>
          ))}
        </div>
      )
    } catch {
      return <span className="text-gray-500">{String(value)}</span>
    }
  }
  return <span className="text-gray-300">{String(value)}</span>
}

export default function ACSSelfModelSection() {
  const [current, setCurrent] = useState<SelfModelVersion | null>(null)
  const [history, setHistory] = useState<SelfModelVersion[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)
  const [showRaw, setShowRaw] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState('')
  const [editError, setEditError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const fetchSelfModel = useCallback(async () => {
    try {
      const [currentRes, historyRes] = await Promise.all([
        fetch(`${APP_CONFIG.apiUrl}/api/acs/self-model`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/api/acs/self-model/history`, { credentials: 'include' }),
      ])
      if (currentRes.ok) {
        const data = await currentRes.json()
        const model = data.model || data
        if (model && typeof model === 'object') {
          const content = model.content && typeof model.content === 'object' ? model.content : model
          setCurrent({
            version: model.version ?? 0,
            content,
            created_at: model.created_at || '',
          })
        }
      }
      if (historyRes.ok) {
        const data = await historyRes.json()
        const items = Array.isArray(data) ? data : data.history || []
        setHistory(items.map((h: Record<string, unknown>) => ({
          version: (h.version as number) ?? 0,
          content: (h.content && typeof h.content === 'object' ? h.content : {}) as Record<string, unknown>,
          created_at: (h.created_at as string) || '',
        })))
      }
      if (!currentRes.ok && !historyRes.ok) {
        setError('Failed to load self-model')
      } else {
        setError(null)
      }
    } catch {
      setError('Failed to load self-model')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchSelfModel() }, [fetchSelfModel])

  const startEditing = () => {
    if (!current) return
    setEditText(JSON.stringify(current.content, null, 2))
    setEditError(null)
    setEditing(true)
    // Editing always works against the live current version, not history view
    setSelectedVersion(null)
  }

  const cancelEditing = () => {
    setEditing(false)
    setEditError(null)
    setEditText('')
  }

  const saveEdit = async () => {
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(editText)
    } catch (e) {
      setEditError(`Invalid JSON: ${(e as Error).message}`)
      return
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      setEditError('Top-level value must be a JSON object')
      return
    }

    setSaving(true)
    setEditError(null)
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/self-model`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: parsed }),
      })
      if (!res.ok) {
        const errBody = await res.text().catch(() => '')
        throw new Error(`Save failed (${res.status}): ${errBody.slice(0, 200)}`)
      }
      setEditing(false)
      setEditText('')
      await fetchSelfModel()
    } catch (e) {
      setEditError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="text-gray-400 p-4">Loading...</div>
  if (error && !current) return <div className="text-red-400 p-4">{error}</div>

  const displayModel = selectedVersion !== null
    ? history.find(h => h.version === selectedVersion)
    : current

  if (!displayModel) {
    return (
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-8 text-center">
        <p className="text-gray-400">No self-model generated yet.</p>
        <p className="text-gray-500 text-sm mt-1">The ACS builds a self-model over time through autonomous sessions.</p>
      </div>
    )
  }

  const isEditableVersion = !editing && current && displayModel.version === current.version

  return (
    <div className="space-y-4">
      {/* Header with version info */}
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-gray-400">
          Version {displayModel.version}
          {displayModel.created_at ? ` — ${new Date(displayModel.created_at).toLocaleString()}` : ''}
          {editing && <span className="ml-2 text-amber-400">(editing)</span>}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {!editing && (
            <button onClick={() => setShowRaw(r => !r)}
              className="text-sm text-indigo-400 hover:text-indigo-300 transition-colors">
              {showRaw ? 'Structured view' : 'Raw JSON'}
            </button>
          )}
          {isEditableVersion && (
            <button onClick={startEditing}
              className="text-sm px-2.5 py-1 rounded border border-gray-700 text-gray-300 hover:text-white hover:border-indigo-500/60 hover:bg-indigo-900/20 transition-colors"
              title="Edit the current self-model and save as a new version">
              Edit
            </button>
          )}
        </div>
      </div>

      {/* Content / Editor */}
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
        {editing ? (
          <div className="space-y-3">
            <p className="text-xs text-gray-500">
              Edit the JSON directly. Saving creates a new version. Sara may merge over the top of this on her next reflection cycle, so manual edits are a course-correction, not permanent override.
            </p>
            <textarea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              spellCheck={false}
              className="w-full h-96 bg-gray-900 text-gray-200 text-xs font-mono rounded border border-gray-700 p-3 focus:outline-none focus:border-indigo-500/60 resize-y"
            />
            {editError && (
              <div className="text-xs text-red-400 bg-red-900/20 border border-red-800/40 rounded p-2 whitespace-pre-wrap">
                {editError}
              </div>
            )}
            <div className="flex items-center justify-end gap-2">
              <button
                onClick={cancelEditing}
                disabled={saving}
                className="text-sm px-3 py-1 rounded border border-gray-700 text-gray-300 hover:text-white hover:border-gray-500 transition-colors disabled:opacity-50">
                Cancel
              </button>
              <button
                onClick={saveEdit}
                disabled={saving}
                className="text-sm px-3 py-1 rounded bg-indigo-600 text-white hover:bg-indigo-500 transition-colors disabled:opacity-50">
                {saving ? 'Saving…' : 'Save as new version'}
              </button>
            </div>
          </div>
        ) : showRaw ? (
          <pre className="text-xs text-gray-300 overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(displayModel.content, null, 2)}
          </pre>
        ) : (
          <div className="text-sm">
            {renderValue(displayModel.content)}
          </div>
        )}
      </div>

      {/* Version history timeline */}
      {history.length > 1 && (
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Version History</h3>
          <div className="space-y-1">
            {history.map(v => (
              <button
                key={v.version}
                onClick={() => setSelectedVersion(selectedVersion === v.version ? null : v.version)}
                className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                  (selectedVersion === v.version || (selectedVersion === null && current?.version === v.version))
                    ? 'bg-indigo-900/30 text-indigo-400 border border-indigo-500/30'
                    : 'bg-gray-800/30 text-gray-400 hover:bg-gray-700/50 border border-transparent'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span>Version {v.version}</span>
                  <span className="text-xs text-gray-500">{v.created_at ? new Date(v.created_at).toLocaleString() : ''}</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
