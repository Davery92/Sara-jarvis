/// <reference types="vite/client" />

export type Mode = 'wakeWord' | 'pushToTalk' | 'silent'

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
      resizeWindow: (width: number, height: number) => void
      showContextMenu: () => void
      onOpenSettings: (callback: () => void) => void
    }
  }
}
