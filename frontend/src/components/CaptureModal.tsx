import { useEffect, useRef, useState } from 'react'
import { postJson } from './overlay/OverlayContent'

interface CaptureModalProps {
  isOpen: boolean
  onClose: () => void
}

const URL_RE = /^https?:\/\/\S+$/i

/**
 * item 5.2 (2026-07-31) — the web half of universal capture. iOS gets this
 * via the share sheet (targets/share/); the web hotkey (⌘⇧C / Ctrl⇧C) is the
 * same idea for whatever's already open in the browser: paste a link or type
 * a note, it lands in the same content inbox the share extension feeds.
 */
export function CaptureModal({ isOpen, onClose }: CaptureModalProps) {
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (isOpen) {
      setValue('')
      setResult(null)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isOpen, onClose])

  if (!isOpen) return null

  const submit = async () => {
    const text = value.trim()
    if (!text || saving) return
    setSaving(true)
    setResult(null)
    try {
      if (URL_RE.test(text)) {
        await postJson('/api/inbox/share', { url: text })
      } else {
        await postJson('/api/inbox/share/text', { text })
      }
      setResult({ ok: true, message: 'Saved to your inbox.' })
      setValue('')
      setTimeout(onClose, 900)
    } catch {
      setResult({ ok: false, message: "Couldn't save that — try again." })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-[15vh]"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-white/10 bg-slate-900 p-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
          Capture for Sara
        </div>
        <textarea
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault()
              submit()
            }
          }}
          placeholder="Paste a link, or type a quick note…"
          rows={3}
          className="w-full resize-none rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-teal-300/30"
        />
        <div className="mt-3 flex items-center justify-between">
          <span className="text-xs text-slate-500">
            {result ? (
              <span className={result.ok ? 'text-emerald-400' : 'text-red-400'}>{result.message}</span>
            ) : (
              '⌘/Ctrl + Enter to save · Esc to cancel'
            )}
          </span>
          <button
            onClick={submit}
            disabled={!value.trim() || saving}
            className="rounded-xl bg-teal-400/90 px-3.5 py-1.5 text-sm font-medium text-slate-950 transition-colors hover:bg-teal-300 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
