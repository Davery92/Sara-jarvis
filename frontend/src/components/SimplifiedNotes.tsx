import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../config'
import MarkdownRenderer from './MarkdownRenderer'

interface Note {
  id: number
  title: string
  content: string
  created_at: string
  updated_at: string
  folder_id?: number
}

interface SimplifiedNotesProps {
  notes: Note[]
  setNotes: React.Dispatch<React.SetStateAction<Note[]>>
  editingNote: number | null
  setEditingNote: React.Dispatch<React.SetStateAction<number | null>>
  editNoteContent: string
  setEditNoteContent: React.Dispatch<React.SetStateAction<string>>
  editNoteTitle: string
  setEditNoteTitle: React.Dispatch<React.SetStateAction<string>>
}

export default function SimplifiedNotes({
  notes,
  setNotes,
  editingNote,
  setEditingNote,
  editNoteContent,
  setEditNoteContent,
  editNoteTitle,
  setEditNoteTitle
}: SimplifiedNotesProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [noteMode, setNoteMode] = useState<'edit' | 'view'>('edit')

  const currentNote = editingNote ? notes.find(n => n.id === editingNote) : null

  const createNewNote = async () => {
    const title = prompt('Note title:')
    if (title) {
      try {
        const response = await fetch(`${APP_CONFIG.apiUrl}/notes`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ title, content: '' })
        })
        if (response.ok) {
          const note = await response.json()
          setNotes(prev => [note, ...prev])
          setEditingNote(note.id)
          setEditNoteTitle(note.title || '')
          setEditNoteContent(note.content || '')
        }
      } catch (error) {
        console.error('Failed to create note:', error)
      }
    }
  }

  const saveNote = async () => {
    if (!editingNote) return
    
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/notes/${editingNote}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ 
          title: editNoteTitle, 
          content: editNoteContent 
        })
      })
      if (response.ok) {
        const updatedNote = await response.json()
        setNotes(prev => prev.map(note => 
          note.id === editingNote ? updatedNote : note
        ))
      }
    } catch (error) {
      console.error('Failed to save note:', error)
    }
  }

  // Auto-save when content changes
  useEffect(() => {
    if (editingNote && (editNoteContent || editNoteTitle)) {
      const timeoutId = setTimeout(saveNote, 1000)
      return () => clearTimeout(timeoutId)
    }
  }, [editNoteContent, editNoteTitle])

  // Filter notes based on search
  const filteredNotes = notes.filter(note => 
    note.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    note.content.toLowerCase().includes(searchQuery.toLowerCase())
  )

  return (
    <div className="flex h-screen w-full bg-[#18181b] text-[#f8fafc]">
      {/* Left Sidebar */}
      <aside className="flex w-64 flex-col border-r border-[#3f3f46] p-4">
        <div className="mb-6 flex items-center gap-2">
          <div className="h-8 w-8 bg-[#0d7ff2] rounded flex items-center justify-center">
            <span className="text-white font-bold text-sm">S</span>
          </div>
          <h1 className="text-xl font-bold">Notes</h1>
        </div>

        <button 
          onClick={createNewNote}
          className="mb-4 flex w-full items-center justify-center gap-2 rounded-md bg-[#0d7ff2] py-2 font-semibold text-[#f8fafc] hover:bg-[#0c6fd1]"
        >
          <span className="material-symbols-outlined">add</span>
          New Note
        </button>

        {/* Notes List */}
        <div className="flex-1 overflow-y-auto">
          <div className="space-y-1">
            {filteredNotes.map(note => (
              <div 
                key={note.id}
                className={`group relative rounded p-2 text-sm hover:bg-[#27272a] ${
                  editingNote === note.id ? 'bg-[#27272a]' : ''
                }`}
              >
                <div 
                  onClick={() => {
                    setEditingNote(note.id)
                    setEditNoteTitle(note.title || '')
                    setEditNoteContent(note.content || '')
                  }}
                  className="cursor-pointer"
                >
                  <div className="font-medium truncate pr-8">
                    {note.title || 'Untitled'}
                  </div>
                  <div className="text-[#a1a1aa] text-xs truncate">
                    {note.content.substring(0, 50)}...
                  </div>
                </div>
                <button
                  onClick={async (e) => {
                    e.stopPropagation()
                    if (window.confirm(`Are you sure you want to delete "${note.title || 'Untitled'}"?`)) {
                      try {
                        const { apiClient } = await import('../api/client')
                        await apiClient.deleteNote(note.id.toString())
                        setNotes(prev => prev.filter(n => n.id !== note.id))
                        if (editingNote === note.id) {
                          setEditingNote(null)
                          setEditNoteTitle('')
                          setEditNoteContent('')
                        }
                      } catch (error) {
                        console.error('Failed to delete note:', error)
                        alert('Failed to delete note. Please try again.')
                      }
                    }
                  }}
                  className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-600/20 text-red-400 hover:text-red-300 transition-all duration-200"
                  title="Delete note"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex flex-1 flex-col">
        {/* Header */}
        <header className="flex h-14 items-center border-b border-[#3f3f46] px-6">
          <div className="relative w-full max-w-md">
            <svg className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#a1a1aa]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input 
              className="w-full rounded-md border-none bg-[#3f3f46] pl-10 pr-4 py-2 text-sm text-[#f8fafc] placeholder:text-[#a1a1aa] focus:ring-2 focus:ring-[#0d7ff2] focus:ring-offset-2 focus:ring-offset-[#18181b]" 
              type="text" 
              placeholder="Search notes..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </header>

        <div className="flex-1 p-6">
          {editingNote ? (
            <div className="rounded-lg border border-[#3f3f46] bg-[#27272a] h-full flex flex-col">
              {/* Title and Mode Toggle */}
              <div className="p-4 relative">
                <input 
                  className="w-full resize-none border-none bg-transparent text-lg font-medium text-[#f8fafc] placeholder:text-[#a1a1aa] focus:outline-none pr-20" 
                  placeholder="Note title..."
                  value={editNoteTitle}
                  onChange={(e) => setEditNoteTitle(e.target.value)}
                />
                
                {/* Mode Toggle and Delete */}
                <div className="absolute right-4 top-1/2 -translate-y-1/2 flex items-center gap-2">
                  {/* View/Edit Toggle */}
                  <div className="flex bg-[#18181b] border border-[#3f3f46] rounded">
                    <button
                      onClick={() => setNoteMode('view')}
                      className={`px-2 py-1 text-xs rounded-l ${
                        noteMode === 'view' 
                          ? 'bg-[#0d7ff2] text-white' 
                          : 'text-[#a1a1aa] hover:text-[#f8fafc]'
                      }`}
                      title="View mode"
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                      </svg>
                    </button>
                    <button
                      onClick={() => setNoteMode('edit')}
                      className={`px-2 py-1 text-xs rounded-r ${
                        noteMode === 'edit' 
                          ? 'bg-[#0d7ff2] text-white' 
                          : 'text-[#a1a1aa] hover:text-[#f8fafc]'
                      }`}
                      title="Edit mode"
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                      </svg>
                    </button>
                  </div>
                  
                  {/* Delete Button */}
                  <button
                    onClick={async () => {
                      if (window.confirm(`Are you sure you want to delete "${editNoteTitle || 'Untitled'}"?`)) {
                        try {
                          const { apiClient } = await import('../api/client')
                          await apiClient.deleteNote(editingNote!.toString())
                          setNotes(prev => prev.filter(n => n.id !== editingNote))
                          setEditingNote(null)
                          setEditNoteTitle('')
                          setEditNoteContent('')
                        } catch (error) {
                          console.error('Failed to delete note:', error)
                          alert('Failed to delete note. Please try again.')
                        }
                      }
                    }}
                    className="p-1 rounded hover:bg-red-600/20 text-red-400 hover:text-red-300 transition-colors duration-200"
                    title="Delete note"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              </div>
              
              {/* Content */}
              <div className="border-t border-[#3f3f46] p-4 flex-1 relative">
                {noteMode === 'edit' ? (
                  <textarea 
                    className="absolute inset-0 m-4 resize-none border-none bg-transparent text-sm text-[#f8fafc] placeholder:text-[#a1a1aa] focus:outline-none" 
                    placeholder="Start typing your notes here..."
                    value={editNoteContent}
                    onChange={(e) => setEditNoteContent(e.target.value)}
                  />
                ) : (
                  <div 
                    className="absolute inset-0 m-4 overflow-y-auto border-none bg-transparent text-sm text-[#f8fafc] focus:outline-none"
                    style={{ fontFamily: 'inherit' }}
                  >
                    <MarkdownRenderer 
                      content={editNoteContent || 'No content yet. Switch to edit mode to add content.'}
                      className=""
                    />
                  </div>
                )}
              </div>
              
              {/* Footer */}
              <div className="border-t border-[#3f3f46] px-4 py-2">
                <p className="text-xs text-[#a1a1aa]">
                  Last edited: {currentNote ? new Date(currentNote.updated_at).toLocaleString() : ''}
                </p>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-full bg-[#27272a] rounded-lg border border-[#3f3f46]">
              <div className="text-center">
                <span className="material-symbols-outlined text-6xl text-[#a1a1aa] mb-4 block">description</span>
                <h3 className="text-lg font-medium mb-2">Select a note to edit</h3>
                <p className="text-[#a1a1aa]">Choose a note from the sidebar or create a new one</p>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}