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
    noteId?: number;
    folderId?: number;
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
};

// Auth Stack Navigator
export type AuthStackParamList = {
  Login: undefined;
  Signup: undefined;
  ForgotPassword: undefined;
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

// Main Tab Navigator
export type MainTabParamList = {
  Home: undefined;
  Chat: {
    healthAlert?: HealthAlertContext;
    nudge?: NudgeContext;
    quickReply?: QuickReplyContext;
  } | undefined;
  Learning: undefined;
  Notes: undefined;
  Fitness: undefined;
  More: undefined;
  Recipes: undefined;
  Documents: undefined;
  Calendar: undefined;
  Briefings: undefined;
  Health: undefined;
  Settings: undefined;
  Projects: undefined;
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
