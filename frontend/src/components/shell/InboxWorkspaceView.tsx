import React, { Suspense, lazy } from 'react'

const ContentInbox = lazy(() => import('../ContentInbox'))
const AttentionInbox = lazy(() => import('../AttentionInbox'))

interface InboxWorkspaceViewProps {
  inboxUnreadCount: number
  inboxTab: 'content' | 'attention'
  contentInboxStats: any
  attentionUnreadCount: number
  onSelectInboxTab: (tab: 'content' | 'attention') => void
  onOpenContentChat: (inboxItemId: string, title: string) => void
  onOpenAttentionChat: (prompt: string) => void
  onOpenNote?: (noteId: string) => void
}

function ViewLoadingState({ label }: { label: string }) {
  return (
    <div className="flex-1 min-h-0 flex items-center justify-center">
      <div className="rounded-md border border-card bg-card px-4 py-3 text-sm text-gray-400">
        {label}
      </div>
    </div>
  )
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

  return (
    <div className="flex-1 min-h-0 flex flex-col gap-4">
      <div className="assistant-panel flex-shrink-0 rounded-md px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-display text-base font-semibold text-white">Inbox</h2>
          <span className="text-xs text-slate-400">
            {inboxUnreadCount > 0
              ? `${inboxUnreadCount} waiting`
              : 'Quiet'}
          </span>
        </div>

        <div className="mt-2 rounded-md border border-white/8 bg-slate-950/35 p-1">
          <div className="flex gap-1">
            <button
              onClick={() => onSelectInboxTab('content')}
              className={[
                'flex-1 rounded-md px-3 py-1.5 text-sm transition',
                inboxTab === 'content'
                  ? 'bg-teal-400/12 text-white shadow-[0_4px_12px_rgba(13,148,136,0.15)]'
                  : 'text-slate-400 hover:bg-white/[0.04] hover:text-white',
              ].join(' ')}
            >
              Captured
              {contentUnreadCount > 0 ? <span className="ml-1.5 text-xs text-slate-500">· {contentUnreadCount}</span> : null}
            </button>
            <button
              onClick={() => onSelectInboxTab('attention')}
              className={[
                'flex-1 rounded-md px-3 py-1.5 text-sm transition',
                inboxTab === 'attention'
                  ? 'bg-teal-400/12 text-white shadow-[0_4px_12px_rgba(13,148,136,0.15)]'
                  : 'text-slate-400 hover:bg-white/[0.04] hover:text-white',
              ].join(' ')}
            >
              Attention
              {attentionUnreadCount > 0 ? <span className="ml-1.5 text-xs text-slate-500">· {attentionUnreadCount}</span> : null}
            </button>
          </div>
        </div>
      </div>

      <div className="assistant-panel-soft flex flex-col flex-1 min-h-0 overflow-hidden rounded-md p-2">
        <div className="border-b border-white/8 px-4 pb-3 pt-2">
          <p className="text-sm font-medium text-white">
            {inboxTab === 'content' ? 'Captured content queue' : 'Assistant follow-up queue'}
          </p>
          <p className="mt-1 text-sm text-slate-500">
            {inboxTab === 'content'
              ? 'Open reports, notes, and saved material, then move directly into chat when needed.'
              : 'Handle clarifications and mission handoffs before they turn into background noise.'}
          </p>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-2 pt-3">
        <Suspense
          fallback={
            <ViewLoadingState
              label={inboxTab === 'content' ? 'Loading content inbox…' : 'Loading attention inbox…'}
            />
          }
        >
          {inboxTab === 'content' ? (
            <ContentInbox onNavigateToChat={onOpenContentChat} />
          ) : (
            <AttentionInbox onStartChat={onOpenAttentionChat} onOpenNote={onOpenNote} />
          )}
        </Suspense>
        </div>
      </div>
    </div>
  )
}
