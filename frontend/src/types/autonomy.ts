/** Types for the Cortana Evolution autonomy system (Phases 0-3). */

export interface ActionTrace {
  id: string
  run_uuid: string | null
  run_id: number | null
  source: string
  action_name: string
  action_args: Record<string, any> | null
  risk_tier: number
  decision: string
  decision_reason: string | null
  simulation: Record<string, any> | null
  result: Record<string, any> | null
  success: boolean
  error_message: string | null
  step_index: number
  duration_ms: number | null
  created_at: string
}

export interface TraceStats {
  hours: number
  total: number
  succeeded: number
  failed: number
  runs: number
  unique_actions: number
  avg_duration_ms: number | null
  breakdown: {
    action_name: string
    source: string
    risk_tier: number
    count: number
    succeeded: number
    failed: number
  }[]
}

export interface AttentionItem {
  id: string
  title: string
  body: string | null
  category: string
  priority: 'low' | 'normal' | 'high' | 'urgent' | 'critical'
  source: string
  status: 'new' | 'sent' | 'read' | 'archived' | 'dropped'
  dedupe_key: string | null
  payload: Record<string, any> | null
  created_at: string
  updated_at: string
  read_at: string | null
  archived_at: string | null
}

export interface Mission {
  id: string
  title: string
  description: string | null
  source: string
  state: 'pending' | 'running' | 'awaiting_confirm' | 'done' | 'failed' | 'cancelled'
  priority: string
  total_steps: number
  completed_steps: number
  current_step_index: number
  requires_confirmation: boolean
  metadata: Record<string, any> | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  steps?: MissionStep[]
}

export interface MissionStep {
  id: string
  step_index: number
  action_name: string
  action_args: Record<string, any> | null
  description: string | null
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped'
  result: Record<string, any> | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
}

export interface PolicyCandidate {
  id: string
  title: string
  description: string | null
  candidate_type: 'standing_order' | 'automation'
  source: 'dream' | 'reflection'
  source_id: string | null
  status: 'new' | 'accepted' | 'rejected' | 'expired'
  confidence: number
  proposed_config: Record<string, any>
  created_at: string
  decided_at: string | null
  decided_action: string | null
  result_id: string | null
}
