const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  // API URL
  getApiUrl: (): Promise<string> => ipcRenderer.invoke('get-api-url'),
  setApiUrl: (url: string): Promise<void> => ipcRenderer.invoke('set-api-url', url),

  // Auth token
  getAuthToken: (): Promise<string | null> => ipcRenderer.invoke('get-auth-token'),
  setAuthToken: (token: string | null): Promise<void> => ipcRenderer.invoke('set-auth-token', token),

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
