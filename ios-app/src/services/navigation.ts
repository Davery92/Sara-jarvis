/**
 * Navigation Service
 *
 * Provides navigation capabilities from outside React components.
 * Used for deep linking from push notifications.
 */

import { createNavigationContainerRef, CommonActions } from '@react-navigation/native';
import { RootStackParamList } from '../types/navigation';

export const navigationRef = createNavigationContainerRef<RootStackParamList>();

/**
 * Maps native route names (tabs + stack screens) to the web canonical view
 * vocabulary (frontend/src/navigation/views.ts) so Sara's app_current_view
 * means the same thing regardless of platform. New screens are a one-line add.
 */
export const ROUTE_TO_VIEW: Record<string, string> = {
  // Bottom tabs
  Sara: 'chat',
  AssistantInboxTab: 'inbox',
  Fitness: 'fitness',
  More: 'dashboard',
  // Chat
  Chat: 'chat',
  // Notes
  Notes: 'notes',
  NoteEditor: 'notes',
  // Recipes
  Recipes: 'recipes',
  RecipeForm: 'recipes',
  // Fitness-adjacent
  Health: 'fitness',
  RecoveryForm: 'fitness',
  NutritionGoalsForm: 'fitness',
  WorkoutMode: 'fitness',
  Cardio: 'fitness',
  TabataTimer: 'fitness',
  // Content / knowledge
  Documents: 'documents',
  Studio: 'artifacts',
  Knowledge: 'knowledge',
  Learning: 'learn',
  // Schedule
  Calendar: 'calendar',
  EventForm: 'calendar',
  ReminderForm: 'calendar',
  Briefings: 'briefings',
  // Work
  Projects: 'projects',
  Automations: 'automations',
  AgentTasks: 'automations',
  DailyTasks: 'tasks',
  // Comms / inbox
  Email: 'email',
  EmailDetail: 'email',
  Inbox: 'inbox',
  AssistantInbox: 'inbox',
  Notifications: 'inbox',
  // System
  ACS: 'acs',
  System: 'system',
  Settings: 'settings',
  AssistantAnalytics: 'dashboard',
  DailyPlan: 'dashboard',
};

/**
 * Resolve the deepest active route to a canonical web view name. Falls back to
 * 'dashboard' for unmapped/unknown screens.
 */
export function getCurrentViewName(): string {
  try {
    if (!navigationRef.isReady()) return 'dashboard';
    const route = navigationRef.getCurrentRoute();
    if (!route?.name) return 'dashboard';
    return ROUTE_TO_VIEW[route.name] ?? 'dashboard';
  } catch {
    return 'dashboard';
  }
}

// Queue for pending navigations when navigator isn't ready
type PendingNavigation =
  | { kind: 'tab'; name: string; params?: object }
  | { kind: 'stack'; name: string; params?: object }
  | { kind: 'root'; name: string; params?: object };

let pendingNavigation: PendingNavigation | null = null;

/**
 * Process any pending navigation once navigator is ready
 * Call this from NavigationContainer's onReady callback
 */
export function onNavigatorReady() {
  console.log('[Navigation] Navigator is ready');
  if (pendingNavigation) {
    console.log('[Navigation] Processing pending navigation to:', pendingNavigation.name);
    const { kind, name, params } = pendingNavigation;
    pendingNavigation = null;
    if (kind === 'tab') {
      navigateToTab(name, params);
    } else if (kind === 'stack') {
      navigateToStackScreen(name, params);
    } else {
      navigate(name, params);
    }
  }
}

/**
 * Navigate to a screen
 */
export function navigate(name: string, params?: object) {
  if (navigationRef.isReady()) {
    navigationRef.dispatch(
      CommonActions.navigate({
        name,
        params,
      })
    );
  } else {
    console.log('[Navigation] Navigator not ready, queueing navigation to:', name);
    pendingNavigation = { kind: 'root', name, params };
  }
}

/**
 * Navigate to a specific tab with optional params
 */
export function navigateToTab(tabName: string, params?: object) {
  if (navigationRef.isReady()) {
    try {
      // Navigate through the nested structure: Main -> MainTabs -> tabName
      // @ts-ignore
      navigationRef.navigate('Main', {
        screen: 'MainTabs',
        params: {
          screen: tabName,
          params: params,
        },
      });
    } catch (error) {
      console.error('[Navigation] Error navigating to', tabName, error);
    }
  } else {
    console.log('[Navigation] Navigator not ready, queueing navigation to:', tabName);
    pendingNavigation = { kind: 'tab', name: tabName, params };
  }
}

function navigateToStackScreen(screenName: string, params?: object) {
  if (navigationRef.isReady()) {
    try {
      // @ts-ignore
      navigationRef.navigate('Main', {
        screen: screenName,
        params,
      });
    } catch (error) {
      console.error('[Navigation] Error navigating to screen:', screenName, error);
    }
  } else {
    console.log('[Navigation] Navigator not ready, queueing stack navigation to:', screenName);
    pendingNavigation = { kind: 'stack', name: screenName, params };
  }
}

/**
 * Navigate to Fitness tab
 */
export function navigateToFitness() {
  navigateToTab('Fitness');
}

/**
 * Navigate to Chat tab with optional context
 */
export function navigateToChat(params?: {
  healthAlert?: { severity: string; insightId?: string; title?: string; body?: string };
  nudge?: { nudgeType: string; title: string; message: string; actionSuggestion?: string };
  quickReply?: { message: string; nudgeType?: string; title?: string };
  heartbeat?: { title: string; message: string; priority: string };
  inboxItem?: { id: string; title: string };
  noteContext?: { id: string; title: string; prompt?: string; preview?: string };
  taskInject?: { taskId: string; conversationId?: string; noteId?: string };
  notification?: { id: string; title: string; message: string; category: string; item_type: string };
}) {
  console.log('[Navigation] navigateToChat called with params:', params);
  navigateToStackScreen('Chat', params);
}

/**
 * Navigate to Inbox screen
 */
export function navigateToInbox(
  params: { tab?: 'content' | 'attention'; focus?: 'all' | 'waiting' | 'in_progress' | 'new' | 'done' | 'archived' } = { focus: 'new' }
) {
  const focus =
    params.focus ||
    (params.tab === 'attention' ? 'waiting' : 'new');

  navigateToTab('AssistantInboxTab', { focus });
}

export function navigateToNotifications(params?: { notificationId?: number }) {
  navigateToStackScreen('Notifications', params);
}

export function navigateToNoteEditor(noteId: string | number, params?: { onSave?: () => void }) {
  navigate('NoteEditor', {
    noteId,
    ...params,
  });
}

/**
 * Sara ui_command handler — chat-driven navigation ("open my inbox",
 * "bring up my note about the server build"). The backend emits a
 * `ui_command` SSE event; overlay kinds (webapp surfaces) and screen
 * targets both map to native screens here.
 */
export interface SaraUiCommand {
  action: string;
  overlay?: string;
  screen?: string;
  payload?: Record<string, any>;
}

const OVERLAY_TO_SCREEN: Record<string, () => void> = {
  brief: () => navigateToStackScreen('Briefings'),
  nutrition: () => navigateToTab('Fitness'),
  calendar: () => navigateToStackScreen('Calendar'),
  tasks: () => navigateToStackScreen('AgentTasks'),
};

const SCREEN_TARGETS: Record<string, () => void> = {
  inbox: () => navigateToInbox(),
  notifications: () => navigateToNotifications(),
  email: () => navigateToStackScreen('Email'),
  documents: () => navigateToStackScreen('Documents'),
  recipes: () => navigateToStackScreen('Recipes'),
  settings: () => navigateToStackScreen('Settings'),
  health: () => navigateToStackScreen('Health'),
  learning: () => navigateToStackScreen('Learning'),
  projects: () => navigateToStackScreen('Projects'),
  automations: () => navigateToStackScreen('Automations'),
  knowledge: () => navigateToStackScreen('Knowledge'),
  fitness: () => navigateToTab('Fitness'),
  notes: () => navigateToStackScreen('Notes'),
  chat: () => navigateToChat(),
};

export function handleSaraUiCommand(cmd: SaraUiCommand): boolean {
  try {
    if (cmd?.action === 'open_overlay' && cmd.overlay) {
      if (cmd.overlay === 'note' && cmd.payload?.note_id) {
        navigateToNoteEditor(cmd.payload.note_id);
        return true;
      }
      const open = OVERLAY_TO_SCREEN[cmd.overlay];
      if (open) {
        open();
        return true;
      }
      return false;
    }
    if (cmd?.action === 'navigate' && cmd.screen) {
      const open = SCREEN_TARGETS[cmd.screen];
      if (open) {
        open();
        return true;
      }
    }
    return false;
  } catch (error) {
    console.error('[Navigation] Failed to handle ui_command:', error);
    return false;
  }
}

/**
 * Go back
 */
export function goBack() {
  if (navigationRef.isReady() && navigationRef.canGoBack()) {
    navigationRef.goBack();
  }
}
