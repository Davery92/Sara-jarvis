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
  critical: 'border-red-400/15 bg-red-500/[0.06] hover:bg-red-500/[0.09]',
  warning: 'border-amber-400/15 bg-amber-500/[0.06] hover:bg-amber-500/[0.09]',
  normal: 'border-white/5 bg-white/[0.025] hover:bg-white/[0.045]',
}

const toneDotClasses: Record<LaneTone, string> = {
  critical: 'bg-red-300 shadow-[0_0_14px_rgba(248,113,113,0.45)]',
  warning: 'bg-amber-300 shadow-[0_0_14px_rgba(251,191,36,0.35)]',
  normal: 'bg-teal-300 shadow-[0_0_14px_rgba(94,234,212,0.32)]',
}

const laneAccentClasses: Record<LaneTone, string> = {
  critical: 'from-red-300/28',
  warning: 'from-amber-300/24',
  normal: 'from-teal-300/20',
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
  tone = 'normal',
}: {
  title: string
  subtitle: string
  items: LaneItem[]
  emptyLabel: string
  tone?: LaneTone
}) {
  return (
    <div className="assistant-panel-soft relative overflow-hidden rounded-2xl p-4">
      <div className={`absolute inset-x-0 top-0 h-px bg-gradient-to-r ${laneAccentClasses[tone]} via-white/8 to-transparent`} />
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-semibold text-white">{title}</h3>
          <p className="mt-1 text-xs leading-relaxed text-slate-500">{subtitle}</p>
        </div>
        <span className="rounded-full border border-white/8 bg-white/[0.03] px-2.5 py-1 text-xs font-medium text-slate-400">
          {items.length}
        </span>
      </div>
      <div className="space-y-2">
        {items.length === 0 ? (
          <div className="assistant-panel-muted rounded-2xl px-3 py-3 text-xs text-slate-500">
            {emptyLabel}
          </div>
        ) : (
          items.map((item) => (
            <button
              key={item.id}
              onClick={item.onClick}
              className={`w-full rounded-2xl border px-3 py-3 text-left transition ${toneClasses[item.tone]}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full mt-0.5 flex-shrink-0 ${toneDotClasses[item.tone]}`} />
                    <p className="truncate text-sm font-medium text-slate-100">{item.title}</p>
                  </div>
                  <p className="ml-4 mt-1 truncate text-xs text-slate-500">{item.subtitle}</p>
                </div>
                {item.cta && (
                  <span className="flex-shrink-0 rounded-full border border-white/8 bg-slate-950/40 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
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
    <div className="assistant-panel rounded-3xl p-5">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div>
          <div className="assistant-kicker mb-2">Mission Control</div>
          <h2 className="font-display text-xl font-semibold text-white">What needs movement</h2>
          <p className="mt-2 text-sm text-slate-500">
            {attentionUnreadCount > 0
              ? `${attentionUnreadCount} attention item(s) need review`
              : 'No unread attention items'}
          </p>
        </div>
        <button
          onClick={() => onNavigate('inbox')}
          className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-2 text-sm font-medium text-slate-200 transition hover:bg-white/[0.06] hover:text-white"
        >
          Open Inbox
        </button>
      </div>
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
        <LaneColumn
          title="Now"
          subtitle="Urgent and in-progress"
          items={lanes.nowItems}
          emptyLabel="No urgent work right now."
          tone={lanes.nowItems.some((item) => item.tone === 'critical') ? 'critical' : 'normal'}
        />
        <LaneColumn
          title="Soon"
          subtitle="Queued and upcoming"
          items={lanes.soonItems}
          emptyLabel="Nothing queued for the next window."
          tone="normal"
        />
        <LaneColumn
          title="Needs Decision"
          subtitle="Items waiting on your input"
          items={lanes.decisionItems}
          emptyLabel="No pending decisions."
          tone={lanes.decisionItems.length > 0 ? 'warning' : 'normal'}
        />
      </div>
    </div>
  )
}
