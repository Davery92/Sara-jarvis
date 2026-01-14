import { useEffect } from 'react'
import { useAuthStore } from './store/authStore'
import { useCanvasStore } from './store/canvasStore'
import LoginScreen from './components/LoginScreen'
import Canvas from './components/Canvas'
import ModeWheel from './components/ModeWheel'
import NotesPicker from './components/NotesPicker'

function App() {
  const { user, isLoading, checkAuth } = useAuthStore()
  const { isNotesPickerOpen } = useCanvasStore()

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
    <div className="w-full h-full relative overflow-hidden bg-canvas-bg">
      <Canvas />
      <ModeWheel />
      {isNotesPickerOpen && <NotesPicker />}
    </div>
  )
}

export default App
