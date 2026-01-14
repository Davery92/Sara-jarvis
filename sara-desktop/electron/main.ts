import { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage, screen, Notification } from 'electron'
import path from 'path'
import fs from 'fs'
import { spawn, ChildProcess } from 'child_process'
import WebSocket from 'ws'

let sidecarProcess: ChildProcess | null = null
let sidecarBridge: WebSocket | null = null
let bridgeReconnectTimeout: NodeJS.Timeout | null = null

function startSidecar(store: SimpleStore) {
  if (sidecarProcess) return

  let sidecarPath: string
  if (app.isPackaged) {
    sidecarPath = path.join(process.resourcesPath, 'sidecar', 'main.py')
  } else {
    sidecarPath = path.join(__dirname, '..', 'sidecar', 'main.py')
  }

  if (!fs.existsSync(sidecarPath)) {
    console.log('[Main] Sidecar not found at:', sidecarPath)
    return
  }

  console.log('[Main] Starting sidecar from:', sidecarPath)

  const authToken = store.get('authToken', '') as string
  const apiUrl = store.get('apiUrl', 'https://sara-api.avery.cloud') as string
  const isWindows = process.platform === 'win32'
  const pythonCmd = isWindows ? 'python' : 'python3'

  sidecarProcess = spawn(pythonCmd, [sidecarPath], {
    env: { ...process.env, SARA_AUTH_TOKEN: authToken, SARA_BACKEND_URL: apiUrl },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  sidecarProcess.stdout?.on('data', (data) => console.log('[Sidecar]', data.toString().trim()))
  sidecarProcess.stderr?.on('data', (data) => console.error('[Sidecar]', data.toString().trim()))
  sidecarProcess.on('close', (code) => {
    console.log(`[Main] Sidecar exited with code ${code}`)
    sidecarProcess = null
  })
}

function stopSidecar() {
  if (sidecarProcess) {
    sidecarProcess.kill()
    sidecarProcess = null
  }
  disconnectBridge()
}

// Connect to sidecar's WebSocket bridge
function connectToBridge(store: SimpleStore) {
  if (sidecarBridge && sidecarBridge.readyState === WebSocket.OPEN) return

  const bridgeUrl = 'ws://127.0.0.1:9876'
  console.log('[Main] Connecting to sidecar bridge:', bridgeUrl)

  try {
    sidecarBridge = new WebSocket(bridgeUrl)

    sidecarBridge.on('open', () => {
      console.log('[Main] Connected to sidecar bridge')
      // Send auth token to sidecar
      const token = store.get('authToken', '') as string
      if (token && sidecarBridge) {
        sidecarBridge.send(JSON.stringify({ type: 'auth_token', token }))
      }
    })

    sidecarBridge.on('message', (data) => {
      try {
        const message = JSON.parse(data.toString())
        handleBridgeMessage(message)
      } catch (e) {
        console.error('[Main] Failed to parse bridge message:', e)
      }
    })

    sidecarBridge.on('close', () => {
      console.log('[Main] Disconnected from sidecar bridge')
      sidecarBridge = null
      // Reconnect after delay
      if (!bridgeReconnectTimeout) {
        bridgeReconnectTimeout = setTimeout(() => {
          bridgeReconnectTimeout = null
          connectToBridge(store)
        }, 3000)
      }
    })

    sidecarBridge.on('error', (err) => {
      console.error('[Main] Bridge connection error:', err.message)
    })

  } catch (e) {
    console.error('[Main] Failed to connect to bridge:', e)
  }
}

function disconnectBridge() {
  if (bridgeReconnectTimeout) {
    clearTimeout(bridgeReconnectTimeout)
    bridgeReconnectTimeout = null
  }
  if (sidecarBridge) {
    sidecarBridge.close()
    sidecarBridge = null
  }
}

function handleBridgeMessage(message: { type: string; [key: string]: any }) {
  console.log('[Main] Bridge message:', message.type)

  switch (message.type) {
    case 'show_note':
      // Show note popup
      createNoteWindow(
        message.note_id || 'remote-note',
        message.title || 'Note',
        message.content || ''
      )
      break

    case 'show_timer':
      // Show timer popup
      createTimerWindow(
        message.timer_id || `timer-${Date.now()}`,
        message.label || 'Timer',
        message.remaining_seconds || 0
      )
      break

    case 'show_notification':
      // Show system notification
      if (Notification.isSupported()) {
        new Notification({
          title: message.title || 'Sara',
          body: message.message || ''
        }).show()
      }
      break

    case 'speak':
      // Forward to renderer for TTS (browser speech synthesis)
      mainWindow?.webContents.send('speak', message.text)
      break

    case 'activity_update':
      // Forward activity updates to renderer
      mainWindow?.webContents.send('activity-update', message.activity)
      break

    case 'pong':
      // Health check response
      break

    default:
      console.log('[Main] Unknown bridge message type:', message.type)
  }
}

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
const CIRCLE_WIDTH = 240  // Smoke ring (100) + 2 side buttons (40 each) + gaps + padding
const CIRCLE_HEIGHT = 120 // Smoke ring (100) + padding
const CHAT_WIDTH = 320
const CHAT_HEIGHT = 450
const NOTE_WIDTH = 500
const NOTE_HEIGHT = 600
const TIMER_WIDTH = 200
const TIMER_HEIGHT = 80
const SETTINGS_WIDTH = 400
const SETTINGS_HEIGHT = 500

function createWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize

  // Get saved position or default to bottom-right corner
  let savedX = store.get('windowX', width - CIRCLE_WIDTH - 20) as number
  let savedY = store.get('windowY', height - CIRCLE_HEIGHT - 20) as number

  // Validate position is on-screen (handle multi-monitor changes, corrupted settings, etc.)
  if (savedX < 0 || savedX > width - 50 || savedY < 0 || savedY > height - 50) {
    console.log('[Main] Saved position off-screen, resetting to default')
    savedX = width - CIRCLE_WIDTH - 20
    savedY = height - CIRCLE_HEIGHT - 20
    store.set('windowX', savedX)
    store.set('windowY', savedY)
  }

  console.log('[Main] Creating circle window at', savedX, savedY, 'size', CIRCLE_WIDTH, 'x', CIRCLE_HEIGHT)

  mainWindow = new BrowserWindow({
    width: CIRCLE_WIDTH,
    height: CIRCLE_HEIGHT,
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
  const indexPath = path.join(__dirname, '../dist/index.html')
  console.log('[Main] Loading circle view from:', indexPath)

  if (process.env.NODE_ENV === 'development' || !app.isPackaged) {
    mainWindow.loadURL('http://localhost:5173?view=circle')
  } else {
    mainWindow.loadFile(indexPath, { query: { view: 'circle' } })
  }

  // Debug: Log when page loads
  mainWindow.webContents.on('did-finish-load', () => {
    console.log('[Main] Circle window finished loading')
  })

  mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription) => {
    console.error('[Main] Circle window failed to load:', errorCode, errorDescription)
  })

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

function createChatWindow() {
  if (chatWindow) {
    chatWindow.show()
    chatWindow.focus()
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

  // Load the chat view
  if (process.env.NODE_ENV === 'development' || !app.isPackaged) {
    chatWindow.loadURL('http://localhost:5173?view=chat')
  } else {
    chatWindow.loadFile(path.join(__dirname, '../dist/index.html'), { query: { view: 'chat' } })
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
    return { x: screenW - CHAT_WIDTH - 20, y: screenH - CHAT_HEIGHT - CIRCLE_HEIGHT - 20 }
  }

  const [circleX, circleY] = mainWindow.getPosition()

  // Position chat so its bottom-right corner is near the circle's top-left
  // This creates a "speech bubble" effect where chat appears above/left of circle
  let x = circleX + CIRCLE_WIDTH - CHAT_WIDTH  // Align right edges
  let y = circleY - CHAT_HEIGHT - 10  // Position above circle with 10px gap

  // Clamp to screen bounds
  x = Math.max(10, Math.min(x, screenW - CHAT_WIDTH - 10))
  y = Math.max(10, Math.min(y, screenH - CHAT_HEIGHT - 10))

  // If not enough room above, position to the left of circle
  if (y < 10) {
    y = circleY
    x = circleX - CHAT_WIDTH - 10
    if (x < 10) {
      x = circleX + CIRCLE_WIDTH + 10  // Position to the right instead
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

function showChatWindow() {
  createChatWindow()
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

function createTray() {
  try {
    const iconPath = path.join(__dirname, '../assets/icons/tray.png')
    const trayIcon = nativeImage.createFromPath(iconPath)
    tray = new Tray(trayIcon.isEmpty() ? nativeImage.createEmpty() : trayIcon)
  } catch {
    tray = new Tray(nativeImage.createEmpty())
  }

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show Sara',
      click: () => {
        mainWindow?.show()
        fadeIn()
      },
    },
    {
      label: 'Open Chat',
      click: () => {
        showChatWindow()
      },
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

  tray.setToolTip('Sara - Your AI Assistant')
  tray.setContextMenu(contextMenu)

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
  } else {
    store.delete('authToken')
  }
})

ipcMain.on('activity-detected', () => {
  fadeIn()
})

// Chat window controls
ipcMain.on('show-chat', () => {
  showChatWindow()
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
app.whenReady().then(() => {
  // Initialize settings store (must be after app is ready)
  store.init()

  // Start sidecar for activity monitoring and screenshots
  startSidecar(store)

  // Connect to sidecar bridge after a short delay (let sidecar start its WebSocket server)
  setTimeout(() => connectToBridge(store), 2000)

  createWindow()
  createTray()
  resetActivityTimer()

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

app.on('before-quit', () => {
  isQuitting = true
  stopSidecar()
})
