import { useState, useEffect, useRef, useCallback, type ReactNode } from 'react'
import {
  getCalmMode, setCalmMode, getEnhancedVisuals, setEnhancedVisuals,
  getAIProvider, setAIProvider, getAIApiKey, setAIApiKey,
  getAIBaseUrl, setAIBaseUrl, getAIModel, setAIModel, getAINotificationModel, setAINotificationModel,
  getEmbeddingBaseUrl, setEmbeddingBaseUrl, getEmbeddingModel, setEmbeddingModel,
  getEmbeddingDimension, setEmbeddingDimension
} from '../utils/prefs'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient, AISettingsUpdate, TokenStats, Device, AutonomyFlags, AutonomyRolloutSummary, CodexOAuthStatus, NotificationPrefItem, NotificationPrefsResponse } from '../api/client'
import { APP_CONFIG } from '../config'
import SchedulesSection from '../components/SchedulesSection'
import TunablesSection from '../components/TunablesSection'

interface MorningBriefSummary {
  id: string
  brief_date: string
  has_audio: boolean
  audio_duration_seconds: number | null
  generated_at: string | null
  viewed_at: string | null
}

interface MorningBriefDetail {
  id: string
  brief_date: string
  news_summary: string | null
  weather_summary: string | null
  calendar_summary: string | null
  full_text: string | null
  has_audio: boolean
  audio_duration_seconds: number | null
  recovery_text: string | null
  has_recovery_audio: boolean
  generated_at: string | null
}

const inputCls =
  'w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-teal-300/30'
const labelCls = 'mb-1.5 block text-sm text-slate-300'
const hintCls = 'mt-1 text-xs text-slate-500'
const btnSecondary =
  'rounded-xl border border-white/10 px-3.5 py-2 text-sm text-slate-300 transition-colors hover:bg-white/[0.06] hover:text-white disabled:opacity-50 disabled:cursor-not-allowed'
const btnPrimary =
  'rounded-xl bg-teal-400/90 px-3.5 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-teal-300 disabled:opacity-50 disabled:cursor-not-allowed'
const quietLinkCls = 'text-xs text-slate-500 transition-colors hover:text-teal-300'

function SectionHeading({ label, action }: { label: string; action?: ReactNode }) {
  return (
    <div className="mb-4 flex items-baseline justify-between gap-3">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</h2>
      {action}
    </div>
  )
}

function ConnectedDevices() {
  const queryClient = useQueryClient()
  const [editingDevice, setEditingDevice] = useState<string | null>(null)
  const [editName, setEditName] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['devices'],
    queryFn: () => apiClient.getDevices(),
    refetchInterval: 30000, // Poll every 30 seconds
  })

  const updateNameMutation = useMutation({
    mutationFn: ({ deviceId, name }: { deviceId: string; name: string }) =>
      apiClient.updateDeviceName(deviceId, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['devices'] })
      setEditingDevice(null)
      setEditName('')
    },
  })

  const removeDeviceMutation = useMutation({
    mutationFn: (deviceId: string) => apiClient.removeDevice(deviceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['devices'] })
    },
  })

  const startEdit = (device: Device) => {
    setEditingDevice(device.device_id)
    setEditName(device.friendly_name || device.hostname || '')
  }

  const saveEdit = (deviceId: string) => {
    if (editName.trim()) {
      updateNameMutation.mutate({ deviceId, name: editName.trim() })
    }
  }

  const getPlatformIcon = (platform: string | null) => {
    if (platform === 'darwin') {
      return (
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
          <path d="M18.71 19.5C17.88 20.74 17 21.95 15.66 21.97C14.32 22 13.89 21.18 12.37 21.18C10.84 21.18 10.37 21.95 9.1 22C7.79 22.05 6.8 20.68 5.96 19.47C4.25 17 2.94 12.45 4.7 9.39C5.57 7.87 7.13 6.91 8.82 6.88C10.1 6.86 11.32 7.75 12.11 7.75C12.89 7.75 14.37 6.68 15.92 6.84C16.57 6.87 18.39 7.1 19.56 8.82C19.47 8.88 17.39 10.1 17.41 12.63C17.44 15.65 20.06 16.66 20.09 16.67C20.06 16.74 19.67 18.11 18.71 19.5ZM13 3.5C13.73 2.67 14.94 2.04 15.94 2C16.07 3.17 15.6 4.35 14.9 5.19C14.21 6.04 13.07 6.7 11.95 6.61C11.8 5.46 12.36 4.26 13 3.5Z" />
        </svg>
      )
    }
    if (platform === 'win32') {
      return (
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
          <path d="M3 5.5L10.5 4.5V11.5H3V5.5ZM10.5 12.5V19.5L3 18.5V12.5H10.5ZM11.5 4.35L21 3V11.5H11.5V4.35ZM21 12.5V21L11.5 19.65V12.5H21Z" />
        </svg>
      )
    }
    return (
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12.504 0c-.155 0-.315.008-.48.021-4.226.333-3.105 4.807-3.17 6.298-.076 1.092-.3 1.953-1.05 3.02-.885 1.051-2.127 2.75-2.716 4.521-.278.832-.41 1.684-.287 2.489a.424.424 0 00-.11.135c-.26.268-.45.6-.663.839-.199.199-.485.267-.797.4-.313.136-.658.269-.864.68-.09.189-.136.394-.132.602 0 .199.027.4.055.536.058.399.116.728.04.97-.249.68-.28 1.145-.106 1.484.174.334.535.47.94.601.81.2 1.91.135 2.774.6.926.466 1.866.67 2.616.47.526-.116.97-.464 1.208-.946.587-.003 1.23-.269 2.26-.334.699-.058 1.574.267 2.577.2.025.134.063.198.114.333l.003.003c.391.778 1.113 1.132 1.884 1.071.771-.06 1.592-.536 2.257-1.306.631-.765 1.683-1.084 2.378-1.503.348-.199.629-.469.649-.853.023-.4-.2-.811-.714-1.376v-.097l-.003-.003c-.17-.2-.25-.535-.338-.926-.085-.401-.182-.786-.492-1.046h-.003c-.059-.054-.123-.067-.188-.135a.357.357 0 00-.19-.064c.431-1.278.264-2.55-.173-3.694-.533-1.41-1.465-2.638-2.175-3.483-.796-1.005-1.576-1.957-1.56-3.368.026-2.152.236-6.133-3.544-6.139zm.529 3.405h.013c.213 0 .396.062.584.198.19.135.33.332.438.533.105.259.158.459.166.724 0-.02.006-.04.006-.06v.105a.086.086 0 01-.004-.021l-.004-.024a1.807 1.807 0 01-.15.706.953.953 0 01-.213.335.71.71 0 00-.088-.042c-.104-.045-.198-.064-.284-.133a1.312 1.312 0 00-.22-.066c.05-.06.146-.133.183-.198.053-.128.082-.264.088-.402v-.02a1.21 1.21 0 00-.061-.4c-.045-.134-.101-.2-.183-.333-.084-.066-.167-.132-.267-.132h-.016c-.093 0-.176.03-.262.132a.8.8 0 00-.205.334 1.18 1.18 0 00-.09.4v.019c.002.089.008.179.02.267-.193-.067-.438-.135-.607-.202a1.635 1.635 0 01-.018-.2v-.02a1.772 1.772 0 01.15-.768c.082-.22.232-.406.43-.534a.985.985 0 01.594-.2zm-2.962.059h.036c.142 0 .27.048.399.135.146.129.264.288.344.465.09.199.14.4.153.667v.004c.007.134.006.2-.002.266v.08c-.03.007-.056.018-.083.024-.152.055-.274.135-.393.2.012-.09.013-.18.003-.267v-.015c-.012-.133-.04-.2-.082-.333a.613.613 0 00-.166-.267.248.248 0 00-.183-.064h-.021c-.071.006-.13.04-.186.132a.552.552 0 00-.12.27.944.944 0 00-.023.33v.015c.012.135.037.2.08.334.046.134.098.2.166.268.01.009.02.018.034.024-.07.057-.117.07-.176.136a.304.304 0 01-.131.068 2.62 2.62 0 01-.275-.402 1.772 1.772 0 01-.155-.667 1.759 1.759 0 01.08-.668 1.43 1.43 0 01.283-.535c.128-.133.26-.2.418-.2zm1.37 1.706c.332 0 .733.065 1.216.399.293.2.523.269 1.052.468h.003c.255.136.405.266.478.399v-.131a.571.571 0 01.016.47c-.123.31-.516.643-1.063.842v.002c-.268.135-.501.333-.775.465-.276.135-.588.292-1.012.267a1.139 1.139 0 01-.448-.067 3.566 3.566 0 01-.322-.198c-.195-.135-.363-.332-.612-.465v-.005h-.005c-.4-.246-.616-.512-.686-.71-.07-.268-.005-.47.193-.6.224-.135.38-.271.483-.336.104-.074.143-.102.176-.131h.002v-.003c.169-.202.436-.47.839-.601.139-.036.294-.065.466-.065zm2.8 2.142c.358 1.417 1.196 3.475 1.735 4.473.286.534.855 1.659 1.102 3.024.156-.005.33.018.513.064.646-1.671-.546-3.467-1.089-3.966-.22-.2-.232-.335-.123-.335.59.534 1.365 1.572 1.646 2.757.13.535.16 1.104.021 1.67.067.028.135.06.205.067 1.032.534 1.413.938 1.23 1.537v-.043c-.06-.003-.12 0-.18 0h-.016c.151-.467-.182-.825-1.065-1.224-.915-.4-1.646-.336-1.77.465-.008.043-.013.066-.018.135-.068.023-.139.053-.209.064-.43.268-.662.669-.793 1.187-.13.533-.17 1.156-.205 1.869v.003c-.02.334-.17.838-.319 1.35-1.5 1.072-3.58 1.538-5.348.334a2.645 2.645 0 00-.402-.533 1.45 1.45 0 00-.275-.333c.182 0 .338-.03.465-.067a.615.615 0 00.314-.334c.108-.267 0-.697-.345-1.163-.345-.467-.931-.995-1.788-1.521-.63-.4-.986-.87-1.15-1.396-.165-.534-.143-1.085-.015-1.645.245-1.07.873-2.11 1.274-2.763.107-.065.037.135-.408.974-.396.751-1.14 2.497-.122 3.854a8.123 8.123 0 01.647-2.876c.564-1.278 1.743-3.504 1.836-5.268.048.036.217.135.289.202.218.133.38.333.59.465.21.201.477.335.876.335.039.003.075.006.11.006.412 0 .73-.134.997-.268.29-.134.52-.334.74-.4h.005c.467-.135.835-.402 1.044-.7zm2.185 8.958c.037.6.343 1.245.882 1.377.588.134 1.434-.333 1.791-.765l.211-.01c.315-.007.577.01.847.268l.003.003c.208.199.305.53.391.876.085.4.154.78.409 1.066.486.527.645.906.636 1.14l.003-.007v.018l-.003-.012c-.015.262-.185.396-.498.574-.63.328-1.58.608-2.35 1.487-.247.268-.51.652-.753 1.067-.39.67-.773 1.404-1.275 1.88-.503.467-1.101.6-1.71.536-.12-.01-.24-.03-.36-.067-.24-.066-.48-.267-.728-.599l-.099-.131-.132-.136c.254-.065.535-.4.677-.669.123-.399-.001-.87-.254-1.338-.12-.224-.264-.45-.412-.64l.191.002c.476.003.91-.268 1.155-.736.246-.464.249-1.067-.038-1.532l-.106-.165-.116-.136c.233-.134.453-.3.657-.466v-.024c.224-.334.422-.8.48-1.201.18-.6.027-1.333-.182-1.936zm.854 5.894l.034.018-.003-.003-.006-.006zm-6.502 3.001c-.018.135-.035.27-.092.398-.106.264-.308.531-.615.601v.002c-.05.009-.1.014-.15.014-.163 0-.32-.053-.455-.137-.15-.085-.332-.198-.515-.267-.274-.1-.527-.164-.72-.1l-.003.003c-.028.006-.053.02-.08.028-.198.065-.372.135-.475.2-.058.035-.103.068-.134.2a.14.14 0 00-.038.067c.431.266.926.402 1.489.402.536 0 1.136-.135 1.751-.468.618-.332 1.27-.867 1.751-1.736-.17.135-.38.27-.588.4-.358.2-.771.334-1.126.467z" />
      </svg>
    )
  }

  const formatLastActivity = (dateStr: string | null): string => {
    if (!dateStr) return 'Never'
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)

    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins}m ago`
    const diffHours = Math.floor(diffMins / 60)
    if (diffHours < 24) return `${diffHours}h ago`
    const diffDays = Math.floor(diffHours / 24)
    return `${diffDays}d ago`
  }

  const devices = data?.devices || []

  return (
    <section className="mt-12">
      <SectionHeading label="Connected devices" />
      {isLoading ? (
        <p className="text-sm text-slate-500">Checking devices…</p>
      ) : error ? (
        <p className="text-sm text-slate-500">Couldn't load devices right now.</p>
      ) : devices.length === 0 ? (
        <p className="text-sm text-slate-500">No devices connected yet — download and run the desktop app to connect.</p>
      ) : (
        <div className="space-y-1">
          {devices.map((device) => (
            <div
              key={device.device_id}
              className="flex items-center justify-between rounded-lg px-2 py-2.5 transition-colors hover:bg-white/[0.04]"
            >
              <div className="flex items-center gap-4 flex-1 min-w-0">
                {/* Online status dot */}
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                  device.is_online ? 'bg-emerald-400' : 'bg-slate-600'
                }`} />

                {/* Platform icon */}
                <div className="text-slate-500 flex-shrink-0">
                  {getPlatformIcon(device.platform)}
                </div>

                {/* Device name */}
                <div className="flex-1 min-w-0">
                  {editingDevice === device.device_id ? (
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') saveEdit(device.device_id)
                          if (e.key === 'Escape') setEditingDevice(null)
                        }}
                        className="w-48 rounded-xl border border-white/10 bg-white/[0.04] px-2 py-1 text-sm text-slate-100 outline-none focus:border-teal-300/30"
                        autoFocus
                      />
                      <button
                        onClick={() => saveEdit(device.device_id)}
                        disabled={updateNameMutation.isPending}
                        className="text-xs text-teal-300 transition-colors hover:text-teal-200"
                      >
                        Save
                      </button>
                      <button
                        onClick={() => setEditingDevice(null)}
                        className={quietLinkCls}
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <>
                      <div className="truncate text-[15px] text-slate-200">
                        {device.friendly_name || device.hostname || 'Unknown Device'}
                      </div>
                      <div className="truncate text-xs text-slate-500">
                        {device.device_id.slice(0, 30)}...
                      </div>
                    </>
                  )}
                </div>

                {/* Activity */}
                <div className="text-xs text-slate-500 flex-shrink-0 hidden sm:block">
                  {device.is_online ? (
                    <span>{device.activity_level}</span>
                  ) : (
                    <span>{formatLastActivity(device.last_activity_at)}</span>
                  )}
                </div>
              </div>

              {/* Actions */}
              {editingDevice !== device.device_id && (
                <div className="flex items-center gap-3 ml-4">
                  <button
                    onClick={() => startEdit(device)}
                    className={quietLinkCls}
                    title="Edit name"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => {
                      if (confirm('Remove this device from your account?')) {
                        removeDeviceMutation.mutate(device.device_id)
                      }
                    }}
                    disabled={removeDeviceMutation.isPending}
                    className="text-xs text-slate-500 transition-colors hover:text-rose-300 disabled:opacity-50"
                    title="Remove device"
                  >
                    Remove
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function TokenUsageStats() {
  const queryClient = useQueryClient()
  const [showResetConfirm, setShowResetConfirm] = useState(false)

  const { data: tokenStats, isLoading, error } = useQuery({
    queryKey: ['token-usage', 'stats'],
    queryFn: () => apiClient.getTokenStats(),
    refetchInterval: 30000, // Refresh every 30 seconds
  })

  const resetMutation = useMutation({
    mutationFn: () => apiClient.resetTokenStats(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['token-usage', 'stats'] })
      setShowResetConfirm(false)
    },
  })

  const formatNumber = (num: number): string => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(2)}M`
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`
    return num.toString()
  }

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return 'Never'
    const date = new Date(dateStr)
    return date.toLocaleString()
  }

  if (isLoading) {
    return <p className="text-sm text-slate-500">Loading token usage…</p>
  }

  if (error) {
    return <p className="text-sm text-slate-500">Token statistics aren't available right now.</p>
  }

  return (
    <div className="space-y-4">
      {/* Stats */}
      <div className="grid grid-cols-2 gap-x-8 gap-y-5 md:grid-cols-4">
        {[
          ['Total tokens', tokenStats?.total_tokens || 0],
          ['Prompt', tokenStats?.total_prompt_tokens || 0],
          ['Completion', tokenStats?.total_completion_tokens || 0],
          ['Requests', tokenStats?.total_requests || 0],
        ].map(([label, value]) => (
          <div key={label as string}>
            <div className="text-2xl font-semibold tabular-nums text-white">{formatNumber(value as number)}</div>
            <div className="mt-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
              {label as string}
            </div>
          </div>
        ))}
      </div>

      {/* Meta Info & Reset */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="text-xs text-slate-500">
          {tokenStats?.last_reset_at ? (
            <span>Tracking since {formatDate(tokenStats.last_reset_at)}</span>
          ) : (
            <span>Tracking since start</span>
          )}
          {tokenStats?.updated_at && (
            <span className="ml-3">Last update {formatDate(tokenStats.updated_at)}</span>
          )}
        </div>

        {!showResetConfirm ? (
          <button
            onClick={() => setShowResetConfirm(true)}
            className={quietLinkCls}
          >
            Reset counter
          </button>
        ) : (
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-400">Are you sure?</span>
            <button
              onClick={() => resetMutation.mutate()}
              disabled={resetMutation.isPending}
              className="text-xs text-rose-300 transition-colors hover:text-rose-200 disabled:opacity-50"
            >
              {resetMutation.isPending ? 'Resetting…' : 'Yes, reset'}
            </button>
            <button
              onClick={() => setShowResetConfirm(false)}
              className={quietLinkCls}
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

interface DownloadInfo {
  filename: string
  platform: string
  arch: string
  type: string
  agent_type: 'desktop' | 'headless'
  size_bytes: number
  size_mb: number
  modified: string
}

function DesktopAppDownloads() {
  const [showInstallNotes, setShowInstallNotes] = useState(false)
  const { data, isLoading, error } = useQuery({
    queryKey: ['downloads'],
    queryFn: async () => {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/downloads`, {
        credentials: 'include',
      })
      if (!response.ok) throw new Error('Failed to fetch downloads')
      return response.json() as Promise<{ downloads: DownloadInfo[]; version: string }>
    },
  })

  const handleDownload = (filename: string) => {
    window.open(`${APP_CONFIG.apiUrl}/api/downloads/${filename}`, '_blank')
  }

  const getPlatformIcon = (platform: string) => {
    if (platform === 'Windows') {
      return (
        <svg className="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
          <path d="M3 5.5L10.5 4.5V11.5H3V5.5ZM10.5 12.5V19.5L3 18.5V12.5H10.5ZM11.5 4.35L21 3V11.5H11.5V4.35ZM21 12.5V21L11.5 19.65V12.5H21Z" />
        </svg>
      )
    }
    if (platform === 'macOS') {
      return (
        <svg className="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
          <path d="M18.71 19.5C17.88 20.74 17 21.95 15.66 21.97C14.32 22 13.89 21.18 12.37 21.18C10.84 21.18 10.37 21.95 9.1 22C7.79 22.05 6.8 20.68 5.96 19.47C4.25 17 2.94 12.45 4.7 9.39C5.57 7.87 7.13 6.91 8.82 6.88C10.1 6.86 11.32 7.75 12.11 7.75C12.89 7.75 14.37 6.68 15.92 6.84C16.57 6.87 18.39 7.1 19.56 8.82C19.47 8.88 17.39 10.1 17.41 12.63C17.44 15.65 20.06 16.66 20.09 16.67C20.06 16.74 19.67 18.11 18.71 19.5ZM13 3.5C13.73 2.67 14.94 2.04 15.94 2C16.07 3.17 15.6 4.35 14.9 5.19C14.21 6.04 13.07 6.7 11.95 6.61C11.8 5.46 12.36 4.26 13 3.5Z" />
        </svg>
      )
    }
    if (platform === 'Linux') {
      return (
        <svg className="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12.504 0c-.155 0-.315.008-.48.021-4.226.333-3.105 4.807-3.17 6.298-.076 1.092-.3 1.953-1.05 3.02-.885 1.051-2.127 2.75-2.716 4.521-.278.832-.41 1.684-.287 2.489a.424.424 0 00-.11.135c-.26.268-.45.6-.663.839-.199.199-.485.267-.797.4-.313.136-.658.269-.864.68-.09.189-.136.394-.132.602 0 .199.027.4.055.536.058.399.116.728.04.97-.249.68-.28 1.145-.106 1.484.174.334.535.47.94.601.81.2 1.91.135 2.774.6.926.466 1.866.67 2.616.47.526-.116.97-.464 1.208-.946.587-.003 1.23-.269 2.26-.334.699-.058 1.574.267 2.577.2.025.134.063.198.114.333l.003.003c.391.778 1.113 1.132 1.884 1.071.771-.06 1.592-.536 2.257-1.306.631-.765 1.683-1.084 2.378-1.503.348-.199.629-.469.649-.853.023-.4-.2-.811-.714-1.376v-.097l-.003-.003c-.17-.2-.25-.535-.338-.926-.085-.401-.182-.786-.492-1.046h-.003c-.059-.054-.123-.067-.188-.135a.357.357 0 00-.19-.064c.431-1.278.264-2.55-.173-3.694-.533-1.41-1.465-2.638-2.175-3.483-.796-1.005-1.576-1.957-1.56-3.368.026-2.152.236-6.133-3.544-6.139zm.529 3.405h.013c.213 0 .396.062.584.198.19.135.33.332.438.533.105.259.158.459.166.724 0-.02.006-.04.006-.06v.105a.086.086 0 01-.004-.021l-.004-.024a1.807 1.807 0 01-.15.706.953.953 0 01-.213.335.71.71 0 00-.088-.042c-.104-.045-.198-.064-.284-.133a1.312 1.312 0 00-.22-.066c.05-.06.146-.133.183-.198.053-.128.082-.264.088-.402v-.02a1.21 1.21 0 00-.061-.4c-.045-.134-.101-.2-.183-.333-.084-.066-.167-.132-.267-.132h-.016c-.093 0-.176.03-.262.132a.8.8 0 00-.205.334 1.18 1.18 0 00-.09.4v.019c.002.089.008.179.02.267-.193-.067-.438-.135-.607-.202a1.635 1.635 0 01-.018-.2v-.02a1.772 1.772 0 01.15-.768c.082-.22.232-.406.43-.534a.985.985 0 01.594-.2zm-2.962.059h.036c.142 0 .27.048.399.135.146.129.264.288.344.465.09.199.14.4.153.667v.004c.007.134.006.2-.002.266v.08c-.03.007-.056.018-.083.024-.152.055-.274.135-.393.2.012-.09.013-.18.003-.267v-.015c-.012-.133-.04-.2-.082-.333a.613.613 0 00-.166-.267.248.248 0 00-.183-.064h-.021c-.071.006-.13.04-.186.132a.552.552 0 00-.12.27.944.944 0 00-.023.33v.015c.012.135.037.2.08.334.046.134.098.2.166.268.01.009.02.018.034.024-.07.057-.117.07-.176.136a.304.304 0 01-.131.068 2.62 2.62 0 01-.275-.402 1.772 1.772 0 01-.155-.667 1.759 1.759 0 01.08-.668 1.43 1.43 0 01.283-.535c.128-.133.26-.2.418-.2zm1.37 1.706c.332 0 .733.065 1.216.399.293.2.523.269 1.052.468h.003c.255.136.405.266.478.399v-.131a.571.571 0 01.016.47c-.123.31-.516.643-1.063.842v.002c-.268.135-.501.333-.775.465-.276.135-.588.292-1.012.267a1.139 1.139 0 01-.448-.067 3.566 3.566 0 01-.322-.198c-.195-.135-.363-.332-.612-.465v-.005h-.005c-.4-.246-.616-.512-.686-.71-.07-.268-.005-.47.193-.6.224-.135.38-.271.483-.336.104-.074.143-.102.176-.131h.002v-.003c.169-.202.436-.47.839-.601.139-.036.294-.065.466-.065zm2.8 2.142c.358 1.417 1.196 3.475 1.735 4.473.286.534.855 1.659 1.102 3.024.156-.005.33.018.513.064.646-1.671-.546-3.467-1.089-3.966-.22-.2-.232-.335-.123-.335.59.534 1.365 1.572 1.646 2.757.13.535.16 1.104.021 1.67.067.028.135.06.205.067 1.032.534 1.413.938 1.23 1.537v-.043c-.06-.003-.12 0-.18 0h-.016c.151-.467-.182-.825-1.065-1.224-.915-.4-1.646-.336-1.77.465-.008.043-.013.066-.018.135-.068.023-.139.053-.209.064-.43.268-.662.669-.793 1.187-.13.533-.17 1.156-.205 1.869v.003c-.02.334-.17.838-.319 1.35-1.5 1.072-3.58 1.538-5.348.334a2.645 2.645 0 00-.402-.533 1.45 1.45 0 00-.275-.333c.182 0 .338-.03.465-.067a.615.615 0 00.314-.334c.108-.267 0-.697-.345-1.163-.345-.467-.931-.995-1.788-1.521-.63-.4-.986-.87-1.15-1.396-.165-.534-.143-1.085-.015-1.645.245-1.07.873-2.11 1.274-2.763.107-.065.037.135-.408.974-.396.751-1.14 2.497-.122 3.854a8.123 8.123 0 01.647-2.876c.564-1.278 1.743-3.504 1.836-5.268.048.036.217.135.289.202.218.133.38.333.59.465.21.201.477.335.876.335.039.003.075.006.11.006.412 0 .73-.134.997-.268.29-.134.52-.334.74-.4h.005c.467-.135.835-.402 1.044-.7zm2.185 8.958c.037.6.343 1.245.882 1.377.588.134 1.434-.333 1.791-.765l.211-.01c.315-.007.577.01.847.268l.003.003c.208.199.305.53.391.876.085.4.154.78.409 1.066.486.527.645.906.636 1.14l.003-.007v.018l-.003-.012c-.015.262-.185.396-.498.574-.63.328-1.58.608-2.35 1.487-.247.268-.51.652-.753 1.067-.39.67-.773 1.404-1.275 1.88-.503.467-1.101.6-1.71.536-.12-.01-.24-.03-.36-.067-.24-.066-.48-.267-.728-.599l-.099-.131-.132-.136c.254-.065.535-.4.677-.669.123-.399-.001-.87-.254-1.338-.12-.224-.264-.45-.412-.64l.191.002c.476.003.91-.268 1.155-.736.246-.464.249-1.067-.038-1.532l-.106-.165-.116-.136c.233-.134.453-.3.657-.466v-.024c.224-.334.422-.8.48-1.201.18-.6.027-1.333-.182-1.936zm.854 5.894l.034.018-.003-.003-.006-.006zm-6.502 3.001c-.018.135-.035.27-.092.398-.106.264-.308.531-.615.601v.002c-.05.009-.1.014-.15.014-.163 0-.32-.053-.455-.137-.15-.085-.332-.198-.515-.267-.274-.1-.527-.164-.72-.1l-.003.003c-.028.006-.053.02-.08.028-.198.065-.372.135-.475.2-.058.035-.103.068-.134.2a.14.14 0 00-.038.067c.431.266.926.402 1.489.402.536 0 1.136-.135 1.751-.468.618-.332 1.27-.867 1.751-1.736-.17.135-.38.27-.588.4-.358.2-.771.334-1.126.467z" />
        </svg>
      )
    }
    return (
      <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    )
  }

  const getArchLabel = (arch: string) => {
    if (arch === 'arm64') return 'Apple Silicon'
    if (arch === 'x64') return 'Intel/AMD 64-bit'
    return arch
  }

  if (isLoading) {
    return (
      <section className="mt-12">
        <SectionHeading label="Desktop app" />
        <p className="text-sm text-slate-500">Loading downloads…</p>
      </section>
    )
  }

  if (error || !data?.downloads?.length) {
    return (
      <section className="mt-12">
        <SectionHeading label="Desktop app" />
        <p className="text-sm text-slate-500">
          {error ? "Couldn't load downloads right now." : 'No downloads available yet.'}
        </p>
      </section>
    )
  }

  // Separate desktop and headless downloads
  const desktopDownloads = data.downloads.filter(d => d.agent_type !== 'headless')
  const headlessDownloads = data.downloads.filter(d => d.agent_type === 'headless')

  // Group desktop downloads by platform
  const byPlatform: Record<string, DownloadInfo[]> = {}
  desktopDownloads.forEach((d) => {
    if (!byPlatform[d.platform]) byPlatform[d.platform] = []
    byPlatform[d.platform].push(d)
  })

  return (
    <section className="mt-12">
      <SectionHeading
        label="Desktop app"
        action={<span className="text-xs text-slate-500">v{data.version}</span>}
      />

      <div className="space-y-6">
        {Object.entries(byPlatform).map(([platform, downloads]) => (
          <div key={platform}>
            <div className="mb-1 flex items-center gap-2 px-2 text-sm text-slate-300">
              <span className="text-slate-500">{getPlatformIcon(platform)}</span>
              {platform}
            </div>
            <div className="space-y-1">
              {downloads.map((download) => (
                <div
                  key={download.filename}
                  className="flex items-center justify-between rounded-lg px-2 py-2 transition-colors hover:bg-white/[0.04]"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-[15px] text-slate-200">
                      {getArchLabel(download.arch)}
                    </div>
                    <div className="text-xs text-slate-500">
                      {download.filename} ({download.size_mb} MB)
                    </div>
                  </div>
                  <button
                    onClick={() => handleDownload(download.filename)}
                    className={`ml-4 flex-shrink-0 ${btnSecondary}`}
                  >
                    Download
                  </button>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Linux Headless Agent Section */}
      {headlessDownloads.length > 0 && (
        <div className="mt-6">
          <div className="mb-1 px-2 text-sm text-slate-300">Linux headless agent</div>
          <p className="px-2 text-xs text-slate-500">
            For servers without a GUI — runs as a systemd service with system metrics, remote commands, and auto-start.
          </p>

          <div className="mt-1 space-y-1">
            {headlessDownloads.map((download) => (
              <div
                key={download.filename}
                className="flex items-center justify-between rounded-lg px-2 py-2 transition-colors hover:bg-white/[0.04]"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-[15px] text-slate-200">
                    Headless Agent (x64)
                  </div>
                  <div className="text-xs text-slate-500">
                    {download.filename} ({download.size_mb} MB)
                  </div>
                </div>
                <button
                  onClick={() => handleDownload(download.filename)}
                  className={`ml-4 flex-shrink-0 ${btnSecondary}`}
                >
                  Download
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Install notes (demoted behind an expander) */}
      <div className="mt-4 px-2">
        <button
          type="button"
          onClick={() => setShowInstallNotes((v) => !v)}
          className="text-xs text-slate-500 transition-colors hover:text-slate-300"
        >
          {showInstallNotes ? '▴ hide install notes' : '▾ install notes'}
        </button>
        {showInstallNotes && (
          <div className="mt-3 space-y-4 border-l border-white/10 pl-4 text-xs text-slate-400">
            <div>
              <p className="font-medium text-slate-300">Desktop app installation</p>
              <ul className="mt-1 space-y-1">
                <li><strong className="text-slate-300">Windows:</strong> Extract the archive and run Sara.exe</li>
                <li><strong className="text-slate-300">macOS:</strong> Extract the zip and move Sara.app to Applications</li>
              </ul>
            </div>

            {headlessDownloads.length > 0 && (
              <div>
                <p className="font-medium text-slate-300">Headless agent quick install</p>
                <code className="mt-1 block break-all rounded bg-white/[0.04] px-2 py-1.5 font-mono text-[10px] text-slate-300">
                  curl -L {APP_CONFIG.apiUrl}/api/downloads/sara-agent-linux.tar.gz | tar xz && cd sara-agent && sudo ./install.sh
                </code>
              </div>
            )}

            <div>
              <p className="font-medium text-slate-300">Activity monitoring setup (optional)</p>
              <p className="mt-1">
                For activity tracking and screenshot features, install Python 3 and run:
              </p>
              <div className="mt-2 space-y-2">
                <div>
                  <p className="text-slate-300">Windows (PowerShell):</p>
                  <code className="mt-1 block break-all rounded bg-white/[0.04] px-2 py-1 font-mono text-[10px] text-slate-300">
                    pip install pynput mss Pillow websockets httpx numpy
                  </code>
                </div>
                <div>
                  <p className="text-slate-300">macOS (Terminal):</p>
                  <code className="mt-1 block break-all rounded bg-white/[0.04] px-2 py-1 font-mono text-[10px] text-slate-300">
                    pip3 install pynput mss Pillow websockets httpx numpy
                  </code>
                </div>
              </div>
              <p className="mt-2">
                Download Python from <a href="https://python.org/downloads" target="_blank" rel="noopener noreferrer" className="underline transition-colors hover:text-teal-300">python.org</a>
              </p>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}

function SaraBriefArchive() {
  const [selectedBriefDate, setSelectedBriefDate] = useState<string | null>(null)

  const {
    data: briefs = [],
    isLoading: briefsLoading,
    error: briefsError,
    refetch: refetchBriefs,
  } = useQuery<MorningBriefSummary[]>({
    queryKey: ['morning-brief', 'history', 21],
    queryFn: async () => {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/morning-brief/history?limit=21`, {
        credentials: 'include',
      })
      if (!response.ok) throw new Error('Failed to fetch brief history')
      const data = await response.json()
      return Array.isArray(data) ? data : []
    },
    refetchInterval: 60000,
  })

  useEffect(() => {
    if (briefs.length === 0) {
      setSelectedBriefDate(null)
      return
    }

    const selectedStillExists = selectedBriefDate
      ? briefs.some((brief) => brief.brief_date === selectedBriefDate)
      : false

    if (!selectedStillExists) {
      setSelectedBriefDate(briefs[0].brief_date)
    }
  }, [briefs, selectedBriefDate])

  const {
    data: selectedBrief,
    isLoading: briefDetailLoading,
    error: briefDetailError,
  } = useQuery<MorningBriefDetail>({
    queryKey: ['morning-brief', 'detail', selectedBriefDate],
    enabled: !!selectedBriefDate,
    queryFn: async () => {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/morning-brief/${selectedBriefDate}?include_recovery=false`,
        { credentials: 'include' }
      )
      if (!response.ok) throw new Error('Failed to fetch brief detail')
      return await response.json()
    },
  })

  const formatDate = (dateStr: string) => {
    const date = new Date(`${dateStr}T12:00:00`)
    const today = new Date()
    const yesterday = new Date(today)
    yesterday.setDate(yesterday.getDate() - 1)

    if (dateStr === today.toISOString().split('T')[0]) return 'Today'
    if (dateStr === yesterday.toISOString().split('T')[0]) return 'Yesterday'

    return date.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    })
  }

  return (
    <section className="mt-12">
      <SectionHeading
        label="Brief archive"
        action={
          <button type="button" onClick={() => refetchBriefs()} className={quietLinkCls}>
            Refresh
          </button>
        }
      />

      {briefsLoading ? (
        <p className="text-sm text-slate-500">Loading brief archive…</p>
      ) : briefsError ? (
        <p className="text-sm text-slate-500">Unable to load briefs right now.</p>
      ) : briefs.length === 0 ? (
        <p className="text-sm text-slate-500">No briefs generated yet.</p>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-1">
            <div className="max-h-72 space-y-0.5 overflow-y-auto pr-1">
              {briefs.map((brief) => (
                <button
                  key={brief.id}
                  type="button"
                  onClick={() => setSelectedBriefDate(brief.brief_date)}
                  className={`w-full rounded-lg px-2 py-2 text-left transition-colors ${
                    selectedBriefDate === brief.brief_date ? 'bg-white/[0.06]' : 'hover:bg-white/[0.04]'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={`text-sm ${selectedBriefDate === brief.brief_date ? 'text-white' : 'text-slate-300'}`}>
                      {formatDate(brief.brief_date)}
                    </span>
                    {brief.has_audio && (
                      <span className="rounded border border-white/10 px-1.5 py-0.5 text-[10px] text-slate-400">
                        Audio
                      </span>
                    )}
                  </div>
                  {brief.generated_at && (
                    <p className="mt-0.5 text-xs text-slate-500">
                      {new Date(brief.generated_at).toLocaleTimeString('en-US', {
                        hour: 'numeric',
                        minute: '2-digit',
                      })}
                    </p>
                  )}
                </button>
              ))}
            </div>
          </div>

          <div className="lg:col-span-2 lg:border-l lg:border-white/10 lg:pl-6">
            {briefDetailLoading ? (
              <p className="text-sm text-slate-500">Loading brief…</p>
            ) : briefDetailError ? (
              <p className="text-sm text-slate-500">Unable to load this brief.</p>
            ) : selectedBrief ? (
              <div>
                <div className="mb-3 flex items-baseline justify-between gap-3">
                  <h4 className="text-[15px] text-slate-200">{formatDate(selectedBrief.brief_date)} brief</h4>
                  {selectedBrief.generated_at && (
                    <span className="text-xs text-slate-500">
                      Generated {new Date(selectedBrief.generated_at).toLocaleString('en-US')}
                    </span>
                  )}
                </div>
                <div className="max-h-80 overflow-y-auto pr-2">
                  <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-300">
                    {selectedBrief.full_text || 'No full brief text was saved for this entry.'}
                  </p>
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-500">Select a brief to view details.</p>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

// Provider configuration presets
const PROVIDER_PRESETS = {
  local: {
    openai_base_url: 'http://100.104.68.115:11434/v1',
    openai_model: 'gpt-oss:20b',
    embedding_base_url: 'http://100.104.68.115:11434',
    embedding_model: 'bge-m3',
  },
  gemini: {
    openai_base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/',
    openai_model: 'gemini-3-flash-preview',
    embedding_base_url: 'http://10.185.1.8:11434',
    embedding_model: 'bge-m3',
  },
  openai: {
    openai_base_url: 'https://api.openai.com/v1',
    openai_model: 'gpt-4o',
    embedding_base_url: 'https://api.openai.com/v1',
    embedding_model: 'text-embedding-3-large',
  },
  codex: {
    openai_base_url: 'https://chatgpt.com/backend-api',
    openai_model: 'gpt-5.3-codex',
    embedding_base_url: 'http://100.104.68.115:11434',
    embedding_model: 'bge-m3',
  },
  claude: {
    openai_base_url: 'https://api.anthropic.com/v1',
    openai_model: 'claude-sonnet-4-6',
    embedding_base_url: 'http://100.104.68.115:11434',
    embedding_model: 'bge-m3',
  },
  custom: {} // Keep current values
} as const

// Claude model options for the dropdown
const CLAUDE_MODELS = [
  { value: 'claude-opus-4-6', label: 'Claude Opus 4.6' },
  { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
  { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5' },
] as const

type ProviderType = keyof typeof PROVIDER_PRESETS


export default function Settings() {
  const [aiProvider, setAiProviderState] = useState<ProviderType>(getAIProvider() as ProviderType || 'local')
  const [formData, setFormData] = useState<AISettingsUpdate>({
    ai_provider: getAIProvider(),
    openai_api_key: getAIApiKey(),
    openai_base_url: getAIBaseUrl(),
    openai_model: getAIModel(),
    openai_notification_model: getAINotificationModel(),
    embedding_base_url: getEmbeddingBaseUrl(),
    embedding_model: getEmbeddingModel(),
    embedding_dimension: getEmbeddingDimension(),
    // Background processing defaults
    bg_llm_primary_url: 'http://100.104.68.115:11434/v1',
    bg_llm_primary_model: 'gpt-oss:20b',
    bg_llm_fallback_url: 'http://100.104.68.115:11434/v1',
    bg_llm_fallback_model: 'gpt-oss:20b',
  })
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [vmTestResult, setVmTestResult] = useState<{ status: string; host: string } | null>(null)
  const [vmTestLoading, setVmTestLoading] = useState(false)
  const queryClient = useQueryClient()

  // Fetch current AI settings
  const { data: settings, isLoading } = useQuery({
    queryKey: ['settings', 'ai'],
    queryFn: () => apiClient.getAISettings(),
  })

  const {
    data: autonomyFlags,
    isLoading: autonomyFlagsLoading,
    error: autonomyFlagsError,
  } = useQuery<AutonomyFlags>({
    queryKey: ['settings', 'autonomy-flags'],
    queryFn: () => apiClient.getAutonomyFlags(),
    refetchInterval: 60000,
  })

  const {
    data: rolloutSummary,
    isLoading: rolloutSummaryLoading,
    error: rolloutSummaryError,
  } = useQuery<AutonomyRolloutSummary>({
    queryKey: ['autonomy', 'rollout-summary', 24],
    queryFn: () => apiClient.getAutonomyRolloutSummary(24),
    refetchInterval: 60000,
  })

  const {
    data: codexOAuthStatus,
    isLoading: codexOAuthLoading,
    isFetching: codexOAuthFetching,
    refetch: refetchCodexOAuthStatus,
  } = useQuery<CodexOAuthStatus>({
    queryKey: ['settings', 'codex-oauth'],
    queryFn: () => apiClient.getCodexOAuthStatus(),
    refetchInterval: 60000,
  })

  // Notification preferences
  const {
    data: notifPrefsData,
    isLoading: notifPrefsLoading,
  } = useQuery<NotificationPrefsResponse>({
    queryKey: ['settings', 'notification-preferences'],
    queryFn: () => apiClient.getNotificationPreferences(),
  })

  const updateNotifPrefsMutation = useMutation({
    mutationFn: (prefs: NotificationPrefItem[]) => apiClient.updateNotificationPreferences(prefs),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'notification-preferences'] })
    },
  })

  // Update settings mutation
  const updateSettingsMutation = useMutation({
    mutationFn: (data: AISettingsUpdate) => apiClient.updateAISettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'ai'] })
      setTestResult({ success: true, message: 'Settings updated successfully!' })
      setTimeout(() => setTestResult(null), 3000)
    },
    onError: (error: any) => {
      setTestResult({ success: false, message: error.response?.data?.detail || 'Failed to update settings' })
      setTimeout(() => setTestResult(null), 5000)
    },
  })

  // Test settings mutation
  const testSettingsMutation = useMutation({
    mutationFn: () => apiClient.testAISettings(),
    onSuccess: () => {
      setTestResult({ success: true, message: 'Connection test successful!' })
      setTimeout(() => setTestResult(null), 3000)
    },
    onError: (error: any) => {
      setTestResult({ success: false, message: error.response?.data?.detail || 'Connection test failed' })
      setTimeout(() => setTestResult(null), 5000)
    },
  })

  const startCodexOAuthMutation = useMutation({
    mutationFn: () => apiClient.startCodexOAuth(`${window.location.origin}/settings`),
    onSuccess: async (result) => {
      const manualFlow = !!result.requires_manual_code || /localhost:1455|127\.0\.0\.1:1455/.test(result.redirect_uri || '')
      if (!manualFlow) {
        window.location.href = result.auth_url
        return
      }

      window.open(result.auth_url, '_blank', 'noopener,noreferrer')
      const pastedUrl = window.prompt(
        'After finishing ChatGPT sign-in, copy the full final URL from the browser address bar (it starts with http://localhost:1455/auth/callback...) and paste it here:'
      )
      if (!pastedUrl) {
        setTestResult({ success: false, message: 'OAuth not completed: no callback URL pasted.' })
        setTimeout(() => setTestResult(null), 5000)
        return
      }

      try {
        await apiClient.completeCodexOAuth({ redirect_url: pastedUrl.trim() })
        queryClient.invalidateQueries({ queryKey: ['settings', 'codex-oauth'] })
        queryClient.invalidateQueries({ queryKey: ['settings', 'ai'] })
        setAiProviderState('codex')
        setAIProvider('codex')
        setTestResult({ success: true, message: 'Codex OAuth connected successfully' })
        setTimeout(() => setTestResult(null), 5000)
      } catch (error: any) {
        setTestResult({ success: false, message: error.response?.data?.detail || 'Failed to complete Codex OAuth' })
        setTimeout(() => setTestResult(null), 5000)
      }
    },
    onError: (error: any) => {
      setTestResult({ success: false, message: error.response?.data?.detail || 'Failed to start Codex OAuth' })
      setTimeout(() => setTestResult(null), 5000)
    },
  })

  const disconnectCodexOAuthMutation = useMutation({
    mutationFn: () => apiClient.disconnectCodexOAuth(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'codex-oauth'] })
      queryClient.invalidateQueries({ queryKey: ['settings', 'ai'] })
      setTestResult({ success: true, message: 'Codex OAuth disconnected' })
      setTimeout(() => setTestResult(null), 3000)
    },
    onError: (error: any) => {
      setTestResult({ success: false, message: error.response?.data?.detail || 'Failed to disconnect Codex OAuth' })
      setTimeout(() => setTestResult(null), 5000)
    },
  })

  // Initialize form data when settings load, preferring localStorage values
  useEffect(() => {
    if (settings) {
      const provider = getAIProvider() || settings.ai_provider || 'local'
      setAiProviderState(provider as ProviderType)
      setFormData({
        // Use localStorage values if available, otherwise fall back to server settings
        ai_provider: provider,
        openai_api_key: getAIApiKey() || settings.openai_api_key || '',
        openai_base_url: getAIBaseUrl() || settings.openai_base_url,
        openai_model: getAIModel() || settings.openai_model,
        openai_notification_model: getAINotificationModel() || settings.openai_notification_model,
        embedding_base_url: getEmbeddingBaseUrl() || settings.embedding_base_url,
        embedding_model: getEmbeddingModel() || settings.embedding_model,
        embedding_dimension: getEmbeddingDimension() || settings.embedding_dimension,
        // Background processing settings
        bg_llm_primary_url: settings.bg_llm_primary_url || 'http://100.104.68.115:11434/v1',
        bg_llm_primary_model: settings.bg_llm_primary_model || 'gpt-oss:20b',
        bg_llm_fallback_url: settings.bg_llm_fallback_url || 'http://100.104.68.115:11434/v1',
        bg_llm_fallback_model: settings.bg_llm_fallback_model || 'gpt-oss:20b',
        // VM sandbox settings
        vm_sandbox_host: settings.vm_sandbox_host || '10.185.1.176',
        vm_sandbox_username: settings.vm_sandbox_username || 'sara',
        vm_sandbox_ssh_key_path: settings.vm_sandbox_ssh_key_path || '~/.ssh/sara_agent',
      })
    }
  }, [settings])

  useEffect(() => {
    const url = new URL(window.location.href)
    const oauthStatus = url.searchParams.get('codex_oauth')
    if (!oauthStatus) return

    const reason = url.searchParams.get('reason')
    if (oauthStatus === 'success') {
      setTestResult({ success: true, message: 'Codex OAuth connected successfully' })
      queryClient.invalidateQueries({ queryKey: ['settings', 'codex-oauth'] })
      queryClient.invalidateQueries({ queryKey: ['settings', 'ai'] })
      setAiProviderState('codex')
      setAIProvider('codex')
    } else {
      setTestResult({ success: false, message: `Codex OAuth failed${reason ? `: ${reason}` : ''}` })
    }

    setTimeout(() => setTestResult(null), 5000)
    url.searchParams.delete('codex_oauth')
    url.searchParams.delete('reason')
    window.history.replaceState({}, document.title, url.toString())
  }, [queryClient])

  const handleProviderChange = (provider: ProviderType) => {
    // Save current API key to provider-specific storage before switching
    const currentProvider = aiProvider
    if (formData.openai_api_key && formData.openai_api_key !== '***') {
      localStorage.setItem(`sara_${currentProvider}_api_key`, formData.openai_api_key)
    }

    setAiProviderState(provider)
    setAIProvider(provider)

    if (provider !== 'custom') {
      // Auto-fill form with provider presets
      const preset = PROVIDER_PRESETS[provider]

      // Load provider-specific API key from localStorage
      const savedApiKey = provider === 'codex'
        ? ''
        : (localStorage.getItem(`sara_${provider}_api_key`) || '')

      const updated = {
        ...formData,
        ai_provider: provider,
        openai_api_key: savedApiKey,
        ...preset
      }
      setFormData(updated)

      // Save preset values to localStorage
      if (preset.openai_base_url) setAIBaseUrl(preset.openai_base_url)
      if (preset.openai_model) setAIModel(preset.openai_model)
      if (preset.embedding_base_url) setEmbeddingBaseUrl(preset.embedding_base_url)
      if (preset.embedding_model) setEmbeddingModel(preset.embedding_model)
      if (savedApiKey) setAIApiKey(savedApiKey)
    } else {
      // Just update provider, keep existing values
      setFormData(prev => ({ ...prev, ai_provider: provider }))
    }
  }

  const handleInputChange = (field: keyof AISettingsUpdate, value: string | number) => {
    setFormData(prev => ({
      ...prev,
      [field]: value
    }))

    // Save to localStorage immediately for persistence
    switch (field) {
      case 'ai_provider':
        setAIProvider(value as string)
        break
      case 'openai_api_key':
        setAIApiKey(value as string)
        // Also save to provider-specific storage
        if (value && value !== '***') {
          localStorage.setItem(`sara_${aiProvider}_api_key`, value as string)
        }
        break
      case 'openai_base_url':
        setAIBaseUrl(value as string)
        break
      case 'openai_model':
        setAIModel(value as string)
        break
      case 'openai_notification_model':
        setAINotificationModel(value as string)
        break
      case 'embedding_base_url':
        setEmbeddingBaseUrl(value as string)
        break
      case 'embedding_model':
        setEmbeddingModel(value as string)
        break
      case 'embedding_dimension':
        setEmbeddingDimension(value as number)
        break
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    // Remove empty-string fields so we don't overwrite with blanks
    // Also skip masked API key values (***) to avoid overwriting the real key
    const cleaned: AISettingsUpdate = {}
    Object.entries(formData).forEach(([k, v]) => {
      if (v !== '' && v !== undefined && v !== null) {
        // Don't send masked API key - would overwrite the real one
        if (k === 'openai_api_key' && (v === '***' || String(v).startsWith('***'))) {
          return
        }
        // @ts-ignore - dynamic assembly of payload
        cleaned[k] = v
      }
    })
    updateSettingsMutation.mutate(cleaned)
  }

  const handleTestConnection = () => {
    testSettingsMutation.mutate()
  }

  const handleConnectCodexOAuth = () => {
    startCodexOAuthMutation.mutate()
  }

  const handleDisconnectCodexOAuth = () => {
    disconnectCodexOAuthMutation.mutate()
  }

  const handleRefreshCodexOAuthStatus = async () => {
    try {
      await refetchCodexOAuthStatus()
      setTestResult({ success: true, message: 'Codex OAuth status refreshed' })
      setTimeout(() => setTestResult(null), 2500)
    } catch (error: any) {
      setTestResult({ success: false, message: error?.response?.data?.detail || 'Failed to refresh Codex OAuth status' })
      setTimeout(() => setTestResult(null), 5000)
    }
  }

  const handleReset = () => {
    // Reset to localStorage values (or defaults if none saved)
    const provider = getAIProvider() as ProviderType || 'local'
    setAiProviderState(provider)
    const resetData = {
      ai_provider: provider,
      openai_api_key: getAIApiKey(),
      openai_base_url: getAIBaseUrl(),
      openai_model: getAIModel(),
      openai_notification_model: getAINotificationModel(),
      embedding_base_url: getEmbeddingBaseUrl(),
      embedding_model: getEmbeddingModel(),
      embedding_dimension: getEmbeddingDimension(),
    }
    setFormData(resetData)
  }

  const pct = (value: number) => `${(value * 100).toFixed(1)}%`
  const providerLabels: Record<ProviderType, string> = {
    local: 'Local runtime',
    gemini: 'Gemini',
    openai: 'OpenAI',
    codex: 'ChatGPT OAuth',
    claude: 'Claude',
    custom: 'Custom',
  }
  const enabledNotificationCount = notifPrefsData?.preferences.filter((pref) => pref.enabled).length ?? 0
  const autonomyEnabledCount = autonomyFlags
    ? [
        autonomyFlags.autonomy_traces_enabled,
        autonomyFlags.autonomy_structured_plan,
        autonomyFlags.autonomy_policy_engine,
        autonomyFlags.autonomy_attention_enabled,
        autonomyFlags.autonomy_missions_enabled,
        autonomyFlags.autonomy_policy_candidates_enabled,
      ].filter(Boolean).length
    : 0
  if (isLoading) {
    return (
      <div className="flex-1 px-4 py-8 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-5xl">
          <p className="text-sm text-slate-500">Loading settings…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 px-4 pb-12 pt-4 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-5xl">
        {/* Header — one slim row */}
        <div className="flex h-12 items-center gap-3">
          <h1 className="font-display text-xl font-semibold text-white">Settings</h1>
          <span className="text-sm text-slate-500">· {providerLabels[aiProvider] || 'Unassigned'}</span>
        </div>

        {/* Scheduled Jobs (DB-backed Celery beat) */}
        <section className="mt-8">
          <SchedulesSection />
        </section>

        {/* Behavior Tunables (cooldowns, deliberation thresholds, brief tone) */}
        <section className="mt-12">
          <TunablesSection />
        </section>

        {/* Autonomy Feature Flag Status */}
        <section className="mt-12">
          <SectionHeading
            label="Autonomy gates"
            action={
              !autonomyFlagsLoading && autonomyFlags ? (
                <span className="text-xs text-slate-500">{autonomyEnabledCount} of 6 on</span>
              ) : undefined
            }
          />
          {autonomyFlagsLoading ? (
            <p className="text-sm text-slate-500">Loading autonomy status…</p>
          ) : autonomyFlagsError || !autonomyFlags ? (
            <p className="text-sm text-slate-500">Autonomy status unavailable right now.</p>
          ) : (
            <div className="grid grid-cols-1 gap-x-8 gap-y-1 md:grid-cols-2">
              {[
                ['Traces', autonomyFlags.autonomy_traces_enabled],
                ['Structured Plan', autonomyFlags.autonomy_structured_plan],
                ['Policy Engine', autonomyFlags.autonomy_policy_engine],
                ['Attention Queue', autonomyFlags.autonomy_attention_enabled],
                ['Missions', autonomyFlags.autonomy_missions_enabled],
                ['Policy Candidates', autonomyFlags.autonomy_policy_candidates_enabled],
              ].map(([label, enabled]) => (
                <div
                  key={label as string}
                  className="flex items-baseline justify-between rounded px-2 py-1.5"
                >
                  <span className="text-[15px] text-slate-200">{label as string}</span>
                  <span className={`text-xs ${enabled ? 'text-slate-300' : 'text-slate-500'}`}>
                    {enabled ? 'On' : 'Off'}
                  </span>
                </div>
              ))}
              <div
                className={`md:col-span-2 flex items-baseline justify-between px-2 py-1.5 ${
                  autonomyFlags.automation_admin_configured ? '' : 'border-l-2 border-rose-400/70'
                }`}
              >
                <span className="text-[15px] text-slate-200">Automation Admin Access</span>
                <span
                  className={`text-xs ${
                    autonomyFlags.automation_admin_configured ? 'text-slate-300' : 'text-rose-300'
                  }`}
                >
                  {autonomyFlags.automation_admin_configured
                    ? `Configured (roles: ${autonomyFlags.automation_admin_role_count}, allowlist: ${autonomyFlags.automation_admin_email_count})`
                    : 'Not configured'}
                </span>
              </div>
            </div>
          )}
        </section>

        <section className="mt-12">
          <SectionHeading label="Rollout health · last 24h" />
          {rolloutSummaryLoading ? (
            <p className="text-sm text-slate-500">Loading rollout health…</p>
          ) : rolloutSummaryError || !rolloutSummary ? (
            <p className="text-sm text-slate-500">Rollout health data unavailable right now.</p>
          ) : (
            <div className="space-y-5">
              <div className="grid grid-cols-1 gap-x-8 gap-y-1 md:grid-cols-2">
                {[
                  ['Agent runs', `${rolloutSummary.run_log.total_runs}`],
                  ['Plan fallback rate', `${pct(rolloutSummary.rates.fallback_rate)} (max ${pct(rolloutSummary.thresholds.max_fallback_rate)})`],
                  ['Action failure rate', `${pct(rolloutSummary.rates.action_failure_rate)} (max ${pct(rolloutSummary.thresholds.max_action_failure_rate)})`],
                  ['Notification dedup block', `${pct(rolloutSummary.rates.dedup_block_rate)} (max ${pct(rolloutSummary.thresholds.max_dedup_block_rate)})`],
                  ['Attention backlog', `${pct(rolloutSummary.rates.attention_backlog_ratio)} (max ${pct(rolloutSummary.thresholds.max_attention_backlog_ratio)})`],
                  ['Mission failure', `${pct(rolloutSummary.rates.mission_failure_rate)} (max ${pct(rolloutSummary.thresholds.max_mission_failure_rate)})`],
                ].map(([label, value]) => (
                  <div
                    key={label as string}
                    className="flex items-baseline justify-between gap-3 px-2 py-1.5"
                  >
                    <span className="text-[15px] text-slate-200">{label as string}</span>
                    <span className="text-xs tabular-nums text-slate-400">{value as string}</span>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-1 gap-x-8 gap-y-1 md:grid-cols-2">
                {Object.entries(rolloutSummary.evaluations).map(([flag, evaluation]) => (
                  <div
                    key={flag}
                    className={`px-2 py-1.5 ${
                      evaluation.status === 'unhealthy' ? 'border-l-2 border-rose-400/70' : ''
                    }`}
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-[15px] text-slate-200">{flag}</span>
                      <span
                        className={`text-xs ${
                          evaluation.status === 'healthy'
                            ? 'text-slate-400'
                            : evaluation.status === 'unhealthy'
                            ? 'text-rose-300'
                            : 'text-slate-500'
                        }`}
                      >
                        {evaluation.status}
                      </span>
                    </div>
                    {evaluation.reasons.length > 0 && (
                      <p className="mt-1 break-words text-xs text-slate-500">{evaluation.reasons.join(' · ')}</p>
                    )}
                  </div>
                ))}
              </div>

              {rolloutSummary.rollback_recommendations.length > 0 && (
                <div className="border-l-2 border-rose-400/70 px-3 py-1">
                  <p className="text-sm font-medium text-rose-300">Rollback recommended</p>
                  <div className="mt-1 space-y-1 text-xs text-slate-400">
                    {rolloutSummary.rollback_recommendations.map((item) => (
                      <p key={item.flag}>
                        {item.flag}: {item.reasons.join(' | ')}
                      </p>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        {/* Test Result Alert */}
        {testResult && (
          <div
            className={`mt-8 rounded-lg border-l-2 bg-white/[0.03] px-4 py-3 ${
              testResult.success ? 'border-emerald-400/70' : 'border-rose-400/70'
            }`}
          >
            <p className={`text-sm ${testResult.success ? 'text-slate-200' : 'text-rose-200'}`}>
              {testResult.message}
            </p>
          </div>
        )}

        {/* Settings Form */}
        <form onSubmit={handleSubmit}>
            {/* AI Provider Selection */}
            <section className="mt-12">
              <SectionHeading label="AI provider" />
              <div className="space-y-4">
                <div>
                  <label htmlFor="ai_provider" className={labelCls}>
                    Provider
                  </label>
                  <select
                    id="ai_provider"
                    value={aiProvider}
                    onChange={(e) => handleProviderChange(e.target.value as ProviderType)}
                    className={inputCls}
                  >
                    <option value="local">Local (Ollama/LM Studio)</option>
                    <option value="gemini">Google Gemini</option>
                    <option value="openai">OpenAI</option>
                    <option value="codex">ChatGPT Codex (OAuth)</option>
                    <option value="claude">Anthropic Claude</option>
                    <option value="custom">Custom Configuration</option>
                  </select>
                  <p className={hintCls}>
                    Presets fill the URLs and models below; Custom keeps your values
                  </p>
                </div>

                {(aiProvider === 'gemini' || aiProvider === 'openai' || aiProvider === 'claude') && (
                  <div>
                    <label htmlFor="openai_api_key" className={labelCls}>
                      API Key
                    </label>
                    <input
                      type="password"
                      id="openai_api_key"
                      value={formData.openai_api_key || ''}
                      onChange={(e) => handleInputChange('openai_api_key', e.target.value)}
                      className={inputCls}
                      placeholder={
                        aiProvider === 'gemini' ? 'Enter Gemini API key' :
                        aiProvider === 'claude' ? 'Enter Claude API key (sk-ant-...)' :
                        'Enter OpenAI API key'
                      }
                    />
                    <p className={hintCls}>
                      {aiProvider === 'gemini'
                        ? 'Get your API key from https://aistudio.google.com/apikey'
                        : aiProvider === 'claude'
                        ? 'Get your API key from https://console.anthropic.com/settings/keys'
                        : 'Get your API key from https://platform.openai.com/api-keys'}
                    </p>
                  </div>
                )}

                {aiProvider === 'codex' && (
                  <div>
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <p className="text-[15px] text-slate-200">
                          ChatGPT OAuth connection
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          {codexOAuthLoading
                            ? 'Checking connection status…'
                            : codexOAuthStatus?.connected
                            ? `Connected${codexOAuthStatus.email ? ` as ${codexOAuthStatus.email}` : ''}`
                            : 'Not connected'}
                        </p>
                        {codexOAuthStatus?.expires_at && codexOAuthStatus.connected && (
                          <p className="mt-1 text-xs text-slate-500">
                            Token expiry: {new Date(codexOAuthStatus.expires_at).toLocaleString('en-US')}
                          </p>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={handleRefreshCodexOAuthStatus}
                          disabled={codexOAuthLoading || codexOAuthFetching}
                          className={btnSecondary}
                        >
                          {(codexOAuthLoading || codexOAuthFetching) ? 'Refreshing…' : 'Refresh Status'}
                        </button>
                        {!codexOAuthStatus?.connected ? (
                          <button
                            type="button"
                            onClick={handleConnectCodexOAuth}
                            disabled={startCodexOAuthMutation.isPending}
                            className={btnSecondary}
                          >
                            {startCodexOAuthMutation.isPending ? 'Starting…' : 'Connect ChatGPT'}
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={handleDisconnectCodexOAuth}
                            disabled={disconnectCodexOAuthMutation.isPending}
                            className={btnSecondary}
                          >
                            {disconnectCodexOAuthMutation.isPending ? 'Disconnecting…' : 'Disconnect'}
                          </button>
                        )}
                      </div>
                    </div>
                    <p className="mt-2 text-xs text-slate-500">
                      Uses your ChatGPT subscription via OAuth. No API key required. If prompted, paste the localhost callback URL back here to complete.
                    </p>
                  </div>
                )}

                {aiProvider === 'claude' && (
                  <div>
                    <label htmlFor="claude_model" className={labelCls}>
                      Claude Model
                    </label>
                    <select
                      id="claude_model"
                      value={formData.openai_model || 'claude-sonnet-4-6'}
                      onChange={(e) => handleInputChange('openai_model', e.target.value)}
                      className={inputCls}
                    >
                      {CLAUDE_MODELS.map((model) => (
                        <option key={model.value} value={model.value}>{model.label}</option>
                      ))}
                    </select>
                    <p className={hintCls}>
                      Opus is most capable, Haiku is fastest
                    </p>
                  </div>
                )}
              </div>
            </section>

            {/* AI Model Settings */}
            <section className="mt-12">
              <SectionHeading label="Models" />
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                <div>
                  <label htmlFor="openai_base_url" className={labelCls}>
                    AI Base URL
                  </label>
                  <input
                    type="url"
                    id="openai_base_url"
                    value={formData.openai_base_url || ''}
                    onChange={(e) => handleInputChange('openai_base_url', e.target.value)}
                    className={inputCls}
                    placeholder={settings?.openai_base_url || 'http://100.104.68.115:11434/v1'}
                  />
                  <p className={hintCls}>OpenAI-compatible API endpoint</p>
                </div>

                <div>
                  <label htmlFor="openai_model" className={labelCls}>
                    Main AI Model
                  </label>
                  <input
                    type="text"
                    id="openai_model"
                    value={formData.openai_model || ''}
                    onChange={(e) => handleInputChange('openai_model', e.target.value)}
                    className={inputCls}
                    placeholder={settings?.openai_model || 'gpt-oss:20b'}
                  />
                  <p className={hintCls}>Model name to use for chat and reasoning</p>
                </div>

                <div>
                  <label htmlFor="openai_notification_model" className={labelCls}>
                    Notification Model
                  </label>
                  <input
                    type="text"
                    id="openai_notification_model"
                    value={formData.openai_notification_model || ''}
                    onChange={(e) => handleInputChange('openai_notification_model', e.target.value)}
                    className={inputCls}
                    placeholder={settings?.openai_notification_model || 'gpt-oss:20b'}
                  />
                  <p className={hintCls}>Faster model for generating push notifications</p>
                </div>
              </div>
            </section>

            {/* Embedding Settings */}
            <section className="mt-12">
              <SectionHeading label="Embeddings" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label htmlFor="embedding_base_url" className={labelCls}>
                    Embedding Base URL
                  </label>
                  <input
                    type="url"
                    id="embedding_base_url"
                    value={formData.embedding_base_url || ''}
                    onChange={(e) => handleInputChange('embedding_base_url', e.target.value)}
                    className={inputCls}
                    placeholder={settings?.embedding_base_url || 'http://100.104.68.115:11434'}
                  />
                  <p className={hintCls}>Embedding service endpoint</p>
                </div>

                <div>
                  <label htmlFor="embedding_model" className={labelCls}>
                    Embedding Model
                  </label>
                  <input
                    type="text"
                    id="embedding_model"
                    value={formData.embedding_model || ''}
                    onChange={(e) => handleInputChange('embedding_model', e.target.value)}
                    className={inputCls}
                    placeholder={settings?.embedding_model || 'bge-m3'}
                  />
                  <p className={hintCls}>Model for generating embeddings</p>
                </div>

                <div>
                  <label htmlFor="embedding_dimension" className={labelCls}>
                    Embedding Dimension
                  </label>
                  <input
                    type="number"
                    id="embedding_dimension"
                    value={formData.embedding_dimension || ''}
                    onChange={(e) => handleInputChange('embedding_dimension', parseInt(e.target.value))}
                    className={inputCls}
                    placeholder={settings?.embedding_dimension?.toString() || '1024'}
                    min="1"
                    max="4096"
                  />
                  <p className={hintCls}>Vector dimension for embeddings</p>
                </div>
              </div>
            </section>

            {/* Background Processing Settings */}
            <section className="mt-12">
              <SectionHeading
                label="Background processing"
                action={<span className="text-xs text-slate-500">dreaming, consolidation, automated tasks</span>}
              />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label htmlFor="bg_llm_primary_url" className={labelCls}>
                    Primary URL
                  </label>
                  <input
                    type="url"
                    id="bg_llm_primary_url"
                    value={formData.bg_llm_primary_url || ''}
                    onChange={(e) => handleInputChange('bg_llm_primary_url', e.target.value)}
                    className={inputCls}
                    placeholder="http://100.104.68.115:11434/v1"
                  />
                  <p className={hintCls}>Main endpoint for background tasks</p>
                </div>

                <div>
                  <label htmlFor="bg_llm_primary_model" className={labelCls}>
                    Primary Model
                  </label>
                  <input
                    type="text"
                    id="bg_llm_primary_model"
                    value={formData.bg_llm_primary_model || ''}
                    onChange={(e) => handleInputChange('bg_llm_primary_model', e.target.value)}
                    className={inputCls}
                    placeholder="gpt-oss:20b"
                  />
                  <p className={hintCls}>Model for deep analysis tasks</p>
                </div>

                <div>
                  <label htmlFor="bg_llm_fallback_url" className={labelCls}>
                    Fallback URL
                  </label>
                  <input
                    type="url"
                    id="bg_llm_fallback_url"
                    value={formData.bg_llm_fallback_url || ''}
                    onChange={(e) => handleInputChange('bg_llm_fallback_url', e.target.value)}
                    className={inputCls}
                    placeholder="http://100.104.68.115:11434/v1"
                  />
                  <p className={hintCls}>Backup endpoint if primary fails</p>
                </div>

                <div>
                  <label htmlFor="bg_llm_fallback_model" className={labelCls}>
                    Fallback Model
                  </label>
                  <input
                    type="text"
                    id="bg_llm_fallback_model"
                    value={formData.bg_llm_fallback_model || ''}
                    onChange={(e) => handleInputChange('bg_llm_fallback_model', e.target.value)}
                    className={inputCls}
                    placeholder="gpt-oss:20b"
                  />
                  <p className={hintCls}>Faster model for quick background tasks</p>
                </div>
              </div>
            </section>

            {/* Sandbox VM Settings */}
            <section className="mt-12">
              <SectionHeading
                label="Sandbox VM"
                action={<span className="text-xs text-slate-500">where Sara dispatches coding agents</span>}
              />
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div>
                  <label htmlFor="vm_sandbox_host" className={labelCls}>
                    VM Host
                  </label>
                  <input
                    type="text"
                    id="vm_sandbox_host"
                    value={formData.vm_sandbox_host || ''}
                    onChange={(e) => handleInputChange('vm_sandbox_host', e.target.value)}
                    className={inputCls}
                    placeholder="10.185.1.176"
                  />
                  <p className={hintCls}>IP address or hostname of the sandbox VM</p>
                </div>

                <div>
                  <label htmlFor="vm_sandbox_username" className={labelCls}>
                    SSH Username
                  </label>
                  <input
                    type="text"
                    id="vm_sandbox_username"
                    value={formData.vm_sandbox_username || ''}
                    onChange={(e) => handleInputChange('vm_sandbox_username', e.target.value)}
                    className={inputCls}
                    placeholder="sara"
                  />
                  <p className={hintCls}>SSH user on the VM</p>
                </div>

                <div>
                  <label htmlFor="vm_sandbox_ssh_key_path" className={labelCls}>
                    SSH Key Path
                  </label>
                  <input
                    type="text"
                    id="vm_sandbox_ssh_key_path"
                    value={formData.vm_sandbox_ssh_key_path || ''}
                    onChange={(e) => handleInputChange('vm_sandbox_ssh_key_path', e.target.value)}
                    className={inputCls}
                    placeholder="~/.ssh/sara_agent"
                  />
                  <p className={hintCls}>Path to SSH private key on the server</p>
                </div>
              </div>

              <div className="mt-4 flex items-center gap-3">
                <button
                  type="button"
                  onClick={async () => {
                    setVmTestLoading(true)
                    setVmTestResult(null)
                    try {
                      const result = await apiClient.testVMConnection()
                      setVmTestResult(result)
                    } catch (err: any) {
                      setVmTestResult({ status: 'error', host: formData.vm_sandbox_host || '' })
                    } finally {
                      setVmTestLoading(false)
                    }
                  }}
                  disabled={vmTestLoading}
                  className={btnSecondary}
                >
                  {vmTestLoading ? 'Testing…' : 'Test Connection'}
                </button>
                {vmTestResult && (
                  <span className={`text-xs ${vmTestResult.status === 'connected' ? 'text-slate-300' : 'text-rose-300'}`}>
                    {vmTestResult.status === 'connected'
                      ? `Connected to ${vmTestResult.host}`
                      : `Connection failed: ${vmTestResult.status}`}
                  </span>
                )}
              </div>
            </section>

            {/* Desktop Agent Settings */}
            <section className="mt-12">
              <SectionHeading label="Desktop agent & vision" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label htmlFor="vision_model" className={labelCls}>
                    Vision Model
                  </label>
                  <input
                    type="text"
                    id="vision_model"
                    defaultValue="qwen3-vl:latest"
                    className={inputCls}
                    placeholder="qwen3-vl:latest"
                  />
                  <p className={hintCls}>Ollama vision model for screenshot analysis</p>
                </div>

                <div>
                  <label htmlFor="vision_endpoint" className={labelCls}>
                    Vision Endpoint
                  </label>
                  <input
                    type="url"
                    id="vision_endpoint"
                    defaultValue="http://10.185.1.8:11434"
                    className={inputCls}
                    placeholder="http://10.185.1.8:11434"
                  />
                  <p className={hintCls}>Ollama server for vision model</p>
                </div>

                <div>
                  <label htmlFor="screenshot_interval" className={labelCls}>
                    Screenshot Interval (seconds)
                  </label>
                  <input
                    type="number"
                    id="screenshot_interval"
                    defaultValue={30}
                    min={10}
                    max={300}
                    className={inputCls}
                  />
                  <p className={hintCls}>How often the desktop agent captures screenshots</p>
                </div>

                <div className="flex items-center justify-between rounded-lg px-2 py-3 transition-colors hover:bg-white/[0.04]">
                  <div>
                    <div className="text-[15px] text-slate-200">Screenshot Capture</div>
                    <div className="text-xs text-slate-500">Enable periodic screenshot capture</div>
                  </div>
                  <label className="inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      className="sr-only peer"
                      defaultChecked={true}
                    />
                    <span className="w-10 h-6 bg-white/10 rounded-full p-1 transition-colors duration-200 peer-checked:bg-teal-500/70">
                      <span className="block w-4 h-4 bg-white rounded-full transform transition-transform duration-200 peer-checked:translate-x-4"></span>
                    </span>
                  </label>
                </div>

                <div className="flex items-center justify-between rounded-lg px-2 py-3 transition-colors hover:bg-white/[0.04]">
                  <div>
                    <div className="text-[15px] text-slate-200">Cross-Device Commands</div>
                    <div className="text-xs text-slate-500">Route commands to active device</div>
                  </div>
                  <label className="inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      className="sr-only peer"
                      defaultChecked={true}
                    />
                    <span className="w-10 h-6 bg-white/10 rounded-full p-1 transition-colors duration-200 peer-checked:bg-teal-500/70">
                      <span className="block w-4 h-4 bg-white rounded-full transform transition-transform duration-200 peer-checked:translate-x-4"></span>
                    </span>
                  </label>
                </div>
              </div>
            </section>

            {/* Notification Preferences */}
            <section className="mt-12">
              <SectionHeading
                label="Notifications"
                action={
                  !notifPrefsLoading ? (
                    <span className="text-xs text-slate-500">{enabledNotificationCount} enabled</span>
                  ) : undefined
                }
              />
              {notifPrefsLoading ? (
                <p className="text-sm text-slate-500">Loading preferences…</p>
              ) : (
                <div className="space-y-1">
                  {(notifPrefsData?.preferences || []).map((pref) => {
                    const categoryLabels: Record<string, { label: string; desc: string }> = {
                      health: { label: 'Health', desc: 'HRV, heart rate, blood pressure, body temperature, SpO2, etc.' },
                      fitness: { label: 'Fitness', desc: 'Workouts, steps, calories burned, recovery scores, exercise reminders' },
                      calendar: { label: 'Calendar', desc: 'Meeting reminders, schedule changes, upcoming events' },
                      email: { label: 'Email', desc: 'Important unread emails, action-required messages' },
                      security: { label: 'Security', desc: 'Door locks, motion detection, security alerts' },
                      home: { label: 'Home', desc: 'Lights, temperature, home automation events' },
                      general: { label: 'General', desc: 'Check-ins, project updates, misc notifications' },
                    }
                    const info = categoryLabels[pref.category] || { label: pref.category, desc: '' }

                    return (
                      <div
                        key={pref.category}
                        className="flex items-center justify-between rounded-lg px-2 py-3 transition-colors hover:bg-white/[0.04]"
                      >
                        <div className="flex-1 min-w-0">
                          <div className="text-[15px] text-slate-200">{info.label}</div>
                          <div className="text-xs text-slate-500 mt-0.5">{info.desc}</div>
                        </div>
                        <label className="inline-flex items-center cursor-pointer ml-4 flex-shrink-0">
                          <input
                            type="checkbox"
                            className="sr-only peer"
                            checked={pref.enabled}
                            onChange={(e) => {
                              const updated = (notifPrefsData?.preferences || []).map(p =>
                                p.category === pref.category
                                  ? { ...p, enabled: e.target.checked }
                                  : p
                              )
                              updateNotifPrefsMutation.mutate(updated)
                            }}
                          />
                          <span className={`w-10 h-6 rounded-full p-1 transition-colors duration-200 ${pref.enabled ? 'bg-teal-500/70' : 'bg-white/10'}`}>
                            <span className={`block w-4 h-4 bg-white rounded-full transform transition-transform duration-200 ${pref.enabled ? 'translate-x-4' : 'translate-x-0'}`}></span>
                          </span>
                        </label>
                      </div>
                    )
                  })}
                </div>
              )}
            </section>

            {/* Token Usage Statistics */}
            <section className="mt-12">
              <SectionHeading label="Token usage" />
              <TokenUsageStats />
            </section>

            {/* Appearance */}
            <section className="mt-12">
              <SectionHeading label="Appearance" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="flex items-center justify-between rounded-lg px-2 py-3 transition-colors hover:bg-white/[0.04]">
                  <div>
                    <div className="text-[15px] text-slate-200">Calm Mode</div>
                    <div className="text-xs text-slate-500">Reduces visual intensity and tempo.</div>
                  </div>
                  <label className="inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      className="sr-only"
                      defaultChecked={getCalmMode()}
                      onChange={(e) => {
                        const v = e.target.checked
                        setCalmMode(v)
                        // Apply immediately
                        if (v) {
                        } else {
                        }
                      }}
                    />
                    <span className="w-10 h-6 bg-white/10 rounded-full p-1 transition-colors duration-200 peer-checked:bg-teal-500/70">
                      <span className="block w-4 h-4 bg-white rounded-full transform transition-transform duration-200 translate-x-0 peer-checked:translate-x-4"></span>
                    </span>
                  </label>
                </div>

                <div className="flex items-center justify-between rounded-lg px-2 py-3 transition-colors hover:bg-white/[0.04]">
                  <div>
                    <div className="text-[15px] text-slate-200">Enhanced Visuals</div>
                    <div className="text-xs text-slate-500">Enable richer particle effects on capable devices.</div>
                  </div>
                  <label className="inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      className="sr-only"
                      defaultChecked={getEnhancedVisuals()}
                      onChange={(e) => setEnhancedVisuals(e.target.checked)}
                    />
                    <span className="w-10 h-6 bg-white/10 rounded-full p-1 transition-colors duration-200 peer-checked:bg-teal-500/70">
                      <span className="block w-4 h-4 bg-white rounded-full transform transition-transform duration-200 translate-x-0 peer-checked:translate-x-4"></span>
                    </span>
                  </label>
                </div>
              </div>
            </section>

            {/* Actions */}
            <div className="mt-12 flex flex-col border-t border-white/10 pt-6 sm:flex-row sm:justify-between sm:items-center space-y-3 sm:space-y-0 sm:space-x-3">
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={handleTestConnection}
                  disabled={testSettingsMutation.isPending}
                  className={`${btnSecondary} tap-target`}
                >
                  {testSettingsMutation.isPending ? 'Testing…' : 'Test Connection'}
                </button>

                <button
                  type="button"
                  onClick={handleReset}
                  className={`${btnSecondary} tap-target`}
                >
                  Reset
                </button>

                <button
                  type="button"
                  onClick={() => {
                    if (!confirm('Clear all saved URLs and reset to defaults?')) return
                    // Clear all saved URLs and reset to defaults
                    setAIBaseUrl('')
                    setAIModel('')
                    setAINotificationModel('')
                    setEmbeddingBaseUrl('')
                    setEmbeddingModel('')
                    setEmbeddingDimension(0)
                    
                    // Reset form to defaults
                    setFormData({
                      openai_base_url: 'http://100.104.68.115:11434/v1',
                      openai_model: 'gpt-oss:20b',
                      openai_notification_model: 'gpt-oss:20b',
                      embedding_base_url: 'http://100.104.68.115:11434',
                      embedding_model: 'bge-m3',
                      embedding_dimension: 1024,
                    })
                    
                    setTestResult({ success: true, message: 'Saved URLs cleared - reset to defaults' })
                    setTimeout(() => setTestResult(null), 3000)
                  }}
                  className="text-xs text-slate-500 transition-colors hover:text-rose-300 tap-target"
                >
                  Clear Saved URLs
                </button>
              </div>

              <button
                type="submit"
                disabled={updateSettingsMutation.isPending}
                className={`${btnPrimary} tap-target`}
              >
                {updateSettingsMutation.isPending ? 'Saving…' : 'Save Settings'}
              </button>
            </div>
          </form>

        {/* Desktop App Downloads */}
        <DesktopAppDownloads />

        {/* Connected Devices */}
        <ConnectedDevices />

        {/* Brief Archive */}
        <SaraBriefArchive />

        {/* Developer Tools */}
        <section className="mt-12">
          <SectionHeading label="Developer tools" />
          <div className="flex items-center justify-between rounded-lg px-2 py-2.5 transition-colors hover:bg-white/[0.04]">
            <div>
              <div className="text-[15px] text-slate-200">Orchestrator Lab</div>
              <p className="mt-0.5 text-xs text-slate-500">
                Test multi-agent task orchestration with live visualization
              </p>
              <div className="mt-1 flex gap-4 text-xs text-slate-500">
                <span>Orchestrator: qwen3-vl:30b</span>
                <span>Workers: ministral-3</span>
              </div>
            </div>
            <button
              onClick={() => {
                // Navigate to orchestrator lab - this will be handled by parent
                const event = new CustomEvent('navigate', { detail: { view: 'orchestrator-lab' } })
                window.dispatchEvent(event)
              }}
              className={`ml-4 flex-shrink-0 ${btnSecondary}`}
            >
              Open Lab
            </button>
          </div>
        </section>

        {/* Memory Maintenance */}
        <section className="mt-12">
          <SectionHeading label="Memory maintenance" />
          <div className="flex items-center justify-between rounded-lg px-2 py-2.5 transition-colors hover:bg-white/[0.04]">
            <div>
              <div className="text-[15px] text-slate-200">Nightly consolidation</div>
              <p className="mt-0.5 text-xs text-slate-500">Run on demand for yesterday's traces</p>
            </div>
            <button
              onClick={async () => {
                  try {
                    const yesterday = new Date(Date.now() - 24*60*60*1000)
                    const day = yesterday.toISOString().slice(0,10)
                    const resp = await fetch(`${APP_CONFIG.apiUrl}/memory/consolidate`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      credentials: 'include',
                      body: JSON.stringify({ day })
                    })
                    if (resp.ok) {
                      setTestResult({ success: true, message: 'Consolidation started/succeeded for yesterday.' })
                    } else {
                      const txt = await resp.text()
                      setTestResult({ success: false, message: `Consolidation failed: ${resp.status} ${txt}` })
                    }
                    setTimeout(() => setTestResult(null), 4000)
                  } catch (err: any) {
                    setTestResult({ success: false, message: err?.message || 'Consolidation failed' })
                    setTimeout(() => setTestResult(null), 5000)
                  }
                }}
              className={`ml-4 flex-shrink-0 ${btnSecondary}`}
            >
              Run Consolidation (Yesterday)
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}
