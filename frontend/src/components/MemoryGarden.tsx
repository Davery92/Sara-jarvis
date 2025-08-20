import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../config'
import KnowledgeGraph from './KnowledgeGraph'
import TimelineView from './TimelineView'
import MemoryManager from './MemoryManager'

interface DreamInsight {
  id: number
  title: string
  content: string
  type: string
  confidence: number
  created_at: string
  metadata: any
}

interface Note {
  id: number
  title: string
  content: string
  created_at: string
  updated_at: string
  folder_id?: number
}

interface MemoryGardenProps {
  notes: Note[]
  setNotes: React.Dispatch<React.SetStateAction<Note[]>>
  editingNote: number | null
  setEditingNote: React.Dispatch<React.SetStateAction<number | null>>
}

export default function MemoryGarden({
  notes,
  setNotes,
  editingNote,
  setEditingNote
}: MemoryGardenProps) {
  const [currentView, setCurrentView] = useState<'graph' | 'timeline' | 'insights' | 'memory'>('graph')
  const [dreamInsights, setDreamInsights] = useState<DreamInsight[]>([])
  const [loadingInsights, setLoadingInsights] = useState(false)

  useEffect(() => {
    fetchDreamInsights()
  }, [])

  const fetchDreamInsights = async () => {
    setLoadingInsights(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/memory/insights`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setDreamInsights(data.insights || [])
      }
    } catch (error) {
      console.error('Failed to fetch dream insights:', error)
    } finally {
      setLoadingInsights(false)
    }
  }

  const markInsightAsHelpful = async (insightId: number, helpful: boolean) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/memory/insights/${insightId}/feedback`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ helpful })
      })
      // Refresh insights
      fetchDreamInsights()
    } catch (error) {
      console.error('Failed to update insight feedback:', error)
    }
  }

  return (
    <div className="flex h-screen w-full bg-[#18181b] text-[#f8fafc]">
      {/* Left Sidebar */}
      <aside className="flex w-64 flex-col border-r border-[#3f3f46] p-4">
        <div className="mb-6 flex items-center gap-2">
          <div className="h-8 w-8 bg-[#0d7ff2] rounded flex items-center justify-center">
            <span className="text-white font-bold text-sm">S</span>
          </div>
          <h1 className="text-xl font-bold">Memory Garden</h1>
        </div>

        <nav className="flex flex-col gap-1">
          <button
            onClick={() => setCurrentView('graph')}
            className={`flex items-center justify-center rounded-md px-3 py-2 text-sm font-medium ${
              currentView === 'graph' 
                ? 'bg-[#3f3f46] text-[#f8fafc]' 
                : 'text-[#a1a1aa] hover:bg-[#3f3f46] hover:text-[#f8fafc]'
            }`}
          >
            Knowledge Graph
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
            onClick={() => setCurrentView('insights')}
            className={`flex items-center justify-center rounded-md px-3 py-2 text-sm font-medium ${
              currentView === 'insights' 
                ? 'bg-[#3f3f46] text-[#f8fafc]' 
                : 'text-[#a1a1aa] hover:bg-[#3f3f46] hover:text-[#f8fafc]'
            }`}
          >
            Dream Insights
            {dreamInsights.length > 0 && (
              <span className="ml-2 bg-[#0d7ff2] text-white text-xs rounded-full px-2 py-0.5">
                {dreamInsights.length}
              </span>
            )}
          </button>
          
          <button
            onClick={() => setCurrentView('memory')}
            className={`flex items-center justify-center rounded-md px-3 py-2 text-sm font-medium ${
              currentView === 'memory' 
                ? 'bg-[#3f3f46] text-[#f8fafc]' 
                : 'text-[#a1a1aa] hover:bg-[#3f3f46] hover:text-[#f8fafc]'
            }`}
          >
            Memory Manager
          </button>
        </nav>
      </aside>

      {/* Main Content */}
      <main className="flex flex-1 flex-col">
        {/* Header */}
        <header className="flex h-14 items-center border-b border-[#3f3f46] px-6">
          <h2 className="text-lg font-medium">
            {currentView === 'graph' && 'Knowledge Graph'}
            {currentView === 'timeline' && 'Memory Timeline'}
            {currentView === 'insights' && 'Dream Insights'}
            {currentView === 'memory' && 'Memory Management'}
          </h2>
          
          {currentView === 'insights' && (
            <button
              onClick={fetchDreamInsights}
              className="ml-auto px-3 py-1 text-sm bg-[#0d7ff2] text-white rounded hover:bg-[#0c6fd1]"
            >
              Refresh
            </button>
          )}
        </header>

        <div className="flex-1 p-6">
          {currentView === 'graph' && (
            <div className="h-full">
              <KnowledgeGraph 
                notes={notes}
                onNodeClick={(nodeId, nodeType) => {
                  if (nodeType === 'note') {
                    const noteId = parseInt(nodeId)
                    setEditingNote(noteId)
                  }
                }}
                useApiData={true}
              />
            </div>
          )}

          {currentView === 'timeline' && (
            <TimelineView
              notes={notes}
              onItemClick={(item) => {
                if (item.type === 'note' && item.metadata?.note_id) {
                  const noteId = item.metadata.note_id
                  setEditingNote(noteId)
                }
              }}
            />
          )}

          {currentView === 'insights' && (
            <div className="space-y-4">
              {loadingInsights ? (
                <div className="flex items-center justify-center h-32">
                  <div className="text-[#a1a1aa]">Loading dream insights...</div>
                </div>
              ) : dreamInsights.length > 0 ? (
                dreamInsights.map((insight) => (
                  <div key={insight.id} className="bg-[#27272a] rounded-lg border border-[#3f3f46] p-6">
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="px-2 py-1 text-xs font-medium bg-[#0d7ff2] text-white rounded">
                            {insight.type}
                          </span>
                          <span className="text-xs text-[#a1a1aa]">
                            Confidence: {Math.round(insight.confidence * 100)}%
                          </span>
                          <span className="text-xs text-[#a1a1aa]">
                            {new Date(insight.created_at).toLocaleDateString()}
                          </span>
                        </div>
                        <h3 className="text-lg font-medium mb-2">{insight.title}</h3>
                        <p className="text-sm text-[#f8fafc] leading-relaxed whitespace-pre-wrap">
                          {insight.content}
                        </p>
                      </div>
                    </div>
                    
                    <div className="flex items-center gap-2 pt-4 border-t border-[#3f3f46]">
                      <span className="text-xs text-[#a1a1aa] mr-2">Was this insight helpful?</span>
                      <button
                        onClick={() => markInsightAsHelpful(insight.id, true)}
                        className="px-2 py-1 text-xs bg-green-600/20 text-green-400 rounded hover:bg-green-600/30"
                      >
                        👍 Helpful
                      </button>
                      <button
                        onClick={() => markInsightAsHelpful(insight.id, false)}
                        className="px-2 py-1 text-xs bg-red-600/20 text-red-400 rounded hover:bg-red-600/30"
                      >
                        👎 Not helpful
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="flex items-center justify-center h-32">
                  <div className="text-center">
                    <div className="text-4xl mb-4">🌙</div>
                    <h3 className="text-lg font-medium mb-2">No dream insights yet</h3>
                    <p className="text-[#a1a1aa]">Dream insights will appear here as Sara processes your memories</p>
                  </div>
                </div>
              )}
            </div>
          )}

          {currentView === 'memory' && (
            <MemoryManager onClose={() => setCurrentView('graph')} />
          )}
        </div>
      </main>
    </div>
  )
}