import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../../config'
import LearningChat from './LearningChat'
import TopicSidebar from './TopicSidebar'
import TopicCanvas from './TopicCanvas'
import Scratchpad from './Scratchpad'
import LearningPathPanel from './LearningPathPanel'

// Types
export interface LearningTopic {
  id: string
  user_id: string
  parent_id: string | null
  title: string
  description: string | null
  status: string
  mastery_level: number
  priority: number
  created_at: string
  updated_at: string
}

export interface TopicSource {
  id: string
  topic_id: string
  source_type: string
  url: string | null
  title: string | null
  quality_score: number
  fetch_status: string
  created_at: string
}

export interface LearningArtifact {
  id: string
  topic_id: string | null
  artifact_type: string
  title: string | null
  content: Record<string, unknown>
  version: number
  created_at: string
  updated_at: string
}

type LearningView = 'chat' | 'canvas' | 'sources'

export default function LearningSection() {
  // State
  const [topics, setTopics] = useState<LearningTopic[]>([])
  const [currentTopic, setCurrentTopic] = useState<LearningTopic | null>(null)
  const [currentView, setCurrentView] = useState<LearningView>('chat')
  const [sources, setSources] = useState<TopicSource[]>([])
  const [scratchpadContent, setScratchpadContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [showScratchpad, setShowScratchpad] = useState(true)
  const [showLearningPath, setShowLearningPath] = useState(false)
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768)

  // Load topics on mount
  useEffect(() => {
    loadTopics()

    const handleResize = () => setIsMobile(window.innerWidth < 768)
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  // Load sources when topic changes
  useEffect(() => {
    if (currentTopic) {
      loadSources(currentTopic.id)
      loadScratchpad(currentTopic.id)
    } else {
      setSources([])
      setScratchpadContent('')
    }
  }, [currentTopic?.id])

  const loadTopics = async () => {
    try {
      setLoading(true)
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/topics`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setTopics(data)
      }
    } catch (error) {
      console.error('Failed to load topics:', error)
    } finally {
      setLoading(false)
    }
  }

  const loadSources = async (topicId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/topics/${topicId}/sources`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setSources(data)
      }
    } catch (error) {
      console.error('Failed to load sources:', error)
    }
  }

  const loadScratchpad = async (topicId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/topics/${topicId}/scratchpad`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setScratchpadContent(data.content || '')
      }
    } catch (error) {
      console.error('Failed to load scratchpad:', error)
    }
  }

  const handleCreateTopic = async (title: string, description?: string, parentId?: string, autoResearch?: boolean) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/topics`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ title, description, parent_id: parentId })
      })
      if (response.ok) {
        const newTopic = await response.json()
        setTopics([newTopic, ...topics])
        setCurrentTopic(newTopic)

        // Auto-research: discover and add sources automatically
        if (autoResearch) {
          try {
            const researchResponse = await fetch(`${APP_CONFIG.apiUrl}/api/learn/topics/${newTopic.id}/auto-research`, {
              method: 'POST',
              credentials: 'include'
            })
            if (researchResponse.ok) {
              const researchData = await researchResponse.json()
              // Reload sources to show the newly added ones
              if (researchData.sources_added > 0) {
                loadSources(newTopic.id)
              }
            }
          } catch (researchError) {
            console.error('Auto-research failed:', researchError)
            // Don't fail the topic creation if auto-research fails
          }
        }
      }
    } catch (error) {
      console.error('Failed to create topic:', error)
    }
  }

  const handleUpdateScratchpad = async (content: string) => {
    if (!currentTopic) return

    setScratchpadContent(content)

    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/learn/topics/${currentTopic.id}/scratchpad`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ content })
      })
    } catch (error) {
      console.error('Failed to save scratchpad:', error)
    }
  }

  const handleAddSource = async (url: string, sourceType: string = 'web') => {
    if (!currentTopic) return

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/sources`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          topic_id: currentTopic.id,
          source_type: sourceType,
          url
        })
      })
      if (response.ok) {
        const newSource = await response.json()
        setSources([newSource, ...sources])
      }
    } catch (error) {
      console.error('Failed to add source:', error)
    }
  }

  // Handler for selecting topic from learning path
  const handleSelectTopicFromPath = (topicId: string) => {
    const topic = topics.find(t => t.id === topicId)
    if (topic) {
      setCurrentTopic(topic)
    }
  }

  const handleFetchSource = async (sourceId: string) => {
    try {
      // Update local state to show fetching status
      setSources(sources.map(s =>
        s.id === sourceId ? { ...s, fetch_status: 'fetching' } : s
      ))

      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/sources/${sourceId}/fetch`, {
        method: 'POST',
        credentials: 'include'
      })

      if (response.ok) {
        const result = await response.json()
        // Update source with new status
        setSources(sources.map(s =>
          s.id === sourceId
            ? { ...s, fetch_status: result.status === 'success' ? 'fetched' : 'failed', quality_score: 0.7 }
            : s
        ))
      } else {
        // Mark as failed
        setSources(sources.map(s =>
          s.id === sourceId ? { ...s, fetch_status: 'failed' } : s
        ))
      }
    } catch (error) {
      console.error('Failed to fetch source:', error)
      setSources(sources.map(s =>
        s.id === sourceId ? { ...s, fetch_status: 'failed' } : s
      ))
    }
  }

  // Mobile layout
  if (isMobile) {
    return (
      <div className="flex flex-col h-[calc(100vh-7rem)] bg-gray-900">
        {/* Mobile Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
          <div className="flex items-center gap-2">
            <span className="material-icons text-teal-400">school</span>
            <span className="font-semibold text-white">
              {currentTopic?.title || 'Learning'}
            </span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setCurrentView('chat')}
              className={`px-3 py-1 rounded text-sm ${
                currentView === 'chat' ? 'bg-teal-600 text-white' : 'text-gray-400'
              }`}
            >
              Chat
            </button>
            <button
              onClick={() => setCurrentView('canvas')}
              className={`px-3 py-1 rounded text-sm ${
                currentView === 'canvas' ? 'bg-teal-600 text-white' : 'text-gray-400'
              }`}
            >
              Canvas
            </button>
          </div>
        </div>

        {/* Mobile Content */}
        <div className="flex-1 overflow-hidden">
          {currentView === 'chat' ? (
            <LearningChat
              topicId={currentTopic?.id || null}
              topicTitle={currentTopic?.title}
            />
          ) : (
            <TopicCanvas
              topicId={currentTopic?.id || null}
            />
          )}
        </div>
      </div>
    )
  }

  // Desktop layout - 3 zone
  return (
    <div className="flex h-[calc(100vh-4rem)] bg-gray-900">
      {/* Left Sidebar - Topics */}
      <div className="w-64 border-r border-gray-700 flex flex-col">
        <TopicSidebar
          topics={topics}
          currentTopic={currentTopic}
          onSelectTopic={setCurrentTopic}
          onCreateTopic={handleCreateTopic}
          loading={loading}
        />
      </div>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* View Tabs */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700">
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-semibold text-white">
              {currentTopic?.title || 'Select a topic to start learning'}
            </h2>
            <button
              onClick={() => setShowLearningPath(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium text-teal-400 hover:bg-teal-500/10 transition-colors"
              title="View Learning Path"
            >
              <span className="material-icons text-sm">route</span>
              Path
            </button>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setCurrentView('chat')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                currentView === 'chat'
                  ? 'bg-teal-600 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`}
            >
              <span className="flex items-center gap-2">
                <span className="material-icons text-sm">chat</span>
                Chat
              </span>
            </button>
            <button
              onClick={() => setCurrentView('canvas')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                currentView === 'canvas'
                  ? 'bg-teal-600 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`}
            >
              <span className="flex items-center gap-2">
                <span className="material-icons text-sm">account_tree</span>
                Canvas
              </span>
            </button>
            <button
              onClick={() => setCurrentView('sources')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                currentView === 'sources'
                  ? 'bg-teal-600 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`}
            >
              <span className="flex items-center gap-2">
                <span className="material-icons text-sm">library_books</span>
                Sources
              </span>
            </button>
            <button
              onClick={() => setShowScratchpad(!showScratchpad)}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                showScratchpad
                  ? 'bg-gray-700 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`}
            >
              <span className="flex items-center gap-2">
                <span className="material-icons text-sm">edit_note</span>
                Notes
              </span>
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden flex">
          {/* Main View */}
          <div className={`${showScratchpad ? 'flex-1' : 'w-full'} overflow-hidden`}>
            {currentView === 'chat' && (
              <LearningChat
                topicId={currentTopic?.id || null}
                topicTitle={currentTopic?.title}
              />
            )}
            {currentView === 'canvas' && (
              <TopicCanvas
                topicId={currentTopic?.id || null}
              />
            )}
            {currentView === 'sources' && (
              <div className="h-full overflow-auto p-4">
                <div className="max-w-2xl mx-auto space-y-4">
                  {/* Add Source Form */}
                  <div className="bg-gray-800 rounded-lg p-4">
                    <h3 className="text-sm font-medium text-gray-300 mb-3">Add Source</h3>
                    <form
                      onSubmit={(e) => {
                        e.preventDefault()
                        const form = e.target as HTMLFormElement
                        const input = form.elements.namedItem('url') as HTMLInputElement
                        if (input.value.trim()) {
                          handleAddSource(input.value.trim())
                          input.value = ''
                        }
                      }}
                      className="flex gap-2"
                    >
                      <input
                        type="url"
                        name="url"
                        placeholder="Enter URL..."
                        className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-teal-500"
                        disabled={!currentTopic}
                      />
                      <button
                        type="submit"
                        disabled={!currentTopic}
                        className="bg-teal-600 hover:bg-teal-700 disabled:bg-gray-700 text-white px-4 py-2 rounded-lg text-sm"
                      >
                        Add
                      </button>
                    </form>
                  </div>

                  {/* Sources List */}
                  {sources.length === 0 ? (
                    <div className="text-center py-12 text-gray-500">
                      {currentTopic ? 'No sources yet. Add a URL above to get started.' : 'Select a topic to view sources'}
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {sources.map(source => (
                        <div
                          key={source.id}
                          className="bg-gray-800 rounded-lg p-4 hover:bg-gray-750 transition-colors"
                        >
                          <div className="flex items-start justify-between gap-4">
                            <div className="min-w-0">
                              <p className="text-white font-medium truncate">
                                {source.title || source.url}
                              </p>
                              {source.title && source.url && (
                                <p className="text-gray-400 text-sm truncate mt-1">
                                  {source.url}
                                </p>
                              )}
                              <div className="flex items-center gap-3 mt-2 text-xs text-gray-500">
                                <span className="capitalize">{source.source_type}</span>
                                <span className={`px-2 py-0.5 rounded ${
                                  source.fetch_status === 'fetched'
                                    ? 'bg-green-900/50 text-green-400'
                                    : source.fetch_status === 'failed'
                                    ? 'bg-red-900/50 text-red-400'
                                    : 'bg-yellow-900/50 text-yellow-400'
                                }`}>
                                  {source.fetch_status}
                                </span>
                              </div>
                            </div>
                            <div className="flex items-center gap-2">
                              {source.fetch_status === 'pending' && (
                                <button
                                  onClick={() => handleFetchSource(source.id)}
                                  className="px-2 py-1 text-xs bg-teal-600 hover:bg-teal-700 text-white rounded transition-colors"
                                >
                                  Fetch
                                </button>
                              )}
                              {source.fetch_status === 'fetching' && (
                                <span className="text-xs text-teal-400 animate-pulse">
                                  Processing...
                                </span>
                              )}
                              {source.fetch_status === 'fetched' && (
                                <span className="text-xs text-gray-500">
                                  {Math.round(source.quality_score * 100)}%
                                </span>
                              )}
                              {source.fetch_status === 'failed' && (
                                <button
                                  onClick={() => handleFetchSource(source.id)}
                                  className="px-2 py-1 text-xs bg-red-600 hover:bg-red-700 text-white rounded transition-colors"
                                >
                                  Retry
                                </button>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Scratchpad */}
          {showScratchpad && (
            <div className="w-80 border-l border-gray-700">
              <Scratchpad
                content={scratchpadContent}
                onChange={handleUpdateScratchpad}
                disabled={!currentTopic}
              />
            </div>
          )}
        </div>
      </div>

      {/* Learning Path Panel */}
      <LearningPathPanel
        isVisible={showLearningPath}
        onClose={() => setShowLearningPath(false)}
        onSelectTopic={handleSelectTopicFromPath}
      />
    </div>
  )
}
