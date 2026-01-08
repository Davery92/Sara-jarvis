import { useState, useEffect, useCallback } from 'react'
import FloatingCircle from './components/FloatingCircle'
import MiniChat from './components/MiniChat'
import SettingsModal from './components/SettingsModal'
import NoteViewer from './components/NoteViewer'
import TimerFloat from './components/TimerFloat'
import { sidecarBridge } from './services/sidecarBridge'

export type Mode = 'wakeWord' | 'pushToTalk' | 'silent'
export type VoiceState = 'idle' | 'listening' | 'processing' | 'speaking'
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

function App() {
  const viewType = getViewType()
  const [mode, setMode] = useState<Mode>('wakeWord')
  const [voiceState, setVoiceState] = useState<VoiceState>('idle')
  const [isVisible, setIsVisible] = useState(true)
  const [showSettings, setShowSettings] = useState(false)
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)

  // Initialize from Electron store
  useEffect(() => {
    const init = async () => {
      if (window.electronAPI) {
        const savedMode = await window.electronAPI.getMode()
        setMode(savedMode)
        setChatOpen(savedMode === 'silent')

        const token = await window.electronAPI.getAuthToken()
        setIsAuthenticated(!!token)

        // Listen for mode changes from tray menu
        window.electronAPI.onModeChanged((newMode) => {
          console.log('[App] Mode changed to:', newMode)
          setMode(newMode)
          setChatOpen(newMode === 'silent')
        })

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

      // Connect to sidecar and listen for wake word
      sidecarBridge.on('wake_word_detected', () => {
        console.log('[App] Wake word detected!')
        // Open chat window when wake word is heard
        window.electronAPI?.showChat()
        setChatOpen(true)
        setVoiceState('listening')
      })

      // Listen for activity updates
      sidecarBridge.on('activity_update', (msg) => {
        console.log('[App] Activity update:', msg)
      })
    }
    init()

    return () => {
      sidecarBridge.disconnect()
    }
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
          state={voiceState}
          mode={mode}
          chatOpen={chatOpen}
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
