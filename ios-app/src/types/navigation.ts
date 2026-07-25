import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import type { BottomTabScreenProps } from '@react-navigation/bottom-tabs';
import type { CompositeScreenProps } from '@react-navigation/native';

// Root Stack Navigator
export type RootStackParamList = {
  Auth: undefined;
  Main: undefined;
  RecoveryForm: {
    log?: any;
    onSave?: () => void;
  };
  EventForm: {
    event?: any;
    onSave?: () => void;
  };
  ReminderForm: {
    reminder?: any;
    onSave?: () => void;
  };
  NoteEditor: {
    noteId?: string | number;
    folderId?: string | number;
    onSave?: () => void;
  };
  NutritionGoalsForm: {
    onSave?: () => void;
  };
  RecipeForm: {
    recipe?: any;
    onSave?: () => void;
  };
  WorkoutMode: {
    templateId?: string;  // If provided, starts workout with this template
  } | undefined;
  Cardio: undefined;
  TabataTimer: {
    // A saved TabataPreset OR an ad-hoc config from the editor's "Start now".
    preset: import('../services/cardio').TabataPreset;
  };
  DailyPlan: undefined;
};

// Auth Stack Navigator
export type AuthStackParamList = {
  Login: undefined;
  Signup: undefined;
};

// Health Alert data passed when opening chat from notification
export type HealthAlertContext = {
  severity: string;
  insightId?: string;
  title?: string;
  body?: string;
};

// Nudge context passed when opening chat from notification (meal reminders, morning check-ins, etc.)
export type NudgeContext = {
  nudgeType: string;  // 'morning_checkin', 'missed_meal', 'bedtime', etc.
  title: string;
  message: string;
  actionSuggestion?: string;
};

// Quick reply context when user replies from notification
export type QuickReplyContext = {
  message: string;
  nudgeType?: string;
  title?: string;
};

// Heartbeat context passed when opening chat from heartbeat notification (proactive check-ins from Sara)
export type HeartbeatContext = {
  title: string;
  message: string;
  priority: string;  // 'low', 'normal', 'high'
};

// ACS notification context passed when opening chat from notification screen
export type NotificationContext = {
  id: string;
  title: string;
  message: string;
  category: string;
  item_type: string;  // 'notification' | 'acs_discovery'
};

export type NoteContext = {
  id: string;
  title: string;
  prompt?: string;
  preview?: string;
};

// Chat screen params (used by Sara tab)
export type ChatScreenParams = {
  healthAlert?: HealthAlertContext;
  nudge?: NudgeContext;
  quickReply?: QuickReplyContext;
  heartbeat?: HeartbeatContext;
  inboxItem?: { id: string; title: string };
  noteContext?: NoteContext;
  notification?: NotificationContext;
  taskInject?: { taskId: string; conversationId?: string; noteId?: string };
};

// Main Tab Navigator — SINGULAR_SARA_MASTER_PLAN §U8: Sara, Today, Chat,
// Life, More. `AssistantInboxTab` keeps its route key (existing call sites
// navigate to it by name) but is now labeled "Today" in the tab bar; `Life`
// replaces the standalone `Fitness` tab (Fitness itself moves to the app
// stack, reachable from the Life hub and from any existing
// navigation.navigate('Fitness') call).
export type MainTabParamList = {
  Sara: undefined;
  AssistantInboxTab: {
    focus?: 'all' | 'waiting' | 'in_progress' | 'new' | 'done' | 'archived';
  } | undefined;
  Chat: ChatScreenParams | undefined;
  Life: undefined;
  More: undefined;
};

// Screen Props Types
export type RootStackScreenProps<T extends keyof RootStackParamList> =
  NativeStackScreenProps<RootStackParamList, T>;

export type AuthStackScreenProps<T extends keyof AuthStackParamList> =
  CompositeScreenProps<
    NativeStackScreenProps<AuthStackParamList, T>,
    RootStackScreenProps<keyof RootStackParamList>
  >;

export type MainTabScreenProps<T extends keyof MainTabParamList> =
  CompositeScreenProps<
    BottomTabScreenProps<MainTabParamList, T>,
    RootStackScreenProps<keyof RootStackParamList>
  >;

declare global {
  namespace ReactNavigation {
    interface RootParamList extends RootStackParamList {}
  }
}
