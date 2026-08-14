import React from 'react'
import LiveTimer from './LiveTimer'

interface TimelineRow {
  key: string
  kind: 'calendar' | 'reminder' | 'timer' | 'training'
  time: Date | null
  isAllDay: boolean
  glyph: string
  label: string
  sub?: string
  isNow: boolean
  isPast: boolean
  isTimer?: boolean
  timerEndTime?: string
}

/**
 * Card B — Today timeline (mission-control redesign §4.3). One chronological
 * rail merging calendar, reminders, timers, and the training session — the
 * merge is the point, not three separate lists.
 */
export default function TodayTimeline({
  calendarEvents,
  reminders,
  timers,
  todayTemplate,
  activeWorkout,
  currentTime,
  onNavigate,
}: {
  calendarEvents: any[]
  reminders: any[]
  timers: any[]
  todayTemplate: any
  activeWorkout: any
  currentTime: Date
  onNavigate: (view: any) => void
}) {
  const now = currentTime

  const rows: TimelineRow[] = []

  calendarEvents.forEach((evt: any, i: number) => {
    const start = new Date(evt.start_time || evt.start || evt.dtstart)
    const end = new Date(evt.end_time || evt.end || evt.dtend)
    const isAllDay = Boolean(evt.all_day) || end.getTime() - start.getTime() >= 23 * 60 * 60 * 1000
    const isNow = !isAllDay && now >= start && now <= end
    const isPast = !isAllDay && now > end
    rows.push({
      key: `evt-${evt.id || i}`,
      kind: 'calendar',
      time: isAllDay ? null : start,
      isAllDay,
      glyph: '📅',
      label: evt.title || evt.summary,
      sub: evt.location,
      isNow,
      isPast,
    })
  })

  reminders.forEach((r: any) => {
    const time = new Date(r.reminder_time)
    rows.push({
      key: `rem-${r.id}`,
      kind: 'reminder',
      time,
      isAllDay: false,
      glyph: '🔔',
      label: r.title,
      isNow: false,
      isPast: time < now,
    })
  })

  timers.forEach((t: any) => {
    const end = new Date(t.end_time)
    const finished = end <= now
    rows.push({
      key: `timer-${t.id}`,
      kind: 'timer',
      time: end,
      isAllDay: false,
      glyph: '⏱',
      label: t.title,
      isNow: !finished,
      isPast: finished,
      isTimer: true,
      timerEndTime: t.end_time,
    })
  })

  if (activeWorkout) {
    const start = activeWorkout.started_at ? new Date(activeWorkout.started_at) : now
    rows.push({
      key: 'active-workout',
      kind: 'training',
      time: start,
      isAllDay: false,
      glyph: '🏋',
      label: `${activeWorkout.workout_snapshot?.template_name || 'Workout'} — in progress`,
      isNow: true,
      isPast: false,
    })
  } else if (todayTemplate) {
    const exerciseCount = Array.isArray(todayTemplate.exercises) ? todayTemplate.exercises.length : null
    rows.push({
      key: 'today-template',
      kind: 'training',
      time: null,
      isAllDay: true,
      glyph: '🏋',
      label: `${todayTemplate.name}${exerciseCount != null ? ` — ${exerciseCount} exercises` : ''}`,
      isNow: false,
      isPast: false,
    })
  }

  const allDayRows = rows.filter((r) => r.isAllDay)
  const timedRows = rows
    .filter((r) => !r.isAllDay)
    .sort((a, b) => (a.time?.getTime() || 0) - (b.time?.getTime() || 0))

  const nowIndex = timedRows.findIndex((r) => (r.time?.getTime() || 0) >= now.getTime())

  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-white/8 bg-white/[0.02] p-4">
        <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Today</h2>
        <p className="text-sm text-slate-500">Clear day.</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.02] p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Today</h2>
        <button
          onClick={() => onNavigate('calendar')}
          className="text-xs text-slate-500 transition-colors hover:text-teal-300"
        >
          Open calendar →
        </button>
      </div>
      <div className="space-y-1">
        {allDayRows.map((row) => (
          <TimelineLine key={row.key} row={row} />
        ))}
        {timedRows.map((row, i) => (
          <React.Fragment key={row.key}>
            {i === nowIndex && i > 0 && <div className="my-1 h-px bg-teal-400/40" />}
            <TimelineLine row={row} />
          </React.Fragment>
        ))}
      </div>
    </div>
  )
}

function TimelineLine({ row }: { row: TimelineRow }) {
  return (
    <div className={`flex items-baseline gap-3 rounded-lg px-2 py-1.5 ${row.isNow ? 'bg-teal-400/[0.06]' : ''}`}>
      <span
        className={`w-[4.5rem] flex-shrink-0 text-right text-sm tabular-nums ${
          row.isNow ? 'font-medium text-teal-300' : 'text-slate-500'
        }`}
      >
        {row.isTimer && row.timerEndTime ? (
          <LiveTimer endTime={row.timerEndTime} />
        ) : row.isAllDay || !row.time ? (
          'All day'
        ) : (
          row.time.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
        )}
      </span>
      <span className="w-4 flex-shrink-0 text-center text-sm">{row.glyph}</span>
      <div className="min-w-0 flex-1">
        <span
          className={`text-[15px] ${
            row.isNow
              ? 'font-medium text-teal-200'
              : row.isPast
                ? row.kind === 'calendar'
                  ? 'text-slate-500 line-through decoration-slate-700'
                  : 'text-slate-500'
                : 'text-slate-200'
          }`}
        >
          {row.label}
          {row.isNow && <span className="ml-2 text-xs font-normal text-teal-400">now</span>}
        </span>
        {row.sub && <span className="ml-2 text-xs text-slate-500">{row.sub}</span>}
      </div>
    </div>
  )
}
