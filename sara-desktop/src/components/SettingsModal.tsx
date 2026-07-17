import { useEffect, useState } from 'react'
import { apiClient } from '../services/api'

interface SettingsModalProps {
  onClose: () => void
  onAuthChange: (authenticated: boolean) => void
}

type TabId = 'account' | 'appearance' | 'overlays' | 'privacy' | 'voice' | 'permissions' | 'about'

const TABS: { id: TabId; label: string }[] = [
  { id: 'account', label: 'Account' },
  { id: 'appearance', label: 'Appearance' },
  { id: 'overlays', label: 'Overlays' },
  { id: 'privacy', label: 'Privacy' },
  { id: 'voice', label: 'Voice' },
  { id: 'permissions', label: 'Permissions' },
  { id: 'about', label: 'About' },
]

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex items-center justify-between gap-3 py-1.5 cursor-pointer">
      <span className="text-sm text-gray-300">{label}</span>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={`w-10 h-5 rounded-full transition-colors relative shrink-0 ${checked ? 'bg-indigo-600' : 'bg-gray-700'}`}
      >
        <span
          className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${checked ? 'translate-x-5' : 'translate-x-0.5'}`}
        />
      </button>
    </label>
  )
}

// ── Account ─────────────────────────────────────────────────────────────

function AccountTab({ onAuthChange }: { onAuthChange: (authenticated: boolean) => void }) {
  const [apiUrl, setApiUrl] = useState('https://sara-api.avery.cloud')
  const [webappUrl, setWebappUrl] = useState('https://sara.avery.cloud')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [connection, setConnection] = useState<{ sidecarRunning: boolean; bridgeConnected: boolean } | null>(null)

  useEffect(() => {
    const init = async () => {
      if (!window.electronAPI) return
      const url = await window.electronAPI.getApiUrl()
      setApiUrl(url)
      apiClient.setBaseUrl(url)
      setWebappUrl(await window.electronAPI.getWebappUrl())
      const token = await window.electronAPI.getAuthToken()
      setIsAuthenticated(!!token)
      setConnection(await window.electronAPI.getConnectionStatus())
    }
    init()
    const interval = setInterval(async () => {
      if (window.electronAPI) setConnection(await window.electronAPI.getConnectionStatus())
    }, 5000)
    return () => clearInterval(interval)
  }, [])

  const handleLogin = async () => {
    if (!email.trim() || !password.trim()) {
      setError('Please enter email and password')
      return
    }
    setIsLoading(true)
    setError('')
    try {
      await window.electronAPI?.setApiUrl(apiUrl)
      apiClient.setBaseUrl(apiUrl)
      const result = await apiClient.login(email, password)
      if (result.token) {
        await window.electronAPI?.setAuthToken(result.token)
        setIsAuthenticated(true)
        onAuthChange(true)
        setPassword('')
      } else {
        setError(result.error || 'Login failed. Please check your credentials.')
      }
    } catch (err) {
      console.error('Login error:', err)
      setError('Failed to connect. Please check the API URL.')
    } finally {
      setIsLoading(false)
    }
  }

  const handleLogout = async () => {
    await window.electronAPI?.setAuthToken(null)
    apiClient.setToken(null)
    setIsAuthenticated(false)
    onAuthChange(false)
  }

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <label className="text-sm font-medium text-gray-300">Backend API URL</label>
        <input
          type="url"
          value={apiUrl}
          onChange={(e) => setApiUrl(e.target.value)}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm focus:outline-none focus:border-indigo-500"
        />
      </div>
      <div className="space-y-2">
        <label className="text-sm font-medium text-gray-300">Webapp URL (overlay windows)</label>
        <input
          type="url"
          value={webappUrl}
          onChange={(e) => setWebappUrl(e.target.value)}
          onBlur={() => window.electronAPI?.setWebappUrl(webappUrl)}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm focus:outline-none focus:border-indigo-500"
        />
      </div>

      <div className="space-y-1 text-sm">
        <p className="text-gray-400">Connection status</p>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${connection?.sidecarRunning ? 'bg-emerald-500' : 'bg-gray-600'}`} />
          <span className="text-gray-300">Sidecar {connection?.sidecarRunning ? 'running' : 'stopped'}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${connection?.bridgeConnected ? 'bg-emerald-500' : 'bg-gray-600'}`} />
          <span className="text-gray-300">Backend WS {connection?.bridgeConnected ? 'connected' : 'disconnected'}</span>
        </div>
      </div>

      <div className="space-y-3 pt-2 border-t border-gray-800">
        {isAuthenticated ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-green-400">
              <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z" />
              </svg>
              <span className="text-sm">Connected</span>
            </div>
            <button
              onClick={handleLogout}
              className="w-full bg-red-600/20 hover:bg-red-600/30 text-red-400 border border-red-600/30 rounded-lg px-4 py-2 text-sm transition-colors"
            >
              Log Out
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm focus:outline-none focus:border-indigo-500"
              placeholder="Email"
            />
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm focus:outline-none focus:border-indigo-500"
              placeholder="Password"
            />
            {error && <p className="text-red-400 text-sm">{error}</p>}
            <button
              onClick={handleLogin}
              disabled={isLoading}
              className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 text-white rounded-lg px-4 py-2 text-sm transition-colors"
            >
              {isLoading ? 'Connecting...' : 'Connect'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Appearance / HUD ─────────────────────────────────────────────────────

const HOTKEY_LABELS: Record<string, string> = {
  summonChat: 'Summon chat',
  quickJotNote: 'Quick-jot note',
  recordVoiceNote: 'Record voice note',
  screenshotAndAsk: 'Screenshot & ask',
}

function AppearanceTab() {
  const [hudMode, setHudModeState] = useState('always')
  const [followActive, setFollowActive] = useState(false)
  const [hotkeys, setHotkeys] = useState<Record<string, string>>({})
  const [hotkeyDrafts, setHotkeyDrafts] = useState<Record<string, string>>({})
  const [hotkeyError, setHotkeyError] = useState<string | null>(null)

  useEffect(() => {
    const init = async () => {
      if (!window.electronAPI) return
      setHudModeState(await window.electronAPI.getHudMode())
      setFollowActive(await window.electronAPI.getFollowActiveDisplay())
      const bindings = await window.electronAPI.getHotkeys()
      setHotkeys(bindings)
      setHotkeyDrafts(bindings)
    }
    init()
  }, [])

  const applyHotkey = async (action: string) => {
    const accelerator = hotkeyDrafts[action]
    if (!accelerator || accelerator === hotkeys[action]) return
    const ok = await window.electronAPI?.setHotkey(action, accelerator)
    if (ok) {
      setHotkeys((h) => ({ ...h, [action]: accelerator }))
      setHotkeyError(null)
    } else {
      setHotkeyError(`Could not bind "${accelerator}" for ${HOTKEY_LABELS[action] || action} (already in use?)`)
      setHotkeyDrafts((d) => ({ ...d, [action]: hotkeys[action] }))
    }
  }

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <label className="text-sm font-medium text-gray-300">HUD visibility</label>
        <select
          value={hudMode}
          onChange={async (e) => {
            setHudModeState(e.target.value)
            await window.electronAPI?.setHudMode(e.target.value)
          }}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm focus:outline-none focus:border-indigo-500"
        >
          <option value="always">Always visible</option>
          <option value="dim-when-idle">Dim when idle</option>
          <option value="hide-when-fullscreen">Hide when a fullscreen app is active</option>
        </select>
      </div>

      <Toggle
        checked={followActive}
        onChange={async (v) => {
          setFollowActive(v)
          await window.electronAPI?.setFollowActiveDisplay(v)
        }}
        label="Follow the cursor's monitor across displays"
      />

      <div className="space-y-2 pt-2 border-t border-gray-800">
        <p className="text-sm font-medium text-gray-300">Global hotkeys</p>
        {Object.keys(HOTKEY_LABELS).map((action) => (
          <div key={action} className="flex items-center gap-2">
            <span className="text-xs text-gray-400 w-32 shrink-0">{HOTKEY_LABELS[action]}</span>
            <input
              value={hotkeyDrafts[action] || ''}
              onChange={(e) => setHotkeyDrafts((d) => ({ ...d, [action]: e.target.value }))}
              onBlur={() => applyHotkey(action)}
              onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
              className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1 text-white text-xs font-mono focus:outline-none focus:border-indigo-500"
            />
          </div>
        ))}
        {hotkeyError && <p className="text-red-400 text-xs">{hotkeyError}</p>}
        <p className="text-xs text-gray-500">
          Use Electron accelerator syntax, e.g. CommandOrControl+Shift+Space.
        </p>
      </div>
    </div>
  )
}

// ── Overlays ─────────────────────────────────────────────────────────────

const OVERLAY_KIND_LABELS: Record<string, string> = {
  brief: 'Morning brief',
  nutrition: 'Nutrition',
  calendar: 'Calendar',
  tasks: 'Background tasks',
  note: 'Note',
  'blank-note': 'Blank note',
  report: 'Report',
  timers: 'Timers',
  inbox: 'Inbox',
  recipes: 'Recipes',
}

function OverlaysTab() {
  const [autoOpenReports, setAutoOpenReports] = useState(true)
  const [enabledByKind, setEnabledByKind] = useState<Record<string, boolean>>({})

  useEffect(() => {
    window.electronAPI?.getOverlaySettings().then((s) => {
      setAutoOpenReports(s.autoOpenReports)
      setEnabledByKind(s.enabledByKind)
    })
  }, [])

  return (
    <div className="space-y-4">
      <Toggle
        checked={autoOpenReports}
        onChange={async (v) => {
          setAutoOpenReports(v)
          await window.electronAPI?.setOverlaySettings({ autoOpenReports: v })
        }}
        label="Open reports automatically when finished"
      />
      <div className="pt-2 border-t border-gray-800">
        <p className="text-sm font-medium text-gray-300 mb-1">Enabled overlays</p>
        {Object.entries(OVERLAY_KIND_LABELS).map(([kind, label]) => (
          <Toggle
            key={kind}
            checked={enabledByKind[kind] !== false}
            onChange={async (v) => {
              const next = { ...enabledByKind, [kind]: v }
              setEnabledByKind(next)
              await window.electronAPI?.setOverlaySettings({ enabledByKind: { [kind]: v } })
            }}
            label={label}
          />
        ))}
      </div>
    </div>
  )
}

// ── Privacy ──────────────────────────────────────────────────────────────

function PrivacyTab() {
  const [focusTrackingEnabled, setFocusTrackingEnabled] = useState(true)
  const [screenshotEnabled, setScreenshotEnabled] = useState(true)
  const [screenshotInterval, setScreenshotInterval] = useState(300)
  const [deviceId, setDeviceId] = useState<string | null>(null)

  useEffect(() => {
    const init = async () => {
      if (!window.electronAPI) return
      setFocusTrackingEnabled(await window.electronAPI.getFocusTrackingEnabled())

      try {
        const apiUrl = await window.electronAPI.getApiUrl()
        const token = await window.electronAPI.getAuthToken()
        const res = await fetch(`${apiUrl}/api/devices/list`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          credentials: 'include',
        })
        if (res.ok) {
          const data = await res.json()
          // Best-effort: the renderer doesn't have the real hostname, so
          // this picks the currently-connected device (almost always this
          // one, since Settings only opens from a running desktop instance).
          const mine = (data.devices || []).find((d: any) => d.is_connected) || (data.devices || [])[0]
          if (mine) {
            setDeviceId(mine.device_id)
            setScreenshotEnabled(mine.screenshot_enabled !== false)
          }
        }
      } catch {
        // best-effort
      }
    }
    init()
  }, [])

  const pushConfig = async (patch: { screenshot_enabled?: boolean; screenshot_interval_seconds?: number }) => {
    if (!deviceId) return
    const apiUrl = await window.electronAPI?.getApiUrl()
    const token = await window.electronAPI?.getAuthToken()
    await fetch(`${apiUrl}/api/devices/${deviceId}/config`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      credentials: 'include',
      body: JSON.stringify(patch),
    })
  }

  return (
    <div className="space-y-4">
      <Toggle
        checked={focusTrackingEnabled}
        onChange={async (v) => {
          setFocusTrackingEnabled(v)
          await window.electronAPI?.setFocusTrackingEnabled(v)
        }}
        label="Focus tracking (app/window activity)"
      />
      <Toggle
        checked={screenshotEnabled}
        onChange={async (v) => {
          setScreenshotEnabled(v)
          await pushConfig({ screenshot_enabled: v })
        }}
        label="Ambient screenshots"
      />
      <div className="space-y-1">
        <label className="text-sm text-gray-300">Ambient screenshot interval (seconds)</label>
        <input
          type="number"
          min={10}
          value={screenshotInterval}
          onChange={(e) => setScreenshotInterval(parseInt(e.target.value, 10) || 300)}
          onBlur={() => pushConfig({ screenshot_interval_seconds: screenshotInterval })}
          className="w-32 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-white text-sm focus:outline-none focus:border-indigo-500"
        />
      </div>
      <p className="text-xs text-gray-500 pt-2 border-t border-gray-800">
        On-demand "screenshot & ask" still works even with ambient screenshots off — it only
        captures when you explicitly ask.
      </p>
    </div>
  )
}

// ── Voice ────────────────────────────────────────────────────────────────

function VoiceTab() {
  const [ttsVoice, setTtsVoice] = useState('af_heart')
  const [ttsSpeed, setTtsSpeed] = useState(1.0)
  const [useJetsonAtHome, setUseJetsonAtHome] = useState(true)
  const [jetsonHost, setJetsonHost] = useState('')

  useEffect(() => {
    window.electronAPI?.getVoiceSettings().then((s) => {
      setTtsVoice(s.ttsVoice)
      setTtsSpeed(s.ttsSpeed)
      setUseJetsonAtHome(s.useJetsonAtHome)
      setJetsonHost(s.jetsonHost)
    })
  }, [])

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <label className="text-sm font-medium text-gray-300">TTS voice</label>
        <input
          value={ttsVoice}
          onChange={(e) => setTtsVoice(e.target.value)}
          onBlur={() => window.electronAPI?.setVoiceSettings({ ttsVoice })}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm focus:outline-none focus:border-indigo-500"
        />
      </div>
      <div className="space-y-1">
        <label className="text-sm text-gray-300">TTS speed ({ttsSpeed.toFixed(2)}x)</label>
        <input
          type="range"
          min={0.5}
          max={1.5}
          step={0.05}
          value={ttsSpeed}
          onChange={(e) => setTtsSpeed(parseFloat(e.target.value))}
          onMouseUp={() => window.electronAPI?.setVoiceSettings({ ttsSpeed })}
          className="w-full"
        />
      </div>
      <Toggle
        checked={useJetsonAtHome}
        onChange={async (v) => {
          setUseJetsonAtHome(v)
          await window.electronAPI?.setVoiceSettings({ useJetsonAtHome: v })
        }}
        label="Use the Jetson for voice notes/wake word at home"
      />
      <div className="space-y-1">
        <label className="text-sm text-gray-300">Jetson host/IP</label>
        <input
          value={jetsonHost}
          placeholder="e.g. 10.185.1.155"
          onChange={(e) => setJetsonHost(e.target.value)}
          onBlur={() => window.electronAPI?.setVoiceSettings({ jetsonHost })}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm focus:outline-none focus:border-indigo-500"
        />
        <p className="text-xs text-gray-500">Takes effect the next time the sidecar restarts.</p>
      </div>
      <div className="pt-2 border-t border-gray-800 text-xs text-gray-500 space-y-1">
        <p>Mic device picker, level meter, push-to-talk, and local wake word</p>
        <p>land with the sidecar voice module (Workstream A6/B3).</p>
      </div>
    </div>
  )
}

// ── Permissions (shell — filled in by the Mac onboarding checklist, A8) ──

const PERMISSION_LABELS: Record<string, string> = {
  screen_recording: 'Screen Recording',
  accessibility: 'Accessibility',
  input_monitoring: 'Input Monitoring',
  microphone: 'Microphone',
}

const PERMISSION_SETTINGS_URLS: Record<string, string> = {
  screen_recording: 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture',
  accessibility: 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility',
  input_monitoring: 'x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent',
  microphone: 'x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone',
}

function AutostartRow() {
  const [autostart, setAutostartState] = useState(true)
  useEffect(() => {
    window.electronAPI?.getAutostart().then(setAutostartState)
  }, [])
  return (
    <Toggle
      checked={autostart}
      onChange={async (v) => {
        setAutostartState(v)
        await window.electronAPI?.setAutostart(v)
      }}
      label="Launch Sara at login"
    />
  )
}

function PermissionsTab() {
  const [permissions, setPermissions] = useState<Record<string, string> | null>(null)
  const isMac = window.electronAPI?.platform === 'darwin'

  useEffect(() => {
    if (!isMac) return
    window.electronAPI?.onPermissionsReport(setPermissions)
    window.electronAPI?.requestPermissionsRecheck()
  }, [isMac])

  if (!isMac) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-gray-400">No special OS permissions are required on this platform.</p>
        <AutostartRow />
        <p className="text-xs text-gray-500 pt-2 border-t border-gray-800">
          Mic device selection lands with the sidecar voice module (Workstream A6).
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <AutostartRow />
      <div className="pt-2 border-t border-gray-800" />
      {!permissions ? (
        <p className="text-sm text-gray-500 animate-pulse">Checking permissions…</p>
      ) : (
        Object.keys(PERMISSION_LABELS).map((key) => {
          const status = permissions[key] || 'unknown'
          const granted = status === 'granted'
          return (
            <div key={key} className="flex items-center justify-between bg-gray-800/60 rounded-lg px-3 py-2">
              <div className="flex items-center gap-2">
                <span>{granted ? '✅' : status === 'unknown' ? '❔' : '❌'}</span>
                <span className="text-sm text-gray-200">{PERMISSION_LABELS[key]}</span>
              </div>
              {!granted && (
                <button
                  className="text-xs text-indigo-400 hover:text-indigo-300"
                  onClick={() => window.electronAPI?.openSystemSettings(PERMISSION_SETTINGS_URLS[key])}
                >
                  Open System Settings
                </button>
              )}
            </div>
          )
        })
      )}
      <button
        onClick={() => window.electronAPI?.requestPermissionsRecheck()}
        className="w-full bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-lg px-4 py-2 text-sm transition-colors"
      >
        Re-check
      </button>
    </div>
  )
}

// ── About / Updates ────────────────────────────────────────────────────

function AboutTab() {
  return (
    <div className="space-y-3 text-sm">
      <p className="text-gray-300">Sara Desktop</p>
      <button
        onClick={() => window.electronAPI?.showContextMenu()}
        className="text-indigo-400 hover:text-indigo-300 text-xs"
      >
        Open tray menu to check for updates
      </button>
    </div>
  )
}

export default function SettingsModal({ onClose, onAuthChange }: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<TabId>('account')

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 no-drag">
      <div className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-2xl h-[520px] shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700 shrink-0">
          <h2 className="text-lg font-semibold text-white">Settings</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex flex-1 min-h-0">
          {/* Tab list */}
          <div className="w-36 border-r border-gray-800 py-2 shrink-0 overflow-y-auto">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`w-full text-left px-4 py-2 text-sm transition-colors ${
                  activeTab === tab.id ? 'bg-gray-800 text-white' : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="flex-1 p-6 overflow-y-auto">
            {activeTab === 'account' && <AccountTab onAuthChange={onAuthChange} />}
            {activeTab === 'appearance' && <AppearanceTab />}
            {activeTab === 'overlays' && <OverlaysTab />}
            {activeTab === 'privacy' && <PrivacyTab />}
            {activeTab === 'voice' && <VoiceTab />}
            {activeTab === 'permissions' && <PermissionsTab />}
            {activeTab === 'about' && <AboutTab />}
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-700 flex justify-end shrink-0">
          <button
            onClick={onClose}
            className="bg-gray-700 hover:bg-gray-600 text-white rounded-lg px-4 py-2 text-sm transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
