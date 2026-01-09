type Mode = 'wakeWord' | 'pushToTalk' | 'silent'

interface NoteData {
  id: string
  title: string
  content: string
}

interface TimerData {
  id: string
  name: string
  remainingSeconds: number
}

declare global {
  interface Window {
    electronAPI: {
      getMode: () => Promise<Mode>
      setMode: (mode: Mode) => Promise<void>
      onModeChanged: (callback: (mode: Mode) => void) => void
      getApiUrl: () => Promise<string>
      setApiUrl: (url: string) => Promise<void>
      getAuthToken: () => Promise<string | null>
      setAuthToken: (token: string | null) => Promise<void>
      activityDetected: () => void
      onVisibilityChanged: (callback: (visible: boolean) => void) => void
      showChat: (options?: { voice?: boolean }) => void
      hideChat: () => void
      onStartVoice: (callback: () => void) => void
      showNote: (noteData: NoteData) => void
      closeNote: () => void
      showTimer: (timerData: TimerData) => void
      closeTimer: (timerId: string) => void
      updateTimer: (timerData: { id: string; remainingSeconds: number }) => void
      onTimerUpdate: (callback: (data: { id: string; remainingSeconds: number }) => void) => void
      showContextMenu: () => void
      onOpenSettings: (callback: () => void) => void
    }
  }
}

export {}
