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
      getApiUrl: () => Promise<string>
      setApiUrl: (url: string) => Promise<void>
      getAuthToken: () => Promise<string | null>
      setAuthToken: (token: string | null) => Promise<void>
      activityDetected: () => void
      onVisibilityChanged: (callback: (visible: boolean) => void) => void
      showChat: () => void
      hideChat: () => void
      showNote: (noteData: NoteData) => void
      closeNote: () => void
      closeSettings: () => void
      showTimer: (timerData: TimerData) => void
      closeTimer: (timerId: string) => void
      updateTimer: (timerData: { id: string; remainingSeconds: number }) => void
      onTimerUpdate: (callback: (data: { id: string; remainingSeconds: number }) => void) => void
      showContextMenu: () => void
      onOpenSettings: (callback: () => void) => void
      openUrl: (url: string) => void
      requestMicPermission: () => Promise<boolean>
      getMicPermissionStatus: () => Promise<string>
    }
  }
}

export {}
