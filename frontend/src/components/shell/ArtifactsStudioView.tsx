/**
 * Artifacts Studio
 *
 * A dedicated home for everything Sara has built: a persistent, browsable,
 * searchable library of artifacts with a full-width viewer pane. Reuses the
 * canvas ArtifactRenderer + the useArtifacts CRUD hook — nothing is forked.
 */
import React, { useEffect, useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useArtifacts } from '../canvas/hooks/useArtifacts'
import { ArtifactRenderer } from '../canvas/ArtifactRenderer'
import type { Artifact, ArtifactType } from '../canvas/types'

interface ArtifactsStudioViewProps {
  onAskSara: (prompt: string) => void
}

const TYPE_ICON: Record<string, string> = {
  code: 'code',
  diagram: 'account_tree',
  document: 'article',
  mindmap: 'hub',
  note: 'sticky_note_2',
  table: 'table_chart',
  canvas: 'draw',
  file: 'description',
}

const TYPE_LABEL: Record<string, string> = {
  code: 'Code',
  diagram: 'Diagram',
  document: 'Document',
  mindmap: 'Mindmap',
  note: 'Note',
  table: 'Table',
  canvas: 'Canvas',
  file: 'File',
}

// Editing is only meaningful where the renderer actually supports onUpdate.
const EDITABLE_TYPES = new Set<string>(['document', 'note', 'code'])

function iconFor(type: string): string {
  return TYPE_ICON[type] || 'auto_awesome'
}

function labelFor(type: string): string {
  return TYPE_LABEL[type] || type
}

function formatWhen(iso: string): string {
  try {
    return new Date(iso).toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    })
  } catch {
    return ''
  }
}

const ArtifactsStudioView: React.FC<ArtifactsStudioViewProps> = ({ onAskSara }) => {
  const { artifacts, loading, error, updateArtifact, deleteArtifact, refreshArtifacts } =
    useArtifacts({ autoLoad: true })

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [search, setSearch] = useState('')
  const [isEditing, setIsEditing] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState('')

  // Deep-link support: /artifacts?id=… selects that artifact. Re-runs when the
  // query changes (the view stays mounted, so a plain [] effect would miss it).
  const location = useLocation()
  useEffect(() => {
    const deepId = new URLSearchParams(location.search).get('id')
    if (deepId) {
      setSelectedId(deepId)
      refreshArtifacts()
    }
  }, [location.search, refreshArtifacts])

  const typesPresent = useMemo(() => {
    const set = new Set<string>()
    artifacts.forEach((a) => set.add(a.artifact_type))
    return Array.from(set)
  }, [artifacts])

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    return artifacts
      .filter((a) => (typeFilter === 'all' ? true : a.artifact_type === typeFilter))
      .filter((a) => (q ? a.title.toLowerCase().includes(q) : true))
      .slice()
      .sort((a, b) => {
        if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1
        return (b.updated_at || '').localeCompare(a.updated_at || '')
      })
  }, [artifacts, typeFilter, search])

  const selected = useMemo(
    () => artifacts.find((a) => a.id === selectedId) || null,
    [artifacts, selectedId],
  )

  // Reset transient viewer state when the selection changes.
  useEffect(() => {
    setIsEditing(false)
    setRenaming(false)
  }, [selectedId])

  const handlePin = async (a: Artifact) => {
    await updateArtifact(a.id, { is_pinned: !a.is_pinned })
  }

  const handleDelete = async (a: Artifact) => {
    if (!confirm(`Delete "${a.title}"? This can't be undone.`)) return
    await deleteArtifact(a.id)
    if (selectedId === a.id) setSelectedId(null)
  }

  const startRename = (a: Artifact) => {
    setRenameValue(a.title)
    setRenaming(true)
  }

  const commitRename = async (a: Artifact) => {
    const next = renameValue.trim()
    setRenaming(false)
    if (next && next !== a.title) {
      await updateArtifact(a.id, { title: next })
    }
  }

  const askRevise = (a: Artifact) => {
    onAskSara(`Let's revise the ${labelFor(a.artifact_type).toLowerCase()} "${a.title}".`)
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col md:flex-row gap-4">
      {/* Library pane */}
      <aside className="md:w-96 flex-shrink-0 flex flex-col min-h-0 bg-card border border-card rounded-md">
        <div className="p-4 border-b border-card space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <span className="material-icons text-teal-400">auto_awesome</span>
              Studio
            </h2>
            <button
              onClick={() => refreshArtifacts()}
              className="p-1.5 rounded hover:bg-gray-800 text-gray-400 hover:text-white"
              title="Refresh"
            >
              <span className="material-icons text-lg">refresh</span>
            </button>
          </div>

          <div className="relative">
            <span className="material-icons absolute left-2 top-1/2 -translate-y-1/2 text-gray-500 text-lg">
              search
            </span>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search artifacts…"
              className="w-full bg-gray-900 border border-gray-700 rounded-md pl-8 pr-3 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-teal-500"
            />
          </div>

          <div className="flex flex-wrap gap-1.5">
            <Chip active={typeFilter === 'all'} onClick={() => setTypeFilter('all')}>
              All
            </Chip>
            {typesPresent.map((t) => (
              <Chip key={t} active={typeFilter === t} onClick={() => setTypeFilter(t)}>
                {labelFor(t)}
              </Chip>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0 p-2 space-y-1.5">
          {loading && artifacts.length === 0 && (
            <p className="text-sm text-gray-500 p-3">Loading…</p>
          )}
          {error && <p className="text-sm text-red-400 p-3">{error}</p>}
          {!loading && visible.length === 0 && (
            <div className="text-sm text-gray-500 p-4 text-center">
              {artifacts.length === 0
                ? 'Nothing here yet. Anything Sara builds in chat lands here.'
                : 'No artifacts match your filters.'}
            </div>
          )}
          {visible.map((a) => (
            <button
              key={a.id}
              onClick={() => setSelectedId(a.id)}
              className={`w-full text-left rounded-md p-3 border transition-colors ${
                a.id === selectedId
                  ? 'border-teal-500 bg-teal-500/10'
                  : 'border-transparent hover:bg-gray-800'
              }`}
            >
              <div className="flex items-start gap-2">
                <span className="material-icons text-gray-400 text-xl mt-0.5">
                  {iconFor(a.artifact_type)}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <p className="text-sm font-medium text-white truncate flex-1">{a.title}</p>
                    {a.is_pinned && (
                      <span className="material-icons text-teal-400 text-sm">push_pin</span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {labelFor(a.artifact_type)} · {formatWhen(a.updated_at)}
                  </p>
                </div>
              </div>
            </button>
          ))}
        </div>
      </aside>

      {/* Viewer pane */}
      <section className="flex-1 min-h-0 flex flex-col bg-card border border-card rounded-md overflow-hidden">
        {!selected ? (
          <div className="flex-1 flex items-center justify-center text-gray-500">
            <div className="text-center">
              <span className="material-icons text-5xl text-gray-700">auto_awesome</span>
              <p className="mt-2">Select an artifact to view it</p>
            </div>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between gap-3 p-4 border-b border-card">
              <div className="flex items-center gap-2 min-w-0">
                <span className="material-icons text-gray-400">{iconFor(selected.artifact_type)}</span>
                {renaming ? (
                  <input
                    autoFocus
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onBlur={() => commitRename(selected)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') commitRename(selected)
                      if (e.key === 'Escape') setRenaming(false)
                    }}
                    className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-white text-base focus:outline-none focus:border-teal-500"
                  />
                ) : (
                  <h3
                    className="text-base font-semibold text-white truncate cursor-text"
                    title="Click to rename"
                    onClick={() => startRename(selected)}
                  >
                    {selected.title}
                  </h3>
                )}
              </div>

              <div className="flex items-center gap-1 flex-shrink-0">
                {EDITABLE_TYPES.has(selected.artifact_type) && (
                  <button
                    onClick={() => setIsEditing((v) => !v)}
                    className={`px-2.5 py-1 rounded text-sm ${
                      isEditing ? 'bg-teal-600 text-white' : 'hover:bg-gray-800 text-gray-400'
                    }`}
                    title={isEditing ? 'Done editing' : 'Edit'}
                  >
                    {isEditing ? 'Done' : 'Edit'}
                  </button>
                )}
                <button
                  onClick={() => askRevise(selected)}
                  className="p-2 rounded hover:bg-gray-800 text-gray-400 hover:text-white"
                  title="Ask Sara to revise"
                >
                  <span className="material-icons text-lg">forum</span>
                </button>
                <button
                  onClick={() => handlePin(selected)}
                  className={`p-2 rounded hover:bg-gray-800 ${
                    selected.is_pinned ? 'text-teal-400' : 'text-gray-400 hover:text-white'
                  }`}
                  title={selected.is_pinned ? 'Unpin' : 'Pin'}
                >
                  <span className="material-icons text-lg">push_pin</span>
                </button>
                <button
                  onClick={() => handleDelete(selected)}
                  className="p-2 rounded hover:bg-gray-800 text-gray-400 hover:text-red-400"
                  title="Delete"
                >
                  <span className="material-icons text-lg">delete</span>
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-auto min-h-0">
              <ArtifactRenderer
                artifact={selected}
                isEditing={isEditing}
                onUpdate={async (content) => {
                  await updateArtifact(selected.id, { content })
                }}
              />
            </div>

            <div className="px-4 py-2 border-t border-card text-xs text-gray-500">
              Updated {formatWhen(selected.updated_at)}
            </div>
          </>
        )}
      </section>
    </div>
  )
}

const Chip: React.FC<{
  active: boolean
  onClick: () => void
  children: React.ReactNode
}> = ({ active, onClick, children }) => (
  <button
    onClick={onClick}
    className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${
      active
        ? 'border-teal-500 bg-teal-500/15 text-teal-300'
        : 'border-gray-700 text-gray-400 hover:border-gray-500'
    }`}
  >
    {children}
  </button>
)

export default ArtifactsStudioView
