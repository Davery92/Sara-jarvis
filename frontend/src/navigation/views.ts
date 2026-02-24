export type AppView =
  | 'login'
  | 'dashboard'
  | 'chat'
  | 'notes'
  | 'habits'
  | 'documents'
  | 'calendar'
  | 'email'
  | 'fitness'
  | 'learn'
  | 'projects'
  | 'recipes'
  | 'temerant'
  | 'temerant-rpg'
  | 'briefings'
  | 'sensory-monitor'
  | 'saras-mind'
  | 'inbox'
  | 'workspace'
  | 'settings'
  | 'knowledge'
  | 'intelligence'
  | 'privacy-dashboard'
  | 'orchestrator-lab'

interface AppViewConfig {
  view: AppView
  path: string
  title: string
  icon?: string
  keywords: string[]
  includeInPalette?: boolean
}

export const APP_VIEWS: AppViewConfig[] = [
  { view: 'login', path: '/login', title: 'Login', keywords: ['auth', 'signin'], includeInPalette: false },
  { view: 'dashboard', path: '/', title: 'Home', icon: '🏠', keywords: ['home', 'dashboard'] },
  { view: 'chat', path: '/chat', title: 'Chat', icon: '💬', keywords: ['chat', 'talk', 'conversation'] },
  { view: 'notes', path: '/notes', title: 'Notes', icon: '📝', keywords: ['notes', 'knowledge', 'write'] },
  { view: 'habits', path: '/habits', title: 'Habits', icon: '🎯', keywords: ['habits', 'tracking', 'goals'] },
  { view: 'documents', path: '/documents', title: 'Documents', icon: '📄', keywords: ['documents', 'files', 'uploads'] },
  { view: 'calendar', path: '/calendar', title: 'Calendar', icon: '📅', keywords: ['calendar', 'events', 'schedule'] },
  { view: 'email', path: '/email', title: 'Email', icon: '📧', keywords: ['email', 'mail', 'inbox', 'messages'] },
  { view: 'fitness', path: '/fitness', title: 'Fitness', icon: '💪', keywords: ['fitness', 'health', 'workout'] },
  { view: 'learn', path: '/learn', title: 'Learn', icon: '🎓', keywords: ['learn', 'study', 'education'] },
  { view: 'projects', path: '/projects', title: 'Projects', icon: '📁', keywords: ['projects', 'work', 'planning'] },
  { view: 'recipes', path: '/recipes', title: 'Recipes', icon: '👨‍🍳', keywords: ['recipes', 'cooking', 'food'] },
  { view: 'temerant', path: '/temerant', title: 'Temerant', icon: '🗝️', keywords: ['temerant', 'rpg', 'oracle', 'university', 'habit'] },
  { view: 'temerant-rpg', path: '/temerant-rpg', title: 'Temerant RPG', icon: '🎭', keywords: ['temerant', 'rpg', 'scene', 'daveth', 'university'] },
  { view: 'briefings', path: '/briefings', title: 'Morning Brief', icon: '🌅', keywords: ['brief', 'briefings', 'morning'] },
  { view: 'sensory-monitor', path: '/sensory-monitor', title: 'Sensory', icon: '📡', keywords: ['sensory', 'monitor'] },
  { view: 'saras-mind', path: '/saras-mind', title: "Sara's Mind", icon: '🧠', keywords: ['mind', 'thoughts', 'deliberation', 'inner', 'autonomy', 'observations'] },
  { view: 'inbox', path: '/inbox', title: 'Inbox', icon: '📥', keywords: ['inbox', 'content'] },
  { view: 'knowledge', path: '/knowledge', title: 'Knowledge', icon: '🧬', keywords: ['knowledge', 'pkg', 'personal', 'facts', 'preferences', 'people'] },
  { view: 'intelligence', path: '/intelligence', title: 'Intelligence', icon: '📡', keywords: ['intelligence', 'news', 'tech', 'ai', 'research', 'feed'] },
  { view: 'workspace', path: '/workspace', title: 'Canvas', icon: '🧩', keywords: ['canvas', 'workspace', 'workbench'] },
  { view: 'settings', path: '/settings', title: 'Settings', icon: '⚙️', keywords: ['settings', 'preferences', 'config'] },
  { view: 'privacy-dashboard', path: '/privacy-dashboard', title: 'Privacy', icon: '🔒', keywords: ['privacy', 'security'], includeInPalette: false },
  { view: 'orchestrator-lab', path: '/orchestrator-lab', title: 'Orchestrator Lab', icon: '🧠', keywords: ['orchestrator', 'automation', 'lab'] },
]

const VIEW_ALIASES: Record<string, AppView> = {
  orchestrator: 'orchestrator-lab',
}

export const PATH_TO_VIEW: Record<string, AppView> = APP_VIEWS.reduce((acc, item) => {
  acc[item.path] = item.view
  return acc
}, {} as Record<string, AppView>)

export const VIEW_TO_PATH: Record<AppView, string> = APP_VIEWS.reduce((acc, item) => {
  acc[item.view] = item.path
  return acc
}, {} as Record<AppView, string>)

export const resolveViewAlias = (view: string): AppView | null => {
  if ((VIEW_TO_PATH as Record<string, string>)[view]) return view as AppView
  return VIEW_ALIASES[view] || null
}

export const viewForPath = (pathname: string): AppView =>
  PATH_TO_VIEW[pathname] || 'dashboard'

export const pathForView = (view: string): string => {
  const resolved = resolveViewAlias(view)
  return resolved ? VIEW_TO_PATH[resolved] : '/'
}

export const PALETTE_NAV_VIEWS = APP_VIEWS.filter(
  (item) => item.includeInPalette !== false
)
