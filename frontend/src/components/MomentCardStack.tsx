import { useEffect, useState } from 'react'
import { getJson, postJson } from './overlay/OverlayContent'

interface MomentCard {
  id: string
  kind: 'proof_of_memory' | 'artifact_unwrap'
  title: string
  body: string
  source_ref: string | null
  source_kind: string | null
  created_at: string
}

const KIND_ICON: Record<string, string> = {
  proof_of_memory: '💭',
  artifact_unwrap: '🎁',
}

/**
 * items 5.8/5.9 (2026-07-31) — rare, minted cards: a right-moment memory
 * callback, or "Sara made you something." Deliberately renders nothing when
 * there's nothing to show — these are meant to feel like a genuine surprise
 * on the rare occasions dreaming actually mints one, not a permanent widget
 * with an empty state to design around.
 */
export function MomentCardStack() {
  const [cards, setCards] = useState<MomentCard[]>([])
  const [unwrapped, setUnwrapped] = useState<Set<string>>(new Set())

  useEffect(() => {
    getJson('/api/moment-cards')
      .then((data) => setCards(Array.isArray(data) ? data : []))
      .catch(() => setCards([]))
  }, [])

  if (cards.length === 0) return null

  const unwrap = async (card: MomentCard) => {
    if (unwrapped.has(card.id)) return
    setUnwrapped((prev) => new Set(prev).add(card.id))
    try {
      await postJson(`/api/moment-cards/${card.id}/seen`, {})
    } catch {
      // best-effort — the card still reads as unwrapped locally this session
    }
  }

  const dismiss = async (card: MomentCard) => {
    setCards((prev) => prev.filter((c) => c.id !== card.id))
    try {
      await postJson(`/api/moment-cards/${card.id}/dismiss`, {})
    } catch {
      // no-op; worst case it reappears next load
    }
  }

  return (
    <div className="mb-8 space-y-3">
      {cards.map((card) => {
        const isUnwrapped = unwrapped.has(card.id)
        return (
          <div
            key={card.id}
            className="relative overflow-hidden rounded-2xl border border-teal-400/20 bg-gradient-to-br from-teal-500/10 via-cyan-500/5 to-indigo-500/10 p-4"
          >
            <div className="flex items-start gap-3">
              <span className="text-2xl leading-none">{KIND_ICON[card.kind] || '✨'}</span>
              <div className="min-w-0 flex-1">
                <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-teal-300/80">
                  {card.title}
                </div>
                {isUnwrapped ? (
                  <p className="mt-1.5 text-[15px] leading-relaxed text-slate-100">{card.body}</p>
                ) : (
                  <button
                    onClick={() => unwrap(card)}
                    className="mt-2 rounded-xl border border-teal-400/30 bg-teal-400/10 px-3 py-1.5 text-sm font-medium text-teal-200 transition-colors hover:bg-teal-400/20"
                  >
                    {card.kind === 'artifact_unwrap' ? 'Unwrap' : 'See what she means'}
                  </button>
                )}
              </div>
              {isUnwrapped && (
                <button
                  onClick={() => dismiss(card)}
                  className="shrink-0 text-slate-500 transition-colors hover:text-slate-300"
                  aria-label="Dismiss"
                >
                  ✕
                </button>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
