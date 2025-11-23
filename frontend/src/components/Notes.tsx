import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../config'
import MarkdownRenderer from './MarkdownRenderer'
import { parseWikiLinks } from '../utils/linkParser'

interface Note {
  id: number
  title: string
  content: string
  created_at: string
  updated_at: string
  folder_id?: number
}

interface Folder {
  id: number
  name: string
  parent_id?: number
}

interface NoteConnection {
  id: number
  source_note_id: number
  target_note_id: number
  connection_type: string
  strength: number
  auto_generated: boolean
}

interface NotesProps {
  notes: Note[]
  setNotes: React.Dispatch<React.SetStateAction<Note[]>>
  editingNote: number | null
  setEditingNote: React.Dispatch<React.SetStateAction<number | null>>
  editNoteContent: string
  setEditNoteContent: React.Dispatch<React.SetStateAction<string>>
  editNoteTitle: string
  setEditNoteTitle: React.Dispatch<React.SetStateAction<string>>
}

export default function Notes({
  notes,
  setNotes,
  editingNote,
  setEditingNote,
  editNoteContent,
  setEditNoteContent,
  editNoteTitle,
  setEditNoteTitle
}: NotesProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [noteMode, setNoteMode] = useState<'edit' | 'view'>('edit')
  const [folders, setFolders] = useState<Folder[]>([])
  const [selectedFolder, setSelectedFolder] = useState<number | null>(null)
  const [backlinks, setBacklinks] = useState<Note[]>([])
  const [showBacklinks, setShowBacklinks] = useState(true)
  const [showNewNoteDialog, setShowNewNoteDialog] = useState(false)
  const [showNewFolderDialog, setShowNewFolderDialog] = useState(false)
  const [newNoteName, setNewNoteName] = useState('')
  const [newFolderName, setNewFolderName] = useState('')
  const [folderToDelete, setFolderToDelete] = useState<number | null>(null)
  const [noteToDelete, setNoteToDelete] = useState<Note | null>(null)
  const [expandedFolders, setExpandedFolders] = useState<Set<number>>(new Set())
  const [draggedNoteId, setDraggedNoteId] = useState<number | null>(null)
  const [dropTargetFolderId, setDropTargetFolderId] = useState<number | string | null>(null)

  const currentNote = editingNote ? notes.find(n => n.id === editingNote) : null

  const toggleFolderExpand = (folderId: number) => {
    setExpandedFolders(prev => {
      const newSet = new Set(prev)
      if (newSet.has(folderId)) {
        newSet.delete(folderId)
      } else {
        newSet.add(folderId)
      }
      return newSet
    })
  }

  // Load folders
  useEffect(() => {
    loadFolders()
  }, [])

  // Load backlinks when note changes
  useEffect(() => {
    if (editingNote) {
      loadBacklinks(editingNote)
    } else {
      setBacklinks([])
    }
  }, [editingNote])

  const loadFolders = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/folders`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setFolders(data)
      }
    } catch (error) {
      console.error('Failed to load folders:', error)
    }
  }

  const loadBacklinks = async (noteId: number) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/notes/${noteId}/backlinks`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setBacklinks(data)
      }
    } catch (error) {
      console.error('Failed to load backlinks:', error)
      setBacklinks([])
    }
  }

  const createNewNote = async () => {
    console.log('createNewNote clicked')
    setShowNewNoteDialog(true)
    setNewNoteName('')
  }

  const submitNewNote = async () => {
    if (!newNoteName.trim()) return
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          title: newNoteName,
          content: '',
          folder_id: selectedFolder
        })
      })
      if (response.ok) {
        const note = await response.json()
        setNotes(prev => [note, ...prev])
        setEditingNote(note.id)
        setEditNoteTitle(note.title || '')
        setEditNoteContent(note.content || '')
        setShowNewNoteDialog(false)
        setNewNoteName('')
      }
    } catch (error) {
      console.error('Failed to create note:', error)
    }
  }

  const createNewFolder = async () => {
    console.log('createNewFolder clicked')
    setShowNewFolderDialog(true)
    setNewFolderName('')
  }

  const submitNewFolder = async () => {
    if (!newFolderName.trim()) return
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/folders`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ name: newFolderName, parent_id: selectedFolder })
      })
      if (response.ok) {
        const folder = await response.json()
        setFolders(prev => [...prev, folder])
        setShowNewFolderDialog(false)
        setNewFolderName('')
      }
    } catch (error) {
      console.error('Failed to create folder:', error)
    }
  }

  const deleteFolder = async (folderId: number, e: React.MouseEvent) => {
    e.stopPropagation()
    setFolderToDelete(folderId)
  }

  const confirmDeleteFolder = async () => {
    if (!folderToDelete) return
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/folders/${folderToDelete}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      if (response.ok) {
        setFolders(prev => prev.filter(f => f.id !== folderToDelete))
        if (selectedFolder === folderToDelete) {
          setSelectedFolder(null)
        }
        loadFolders()
      }
    } catch (error) {
      console.error('Failed to delete folder:', error)
    }
    setFolderToDelete(null)
  }

  const confirmDeleteNote = async () => {
    if (!noteToDelete) return
    try {
      await fetch(`${APP_CONFIG.apiUrl}/notes/${noteToDelete.id}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      setNotes(prev => prev.filter(n => n.id !== noteToDelete.id))
      if (editingNote === noteToDelete.id) {
        setEditingNote(null)
        setEditNoteTitle('')
        setEditNoteContent('')
      }
    } catch (error) {
      console.error('Failed to delete note:', error)
    }
    setNoteToDelete(null)
  }

  const moveNoteToFolder = async (noteId: number, folderId: number | null) => {
    try {
      const note = notes.find(n => n.id === noteId)
      if (!note) return

      const response = await fetch(`${APP_CONFIG.apiUrl}/notes/${noteId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          title: note.title,
          content: note.content,
          folder_id: folderId
        })
      })
      if (response.ok) {
        const updatedNote = await response.json()
        setNotes(prev => prev.map(n => n.id === noteId ? updatedNote : n))
      }
    } catch (error) {
      console.error('Failed to move note:', error)
    }
  }

  const handleDragStart = (e: React.DragEvent, noteId: number) => {
    setDraggedNoteId(noteId)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', noteId.toString())
  }

  const handleDragEnd = () => {
    setDraggedNoteId(null)
    setDropTargetFolderId(null)
  }

  const handleDragOver = (e: React.DragEvent, folderId: number | string) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDropTargetFolderId(folderId)
  }

  const handleDragLeave = () => {
    setDropTargetFolderId(null)
  }

  const handleDrop = async (e: React.DragEvent, folderId: number | null) => {
    e.preventDefault()
    if (draggedNoteId !== null) {
      await moveNoteToFolder(draggedNoteId, folderId)
    }
    setDraggedNoteId(null)
    setDropTargetFolderId(null)
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

        // Auto-detect and create note connections
        detectAndCreateConnections(editingNote, editNoteContent)
      }
    } catch (error) {
      console.error('Failed to save note:', error)
    }
  }

  const detectAndCreateConnections = async (noteId: number, content: string) => {
    // Parse [[Note Title]] links from content
    const parsedLinks = parseWikiLinks(content, notes)

    // Create connections for each linked note
    for (const link of parsedLinks) {
      const targetNote = notes.find(n => n.title === link.noteTitle)
      if (targetNote) {
        try {
          await fetch(`${APP_CONFIG.apiUrl}/notes/${noteId}/connections`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
              target_note_id: targetNote.id,
              connection_type: 'reference',
              auto_generated: true
            })
          })
        } catch (error) {
          console.error('Failed to create connection:', error)
        }
      }
    }
  }

  // Auto-save when content changes
  useEffect(() => {
    if (editingNote && (editNoteContent || editNoteTitle)) {
      const timeoutId = setTimeout(saveNote, 1000)
      return () => clearTimeout(timeoutId)
    }
  }, [editNoteContent, editNoteTitle])

  // Filter notes based on search and folder
  const filteredNotes = notes.filter(note => {
    const matchesSearch = note.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      note.content.toLowerCase().includes(searchQuery.toLowerCase())
    const matchesFolder = selectedFolder === null || note.folder_id === selectedFolder
    return matchesSearch && matchesFolder
  })

  // Get folder hierarchy
  const getFolderPath = (folderId: number | null): string => {
    if (!folderId) return ''
    const folder = folders.find(f => f.id === folderId)
    if (!folder) return ''
    const parentPath = folder.parent_id ? getFolderPath(folder.parent_id) + ' / ' : ''
    return parentPath + folder.name
  }

  return (
    <div className="flex h-screen w-full bg-[#18181b] text-[#f8fafc]">
      {/* Left Sidebar - Folder Tree & Notes List */}
      <aside className="flex w-64 flex-col border-r border-[#3f3f46] p-4">
        <div className="mb-6 flex items-center gap-2">
          <div className="h-8 w-8 bg-[#0d7ff2] rounded flex items-center justify-center">
            <span className="text-white font-bold text-sm">📝</span>
          </div>
          <h1 className="text-xl font-bold">Notes</h1>
        </div>

        <div className="mb-4 flex gap-2">
          <button
            onClick={createNewNote}
            className="flex-1 flex items-center justify-center gap-1 rounded-md bg-[#0d7ff2] py-2 text-sm font-semibold text-[#f8fafc] hover:bg-[#0c6fd1]"
            title="New Note"
          >
            <span className="material-icons text-sm">add</span>
            Note
          </button>
          <button
            onClick={createNewFolder}
            className="flex-1 flex items-center justify-center gap-1 rounded-md bg-[#27272a] py-2 text-sm font-semibold text-[#f8fafc] hover:bg-[#3f3f46]"
            title="New Folder"
          >
            <span className="material-icons text-sm">create_new_folder</span>
            Folder
          </button>
        </div>

        {/* Selected Folder Indicator */}
        {selectedFolder && (
          <div className="mb-3 flex items-center justify-between bg-[#0d7ff2]/20 rounded px-3 py-2">
            <div className="text-xs">
              <span className="text-[#a1a1aa]">Creating in:</span>
              <div className="font-medium text-[#0d7ff2]">
                {folders.find(f => f.id === selectedFolder)?.name || 'Unknown'}
              </div>
            </div>
            <button
              onClick={() => setSelectedFolder(null)}
              className="text-[#a1a1aa] hover:text-white"
              title="Clear selection (create at root)"
            >
              <span className="material-icons text-sm">close</span>
            </button>
          </div>
        )}

        {/* Hierarchical Folder Tree */}
        <div className="mb-4 flex-1 overflow-y-auto">
          <div className="text-xs font-semibold text-[#a1a1aa] mb-2 uppercase">Files</div>
          <div className="space-y-1">
            {/* Render folder tree recursively */}
            {(() => {
              const renderFolder = (folder: Folder, depth: number = 0) => {
                const isExpanded = expandedFolders.has(folder.id)
                const subFolders = folders.filter(f => f.parent_id === folder.id)
                const folderNotes = notes.filter(n => n.folder_id === folder.id)
                const hasChildren = subFolders.length > 0 || folderNotes.length > 0

                return (
                  <div key={folder.id}>
                    <div
                      className={`group w-full text-left rounded p-2 text-sm hover:bg-[#27272a] flex items-center gap-1 transition-colors ${
                        dropTargetFolderId === folder.id ? 'bg-[#0d7ff2]/30 ring-2 ring-[#0d7ff2]' : ''
                      }`}
                      style={{ paddingLeft: `${depth * 16 + 8}px` }}
                      onDragOver={(e) => handleDragOver(e, folder.id)}
                      onDragLeave={handleDragLeave}
                      onDrop={(e) => handleDrop(e, folder.id)}
                    >
                      <button
                        onClick={() => hasChildren && toggleFolderExpand(folder.id)}
                        className="w-5 flex-shrink-0"
                      >
                        {hasChildren && (
                          <span className="material-icons text-xs text-[#a1a1aa]">
                            {isExpanded ? 'expand_more' : 'chevron_right'}
                          </span>
                        )}
                      </button>
                      <button
                        onClick={() => setSelectedFolder(folder.id)}
                        className="flex-1 flex items-center gap-2 text-left"
                      >
                        <span className="material-icons text-sm">
                          {isExpanded ? 'folder_open' : 'folder'}
                        </span>
                        {folder.name}
                      </button>
                      <button
                        onClick={(e) => deleteFolder(folder.id, e)}
                        className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-300"
                        title="Delete folder"
                      >
                        <span className="material-icons text-sm">delete</span>
                      </button>
                    </div>
                    {isExpanded && (
                      <>
                        {subFolders.map(sf => renderFolder(sf, depth + 1))}
                        {folderNotes
                          .filter(note =>
                            note.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
                            note.content.toLowerCase().includes(searchQuery.toLowerCase())
                          )
                          .map(note => (
                            <div
                              key={note.id}
                              draggable
                              onDragStart={(e) => handleDragStart(e, note.id)}
                              onDragEnd={handleDragEnd}
                              onClick={() => {
                                setEditingNote(note.id)
                                setEditNoteTitle(note.title || '')
                                setEditNoteContent(note.content || '')
                              }}
                              className={`group relative cursor-pointer rounded p-2 text-sm hover:bg-[#27272a] ${
                                editingNote === note.id ? 'bg-[#27272a] border-l-2 border-[#0d7ff2]' : ''
                              } ${draggedNoteId === note.id ? 'opacity-50' : ''}`}
                              style={{ paddingLeft: `${(depth + 1) * 16 + 8}px` }}
                            >
                              <div className="flex items-center gap-2">
                                <span className="material-icons text-sm text-[#a1a1aa] cursor-grab">drag_indicator</span>
                                <span className="material-icons text-sm text-[#a1a1aa]">description</span>
                                <span className="font-medium truncate pr-8">{note.title || 'Untitled'}</span>
                              </div>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setNoteToDelete(note)
                                }}
                                className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-600/20 text-red-400 transition-all"
                              >
                                <span className="material-icons text-sm">delete</span>
                              </button>
                            </div>
                          ))}
                      </>
                    )}
                  </div>
                )
              }

              return (
                <>
                  {folders.filter(f => !f.parent_id).map(folder => renderFolder(folder, 0))}
                  {/* Root drop zone */}
                  <div
                    className={`mt-2 rounded p-2 text-xs text-[#a1a1aa] border border-dashed transition-colors ${
                      dropTargetFolderId === 'root' ? 'border-[#0d7ff2] bg-[#0d7ff2]/20' : 'border-[#3f3f46]'
                    }`}
                    onDragOver={(e) => handleDragOver(e, 'root')}
                    onDragLeave={handleDragLeave}
                    onDrop={(e) => handleDrop(e, null)}
                  >
                    Drop here for root level
                  </div>
                  {/* Root-level notes (no folder) */}
                  {notes
                    .filter(note =>
                      !note.folder_id &&
                      (note.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
                       note.content.toLowerCase().includes(searchQuery.toLowerCase()))
                    )
                    .map(note => (
                      <div
                        key={note.id}
                        draggable
                        onDragStart={(e) => handleDragStart(e, note.id)}
                        onDragEnd={handleDragEnd}
                        onClick={() => {
                          setEditingNote(note.id)
                          setEditNoteTitle(note.title || '')
                          setEditNoteContent(note.content || '')
                        }}
                        className={`group relative cursor-pointer rounded p-2 text-sm hover:bg-[#27272a] ${
                          editingNote === note.id ? 'bg-[#27272a] border-l-2 border-[#0d7ff2]' : ''
                        } ${draggedNoteId === note.id ? 'opacity-50' : ''}`}
                      >
                        <div className="flex items-center gap-2 pl-5">
                          <span className="material-icons text-sm text-[#a1a1aa] cursor-grab">drag_indicator</span>
                          <span className="material-icons text-sm text-[#a1a1aa]">description</span>
                          <span className="font-medium truncate pr-8">{note.title || 'Untitled'}</span>
                        </div>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            setNoteToDelete(note)
                          }}
                          className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-600/20 text-red-400 transition-all"
                        >
                          <span className="material-icons text-sm">delete</span>
                        </button>
                      </div>
                    ))}
                </>
              )
            })()}
          </div>
        </div>

        {/* Search */}
        <div className="relative">
          <input
            className="w-full rounded-md border-none bg-[#3f3f46] pl-8 pr-4 py-2 text-sm text-[#f8fafc] placeholder:text-[#a1a1aa] focus:ring-2 focus:ring-[#0d7ff2]"
            type="text"
            placeholder="Search..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <span className="material-icons text-sm absolute left-2 top-1/2 -translate-y-1/2 text-[#a1a1aa]">search</span>
        </div>
      </aside>

      {/* Main Content - Editor */}
      <main className="flex flex-1 flex-col">
        {editingNote ? (
          <>
            {/* Editor Header */}
            <header className="flex h-14 items-center border-b border-[#3f3f46] px-6 gap-4">
              <input
                type="text"
                value={editNoteTitle}
                onChange={(e) => setEditNoteTitle(e.target.value)}
                placeholder="Untitled"
                className="flex-1 bg-transparent border-none text-xl font-semibold text-[#f8fafc] placeholder:text-[#a1a1aa] focus:outline-none"
              />
              <div className="flex gap-2">
                <button
                  onClick={() => setNoteMode(noteMode === 'edit' ? 'view' : 'edit')}
                  className={`px-3 py-1 rounded text-sm ${
                    noteMode === 'edit'
                      ? 'bg-[#0d7ff2] text-white'
                      : 'bg-[#27272a] text-[#a1a1aa] hover:text-white'
                  }`}
                >
                  {noteMode === 'edit' ? '✏️ Edit' : '👁️ Preview'}
                </button>
                <button
                  onClick={() => setShowBacklinks(!showBacklinks)}
                  className="px-3 py-1 rounded text-sm bg-[#27272a] text-[#a1a1aa] hover:text-white"
                  title="Toggle backlinks panel"
                >
                  <span className="material-icons text-sm">link</span>
                </button>
              </div>
            </header>

            <div className="flex-1 p-6 overflow-y-auto">
              {noteMode === 'edit' ? (
                <textarea
                  value={editNoteContent}
                  onChange={(e) => setEditNoteContent(e.target.value)}
                  placeholder="Start writing... Use [[Note Title]] to link to other notes"
                  className="w-full h-full bg-transparent border-none text-[#f8fafc] placeholder:text-[#a1a1aa] focus:outline-none resize-none font-mono"
                  style={{ minHeight: '400px' }}
                />
              ) : (
                <div className="prose prose-invert max-w-none">
                  <MarkdownRenderer content={editNoteContent} />
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-[#a1a1aa]">
            <div className="text-center">
              <span className="material-icons text-6xl mb-4">notes</span>
              <p>Select a note or create a new one</p>
            </div>
          </div>
        )}
      </main>

      {/* Right Sidebar - Backlinks & Context */}
      {showBacklinks && editingNote && (
        <aside className="w-64 border-l border-[#3f3f46] p-4 overflow-y-auto">
          <h3 className="text-sm font-semibold text-[#a1a1aa] mb-4 uppercase">Backlinks ({backlinks.length})</h3>
          <div className="space-y-2">
            {backlinks.length > 0 ? (
              backlinks.map(note => (
                <div
                  key={note.id}
                  onClick={() => {
                    setEditingNote(note.id)
                    setEditNoteTitle(note.title || '')
                    setEditNoteContent(note.content || '')
                  }}
                  className="p-2 rounded bg-[#27272a] hover:bg-[#3f3f46] cursor-pointer"
                >
                  <div className="text-sm font-medium truncate">{note.title}</div>
                  <div className="text-xs text-[#a1a1aa] truncate">{note.content.substring(0, 50)}...</div>
                </div>
              ))
            ) : (
              <p className="text-sm text-[#a1a1aa]">No backlinks yet. Link to this note from another note using [[{editNoteTitle}]]</p>
            )}
          </div>

          <div className="mt-6">
            <h3 className="text-sm font-semibold text-[#a1a1aa] mb-2 uppercase">Info</h3>
            <div className="text-xs text-[#a1a1aa] space-y-1">
              {currentNote?.folder_id && (
                <div>📁 {getFolderPath(currentNote.folder_id)}</div>
              )}
              <div>Created: {currentNote ? new Date(currentNote.created_at).toLocaleDateString() : ''}</div>
              <div>Updated: {currentNote ? new Date(currentNote.updated_at).toLocaleDateString() : ''}</div>
            </div>
          </div>
        </aside>
      )}

      {/* New Note Dialog */}
      {showNewNoteDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-[#27272a] rounded-lg p-6 w-96">
            <h2 className="text-lg font-semibold mb-4">New Note</h2>
            <input
              type="text"
              value={newNoteName}
              onChange={(e) => setNewNoteName(e.target.value)}
              placeholder="Note title..."
              className="w-full bg-[#3f3f46] rounded px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-[#0d7ff2]"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') submitNewNote()
                if (e.key === 'Escape') setShowNewNoteDialog(false)
              }}
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowNewNoteDialog(false)}
                className="px-4 py-2 rounded bg-[#3f3f46] hover:bg-[#52525b]"
              >
                Cancel
              </button>
              <button
                onClick={submitNewNote}
                className="px-4 py-2 rounded bg-[#0d7ff2] hover:bg-[#0c6fd1]"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}

      {/* New Folder Dialog */}
      {showNewFolderDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-[#27272a] rounded-lg p-6 w-96">
            <h2 className="text-lg font-semibold mb-4">
              {selectedFolder ? 'New Sub-Folder' : 'New Folder'}
            </h2>
            {selectedFolder && (
              <div className="text-sm text-[#a1a1aa] mb-3">
                Inside: <span className="text-[#0d7ff2]">{folders.find(f => f.id === selectedFolder)?.name || 'Unknown'}</span>
              </div>
            )}
            <input
              type="text"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              placeholder="Folder name..."
              className="w-full bg-[#3f3f46] rounded px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-[#0d7ff2]"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') submitNewFolder()
                if (e.key === 'Escape') setShowNewFolderDialog(false)
              }}
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowNewFolderDialog(false)}
                className="px-4 py-2 rounded bg-[#3f3f46] hover:bg-[#52525b]"
              >
                Cancel
              </button>
              <button
                onClick={submitNewFolder}
                className="px-4 py-2 rounded bg-[#0d7ff2] hover:bg-[#0c6fd1]"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Folder Confirmation Dialog */}
      {folderToDelete && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-[#27272a] rounded-lg p-6 w-96">
            <h2 className="text-lg font-semibold mb-4">Delete Folder?</h2>
            <p className="text-[#a1a1aa] mb-4">Notes inside will be moved to root.</p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setFolderToDelete(null)}
                className="px-4 py-2 rounded bg-[#3f3f46] hover:bg-[#52525b]"
              >
                Cancel
              </button>
              <button
                onClick={confirmDeleteFolder}
                className="px-4 py-2 rounded bg-red-600 hover:bg-red-700"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Note Confirmation Dialog */}
      {noteToDelete && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-[#27272a] rounded-lg p-6 w-96">
            <h2 className="text-lg font-semibold mb-4">Delete Note?</h2>
            <p className="text-[#a1a1aa] mb-4">Delete "{noteToDelete.title || 'Untitled'}"?</p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setNoteToDelete(null)}
                className="px-4 py-2 rounded bg-[#3f3f46] hover:bg-[#52525b]"
              >
                Cancel
              </button>
              <button
                onClick={confirmDeleteNote}
                className="px-4 py-2 rounded bg-red-600 hover:bg-red-700"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
