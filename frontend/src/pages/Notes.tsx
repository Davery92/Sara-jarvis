import { startTransition, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  ArrowsPointingInIcon,
  ArrowsPointingOutIcon,
  ArrowPathIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  FolderIcon,
  MagnifyingGlassIcon,
  PlusIcon,
  StarIcon as StarIconOutline,
  TrashIcon,
  XMarkIcon,
} from '@heroicons/react/24/outline'
import { StarIcon as StarIconSolid } from '@heroicons/react/24/solid'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { APP_CONFIG } from '../config'

interface NoteRecord {
  id: string
  title: string
  content: string
  folder_id?: string | null
  tags: string[]
  starred: boolean
  created_at: string
  updated_at: string
}

interface FolderRecord {
  id: string
  name: string
  parent_id?: string | null
  notes_count: number
  subfolders_count: number
  created_at: string
  updated_at: string
}

interface FolderBranch {
  folder: FolderRecord
  children: FolderBranch[]
  notes: NoteRecord[]
}

interface NoteMeta {
  folderPath: string
  tags: string[]
  outgoingIds: string[]
  wordCount: number
  preview: string
}

interface GraphNode {
  id: string
  title: string
  starred: boolean
  degree: number
}

interface GraphEdge {
  source: string
  target: string
}

interface SimNode extends GraphNode {
  x: number
  y: number
  vx: number
  vy: number
  radius: number
}

interface SimEdge {
  source: SimNode
  target: SimNode
}

interface CreateDialogProps {
  kind: 'note' | 'folder'
  value: string
  parentLabel: string
  pending: boolean
  onChange: (value: string) => void
  onClose: () => void
  onSubmit: () => void
}

interface FolderTreeProps {
  branches: FolderBranch[]
  rootNotes: NoteRecord[]
  activeNoteId: string | null
  selectedFolderId: string | null
  expandedFolders: Set<string>
  starredNotes: Set<string>
  unreadNoteIds: Set<string>
  onToggleFolder: (folderId: string) => void
  onSelectFolder: (folderId: string | null) => void
  onSelectNote: (noteId: string) => void
}

interface CommandPaletteProps {
  notes: NoteRecord[]
  noteMeta: Map<string, NoteMeta>
  onClose: () => void
  onSelect: (noteId: string) => void
}

interface NoteContentProps {
  content: string
  titleLookup: Map<string, NoteRecord>
  onSelectNote: (noteId: string) => void
}

interface GraphViewProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  activeNoteId: string | null
  onSelectNote: (noteId: string) => void
}

const LAST_READ_PREFIX = 'sara:notes:lastRead:'

function getLastReadTimestamp(noteId: string): number {
  try {
    const value = localStorage.getItem(`${LAST_READ_PREFIX}${noteId}`)
    return value ? Number(value) : 0
  } catch {
    return 0
  }
}

function markNoteAsRead(noteId: string): void {
  try {
    localStorage.setItem(`${LAST_READ_PREFIX}${noteId}`, String(Date.now()))
  } catch {
    // localStorage may be unavailable
  }
}

function isNoteUnread(note: NoteRecord): boolean {
  const lastRead = getLastReadTimestamp(note.id)
  if (lastRead === 0) {
    // Never read — consider unread if updated in the last 7 days
    const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000
    return safeDate(note.updated_at).getTime() > sevenDaysAgo
  }
  return safeDate(note.updated_at).getTime() > lastRead
}

function branchHasUnread(branch: FolderBranch, unreadIds: Set<string>): boolean {
  if (branch.notes.some((note) => unreadIds.has(note.id))) {
    return true
  }
  return branch.children.some((child) => branchHasUnread(child, unreadIds))
}

const ROOT_BUCKET = '__root__'

function extractWikiLinkTitles(content: string): string[] {
  const titles: string[] = []
  const matcher = /\[\[([^\]]+)\]\]/g
  let match: RegExpExecArray | null

  while ((match = matcher.exec(content)) !== null) {
    const value = match[1].trim()
    if (value) {
      titles.push(value)
    }
  }

  return titles
}

function buildFolderPath(folderId: string | null | undefined, folderMap: Map<string, FolderRecord>): string {
  if (!folderId) {
    return 'Unfiled'
  }

  const segments: string[] = []
  let current = folderMap.get(folderId)
  let guard = 0

  while (current && guard <= folderMap.size) {
    segments.unshift(current.name)
    current = current.parent_id ? folderMap.get(current.parent_id) : undefined
    guard += 1
  }

  return segments.join(' / ') || 'Unfiled'
}

function createPreview(content: string): string {
  const normalized = content.replace(/\s+/g, ' ').trim()
  if (!normalized) {
    return 'No content yet'
  }

  return normalized.length > 140 ? `${normalized.slice(0, 137)}...` : normalized
}

function safeDate(value: string): Date {
  // Backend sends UTC timestamps without Z suffix — append if missing
  let normalized = value
  if (normalized && !normalized.endsWith('Z') && !normalized.includes('+') && !normalized.includes('-', 10)) {
    normalized += 'Z'
  }
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? new Date(0) : date
}

function formatShortDate(value: string): string {
  return safeDate(value).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function formatLongDate(value: string): string {
  return safeDate(value).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function sortNotes(notes: NoteRecord[]): NoteRecord[] {
  return [...notes].sort((left, right) => safeDate(right.updated_at).getTime() - safeDate(left.updated_at).getTime())
}

function buildFolderTree(folders: FolderRecord[], notes: NoteRecord[]): { branches: FolderBranch[]; rootNotes: NoteRecord[] } {
  const folderChildren = new Map<string, FolderRecord[]>()
  const notesByFolder = new Map<string, NoteRecord[]>()

  folders.forEach((folder) => {
    const key = folder.parent_id || ROOT_BUCKET
    const current = folderChildren.get(key) || []
    current.push(folder)
    folderChildren.set(key, current)
  })

  notes.forEach((note) => {
    const key = note.folder_id || ROOT_BUCKET
    const current = notesByFolder.get(key) || []
    current.push(note)
    notesByFolder.set(key, current)
  })

  folderChildren.forEach((value, key) => {
    folderChildren.set(
      key,
      [...value].sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: 'base' }))
    )
  })

  notesByFolder.forEach((value, key) => {
    notesByFolder.set(key, sortNotes(value))
  })

  const buildBranch = (parentId: string | null): FolderBranch[] => {
    const key = parentId || ROOT_BUCKET

    return (folderChildren.get(key) || []).map((folder) => ({
      folder,
      children: buildBranch(folder.id),
      notes: notesByFolder.get(folder.id) || [],
    }))
  }

  const allBranches = buildBranch(null)
  // Pin "Sara's Notes" folder to the top
  allBranches.sort((a, b) => {
    if (a.folder.name === "Sara's Notes") return -1
    if (b.folder.name === "Sara's Notes") return 1
    return 0
  })

  return {
    branches: allBranches,
    rootNotes: notesByFolder.get(ROOT_BUCKET) || [],
  }
}

function groupNotesByDate(notes: NoteRecord[]): { label: string; notes: NoteRecord[] }[] {
  const groups = new Map<string, NoteRecord[]>()
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)

  const fmt = (d: Date) => d.toISOString().slice(0, 10)
  const todayKey = fmt(today)
  const yesterdayKey = fmt(yesterday)

  for (const note of notes) {
    const d = safeDate(note.created_at)
    const key = fmt(d)
    const list = groups.get(key) || []
    list.push(note)
    groups.set(key, list)
  }

  // Sort date keys descending (newest first)
  const sortedKeys = [...groups.keys()].sort((a, b) => b.localeCompare(a))

  return sortedKeys.map((key) => {
    let label: string
    if (key === todayKey) {
      label = 'Today'
    } else if (key === yesterdayKey) {
      label = 'Yesterday'
    } else {
      const d = new Date(key + 'T00:00:00')
      label = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
    }
    return { label, notes: groups.get(key)! }
  })
}

function pruneEmptyBranches(branches: FolderBranch[]): FolderBranch[] {
  return branches
    .map((branch) => ({
      ...branch,
      children: pruneEmptyBranches(branch.children),
    }))
    .filter((branch) => branch.notes.length > 0 || branch.children.length > 0)
}

function buildWikiMarkdown(content: string, titleLookup: Map<string, NoteRecord>): string {
  return content.replace(/\[\[([^\]]+)\]\]/g, (_match, rawTitle: string) => {
    const title = rawTitle.trim()
    const target = titleLookup.get(title.toLowerCase())

    if (target) {
      return `[${title}](note://${target.id})`
    }

    return `[${title}](missing-note://${encodeURIComponent(title)})`
  })
}

function normalizeTags(tags: string[]): string[] {
  const normalized: string[] = []
  const seen = new Set<string>()

  tags.forEach((value) => {
    const tag = value.trim().toLowerCase()
    if (!tag || seen.has(tag)) {
      return
    }

    seen.add(tag)
    normalized.push(tag.slice(0, 48))
  })

  return normalized.slice(0, 20)
}

function parseTagInput(value: string): string[] {
  return normalizeTags(
    value
      .split(',')
      .map((segment) => segment.trim())
      .filter(Boolean)
  )
}

function tagsToInput(tags: string[]): string {
  return normalizeTags(tags || []).join(', ')
}

function areTagListsEqual(left: string[], right: string[]): boolean {
  if (left.length !== right.length) {
    return false
  }

  return left.every((value, index) => value === right[index])
}

function normalizeIncomingNote(note: NoteRecord): NoteRecord {
  return {
    ...note,
    tags: normalizeTags(note.tags || []),
    starred: Boolean(note.starred),
  }
}

function CreateDialog({
  kind,
  value,
  parentLabel,
  pending,
  onChange,
  onClose,
  onSubmit,
}: CreateDialogProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      onClose()
    }

    if (event.key === 'Enter') {
      onSubmit()
    }
  }

  const label = kind === 'note' ? 'New Note' : 'New Folder'
  const placeholder = kind === 'note' ? 'Architectural recap' : 'Research'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 px-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-white/10 bg-[#0c1626] p-6 shadow-[0_8px_40px_rgba(2,8,23,0.6)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-display text-lg font-semibold text-white">{label}</h2>
            <p className="mt-1 text-xs text-slate-500">Parent: {parentLabel}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-white/[0.06] hover:text-slate-200"
            aria-label="Close dialog"
          >
            <XMarkIcon className="h-5 w-5" />
          </button>
        </div>

        <div className="mt-5">
          <label className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
            {kind === 'note' ? 'Title' : 'Name'}
          </label>
          <input
            ref={inputRef}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            className="mt-2 w-full rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-sm text-slate-100 outline-none transition focus:border-teal-300/30 placeholder:text-slate-600"
          />
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-white/10 px-3.5 py-2 text-sm text-slate-300 transition hover:bg-white/[0.06] hover:text-white"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={pending || !value.trim()}
            className="rounded-xl bg-teal-400/90 px-3.5 py-2 text-sm font-medium text-slate-950 transition hover:bg-teal-300 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-slate-500"
          >
            {pending ? 'Saving...' : kind === 'note' ? 'Create note' : 'Create folder'}
          </button>
        </div>
      </div>
    </div>
  )
}

function FolderTree({
  branches,
  rootNotes,
  activeNoteId,
  selectedFolderId,
  expandedFolders,
  starredNotes,
  unreadNoteIds,
  onToggleFolder,
  onSelectFolder,
  onSelectNote,
}: FolderTreeProps) {
  const [unfiledCollapsed, setUnfiledCollapsed] = useState(true)
  return (
    <div className="space-y-0.5">
      <button
        type="button"
        onClick={() => onSelectFolder(null)}
        className={`flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-sm transition-colors ${
          selectedFolderId === null ? 'bg-white/[0.06] text-white' : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200'
        }`}
      >
        <span className="font-medium">Workspace</span>
        <span className="text-xs text-slate-600">{rootNotes.length + branches.length}</span>
      </button>

      {branches.map((branch) => (
        <FolderBranchNode
          key={branch.folder.id}
          branch={branch}
          activeNoteId={activeNoteId}
          selectedFolderId={selectedFolderId}
          expandedFolders={expandedFolders}
          starredNotes={starredNotes}
          unreadNoteIds={unreadNoteIds}
          onToggleFolder={onToggleFolder}
          onSelectFolder={onSelectFolder}
          onSelectNote={onSelectNote}
          depth={0}
        />
      ))}

      {rootNotes.length > 0 && (
        <div className="space-y-0.5 pt-2">
          <button
            type="button"
            onClick={() => setUnfiledCollapsed(c => !c)}
            className="flex w-full items-center gap-1 px-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 transition-colors hover:text-slate-300"
          >
            {unfiledCollapsed ? <ChevronRightIcon className="h-3 w-3" /> : <ChevronDownIcon className="h-3 w-3" />}
            <span>Unfiled</span>
            {rootNotes.some((n) => unreadNoteIds.has(n.id)) && (
              <span className="h-1.5 w-1.5 rounded-full bg-teal-300/80 flex-shrink-0" />
            )}
            <span className="ml-auto text-[10px] font-normal text-slate-600">{rootNotes.length}</span>
          </button>
          {!unfiledCollapsed && rootNotes.map((note) => (
            <button
              key={note.id}
              type="button"
              onClick={() => onSelectNote(note.id)}
              className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors ${
                activeNoteId === note.id
                  ? 'bg-white/[0.06] text-white'
                  : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200'
              }`}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-slate-600" />
              <span className="min-w-0 flex-1 truncate">{note.title.trim() || 'Untitled'}</span>
              {unreadNoteIds.has(note.id) && <span className="h-1.5 w-1.5 rounded-full bg-teal-300/80 flex-shrink-0" />}
              {starredNotes.has(note.id) && <StarIconSolid className="h-3.5 w-3.5 text-amber-300/80" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function FolderBranchNode({
  branch,
  activeNoteId,
  selectedFolderId,
  expandedFolders,
  starredNotes,
  unreadNoteIds,
  onToggleFolder,
  onSelectFolder,
  onSelectNote,
  depth,
}: {
  branch: FolderBranch
  activeNoteId: string | null
  selectedFolderId: string | null
  expandedFolders: Set<string>
  starredNotes: Set<string>
  unreadNoteIds: Set<string>
  onToggleFolder: (folderId: string) => void
  onSelectFolder: (folderId: string | null) => void
  onSelectNote: (noteId: string) => void
  depth: number
}) {
  const isExpanded = expandedFolders.has(branch.folder.id)
  const leftPad = depth * 12

  return (
    <div className="space-y-0.5">
      <button
        type="button"
        onClick={() => {
          onSelectFolder(branch.folder.id)
          onToggleFolder(branch.folder.id)
        }}
        className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors ${
          selectedFolderId === branch.folder.id
            ? 'bg-white/[0.06] text-white'
            : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200'
        }`}
        style={{ paddingLeft: 8 + leftPad }}
      >
        {isExpanded ? <ChevronDownIcon className="h-3.5 w-3.5 text-slate-600" /> : <ChevronRightIcon className="h-3.5 w-3.5 text-slate-600" />}
        {branch.folder.name === "Sara's Notes" ? (
          <svg className="h-4 w-4 text-purple-300/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
        ) : (
          <FolderIcon className="h-4 w-4 text-slate-500" />
        )}
        <span className="min-w-0 flex-1 truncate">{branch.folder.name}</span>
        {branchHasUnread(branch, unreadNoteIds) && (
          <span className="h-1.5 w-1.5 rounded-full bg-teal-300/80 flex-shrink-0" />
        )}
        {branch.folder.name === "Sara's Notes" && (
          <span className="text-[10px] font-medium text-purple-300/70">Sara</span>
        )}
        <span className="text-[11px] text-slate-600">{branch.notes.length + branch.children.length}</span>
      </button>

      {isExpanded && (
        <div className="space-y-0.5">
          {branch.children.map((child) => (
            <FolderBranchNode
              key={child.folder.id}
              branch={child}
              activeNoteId={activeNoteId}
              selectedFolderId={selectedFolderId}
              expandedFolders={expandedFolders}
              starredNotes={starredNotes}
              unreadNoteIds={unreadNoteIds}
              onToggleFolder={onToggleFolder}
              onSelectFolder={onSelectFolder}
              onSelectNote={onSelectNote}
              depth={depth + 1}
            />
          ))}

          {groupNotesByDate(branch.notes).map((group) => (
            <div key={group.label}>
              <div
                className="px-2 pt-2 pb-0.5 text-[10px] font-semibold uppercase tracking-widest text-slate-600"
                style={{ paddingLeft: 30 + leftPad }}
              >
                {group.label}
              </div>
              {group.notes.map((note) => (
                <button
                  key={note.id}
                  type="button"
                  onClick={() => onSelectNote(note.id)}
                  className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors ${
                    activeNoteId === note.id
                      ? 'bg-white/[0.06] text-white'
                      : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200'
                  }`}
                  style={{ paddingLeft: 30 + leftPad }}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${unreadNoteIds.has(note.id) ? 'bg-teal-300/80' : branch.folder.name === "Sara's Notes" ? 'bg-purple-300/60' : 'bg-slate-600'}`} />
                  <span className="min-w-0 flex-1 truncate">{note.title.trim() || 'Untitled'}</span>
                  {branch.folder.name === "Sara's Notes" && (
                    <span className="text-[9px] font-medium text-purple-300/70">Sara</span>
                  )}
                  {starredNotes.has(note.id) && <StarIconSolid className="h-3.5 w-3.5 text-amber-300/80" />}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function CommandPalette({ notes, noteMeta, onClose, onSelect }: CommandPaletteProps) {
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement | null>(null)
  const deferredQuery = useDeferredValue(query)
  const normalizedQuery = deferredQuery.trim().toLowerCase()

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const results = useMemo(() => {
    const scored = notes
      .map((note) => {
        const meta = noteMeta.get(note.id)
        const haystack = [
          note.title,
          note.content,
          meta?.folderPath || '',
          ...(meta?.tags || []),
        ]
          .join(' ')
          .toLowerCase()

        const title = note.title.toLowerCase()
        let score = 0

        if (!normalizedQuery) {
          score = 1
        } else if (title === normalizedQuery) {
          score = 6
        } else if (title.startsWith(normalizedQuery)) {
          score = 5
        } else if (title.includes(normalizedQuery)) {
          score = 4
        } else if (haystack.includes(normalizedQuery)) {
          score = 2
        }

        return { note, score }
      })
      .filter((entry) => entry.score > 0)
      .sort((left, right) => {
        if (right.score !== left.score) {
          return right.score - left.score
        }

        return safeDate(right.note.updated_at).getTime() - safeDate(left.note.updated_at).getTime()
      })

    return scored.slice(0, 10)
  }, [normalizedQuery, noteMeta, notes])

  const submitFirst = () => {
    const first = results[0]
    if (!first) {
      return
    }

    onSelect(first.note.id)
    onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-slate-950/60 px-4 pt-24 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl overflow-hidden rounded-2xl border border-white/10 bg-[#0c1626] shadow-[0_8px_40px_rgba(2,8,23,0.6)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="border-b border-white/8 px-5 py-4">
          <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 transition-colors focus-within:border-teal-300/30">
            <MagnifyingGlassIcon className="h-5 w-5 text-slate-500" />
            <input
              ref={inputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  onClose()
                }

                if (event.key === 'Enter') {
                  submitFirst()
                }
              }}
              placeholder="Jump to a note, folder, or tag..."
              className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-600"
            />
            <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-600">
              esc
            </span>
          </div>
        </div>

        <div className="max-h-[26rem] overflow-y-auto p-3">
          {results.length === 0 ? (
            <p className="px-4 py-10 text-center text-sm text-slate-500">
              No notes matched that search.
            </p>
          ) : (
            <div className="space-y-1">
              {results.map(({ note }) => {
                const meta = noteMeta.get(note.id)

                return (
                  <button
                    key={note.id}
                    type="button"
                    onClick={() => {
                      onSelect(note.id)
                      onClose()
                    }}
                    className="flex w-full items-start justify-between gap-4 rounded-xl px-4 py-3 text-left transition-colors hover:bg-white/[0.04]"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-slate-100">{note.title.trim() || 'Untitled'}</div>
                      <div className="mt-1 truncate text-xs text-slate-500">{meta?.folderPath || 'Unfiled'}</div>
                      <div className="mt-2 text-xs text-slate-500">{meta?.preview || 'No content yet'}</div>
                    </div>
                    <div className="hidden flex-wrap justify-end gap-2 md:flex">
                      {(meta?.tags || []).slice(0, 3).map((tag) => (
                        <span
                          key={`${note.id}-${tag}`}
                          className="rounded-full bg-white/[0.06] px-2 py-1 text-[10px] font-medium text-slate-400"
                        >
                          #{tag}
                        </span>
                      ))}
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function NoteContent({ content, titleLookup, onSelectNote }: NoteContentProps) {
  const markdown = useMemo(() => buildWikiMarkdown(content, titleLookup), [content, titleLookup])

  return (
    <div className="prose prose-invert max-w-none text-[15px] leading-relaxed prose-headings:text-white prose-strong:text-slate-100 prose-a:no-underline">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className="mb-4 font-display text-2xl font-semibold tracking-tight text-white">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-3 mt-8 font-display text-xl font-semibold tracking-tight text-white">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-2 mt-6 text-lg font-semibold text-white">{children}</h3>,
          p: ({ children }) => <p className="mb-3 text-[15px] leading-relaxed text-slate-300">{children}</p>,
          ul: ({ children }) => <ul className="mb-4 space-y-2 pl-5 text-[15px] leading-relaxed text-slate-300">{children}</ul>,
          ol: ({ children }) => <ol className="mb-4 space-y-2 pl-5 text-[15px] leading-relaxed text-slate-300">{children}</ol>,
          li: ({ children }) => <li className="pl-1">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="my-5 border-l-2 border-teal-400/50 pl-4 text-slate-400">
              {children}
            </blockquote>
          ),
          code: ({ className, children, ...props }: any) => {
            // react-markdown v9 dropped the `inline` prop, so we detect block
            // code ourselves: a fenced block has a `language-*` class OR its text
            // spans multiple lines. Everything else is an inline span — otherwise
            // single-backtick code wrongly renders as a full-width black box.
            const text = String(children ?? '')
            const isBlock = /language-/.test(className || '') || text.includes('\n')

            if (!isBlock) {
              return (
                <code
                  className="rounded-[5px] border border-slate-600/40 bg-slate-700/30 px-1.5 py-0.5 text-[0.88em] font-medium text-cyan-200"
                  {...props}
                >
                  {children}
                </code>
              )
            }

            return (
              <pre className="my-4 overflow-x-auto rounded-xl border border-slate-700/50 bg-slate-800/40 px-4 py-3.5 text-[13.5px] leading-relaxed text-slate-100">
                <code className={className} {...props}>
                  {children}
                </code>
              </pre>
            )
          },
          pre: ({ children }) => <>{children}</>,
          a: ({ href, children }) => {
            if (!href) {
              return <span>{children}</span>
            }

            if (href.startsWith('note://')) {
              const noteId = href.slice('note://'.length)

              return (
                <button
                  type="button"
                  onClick={() => onSelectNote(noteId)}
                  className="border-b border-dashed border-teal-300/40 font-medium text-teal-300 transition-colors hover:text-teal-200"
                >
                  {children}
                </button>
              )
            }

            if (href.startsWith('missing-note://')) {
              return (
                <span className="border-b border-dashed border-rose-300/40 font-medium text-rose-300/80">
                  {children}
                </span>
              )
            }

            return (
              <a
                href={href}
                className="font-medium text-teal-300 underline decoration-teal-300/30 underline-offset-2 transition-colors hover:text-teal-200"
                target="_blank"
                rel="noopener noreferrer"
              >
                {children}
              </a>
            )
          },
          table: ({ children }) => (
            <div className="my-5 overflow-x-auto rounded-xl border border-white/10">
              <table className="w-full border-collapse text-sm">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-white/[0.04]">{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => <tr className="border-b border-white/8 last:border-b-0">{children}</tr>,
          th: ({ children }) => <th className="px-4 py-3 text-left font-semibold text-slate-200">{children}</th>,
          td: ({ children }) => <td className="px-4 py-3 text-slate-400">{children}</td>,
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  )
}

function GraphView({ nodes, edges, activeNoteId, onSelectNote }: GraphViewProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const animationFrameRef = useRef<number | null>(null)
  const nodesRef = useRef<SimNode[]>([])
  const edgesRef = useRef<SimEdge[]>([])
  const sizeRef = useRef({ width: 640, height: 420 })
  const panRef = useRef({ x: 0, y: 0 })
  const [hoveredNoteId, setHoveredNoteId] = useState<string | null>(null)
  const interactionRef = useRef<{
    mode: 'idle' | 'drag' | 'pan'
    nodeId: string | null
    pointerId: number | null
    moved: boolean
    lastX: number
    lastY: number
  }>({
    mode: 'idle',
    nodeId: null,
    pointerId: null,
    moved: false,
    lastX: 0,
    lastY: 0,
  })

  useEffect(() => {
    const width = Math.max(sizeRef.current.width, 640)
    const height = Math.max(sizeRef.current.height, 420)
    const denominator = Math.max(nodes.length, 1)
    const placed = nodes.map((node, index) => ({
      ...node,
      x: width / 2 + Math.cos((index / denominator) * Math.PI * 2) * Math.min(width * 0.24, 190),
      y: height / 2 + Math.sin((index / denominator) * Math.PI * 2) * Math.min(height * 0.22, 160),
      vx: 0,
      vy: 0,
      radius: 8 + Math.min(node.degree * 1.5, 12),
    }))

    const nodeMap = new Map(placed.map((node) => [node.id, node]))

    nodesRef.current = placed
    edgesRef.current = edges
      .map((edge) => {
        const source = nodeMap.get(edge.source)
        const target = nodeMap.get(edge.target)

        if (!source || !target) {
          return null
        }

        return { source, target }
      })
      .filter(Boolean) as SimEdge[]

    panRef.current = { x: 0, y: 0 }
  }, [edges, nodes])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) {
      return undefined
    }

    const context = canvas.getContext('2d')
    if (!context) {
      return undefined
    }

    const resizeCanvas = () => {
      const rect = canvas.getBoundingClientRect()
      const width = rect.width || 640
      const height = rect.height || 420
      const pixelRatio = window.devicePixelRatio || 1

      sizeRef.current = { width, height }
      canvas.width = width * pixelRatio
      canvas.height = height * pixelRatio
    }

    resizeCanvas()

    const observer = new ResizeObserver(resizeCanvas)
    observer.observe(canvas)

    const draw = () => {
      const { width, height } = sizeRef.current
      const pixelRatio = window.devicePixelRatio || 1
      const graphNodes = nodesRef.current
      const graphEdges = edgesRef.current

      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)
      context.clearRect(0, 0, width, height)

      for (let left = 0; left < graphNodes.length; left += 1) {
        for (let right = left + 1; right < graphNodes.length; right += 1) {
          const source = graphNodes[left]
          const target = graphNodes[right]
          const dx = target.x - source.x
          const dy = target.y - source.y
          const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
          const force = 1000 / (distance * distance)

          source.vx -= (dx / distance) * force
          source.vy -= (dy / distance) * force
          target.vx += (dx / distance) * force
          target.vy += (dy / distance) * force
        }
      }

      graphEdges.forEach((edge) => {
        const dx = edge.target.x - edge.source.x
        const dy = edge.target.y - edge.source.y
        const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
        const pull = (distance - 130) * 0.009

        edge.source.vx += (dx / distance) * pull
        edge.source.vy += (dy / distance) * pull
        edge.target.vx -= (dx / distance) * pull
        edge.target.vy -= (dy / distance) * pull
      })

      graphNodes.forEach((node) => {
        node.vx += (width / 2 - node.x) * 0.0016
        node.vy += (height / 2 - node.y) * 0.0016

        if (interactionRef.current.mode === 'drag' && interactionRef.current.nodeId === node.id) {
          node.vx = 0
          node.vy = 0
          return
        }

        node.vx *= 0.88
        node.vy *= 0.88
        node.x += node.vx
        node.y += node.vy
      })

      context.save()
      context.translate(panRef.current.x, panRef.current.y)

      graphEdges.forEach((edge) => {
        const connected = edge.source.id === activeNoteId || edge.target.id === activeNoteId
        context.beginPath()
        context.moveTo(edge.source.x, edge.source.y)
        context.lineTo(edge.target.x, edge.target.y)
        context.strokeStyle = connected ? 'rgba(103, 232, 249, 0.42)' : 'rgba(71, 85, 105, 0.52)'
        context.lineWidth = connected ? 2 : 1
        context.stroke()
      })

      graphNodes.forEach((node) => {
        const isActive = node.id === activeNoteId
        const isHovered = node.id === hoveredNoteId
        const nodeColor = isActive ? '#67e8f9' : node.starred ? '#f59e0b' : '#14b8a6'

        if (isActive || isHovered) {
          context.beginPath()
          context.arc(node.x, node.y, node.radius + 8, 0, Math.PI * 2)
          context.fillStyle = isActive ? 'rgba(103, 232, 249, 0.12)' : 'rgba(20, 184, 166, 0.08)'
          context.fill()
        }

        context.beginPath()
        context.arc(node.x, node.y, node.radius, 0, Math.PI * 2)
        context.fillStyle = nodeColor
        context.fill()

        if (isActive || isHovered) {
          context.font = '12px Inter, system-ui, sans-serif'
          context.textAlign = 'center'
          context.fillStyle = isActive ? '#ecfeff' : '#cbd5e1'
          context.fillText(node.title, node.x, node.y - node.radius - 10)
        }
      })

      context.restore()
      animationFrameRef.current = window.requestAnimationFrame(draw)
    }

    draw()

    return () => {
      observer.disconnect()

      if (animationFrameRef.current) {
        window.cancelAnimationFrame(animationFrameRef.current)
      }
    }
  }, [activeNoteId, hoveredNoteId])

  const getNodeAtPoint = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current
    if (!canvas) {
      return null
    }

    const rect = canvas.getBoundingClientRect()
    const x = clientX - rect.left - panRef.current.x
    const y = clientY - rect.top - panRef.current.y

    return (
      nodesRef.current.find((node) => {
        const dx = node.x - x
        const dy = node.y - y

        return dx * dx + dy * dy <= (node.radius + 5) * (node.radius + 5)
      }) || null
    )
  }

  const finishPointer = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (interactionRef.current.pointerId !== null && event.currentTarget.hasPointerCapture(interactionRef.current.pointerId)) {
      event.currentTarget.releasePointerCapture(interactionRef.current.pointerId)
    }

    if (!interactionRef.current.moved) {
      const hit = getNodeAtPoint(event.clientX, event.clientY)
      if (hit) {
        onSelectNote(hit.id)
      }
      setHoveredNoteId(hit?.id || null)
    }

    interactionRef.current = {
      mode: 'idle',
      nodeId: null,
      pointerId: null,
      moved: false,
      lastX: 0,
      lastY: 0,
    }
  }

  if (nodes.length === 0) {
    return (
      <div className="flex h-full min-h-[26rem] items-center justify-center text-sm text-slate-500">
        Add some notes with `[[wiki links]]` to build a graph.
      </div>
    )
  }

  const isInteracting = interactionRef.current.mode !== 'idle'

  return (
    <canvas
      ref={canvasRef}
      className="block h-full min-h-[30rem] w-full rounded-2xl border border-white/8 bg-[#050b16]"
      style={{ cursor: isInteracting ? 'grabbing' : hoveredNoteId ? 'pointer' : 'grab' }}
      onPointerDown={(event) => {
        const hit = getNodeAtPoint(event.clientX, event.clientY)

        event.currentTarget.setPointerCapture(event.pointerId)
        interactionRef.current = {
          mode: hit ? 'drag' : 'pan',
          nodeId: hit?.id || null,
          pointerId: event.pointerId,
          moved: false,
          lastX: event.clientX,
          lastY: event.clientY,
        }
      }}
      onPointerMove={(event) => {
        const interaction = interactionRef.current

        if (interaction.mode === 'idle') {
          const hit = getNodeAtPoint(event.clientX, event.clientY)
          setHoveredNoteId(hit?.id || null)
          return
        }

        const deltaX = event.clientX - interaction.lastX
        const deltaY = event.clientY - interaction.lastY

        if (Math.abs(deltaX) + Math.abs(deltaY) > 2) {
          interaction.moved = true
        }

        if (interaction.mode === 'drag' && interaction.nodeId) {
          const node = nodesRef.current.find((candidate) => candidate.id === interaction.nodeId)
          const canvas = canvasRef.current

          if (node && canvas) {
            const rect = canvas.getBoundingClientRect()
            node.x = event.clientX - rect.left - panRef.current.x
            node.y = event.clientY - rect.top - panRef.current.y
            node.vx = 0
            node.vy = 0
          }
        } else if (interaction.mode === 'pan') {
          panRef.current.x += deltaX
          panRef.current.y += deltaY
        }

        interaction.lastX = event.clientX
        interaction.lastY = event.clientY
      }}
      onPointerUp={finishPointer}
      onPointerCancel={finishPointer}
      onPointerLeave={() => {
        if (interactionRef.current.mode === 'idle') {
          setHoveredNoteId(null)
        }
      }}
    />
  )
}

interface NotesProps {
  /** "Chat about this" — opens the chat view pre-loaded with the note's context. */
  onChatAboutNote?: (title: string, content: string) => void
}

export default function Notes({ onChatAboutNote }: NotesProps = {}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [notes, setNotes] = useState<NoteRecord[]>([])
  const [folders, setFolders] = useState<FolderRecord[]>([])
  const [dbConnections, setDbConnections] = useState<{ source: string; target: string }[]>([])
  const graphLoadedRef = useRef(false)
  const contentLoadedRef = useRef<Set<string>>(new Set())
  const [contentVersion, setContentVersion] = useState(0)
  const [loading, setLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [activeNoteId, setActiveNoteId] = useState<string | null>(null)
  const [selectedFolderId, setSelectedFolderId] = useState<string | null>(null)
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set())
  const [showGraph, setShowGraph] = useState(false)
  const [showPalette, setShowPalette] = useState(false)
  const [showRightPanel, setShowRightPanel] = useState(false)
  const [isFocusMode, setIsFocusMode] = useState(false)
  const [editorMode, setEditorMode] = useState<'preview' | 'edit'>('preview')
  const editorTextareaRef = useRef<HTMLTextAreaElement | null>(null)
  const [draftTitle, setDraftTitle] = useState('')
  const [draftContent, setDraftContent] = useState('')
  const [draftTagsText, setDraftTagsText] = useState('')
  const [draftStarred, setDraftStarred] = useState(false)
  const [saveState, setSaveState] = useState<'saved' | 'saving' | 'error'>('saved')
  const [showCreateNote, setShowCreateNote] = useState(false)
  const [showCreateFolder, setShowCreateFolder] = useState(false)
  const [createName, setCreateName] = useState('')
  const [createPending, setCreatePending] = useState(false)
  const [readVersion, setReadVersion] = useState(0)
  const hydratedNoteIdRef = useRef<string | null>(null)
  const saveSequenceRef = useRef(0)
  const deferredSearch = useDeferredValue(searchQuery)
  const normalizedQuery = deferredSearch.trim().toLowerCase()
  const requestedNoteId = searchParams.get('id')
  const draftTags = useMemo(() => parseTagInput(draftTagsText), [draftTagsText])

  useEffect(() => {
    let cancelled = false

    const loadWorkspace = async () => {
      setLoading(true)
      setErrorMessage(null)

      try {
        // Critical path: only the vault list + folders. We request notes WITHOUT
        // full bodies (include_content=false) so the payload is a few hundred KB
        // instead of ~5MB; full content is lazy-loaded when a note is opened.
        // Graph data (~2MB, ~10k links) is NOT loaded here — it's fetched lazily
        // the first time the Graph view is opened.
        const [notesResponse, foldersResponse] = await Promise.all([
          fetch(`${APP_CONFIG.apiUrl}/notes?include_content=false`, { credentials: 'include' }),
          fetch(`${APP_CONFIG.apiUrl}/folders`, { credentials: 'include' }),
        ])

        if (!notesResponse.ok || !foldersResponse.ok) {
          throw new Error('Failed to load notes workspace')
        }

        const [notesData, foldersData] = await Promise.all([
          notesResponse.json() as Promise<NoteRecord[]>,
          foldersResponse.json() as Promise<FolderRecord[]>,
        ])

        if (cancelled) {
          return
        }

        setNotes(sortNotes(notesData.map(normalizeIncomingNote)))
        setFolders(
          [...foldersData].sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: 'base' }))
        )
        // Default Sara's Notes subfolders to collapsed
        const sarasNotesFolder = foldersData.find((f) => f.name === "Sara's Notes")
        const sarasNotesFolderId = sarasNotesFolder?.id ?? null
        const sarasSubfolderIds = new Set(
          sarasNotesFolderId
            ? foldersData.filter((f) => f.parent_id === sarasNotesFolderId).map((f) => f.id)
            : []
        )
        setExpandedFolders(
          new Set(foldersData.filter((folder) => !sarasSubfolderIds.has(folder.id)).map((folder) => folder.id))
        )
      } catch (error) {
        console.error('Failed to load notes workspace:', error)
        if (!cancelled) {
          setErrorMessage('Could not load your notes right now.')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void loadWorkspace()

    return () => {
      cancelled = true
    }
  }, [])

  // Lazy-load graph connections (~2MB / ~10k links) only the first time the
  // Graph view is opened — keeps it off the initial page-load critical path.
  useEffect(() => {
    if (!showGraph || graphLoadedRef.current) {
      return
    }
    graphLoadedRef.current = true
    let cancelled = false
    void (async () => {
      try {
        const res = await fetch(`${APP_CONFIG.apiUrl}/notes/graph-data`, { credentials: 'include' })
        if (!res.ok) {
          graphLoadedRef.current = false
          return
        }
        const data = (await res.json()) as { links?: { source: string; target: string }[] }
        if (!cancelled && data.links) {
          setDbConnections(data.links.map((l) => ({ source: l.source, target: l.target })))
        }
      } catch {
        graphLoadedRef.current = false // allow a retry on next open
      }
    })()
    return () => {
      cancelled = true
    }
  }, [showGraph])

  const folderMap = useMemo(() => new Map(folders.map((folder) => [folder.id, folder])), [folders])

  const unreadNoteIds = useMemo(() => {
    void readVersion // depend on readVersion to recompute after marking read
    const ids = new Set<string>()
    for (const note of notes) {
      if (isNoteUnread(note)) {
        ids.add(note.id)
      }
    }
    return ids
  }, [notes, readVersion])

  const titleLookup = useMemo(() => {
    const lookup = new Map<string, NoteRecord>()
    notes.forEach((note) => {
      const title = note.title.trim().toLowerCase()
      if (title && !lookup.has(title)) {
        lookup.set(title, note)
      }
    })
    return lookup
  }, [notes])

  const noteMeta = useMemo(() => {
    const meta = new Map<string, NoteMeta>()

    notes.forEach((note) => {
      const folderPath = buildFolderPath(note.folder_id, folderMap)
      const outgoingIds = Array.from(
        new Set(
          extractWikiLinkTitles(note.content)
            .map((title) => titleLookup.get(title.toLowerCase())?.id || null)
            .filter(Boolean)
        )
      ) as string[]
      const contentWords = note.content.trim() ? note.content.trim().split(/\s+/).length : 0

      meta.set(note.id, {
        folderPath,
        tags: normalizeTags(note.tags || []),
        outgoingIds,
        wordCount: contentWords,
        preview: createPreview(note.content),
      })
    })

    return meta
  }, [folderMap, notes, titleLookup])

  const starredNotes = useMemo(
    () => new Set(notes.filter((note) => note.starred).map((note) => note.id)),
    [notes]
  )

  const filteredNotes = useMemo(() => {
    const sorted = sortNotes(notes)

    if (!normalizedQuery) {
      return sorted
    }

    return sorted.filter((note) => {
      const meta = noteMeta.get(note.id)
      const haystack = [
        note.title,
        note.content,
        meta?.folderPath || '',
        ...(meta?.tags || []),
      ]
        .join(' ')
        .toLowerCase()

      return haystack.includes(normalizedQuery)
    })
  }, [normalizedQuery, noteMeta, notes])

  const treeData = useMemo(() => {
    const built = buildFolderTree(folders, filteredNotes)

    if (!normalizedQuery) {
      return built
    }

    return {
      branches: pruneEmptyBranches(built.branches),
      rootNotes: built.rootNotes,
    }
  }, [filteredNotes, folders, normalizedQuery])

  const activeNote = useMemo(
    () => notes.find((note) => note.id === activeNoteId) || null,
    [activeNoteId, notes]
  )

  useEffect(() => {
    if (!notes.length) {
      hydratedNoteIdRef.current = null
      setActiveNoteId(null)
      setDraftTitle('')
      setDraftContent('')
      setDraftTagsText('')
      setDraftStarred(false)
      return
    }

    const resolvedId =
      (requestedNoteId && notes.some((note) => note.id === requestedNoteId) && requestedNoteId) ||
      (activeNoteId && notes.some((note) => note.id === activeNoteId) && activeNoteId) ||
      notes[0].id

    if (resolvedId !== activeNoteId) {
      setActiveNoteId(resolvedId)
    }

    if (requestedNoteId !== resolvedId) {
      setSearchParams({ id: resolvedId }, { replace: true })
    }
  }, [activeNoteId, notes, requestedNoteId, setSearchParams])

  useEffect(() => {
    if (!activeNote) {
      hydratedNoteIdRef.current = null
      setDraftTitle('')
      setDraftContent('')
      setDraftTagsText('')
      setDraftStarred(false)
      setSaveState('saved')
      return
    }

    // Mark the active note as read
    if (activeNote.id !== hydratedNoteIdRef.current) {
      markNoteAsRead(activeNote.id)
      setReadVersion((v) => v + 1)
    }

    // The vault list ships only excerpts (include_content=false). Fetch the full
    // body once per note before hydrating the editor, so editing/save and the
    // isDirty check operate on complete content — otherwise a truncated excerpt
    // would make the note look permanently "dirty" and could overwrite the body.
    if (!contentLoadedRef.current.has(activeNote.id)) {
      const targetId = activeNote.id
      let cancelled = false
      void (async () => {
        try {
          const res = await fetch(`${APP_CONFIG.apiUrl}/notes/${targetId}`, { credentials: 'include' })
          if (res.ok) {
            const full = normalizeIncomingNote((await res.json()) as NoteRecord)
            if (!cancelled) {
              setNotes((current) => current.map((n) => (n.id === targetId ? { ...n, content: full.content } : n)))
            }
          }
        } catch {
          // keep the excerpt if the fetch fails — better than nothing
        } finally {
          if (!cancelled) {
            contentLoadedRef.current.add(targetId)
            setContentVersion((v) => v + 1) // re-run this effect to hydrate
          }
        }
      })()
      return () => {
        cancelled = true
      }
    }

    if (hydratedNoteIdRef.current !== activeNote.id) {
      hydratedNoteIdRef.current = activeNote.id
      setDraftTitle(activeNote.title || '')
      setDraftContent(activeNote.content || '')
      setDraftTagsText(tagsToInput(activeNote.tags || []))
      setDraftStarred(Boolean(activeNote.starred))
      setSaveState('saved')
    }
  }, [activeNote, contentVersion])

  // When the editor flips into edit mode, drop the cursor into the body so the
  // user can start typing immediately (single-pane "click to edit" feel).
  useEffect(() => {
    if (editorMode === 'edit') {
      const el = editorTextareaRef.current
      if (el) {
        el.focus()
      }
    }
  }, [editorMode, activeNoteId])

  const isDirty = Boolean(
    activeNote &&
      (
        draftTitle !== activeNote.title ||
        draftContent !== activeNote.content ||
        draftStarred !== Boolean(activeNote.starred) ||
        !areTagListsEqual(draftTags, normalizeTags(activeNote.tags || []))
      )
  )

  const saveActiveNote = useCallback(async (force: boolean = false) => {
    if (!activeNote) {
      return
    }

    if (!force && !isDirty) {
      return
    }

    const sequence = saveSequenceRef.current + 1
    saveSequenceRef.current = sequence
    setSaveState('saving')

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/notes/${activeNote.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          title: draftTitle,
          content: draftContent,
          folder_id: activeNote.folder_id || null,
          tags: draftTags,
          starred: draftStarred,
        }),
      })

      if (!response.ok) {
        throw new Error('Failed to save note')
      }

      const updated = normalizeIncomingNote((await response.json()) as NoteRecord)

      setNotes((current) =>
        sortNotes(current.map((note) => (note.id === updated.id ? updated : note)))
      )

      if (saveSequenceRef.current === sequence) {
        setSaveState('saved')
      }
    } catch (error) {
      console.error('Failed to save note:', error)
      if (saveSequenceRef.current === sequence) {
        setSaveState('error')
      }
    }
  }, [activeNote, draftContent, draftStarred, draftTags, draftTitle, isDirty])

  useEffect(() => {
    if (!activeNote || !isDirty) {
      return undefined
    }

    const timeoutId = window.setTimeout(() => {
      void saveActiveNote()
    }, 800)

    return () => window.clearTimeout(timeoutId)
  }, [activeNote, isDirty, saveActiveNote])

  const selectNote = useCallback(async (noteId: string) => {
    if (noteId === activeNoteId) {
      return
    }

    if (activeNote && isDirty) {
      await saveActiveNote(true)
    }

    // Mark note as read and refresh unread indicators
    markNoteAsRead(noteId)
    setReadVersion((v) => v + 1)

    setActiveNoteId(noteId)
    setSearchParams({ id: noteId }, { replace: true })
  }, [activeNote, activeNoteId, isDirty, saveActiveNote, setSearchParams])

  const createNote = async () => {
    setCreatePending(true)

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          title: createName.trim() || 'Untitled',
          content: '',
          folder_id: selectedFolderId,
          tags: [],
          starred: false,
        }),
      })

      if (!response.ok) {
        throw new Error('Failed to create note')
      }

      const created = normalizeIncomingNote((await response.json()) as NoteRecord)
      contentLoadedRef.current.add(created.id) // freshly created: body is already complete
      setNotes((current) => sortNotes([created, ...current]))
      setShowCreateNote(false)
      setCreateName('')
      setActiveNoteId(created.id)
      setSearchParams({ id: created.id }, { replace: true })
      setEditorMode('edit')
    } catch (error) {
      console.error('Failed to create note:', error)
      setErrorMessage('Could not create that note.')
    } finally {
      setCreatePending(false)
    }
  }

  const createFolder = async () => {
    setCreatePending(true)

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/folders`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          name: createName.trim(),
          parent_id: selectedFolderId,
        }),
      })

      if (!response.ok) {
        throw new Error('Failed to create folder')
      }

      const created = (await response.json()) as FolderRecord
      setFolders((current) =>
        [...current, created].sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: 'base' }))
      )
      setExpandedFolders((current) => new Set([...current, created.id]))
      setSelectedFolderId(created.id)
      setShowCreateFolder(false)
      setCreateName('')
    } catch (error) {
      console.error('Failed to create folder:', error)
      setErrorMessage('Could not create that folder.')
    } finally {
      setCreatePending(false)
    }
  }

  const moveNoteToFolder = useCallback(async (noteId: string, folderId: string | null) => {
    const noteToMove = notes.find((note) => note.id === noteId)
    if (!noteToMove) {
      return
    }

    const isCurrentNote = activeNote?.id === noteId
    const previousFolderId = noteToMove.folder_id || null

    const payload = {
      title: isCurrentNote ? draftTitle : noteToMove.title,
      content: isCurrentNote ? draftContent : noteToMove.content,
      folder_id: folderId,
      tags: isCurrentNote ? draftTags : normalizeTags(noteToMove.tags || []),
      starred: isCurrentNote ? draftStarred : Boolean(noteToMove.starred),
    }

    if (isCurrentNote) {
      setSaveState('saving')
    }

    setNotes((current) =>
      sortNotes(
        current.map((note) =>
          note.id === noteId ? { ...note, folder_id: folderId } : note
        )
      )
    )

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/notes/${noteId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload),
      })

      if (!response.ok) {
        throw new Error('Failed to move note')
      }

      const updated = normalizeIncomingNote((await response.json()) as NoteRecord)
      setNotes((current) =>
        sortNotes(current.map((note) => (note.id === updated.id ? updated : note)))
      )

      if (isCurrentNote) {
        setSaveState('saved')
      }
    } catch (error) {
      console.error('Failed to move note:', error)
      setNotes((current) =>
        sortNotes(
          current.map((note) =>
            note.id === noteId ? { ...note, folder_id: previousFolderId } : note
          )
        )
      )
      if (isCurrentNote) {
        setSaveState('error')
      }
      setErrorMessage('Could not move that note.')
    }
  }, [activeNote, draftContent, draftStarred, draftTags, draftTitle, notes])

  const deleteCurrentNote = async () => {
    if (!activeNote) {
      return
    }

    const noteTitle = activeNote.title.trim() || 'Untitled'
    const confirmed = window.confirm(`Delete "${noteTitle}"?`)

    if (!confirmed) {
      return
    }

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/notes/${activeNote.id}`, {
        method: 'DELETE',
        credentials: 'include',
      })

      if (!response.ok) {
        throw new Error('Failed to delete note')
      }

      const remaining = notes.filter((note) => note.id !== activeNote.id)
      setNotes(remaining)

      const nextNoteId = remaining[0]?.id || null
      setActiveNoteId(nextNoteId)

      if (nextNoteId) {
        setSearchParams({ id: nextNoteId }, { replace: true })
      } else {
        setSearchParams({}, { replace: true })
      }
    } catch (error) {
      console.error('Failed to delete note:', error)
      setErrorMessage('Could not delete that note.')
    }
  }

  const backlinks = useMemo(() => {
    if (!activeNote) {
      return []
    }

    return notes.filter((note) => note.id !== activeNote.id && (noteMeta.get(note.id)?.outgoingIds || []).includes(activeNote.id))
  }, [activeNote, noteMeta, notes])

  const outgoingLinks = useMemo(() => {
    if (!activeNote) {
      return []
    }

    const linkedIds = Array.from(
      new Set(
        extractWikiLinkTitles(draftContent)
          .map((title) => titleLookup.get(title.toLowerCase())?.id || null)
          .filter(Boolean)
      )
    ) as string[]

    return notes.filter((note) => linkedIds.includes(note.id))
  }, [activeNote, draftContent, notes, titleLookup])

  const allTags = useMemo(
    () =>
      Array.from(
        new Set(
          Array.from(noteMeta.values()).flatMap((meta) => meta.tags)
        )
      ).sort(),
    [noteMeta]
  )

  const graphData = useMemo(() => {
    const degreeMap = new Map<string, number>()
    const graphEdges: GraphEdge[] = []
    const edgeSet = new Set<string>()

    // Wiki-link connections (from note content)
    notes.forEach((note) => {
      const outgoingIds = noteMeta.get(note.id)?.outgoingIds || []

      outgoingIds.forEach((targetId) => {
        const key = [note.id, targetId].sort().join(':')
        if (!edgeSet.has(key)) {
          edgeSet.add(key)
          graphEdges.push({ source: note.id, target: targetId })
          degreeMap.set(note.id, (degreeMap.get(note.id) || 0) + 1)
          degreeMap.set(targetId, (degreeMap.get(targetId) || 0) + 1)
        }
      })
    })

    // Database connections (semantic, temporal, auto-generated)
    const noteIds = new Set(notes.map((n) => n.id))
    dbConnections.forEach(({ source, target }) => {
      if (!noteIds.has(source) || !noteIds.has(target)) return
      const key = [source, target].sort().join(':')
      if (!edgeSet.has(key)) {
        edgeSet.add(key)
        graphEdges.push({ source, target })
        degreeMap.set(source, (degreeMap.get(source) || 0) + 1)
        degreeMap.set(target, (degreeMap.get(target) || 0) + 1)
      }
    })

    const graphNodes: GraphNode[] = notes.map((note) => ({
      id: note.id,
      title: note.title.trim() || 'Untitled',
      starred: Boolean(note.starred),
      degree: degreeMap.get(note.id) || 0,
    }))

    return { nodes: graphNodes, edges: graphEdges }
  }, [dbConnections, noteMeta, notes])

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const lowerKey = event.key.toLowerCase()

      if ((event.metaKey || event.ctrlKey) && lowerKey === 'p') {
        event.preventDefault()
        startTransition(() => setShowPalette(true))
      }

      if ((event.metaKey || event.ctrlKey) && lowerKey === 'g') {
        event.preventDefault()
        setShowGraph((current) => !current)
      }

      if ((event.metaKey || event.ctrlKey) && lowerKey === 's' && activeNote) {
        event.preventDefault()
        void saveActiveNote(true)
      }

      if (event.key === 'Escape') {
        setShowPalette(false)
      }
    }

    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [activeNote, saveActiveNote])

  const activeMeta = activeNote ? noteMeta.get(activeNote.id) : null
  const starredList = useMemo(
    () => sortNotes(notes.filter((note) => note.starred)).slice(0, 6),
    [notes]
  )
  const folderOptions = useMemo(
    () =>
      folders
        .map((folder) => ({
          id: folder.id,
          label: buildFolderPath(folder.id, folderMap),
        }))
        .sort((left, right) => left.label.localeCompare(right.label, undefined, { sensitivity: 'base' })),
    [folderMap, folders]
  )
  const selectedFolderLabel = selectedFolderId ? buildFolderPath(selectedFolderId, folderMap) : 'Workspace root'

  return (
    <div className={isFocusMode ? 'fixed inset-0 z-[60] bg-[#050b16]' : 'h-full min-h-0'}>
      <div className="flex h-full min-h-0 flex-col overflow-hidden px-4 pb-4 pt-3 sm:px-6 lg:px-8">
        <div className={`flex min-h-0 flex-1 flex-col ${isFocusMode ? 'gap-2' : 'gap-3'}`}>
          {!isFocusMode && (
          <header className="flex flex-wrap items-center gap-x-3 gap-y-2 py-1">
            <h1 className="font-display text-xl font-semibold text-white">Notes</h1>
            <span className="text-xs text-slate-500">
              {notes.length} {notes.length === 1 ? 'note' : 'notes'} · {folders.length}{' '}
              {folders.length === 1 ? 'folder' : 'folders'}
            </span>

            <div className="ml-auto flex flex-wrap items-center gap-1">
              <button
                type="button"
                onClick={() => {
                  setCreateName('')
                  setShowCreateFolder(true)
                  setShowCreateNote(false)
                }}
                className="rounded-lg px-2.5 py-1.5 text-xs text-slate-500 transition-colors hover:text-teal-300"
              >
                + Folder
              </button>
              <button
                type="button"
                onClick={() => setShowGraph((current) => !current)}
                className="rounded-lg px-2.5 py-1.5 text-xs text-slate-500 transition-colors hover:text-teal-300"
              >
                {showGraph ? 'Editor' : 'Graph'}
              </button>
              {!showGraph && (
                <button
                  type="button"
                  onClick={() => setIsFocusMode(true)}
                  className="rounded-lg px-2.5 py-1.5 text-xs text-slate-500 transition-colors hover:text-teal-300"
                >
                  Focus
                </button>
              )}
              {!showGraph && (
                <button
                  type="button"
                  onClick={() => setShowRightPanel((current) => !current)}
                  className="rounded-lg px-2.5 py-1.5 text-xs text-slate-500 transition-colors hover:text-teal-300"
                >
                  {showRightPanel ? 'Hide details' : 'Details'}
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  setCreateName('')
                  setShowCreateNote(true)
                  setShowCreateFolder(false)
                }}
                className="ml-1 inline-flex items-center gap-1.5 rounded-xl bg-teal-400/90 px-3.5 py-2 text-sm font-medium text-slate-950 transition hover:bg-teal-300"
              >
                <PlusIcon className="h-4 w-4" />
                New note
              </button>
            </div>
          </header>
          )}

          {errorMessage && (
            <div className="border-l-2 border-rose-400/70 py-1 pl-4 text-sm text-rose-200">
              {errorMessage}
            </div>
          )}

          {loading ? (
              <div className="flex min-h-[30rem] flex-1 items-center justify-center">
                <div className="flex items-center gap-3 text-sm text-slate-500">
                  <ArrowPathIcon className="h-4 w-4 animate-spin" />
                  Loading your vault...
                </div>
              </div>
            ) : (
                <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden md:flex-row">
                  {!isFocusMode && (
                  <aside className="flex w-full min-h-[14rem] max-h-[40vh] shrink-0 flex-col overflow-hidden border-b border-white/8 pb-3 md:h-full md:max-h-none md:w-72 md:border-b-0 md:border-r md:pb-0 md:pr-4 xl:w-[18rem]">
                    <div className="pb-3">
                      <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 transition-colors focus-within:border-teal-300/30">
                        <MagnifyingGlassIcon className="h-4 w-4 text-slate-500" />
                        <input
                          value={searchQuery}
                          onChange={(event) => setSearchQuery(event.target.value)}
                          placeholder="Search notes/folders"
                          className="w-full bg-transparent text-sm text-slate-200 outline-none placeholder:text-slate-600"
                        />
                        <button
                          type="button"
                          onClick={() => setShowPalette(true)}
                          className="hidden whitespace-nowrap text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600 transition-colors hover:text-teal-300 sm:block"
                        >
                          ⌘P
                        </button>
                      </div>
                    </div>

                    <div className="max-h-28 overflow-y-auto py-2">
                      <div className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Starred</div>
                      {starredList.length === 0 ? (
                        <p className="px-2 text-xs text-slate-600">Star key notes to pin them here.</p>
                      ) : (
                        <div className="space-y-0.5">
                          {starredList.map((note) => (
                            <button
                              key={note.id}
                              type="button"
                              onClick={() => void selectNote(note.id)}
                              className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors ${
                                activeNoteId === note.id
                                  ? 'bg-white/[0.06] text-white'
                                  : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200'
                              }`}
                            >
                              <StarIconSolid className="h-3.5 w-3.5 text-amber-300/80" />
                              <span className="min-w-0 flex-1 truncate">{note.title.trim() || 'Untitled'}</span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="min-h-0 flex-[1.35] overflow-y-auto py-3">
                      <div className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Vault</div>
                      {treeData.rootNotes.length === 0 && treeData.branches.length === 0 ? (
                        <p className="px-2 text-sm text-slate-500">
                          {normalizedQuery ? 'No notes match that search.' : 'Create your first note to get started.'}
                        </p>
                      ) : (
                        <FolderTree
                          branches={treeData.branches}
                          rootNotes={treeData.rootNotes}
                          activeNoteId={activeNoteId}
                          selectedFolderId={selectedFolderId}
                          expandedFolders={expandedFolders}
                          starredNotes={starredNotes}
                          unreadNoteIds={unreadNoteIds}
                          onToggleFolder={(folderId) =>
                            setExpandedFolders((current) => {
                              const next = new Set(current)
                              if (next.has(folderId)) {
                                next.delete(folderId)
                              } else {
                                next.add(folderId)
                              }
                              return next
                            })
                          }
                          onSelectFolder={setSelectedFolderId}
                          onSelectNote={(noteId) => void selectNote(noteId)}
                        />
                      )}
                    </div>

                    <div className="max-h-24 overflow-y-auto pt-2">
                      <div className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Tags</div>
                      <div className="flex flex-wrap gap-1.5 px-2">
                        {allTags.length === 0 ? (
                          <span className="text-xs text-slate-600">Add `#tags` in note text.</span>
                        ) : (
                          allTags.slice(0, 10).map((tag) => (
                            <button
                              key={tag}
                              type="button"
                              onClick={() => setSearchQuery(tag)}
                              className="rounded-full bg-white/[0.06] px-2.5 py-0.5 text-[11px] text-slate-400 transition-colors hover:text-teal-300"
                            >
                              #{tag}
                            </button>
                          ))
                        )}
                      </div>
                    </div>
                  </aside>
                  )}

                  <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
                    {showGraph ? (
                      <div className="flex min-h-[32rem] flex-1 flex-col pl-0 pt-1 md:pl-5">
                        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-3 text-xs text-slate-500">
                          <span>Drag nodes to reorganize · drag empty space to pan · click a node to open it</span>
                          <span className="hidden uppercase tracking-[0.14em] text-slate-600 sm:block">⌘G</span>
                        </div>
                        <div className="flex-1 min-h-[30rem]">
                          <GraphView
                            nodes={graphData.nodes}
                            edges={graphData.edges}
                            activeNoteId={activeNoteId}
                            onSelectNote={(noteId) => void selectNote(noteId)}
                          />
                        </div>
                      </div>
                    ) : activeNote ? (
                      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
                        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                          <div className={isFocusMode ? 'px-6 pb-2 pt-6' : 'px-1 pb-2 pt-4 md:px-5'}>
                            <div className="mx-auto w-full max-w-[75ch]">
                              <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
                                <input
                                  value={draftTitle}
                                  onChange={(event) => setDraftTitle(event.target.value)}
                                  placeholder="Untitled"
                                  className="min-w-0 flex-1 basis-64 bg-transparent font-display text-2xl font-semibold text-white outline-none placeholder:text-slate-600 md:text-3xl"
                                />

                                <div className="flex flex-shrink-0 items-center gap-0.5 pt-1">
                                  {onChatAboutNote && (
                                    <button
                                      type="button"
                                      onClick={() => onChatAboutNote(draftTitle, draftContent)}
                                      className="rounded-lg px-2 py-1.5 text-xs text-slate-500 transition-colors hover:text-teal-300"
                                      title="Discuss this note with Sara"
                                    >
                                      Chat about this
                                    </button>
                                  )}

                                  {editorMode === 'edit' ? (
                                    <button
                                      type="button"
                                      onClick={() => {
                                        void saveActiveNote(false)
                                        setEditorMode('preview')
                                      }}
                                      className="rounded-lg px-2 py-1.5 text-xs text-teal-300 transition-colors hover:text-teal-200"
                                      title="Finish editing (Esc)"
                                    >
                                      Done
                                    </button>
                                  ) : (
                                    <button
                                      type="button"
                                      onClick={() => setEditorMode('edit')}
                                      className="rounded-lg px-2 py-1.5 text-xs text-slate-500 transition-colors hover:text-teal-300"
                                      title="Edit this note"
                                    >
                                      Edit
                                    </button>
                                  )}

                                  <button
                                    type="button"
                                    onClick={() => setDraftStarred((current) => !current)}
                                    className={`rounded-lg p-1.5 transition-colors ${
                                      draftStarred ? 'text-amber-300' : 'text-slate-500 hover:text-amber-300'
                                    }`}
                                    title={draftStarred ? 'Unstar' : 'Star'}
                                    aria-label={draftStarred ? 'Unstar this note' : 'Star this note'}
                                  >
                                    {draftStarred ? (
                                      <StarIconSolid className="h-4 w-4" />
                                    ) : (
                                      <StarIconOutline className="h-4 w-4" />
                                    )}
                                  </button>

                                  <button
                                    type="button"
                                    onClick={() => setIsFocusMode((current) => !current)}
                                    className="rounded-lg p-1.5 text-slate-500 transition-colors hover:text-slate-200"
                                    title={isFocusMode ? 'Exit focus' : 'Focus'}
                                    aria-label={isFocusMode ? 'Exit focus mode' : 'Enter focus mode'}
                                  >
                                    {isFocusMode ? (
                                      <ArrowsPointingInIcon className="h-4 w-4" />
                                    ) : (
                                      <ArrowsPointingOutIcon className="h-4 w-4" />
                                    )}
                                  </button>

                                  <button
                                    type="button"
                                    onClick={() => void deleteCurrentNote()}
                                    className="rounded-lg p-1.5 text-slate-500 transition-colors hover:text-rose-300"
                                    title="Delete note"
                                    aria-label="Delete note"
                                  >
                                    <TrashIcon className="h-4 w-4" />
                                  </button>
                                </div>
                              </div>

                              <div className="mt-1.5 text-xs text-slate-500">
                                {activeMeta?.folderPath || 'Unfiled'} · created {formatShortDate(activeNote.created_at)} ·
                                updated {formatLongDate(activeNote.updated_at)} · {activeMeta?.wordCount || 0} words ·{' '}
                                <span
                                  className={
                                    saveState === 'error'
                                      ? 'text-rose-300'
                                      : saveState === 'saving'
                                      ? 'text-slate-400'
                                      : 'text-slate-500'
                                  }
                                >
                                  {saveState === 'error' ? 'save failed' : saveState === 'saving' ? 'saving…' : 'saved'}
                                </span>
                              </div>
                            </div>
                          </div>

                          <div className={`min-h-0 flex-1 overflow-y-auto ${isFocusMode ? 'px-6 pb-10 pt-2' : 'px-1 pb-10 pt-2 md:px-5'}`}>
                            {editorMode === 'edit' ? (
                              <textarea
                                ref={editorTextareaRef}
                                value={draftContent}
                                onChange={(event) => setDraftContent(event.target.value)}
                                onKeyDown={(event) => {
                                  if (event.key === 'Escape') {
                                    event.preventDefault()
                                    void saveActiveNote(false)
                                    setEditorMode('preview')
                                  }
                                }}
                                placeholder="Write with markdown and [[wiki links]]...  (Esc to preview)"
                                className="mx-auto block h-full min-h-[24rem] w-full max-w-[75ch] resize-none bg-transparent font-mono text-[15px] leading-relaxed text-slate-200 outline-none placeholder:text-slate-600"
                              />
                            ) : (
                              <div
                                onDoubleClick={() => setEditorMode('edit')}
                                title="Double-click to edit"
                                className="mx-auto min-h-[24rem] w-full max-w-[75ch] cursor-text"
                              >
                                {draftContent.trim() ? (
                                  <NoteContent
                                    content={draftContent}
                                    titleLookup={titleLookup}
                                    onSelectNote={(noteId) => void selectNote(noteId)}
                                  />
                                ) : (
                                  <button
                                    type="button"
                                    onClick={() => setEditorMode('edit')}
                                    className="text-left text-sm text-slate-500 transition-colors hover:text-teal-300"
                                  >
                                    This note is empty — click to start writing.
                                  </button>
                                )}
                              </div>
                            )}
                          </div>
                        </div>

                        {showRightPanel && !isFocusMode && (
                          <aside className="w-full max-h-[34vh] overflow-y-auto border-t border-white/8 py-4 md:max-h-none md:w-72 md:border-l md:border-t-0 md:py-2 md:pl-5">
                            <div className="space-y-8">
                              <section>
                                <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Properties</div>
                                <div className="space-y-2 text-sm">
                                  <div className="flex items-center justify-between gap-3">
                                    <span className="text-slate-500">Path</span>
                                    <span className="max-w-[10rem] truncate text-right text-slate-200">{activeMeta?.folderPath || 'Unfiled'}</span>
                                  </div>
                                  <div className="flex items-center justify-between gap-3">
                                    <span className="text-slate-500">Words</span>
                                    <span className="text-slate-200">{activeMeta?.wordCount || 0}</span>
                                  </div>
                                  <div className="flex items-center justify-between gap-3">
                                    <span className="text-slate-500">Outgoing</span>
                                    <span className="text-slate-200">{outgoingLinks.length}</span>
                                  </div>
                                  <div className="flex items-center justify-between gap-3">
                                    <span className="text-slate-500">Backlinks</span>
                                    <span className="text-slate-200">{backlinks.length}</span>
                                  </div>
                                  <div className="pt-2">
                                    <label className="block text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                                      Move to
                                    </label>
                                    <select
                                      value={activeNote.folder_id || ''}
                                      onChange={(event) => void moveNoteToFolder(activeNote.id, event.target.value || null)}
                                      className="mt-2 w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-300 outline-none transition focus:border-teal-300/30"
                                    >
                                      <option value="">Workspace root</option>
                                      {folderOptions.map((folder) => (
                                        <option key={folder.id} value={folder.id}>
                                          {folder.label}
                                        </option>
                                      ))}
                                    </select>
                                  </div>
                                </div>
                              </section>

                              <section>
                                <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Tags</div>
                                <input
                                  value={draftTagsText}
                                  onChange={(event) => setDraftTagsText(event.target.value)}
                                  placeholder="architecture, memory, research"
                                  className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-300 outline-none transition focus:border-teal-300/30 placeholder:text-slate-600"
                                />
                                <div className="mt-3 flex flex-wrap gap-1.5">
                                  {draftTags.length === 0 ? (
                                    <span className="text-xs text-slate-600">No saved tags yet.</span>
                                  ) : (
                                    draftTags.map((tag) => (
                                      <button
                                        key={tag}
                                        type="button"
                                        onClick={() => setSearchQuery(tag)}
                                        className="rounded-full bg-white/[0.06] px-2.5 py-0.5 text-[11px] text-slate-400 transition-colors hover:text-teal-300"
                                      >
                                        #{tag}
                                      </button>
                                    ))
                                  )}
                                </div>
                              </section>

                              <section>
                                <div className="mb-3 flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                                  <span>Backlinks</span>
                                  <span>{backlinks.length}</span>
                                </div>
                                <div className="space-y-0.5">
                                  {backlinks.length === 0 ? (
                                    <p className="text-xs text-slate-600">No backlinks yet.</p>
                                  ) : (
                                    backlinks.map((note) => (
                                      <button
                                        key={note.id}
                                        type="button"
                                        onClick={() => void selectNote(note.id)}
                                        className="w-full rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-white/[0.04]"
                                      >
                                        <div className="truncate text-sm text-slate-300">{note.title.trim() || 'Untitled'}</div>
                                        <div className="truncate text-xs text-slate-600">{noteMeta.get(note.id)?.folderPath || 'Unfiled'}</div>
                                      </button>
                                    ))
                                  )}
                                </div>
                              </section>

                              <section>
                                <div className="mb-3 flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                                  <span>Outgoing</span>
                                  <span>{outgoingLinks.length}</span>
                                </div>
                                <div className="space-y-0.5">
                                  {outgoingLinks.length === 0 ? (
                                    <p className="text-xs text-slate-600">Add `[[Note Title]]` links to connect notes.</p>
                                  ) : (
                                    outgoingLinks.map((note) => (
                                      <button
                                        key={note.id}
                                        type="button"
                                        onClick={() => void selectNote(note.id)}
                                        className="w-full rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-white/[0.04]"
                                      >
                                        <div className="truncate text-sm text-slate-300">{note.title.trim() || 'Untitled'}</div>
                                        <div className="truncate text-xs text-slate-600">{noteMeta.get(note.id)?.folderPath || 'Unfiled'}</div>
                                      </button>
                                    ))
                                  )}
                                </div>
                              </section>
                            </div>
                          </aside>
                        )}
                      </div>
                    ) : (
                      <div className="flex flex-1 items-center justify-center p-8 text-center">
                        <p className="text-sm text-slate-500">Your vault is empty — create a note to get started.</p>
                      </div>
                    )}
                  </main>
                </div>
            )}
          </div>
        </div>
      {showPalette && (
        <CommandPalette
          notes={notes}
          noteMeta={noteMeta}
          onClose={() => setShowPalette(false)}
          onSelect={(noteId) => void selectNote(noteId)}
        />
      )}

      {showCreateNote && (
        <CreateDialog
          kind="note"
          value={createName}
          parentLabel={selectedFolderLabel}
          pending={createPending}
          onChange={setCreateName}
          onClose={() => {
            setShowCreateNote(false)
            setCreateName('')
          }}
          onSubmit={() => void createNote()}
        />
      )}

      {showCreateFolder && (
        <CreateDialog
          kind="folder"
          value={createName}
          parentLabel={selectedFolderLabel}
          pending={createPending}
          onChange={setCreateName}
          onClose={() => {
            setShowCreateFolder(false)
            setCreateName('')
          }}
          onSubmit={() => void createFolder()}
        />
      )}
    </div>
  )
}
