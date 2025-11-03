import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../config'

interface Episode {
  id: string
  role: string
  content: string
  created_at: string
  importance: number
  source: string
}

interface MemoryManagerProps {
  onClose?: () => void
}

export default function MemoryManager({ onClose }: MemoryManagerProps) {
  const [episodes, setEpisodes] = useState<Episode[]>([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [roleFilter, setRoleFilter] = useState<'all' | 'user' | 'assistant'>('all')
  const [selectedEpisode, setSelectedEpisode] = useState<Episode | null>(null)
  const [editingImportance, setEditingImportance] = useState<string | null>(null)
  const [isMobile, setIsMobile] = useState(false)
  const [mobileTab, setMobileTab] = useState<'list' | 'detail'>('list')

  useEffect(() => {
    fetchEpisodes()
  }, [])

  // Mobile detection
  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768)
    }
    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
  }, [])

  // Auto-switch to detail tab when an episode is selected on mobile
  useEffect(() => {
    if (isMobile && selectedEpisode && mobileTab === 'list') {
      setMobileTab('detail')
    }
  }, [selectedEpisode, isMobile])

  const fetchEpisodes = async () => {
    setLoading(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/memory/episodes?limit=100`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setEpisodes(data.episodes || [])
      }
    } catch (error) {
      console.error('Failed to fetch episodes:', error)
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
        setEpisodes(episodes.filter(ep => ep.id !== episodeId))
        if (selectedEpisode?.id === episodeId) {
          setSelectedEpisode(null)
        }
      }
    } catch (error) {
      console.error('Failed to delete episode:', error)
      alert('Failed to delete memory')
    }
  }

  const updateImportance = async (episodeId: string, newImportance: number) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/memory/episodes/${episodeId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ importance: newImportance })
      })

      if (response.ok) {
        setEpisodes(episodes.map(ep =>
          ep.id === episodeId ? { ...ep, importance: newImportance } : ep
        ))
        if (selectedEpisode?.id === episodeId) {
          setSelectedEpisode({ ...selectedEpisode, importance: newImportance })
        }
        setEditingImportance(null)
      }
    } catch (error) {
      console.error('Failed to update importance:', error)
      alert('Failed to update importance')
    }
  }

  const filteredEpisodes = episodes.filter(ep => {
    const matchesSearch = ep.content.toLowerCase().includes(searchTerm.toLowerCase())
    const matchesRole = roleFilter === 'all' || ep.role === roleFilter
    return matchesSearch && matchesRole
  })

  const getImportanceColor = (importance: number) => {
    if (importance >= 0.8) return 'text-red-400'
    if (importance >= 0.5) return 'text-yellow-400'
    return 'text-green-400'
  }

  const getImportanceLabel = (importance: number) => {
    if (importance >= 0.8) return 'Critical'
    if (importance >= 0.5) return 'Important'
    return 'Normal'
  }

  return (
    <div className={`w-full h-full bg-[#18181b] overflow-hidden flex relative ${
      isMobile ? 'pb-16' : ''
    }`}>
      {/* Left Sidebar - Episode List */}
      <div className={`w-full md:w-1/3 border-r border-[#3f3f46] flex flex-col ${
        isMobile && mobileTab !== 'list' ? 'hidden' : ''
      }`}>
        {/* Header */}
        <div className="p-4 border-b border-[#3f3f46]">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium text-[#f8fafc]">Memory Manager</h3>
            {onClose && (
              <button
                onClick={onClose}
                className="text-[#a1a1aa] hover:text-[#f8fafc]"
              >
                ×
              </button>
            )}
          </div>

          {/* Search */}
          <input
            type="text"
            placeholder="Search memories..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full px-3 py-2 bg-[#27272a] border border-[#3f3f46] rounded text-[#f8fafc] text-sm focus:outline-none focus:border-[#0d7ff2]"
          />

          {/* Filters */}
          <div className="flex gap-2 mt-3">
            <button
              onClick={() => setRoleFilter('all')}
              className={`px-3 py-1 text-xs rounded ${
                roleFilter === 'all'
                  ? 'bg-[#0d7ff2] text-white'
                  : 'bg-[#27272a] text-[#a1a1aa] hover:bg-[#3f3f46]'
              }`}
            >
              All
            </button>
            <button
              onClick={() => setRoleFilter('user')}
              className={`px-3 py-1 text-xs rounded ${
                roleFilter === 'user'
                  ? 'bg-[#0d7ff2] text-white'
                  : 'bg-[#27272a] text-[#a1a1aa] hover:bg-[#3f3f46]'
              }`}
            >
              User
            </button>
            <button
              onClick={() => setRoleFilter('assistant')}
              className={`px-3 py-1 text-xs rounded ${
                roleFilter === 'assistant'
                  ? 'bg-[#0d7ff2] text-white'
                  : 'bg-[#27272a] text-[#a1a1aa] hover:bg-[#3f3f46]'
              }`}
            >
              Assistant
            </button>
          </div>

          <div className="text-xs text-[#a1a1aa] mt-3">
            {filteredEpisodes.length} of {episodes.length} memories
          </div>
        </div>

        {/* Episode List */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="text-[#a1a1aa]">Loading memories...</div>
            </div>
          ) : filteredEpisodes.length === 0 ? (
            <div className="flex items-center justify-center h-32">
              <div className="text-center text-[#a1a1aa]">
                <div className="text-2xl mb-2">🧠</div>
                <div className="text-sm">No memories found</div>
              </div>
            </div>
          ) : (
            filteredEpisodes.map((episode) => (
              <div
                key={episode.id}
                onClick={() => setSelectedEpisode(episode)}
                className={`p-4 border-b border-[#3f3f46] cursor-pointer hover:bg-[#27272a] ${
                  selectedEpisode?.id === episode.id ? 'bg-[#27272a]' : ''
                }`}
              >
                <div className="flex items-start justify-between mb-2">
                  <span className={`text-xs font-medium ${
                    episode.role === 'user' ? 'text-blue-400' : 'text-purple-400'
                  }`}>
                    {episode.role === 'user' ? 'You' : 'Sara'}
                  </span>
                  <span className={`text-xs ${getImportanceColor(episode.importance)}`}>
                    {getImportanceLabel(episode.importance)}
                  </span>
                </div>
                <p className="text-sm text-[#f8fafc] line-clamp-2 mb-2">
                  {episode.content}
                </p>
                <div className="text-xs text-[#a1a1aa]">
                  {new Date(episode.created_at).toLocaleDateString()} {new Date(episode.created_at).toLocaleTimeString()}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Right Panel - Episode Details */}
      <div className={`flex-1 flex flex-col ${
        isMobile && mobileTab !== 'detail' ? 'hidden' : ''
      }`}>
        {selectedEpisode ? (
          <>
            {/* Detail Header */}
            <div className="p-6 border-b border-[#3f3f46]">
              <div className="flex items-start justify-between mb-4">
                <div>
                  <div className="flex items-center gap-3 mb-2">
                    <span className={`px-3 py-1 text-sm font-medium rounded ${
                      selectedEpisode.role === 'user'
                        ? 'bg-blue-500/20 text-blue-400'
                        : 'bg-purple-500/20 text-purple-400'
                    }`}>
                      {selectedEpisode.role === 'user' ? 'You' : 'Sara'}
                    </span>
                    <span className="text-sm text-[#a1a1aa]">
                      {new Date(selectedEpisode.created_at).toLocaleString()}
                    </span>
                  </div>
                  <div className="text-xs text-[#a1a1aa]">
                    Source: {selectedEpisode.source || 'conversation'}
                  </div>
                </div>
                <button
                  onClick={() => deleteEpisode(selectedEpisode.id)}
                  className="px-3 py-1 text-sm bg-red-600/20 text-red-400 rounded hover:bg-red-600/30"
                >
                  Delete
                </button>
              </div>

              {/* Importance Slider */}
              <div className="mt-4">
                <div className="flex items-center justify-between mb-2">
                  <label className="text-sm font-medium text-[#f8fafc]">
                    Importance
                  </label>
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-medium ${getImportanceColor(selectedEpisode.importance)}`}>
                      {getImportanceLabel(selectedEpisode.importance)} ({Math.round(selectedEpisode.importance * 100)}%)
                    </span>
                    {editingImportance === selectedEpisode.id ? (
                      <button
                        onClick={() => setEditingImportance(null)}
                        className="text-xs text-[#a1a1aa] hover:text-[#f8fafc]"
                      >
                        Cancel
                      </button>
                    ) : (
                      <button
                        onClick={() => setEditingImportance(selectedEpisode.id)}
                        className="text-xs text-blue-400 hover:text-blue-300"
                      >
                        Edit
                      </button>
                    )}
                  </div>
                </div>
                {editingImportance === selectedEpisode.id ? (
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.1"
                      value={selectedEpisode.importance}
                      onChange={(e) => {
                        const newValue = parseFloat(e.target.value)
                        setSelectedEpisode({ ...selectedEpisode, importance: newValue })
                      }}
                      className="flex-1"
                    />
                    <button
                      onClick={() => updateImportance(selectedEpisode.id, selectedEpisode.importance)}
                      className="px-3 py-1 text-xs bg-[#0d7ff2] text-white rounded hover:bg-[#0c6fd1]"
                    >
                      Save
                    </button>
                  </div>
                ) : (
                  <div className="w-full bg-[#3f3f46] rounded-full h-2">
                    <div
                      className={`h-2 rounded-full ${
                        selectedEpisode.importance >= 0.8
                          ? 'bg-red-500'
                          : selectedEpisode.importance >= 0.5
                          ? 'bg-yellow-500'
                          : 'bg-green-500'
                      }`}
                      style={{ width: `${selectedEpisode.importance * 100}%` }}
                    ></div>
                  </div>
                )}
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 p-6 overflow-y-auto">
              <h4 className="text-sm font-medium text-[#a1a1aa] mb-3">Content</h4>
              <div className="bg-[#27272a] rounded-lg border border-[#3f3f46] p-4">
                <p className="text-[#f8fafc] whitespace-pre-wrap leading-relaxed">
                  {selectedEpisode.content}
                </p>
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center text-[#a1a1aa]">
              <div className="w-16 h-16 mx-auto mb-4 bg-[#27272a] rounded-full flex items-center justify-center">
                <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                </svg>
              </div>
              <h3 className="text-lg font-medium mb-2">Select a memory</h3>
              <p className="text-sm">Choose a memory from the list to view and manage it</p>
            </div>
          </div>
        )}
      </div>

      {/* Mobile Bottom Tab Bar */}
      {isMobile && (
        <div className="fixed bottom-0 left-0 right-0 bg-[#18181b] border-t border-[#3f3f46] flex items-center justify-around px-4 py-3 z-50">
          <button
            onClick={() => setMobileTab('list')}
            className={`flex flex-col items-center gap-1 px-6 py-2 rounded tap-target ${
              mobileTab === 'list' ? 'text-[#0d7ff2]' : 'text-[#a1a1aa]'
            }`}
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
            <span className="text-xs font-medium">List</span>
          </button>

          <button
            onClick={() => setMobileTab('detail')}
            className={`flex flex-col items-center gap-1 px-6 py-2 rounded tap-target ${
              mobileTab === 'detail' ? 'text-[#0d7ff2]' : 'text-[#a1a1aa]'
            }`}
            disabled={!selectedEpisode}
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <span className="text-xs font-medium">Detail</span>
          </button>
        </div>
      )}
    </div>
  )
}
