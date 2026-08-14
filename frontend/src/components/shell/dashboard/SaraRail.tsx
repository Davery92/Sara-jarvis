import React from 'react'

/**
 * Card C — Sara rail (mission-control redesign §4.4). Compresses the old
 * right rail into fixed sub-blocks: state, thought, watching-for, digest,
 * journal, open threads.
 */
export default function SaraRail({
  kernelState,
  activityState,
  emotionalState,
  interruptibility,
  latestThought,
  watchingFor,
  digest,
  briefLoaded,
  quietLine,
  formatRelativeTime,
  journalEntries,
  expandedJournalEntries,
  onToggleJournalEntry,
  emotionEmoji,
  threadTopics,
  onNavigate,
  onAskSara,
}: {
  kernelState: string | null
  activityState: string | null
  emotionalState: string | null
  interruptibility: number | null
  latestThought: string | null
  watchingFor: string[] | null
  digest: { items: { text: string; at: string; delivered?: boolean }[]; machinery: { tool_calls: number; errors: number } } | null
  briefLoaded: boolean
  quietLine: string | null
  formatRelativeTime: (ts: string) => string
  journalEntries: any[]
  expandedJournalEntries: Set<string>
  onToggleJournalEntry: (entryKey: string) => void
  emotionEmoji: Record<string, string>
  threadTopics: string[]
  onNavigate: (view: any) => void
  onAskSara?: (prompt: string) => void
}) {
  const humanize = (s: string | null) => (s ? s.replace(/_/g, ' ') : null)
  const stateChips = [humanize(kernelState), humanize(activityState), humanize(emotionalState)].filter(Boolean)

  const humanDigest = digest?.items || []
  const toolCount = digest?.machinery?.tool_calls || 0
  const errorCount = digest?.machinery?.errors || 0

  const latestEntry = journalEntries[0]
  const entryKey = latestEntry ? String(latestEntry.id || 0) : ''
  const fullContent = latestEntry
    ? latestEntry.content || latestEntry.details?.full_content || latestEntry.summary || latestEntry.text || ''
    : ''
  const isExpanded = expandedJournalEntries.has(entryKey)

  return (
    <div className="space-y-4 rounded-xl border border-white/8 bg-white/[0.02] p-4">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Sara</h2>

      {stateChips.length > 0 && (
        <div
          className="flex flex-wrap items-center gap-1.5"
          title={interruptibility != null ? `Interruptibility: ${Math.round(interruptibility * 100)}%` : undefined}
        >
          {stateChips.map((c, i) => (
            <span key={i} className="rounded-full border border-white/10 bg-white/[0.03] px-2 py-0.5 text-[11px] text-slate-300">
              {c}
            </span>
          ))}
        </div>
      )}

      {latestThought && (
        <p className="truncate text-sm italic text-slate-400" title={latestThought}>
          “{latestThought}”
        </p>
      )}

      {watchingFor && watchingFor.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {watchingFor.slice(0, 3).map((w, i) => (
            <span key={i} className="rounded-full border border-white/8 bg-white/[0.02] px-2 py-0.5 text-[11px] text-slate-500">
              👀 {w}
            </span>
          ))}
        </div>
      )}

      <div>
        <h3 className="mb-1.5 text-[11px] font-medium text-slate-500">While you were away</h3>
        {!briefLoaded ? (
          <p className="text-xs text-slate-500">Checking…</p>
        ) : humanDigest.length === 0 && toolCount === 0 && errorCount === 0 ? (
          <p className="text-xs text-slate-500">{quietLine || 'Quiet lately.'}</p>
        ) : (
          <div className="space-y-1.5">
            {humanDigest.slice(0, 3).map((a, i) => (
              <div key={`${a.at}-${i}`} className="flex items-baseline gap-2">
                <p className="min-w-0 flex-1 truncate text-xs text-slate-300">{a.text}</p>
                <span className="flex-shrink-0 text-[10px] tabular-nums text-slate-500">{formatRelativeTime(a.at)}</span>
              </div>
            ))}
            {(toolCount > 0 || errorCount > 0) && (
              <p className="text-[10px] text-slate-500">
                {toolCount > 0 && `${toolCount} tool ${toolCount === 1 ? 'call' : 'calls'}`}
                {toolCount > 0 && errorCount > 0 && ' · '}
                {errorCount > 0 && <span className="text-rose-400/80">{errorCount} {errorCount === 1 ? 'error' : 'errors'}</span>}
              </p>
            )}
          </div>
        )}
      </div>

      {latestEntry && (
        <div>
          <div className="mb-1 flex items-baseline justify-between">
            <h3 className="text-[11px] font-medium text-slate-500">Journal</h3>
            <button
              onClick={() => onNavigate('briefings')}
              className="text-[11px] text-slate-500 transition-colors hover:text-teal-300"
            >
              All entries →
            </button>
          </div>
          <p className="text-xs leading-relaxed text-slate-400 whitespace-pre-wrap break-words">
            {isExpanded || fullContent.length <= 140 ? fullContent : `${fullContent.slice(0, 140).trimEnd()}…`}
          </p>
          <div className="mt-1 flex items-center gap-2 text-[10px] text-slate-500">
            {latestEntry.emotional_state && (
              <span>{emotionEmoji[latestEntry.emotional_state] || ''} {latestEntry.emotional_state}</span>
            )}
            {fullContent.length > 140 && (
              <button onClick={() => onToggleJournalEntry(entryKey)} className="text-teal-400/80 hover:text-teal-300">
                {isExpanded ? 'Show less' : 'Read more'}
              </button>
            )}
          </div>
        </div>
      )}

      {threadTopics.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-[11px] font-medium text-slate-500">Open threads</h3>
          <div className="flex flex-wrap gap-1.5">
            {threadTopics.slice(0, 3).map((topic, i) => (
              <button
                key={i}
                onClick={() => onAskSara?.(`re: ${topic}`)}
                className="rounded-full border border-white/8 bg-white/[0.02] px-2 py-0.5 text-[11px] text-slate-400 transition-colors hover:border-teal-300/30 hover:text-teal-300"
              >
                re: {topic}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
