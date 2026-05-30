import React from 'react'
import AutomationTasksIndicator from '../AutomationTasksIndicator'
import BackgroundTasksIndicator from '../BackgroundTasksIndicator'

interface ShellHeaderProps {
  assistantName: string
  userEmail?: string
  onOpenAutomations: () => void
  onNavigateToWorkspace: (noteId: string) => Promise<void>
}

const ShellHeader: React.FC<ShellHeaderProps> = ({
  assistantName,
  userEmail,
  onOpenAutomations,
  onNavigateToWorkspace,
}) => {
  return (
    <header className="hidden md:flex items-center justify-end gap-3 mb-3 flex-shrink-0">
      <AutomationTasksIndicator onOpenAutomations={onOpenAutomations} />
      <BackgroundTasksIndicator onNavigateToWorkspace={onNavigateToWorkspace} />
      <div className="h-5 w-px bg-white/8" />
      <span className="text-xs text-slate-400">{userEmail || 'Signed in'}</span>
      <span className="rounded-full border border-white/8 bg-white/[0.03] px-2.5 py-1 text-[11px] text-slate-500">
        ⌘K
      </span>
    </header>
  )
}

export default ShellHeader
