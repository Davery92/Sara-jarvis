import { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage, screen, shell, systemPreferences, session } from 'electron'
import path from 'path'
import fs from 'fs'
import { spawn, ChildProcess } from 'child_process'

// Early debug logging to file (for troubleshooting packaged app startup)
const debugLogPath = path.join(process.env.APPDATA || process.env.HOME || '.', 'sara-debug.log')
function debugLog(msg: string) {
  try {
    const timestamp = new Date().toISOString()
    fs.appendFileSync(debugLogPath, `[${timestamp}] ${msg}\n`)
  } catch (e) {
    // Silently fail if we can't write
  }
}
debugLog('=== Sara starting ===')
debugLog(`Process argv: ${process.argv.join(' ')}`)
debugLog(`__dirname: ${__dirname}`)
debugLog(`app.isPackaged: ${app?.isPackaged}`)
debugLog(`NODE_ENV: ${process.env.NODE_ENV}`)

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
let sidecarProcess: ChildProcess | null = null

// Sidecar management
function startSidecar() {
  if (sidecarProcess) {
    console.log('[Main] Sidecar already running')
    return
  }

  // Get the path to the sidecar executable
  let sidecarPath: string
  let useCompiledBinary = false

  if (app.isPackaged) {
    // In packaged app, use compiled sidecar executable
    const isWindows = process.platform === 'win32'
    const binaryName = isWindows ? 'sidecar.exe' : 'sidecar'
    sidecarPath = path.join(process.resourcesPath, 'sidecar', binaryName)
    useCompiledBinary = true
  } else {
    // In development, use Python script directly
    sidecarPath = path.join(__dirname, '..', 'sidecar', 'main.py')
  }

  // Check if sidecar exists
  if (!fs.existsSync(sidecarPath)) {
    console.log('[Main] Sidecar not found at:', sidecarPath)
    debugLog(`Sidecar not found at: ${sidecarPath}`)
    return
  }

  console.log('[Main] Starting sidecar from:', sidecarPath)
  debugLog(`Starting sidecar from: ${sidecarPath}`)

  // Get auth token and API URL from store
  const authToken = store.get('authToken', '') as string
  const apiUrl = store.get('apiUrl', 'https://sara-api.avery.cloud') as string

  // Spawn process - compiled binary or Python script
  if (useCompiledBinary) {
    // Run compiled executable directly
    sidecarProcess = spawn(sidecarPath, [], {
      env: {
        ...process.env,
        SARA_AUTH_TOKEN: authToken,
        SARA_BACKEND_URL: apiUrl,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
  } else {
    // Run Python script in development
    sidecarProcess = spawn('python3', [sidecarPath], {
      env: {
        ...process.env,
        SARA_AUTH_TOKEN: authToken,
        SARA_BACKEND_URL: apiUrl,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
  }

  sidecarProcess.stdout?.on('data', (data) => {
    console.log('[Sidecar]', data.toString().trim())
  })

  sidecarProcess.stderr?.on('data', (data) => {
    console.error('[Sidecar Error]', data.toString().trim())
  })

  sidecarProcess.on('close', (code) => {
    console.log(`[Main] Sidecar exited with code ${code}`)
    debugLog(`Sidecar exited with code ${code}`)
    sidecarProcess = null

    // Restart sidecar if it crashed and we're not quitting
    if (!isQuitting && code !== 0) {
      console.log('[Main] Restarting sidecar in 5 seconds...')
      setTimeout(startSidecar, 5000)
    }
  })

  sidecarProcess.on('error', (err) => {
    console.error('[Main] Failed to start sidecar:', err)
    debugLog(`Failed to start sidecar: ${err.message}`)
    sidecarProcess = null
  })
}

function stopSidecar() {
  if (sidecarProcess) {
    console.log('[Main] Stopping sidecar...')
    sidecarProcess.kill()
    sidecarProcess = null
  }
}

// Activity monitoring
let activityTimeout: NodeJS.Timeout | null = null
const INACTIVITY_TIMEOUT = 10 * 60 * 1000 // 10 minutes
let isVisible = true

// Window sizes
const CIRCLE_WIDTH = 220  // Wide to fit quick action buttons (40+16+100+16+40=212)
const CIRCLE_HEIGHT = 120  // Tall enough for smoke ring
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
  // Use sensible defaults for the new wider window
  const defaultX = width - CIRCLE_WIDTH - 20
  const defaultY = height - CIRCLE_HEIGHT - 20
  let savedX = store.get('windowX', defaultX) as number
  let savedY = store.get('windowY', defaultY) as number

  // Clamp to screen bounds in case saved position is off-screen
  savedX = Math.max(0, Math.min(savedX, width - CIRCLE_WIDTH))
  savedY = Math.max(0, Math.min(savedY, height - CIRCLE_HEIGHT))

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
  if (process.env.NODE_ENV === 'development' || !app.isPackaged) {
    mainWindow.loadURL('http://localhost:5173?view=circle')
  } else {
    // In packaged app, index.html is at the same level as main.js
    mainWindow.loadFile(path.join(__dirname, 'index.html'), { query: { view: 'circle' } })
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

function createChatWindow() {
  if (chatWindow) {
    // Force reload to ensure fresh JS bundle is loaded (fixes caching issues)
    chatWindow.webContents.reloadIgnoringCache()
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

  // Load the chat view with auth parameter
  // Pass auth state directly to avoid race condition in renderer
  const authToken = store.get('authToken', null) as string | null
  const hasAuth = authToken ? 'true' : 'false'

  if (process.env.NODE_ENV === 'development' || !app.isPackaged) {
    const authParam = `&authenticated=${hasAuth}`
    chatWindow.loadURL(`http://localhost:5173?view=chat${authParam}`)
  } else {
    const query: Record<string, string> = { view: 'chat', authenticated: hasAuth }
    chatWindow.loadFile(path.join(__dirname, 'index.html'), { query })
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
    noteWindow.loadFile(path.join(__dirname, 'index.html'), {
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
    timerWindow.loadFile(path.join(__dirname, 'index.html'), {
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
    settingsWindow.loadFile(path.join(__dirname, 'index.html'), {
      query: { view: 'settings' }
    })
  }

  settingsWindow.on('closed', () => {
    settingsWindow = null
  })
}

function rebuildTrayMenu() {
  if (!tray) return

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
debugLog('Setting up app.whenReady...')
app.whenReady().then(async () => {
  debugLog('app.whenReady fired!')
  // Clear Chromium's HTTP cache to ensure fresh JS loads after rebuilds
  // This fixes the issue where old JavaScript bundles are served from cache
  await session.defaultSession.clearCache()
  debugLog('Session cache cleared')
  console.log('[Main] Cleared session cache')

  // Initialize settings store (must be after app is ready)
  store.init()

  // Request microphone permission on macOS (required for getUserMedia in renderer)
  if (process.platform === 'darwin') {
    const micStatus = systemPreferences.getMediaAccessStatus('microphone')
    console.log('[Main] Microphone permission status:', micStatus)
    if (micStatus !== 'granted') {
      const granted = await systemPreferences.askForMediaAccess('microphone')
      console.log('[Main] Microphone permission granted:', granted)
    }
  }

  createWindow()
  createTray()
  resetActivityTimer()

  // Start the sidecar (activity monitoring, screenshots)
  startSidecar()

  // Auto-start on login (can be toggled in settings)
  const autoStart = store.get('autoStart', true) as boolean
  app.setLoginItemSettings({
    openAtLogin: autoStart,
    openAsHidden: true,
  })

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

// IPC handler for opening URLs in default browser
ipcMain.on('open-url', (_, url: string) => {
  shell.openExternal(url)
})

// IPC handlers for microphone permission (macOS)
ipcMain.handle('request-mic-permission', async () => {
  if (process.platform === 'darwin') {
    return await systemPreferences.askForMediaAccess('microphone')
  }
  return true // Non-macOS platforms don't need explicit permission
})

ipcMain.handle('get-mic-permission', () => {
  if (process.platform === 'darwin') {
    return systemPreferences.getMediaAccessStatus('microphone')
  }
  return 'granted'
})
