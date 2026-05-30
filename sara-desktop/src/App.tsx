import { useState, useEffect, useCallback } from 'react'
import FloatingCircle from './components/FloatingCircle'
import MiniChat from './components/MiniChat'
import SettingsModal from './components/SettingsModal'
import NoteViewer from './components/NoteViewer'
import TimerFloat from './components/TimerFloat'

export type ViewType = 'circle' | 'chat' | 'note' | 'timer' | 'settings'

// Get view type from URL query parameter
function getViewType(): ViewType {
  const params = new URLSearchParams(window.location.search)
  const view = params.get('view')
  if (view === 'chat') return 'chat'
  if (view === 'note') return 'note'
  if (view === 'timer') return 'timer'
  if (view === 'settings') return 'settings'
  return 'circle'
}

// Check if pre-authenticated from URL param (avoids race condition)
function isPreAuthenticated(): boolean {
  const params = new URLSearchParams(window.location.search)
  return params.get('authenticated') === 'true'
}

function App() {
  const viewType = getViewType()
  const [isVisible, setIsVisible] = useState(true)
  const [showSettings, setShowSettings] = useState(false)
  // Initialize auth from URL param if present (main process knows auth state)
  const [isAuthenticated, setIsAuthenticated] = useState(isPreAuthenticated())
  const [chatOpen, setChatOpen] = useState(false)

  // Initialize from Electron store
  useEffect(() => {
    const init = async () => {
      if (window.electronAPI) {
        const token = await window.electronAPI.getAuthToken()
        setIsAuthenticated(!!token)

        // Listen for visibility changes (only affects circle window)
        if (viewType === 'circle') {
          window.electronAPI.onVisibilityChanged((visible) => {
            setIsVisible(visible)
          })
        }

        // Listen for settings request
        window.electronAPI.onOpenSettings(() => {
          setShowSettings(true)
        })
      }
    }
    init()
  }, [viewType])

  // Handle circle click - toggle chat open/closed
  const handleCircleClick = useCallback(() => {
    console.log('[App] Circle clicked, chatOpen:', chatOpen)
    if (chatOpen) {
      // Close chat
      window.electronAPI?.hideChat()
      setChatOpen(false)
    } else {
      // Open chat
      window.electronAPI?.showChat()
      setChatOpen(true)
    }
  }, [chatOpen])

  // Handle right click
  const handleRightClick = useCallback(() => {
    window.electronAPI?.showContextMenu()
  }, [])

  // Report activity on any interaction
  const handleActivity = useCallback(() => {
    window.electronAPI?.activityDetected()
  }, [])

  // Handle chat close
  const handleChatClose = useCallback(() => {
    window.electronAPI?.hideChat()
  }, [])

  // Render based on view type
  if (viewType === 'note') {
    // Note viewer window
    return <NoteViewer />
  }

  if (viewType === 'timer') {
    // Timer float window
    return <TimerFloat />
  }

  if (viewType === 'settings') {
    // Settings window - standalone centered window
    return (
      <div className="settings-window w-full h-full">
        <SettingsModal
          onClose={() => window.electronAPI?.closeSettings()}
          onAuthChange={setIsAuthenticated}
        />
      </div>
    )
  }

  if (viewType === 'chat') {
    // Chat window - just render the chat (fully interactive, no drag)
    return (
      <div className="chat-window w-full h-full">
        <MiniChat
          onClose={handleChatClose}
          isAuthenticated={isAuthenticated}
          onNeedAuth={() => setShowSettings(true)}
        />
        {showSettings && (
          <SettingsModal
            onClose={() => setShowSettings(false)}
            onAuthChange={setIsAuthenticated}
          />
        )}
      </div>
    )
  }

  // Circle window - draggable background, clickable circle
  return (
    <div
      className="circle-window w-full h-full"
      onMouseMove={handleActivity}
      onKeyDown={handleActivity}
    >
      <div className={`transition-opacity duration-500 ${isVisible ? 'opacity-100' : 'opacity-20'}`}>
        <FloatingCircle
          onClick={handleCircleClick}
          onRightClick={handleRightClick}
        />
      </div>

      {showSettings && (
        <SettingsModal
          onClose={() => setShowSettings(false)}
          onAuthChange={setIsAuthenticated}
        />
      )}
    </div>
  )
}

export default App
