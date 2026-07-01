import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { APP_CONFIG } from '../../config'
import { AppView } from '../../navigation/views'

interface DashboardHomeViewProps {
  attentionItems: any[]
  attentionUnreadCount: number
  missions: any[]
  reminders: any[]
  timers: any[]
  calendarEvents: any[]
  onNavigate: (view: AppView) => void
  greeting: string
  weather: any
  weatherEmoji: Record<string, string>
  contentInboxStats: any
  missionAwaitingCount: number
  runningMissionCount: number
  morningBrief: any
  morningBriefLoading: boolean
  briefAudioPlaying: boolean
  briefAudioRef: React.RefObject<HTMLAudioElement>
  onPlayBriefAudio: () => void
  onBriefAudioEnded: () => void
  onBriefAudioPaused: () => void
  onBriefAudioError: () => void
  onReviewAttentionInbox: () => void
  currentTime: Date
  journalEntries: any[]
  expandedJournalEntries: Set<string>
  onToggleJournalEntry: (entryKey: string) => void
  emotionEmoji: Record<string, string>
  saraStatus: any
  connectedDevices: any[]
  standingOrders: any[]
  formatRelativeTime: (ts: string) => string
  onAskSara?: (prompt: string) => void
}

function SectionHeading({ label, action }: { label: string; action?: React.ReactNode }) {
  return (
    <div className="mb-4 flex items-baseline justify-between gap-3">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</h2>
      {action}
    </div>
  )
}

function QuietLink({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className="text-xs text-slate-500 transition-colors hover:text-teal-300"
    >
      {children}
    </button>
  )
}

function LiveTimer({ endTime, className = '' }: { endTime: string; className?: string }) {
  const [timeLeft, setTimeLeft] = React.useState('')

  React.useEffect(() => {
    const updateTimer = () => {
      const now = new Date()
      const end = new Date(endTime)
      const diff = end.getTime() - now.getTime()

      if (diff <= 0) {
        setTimeLeft('FINISHED')
        return
      }

      const hours = Math.floor(diff / (1000 * 60 * 60))
      const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60))
      const seconds = Math.floor((diff % (1000 * 60)) / 1000)
      setTimeLeft(
        hours > 0
          ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
          : `${minutes}:${String(seconds).padStart(2, '0')}`
      )
    }
    updateTimer()
    const interval = setInterval(updateTimer, 1000)
    return () => clearInterval(interval)
  }, [endTime])

  return <span className={className}>{timeLeft}</span>
}

/**
 * StatChip — a single glanceable, clickable count in the header band.
 * Renders nothing when the count is zero so the strip never shows noise.
 */
function StatChip({
  count,
  label,
  onClick,
  tone = 'default',
}: {
  count: number
  label: string
  onClick?: () => void
  tone?: 'default' | 'amber' | 'teal'
}) {
  if (!count) return null
  const toneClasses =
    tone === 'amber'
      ? 'border-amber-400/30 bg-amber-400/10 text-amber-200 hover:border-amber-300/50'
      : tone === 'teal'
        ? 'border-teal-400/25 bg-teal-400/[0.07] text-teal-200 hover:border-teal-300/40'
        : 'border-white/10 bg-white/[0.03] text-slate-300 hover:border-white/20'
  return (
    <button
      onClick={onClick}
      disabled={!onClick}
      className={`inline-flex items-baseline gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors ${toneClasses} ${
        onClick ? '' : 'cursor-default'
      }`}
    >
      <span className="font-semibold tabular-nums">{count}</span>
      <span className="text-[11px] opacity-80">{label}</span>
    </button>
  )
}

/**
 * WeatherCard — the richer weather read that anchors the top-right of the
 * header band, giving the wide layout something to do above the fold.
 */
function WeatherCard({ weather, weatherEmoji }: { weather: any; weatherEmoji: Record<string, string> }) {
  if (!weather) return null
  const cur = weather.current || weather
  const temp = Math.round(cur.temperature ?? cur.temp ?? 0)
  const desc = cur.description || cur.summary || weather.description || ''
  const emoji = weatherEmoji[cur.icon || weather.icon] || '🌡'
  const hi = cur.temp_max ?? cur.high ?? weather.high
  const lo = cur.temp_min ?? cur.low ?? weather.low
  // feels_like occasionally arrives in a different unit than temperature; only
  // show it when it's plausibly the same scale (within ~25° of the reading).
  const feelsRaw = cur.feels_like ?? cur.apparent_temperature
  const feels = feelsRaw != null && Math.abs(feelsRaw - temp) <= 25 ? feelsRaw : null
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-white/8 bg-white/[0.02] px-4 py-3">
      <span className="text-3xl leading-none">{emoji}</span>
      <div className="min-w-0">
        <div className="flex items-baseline gap-1.5">
          <span className="text-2xl font-semibold leading-none text-white">{temp}°</span>
          {(hi != null || lo != null) && (
            <span className="text-xs tabular-nums text-slate-500">
              {hi != null ? `${Math.round(hi)}°` : ''}
              {hi != null && lo != null ? ' / ' : ''}
              {lo != null ? `${Math.round(lo)}°` : ''}
            </span>
          )}
        </div>
        {desc && <p className="mt-0.5 truncate text-xs capitalize text-slate-400">{desc}</p>}
        {feels != null && (
          <p className="text-[11px] text-slate-500">Feels {Math.round(feels)}°</p>
        )}
      </div>
    </div>
  )
}

/**
 * ActivityDigest — "While you were away".
 *
 * Same data as the old right-rail feed, but humanized: thoughts, reflections,
 * focus changes, and outreach read as sentences; raw tool calls and errors are
 * collapsed into a single machinery line that expands on demand. Sara's work
 * should read like a colleague's standup, not a log file.
 */
// Internal plumbing that leaks in as "thoughts"/"reflections" — goal-closure
// retry loops, server-error recovery, etc. These are machinery talking to
// itself, never news for David, so they're filtered out of the human feed.
const DIGEST_NOISE = [
  // Internal "goal" subsystem churn — closure/update/retry loops, zombie/stale
  // goals, etc. The daemon phrases these many ways, so match goal + any verb.
  /\bgoal\b[^.]*\b(closure|update|loop|attempt|retry|abandon|prune|refresh)/i,
  /\b(zombie|stale|futile|dead|orphan)\b[^.]*\bgoal/i,
  /\bgoal\b[^.]*\b(zombie|stale|futile|abandoned)/i,
  /closure (loop|retry)/i,
  /retry loop/i,
  // Server / API error-recovery chatter.
  /server (error|recovery)/i,
  /\d{3} errors?\b/i,
  /\bbackoff\b/i,
  /persistent server/i,
  /architecture goal/i,
  // Idle filler — "quiet turn, nothing pressing" / "no active work".
  /quiet turn/i,
  /nothing (pressing|to do)/i,
  /no active work/i,
]
const isDigestNoise = (text: string) => DIGEST_NOISE.some((re) => re.test(text || ''))

function ActivityDigest({ timeAgo }: { timeAgo: (ts: string) => string }) {
  const [items, setItems] = React.useState<any[]>([])
  const [loaded, setLoaded] = React.useState(false)
  const [showMachinery, setShowMachinery] = React.useState(false)

  React.useEffect(() => {
    let cancelled = false
    const fetchActivity = async () => {
      try {
        const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/v2/activity?limit=60`, {
          credentials: 'include',
        })
        if (res.ok && !cancelled) {
          setItems((await res.json()) || [])
        }
      } catch {
        /* keep last good */
      } finally {
        if (!cancelled) setLoaded(true)
      }
    }
    fetchActivity()
    const t = setInterval(fetchActivity, 30000)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [])

  const HUMAN_KINDS: Record<string, string> = {
    boot: 'Woke up',
    thought: 'Thought about',
    reflection: 'Reflected',
    focus_set: 'Started focusing on',
    notify_david: 'Reached out',
    inbox_pickup: 'Picked up',
    inbox_complete: 'Finished',
  }
  const MACHINE_KINDS = new Set(['tool_call', 'tool_result', 'error'])

  // Collapse runs of near-identical updates ("idle, nothing to do" × 5) into one
  // line, and drop internal-plumbing chatter entirely.
  const human = items
    .filter((a) => HUMAN_KINDS[a.kind])
    .filter((a) => !isDigestNoise(a.summary))
    .filter((a, i, arr) => i === 0 || a.summary !== arr[i - 1].summary)
    .slice(0, 6)
  const machine = items.filter((a) => MACHINE_KINDS.has(a.kind))
  const errorCount = machine.filter((a) => a.kind === 'error').length
  const toolCount = machine.length - errorCount

  return (
    <section>
      <SectionHeading label="While you were away" />
      {!loaded ? (
        <p className="text-sm text-slate-500">Checking…</p>
      ) : human.length === 0 && machine.length === 0 ? (
        <p className="text-sm text-slate-500">Quiet lately — nothing to report.</p>
      ) : (
        <div className="space-y-3">
          {human.map((a) => (
            <div key={a.id} className="flex items-baseline gap-3">
              <p className="min-w-0 flex-1 text-[15px] leading-relaxed text-slate-300">
                {(a.summary || HUMAN_KINDS[a.kind] || '').slice(0, 180)}
                {(a.summary || '').length > 180 ? '…' : ''}
              </p>
              <span className="flex-shrink-0 text-xs tabular-nums text-slate-500">{timeAgo(a.created_at)}</span>
            </div>
          ))}
          {human.length === 0 && (
            <p className="text-sm text-slate-500">Working quietly in the background.</p>
          )}
          {machine.length > 0 && (
            <div className="pt-1">
              <button
                onClick={() => setShowMachinery((v) => !v)}
                className="text-xs text-slate-500 transition-colors hover:text-slate-300"
              >
                {toolCount > 0 && `${toolCount} tool ${toolCount === 1 ? 'call' : 'calls'}`}
                {toolCount > 0 && errorCount > 0 && ' · '}
                {errorCount > 0 && (
                  <span className="text-rose-400/80">{errorCount} {errorCount === 1 ? 'error' : 'errors'}</span>
                )}
                <span className="ml-1.5 text-slate-600">{showMachinery ? '▴ hide' : '▾ details'}</span>
              </button>
              {showMachinery && (
                <div className="mt-2 space-y-1.5 border-l border-white/8 pl-3">
                  {machine.slice(0, 12).map((a) => (
                    <div key={a.id} className="flex items-baseline gap-3">
                      <p className={`min-w-0 flex-1 font-mono text-xs leading-relaxed ${a.kind === 'error' ? 'text-rose-300/80' : 'text-slate-500'}`}>
                        {(a.summary || a.kind).slice(0, 140)}
                      </p>
                      <span className="flex-shrink-0 text-[11px] tabular-nums text-slate-600">{timeAgo(a.created_at)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

export default function DashboardHomeView({
  attentionItems,
  attentionUnreadCount,
  timers,
  calendarEvents,
  onNavigate,
  greeting,
  weather,
  weatherEmoji,
  contentInboxStats,
  missionAwaitingCount,
  runningMissionCount,
  morningBrief,
  morningBriefLoading,
  briefAudioPlaying,
  briefAudioRef,
  onPlayBriefAudio,
  onBriefAudioEnded,
  onBriefAudioPaused,
  onBriefAudioError,
  onReviewAttentionInbox,
  currentTime,
  journalEntries,
  expandedJournalEntries,
  onToggleJournalEntry,
  emotionEmoji,
  standingOrders,
  formatRelativeTime,
  onAskSara,
}: DashboardHomeViewProps) {
  const [askDraft, setAskDraft] = React.useState('')

  const contentUnreadCount = Number(contentInboxStats?.unread || 0)
  const urgentAttention = attentionItems
    .filter((item) => item.status === 'new' || item.status === 'sent')
    .slice(0, 3)
  const needsYouCount = attentionUnreadCount + missionAwaitingCount

  // Upcoming events only — past events still render in the timeline but the
  // header chip should count what's still ahead today.
  const upcomingEvents = calendarEvents.filter((evt: any) => {
    const end = new Date(evt.end_time || evt.end || evt.dtend || evt.start_time || evt.start)
    return end.getTime() >= currentTime.getTime()
  })

  const dateLine = currentTime.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  })

  const submitAsk = (e: React.FormEvent) => {
    e.preventDefault()
    const prompt = askDraft.trim()
    if (!prompt || !onAskSara) return
    setAskDraft('')
    onAskSara(prompt)
  }

  return (
    <div className="relative flex-1 overflow-y-auto min-h-0">
      <div className="mx-auto w-full max-w-[1180px] px-4 pb-36 pt-4 md:px-8 md:pt-10">
        {/* Header band — greeting + glanceable stats on the left, weather on the right */}
        <header className="flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <h1 className="font-display text-3xl font-semibold leading-tight text-white md:text-[2.3rem]">
              {greeting}, David.
            </h1>
            <p className="mt-2 text-[15px] text-slate-400">{dateLine}</p>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <StatChip
                count={needsYouCount}
                label={needsYouCount === 1 ? 'needs you' : 'need you'}
                tone="amber"
                onClick={onReviewAttentionInbox}
              />
              <StatChip
                count={upcomingEvents.length}
                label="ahead today"
                tone="teal"
                onClick={() => onNavigate('calendar')}
              />
              <StatChip
                count={contentUnreadCount}
                label={contentUnreadCount === 1 ? 'capture' : 'captures'}
                onClick={() => onNavigate('inbox')}
              />
              <StatChip
                count={runningMissionCount}
                label={runningMissionCount === 1 ? 'mission running' : 'missions running'}
                onClick={() => onNavigate('automations')}
              />
              <StatChip count={timers.length} label={timers.length === 1 ? 'timer' : 'timers'} />
            </div>
          </div>
          <WeatherCard weather={weather} weatherEmoji={weatherEmoji} />
        </header>

        {morningBrief && (
          <audio
            ref={briefAudioRef}
            onEnded={onBriefAudioEnded}
            onPause={onBriefAudioPaused}
            onError={onBriefAudioError}
            style={{ display: 'none' }}
          />
        )}

        {/* Command-center grid — actionable + brief on the left, Sara's state on the right rail */}
        <div className="mt-10 grid grid-cols-1 gap-x-12 gap-y-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,360px)]">
          {/* LEFT — what needs you, the brief, the day */}
          <div className="space-y-12">
            {/* Needs you — the one thing the page exists to tell you */}
            <section>
              <SectionHeading label="Needs you" />
              {needsYouCount > 0 ? (
                <div className="space-y-3">
                  {urgentAttention.map((item) => (
                    <button
                      key={item.id}
                      onClick={onReviewAttentionInbox}
                      className="group flex w-full items-baseline gap-3 rounded-lg border border-amber-400/20 bg-amber-400/[0.04] px-4 py-3 text-left transition-colors hover:border-amber-300/40 hover:bg-amber-400/[0.07]"
                    >
                      <span className="min-w-0 flex-1 text-[15px] font-medium leading-relaxed text-slate-100 group-hover:text-white">
                        {item.title || 'Needs your input'}
                      </span>
                      <span className="flex-shrink-0 text-xs text-slate-500">
                        {item.created_at ? formatRelativeTime(item.created_at) : ''}
                      </span>
                    </button>
                  ))}
                  {missionAwaitingCount > 0 && (
                    <button
                      onClick={() => onNavigate('automations')}
                      className="group flex w-full items-baseline gap-3 rounded-lg border border-amber-400/20 bg-amber-400/[0.04] px-4 py-3 text-left transition-colors hover:border-amber-300/40 hover:bg-amber-400/[0.07]"
                    >
                      <span className="text-[15px] font-medium leading-relaxed text-slate-100 group-hover:text-white">
                        {missionAwaitingCount} {missionAwaitingCount === 1 ? 'mission is' : 'missions are'} waiting on a decision from you
                      </span>
                    </button>
                  )}
                </div>
              ) : (
                <p className="rounded-lg border border-white/8 bg-white/[0.02] px-4 py-3 text-[15px] text-slate-500">
                  Nothing needs you right now.
                </p>
              )}
            </section>

            {/* Morning brief */}
            <section>
              <SectionHeading
                label="Morning brief"
                action={
                  <div className="flex items-center gap-3">
                    {morningBrief && (
                      <QuietLink onClick={onPlayBriefAudio}>
                        {briefAudioPlaying ? '⏸ Pause' : '▸ Listen'}
                      </QuietLink>
                    )}
                    <QuietLink onClick={() => onNavigate('briefings')}>Open full brief →</QuietLink>
                  </div>
                }
              />
              {morningBriefLoading ? (
                <p className="text-sm text-slate-500">Loading brief…</p>
              ) : morningBrief ? (
                <div
                  className="prose prose-invert max-w-none rounded-xl border border-white/8 bg-white/[0.02] px-5 py-4 text-[15px] leading-relaxed text-slate-300
                    prose-headings:mb-1 prose-headings:mt-3 prose-headings:text-[13px] prose-headings:font-semibold prose-headings:uppercase prose-headings:tracking-wide prose-headings:text-slate-400
                    prose-p:my-1.5 prose-ul:my-1.5 prose-li:my-0.5 prose-strong:font-medium prose-strong:text-slate-100"
                >
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {(() => {
                      const text = morningBrief.full_text || morningBrief.summary || ''
                      if (text.length <= 600) return text
                      const cut = text.slice(0, 600)
                      return `${cut.slice(0, Math.max(cut.lastIndexOf('\n'), cut.lastIndexOf(' ')))}…`
                    })()}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="text-sm text-slate-500">No brief available yet today.</p>
              )}
            </section>

            {/* Today's schedule */}
            <section>
              <SectionHeading
                label="Today"
                action={<QuietLink onClick={() => onNavigate('calendar')}>Open calendar →</QuietLink>}
              />
              {calendarEvents.length > 0 ? (
                <div className="space-y-2.5">
                  {calendarEvents.map((evt: any, i: number) => {
                    const start = new Date(evt.start_time || evt.start || evt.dtstart)
                    const end = new Date(evt.end_time || evt.end || evt.dtend)
                    const now = new Date()
                    const isAllDay = Boolean(evt.all_day) || end.getTime() - start.getTime() >= 23 * 60 * 60 * 1000
                    const isNow = !isAllDay && now >= start && now <= end
                    const isPast = !isAllDay && now > end
                    return (
                      <div
                        key={evt.id || i}
                        className={`flex items-baseline gap-4 rounded-lg px-3 py-2 ${
                          isNow ? 'bg-teal-400/[0.06]' : ''
                        }`}
                      >
                        <span
                          className={`w-[4.5rem] flex-shrink-0 text-right text-sm tabular-nums ${
                            isNow ? 'font-medium text-teal-300' : 'text-slate-500'
                          }`}
                        >
                          {isAllDay
                            ? 'All day'
                            : start.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}
                        </span>
                        <div className="min-w-0 flex-1">
                          <span
                            className={`text-[15px] ${
                              isNow
                                ? 'font-medium text-teal-200'
                                : isPast
                                  ? 'text-slate-500 line-through decoration-slate-700'
                                  : 'text-slate-200'
                            }`}
                          >
                            {evt.title || evt.summary}
                            {isNow && <span className="ml-2 text-xs font-normal text-teal-400">now</span>}
                          </span>
                          {evt.location && <span className="ml-2 text-xs text-slate-500">{evt.location}</span>}
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <p className="text-sm text-slate-500">No events today.</p>
              )}
            </section>

            {/* Ongoing: standing orders + timers */}
            {(standingOrders.length > 0 || timers.length > 0) && (
              <section>
                <SectionHeading label="Ongoing" />
                <div className="space-y-2.5">
                  {timers.map((timer: any) => (
                    <div key={timer.id} className="flex items-baseline gap-4">
                      <LiveTimer
                        endTime={timer.end_time}
                        className="w-[4.5rem] flex-shrink-0 text-right font-mono text-sm text-teal-300"
                      />
                      <span className="min-w-0 flex-1 truncate text-[15px] text-slate-200">{timer.title}</span>
                    </div>
                  ))}
                  {standingOrders.slice(0, 4).map((order: any) => (
                    <div key={order.id} className="flex items-baseline gap-4">
                      <span className="w-[4.5rem] flex-shrink-0 text-right text-sm tabular-nums text-slate-500">
                        {order.fires_at
                          ? new Date(order.fires_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
                          : order.scheduled_time || '—'}
                      </span>
                      <span className="min-w-0 flex-1 text-[15px] leading-relaxed text-slate-300">
                        {order.description}
                        {order.trigger_config?.one_shot && (
                          <span className="ml-2 text-xs text-slate-500">one-time</span>
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </div>

          {/* RIGHT RAIL — what Sara's been up to */}
          <aside className="space-y-12 lg:border-l lg:border-white/8 lg:pl-10">
            {/* What Sara's been doing, in her own words */}
            <ActivityDigest timeAgo={formatRelativeTime} />

            {/* Sara's journal */}
            {journalEntries.length > 0 && (
              <section>
                <SectionHeading label="Sara's journal" />
                <div className="space-y-5">
                  {journalEntries.slice(0, 3).map((entry: any, i: number) => {
                    const entryKey = String(entry.id || i)
                    const fullContent =
                      entry.content || entry.details?.full_content || entry.summary || entry.text || ''
                    const isExpanded = expandedJournalEntries.has(entryKey)
                    const shouldTruncate = fullContent.length > 240 && !isExpanded
                    const displayText = shouldTruncate
                      ? `${fullContent.slice(0, 240).trimEnd()}…`
                      : fullContent

                    return (
                      <div key={entry.id || i}>
                        <p className="text-[14px] leading-relaxed text-slate-400 whitespace-pre-wrap break-words">
                          {displayText}
                        </p>
                        <div className="mt-1.5 flex items-center gap-2 text-xs text-slate-500">
                          {(entry.timestamp || entry.created_at) && (
                            <span>
                              {new Date(entry.timestamp || entry.created_at).toLocaleTimeString('en-US', {
                                hour: 'numeric',
                                minute: '2-digit',
                              })}
                            </span>
                          )}
                          {entry.emotional_state && (
                            <span>
                              {emotionEmoji[entry.emotional_state] || ''} {entry.emotional_state}
                            </span>
                          )}
                          {fullContent.length > 240 && (
                            <button
                              onClick={() => onToggleJournalEntry(entryKey)}
                              className="text-teal-400/80 transition-colors hover:text-teal-300"
                            >
                              {isExpanded ? 'Show less' : 'Read more'}
                            </button>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </section>
            )}
          </aside>
        </div>
      </div>

      {/* Ask dock — Sara is always one keystroke away */}
      {onAskSara && (
        <div className="pointer-events-none sticky bottom-0 left-0 right-0">
          <div className="mx-auto w-full max-w-[1180px] px-4 pb-4 md:px-8">
            <form
              onSubmit={submitAsk}
              className="pointer-events-auto flex items-center gap-2 rounded-2xl border border-white/10 bg-[#0c1626]/95 px-4 py-1.5 shadow-[0_8px_40px_rgba(2,8,23,0.6)] backdrop-blur-xl transition-colors focus-within:border-teal-300/30"
            >
              <span className="material-icons text-[18px] text-teal-300/70">auto_awesome</span>
              <input
                value={askDraft}
                onChange={(e) => setAskDraft(e.target.value)}
                placeholder="Ask Sara anything…"
                className="min-w-0 flex-1 bg-transparent py-2.5 text-[15px] text-slate-100 placeholder-slate-500 outline-none"
              />
              <button
                type="submit"
                disabled={!askDraft.trim()}
                className="rounded-xl p-2 text-slate-500 transition-colors enabled:text-teal-300 enabled:hover:bg-teal-400/10 disabled:opacity-40"
                aria-label="Send to Sara"
              >
                <span className="material-icons text-[18px]">arrow_upward</span>
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
