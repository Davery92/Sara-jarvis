import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Folder,
  FileText,
  ChevronRight,
  ChevronDown,
  Plus,
  Edit2,
  Save,
  X,
  Trash2,
  FolderPlus,
  Loader2,
  ExternalLink,
} from 'lucide-react'
import { notesApi, foldersApi, type TreeNode } from '../../services/api'
import { useCanvasStore } from '../../store/canvasStore'
import type { NoteWindowData, Note } from '../../types'

interface NoteContentProps {
  data: NoteWindowData
  windowId: string
}

export default function NoteContent({ data }: NoteContentProps) {
  const queryClient = useQueryClient()
  const { openWindow } = useCanvasStore()
  const [selectedNote, setSelectedNote] = useState<Note | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editContent, setEditContent] = useState('')
  const [showNewNote, setShowNewNote] = useState(false)
  const [showNewFolder, setShowNewFolder] = useState(false)
  const [newNoteFolderId, setNewNoteFolderId] = useState<string | null>(null)
  const [newFolderParentId, setNewFolderParentId] = useState<string | null>(null)
  const [newItemName, setNewItemName] = useState('')

  // Fetch folder tree
  const { data: tree = [], isLoading } = useQuery({
    queryKey: ['folders', 'tree'],
    queryFn: foldersApi.getTree,
  })

  // Load initial note if provided in data
  useEffect(() => {
    if (data.noteId && data.content) {
      setSelectedNote({
        id: data.noteId,
        title: data.title || 'Untitled',
        content: data.content,
        folder_id: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      })
    }
  }, [data.noteId, data.title, data.content])

  // Mutations
  const createNoteMutation = useMutation({
    mutationFn: ({ title, content, folderId }: { title: string; content: string; folderId: string | null }) =>
      notesApi.create(title, content, folderId),
    onSuccess: (newNote) => {
      queryClient.invalidateQueries({ queryKey: ['folders', 'tree'] })
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      setSelectedNote(newNote)
      setShowNewNote(false)
      setNewItemName('')
    },
  })

  const updateNoteMutation = useMutation({
    mutationFn: ({ id, title, content }: { id: string; title: string; content: string }) =>
      notesApi.update(id, { title, content }),
    onSuccess: (updatedNote) => {
      queryClient.invalidateQueries({ queryKey: ['folders', 'tree'] })
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      setSelectedNote(updatedNote)
      setIsEditing(false)
    },
  })

  const deleteNoteMutation = useMutation({
    mutationFn: notesApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['folders', 'tree'] })
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      setSelectedNote(null)
    },
  })

  const createFolderMutation = useMutation({
    mutationFn: ({ name, parentId }: { name: string; parentId: string | null }) =>
      foldersApi.create(name, parentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['folders', 'tree'] })
      setShowNewFolder(false)
      setNewItemName('')
    },
  })

  const deleteFolderMutation = useMutation({
    mutationFn: foldersApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['folders', 'tree'] })
    },
  })

  // Handlers
  const handleSelectNote = async (node: TreeNode) => {
    try {
      const note = await notesApi.get(node.id)
      setSelectedNote(note)
      setIsEditing(false)
    } catch (error) {
      console.error('Failed to load note:', error)
    }
  }

  const handleStartEdit = () => {
    if (selectedNote) {
      setEditTitle(selectedNote.title)
      setEditContent(selectedNote.content)
      setIsEditing(true)
    }
  }

  const handleSaveEdit = () => {
    if (selectedNote) {
      updateNoteMutation.mutate({
        id: selectedNote.id,
        title: editTitle,
        content: editContent,
      })
    }
  }

  const handleCreateNote = () => {
    if (!newItemName.trim()) return
    createNoteMutation.mutate({
      title: newItemName.trim(),
      content: '',
      folderId: newNoteFolderId,
    })
  }

  const handleCreateFolder = () => {
    if (!newItemName.trim()) return
    createFolderMutation.mutate({
      name: newItemName.trim(),
      parentId: newFolderParentId,
    })
  }

  // Detach note as a separate read-only window
  const handleDetach = () => {
    if (!selectedNote) return
    openWindow('report', {
      title: selectedNote.title,
      content: selectedNote.content,
    }, {
      title: selectedNote.title,
    })
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-canvas-muted">
        <Loader2 className="animate-spin mr-2" size={20} />
        Loading notes...
      </div>
    )
  }

  return (
    <div className="flex h-full bg-canvas-bg">
      {/* Sidebar - Folder Tree */}
      <div className="w-64 border-r border-canvas-border flex flex-col">
        {/* Sidebar Header */}
        <div className="p-2 border-b border-canvas-border flex items-center justify-between">
          <span className="text-sm font-medium text-white">Notes</span>
          <div className="flex gap-1">
            <button
              onClick={() => {
                setShowNewFolder(true)
                setShowNewNote(false)
                setNewFolderParentId(null)
                setNewItemName('')
              }}
              className="p-1.5 hover:bg-canvas-elevated rounded text-canvas-muted hover:text-white"
              title="New Folder"
            >
              <FolderPlus size={16} />
            </button>
            <button
              onClick={() => {
                setShowNewNote(true)
                setShowNewFolder(false)
                setNewNoteFolderId(null)
                setNewItemName('')
              }}
              className="p-1.5 hover:bg-canvas-elevated rounded text-canvas-muted hover:text-white"
              title="New Note"
            >
              <Plus size={16} />
            </button>
          </div>
        </div>

        {/* New Item Form */}
        {(showNewNote || showNewFolder) && (
          <div className="p-2 border-b border-canvas-border bg-canvas-surface">
            <div className="text-xs text-canvas-muted mb-1">
              {showNewNote ? 'New Note' : 'New Folder'}
              {showNewNote && newNoteFolderId && ' (in folder)'}
              {showNewFolder && newFolderParentId && ' (subfolder)'}
            </div>
            <input
              type="text"
              value={newItemName}
              onChange={(e) => setNewItemName(e.target.value)}
              placeholder={showNewNote ? 'Note title...' : 'Folder name...'}
              className="w-full px-2 py-1 text-sm bg-canvas-elevated border border-canvas-border rounded text-white placeholder-canvas-muted focus:outline-none focus:border-blue-500"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  showNewNote ? handleCreateNote() : handleCreateFolder()
                }
                if (e.key === 'Escape') {
                  setShowNewNote(false)
                  setShowNewFolder(false)
                }
              }}
            />
            <div className="flex gap-1 mt-1">
              <button
                onClick={showNewNote ? handleCreateNote : handleCreateFolder}
                disabled={createNoteMutation.isPending || createFolderMutation.isPending}
                className="flex-1 px-2 py-1 text-xs bg-blue-500 hover:bg-blue-600 rounded text-white"
              >
                Create
              </button>
              <button
                onClick={() => {
                  setShowNewNote(false)
                  setShowNewFolder(false)
                }}
                className="px-2 py-1 text-xs bg-canvas-elevated hover:bg-canvas-border rounded text-canvas-muted"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Tree View */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-1">
          {tree.length === 0 ? (
            <div className="p-4 text-center text-canvas-muted text-sm">
              No notes yet. Create one to get started.
            </div>
          ) : (
            tree.map((node) => (
              <TreeNodeItem
                key={node.id}
                node={node}
                selectedId={selectedNote?.id}
                onSelectNote={handleSelectNote}
                onNewNote={(folderId) => {
                  setShowNewNote(true)
                  setShowNewFolder(false)
                  setNewNoteFolderId(folderId)
                  setNewItemName('')
                }}
                onNewFolder={(parentId) => {
                  setShowNewFolder(true)
                  setShowNewNote(false)
                  setNewFolderParentId(parentId)
                  setNewItemName('')
                }}
                onDeleteFolder={(id) => deleteFolderMutation.mutate(id)}
              />
            ))
          )}
        </div>
      </div>

      {/* Main Content - Note View/Editor */}
      <div className="flex-1 flex flex-col">
        {selectedNote ? (
          <>
            {/* Note Header */}
            <div className="p-3 border-b border-canvas-border flex items-center justify-between">
              {isEditing ? (
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="flex-1 px-2 py-1 bg-canvas-elevated border border-canvas-border rounded text-white text-lg font-medium focus:outline-none focus:border-blue-500"
                />
              ) : (
                <h2 className="text-lg font-medium text-white truncate">{selectedNote.title}</h2>
              )}
              <div className="flex items-center gap-2 ml-2">
                {isEditing ? (
                  <>
                    <button
                      onClick={handleSaveEdit}
                      disabled={updateNoteMutation.isPending}
                      className="p-2 bg-green-500 hover:bg-green-600 rounded text-white"
                      title="Save"
                    >
                      <Save size={16} />
                    </button>
                    <button
                      onClick={() => setIsEditing(false)}
                      className="p-2 bg-canvas-elevated hover:bg-canvas-border rounded text-canvas-muted"
                      title="Cancel"
                    >
                      <X size={16} />
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      onClick={handleDetach}
                      className="p-2 bg-blue-500/20 hover:bg-blue-500 rounded text-blue-400 hover:text-white"
                      title="Open as separate window"
                    >
                      <ExternalLink size={16} />
                    </button>
                    <button
                      onClick={handleStartEdit}
                      className="p-2 bg-canvas-elevated hover:bg-canvas-border rounded text-white"
                      title="Edit"
                    >
                      <Edit2 size={16} />
                    </button>
                    <button
                      onClick={() => {
                        if (confirm('Delete this note?')) {
                          deleteNoteMutation.mutate(selectedNote.id)
                        }
                      }}
                      className="p-2 bg-red-500/20 hover:bg-red-500 rounded text-red-400 hover:text-white"
                      title="Delete"
                    >
                      <Trash2 size={16} />
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* Note Content */}
            <div className="flex-1 overflow-y-auto custom-scrollbar">
              {isEditing ? (
                <textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  className="w-full h-full p-4 bg-canvas-bg text-white font-mono text-sm resize-none focus:outline-none"
                  placeholder="Write your note in markdown..."
                />
              ) : (
                <div className="p-4 markdown-content">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {selectedNote.content || '*No content*'}
                  </ReactMarkdown>
                </div>
              )}
            </div>

            {/* Note Footer */}
            <div className="px-4 py-2 border-t border-canvas-border text-xs text-canvas-muted">
              Updated {new Date(selectedNote.updated_at).toLocaleString()}
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-canvas-muted">
            <div className="text-center">
              <FileText size={48} className="mx-auto mb-4 opacity-30" />
              <p>Select a note to view</p>
              <p className="text-sm mt-1">or create a new one</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Recursive Tree Node Component
function TreeNodeItem({
  node,
  selectedId,
  onSelectNote,
  onNewNote,
  onNewFolder,
  onDeleteFolder,
  depth = 0,
}: {
  node: TreeNode
  selectedId?: string
  onSelectNote: (node: TreeNode) => void
  onNewNote: (folderId: string | null) => void
  onNewFolder: (parentId: string | null) => void
  onDeleteFolder: (id: string) => void
  depth?: number
}) {
  const [isExpanded, setIsExpanded] = useState(true)
  const [showMenu, setShowMenu] = useState(false)

  const isFolder = node.type === 'folder'
  const isSelected = node.id === selectedId

  return (
    <div>
      <div
        className={`flex items-center gap-1 px-2 py-1.5 rounded cursor-pointer group ${
          isSelected ? 'bg-blue-500/20 text-white' : 'hover:bg-canvas-elevated text-canvas-muted hover:text-white'
        }`}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={() => {
          if (isFolder) {
            setIsExpanded(!isExpanded)
          } else {
            onSelectNote(node)
          }
        }}
      >
        {isFolder ? (
          <>
            {isExpanded ? (
              <ChevronDown size={14} className="flex-shrink-0" />
            ) : (
              <ChevronRight size={14} className="flex-shrink-0" />
            )}
            <Folder size={14} className="flex-shrink-0 text-yellow-500" />
          </>
        ) : (
          <>
            <span className="w-3.5" />
            <FileText size={14} className="flex-shrink-0 text-blue-400" />
          </>
        )}
        <span className="flex-1 truncate text-sm">{node.name}</span>

        {/* Context menu for folders */}
        {isFolder && (
          <div className="relative opacity-0 group-hover:opacity-100">
            <button
              onClick={(e) => {
                e.stopPropagation()
                setShowMenu(!showMenu)
              }}
              className="p-0.5 hover:bg-canvas-surface rounded"
            >
              <Plus size={12} />
            </button>
            {showMenu && (
              <div
                className="absolute right-0 top-full mt-1 bg-canvas-surface border border-canvas-border rounded shadow-lg z-20 py-1 min-w-[120px]"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  onClick={() => {
                    onNewNote(node.id)
                    setShowMenu(false)
                  }}
                  className="w-full px-3 py-1.5 text-left text-xs hover:bg-canvas-elevated text-canvas-muted hover:text-white flex items-center gap-2"
                >
                  <FileText size={12} /> New Note
                </button>
                <button
                  onClick={() => {
                    onNewFolder(node.id)
                    setShowMenu(false)
                  }}
                  className="w-full px-3 py-1.5 text-left text-xs hover:bg-canvas-elevated text-canvas-muted hover:text-white flex items-center gap-2"
                >
                  <FolderPlus size={12} /> New Subfolder
                </button>
                <div className="border-t border-canvas-border my-1" />
                <button
                  onClick={() => {
                    if (confirm(`Delete folder "${node.name}"? Notes will be moved to root.`)) {
                      onDeleteFolder(node.id)
                    }
                    setShowMenu(false)
                  }}
                  className="w-full px-3 py-1.5 text-left text-xs hover:bg-canvas-elevated text-red-400 flex items-center gap-2"
                >
                  <Trash2 size={12} /> Delete Folder
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Children */}
      {isFolder && isExpanded && node.children.length > 0 && (
        <div>
          {node.children.map((child) => (
            <TreeNodeItem
              key={child.id}
              node={child}
              selectedId={selectedId}
              onSelectNote={onSelectNote}
              onNewNote={onNewNote}
              onNewFolder={onNewFolder}
              onDeleteFolder={onDeleteFolder}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  )
}
