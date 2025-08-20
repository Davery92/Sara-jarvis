import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../config'
import KnowledgeGraph from './KnowledgeGraph'
import TimelineView from './TimelineView'
import MemoryManager from './MemoryManager'
import MarkdownRenderer from './MarkdownRenderer'
import { findBacklinks, findRelatedNotes, getContentLinks } from '../utils/linkParser'
import { detectAndCreateConnections, suggestSemanticConnections } from '../utils/connectionDetector'

interface Note {
  id: number
  title: string
  content: string
  created_at: string
  updated_at: string
  folder_id?: number
}

interface NotesKnowledgeGardenProps {
  notes: Note[]
  setNotes: React.Dispatch<React.SetStateAction<Note[]>>
  editingNote: number | null
  setEditingNote: React.Dispatch<React.SetStateAction<number | null>>
  editNoteContent: string
  setEditNoteContent: React.Dispatch<React.SetStateAction<string>>
  editNoteTitle: string
  setEditNoteTitle: React.Dispatch<React.SetStateAction<string>>
}

export default function NotesKnowledgeGarden({
  notes,
  setNotes,
  editingNote,
  setEditingNote,
  editNoteContent,
  setEditNoteContent,
  editNoteTitle,
  setEditNoteTitle
}: NotesKnowledgeGardenProps) {
  const [currentView, setCurrentView] = useState<'notes' | 'timeline' | 'search' | 'settings' | 'memory'>('notes')
  const [searchQuery, setSearchQuery] = useState('')
  const [backlinks, setBacklinks] = useState<Note[]>([])
  const [relatedNotes, setRelatedNotes] = useState<Note[]>([])
  const [connectionSuggestions, setConnectionSuggestions] = useState<{ note: Note, similarity: number }[]>([])
  const [memoryContext, setMemoryContext] = useState<any[]>([])
  const [loadingMemory, setLoadingMemory] = useState(false)
  const [noteMode, setNoteMode] = useState<'edit' | 'view'>('edit')

  const currentNote = editingNote ? notes.find(n => n.id === editingNote) : null

  // Find backlinks and related notes for current note
  useEffect(() => {
    if (currentNote) {
      // Use our new link parsing utilities
      const foundBacklinks = findBacklinks(currentNote, notes)
      setBacklinks(foundBacklinks)

      // Find semantically related notes
      const related = findRelatedNotes(currentNote, notes, 0.05) // Lower threshold for more results
      setRelatedNotes(related)

      // Get connection suggestions
      suggestSemanticConnections(currentNote.id, notes).then(suggestions => {
        setConnectionSuggestions(suggestions)
      })

      // Fetch related memory episodes
      fetchMemoryContext(currentNote)
    }
  }, [currentNote, notes])

  const fetchMemoryContext = async (note: Note) => {
    if (!note.title && !note.content) return

    setLoadingMemory(true)
    try {
      // Create a search query from note title and key content words
      const searchQuery = note.title || note.content.substring(0, 100)
      
      const response = await fetch(`${APP_CONFIG.apiUrl}/memory/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          query: searchQuery,
          scopes: ['episodes'],
          limit: 5
        })
      })

      if (response.ok) {
        const data = await response.json()
        setMemoryContext(data.results || [])
      }
    } catch (error) {
      console.error('Failed to fetch memory context:', error)
    } finally {
      setLoadingMemory(false)
    }
  }

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

        // Auto-detect and create connections after saving
        const updatedNotes = notes.map(note => 
          note.id === editingNote ? { ...updatedNote, id: parseInt(updatedNote.id) } : note
        )
        detectAndCreateConnections(editingNote, updatedNotes)
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

  return (
    <div className="flex h-screen w-full bg-[#18181b] text-[#f8fafc]">
      {/* Left Sidebar */}
      <aside className="flex w-64 flex-col border-r border-[#3f3f46] p-4">
        <div className="mb-6 flex items-center gap-2">
          <div className="h-8 w-8 bg-[#0d7ff2] rounded flex items-center justify-center">
            <span className="text-white font-bold text-sm">S</span>
          </div>
          <h1 className="text-xl font-bold">Sara Notes</h1>
        </div>

        <nav className="flex flex-col gap-1">
          <button
            onClick={() => setCurrentView('notes')}
            className={`flex items-center justify-center rounded-md px-3 py-2 text-sm font-medium ${
              currentView === 'notes' 
                ? 'bg-[#3f3f46] text-[#f8fafc]' 
                : 'text-[#a1a1aa] hover:bg-[#3f3f46] hover:text-[#f8fafc]'
            }`}
          >
            Notes
          </button>
          
          
          <button
            onClick={() => setCurrentView('timeline')}
            className={`flex items-center justify-center rounded-md px-3 py-2 text-sm font-medium ${
              currentView === 'timeline' 
                ? 'bg-[#3f3f46] text-[#f8fafc]' 
                : 'text-[#a1a1aa] hover:bg-[#3f3f46] hover:text-[#f8fafc]'
            }`}
          >
            Timeline
          </button>
          
          <button
            onClick={() => setCurrentView('search')}
            className={`flex items-center justify-center rounded-md px-3 py-2 text-sm font-medium ${
              currentView === 'search' 
                ? 'bg-[#3f3f46] text-[#f8fafc]' 
                : 'text-[#a1a1aa] hover:bg-[#3f3f46] hover:text-[#f8fafc]'
            }`}
          >
            Search
          </button>
          
          <button
            onClick={() => setCurrentView('settings')}
            className={`flex items-center justify-center rounded-md px-3 py-2 text-sm font-medium ${
              currentView === 'settings' 
                ? 'bg-[#3f3f46] text-[#f8fafc]' 
                : 'text-[#a1a1aa] hover:bg-[#3f3f46] hover:text-[#f8fafc]'
            }`}
          >
            Settings
          </button>
        </nav>

        <button 
          onClick={createNewNote}
          className="mt-auto flex w-full items-center justify-center gap-2 rounded-md bg-[#0d7ff2] py-2 font-semibold text-[#f8fafc] hover:bg-[#0c6fd1]"
        >
          <span className="material-symbols-outlined">add</span>
          New Note
        </button>

        {/* Notes List */}
        <div className="mt-4 flex-1 overflow-y-auto">
          <div className="space-y-1">
            {notes.map(note => (
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

        <div className="flex flex-1">
          {/* Editor */}
          <div className="flex-1 p-6 min-h-0">
            {currentView === 'notes' && editingNote ? (
              <div className="rounded-lg border border-[#3f3f46] bg-[#27272a] h-full flex flex-col min-h-0">
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
            ) : currentView === 'timeline' ? (
              <TimelineView
                notes={notes}
                onItemClick={(item) => {
                  if (item.type === 'note' && item.metadata?.note_id) {
                    const noteId = item.metadata.note_id
                    const note = notes.find(n => n.id === noteId)
                    if (note) {
                      setEditingNote(noteId)
                      setEditNoteTitle(note.title || '')
                      setEditNoteContent(note.content || '')
                      setCurrentView('notes') // Switch to notes view
                    }
                  }
                }}
              />
            ) : currentView === 'settings' ? (
              <div className="space-y-6">
                <div className="bg-[#27272a] rounded-lg border border-[#3f3f46] p-6">
                  <h3 className="text-lg font-medium text-[#f8fafc] mb-4">Knowledge Garden Settings</h3>
                  <div className="space-y-4">
                    <div className="flex items-center justify-between p-3 bg-[#18181b] rounded border border-[#3f3f46]">
                      <div>
                        <h4 className="text-sm font-medium text-[#f8fafc]">Memory Management</h4>
                        <p className="text-xs text-[#a1a1aa]">Curate and manage your AI's episodic memories</p>
                      </div>
                      <button
                        onClick={() => setCurrentView('memory')}
                        className="px-3 py-1 text-sm bg-[#0d7ff2] text-white rounded hover:bg-[#0c6fd1]"
                      >
                        Manage
                      </button>
                    </div>
                    
                    <div className="flex items-center justify-between p-3 bg-[#18181b] rounded border border-[#3f3f46]">
                      <div>
                        <h4 className="text-sm font-medium text-[#f8fafc]">Auto-Connection Detection</h4>
                        <p className="text-xs text-[#a1a1aa]">Automatically detect and create note connections</p>
                      </div>
                      <button
                        onClick={async () => {
                          const { updateAllConnections } = await import('../utils/connectionDetector')
                          updateAllConnections(notes)
                        }}
                        className="px-3 py-1 text-sm bg-[#4ade80] text-white rounded hover:bg-[#16a34a]"
                      >
                        Scan All
                      </button>
                    </div>

                    <div className="flex items-center justify-between p-3 bg-[#18181b] rounded border border-[#3f3f46]">
                      <div>
                        <h4 className="text-sm font-medium text-[#f8fafc]">Knowledge Stats</h4>
                        <p className="text-xs text-[#a1a1aa]">{notes.length} notes in your knowledge garden</p>
                      </div>
                      <div className="text-sm text-[#0d7ff2]">
                        {notes.length} items
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ) : currentView === 'memory' ? (
              <MemoryManager onClose={() => setCurrentView('settings')} />
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

          {/* Right Sidebar - Context Panel */}
          {currentView === 'notes' && editingNote && (
            <aside className="w-72 border-l border-[#3f3f46] p-4">
              <div className="space-y-6">
                {/* Backlinks */}
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-[#a1a1aa]">Backlinks</h3>
                  <div className="space-y-2">
                    {backlinks.length > 0 ? (
                      backlinks.map(note => (
                        <button
                          key={note.id}
                          onClick={() => {
                            setEditingNote(note.id)
                            setEditNoteTitle(note.title || '')
                            setEditNoteContent(note.content || '')
                          }}
                          className="block w-full text-left rounded-md p-2 text-sm text-[#f8fafc] hover:bg-[#3f3f46]"
                        >
                          {note.title || 'Untitled'}
                        </button>
                      ))
                    ) : (
                      <p className="text-xs text-[#a1a1aa]">No backlinks found</p>
                    )}
                  </div>
                </div>

                {/* Related Notes */}
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-[#a1a1aa]">Related Notes</h3>
                  <div className="space-y-2">
                    {relatedNotes.length > 0 ? (
                      relatedNotes.map(note => (
                        <button
                          key={note.id}
                          onClick={() => {
                            setEditingNote(note.id)
                            setEditNoteTitle(note.title || '')
                            setEditNoteContent(note.content || '')
                          }}
                          className="block w-full text-left rounded-md p-2 text-sm text-[#f8fafc] hover:bg-[#3f3f46]"
                        >
                          {note.title || 'Untitled'}
                        </button>
                      ))
                    ) : (
                      <p className="text-xs text-[#a1a1aa]">No related notes found</p>
                    )}
                  </div>
                </div>

                {/* Connection Suggestions */}
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-[#a1a1aa]">Connection Suggestions</h3>
                  <div className="space-y-2">
                    {connectionSuggestions.length > 0 ? (
                      connectionSuggestions.map(({ note, similarity }) => (
                        <div key={note.id} className="flex items-center justify-between p-2 rounded-md bg-[#27272a] border border-[#3f3f46]">
                          <button
                            onClick={() => {
                              setEditingNote(note.id)
                              setEditNoteTitle(note.title || '')
                              setEditNoteContent(note.content || '')
                            }}
                            className="flex-1 text-left text-sm text-[#f8fafc] hover:text-[#0d7ff2]"
                          >
                            {note.title || 'Untitled'}
                          </button>
                          <div className="flex items-center gap-1">
                            <span className="text-xs text-[#a1a1aa]">{Math.round(similarity * 100)}%</span>
                            <button
                              onClick={async () => {
                                if (currentNote) {
                                  const { createManualConnection } = await import('../utils/connectionDetector')
                                  const success = await createManualConnection(currentNote.id, note.id, 'semantic')
                                  if (success) {
                                    // Refresh suggestions by removing this one
                                    setConnectionSuggestions(prev => prev.filter(s => s.note.id !== note.id))
                                  }
                                }
                              }}
                              className="text-xs text-[#0d7ff2] hover:text-[#0c6fd1] px-1"
                              title="Create connection"
                            >
                              +
                            </button>
                          </div>
                        </div>
                      ))
                    ) : (
                      <p className="text-xs text-[#a1a1aa]">No suggestions available</p>
                    )}
                  </div>
                </div>

                {/* Memory Context */}
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-[#a1a1aa]">Memory Context</h3>
                  <div className="space-y-2">
                    {loadingMemory ? (
                      <div className="text-xs text-[#a1a1aa] bg-[#27272a] p-3 rounded border border-[#3f3f46]">
                        <p>Loading memories...</p>
                      </div>
                    ) : memoryContext.length > 0 ? (
                      memoryContext.map((memory, index) => (
                        <div key={index} className="bg-[#27272a] p-3 rounded border border-[#3f3f46]">
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-xs font-medium text-[#0d7ff2]">
                              {memory.metadata?.role || 'Memory'}
                            </span>
                            <span className="text-xs text-[#a1a1aa]">
                              {Math.round(memory.score * 100)}% match
                            </span>
                          </div>
                          <p className="text-xs text-[#f8fafc] line-clamp-3">
                            {memory.text}
                          </p>
                          {memory.metadata?.timestamp && (
                            <p className="text-xs text-[#a1a1aa] mt-1">
                              {new Date(memory.metadata.timestamp).toLocaleDateString()}
                            </p>
                          )}
                        </div>
                      ))
                    ) : (
                      <div className="text-xs text-[#a1a1aa] bg-[#27272a] p-3 rounded border border-[#3f3f46]">
                        <p>No related memories found</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </aside>
          )}
        </div>
      </main>
    </div>
  )
}