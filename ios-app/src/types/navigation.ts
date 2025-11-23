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
};

// Auth Stack Navigator
export type AuthStackParamList = {
  Login: undefined;
  Signup: undefined;
  ForgotPassword: undefined;
};

// Main Tab Navigator
export type MainTabParamList = {
  Home: undefined;
  Chat: undefined;
  Notes: undefined;
  Fitness: undefined;
  More: undefined;
  Recipes: undefined;
  Documents: undefined;
  Calendar: undefined;
  Briefings: undefined;
  ContextMode: undefined;
  SmartInsights: undefined;
  Health: undefined;
  Settings: undefined;
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
