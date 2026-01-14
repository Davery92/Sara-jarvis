import { useEffect, useState, useCallback } from 'react'
import { useAuthStore } from './store/authStore'
import { useCanvasStore } from './store/canvasStore'
import LoginScreen from './components/LoginScreen'
import Canvas from './components/Canvas'
import ModeWheel from './components/ModeWheel'
import NotesPicker from './components/NotesPicker'
import { ThreeScene } from './components/three'
import { modelsApi } from './services/api'
import type { FileViewerWindowData } from './types'

const MODEL_3D_EXTENSIONS = ['stl', 'obj', 'gltf', 'glb']

function App() {
  const { user, isLoading, checkAuth } = useAuthStore()
  const { isNotesPickerOpen, addSceneObject, openWindow } = useCanvasStore()
  const [isDragOver, setIsDragOver] = useState(false)

  // Check authentication on mount
  useEffect(() => {
    checkAuth()
  }, [checkAuth])

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
      // Escape to close panels
      if (e.key === 'Escape') {
        useCanvasStore.getState().setNotesPickerOpen(false)
      }
      // F11 or F for fullscreen toggle (F11 is browser default)
      if (e.key === 'f' && !e.ctrlKey && !e.metaKey) {
        if (document.fullscreenElement) {
          document.exitFullscreen()
        } else {
          document.documentElement.requestFullscreen()
        }
      }
      // R to reset view
      if (e.key === 'r' && !e.ctrlKey && !e.metaKey) {
        useCanvasStore.getState().resetTransform()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

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

      {/* UI overlays */}
      <ModeWheel />
      {isNotesPickerOpen && <NotesPicker />}

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
