import { useState } from 'react'
import { useAuth } from '../hooks/useAuth'
import { APP_CONFIG } from '../config'

export default function Settings() {
  const { user, updateProfile, logout } = useAuth()
  const [activeTab, setActiveTab] = useState<'profile' | 'preferences' | 'security' | 'about'>('profile')
  const [isEditing, setIsEditing] = useState(false)
  const [formData, setFormData] = useState({
    name: user?.name || '',
    email: user?.email || '',
  })
  const [preferences, setPreferences] = useState({
    theme: user?.preferences?.theme || 'light' as 'light' | 'dark',
    notifications: user?.preferences?.notifications ?? true,
    timezone: user?.preferences?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone,
  })
  const [isSaving, setIsSaving] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const handleProfileSave = async () => {
    if (!formData.name.trim()) {
      setMessage({ type: 'error', text: 'Name is required' })
      return
    }

    setIsSaving(true)
    try {
      await updateProfile({
        name: formData.name.trim(),
        email: formData.email.trim(),
      })
      setIsEditing(false)
      setMessage({ type: 'success', text: 'Profile updated successfully' })
    } catch (error) {
      setMessage({ type: 'error', text: 'Failed to update profile' })
    } finally {
      setIsSaving(false)
    }
  }

  const handlePreferencesSave = async () => {
    setIsSaving(true)
    try {
      await updateProfile({
        preferences,
      })
      setMessage({ type: 'success', text: 'Preferences updated successfully' })
    } catch (error) {
      setMessage({ type: 'error', text: 'Failed to update preferences' })
    } finally {
      setIsSaving(false)
    }
  }

  const handleLogout = async () => {
    if (window.confirm('Are you sure you want to sign out?')) {
      try {
        await logout()
      } catch (error) {
        setMessage({ type: 'error', text: 'Failed to sign out' })
      }
    }
  }

  const timezones = [
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'America/Phoenix',
    'America/Anchorage',
    'Pacific/Honolulu',
    'Europe/London',
    'Europe/Paris',
    'Europe/Berlin',
    'Asia/Tokyo',
    'Asia/Shanghai',
    'Asia/Kolkata',
    'Australia/Sydney',
    'UTC',
  ]

  const tabs = [
    { id: 'profile', name: 'Profile', icon: '👤' },
    { id: 'preferences', name: 'Preferences', icon: '⚙️' },
    { id: 'security', name: 'Security', icon: '🔒' },
    { id: 'about', name: 'About', icon: 'ℹ️' },
  ] as const

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-600 mt-2">Manage your account and preferences</p>
      </div>

      {/* Message */}
      {message && (
        <div className={`mb-6 p-4 rounded-lg ${
          message.type === 'success' 
            ? 'bg-green-50 border border-green-200' 
            : 'bg-red-50 border border-red-200'
        }`}>
          <div className="flex">
            <div className="flex-shrink-0">
              {message.type === 'success' ? (
                <svg className="h-5 w-5 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              ) : (
                <svg className="h-5 w-5 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              )}
            </div>
            <div className="ml-3">
              <p className={`text-sm ${
                message.type === 'success' ? 'text-green-800' : 'text-red-800'
              }`}>
                {message.text}
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {/* Tabs */}
        <div className="border-b border-gray-200">
          <nav className="-mb-px flex">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`py-4 px-6 text-sm font-medium border-b-2 transition-colors duration-200 ${
                  activeTab === tab.id
                    ? 'border-indigo-500 text-indigo-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                <span className="mr-2">{tab.icon}</span>
                {tab.name}
              </button>
            ))}
          </nav>
        </div>

        {/* Tab Content */}
        <div className="p-6">
          {activeTab === 'profile' && (
            <div>
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Profile Information</h2>
              
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Full Name</label>
                  {isEditing ? (
                    <input
                      type="text"
                      value={formData.name}
                      onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                    />
                  ) : (
                    <p className="text-gray-900 py-2">{user?.name}</p>
                  )}
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Email Address</label>
                  <p className="text-gray-900 py-2">{user?.email}</p>
                  <p className="text-sm text-gray-500">Email address cannot be changed</p>
                </div>

                <div className="flex items-center space-x-3 pt-4">
                  {isEditing ? (
                    <>
                      <button
                        onClick={handleProfileSave}
                        disabled={isSaving}
                        className="bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200"
                      >
                        {isSaving ? 'Saving...' : 'Save Changes'}
                      </button>
                      <button
                        onClick={() => {
                          setIsEditing(false)
                          setFormData({
                            name: user?.name || '',
                            email: user?.email || '',
                          })
                        }}
                        className="text-gray-500 hover:text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-100 transition-colors duration-200"
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => setIsEditing(true)}
                      className="bg-gray-100 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-200 transition-colors duration-200"
                    >
                      Edit Profile
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'preferences' && (
            <div>
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Preferences</h2>
              
              <div className="space-y-6">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Theme</label>
                  <div className="grid grid-cols-2 gap-3">
                    {(['light', 'dark'] as const).map((theme) => (
                      <button
                        key={theme}
                        onClick={() => setPreferences(prev => ({ ...prev, theme }))}
                        className={`p-3 border rounded-lg text-left transition-colors duration-200 ${
                          preferences.theme === theme
                            ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                            : 'border-gray-200 hover:border-gray-300'
                        }`}
                      >
                        <div className="flex items-center">
                          <span className="mr-2">{theme === 'light' ? '☀️' : '🌙'}</span>
                          <span className="font-medium capitalize">{theme}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Timezone</label>
                  <select
                    value={preferences.timezone}
                    onChange={(e) => setPreferences(prev => ({ ...prev, timezone: e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                  >
                    {timezones.map((tz) => (
                      <option key={tz} value={tz}>{tz}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <div className="flex items-center justify-between">
                    <div>
                      <label className="text-sm font-medium text-gray-700">Notifications</label>
                      <p className="text-sm text-gray-500">Receive email notifications for reminders and events</p>
                    </div>
                    <button
                      onClick={() => setPreferences(prev => ({ ...prev, notifications: !prev.notifications }))}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors duration-200 ${
                        preferences.notifications ? 'bg-indigo-600' : 'bg-gray-200'
                      }`}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform duration-200 ${
                          preferences.notifications ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>
                </div>

                <div className="pt-4">
                  <button
                    onClick={handlePreferencesSave}
                    disabled={isSaving}
                    className="bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200"
                  >
                    {isSaving ? 'Saving...' : 'Save Preferences'}
                  </button>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'security' && (
            <div>
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Security</h2>
              
              <div className="space-y-6">
                <div className="border border-gray-200 rounded-lg p-4">
                  <h3 className="font-medium text-gray-900 mb-2">Password</h3>
                  <p className="text-sm text-gray-600 mb-3">
                    Change your password to keep your account secure
                  </p>
                  <button className="bg-gray-100 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-200 transition-colors duration-200">
                    Change Password
                  </button>
                </div>

                <div className="border border-red-200 rounded-lg p-4">
                  <h3 className="font-medium text-red-900 mb-2">Sign Out</h3>
                  <p className="text-sm text-red-600 mb-3">
                    Sign out of your account on this device
                  </p>
                  <button
                    onClick={handleLogout}
                    className="bg-red-600 text-white px-4 py-2 rounded-lg hover:bg-red-700 transition-colors duration-200"
                  >
                    Sign Out
                  </button>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'about' && (
            <div>
              <h2 className="text-lg font-semibold text-gray-900 mb-4">About {APP_CONFIG.assistantName}</h2>
              
              <div className="space-y-6">
                <div className="text-center">
                  <div className="w-16 h-16 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center mx-auto mb-4">
                    <span className="text-white font-bold text-2xl">{APP_CONFIG.assistantName.charAt(0)}</span>
                  </div>
                  <h3 className="text-xl font-semibold text-gray-900 mb-2">{APP_CONFIG.ui.title}</h3>
                  <p className="text-gray-600">{APP_CONFIG.ui.subtitle}</p>
                </div>

                <div className="border-t border-gray-200 pt-6">
                  <dl className="space-y-4">
                    <div>
                      <dt className="text-sm font-medium text-gray-500">Version</dt>
                      <dd className="text-sm text-gray-900">1.0.0</dd>
                    </div>
                    <div>
                      <dt className="text-sm font-medium text-gray-500">Domain</dt>
                      <dd className="text-sm text-gray-900">{APP_CONFIG.domain}</dd>
                    </div>
                    <div>
                      <dt className="text-sm font-medium text-gray-500">Features</dt>
                      <dd className="text-sm text-gray-900">
                        <ul className="list-disc list-inside space-y-1">
                          <li>AI-powered chat assistant</li>
                          <li>Personal knowledge management</li>
                          <li>Document processing and search</li>
                          <li>Notes and reminders</li>
                          <li>Calendar integration</li>
                          <li>Memory and context retention</li>
                        </ul>
                      </dd>
                    </div>
                  </dl>
                </div>

                <div className="border-t border-gray-200 pt-6 text-center">
                  <p className="text-sm text-gray-500">
                    Built with modern web technologies for the best user experience
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
