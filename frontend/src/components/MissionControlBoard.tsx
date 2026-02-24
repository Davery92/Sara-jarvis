import React, { useMemo } from 'react'

type LaneTone = 'critical' | 'warning' | 'normal'

interface LaneItem {
  id: string
  title: string
  subtitle: string
  tone: LaneTone
  cta?: string
  onClick?: () => void
}

interface MissionControlBoardProps {
  attentionItems: any[]
  attentionUnreadCount: number
  missions: any[]
  reminders: any[]
  timers: any[]
  calendarEvents: any[]
  candidateSkills?: any[]
  onNavigate: (view: string) => void
}

const toneClasses: Record<LaneTone, string> = {
  critical: 'border-red-500/30 bg-red-500/5',
  warning: 'border-amber-500/30 bg-amber-500/5',
  normal: 'border-teal-500/20 bg-gray-800/40',
}

const toneDotClasses: Record<LaneTone, string> = {
  critical: 'bg-red-400',
  warning: 'bg-amber-400',
  normal: 'bg-teal-400',
}

function safeDate(...candidates: Array<string | null | undefined>): Date | null {
  for (const value of candidates) {
    if (!value) continue
    const parsed = new Date(value)
    if (!Number.isNaN(parsed.getTime())) return parsed
  }
  return null
}

function relativeTime(date: Date | null): string {
  if (!date) return 'time unknown'
  const ms = date.getTime() - Date.now()
  const abs = Math.abs(ms)
  const minutes = Math.round(abs / 60000)

  if (minutes < 1) return 'now'
  if (minutes < 60) return ms >= 0 ? `in ${minutes}m` : `${minutes}m ago`

  const hours = Math.round(minutes / 60)
  if (hours < 24) return ms >= 0 ? `in ${hours}h` : `${hours}h ago`

  const days = Math.round(hours / 24)
  return ms >= 0 ? `in ${days}d` : `${days}d ago`
}

function LaneColumn({
  title,
  subtitle,
  items,
  emptyLabel,
}: {
  title: string
  subtitle: string
  items: LaneItem[]
  emptyLabel: string
}) {
  return (
    <div className="bg-card border border-card rounded-xl p-4">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-gray-200 uppercase tracking-wider">{title}</h3>
        <p className="text-xs text-gray-500 mt-1">{subtitle}</p>
      </div>
      <div className="space-y-2">
        {items.length === 0 ? (
          <div className="rounded-lg border border-gray-700/60 bg-gray-900/50 px-3 py-2 text-xs text-gray-500">
            {emptyLabel}
          </div>
        ) : (
          items.map((item) => (
            <button
              key={item.id}
              onClick={item.onClick}
              className={`w-full text-left rounded-lg border px-3 py-2 transition-colors hover:border-gray-500 ${toneClasses[item.tone]}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full mt-0.5 flex-shrink-0 ${toneDotClasses[item.tone]}`} />
                    <p className="text-sm text-gray-100 truncate">{item.title}</p>
                  </div>
                  <p className="text-xs text-gray-400 mt-1 ml-4 truncate">{item.subtitle}</p>
                </div>
                {item.cta && (
                  <span className="text-[10px] px-2 py-0.5 rounded bg-gray-700 text-gray-300 flex-shrink-0">
                    {item.cta}
                  </span>
                )}
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  )
}

export default function MissionControlBoard({
  attentionItems,
  attentionUnreadCount,
  missions,
  reminders,
  timers,
  calendarEvents,
  candidateSkills = [],
  onNavigate,
}: MissionControlBoardProps) {
  const lanes = useMemo(() => {
    const nowItems: LaneItem[] = []
    const soonItems: LaneItem[] = []
    const decisionItems: LaneItem[] = []

    const awaitingConfirm = missions
      .filter((m) => m.state === 'awaiting_confirm')
      .slice(0, 4)

    awaitingConfirm.forEach((mission) => {
      const createdAt = safeDate(mission.created_at)
      const item: LaneItem = {
        id: `awaiting-${mission.id}`,
        title: mission.title || 'Mission awaiting confirmation',
        subtitle: `Awaiting confirmation • ${relativeTime(createdAt)}`,
        tone: 'critical',
        cta: 'Review',
        onClick: () => onNavigate('inbox'),
      }
      nowItems.push(item)
      decisionItems.push(item)
    })

    missions
      .filter((m) => m.state === 'running')
      .slice(0, 4)
      .forEach((mission) => {
        const progress = mission.total_steps
          ? `${mission.completed_steps || 0}/${mission.total_steps} steps`
          : 'in progress'
        nowItems.push({
          id: `running-${mission.id}`,
          title: mission.title || 'Running mission',
          subtitle: `Mission running • ${progress}`,
          tone: 'normal',
          cta: 'Open',
          onClick: () => onNavigate('inbox'),
        })
      })

    timers
      .filter((t) => t.is_active)
      .slice(0, 3)
      .forEach((timer) => {
        const endsAt = safeDate(timer.end_time)
        nowItems.push({
          id: `timer-${timer.id}`,
          title: timer.title || 'Active timer',
          subtitle: `Ends ${relativeTime(endsAt)}`,
          tone: 'warning',
          cta: 'Home',
          onClick: () => onNavigate('dashboard'),
        })
      })

    reminders
      .filter((r) => !r.completed && !r.is_completed)
      .map((r) => ({
        raw: r,
        due: safeDate(r.reminder_time, r.due_date),
      }))
      .filter((entry) => entry.due)
      .sort((a, b) => (a.due!.getTime() - b.due!.getTime()))
      .forEach(({ raw, due }) => {
        if (!due) return
        const diffMin = Math.round((due.getTime() - Date.now()) / 60000)
        if (diffMin <= 60 && diffMin >= -30 && nowItems.length < 10) {
          nowItems.push({
            id: `reminder-now-${raw.id}`,
            title: raw.title || 'Reminder',
            subtitle: `Due ${relativeTime(due)}`,
            tone: diffMin <= 15 ? 'critical' : 'warning',
            cta: 'Home',
            onClick: () => onNavigate('dashboard'),
          })
        } else if (diffMin > 60 && diffMin <= 24 * 60 && soonItems.length < 8) {
          soonItems.push({
            id: `reminder-soon-${raw.id}`,
            title: raw.title || 'Reminder',
            subtitle: `Due ${relativeTime(due)}`,
            tone: 'normal',
            cta: 'Home',
            onClick: () => onNavigate('dashboard'),
          })
        }
      })

    missions
      .filter((m) => m.state === 'pending')
      .slice(0, 4)
      .forEach((mission) => {
        soonItems.push({
          id: `pending-${mission.id}`,
          title: mission.title || 'Pending mission',
          subtitle: `Queued mission • ${relativeTime(safeDate(mission.created_at))}`,
          tone: 'normal',
          cta: 'Open',
          onClick: () => onNavigate('inbox'),
        })
      })

    calendarEvents
      .map((evt) => ({
        raw: evt,
        start: safeDate(evt.start_time, evt.start, evt.dtstart),
      }))
      .filter((entry) => entry.start)
      .sort((a, b) => a.start!.getTime() - b.start!.getTime())
      .slice(0, 4)
      .forEach(({ raw, start }) => {
        if (!start) return
        soonItems.push({
          id: `event-${raw.id || raw.title}`,
          title: raw.title || raw.summary || 'Calendar event',
          subtitle: `Starts ${relativeTime(start)}`,
          tone: 'normal',
          cta: 'Calendar',
          onClick: () => onNavigate('calendar'),
        })
      })

    attentionItems
      .filter((item) => item.status === 'new' || item.status === 'sent')
      .slice(0, 6)
      .forEach((item) => {
        decisionItems.push({
          id: `attention-${item.id}`,
          title: item.title || 'Attention item',
          subtitle: `${item.priority || 'normal'} priority • ${relativeTime(safeDate(item.created_at))}`,
          tone: item.priority === 'urgent' || item.priority === 'critical' ? 'critical' : 'warning',
          cta: 'Inbox',
          onClick: () => onNavigate('inbox'),
        })
      })

    candidateSkills
      .filter((s) => s.status === 'pending')
      .slice(0, 3)
      .forEach((skill) => {
        decisionItems.push({
          id: `skill-${skill.id}`,
          title: `Skill: ${skill.name}`,
          subtitle: `Agent-proposed skill • ${relativeTime(safeDate(skill.created_at))}`,
          tone: 'warning',
          cta: 'Review',
          onClick: () => onNavigate('settings'),
        })
      })

    return {
      nowItems: nowItems.slice(0, 6),
      soonItems: soonItems.slice(0, 6),
      decisionItems: decisionItems.slice(0, 6),
    }
  }, [attentionItems, missions, reminders, timers, calendarEvents, candidateSkills, onNavigate])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">Mission Control</h2>
          <p className="text-xs text-gray-500 mt-1">
            {attentionUnreadCount > 0
              ? `${attentionUnreadCount} attention item(s) need review`
              : 'No unread attention items'}
          </p>
        </div>
        <button
          onClick={() => onNavigate('inbox')}
          className="text-xs px-3 py-1.5 rounded-lg border border-teal-500/30 text-teal-400 hover:bg-teal-500/10"
        >
          Open Inbox
        </button>
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
        <LaneColumn
          title="Now"
          subtitle="Urgent and in-progress"
          items={lanes.nowItems}
          emptyLabel="No urgent work right now."
        />
        <LaneColumn
          title="Soon"
          subtitle="Queued and upcoming"
          items={lanes.soonItems}
          emptyLabel="Nothing queued for the next window."
        />
        <LaneColumn
          title="Needs Decision"
          subtitle="Items waiting on your input"
          items={lanes.decisionItems}
          emptyLabel="No pending decisions."
        />
      </div>
    </div>
  )
}
