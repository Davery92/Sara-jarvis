import { useState, useEffect, useRef, useCallback } from 'react'
import {
  BellAlertIcon,
  Cog6ToothIcon,
  CpuChipIcon,
  ShieldCheckIcon,
} from '@heroicons/react/24/outline'
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

  if (isLoading) {
    return (
      <div className="mt-8 bg-card border border-card rounded-md p-6">
        <div className="animate-pulse">
          <div className="h-6 bg-gray-700 rounded w-48 mb-4"></div>
          <div className="space-y-3">
            <div className="h-16 bg-gray-800 rounded"></div>
            <div className="h-16 bg-gray-800 rounded"></div>
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="mt-8 bg-card border border-card rounded-md p-6">
        <div className="flex items-center mb-4">
          <svg className="w-6 h-6 text-teal-400 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
          <h3 className="text-lg font-medium text-white">Connected Devices</h3>
        </div>
        <p className="text-gray-400 text-sm">Failed to load devices. Please try again later.</p>
      </div>
    )
  }

  const devices = data?.devices || []

  return (
    <div className="mt-8 bg-card border border-card rounded-md p-6">
      <div className="flex items-center mb-4">
        <svg className="w-6 h-6 text-teal-400 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
        <h3 className="text-lg font-medium text-white">Connected Devices</h3>
      </div>

      <p className="text-gray-400 text-sm mb-6">
        Desktop agents running the Sara companion app. Devices send activity and screenshots to provide context.
      </p>

      {devices.length === 0 ? (
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-6 text-center">
          <svg className="w-12 h-12 text-gray-600 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
          <p className="text-gray-400 text-sm">No devices connected yet.</p>
          <p className="text-gray-500 text-xs mt-1">Download and run the desktop app to connect.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {devices.map((device) => (
            <div
              key={device.device_id}
              className="flex items-center justify-between bg-gray-800/50 border border-gray-700 rounded-lg px-4 py-3"
            >
              <div className="flex items-center gap-4 flex-1 min-w-0">
                {/* Online status dot */}
                <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                  device.is_online ? 'bg-green-500' : 'bg-gray-500'
                }`} />

                {/* Platform icon */}
                <div className="text-gray-400 flex-shrink-0">
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
                        className="px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white text-sm w-48 focus:outline-none focus:border-teal-500"
                        autoFocus
                      />
                      <button
                        onClick={() => saveEdit(device.device_id)}
                        disabled={updateNameMutation.isPending}
                        className="text-teal-400 hover:text-teal-300 text-sm"
                      >
                        Save
                      </button>
                      <button
                        onClick={() => setEditingDevice(null)}
                        className="text-gray-400 hover:text-gray-300 text-sm"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <>
                      <div className="text-white font-medium truncate">
                        {device.friendly_name || device.hostname || 'Unknown Device'}
                      </div>
                      <div className="text-xs text-gray-500 truncate">
                        {device.device_id.slice(0, 30)}...
                      </div>
                    </>
                  )}
                </div>

                {/* Activity */}
                <div className="text-xs text-gray-400 flex-shrink-0 hidden sm:block">
                  {device.is_online ? (
                    <span className="text-green-400">{device.activity_level}</span>
                  ) : (
                    <span>{formatLastActivity(device.last_activity_at)}</span>
                  )}
                </div>
              </div>

              {/* Actions */}
              {editingDevice !== device.device_id && (
                <div className="flex items-center gap-2 ml-4">
                  <button
                    onClick={() => startEdit(device)}
                    className="px-2 py-1 text-xs text-gray-400 hover:text-white transition"
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
                    className="px-2 py-1 text-xs text-red-400 hover:text-red-300 transition"
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
    </div>
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
    return (
      <div className="animate-pulse">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="bg-gray-800 rounded-lg p-4 h-20"></div>
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-red-400 text-sm">
        Failed to load token statistics. The feature may not be available yet.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <div className="text-xs text-gray-400 uppercase tracking-wide">Total Tokens</div>
          <div className="text-2xl font-bold text-teal-400 mt-1">
            {formatNumber(tokenStats?.total_tokens || 0)}
          </div>
        </div>
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <div className="text-xs text-gray-400 uppercase tracking-wide">Prompt Tokens</div>
          <div className="text-2xl font-bold text-blue-400 mt-1">
            {formatNumber(tokenStats?.total_prompt_tokens || 0)}
          </div>
        </div>
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <div className="text-xs text-gray-400 uppercase tracking-wide">Completion Tokens</div>
          <div className="text-2xl font-bold text-purple-400 mt-1">
            {formatNumber(tokenStats?.total_completion_tokens || 0)}
          </div>
        </div>
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <div className="text-xs text-gray-400 uppercase tracking-wide">Total Requests</div>
          <div className="text-2xl font-bold text-green-400 mt-1">
            {formatNumber(tokenStats?.total_requests || 0)}
          </div>
        </div>
      </div>

      {/* Meta Info & Reset */}
      <div className="flex flex-wrap items-center justify-between gap-4 text-sm">
        <div className="text-gray-400">
          {tokenStats?.last_reset_at ? (
            <span>Tracking since: {formatDate(tokenStats.last_reset_at)}</span>
          ) : (
            <span>Tracking since: Start</span>
          )}
          {tokenStats?.updated_at && (
            <span className="ml-4 text-gray-500">Last update: {formatDate(tokenStats.updated_at)}</span>
          )}
        </div>

        {!showResetConfirm ? (
          <button
            onClick={() => setShowResetConfirm(true)}
            className="px-3 py-1.5 text-xs font-medium text-red-400 bg-red-900/20 border border-red-500/30 rounded-lg hover:bg-red-900/30 transition-colors"
          >
            Reset Counter
          </button>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400">Are you sure?</span>
            <button
              onClick={() => resetMutation.mutate()}
              disabled={resetMutation.isPending}
              className="px-3 py-1.5 text-xs font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
            >
              {resetMutation.isPending ? 'Resetting...' : 'Yes, Reset'}
            </button>
            <button
              onClick={() => setShowResetConfirm(false)}
              className="px-3 py-1.5 text-xs font-medium text-gray-400 bg-gray-700 rounded-lg hover:bg-gray-600 transition-colors"
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
      <div className="mt-8 bg-card border border-card rounded-md p-6">
        <div className="animate-pulse">
          <div className="h-6 bg-gray-700 rounded w-48 mb-4"></div>
          <div className="space-y-3">
            <div className="h-20 bg-gray-800 rounded"></div>
            <div className="h-20 bg-gray-800 rounded"></div>
          </div>
        </div>
      </div>
    )
  }

  if (error || !data?.downloads?.length) {
    return (
      <div className="mt-8 bg-card border border-card rounded-md p-6">
        <div className="flex items-center mb-4">
          <svg className="w-6 h-6 text-indigo-400 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          <h3 className="text-lg font-medium text-white">Desktop App</h3>
        </div>
        <p className="text-gray-400 text-sm">
          {error ? 'Failed to load downloads. Please try again later.' : 'No downloads available yet.'}
        </p>
      </div>
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
    <div className="mt-8 bg-card border border-card rounded-md p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center">
          <svg className="w-6 h-6 text-indigo-400 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          <h3 className="text-lg font-medium text-white">Sara Desktop Companion</h3>
        </div>
        <span className="text-xs text-gray-500 bg-gray-800 px-2 py-1 rounded">v{data.version}</span>
      </div>

      <p className="text-gray-400 text-sm mb-6">
        A floating desktop companion. Click to open chat, with support for text and voice input, notes overlay, and timer displays.
      </p>

      <div className="space-y-4">
        {Object.entries(byPlatform).map(([platform, downloads]) => (
          <div key={platform} className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
            <div className="flex items-center gap-3 mb-3">
              <div className="text-gray-300">{getPlatformIcon(platform)}</div>
              <h4 className="text-white font-medium">{platform}</h4>
            </div>
            <div className="space-y-2">
              {downloads.map((download) => (
                <div
                  key={download.filename}
                  className="flex items-center justify-between bg-gray-900/50 rounded-lg px-4 py-3"
                >
                  <div className="flex-1">
                    <div className="text-sm text-white font-medium">
                      {getArchLabel(download.arch)}
                    </div>
                    <div className="text-xs text-gray-500">
                      {download.filename} ({download.size_mb} MB)
                    </div>
                  </div>
                  <button
                    onClick={() => handleDownload(download.filename)}
                    className="ml-4 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
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
        <div className="mt-6 pt-6 border-t border-gray-700">
          <div className="flex items-center gap-3 mb-3">
            <div className="text-green-400">
              <svg className="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12.504 0c-.155 0-.315.008-.48.021-4.226.333-3.105 4.807-3.17 6.298-.076 1.092-.3 1.953-1.05 3.02-.885 1.051-2.127 2.75-2.716 4.521-.278.832-.41 1.684-.287 2.489a.424.424 0 00-.11.135c-.26.268-.45.6-.663.839-.199.199-.485.267-.797.4-.313.136-.658.269-.864.68-.09.189-.136.394-.132.602 0 .199.027.4.055.536.058.399.116.728.04.97-.249.68-.28 1.145-.106 1.484.174.334.535.47.94.601.81.2 1.91.135 2.774.6.926.466 1.866.67 2.616.47.526-.116.97-.464 1.208-.946.587-.003 1.23-.269 2.26-.334.699-.058 1.574.267 2.577.2.025.134.063.198.114.333l.003.003c.391.778 1.113 1.132 1.884 1.071.771-.06 1.592-.536 2.257-1.306.631-.765 1.683-1.084 2.378-1.503.348-.199.629-.469.649-.853.023-.4-.2-.811-.714-1.376v-.097l-.003-.003c-.17-.2-.25-.535-.338-.926-.085-.401-.182-.786-.492-1.046h-.003c-.059-.054-.123-.067-.188-.135a.357.357 0 00-.19-.064c.431-1.278.264-2.55-.173-3.694-.533-1.41-1.465-2.638-2.175-3.483-.796-1.005-1.576-1.957-1.56-3.368.026-2.152.236-6.133-3.544-6.139z" />
              </svg>
            </div>
            <div>
              <h4 className="text-white font-medium">Linux Headless Agent</h4>
              <p className="text-xs text-gray-400">For servers without a GUI - runs as a systemd service</p>
            </div>
          </div>

          {headlessDownloads.map((download) => (
            <div
              key={download.filename}
              className="flex items-center justify-between bg-gray-900/50 rounded-lg px-4 py-3"
            >
              <div className="flex-1">
                <div className="text-sm text-white font-medium">
                  Headless Agent (x64)
                </div>
                <div className="text-xs text-gray-500">
                  {download.filename} ({download.size_mb} MB)
                </div>
                <div className="text-xs text-green-400/80 mt-1">
                  Includes: System metrics, remote commands, auto-start
                </div>
              </div>
              <button
                onClick={() => handleDownload(download.filename)}
                className="ml-4 px-4 py-2 bg-green-600 hover:bg-green-500 text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                Download
              </button>
            </div>
          ))}

          <div className="mt-3 p-3 bg-green-900/20 border border-green-500/20 rounded-lg">
            <div className="text-xs text-green-300">
              <p className="font-medium">Quick Install:</p>
              <code className="block mt-2 bg-black/30 px-2 py-1.5 rounded text-green-100 font-mono text-[10px] break-all">
                curl -L {APP_CONFIG.apiUrl}/api/downloads/sara-agent-linux.tar.gz | tar xz && cd sara-agent && sudo ./install.sh
              </code>
            </div>
          </div>
        </div>
      )}

      <div className="mt-4 p-3 bg-blue-900/20 border border-blue-500/20 rounded-lg">
        <div className="flex items-start gap-2">
          <svg className="w-5 h-5 text-blue-400 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
          </svg>
          <div className="text-xs text-blue-300">
            <p className="font-medium">Desktop App Installation:</p>
            <ul className="mt-1 space-y-1 text-blue-300/80">
              <li><strong>Windows:</strong> Extract the archive and run Sara.exe</li>
              <li><strong>macOS:</strong> Extract the zip and move Sara.app to Applications</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Activity Monitoring Setup */}
      <div className="mt-4 p-4 bg-amber-900/20 border border-amber-500/20 rounded-lg">
        <div className="flex items-start gap-2">
          <svg className="w-5 h-5 text-amber-400 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
          </svg>
          <div className="text-xs text-amber-200">
            <p className="font-medium text-amber-300">Activity Monitoring Setup (Optional)</p>
            <p className="mt-1 text-amber-200/80">
              For activity tracking and screenshot features, install Python 3 and run:
            </p>
            <div className="mt-2 space-y-2">
              <div>
                <p className="text-amber-300/80 font-medium">Windows (PowerShell):</p>
                <code className="block mt-1 bg-black/30 px-2 py-1 rounded text-amber-100 font-mono text-[10px] break-all">
                  pip install pynput mss Pillow websockets httpx numpy
                </code>
              </div>
              <div>
                <p className="text-amber-300/80 font-medium">macOS (Terminal):</p>
                <code className="block mt-1 bg-black/30 px-2 py-1 rounded text-amber-100 font-mono text-[10px] break-all">
                  pip3 install pynput mss Pillow websockets httpx numpy
                </code>
              </div>
            </div>
            <p className="mt-2 text-amber-200/60">
              Download Python from <a href="https://python.org/downloads" target="_blank" rel="noopener noreferrer" className="underline hover:text-amber-100">python.org</a>
            </p>
          </div>
        </div>
      </div>
    </div>
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
    <div className="mt-8 bg-card border border-card rounded-md p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-medium text-white">Sara Brief Archive</h3>
          <p className="text-gray-400 text-sm mt-1">View full briefs Sara generated about your day and context.</p>
        </div>
        <button
          type="button"
          onClick={() => refetchBriefs()}
          className="px-3 py-1.5 text-xs text-teal-300 bg-teal-900/20 border border-teal-500/30 rounded-lg hover:bg-teal-900/30 transition"
        >
          Refresh
        </button>
      </div>

      {briefsLoading ? (
        <p className="text-sm text-gray-500 py-8 text-center">Loading brief archive...</p>
      ) : briefsError ? (
        <p className="text-sm text-red-300 py-8 text-center">Unable to load briefs right now.</p>
      ) : briefs.length === 0 ? (
        <p className="text-sm text-gray-500 py-8 text-center">No briefs generated yet.</p>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-1 border border-gray-700 rounded-lg bg-gray-800/40 overflow-hidden">
            <div className="px-3 py-2 text-xs uppercase tracking-wider text-gray-400 border-b border-gray-700">
              Recent Briefs
            </div>
            <div className="max-h-72 overflow-y-auto divide-y divide-gray-700/70">
              {briefs.map((brief) => (
                <button
                  key={brief.id}
                  type="button"
                  onClick={() => setSelectedBriefDate(brief.brief_date)}
                  className={`w-full px-3 py-2 text-left transition ${
                    selectedBriefDate === brief.brief_date ? 'bg-gray-700/50' : 'hover:bg-gray-700/30'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-white">{formatDate(brief.brief_date)}</span>
                    {brief.has_audio && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-900/30 text-blue-300 border border-blue-700/40">
                        Audio
                      </span>
                    )}
                  </div>
                  {brief.generated_at && (
                    <p className="mt-1 text-xs text-gray-400">
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

          <div className="lg:col-span-2 border border-gray-700 rounded-lg bg-gray-800/30 p-4">
            {briefDetailLoading ? (
              <p className="text-sm text-gray-500 py-8 text-center">Loading brief...</p>
            ) : briefDetailError ? (
              <p className="text-sm text-red-300 py-8 text-center">Unable to load this brief.</p>
            ) : selectedBrief ? (
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h4 className="text-white font-medium">{formatDate(selectedBrief.brief_date)} Brief</h4>
                  {selectedBrief.generated_at && (
                    <span className="text-xs text-gray-400">
                      Generated {new Date(selectedBrief.generated_at).toLocaleString('en-US')}
                    </span>
                  )}
                </div>
                <div className="max-h-80 overflow-y-auto pr-2">
                  <p className="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap break-words">
                    {selectedBrief.full_text || 'No full brief text was saved for this entry.'}
                  </p>
                </div>
              </div>
            ) : (
              <p className="text-sm text-gray-500 py-8 text-center">Select a brief to view details.</p>
            )}
          </div>
        </div>
      )}
    </div>
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
  const settingsHeroStats = [
    {
      label: 'AI Provider',
      value: providerLabels[aiProvider] || 'Unassigned',
      detail: codexOAuthStatus?.connected ? 'ChatGPT connection is live' : 'Primary model path for Sara',
      Icon: CpuChipIcon,
      accentClass: 'bg-cyan-400/10 text-cyan-200',
    },
    {
      label: 'Alerts Enabled',
      value: notifPrefsLoading ? '...' : String(enabledNotificationCount),
      detail: 'Notification categories Sara may proactively use',
      Icon: BellAlertIcon,
      accentClass: 'bg-teal-400/10 text-teal-200',
    },
    {
      label: 'Autonomy Gates',
      value: autonomyFlagsLoading ? '...' : String(autonomyEnabledCount),
      detail: autonomyFlags?.automation_admin_configured ? 'Admin gate configured' : 'Admin gate still needs setup',
      Icon: ShieldCheckIcon,
      accentClass: 'bg-emerald-400/10 text-emerald-200',
    },
    {
      label: 'Workspace Mode',
      value: getCalmMode() ? 'Calm' : 'Standard',
      detail: getEnhancedVisuals() ? 'Enhanced visuals enabled' : 'Balanced visual load',
      Icon: Cog6ToothIcon,
      accentClass: 'bg-indigo-400/10 text-indigo-200',
    },
  ]

  if (isLoading) {
    return (
      <div className="flex-1 px-4 py-8 sm:px-6 lg:px-8">
        <div className="assistant-panel mx-auto max-w-2xl rounded-md p-8 text-center">
          <div className="mx-auto h-12 w-12 animate-spin rounded-full border-b-2 border-cyan-400"></div>
          <p className="mt-4 text-sm text-[var(--assistant-text-soft)]">Loading settings...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 px-4 pb-12 pt-4 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-6xl space-y-8">
        <section className="assistant-panel-soft rounded-md px-4 py-3.5 sm:px-5">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div className="min-w-0 max-w-2xl">
              <div className="assistant-kicker mb-2">Assistant Runtime</div>
              <div className="flex flex-col gap-2 md:flex-row md:items-end md:gap-3">
                <h1 className="font-display text-2xl font-semibold text-white">Settings</h1>
                <p className="max-w-xl text-sm leading-6 text-[var(--assistant-text-soft)]">
                  Control the models, guardrails, devices, and background behaviors that shape how Sara runs.
                </p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              {settingsHeroStats.map(({ label, value }) => (
                <div key={label} className="assistant-panel flex min-w-[148px] items-center justify-between gap-3 rounded-md px-3 py-2.5">
                  <span className="assistant-kicker">{label}</span>
                  <span className="text-sm font-medium text-white">{value}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section>
          <div className="assistant-kicker mb-3">Operations</div>
          <p className="mb-5 max-w-3xl text-sm text-[var(--assistant-text-soft)]">
            Keep schedules, tunables, and rollout guardrails aligned before you change deeper runtime behavior.
          </p>
        </section>

        {/* Scheduled Jobs (DB-backed Celery beat) */}
        <SchedulesSection />

        {/* Behavior Tunables (cooldowns, deliberation thresholds, brief tone) */}
        <TunablesSection />

        {/* Autonomy Feature Flag Status */}
        <div className="assistant-panel rounded-md p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="assistant-kicker mb-3">Autonomy Health</div>
              <h2 className="font-display text-2xl font-semibold text-white">Autonomy Flag Status</h2>
              <p className="mt-2 text-sm text-[var(--assistant-text-soft)]">
                Read-only visibility into runtime autonomy rollout flags and admin gate setup.
              </p>
            </div>
          </div>
          {autonomyFlagsLoading ? (
            <p className="mt-4 text-sm text-gray-500">Loading autonomy status...</p>
          ) : autonomyFlagsError || !autonomyFlags ? (
            <p className="mt-4 text-sm text-red-300">Autonomy status unavailable right now.</p>
          ) : (
            <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
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
                  className="flex items-center justify-between bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-2"
                >
                  <span className="text-sm text-gray-200">{label as string}</span>
                  <span
                    className={`text-xs font-semibold px-2 py-0.5 rounded ${
                      enabled
                        ? 'bg-green-900/40 text-green-300 border border-green-700/50'
                        : 'bg-gray-700/60 text-gray-300 border border-gray-600/60'
                    }`}
                  >
                    {enabled ? 'ON' : 'OFF'}
                  </span>
                </div>
              ))}
              <div className="md:col-span-2 flex items-center justify-between bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-2">
                <span className="text-sm text-gray-200">Automation Admin Access</span>
                <span
                  className={`text-xs font-semibold px-2 py-0.5 rounded ${
                    autonomyFlags.automation_admin_configured
                      ? 'bg-green-900/40 text-green-300 border border-green-700/50'
                      : 'bg-red-900/30 text-red-300 border border-red-700/50'
                  }`}
                >
                  {autonomyFlags.automation_admin_configured
                    ? `Configured (roles: ${autonomyFlags.automation_admin_role_count}, allowlist: ${autonomyFlags.automation_admin_email_count})`
                    : 'Not Configured'}
                </span>
              </div>
            </div>
          )}
        </div>

        <div className="assistant-panel rounded-md p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="assistant-kicker mb-3">Autonomy Health</div>
              <h2 className="font-display text-2xl font-semibold text-white">Autonomy Rollout Health (24h)</h2>
              <p className="mt-2 text-sm text-[var(--assistant-text-soft)]">
                Live rates vs configured thresholds for rollout and rollback decisions.
              </p>
            </div>
          </div>
          {rolloutSummaryLoading ? (
            <p className="mt-4 text-sm text-gray-500">Loading rollout health...</p>
          ) : rolloutSummaryError || !rolloutSummary ? (
            <p className="mt-4 text-sm text-red-300">Rollout health data unavailable right now.</p>
          ) : (
            <div className="mt-4 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
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
                    className="flex items-center justify-between bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-2"
                  >
                    <span className="text-sm text-gray-200">{label as string}</span>
                    <span className="text-sm text-gray-300">{value as string}</span>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {Object.entries(rolloutSummary.evaluations).map(([flag, evaluation]) => (
                  <div
                    key={flag}
                    className="bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-3"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-gray-200">{flag}</span>
                      <span
                        className={`text-xs font-semibold px-2 py-0.5 rounded border ${
                          evaluation.status === 'healthy'
                            ? 'bg-green-900/40 text-green-300 border-green-700/50'
                            : evaluation.status === 'unhealthy'
                            ? 'bg-red-900/30 text-red-300 border-red-700/50'
                            : 'bg-gray-700/60 text-gray-300 border-gray-600/60'
                        }`}
                      >
                        {evaluation.status}
                      </span>
                    </div>
                    {evaluation.reasons.length > 0 && (
                      <p className="text-xs text-gray-400 mt-2 break-words">{evaluation.reasons.join(' · ')}</p>
                    )}
                  </div>
                ))}
              </div>

              {rolloutSummary.rollback_recommendations.length > 0 && (
                <div className="rounded-lg border border-red-700/50 bg-red-900/20 px-3 py-3">
                  <p className="text-sm font-medium text-red-300 mb-1">Rollback Recommended</p>
                  <div className="text-xs text-red-200 space-y-1">
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
        </div>

        {/* Test Result Alert */}
        {testResult && (
          <div className={`assistant-panel rounded-md p-4 ${
            testResult.success 
              ? 'bg-green-900/20 border border-green-500/30 text-green-400' 
              : 'bg-red-900/20 border border-red-500/30 text-red-400'
          }`}>
            <div className="flex items-center">
              <div className="flex-shrink-0">
                {testResult.success ? (
                  <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                  </svg>
                ) : (
                  <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                  </svg>
                )}
              </div>
              <div className="ml-3">
                <p className="text-sm font-medium">{testResult.message}</p>
              </div>
            </div>
          </div>
        )}

        {/* Settings Form */}
        <section>
          <div className="assistant-kicker mb-3">Core Runtime Configuration</div>
          <p className="mb-5 max-w-3xl text-sm text-[var(--assistant-text-soft)]">
            This is the main control surface for model routing, embeddings, background jobs, devices, and
            notification behavior.
          </p>
        </section>

        <div className="assistant-panel rounded-md">
          <form onSubmit={handleSubmit} className="p-6 space-y-6">
            <div className="border-b border-white/10 pb-6">
              <div className="assistant-kicker mb-3">Configuration Surface</div>
              <h2 className="font-display text-2xl font-semibold text-white">How Sara should think and run</h2>
              <p className="mt-3 max-w-3xl text-sm text-[var(--assistant-text-soft)]">
                Update the core provider, memory, sandbox, and notification behavior here. Changes apply to the
                live assistant runtime, not just this browser.
              </p>
            </div>

            {/* AI Provider Selection */}
            <div className="border-b border-gray-700 pb-6">
              <h3 className="text-lg font-medium text-white mb-4">AI Provider Selection</h3>
              <div className="space-y-4">
                <div>
                  <label htmlFor="ai_provider" className="block text-sm font-medium text-gray-300 mb-2">
                    Select Provider
                  </label>
                  <select
                    id="ai_provider"
                    value={aiProvider}
                    onChange={(e) => handleProviderChange(e.target.value as ProviderType)}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white"
                  >
                    <option value="local">Local (Ollama/LM Studio)</option>
                    <option value="gemini">Google Gemini</option>
                    <option value="openai">OpenAI</option>
                    <option value="codex">ChatGPT Codex (OAuth)</option>
                    <option value="claude">Anthropic Claude</option>
                    <option value="custom">Custom Configuration</option>
                  </select>
                  <p className="mt-1 text-xs text-gray-400">
                    Choose a provider to auto-configure URLs and models, or select Custom for manual setup
                  </p>
                </div>

                {(aiProvider === 'gemini' || aiProvider === 'openai' || aiProvider === 'claude') && (
                  <div>
                    <label htmlFor="openai_api_key" className="block text-sm font-medium text-gray-300 mb-2">
                      API Key
                    </label>
                    <input
                      type="password"
                      id="openai_api_key"
                      value={formData.openai_api_key || ''}
                      onChange={(e) => handleInputChange('openai_api_key', e.target.value)}
                      className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                      placeholder={
                        aiProvider === 'gemini' ? 'Enter Gemini API key' :
                        aiProvider === 'claude' ? 'Enter Claude API key (sk-ant-...)' :
                        'Enter OpenAI API key'
                      }
                    />
                    <p className="mt-1 text-xs text-gray-400">
                      {aiProvider === 'gemini'
                        ? 'Get your API key from https://aistudio.google.com/apikey'
                        : aiProvider === 'claude'
                        ? 'Get your API key from https://console.anthropic.com/settings/keys'
                        : 'Get your API key from https://platform.openai.com/api-keys'}
                    </p>
                  </div>
                )}

                {aiProvider === 'codex' && (
                  <div className="rounded-lg border border-gray-700 bg-gray-800/40 p-4">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <p className="text-sm font-medium text-gray-200">
                          ChatGPT OAuth Connection
                        </p>
                        <p className="text-xs text-gray-400 mt-1">
                          {codexOAuthLoading
                            ? 'Checking connection status...'
                            : codexOAuthStatus?.connected
                            ? `Connected${codexOAuthStatus.email ? ` as ${codexOAuthStatus.email}` : ''}`
                            : 'Not connected'}
                        </p>
                        {codexOAuthStatus?.expires_at && codexOAuthStatus.connected && (
                          <p className="text-xs text-gray-500 mt-1">
                            Token expiry: {new Date(codexOAuthStatus.expires_at).toLocaleString('en-US')}
                          </p>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={handleRefreshCodexOAuthStatus}
                          disabled={codexOAuthLoading || codexOAuthFetching}
                          className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-sm disabled:opacity-60"
                        >
                          {(codexOAuthLoading || codexOAuthFetching) ? 'Refreshing...' : 'Refresh Status'}
                        </button>
                        {!codexOAuthStatus?.connected ? (
                          <button
                            type="button"
                            onClick={handleConnectCodexOAuth}
                            disabled={startCodexOAuthMutation.isPending}
                            className="px-3 py-2 bg-teal-600 hover:bg-teal-500 text-white rounded-lg text-sm disabled:opacity-60"
                          >
                            {startCodexOAuthMutation.isPending ? 'Starting...' : 'Connect ChatGPT'}
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={handleDisconnectCodexOAuth}
                            disabled={disconnectCodexOAuthMutation.isPending}
                            className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-sm disabled:opacity-60"
                          >
                            {disconnectCodexOAuthMutation.isPending ? 'Disconnecting...' : 'Disconnect'}
                          </button>
                        )}
                      </div>
                    </div>
                    <p className="mt-3 text-xs text-gray-400">
                      Uses your ChatGPT subscription via OAuth. No API key required. If prompted, paste the localhost callback URL back here to complete.
                    </p>
                  </div>
                )}

                {aiProvider === 'claude' && (
                  <div>
                    <label htmlFor="claude_model" className="block text-sm font-medium text-gray-300 mb-2">
                      Claude Model
                    </label>
                    <select
                      id="claude_model"
                      value={formData.openai_model || 'claude-sonnet-4-6'}
                      onChange={(e) => handleInputChange('openai_model', e.target.value)}
                      className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white"
                    >
                      {CLAUDE_MODELS.map((model) => (
                        <option key={model.value} value={model.value}>{model.label}</option>
                      ))}
                    </select>
                    <p className="mt-1 text-xs text-gray-400">
                      Select the Claude model to use. Opus is most capable, Haiku is fastest.
                    </p>
                  </div>
                )}
              </div>
            </div>

            {/* AI Model Settings */}
            <div>
              <h3 className="text-lg font-medium text-white mb-4">AI Model Configuration</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                <div>
                  <label htmlFor="openai_base_url" className="block text-sm font-medium text-gray-300 mb-2">
                    AI Base URL
                  </label>
                  <input
                    type="url"
                    id="openai_base_url"
                    value={formData.openai_base_url || ''}
                    onChange={(e) => handleInputChange('openai_base_url', e.target.value)}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                    placeholder={settings?.openai_base_url || 'http://100.104.68.115:11434/v1'}
                  />
                  <p className="mt-1 text-xs text-gray-400">OpenAI-compatible API endpoint</p>
                </div>

                <div>
                  <label htmlFor="openai_model" className="block text-sm font-medium text-gray-300 mb-2">
                    Main AI Model
                  </label>
                  <input
                    type="text"
                    id="openai_model"
                    value={formData.openai_model || ''}
                    onChange={(e) => handleInputChange('openai_model', e.target.value)}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                    placeholder={settings?.openai_model || 'gpt-oss:20b'}
                  />
                  <p className="mt-1 text-xs text-gray-400">Model name to use for chat and reasoning</p>
                </div>

                <div>
                  <label htmlFor="openai_notification_model" className="block text-sm font-medium text-gray-300 mb-2">
                    Notification Model
                  </label>
                  <input
                    type="text"
                    id="openai_notification_model"
                    value={formData.openai_notification_model || ''}
                    onChange={(e) => handleInputChange('openai_notification_model', e.target.value)}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                    placeholder={settings?.openai_notification_model || 'gpt-oss:20b'}
                  />
                  <p className="mt-1 text-xs text-gray-400">Faster model for generating push notifications</p>
                </div>
              </div>
            </div>

            {/* Embedding Settings */}
            <div className="border-t border-gray-700 pt-6">
              <h3 className="text-lg font-medium text-white mb-4">Embedding Configuration</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label htmlFor="embedding_base_url" className="block text-sm font-medium text-gray-300 mb-2">
                    Embedding Base URL
                  </label>
                  <input
                    type="url"
                    id="embedding_base_url"
                    value={formData.embedding_base_url || ''}
                    onChange={(e) => handleInputChange('embedding_base_url', e.target.value)}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                    placeholder={settings?.embedding_base_url || 'http://100.104.68.115:11434'}
                  />
                  <p className="mt-1 text-xs text-gray-400">Embedding service endpoint</p>
                </div>

                <div>
                  <label htmlFor="embedding_model" className="block text-sm font-medium text-gray-300 mb-2">
                    Embedding Model
                  </label>
                  <input
                    type="text"
                    id="embedding_model"
                    value={formData.embedding_model || ''}
                    onChange={(e) => handleInputChange('embedding_model', e.target.value)}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                    placeholder={settings?.embedding_model || 'bge-m3'}
                  />
                  <p className="mt-1 text-xs text-gray-400">Model for generating embeddings</p>
                </div>

                <div>
                  <label htmlFor="embedding_dimension" className="block text-sm font-medium text-gray-300 mb-2">
                    Embedding Dimension
                  </label>
                  <input
                    type="number"
                    id="embedding_dimension"
                    value={formData.embedding_dimension || ''}
                    onChange={(e) => handleInputChange('embedding_dimension', parseInt(e.target.value))}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                    placeholder={settings?.embedding_dimension?.toString() || '1024'}
                    min="1"
                    max="4096"
                  />
                  <p className="mt-1 text-xs text-gray-400">Vector dimension for embeddings</p>
                </div>
              </div>
            </div>

            {/* Background Processing Settings */}
            <div className="border-t border-gray-700 pt-6">
              <h3 className="text-lg font-medium text-white mb-4">Background Processing</h3>
              <p className="text-gray-400 text-sm mb-4">
                Configure the models used for dreaming, memory consolidation, and other automated background tasks.
                These settings are separate from your chat model selection.
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label htmlFor="bg_llm_primary_url" className="block text-sm font-medium text-gray-300 mb-2">
                    Primary URL
                  </label>
                  <input
                    type="url"
                    id="bg_llm_primary_url"
                    value={formData.bg_llm_primary_url || ''}
                    onChange={(e) => handleInputChange('bg_llm_primary_url', e.target.value)}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                    placeholder="http://100.104.68.115:11434/v1"
                  />
                  <p className="mt-1 text-xs text-gray-400">Main endpoint for background tasks</p>
                </div>

                <div>
                  <label htmlFor="bg_llm_primary_model" className="block text-sm font-medium text-gray-300 mb-2">
                    Primary Model
                  </label>
                  <input
                    type="text"
                    id="bg_llm_primary_model"
                    value={formData.bg_llm_primary_model || ''}
                    onChange={(e) => handleInputChange('bg_llm_primary_model', e.target.value)}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                    placeholder="gpt-oss:20b"
                  />
                  <p className="mt-1 text-xs text-gray-400">Model for deep analysis tasks</p>
                </div>

                <div>
                  <label htmlFor="bg_llm_fallback_url" className="block text-sm font-medium text-gray-300 mb-2">
                    Fallback URL
                  </label>
                  <input
                    type="url"
                    id="bg_llm_fallback_url"
                    value={formData.bg_llm_fallback_url || ''}
                    onChange={(e) => handleInputChange('bg_llm_fallback_url', e.target.value)}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                    placeholder="http://100.104.68.115:11434/v1"
                  />
                  <p className="mt-1 text-xs text-gray-400">Backup endpoint if primary fails</p>
                </div>

                <div>
                  <label htmlFor="bg_llm_fallback_model" className="block text-sm font-medium text-gray-300 mb-2">
                    Fallback Model
                  </label>
                  <input
                    type="text"
                    id="bg_llm_fallback_model"
                    value={formData.bg_llm_fallback_model || ''}
                    onChange={(e) => handleInputChange('bg_llm_fallback_model', e.target.value)}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                    placeholder="gpt-oss:20b"
                  />
                  <p className="mt-1 text-xs text-gray-400">Faster model for quick background tasks</p>
                </div>
              </div>
            </div>

            {/* Sandbox VM Settings */}
            <div className="border-t border-gray-700 pt-6">
              <h3 className="text-lg font-medium text-white mb-4">Sandbox VM</h3>
              <p className="text-gray-400 text-sm mb-4">
                Configure the remote VM where Sara dispatches Claude Code agents to run tasks autonomously.
              </p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div>
                  <label htmlFor="vm_sandbox_host" className="block text-sm font-medium text-gray-300 mb-2">
                    VM Host
                  </label>
                  <input
                    type="text"
                    id="vm_sandbox_host"
                    value={formData.vm_sandbox_host || ''}
                    onChange={(e) => handleInputChange('vm_sandbox_host', e.target.value)}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                    placeholder="10.185.1.176"
                  />
                  <p className="mt-1 text-xs text-gray-400">IP address or hostname of the sandbox VM</p>
                </div>

                <div>
                  <label htmlFor="vm_sandbox_username" className="block text-sm font-medium text-gray-300 mb-2">
                    SSH Username
                  </label>
                  <input
                    type="text"
                    id="vm_sandbox_username"
                    value={formData.vm_sandbox_username || ''}
                    onChange={(e) => handleInputChange('vm_sandbox_username', e.target.value)}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                    placeholder="sara"
                  />
                  <p className="mt-1 text-xs text-gray-400">SSH user on the VM</p>
                </div>

                <div>
                  <label htmlFor="vm_sandbox_ssh_key_path" className="block text-sm font-medium text-gray-300 mb-2">
                    SSH Key Path
                  </label>
                  <input
                    type="text"
                    id="vm_sandbox_ssh_key_path"
                    value={formData.vm_sandbox_ssh_key_path || ''}
                    onChange={(e) => handleInputChange('vm_sandbox_ssh_key_path', e.target.value)}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                    placeholder="~/.ssh/sara_agent"
                  />
                  <p className="mt-1 text-xs text-gray-400">Path to SSH private key on the server</p>
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
                  className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-sm disabled:opacity-60"
                >
                  {vmTestLoading ? 'Testing...' : 'Test Connection'}
                </button>
                {vmTestResult && (
                  <span className={`text-sm ${vmTestResult.status === 'connected' ? 'text-green-400' : 'text-red-400'}`}>
                    {vmTestResult.status === 'connected'
                      ? `Connected to ${vmTestResult.host}`
                      : `Connection failed: ${vmTestResult.status}`}
                  </span>
                )}
              </div>
            </div>

            {/* Desktop Agent Settings */}
            <div className="border-t border-gray-700 pt-6">
              <h3 className="text-lg font-medium text-white mb-4">Desktop Agent & Vision</h3>
              <p className="text-gray-400 text-sm mb-4">
                Configure the desktop agent's vision model for screenshot analysis and cross-device features.
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label htmlFor="vision_model" className="block text-sm font-medium text-gray-300 mb-2">
                    Vision Model
                  </label>
                  <input
                    type="text"
                    id="vision_model"
                    defaultValue="qwen3-vl:latest"
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                    placeholder="qwen3-vl:latest"
                  />
                  <p className="mt-1 text-xs text-gray-400">Ollama vision model for screenshot analysis</p>
                </div>

                <div>
                  <label htmlFor="vision_endpoint" className="block text-sm font-medium text-gray-300 mb-2">
                    Vision Endpoint
                  </label>
                  <input
                    type="url"
                    id="vision_endpoint"
                    defaultValue="http://10.185.1.8:11434"
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                    placeholder="http://10.185.1.8:11434"
                  />
                  <p className="mt-1 text-xs text-gray-400">Ollama server for vision model</p>
                </div>

                <div>
                  <label htmlFor="screenshot_interval" className="block text-sm font-medium text-gray-300 mb-2">
                    Screenshot Interval (seconds)
                  </label>
                  <input
                    type="number"
                    id="screenshot_interval"
                    defaultValue={30}
                    min={10}
                    max={300}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-teal-500 text-white placeholder-gray-400"
                  />
                  <p className="mt-1 text-xs text-gray-400">How often the desktop agent captures screenshots</p>
                </div>

                <div className="flex items-center justify-between bg-gray-800 border border-gray-700 rounded-lg p-4">
                  <div>
                    <div className="text-sm font-medium text-white">Screenshot Capture</div>
                    <div className="text-xs text-gray-400">Enable periodic screenshot capture</div>
                  </div>
                  <label className="inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      className="sr-only peer"
                      defaultChecked={true}
                    />
                    <span className="w-10 h-6 bg-gray-600 rounded-full p-1 transition-colors duration-200 peer-checked:bg-teal-600">
                      <span className="block w-4 h-4 bg-white rounded-full transform transition-transform duration-200 peer-checked:translate-x-4"></span>
                    </span>
                  </label>
                </div>

                <div className="flex items-center justify-between bg-gray-800 border border-gray-700 rounded-lg p-4">
                  <div>
                    <div className="text-sm font-medium text-white">Cross-Device Commands</div>
                    <div className="text-xs text-gray-400">Route commands to active device</div>
                  </div>
                  <label className="inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      className="sr-only peer"
                      defaultChecked={true}
                    />
                    <span className="w-10 h-6 bg-gray-600 rounded-full p-1 transition-colors duration-200 peer-checked:bg-teal-600">
                      <span className="block w-4 h-4 bg-white rounded-full transform transition-transform duration-200 peer-checked:translate-x-4"></span>
                    </span>
                  </label>
                </div>
              </div>
            </div>

            {/* Notification Preferences */}
            <div className="border-t border-gray-700 pt-6">
              <h3 className="text-lg font-medium text-white mb-4">Notification Preferences</h3>
              <p className="text-gray-400 text-sm mb-4">
                Control which categories of proactive notifications Sara can send you.
                Disabled categories are blocked at the notification pipeline level.
              </p>
              {notifPrefsLoading ? (
                <p className="text-sm text-gray-500">Loading preferences...</p>
              ) : (
                <div className="space-y-3">
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
                        className="flex items-center justify-between bg-gray-800 border border-gray-700 rounded-lg p-4"
                      >
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium text-white">{info.label}</div>
                          <div className="text-xs text-gray-400 mt-0.5">{info.desc}</div>
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
                          <span className={`w-10 h-6 rounded-full p-1 transition-colors duration-200 ${pref.enabled ? 'bg-teal-600' : 'bg-gray-600'}`}>
                            <span className={`block w-4 h-4 bg-white rounded-full transform transition-transform duration-200 ${pref.enabled ? 'translate-x-4' : 'translate-x-0'}`}></span>
                          </span>
                        </label>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            {/* Token Usage Statistics */}
            <div className="border-t border-gray-700 pt-6">
              <h3 className="text-lg font-medium text-white mb-4">Token Usage Statistics</h3>
              <TokenUsageStats />
            </div>

            {/* Appearance */}
            <div className="border-t border-gray-700 pt-6">
              <h3 className="text-lg font-medium text-white mb-4">Appearance</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="flex items-center justify-between bg-gray-800 border border-gray-700 rounded-lg p-4">
                  <div>
                    <div className="text-sm font-medium text-white">Calm Mode</div>
                    <div className="text-xs text-gray-400">Reduces visual intensity and tempo.</div>
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
                    <span className="w-10 h-6 bg-gray-600 rounded-full p-1 transition-colors duration-200 peer-checked:bg-teal-600">
                      <span className="block w-4 h-4 bg-white rounded-full transform transition-transform duration-200 translate-x-0 peer-checked:translate-x-4"></span>
                    </span>
                  </label>
                </div>

                <div className="flex items-center justify-between bg-gray-800 border border-gray-700 rounded-lg p-4">
                  <div>
                    <div className="text-sm font-medium text-white">Enhanced Visuals</div>
                    <div className="text-xs text-gray-400">Enable richer particle effects on capable devices.</div>
                  </div>
                  <label className="inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      className="sr-only"
                      defaultChecked={getEnhancedVisuals()}
                      onChange={(e) => setEnhancedVisuals(e.target.checked)}
                    />
                    <span className="w-10 h-6 bg-gray-600 rounded-full p-1 transition-colors duration-200 peer-checked:bg-teal-600">
                      <span className="block w-4 h-4 bg-white rounded-full transform transition-transform duration-200 translate-x-0 peer-checked:translate-x-4"></span>
                    </span>
                  </label>
                </div>
              </div>
              <p className="mt-2 text-xs text-gray-400">Visual preference changes take effect immediately. Calm Mode reduces animation intensity and tempo.</p>
            </div>

            {/* Actions */}
            <div className="border-t border-gray-700 pt-6 flex flex-col sm:flex-row sm:justify-between sm:items-center space-y-3 sm:space-y-0 sm:space-x-3">
              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={handleTestConnection}
                  disabled={testSettingsMutation.isPending}
                  className="px-4 py-2 text-sm font-medium text-teal-400 bg-teal-900/20 border border-teal-500/30 rounded-lg hover:bg-teal-900/30 focus:ring-2 focus:ring-teal-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200 tap-target"
                >
                  {testSettingsMutation.isPending ? (
                    <div className="flex items-center space-x-2">
                      <div className="w-4 h-4 border-2 border-teal-400 border-t-transparent rounded-full animate-spin"></div>
                      <span>Testing...</span>
                    </div>
                  ) : (
                    'Test Connection'
                  )}
                </button>

                <button
                  type="button"
                  onClick={handleReset}
                  className="px-4 py-2 text-sm font-medium text-gray-300 bg-gray-800 border border-gray-700 rounded-lg hover:bg-gray-700 focus:ring-2 focus:ring-gray-500 focus:ring-offset-2 transition-colors duration-200 tap-target"
                >
                  Reset
                </button>

                <button
                  type="button"
                  onClick={() => {
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
                  className="px-4 py-2 text-sm font-medium text-orange-400 bg-orange-900/20 border border-orange-500/30 rounded-lg hover:bg-orange-900/30 focus:ring-2 focus:ring-orange-500 focus:ring-offset-2 transition-colors duration-200 tap-target"
                >
                  Clear Saved URLs
                </button>
              </div>

              <button
                type="submit"
                disabled={updateSettingsMutation.isPending}
                className="px-6 py-2 text-sm font-medium text-white bg-teal-600 rounded-lg hover:bg-teal-700 focus:ring-2 focus:ring-teal-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200 tap-target"
              >
                {updateSettingsMutation.isPending ? (
                  <div className="flex items-center space-x-2">
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                    <span>Saving...</span>
                  </div>
                ) : (
                  'Save Settings'
                )}
              </button>
            </div>
          </form>
        </div>

        <section>
          <div className="assistant-kicker mb-3">Devices, Cognition, and History</div>
          <p className="mb-5 max-w-3xl text-sm text-[var(--assistant-text-soft)]">
            Deeper assistant workspaces live here: desktop runtime setup, connected devices, and brief history.
          </p>
        </section>

        {/* Desktop App Downloads */}
        <DesktopAppDownloads />

        {/* Connected Devices */}
        <ConnectedDevices />

        {/* Brief Archive */}
        <SaraBriefArchive />

        {/* Developer Tools */}
        <div className="assistant-panel rounded-md p-6">
          <div className="flex items-center mb-4">
            <svg className="w-6 h-6 text-purple-400 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
            </svg>
            <div>
              <div className="assistant-kicker mb-2">Developer Surface</div>
              <h3 className="font-display text-2xl font-semibold text-white">Developer Tools</h3>
            </div>
          </div>

          <p className="text-sm text-[var(--assistant-text-soft)] mb-4">
            Experimental features for testing and development.
          </p>

          <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-lg">🧪</span>
                  <h4 className="text-white font-medium">Orchestrator Lab</h4>
                </div>
                <p className="text-xs text-gray-400 mt-1">
                  Test multi-agent task orchestration with live visualization
                </p>
                <div className="flex gap-4 mt-2 text-xs text-gray-500">
                  <span>Orchestrator: <span className="text-teal-400">qwen3-vl:30b</span></span>
                  <span>Workers: <span className="text-purple-400">ministral-3</span></span>
                </div>
              </div>
              <button
                onClick={() => {
                  // Navigate to orchestrator lab - this will be handled by parent
                  const event = new CustomEvent('navigate', { detail: { view: 'orchestrator-lab' } })
                  window.dispatchEvent(event)
                }}
                className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition text-sm font-medium flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Open Lab
              </button>
            </div>
          </div>
        </div>

        {/* Information */}
        <div className="mt-8 bg-blue-900/20 border border-blue-500/30 rounded-lg p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-blue-400" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3">
              <h3 className="text-sm font-medium text-blue-400">Information</h3>
              <div className="mt-1 text-sm text-blue-300">
                <p>Changes to these settings will affect how Sara processes your requests, generates responses, and creates push notifications. The notification model should be smaller/faster for quick message generation. Make sure your AI and embedding services are accessible before saving.</p>
                <p className="mt-2"><strong>Auto-Save:</strong> URL and model settings are automatically saved to your browser's local storage as you type, so you don't need to re-enter them on each visit.</p>
              </div>
            </div>

            {/* Memory Maintenance */}
            <div className="border-t border-gray-700 pt-6">
              <h3 className="text-lg font-medium text-white mb-4">Memory Maintenance</h3>
              <p className="text-gray-400 text-sm mb-4">Run nightly consolidation on demand for yesterday’s traces.</p>
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
                className="px-4 py-2 bg-indigo-600/20 text-indigo-300 rounded-lg hover:bg-indigo-600/30 text-sm"
              >
                Run Consolidation (Yesterday)
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
