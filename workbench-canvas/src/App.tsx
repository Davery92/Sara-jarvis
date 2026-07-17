import { useEffect, useState, useCallback } from 'react'
import { useAuthStore } from './store/authStore'
import { useCanvasStore } from './store/canvasStore'
import LoginScreen from './components/LoginScreen'
import Canvas from './components/Canvas'
import ModeWheel from './components/ModeWheel'
import NotesPicker from './components/NotesPicker'
import MapPicker from './components/maps/MapPicker'
import MapImportModal from './components/maps/MapImportModal'
import MapNodeEditor from './components/maps/MapNodeEditor'
import SaraStatusStrip from './components/SaraStatusStrip'
import AttentionFeedPanel from './components/AttentionFeedPanel'
import ScenePicker from './components/ScenePicker'
import PartnerThoughts from './components/PartnerThoughts'
import PartnerActionQueue from './components/PartnerActionQueue'
import MissionFeed from './components/MissionFeed'
import { ThreeScene } from './components/three'
import { modelsApi } from './services/api'
import { pollPendingWorkspaceCommands } from './services/workspaceCommands'
import type { FileViewerWindowData } from './types'

const MODEL_3D_EXTENSIONS = ['stl', 'obj', 'gltf', 'glb']

function App() {
  const { user, isLoading, checkAuth } = useAuthStore()
  const {
    isNotesPickerOpen,
    isMapPickerOpen,
    isMapImportModalOpen,
    editingNodeId,
    mapSelection,
    maps,
    addSceneObject,
    openWindow,
    deleteMapNode,
    deleteMapEdge,
    cancelConnection,
    clearMapSelection,
    setNotesPickerOpen,
    setMapPickerOpen,
    setEditingNodeId,
    loadStateFromServer,
  } = useCanvasStore()
  const [isDragOver, setIsDragOver] = useState(false)
  const [isAttentionOpen, setIsAttentionOpen] = useState(false)
  const [isScenePickerOpen, setIsScenePickerOpen] = useState(false)

  // Check authentication on mount
  useEffect(() => {
    checkAuth()
  }, [checkAuth])

  // Load persisted workspace state once authenticated
  useEffect(() => {
    if (!user) return
    loadStateFromServer().catch((err) => {
      console.error('[App] Failed to load workspace state:', err)
    })
  }, [user, loadStateFromServer])

  // Request fullscreen on first interaction
  useEffect(() => {
    const requestFullscreen = () => {
      if (document.documentElement.requestFullscreen && !document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {
          // Fullscreen might be blocked, that's okay
        })
      }
      // Remove listener after first attempt
      document.removeEventListener('click', requestFullscreen)
    }

    document.addEventListener('click', requestFullscreen)
    return () => document.removeEventListener('click', requestFullscreen)
  }, [])

  // Handle keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Skip if typing in an input or textarea
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return
      }

      // Escape to close panels and cancel connection mode
      if (e.key === 'Escape') {
        const state = useCanvasStore.getState()
        if (state.mapSelection?.connectionSource) {
          cancelConnection()
        } else if (state.isMapPickerOpen) {
          setMapPickerOpen(false)
        } else if (state.isNotesPickerOpen) {
          setNotesPickerOpen(false)
        } else if (state.editingNodeId) {
          setEditingNodeId(null)
        } else if (state.mapSelection) {
          clearMapSelection()
        }
      }

      // Delete key to delete selected map items
      if (e.key === 'Delete' || e.key === 'Backspace') {
        const state = useCanvasStore.getState()
        if (state.mapSelection) {
          const { mapId, nodeIds, edgeIds } = state.mapSelection
          // Find the map to check if it's readonly
          const map = state.maps.find((m) => m.id === mapId)
          if (map && !map.isReadonly) {
            // Delete selected edges first
            edgeIds.forEach((edgeId) => deleteMapEdge(mapId, edgeId))
            // Delete selected nodes
            nodeIds.forEach((nodeId) => deleteMapNode(mapId, nodeId))
          }
        }
      }

      // App shortcuts (no modifier keys)
      if (!e.ctrlKey && !e.metaKey && !e.altKey) {
        switch (e.key.toLowerCase()) {
          case 'm': // Maps
            setMapPickerOpen(!useCanvasStore.getState().isMapPickerOpen)
            break
          case 'c': // Chat
            openWindow('chat', {})
            break
          case 'n': // Notes
            openWindow('note', {})
            break
          case 's': // Search/Research
            openWindow('research', {})
            break
          case 'p': // Projects
            openWindow('projects', {})
            break
          case 't': // Timers
            openWindow('timers', {})
            break
          case 'g': // Gym/Fitness
            openWindow('fitness', {})
            break
          case 'l': // Learning
            openWindow('learning', {})
            break
          case 'f': // Fullscreen
            if (document.fullscreenElement) {
              document.exitFullscreen()
            } else {
              document.documentElement.requestFullscreen()
            }
            break
          case 'r': // Reset view
            useCanvasStore.getState().resetTransform()
            break
          case '?': // Help (show shortcuts)
            openWindow('settings', {})
            break
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [cancelConnection, clearMapSelection, deleteMapEdge, deleteMapNode, openWindow, setEditingNodeId, setMapPickerOpen, setNotesPickerOpen])

  // Poll for pending workspace commands from voice
  useEffect(() => {
    if (!user) return // Only poll when authenticated

    const pollPendingCommands = async () => {
      await pollPendingWorkspaceCommands('app')
    }

    // Poll every 2 seconds
    const interval = setInterval(pollPendingCommands, 2000)

    // Initial poll
    pollPendingCommands()

    return () => clearInterval(interval)
  }, [user])

  // Handle drag and drop for files
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)
  }, [])

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)

    const files = Array.from(e.dataTransfer.files)
    if (files.length === 0) return

    for (let index = 0; index < files.length; index++) {
      const file = files[index]
      const ext = file.name.split('.').pop()?.toLowerCase() || ''

      if (MODEL_3D_EXTENSIONS.includes(ext)) {
        try {
          const model = await modelsApi.upload(file)
          addSceneObject({
            modelId: model.id,
            modelUrl: model.download_url,
            format: ext as 'stl' | 'obj' | 'gltf' | 'glb',
            position: { x: index * 3, y: 0, z: index * 3 },
            rotation: { x: 0, y: 0, z: 0 },
            scale: 1,
            filename: model.filename,
          })
        } catch (err) {
          console.error('Failed to upload 3D model:', err)
        }
      } else if (ext === 'pdf' || file.type === 'application/pdf') {
        // Handle PDFs specially - create a blob URL for viewing
        const blobUrl = URL.createObjectURL(file)
        const fileData: FileViewerWindowData = {
          filename: file.name,
          content: blobUrl,
          mimeType: 'application/pdf',
          source: 'local',
        }
        openWindow('fileviewer', fileData, {
          title: file.name,
          position: { x: 100 + index * 30, y: 100 + index * 30 },
          width: 800,
          height: 900,
        })
      } else if (file.type.startsWith('image/') || ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(ext)) {
        // Handle images - create a blob URL
        const blobUrl = URL.createObjectURL(file)
        const fileData: FileViewerWindowData = {
          filename: file.name,
          content: blobUrl,
          mimeType: file.type || `image/${ext}`,
          source: 'local',
        }
        openWindow('fileviewer', fileData, {
          title: file.name,
          position: { x: 100 + index * 30, y: 100 + index * 30 },
          width: 600,
          height: 500,
        })
      } else if (['docx', 'doc', 'xlsx', 'xls', 'pptx', 'ppt'].includes(ext)) {
        // Handle Office documents - create blob URL for download
        const blobUrl = URL.createObjectURL(file)
        const fileData: FileViewerWindowData = {
          filename: file.name,
          content: blobUrl,
          mimeType: file.type || 'application/octet-stream',
          source: 'local',
        }
        openWindow('fileviewer', fileData, {
          title: file.name,
          position: { x: 100 + index * 30, y: 100 + index * 30 },
        })
      } else {
        const reader = new FileReader()
        reader.onload = (event) => {
          const content = event.target?.result as string
          const fileData: FileViewerWindowData = {
            filename: file.name,
            content,
            mimeType: file.type || undefined,
            source: 'local',
          }
          openWindow('fileviewer', fileData, {
            title: file.name,
            position: { x: 100 + index * 30, y: 100 + index * 30 },
          })
        }
        reader.readAsText(file)
      }
    }
  }, [addSceneObject, openWindow])

  // Show loading state
  if (isLoading) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-canvas-bg">
        <div className="text-white text-xl">Loading...</div>
      </div>
    )
  }

  // Show login if not authenticated
  if (!user) {
    return <LoginScreen />
  }

  // Main canvas view
  return (
    <div
      className="w-full h-full relative overflow-hidden bg-canvas-bg"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* 3D Layer - behind everything */}
      <ThreeScene className="absolute inset-0 z-0" />

      {/* 2D Layer - windows float above */}
      <div className="absolute inset-0 z-10 pointer-events-none">
        <Canvas />
      </div>

      {/* Sara ambient presence */}
      {user && (
        <SaraStatusStrip
          onAttentionClick={() => setIsAttentionOpen(prev => !prev)}
          onScenePickerClick={() => setIsScenePickerOpen(prev => !prev)}
          attentionOpen={isAttentionOpen}
        />
      )}
      <AttentionFeedPanel isOpen={isAttentionOpen} onClose={() => setIsAttentionOpen(false)} />
      <ScenePicker isOpen={isScenePickerOpen} onClose={() => setIsScenePickerOpen(false)} />
      <PartnerThoughts />
      <PartnerActionQueue />
      <MissionFeed />

      {/* UI overlays */}
      <ModeWheel />
      {isNotesPickerOpen && <NotesPicker />}
      {isMapPickerOpen && <MapPicker />}
      {isMapImportModalOpen && <MapImportModal />}

      {/* Map Node Editor */}
      {editingNodeId && mapSelection && (() => {
        const map = maps.find((m) => m.id === mapSelection.mapId)
        const node = map?.mapData.nodes.find((n) => n.id === editingNodeId)
        if (map && node && !map.isReadonly) {
          return (
            <MapNodeEditor
              mapId={map.id}
              nodeId={node.id}
              initialContent={node.content}
              onClose={() => setEditingNodeId(null)}
            />
          )
        }
        return null
      })()}

      {/* Drag overlay */}
      {isDragOver && (
        <div className="absolute inset-0 bg-teal-500/20 border-4 border-dashed border-teal-500 flex items-center justify-center pointer-events-none z-50">
          <div className="bg-canvas-surface/90 px-8 py-4 rounded-lg shadow-xl">
            <p className="text-white text-lg font-medium">Drop 3D models or files here</p>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
