import React, { useState, useEffect, useCallback } from 'react'
import { APP_CONFIG } from '../config'

// --- Types ---

interface PKGFact {
  type: string
  pkg_id: string
  confidence: number
  source: string
  first_learned: string
  last_confirmed: string
  times_confirmed: number
  [key: string]: any
}

interface PKGStats {
  total: number
  by_type: Record<string, number>
  confidence_distribution: {
    high: number
    medium: number
    low: number
  }
}

interface PKGSummary {
  summary: string
  total: number
  stats: PKGStats
  highlights: Array<{ type: string; text: string; confidence: number }>
}

const CATEGORIES = ['All', 'Person', 'Preference', 'Routine', 'Goal', 'Interest', 'Health', 'Place', 'Fact'] as const
type Category = (typeof CATEGORIES)[number]

const CATEGORY_ICONS: Record<string, string> = {
  All: 'hub',
  Person: 'people',
  Preference: 'favorite',
  Routine: 'schedule',
  Goal: 'flag',
  Interest: 'interests',
  Health: 'monitor_heart',
  Place: 'place',
  Fact: 'lightbulb',
}

// --- Helpers ---

function confidenceColor(c: number): string {
  if (c >= 0.8) return 'text-green-400'
  if (c >= 0.5) return 'text-yellow-400'
  return 'text-red-400'
}

function confidenceBg(c: number): string {
  if (c >= 0.8) return 'bg-green-500/20 border-green-500/30'
  if (c >= 0.5) return 'bg-yellow-500/20 border-yellow-500/30'
  return 'bg-red-500/20 border-red-500/30'
}

function confidenceLabel(c: number): string {
  if (c >= 0.8) return 'High'
  if (c >= 0.5) return 'Medium'
  return 'Low'
}

function formatDate(iso: string): string {
  if (!iso) return 'Unknown'
  try {
    return new Date(iso).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  } catch {
    return iso
  }
}

function getFactDisplayName(fact: PKGFact): string {
  const t = fact.type
  if (t === 'Person') return fact.name || 'Unknown Person'
  if (t === 'Preference') return `${fact.domain || ''}: ${fact.key || ''} = ${fact.value || ''}`
  if (t === 'Routine') return fact.activity || 'Unknown Routine'
  if (t === 'Goal') return fact.description || 'Unknown Goal'
  if (t === 'Interest') return fact.topic || 'Unknown Interest'
  if (t === 'Health') return `${fact.metric || ''}: ${fact.current_value || fact.value || ''}`
  if (t === 'Place') return `${fact.name || 'Unknown'} (${fact.place_type || fact.type || ''})`
  if (t === 'Fact') return `${fact.subject || ''} ${fact.predicate || ''} ${fact.object || ''}`
  return fact.name || fact.topic || fact.description || JSON.stringify(fact).slice(0, 60)
}

function getFactProperties(fact: PKGFact): Array<{ key: string; value: string }> {
  const skip = new Set([
    'type', 'pkg_id', 'confidence', 'source', 'first_learned', 'last_confirmed',
    'times_confirmed', 'version', 'superseded_by', 'dedup_key',
  ])
  return Object.entries(fact)
    .filter(([k, v]) => !skip.has(k) && v != null && v !== '')
    .map(([k, v]) => ({ key: k.replace(/_/g, ' '), value: String(v) }))
}

// --- API helpers ---

async function apiFetch(path: string, options?: RequestInit) {
  const res = await fetch(`${APP_CONFIG.apiUrl}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

// --- Component ---

export default function PersonalKnowledge() {
  const [activeCategory, setActiveCategory] = useState<Category>('All')
  const [facts, setFacts] = useState<PKGFact[]>([])
  const [stats, setStats] = useState<PKGStats | null>(null)
  const [summary, setSummary] = useState<PKGSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValues, setEditValues] = useState<Record<string, string>>({})
  const [showAddModal, setShowAddModal] = useState(false)
  const [addType, setAddType] = useState<string>('Fact')
  const [addProps, setAddProps] = useState<Record<string, string>>({})
  const [addConfidence, setAddConfidence] = useState(0.9)
  const [reextractLoading, setReextractLoading] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)

  const showToast = useCallback((msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }, [])

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const category = activeCategory === 'All' ? undefined : activeCategory
      const params = new URLSearchParams()
      if (category) params.set('category', category)
      if (searchQuery.trim()) params.set('search', searchQuery.trim())
      params.set('limit', '100')

      const [browseData, statsData, summaryData] = await Promise.all([
        apiFetch(`/api/pkg/browse?${params}`),
        apiFetch('/api/pkg/stats'),
        apiFetch('/api/pkg/summary'),
      ])

      setFacts(browseData.facts || [])
      setStats(statsData)
      setSummary(summaryData)
    } catch (err) {
      console.error('Failed to load PKG data:', err)
    } finally {
      setLoading(false)
    }
  }, [activeCategory, searchQuery])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleDelete = async (pkgId: string) => {
    try {
      await apiFetch(`/api/pkg/${pkgId}`, { method: 'DELETE' })
      showToast('Fact deleted')
      setDeleteConfirmId(null)
      setExpandedId(null)
      loadData()
    } catch (err) {
      showToast('Failed to delete fact')
    }
  }

  const handleSaveEdit = async (pkgId: string) => {
    try {
      const updates: any = {}
      const confStr = editValues['__confidence']
      if (confStr !== undefined) {
        const parsed = parseFloat(confStr)
        if (!isNaN(parsed)) updates.confidence = Math.min(Math.max(parsed, 0), 1)
      }
      const props: Record<string, string> = {}
      for (const [k, v] of Object.entries(editValues)) {
        if (k !== '__confidence') props[k] = v
      }
      if (Object.keys(props).length > 0) updates.properties = props

      await apiFetch(`/api/pkg/${pkgId}`, {
        method: 'PATCH',
        body: JSON.stringify(updates),
      })
      showToast('Fact updated')
      setEditingId(null)
      setEditValues({})
      loadData()
    } catch (err) {
      showToast('Failed to update fact')
    }
  }

  const handleAdd = async () => {
    if (Object.keys(addProps).length === 0) {
      showToast('Add at least one property')
      return
    }
    try {
      await apiFetch('/api/pkg/node', {
        method: 'POST',
        body: JSON.stringify({
          fact_type: addType,
          properties: addProps,
          confidence: addConfidence,
        }),
      })
      showToast('Fact added')
      setShowAddModal(false)
      setAddProps({})
      loadData()
    } catch (err) {
      showToast('Failed to add fact')
    }
  }

  const handleReextract = async () => {
    setReextractLoading(true)
    try {
      await apiFetch('/api/pkg/reextract', { method: 'POST' })
      showToast('Re-extraction queued -- new facts will appear shortly')
    } catch (err) {
      showToast('Failed to queue re-extraction')
    } finally {
      setReextractLoading(false)
    }
  }

  const startEditing = (fact: PKGFact) => {
    setEditingId(fact.pkg_id)
    const vals: Record<string, string> = { __confidence: String(fact.confidence) }
    for (const { key, value } of getFactProperties(fact)) {
      vals[key.replace(/ /g, '_')] = value
    }
    setEditValues(vals)
  }

  // Property templates for add form
  const propTemplates: Record<string, string[]> = {
    Person: ['name', 'relationship_to_david', 'notes'],
    Preference: ['domain', 'key', 'value', 'strength'],
    Routine: ['activity', 'typical_time', 'day_of_week', 'frequency'],
    Goal: ['description', 'status', 'deadline'],
    Interest: ['topic', 'depth', 'notes'],
    Health: ['metric', 'current_value', 'trend'],
    Place: ['name', 'place_type', 'significance', 'address'],
    Fact: ['subject', 'predicate', 'object', 'category'],
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-teal-600 text-white px-4 py-2 rounded-lg shadow-lg text-sm animate-pulse">
          {toast}
        </div>
      )}

      {/* Header */}
      <div className="flex-shrink-0 mb-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-2xl font-bold text-white flex items-center gap-2">
            <span className="material-icons text-teal-400">psychology</span>
            Personal Knowledge
          </h2>
          <div className="flex items-center gap-2">
            <button
              onClick={handleReextract}
              disabled={reextractLoading}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 border border-purple-500/30 text-sm transition-colors disabled:opacity-50"
            >
              <span className="material-icons text-sm">{reextractLoading ? 'hourglass_top' : 'auto_fix_high'}</span>
              {reextractLoading ? 'Extracting...' : 'Re-extract'}
            </button>
            <button
              onClick={() => setShowAddModal(true)}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-teal-500/20 hover:bg-teal-500/30 text-teal-300 border border-teal-500/30 text-sm transition-colors"
            >
              <span className="material-icons text-sm">add</span>
              Add Fact
            </button>
          </div>
        </div>

        {/* Summary bar */}
        {summary && (
          <div className="bg-gray-800/50 border border-gray-700/50 rounded-xl p-4 mb-4">
            <p className="text-gray-300 text-sm">{summary.summary}</p>
            {summary.highlights.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {summary.highlights.slice(0, 6).map((h, i) => (
                  <span
                    key={i}
                    className={`text-xs px-2 py-1 rounded-full border ${confidenceBg(h.confidence)}`}
                  >
                    <span className={confidenceColor(h.confidence)}>{h.text}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Search + Category tabs */}
        <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-center">
          <div className="relative flex-1 max-w-md">
            <span className="material-icons absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-lg">search</span>
            <input
              type="text"
              placeholder="Search knowledge..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-500 text-sm focus:outline-none focus:border-teal-500"
            />
          </div>
          <div className="flex gap-1 overflow-x-auto scrollbar-hidden">
            {CATEGORIES.map((cat) => {
              const count = cat === 'All' ? stats?.total : stats?.by_type?.[cat]
              return (
                <button
                  key={cat}
                  onClick={() => setActiveCategory(cat)}
                  className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm whitespace-nowrap transition-colors ${
                    activeCategory === cat
                      ? 'bg-teal-500/20 text-teal-400 border border-teal-500/30'
                      : 'text-gray-400 hover:text-white hover:bg-gray-800 border border-transparent'
                  }`}
                >
                  <span className="material-icons text-sm">{CATEGORY_ICONS[cat]}</span>
                  {cat}
                  {count != null && count > 0 && (
                    <span className="text-xs text-gray-500">({count})</span>
                  )}
                </button>
              )
            })}
          </div>
        </div>
      </div>

      {/* Fact list */}
      <div className="flex-1 overflow-y-auto min-h-0 space-y-2 pr-1">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-teal-400" />
          </div>
        ) : facts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-gray-500">
            <span className="material-icons text-4xl mb-2">search_off</span>
            <p>No facts found{searchQuery ? ` matching "${searchQuery}"` : activeCategory !== 'All' ? ` in ${activeCategory}` : ''}</p>
          </div>
        ) : (
          facts.map((fact) => {
            const isExpanded = expandedId === fact.pkg_id
            const isEditing = editingId === fact.pkg_id
            const props = getFactProperties(fact)

            return (
              <div
                key={fact.pkg_id}
                className="bg-gray-800/60 border border-gray-700/50 rounded-xl overflow-hidden hover:border-gray-600/50 transition-colors"
              >
                {/* Row header */}
                <button
                  className="w-full flex items-center gap-3 px-4 py-3 text-left"
                  onClick={() => setExpandedId(isExpanded ? null : fact.pkg_id)}
                >
                  <span className="material-icons text-gray-500 text-lg">{CATEGORY_ICONS[fact.type] || 'help'}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-white text-sm font-medium truncate">{getFactDisplayName(fact)}</p>
                    <p className="text-gray-500 text-xs">{fact.type} &middot; {fact.source?.replace(/_/g, ' ')}</p>
                  </div>
                  <div className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border ${confidenceBg(fact.confidence)}`}>
                    <span className={confidenceColor(fact.confidence)}>{Math.round(fact.confidence * 100)}%</span>
                  </div>
                  <span className={`material-icons text-gray-500 text-sm transition-transform ${isExpanded ? 'rotate-180' : ''}`}>
                    expand_more
                  </span>
                </button>

                {/* Expanded detail */}
                {isExpanded && (
                  <div className="border-t border-gray-700/50 px-4 py-3 space-y-3">
                    {isEditing ? (
                      /* Edit mode */
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <label className="text-xs text-gray-400 w-24">Confidence:</label>
                          <input
                            type="number"
                            min="0"
                            max="1"
                            step="0.05"
                            value={editValues['__confidence'] || ''}
                            onChange={(e) => setEditValues({ ...editValues, __confidence: e.target.value })}
                            className="flex-1 bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white"
                          />
                        </div>
                        {props.map(({ key, value }) => {
                          const fieldKey = key.replace(/ /g, '_')
                          return (
                            <div key={key} className="flex items-center gap-2">
                              <label className="text-xs text-gray-400 w-24 capitalize">{key}:</label>
                              <input
                                value={editValues[fieldKey] ?? value}
                                onChange={(e) => setEditValues({ ...editValues, [fieldKey]: e.target.value })}
                                className="flex-1 bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white"
                              />
                            </div>
                          )
                        })}
                        <div className="flex gap-2 pt-1">
                          <button
                            onClick={() => handleSaveEdit(fact.pkg_id)}
                            className="px-3 py-1 rounded bg-teal-600 hover:bg-teal-700 text-white text-xs"
                          >
                            Save
                          </button>
                          <button
                            onClick={() => { setEditingId(null); setEditValues({}) }}
                            className="px-3 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      /* View mode */
                      <>
                        <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                          {props.map(({ key, value }) => (
                            <div key={key}>
                              <span className="text-xs text-gray-500 capitalize">{key}:</span>
                              <span className="text-sm text-gray-300 ml-1">{value}</span>
                            </div>
                          ))}
                        </div>
                        <div className="flex items-center gap-4 text-xs text-gray-500 pt-1 border-t border-gray-700/30">
                          <span>First learned: {formatDate(fact.first_learned)}</span>
                          <span>Last confirmed: {formatDate(fact.last_confirmed)}</span>
                          <span>Confirmed {fact.times_confirmed || 1}x</span>
                          <span className={confidenceColor(fact.confidence)}>
                            {confidenceLabel(fact.confidence)} confidence ({Math.round(fact.confidence * 100)}%)
                          </span>
                        </div>
                        <div className="flex gap-2 pt-1">
                          <button
                            onClick={() => startEditing(fact)}
                            className="flex items-center gap-1 px-2 py-1 rounded text-xs text-gray-400 hover:text-white hover:bg-gray-700"
                          >
                            <span className="material-icons text-sm">edit</span>
                            Edit
                          </button>
                          {deleteConfirmId === fact.pkg_id ? (
                            <>
                              <span className="text-xs text-red-400 py-1">Delete this fact?</span>
                              <button
                                onClick={() => handleDelete(fact.pkg_id)}
                                className="px-2 py-1 rounded text-xs text-red-400 hover:bg-red-500/20"
                              >
                                Yes, delete
                              </button>
                              <button
                                onClick={() => setDeleteConfirmId(null)}
                                className="px-2 py-1 rounded text-xs text-gray-400 hover:text-white"
                              >
                                Cancel
                              </button>
                            </>
                          ) : (
                            <button
                              onClick={() => setDeleteConfirmId(fact.pkg_id)}
                              className="flex items-center gap-1 px-2 py-1 rounded text-xs text-gray-400 hover:text-red-400 hover:bg-red-500/10"
                            >
                              <span className="material-icons text-sm">delete</span>
                              Delete
                            </button>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>

      {/* Add Fact Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={() => setShowAddModal(false)}>
          <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg p-6 space-y-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-white">Add Knowledge</h3>
              <button onClick={() => setShowAddModal(false)} className="text-gray-400 hover:text-white">
                <span className="material-icons">close</span>
              </button>
            </div>

            {/* Type selector */}
            <div>
              <label className="text-sm text-gray-400 block mb-1">Type</label>
              <div className="flex flex-wrap gap-2">
                {CATEGORIES.filter((c) => c !== 'All').map((cat) => (
                  <button
                    key={cat}
                    onClick={() => {
                      setAddType(cat)
                      setAddProps({})
                    }}
                    className={`px-3 py-1 rounded-lg text-sm ${
                      addType === cat
                        ? 'bg-teal-500/20 text-teal-400 border border-teal-500/30'
                        : 'text-gray-400 hover:text-white bg-gray-800 border border-gray-700'
                    }`}
                  >
                    {cat}
                  </button>
                ))}
              </div>
            </div>

            {/* Property fields */}
            <div className="space-y-2">
              <label className="text-sm text-gray-400 block">Properties</label>
              {(propTemplates[addType] || ['key', 'value']).map((field) => (
                <div key={field} className="flex items-center gap-2">
                  <label className="text-xs text-gray-500 w-28 capitalize">{field.replace(/_/g, ' ')}:</label>
                  <input
                    value={addProps[field] || ''}
                    onChange={(e) => setAddProps({ ...addProps, [field]: e.target.value })}
                    className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-white placeholder-gray-600"
                    placeholder={field.replace(/_/g, ' ')}
                  />
                </div>
              ))}
            </div>

            {/* Confidence slider */}
            <div>
              <label className="text-sm text-gray-400 block mb-1">
                Confidence: <span className={confidenceColor(addConfidence)}>{Math.round(addConfidence * 100)}%</span>
              </label>
              <input
                type="range"
                min="0.1"
                max="1"
                step="0.05"
                value={addConfidence}
                onChange={(e) => setAddConfidence(parseFloat(e.target.value))}
                className="w-full accent-teal-500"
              />
            </div>

            {/* Actions */}
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowAddModal(false)}
                className="px-4 py-2 rounded-lg bg-gray-800 text-gray-300 hover:bg-gray-700 text-sm"
              >
                Cancel
              </button>
              <button
                onClick={handleAdd}
                className="px-4 py-2 rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-sm"
              >
                Add Fact
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
