import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { AppView } from '../../navigation/views'
import DashboardTasks from '../DashboardTasks'
import SaraStatusCard from '../SaraStatusCard'
import MissionControlBoard from '../MissionControlBoard'
import SystemEventsTicker from '../SystemEventsTicker'

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

      if (hours > 0) {
        setTimeLeft(`${hours}h ${minutes}m ${seconds}s`)
      } else if (minutes > 0) {
        setTimeLeft(`${minutes}m ${seconds}s`)
      } else {
        setTimeLeft(`${seconds}s`)
      }
    }

    updateTimer()
    const interval = setInterval(updateTimer, 1000)
    return () => clearInterval(interval)
  }, [endTime])

  return <span className={className}>{timeLeft}</span>
}

export default function DashboardHomeView({
  attentionItems,
  attentionUnreadCount,
  missions,
  reminders,
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
  saraStatus,
  connectedDevices,
  standingOrders,
  formatRelativeTime,
}: DashboardHomeViewProps) {
  const contentUnreadCount = Number(contentInboxStats?.unread || 0)
  const heroStats = [
    {
      label: 'Attention',
      value: attentionUnreadCount,
      detail: attentionUnreadCount > 0 ? 'Needs your input' : 'Quiet right now',
      accent: 'text-teal-200',
      icon: 'notifications_active',
    },
    {
      label: 'Captures',
      value: contentUnreadCount,
      detail: contentUnreadCount > 0 ? 'Waiting in inbox' : 'Inbox is clear',
      accent: 'text-sky-200',
      icon: 'description',
    },
    {
      label: 'Missions',
      value: missionAwaitingCount > 0 ? missionAwaitingCount : runningMissionCount,
      detail: missionAwaitingCount > 0 ? 'Waiting on you' : 'Running in background',
      accent: missionAwaitingCount > 0 ? 'text-amber-200' : 'text-teal-200',
      icon: 'bolt',
    },
  ]

  return (
    <div className="flex-1 overflow-y-auto min-h-0 grid grid-cols-1 lg:grid-cols-3 gap-3 md:gap-4">
      <div className="lg:col-span-2 space-y-3 md:space-y-4">
        <div className="assistant-panel rounded-3xl p-4 md:p-5">
          <div className="flex items-start justify-between gap-3 mb-3">
            <div>
              <div className="assistant-kicker mb-2">Today</div>
              <h1 className="font-display text-xl md:text-2xl font-semibold text-white">{greeting}</h1>
              {weather && (
                <p className="mt-2 inline-flex items-center gap-2 rounded-full border border-white/8 bg-white/[0.03] px-2.5 py-1 text-xs text-slate-300">
                  {weatherEmoji[weather.current?.icon || weather.icon] || weatherEmoji['clear-day']}{' '}
                  {Math.round(weather.current?.temperature ?? weather.temperature ?? weather.temp ?? 0)}&deg;F
                  <span className="text-slate-500">·</span>
                  {weather.current?.description || weather.description || weather.summary || 'Clear'}
                </p>
              )}
            </div>
            {morningBrief && (
              <button
                onClick={onPlayBriefAudio}
                className="flex items-center gap-1.5 rounded-2xl border border-teal-200/15 bg-teal-300/10 px-3.5 py-2 text-teal-100 transition-colors hover:bg-teal-300/16"
              >
                <span className="material-icons text-sm">{briefAudioPlaying ? 'pause' : 'play_arrow'}</span>
                <span className="text-xs font-medium">{briefAudioPlaying ? 'Pause' : 'Listen'}</span>
              </button>
            )}
          </div>

          {morningBrief && (
            <audio
              ref={briefAudioRef}
              onEnded={onBriefAudioEnded}
              onPause={onBriefAudioPaused}
              onError={onBriefAudioError}
              style={{ display: 'none' }}
            />
          )}

          {morningBriefLoading ? (
            <div className="flex items-center gap-2 text-gray-500 py-4">
              <div className="animate-spin w-4 h-4 border-2 border-gray-500 border-t-transparent rounded-full"></div>
              <span className="text-sm">Loading brief...</span>
            </div>
          ) : morningBrief ? (
            <div className="assistant-panel-soft rounded-2xl p-3">
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="assistant-kicker">Morning Brief</div>
                <button
                  onClick={() => onNavigate('briefings')}
                  className="rounded-full border border-white/8 bg-white/[0.03] px-2.5 py-1 text-[11px] text-slate-300 transition hover:bg-white/[0.06] hover:text-white"
                >
                  Open full brief
                </button>
              </div>
              <div
                className="text-gray-300 text-sm leading-relaxed prose prose-invert prose-sm max-w-none
                  prose-headings:text-gray-200 prose-headings:text-sm prose-headings:font-semibold prose-headings:mt-2 prose-headings:mb-1
                  prose-p:my-1 prose-ul:my-1 prose-li:my-0 prose-strong:text-gray-200"
              >
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {(morningBrief.full_text || morningBrief.summary || '').slice(0, 600)}
                </ReactMarkdown>
              </div>
            </div>
          ) : (
            <p className="text-gray-500 text-xs py-1">No brief available yet today.</p>
          )}

          <div className="mt-3 grid gap-2 md:grid-cols-3">
            {heroStats.map((stat) => (
              <button
                key={stat.label}
                onClick={() => {
                  if (stat.label === 'Attention') onReviewAttentionInbox()
                  if (stat.label === 'Captures') onNavigate('inbox')
                  if (stat.label === 'Missions') onNavigate('automations')
                }}
                className="assistant-panel-soft rounded-2xl p-3 text-left transition hover:border-white/14 hover:bg-white/[0.05]"
              >
                <div className="mb-2 flex items-center justify-between">
                  <span className="assistant-kicker">{stat.label}</span>
                  <span className={`material-icons text-base ${stat.accent}`}>{stat.icon}</span>
                </div>
                <div className="font-display text-xl text-white">{stat.value}</div>
                <p className="mt-1 text-xs text-slate-400">{stat.detail}</p>
              </button>
            ))}
          </div>
        </div>

        <MissionControlBoard
          attentionItems={attentionItems}
          attentionUnreadCount={attentionUnreadCount}
          missions={missions}
          reminders={reminders}
          timers={timers}
          calendarEvents={calendarEvents}
          onNavigate={onNavigate}
        />

        <SystemEventsTicker />

        <div className="assistant-panel-soft rounded-2xl p-3 md:p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display text-sm font-semibold text-white">
              {currentTime.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
            </h2>
            <button onClick={() => onNavigate('calendar')} className="text-gray-500 hover:text-teal-400 transition-colors">
              <span className="material-icons text-sm">open_in_new</span>
            </button>
          </div>
          {calendarEvents.length > 0 ? (
            <div className="space-y-2">
              {calendarEvents.map((evt: any, i: number) => {
                const start = new Date(evt.start_time || evt.start || evt.dtstart)
                const end = new Date(evt.end_time || evt.end || evt.dtend)
                const now = new Date()
                const isNow = now >= start && now <= end
                return (
                  <div key={evt.id || i} className="flex items-stretch gap-3">
                    <div className={`w-1 rounded-full flex-shrink-0 ${isNow ? 'bg-teal-400' : 'bg-gray-600'}`}></div>
                    <div className="flex-1 py-1">
                      <div className="flex items-baseline justify-between">
                        <span className={`font-medium text-sm ${isNow ? 'text-teal-400' : 'text-gray-200'}`}>
                          {evt.title || evt.summary}
                        </span>
                        <span className="text-xs text-gray-500 ml-2 flex-shrink-0">
                          {start.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}
                          {' - '}
                          {end.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}
                        </span>
                      </div>
                      {evt.location && <span className="text-xs text-gray-500">{evt.location}</span>}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="text-gray-500 text-sm text-center py-3">No events today</p>
          )}
        </div>

        <DashboardTasks onNavigate={onNavigate} />

        <div className="assistant-panel-soft rounded-2xl p-3 md:p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="assistant-kicker mb-1">Sara&apos;s Journal</div>
              <h2 className="font-display text-sm font-semibold text-white">Recent inner notes</h2>
            </div>
          </div>
          {journalEntries.length > 0 ? (
            <div className="space-y-3">
              {journalEntries.slice(0, 5).map((entry: any, i: number) => {
                const entryKey = String(entry.id || i)
                const fullContent = entry.content || entry.details?.full_content || entry.summary || entry.text || ''
                const isExpanded = expandedJournalEntries.has(entryKey)
                const shouldTruncate = fullContent.length > 280 && !isExpanded
                const displayText = shouldTruncate ? `${fullContent.slice(0, 280).trimEnd()}...` : fullContent

                return (
                  <div key={entry.id || i} className="flex gap-3">
                    <span className="text-xs text-gray-500 flex-shrink-0 w-14 pt-0.5 text-right">
                      {entry.timestamp || entry.created_at
                        ? new Date(entry.timestamp || entry.created_at).toLocaleTimeString('en-US', {
                            hour: 'numeric',
                            minute: '2-digit',
                          })
                        : ''}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap break-words">
                        {displayText}
                      </p>
                      {fullContent.length > 280 && (
                        <button
                          onClick={() => onToggleJournalEntry(entryKey)}
                          className="mt-1 text-xs text-teal-400 hover:text-teal-300 transition-colors"
                        >
                          {isExpanded ? 'Show less' : 'Read full entry'}
                        </button>
                      )}
                      {entry.emotional_state && (
                        <span className="text-xs text-gray-500 mt-0.5 inline-block">
                          {emotionEmoji[entry.emotional_state] || ''} {entry.emotional_state}
                        </span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="text-gray-500 text-sm text-center py-3">No journal entries in the last 24 hours</p>
          )}
        </div>
      </div>

      <div className="lg:col-span-1 space-y-4 md:space-y-6">
        <SaraStatusCard />

        <div className="assistant-panel-muted rounded-2xl p-3">
          <div className="assistant-kicker mb-2">Activity & Devices</div>
          <h2 className="font-display text-sm font-semibold text-white mb-2">Current presence</h2>
          {saraStatus && (
            <div className="mb-4">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-lg">{emotionEmoji[saraStatus.emotional_state] || emotionEmoji.neutral}</span>
                <span className="text-sm text-gray-300 capitalize">{saraStatus.emotional_state || 'neutral'}</span>
              </div>
              {saraStatus.latest_thought && (
                <p className="text-xs text-gray-500 italic leading-relaxed">
                  "{(saraStatus.latest_thought || '').slice(0, 120)}
                  {(saraStatus.latest_thought || '').length > 120 ? '...' : ''}"
                </p>
              )}
            </div>
          )}
          <div className="space-y-2">
            {connectedDevices.length > 0 ? connectedDevices.map((dev: any, i: number) => (
              <div key={dev.device_id || i} className="flex items-center gap-2">
                <div
                  className={`w-2 h-2 rounded-full flex-shrink-0 ${
                    dev.is_connected ? 'bg-green-400' : dev.is_online ? 'bg-yellow-400' : 'bg-gray-600'
                  }`}
                ></div>
                <span className="text-sm text-gray-300">{dev.friendly_name || dev.hostname || 'Unknown'}</span>
                <span className="text-xs text-gray-500 ml-auto">{dev.platform || ''}</span>
              </div>
            )) : (
              <p className="text-gray-500 text-xs">No devices connected</p>
            )}
          </div>
        </div>

        <div className="assistant-panel-muted rounded-2xl p-3">
          <div className="assistant-kicker mb-2">Standing Orders</div>
          <h2 className="font-display text-sm font-semibold text-white mb-2">Keep doing</h2>
          {standingOrders.length > 0 ? (
            <div className="space-y-2">
              {standingOrders.slice(0, 5).map((order: any) => (
                <div key={order.id} className="flex items-start gap-2">
                  <span className="material-icons text-sm text-gray-500 mt-0.5" style={{ fontSize: '16px' }}>
                    {order.trigger_type === 'timer'
                      ? 'timer'
                      : order.trigger_type === 'time'
                        ? 'schedule'
                        : order.trigger_type === 'climate'
                          ? 'thermostat'
                          : order.trigger_type === 'presence'
                            ? 'sensors'
                            : 'auto_awesome'}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-300 leading-tight">{order.description}</p>
                    <div className="flex items-center gap-2 mt-0.5">
                      {order.fires_at && (
                        <span className="text-xs text-amber-400">
                          {new Date(order.fires_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                        </span>
                      )}
                      {order.scheduled_time && (
                        <span className="text-xs text-blue-400">
                          {order.scheduled_time}
                          {order.scheduled_days ? ` (${order.scheduled_days.join(', ')})` : ' daily'}
                        </span>
                      )}
                      {!order.fires_at && !order.scheduled_time && (
                        <span className="text-xs text-gray-500">{order.execution_count || 0} runs</span>
                      )}
                      {order.last_executed_at && (
                        <span className="text-xs text-gray-600">&middot; {formatRelativeTime(order.last_executed_at)}</span>
                      )}
                      {order.trigger_config?.one_shot && (
                        <span className="text-xs text-gray-600">&middot; one-time</span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-500 text-xs text-center py-2">No active standing orders</p>
          )}
        </div>

        {timers.length > 0 && (
          <div className="assistant-panel-muted rounded-2xl p-3">
            <div className="assistant-kicker mb-2">Active Timers</div>
            <h2 className="font-display text-sm font-semibold text-white mb-2">Live countdowns</h2>
            <div className="space-y-2">
              {timers.map((timer: any) => (
                <div key={timer.id} className="flex items-center justify-between bg-gray-800/50 p-2 rounded-lg">
                  <span className="text-sm text-gray-300 truncate mr-2">{timer.title}</span>
                  <LiveTimer endTime={timer.end_time} className="text-teal-400 font-mono text-sm flex-shrink-0" />
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
