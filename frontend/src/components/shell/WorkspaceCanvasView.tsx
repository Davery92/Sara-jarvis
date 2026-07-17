import React from 'react'

interface WorkspaceCanvasViewProps {
  workbenchUrl: string
  onOpenCanvas: () => void
  onBackToChat: () => void
}

const WorkspaceCanvasView: React.FC<WorkspaceCanvasViewProps> = ({
  workbenchUrl,
  onOpenCanvas,
  onBackToChat,
}) => {
  return (
    <div className="flex-1 overflow-y-auto min-h-0">
      <div className="max-w-3xl mx-auto bg-card border border-card rounded-md p-8 space-y-4">
        <div className="flex items-center gap-3">
          <span className="material-icons text-cyan-400 text-3xl">dashboard_customize</span>
          <h2 className="text-2xl font-semibold text-white">Canvas Workspace</h2>
        </div>
        <p className="text-gray-300">
          The full workbench canvas runs as a dedicated app so you can manage multiple windows and maps in one space.
        </p>
        <div className="bg-gray-900/60 border border-gray-700 rounded-lg p-4">
          <p className="text-xs uppercase tracking-wider text-gray-500 mb-1">Workspace URL</p>
          <p className="text-sm text-cyan-300 break-all">{workbenchUrl}</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={onOpenCanvas}
            className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-700 text-white font-medium"
          >
            Open Canvas
          </button>
          <button
            onClick={onBackToChat}
            className="px-4 py-2 rounded-lg border border-gray-600 text-gray-300 hover:text-white hover:border-gray-500"
          >
            Back to Chat
          </button>
        </div>
      </div>
    </div>
  )
}

export default WorkspaceCanvasView
