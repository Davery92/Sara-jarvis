import { useState, useEffect } from 'react'
import {
  getCalmMode, setCalmMode, getEnhancedVisuals, setEnhancedVisuals,
  getAIBaseUrl, setAIBaseUrl, getAIModel, setAIModel, getAINotificationModel, setAINotificationModel,
  getEmbeddingBaseUrl, setEmbeddingBaseUrl, getEmbeddingModel, setEmbeddingModel,
  getEmbeddingDimension, setEmbeddingDimension
} from '../utils/prefs'
import { spriteBus } from '../state/spriteBus'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient, AISettingsUpdate } from '../api/client'
import { GTKYTrigger } from '../components/onboarding/GTKYTrigger'
import { APP_CONFIG } from '../config'

function AgentStatus() {
  const { data: agentStatus } = useQuery({
    queryKey: ['shadow', 'agent-status'],
    queryFn: () => apiClient.getShadowAgentStatus(),
    refetchInterval: 10000, // Poll every 10 seconds
  })

  if (!agentStatus || agentStatus.total_active === 0) {
    return (
      <div className="mt-4 p-3 bg-gray-800/50 border border-gray-700 rounded-lg">
        <div className="flex items-center">
          <div className="w-2 h-2 bg-gray-500 rounded-full mr-3"></div>
          <p className="text-sm text-gray-400">No agents connected (agents appear when Shadow session is active)</p>
        </div>
      </div>
    )
  }

  return (
    <div className="mt-4 space-y-2">
      <h4 className="text-sm font-medium text-white">Connected Agents</h4>
      {agentStatus.agents.map((agent: any, idx: number) => (
        <div key={idx} className="p-3 bg-green-900/20 border border-green-500/30 rounded-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center">
              <div className="w-2 h-2 bg-green-500 rounded-full mr-3 animate-pulse"></div>
              <div>
                <p className="text-sm font-medium text-green-300">Agent Online</p>
                <p className="text-xs text-gray-400">
                  Monitoring: {agent.monitoring.browser && 'Browser'} {agent.monitoring.browser && agent.monitoring.editor && '+ '}{agent.monitoring.editor && 'VS Code'}
                </p>
              </div>
            </div>
            <div className="text-right">
              <p className="text-xs text-gray-400">{agent.event_count} events</p>
              <p className="text-xs text-gray-500">Last seen: {new Date(agent.last_seen).toLocaleTimeString()}</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

export default function Settings() {
  const [formData, setFormData] = useState<AISettingsUpdate>({
    openai_base_url: getAIBaseUrl(),
    openai_model: getAIModel(),
    openai_notification_model: getAINotificationModel(),
    embedding_base_url: getEmbeddingBaseUrl(),
    embedding_model: getEmbeddingModel(),
    embedding_dimension: getEmbeddingDimension(),
  })
  const [showGTKY, setShowGTKY] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [fitnessPrompt, setFitnessPrompt] = useState('')
  const [fitnessSaveResult, setFitnessSaveResult] = useState<{ success: boolean; message: string } | null>(null)
  const queryClient = useQueryClient()

  // Fetch current AI settings
  const { data: settings, isLoading } = useQuery({
    queryKey: ['settings', 'ai'],
    queryFn: () => apiClient.getAISettings(),
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

  // Initialize form data when settings load, preferring localStorage values
  useEffect(() => {
    if (settings) {
      setFormData({
        // Use localStorage values if available, otherwise fall back to server settings
        openai_base_url: getAIBaseUrl() || settings.openai_base_url,
        openai_model: getAIModel() || settings.openai_model,
        openai_notification_model: getAINotificationModel() || settings.openai_notification_model,
        embedding_base_url: getEmbeddingBaseUrl() || settings.embedding_base_url,
        embedding_model: getEmbeddingModel() || settings.embedding_model,
        embedding_dimension: getEmbeddingDimension() || settings.embedding_dimension,
      })
    }
  }, [settings])

  // Fetch fitness settings
  useEffect(() => {
    const fetchFitnessSettings = async () => {
      try {
        const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/settings`, {
          credentials: 'include',
        })
        if (response.ok) {
          const data = await response.json()
          setFitnessPrompt(data.system_prompt || '')
        }
      } catch (error) {
        console.error('Failed to fetch fitness settings:', error)
      }
    }
    fetchFitnessSettings()
  }, [])

  const handleInputChange = (field: keyof AISettingsUpdate, value: string | number) => {
    setFormData(prev => ({
      ...prev,
      [field]: value
    }))
    
    // Save to localStorage immediately for persistence
    switch (field) {
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
    const cleaned: AISettingsUpdate = {}
    Object.entries(formData).forEach(([k, v]) => {
      if (v !== '' && v !== undefined && v !== null) {
        // @ts-ignore - dynamic assembly of payload
        cleaned[k] = v
      }
    })
    updateSettingsMutation.mutate(cleaned)
  }

  const handleTestConnection = () => {
    testSettingsMutation.mutate()
  }

  const handleReset = () => {
    // Reset to localStorage values (or defaults if none saved)
    const resetData = {
      openai_base_url: getAIBaseUrl(),
      openai_model: getAIModel(),
      openai_notification_model: getAINotificationModel(),
      embedding_base_url: getEmbeddingBaseUrl(),
      embedding_model: getEmbeddingModel(),
      embedding_dimension: getEmbeddingDimension(),
    }
    setFormData(resetData)
  }

  const handleSaveFitnessPrompt = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ system_prompt: fitnessPrompt }),
      })
      if (response.ok) {
        setFitnessSaveResult({ success: true, message: 'Fitness system prompt saved successfully!' })
        setTimeout(() => setFitnessSaveResult(null), 3000)
      } else {
        setFitnessSaveResult({ success: false, message: 'Failed to save fitness prompt' })
        setTimeout(() => setFitnessSaveResult(null), 5000)
      }
    } catch (error) {
      setFitnessSaveResult({ success: false, message: 'Failed to save fitness prompt' })
      setTimeout(() => setFitnessSaveResult(null), 5000)
    }
  }

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading settings...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 py-8">
      <div className="max-w-4xl mx-auto px-4">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-white mb-2">Settings</h1>
          <p className="text-gray-400">Configure AI models, embeddings, and personalization</p>
        </div>

        {/* Test Result Alert */}
        {testResult && (
          <div className={`mb-6 p-4 rounded-lg ${
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
        <div className="bg-card border border-card rounded-xl">
          <form onSubmit={handleSubmit} className="p-6 space-y-6">
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
                    placeholder={settings?.openai_model || 'gpt-oss:120b'}
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

            {/* Appearance & Sprite */}
            <div className="border-t border-gray-700 pt-6">
              <h3 className="text-lg font-medium text-white mb-4">Appearance & Sprite</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="flex items-center justify-between bg-gray-800 border border-gray-700 rounded-lg p-4">
                  <div>
                    <div className="text-sm font-medium text-white">Calm Mode</div>
                    <div className="text-xs text-gray-400">Keep the sprite’s visuals gentle even when active.</div>
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
                          spriteBus.setVisuals({ energyScale: 0.985, tempoBreatheSec: 5.2, tempoShimmerSec: 13, brightnessScale: 0.975, saturationScale: 0.94 }, 'calm:toggle')
                        } else {
                          spriteBus.setVisuals({ energyScale: 1.0, tempoBreatheSec: 3.6, tempoShimmerSec: 11, brightnessScale: 1.0, saturationScale: 1.0 }, 'calm:toggle')
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
                      openai_model: 'gpt-oss:120b',
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

        {/* Voice Agent Downloads */}
        <div className="mt-8 bg-card border border-card rounded-xl p-6">
          <div className="flex items-center mb-4">
            <svg className="w-6 h-6 text-green-400 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
            </svg>
            <h3 className="text-lg font-medium text-white">🎙️ Voice Control Agent</h3>
          </div>

          <p className="text-gray-400 text-sm mb-6">
            Download the voice-controlled desktop agent. Say "sarah" to activate voice commands and interact with Sara hands-free.
            Supports Shadow Mode, reminders, notes, and all Sara features via voice.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Windows Voice Agent */}
            <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
              <div className="flex items-center mb-3">
                <svg className="w-8 h-8 text-blue-400 mr-3" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.9-1.801" />
                </svg>
                <div>
                  <h4 className="text-white font-medium">Windows Voice Agent</h4>
                  <p className="text-xs text-gray-400">Single-file installer</p>
                </div>
              </div>
              <p className="text-sm text-gray-300 mb-3">
                Wake word detection, voice commands, system tray control. No installation required!
              </p>
              <a
                href="http://10.185.1.180:8000/api/agent/downloads/windows"
                download="SaraShadowAgent-Installer.exe"
                className="inline-flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition text-sm font-medium w-full justify-center"
              >
                <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                Download for Windows
              </a>
              <p className="text-xs text-gray-500 mt-2">
                Just run the .exe - it will appear in your system tray. Say "sarah" to activate!
              </p>
            </div>

            {/* macOS Voice Agent */}
            <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
              <div className="flex items-center mb-3">
                <svg className="w-8 h-8 text-purple-400 mr-3" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z" />
                </svg>
                <div>
                  <h4 className="text-white font-medium">macOS Voice Agent</h4>
                  <p className="text-xs text-gray-400">DMG installer</p>
                </div>
              </div>
              <p className="text-sm text-gray-300 mb-3">
                Wake word detection, voice commands, menu bar control. Drag-and-drop installation!
              </p>
              <a
                href="http://10.185.1.180:8000/api/agent/downloads/macos"
                download="SaraShadowAgent-Installer.dmg"
                className="inline-flex items-center px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition text-sm font-medium w-full justify-center"
              >
                <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                Download for macOS
              </a>
              <p className="text-xs text-gray-500 mt-2">
                Open DMG, drag to Applications. Grant microphone permission when prompted.
              </p>
            </div>
          </div>

          <div className="mt-4 p-3 bg-green-900/20 border border-green-500/30 rounded-lg">
            <p className="text-sm text-green-300">
              <strong>Voice Modes:</strong> Always-On (continuously listens), Shadow-Only (active during sessions), or Push-to-Talk (manual activation).
              Configure via system tray menu.
            </p>
          </div>
        </div>

        {/* Shadow Agent Downloads */}
        <div className="mt-8 bg-card border border-card rounded-xl p-6">
          <div className="flex items-center mb-4">
            <svg className="w-6 h-6 text-purple-400 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
            <h3 className="text-lg font-medium text-white">🕵️ Shadow Mode Desktop Agent</h3>
          </div>

          <p className="text-gray-400 text-sm mb-6">
            Download and install the Shadow Mode agent to automatically capture browser and VS Code activity during Shadow sessions.
            The agent runs in the background and only sends events when a Shadow session is active.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Windows Agent */}
            <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
              <div className="flex items-center mb-3">
                <svg className="w-8 h-8 text-blue-400 mr-3" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.9-1.801" />
                </svg>
                <div>
                  <h4 className="text-white font-medium">Windows Agent</h4>
                  <p className="text-xs text-gray-400">PowerShell installer</p>
                </div>
              </div>
              <p className="text-sm text-gray-300 mb-3">
                Supports Chrome, Firefox, Edge, Brave, Opera, and VS Code on Windows 10/11
              </p>
              <a
                href="http://10.185.1.180:8000/shadow/agent/download/windows"
                download="sara-shadow-agent-install.ps1"
                className="inline-flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition text-sm font-medium w-full justify-center"
              >
                <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                Download for Windows
              </a>
              <p className="text-xs text-gray-500 mt-2">
                Run: <code className="bg-gray-900 px-1 rounded">powershell -ExecutionPolicy Bypass -File install.ps1</code>
              </p>
            </div>

            {/* macOS/Linux Agent */}
            <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
              <div className="flex items-center mb-3">
                <svg className="w-8 h-8 text-gray-300 mr-3" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z" />
                </svg>
                <div>
                  <h4 className="text-white font-medium">macOS / Linux Agent</h4>
                  <p className="text-xs text-gray-400">Bash installer</p>
                </div>
              </div>
              <p className="text-sm text-gray-300 mb-3">
                Supports Chrome, Safari, Firefox, Brave, and VS Code on macOS/Linux
              </p>
              <a
                href="http://10.185.1.180:8000/shadow/agent/download/macos"
                download="sara-shadow-agent-install.sh"
                className="inline-flex items-center px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 transition text-sm font-medium w-full justify-center"
              >
                <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                Download for macOS/Linux
              </a>
              <p className="text-xs text-gray-500 mt-2">
                Run: <code className="bg-gray-900 px-1 rounded">bash install.sh [API_URL]</code>
              </p>
            </div>
          </div>

          <div className="mt-4 p-3 bg-purple-900/20 border border-purple-500/30 rounded-lg">
            <p className="text-sm text-purple-300">
              <strong>Privacy:</strong> The agent only captures metadata (window titles, URLs, file paths) when a Shadow session is active.
              No screenshots or keystrokes are recorded.
            </p>
          </div>

          {/* Agent Status */}
          <AgentStatus />
        </div>

        {/* Fitness System Prompt */}
        <div className="mt-8 bg-card border border-card rounded-xl p-6">
          <div className="flex items-center mb-4">
            <svg className="w-6 h-6 text-orange-400 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            <h3 className="text-lg font-medium text-white">Fitness System Prompt</h3>
          </div>

          <p className="text-gray-400 text-sm mb-4">
            Customize Sara's fitness coaching behavior. Use template variables to dynamically insert system information into the prompt.
          </p>

          {/* Result Alert */}
          {fitnessSaveResult && (
            <div className={`mb-4 p-3 rounded-lg ${
              fitnessSaveResult.success
                ? 'bg-green-900/20 border border-green-500/30 text-green-400'
                : 'bg-red-900/20 border border-red-500/30 text-red-400'
            }`}>
              <div className="flex items-center">
                <div className="flex-shrink-0">
                  {fitnessSaveResult.success ? (
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
                  <p className="text-sm font-medium">{fitnessSaveResult.message}</p>
                </div>
              </div>
            </div>
          )}

          <div className="space-y-4">
            <div>
              <label htmlFor="fitnessPrompt" className="block text-sm font-medium text-gray-300 mb-2">
                Custom System Prompt
              </label>
              <textarea
                id="fitnessPrompt"
                value={fitnessPrompt}
                onChange={(e) => setFitnessPrompt(e.target.value)}
                rows={8}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:ring-2 focus:ring-orange-500 focus:border-orange-500 text-white placeholder-gray-400 font-mono text-sm"
                placeholder="You are a fitness coach. Today is {{SYSTEM_DATE}}..."
              />
              <p className="mt-2 text-xs text-gray-400">
                This prompt will be used when Sara provides fitness-related suggestions and analysis.
              </p>
            </div>

            <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
              <h4 className="text-sm font-medium text-white mb-2">Available Template Variables</h4>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs">
                <code className="px-2 py-1 bg-gray-900 rounded text-blue-300">{`{{SYSTEM_DATE}}`}</code>
                <code className="px-2 py-1 bg-gray-900 rounded text-blue-300">{`{{SYSTEM_TIME}}`}</code>
                <code className="px-2 py-1 bg-gray-900 rounded text-blue-300">{`{{SYSTEM_DAY_OF_WEEK}}`}</code>
                <code className="px-2 py-1 bg-gray-900 rounded text-blue-300">{`{{SYSTEM_MONTH}}`}</code>
                <code className="px-2 py-1 bg-gray-900 rounded text-blue-300">{`{{SYSTEM_YEAR}}`}</code>
                <code className="px-2 py-1 bg-gray-900 rounded text-blue-300">{`{{USER_NAME}}`}</code>
                <code className="px-2 py-1 bg-gray-900 rounded text-blue-300">{`{{USER_EMAIL}}`}</code>
                <code className="px-2 py-1 bg-gray-900 rounded text-blue-300">{`{{ASSISTANT_NAME}}`}</code>
              </div>
              <p className="mt-2 text-xs text-gray-400">
                Variables are automatically replaced with current values when Sara processes your requests.
              </p>
            </div>

            <button
              onClick={handleSaveFitnessPrompt}
              className="w-full px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 transition text-sm font-medium"
            >
              Save Fitness Prompt
            </button>
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

            {/* Get To Know You (GTKY) */}
            <div className="border-t border-gray-700 pt-6">
              <h3 className="text-lg font-medium text-white mb-4">Get To Know You (GTKY)</h3>
              <p className="text-gray-400 text-sm mb-4">
                Help Sara personalize your experience. You can start or revisit the GTKY interview any time.
              </p>
              {!showGTKY ? (
                <button
                  onClick={() => setShowGTKY(true)}
                  className="px-4 py-2 bg-teal-600/20 text-teal-300 rounded-lg hover:bg-teal-600/30 text-sm"
                >
                  Start GTKY Interview
                </button>
              ) : (
                <div className="mt-4">
                  <GTKYTrigger
                    onComplete={() => {
                      setShowGTKY(false)
                    }}
                    onSpriteStateChange={() => {}}
                    personalityMode={'companion'}
                  />
                </div>
              )}
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
