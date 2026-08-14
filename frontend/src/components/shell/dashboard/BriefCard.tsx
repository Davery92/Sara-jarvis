import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const MAX_CHARS = 280

function collapseBriefText(text: string): string {
  const bulletLines = text.split('\n').filter((line) => /^\s*[-*]\s+/.test(line))
  if (bulletLines.length > 0) {
    return bulletLines.slice(0, 3).join('\n')
  }
  if (text.length <= MAX_CHARS) return text
  const cut = text.slice(0, MAX_CHARS)
  const lastSentenceEnd = Math.max(
    cut.lastIndexOf('. '),
    cut.lastIndexOf('! '),
    cut.lastIndexOf('? '),
    cut.lastIndexOf('.\n'),
  )
  if (lastSentenceEnd > 0) return cut.slice(0, lastSentenceEnd + 1)
  return `${cut.slice(0, Math.max(cut.lastIndexOf('\n'), cut.lastIndexOf(' ')))}…`
}

/**
 * Card D — Brief (mission-control redesign §4.5). Capped to ~3 bullets or
 * ~280 chars; the audio element and suggested-action chips live here.
 */
export default function BriefCard({
  morningBrief,
  morningBriefLoading,
  briefAudioPlaying,
  briefAudioRef,
  onPlayBriefAudio,
  onBriefAudioEnded,
  onBriefAudioPaused,
  onBriefAudioError,
  timePeriod,
  suggestedActions,
  onNavigate,
  onAskSara,
}: {
  morningBrief: any
  morningBriefLoading: boolean
  briefAudioPlaying: boolean
  briefAudioRef: React.RefObject<HTMLAudioElement>
  onPlayBriefAudio: () => void
  onBriefAudioEnded: () => void
  onBriefAudioPaused: () => void
  onBriefAudioError: () => void
  timePeriod: string | null
  suggestedActions: { label: string; message: string; icon?: string }[]
  onNavigate: (view: any) => void
  onAskSara?: (prompt: string) => void
}) {
  const label = timePeriod === 'evening' || timePeriod === 'night' ? 'Evening brief' : 'Morning brief'

  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.02] p-4">
      {morningBrief && (
        <audio
          ref={briefAudioRef}
          onEnded={onBriefAudioEnded}
          onPause={onBriefAudioPaused}
          onError={onBriefAudioError}
          style={{ display: 'none' }}
        />
      )}
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</h2>
        <div className="flex flex-shrink-0 items-center gap-3">
          {morningBrief && (
            <button onClick={onPlayBriefAudio} className="text-xs text-slate-500 transition-colors hover:text-teal-300">
              {briefAudioPlaying ? '⏸ Pause' : '▸ Listen'}
            </button>
          )}
          <button onClick={() => onNavigate('briefings')} className="text-xs text-slate-500 transition-colors hover:text-teal-300">
            Open full brief →
          </button>
        </div>
      </div>
      {morningBriefLoading ? (
        <p className="text-sm text-slate-500">Loading brief…</p>
      ) : morningBrief ? (
        <div
          className="prose prose-invert max-w-none text-sm leading-relaxed text-slate-300
            prose-headings:mb-1 prose-headings:mt-2 prose-headings:text-[13px] prose-headings:font-semibold prose-headings:uppercase prose-headings:tracking-wide prose-headings:text-slate-400
            prose-p:my-1 prose-ul:my-1 prose-li:my-0.5 prose-strong:font-medium prose-strong:text-slate-100"
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {collapseBriefText(morningBrief.full_text || morningBrief.summary || '')}
          </ReactMarkdown>
        </div>
      ) : (
        <p className="text-sm text-slate-500">No brief available yet today.</p>
      )}
      {suggestedActions.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {suggestedActions.map((a, i) => (
            <button
              key={i}
              onClick={() => onAskSara?.(a.message)}
              className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[11px] text-slate-300 transition-colors hover:border-teal-300/30 hover:text-teal-200"
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
