// Sara ambient status types

export interface SaraStatus {
  emotional_state: string
  latest_thought: string | null | Record<string, unknown>
  watching_for: string[] | string | null
  hours_since_last_chat: number | null
  pending_observations: number
}

export interface SaraSuggestedAction {
  label: string
  message: string
  icon?: string
}

export interface SaraBrief {
  activity_state: string
  interruptibility: number
  time_period: string // 'morning' | 'afternoon' | 'evening' | 'night'
  suggested_actions: SaraSuggestedAction[]
  sara_status: {
    emotional_state?: string
    latest_thought?: string | null
    watching_for?: string[] | string | null
  }
  brief_sections?: Array<{
    type: string
    data: Record<string, unknown>
  }>
}

export interface AttentionItem {
  id: string
  title: string
  body: string
  category: string
  priority: 'critical' | 'urgent' | 'high' | 'normal' | 'low'
  source: string
  status: 'new' | 'sent' | 'read' | 'archived'
  created_at: string
  updated_at?: string
}

export interface AttentionCount {
  count: number
}
