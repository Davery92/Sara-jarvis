import { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage, screen, shell } from 'electron'
import path from 'path'
import fs from 'fs'
import WebSocket from 'ws'
import { sidecarManager } from './sidecar'

// Simple file-based settings store (zero dependencies)
class SimpleStore {
  private data: Record<string, unknown> = {}
  private filePath: string = ''

  init() {
    // Must be called after app is ready
    const userDataPath = app.getPath('userData')
    this.filePath = path.join(userDataPath, 'sara-settings.json')
    this.load()
  }

  private load() {
    try {
      if (fs.existsSync(this.filePath)) {
        const content = fs.readFileSync(this.filePath, 'utf-8')
        this.data = JSON.parse(content)
      }
    } catch (e) {
      console.error('[SimpleStore] Failed to load settings:', e)
      this.data = {}
    }
  }

  private save() {
    try {
      const dir = path.dirname(this.filePath)
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true })
      }
      fs.writeFileSync(this.filePath, JSON.stringify(this.data, null, 2))
    } catch (e) {
      console.error('[SimpleStore] Failed to save settings:', e)
    }
  }

  get<T>(key: string, defaultValue?: T): T {
    return (this.data[key] as T) ?? (defaultValue as T)
  }

  set(key: string, value: unknown) {
    this.data[key] = value
    this.save()
  }

  delete(key: string) {
    delete this.data[key]
    this.save()
  }
}

const store = new SimpleStore()

let mainWindow: BrowserWindow | null = null  // Circle window (always 100x100)
let chatWindow: BrowserWindow | null = null  // Chat popup window
let noteWindow: BrowserWindow | null = null  // Note viewer popup
let settingsWindow: BrowserWindow | null = null  // Settings window
let timerWindows: Map<string, BrowserWindow> = new Map()  // Floating timer windows
let tray: Tray | null = null
let isQuitting = false

// Activity monitoring
let activityTimeout: NodeJS.Timeout | null = null
const INACTIVITY_TIMEOUT = 10 * 60 * 1000 // 10 minutes
let isVisible = true

// Window sizes
const CIRCLE_SIZE = 100
const CHAT_WIDTH = 320
const CHAT_HEIGHT = 450
const NOTE_WIDTH = 500
const NOTE_HEIGHT = 600
const TIMER_WIDTH = 200
const TIMER_HEIGHT = 80
const SETTINGS_WIDTH = 400
const SETTINGS_HEIGHT = 500

// Sidecar WebSocket connection for main process
let sidecarWs: WebSocket | null = null
let audioDevices: Array<{ index: number; name: string; is_current: boolean }> = []
let currentAudioDevice: string | null = null

function connectToSidecar() {
  console.log('[Main] connectToSidecar called, current state:', sidecarWs?.readyState)
  if (sidecarWs?.readyState === WebSocket.OPEN) return

  try {
    console.log('[Main] Creating WebSocket connection to sidecar...')
    sidecarWs = new WebSocket('ws://127.0.0.1:9876')

    sidecarWs.on('open', () => {
      console.log('[Main] Connected to sidecar')
      // Request audio devices
      sidecarWs?.send(JSON.stringify({ type: 'get_audio_devices' }))
    })

    sidecarWs.on('message', (data: WebSocket.RawData) => {
      try {
        const msg = JSON.parse(data.toString())
        if (msg.type === 'audio_devices') {
          audioDevices = msg.devices || []
          currentAudioDevice = msg.current_device
          console.log('[Main] Got audio devices:', audioDevices.length)
          rebuildTrayMenu()
        } else if (msg.type === 'audio_device_changed') {
          currentAudioDevice = msg.device_name
          // Refresh device list
          sidecarWs?.send(JSON.stringify({ type: 'get_audio_devices' }))
        }
      } catch (e) {
        console.error('[Main] Failed to parse sidecar message:', e)
      }
    })

    sidecarWs.on('close', () => {
      console.log('[Main] Sidecar connection closed')
      sidecarWs = null
      // Retry connection
      setTimeout(connectToSidecar, 5000)
    })

    sidecarWs.on('error', (err: Error) => {
      console.error('[Main] Sidecar connection error:', err.message)
      // Retry on error (connection failures don't trigger 'close')
      sidecarWs = null
      setTimeout(connectToSidecar, 2000)
    })
  } catch (e) {
    console.error('[Main] Failed to connect to sidecar:', e)
    setTimeout(connectToSidecar, 2000)
  }
}

function setAudioDevice(deviceIndex: number, deviceName: string) {
  if (sidecarWs?.readyState === WebSocket.OPEN) {
    sidecarWs.send(JSON.stringify({
      type: 'set_audio_device',
      device_index: deviceIndex,
      device_name: deviceName
    }))
  }
}

function refreshAudioDevices() {
  if (sidecarWs?.readyState === WebSocket.OPEN) {
    sidecarWs.send(JSON.stringify({ type: 'get_audio_devices' }))
  }
}

function createWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize

  // Get saved position or default to bottom-right corner
  const savedX = store.get('windowX', width - 120) as number
  const savedY = store.get('windowY', height - 120) as number

  mainWindow = new BrowserWindow({
    width: CIRCLE_SIZE,
    height: CIRCLE_SIZE,
    x: savedX,
    y: savedY,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  // Remove menu bar
  mainWindow.setMenu(null)

  // Load the app (circle view)
  if (process.env.NODE_ENV === 'development' || !app.isPackaged) {
    mainWindow.loadURL('http://localhost:5173?view=circle')
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'), { query: { view: 'circle' } })
  }

  // Open DevTools for debugging (press F12 or Ctrl+Shift+I)
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.key === 'F12' || (input.control && input.shift && input.key === 'I')) {
      mainWindow?.webContents.toggleDevTools()
    }
  })

  // Save position when window is moved
  mainWindow.on('moved', () => {
    if (mainWindow) {
      const [x, y] = mainWindow.getPosition()
      store.set('windowX', x)
      store.set('windowY', y)
      // Reposition chat window if it's open
      repositionChatWindow()
    }
  })

  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault()
      mainWindow?.hide()
      chatWindow?.hide()
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function createChatWindow(voiceMode: boolean = false) {
  if (chatWindow) {
    chatWindow.show()
    chatWindow.focus()
    // If voice mode requested on existing window, send event to start voice
    if (voiceMode) {
      chatWindow.webContents.send('start-voice')
    }
    return
  }

  // Position chat window above the circle
  const chatPos = getChatWindowPosition()

  chatWindow = new BrowserWindow({
    width: CHAT_WIDTH,
    height: CHAT_HEIGHT,
    x: chatPos.x,
    y: chatPos.y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  chatWindow.setMenu(null)

  // Load the chat view with optional voice parameter
  const voiceParam = voiceMode ? '&voice=true' : ''
  if (process.env.NODE_ENV === 'development' || !app.isPackaged) {
    chatWindow.loadURL(`http://localhost:5173?view=chat${voiceParam}`)
  } else {
    const query: Record<string, string> = { view: 'chat' }
    if (voiceMode) query.voice = 'true'
    chatWindow.loadFile(path.join(__dirname, '../dist/index.html'), { query })
  }

  // Open DevTools for debugging
  chatWindow.webContents.on('before-input-event', (event, input) => {
    if (input.key === 'F12' || (input.control && input.shift && input.key === 'I')) {
      chatWindow?.webContents.toggleDevTools()
    }
  })

  chatWindow.on('closed', () => {
    chatWindow = null
  })
}

function getChatWindowPosition(): { x: number, y: number } {
  const { width: screenW, height: screenH } = screen.getPrimaryDisplay().workAreaSize

  if (!mainWindow) {
    return { x: screenW - CHAT_WIDTH - 20, y: screenH - CHAT_HEIGHT - CIRCLE_SIZE - 20 }
  }

  const [circleX, circleY] = mainWindow.getPosition()

  // Position chat so its bottom-right corner is near the circle's top-left
  // This creates a "speech bubble" effect where chat appears above/left of circle
  let x = circleX + CIRCLE_SIZE - CHAT_WIDTH  // Align right edges
  let y = circleY - CHAT_HEIGHT - 10  // Position above circle with 10px gap

  // Clamp to screen bounds
  x = Math.max(10, Math.min(x, screenW - CHAT_WIDTH - 10))
  y = Math.max(10, Math.min(y, screenH - CHAT_HEIGHT - 10))

  // If not enough room above, position to the left of circle
  if (y < 10) {
    y = circleY
    x = circleX - CHAT_WIDTH - 10
    if (x < 10) {
      x = circleX + CIRCLE_SIZE + 10  // Position to the right instead
    }
  }

  return { x, y }
}

function repositionChatWindow() {
  if (chatWindow && chatWindow.isVisible()) {
    const pos = getChatWindowPosition()
    chatWindow.setPosition(pos.x, pos.y)
  }
}

function showChatWindow(voiceMode: boolean = false) {
  createChatWindow(voiceMode)
}

function hideChatWindow() {
  chatWindow?.hide()
}

function createNoteWindow(noteId: string, title: string, content: string) {
  // Close existing note window if open
  if (noteWindow) {
    noteWindow.close()
    noteWindow = null
  }

  const { width: screenW, height: screenH } = screen.getPrimaryDisplay().workAreaSize

  // Center the note window on screen
  const x = Math.round((screenW - NOTE_WIDTH) / 2)
  const y = Math.round((screenH - NOTE_HEIGHT) / 2)

  noteWindow = new BrowserWindow({
    width: NOTE_WIDTH,
    height: NOTE_HEIGHT,
    x,
    y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: false,
    resizable: true,
    hasShadow: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  noteWindow.setMenu(null)

  // Encode note data in URL
  const noteData = encodeURIComponent(JSON.stringify({ id: noteId, title, content }))

  if (process.env.NODE_ENV === 'development' || !app.isPackaged) {
    noteWindow.loadURL(`http://localhost:5173?view=note&data=${noteData}`)
  } else {
    noteWindow.loadFile(path.join(__dirname, '../dist/index.html'), {
      query: { view: 'note', data: noteData }
    })
  }

  noteWindow.on('closed', () => {
    noteWindow = null
  })
}

function createTimerWindow(timerId: string, name: string, remainingSeconds: number) {
  // Check if timer window already exists
  if (timerWindows.has(timerId)) {
    const existingWindow = timerWindows.get(timerId)
    existingWindow?.webContents.send('timer-update', { id: timerId, name, remainingSeconds })
    return
  }

  const { width: screenW } = screen.getPrimaryDisplay().workAreaSize

  // Stack timer windows in the top-right corner
  const timerCount = timerWindows.size
  const x = screenW - TIMER_WIDTH - 20
  const y = 20 + (timerCount * (TIMER_HEIGHT + 10))

  const timerWindow = new BrowserWindow({
    width: TIMER_WIDTH,
    height: TIMER_HEIGHT,
    x,
    y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    hasShadow: true,
    focusable: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  timerWindow.setMenu(null)

  // Encode timer data in URL
  const timerData = encodeURIComponent(JSON.stringify({ id: timerId, name, remainingSeconds }))

  if (process.env.NODE_ENV === 'development' || !app.isPackaged) {
    timerWindow.loadURL(`http://localhost:5173?view=timer&data=${timerData}`)
  } else {
    timerWindow.loadFile(path.join(__dirname, '../dist/index.html'), {
      query: { view: 'timer', data: timerData }
    })
  }

  timerWindows.set(timerId, timerWindow)

  timerWindow.on('closed', () => {
    timerWindows.delete(timerId)
  })
}

function closeTimerWindow(timerId: string) {
  const timerWindow = timerWindows.get(timerId)
  if (timerWindow) {
    timerWindow.close()
    timerWindows.delete(timerId)
  }
}

function createSettingsWindow() {
  if (settingsWindow) {
    settingsWindow.show()
    settingsWindow.focus()
    return
  }

  const { width: screenW, height: screenH } = screen.getPrimaryDisplay().workAreaSize

  // Center the settings window on screen
  const x = Math.round((screenW - SETTINGS_WIDTH) / 2)
  const y = Math.round((screenH - SETTINGS_HEIGHT) / 2)

  settingsWindow = new BrowserWindow({
    width: SETTINGS_WIDTH,
    height: SETTINGS_HEIGHT,
    x,
    y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: false,
    resizable: false,
    hasShadow: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  settingsWindow.setMenu(null)

  if (process.env.NODE_ENV === 'development' || !app.isPackaged) {
    settingsWindow.loadURL('http://localhost:5173?view=settings')
  } else {
    settingsWindow.loadFile(path.join(__dirname, '../dist/index.html'), {
      query: { view: 'settings' }
    })
  }

  settingsWindow.on('closed', () => {
    settingsWindow = null
  })
}

function rebuildTrayMenu() {
  if (!tray) return

  // Build microphone submenu from audio devices
  const micSubmenu: Electron.MenuItemConstructorOptions[] = audioDevices.length > 0
    ? audioDevices.map((device) => ({
        label: device.name,
        type: 'radio' as const,
        checked: device.name === currentAudioDevice,
        click: () => {
          console.log('[Main] Switching to audio device:', device.name)
          setAudioDevice(device.index, device.name)
        },
      }))
    : [{ label: 'No devices found', enabled: false }]

  // Add refresh option
  micSubmenu.push({ type: 'separator' })
  micSubmenu.push({
    label: 'Refresh Devices',
    click: () => {
      refreshAudioDevices()
    },
  })

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show Sara',
      click: () => {
        mainWindow?.show()
        fadeIn()
      },
    },
    {
      label: 'Mode',
      submenu: [
        {
          label: 'Wake Word',
          type: 'radio',
          checked: store.get('mode', 'wakeWord') === 'wakeWord',
          click: () => {
            console.log('[Main] Mode changed to wakeWord')
            store.set('mode', 'wakeWord')
            hideChatWindow()
            mainWindow?.webContents.send('mode-changed', 'wakeWord')
          },
        },
        {
          label: 'Push to Talk',
          type: 'radio',
          checked: store.get('mode') === 'pushToTalk',
          click: () => {
            console.log('[Main] Mode changed to pushToTalk')
            store.set('mode', 'pushToTalk')
            hideChatWindow()
            mainWindow?.webContents.send('mode-changed', 'pushToTalk')
          },
        },
        {
          label: 'Silent (Text)',
          type: 'radio',
          checked: store.get('mode') === 'silent',
          click: () => {
            console.log('[Main] Mode changed to silent')
            store.set('mode', 'silent')
            showChatWindow()
            mainWindow?.webContents.send('mode-changed', 'silent')
          },
        },
      ],
    },
    {
      label: 'Microphone',
      submenu: micSubmenu,
    },
    { type: 'separator' },
    {
      label: 'Settings',
      click: () => {
        createSettingsWindow()
      },
    },
    { type: 'separator' },
    {
      label: 'Quit Sara',
      click: () => {
        isQuitting = true
        app.quit()
      },
    },
  ])

  tray.setContextMenu(contextMenu)
}

function createTray() {
  try {
    const iconPath = path.join(__dirname, '../assets/icons/tray.png')
    const trayIcon = nativeImage.createFromPath(iconPath)
    tray = new Tray(trayIcon.isEmpty() ? nativeImage.createEmpty() : trayIcon)
  } catch {
    tray = new Tray(nativeImage.createEmpty())
  }

  tray.setToolTip('Sara - Your AI Assistant')
  rebuildTrayMenu()

  tray.on('click', () => {
    if (mainWindow?.isVisible()) {
      mainWindow.hide()
      chatWindow?.hide()
    } else {
      mainWindow?.show()
      fadeIn()
    }
  })
}

function fadeIn() {
  if (mainWindow && !isVisible) {
    isVisible = true
    mainWindow.webContents.send('visibility-changed', true)
  }
  resetActivityTimer()
}

function fadeOut() {
  if (mainWindow && isVisible) {
    isVisible = false
    mainWindow.webContents.send('visibility-changed', false)
  }
}

function resetActivityTimer() {
  if (activityTimeout) {
    clearTimeout(activityTimeout)
  }
  activityTimeout = setTimeout(() => {
    fadeOut()
  }, INACTIVITY_TIMEOUT)
}

// IPC Handlers
ipcMain.handle('get-mode', () => {
  return store.get('mode', 'wakeWord')
})

ipcMain.handle('set-mode', (_, mode: string) => {
  store.set('mode', mode)
})

ipcMain.handle('get-api-url', () => {
  return store.get('apiUrl', 'https://sara-api.avery.cloud')
})

ipcMain.handle('set-api-url', (_, url: string) => {
  store.set('apiUrl', url)
})

ipcMain.handle('get-auth-token', () => {
  return store.get('authToken', null)
})

ipcMain.handle('set-auth-token', (_, token: string | null) => {
  if (token) {
    store.set('authToken', token)
    // Also update sidecar with the new token
    sidecarManager.setAuthToken(token)
  } else {
    store.delete('authToken')
  }
})

ipcMain.on('activity-detected', () => {
  fadeIn()
})

// Chat window controls
ipcMain.on('show-chat', (_, options?: { voice?: boolean }) => {
  showChatWindow(options?.voice)
})

ipcMain.on('hide-chat', () => {
  hideChatWindow()
})

ipcMain.on('show-context-menu', () => {
  if (tray) {
    tray.popUpContextMenu()
  }
})

// Note window controls
ipcMain.on('show-note', (_, noteData: { id: string; title: string; content: string }) => {
  createNoteWindow(noteData.id, noteData.title, noteData.content)
})

ipcMain.on('close-note', () => {
  noteWindow?.close()
})

ipcMain.on('close-settings', () => {
  settingsWindow?.close()
})

// Timer window controls
ipcMain.on('show-timer', (_, timerData: { id: string; name: string; remainingSeconds: number }) => {
  createTimerWindow(timerData.id, timerData.name, timerData.remainingSeconds)
})

ipcMain.on('close-timer', (_, timerId: string) => {
  closeTimerWindow(timerId)
})

ipcMain.on('update-timer', (_, timerData: { id: string; remainingSeconds: number }) => {
  const timerWindow = timerWindows.get(timerData.id)
  if (timerWindow) {
    timerWindow.webContents.send('timer-update', timerData)
  }
})

// App lifecycle
app.whenReady().then(async () => {
  // Initialize settings store (must be after app is ready)
  store.init()

  createWindow()
  createTray()
  resetActivityTimer()

  // Start the Python sidecar for wake word, activity, screenshots
  try {
    // Pass auth token to sidecar if available
    const authToken = store.get('authToken', null) as string | null
    if (authToken) {
      sidecarManager.setAuthToken(authToken)
    }
    await sidecarManager.start()
    console.log('[Main] Sidecar started')

    // Connect to sidecar WebSocket for audio device management
    // Give sidecar a moment to start its WebSocket server
    console.log('[Main] Scheduling sidecar WebSocket connection in 3 seconds...')
    setTimeout(() => {
      console.log('[Main] Timer fired, connecting to sidecar...')
      connectToSidecar()
    }, 3000)
  } catch (error) {
    console.error('[Main] Failed to start sidecar:', error)
  }

  // Auto-start on login (can be toggled in settings)
  const autoStart = store.get('autoStart', true) as boolean
  app.setLoginItemSettings({
    openAtLogin: autoStart,
    openAsHidden: true,
  })

  // If mode was saved as silent, show chat window
  if (store.get('mode') === 'silent') {
    showChatWindow()
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', async () => {
  isQuitting = true
  // Stop the sidecar gracefully
  await sidecarManager.stop()
})

// IPC handler for opening URLs in default browser
ipcMain.on('open-url', (_, url: string) => {
  shell.openExternal(url)
})

// IPC handler for sidecar status
ipcMain.handle('sidecar-status', () => {
  return {
    running: sidecarManager.isRunning()
  }
})

// IPC handler to restart sidecar
ipcMain.handle('restart-sidecar', async () => {
  return await sidecarManager.restart()
})
