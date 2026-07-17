/**
 * Standalone /overlay/:kind route — chrome-less, dark, compact.
 *
 * Rendered by the webapp for two audiences: the desktop Electron app, which
 * opens this in a frameless always-on-top BrowserWindow (Desktop Jarvis
 * Overhaul A2), and direct browser navigation for testing/debugging.
 *
 * Auth: the desktop passes its JWT through the one-time `/auth/token-cookie`
 * exchange, which sets the normal httpOnly session cookie and redirects here
 * with no token in the URL — this page relies purely on that cookie
 * (`credentials: 'include'` on every request, same as the rest of the app).
 */
import { useMemo } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { OVERLAY_ICONS, OVERLAY_TITLES, renderOverlayContent, type OverlayKind } from '../components/overlay/OverlayContent'

const KNOWN_KINDS: OverlayKind[] = [
  'brief', 'nutrition', 'calendar', 'tasks', 'note', 'blank-note', 'report', 'timers', 'inbox', 'recipes', 'patterns',
]

// Electron's frameless BrowserWindow has no OS titlebar/close button — this
// is the only way out of it besides the Escape-key handler in main.ts,
// which isn't discoverable. window.close() closes the BrowserWindow itself
// (no 'close' preventDefault is registered for overlay windows in main.ts).
declare global {
  interface Window {
    electronAPI?: { platform?: string }
  }
}
const isElectronOverlay = typeof window !== 'undefined' && !!window.electronAPI

export default function OverlayPage() {
  const { kind: rawKind } = useParams<{ kind: string }>()
  const [searchParams] = useSearchParams()

  const kind = (KNOWN_KINDS as string[]).includes(rawKind || '') ? (rawKind as OverlayKind) : null

  const payload = useMemo(() => {
    const encoded = searchParams.get('payload')
    if (encoded) {
      try {
        return JSON.parse(decodeURIComponent(encoded))
      } catch {
        // fall through to individual params
      }
    }
    const out: Record<string, any> = {}
    searchParams.forEach((value, key) => {
      if (key === 'payload') return
      if (value === 'true') out[key] = true
      else if (value === 'false') out[key] = false
      else out[key] = value
    })
    return out
  }, [searchParams])

  if (!kind) {
    return (
      <div className="min-h-screen bg-gray-950 text-gray-400 flex items-center justify-center text-sm">
        Unknown overlay: {rawKind}
      </div>
    )
  }

  return (
    <div className="h-screen w-screen bg-gray-950 text-gray-100 flex flex-col overflow-hidden select-none">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-800 shrink-0 [-webkit-app-region:drag]">
        <span>{OVERLAY_ICONS[kind]}</span>
        <h1 className="text-sm font-semibold text-gray-100 flex-1">{OVERLAY_TITLES[kind]}</h1>
        {isElectronOverlay && (
          <button
            onClick={() => window.close()}
            className="[-webkit-app-region:no-drag] w-6 h-6 rounded-full flex items-center justify-center text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
            title="Close (Esc)"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col [-webkit-app-region:no-drag]">
        {renderOverlayContent(kind, payload)}
      </div>
    </div>
  )
}
