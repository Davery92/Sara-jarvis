import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../../config'
import LearningChat from './LearningChat'
import TopicSidebar from './TopicSidebar'
import TopicCanvas from './TopicCanvas'
import Scratchpad from './Scratchpad'
import LearningPathPanel from './LearningPathPanel'
import BlueprintImporter from './BlueprintImporter'
import ArtifactLibrary from './ArtifactLibrary'
import LessonReader from './LessonReader'
import FloatingLearningPanel, { PanelRect } from './FloatingLearningPanel'

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

type LearningView = 'chat' | 'canvas' | 'sources' | 'library'
type FloatingPanelId = 'learning-chat' | 'learning-reader'
const LEARNING_DETACHED_PANELS_PREF_KEY = 'sara.learning.detachedPanels.v1'

interface TopicDetachedPanelsPrefs {
  chatDetached?: boolean
  chatRect?: PanelRect
  readerDetached?: boolean
  readerRect?: PanelRect
  readerArtifactId?: string | null
}

interface DetachedPanelsPrefsStore {
  topics?: Record<string, TopicDetachedPanelsPrefs>
}

function defaultChatRect(): PanelRect {
  return {
    x: Math.max(24, window.innerWidth - 520),
    y: 88,
    width: 480,
    height: Math.max(420, window.innerHeight - 176)
  }
}

function defaultReaderRect(): PanelRect {
  return {
    x: 90,
    y: 84,
    width: Math.min(820, Math.max(560, window.innerWidth - 380)),
    height: Math.max(460, window.innerHeight - 150)
  }
}

function normalizeRect(value: unknown, fallback: PanelRect): PanelRect {
  if (!value || typeof value !== 'object') return fallback
  const raw = value as Partial<PanelRect>
  if (
    typeof raw.x !== 'number' ||
    typeof raw.y !== 'number' ||
    typeof raw.width !== 'number' ||
    typeof raw.height !== 'number'
  ) {
    return fallback
  }
  if (!Number.isFinite(raw.x) || !Number.isFinite(raw.y) || !Number.isFinite(raw.width) || !Number.isFinite(raw.height)) {
    return fallback
  }
  return {
    x: raw.x,
    y: raw.y,
    width: raw.width,
    height: raw.height
  }
}

function readDetachedPanelsPrefsStore(): DetachedPanelsPrefsStore {
  try {
    const raw = localStorage.getItem(LEARNING_DETACHED_PANELS_PREF_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as DetachedPanelsPrefsStore
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function writeDetachedPanelsPrefsStore(store: DetachedPanelsPrefsStore) {
  try {
    localStorage.setItem(LEARNING_DETACHED_PANELS_PREF_KEY, JSON.stringify(store))
  } catch {
    // ignore
  }
}

function readTopicDetachedPanelsPrefs(topicId: string): TopicDetachedPanelsPrefs {
  const store = readDetachedPanelsPrefsStore()
  return store.topics?.[topicId] || {}
}

function writeTopicDetachedPanelsPrefs(topicId: string, prefs: TopicDetachedPanelsPrefs) {
  const store = readDetachedPanelsPrefsStore()
  writeDetachedPanelsPrefsStore({
    ...store,
    topics: {
      ...(store.topics || {}),
      [topicId]: prefs
    }
  })
}

function getArtifactTypeLabel(artifactType: string): string {
  if (artifactType === 'lesson') return 'Lesson'
  if (artifactType === 'study_guide_pareto') return 'Pareto Guide'
  if (artifactType === 'study_guide_deep') return 'Deep Guide'
  return artifactType.replace(/_/g, ' ')
}

function getArtifactTypeIcon(artifactType: string): string {
  if (artifactType === 'lesson') return 'menu_book'
  if (artifactType === 'study_guide_pareto') return 'bolt'
  if (artifactType === 'study_guide_deep') return 'psychology'
  return 'article'
}

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
  const [showBlueprintImporter, setShowBlueprintImporter] = useState(false)
  const [autoResearching, setAutoResearching] = useState(false)
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768)
  const [artifacts, setArtifacts] = useState<LearningArtifact[]>([])
  const [activeArtifact, setActiveArtifact] = useState<LearningArtifact | null>(null)
  const [detachedArtifact, setDetachedArtifact] = useState<LearningArtifact | null>(null)
  const [pendingDetachedArtifactId, setPendingDetachedArtifactId] = useState<string | null>(null)
  const [isChatDetached, setIsChatDetached] = useState(false)
  const [chatRect, setChatRect] = useState<PanelRect>(() => defaultChatRect())
  const [readerRect, setReaderRect] = useState<PanelRect>(() => defaultReaderRect())
  const [prefsReadyTopicId, setPrefsReadyTopicId] = useState<string | null>(null)
  const [floatingZIndex, setFloatingZIndex] = useState<Record<FloatingPanelId, number>>({
    'learning-chat': 100,
    'learning-reader': 101
  })
  const [loadingArtifacts, setLoadingArtifacts] = useState(false)
  const [mobileReaderMode, setMobileReaderMode] = useState<'reader' | 'chat'>('reader')

  // Load topics on mount
  useEffect(() => {
    loadTopics()

    const handleResize = () => setIsMobile(window.innerWidth < 768)
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  // Load sources and artifacts when topic changes
  useEffect(() => {
    if (currentTopic) {
      loadSources(currentTopic.id)
      loadScratchpad(currentTopic.id)
      loadArtifacts(currentTopic.id)
    } else {
      setSources([])
      setScratchpadContent('')
      setArtifacts([])
    }
  }, [currentTopic?.id])

  // Keep opened artifacts scoped to selected topic
  useEffect(() => {
    if (!currentTopic?.id) {
      setActiveArtifact(null)
      setDetachedArtifact(null)
      return
    }

    setActiveArtifact((prev) => (prev && prev.topic_id === currentTopic.id ? prev : null))
    setDetachedArtifact((prev) => (prev && prev.topic_id === currentTopic.id ? prev : null))
  }, [currentTopic?.id])

  // Disable detached panels on mobile; desktop-only behavior.
  useEffect(() => {
    if (!isMobile) return
    setIsChatDetached(false)
    setDetachedArtifact(null)
    setPendingDetachedArtifactId(null)
  }, [isMobile])

  // Restore detached panel preferences whenever topic changes.
  useEffect(() => {
    const topicId = currentTopic?.id
    setPrefsReadyTopicId(null)

    if (!topicId) {
      setPendingDetachedArtifactId(null)
      setIsChatDetached(false)
      return
    }

    if (isMobile) return

    const prefs = readTopicDetachedPanelsPrefs(topicId)
    setChatRect(normalizeRect(prefs.chatRect, defaultChatRect()))
    setReaderRect(normalizeRect(prefs.readerRect, defaultReaderRect()))
    setIsChatDetached(Boolean(prefs.chatDetached))
    setPendingDetachedArtifactId(
      prefs.readerDetached && prefs.readerArtifactId ? prefs.readerArtifactId : null
    )
    setPrefsReadyTopicId(topicId)
  }, [currentTopic?.id, isMobile])

  const loadTopics = async (): Promise<LearningTopic[]> => {
    try {
      setLoading(true)
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/topics?include_all=true`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setTopics(data)
        return data
      }
      return []
    } catch (error) {
      console.error('Failed to load topics:', error)
      return []
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

  const loadArtifacts = async (topicId: string) => {
    setLoadingArtifacts(true)
    try {
      const types = ['lesson', 'study_guide_pareto', 'study_guide_deep']
      const results = await Promise.all(
        types.map(async (type) => {
          try {
            const response = await fetch(
              `${APP_CONFIG.apiUrl}/api/learn/artifacts?topic_id=${topicId}&artifact_type=${type}`,
              { credentials: 'include' }
            )
            if (response.ok) {
              const data = await response.json()
              return Array.isArray(data) ? data : (data?.artifacts || [])
            }
            return []
          } catch {
            return []
          }
        })
      )
      setArtifacts(results.flat())
    } catch (error) {
      console.error('Failed to load artifacts:', error)
      setArtifacts([])
    } finally {
      setLoadingArtifacts(false)
    }
  }

  const bringFloatingPanelToFront = (panelId: FloatingPanelId) => {
    setFloatingZIndex((prev) => {
      const max = Math.max(...Object.values(prev), 100)
      return {
        ...prev,
        [panelId]: max + 1
      }
    })
  }

  const handleOpenArtifact = (artifact: LearningArtifact) => {
    setPendingDetachedArtifactId(null)
    setDetachedArtifact(null)
    setActiveArtifact(artifact)
    setMobileReaderMode('reader')
  }

  const handleDetachArtifact = () => {
    if (!activeArtifact) return
    setPendingDetachedArtifactId(null)
    setDetachedArtifact(activeArtifact)
    setActiveArtifact(null)
    bringFloatingPanelToFront('learning-reader')
  }

  const handleAttachArtifact = () => {
    if (!detachedArtifact) return
    setPendingDetachedArtifactId(null)
    setActiveArtifact(detachedArtifact)
    setDetachedArtifact(null)
  }

  const handleDetachChat = () => {
    setIsChatDetached(true)
    bringFloatingPanelToFront('learning-chat')
  }

  const handleAttachChat = () => {
    setIsChatDetached(false)
    if (!activeArtifact) {
      setCurrentView('chat')
    }
  }

  // When preferences request a detached reader, restore the referenced artifact once loaded.
  useEffect(() => {
    if (!pendingDetachedArtifactId || !currentTopic?.id || isMobile) return

    const match = artifacts.find(
      (artifact) => artifact.id === pendingDetachedArtifactId && artifact.topic_id === currentTopic.id
    )
    if (match) {
      setDetachedArtifact(match)
      setActiveArtifact(null)
      setPendingDetachedArtifactId(null)
      bringFloatingPanelToFront('learning-reader')
      return
    }

    if (!loadingArtifacts) {
      setPendingDetachedArtifactId(null)
    }
  }, [pendingDetachedArtifactId, artifacts, loadingArtifacts, currentTopic?.id, isMobile])

  // Persist detached state + geometry per topic for continuity.
  useEffect(() => {
    if (isMobile) return
    const topicId = currentTopic?.id
    if (!topicId || prefsReadyTopicId !== topicId) return
    if (pendingDetachedArtifactId) return

    writeTopicDetachedPanelsPrefs(topicId, {
      chatDetached: isChatDetached,
      chatRect,
      readerDetached: Boolean(detachedArtifact),
      readerRect,
      readerArtifactId: detachedArtifact?.id || null
    })
  }, [
    isMobile,
    currentTopic?.id,
    prefsReadyTopicId,
    pendingDetachedArtifactId,
    isChatDetached,
    chatRect,
    readerRect,
    detachedArtifact?.id
  ])

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

  const handleFileUpload = async (file: File) => {
    if (!currentTopic) return

    // Validate file type
    const allowedTypes = ['.pdf', '.txt', '.md', '.markdown']
    const fileExt = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!allowedTypes.includes(fileExt)) {
      console.error('Unsupported file type:', fileExt)
      return
    }

    // Create a temporary source entry to show upload progress
    const tempId = `uploading-${Date.now()}`
    const tempSource: TopicSource = {
      id: tempId,
      topic_id: currentTopic.id,
      source_type: fileExt === '.pdf' ? 'pdf' : 'document',
      url: null,
      title: file.name,
      quality_score: 0,
      fetch_status: 'uploading',
      created_at: new Date().toISOString()
    }
    setSources([tempSource, ...sources])

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('topic_id', currentTopic.id)

      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/sources/upload`, {
        method: 'POST',
        credentials: 'include',
        body: formData
      })

      if (response.ok) {
        const result = await response.json()
        // Replace temp source with real one
        setSources(prev => prev.map(s =>
          s.id === tempId
            ? {
                id: result.source_id,
                topic_id: currentTopic.id,
                source_type: fileExt === '.pdf' ? 'pdf' : 'document',
                url: null,
                title: result.title || file.name,
                quality_score: 0.7,
                fetch_status: result.status === 'success' ? 'fetched' : 'failed',
                created_at: new Date().toISOString()
              }
            : s
        ))
      } else {
        // Mark as failed
        setSources(prev => prev.map(s =>
          s.id === tempId ? { ...s, fetch_status: 'failed' } : s
        ))
      }
    } catch (error) {
      console.error('Failed to upload file:', error)
      // Remove temp source on error
      setSources(prev => prev.filter(s => s.id !== tempId))
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()

    const files = e.dataTransfer.files
    if (files.length > 0) {
      handleFileUpload(files[0])
    }
  }

  // Auto-research: discover and add sources automatically
  const handleAutoResearch = async () => {
    if (!currentTopic || autoResearching) return
    setAutoResearching(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/topics/${currentTopic.id}/auto-research`, {
        method: 'POST',
        credentials: 'include'
      })
      if (response.ok) {
        const result = await response.json()
        // Reload sources to show new ones
        const srcRes = await fetch(`${APP_CONFIG.apiUrl}/api/learn/topics/${currentTopic.id}/sources`, {
          credentials: 'include'
        })
        if (srcRes.ok) {
          const srcData = await srcRes.json()
          setSources(srcData)
        }
      }
    } catch (err) {
      console.error('Auto-research failed:', err)
    } finally {
      setAutoResearching(false)
    }
  }

  // Delete a topic
  const handleDeleteTopic = async (topicId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/topics/${topicId}`, {
        method: 'DELETE',
        credentials: 'include'
      })
      if (response.ok) {
        setTopics(topics.filter(t => t.id !== topicId))
        if (currentTopic?.id === topicId) {
          setCurrentTopic(null)
        }
      }
    } catch (err) {
      console.error('Delete topic failed:', err)
    }
  }

  // Handler for selecting topic from learning path
  const handleSelectTopicFromPath = (topicId: string) => {
    const topic = topics.find(t => t.id === topicId)
    if (topic) {
      setCurrentTopic(topic)
    }
  }

  const handleBlueprintMaterialized = async (rootTopicId?: string) => {
    const refreshedTopics = await loadTopics()
    if (rootTopicId) {
      const matched = refreshedTopics.find(t => t.id === rootTopicId)
      if (matched) {
        setCurrentTopic(matched)
      }
    }
    setCurrentView('chat')
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
      <>
        <div className="flex flex-col h-full bg-gray-900">
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
                onClick={() => setShowBlueprintImporter(true)}
                className="px-3 py-1 rounded text-sm text-teal-300 hover:text-white hover:bg-gray-800"
                title="Import Learning Plan"
              >
                Import
              </button>
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
              <button
                onClick={() => setCurrentView('library')}
                className={`px-3 py-1 rounded text-sm ${
                  currentView === 'library' ? 'bg-teal-600 text-white' : 'text-gray-400'
                }`}
              >
                Library
              </button>
            </div>
          </div>

          {/* Mobile Content */}
          <div className="flex-1 overflow-hidden">
            {activeArtifact ? (
              <div className="flex flex-col h-full">
                {/* Toggle bar for mobile reader/chat */}
                <div className="flex border-b border-gray-700">
                  <button
                    onClick={() => setMobileReaderMode('reader')}
                    className={`flex-1 py-2 text-sm font-medium text-center transition-colors ${
                      mobileReaderMode === 'reader'
                        ? 'bg-teal-600 text-white'
                        : 'text-gray-400 hover:text-white'
                    }`}
                  >
                    Reader
                  </button>
                  <button
                    onClick={() => setMobileReaderMode('chat')}
                    className={`flex-1 py-2 text-sm font-medium text-center transition-colors ${
                      mobileReaderMode === 'chat'
                        ? 'bg-teal-600 text-white'
                        : 'text-gray-400 hover:text-white'
                    }`}
                  >
                    Chat
                  </button>
                </div>
                <div className="flex-1 overflow-hidden">
                  {mobileReaderMode === 'reader' ? (
                    <LessonReader
                      artifact={activeArtifact}
                      onClose={() => setActiveArtifact(null)}
                    />
                  ) : (
                    <LearningChat
                      topicId={currentTopic?.id || null}
                      topicTitle={currentTopic?.title}
                    />
                  )}
                </div>
              </div>
            ) : currentView === 'chat' ? (
              <LearningChat
                topicId={currentTopic?.id || null}
                topicTitle={currentTopic?.title}
              />
            ) : currentView === 'library' ? (
              <ArtifactLibrary
                artifacts={artifacts}
                loading={loadingArtifacts}
                onOpenArtifact={handleOpenArtifact}
                onRefresh={() => currentTopic && loadArtifacts(currentTopic.id)}
              />
            ) : (
              <TopicCanvas
                topicId={currentTopic?.id || null}
              />
            )}
          </div>
        </div>
        <BlueprintImporter
          isVisible={showBlueprintImporter}
          onClose={() => setShowBlueprintImporter(false)}
          onMaterialized={handleBlueprintMaterialized}
          parentTopicId={currentTopic?.id || null}
          parentTopicTitle={currentTopic?.title || null}
          availableTopics={topics}
          onOpenArtifact={(artifact) => {
            handleOpenArtifact(artifact)
            setShowBlueprintImporter(false)
          }}
        />
      </>
    )
  }

  // Desktop layout - 3 zone
  return (
    <div className="flex h-full bg-gray-900 relative">
      {/* Left Sidebar - Topics */}
      <div className="w-64 border-r border-gray-700 flex flex-col">
        <TopicSidebar
          topics={topics}
          currentTopic={currentTopic}
          onSelectTopic={setCurrentTopic}
          onCreateTopic={handleCreateTopic}
          onDeleteTopic={handleDeleteTopic}
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
              onClick={() => setShowBlueprintImporter(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium text-teal-400 hover:bg-teal-500/10 transition-colors"
              title="Import Blueprint"
            >
              <span className="material-icons text-sm">upload_file</span>
              Import Plan
            </button>
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
              onClick={() => setCurrentView('library')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                currentView === 'library'
                  ? 'bg-teal-600 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`}
            >
              <span className="flex items-center gap-2">
                <span className="material-icons text-sm">local_library</span>
                Library
                {artifacts.length > 0 && (
                  <span className="bg-teal-700/50 text-teal-300 text-[10px] px-1.5 py-0.5 rounded-full">
                    {artifacts.length}
                  </span>
                )}
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
            <button
              onClick={isChatDetached ? handleAttachChat : handleDetachChat}
              disabled={!currentTopic}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                isChatDetached
                  ? 'bg-blue-700/50 text-blue-100 hover:bg-blue-700/70'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              } disabled:bg-gray-800 disabled:text-gray-600`}
              title={isChatDetached ? 'Attach chat back' : 'Detach chat into a floating panel'}
            >
              <span className="flex items-center gap-2">
                <span className="material-icons text-sm">
                  {isChatDetached ? 'vertical_align_bottom' : 'open_in_new'}
                </span>
                {isChatDetached ? 'Attach Chat' : 'Detach Chat'}
              </span>
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden flex">
          {/* Split view: reader + chat when an artifact is open */}
          {activeArtifact ? (
            <div className="flex-1 flex overflow-hidden">
              <div className={`${isChatDetached ? 'w-full' : 'w-[60%] border-r border-gray-700'} overflow-hidden`}>
                <LessonReader
                  artifact={activeArtifact}
                  onClose={() => setActiveArtifact(null)}
                  onDetach={handleDetachArtifact}
                  showDetachButton
                />
              </div>
              {!isChatDetached && (
                <div className="w-[40%] overflow-hidden">
                  <LearningChat
                    topicId={currentTopic?.id || null}
                    topicTitle={currentTopic?.title}
                  />
                </div>
              )}
            </div>
          ) : (
          <>
          {/* Main View */}
          <div className={`${showScratchpad ? 'flex-1' : 'w-full'} overflow-hidden`}>
            {currentView === 'chat' && (
              isChatDetached ? (
                <div className="h-full flex items-center justify-center px-6">
                  <div className="max-w-md bg-gray-800 border border-gray-700 rounded-md p-6 text-center">
                    <span className="material-icons text-3xl text-blue-400 mb-2">open_in_new</span>
                    <h3 className="text-base font-semibold text-white mb-1">Chat is detached</h3>
                    <p className="text-sm text-gray-400 mb-4">
                      Continue in the floating chat window while you work on guides, sources, and your canvas.
                    </p>
                    <button
                      onClick={handleAttachChat}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm transition-colors"
                    >
                      <span className="material-icons text-sm">vertical_align_bottom</span>
                      Attach Chat
                    </button>
                  </div>
                </div>
              ) : (
                <LearningChat
                  topicId={currentTopic?.id || null}
                  topicTitle={currentTopic?.title}
                />
              )
            )}
            {currentView === 'canvas' && (
              <TopicCanvas
                topicId={currentTopic?.id || null}
              />
            )}
            {currentView === 'library' && (
              <ArtifactLibrary
                artifacts={artifacts}
                loading={loadingArtifacts}
                onOpenArtifact={handleOpenArtifact}
                onRefresh={() => currentTopic && loadArtifacts(currentTopic.id)}
              />
            )}
            {currentView === 'sources' && (
              <div
                className="h-full overflow-auto p-4"
                onDragOver={handleDragOver}
                onDrop={handleDrop}
              >
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

                  {/* File Upload Zone */}
                  <div className="bg-gray-800 rounded-lg p-4">
                    <h3 className="text-sm font-medium text-gray-300 mb-3">Upload File</h3>
                    <label
                      className={`flex flex-col items-center justify-center w-full h-24 border-2 border-dashed rounded-lg cursor-pointer transition-colors ${
                        currentTopic
                          ? 'border-gray-600 hover:border-teal-500 hover:bg-gray-700/50'
                          : 'border-gray-700 cursor-not-allowed opacity-50'
                      }`}
                    >
                      <div className="flex flex-col items-center justify-center pt-2 pb-2">
                        <span className="material-icons text-gray-400 text-2xl mb-1">upload_file</span>
                        <p className="text-sm text-gray-400">
                          <span className="font-semibold text-teal-400">Click to upload</span> or drag and drop
                        </p>
                        <p className="text-xs text-gray-500 mt-1">PDF, TXT, MD files</p>
                      </div>
                      <input
                        type="file"
                        className="hidden"
                        accept=".pdf,.txt,.md,.markdown"
                        disabled={!currentTopic}
                        onChange={(e) => {
                          const file = e.target.files?.[0]
                          if (file) {
                            handleFileUpload(file)
                            e.target.value = ''  // Reset input
                          }
                        }}
                      />
                    </label>
                  </div>

                  {/* Auto-Research Button */}
                  <button
                    onClick={handleAutoResearch}
                    disabled={!currentTopic || autoResearching}
                    className="w-full flex items-center justify-center gap-2 bg-teal-600/20 hover:bg-teal-600/30 disabled:bg-gray-800 disabled:text-gray-600 text-teal-400 border border-teal-600/30 rounded-lg px-4 py-3 text-sm font-medium transition-colors"
                  >
                    <span className={`material-icons text-sm ${autoResearching ? 'animate-spin' : ''}`}>
                      {autoResearching ? 'refresh' : 'travel_explore'}
                    </span>
                    {autoResearching ? 'Searching for sources...' : 'Find Sources Automatically'}
                  </button>

                  {/* Sources List */}
                  {sources.length === 0 ? (
                    <div className="text-center py-12 text-gray-500">
                      {currentTopic ? 'No sources yet. Add a URL or upload a file above.' : 'Select a topic to view sources'}
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
                                    : source.fetch_status === 'uploading'
                                    ? 'bg-blue-900/50 text-blue-400'
                                    : 'bg-yellow-900/50 text-yellow-400'
                                }`}>
                                  {source.fetch_status === 'uploading' ? 'uploading...' : source.fetch_status}
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
                              {(source.fetch_status === 'fetching' || source.fetch_status === 'uploading') && (
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
          </>
          )}
        </div>
      </div>

      {/* Learning Path Panel */}
      <LearningPathPanel
        isVisible={showLearningPath}
        onClose={() => setShowLearningPath(false)}
        onSelectTopic={handleSelectTopicFromPath}
        focusTopicId={currentTopic?.id}
        focusTopicTitle={currentTopic?.title}
      />

      <BlueprintImporter
        isVisible={showBlueprintImporter}
        onClose={() => setShowBlueprintImporter(false)}
        onMaterialized={handleBlueprintMaterialized}
        parentTopicId={currentTopic?.id || null}
        parentTopicTitle={currentTopic?.title || null}
        availableTopics={topics}
        onOpenArtifact={(artifact) => {
          handleOpenArtifact(artifact)
          setShowBlueprintImporter(false)
        }}
      />

      {detachedArtifact && (
        <FloatingLearningPanel
          id="learning-reader"
          title={detachedArtifact.title || 'Detached Reader'}
          subtitle={getArtifactTypeLabel(detachedArtifact.artifact_type)}
          icon={getArtifactTypeIcon(detachedArtifact.artifact_type)}
          initialRect={readerRect}
          zIndex={floatingZIndex['learning-reader']}
          onFocus={bringFloatingPanelToFront}
          onAttach={handleAttachArtifact}
          onClose={() => setDetachedArtifact(null)}
          onRectChange={setReaderRect}
        >
          <LessonReader
            artifact={detachedArtifact}
            onClose={() => setDetachedArtifact(null)}
            showHeader={false}
          />
        </FloatingLearningPanel>
      )}

      {isChatDetached && (
        <FloatingLearningPanel
          id="learning-chat"
          title={currentTopic?.title ? `Tutor Chat: ${currentTopic.title}` : 'Tutor Chat'}
          subtitle="Socratic tutor"
          icon="chat"
          initialRect={chatRect}
          zIndex={floatingZIndex['learning-chat']}
          onFocus={bringFloatingPanelToFront}
          onAttach={handleAttachChat}
          onClose={() => setIsChatDetached(false)}
          onRectChange={setChatRect}
        >
          <LearningChat
            topicId={currentTopic?.id || null}
            topicTitle={currentTopic?.title}
          />
        </FloatingLearningPanel>
      )}
    </div>
  )
}
