import React from 'react'

import { AppView } from '../../navigation/views'
import { MomentCardStack } from '../MomentCardStack'
import HeaderBand from './dashboard/HeaderBand'
import StatTile from './dashboard/StatTile'
import NeedsYouCard from './dashboard/NeedsYouCard'
import TodayTimeline from './dashboard/TodayTimeline'
import SaraRail from './dashboard/SaraRail'
import BriefCard from './dashboard/BriefCard'
import BodyCard from './dashboard/BodyCard'
import OngoingCard from './dashboard/OngoingCard'
import LiveTimer from './dashboard/LiveTimer'

function findSection(sections: any[], type: string) {
  return (sections || []).find((s: any) => s?.type === type) || null
}

interface DashboardHomeViewProps {
  attentionItems: any[]
  needsYouTotal: number
  missions: any[]
  missionAwaitingCount: number
  runningMissionCount: number
  todayReminders: any[]
  timers: any[]
  calendarEvents: any[]
  standingOrders: any[]
  onNavigate: (view: AppView) => void
  greeting: string
  weather: any
  weatherEmoji: Record<string, string>
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
  digest: { items: { text: string; at: string; delivered?: boolean }[]; machinery: { tool_calls: number; errors: number } } | null
  briefLoaded: boolean
  quietLine: string | null
  formatRelativeTime: (ts: string) => string
  onAskSara?: (prompt: string) => void
  briefSections: any[]
  saraStatusLine: { emotional_state?: string; latest_thought?: string | null; watching_for?: string[] | null; kernel_state?: string } | null
  activityState: string | null
  interruptibility: number | null
  suggestedActions: { label: string; message: string; icon?: string }[]
  selfStatus: { healthy: boolean; degraded: { subsystem: string; name: string; impact: string; severity: string }[] } | null
  timePeriod: string | null
  recovery: any
  todayTemplate: any
  activeWorkout: any
  weightTrend: any[]
  onVerificationAnswer: (pkgId: string, confirmed: boolean) => void
}

export default function DashboardHomeView({
  attentionItems,
  needsYouTotal,
  missions,
  missionAwaitingCount,
  runningMissionCount,
  todayReminders,
  timers,
  calendarEvents,
  standingOrders,
  onNavigate,
  greeting,
  weather,
  weatherEmoji,
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
  digest,
  briefLoaded,
  quietLine,
  formatRelativeTime,
  onAskSara,
  briefSections,
  saraStatusLine,
  activityState,
  interruptibility,
  suggestedActions,
  selfStatus,
  timePeriod,
  recovery,
  todayTemplate,
  activeWorkout,
  weightTrend,
  onVerificationAnswer,
}: DashboardHomeViewProps) {
  const [askDraft, setAskDraft] = React.useState('')

  const needsYouCount = needsYouTotal + missionAwaitingCount
  const oldestNeedsYou = attentionItems[0]

  const upcomingEvents = calendarEvents.filter((evt: any) => {
    const end = new Date(evt.end_time || evt.end || evt.dtend || evt.start_time || evt.start)
    return end.getTime() >= currentTime.getTime()
  })

  const dateLine = currentTime.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  })

  const calendarSection = findSection(briefSections, 'calendar')
  const fitnessSection = findSection(briefSections, 'fitness')
  const learningSection = findSection(briefSections, 'learning')
  const threadsSection = findSection(briefSections, 'threads')
  const verificationSection = findSection(briefSections, 'verification')

  const nextInMinutes = calendarSection?.data?.next_in_minutes
  const reviewsDue = learningSection?.data?.reviews_due || 0
  const fitness = fitnessSection?.data || null
  const threadTopics: string[] = threadsSection?.data?.topics || []

  const activeTimer = timers.find((t: any) => new Date(t.end_time) > currentTime)

  const submitAsk = (e: React.FormEvent) => {
    e.preventDefault()
    const prompt = askDraft.trim()
    if (!prompt || !onAskSara) return
    setAskDraft('')
    onAskSara(prompt)
  }

  return (
    <div className="relative flex-1 overflow-y-auto min-h-0">
      <div className="mx-auto w-full max-w-[1440px] px-4 pb-36 pt-4 md:px-8 md:pt-6">
        <MomentCardStack />

        <HeaderBand
          greeting={greeting}
          dateLine={dateLine}
          weather={weather}
          weatherEmoji={weatherEmoji}
          emotionalState={saraStatusLine?.emotional_state || null}
          kernelState={saraStatusLine?.kernel_state || null}
          degraded={!selfStatus?.healthy ? selfStatus?.degraded || [] : null}
          onOpenDiagnostics={() => onNavigate('interior')}
        />

        {/* KPI strip — one row, horizontal scroll below lg */}
        <div className="mt-2 flex gap-2.5 overflow-x-auto pb-1 snap-x lg:flex-wrap lg:overflow-visible">
          {needsYouCount > 0 && (
            <StatTile
              label="Need you"
              value={needsYouCount}
              sub={oldestNeedsYou?.created_at ? formatRelativeTime(oldestNeedsYou.created_at) : undefined}
              tone="amber"
              onClick={onReviewAttentionInbox}
            />
          )}
          {upcomingEvents.length > 0 && (
            <StatTile
              label="Events"
              value={upcomingEvents.length}
              sub={nextInMinutes != null ? `next in ${nextInMinutes}m` : undefined}
              onClick={() => onNavigate('calendar')}
            />
          )}
          <StatTile
            label="Calories"
            value={`${(fitness?.calories_today ?? 0).toLocaleString()}${fitness?.goal ? ` / ${fitness.goal.toLocaleString()}` : ''}`}
            sub={fitness?.goal ? `${Math.max(0, fitness.goal - (fitness.calories_today ?? 0)).toLocaleString()} left` : undefined}
            onClick={() => onNavigate('fitness')}
          />
          <StatTile
            label="Protein"
            value={`${(fitness?.protein_today ?? 0).toLocaleString()}g`}
            onClick={() => onNavigate('fitness')}
          />
          {recovery?.readiness_score != null && (
            <StatTile
              label="Recovery"
              value={recovery.readiness_score}
              sub={recovery.readiness_label || undefined}
              onClick={() => onNavigate('fitness')}
            />
          )}
          {reviewsDue > 0 && (
            <StatTile label="Reviews due" value={reviewsDue} onClick={() => onNavigate('learn')} />
          )}
          {runningMissionCount > 0 && (
            <StatTile
              label={runningMissionCount === 1 ? 'Mission' : 'Missions'}
              value={runningMissionCount}
              sub={missionAwaitingCount > 0 ? `${missionAwaitingCount} awaiting` : undefined}
              tone="teal"
              onClick={() => onNavigate('automations')}
            />
          )}
          {activeTimer && (
            <StatTile
              label="Timer"
              value={<LiveTimer endTime={activeTimer.end_time} />}
              sub={activeTimer.title}
              tone="teal"
              onClick={() => {}}
            />
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

        {/*
          12-column mission-control grid (§3/§7). Cards are flat grid
          children (not nested per-column wrappers) so `order` can differ by
          breakpoint: mobile priority is A → B → E → D → C → F, desktop
          groups A/D/E into one visual column via B/C's row-span-3 reserving
          their rows before D/E are auto-placed. Sparse auto-placement (the
          grid default) resolves this correctly as long as the order-implied
          traversal at each breakpoint places B and C right after A.
        */}
        <div className="mt-5 grid grid-cols-1 items-start gap-5 lg:grid-cols-12">
          <div className="order-1 lg:order-1 lg:col-span-5">
            <NeedsYouCard
              items={attentionItems}
              missionAwaitingCount={missionAwaitingCount}
              verificationQuestion={verificationSection?.content || null}
              verificationData={verificationSection?.data || null}
              formatRelativeTime={formatRelativeTime}
              onOpenItem={onReviewAttentionInbox}
              onOpenMissions={() => onNavigate('automations')}
              onVerificationAnswer={onVerificationAnswer}
            />
          </div>

          <div className="order-2 lg:order-2 lg:col-span-4 lg:row-span-3">
            <TodayTimeline
              calendarEvents={calendarEvents}
              reminders={todayReminders}
              timers={timers}
              todayTemplate={todayTemplate}
              activeWorkout={activeWorkout}
              currentTime={currentTime}
              onNavigate={onNavigate}
            />
          </div>

          <div className="order-5 lg:order-3 lg:col-span-3 lg:row-span-3">
            <SaraRail
              kernelState={saraStatusLine?.kernel_state || null}
              activityState={activityState}
              emotionalState={saraStatusLine?.emotional_state || null}
              interruptibility={interruptibility}
              latestThought={saraStatusLine?.latest_thought || null}
              watchingFor={saraStatusLine?.watching_for || null}
              digest={digest}
              briefLoaded={briefLoaded}
              quietLine={quietLine}
              formatRelativeTime={formatRelativeTime}
              journalEntries={journalEntries}
              expandedJournalEntries={expandedJournalEntries}
              onToggleJournalEntry={onToggleJournalEntry}
              emotionEmoji={emotionEmoji}
              threadTopics={threadTopics}
              onNavigate={onNavigate}
              onAskSara={onAskSara}
            />
          </div>

          <div className="order-4 lg:order-4 lg:col-span-5">
            <BriefCard
              morningBrief={morningBrief}
              morningBriefLoading={morningBriefLoading}
              briefAudioPlaying={briefAudioPlaying}
              briefAudioRef={briefAudioRef}
              onPlayBriefAudio={onPlayBriefAudio}
              onBriefAudioEnded={onBriefAudioEnded}
              onBriefAudioPaused={onBriefAudioPaused}
              onBriefAudioError={onBriefAudioError}
              timePeriod={timePeriod}
              suggestedActions={suggestedActions}
              onNavigate={onNavigate}
              onAskSara={onAskSara}
            />
          </div>

          <div className="order-3 lg:order-5 lg:col-span-5">
            <BodyCard
              fitness={fitness}
              todayTemplate={todayTemplate}
              activeWorkout={activeWorkout}
              weightTrend={weightTrend}
              onNavigate={onNavigate}
            />
          </div>

          <div className="order-6 lg:order-6 lg:col-span-12">
            <OngoingCard
              standingOrders={standingOrders}
              missions={missions}
              formatRelativeTime={formatRelativeTime}
              onNavigate={onNavigate}
            />
          </div>
        </div>
      </div>

      {/* Ask dock — Sara is always one keystroke away */}
      {onAskSara && (
        <div className="pointer-events-none sticky bottom-0 left-0 right-0">
          <div className="mx-auto w-full max-w-[1440px] px-4 pb-4 md:px-8">
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
