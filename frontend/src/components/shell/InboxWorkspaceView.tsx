import React, { Suspense, lazy } from 'react'

const AttentionInbox = lazy(() => import('../AttentionInbox'))

interface InboxWorkspaceViewProps {
  attentionUnreadCount: number
  onOpenAttentionChat: (prompt: string) => void
  onOpenNote?: (noteId: string) => void
}

export default function InboxWorkspaceView({
  attentionUnreadCount,
  onOpenAttentionChat,
  onOpenNote,
}: InboxWorkspaceViewProps) {
  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* Slim header row: title + live state. Content-inbox tab deleted
          (work-order item 2, 2026-07-30) — the capture table/endpoint stay
          dormant, write-frozen, for felt-layer #2 to rebuild capture on
          top of later; see SARA_ALIVE_BUILD_PLAN's kill-list row. */}
      <div className="flex flex-shrink-0 items-baseline justify-between gap-4 px-1 pb-4">
        <div className="flex min-w-0 items-baseline gap-3">
          <h2 className="font-display text-xl font-semibold text-white">Today</h2>
          {attentionUnreadCount > 0 && (
            <span className="truncate text-xs text-slate-500">
              {attentionUnreadCount} need{attentionUnreadCount === 1 ? 's' : ''} attention
            </span>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-1">
        <Suspense fallback={<p className="pt-6 text-sm text-slate-500">Loading…</p>}>
          <AttentionInbox onStartChat={onOpenAttentionChat} onOpenNote={onOpenNote} />
        </Suspense>
      </div>
    </div>
  )
}
