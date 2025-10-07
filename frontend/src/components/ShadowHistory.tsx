import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { ClockIcon, CheckCircleIcon, LightBulbIcon, QuestionMarkCircleIcon, DocumentTextIcon, ChevronRightIcon } from '@heroicons/react/24/outline'

export default function ShadowHistory() {
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)

  // Fetch recent sessions
  const { data: sessions, isLoading: sessionsLoading } = useQuery({
    queryKey: ['shadow', 'recent'],
    queryFn: () => apiClient.getRecentShadowSessions(50),
  })

  // Fetch summary for selected session
  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['shadow', 'summary', selectedSessionId],
    queryFn: () => apiClient.getShadowSessionSummary(selectedSessionId!),
    enabled: !!selectedSessionId,
  })

  const formatDuration = (minutes: number) => {
    if (minutes < 60) return `${minutes}m`
    const hours = Math.floor(minutes / 60)
    const mins = minutes % 60
    return `${hours}h ${mins}m`
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    const today = new Date()
    const yesterday = new Date(today)
    yesterday.setDate(yesterday.getDate() - 1)

    if (date.toDateString() === today.toDateString()) {
      return `Today ${date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}`
    } else if (date.toDateString() === yesterday.toDateString()) {
      return `Yesterday ${date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}`
    } else {
      return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
    }
  }

  if (sessionsLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-gray-400">Loading sessions...</div>
      </div>
    )
  }

  if (!sessions || sessions.sessions?.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-96 text-gray-400">
        <ClockIcon className="w-16 h-16 mb-4 opacity-50" />
        <p className="text-lg">No Shadow sessions yet</p>
        <p className="text-sm mt-2">Start a Shadow session to track your work automatically</p>
      </div>
    )
  }

  const sessionList = sessions.sessions || []

  return (
    <div className="flex h-[calc(100vh-8rem)] gap-4">
      {/* Session List */}
      <div className="w-96 bg-gray-800/50 rounded-lg border border-gray-700 overflow-hidden flex flex-col">
        <div className="p-4 border-b border-gray-700">
          <h2 className="text-lg font-semibold text-white">Shadow Sessions</h2>
          <p className="text-sm text-gray-400 mt-1">{sessionList.length} sessions</p>
        </div>
        <div className="flex-1 overflow-y-auto">
          {sessionList.map((session: any) => (
            <button
              key={session.session_id}
              onClick={() => setSelectedSessionId(session.session_id)}
              className={`w-full text-left p-4 border-b border-gray-700/50 transition hover:bg-gray-700/30 ${
                selectedSessionId === session.session_id ? 'bg-purple-900/20 border-l-4 border-l-purple-500' : ''
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-white truncate">
                    {session.context || 'Shadow Session'}
                  </div>
                  <div className="text-xs text-gray-400 mt-1">
                    {formatDate(session.started_at)}
                  </div>
                  <div className="flex items-center gap-3 mt-2 text-xs text-gray-500">
                    <span className="flex items-center gap-1">
                      <ClockIcon className="w-3 h-3" />
                      {formatDuration(session.duration_minutes)}
                    </span>
                    <span className={`px-2 py-0.5 rounded-full text-xs ${
                      session.status === 'completed' ? 'bg-green-900/30 text-green-400' : 'bg-gray-700 text-gray-400'
                    }`}>
                      {session.status}
                    </span>
                  </div>
                </div>
                <ChevronRightIcon className="w-5 h-5 text-gray-500 flex-shrink-0 ml-2" />
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Summary Viewer */}
      <div className="flex-1 bg-gray-800/50 rounded-lg border border-gray-700 overflow-hidden">
        {!selectedSessionId ? (
          <div className="flex items-center justify-center h-full text-gray-400">
            <div className="text-center">
              <DocumentTextIcon className="w-16 h-16 mx-auto mb-4 opacity-50" />
              <p>Select a session to view summary</p>
            </div>
          </div>
        ) : summaryLoading ? (
          <div className="flex items-center justify-center h-full text-gray-400">
            <div>Loading summary...</div>
          </div>
        ) : summary ? (
          <div className="h-full overflow-y-auto p-6">
            <div className="max-w-4xl">
              {/* Header */}
              <div className="mb-6">
                <h2 className="text-2xl font-bold text-white mb-2">Session Summary</h2>
                <div className="flex items-center gap-4 text-sm text-gray-400">
                  <span>Session ID: {selectedSessionId.slice(0, 8)}</span>
                </div>
              </div>

              {/* Tasks */}
              {summary.tasks && summary.tasks.length > 0 && (
                <div className="mb-6">
                  <div className="flex items-center gap-2 mb-3">
                    <CheckCircleIcon className="w-5 h-5 text-green-400" />
                    <h3 className="text-lg font-semibold text-white">Tasks Captured ({summary.tasks.length})</h3>
                  </div>
                  <div className="space-y-2">
                    {summary.tasks.map((task: any, idx: number) => (
                      <div key={idx} className="bg-gray-700/30 rounded-lg p-3 border border-gray-600/50">
                        <p className="text-gray-200">{task.content || task}</p>
                        {task.context && (
                          <p className="text-xs text-gray-500 mt-1">{task.context}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Decisions */}
              {summary.decisions && summary.decisions.length > 0 && (
                <div className="mb-6">
                  <div className="flex items-center gap-2 mb-3">
                    <div className="w-5 h-5 text-blue-400">🎯</div>
                    <h3 className="text-lg font-semibold text-white">Decisions Made ({summary.decisions.length})</h3>
                  </div>
                  <div className="space-y-2">
                    {summary.decisions.map((decision: any, idx: number) => (
                      <div key={idx} className="bg-blue-900/20 rounded-lg p-3 border border-blue-500/30">
                        <p className="text-gray-200">{decision.content || decision}</p>
                        {decision.context && (
                          <p className="text-xs text-gray-500 mt-1">{decision.context}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Questions */}
              {summary.questions && summary.questions.length > 0 && (
                <div className="mb-6">
                  <div className="flex items-center gap-2 mb-3">
                    <QuestionMarkCircleIcon className="w-5 h-5 text-yellow-400" />
                    <h3 className="text-lg font-semibold text-white">Questions Noted ({summary.questions.length})</h3>
                  </div>
                  <div className="space-y-2">
                    {summary.questions.map((question: any, idx: number) => (
                      <div key={idx} className="bg-yellow-900/20 rounded-lg p-3 border border-yellow-500/30">
                        <p className="text-gray-200">{question.content || question}</p>
                        {question.context && (
                          <p className="text-xs text-gray-500 mt-1">{question.context}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Ideas */}
              {summary.ideas && summary.ideas.length > 0 && (
                <div className="mb-6">
                  <div className="flex items-center gap-2 mb-3">
                    <LightBulbIcon className="w-5 h-5 text-purple-400" />
                    <h3 className="text-lg font-semibold text-white">Ideas Generated ({summary.ideas.length})</h3>
                  </div>
                  <div className="space-y-2">
                    {summary.ideas.map((idea: any, idx: number) => (
                      <div key={idx} className="bg-purple-900/20 rounded-lg p-3 border border-purple-500/30">
                        <p className="text-gray-200">{idea.content || idea}</p>
                        {idea.context && (
                          <p className="text-xs text-gray-500 mt-1">{idea.context}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* References/Files */}
              {summary.refs && summary.refs.length > 0 && (
                <div className="mb-6">
                  <div className="flex items-center gap-2 mb-3">
                    <DocumentTextIcon className="w-5 h-5 text-gray-400" />
                    <h3 className="text-lg font-semibold text-white">References ({summary.refs.length})</h3>
                  </div>
                  <div className="space-y-2">
                    {summary.refs.map((ref: any, idx: number) => (
                      <div key={idx} className="bg-gray-700/30 rounded-lg p-3 border border-gray-600/50">
                        <p className="text-gray-200 text-sm">
                          {ref.title || ref.path || ref.url || 'Unknown reference'}
                        </p>
                        {ref.type && (
                          <span className="text-xs text-gray-500 mt-1 block">{ref.type}</span>
                        )}
                        {ref.url && ref.url !== ref.title && (
                          <span className="text-xs text-gray-500 mt-1 block font-mono">{ref.url}</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Empty state */}
              {(!summary.tasks || summary.tasks.length === 0) &&
               (!summary.decisions || summary.decisions.length === 0) &&
               (!summary.questions || summary.questions.length === 0) &&
               (!summary.ideas || summary.ideas.length === 0) && (
                <div className="text-center py-12 text-gray-400">
                  <DocumentTextIcon className="w-16 h-16 mx-auto mb-4 opacity-50" />
                  <p>No summary data available for this session</p>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-gray-400">
            <div className="text-center">
              <p>No summary found for this session</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
