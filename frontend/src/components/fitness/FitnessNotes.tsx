import React, { useState, useEffect } from 'react'
import { FileText, Plus, X, Edit2, Trash2 } from 'lucide-react'
import { APP_CONFIG } from '../../config'

interface Note {
  id: string
  title: string
  content: string
  category: string
  created_at: string
  updated_at: string
}

export default function FitnessNotes() {
  const [notes, setNotes] = useState<Note[]>([])
  const [category, setCategory] = useState('all')
  const [showModal, setShowModal] = useState(false)
  const [editingNote, setEditingNote] = useState<Note | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  // Form state
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [noteCategory, setNoteCategory] = useState('general')

  // Fetch notes on mount
  useEffect(() => {
    fetchNotes()
  }, [])

  const fetchNotes = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/notes/search`, {
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        setNotes(data.notes || [])
      }
    } catch (error) {
      console.error('Failed to fetch notes:', error)
    }
  }

  const openNewNoteModal = () => {
    setEditingNote(null)
    setTitle('')
    setContent('')
    setNoteCategory('general')
    setShowModal(true)
  }

  const openEditModal = (note: Note) => {
    setEditingNote(note)
    setTitle(note.title)
    setContent(note.content)
    setNoteCategory(note.category)
    setShowModal(true)
  }

  const closeModal = () => {
    setShowModal(false)
    setEditingNote(null)
    setTitle('')
    setContent('')
    setNoteCategory('general')
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim() || !content.trim()) return

    setIsLoading(true)
    try {
      if (editingNote) {
        // Update existing note
        const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/notes/${editingNote.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ title, content, category: noteCategory })
        })
        if (response.ok) {
          await fetchNotes()
          closeModal()
        }
      } else {
        // Create new note
        const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/notes`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ title, content, category: noteCategory })
        })
        if (response.ok) {
          await fetchNotes()
          closeModal()
        }
      }
    } catch (error) {
      console.error('Failed to save note:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleDelete = async (noteId: string) => {
    if (!confirm('Are you sure you want to delete this note?')) return

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/notes/${noteId}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (response.ok) {
        await fetchNotes()
      }
    } catch (error) {
      console.error('Failed to delete note:', error)
    }
  }

  const filteredNotes = category === 'all'
    ? notes
    : notes.filter(note => note.category === category)

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-2xl font-bold">Fitness Notes</h2>
          <p className="text-gray-400 text-sm mt-1">Document your fitness journey</p>
        </div>
        <button
          onClick={openNewNoteModal}
          className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg flex items-center gap-2 transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Note
        </button>
      </div>

      {/* Category Filter */}
      <div className="mb-6 flex gap-2 flex-wrap">
        {['all', 'nutrition', 'workout', 'goal', 'progress', 'general'].map((cat) => (
          <button
            key={cat}
            onClick={() => setCategory(cat)}
            className={`
              px-4 py-2 rounded-lg text-sm capitalize transition-colors
              ${category === cat
                ? 'bg-purple-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }
            `}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* Notes List */}
      {filteredNotes.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <FileText className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>No notes yet</p>
          <p className="text-sm mt-1">Create your first fitness note</p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredNotes.map((note) => (
            <div key={note.id} className="bg-gray-800 rounded-lg p-4 hover:bg-gray-750 transition-colors">
              <div className="flex justify-between items-start mb-2">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="text-lg font-semibold">{note.title}</h3>
                    <span className="px-2 py-0.5 bg-purple-600/20 text-purple-400 text-xs rounded capitalize">
                      {note.category}
                    </span>
                  </div>
                  <p className="text-gray-400 text-sm whitespace-pre-wrap">{note.content}</p>
                </div>
                <div className="flex gap-2 ml-4">
                  <button
                    onClick={() => openEditModal(note)}
                    className="p-2 hover:bg-gray-700 rounded-lg transition-colors"
                    title="Edit note"
                  >
                    <Edit2 className="w-4 h-4 text-gray-400" />
                  </button>
                  <button
                    onClick={() => handleDelete(note.id)}
                    className="p-2 hover:bg-gray-700 rounded-lg transition-colors"
                    title="Delete note"
                  >
                    <Trash2 className="w-4 h-4 text-red-400" />
                  </button>
                </div>
              </div>
              <div className="text-xs text-gray-500 mt-2">
                {new Date(note.created_at).toLocaleDateString()}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg max-w-2xl w-full p-6">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-xl font-bold">
                {editingNote ? 'Edit Note' : 'New Fitness Note'}
              </h3>
              <button onClick={closeModal} className="p-2 hover:bg-gray-700 rounded-lg">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSubmit}>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-2">Title</label>
                  <input
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-purple-500 focus:outline-none"
                    placeholder="Note title..."
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Category</label>
                  <select
                    value={noteCategory}
                    onChange={(e) => setNoteCategory(e.target.value)}
                    className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-purple-500 focus:outline-none capitalize"
                  >
                    {['nutrition', 'workout', 'goal', 'progress', 'general'].map((cat) => (
                      <option key={cat} value={cat} className="capitalize">{cat}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Content</label>
                  <textarea
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    className="w-full px-4 py-2 bg-gray-900 rounded-lg border border-gray-700 focus:border-purple-500 focus:outline-none min-h-[200px]"
                    placeholder="Write your note..."
                    required
                  />
                </div>
              </div>

              <div className="flex gap-3 mt-6">
                <button
                  type="submit"
                  disabled={isLoading}
                  className="flex-1 px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isLoading ? 'Saving...' : editingNote ? 'Update Note' : 'Create Note'}
                </button>
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg font-medium"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
