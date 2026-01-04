// Auto-generated TypeScript types for Sara tools
// Generated at: 2025-11-14T14:35:20.453000
// DO NOT EDIT MANUALLY

// Tool categories
export enum ToolCategory {
  MEMORY = 'memory',
  KNOWLEDGE_GRAPH = 'knowledge_graph',
  NOTES = 'notes',
  TIME = 'time',
  WEB = 'web',
  FITNESS = 'fitness',
  SHADOW = 'shadow',
  HEALTH = 'health',
  GOALS = 'goals',
  INTELLIGENCE = 'intelligence',
}

// 🔍 Analyze your knowledge graph to identify gaps, isolated content, and potential connections. Helps discover orphaned content and suggests areas for knowledge expansion.
// Category: knowledge_graph
export interface AnalyzeKnowledgeGapsParams {
  isolation_threshold?: number | undefined; // Consider items with fewer than this many connections as isolated (default: 2)
}

// Create a new calendar event with title, start/end times, and optional location and description.
// Category: time
export interface CalendarCreateParams {
  title: string; // The event title
  starts_at: string; // Event start time (ISO 8601 datetime format, e.g., '2024-01-15T14:30:00Z')
  ends_at: string; // Event end time (ISO 8601 datetime format, e.g., '2024-01-15T15:30:00Z')
  location?: string | undefined; // Optional event location
  description?: string | undefined; // Optional event description
}

// List calendar events for a date range. If no dates are provided, shows events for the current week.
// Category: time
export interface CalendarListParams {
  start_date?: string | undefined; // Start date for event listing (YYYY-MM-DD format). Defaults to today.
  end_date?: string | undefined; // End date for event listing (YYYY-MM-DD format). Defaults to 7 days from start_date.
  limit?: number | undefined; // Maximum number of events to return (default: 50)
}

// 🧩 Discover knowledge clusters and communities in your content using advanced graph algorithms. Finds groups of related content and identifies knowledge themes.
// Category: knowledge_graph
export interface DiscoverKnowledgeClustersParams {
  min_cluster_size?: number | undefined; // Minimum size for clusters to report (default: 3)
}

// 🔗 Discover what content is connected to a specific note, conversation, or document. Shows direct and indirect relationships, helping understand how ideas are linked in your knowledge.
// Category: knowledge_graph
export interface FindConnectionsParams {
  content_id: string; // ID of the content to find connections for
  depth?: number | undefined; // How many degrees of connection to explore (1=direct, 2=friends of friends, etc.)
  connection_types?: Array<any> | undefined; // Optional filter for specific relationship types (REFERENCES, SEMANTIC_SIMILAR, etc.)
}

// Create a fitness note with title, content, and category. Categories: nutrition, workout, goal, progress, general. Notes are automatically embedded for semantic search.
// Category: fitness
export interface FitnessNoteCreateParams {
  title?: string | undefined; // Title for the note
  content: string; // The note content
  category: "nutrition" | "workout" | "goal" | "progress" | "general"; // Note category
}

// Edit an existing fitness note's title, content, or category. The note will be re-embedded after editing.
// Category: fitness
export interface FitnessNoteEditParams {
  note_id: string; // The ID of the note to edit
  title?: string | undefined; // New title
  content?: string | undefined; // New content
  category?: "nutrition" | "workout" | "goal" | "progress" | "general" | undefined; // New category
}

// Search through fitness notes using keywords or semantic similarity. Optionally filter by category.
// Category: fitness
export interface FitnessNoteSearchParams {
  query: string; // Search query
  category?: "nutrition" | "workout" | "goal" | "progress" | "general" | "all" | undefined; // Filter by category
  limit?: number | undefined; // Maximum results (default: 10)
}

// Get user's current fitness status: today's nutrition, recent workouts (last 3-7 days), upcoming scheduled workouts, and recovery metrics. Use this when the user asks about their fitness, workouts, nutrition, or training progress.
// Category: fitness
export interface FitnessSummaryParams {
  days_back?: number | undefined; // Number of days to look back for recent workouts (default: 3)
}

// MANUAL food logging tool - use ONLY when the user provides specific nutrition values (calories, protein, carbs, fats) or when food_search_and_log tool is not appropriate. For natural language food descriptions, use food_search_and_log instead for automatic USDA nutrition lookup.
// Category: fitness
export interface FoodLogCreateParams {
  meal_type: "breakfast" | "lunch" | "dinner" | "snack"; // Type of meal
  food_description?: string | undefined; // Simple description of food items (e.g., '3 eggs, 4oz ground beef'). Do NOT use JSON arrays.
  calories?: number | undefined; // Total calories (optional)
  protein?: number | undefined; // Protein in grams (optional)
  carbs?: number | undefined; // Carbohydrates in grams (optional)
  fats?: number | undefined; // Fats in grams (optional)
  notes?: string | undefined; // Additional notes about the meal
  logged_at?: string | undefined; // When the meal was eaten (ISO format, defaults to now)
}

// Search food log entries by date range. Returns meals with nutritional totals.
// Category: fitness
export interface FoodLogSearchParams {
  start_date?: string | undefined; // Start date (ISO format, defaults to today)
  end_date?: string | undefined; // End date (ISO format, defaults to today)
  meal_type?: "breakfast" | "lunch" | "dinner" | "snack" | "all" | undefined; // Filter by meal type (optional)
  limit?: number | undefined; // Maximum results (default: 20)
}

// Get nutrition summary for a date range (daily averages, totals, meal distribution).
// Category: fitness
export interface FoodLogSummaryParams {
  start_date?: string | undefined; // Start date (ISO format)
  end_date?: string | undefined; // End date (ISO format)
  period?: "day" | "week" | "month" | undefined; // Summary period
}

// PREFERRED TOOL for logging meals. Parse natural language food descriptions (e.g., '3 eggs and 4oz ground beef' or 'chicken breast 6oz and rice 1 cup'), automatically search USDA nutrition database for accurate data, calculate nutritional totals, and log the meal. Use this whenever the user mentions eating food in natural language. This provides accurate USDA nutrition data instead of estimates.
// Category: fitness
export interface FoodSearchAndLogParams {
  user_input: string; // Natural language food description like '3 eggs and 4oz ground beef' or '2 chicken breasts and 1 cup rice'
  meal_type: "breakfast" | "lunch" | "dinner" | "snack"; // Type of meal
}

// Retrieve full page content from a previous open_page call using its reference ID. ONLY use this if the 500-char preview from open_page was insufficient to answer the question. The preview usually contains enough information - avoid calling this unless truly necessary.
// Category: web
export interface GetPageDetailsParams {
  reference_id: string; // The reference ID from a previous open_page call
}

// Retrieve full details of a previous web search using its reference ID. ONLY use this if the compact summary from web_search was insufficient to answer the user's question. The summary usually contains enough information - avoid calling this unless truly necessary.
// Category: web
export interface GetWebSearchDetailsParams {
  reference_id: string; // The reference ID from a previous web_search call
}

// 🧠 Search across ALL of your knowledge - notes, conversations, and documents - using advanced graph intelligence. This tool can find content by topic, discover related items, and show connections between different types of content.
// Category: knowledge_graph
export interface KnowledgeGraphSearchParams {
  query: string; // Search query to find relevant content across all types
  content_types?: Array<any> | undefined; // Optional filter for specific content types (default: all types)
  include_connections?: boolean | undefined; // Whether to include connected content in results (default: true)
  limit?: number | undefined; // Maximum number of results to return (default: 15)
}

// Search personal memory across notes, document chunks, episodes, and semantic summaries. Use this to find relevant information from the user's knowledge base.
// Category: memory
export interface MemorySearchParams {
  query: string; // The search query to find relevant memories
  scopes?: Array<any> | undefined; // Which types of memory to search. Defaults to all types.
  limit?: number | undefined; // Maximum number of results to return (default: 6)
}

// Create a new note with optional title and content. The note will be automatically embedded for semantic search.
// Category: notes
export interface NotesCreateParams {
  title?: string | undefined; // Optional title for the note
  content: string; // The note content
}

// Delete a note by its ID. This action cannot be undone.
// Category: notes
export interface NotesDeleteParams {
  note_id: string; // The ID of the note to delete
}

// Edit an existing note's title or content. The note will be re-embedded after editing.
// Category: notes
export interface NotesEditParams {
  note_id: string; // The ID of the note to edit
  title?: string | undefined; // New title for the note
  content?: string | undefined; // New content for the note
}

// List all notes for the user, optionally filtered by folder. Returns note IDs, titles, and preview of content.
// Category: notes
export interface NotesListParams {
  folder_id?: string | undefined; // Optional folder ID to filter notes by folder
  limit?: number | undefined; // Maximum number of notes to return (default: 20)
}

// Search through notes using keywords or semantic similarity.
// Category: notes
export interface NotesSearchParams {
  query: string; // Search query for finding notes
  limit?: number | undefined; // Maximum number of notes to return (default: 10)
}

// Open a web page and return a compact summary with title and first 500 chars of content. This preview is usually sufficient for most questions. Full page content is stored if needed later.
// Category: web
export interface OpenPageParams {
  url: string; // URL to open
}

// Create or update daily recovery log with metrics like HRV, heart rate, sleep hours, soreness level (1-10), and body weight. Use this when the user shares recovery data or morning metrics.
// Category: fitness
export interface RecoveryLogCreateParams {
  log_date?: string | undefined; // Date for the recovery log (YYYY-MM-DD format, defaults to today)
  hrv?: number | undefined; // Heart Rate Variability in milliseconds (optional)
  heart_rate?: number | undefined; // Resting heart rate in BPM (optional)
  sleep_hours?: number | undefined; // Hours of sleep (can include decimals like 7.5)
  soreness_level?: number | undefined; // Muscle soreness on 1-10 scale (1=none, 10=extremely sore)
  body_weight?: number | undefined; // Body weight (optional)
  weight_unit?: "lbs" | "kg" | undefined; // Unit for body weight
  notes?: string | undefined; // Additional notes about recovery, how you feel, injuries, etc.
}

// Get recovery log for a specific date to see HRV, sleep, soreness, and other metrics from that day.
// Category: fitness
export interface RecoveryLogGetParams {
  log_date?: string | undefined; // Date to retrieve (YYYY-MM-DD format, defaults to today)
}

// Get recent recovery logs (default: last 7 days) to analyze trends in HRV, sleep quality, soreness patterns, and overall recovery status.
// Category: fitness
export interface RecoveryLogRecentParams {
  days?: number | undefined; // Number of days to retrieve (default: 7, max: 90)
}

// Cancel a reminder by ID. This sets the reminder status to 'cancelled'.
// Category: time
export interface RemindersCancelParams {
  reminder_id: string; // The ID of the reminder to cancel
}

// Create a new reminder with text and due date/time. The due_at parameter should be an ISO 8601 datetime string.
// Category: time
export interface RemindersCreateParams {
  text: string; // The reminder text/message
  due_at: string; // When the reminder should trigger (ISO 8601 datetime format, e.g., '2024-01-15T14:30:00Z')
}

// List reminders for a specific day or all upcoming reminders. Can filter by status (scheduled, completed, cancelled).
// Category: time
export interface RemindersListParams {
  date?: string | undefined; // Optional date to filter reminders (YYYY-MM-DD format). If not provided, shows all upcoming reminders.
  status?: string | undefined; // Filter by status (scheduled, completed, cancelled). Defaults to 'scheduled'.
  limit?: number | undefined; // Maximum number of reminders to return (default: 20)
}

// Start a SHADOW MODE session (NOT a timer) to automatically capture browser activity, VS Code files, tasks, decisions, and ideas from a desktop agent. Use this when the user says 'shadow me', 'start shadow mode', 'shadow session', or wants to track their work activity automatically.
// Category: notes
export interface StartShadowSessionParams {
  duration_minutes?: number | undefined; // Duration of the session in minutes (e.g., 2, 30, 60, 90)
  context?: string | undefined; // Optional context describing what you'll be working on
}

// Get detailed information about a specific workout template including all exercises, sets, reps, and RPE targets
// Category: fitness
export interface TemplateGetParams {
  template_id?: string | undefined; // The ID of the template to retrieve
  template_name?: string | undefined; // Alternatively, the name of the template (case-insensitive partial match)
}

// List all workout templates with their scheduled days and exercises
// Category: fitness
export interface TemplateListParams {
  phase_id?: string | undefined; // Optional: Filter templates by training phase ID
}

// Cancel a running timer by ID. This sets the timer status to 'cancelled'.
// Category: time
export interface TimersCancelParams {
  timer_id: string; // The ID of the timer to cancel
}

// Start a new timer with optional label and duration. Use duration_seconds for precise durations (e.g., 30 seconds, 90 seconds). For longer timers, can use duration in minutes. If no duration is provided, defaults to 25 minutes.
// Category: time
export interface TimersStartParams {
  label?: string | undefined; // Optional label/description for the timer
  duration?: number | undefined; // Duration in minutes. Deprecated - use duration_seconds for more precision.
  duration_seconds?: number | undefined; // Duration in seconds. Takes priority over duration if both provided.
}

// Check the status of all active timers, including time remaining and whether they've completed.
// Category: time
export interface TimersStatusParams {
  include_completed?: boolean | undefined; // Whether to include recently completed timers (default: false)
  limit?: number | undefined; // Maximum number of timers to return (default: 10)
}

// Search the web using SearXNG. Returns a compact summary with top 5 results (title, URL, 200-char snippet). This summary is usually sufficient to answer most questions. Full details are stored temporarily if needed later.
// Category: web
export interface WebSearchParams {
  query: string; // Search query
  recency?: "any" | "day" | "week" | "month" | undefined; // Result freshness preference
  sites?: Array<any> | undefined; // Optional site filters (e.g., 'docs.python.org')
  max_results?: number | undefined; // Maximum results to return
}

// Get detailed workout logs showing all logged sets (weight, reps, RPE) for a specific date or workout session. Use this to see what exercises were performed and how much weight was lifted.
// Category: fitness
export interface WorkoutDetailsParams {
  date?: string | undefined; // Date to get workout details for (YYYY-MM-DD format). Defaults to today.
  workout_id?: string | undefined; // Optional specific workout ID to get details for
  exercise_name?: string | undefined; // Optional filter by specific exercise name
}

// List available workouts, optionally filtered by status (scheduled, completed, all). Shows planned workouts from fitness plans.
// Category: fitness
export interface WorkoutListParams {
  status?: "scheduled" | "completed" | "all" | undefined; // Filter by workout status
  limit?: number | undefined; // Maximum results (default: 20)
}

// Log exercise sets completed during a workout. Records weight, reps, RPE (Rate of Perceived Exertion 1-10) for each set.
// Category: fitness
export interface WorkoutLogCreateParams {
  workout_id?: string | undefined; // ID of the workout being logged (optional - will auto-create today's workout if not provided)
  exercise_id: string; // Exercise name or identifier
  set_index: number; // Set number (1, 2, 3...)
  weight?: number | undefined; // Weight used (lbs or kg)
  reps?: number | undefined; // Repetitions completed
  rpe?: number | undefined; // Rate of Perceived Exertion (1-10)
  notes?: string | undefined; // Additional notes about the set
  session_date?: string | undefined; // Optional custom workout date in YYYY-MM-DD format (defaults to today)
  session_time?: string | undefined; // Optional full ISO timestamp for exact workout time
}

// Get workout statistics for a date range: total workouts, exercises logged, volume trends.
// Category: fitness
export interface WorkoutStatsParams {
  start_date?: string | undefined; // Start date (ISO format)
  end_date?: string | undefined; // End date (ISO format)
  period?: "week" | "month" | "all" | undefined; // Stats period
}

// Tool names enum
export enum ToolName {
  AnalyzeKnowledgeGaps = 'analyze_knowledge_gaps',
  CalendarCreate = 'calendar_create',
  CalendarList = 'calendar_list',
  DiscoverKnowledgeClusters = 'discover_knowledge_clusters',
  FindConnections = 'find_connections',
  FitnessNoteCreate = 'fitness_note_create',
  FitnessNoteEdit = 'fitness_note_edit',
  FitnessNoteSearch = 'fitness_note_search',
  FitnessSummary = 'fitness_summary',
  FoodLogCreate = 'food_log_create',
  FoodLogSearch = 'food_log_search',
  FoodLogSummary = 'food_log_summary',
  FoodSearchAndLog = 'food_search_and_log',
  GetPageDetails = 'get_page_details',
  GetWebSearchDetails = 'get_web_search_details',
  KnowledgeGraphSearch = 'knowledge_graph_search',
  MemorySearch = 'memory_search',
  NotesCreate = 'notes_create',
  NotesDelete = 'notes_delete',
  NotesEdit = 'notes_edit',
  NotesList = 'notes_list',
  NotesSearch = 'notes_search',
  OpenPage = 'open_page',
  RecoveryLogCreate = 'recovery_log_create',
  RecoveryLogGet = 'recovery_log_get',
  RecoveryLogRecent = 'recovery_log_recent',
  RemindersCancel = 'reminders_cancel',
  RemindersCreate = 'reminders_create',
  RemindersList = 'reminders_list',
  StartShadowSession = 'start_shadow_session',
  TemplateGet = 'template_get',
  TemplateList = 'template_list',
  TimersCancel = 'timers_cancel',
  TimersStart = 'timers_start',
  TimersStatus = 'timers_status',
  WebSearch = 'web_search',
  WorkoutDetails = 'workout_details',
  WorkoutList = 'workout_list',
  WorkoutLogCreate = 'workout_log_create',
  WorkoutStats = 'workout_stats',
}

// Tool registry type
export interface ToolRegistry {
  analyze_knowledge_gaps: {
    params: AnalyzeKnowledgeGapsParams;
    result: { success: boolean; message?: string; data?: any };
  };
  calendar_create: {
    params: CalendarCreateParams;
    result: { success: boolean; message?: string; data?: any };
  };
  calendar_list: {
    params: CalendarListParams;
    result: { success: boolean; message?: string; data?: any };
  };
  discover_knowledge_clusters: {
    params: DiscoverKnowledgeClustersParams;
    result: { success: boolean; message?: string; data?: any };
  };
  find_connections: {
    params: FindConnectionsParams;
    result: { success: boolean; message?: string; data?: any };
  };
  fitness_note_create: {
    params: FitnessNoteCreateParams;
    result: { success: boolean; message?: string; data?: any };
  };
  fitness_note_edit: {
    params: FitnessNoteEditParams;
    result: { success: boolean; message?: string; data?: any };
  };
  fitness_note_search: {
    params: FitnessNoteSearchParams;
    result: { success: boolean; message?: string; data?: any };
  };
  fitness_summary: {
    params: FitnessSummaryParams;
    result: { success: boolean; message?: string; data?: any };
  };
  food_log_create: {
    params: FoodLogCreateParams;
    result: { success: boolean; message?: string; data?: any };
  };
  food_log_search: {
    params: FoodLogSearchParams;
    result: { success: boolean; message?: string; data?: any };
  };
  food_log_summary: {
    params: FoodLogSummaryParams;
    result: { success: boolean; message?: string; data?: any };
  };
  food_search_and_log: {
    params: FoodSearchAndLogParams;
    result: { success: boolean; message?: string; data?: any };
  };
  get_page_details: {
    params: GetPageDetailsParams;
    result: { success: boolean; message?: string; data?: any };
  };
  get_web_search_details: {
    params: GetWebSearchDetailsParams;
    result: { success: boolean; message?: string; data?: any };
  };
  knowledge_graph_search: {
    params: KnowledgeGraphSearchParams;
    result: { success: boolean; message?: string; data?: any };
  };
  memory_search: {
    params: MemorySearchParams;
    result: { success: boolean; message?: string; data?: any };
  };
  notes_create: {
    params: NotesCreateParams;
    result: { success: boolean; message?: string; data?: any };
  };
  notes_delete: {
    params: NotesDeleteParams;
    result: { success: boolean; message?: string; data?: any };
  };
  notes_edit: {
    params: NotesEditParams;
    result: { success: boolean; message?: string; data?: any };
  };
  notes_list: {
    params: NotesListParams;
    result: { success: boolean; message?: string; data?: any };
  };
  notes_search: {
    params: NotesSearchParams;
    result: { success: boolean; message?: string; data?: any };
  };
  open_page: {
    params: OpenPageParams;
    result: { success: boolean; message?: string; data?: any };
  };
  recovery_log_create: {
    params: RecoveryLogCreateParams;
    result: { success: boolean; message?: string; data?: any };
  };
  recovery_log_get: {
    params: RecoveryLogGetParams;
    result: { success: boolean; message?: string; data?: any };
  };
  recovery_log_recent: {
    params: RecoveryLogRecentParams;
    result: { success: boolean; message?: string; data?: any };
  };
  reminders_cancel: {
    params: RemindersCancelParams;
    result: { success: boolean; message?: string; data?: any };
  };
  reminders_create: {
    params: RemindersCreateParams;
    result: { success: boolean; message?: string; data?: any };
  };
  reminders_list: {
    params: RemindersListParams;
    result: { success: boolean; message?: string; data?: any };
  };
  start_shadow_session: {
    params: StartShadowSessionParams;
    result: { success: boolean; message?: string; data?: any };
  };
  template_get: {
    params: TemplateGetParams;
    result: { success: boolean; message?: string; data?: any };
  };
  template_list: {
    params: TemplateListParams;
    result: { success: boolean; message?: string; data?: any };
  };
  timers_cancel: {
    params: TimersCancelParams;
    result: { success: boolean; message?: string; data?: any };
  };
  timers_start: {
    params: TimersStartParams;
    result: { success: boolean; message?: string; data?: any };
  };
  timers_status: {
    params: TimersStatusParams;
    result: { success: boolean; message?: string; data?: any };
  };
  web_search: {
    params: WebSearchParams;
    result: { success: boolean; message?: string; data?: any };
  };
  workout_details: {
    params: WorkoutDetailsParams;
    result: { success: boolean; message?: string; data?: any };
  };
  workout_list: {
    params: WorkoutListParams;
    result: { success: boolean; message?: string; data?: any };
  };
  workout_log_create: {
    params: WorkoutLogCreateParams;
    result: { success: boolean; message?: string; data?: any };
  };
  workout_stats: {
    params: WorkoutStatsParams;
    result: { success: boolean; message?: string; data?: any };
  };
}