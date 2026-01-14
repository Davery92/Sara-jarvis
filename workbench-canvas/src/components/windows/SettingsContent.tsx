import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Settings, Cpu, Monitor, BarChart3, Loader2, Save, RefreshCw, Trash2, Check } from 'lucide-react'
import { settingsApi, type AISettings, type TokenStats, type Device } from '../../services/api'
import type { SettingsWindowData } from '../../types'

interface SettingsContentProps {
  data: SettingsWindowData
  windowId: string
}

type Tab = 'ai' | 'devices' | 'tokens'

export default function SettingsContent({ data }: SettingsContentProps) {
  const [activeTab, setActiveTab] = useState<Tab>(data.section || 'ai')

  const tabs: { id: Tab; label: string; icon: typeof Cpu }[] = [
    { id: 'ai', label: 'AI Config', icon: Cpu },
    { id: 'devices', label: 'Devices', icon: Monitor },
    { id: 'tokens', label: 'Usage', icon: BarChart3 },
  ]

  return (
    <div className="flex flex-col h-full bg-canvas-bg">
      {/* Tabs */}
      <div className="flex border-b border-canvas-border">
        {tabs.map((tab) => {
          const Icon = tab.icon
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 px-4 py-3 flex items-center justify-center gap-2 text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? 'text-white border-b-2 border-blue-500 bg-canvas-surface/50'
                  : 'text-canvas-muted hover:text-white hover:bg-canvas-surface/30'
              }`}
            >
              <Icon size={16} />
              {tab.label}
            </button>
          )
        })}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-4">
        {activeTab === 'ai' && <AIConfigTab />}
        {activeTab === 'devices' && <DevicesTab />}
        {activeTab === 'tokens' && <TokensTab />}
      </div>
    </div>
  )
}

function AIConfigTab() {
  const queryClient = useQueryClient()
  const [formData, setFormData] = useState<Partial<AISettings>>({})
  const [saved, setSaved] = useState(false)

  const { data: settings, isLoading, error } = useQuery({
    queryKey: ['settings', 'ai'],
    queryFn: settingsApi.getAI,
  })

  const updateMutation = useMutation({
    mutationFn: settingsApi.updateAI,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'ai'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })

  const handleSave = () => {
    if (Object.keys(formData).length > 0) {
      updateMutation.mutate(formData)
    }
  }

  const handleChange = (field: keyof AISettings, value: string | number) => {
    setFormData((prev) => ({ ...prev, [field]: value }))
  }

  if (isLoading) {
    return <LoadingState message="Loading AI settings..." />
  }

  if (error) {
    return <ErrorState message="Failed to load AI settings" />
  }

  const currentValues = { ...settings, ...formData }

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm text-canvas-muted mb-1">Base URL</label>
        <input
          type="text"
          value={currentValues.openai_base_url || ''}
          onChange={(e) => handleChange('openai_base_url', e.target.value)}
          className="w-full px-3 py-2 bg-canvas-surface rounded border border-canvas-border text-white focus:outline-none focus:border-blue-500"
        />
      </div>

      <div>
        <label className="block text-sm text-canvas-muted mb-1">Model</label>
        <input
          type="text"
          value={currentValues.openai_model || ''}
          onChange={(e) => handleChange('openai_model', e.target.value)}
          className="w-full px-3 py-2 bg-canvas-surface rounded border border-canvas-border text-white focus:outline-none focus:border-blue-500"
        />
      </div>

      <div>
        <label className="block text-sm text-canvas-muted mb-1">Notification Model</label>
        <input
          type="text"
          value={currentValues.openai_notification_model || ''}
          onChange={(e) => handleChange('openai_notification_model', e.target.value)}
          className="w-full px-3 py-2 bg-canvas-surface rounded border border-canvas-border text-white focus:outline-none focus:border-blue-500"
        />
      </div>

      <div className="pt-2 border-t border-canvas-border">
        <h3 className="text-sm font-medium text-white mb-3">Embedding Settings</h3>

        <div className="space-y-3">
          <div>
            <label className="block text-sm text-canvas-muted mb-1">Embedding Base URL</label>
            <input
              type="text"
              value={currentValues.embedding_base_url || ''}
              onChange={(e) => handleChange('embedding_base_url', e.target.value)}
              className="w-full px-3 py-2 bg-canvas-surface rounded border border-canvas-border text-white focus:outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm text-canvas-muted mb-1">Embedding Model</label>
            <input
              type="text"
              value={currentValues.embedding_model || ''}
              onChange={(e) => handleChange('embedding_model', e.target.value)}
              className="w-full px-3 py-2 bg-canvas-surface rounded border border-canvas-border text-white focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>
      </div>

      <div className="flex justify-end pt-4">
        <button
          onClick={handleSave}
          disabled={updateMutation.isPending || Object.keys(formData).length === 0}
          className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:opacity-50 rounded text-white font-medium transition-colors"
        >
          {saved ? (
            <>
              <Check size={16} />
              Saved
            </>
          ) : updateMutation.isPending ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              Saving...
            </>
          ) : (
            <>
              <Save size={16} />
              Save Changes
            </>
          )}
        </button>
      </div>
    </div>
  )
}

function DevicesTab() {
  const queryClient = useQueryClient()

  const { data, isLoading, error } = useQuery({
    queryKey: ['settings', 'devices'],
    queryFn: settingsApi.getDevices,
  })

  const removeMutation = useMutation({
    mutationFn: settingsApi.removeDevice,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings', 'devices'] }),
  })

  if (isLoading) {
    return <LoadingState message="Loading devices..." />
  }

  if (error) {
    return <ErrorState message="Failed to load devices" />
  }

  const devices = data?.devices || []

  if (devices.length === 0) {
    return (
      <div className="text-center text-canvas-muted py-8">
        <Monitor size={48} className="mx-auto mb-4 opacity-30" />
        <p>No connected devices</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {devices.map((device) => (
        <div
          key={device.device_id}
          className="p-4 bg-canvas-surface rounded-lg border border-canvas-border"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="font-medium text-white">
              {device.friendly_name || device.hostname || device.device_id.slice(0, 8)}
            </span>
            <div className="flex items-center gap-2">
              <span
                className={`w-2 h-2 rounded-full ${
                  device.is_online ? 'bg-green-500' : 'bg-canvas-muted'
                }`}
              />
              <button
                onClick={() => removeMutation.mutate(device.device_id)}
                className="p-1 text-red-500 hover:bg-canvas-elevated rounded transition-colors"
                title="Remove device"
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
          <div className="text-sm text-canvas-muted space-y-1">
            {device.platform && <div>Platform: {device.platform}</div>}
            {device.activity_level && <div>Activity: {device.activity_level}</div>}
            {device.last_activity_at && (
              <div>Last active: {new Date(device.last_activity_at).toLocaleString()}</div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

function TokensTab() {
  const queryClient = useQueryClient()

  const { data: stats, isLoading, error } = useQuery({
    queryKey: ['settings', 'tokens'],
    queryFn: settingsApi.getTokenStats,
  })

  const resetMutation = useMutation({
    mutationFn: settingsApi.resetTokenStats,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings', 'tokens'] }),
  })

  if (isLoading) {
    return <LoadingState message="Loading token usage..." />
  }

  if (error) {
    return <ErrorState message="Failed to load token usage" />
  }

  const formatNumber = (n: number) => n.toLocaleString()

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <StatCard label="Total Tokens" value={formatNumber(stats?.total_tokens || 0)} />
        <StatCard label="Total Requests" value={formatNumber(stats?.total_requests || 0)} />
        <StatCard label="Prompt Tokens" value={formatNumber(stats?.total_prompt_tokens || 0)} />
        <StatCard label="Completion Tokens" value={formatNumber(stats?.total_completion_tokens || 0)} />
      </div>

      {stats?.last_reset_at && (
        <div className="text-sm text-canvas-muted">
          Last reset: {new Date(stats.last_reset_at).toLocaleString()}
        </div>
      )}

      <div className="flex justify-end pt-4 border-t border-canvas-border">
        <button
          onClick={() => resetMutation.mutate()}
          disabled={resetMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded font-medium transition-colors"
        >
          {resetMutation.isPending ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <RefreshCw size={16} />
          )}
          Reset Stats
        </button>
      </div>
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-4 bg-canvas-surface rounded-lg border border-canvas-border">
      <div className="text-2xl font-bold text-white">{value}</div>
      <div className="text-sm text-canvas-muted">{label}</div>
    </div>
  )
}

function LoadingState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-full text-canvas-muted">
      <Loader2 className="animate-spin mr-2" size={20} />
      {message}
    </div>
  )
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-full text-red-400">
      {message}
    </div>
  )
}
