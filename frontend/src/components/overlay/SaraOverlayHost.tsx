/**
 * SaraOverlayHost — Jarvis-style overlays summoned from chat.
 *
 * Listens for `sara:ui-command` window events (dispatched by ChatInterface
 * when the backend emits a `ui_command` SSE event for phrases like
 * "bring up my morning brief") and renders the requested surface as an
 * overlay on top of whatever view is active.
 */
import { useCallback, useEffect, useState } from 'react'
import { OVERLAY_ICONS, OVERLAY_TITLES, renderOverlayContent, type OverlayKind } from './OverlayContent'

interface UICommand {
  action: string
  overlay: OverlayKind
  payload: Record<string, any>
}

export default function SaraOverlayHost() {
  const [command, setCommand] = useState<UICommand | null>(null)

  useEffect(() => {
    const onCommand = (e: Event) => {
      const detail = (e as CustomEvent).detail as UICommand
      if (detail?.action === 'open_overlay' && detail.overlay) {
        setCommand(detail)
      }
    }
    window.addEventListener('sara:ui-command', onCommand)
    return () => window.removeEventListener('sara:ui-command', onCommand)
  }, [])

  const close = useCallback(() => setCommand(null), [])

  useEffect(() => {
    if (!command) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [command, close])

  if (!command) return null
  const kind = command.overlay

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={close}
    >
      <div
        className="w-full max-w-2xl max-h-[80vh] mx-4 bg-gray-900 border border-gray-700 rounded-xl shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700">
          <h2 className="text-gray-100 font-semibold flex items-center gap-2">
            <span>{OVERLAY_ICONS[kind]}</span>
            {kind === 'note' ? command.payload?.title || 'Note' : OVERLAY_TITLES[kind]}
          </h2>
          <button
            onClick={close}
            className="text-gray-400 hover:text-gray-200 text-xl leading-none px-1"
            aria-label="Close overlay"
          >
            ×
          </button>
        </div>
        <div className="px-5 py-4 overflow-y-auto flex-1 flex flex-col">
          {renderOverlayContent(kind, command.payload || {})}
        </div>
      </div>
    </div>
  )
}
