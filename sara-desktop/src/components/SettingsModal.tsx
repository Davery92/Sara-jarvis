import { useState, useEffect } from 'react'
import { apiClient } from '../services/api'

interface SettingsModalProps {
  onClose: () => void
  onAuthChange: (authenticated: boolean) => void
}

export default function SettingsModal({ onClose, onAuthChange }: SettingsModalProps) {
  const [apiUrl, setApiUrl] = useState('https://sara-api.avery.cloud')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [isAuthenticated, setIsAuthenticated] = useState(false)

  useEffect(() => {
    const init = async () => {
      if (window.electronAPI) {
        const url = await window.electronAPI.getApiUrl()
        setApiUrl(url)
        apiClient.setBaseUrl(url)

        const token = await window.electronAPI.getAuthToken()
        setIsAuthenticated(!!token)
      }
    }
    init()
  }, [])

  const handleLogin = async () => {
    if (!email.trim() || !password.trim()) {
      setError('Please enter email and password')
      return
    }

    setIsLoading(true)
    setError('')

    try {
      // Update API URL first
      await window.electronAPI?.setApiUrl(apiUrl)
      apiClient.setBaseUrl(apiUrl)

      // Attempt login
      const result = await apiClient.login(email, password)

      if (result.token) {
        await window.electronAPI?.setAuthToken(result.token)
        setIsAuthenticated(true)
        onAuthChange(true)
        setPassword('')
      } else {
        // Show the specific error message from the API
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
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 no-drag">
      <div className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-md shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <h2 className="text-lg font-semibold text-white">Settings</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {/* API URL */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-gray-300">API URL</label>
            <input
              type="url"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm focus:outline-none focus:border-indigo-500"
              placeholder="https://sara-api.avery.cloud"
            />
          </div>

          {/* Authentication */}
          <div className="space-y-4">
            <label className="text-sm font-medium text-gray-300">Authentication</label>

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
                {error && (
                  <p className="text-red-400 text-sm">{error}</p>
                )}
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

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-700 flex justify-end">
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
