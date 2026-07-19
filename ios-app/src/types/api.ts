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

// Content types for multimodal messages
export interface TextContent {
  type: 'text';
  text: string;
}

export interface ImageContent {
  type: 'image';
  data: string;  // Base64 encoded
  media_type: string;  // e.g., 'image/jpeg'
}

export type MessageContent = string | (TextContent | ImageContent)[];

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: MessageContent;
  created_at: string;
  episode_id?: string;  // For rating episodes
  metadata?: Record<string, any>;
  attachments?: Attachment[];
  cards?: any[];  // Content cards from tool execution
}

export interface Attachment {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  url: string;
}

export interface Note {
  id: string | number;
  title: string;
  content: string;
  created_at: string;
  updated_at: string;
  folder_id?: string | number | null;
}

export interface Folder {
  id: string | number;
  name: string;
  parent_id?: string | number | null;
  notes_count?: number;
  subfolders_count?: number;
  updated_at?: string;
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
  // Null when Sara couldn't parse a freeform ingredient line (e.g. "3/4 cup
  // mayonnaise" pasted from a recipe) into structured quantity/unit.
  quantity: number | null;
  unit: string | null;
  calories?: number;
  protein?: number;
  carbs?: number;
  fats?: number;
  // Provenance for live-lookup ingredients (R1/R3)
  food_id?: string;
  source?: 'fatsecret' | 'user' | 'manual';
  serving_description?: string;
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

// Project Tracker Types
export interface Project {
  id: string;
  name: string;
  prefix: string;
  description?: string;
  tech_stack?: string;
  business_context?: string;
  github_repo_owner?: string;
  github_repo_name?: string;
  github_repo_url?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  task_counts?: Record<string, number>;
}

export interface Task {
  id: string;
  project_id: string;
  task_number: number;
  tag: string;
  title: string;
  description?: string;
  task_type: 'feature' | 'bug' | 'task' | 'chore';
  status: 'backlog' | 'in_progress' | 'in_qa' | 'completed';
  priority?: 'low' | 'medium' | 'high' | 'critical';
  tags?: string[];
  sort_order: number;
  created_at: string;
  updated_at: string;
  completed_at?: string;
  commit_count: number;
}

export interface TaskBoard {
  backlog: Task[];
  in_progress: Task[];
  in_qa: Task[];
  completed: Task[];
  total: number;
}

export interface Commit {
  id: string;
  sha: string;
  short_sha: string;
  message: string;
  author_name?: string;
  author_email?: string;
  committed_at: string;
  branch?: string;
  additions?: number;
  deletions?: number;
  linked_tasks: string[];
}

export interface QAChecklistItem {
  id: string;
  label: string;
  sort_order: number;
  is_active: boolean;
  created_at: string;
}

export interface QAPendingCommit {
  id: string;
  sha: string;
  message: string;
  author_name?: string;
  committed_at: string;
  qa_status?: string;
}

export interface QAPendingTask {
  task_id: string;
  task_tag: string;
  task_title: string;
  commits: QAPendingCommit[];
}

// Project Files Types
export interface ProjectFolder {
  id: string;
  name: string;
  parent_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectFile {
  id: string;
  filename: string;
  folder_id: string | null;
  mime_type: string | null;
  file_size: number;
  file_size_formatted: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface FileListResponse {
  files: ProjectFile[];
  folders: ProjectFolder[];
  total_files: number;
  total_folders: number;
  current_folder_id: string | null;
  breadcrumb: ProjectFolder[];
}

// Background Task Types
export interface BackgroundTask {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'needs_clarification';
  task_type: string;
  original_query: string;
  result_note_id: string | null;
  workspace_folder_id: string | null;
  clarification_question: string | null;
  error_message: string | null;
  status_label?: string | null;  // friendly current-step label (e.g. "editing mul.py")
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface BackgroundTasksResponse {
  tasks: BackgroundTask[];
}
