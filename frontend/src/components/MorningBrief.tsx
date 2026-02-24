import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { APP_CONFIG } from '../config'
import { WeatherWidget } from './weather/WeatherWidget'

interface BriefSummary {
  id: string
  brief_date: string
  has_audio: boolean
  audio_duration_seconds: number | null
  generated_at: string | null
  viewed_at: string | null
}

interface BriefDetail {
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

export default function MorningBrief() {
  const [briefs, setBriefs] = useState<BriefSummary[]>([])
  const [selectedBrief, setSelectedBrief] = useState<BriefDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [playingRecovery, setPlayingRecovery] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const recoveryAudioRef = useRef<HTMLAudioElement | null>(null)
  const audioBlobUrlRef = useRef<string | null>(null)
  const recoveryBlobUrlRef = useRef<string | null>(null)

  useEffect(() => {
    loadBriefs()
  }, [])

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause()
      }
      if (recoveryAudioRef.current) {
        recoveryAudioRef.current.pause()
      }
      if (audioBlobUrlRef.current) {
        URL.revokeObjectURL(audioBlobUrlRef.current)
        audioBlobUrlRef.current = null
      }
      if (recoveryBlobUrlRef.current) {
        URL.revokeObjectURL(recoveryBlobUrlRef.current)
        recoveryBlobUrlRef.current = null
      }
    }
  }, [])

  const loadBriefs = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/morning-brief/history?limit=14`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setBriefs(data)
        // Auto-load today's brief
        if (data.length > 0) {
          await loadBriefDetail(data[0].brief_date)
        }
      }
    } catch (error) {
      console.error('Failed to load briefs:', error)
    } finally {
      setLoading(false)
    }
  }

  const loadBriefDetail = async (briefDate: string, includeRecovery = true) => {
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/morning-brief/${briefDate}?include_recovery=${includeRecovery}`,
        { credentials: 'include' }
      )
      if (response.ok) {
        const data = await response.json()
        setSelectedBrief(data)
      }
    } catch (error) {
      console.error('Failed to load brief detail:', error)
    }
  }

  const generateBrief = async () => {
    setGenerating(true)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/morning-brief/generate`, {
        method: 'POST',
        credentials: 'include'
      })
      if (response.ok) {
        // Reload briefs list and select today
        await loadBriefs()
      }
    } catch (error) {
      console.error('Failed to generate brief:', error)
    } finally {
      setGenerating(false)
    }
  }

  const loadAudioBlob = async (endpoint: string, blobRef: { current: string | null }) => {
    const response = await fetch(endpoint, { credentials: 'include' })
    if (!response.ok) {
      throw new Error(`Audio request failed (${response.status})`)
    }
    const blob = await response.blob()
    if (blobRef.current) {
      URL.revokeObjectURL(blobRef.current)
    }
    blobRef.current = URL.createObjectURL(blob)
    return blobRef.current
  }

  const playAudio = async () => {
    if (!selectedBrief?.has_audio || !selectedBrief.brief_date) return

    if (audioRef.current) {
      if (playing) {
        audioRef.current.pause()
        setPlaying(false)
      } else {
        try {
          audioRef.current.src = await loadAudioBlob(
            `${APP_CONFIG.apiUrl}/api/morning-brief/${selectedBrief.brief_date}/audio`,
            audioBlobUrlRef
          )
          await audioRef.current.play()
          setPlaying(true)
        } catch (error) {
          console.error('Failed to play brief audio:', error)
          setPlaying(false)
        }
      }
    }
  }

  const playRecoveryAudio = async () => {
    if (!selectedBrief?.has_recovery_audio || !selectedBrief.brief_date) return

    if (recoveryAudioRef.current) {
      if (playingRecovery) {
        recoveryAudioRef.current.pause()
        setPlayingRecovery(false)
      } else {
        try {
          recoveryAudioRef.current.src = await loadAudioBlob(
            `${APP_CONFIG.apiUrl}/api/morning-brief/${selectedBrief.brief_date}/recovery-audio`,
            recoveryBlobUrlRef
          )
          await recoveryAudioRef.current.play()
          setPlayingRecovery(true)
        } catch (error) {
          console.error('Failed to play recovery audio:', error)
          setPlayingRecovery(false)
        }
      }
    }
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr + 'T12:00:00')
    const today = new Date()
    const yesterday = new Date(today)
    yesterday.setDate(yesterday.getDate() - 1)

    if (dateStr === today.toISOString().split('T')[0]) {
      return 'Today'
    } else if (dateStr === yesterday.toISOString().split('T')[0]) {
      return 'Yesterday'
    }
    return date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
  }

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return ''
    const mins = Math.floor(seconds / 60)
    const secs = Math.round(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
      </div>
    )
  }

  return (
    <div className="flex flex-col lg:flex-row gap-4 h-full p-4">
      {/* Hidden audio elements */}
      <audio
        ref={audioRef}
        onEnded={() => setPlaying(false)}
        onPause={() => setPlaying(false)}
        onError={() => setPlaying(false)}
      />
      <audio
        ref={recoveryAudioRef}
        onEnded={() => setPlayingRecovery(false)}
        onPause={() => setPlayingRecovery(false)}
        onError={() => setPlayingRecovery(false)}
      />

      {/* Sidebar - Brief History */}
      <div className="w-full lg:w-64 flex-shrink-0 space-y-4">
        {/* Weather Widget */}
        <WeatherWidget />

        {/* Generate Button */}
        <button
          onClick={generateBrief}
          disabled={generating}
          className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 text-white rounded-lg font-medium transition-colors flex items-center justify-center gap-2"
        >
          {generating ? (
            <>
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
              Generating...
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              Generate Brief
            </>
          )}
        </button>

        {/* Brief History List */}
        <div className="bg-gray-800/50 rounded-lg overflow-hidden">
          <div className="px-3 py-2 bg-gray-700/50 text-xs font-medium text-gray-400 uppercase tracking-wider">
            Recent Briefs
          </div>
          <div className="divide-y divide-gray-700/50 max-h-80 overflow-y-auto">
            {briefs.length === 0 ? (
              <div className="px-3 py-4 text-gray-500 text-sm text-center">
                No briefs yet. Generate your first one!
              </div>
            ) : (
              briefs.map(brief => (
                <button
                  key={brief.id}
                  onClick={() => loadBriefDetail(brief.brief_date)}
                  className={`w-full px-3 py-2 text-left hover:bg-gray-700/50 transition-colors ${
                    selectedBrief?.brief_date === brief.brief_date ? 'bg-gray-700/50' : ''
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-white">
                      {formatDate(brief.brief_date)}
                    </span>
                    {brief.has_audio && (
                      <span className="text-xs text-gray-400">
                        {formatDuration(brief.audio_duration_seconds)}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    {brief.has_audio && (
                      <span className="text-xs text-blue-400">Audio</span>
                    )}
                    {brief.viewed_at && (
                      <span className="text-xs text-green-400">Read</span>
                    )}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 bg-gray-800/30 rounded-lg overflow-hidden">
        {selectedBrief ? (
          <div className="h-full flex flex-col">
            {/* Header with audio controls */}
            <div className="px-4 py-3 bg-gray-700/30 border-b border-gray-700 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-white">
                  {formatDate(selectedBrief.brief_date)} Morning Brief
                </h2>
                {selectedBrief.generated_at && (
                  <p className="text-xs text-gray-400">
                    Generated {new Date(selectedBrief.generated_at).toLocaleTimeString()}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2">
                {selectedBrief.has_audio && (
                  <button
                    onClick={playAudio}
                    className={`px-3 py-1.5 rounded-lg font-medium text-sm flex items-center gap-2 transition-colors ${
                      playing
                        ? 'bg-red-600 hover:bg-red-700 text-white'
                        : 'bg-blue-600 hover:bg-blue-700 text-white'
                    }`}
                  >
                    {playing ? (
                      <>
                        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                          <rect x="6" y="4" width="4" height="16" />
                          <rect x="14" y="4" width="4" height="16" />
                        </svg>
                        Pause
                      </>
                    ) : (
                      <>
                        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                          <path d="M8 5v14l11-7z" />
                        </svg>
                        Play Brief
                      </>
                    )}
                  </button>
                )}
                {selectedBrief.has_recovery_audio && (
                  <button
                    onClick={playRecoveryAudio}
                    className={`px-3 py-1.5 rounded-lg font-medium text-sm flex items-center gap-2 transition-colors ${
                      playingRecovery
                        ? 'bg-red-600 hover:bg-red-700 text-white'
                        : 'bg-green-600 hover:bg-green-700 text-white'
                    }`}
                  >
                    {playingRecovery ? 'Pause' : 'Play Training'}
                  </button>
                )}
              </div>
            </div>

            {/* Brief Content */}
            <div className="flex-1 overflow-y-auto p-4">
              {selectedBrief.full_text ? (
                <div className="prose prose-invert prose-sm max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {selectedBrief.full_text}
                  </ReactMarkdown>
                </div>
              ) : (
                <div className="space-y-6">
                  {/* Weather Section */}
                  {selectedBrief.weather_summary && (
                    <section>
                      <div className="prose prose-invert prose-sm max-w-none">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {selectedBrief.weather_summary}
                        </ReactMarkdown>
                      </div>
                    </section>
                  )}

                  {/* Calendar Section */}
                  {selectedBrief.calendar_summary && (
                    <section>
                      <div className="prose prose-invert prose-sm max-w-none">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {selectedBrief.calendar_summary}
                        </ReactMarkdown>
                      </div>
                    </section>
                  )}

                  {/* News Section */}
                  {selectedBrief.news_summary && (
                    <section>
                      <h3 className="text-lg font-semibold text-white mb-2">Tech News</h3>
                      <div className="prose prose-invert prose-sm max-w-none">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {selectedBrief.news_summary}
                        </ReactMarkdown>
                      </div>
                    </section>
                  )}
                </div>
              )}

              {/* Recovery Section */}
              {selectedBrief.recovery_text && (
                <div className="mt-6 pt-6 border-t border-gray-700">
                  <div className="prose prose-invert prose-sm max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {selectedBrief.recovery_text}
                    </ReactMarkdown>
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-gray-500">
            <div className="text-center">
              <svg className="w-16 h-16 mx-auto mb-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
              <p className="text-lg font-medium">No brief selected</p>
              <p className="text-sm mt-1">Generate a brief or select one from the list</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
