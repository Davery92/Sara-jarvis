import { useState, useMemo } from 'react'
import { X, Search, FileText, Loader2 } from 'lucide-react'
import { useNotes } from '../hooks/useNotes'
import { useCanvasStore } from '../store/canvasStore'

export default function NotesPicker() {
  const { setNotesPickerOpen, openNoteWindow } = useCanvasStore()
  const { data: notes, isLoading, error } = useNotes()
  const [search, setSearch] = useState('')

  // Filter notes by search
  const filteredNotes = useMemo(() => {
    if (!notes) return []
    if (!search.trim()) return notes

    const searchLower = search.toLowerCase()
    return notes.filter(
      (note) =>
        note.title.toLowerCase().includes(searchLower) ||
        note.content.toLowerCase().includes(searchLower)
    )
  }, [notes, search])

  const handleNoteClick = (note: typeof filteredNotes[0]) => {
    openNoteWindow(note.id, note.title, note.content)
  }

  return (
    <div className="absolute left-0 top-0 h-full w-80 bg-canvas-surface border-r border-canvas-border shadow-2xl flex flex-col z-50">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-canvas-border">
        <h2 className="text-lg font-semibold text-white">Notes</h2>
        <button
          onClick={() => setNotesPickerOpen(false)}
          className="w-10 h-10 flex items-center justify-center rounded-lg hover:bg-canvas-elevated text-canvas-muted hover:text-white transition-colors touch-target"
        >
          <X size={20} />
        </button>
      </div>

      {/* Search */}
      <div className="p-4 border-b border-canvas-border">
        <div className="relative">
          <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-canvas-muted" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search notes..."
            className="w-full pl-10 pr-4 py-3 bg-canvas-elevated border border-canvas-border rounded-lg
                       text-white placeholder-canvas-muted
                       focus:outline-none focus:ring-2 focus:ring-accent-blue focus:border-transparent"
          />
        </div>
      </div>

      {/* Notes list */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {isLoading && (
          <div className="flex items-center justify-center py-12">
            <Loader2 size={24} className="animate-spin text-accent-blue" />
          </div>
        )}

        {error && (
          <div className="p-4 text-red-400 text-sm">
            Failed to load notes. Please try again.
          </div>
        )}

        {!isLoading && !error && filteredNotes.length === 0 && (
          <div className="p-4 text-canvas-muted text-sm text-center">
            {search ? 'No notes match your search' : 'No notes yet'}
          </div>
        )}

        {filteredNotes.map((note) => (
          <button
            key={note.id}
            onClick={() => handleNoteClick(note)}
            className="w-full p-4 text-left border-b border-canvas-border hover:bg-canvas-elevated transition-colors"
          >
            <div className="flex items-start gap-3">
              <FileText size={18} className="text-accent-blue flex-shrink-0 mt-0.5" />
              <div className="min-w-0 flex-1">
                <h3 className="text-white font-medium truncate">
                  {note.title || 'Untitled'}
                </h3>
                <p className="text-canvas-muted text-sm line-clamp-2 mt-1">
                  {note.content.slice(0, 100)}
                  {note.content.length > 100 ? '...' : ''}
                </p>
                <p className="text-canvas-muted text-xs mt-2">
                  {new Date(note.updated_at).toLocaleDateString()}
                </p>
              </div>
            </div>
          </button>
        ))}
      </div>

      {/* Footer with count */}
      {notes && (
        <div className="p-3 border-t border-canvas-border text-canvas-muted text-sm text-center">
          {filteredNotes.length} of {notes.length} notes
        </div>
      )}
    </div>
  )
}
