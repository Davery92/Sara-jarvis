import { useEffect, useState } from 'react'

interface NoteData {
  id: string
  title: string
  content: string
}

export default function NoteViewer() {
  const [note, setNote] = useState<NoteData | null>(null)

  useEffect(() => {
    // Parse note data from URL
    const params = new URLSearchParams(window.location.search)
    const data = params.get('data')
    if (data) {
      try {
        const parsed = JSON.parse(decodeURIComponent(data))
        setNote(parsed)
      } catch (e) {
        console.error('Failed to parse note data:', e)
      }
    }
  }, [])

  const handleClose = () => {
    window.electronAPI?.closeNote()
  }

  if (!note) {
    return (
      <div className="w-full h-screen bg-gray-900 rounded-2xl border border-gray-700 flex items-center justify-center">
        <div className="text-gray-500">Loading note...</div>
      </div>
    )
  }

  return (
    <div className="w-full h-screen bg-gray-900 rounded-2xl border border-gray-700 shadow-2xl flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700/50 bg-gray-800/50 cursor-move" style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center">
            <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <h1 className="text-lg font-semibold text-white truncate max-w-[350px]">{note.title}</h1>
        </div>
        <button
          onClick={handleClose}
          className="text-gray-400 hover:text-white transition-colors p-2 hover:bg-gray-700/50 rounded-lg"
          style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="prose prose-invert prose-sm max-w-none">
          <div className="text-gray-200 whitespace-pre-wrap leading-relaxed">
            {note.content}
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="px-5 py-3 border-t border-gray-700/50 bg-gray-800/30 flex items-center justify-between">
        <span className="text-xs text-gray-500">Note ID: {note.id.slice(0, 8)}...</span>
        <button
          onClick={handleClose}
          className="bg-gray-700 hover:bg-gray-600 text-white rounded-lg px-4 py-2 text-sm transition-colors"
        >
          Close
        </button>
      </div>
    </div>
  )
}
