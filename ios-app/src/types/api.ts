// API Response Types
export interface ApiResponse<T = any> {
  success: boolean;
  message?: string;
  data?: T;
  error?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface User {
  id: string;
  email: string;
  full_name?: string;
  created_at: string;
  preferences?: UserPreferences;
}

export interface UserPreferences {
  personality_mode?: string;
  theme?: 'light' | 'dark';
  notifications_enabled?: boolean;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
  metadata?: Record<string, any>;
  attachments?: Attachment[];
}

export interface Attachment {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  url: string;
}

export interface Note {
  id: number;
  title: string;
  content: string;
  created_at: string;
  updated_at: string;
  folder_id?: number;
}

export interface Folder {
  id: number;
  name: string;
  parent_id?: number;
}

export interface Habit {
  id: number;
  name: string;
  description?: string;
  frequency: 'daily' | 'weekly' | 'custom';
  streak_count: number;
  last_completed?: string;
  created_at: string;
}

export interface FoodLog {
  id: number;
  meal_type: 'breakfast' | 'lunch' | 'dinner' | 'snack';
  items: FoodItem[];
  logged_at: string;
  notes?: string;
}

export interface FoodItem {
  name: string;
  serving_size: string;
  calories: number;
  protein: number;
  carbs: number;
  fats: number;
}

export interface WorkoutLog {
  id: number;
  name: string;
  exercises: Exercise[];
  duration_minutes: number;
  logged_at: string;
  notes?: string;
}

export interface Exercise {
  name: string;
  sets: number;
  reps: number;
  weight?: number;
  notes?: string;
}

export interface Document {
  id: number;
  filename: string;
  content_type: string;
  size: number;
  url: string;
  uploaded_at: string;
}

export interface Reminder {
  id: number;
  title: string;
  description?: string;
  due_at: string;
  completed: boolean;
  created_at: string;
}

export interface Timer {
  id: string;
  name: string;
  duration_seconds: number;
  started_at: string;
  remaining_seconds: number;
}

export interface CalendarEvent {
  id: number;
  title: string;
  description?: string;
  start_time: string;
  end_time: string;
  all_day: boolean;
  created_at: string;
}

export interface IngredientItem {
  name: string;
  quantity: number;
  unit: string;
  calories?: number;
  protein?: number;
  carbs?: number;
  fats?: number;
}

export interface Recipe {
  id: string;
  user_id: string;
  name: string;
  description?: string;
  category?: string;
  ingredients: IngredientItem[];
  instructions: string;
  prep_time_minutes?: number;
  servings: number;
  calories?: number;
  protein?: number;
  carbs?: number;
  fats?: number;
  created_at: string;
  updated_at: string;
}
