import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { APP_CONFIG } from '../config'
import { WeatherWidget } from './weather/WeatherWidget'

type BriefType = 'morning' | 'research'

interface BriefSummary {
  id: string
  brief_type: BriefType
  brief_date: string
  has_audio: boolean
  audio_duration_seconds: number | null
  generated_at: string | null
  viewed_at: string | null
  paper_count?: number | null
}

interface BriefDetail {
  id: string
  brief_type: BriefType
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
  paper_count?: number | null
  sources?: any[] | null
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
      const [morningResp, researchResp] = await Promise.all([
        fetch(`${APP_CONFIG.apiUrl}/api/morning-brief/history?limit=14`, { credentials: 'include' }).catch(() => null),
        fetch(`${APP_CONFIG.apiUrl}/api/research-brief/history?limit=14`, { credentials: 'include' }).catch(() => null),
      ])

      const morning: BriefSummary[] = morningResp && morningResp.ok
        ? ((await morningResp.json()) as any[]).map(b => ({
            ...b,
            brief_type: 'morning' as BriefType,
            id: b.id || `morning-${b.brief_date}`,
          }))
        : []

      const research: BriefSummary[] = researchResp && researchResp.ok
        ? ((await researchResp.json()) as any[]).map(b => ({
            ...b,
            brief_type: 'research' as BriefType,
            id: `research-${b.brief_date}`,
            viewed_at: null,
          }))
        : []

      // Sort by date desc; within a date morning first, research second.
      const merged = [...morning, ...research].sort((a, b) => {
        if (a.brief_date !== b.brief_date) return a.brief_date < b.brief_date ? 1 : -1
        return a.brief_type === b.brief_type ? 0 : a.brief_type === 'morning' ? -1 : 1
      })

      setBriefs(merged)
      if (merged.length > 0) {
        await loadBriefDetail(merged[0])
      }
    } catch (error) {
      console.error('Failed to load briefs:', error)
    } finally {
      setLoading(false)
    }
  }

  const loadBriefDetail = async (
    summary: BriefSummary | { brief_type: BriefType; brief_date: string },
    includeRecovery = true
  ) => {
    try {
      const url = summary.brief_type === 'research'
        ? `${APP_CONFIG.apiUrl}/api/research-brief/${summary.brief_date}`
        : `${APP_CONFIG.apiUrl}/api/morning-brief/${summary.brief_date}?include_recovery=${includeRecovery}`
      const response = await fetch(url, { credentials: 'include' })
      if (response.ok) {
        const data = await response.json()
        setSelectedBrief({
          ...data,
          brief_type: summary.brief_type,
          id: data.id || `${summary.brief_type}-${summary.brief_date}`,
          news_summary: data.news_summary ?? null,
          weather_summary: data.weather_summary ?? null,
          calendar_summary: data.calendar_summary ?? null,
          recovery_text: data.recovery_text ?? null,
          has_recovery_audio: data.has_recovery_audio ?? false,
        })
      }
    } catch (error) {
      console.error('Failed to load brief detail:', error)
    }
  }

  const generateBrief = async () => {
    setGenerating(true)
    try {
      // Refresh whichever type the user is currently viewing; default to morning.
      const type: BriefType = selectedBrief?.brief_type ?? 'morning'
      const url = type === 'research'
        ? `${APP_CONFIG.apiUrl}/api/research-brief/generate`
        : `${APP_CONFIG.apiUrl}/api/morning-brief/generate`
      const response = await fetch(url, { method: 'POST', credentials: 'include' })
      if (response.ok) {
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
          const base = selectedBrief.brief_type === 'research'
            ? `${APP_CONFIG.apiUrl}/api/research-brief`
            : `${APP_CONFIG.apiUrl}/api/morning-brief`
          audioRef.current.src = await loadAudioBlob(
            `${base}/${selectedBrief.brief_date}/audio`,
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
      <div className="flex h-full items-center justify-center p-4">
        <div className="assistant-panel flex items-center gap-3 rounded-md px-6 py-5">
          <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-cyan-400"></div>
          <p className="text-sm text-[var(--assistant-text-soft)]">Loading morning brief…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col gap-3 p-4">
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

      <section className="assistant-panel-soft rounded-md px-4 py-3.5 md:px-5">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0 max-w-2xl">
            <div className="assistant-kicker mb-2">
              {selectedBrief?.brief_type === 'research' ? 'Research Context' : 'Daily Context'}
            </div>
            <div className="flex flex-col gap-2 md:flex-row md:items-end md:gap-3">
              <h1 className="font-display text-2xl font-semibold text-white">Briefings</h1>
              <p className="max-w-xl text-sm leading-6 text-[var(--assistant-text-soft)]">
                Review your morning and nightly research briefs, replay the audio, and keep the day’s context in one readable workspace.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <div className="assistant-panel flex min-w-[168px] items-center justify-between gap-3 rounded-md px-3 py-2.5">
              <span className="assistant-kicker">Current Brief</span>
              <span className="text-sm font-medium text-white">
                {selectedBrief ? formatDate(selectedBrief.brief_date) : 'No brief'}
              </span>
            </div>
            <div className="assistant-panel flex min-w-[116px] items-center justify-between gap-3 rounded-md px-3 py-2.5">
              <span className="assistant-kicker">History</span>
              <span className="font-display text-lg text-white">{briefs.length}</span>
            </div>
            <div className="assistant-panel flex min-w-[132px] items-center justify-between gap-3 rounded-md px-3 py-2.5">
              <span className="assistant-kicker">Audio</span>
              <span className="text-sm font-medium text-white">
                {selectedBrief?.has_audio ? formatDuration(selectedBrief.audio_duration_seconds) || 'Ready' : 'Unavailable'}
              </span>
            </div>
            {selectedBrief?.brief_type === 'research' ? (
              <div className="assistant-panel flex min-w-[136px] items-center justify-between gap-3 rounded-md px-3 py-2.5">
                <span className="assistant-kicker">Papers</span>
                <span className="text-sm font-medium text-white">{selectedBrief.paper_count ?? '—'}</span>
              </div>
            ) : (
              <div className="assistant-panel flex min-w-[136px] items-center justify-between gap-3 rounded-md px-3 py-2.5">
                <span className="assistant-kicker">Recovery</span>
                <span className="text-sm font-medium text-white">{selectedBrief?.recovery_text ? 'Included' : 'None'}</span>
              </div>
            )}
          </div>
        </div>
      </section>

      <div className="flex min-h-0 flex-1 flex-col gap-4 lg:flex-row">
        {/* Sidebar - Brief History */}
        <div className="w-full flex-shrink-0 space-y-4 lg:w-72">
          {/* Weather Widget (morning-brief context only) */}
          {selectedBrief?.brief_type !== 'research' && <WeatherWidget />}

          {/* Generate Button */}
          <div className="assistant-panel-soft rounded-md p-4">
            <div className="assistant-kicker mb-3">Generate</div>
            <p className="mb-4 text-sm text-[var(--assistant-text-soft)]">
              Refresh the brief when you want a new summary for the day.
            </p>
            <button
              onClick={generateBrief}
              disabled={generating}
              className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-cyan-500 px-4 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:bg-cyan-700/60 disabled:text-white"
            >
              {generating ? (
                <>
                  <div className="h-4 w-4 animate-spin rounded-full border-b-2 border-current"></div>
                  Generating...
                </>
              ) : (
                <>
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                  Generate Brief
                </>
              )}
            </button>
          </div>

          {/* Brief History List */}
          <div className="assistant-panel-soft overflow-hidden rounded-md">
            <div className="px-4 py-3 text-xs font-medium uppercase tracking-[0.18em] text-[var(--assistant-text-soft)]">
              Recent Briefs
            </div>
            <div className="max-h-80 divide-y divide-white/5 overflow-y-auto">
              {briefs.length === 0 ? (
                <div className="px-4 py-6 text-center text-sm text-[var(--assistant-text-soft)]">
                  No briefs yet. Generate your first one!
                </div>
              ) : (
                briefs.map(brief => {
                  const isActive =
                    selectedBrief?.brief_date === brief.brief_date &&
                    selectedBrief?.brief_type === brief.brief_type
                  const isResearch = brief.brief_type === 'research'
                  return (
                    <button
                      key={brief.id}
                      onClick={() => loadBriefDetail(brief)}
                      className={`w-full px-4 py-3 text-left transition-colors hover:bg-white/[0.04] ${
                        isActive ? 'bg-white/[0.06]' : ''
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex min-w-0 items-center gap-2">
                          <span
                            className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
                              isResearch
                                ? 'border-violet-400/40 bg-violet-500/15 text-violet-200'
                                : 'border-amber-400/40 bg-amber-500/15 text-amber-200'
                            }`}
                          >
                            {isResearch ? 'Research' : 'Morning'}
                          </span>
                          <span className="truncate text-sm font-medium text-white">
                            {formatDate(brief.brief_date)}
                          </span>
                        </div>
                        {brief.has_audio && (
                          <span className="shrink-0 text-xs text-[var(--assistant-text-soft)]">
                            {formatDuration(brief.audio_duration_seconds)}
                          </span>
                        )}
                      </div>
                      <div className="mt-1 flex items-center gap-2">
                        {brief.has_audio && (
                          <span className="text-xs text-cyan-300">Audio</span>
                        )}
                        {isResearch && brief.paper_count ? (
                          <span className="text-xs text-[var(--assistant-text-soft)]">{brief.paper_count} papers</span>
                        ) : null}
                        {brief.viewed_at && (
                          <span className="text-xs text-emerald-300">Read</span>
                        )}
                      </div>
                    </button>
                  )
                })
              )}
            </div>
          </div>
        </div>

        {/* Main Content */}
        <div className="assistant-panel-soft flex min-h-0 flex-1 overflow-hidden rounded-md p-2">
          {selectedBrief ? (
            <div className="assistant-panel flex h-full min-h-0 flex-1 flex-col rounded-md">
              {/* Header with audio controls */}
              <div className="flex items-center justify-between gap-3 border-b border-white/10 px-5 py-4">
                <div>
                  <div className="assistant-kicker mb-2">Selected Brief</div>
                  <h2 className="font-display text-2xl font-semibold text-white">
                    {formatDate(selectedBrief.brief_date)} {selectedBrief.brief_type === 'research' ? 'Research Brief' : 'Morning Brief'}
                  </h2>
                  {selectedBrief.brief_type === 'research' && selectedBrief.paper_count ? (
                    <p className="text-xs text-[var(--assistant-text-soft)]">
                      {selectedBrief.paper_count} papers · arXiv · Hugging Face · Interconnects
                    </p>
                  ) : null}
                  {selectedBrief.generated_at && (
                    <p className="text-xs text-[var(--assistant-text-soft)]">
                      Generated {new Date(selectedBrief.generated_at).toLocaleTimeString()}
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {selectedBrief.has_audio && (
                    <button
                      onClick={playAudio}
                      className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                        playing
                          ? 'bg-red-600 hover:bg-red-700 text-white'
                          : 'bg-cyan-500 hover:bg-cyan-400 text-slate-950'
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
                          {selectedBrief.brief_type === 'research' ? 'Play Research' : 'Play Brief'}
                        </>
                      )}
                    </button>
                  )}
                  {selectedBrief.has_recovery_audio && (
                    <button
                      onClick={playRecoveryAudio}
                      className={`rounded-md px-3 py-2 text-sm font-medium transition-colors ${
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
              <div className="flex-1 overflow-y-auto px-5 py-5">
                {selectedBrief.full_text ? (
                  <div className="prose prose-invert prose-sm max-w-none prose-headings:text-white prose-p:text-slate-200 prose-strong:text-white prose-li:text-slate-200">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {selectedBrief.full_text}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <div className="space-y-6">
                    {/* Weather Section */}
                    {selectedBrief.weather_summary && (
                      <section>
                        <div className="assistant-kicker mb-3">Weather</div>
                        <div className="prose prose-invert prose-sm max-w-none prose-p:text-slate-200 prose-li:text-slate-200">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {selectedBrief.weather_summary}
                          </ReactMarkdown>
                        </div>
                      </section>
                    )}

                    {/* Calendar Section */}
                    {selectedBrief.calendar_summary && (
                      <section>
                        <div className="assistant-kicker mb-3">Calendar</div>
                        <div className="prose prose-invert prose-sm max-w-none prose-p:text-slate-200 prose-li:text-slate-200">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {selectedBrief.calendar_summary}
                          </ReactMarkdown>
                        </div>
                      </section>
                    )}

                    {/* News Section */}
                    {selectedBrief.news_summary && (
                      <section>
                        <div className="assistant-kicker mb-3">Tech News</div>
                        <div className="prose prose-invert prose-sm max-w-none prose-p:text-slate-200 prose-li:text-slate-200">
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
                  <div className="mt-6 border-t border-white/10 pt-6">
                    <div className="assistant-kicker mb-3">Recovery</div>
                    <div className="prose prose-invert prose-sm max-w-none prose-p:text-slate-200 prose-li:text-slate-200">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {selectedBrief.recovery_text}
                      </ReactMarkdown>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="assistant-panel flex h-full items-center justify-center rounded-md text-[var(--assistant-text-soft)]">
              <div className="text-center">
                <svg className="mx-auto mb-4 h-16 w-16 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
                <p className="font-display text-xl text-white">No brief selected</p>
                <p className="mt-1 text-sm">Generate a brief or select one from the list.</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
