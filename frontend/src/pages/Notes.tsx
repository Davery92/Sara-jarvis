import React, { useState, useEffect } from 'react'
import { FolderIcon, DocumentTextIcon, PlusIcon, MagnifyingGlassIcon, FolderPlusIcon } from '@heroicons/react/24/outline'
import { ChevronRightIcon, ChevronDownIcon } from '@heroicons/react/24/solid'
import { APP_CONFIG } from '../config'

interface TreeNode {
  id: string
  name: string
  type: 'folder' | 'note'
  parent_id?: string
  children: TreeNode[]
  created_at: string
  updated_at: string
}

interface Note {
  id: string
  title: string
  content: string
  folder_id?: string
  created_at: string
  updated_at: string
}

interface Folder {
  id: string
  name: string
  parent_id?: string
  notes_count: number
  subfolders_count: number
  created_at: string
  updated_at: string
}

export default function Notes() {
  const [tree, setTree] = useState<TreeNode[]>([])
  const [selectedNote, setSelectedNote] = useState<Note | null>(null)
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null)
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set())
  const [isLoading, setIsLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  
  // Load tree structure
  const loadTree = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/folders/tree`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setTree(data.tree || [])
      }
    } catch (error) {
      console.error('Failed to load tree:', error)
    } finally {
      setIsLoading(false)
    }
  }

  // Load a specific note
  const loadNote = async (noteId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/notes`, {
        credentials: 'include'
      })
      if (response.ok) {
        const notes = await response.json()
        const note = notes.find((n: Note) => n.id === noteId)
        if (note) {
          setSelectedNote(note)
        }
      }
    } catch (error) {
      console.error('Failed to load note:', error)
    }
  }

  // Create new folder
  const createFolder = async (name: string, parentId?: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/folders`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ name, parent_id: parentId })
      })
      if (response.ok) {
        loadTree() // Refresh tree
      }
    } catch (error) {
      console.error('Failed to create folder:', error)
    }
  }

  // Create new note
  const createNote = async (title: string, content: string = '', folderId?: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ title, content, folder_id: folderId })
      })
      if (response.ok) {
        const note = await response.json()
        setSelectedNote(note)
        loadTree() // Refresh tree
      }
    } catch (error) {
      console.error('Failed to create note:', error)
    }
  }

  // Toggle folder expansion
  const toggleFolder = (folderId: string) => {
    const newExpanded = new Set(expandedFolders)
    if (newExpanded.has(folderId)) {
      newExpanded.delete(folderId)
    } else {
      newExpanded.add(folderId)
    }
    setExpandedFolders(newExpanded)
  }

  // Render tree node
  const renderTreeNode = (node: TreeNode, level: number = 0): React.ReactNode => {
    const isExpanded = expandedFolders.has(node.id)
    const paddingLeft = level * 16

    if (node.type === 'folder') {
      return (
        <div key={node.id}>
          <div 
            className={`flex items-center py-1 px-2 hover:bg-gray-700 cursor-pointer ${
              selectedFolder === node.id ? 'bg-gray-600' : ''
            }`}
            style={{ paddingLeft }}
            onClick={() => {
              setSelectedFolder(node.id)
              toggleFolder(node.id)
            }}
          >
            {node.children.length > 0 ? (
              isExpanded ? (
                <ChevronDownIcon className="w-4 h-4 mr-1 text-gray-400" />
              ) : (
                <ChevronRightIcon className="w-4 h-4 mr-1 text-gray-400" />
              )
            ) : (
              <div className="w-4 h-4 mr-1" />
            )}
            <FolderIcon className="w-4 h-4 mr-2 text-blue-400" />
            <span className="text-sm text-gray-200 truncate">{node.name}</span>
          </div>
          {isExpanded && node.children.map(child => renderTreeNode(child, level + 1))}
        </div>
      )
    } else {
      return (
        <div 
          key={node.id}
          className={`flex items-center py-1 px-2 hover:bg-gray-700 cursor-pointer ${
            selectedNote?.id === node.id ? 'bg-gray-600' : ''
          }`}
          style={{ paddingLeft }}
          onClick={() => loadNote(node.id)}
        >
          <div className="w-4 h-4 mr-1" />
          <DocumentTextIcon className="w-4 h-4 mr-2 text-green-400" />
          <span className="text-sm text-gray-200 truncate">{node.name}</span>
        </div>
      )
    }
  }

  useEffect(() => {
    loadTree()
  }, [])

  return (
    <div className="flex h-[calc(100vh-4rem)] bg-gray-900 text-white">
      {/* Sidebar */}
      <div className="w-80 bg-gray-800 border-r border-gray-700 flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-gray-700">
          <h2 className="text-lg font-semibold mb-3">📝 Notes - Obsidian Style</h2>
          
          {/* Search */}
          <div className="relative mb-3">
            <MagnifyingGlassIcon className="w-4 h-4 absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="Search notes..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-gray-700 border border-gray-600 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {/* Action buttons */}
          <div className="flex gap-2">
            <button
              onClick={() => {
                const name = prompt('Folder name:')
                if (name) createFolder(name, selectedFolder || undefined)
              }}
              className="flex items-center px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm"
            >
              <FolderPlusIcon className="w-4 h-4 mr-1" />
              Folder
            </button>
            <button
              onClick={() => {
                const title = prompt('Note title:')
                if (title) createNote(title, '', selectedFolder || undefined)
              }}
              className="flex items-center px-3 py-1.5 bg-green-600 hover:bg-green-700 rounded text-sm"
            >
              <PlusIcon className="w-4 h-4 mr-1" />
              Note
            </button>
          </div>
        </div>

        {/* Tree */}
        <div className="flex-1 overflow-y-auto p-2">
          {isLoading ? (
            <div className="text-center text-gray-400 mt-8">Loading...</div>
          ) : tree.length === 0 ? (
            <div className="text-center text-gray-400 mt-8">
              <DocumentTextIcon className="w-12 h-12 mx-auto mb-2 opacity-50" />
              <p>No notes yet</p>
              <p className="text-xs">Create your first note or folder</p>
            </div>
          ) : (
            tree.map(node => renderTreeNode(node))
          )}
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex flex-col">
        {selectedNote ? (
          <>
            {/* Note header */}
            <div className="p-4 border-b border-gray-700 bg-gray-800">
              <h1 className="text-xl font-semibold">{selectedNote.title || 'Untitled'}</h1>
              <p className="text-sm text-gray-400 mt-1">
                Last modified: {new Date(selectedNote.updated_at).toLocaleDateString()}
              </p>
            </div>

            {/* Note content */}
            <div className="flex-1 p-4">
              <div className="bg-gray-800 rounded-lg p-4 h-full">
                <pre className="text-gray-200 whitespace-pre-wrap font-mono text-sm">
                  {selectedNote.content}
                </pre>
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-400">
            <div className="text-center">
              <DocumentTextIcon className="w-16 h-16 mx-auto mb-4 opacity-50" />
              <h3 className="text-lg font-medium mb-2">Select a note to view</h3>
              <p className="text-sm">Choose a note from the sidebar or create a new one</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}