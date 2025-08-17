import React from 'react'
import { APP_CONFIG } from './config'

function App() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 to-purple-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <h1 className="text-xl font-bold bg-gradient-to-r from-indigo-600 to-purple-600 bg-clip-text text-transparent">
                  {APP_CONFIG.ui.title}
                </h1>
              </div>
            </div>
            <div className="text-sm text-gray-500">
              Demo Mode
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="text-center">
          <div className="mx-auto max-w-md">
            <div className="bg-white rounded-lg shadow-lg p-8">
              <div className="w-16 h-16 bg-gradient-to-r from-indigo-500 to-purple-600 rounded-full mx-auto mb-6 flex items-center justify-center">
                <span className="text-white text-2xl font-bold">S</span>
              </div>
              
              <h1 className="text-2xl font-bold text-gray-900 mb-4">
                Welcome to {APP_CONFIG.assistantName}
              </h1>
              
              <p className="text-gray-600 mb-6">
                {APP_CONFIG.ui.subtitle}
              </p>
              
              <div className="space-y-4">
                <div className="p-4 bg-green-50 border border-green-200 rounded-lg">
                  <div className="flex items-center">
                    <div className="w-2 h-2 bg-green-500 rounded-full mr-3"></div>
                    <span className="text-sm font-medium text-green-800">Frontend Running</span>
                  </div>
                  <p className="text-xs text-green-600 mt-1">React + Vite + Tailwind CSS</p>
                </div>
                
                <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
                  <div className="flex items-center">
                    <div className="w-2 h-2 bg-blue-500 rounded-full mr-3"></div>
                    <span className="text-sm font-medium text-blue-800">Backend Demo</span>
                  </div>
                  <p className="text-xs text-blue-600 mt-1">Simple HTTP server on port 8000</p>
                </div>
                
                <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
                  <div className="flex items-center">
                    <div className="w-2 h-2 bg-yellow-500 rounded-full mr-3"></div>
                    <span className="text-sm font-medium text-yellow-800">Ready for Production</span>
                  </div>
                  <p className="text-xs text-yellow-600 mt-1">Install FastAPI + dependencies for full features</p>
                </div>
              </div>
              
              <div className="mt-8 pt-6 border-t border-gray-200">
                <h3 className="text-sm font-medium text-gray-900 mb-3">Next Steps:</h3>
                <div className="text-xs text-gray-600 space-y-1 text-left">
                  <p>• Point sara.avery.cloud → 10.185.1.180:3000</p>
                  <p>• Install backend dependencies for full AI features</p>
                  <p>• Configure PostgreSQL + pgvector for memory</p>
                  <p>• Set up OpenAI-compatible endpoint</p>
                </div>
              </div>
            </div>
          </div>
        </div>
        
        {/* Features Preview */}
        <div className="mt-16">
          <h2 className="text-center text-lg font-semibold text-gray-900 mb-8">
            Planned Features
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {[
              { name: 'AI Chat', icon: '💬', desc: 'Conversational AI with memory' },
              { name: 'Smart Notes', icon: '📝', desc: 'Semantic search & organization' },
              { name: 'Documents', icon: '📄', desc: 'Upload & search through files' },
              { name: 'Reminders', icon: '⏰', desc: 'Smart scheduling & notifications' },
              { name: 'Calendar', icon: '📅', desc: 'Event management & planning' },
              { name: 'Memory', icon: '🧠', desc: 'Human-like episodic memory' },
              { name: 'Tools', icon: '🛠️', desc: 'AI-powered productivity tools' },
              { name: 'Sync', icon: '🔄', desc: 'Multi-device synchronization' }
            ].map((feature) => (
              <div key={feature.name} className="bg-white rounded-lg p-6 shadow-sm border border-gray-200">
                <div className="text-2xl mb-3">{feature.icon}</div>
                <h3 className="font-medium text-gray-900 mb-2">{feature.name}</h3>
                <p className="text-sm text-gray-600">{feature.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </main>
      
      {/* Footer */}
      <footer className="bg-white border-t border-gray-200 mt-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="text-center text-sm text-gray-500">
            <p>{APP_CONFIG.assistantName} Personal Hub • Built with React + FastAPI</p>
            <p className="mt-1">Designed for {APP_CONFIG.domain}</p>
          </div>
        </div>
      </footer>
    </div>
  )
}

export default App