import React from 'react'

/**
 * StatTile — fixed anatomy for the KPI strip (mission-control redesign §4.1).
 * Identity is by position + label, not by color — tone only marks tiles
 * that demand action (amber) so it never becomes decorative noise.
 */
export interface StatTileProps {
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  tone?: 'default' | 'amber' | 'teal'
  onClick: () => void
}

export default function StatTile({ label, value, sub, tone = 'default', onClick }: StatTileProps) {
  const valueTone = tone === 'amber' ? 'text-amber-200' : tone === 'teal' ? 'text-teal-200' : 'text-slate-100'
  return (
    <button
      onClick={onClick}
      className="flex min-w-[7.5rem] flex-shrink-0 flex-col items-start gap-0.5 rounded-xl border border-white/8 bg-white/[0.02] px-3.5 py-2.5 text-left transition-colors hover:border-white/20 hover:bg-white/[0.04] snap-start"
    >
      <span className="text-[11px] text-slate-500">{label}</span>
      <span className={`text-xl font-semibold leading-tight ${valueTone}`}>{value}</span>
      {sub && <span className="text-[11px] text-slate-500">{sub}</span>}
    </button>
  )
}
