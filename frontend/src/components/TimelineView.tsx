import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../config'

interface Note {
  id: number
  title: string
  content: string
  created_at: string
  updated_at: string
  folder_id?: number
}

interface TimelineItem {
  id: string
  type: 'note' | 'episode' | 'document' | 'insight'
  title: string
  content: string
  timestamp: string
  metadata?: any
}

interface TimelineViewProps {
  notes: Note[]
  onItemClick?: (item: TimelineItem) => void
}

export default function TimelineView({ notes, onItemClick }: TimelineViewProps) {
  const [timelineItems, setTimelineItems] = useState<TimelineItem[]>([])
  const [loading, setLoading] = useState(false)
  const [dateFilter, setDateFilter] = useState<'all' | 'today' | 'week' | 'month'>('all')
  const [typeFilter, setTypeFilter] = useState<'all' | 'notes' | 'episodes' | 'documents' | 'insights'>('all')

  useEffect(() => {
    loadTimelineData()
  }, [notes, dateFilter, typeFilter])

  const loadTimelineData = async () => {
    setLoading(true)
    try {
      const items: TimelineItem[] = []

      // Add notes to timeline
      if (typeFilter === 'all' || typeFilter === 'notes') {
        const noteItems: TimelineItem[] = notes.map(note => ({
          id: `note-${note.id}`,
          type: 'note',
          title: note.title || 'Untitled Note',
          content: note.content,
          timestamp: note.updated_at,
          metadata: { note_id: note.id, created_at: note.created_at }
        }))
        items.push(...noteItems)
      }

      // Add episodes from memory if available
      if (typeFilter === 'all' || typeFilter === 'episodes') {
        try {
          const episodesResponse = await fetch(`${APP_CONFIG.apiUrl}/memory/episodes?page=1&per_page=50`, {
            credentials: 'include'
          })
          
          if (episodesResponse.ok) {
            const episodesData = await episodesResponse.json()
            const episodeItems: TimelineItem[] = episodesData.episodes.map((episode: any) => ({
              id: `episode-${episode.id}`,
              type: 'episode',
              title: `${episode.role}: ${episode.content.substring(0, 50)}...`,
              content: episode.content,
              timestamp: episode.created_at,
              metadata: { 
                role: episode.role, 
                importance: episode.importance,
                source: episode.source 
              }
            }))
            items.push(...episodeItems)
          }
        } catch (error) {
          console.warn('Failed to load episodes for timeline:', error)
        }
      }

      // Add dream insights if available
      if (typeFilter === 'all' || typeFilter === 'insights') {
        try {
          const insightsResponse = await fetch(`${APP_CONFIG.apiUrl}/memory/insights`, {
            credentials: 'include'
          })
          
          if (insightsResponse.ok) {
            const insightsData = await insightsResponse.json()
            const insightItems: TimelineItem[] = insightsData.insights.map((insight: any) => ({
              id: `insight-${insight.id}`,
              type: 'insight',
              title: `💡 ${insight.title}`,
              content: insight.content,
              timestamp: insight.created_at,
              metadata: { 
                type: insight.type,
                confidence: insight.confidence,
                helpful: insight.helpful
              }
            }))
            items.push(...insightItems)
          }
        } catch (error) {
          console.warn('Failed to load insights for timeline:', error)
        }
      }

      // Filter by date
      const filteredItems = filterItemsByDate(items, dateFilter)

      // Sort by timestamp (newest first)
      filteredItems.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())

      setTimelineItems(filteredItems)
    } catch (error) {
      console.error('Failed to load timeline data:', error)
    } finally {
      setLoading(false)
    }
  }

  const filterItemsByDate = (items: TimelineItem[], filter: string): TimelineItem[] => {
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    
    switch (filter) {
      case 'today':
        return items.filter(item => new Date(item.timestamp) >= today)
      case 'week':
        const weekAgo = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000)
        return items.filter(item => new Date(item.timestamp) >= weekAgo)
      case 'month':
        const monthAgo = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000)
        return items.filter(item => new Date(item.timestamp) >= monthAgo)
      default:
        return items
    }
  }

  const formatDate = (timestamp: string) => {
    const date = new Date(timestamp)
    const now = new Date()
    const diffInHours = (now.getTime() - date.getTime()) / (1000 * 60 * 60)
    
    if (diffInHours < 24) {
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    } else if (diffInHours < 24 * 7) {
      return date.toLocaleDateString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })
    } else {
      return date.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })
    }
  }

  const getItemIcon = (type: string) => {
    switch (type) {
      case 'note':
        return '📝'
      case 'episode':
        return '💭'
      case 'document':
        return '📄'
      case 'insight':
        return '🌙'
      default:
        return '•'
    }
  }

  const getItemColor = (type: string) => {
    switch (type) {
      case 'note':
        return 'border-[#4ade80]'
      case 'episode':
        return 'border-[#0d7ff2]'
      case 'document':
        return 'border-[#f59e0b]'
      case 'insight':
        return 'border-[#8b5cf6]'
      default:
        return 'border-[#3f3f46]'
    }
  }

  return (
    <div className="w-full h-full bg-[#27272a] rounded-lg border border-[#3f3f46] overflow-hidden">
      <div className="p-4 border-b border-[#3f3f46]">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-medium text-[#f8fafc]">Knowledge Timeline</h3>
          <div className="flex items-center gap-2">
            <select
              value={dateFilter}
              onChange={(e) => setDateFilter(e.target.value as any)}
              className="bg-[#3f3f46] text-[#f8fafc] text-sm rounded px-2 py-1 border border-[#52525b]"
            >
              <option value="all">All Time</option>
              <option value="today">Today</option>
              <option value="week">This Week</option>
              <option value="month">This Month</option>
            </select>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value as any)}
              className="bg-[#3f3f46] text-[#f8fafc] text-sm rounded px-2 py-1 border border-[#52525b]"
            >
              <option value="all">All Types</option>
              <option value="notes">Notes Only</option>
              <option value="episodes">Episodes Only</option>
              <option value="documents">Documents Only</option>
              <option value="insights">Insights Only</option>
            </select>
          </div>
        </div>
        <p className="text-sm text-[#a1a1aa]">
          {timelineItems.length} items • Chronological view of your knowledge
        </p>
      </div>

      <div className="relative h-[calc(100%-80px)] overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-2 border-[#0d7ff2] border-t-transparent mx-auto mb-2"></div>
              <p className="text-sm text-[#a1a1aa]">Loading timeline...</p>
            </div>
          </div>
        ) : timelineItems.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <span className="material-symbols-outlined text-6xl text-[#a1a1aa] mb-4 block">timeline</span>
              <h3 className="text-lg font-medium mb-2 text-[#f8fafc]">No items in timeline</h3>
              <p className="text-[#a1a1aa]">Create notes or start conversations to see your knowledge timeline</p>
            </div>
          </div>
        ) : (
          <div className="relative">
            {/* Timeline line */}
            <div className="absolute left-8 top-4 bottom-4 w-0.5 bg-gradient-to-b from-[#0d7ff2] via-[#4ade80] to-[#f59e0b]"></div>
            
            {/* Timeline items */}
            <div className="space-y-4 p-4">
              {timelineItems.map((item, index) => (
                <div key={item.id} className="relative flex items-start gap-4">
                  {/* Timeline dot */}
                  <div className={`relative z-10 w-4 h-4 rounded-full border-2 ${getItemColor(item.type)} bg-[#27272a] flex items-center justify-center`}>
                    <div className={`w-2 h-2 rounded-full ${
                      item.type === 'note' ? 'bg-[#4ade80]' :
                      item.type === 'episode' ? 'bg-[#0d7ff2]' :
                      'bg-[#f59e0b]'
                    }`}></div>
                  </div>

                  {/* Item content */}
                  <div 
                    className="flex-1 cursor-pointer"
                    onClick={() => onItemClick?.(item)}
                  >
                    <div className="bg-[#18181b] rounded-lg border border-[#3f3f46] p-3 hover:border-[#52525b] transition-colors">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="text-sm">{getItemIcon(item.type)}</span>
                          <span className="text-sm font-medium text-[#f8fafc]">{item.title}</span>
                          {item.metadata?.importance && (
                            <span className="text-xs px-2 py-0.5 bg-[#0d7ff2] text-white rounded">
                              {Math.round(item.metadata.importance * 100)}%
                            </span>
                          )}
                        </div>
                        <span className="text-xs text-[#a1a1aa]">{formatDate(item.timestamp)}</span>
                      </div>
                      <p className="text-sm text-[#a1a1aa] line-clamp-2">
                        {item.content}
                      </p>
                      {item.metadata?.role && (
                        <div className="mt-2 flex items-center gap-2">
                          <span className="text-xs px-2 py-0.5 bg-[#3f3f46] text-[#a1a1aa] rounded">
                            {item.metadata.role}
                          </span>
                          {item.metadata.source && (
                            <span className="text-xs text-[#a1a1aa]">
                              via {item.metadata.source}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}