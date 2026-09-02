// Content Card Types for rich inline rendering

export interface CardAction {
  label: string;
  action?: 'navigate' | 'message';
  target?: string;  // Screen name for navigation
  message?: string; // Pre-formed message to send to Sara
  params?: Record<string, any>;
  icon?: string;
}

export interface ContentCard {
  card_type: string;
  title?: string;
  items?: any[];
  summary?: string;
  summary_data?: Record<string, number>;
  actions?: CardAction[];
}

export interface SuggestedAction {
  label: string;
  message?: string;
  action?: 'navigate';
  target?: string;
  icon?: string;
}

export interface ToolStatus {
  tool: string;
  status: 'executing' | 'completed';
}

export type AssistantActivityPhase =
  | 'thinking'
  | 'tool_running'
  | 'tool_complete'
  | 'synthesizing'
  | 'responding';

export interface AssistantActivity {
  phase: AssistantActivityPhase;
  tool?: string;
  round?: number;
}

// Calendar card items
export interface CalendarCardItem {
  id?: number;
  title: string;
  start_time: string;
  end_time: string;
  location?: string;
  all_day?: boolean;
}

// Reminder card items
export interface ReminderCardItem {
  id?: number;
  title: string;
  due_at: string;
  completed: boolean;
}

// Timer card items
export interface TimerCardItem {
  id: string;
  title: string;
  duration_seconds: number;
  remaining_seconds: number;
}

// Note card items
export interface NoteCardItem {
  id?: number;
  title: string;
  preview: string;
  folder?: string;
  updated_at?: string;
}

// Email card items
export interface EmailCardItem {
  id?: string;
  sender: string;
  subject: string;
  snippet: string;
  timestamp: string;
  is_read: boolean;
}

// Home card items
export interface HomeCardItem {
  id: string;
  name: string;
  state: string;
  domain: string;
}

// Sara brief response
export interface SaraBriefResponse {
  greeting: string;
  time_period: string;
  activity_state: string;
  interruptibility: number;
  brief_sections: BriefSection[];
  suggested_actions: SuggestedAction[];
  sara_status: {
    emotional_state: string;
    latest_thought: string | null;
    watching_for: string | null;
  };
}

export interface BriefSection {
  type: 'weather' | 'calendar' | 'fitness' | 'threads' | 'learning';
  data: any;
}
