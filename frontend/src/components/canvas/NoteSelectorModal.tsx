/**
 * NoteSelectorModal Component
 *
 * Modal for searching and selecting existing notes to open in the canvas.
 * Features search with debounce and recent notes list.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react'
import { X, Search, FileText, Folder, Clock } from 'lucide-react'
import { APP_CONFIG } from '../../config'

interface Note {
  id: string
  title: string
  content: string
  folder_id?: string
  folder_name?: string
  created_at: string
  updated_at: string
}

interface NoteSelectorModalProps {
  isOpen: boolean
  onClose: () => void
  onSelectNote: (note: Note) => void
}

export function NoteSelectorModal({ isOpen, onClose, onSelectNote }: NoteSelectorModalProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [notes, setNotes] = useState<Note[]>([])
  const [recentNotes, setRecentNotes] = useState<Note[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [activeTab, setActiveTab] = useState<'recent' | 'search'>('recent')
  const searchInputRef = useRef<HTMLInputElement>(null)
  const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null)

  // Focus search input when modal opens
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => searchInputRef.current?.focus(), 100)
      loadRecentNotes()
    }
  }, [isOpen])

  // Load recent notes
  const loadRecentNotes = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/notes?limit=20`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setRecentNotes(data)
      }
    } catch (error) {
      console.error('Failed to load recent notes:', error)
    }
  }

  // Search notes with debounce
  const searchNotes = useCallback(async (query: string) => {
    if (!query.trim()) {
      setNotes([])
      setActiveTab('recent')
      return
    }

    setIsSearching(true)
    setActiveTab('search')

    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/notes?search=${encodeURIComponent(query)}&limit=20`,
        { credentials: 'include' }
      )
      if (response.ok) {
        const data = await response.json()
        setNotes(data)
      }
    } catch (error) {
      console.error('Failed to search notes:', error)
    } finally {
      setIsSearching(false)
    }
  }, [])

  // Debounced search
  useEffect(() => {
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current)
    }

    if (searchQuery.trim()) {
      searchTimeoutRef.current = setTimeout(() => {
        searchNotes(searchQuery)
      }, 300)
    } else {
      setNotes([])
      setActiveTab('recent')
    }

    return () => {
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current)
      }
    }
  }, [searchQuery, searchNotes])

  // Handle note selection
  const handleSelectNote = (note: Note) => {
    onSelectNote(note)
    onClose()
    setSearchQuery('')
  }

  // Handle escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  // Format date for display
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

    if (diffDays === 0) {
      return 'Today'
    } else if (diffDays === 1) {
      return 'Yesterday'
    } else if (diffDays < 7) {
      return `${diffDays} days ago`
    } else {
      return date.toLocaleDateString()
    }
  }

  // Get content preview
  const getPreview = (content: string, maxLength: number = 100) => {
    if (!content) return ''
    const text = content.replace(/[#*_~`]/g, '').trim()
    return text.length > maxLength ? text.slice(0, maxLength) + '...' : text
  }

  if (!isOpen) return null

  const displayNotes = activeTab === 'search' ? notes : recentNotes

  return (
    <div className="fixed inset-0 bg-black/60 flex items-start justify-center pt-20 z-50">
      <div className="bg-gray-800 rounded-xl shadow-2xl w-full max-w-lg mx-4 border border-gray-700 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
          <h2 className="text-lg font-semibold text-white">Open Note in Canvas</h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-gray-700 rounded text-gray-400 hover:text-white"
          >
            <X size={20} />
          </button>
        </div>

        {/* Search */}
        <div className="p-4 border-b border-gray-700">
          <div className="relative">
            <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search notes by title or content..."
              className="w-full bg-gray-900 border border-gray-700 rounded-lg pl-10 pr-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-teal-500"
            />
            {isSearching && (
              <div className="absolute right-3 top-1/2 -translate-y-1/2">
                <div className="w-4 h-4 border-2 border-teal-500 border-t-transparent rounded-full animate-spin" />
              </div>
            )}
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-700">
          <button
            onClick={() => setActiveTab('recent')}
            className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === 'recent'
                ? 'text-teal-400 border-b-2 border-teal-400'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            <Clock size={14} className="inline mr-2" />
            Recent
          </button>
          <button
            onClick={() => setActiveTab('search')}
            className={`flex-1 px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === 'search'
                ? 'text-teal-400 border-b-2 border-teal-400'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            <Search size={14} className="inline mr-2" />
            Search Results
          </button>
        </div>

        {/* Notes List */}
        <div className="max-h-80 overflow-y-auto">
          {displayNotes.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              {activeTab === 'search' && searchQuery
                ? 'No notes found matching your search'
                : 'No notes yet'}
            </div>
          ) : (
            <div className="divide-y divide-gray-700">
              {displayNotes.map((note) => (
                <button
                  key={note.id}
                  onClick={() => handleSelectNote(note)}
                  className="w-full px-4 py-3 hover:bg-gray-700/50 text-left transition-colors group"
                >
                  <div className="flex items-start gap-3">
                    <FileText size={18} className="text-gray-400 mt-0.5 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-white font-medium truncate">
                          {note.title || 'Untitled'}
                        </span>
                        {note.folder_name && (
                          <span className="text-xs text-gray-500 flex items-center gap-1">
                            <Folder size={12} />
                            {note.folder_name}
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-gray-400 mt-1 line-clamp-2">
                        {getPreview(note.content)}
                      </p>
                      <span className="text-xs text-gray-500 mt-1 block">
                        {formatDate(note.updated_at)}
                      </span>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-gray-700 bg-gray-800/50">
          <p className="text-xs text-gray-500 text-center">
            Select a note to open it in the canvas for side-by-side editing
          </p>
        </div>
      </div>
    </div>
  )
}

export default NoteSelectorModal
