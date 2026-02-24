"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const electron_1 = require("electron");
const path_1 = __importDefault(require("path"));
const fs_1 = __importDefault(require("fs"));
const net_1 = __importDefault(require("net"));
const child_process_1 = require("child_process");
const ws_1 = __importDefault(require("ws"));
const electron_updater_1 = require("electron-updater");
let sidecarProcess = null;
let sidecarBridge = null;
let bridgeReconnectTimeout = null;
let currentVoiceState = 'disconnected';
function isLocalPortOpen(port, host = '127.0.0.1', timeoutMs = 400) {
    return new Promise((resolve) => {
        const socket = new net_1.default.Socket();
        let settled = false;
        const finish = (open) => {
            if (settled)
                return;
            settled = true;
            socket.destroy();
            resolve(open);
        };
        socket.setTimeout(timeoutMs);
        socket.once('connect', () => finish(true));
        socket.once('timeout', () => finish(false));
        socket.once('error', () => finish(false));
        socket.connect(port, host);
    });
}
async function startSidecar(store) {
    if (sidecarProcess)
        return;
    const bridgeAlreadyRunning = await isLocalPortOpen(9876);
    if (bridgeAlreadyRunning) {
        console.log('[Main] Existing sidecar bridge detected; requesting shutdown before restart');
        await requestExistingSidecarShutdown();
        await new Promise((resolve) => setTimeout(resolve, 900));
        if (await isLocalPortOpen(9876)) {
            console.log('[Main] Existing sidecar did not stop gracefully; forcing shutdown by port owner');
            await forceKillBridgePortProcess(9876);
            await new Promise((resolve) => setTimeout(resolve, 900));
        }
    }
    let sidecarDir;
    let sidecarPath;
    if (electron_1.app.isPackaged) {
        sidecarDir = path_1.default.join(process.resourcesPath, 'sidecar');
        sidecarPath = path_1.default.join(sidecarDir, 'main.py');
    }
    else {
        sidecarDir = path_1.default.join(__dirname, '..', 'sidecar');
        sidecarPath = path_1.default.join(sidecarDir, 'main.py');
    }
    if (!fs_1.default.existsSync(sidecarPath)) {
        console.log('[Main] Sidecar not found at:', sidecarPath);
        return;
    }
    console.log('[Main] Starting sidecar from:', sidecarPath);
    const authToken = store.get('authToken', '');
    const apiUrl = store.get('apiUrl', 'https://sara-api.avery.cloud');
    const isWindows = process.platform === 'win32';
    const isMac = process.platform === 'darwin';
    // Look for venv Python first, fall back to system Python
    let pythonCmd;
    const venvCandidates = isWindows
        ? [
            path_1.default.join(sidecarDir, 'venv', 'Scripts', 'python.exe'),
            path_1.default.join(sidecarDir, '.venv', 'Scripts', 'python.exe'),
        ]
        : [
            path_1.default.join(sidecarDir, 'venv', 'bin', 'python'),
            path_1.default.join(sidecarDir, '.venv', 'bin', 'python'),
        ];
    const discoveredVenv = venvCandidates.find((candidate) => fs_1.default.existsSync(candidate));
    if (discoveredVenv) {
        pythonCmd = discoveredVenv;
        console.log('[Main] Using venv Python:', pythonCmd);
    }
    else {
        pythonCmd = isWindows ? 'python' : 'python3';
        console.log('[Main] Using system Python:', pythonCmd);
        if (isMac) {
            console.log('[Main] Tip: Run sidecar/setup.sh to create a virtual environment');
        }
    }
    sidecarProcess = (0, child_process_1.spawn)(pythonCmd, [sidecarPath], {
        env: {
            ...process.env,
            SARA_AUTH_TOKEN: authToken,
            SARA_BACKEND_URL: apiUrl,
            SARA_VOICE_PLAYBACK_BACKEND: 'auto',
        },
        stdio: ['ignore', 'pipe', 'pipe'],
        cwd: sidecarDir, // Set working directory to sidecar folder
    });
    sidecarProcess.stdout?.on('data', (data) => console.log('[Sidecar]', data.toString().trim()));
    sidecarProcess.stderr?.on('data', (data) => console.error('[Sidecar]', data.toString().trim()));
    sidecarProcess.on('close', (code) => {
        console.log(`[Main] Sidecar exited with code ${code}`);
        sidecarProcess = null;
    });
}
async function requestExistingSidecarShutdown() {
    await new Promise((resolve) => {
        const ws = new ws_1.default('ws://127.0.0.1:9876');
        let settled = false;
        const finish = () => {
            if (settled)
                return;
            settled = true;
            try {
                ws.close();
            }
            catch {
                // no-op
            }
            resolve();
        };
        const timeout = setTimeout(() => {
            console.log('[Main] Existing sidecar shutdown request timed out');
            finish();
        }, 1500);
        ws.on('open', () => {
            try {
                ws.send(JSON.stringify({ type: 'shutdown_sidecar' }));
                console.log('[Main] Sent shutdown request to existing sidecar');
            }
            catch {
                // no-op
            }
            setTimeout(() => {
                clearTimeout(timeout);
                finish();
            }, 350);
        });
        ws.on('error', () => {
            clearTimeout(timeout);
            finish();
        });
        ws.on('close', () => {
            clearTimeout(timeout);
            finish();
        });
    });
}
async function forceKillBridgePortProcess(port) {
    if (process.platform !== 'win32')
        return;
    const script = `
$connections = Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue
if (-not $connections) { exit 0 }
$pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($pid in $pids) {
  try { Stop-Process -Id $pid -Force -ErrorAction Stop } catch {}
}
`;
    await new Promise((resolve) => {
        const ps = (0, child_process_1.spawn)('powershell.exe', ['-NoProfile', '-Command', script], {
            windowsHide: true,
            stdio: ['ignore', 'pipe', 'pipe'],
        });
        ps.stdout?.on('data', (data) => {
            const output = data.toString().trim();
            if (output) {
                console.log('[Main] Port kill stdout:', output);
            }
        });
        ps.stderr?.on('data', (data) => {
            const output = data.toString().trim();
            if (output) {
                console.warn('[Main] Port kill stderr:', output);
            }
        });
        ps.on('close', () => resolve());
        ps.on('error', () => resolve());
    });
}
function stopSidecar() {
    if (sidecarProcess) {
        sidecarProcess.kill();
        sidecarProcess = null;
    }
    disconnectBridge();
}
// Connect to sidecar's WebSocket bridge
function connectToBridge(store) {
    if (sidecarBridge && sidecarBridge.readyState === ws_1.default.OPEN)
        return;
    const bridgeUrl = 'ws://127.0.0.1:9876';
    console.log('[Main] Connecting to sidecar bridge:', bridgeUrl);
    try {
        sidecarBridge = new ws_1.default(bridgeUrl);
        sidecarBridge.on('open', () => {
            console.log('[Main] Connected to sidecar bridge');
            // Send auth token to sidecar
            const token = store.get('authToken', '');
            if (token && sidecarBridge) {
                sidecarBridge.send(JSON.stringify({ type: 'auth_token', token }));
            }
        });
        sidecarBridge.on('message', (data) => {
            try {
                const message = JSON.parse(data.toString());
                handleBridgeMessage(message);
            }
            catch (e) {
                console.error('[Main] Failed to parse bridge message:', e);
            }
        });
        sidecarBridge.on('close', () => {
            console.log('[Main] Disconnected from sidecar bridge');
            sidecarBridge = null;
            // Reconnect after delay
            if (!bridgeReconnectTimeout) {
                bridgeReconnectTimeout = setTimeout(() => {
                    bridgeReconnectTimeout = null;
                    connectToBridge(store);
                }, 3000);
            }
        });
        sidecarBridge.on('error', (err) => {
            console.error('[Main] Bridge connection error:', err.message);
        });
    }
    catch (e) {
        console.error('[Main] Failed to connect to bridge:', e);
    }
}
function disconnectBridge() {
    if (bridgeReconnectTimeout) {
        clearTimeout(bridgeReconnectTimeout);
        bridgeReconnectTimeout = null;
    }
    if (sidecarBridge) {
        sidecarBridge.close();
        sidecarBridge = null;
    }
}
function handleBridgeMessage(message) {
    console.log('[Main] Bridge message:', message.type);
    switch (message.type) {
        case 'show_note':
            // Show note popup
            createNoteWindow(message.note_id || 'remote-note', message.title || 'Note', message.content || '');
            break;
        case 'show_timer':
            // Show timer popup
            createTimerWindow(message.timer_id || `timer-${Date.now()}`, message.label || 'Timer', message.remaining_seconds || 0);
            break;
        case 'show_notification':
            // Show system notification
            if (electron_1.Notification.isSupported()) {
                new electron_1.Notification({
                    title: message.title || 'Sara',
                    body: message.message || ''
                }).show();
            }
            break;
        case 'speak':
            // Forward to renderer for TTS (browser speech synthesis)
            mainWindow?.webContents.send('speak', message.text);
            break;
        case 'activity_update':
            // Forward activity updates to renderer
            mainWindow?.webContents.send('activity-update', message.activity);
            break;
        case 'voice_state':
            // Update tray icon based on voice state
            currentVoiceState = message.state || 'disconnected';
            console.log('[Main] Voice state:', currentVoiceState);
            updateTrayIcon(currentVoiceState);
            // Forward to renderer
            mainWindow?.webContents.send('voice-state', currentVoiceState);
            break;
        case 'voice_transcript':
            // Voice transcript from Jetson
            console.log('[Main] Voice transcript - User:', message.user, 'Sara:', message.sara?.substring(0, 50));
            // Forward to renderer for display
            mainWindow?.webContents.send('voice-transcript', {
                user: message.user,
                sara: message.sara
            });
            // Also show notification
            if (electron_1.Notification.isSupported() && message.user) {
                new electron_1.Notification({
                    title: 'Voice Command',
                    body: message.user
                }).show();
            }
            break;
        case 'system_metrics':
            // Forward system metrics to renderer
            mainWindow?.webContents.send('system-metrics', message.metrics);
            break;
        case 'pong':
            // Health check response
            break;
        default:
            console.log('[Main] Unknown bridge message type:', message.type);
    }
}
// Simple file-based settings store (zero dependencies)
class SimpleStore {
    constructor() {
        this.data = {};
        this.filePath = '';
    }
    init() {
        // Must be called after app is ready
        const userDataPath = electron_1.app.getPath('userData');
        this.filePath = path_1.default.join(userDataPath, 'sara-settings.json');
        this.load();
    }
    load() {
        try {
            if (fs_1.default.existsSync(this.filePath)) {
                const content = fs_1.default.readFileSync(this.filePath, 'utf-8');
                this.data = JSON.parse(content);
            }
        }
        catch (e) {
            console.error('[SimpleStore] Failed to load settings:', e);
            this.data = {};
        }
    }
    save() {
        try {
            const dir = path_1.default.dirname(this.filePath);
            if (!fs_1.default.existsSync(dir)) {
                fs_1.default.mkdirSync(dir, { recursive: true });
            }
            fs_1.default.writeFileSync(this.filePath, JSON.stringify(this.data, null, 2));
        }
        catch (e) {
            console.error('[SimpleStore] Failed to save settings:', e);
        }
    }
    get(key, defaultValue) {
        return this.data[key] ?? defaultValue;
    }
    set(key, value) {
        this.data[key] = value;
        this.save();
    }
    delete(key) {
        delete this.data[key];
        this.save();
    }
}
const store = new SimpleStore();
let mainWindow = null; // Circle window (always 100x100)
let chatWindow = null; // Chat popup window
let noteWindow = null; // Note viewer popup
let settingsWindow = null; // Settings window
let timerWindows = new Map(); // Floating timer windows
let tray = null;
let isQuitting = false;
const hasSingleInstanceLock = electron_1.app.requestSingleInstanceLock();
// Activity monitoring
let activityTimeout = null;
const INACTIVITY_TIMEOUT = 10 * 60 * 1000; // 10 minutes
let isVisible = true;
// Window sizes
const CIRCLE_WIDTH = 240; // Smoke ring (100) + 2 side buttons (40 each) + gaps + padding
const CIRCLE_HEIGHT = 120; // Smoke ring (100) + padding
const CHAT_WIDTH = 320;
const CHAT_HEIGHT = 450;
const NOTE_WIDTH = 500;
const NOTE_HEIGHT = 600;
const TIMER_WIDTH = 200;
const TIMER_HEIGHT = 80;
const SETTINGS_WIDTH = 400;
const SETTINGS_HEIGHT = 500;
function createWindow() {
    const { width, height } = electron_1.screen.getPrimaryDisplay().workAreaSize;
    // Get saved position or default to bottom-right corner
    let savedX = store.get('windowX', width - CIRCLE_WIDTH - 20);
    let savedY = store.get('windowY', height - CIRCLE_HEIGHT - 20);
    // Validate position is on-screen (handle multi-monitor changes, corrupted settings, etc.)
    if (savedX < 0 || savedX > width - 50 || savedY < 0 || savedY > height - 50) {
        console.log('[Main] Saved position off-screen, resetting to default');
        savedX = width - CIRCLE_WIDTH - 20;
        savedY = height - CIRCLE_HEIGHT - 20;
        store.set('windowX', savedX);
        store.set('windowY', savedY);
    }
    console.log('[Main] Creating circle window at', savedX, savedY, 'size', CIRCLE_WIDTH, 'x', CIRCLE_HEIGHT);
    mainWindow = new electron_1.BrowserWindow({
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
            preload: path_1.default.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
        },
    });
    // Remove menu bar
    mainWindow.setMenu(null);
    // Load the app (circle view)
    const indexPath = path_1.default.join(__dirname, '../dist/index.html');
    console.log('[Main] Loading circle view from:', indexPath);
    if (process.env.NODE_ENV === 'development' || !electron_1.app.isPackaged) {
        mainWindow.loadURL('http://localhost:5173?view=circle');
    }
    else {
        mainWindow.loadFile(indexPath, { query: { view: 'circle' } });
    }
    // Debug: Log when page loads
    mainWindow.webContents.on('did-finish-load', () => {
        console.log('[Main] Circle window finished loading');
    });
    mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription) => {
        console.error('[Main] Circle window failed to load:', errorCode, errorDescription);
    });
    // Open DevTools for debugging (press F12 or Ctrl+Shift+I)
    mainWindow.webContents.on('before-input-event', (event, input) => {
        if (input.key === 'F12' || (input.control && input.shift && input.key === 'I')) {
            mainWindow?.webContents.toggleDevTools();
        }
    });
    // Save position when window is moved
    mainWindow.on('moved', () => {
        if (mainWindow) {
            const [x, y] = mainWindow.getPosition();
            store.set('windowX', x);
            store.set('windowY', y);
            // Reposition chat window if it's open
            repositionChatWindow();
        }
    });
    mainWindow.on('close', (event) => {
        if (!isQuitting) {
            event.preventDefault();
            mainWindow?.hide();
            chatWindow?.hide();
        }
    });
    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}
function createChatWindow() {
    if (chatWindow) {
        chatWindow.show();
        chatWindow.focus();
        return;
    }
    // Position chat window above the circle
    const chatPos = getChatWindowPosition();
    chatWindow = new electron_1.BrowserWindow({
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
            preload: path_1.default.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
        },
    });
    chatWindow.setMenu(null);
    // Load the chat view
    if (process.env.NODE_ENV === 'development' || !electron_1.app.isPackaged) {
        chatWindow.loadURL('http://localhost:5173?view=chat');
    }
    else {
        chatWindow.loadFile(path_1.default.join(__dirname, '../dist/index.html'), { query: { view: 'chat' } });
    }
    // Open DevTools for debugging
    chatWindow.webContents.on('before-input-event', (event, input) => {
        if (input.key === 'F12' || (input.control && input.shift && input.key === 'I')) {
            chatWindow?.webContents.toggleDevTools();
        }
    });
    chatWindow.on('closed', () => {
        chatWindow = null;
    });
}
function getChatWindowPosition() {
    const { width: screenW, height: screenH } = electron_1.screen.getPrimaryDisplay().workAreaSize;
    if (!mainWindow) {
        return { x: screenW - CHAT_WIDTH - 20, y: screenH - CHAT_HEIGHT - CIRCLE_HEIGHT - 20 };
    }
    const [circleX, circleY] = mainWindow.getPosition();
    // Position chat so its bottom-right corner is near the circle's top-left
    // This creates a "speech bubble" effect where chat appears above/left of circle
    let x = circleX + CIRCLE_WIDTH - CHAT_WIDTH; // Align right edges
    let y = circleY - CHAT_HEIGHT - 10; // Position above circle with 10px gap
    // Clamp to screen bounds
    x = Math.max(10, Math.min(x, screenW - CHAT_WIDTH - 10));
    y = Math.max(10, Math.min(y, screenH - CHAT_HEIGHT - 10));
    // If not enough room above, position to the left of circle
    if (y < 10) {
        y = circleY;
        x = circleX - CHAT_WIDTH - 10;
        if (x < 10) {
            x = circleX + CIRCLE_WIDTH + 10; // Position to the right instead
        }
    }
    return { x, y };
}
function repositionChatWindow() {
    if (chatWindow && chatWindow.isVisible()) {
        const pos = getChatWindowPosition();
        chatWindow.setPosition(pos.x, pos.y);
    }
}
function showChatWindow() {
    createChatWindow();
}
function hideChatWindow() {
    chatWindow?.hide();
}
function createNoteWindow(noteId, title, content) {
    // Close existing note window if open
    if (noteWindow) {
        noteWindow.close();
        noteWindow = null;
    }
    const { width: screenW, height: screenH } = electron_1.screen.getPrimaryDisplay().workAreaSize;
    // Center the note window on screen
    const x = Math.round((screenW - NOTE_WIDTH) / 2);
    const y = Math.round((screenH - NOTE_HEIGHT) / 2);
    noteWindow = new electron_1.BrowserWindow({
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
            preload: path_1.default.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
        },
    });
    noteWindow.setMenu(null);
    // Encode note data in URL
    const noteData = encodeURIComponent(JSON.stringify({ id: noteId, title, content }));
    if (process.env.NODE_ENV === 'development' || !electron_1.app.isPackaged) {
        noteWindow.loadURL(`http://localhost:5173?view=note&data=${noteData}`);
    }
    else {
        noteWindow.loadFile(path_1.default.join(__dirname, '../dist/index.html'), {
            query: { view: 'note', data: noteData }
        });
    }
    noteWindow.on('closed', () => {
        noteWindow = null;
    });
}
function createTimerWindow(timerId, name, remainingSeconds) {
    // Check if timer window already exists
    if (timerWindows.has(timerId)) {
        const existingWindow = timerWindows.get(timerId);
        existingWindow?.webContents.send('timer-update', { id: timerId, name, remainingSeconds });
        return;
    }
    const { width: screenW } = electron_1.screen.getPrimaryDisplay().workAreaSize;
    // Stack timer windows in the top-right corner
    const timerCount = timerWindows.size;
    const x = screenW - TIMER_WIDTH - 20;
    const y = 20 + (timerCount * (TIMER_HEIGHT + 10));
    const timerWindow = new electron_1.BrowserWindow({
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
            preload: path_1.default.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
        },
    });
    timerWindow.setMenu(null);
    // Encode timer data in URL
    const timerData = encodeURIComponent(JSON.stringify({ id: timerId, name, remainingSeconds }));
    if (process.env.NODE_ENV === 'development' || !electron_1.app.isPackaged) {
        timerWindow.loadURL(`http://localhost:5173?view=timer&data=${timerData}`);
    }
    else {
        timerWindow.loadFile(path_1.default.join(__dirname, '../dist/index.html'), {
            query: { view: 'timer', data: timerData }
        });
    }
    timerWindows.set(timerId, timerWindow);
    timerWindow.on('closed', () => {
        timerWindows.delete(timerId);
    });
}
function closeTimerWindow(timerId) {
    const timerWindow = timerWindows.get(timerId);
    if (timerWindow) {
        timerWindow.close();
        timerWindows.delete(timerId);
    }
}
function createSettingsWindow() {
    if (settingsWindow) {
        settingsWindow.show();
        settingsWindow.focus();
        return;
    }
    const { width: screenW, height: screenH } = electron_1.screen.getPrimaryDisplay().workAreaSize;
    // Center the settings window on screen
    const x = Math.round((screenW - SETTINGS_WIDTH) / 2);
    const y = Math.round((screenH - SETTINGS_HEIGHT) / 2);
    settingsWindow = new electron_1.BrowserWindow({
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
            preload: path_1.default.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
        },
    });
    settingsWindow.setMenu(null);
    if (process.env.NODE_ENV === 'development' || !electron_1.app.isPackaged) {
        settingsWindow.loadURL('http://localhost:5173?view=settings');
    }
    else {
        settingsWindow.loadFile(path_1.default.join(__dirname, '../dist/index.html'), {
            query: { view: 'settings' }
        });
    }
    settingsWindow.on('closed', () => {
        settingsWindow = null;
    });
}
function updateTrayIcon(voiceState) {
    if (!tray)
        return;
    // Update tooltip to show voice state
    const stateLabels = {
        disconnected: 'Sara - Voice: Disconnected',
        connected: 'Sara - Voice: Ready',
        wake_word: 'Sara - Voice: Listening...',
        speaking: 'Sara - Voice: Speaking...',
    };
    tray.setToolTip(stateLabels[voiceState] || 'Sara - Your AI Assistant');
    // Try to load state-specific icon if it exists
    const iconName = `tray-${voiceState}.png`;
    const iconPath = path_1.default.join(__dirname, '../assets/icons', iconName);
    const defaultIconPath = path_1.default.join(__dirname, '../assets/icons/tray.png');
    try {
        if (fs_1.default.existsSync(iconPath)) {
            const stateIcon = electron_1.nativeImage.createFromPath(iconPath);
            if (!stateIcon.isEmpty()) {
                tray.setImage(stateIcon);
                return;
            }
        }
        // Fall back to default icon
        if (fs_1.default.existsSync(defaultIconPath)) {
            const defaultIcon = electron_1.nativeImage.createFromPath(defaultIconPath);
            if (!defaultIcon.isEmpty()) {
                tray.setImage(defaultIcon);
            }
        }
    }
    catch (e) {
        console.error('[Main] Failed to update tray icon:', e);
    }
}
function createTray() {
    try {
        const iconPath = path_1.default.join(__dirname, '../assets/icons/tray.png');
        const trayIcon = electron_1.nativeImage.createFromPath(iconPath);
        tray = new electron_1.Tray(trayIcon.isEmpty() ? electron_1.nativeImage.createEmpty() : trayIcon);
    }
    catch {
        tray = new electron_1.Tray(electron_1.nativeImage.createEmpty());
    }
    const contextMenu = electron_1.Menu.buildFromTemplate([
        {
            label: 'Show Sara',
            click: () => {
                mainWindow?.show();
                fadeIn();
            },
        },
        {
            label: 'Open Chat',
            click: () => {
                showChatWindow();
            },
        },
        { type: 'separator' },
        {
            label: 'Settings',
            click: () => {
                createSettingsWindow();
            },
        },
        { type: 'separator' },
        {
            label: 'Quit Sara',
            click: () => {
                isQuitting = true;
                electron_1.app.quit();
            },
        },
    ]);
    tray.setToolTip('Sara - Your AI Assistant');
    tray.setContextMenu(contextMenu);
    tray.on('click', () => {
        if (mainWindow?.isVisible()) {
            mainWindow.hide();
            chatWindow?.hide();
        }
        else {
            mainWindow?.show();
            fadeIn();
        }
    });
    // Set initial voice state icon
    updateTrayIcon(currentVoiceState);
}
function fadeIn() {
    if (mainWindow && !isVisible) {
        isVisible = true;
        mainWindow.webContents.send('visibility-changed', true);
    }
    resetActivityTimer();
}
function fadeOut() {
    if (mainWindow && isVisible) {
        isVisible = false;
        mainWindow.webContents.send('visibility-changed', false);
    }
}
function resetActivityTimer() {
    if (activityTimeout) {
        clearTimeout(activityTimeout);
    }
    activityTimeout = setTimeout(() => {
        fadeOut();
    }, INACTIVITY_TIMEOUT);
}
// IPC Handlers
electron_1.ipcMain.handle('get-mode', () => {
    return store.get('mode', 'wakeWord');
});
electron_1.ipcMain.handle('set-mode', (_, mode) => {
    store.set('mode', mode);
});
electron_1.ipcMain.handle('get-api-url', () => {
    return store.get('apiUrl', 'https://sara-api.avery.cloud');
});
electron_1.ipcMain.handle('set-api-url', (_, url) => {
    store.set('apiUrl', url);
});
electron_1.ipcMain.handle('get-auth-token', () => {
    return store.get('authToken', null);
});
electron_1.ipcMain.handle('set-auth-token', (_, token) => {
    if (token) {
        store.set('authToken', token);
        // Push new token to sidecar so it can reconnect with fresh credentials
        if (sidecarBridge && sidecarBridge.readyState === ws_1.default.OPEN) {
            sidecarBridge.send(JSON.stringify({ type: 'auth_token', token }));
        }
    }
    else {
        store.delete('authToken');
    }
});
electron_1.ipcMain.on('activity-detected', () => {
    fadeIn();
});
// Chat window controls
electron_1.ipcMain.on('show-chat', () => {
    showChatWindow();
});
electron_1.ipcMain.on('hide-chat', () => {
    hideChatWindow();
});
electron_1.ipcMain.on('show-context-menu', () => {
    if (tray) {
        tray.popUpContextMenu();
    }
});
// Note window controls
electron_1.ipcMain.on('show-note', (_, noteData) => {
    createNoteWindow(noteData.id, noteData.title, noteData.content);
});
electron_1.ipcMain.on('close-note', () => {
    noteWindow?.close();
});
electron_1.ipcMain.on('close-settings', () => {
    settingsWindow?.close();
});
// Timer window controls
electron_1.ipcMain.on('show-timer', (_, timerData) => {
    createTimerWindow(timerData.id, timerData.name, timerData.remainingSeconds);
});
electron_1.ipcMain.on('close-timer', (_, timerId) => {
    closeTimerWindow(timerId);
});
electron_1.ipcMain.on('update-timer', (_, timerData) => {
    const timerWindow = timerWindows.get(timerData.id);
    if (timerWindow) {
        timerWindow.webContents.send('timer-update', timerData);
    }
});
if (!hasSingleInstanceLock) {
    electron_1.app.quit();
}
else {
    electron_1.app.on('second-instance', () => {
        if (mainWindow) {
            if (!mainWindow.isVisible()) {
                mainWindow.show();
            }
            if (mainWindow.isMinimized()) {
                mainWindow.restore();
            }
            mainWindow.focus();
            fadeIn();
        }
    });
    // App lifecycle
    electron_1.app.whenReady().then(() => {
        // Initialize settings store (must be after app is ready)
        store.init();
        // --- Auto-updater ---
        electron_updater_1.autoUpdater.autoDownload = true;
        electron_updater_1.autoUpdater.autoInstallOnAppQuit = true;
        electron_updater_1.autoUpdater.logger = {
            info: (msg) => console.log('[AutoUpdate]', msg),
            warn: (msg) => console.warn('[AutoUpdate]', msg),
            error: (msg) => console.error('[AutoUpdate]', msg),
            debug: (msg) => console.log('[AutoUpdate:debug]', msg),
        };
        electron_updater_1.autoUpdater.on('update-available', (info) => {
            console.log('[AutoUpdate] Update available:', info.version);
            new electron_1.Notification({
                title: 'Sara Update Available',
                body: `Version ${info.version} is downloading...`,
            }).show();
        });
        electron_updater_1.autoUpdater.on('update-downloaded', (info) => {
            console.log('[AutoUpdate] Update downloaded:', info.version);
            electron_1.dialog.showMessageBox({
                type: 'info',
                title: 'Update Ready',
                message: `Sara ${info.version} has been downloaded.`,
                detail: 'It will be installed when you restart the app. Restart now?',
                buttons: ['Restart', 'Later'],
                defaultId: 0,
            }).then(({ response }) => {
                if (response === 0) {
                    electron_updater_1.autoUpdater.quitAndInstall();
                }
            });
        });
        electron_updater_1.autoUpdater.on('error', (err) => {
            console.error('[AutoUpdate] Error:', err.message);
        });
        // Check for updates on launch, then every 30 minutes
        electron_updater_1.autoUpdater.checkForUpdates().catch(err => console.log('[AutoUpdate] Initial check failed:', err.message));
        setInterval(() => {
            electron_updater_1.autoUpdater.checkForUpdates().catch(err => console.log('[AutoUpdate] Periodic check failed:', err.message));
        }, 30 * 60 * 1000);
        // Start sidecar for activity monitoring and screenshots
        startSidecar(store).catch((err) => {
            console.error('[Main] Failed to start sidecar:', err);
        });
        // Connect to sidecar bridge after a short delay (let sidecar start its WebSocket server)
        setTimeout(() => connectToBridge(store), 2000);
        createWindow();
        createTray();
        resetActivityTimer();
        // Auto-start on login (can be toggled in settings)
        const autoStart = store.get('autoStart', true);
        electron_1.app.setLoginItemSettings({
            openAtLogin: autoStart,
            openAsHidden: true,
        });
        // If mode was saved as silent, show chat window
        if (store.get('mode') === 'silent') {
            showChatWindow();
        }
        electron_1.app.on('activate', () => {
            if (electron_1.BrowserWindow.getAllWindows().length === 0) {
                createWindow();
            }
        });
    });
    electron_1.app.on('window-all-closed', () => {
        if (process.platform !== 'darwin') {
            electron_1.app.quit();
        }
    });
    electron_1.app.on('before-quit', () => {
        isQuitting = true;
        stopSidecar();
    });
}
