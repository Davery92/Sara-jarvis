import React, { Suspense, lazy } from 'react'

const ContentInbox = lazy(() => import('../ContentInbox'))
const AttentionInbox = lazy(() => import('../AttentionInbox'))

interface InboxWorkspaceViewProps {
  inboxUnreadCount: number
  inboxTab: 'content' | 'attention'
  contentInboxStats: any
  attentionUnreadCount: number
  onSelectInboxTab: (tab: 'content' | 'attention') => void
  onOpenContentChat: (inboxItemId: string, title: string, excerpt?: string) => void
  onOpenAttentionChat: (prompt: string) => void
  onOpenNote?: (noteId: string) => void
}

export default function InboxWorkspaceView({
  inboxUnreadCount,
  inboxTab,
  contentInboxStats,
  attentionUnreadCount,
  onSelectInboxTab,
  onOpenContentChat,
  onOpenAttentionChat,
  onOpenNote,
}: InboxWorkspaceViewProps) {
  const contentUnreadCount = Number(contentInboxStats?.unread || 0)

  const stateBits: string[] = []
  if (attentionUnreadCount > 0) {
    stateBits.push(`${attentionUnreadCount} need${attentionUnreadCount === 1 ? 's' : ''} attention`)
  }
  if (contentUnreadCount > 0) {
    stateBits.push(`${contentUnreadCount} ${contentUnreadCount === 1 ? 'capture' : 'captures'}`)
  }

  const tabClass = (active: boolean) =>
    [
      'border-b-2 pb-1 text-sm transition-colors',
      active ? 'border-teal-300 text-white' : 'border-transparent text-slate-500 hover:text-slate-300',
    ].join(' ')

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* Slim header row: title + live state, quiet text tabs on the right */}
      <div className="flex flex-shrink-0 items-baseline justify-between gap-4 px-1 pb-4">
        <div className="flex min-w-0 items-baseline gap-3">
          <h2 className="font-display text-xl font-semibold text-white">Today</h2>
          {stateBits.length > 0 && (
            <span className="truncate text-xs text-slate-500">{stateBits.join(' · ')}</span>
          )}
        </div>
        <div className="flex flex-shrink-0 items-baseline gap-5">
          <button onClick={() => onSelectInboxTab('content')} className={tabClass(inboxTab === 'content')}>
            Captured
            {contentUnreadCount > 0 && <span className="ml-1.5 text-xs text-slate-500">{contentUnreadCount}</span>}
          </button>
          <button onClick={() => onSelectInboxTab('attention')} className={tabClass(inboxTab === 'attention')}>
            Attention
            {attentionUnreadCount > 0 && <span className="ml-1.5 text-xs text-slate-500">{attentionUnreadCount}</span>}
          </button>
        </div>
      </div>

      <div
        className={
          inboxTab === 'content'
            ? 'flex flex-1 min-h-0 flex-col px-1'
            : 'flex-1 min-h-0 overflow-y-auto px-1'
        }
      >
        <Suspense fallback={<p className="pt-6 text-sm text-slate-500">Loading…</p>}>
          {inboxTab === 'content' ? (
            <ContentInbox onNavigateToChat={onOpenContentChat} />
          ) : (
            <AttentionInbox onStartChat={onOpenAttentionChat} onOpenNote={onOpenNote} />
          )}
        </Suspense>
      </div>
    </div>
  )
}
