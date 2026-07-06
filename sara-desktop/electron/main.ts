import { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage, screen, Notification, dialog, globalShortcut, shell } from 'electron'
import path from 'path'
import fs from 'fs'
import net from 'net'
import { spawn, ChildProcess } from 'child_process'
import WebSocket from 'ws'
import { autoUpdater } from 'electron-updater'

let sidecarProcess: ChildProcess | null = null
let sidecarBridge: WebSocket | null = null
let bridgeReconnectTimeout: NodeJS.Timeout | null = null

function isLocalPortOpen(port: number, host = '127.0.0.1', timeoutMs = 400): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = new net.Socket()
    let settled = false

    const finish = (open: boolean) => {
      if (settled) return
      settled = true
      socket.destroy()
      resolve(open)
    }

    socket.setTimeout(timeoutMs)
    socket.once('connect', () => finish(true))
    socket.once('timeout', () => finish(false))
    socket.once('error', () => finish(false))
    socket.connect(port, host)
  })
}

async function startSidecar(store: SimpleStore) {
  if (sidecarProcess) return

  const bridgeAlreadyRunning = await isLocalPortOpen(9876)
  if (bridgeAlreadyRunning) {
    console.log('[Main] Existing sidecar bridge detected; requesting shutdown before restart')
    await requestExistingSidecarShutdown()
    await new Promise((resolve) => setTimeout(resolve, 900))
    if (await isLocalPortOpen(9876)) {
      console.log('[Main] Existing sidecar did not stop gracefully; forcing shutdown by port owner')
      await forceKillBridgePortProcess(9876)
      await new Promise((resolve) => setTimeout(resolve, 900))
    }
    if (await isLocalPortOpen(9876)) {
      console.warn('[Main] Sidecar bridge port 9876 is still occupied; reusing existing sidecar instance')
      return
    }
  }

  const authToken = store.get('authToken', '') as string
  const apiUrl = store.get('apiUrl', 'https://sara-api.avery.cloud') as string
  const isWindows = process.platform === 'win32'

  const useJetsonAtHome = store.get('useJetsonAtHome', true) as boolean
  const jetsonHost = store.get('jetsonHost', '10.185.1.84') as string

  const env = {
    ...process.env,
    SARA_AUTH_TOKEN: authToken,
    SARA_BACKEND_URL: apiUrl,
    // Only set when the user has both enabled Jetson-at-home and configured
    // a host — an empty value disables the sidecar's Jetson bridge entirely.
    SARA_JETSON_HOST: useJetsonAtHome ? jetsonHost : '',
  }

  // Packaged build: spawn the PyInstaller-frozen sidecar.exe directly. No
  // Python required on the user's machine. Dev: fall back to the .py entry
  // point via the local Python interpreter so hot-edits still work.
  let sidecarDir: string
  let spawnCmd: string
  let spawnArgs: string[]

  if (app.isPackaged) {
    sidecarDir = path.join(process.resourcesPath, 'sidecar')
    const frozenExe = path.join(sidecarDir, isWindows ? 'sidecar.exe' : 'sidecar')
    if (!fs.existsSync(frozenExe)) {
      console.error('[Main] Frozen sidecar not found at:', frozenExe)
      return
    }
    spawnCmd = frozenExe
    spawnArgs = []
    console.log('[Main] Starting frozen sidecar:', frozenExe)
  } else {
    sidecarDir = path.join(__dirname, '..', 'sidecar')
    const sidecarPy = path.join(sidecarDir, 'main.py')
    if (!fs.existsSync(sidecarPy)) {
      console.log('[Main] Sidecar source not found at:', sidecarPy)
      return
    }
    const venvCandidates = isWindows
      ? [
          path.join(sidecarDir, 'venv', 'Scripts', 'python.exe'),
          path.join(sidecarDir, '.venv', 'Scripts', 'python.exe'),
        ]
      : [
          path.join(sidecarDir, 'venv', 'bin', 'python'),
          path.join(sidecarDir, '.venv', 'bin', 'python'),
        ]
    spawnCmd = venvCandidates.find((c) => fs.existsSync(c))
      ?? (isWindows ? 'python' : 'python3')
    spawnArgs = [sidecarPy]
    console.log('[Main] Dev mode — starting sidecar via', spawnCmd, spawnArgs)
  }

  sidecarProcess = spawn(spawnCmd, spawnArgs, {
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
    cwd: sidecarDir,
  })

  sidecarProcess.stdout?.on('data', (data) => console.log('[Sidecar]', data.toString().trim()))
  sidecarProcess.stderr?.on('data', (data) => console.error('[Sidecar]', data.toString().trim()))
  sidecarProcess.on('close', (code) => {
    console.log(`[Main] Sidecar exited with code ${code}`)
    sidecarProcess = null
    if (!isQuitting) {
      scheduleSidecarRestart(store)
    }
  })
}

// Auto-restart on crash, with backoff, capped at 5/hour so a persistently
// broken sidecar doesn't spin the CPU forever.
let sidecarRestartTimestamps: number[] = []
const MAX_SIDECAR_RESTARTS_PER_HOUR = 5

function scheduleSidecarRestart(store: SimpleStore) {
  const now = Date.now()
  sidecarRestartTimestamps = sidecarRestartTimestamps.filter((t) => now - t < 60 * 60 * 1000)

  if (sidecarRestartTimestamps.length >= MAX_SIDECAR_RESTARTS_PER_HOUR) {
    console.error('[Main] Sidecar crashed too many times in the last hour; giving up on auto-restart')
    return
  }

  const attempt = sidecarRestartTimestamps.length
  const delayMs = Math.min(60000, 2000 * Math.pow(2, attempt))
  sidecarRestartTimestamps.push(now)
  console.log(`[Main] Restarting sidecar in ${delayMs}ms (attempt ${attempt + 1}/${MAX_SIDECAR_RESTARTS_PER_HOUR} this hour)`)

  setTimeout(() => {
    startSidecar(store).catch((err) => {
      console.error('[Main] Sidecar restart failed:', err)
    })
  }, delayMs)
}

async function requestExistingSidecarShutdown(): Promise<void> {
  await new Promise<void>((resolve) => {
    const ws = new WebSocket('ws://127.0.0.1:9876')
    let settled = false

    const finish = () => {
      if (settled) return
      settled = true
      try {
        ws.close()
      } catch {
        // no-op
      }
      resolve()
    }

    const timeout = setTimeout(() => {
      console.log('[Main] Existing sidecar shutdown request timed out')
      finish()
    }, 1500)

    ws.on('open', () => {
      try {
        ws.send(JSON.stringify({ type: 'shutdown_sidecar' }))
        console.log('[Main] Sent shutdown request to existing sidecar')
      } catch {
        // no-op
      }
      setTimeout(() => {
        clearTimeout(timeout)
        finish()
      }, 350)
    })

    ws.on('error', () => {
      clearTimeout(timeout)
      finish()
    })

    ws.on('close', () => {
      clearTimeout(timeout)
      finish()
    })
  })
}

async function forceKillBridgePortProcess(port: number): Promise<void> {
  if (process.platform !== 'win32') {
    await forceKillBridgePortProcessPosix(port)
    return
  }

  const script = `
$connections = Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue
if (-not $connections) { exit 0 }
$owningPids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($owningPid in $owningPids) {
  try {
    Stop-Process -Id $owningPid -Force -ErrorAction Stop
    Write-Output "Killed PID $owningPid on port ${port}"
  } catch {
    Write-Output "Failed to kill PID $owningPid on port ${port}: $($_.Exception.Message)"
  }
}
`

  await new Promise<void>((resolve) => {
    const ps = spawn('powershell.exe', ['-NoProfile', '-Command', script], {
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    })

    ps.stdout?.on('data', (data) => {
      const output = data.toString().trim()
      if (output) {
        console.log('[Main] Port kill stdout:', output)
      }
    })

    ps.stderr?.on('data', (data) => {
      const output = data.toString().trim()
      if (output) {
        console.warn('[Main] Port kill stderr:', output)
      }
    })

    ps.on('close', () => resolve())
    ps.on('error', () => resolve())
  })
}

async function forceKillBridgePortProcessPosix(port: number): Promise<void> {
  // Equivalent of the Windows PowerShell path above, for macOS/Linux:
  // find PIDs listening on the port via lsof and kill them.
  await new Promise<void>((resolve) => {
    const lsof = spawn('lsof', ['-ti', `:${port}`], { stdio: ['ignore', 'pipe', 'pipe'] })
    let output = ''
    lsof.stdout?.on('data', (data) => {
      output += data.toString()
    })
    lsof.on('close', () => {
      const pids = output.split('\n').map((s) => s.trim()).filter(Boolean)
      if (pids.length === 0) {
        resolve()
        return
      }
      const kill = spawn('kill', ['-9', ...pids], { stdio: ['ignore', 'pipe', 'pipe'] })
      kill.on('close', () => {
        console.log('[Main] Killed PIDs on port', port, ':', pids.join(', '))
        resolve()
      })
      kill.on('error', () => resolve())
    })
    lsof.on('error', () => resolve())
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
      // Re-apply persisted privacy toggles — the sidecar's own state is
      // in-memory only and resets on every restart/reconnect.
      const focusTrackingEnabled = store.get('focusTrackingEnabled', true) as boolean
      sidecarBridge?.send(JSON.stringify({ type: 'set_focus_tracking_enabled', enabled: focusTrackingEnabled }))

      const ttsVoice = store.get('ttsVoice', null) as string | null
      const ttsSpeed = store.get('ttsSpeed', null) as number | null
      if (ttsVoice || ttsSpeed) {
        sidecarBridge?.send(JSON.stringify({ type: 'set_tts_config', voice: ttsVoice, speed: ttsSpeed }))
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

// Shared re-login prompt for any auth failure — sidecar WS rejection (4001)
// or a renderer fetch() getting a 401 back (chat, notes, etc.). Both paths
// converge here so the user always sees the same "log in again" nudge
// instead of a dead-end error bubble.
function handleAuthInvalid() {
  if (Notification.isSupported()) {
    const notification = new Notification({
      title: 'Sara needs you to log in again',
      body: 'Click to reconnect your desktop.',
    })
    notification.on('click', () => createSettingsWindow())
    notification.show()
  }
  mainWindow?.webContents.send('auth-invalid')
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

    case 'show_notification': {
      // Show system notification. When it carries an overlay field, clicking
      // the notification opens that overlay instead of just dismissing (A2).
      if (Notification.isSupported()) {
        const notification = new Notification({
          title: message.title || 'Sara',
          body: message.message || ''
        })
        const overlay = message.overlay as { kind?: string; payload?: Record<string, any> } | undefined
        if (overlay?.kind) {
          notification.on('click', () => {
            createOverlayWindow(overlay.kind!, overlay.payload || {})
          })
        }
        notification.show()
      }
      break
    }

    case 'activity_update':
      // Forward activity updates to renderer
      mainWindow?.webContents.send('activity-update', message.activity)
      applyFullscreenDodge(!!message.activity?.is_fullscreen)
      break

    case 'system_metrics':
      // Forward system metrics to renderer
      mainWindow?.webContents.send('system-metrics', message.metrics)
      break

    case 'open_overlay':
      createOverlayWindow(message.kind, message.payload || {})
      break

    case 'record_voice_note':
      // Real capture lands with the sidecar voice module; for now just let
      // the renderer know a recording was requested (e.g. HUD state).
      mainWindow?.webContents.send('record-voice-note-requested')
      break

    case 'voice_state':
      mainWindow?.webContents.send('voice-state', message.state)
      setSpeakingState(message.state === 'speaking')
      break

    case 'backend_event':
      mainWindow?.webContents.send('backend-event', { event: message.event, data: message.data })
      break

    case 'permissions_report':
      settingsWindow?.webContents.send('permissions-report', message.permissions)
      break

    case 'voice_note_level':
      mainWindow?.webContents.send('voice-note-level', message.level)
      break

    case 'screenshot_config':
      mainWindow?.webContents.send('screenshot-config', !!message.enabled)
      break

    case 'jetson_transcript':
      // Live voice conversation turn from the Jetson (B4) — MiniChat shows
      // it as a "🎤 ..." bubble so voice and desktop chat feel unified.
      chatWindow?.webContents.send('jetson-transcript', { user: message.user, sara: message.sara })
      break

    case 'auth_invalid':
      // The sidecar's stored token was rejected (WS 4001) and it has given
      // up retrying — surface a re-login prompt instead of a silent stall.
      handleAuthInvalid()
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
let quickNoteWindow: BrowserWindow | null = null  // Quick-jot native editor (A4)
let settingsWindow: BrowserWindow | null = null  // Settings window
let timerWindows: Map<string, BrowserWindow> = new Map()  // Floating timer windows
let tray: Tray | null = null
let isQuitting = false

const hasSingleInstanceLock = app.requestSingleInstanceLock()

// Activity monitoring / HUD visibility mode
// 'always': orb never dims or hides (default — the whole point of A1 is that
//   Sara is always on screen, replacing the old unconditional 10-min fade).
// 'dim-when-idle': dims to a resting style after inactivity.
// 'hide-when-fullscreen': hides while the foreground app is fullscreen
//   (games, video, presentations), based on the sidecar's is_fullscreen flag.
type HudMode = 'always' | 'dim-when-idle' | 'hide-when-fullscreen'
let restingTimeout: NodeJS.Timeout | null = null
const RESTING_TIMEOUT = 10 * 60 * 1000 // 10 minutes
let isVisible = true
let isDodgingFullscreen = false

function getHudMode(): HudMode {
  return store.get('hudMode', 'always') as HudMode
}

// Window sizes
const CIRCLE_WIDTH = 240  // Smoke ring (100) + 2 side buttons (40 each) + gaps + padding
const CIRCLE_HEIGHT = 120 // Smoke ring (100) + padding
const CHAT_WIDTH = 320
const CHAT_HEIGHT = 450
const NOTE_WIDTH = 500
const NOTE_HEIGHT = 600
const QUICK_NOTE_WIDTH = 380
const QUICK_NOTE_HEIGHT = 320
const TIMER_WIDTH = 200
const TIMER_HEIGHT = 80
const SETTINGS_WIDTH = 560
const SETTINGS_HEIGHT = 560

// ── Multi-monitor position persistence (A1) ─────────────────────────────
// Position is remembered per-display (not just a single global x/y) so the
// orb reappears where it was left on whichever monitor it was on, and
// (when followActive is on) can follow the cursor across displays.

type DisplayPosition = { x: number; y: number }

function getDisplayPositions(): Record<string, DisplayPosition> {
  return store.get('windowPositionsByDisplay', {}) as Record<string, DisplayPosition>
}

function savePositionForDisplay(displayId: number, x: number, y: number) {
  const positions = getDisplayPositions()
  positions[String(displayId)] = { x, y }
  store.set('windowPositionsByDisplay', positions)
  store.set('lastDisplayId', displayId)
}

function defaultPositionForDisplay(display: Electron.Display): DisplayPosition {
  const { x: dx, y: dy, width, height } = display.workArea
  return { x: dx + width - CIRCLE_WIDTH - 20, y: dy + height - CIRCLE_HEIGHT - 20 }
}

function positionForDisplay(display: Electron.Display): DisplayPosition {
  const saved = getDisplayPositions()[String(display.id)]
  if (saved) {
    // Clamp in case the display's resolution/workArea changed since saving.
    const { x: dx, y: dy, width, height } = display.workArea
    return {
      x: Math.min(Math.max(saved.x, dx), dx + width - 50),
      y: Math.min(Math.max(saved.y, dy), dy + height - 50),
    }
  }
  return defaultPositionForDisplay(display)
}

function targetDisplayForCreate(): Electron.Display {
  const followActive = store.get('followActiveDisplay', false) as boolean
  if (followActive) {
    return screen.getDisplayNearestPoint(screen.getCursorScreenPoint())
  }
  const lastDisplayId = store.get('lastDisplayId', null) as number | null
  if (lastDisplayId != null) {
    const match = screen.getAllDisplays().find((d) => d.id === lastDisplayId)
    if (match) return match
  }
  return screen.getPrimaryDisplay()
}

let followActiveInterval: NodeJS.Timeout | null = null

function startFollowActiveWatcher() {
  if (followActiveInterval) return
  followActiveInterval = setInterval(() => {
    const followActive = store.get('followActiveDisplay', false) as boolean
    if (!followActive || !mainWindow) return
    const cursorDisplay = screen.getDisplayNearestPoint(screen.getCursorScreenPoint())
    const currentDisplay = screen.getDisplayMatching(mainWindow.getBounds())
    if (cursorDisplay.id !== currentDisplay.id) {
      const pos = positionForDisplay(cursorDisplay)
      mainWindow.setPosition(pos.x, pos.y)
      repositionChatWindow()
    }
  }, 2000)
}

function clampMainWindowToDisplay() {
  if (!mainWindow) return
  const display = screen.getDisplayMatching(mainWindow.getBounds())
  const pos = positionForDisplay(display)
  mainWindow.setPosition(pos.x, pos.y)
}

function createWindow() {
  const targetDisplay = targetDisplayForCreate()
  const { x: savedX, y: savedY } = positionForDisplay(targetDisplay)

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

  // Save position (per-display) when window is moved
  mainWindow.on('moved', () => {
    if (mainWindow) {
      const [x, y] = mainWindow.getPosition()
      const display = screen.getDisplayMatching(mainWindow.getBounds())
      savePositionForDisplay(display.id, x, y)
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

  startFollowActiveWatcher()
}

function getManualChatPosition(): { x: number, y: number } | null {
  return store.get('chatWindowManualPosition', null) as { x: number, y: number } | null
}

function createChatWindow() {
  if (chatWindow) {
    chatWindow.show()
    chatWindow.focus()
    return
  }

  // A manual drag (saved below) wins over the default "above the orb"
  // placement — otherwise repositionChatWindow() (called whenever the orb
  // moves) would silently snap a user-dragged chat window back.
  const chatPos = getManualChatPosition() || getChatWindowPosition()

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

  // Dragging the header (index.css .chat-window-header) fires this —
  // remember it so repositionChatWindow() stops overriding the user's
  // placement, and so it's still there next time the window opens.
  chatWindow.on('moved', () => {
    if (chatWindow) {
      const [x, y] = chatWindow.getPosition()
      store.set('chatWindowManualPosition', { x, y })
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
  // Once the user has dragged the chat window, it stays where they put it —
  // only the un-dragged "speech bubble above the orb" default follows the
  // orb around.
  if (chatWindow && chatWindow.isVisible() && !getManualChatPosition()) {
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

// ── Quick-jot native note (A4) ───────────────────────────────────────────
// Native, not a webapp overlay: must open instantly and work offline. Save
// posts straight to /notes; a failed save queues locally and is retried by
// flushPendingQuickNotes() rather than blocking the user.

function createQuickNoteWindow() {
  if (quickNoteWindow) {
    quickNoteWindow.show()
    quickNoteWindow.focus()
    return
  }

  const { width: screenW, height: screenH } = screen.getPrimaryDisplay().workAreaSize
  const x = Math.round((screenW - QUICK_NOTE_WIDTH) / 2)
  const y = Math.round((screenH - QUICK_NOTE_HEIGHT) / 2)

  quickNoteWindow = new BrowserWindow({
    width: QUICK_NOTE_WIDTH,
    height: QUICK_NOTE_HEIGHT,
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

  quickNoteWindow.setMenu(null)

  if (process.env.NODE_ENV === 'development' || !app.isPackaged) {
    quickNoteWindow.loadURL('http://localhost:5173?view=quicknote')
  } else {
    quickNoteWindow.loadFile(path.join(__dirname, '../dist/index.html'), { query: { view: 'quicknote' } })
  }

  quickNoteWindow.on('closed', () => {
    quickNoteWindow = null
  })
}

async function postNote(title: string, content: string): Promise<any> {
  const apiUrl = store.get('apiUrl', 'https://sara-api.avery.cloud') as string
  const token = store.get('authToken', '') as string

  const res = await fetch(`${apiUrl}/notes`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ title: title || 'Untitled', content }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function saveQuickNote(title: string, content: string): Promise<{ success: boolean; queued?: boolean; note?: any }> {
  try {
    const note = await postNote(title, content)
    if (Notification.isSupported()) {
      const notification = new Notification({ title: 'Note saved', body: title || 'Untitled' })
      notification.on('click', () => createOverlayWindow('note', { note_id: note.id }))
      notification.show()
    }
    return { success: true, note }
  } catch (e) {
    console.warn('[Main] Quick note save failed, queueing for retry:', e)
    const pending = store.get('pendingQuickNotes', []) as Array<{ title: string; content: string; queuedAt: string }>
    pending.push({ title, content, queuedAt: new Date().toISOString() })
    store.set('pendingQuickNotes', pending)
    return { success: false, queued: true }
  }
}

async function flushPendingQuickNotes() {
  const pending = store.get('pendingQuickNotes', []) as Array<{ title: string; content: string; queuedAt: string }>
  if (pending.length === 0) return
  const token = store.get('authToken', '') as string
  if (!token) return

  console.log(`[Main] Flushing ${pending.length} queued quick note(s)`)
  const stillPending: typeof pending = []
  for (const note of pending) {
    try {
      await postNote(note.title, note.content)
    } catch {
      stillPending.push(note)
    }
  }
  store.set('pendingQuickNotes', stillPending)
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

// ── Overlay windows (webapp surfaces rendered in frameless BrowserWindows) ──
// Desktop Jarvis Overhaul D1: one implementation (the webapp's /overlay/:kind
// route) serves webapp overlays, desktop overlays, and future surfaces.

const overlayWindows: Map<string, BrowserWindow> = new Map()

const DEFAULT_OVERLAY_SIZE: Record<string, { width: number; height: number }> = {
  note: { width: 520, height: 620 },
  'blank-note': { width: 520, height: 620 },
  report: { width: 640, height: 700 },
  nutrition: { width: 420, height: 560 },
  brief: { width: 520, height: 640 },
  calendar: { width: 420, height: 560 },
  tasks: { width: 420, height: 520 },
  timers: { width: 340, height: 420 },
  inbox: { width: 460, height: 600 },
  recipes: { width: 420, height: 560 },
}

function getWebappUrl(): string {
  return store.get('webappUrl', 'https://sara.avery.cloud') as string
}

function overlayWindowKey(kind: string, payload: Record<string, any>): string {
  const id = payload?.note_id || payload?.report_type || ''
  return `${kind}:${id}`
}

function createOverlayWindow(kind: string, payload: Record<string, any> = {}) {
  const enabledByKind = store.get('overlayEnabledByKind', {}) as Record<string, boolean>
  if (enabledByKind[kind] === false) {
    console.log('[Main] Overlay kind disabled in settings, not opening:', kind)
    return
  }

  const key = overlayWindowKey(kind, payload)
  const existing = overlayWindows.get(key)
  if (existing && !existing.isDestroyed()) {
    existing.show()
    existing.focus()
    return
  }

  const defaultSize = DEFAULT_OVERLAY_SIZE[kind] || { width: 480, height: 600 }
  const savedWidth = store.get(`overlay_${kind}_width`, defaultSize.width) as number
  const savedHeight = store.get(`overlay_${kind}_height`, defaultSize.height) as number
  const { width: screenW, height: screenH } = screen.getPrimaryDisplay().workAreaSize
  const savedX = store.get(`overlay_${kind}_x`, Math.round((screenW - savedWidth) / 2)) as number
  const savedY = store.get(`overlay_${kind}_y`, Math.round((screenH - savedHeight) / 2)) as number

  const overlayWindow = new BrowserWindow({
    width: savedWidth,
    height: savedHeight,
    x: savedX,
    y: savedY,
    frame: false,
    transparent: false,
    alwaysOnTop: true,
    skipTaskbar: false,
    resizable: true,
    hasShadow: true,
    backgroundColor: '#030712',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  overlayWindow.setMenu(null)

  const token = store.get('authToken', '') as string
  const overlayPath = `/overlay/${encodeURIComponent(kind)}?payload=${encodeURIComponent(JSON.stringify(payload || {}))}`
  const webappUrl = getWebappUrl()
  const targetUrl = token
    ? `${webappUrl}/auth/token-cookie?token=${encodeURIComponent(token)}&redirect=${encodeURIComponent(overlayPath)}`
    : `${webappUrl}${overlayPath}`

  overlayWindow.loadURL(targetUrl)

  overlayWindow.webContents.on('before-input-event', (event, input) => {
    if (input.key === 'Escape') {
      overlayWindow.close()
    }
    if (input.key === 'F12' || (input.control && input.shift && input.key === 'I')) {
      overlayWindow.webContents.toggleDevTools()
    }
  })

  const persistBounds = () => {
    if (overlayWindow.isDestroyed()) return
    const bounds = overlayWindow.getBounds()
    store.set(`overlay_${kind}_x`, bounds.x)
    store.set(`overlay_${kind}_y`, bounds.y)
    store.set(`overlay_${kind}_width`, bounds.width)
    store.set(`overlay_${kind}_height`, bounds.height)
  }
  overlayWindow.on('moved', persistBounds)
  overlayWindow.on('resized', persistBounds)

  overlayWindow.on('closed', () => {
    overlayWindows.delete(key)
  })

  overlayWindows.set(key, overlayWindow)
}

// ── Speaking state + cancel-speech hotkey (double-tap Esc while speaking) ──

let isSpeaking = false
let lastEscPressAt = 0
const DOUBLE_TAP_WINDOW_MS = 500

function setSpeakingState(speaking: boolean) {
  if (speaking === isSpeaking) return
  isSpeaking = speaking
  if (speaking) {
    try {
      globalShortcut.register('Escape', () => {
        const now = Date.now()
        if (now - lastEscPressAt < DOUBLE_TAP_WINDOW_MS) {
          void cancelSpeech()
          lastEscPressAt = 0
        } else {
          lastEscPressAt = now
        }
      })
    } catch (e) {
      console.error('[Main] Failed to register cancel-speech hotkey:', e)
    }
  } else {
    globalShortcut.unregister('Escape')
  }
}

async function cancelSpeech() {
  const apiUrl = store.get('apiUrl', 'https://sara-api.avery.cloud') as string
  const token = store.get('authToken', '') as string
  if (!token) return
  try {
    await fetch(`${apiUrl}/api/devices/command`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ command: 'cancel_speech', payload: {} }),
    })
  } catch (e) {
    console.error('[Main] cancelSpeech request failed:', e)
  }
}

// ── Global hotkeys (A1) ──────────────────────────────────────────────────

function requestVoiceNote() {
  if (sidecarBridge && sidecarBridge.readyState === WebSocket.OPEN) {
    sidecarBridge.send(JSON.stringify({ type: 'record_voice_note' }))
  }
}

function requestScreenshotAndAsk() {
  if (sidecarBridge && sidecarBridge.readyState === WebSocket.OPEN) {
    sidecarBridge.send(JSON.stringify({ type: 'screenshot_request', analyze: true }))
  }
}

// Rebindable global hotkeys (A1/A9). Keyed by a stable action id so the
// settings UI can rebind one without needing to know the others' state.
const HOTKEY_ACTIONS: Record<string, () => void> = {
  summonChat: () => showChatWindow(),
  quickJotNote: () => createQuickNoteWindow(),
  recordVoiceNote: () => requestVoiceNote(),
  screenshotAndAsk: () => requestScreenshotAndAsk(),
}

const DEFAULT_HOTKEYS: Record<string, string> = {
  summonChat: 'CommandOrControl+Shift+Space',
  quickJotNote: 'CommandOrControl+Shift+N',
  recordVoiceNote: 'CommandOrControl+Shift+R',
  screenshotAndAsk: 'CommandOrControl+Shift+S',
}

function getHotkeyBindings(): Record<string, string> {
  return { ...DEFAULT_HOTKEYS, ...(store.get('hotkeyBindings', {}) as Record<string, string>) }
}

function registerGlobalHotkeys() {
  const bindings = getHotkeyBindings()
  for (const [action, accelerator] of Object.entries(bindings)) {
    const handler = HOTKEY_ACTIONS[action]
    if (!handler || !accelerator) continue
    try {
      const ok = globalShortcut.register(accelerator, handler)
      if (!ok) {
        console.warn('[Main] Hotkey registration failed (in use by another app):', action, accelerator)
      }
    } catch (e) {
      console.error('[Main] Hotkey registration error:', action, accelerator, e)
    }
  }
}

function rebindHotkey(action: string, accelerator: string): boolean {
  if (!HOTKEY_ACTIONS[action]) return false
  const bindings = getHotkeyBindings()
  const previous = bindings[action]
  if (previous) {
    try {
      globalShortcut.unregister(previous)
    } catch {
      // no-op — best effort
    }
  }
  const ok = globalShortcut.register(accelerator, HOTKEY_ACTIONS[action])
  if (ok) {
    bindings[action] = accelerator
    store.set('hotkeyBindings', bindings)
  } else if (previous) {
    // Roll back to the previous binding rather than leaving the action dead.
    globalShortcut.register(previous, HOTKEY_ACTIONS[action])
  }
  return ok
}

async function checkForUpdatesManual() {
  // User-initiated update check. We want a visible answer either way, so we
  // wire one-shot listeners that fire a dialog whether an update is found,
  // the current version is already latest, or the check errors out.
  let settled = false
  const finish = (title: string, message: string) => {
    if (settled) return
    settled = true
    dialog.showMessageBox({
      type: 'info',
      title,
      message,
      detail: `Currently installed: v${app.getVersion()}`,
      buttons: ['OK'],
    }).catch(() => {})
  }

  const onAvailable = (info: { version: string }) => {
    finish('Update available', `Sara ${info.version} is downloading now. You'll be prompted to restart when it's ready.`)
  }
  const onNotAvailable = () => {
    finish('Up to date', `You're already running the latest version.`)
  }
  const onError = (err: Error) => {
    finish('Update check failed', err?.message || 'Unknown error checking for updates.')
  }

  autoUpdater.once('update-available', onAvailable)
  autoUpdater.once('update-not-available', onNotAvailable)
  autoUpdater.once('error', onError)

  try {
    await autoUpdater.checkForUpdates()
  } catch (err: any) {
    onError(err instanceof Error ? err : new Error(String(err)))
  }
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
      label: `Sara v${app.getVersion()}`,
      enabled: false,
    },
    {
      label: 'Check for Updates…',
      click: () => {
        void checkForUpdatesManual()
      },
    },
    { type: 'separator' },
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

  tray.setToolTip(`Sara v${app.getVersion()}`)
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
  // Only 'dim-when-idle' ever dims the orb — 'always' (the default) means
  // exactly that, and 'hide-when-fullscreen' is handled separately by
  // applyFullscreenDodge() based on the foreground app, not idle time.
  if (getHudMode() !== 'dim-when-idle') return
  if (mainWindow && isVisible) {
    isVisible = false
    mainWindow.webContents.send('visibility-changed', false)
  }
}

function resetActivityTimer() {
  if (restingTimeout) {
    clearTimeout(restingTimeout)
  }
  if (getHudMode() !== 'dim-when-idle') return
  restingTimeout = setTimeout(() => {
    fadeOut()
  }, RESTING_TIMEOUT)
}

function applyFullscreenDodge(isFullscreen: boolean) {
  if (getHudMode() !== 'hide-when-fullscreen') {
    if (isDodgingFullscreen) {
      isDodgingFullscreen = false
      mainWindow?.show()
    }
    return
  }
  if (isFullscreen && !isDodgingFullscreen) {
    isDodgingFullscreen = true
    mainWindow?.hide()
  } else if (!isFullscreen && isDodgingFullscreen) {
    isDodgingFullscreen = false
    mainWindow?.show()
  }
}

// IPC Handlers
ipcMain.handle('get-api-url', () => {
  return store.get('apiUrl', 'https://sara-api.avery.cloud')
})

ipcMain.handle('set-api-url', (_, url: string) => {
  store.set('apiUrl', url)
})

ipcMain.handle('get-webapp-url', () => {
  return getWebappUrl()
})

ipcMain.handle('set-webapp-url', (_, url: string) => {
  store.set('webappUrl', url)
})

ipcMain.handle('get-follow-active-display', () => {
  return store.get('followActiveDisplay', false)
})

ipcMain.handle('set-follow-active-display', (_, enabled: boolean) => {
  store.set('followActiveDisplay', enabled)
})

ipcMain.handle('get-hud-mode', () => {
  return getHudMode()
})

ipcMain.handle('set-hud-mode', (_, mode: HudMode) => {
  store.set('hudMode', mode)
  if (mode !== 'dim-when-idle') {
    fadeIn()
  }
  if (mode !== 'hide-when-fullscreen' && isDodgingFullscreen) {
    isDodgingFullscreen = false
    mainWindow?.show()
  }
})

ipcMain.handle('get-auth-token', () => {
  return store.get('authToken', null)
})

// Renderer fetch() calls (chat, notes, etc.) have no built-in 401 handling
// of their own — api.ts calls this when it sees one so the same re-login
// prompt fires as the sidecar's WS-rejection path.
ipcMain.on('notify-auth-invalid', () => {
  handleAuthInvalid()
})

ipcMain.handle('set-auth-token', (_, token: string | null) => {
  if (token) {
    store.set('authToken', token)
    // Push new token to sidecar so it can reconnect with fresh credentials
    if (sidecarBridge && sidecarBridge.readyState === WebSocket.OPEN) {
      sidecarBridge.send(JSON.stringify({ type: 'auth_token', token }))
    }
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

// Overlay window controls (webapp surfaces — Desktop Jarvis Overhaul A2)
ipcMain.on('open-overlay', (_, kind: string, payload: Record<string, any>) => {
  createOverlayWindow(kind, payload || {})
})

// Quick-jot native note (A4)
ipcMain.handle('save-quick-note', async (_, title: string, content: string) => {
  return saveQuickNote(title, content)
})
ipcMain.on('close-quick-note', () => {
  quickNoteWindow?.close()
})
ipcMain.on('open-quick-note', () => createQuickNoteWindow())

// HUD quick actions (A1) — same handlers as the global hotkeys
ipcMain.on('request-voice-note', () => requestVoiceNote())
ipcMain.on('request-screenshot-and-ask', () => requestScreenshotAndAsk())

// macOS permissions onboarding (A8)
ipcMain.on('request-permissions-recheck', () => {
  if (sidecarBridge && sidecarBridge.readyState === WebSocket.OPEN) {
    sidecarBridge.send(JSON.stringify({ type: 'recheck_permissions' }))
  }
})

ipcMain.on('open-system-settings', (_, url: string) => {
  void shell.openExternal(url)
})

// Launch-at-login (Permissions tab, Windows/macOS row — A8)
ipcMain.handle('get-autostart', () => {
  return store.get('autoStart', true)
})

ipcMain.handle('set-autostart', (_, enabled: boolean) => {
  store.set('autoStart', enabled)
  app.setLoginItemSettings({ openAtLogin: enabled, openAsHidden: true })
})

// Privacy toggles (A9)
ipcMain.handle('get-focus-tracking-enabled', () => {
  return store.get('focusTrackingEnabled', true)
})

ipcMain.handle('set-focus-tracking-enabled', (_, enabled: boolean) => {
  store.set('focusTrackingEnabled', enabled)
  if (sidecarBridge && sidecarBridge.readyState === WebSocket.OPEN) {
    sidecarBridge.send(JSON.stringify({ type: 'set_focus_tracking_enabled', enabled }))
  }
})

ipcMain.handle('get-connection-status', () => {
  return {
    sidecarRunning: !!sidecarProcess,
    bridgeConnected: !!(sidecarBridge && sidecarBridge.readyState === WebSocket.OPEN),
  }
})

// Voice settings (A9 shell — full mic/wake-word controls land with A6/B3)
ipcMain.handle('get-voice-settings', () => {
  return {
    ttsVoice: store.get('ttsVoice', 'af_heart'),
    ttsSpeed: store.get('ttsSpeed', 1.0),
    useJetsonAtHome: store.get('useJetsonAtHome', true),
    jetsonHost: store.get('jetsonHost', '10.185.1.84'),
  }
})

ipcMain.handle('set-voice-settings', (_, settings: { ttsVoice?: string; ttsSpeed?: number; useJetsonAtHome?: boolean; jetsonHost?: string }) => {
  if (settings.ttsVoice !== undefined) store.set('ttsVoice', settings.ttsVoice)
  if (settings.ttsSpeed !== undefined) store.set('ttsSpeed', settings.ttsSpeed)
  if (settings.useJetsonAtHome !== undefined) store.set('useJetsonAtHome', settings.useJetsonAtHome)
  if (settings.jetsonHost !== undefined) store.set('jetsonHost', settings.jetsonHost)
  if (sidecarBridge && sidecarBridge.readyState === WebSocket.OPEN && (settings.ttsVoice !== undefined || settings.ttsSpeed !== undefined)) {
    sidecarBridge.send(JSON.stringify({
      type: 'set_tts_config',
      voice: settings.ttsVoice ?? store.get('ttsVoice', 'af_heart'),
      speed: settings.ttsSpeed ?? store.get('ttsSpeed', 1.0),
    }))
  }
})

// Hotkey rebinding (A1/A9)
ipcMain.handle('get-hotkeys', () => {
  return getHotkeyBindings()
})

ipcMain.handle('set-hotkey', (_, action: string, accelerator: string) => {
  return rebindHotkey(action, accelerator)
})

// Overlay preferences (A9) — consumed by proactive delivery (Workstream D)
// to decide whether a finished report/brief should pop its overlay
// automatically, and which kinds are enabled at all.
const OVERLAY_KINDS = ['brief', 'nutrition', 'calendar', 'tasks', 'note', 'blank-note', 'report', 'timers', 'inbox', 'recipes']

ipcMain.handle('get-overlay-settings', () => {
  const enabledByKind = store.get('overlayEnabledByKind', {}) as Record<string, boolean>
  return {
    autoOpenReports: store.get('autoOpenReports', true),
    enabledByKind: Object.fromEntries(OVERLAY_KINDS.map((k) => [k, enabledByKind[k] !== false])),
  }
})

ipcMain.handle('set-overlay-settings', (_, settings: { autoOpenReports?: boolean; enabledByKind?: Record<string, boolean> }) => {
  if (settings.autoOpenReports !== undefined) store.set('autoOpenReports', settings.autoOpenReports)
  if (settings.enabledByKind) {
    const current = store.get('overlayEnabledByKind', {}) as Record<string, boolean>
    store.set('overlayEnabledByKind', { ...current, ...settings.enabledByKind })
  }
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

if (!hasSingleInstanceLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (!mainWindow.isVisible()) {
        mainWindow.show()
      }
      if (mainWindow.isMinimized()) {
        mainWindow.restore()
      }
      mainWindow.focus()
      fadeIn()
    }
  })

  // App lifecycle
  app.whenReady().then(() => {
    // Initialize settings store (must be after app is ready)
    store.init()

    // macOS: menu-bar-style app, no Dock icon or Cmd+Tab entry (LSUIElement
    // in package.json handles the packaged build; this covers dev mode too).
    if (process.platform === 'darwin' && app.dock) {
      app.dock.hide()
    }

    // --- Auto-updater ---
    autoUpdater.autoDownload = true
    autoUpdater.autoInstallOnAppQuit = true
    autoUpdater.logger = {
      info: (msg: any) => console.log('[AutoUpdate]', msg),
      warn: (msg: any) => console.warn('[AutoUpdate]', msg),
      error: (msg: any) => console.error('[AutoUpdate]', msg),
      debug: (msg: any) => console.log('[AutoUpdate:debug]', msg),
    }

    autoUpdater.on('update-available', (info) => {
      console.log('[AutoUpdate] Update available:', info.version)
      new Notification({
        title: 'Sara Update Available',
        body: `Version ${info.version} is downloading...`,
      }).show()
    })

    autoUpdater.on('update-downloaded', (info) => {
      console.log('[AutoUpdate] Update downloaded:', info.version)
      dialog.showMessageBox({
        type: 'info',
        title: 'Update Ready',
        message: `Sara ${info.version} has been downloaded.`,
        detail: 'It will be installed when you restart the app. Restart now?',
        buttons: ['Restart', 'Later'],
        defaultId: 0,
      }).then(({ response }) => {
        if (response === 0) {
          autoUpdater.quitAndInstall()
        }
      })
    })

    autoUpdater.on('error', (err) => {
      console.error('[AutoUpdate] Error:', err.message)
    })

    // Check for updates on launch, then every 30 minutes
    autoUpdater.checkForUpdates().catch(err => console.log('[AutoUpdate] Initial check failed:', err.message))
    setInterval(() => {
      autoUpdater.checkForUpdates().catch(err => console.log('[AutoUpdate] Periodic check failed:', err.message))
    }, 30 * 60 * 1000)

    // Start sidecar for activity monitoring and screenshots
    startSidecar(store).catch((err) => {
      console.error('[Main] Failed to start sidecar:', err)
    })

    // Connect to sidecar bridge after a short delay (let sidecar start its WebSocket server)
    setTimeout(() => connectToBridge(store), 2000)

    createWindow()
    createTray()
    resetActivityTimer()
    registerGlobalHotkeys()

    // Multi-monitor: clamp the orb back on-screen if a display is unplugged
    // or its resolution/work-area changes (laptop dock/undock, res change).
    screen.on('display-removed', clampMainWindowToDisplay)
    screen.on('display-metrics-changed', clampMainWindowToDisplay)

    // Retry any quick notes that failed to save while offline (A4).
    setInterval(() => {
      flushPendingQuickNotes().catch((e) => console.error('[Main] flushPendingQuickNotes failed:', e))
    }, 2 * 60 * 1000)

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
    globalShortcut.unregisterAll()
    if (followActiveInterval) {
      clearInterval(followActiveInterval)
      followActiveInterval = null
    }
    stopSidecar()
  })
}
