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
      getWebappUrl: () => Promise<string>
      setWebappUrl: (url: string) => Promise<void>
      getAuthToken: () => Promise<string | null>
      setAuthToken: (token: string | null) => Promise<void>
      getHudMode: () => Promise<string>
      setHudMode: (mode: string) => Promise<void>
      getFollowActiveDisplay: () => Promise<boolean>
      setFollowActiveDisplay: (enabled: boolean) => Promise<void>
      activityDetected: () => void
      onVisibilityChanged: (callback: (visible: boolean) => void) => void
      showChat: () => void
      hideChat: () => void
      showNote: (noteData: NoteData) => void
      closeNote: () => void
      saveQuickNote: (title: string, content: string) => Promise<{ success: boolean; queued?: boolean; note?: any }>
      closeQuickNote: () => void
      openQuickNote: () => void
      openOverlay: (kind: string, payload?: Record<string, any>) => void
      requestVoiceNote: () => void
      requestScreenshotAndAsk: () => void
      getFocusTrackingEnabled: () => Promise<boolean>
      setFocusTrackingEnabled: (enabled: boolean) => Promise<void>
      getConnectionStatus: () => Promise<{ sidecarRunning: boolean; bridgeConnected: boolean }>
      getHotkeys: () => Promise<Record<string, string>>
      setHotkey: (action: string, accelerator: string) => Promise<boolean>
      getVoiceSettings: () => Promise<{ ttsVoice: string; ttsSpeed: number; useJetsonAtHome: boolean; jetsonHost: string }>
      setVoiceSettings: (settings: { ttsVoice?: string; ttsSpeed?: number; useJetsonAtHome?: boolean; jetsonHost?: string }) => Promise<void>
      getOverlaySettings: () => Promise<{ autoOpenReports: boolean; enabledByKind: Record<string, boolean> }>
      setOverlaySettings: (settings: { autoOpenReports?: boolean; enabledByKind?: Record<string, boolean> }) => Promise<void>
      onRecordVoiceNoteRequested: (callback: () => void) => void
      onVoiceState: (callback: (state: string) => void) => void
      onVoiceNoteLevel: (callback: (level: number) => void) => void
      onScreenshotConfig: (callback: (enabled: boolean) => void) => void
      onJetsonTranscript: (callback: (turn: { user?: string; sara?: string }) => void) => void
      onBackendEvent: (callback: (event: string, data: any) => void) => void
      onAuthInvalid: (callback: () => void) => void
      notifyAuthInvalid: () => void
      requestPermissionsRecheck: () => void
      openSystemSettings: (url: string) => void
      onPermissionsReport: (callback: (permissions: Record<string, string>) => void) => void
      platform: string
      getAutostart: () => Promise<boolean>
      setAutostart: (enabled: boolean) => Promise<void>
      closeSettings: () => void
      showTimer: (timerData: TimerData) => void
      closeTimer: (timerId: string) => void
      updateTimer: (timerData: { id: string; remainingSeconds: number }) => void
      onTimerUpdate: (callback: (data: { id: string; remainingSeconds: number }) => void) => void
      showContextMenu: () => void
      onOpenSettings: (callback: () => void) => void
      openUrl: (url: string) => void
    }
  }
}

export {}
