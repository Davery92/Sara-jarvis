import type { WindowType, WindowData, NoteWindowData, ChatWindowData, FitnessWindowData, ProjectsWindowData, TimersWindowData, SettingsWindowData, FileViewerWindowData, ModelViewerWindowData, ResearchWindowData, ReportWindowData, EmailWindowData, AutomationWindowData, PKGWindowData } from '../types'
import NoteContent from './windows/NoteContent'
import ChatContent from './windows/ChatContent'
import FitnessContent from './windows/FitnessContent'
import ProjectsContent from './windows/ProjectsContent'
import TimersContent from './windows/TimersContent'
import SettingsContent from './windows/SettingsContent'
import FileViewerContent from './windows/FileViewerContent'
import ModelViewerContent from './windows/ModelViewerContent'
import ResearchContent from './windows/ResearchContent'
import ReportContent from './windows/ReportContent'
import EmailContent from './windows/EmailContent'
import AutomationContent from './windows/AutomationContent'
import PKGContent from './windows/PKGContent'

interface WindowContentProps {
  type: WindowType
  data: WindowData
  windowId: string
}

export function WindowContent({ type, data, windowId }: WindowContentProps) {
  switch (type) {
    case 'note':
      return <NoteContent data={data as NoteWindowData} windowId={windowId} />
    case 'chat':
      return <ChatContent data={data as ChatWindowData} windowId={windowId} />
    case 'fitness':
      return <FitnessContent data={data as FitnessWindowData} windowId={windowId} />
    case 'projects':
      return <ProjectsContent data={data as ProjectsWindowData} windowId={windowId} />
    case 'timers':
      return <TimersContent data={data as TimersWindowData} windowId={windowId} />
    case 'settings':
      return <SettingsContent data={data as SettingsWindowData} windowId={windowId} />
    case 'fileviewer':
      return <FileViewerContent data={data as FileViewerWindowData} windowId={windowId} />
    case 'modelviewer':
      return <ModelViewerContent data={data as ModelViewerWindowData} windowId={windowId} />
    case 'research':
      return <ResearchContent data={data as ResearchWindowData} windowId={windowId} />
    case 'report':
      return <ReportContent data={data as ReportWindowData} windowId={windowId} />
    case 'email':
      return <EmailContent data={data as EmailWindowData} windowId={windowId} />
    case 'automation':
      return <AutomationContent data={data as AutomationWindowData} />
    case 'pkg':
      return <PKGContent data={data as PKGWindowData} windowId={windowId} />
    default:
      return (
        <div className="flex items-center justify-center h-full text-canvas-muted">
          Unknown window type
        </div>
      )
  }
}
