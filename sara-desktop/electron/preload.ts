const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  // API URL
  getApiUrl: (): Promise<string> => ipcRenderer.invoke('get-api-url'),
  setApiUrl: (url: string): Promise<void> => ipcRenderer.invoke('set-api-url', url),

  // Webapp URL (base for overlay windows)
  getWebappUrl: (): Promise<string> => ipcRenderer.invoke('get-webapp-url'),
  setWebappUrl: (url: string): Promise<void> => ipcRenderer.invoke('set-webapp-url', url),

  // Auth token
  getAuthToken: (): Promise<string | null> => ipcRenderer.invoke('get-auth-token'),
  setAuthToken: (token: string | null): Promise<void> => ipcRenderer.invoke('set-auth-token', token),

  // HUD mode + multi-monitor
  getHudMode: (): Promise<string> => ipcRenderer.invoke('get-hud-mode'),
  setHudMode: (mode: string): Promise<void> => ipcRenderer.invoke('set-hud-mode', mode),
  getFollowActiveDisplay: (): Promise<boolean> => ipcRenderer.invoke('get-follow-active-display'),
  setFollowActiveDisplay: (enabled: boolean): Promise<void> => ipcRenderer.invoke('set-follow-active-display', enabled),

  // Activity tracking
  activityDetected: () => ipcRenderer.send('activity-detected'),

  // Visibility
  onVisibilityChanged: (callback: (visible: boolean) => void) => {
    ipcRenderer.on('visibility-changed', (_: any, visible: boolean) => callback(visible))
  },

  // Chat window controls
  showChat: () => ipcRenderer.send('show-chat'),
  hideChat: () => ipcRenderer.send('hide-chat'),

  // Note window controls
  showNote: (noteData: { id: string; title: string; content: string }) =>
    ipcRenderer.send('show-note', noteData),
  closeNote: () => ipcRenderer.send('close-note'),

  // Quick-jot native note (A4)
  saveQuickNote: (title: string, content: string): Promise<{ success: boolean; queued?: boolean; note?: any }> =>
    ipcRenderer.invoke('save-quick-note', title, content),
  closeQuickNote: () => ipcRenderer.send('close-quick-note'),
  openQuickNote: () => ipcRenderer.send('open-quick-note'),

  // Overlay window controls (webapp surfaces — Desktop Jarvis Overhaul A2)
  openOverlay: (kind: string, payload?: Record<string, any>) =>
    ipcRenderer.send('open-overlay', kind, payload || {}),

  // HUD quick actions (A1)
  requestVoiceNote: () => ipcRenderer.send('request-voice-note'),
  requestScreenshotAndAsk: () => ipcRenderer.send('request-screenshot-and-ask'),

  // Privacy toggles + connection status (A9)
  getFocusTrackingEnabled: (): Promise<boolean> => ipcRenderer.invoke('get-focus-tracking-enabled'),
  setFocusTrackingEnabled: (enabled: boolean): Promise<void> => ipcRenderer.invoke('set-focus-tracking-enabled', enabled),
  getConnectionStatus: (): Promise<{ sidecarRunning: boolean; bridgeConnected: boolean }> =>
    ipcRenderer.invoke('get-connection-status'),

  // Hotkey rebinding (A1/A9)
  getHotkeys: (): Promise<Record<string, string>> => ipcRenderer.invoke('get-hotkeys'),
  setHotkey: (action: string, accelerator: string): Promise<boolean> => ipcRenderer.invoke('set-hotkey', action, accelerator),

  // Voice settings shell (A9; full mic/wake-word controls land with A6/B3)
  getVoiceSettings: (): Promise<{ ttsVoice: string; ttsSpeed: number; useJetsonAtHome: boolean; jetsonHost: string }> =>
    ipcRenderer.invoke('get-voice-settings'),
  setVoiceSettings: (settings: { ttsVoice?: string; ttsSpeed?: number; useJetsonAtHome?: boolean; jetsonHost?: string }): Promise<void> =>
    ipcRenderer.invoke('set-voice-settings', settings),

  // Overlay preferences (A9)
  getOverlaySettings: (): Promise<{ autoOpenReports: boolean; enabledByKind: Record<string, boolean> }> =>
    ipcRenderer.invoke('get-overlay-settings'),
  setOverlaySettings: (settings: { autoOpenReports?: boolean; enabledByKind?: Record<string, boolean> }): Promise<void> =>
    ipcRenderer.invoke('set-overlay-settings', settings),
  onRecordVoiceNoteRequested: (callback: () => void) => {
    ipcRenderer.on('record-voice-note-requested', () => callback())
  },
  onVoiceState: (callback: (state: string) => void) => {
    ipcRenderer.on('voice-state', (_: any, state: string) => callback(state))
  },
  onVoiceNoteLevel: (callback: (level: number) => void) => {
    ipcRenderer.on('voice-note-level', (_: any, level: number) => callback(level))
  },
  onScreenshotConfig: (callback: (enabled: boolean) => void) => {
    ipcRenderer.on('screenshot-config', (_: any, enabled: boolean) => callback(enabled))
  },
  onJetsonTranscript: (callback: (turn: { user?: string; sara?: string }) => void) => {
    ipcRenderer.on('jetson-transcript', (_: any, turn: { user?: string; sara?: string }) => callback(turn))
  },
  onBackendEvent: (callback: (event: string, data: any) => void) => {
    ipcRenderer.on('backend-event', (_: any, payload: { event: string; data: any }) => callback(payload.event, payload.data))
  },
  onAuthInvalid: (callback: () => void) => {
    ipcRenderer.on('auth-invalid', () => callback())
  },
  notifyAuthInvalid: () => ipcRenderer.send('notify-auth-invalid'),

  // macOS permissions onboarding (A8)
  requestPermissionsRecheck: () => ipcRenderer.send('request-permissions-recheck'),
  openSystemSettings: (url: string) => ipcRenderer.send('open-system-settings', url),
  onPermissionsReport: (callback: (permissions: Record<string, string>) => void) => {
    ipcRenderer.on('permissions-report', (_: any, permissions: Record<string, string>) => callback(permissions))
  },
  platform: process.platform,

  // Launch-at-login (A8)
  getAutostart: (): Promise<boolean> => ipcRenderer.invoke('get-autostart'),
  setAutostart: (enabled: boolean): Promise<void> => ipcRenderer.invoke('set-autostart', enabled),

  // Settings window controls
  closeSettings: () => ipcRenderer.send('close-settings'),

  // Timer window controls
  showTimer: (timerData: { id: string; name: string; remainingSeconds: number }) =>
    ipcRenderer.send('show-timer', timerData),
  closeTimer: (timerId: string) => ipcRenderer.send('close-timer', timerId),
  updateTimer: (timerData: { id: string; remainingSeconds: number }) =>
    ipcRenderer.send('update-timer', timerData),
  onTimerUpdate: (callback: (data: { id: string; remainingSeconds: number }) => void) => {
    ipcRenderer.on('timer-update', (_: any, data: any) => callback(data))
  },

  // Context menu
  showContextMenu: () => ipcRenderer.send('show-context-menu'),

  // Settings
  onOpenSettings: (callback: () => void) => {
    ipcRenderer.on('open-settings', () => callback())
  },

  // Open URL in default browser
  openUrl: (url: string) => ipcRenderer.send('open-url', url),
})
