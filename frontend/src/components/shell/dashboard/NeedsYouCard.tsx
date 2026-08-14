import React from 'react'

interface VerificationData {
  pkg_id: string
  fact?: string
}

/**
 * Card A — Needs you (mission-control redesign §4.2). Largest visual weight
 * on the page when non-empty; the one thing the page exists to tell you.
 */
export default function NeedsYouCard({
  items,
  missionAwaitingCount,
  verificationQuestion,
  verificationData,
  formatRelativeTime,
  onOpenItem,
  onOpenMissions,
  onVerificationAnswer,
}: {
  items: any[]
  missionAwaitingCount: number
  verificationQuestion: string | null
  verificationData: VerificationData | null
  formatRelativeTime: (ts: string) => string
  onOpenItem: () => void
  onOpenMissions: () => void
  onVerificationAnswer: (pkgId: string, confirmed: boolean) => void
}) {
  const [answered, setAnswered] = React.useState(false)
  const rows = items.slice(0, 5)
  const isEmpty = rows.length === 0 && missionAwaitingCount === 0

  const answer = (confirmed: boolean) => {
    if (!verificationData) return
    setAnswered(true)
    onVerificationAnswer(verificationData.pkg_id, confirmed)
  }

  if (isEmpty && !verificationQuestion) {
    return (
      <div className="rounded-xl border border-white/8 bg-white/[0.02] p-4">
        <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Needs you</h2>
        <p className="text-sm text-slate-500">Nothing needs you.</p>
      </div>
    )
  }

  return (
    <div className={`rounded-xl border p-4 ${isEmpty ? 'border-white/8 bg-white/[0.02]' : 'border-amber-400/20 bg-amber-400/[0.03]'}`}>
      <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Needs you</h2>
      <div className="space-y-2">
        {rows.map((item) => (
          <button
            key={item.id}
            onClick={onOpenItem}
            className="group flex w-full items-baseline gap-3 rounded-lg border border-amber-400/20 bg-amber-400/[0.04] px-3 py-2.5 text-left transition-colors hover:border-amber-300/40 hover:bg-amber-400/[0.07]"
          >
            <span className="min-w-0 flex-1 truncate text-[15px] font-medium text-slate-100 group-hover:text-white">
              {item.title || 'Needs your input'}
            </span>
            {item.category && (
              <span className="flex-shrink-0 rounded-full border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
                {item.category}
              </span>
            )}
            <span className="flex-shrink-0 text-xs text-slate-500">
              {item.created_at ? formatRelativeTime(item.created_at) : ''}
            </span>
            <span className="flex-shrink-0 text-xs text-amber-300/0 group-hover:text-amber-300/80">Open →</span>
          </button>
        ))}
        {missionAwaitingCount > 0 && (
          <button
            onClick={onOpenMissions}
            className="group flex w-full items-baseline gap-3 rounded-lg border border-amber-400/20 bg-amber-400/[0.04] px-3 py-2.5 text-left transition-colors hover:border-amber-300/40 hover:bg-amber-400/[0.07]"
          >
            <span className="text-[15px] font-medium text-slate-100 group-hover:text-white">
              {missionAwaitingCount} {missionAwaitingCount === 1 ? 'mission is' : 'missions are'} waiting on a decision
            </span>
          </button>
        )}
        {verificationQuestion && verificationData && (
          <div className="flex items-center gap-3 rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2.5">
            <span className="min-w-0 flex-1 text-sm text-slate-300">{verificationQuestion}</span>
            {answered ? (
              <span className="flex-shrink-0 text-xs text-slate-500">Thanks</span>
            ) : (
              <div className="flex flex-shrink-0 items-center gap-1.5">
                <button
                  onClick={() => answer(true)}
                  className="rounded-full border border-teal-400/25 bg-teal-400/[0.06] px-2.5 py-0.5 text-xs text-teal-200 hover:border-teal-300/40"
                >
                  Yes
                </button>
                <button
                  onClick={() => answer(false)}
                  className="rounded-full border border-white/10 px-2.5 py-0.5 text-xs text-slate-400 hover:border-white/20"
                >
                  No
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
