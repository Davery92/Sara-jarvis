import { useEffect, useState } from 'react'
import { FileText, MessageSquare, Dumbbell, Briefcase, Timer, Settings, ChevronUp, LayoutGrid, GitBranch, Search, Mail, GraduationCap, Radio, BookOpen } from 'lucide-react'
import { useCanvasStore } from '../store/canvasStore'
import { settingsApi } from '../services/api'
import type { WindowType } from '../types'

interface AppConfig {
  id: WindowType | 'maps'
  icon: typeof FileText
  label: string
  color: string
  opensPickerFirst?: boolean
}

const apps: AppConfig[] = [
  { id: 'chat', icon: MessageSquare, label: 'Chat', color: 'bg-teal-500' },
  { id: 'email', icon: Mail, label: 'Email', color: 'bg-cyan-500' },
  { id: 'research', icon: Search, label: 'Research', color: 'bg-purple-500' },
  { id: 'learning', icon: GraduationCap, label: 'Learning', color: 'bg-indigo-500' },
  { id: 'temerant', icon: BookOpen, label: 'Temerant', color: 'bg-rose-600' },
  { id: 'documents', icon: FileText, label: 'Docs', color: 'bg-blue-600' },
  { id: 'note', icon: FileText, label: 'Notes', color: 'bg-blue-500' },
  { id: 'maps', icon: GitBranch, label: 'Maps', color: 'bg-teal-600', opensPickerFirst: true },
  { id: 'fitness', icon: Dumbbell, label: 'Fitness', color: 'bg-green-500' },
  { id: 'projects', icon: Briefcase, label: 'Projects', color: 'bg-indigo-500' },
  { id: 'intelligence', icon: Radio, label: 'Intel', color: 'bg-emerald-600' },
  { id: 'timers', icon: Timer, label: 'Timers', color: 'bg-orange-500' },
  { id: 'settings', icon: Settings, label: 'Settings', color: 'bg-gray-500' },
]

export default function ModeWheel() {
  const { openWindow, setMapPickerOpen } = useCanvasStore()
  const [isExpanded, setIsExpanded] = useState(false)
  const [temerantEnabled, setTemerantEnabled] = useState(true)

  useEffect(() => {
    settingsApi
      .getAutonomyFlags()
      .then((flags) => {
        if (typeof flags.temerant_enabled === 'boolean') {
          setTemerantEnabled(flags.temerant_enabled)
        }
      })
      .catch(() => {
        // Keep default behavior if flags are unavailable.
      })
  }, [])

  const handleAppClick = (app: AppConfig) => {
    // Special case for maps - open the picker
    if (app.id === 'maps') {
      setMapPickerOpen(true)
      setIsExpanded(false)
      return
    }

    // Open a new window for the app
    openWindow(app.id as WindowType, {})
    setIsExpanded(false)
  }

  const handleMainButtonClick = () => {
    setIsExpanded(!isExpanded)
  }

  const visibleApps = temerantEnabled ? apps : apps.filter((app) => app.id !== 'temerant')

  return (
    <div className="fixed bottom-8 right-8 z-50">
      {/* Expanded app buttons - 2 columns */}
      <div
        className={`grid grid-cols-2 gap-3 mb-3 transition-all duration-200 ${
          isExpanded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4 pointer-events-none'
        }`}
      >
        {visibleApps.map((app) => {
          const Icon = app.icon

          return (
            <button
              key={app.id}
              onClick={() => handleAppClick(app)}
              className={`w-14 h-14 rounded-xl flex flex-col items-center justify-center gap-0.5 transition-all
                         shadow-lg hover:scale-110 active:scale-95 touch-target
                         bg-canvas-elevated hover:bg-canvas-surface`}
              title={app.label}
            >
              <Icon size={20} className="text-white" />
              <span className="text-[10px] text-white/80">{app.label}</span>
            </button>
          )
        })}
      </div>

      {/* Main button */}
      <button
        onClick={handleMainButtonClick}
        className={`w-16 h-16 rounded-full flex items-center justify-center transition-all
                   shadow-xl hover:scale-105 active:scale-95 touch-target
                   bg-gradient-to-br from-blue-500 to-purple-600 ring-2 ring-white/20`}
        title={isExpanded ? 'Close' : 'Open Apps'}
      >
        {isExpanded ? (
          <ChevronUp size={28} className="text-white" />
        ) : (
          <LayoutGrid size={28} className="text-white" />
        )}
      </button>

      {/* Label */}
      <div className="absolute -left-16 top-1/2 -translate-y-1/2 text-canvas-muted text-sm whitespace-nowrap">
        {isExpanded ? 'Apps' : ''}
      </div>
    </div>
  )
}
