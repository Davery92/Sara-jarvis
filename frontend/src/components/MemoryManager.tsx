import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../config'

interface Episode {
  id: string
  source: string
  role: string
  content: string
  importance: number
  meta: any
  created_at: string
}

interface MemoryManagerProps {
  onClose?: () => void
}

export default function MemoryManager({ onClose }: MemoryManagerProps) {
  const [episodes, setEpisodes] = useState<Episode[]>([])
  const [loading, setLoading] = useState(false)
  const [editingEpisode, setEditingEpisode] = useState<Episode | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [importanceFilter, setImportanceFilter] = useState<'all' | 'high' | 'medium' | 'low'>('all')
  const [sortBy, setSortBy] = useState<'date' | 'importance'>('date')
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)

  useEffect(() => {
    loadEpisodes()
  }, [currentPage, importanceFilter, sortBy])

  const loadEpisodes = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page: currentPage.toString(),
        per_page: '20'
      })

      if (importanceFilter !== 'all') {
        const minImportance = {
          'high': 0.7,
          'medium': 0.4,
          'low': 0.0
        }[importanceFilter]
        const maxImportance = {
          'high': 1.0,
          'medium': 0.7,
          'low': 0.4
        }[importanceFilter]
        params.append('min_importance', minImportance.toString())
        params.append('max_importance', maxImportance.toString())
      }

      const response = await fetch(`${APP_CONFIG.apiUrl}/memory/episodes?${params}`, {
        credentials: 'include'
      })

      if (response.ok) {
        const data = await response.json()
        setEpisodes(data.episodes || [])
        setTotalPages(Math.ceil(data.total / 20))
      }
    } catch (error) {
      console.error('Failed to load episodes:', error)
    } finally {
      setLoading(false)
    }
  }

  const deleteEpisode = async (episodeId: string) => {
    if (!confirm('Are you sure you want to delete this memory? This action cannot be undone.')) {
      return
    }

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/memory/episodes/${episodeId}`, {
        method: 'DELETE',
        credentials: 'include'
      })

      if (response.ok) {
        setEpisodes(prev => prev.filter(ep => ep.id !== episodeId))
        console.log('✅ Episode deleted successfully')
      } else {
        console.error('Failed to delete episode')
      }
    } catch (error) {
      console.error('Error deleting episode:', error)
    }
  }

  const updateEpisodeImportance = async (episodeId: string, newImportance: number) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/memory/episodes/${episodeId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ importance: newImportance })
      })

      if (response.ok) {
        setEpisodes(prev => prev.map(ep => 
          ep.id === episodeId ? { ...ep, importance: newImportance } : ep
        ))
        console.log('✅ Episode importance updated')
      }
    } catch (error) {
      console.error('Error updating episode importance:', error)
    }
  }

  const searchEpisodes = async () => {
    if (!searchQuery.trim()) {
      loadEpisodes()
      return
    }

    setLoading(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/memory/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          query: searchQuery,
          scopes: ['episodes'],
          limit: 50
        })
      })

      if (response.ok) {
        const data = await response.json()
        const searchResults = data.results.map((result: any) => ({
          id: result.metadata.episode_id || result.metadata.id,
          content: result.text,
          importance: result.metadata.importance || 0.5,
          role: result.metadata.role || 'unknown',
          source: result.metadata.source || 'unknown',
          created_at: result.metadata.timestamp || new Date().toISOString(),
          meta: result.metadata
        }))
        setEpisodes(searchResults)
      }
    } catch (error) {
      console.error('Failed to search episodes:', error)
    } finally {
      setLoading(false)
    }
  }

  const getImportanceColor = (importance: number) => {
    if (importance >= 0.7) return 'text-red-400'
    if (importance >= 0.4) return 'text-yellow-400'
    return 'text-green-400'
  }

  const getImportanceLabel = (importance: number) => {
    if (importance >= 0.7) return 'High'
    if (importance >= 0.4) return 'Medium'
    return 'Low'
  }

  return (
    <div className="w-full h-full bg-[#27272a] rounded-lg border border-[#3f3f46] overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-[#3f3f46]">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-medium text-[#f8fafc]">Memory Management</h3>
          {onClose && (
            <button
              onClick={onClose}
              className="text-[#a1a1aa] hover:text-[#f8fafc]"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
          )}
        </div>
        
        {/* Search and Filters */}
        <div className="flex items-center gap-3 mb-3">
          <div className="flex-1 relative">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-[#a1a1aa]">search</span>
            <input
              type="text"
              placeholder="Search memories..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && searchEpisodes()}
              className="w-full pl-10 pr-4 py-2 bg-[#3f3f46] border border-[#52525b] rounded text-[#f8fafc] placeholder:text-[#a1a1aa]"
            />
          </div>
          <button
            onClick={searchEpisodes}
            className="px-4 py-2 bg-[#0d7ff2] text-white rounded hover:bg-[#0c6fd1]"
          >
            Search
          </button>
        </div>

        <div className="flex items-center gap-3">
          <select
            value={importanceFilter}
            onChange={(e) => setImportanceFilter(e.target.value as any)}
            className="bg-[#3f3f46] text-[#f8fafc] text-sm rounded px-3 py-1 border border-[#52525b]"
          >
            <option value="all">All Importance</option>
            <option value="high">High (70%+)</option>
            <option value="medium">Medium (40-70%)</option>
            <option value="low">Low (0-40%)</option>
          </select>
          
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as any)}
            className="bg-[#3f3f46] text-[#f8fafc] text-sm rounded px-3 py-1 border border-[#52525b]"
          >
            <option value="date">Sort by Date</option>
            <option value="importance">Sort by Importance</option>
          </select>

          <button
            onClick={() => {
              setSearchQuery('')
              setCurrentPage(1)
              loadEpisodes()
            }}
            className="px-3 py-1 text-sm text-[#a1a1aa] hover:text-[#f8fafc]"
          >
            Clear
          </button>
        </div>

        <p className="text-sm text-[#a1a1aa] mt-2">
          {episodes.length} episodes • Manage your AI's memory
        </p>
      </div>

      {/* Episodes List */}
      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="flex items-center justify-center h-64">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-[#0d7ff2] border-t-transparent"></div>
          </div>
        ) : episodes.length === 0 ? (
          <div className="flex items-center justify-center h-64">
            <div className="text-center">
              <span className="material-symbols-outlined text-6xl text-[#a1a1aa] mb-4 block">psychology</span>
              <h3 className="text-lg font-medium mb-2 text-[#f8fafc]">No memories found</h3>
              <p className="text-[#a1a1aa]">Try adjusting your search or filters</p>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {episodes.map(episode => (
              <div key={episode.id} className="bg-[#18181b] rounded-lg border border-[#3f3f46] p-4">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs px-2 py-1 rounded ${
                      episode.role === 'user' ? 'bg-blue-600' : 
                      episode.role === 'assistant' ? 'bg-green-600' : 'bg-gray-600'
                    } text-white`}>
                      {episode.role}
                    </span>
                    <span className="text-xs text-[#a1a1aa]">
                      {episode.source}
                    </span>
                    <span className="text-xs text-[#a1a1aa]">
                      {new Date(episode.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`text-xs font-medium ${getImportanceColor(episode.importance)}`}>
                      {getImportanceLabel(episode.importance)} ({Math.round(episode.importance * 100)}%)
                    </span>
                    <button
                      onClick={() => deleteEpisode(episode.id)}
                      className="text-red-400 hover:text-red-300 text-sm"
                      title="Delete episode"
                    >
                      <span className="material-symbols-outlined text-lg">delete</span>
                    </button>
                  </div>
                </div>
                
                <p className="text-sm text-[#f8fafc] mb-3 line-clamp-3">
                  {episode.content}
                </p>

                <div className="flex items-center gap-3">
                  <label className="text-xs text-[#a1a1aa]">Importance:</label>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={Math.round(episode.importance * 100)}
                    onChange={(e) => updateEpisodeImportance(episode.id, parseInt(e.target.value) / 100)}
                    className="flex-1 h-2 bg-[#3f3f46] rounded-lg appearance-none cursor-pointer"
                  />
                  <span className="text-xs text-[#a1a1aa] w-12">
                    {Math.round(episode.importance * 100)}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="p-4 border-t border-[#3f3f46]">
          <div className="flex items-center justify-center gap-2">
            <button
              onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
              disabled={currentPage === 1}
              className="px-3 py-1 text-sm bg-[#3f3f46] text-[#f8fafc] rounded disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Previous
            </button>
            <span className="text-sm text-[#a1a1aa]">
              Page {currentPage} of {totalPages}
            </span>
            <button
              onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
              disabled={currentPage === totalPages}
              className="px-3 py-1 text-sm bg-[#3f3f46] text-[#f8fafc] rounded disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}