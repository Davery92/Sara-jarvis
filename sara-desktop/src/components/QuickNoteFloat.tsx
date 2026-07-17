import { useCallback, useRef, useState } from 'react'

/**
 * Quick-jot note — native, not a webapp overlay (Desktop Jarvis Overhaul A4).
 * Opens instantly with no web load. One textarea: the first line becomes the
 * note title, everything after becomes the content. Saves straight to
 * /notes via the main process (offline-safe — a failed save is queued and
 * retried automatically, this window doesn't need to know or wait).
 */
export default function QuickNoteFloat() {
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleClose = useCallback(() => {
    window.electronAPI?.closeQuickNote()
  }, [])

  const handleSave = useCallback(async () => {
    const trimmed = text.trim()
    if (!trimmed || saving) {
      handleClose()
      return
    }
    setSaving(true)
    const lines = trimmed.split('\n')
    const title = lines[0].trim()
    const content = lines.slice(1).join('\n').trim()
    await window.electronAPI?.saveQuickNote(title, content)
    handleClose()
  }, [text, saving, handleClose])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      void handleSave()
    }
    if (e.key === 'Escape') {
      void handleSave()
    }
  }

  return (
    <div className="no-drag w-full h-screen bg-gray-900 rounded-2xl border border-gray-700 shadow-2xl flex flex-col overflow-hidden">
      <div
        className="flex items-center justify-between px-4 py-2 border-b border-gray-700/50 bg-gray-800/50 cursor-move"
        style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
      >
        <span className="text-sm font-medium text-gray-300">Quick note</span>
        <button
          onClick={() => void handleSave()}
          className="text-gray-400 hover:text-white transition-colors p-1"
          style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
      <textarea
        ref={textareaRef}
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Title on the first line, then your note…"
        className="flex-1 bg-transparent text-gray-100 text-sm p-4 outline-none resize-none leading-relaxed placeholder-gray-600"
        disabled={saving}
      />
      <div className="px-4 py-2 border-t border-gray-700/50 bg-gray-800/30 text-xs text-gray-500 flex justify-between">
        <span>{saving ? 'Saving…' : 'Cmd/Ctrl+Enter to save'}</span>
        <span>Esc to save & close</span>
      </div>
    </div>
  )
}
