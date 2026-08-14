import React from 'react'
import { formatFutureRelativeTime } from '../shellDisplay'

/**
 * Card F — Ongoing (mission-control redesign §4.7). Standing orders + running
 * missions in a two-column flow. Renders only when non-empty; timers moved
 * out to the timeline + KPI strip.
 */
export default function OngoingCard({
  standingOrders,
  missions,
  formatRelativeTime,
  onNavigate,
}: {
  standingOrders: any[]
  missions: any[]
  formatRelativeTime: (ts: string) => string
  onNavigate: (view: any) => void
}) {
  const runningMissions = missions.filter((m: any) => m.state === 'running')

  if (standingOrders.length === 0 && runningMissions.length === 0) return null

  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.02] p-4">
      <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Ongoing</h2>
      <div className="grid grid-cols-1 gap-x-8 gap-y-2.5 md:grid-cols-2">
        {runningMissions.map((mission: any) => (
          <button
            key={mission.id}
            onClick={() => onNavigate('automations')}
            className="flex items-baseline gap-3 text-left transition-colors hover:text-teal-200"
          >
            <span className="w-[4.5rem] flex-shrink-0 text-right text-sm tabular-nums text-slate-500">
              {mission.started_at ? formatRelativeTime(mission.started_at) : '—'}
            </span>
            <span className="min-w-0 flex-1 truncate text-[15px] text-slate-300">{mission.title}</span>
          </button>
        ))}
        {standingOrders.slice(0, 4).map((order: any) => (
          <div key={order.id} className="flex items-baseline gap-3">
            <span className="w-[4.5rem] flex-shrink-0 text-right text-sm tabular-nums text-slate-500">
              {order.fires_at ? formatFutureRelativeTime(order.fires_at) : '—'}
            </span>
            <span className="min-w-0 flex-1 truncate text-[15px] text-slate-300">{order.description}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
