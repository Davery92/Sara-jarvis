export type AppView =
  | 'login'
  | 'dashboard'
  | 'chat'
  | 'notes'
  | 'documents'
  | 'artifacts'
  | 'calendar'
  | 'email'
  | 'fitness'
  | 'learn'
  | 'projects'
  | 'recipes'
  | 'briefings'
  | 'sensory-monitor'
  | 'inbox'
  | 'workspace'
  | 'tasks'
  | 'settings'
  | 'knowledge'
  | 'privacy-dashboard'
  | 'automations'
  | 'orchestrator-lab'
  | 'acs'
  // NOTE: 'system-status' and 'mind' removed 2026-07-31 (item 2.3 ruling 4)
  // — embedded into Interior's "Legacy dashboards" section instead of a
  // standalone view.
  | 'system'
  | 'machines'
  | 'interior'
  | 'life'
  | 'work'
  | 'memory'
  | 'dial'

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
  { view: 'dashboard', path: '/', title: 'Home', icon: 'home', keywords: ['home', 'dashboard'] },
  { view: 'chat', path: '/chat', title: 'Chat', icon: 'chat', keywords: ['chat', 'talk', 'conversation'] },
  { view: 'notes', path: '/notes', title: 'Notes', icon: 'edit_note', keywords: ['notes', 'knowledge', 'write'] },
  { view: 'documents', path: '/documents', title: 'Documents', icon: 'description', keywords: ['documents', 'files', 'uploads'] },
  { view: 'artifacts', path: '/artifacts', title: 'Studio', icon: 'auto_awesome', keywords: ['artifact', 'artifacts', 'studio', 'docs', 'files', 'canvas', 'built'] },
  { view: 'tasks', path: '/tasks', title: 'Tasks', icon: 'check_circle', keywords: ['tasks', 'todo', 'daily', 'checklist'] },
  { view: 'calendar', path: '/calendar', title: 'Calendar', icon: 'calendar_today', keywords: ['calendar', 'events', 'schedule'] },
  { view: 'email', path: '/email', title: 'Email', icon: 'mail', keywords: ['email', 'mail', 'inbox', 'messages'] },
  { view: 'fitness', path: '/fitness', title: 'Fitness', icon: 'fitness_center', keywords: ['fitness', 'health', 'workout'] },
  { view: 'learn', path: '/learn', title: 'Learn', icon: 'school', keywords: ['learn', 'study', 'education'] },
  { view: 'projects', path: '/projects', title: 'Projects', icon: 'work', keywords: ['projects', 'work', 'planning'] },
  { view: 'recipes', path: '/recipes', title: 'Recipes', icon: 'restaurant_menu', keywords: ['recipes', 'cooking', 'food'] },
  { view: 'briefings', path: '/briefings', title: 'Briefings', icon: 'wb_sunny', keywords: ['brief', 'briefings', 'morning', 'research', 'papers'] },
  { view: 'sensory-monitor', path: '/sensory-monitor', title: 'Sensory', icon: 'sensors', keywords: ['sensory', 'monitor'] },
  { view: 'inbox', path: '/inbox', title: 'Today', icon: 'inbox', keywords: ['today', 'inbox', 'priorities', 'attention', 'content'] },
  { view: 'knowledge', path: '/knowledge', title: 'Knowledge', icon: 'psychology', keywords: ['knowledge', 'pkg', 'personal', 'facts', 'preferences', 'people'] },
  { view: 'workspace', path: '/workspace', title: 'Canvas', icon: 'grid_view', keywords: ['canvas', 'workspace', 'workbench'] },
  { view: 'automations', path: '/automations', title: 'Agent Tasks', icon: 'bolt', keywords: ['automations', 'agent', 'tasks', 'background', 'dispatch', 'missions'] },
  { view: 'settings', path: '/settings', title: 'Settings', icon: 'settings', keywords: ['settings', 'preferences', 'config'] },
  { view: 'privacy-dashboard', path: '/privacy-dashboard', title: 'Privacy', icon: 'lock', keywords: ['privacy', 'security'], includeInPalette: false },
  { view: 'orchestrator-lab', path: '/orchestrator-lab', title: 'Orchestrator Lab', icon: 'science', keywords: ['orchestrator', 'automation', 'lab'], includeInPalette: false },
  { view: 'acs', path: '/acs', title: 'ACS', icon: 'smart_toy', keywords: ['acs', 'mind', 'thoughts', 'autonomous', 'cognition', 'sara', 'inner', 'queue', 'inbox'] },
  { view: 'system', path: '/system', title: 'The System', icon: 'hub', keywords: ['system', 'awareness', 'world', 'mind', 'god view', 'attention', 'balance', 'thoughts'] },
  { view: 'machines', path: '/machines', title: 'Machines', icon: 'dns', keywords: ['machines', 'fleet', 'servers', 'hosts', 'infrastructure', 'boxes', 'health', 'disk', 'agent'] },
  { view: 'interior', path: '/interior', title: 'Interior', icon: 'insights', keywords: ['interior', 'kernel', 'intents', 'attention', 'actions', 'contradictions', 'singular', 'truth', 'body state'] },
  { view: 'life', path: '/life', title: 'Life', icon: 'favorite', keywords: ['life', 'calendar', 'email', 'fitness', 'recipes', 'routines', 'home'] },
  { view: 'work', path: '/work', title: 'Work', icon: 'work', keywords: ['work', 'projects', 'automations', 'agent tasks', 'machines', 'standing orders'] },
  { view: 'memory', path: '/memory', title: 'Memory', icon: 'psychology', keywords: ['memory', 'notes', 'documents', 'knowledge', 'learn', 'facts', 'people'] },
  { view: 'dial', path: '/dial', title: 'The Dial', icon: 'tune', keywords: ['dial', 'quiet hours', 'autonomy', 'initiative', 'calendar ownership', 'ungag'] },
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
