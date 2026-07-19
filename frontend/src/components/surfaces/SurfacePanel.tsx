/**
 * SurfacePanel — floating overlay hosting the active interactive surface.
 *
 * Lives above the chat (bottom-right) so it doesn't fight the canvas/chat
 * layout. Opened by a surface_command SSE event; the user can close it any time
 * (the UI never needs Sara's permission to close — B4).
 */
import React from 'react'
import { X } from 'lucide-react'
import { SurfaceModel } from './types'
import { useSurface } from './useSurface'
import { SurfaceRenderer } from './SurfaceRenderer'

interface Props {
  surface: SurfaceModel | null
  onClose: () => void
}

export const SurfacePanel: React.FC<Props> = ({ surface, onClose }) => {
  const { surface: live, postEvent } = useSurface(surface)

  if (!live) return null

  return (
    <div className="fixed bottom-4 right-4 z-40 w-[380px] max-w-[calc(100vw-2rem)] max-h-[75vh] flex flex-col rounded-lg border border-gray-700 bg-gray-900 shadow-2xl">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
        <div className="flex items-center gap-2 min-w-0">
          <span className="material-icons text-teal-400 text-lg">widgets</span>
          <h3 className="text-white font-medium text-sm truncate">{live.title}</h3>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded hover:bg-gray-800 text-gray-400 hover:text-white"
          title="Close"
        >
          <X size={16} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <SurfaceRenderer surface={live} onEvent={postEvent} />
      </div>
    </div>
  )
}

export default SurfacePanel
