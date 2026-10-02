/**
 * The workout v2 wire contract, for the web.
 *
 * FITNESS_COACH_IMPLEMENTATION_PLAN Step 14. A **fifth** mirror of the
 * contract that already exists in `backend/app/services/
 * workout_command_service.py`, `ios-app/src/services/workoutContracts.ts`,
 * `targets/watch/WorkoutWireModels.swift` and the Swift copy duplicated into
 * `modules/sara-workout-native/ios/`.
 *
 * Why a separate file rather than importing the React Native one: the two
 * packages do not share a module graph or a bundler, and
 * `ios-app/scripts/check-workout-contract-parity.mjs` reads the copies as
 * text and fails when field names drift. That script is what keeps them
 * honest, and it now reads this file too — adding it immediately caught a
 * missing `set_plan_week` command kind. An import would have made the web
 * copy invisible to the check and let it diverge silently.
 *
 * Nothing here talks to the network or holds state. Types plus the two pure
 * helpers (envelope construction, staleness) that callers would otherwise
 * each reimplement slightly differently.
 */

export const WORKOUT_SCHEMA_VERSION = 2

export type OriginDevice = 'phone' | 'watch' | 'web' | 'server'

export interface LastSessionSummary {
  weights?: number[]
  reps?: number[]
  avg_rpe?: number
}

export interface ResolvedSetEntry {
  index: number
  kind: 'warmup' | 'top' | 'backoff'
  weight: number | null
  /** Free text like "2-4" or "4+". The backend owns rep ranges. */
  reps: string | null
  rpe_cap?: number | null
  rir?: string | null
}

export interface ProjectionExercise {
  name: string | null
  variant: string | null
  /**
   * Working sets this workout is actually asking for. Moves when a set is
   * added or removed; `prescribed_sets` never does. Showing both is what
   * makes "4 sets (3 prescribed)" honest rather than a silent plan rewrite.
   */
  target_sets: number | null
  prescribed_sets?: number | null
  completed_drop_segments?: number | null
  completed_warmup_sets?: number | null
  target_reps: string | null
  target_rpe: number | null
  /** What the athlete has agreed to lift. This is what prefills. */
  approved_weight: number | null
  /** What Sara currently recommends. Never a target until approved. */
  calculated_suggestion: number | null
  completed_sets: number
  last_session: LastSessionSummary | null
  progression_note: string | null
  notes?: string | null
  metric_type?: string | null
  is_per_side?: boolean | null
  superset_group?: string | null
  set_technique?: string | null
  rest_seconds?: number | null
  set_plan?: ResolvedSetEntry[] | null
  next_set?: ResolvedSetEntry | null
  effective_week?: number | null
  held?: boolean | null
  plan_note?: string | null
}

export interface WorkoutProposal {
  proposal_id: string
  session_id: string | null
  kind: string
  scope: Record<string, unknown> | null
  current_value: Record<string, number | string | null> | null
  proposed_value: Record<string, number | string | null> | null
  reason: string | null
  evidence?: Record<string, unknown> | null
  status: 'pending' | 'approved' | 'rejected' | 'expired' | 'superseded'
  expires_at: string | null
}

/**
 * What actually happened, as opposed to what was planned.
 *
 * `set_kind` is the point: a template's `set_technique` says what was asked
 * for, this says what was done. Conflating them is why drop sets used to
 * read as regressions.
 */
export interface PerformedSet {
  id: string
  exercise: string
  set_index: number
  weight: number | null
  reps: number | null
  rpe: number | null
  notes: string | null
  is_pr: boolean
  set_kind: 'working' | 'warmup' | 'drop'
  parent_set_id: string | null
  set_group_id: string | null
  group_sequence: number
  counts_toward_target: boolean
  voided: boolean
  void_reason: string | null
  revised_from_set_id: string | null
  logged_at: string | null
}

export interface WorkoutProjection {
  schema_version: number
  session_id: string
  version: number
  status: 'active' | 'paused' | 'completed' | 'abandoned'
  started_at: string | null
  origin_device: OriginDevice | null
  template: { id: string | null; name: string; is_deload: boolean }
  cursor: { exercise_index: number; set_index: number }
  progress: { completed_sets: number; total_sets: number; total_volume: number }
  current_exercise: ProjectionExercise | null
  performed_sets: PerformedSet[]
  exercises?: ProjectionExercise[]
  /**
   * Rest state from the SERVER's clock. The client computes a countdown for
   * display only — deriving the start time locally makes the timer disagree
   * between two devices watching the same set.
   */
  rest: { active: boolean; started_at: string | null; duration_seconds: number | null }
  healthkit?: {
    state: string | null
    workout_uuid: string | null
    activity_type: string | null
    started_at: string | null
    ended_at: string | null
  } | null
  pending_proposal: WorkoutProposal | null
  updated_at: string | null
}

export type WorkoutCommandKind =
  | 'log_set'
  | 'add_set'
  | 'remove_unlogged_set'
  | 'log_drop_segment'
  | 'revise_set'
  | 'void_set'
  | 'select_exercise'
  | 'set_variant'
  | 'skip_exercise'
  | 'rest_start'
  | 'rest_stop'
  | 'complete'
  | 'abandon'
  | 'approve_proposal'
  | 'reject_proposal'
  | 'healthkit_state'
  | 'set_policy'
  | 'set_plan_week'

export interface CommandEnvelope {
  schema_version: number
  /**
   * Minted **once per attempt**, before the first send, and reused byte for
   * byte on every retry. A new id on retry is how one set becomes two.
   */
  command_id: string
  session_id: string | null
  expected_version: number | null
  origin_device: OriginDevice
  kind: WorkoutCommandKind
  created_at: string
  payload: Record<string, unknown>
}

/** A conflict the server reports, with the state to reconcile from. */
export interface WorkoutConflictDetail {
  code: string
  message: string
  projection: WorkoutProjection | null
}

export type WorkoutErrorKind =
  /** 404 — the thing named is gone; reconcile it away. */
  | 'stale_reference'
  /** 409 — the state moved; refresh and let the athlete decide. */
  | 'conflict'
  | 'unauthenticated'
  | 'validation'
  | 'server'
  | 'network'

export interface WorkoutError {
  kind: WorkoutErrorKind
  message: string
  code?: string
  /** Present on a 409: the current state, so no blind retry is needed. */
  projection?: WorkoutProjection | null
  status?: number
}

/**
 * Build one command envelope.
 *
 * `commandId` is a parameter rather than generated here, deliberately: the
 * caller has to persist it *before* the first send so a retry can reuse it.
 * Generating it inside would make every retry a new command, and a dropped
 * acknowledgement would silently log the set twice.
 */
export function buildEnvelope(
  kind: WorkoutCommandKind,
  commandId: string,
  opts: {
    sessionId?: string | null
    expectedVersion?: number | null
    payload?: Record<string, unknown>
    originDevice?: OriginDevice
  } = {},
): CommandEnvelope {
  return {
    schema_version: WORKOUT_SCHEMA_VERSION,
    command_id: commandId,
    session_id: opts.sessionId ?? null,
    expected_version: opts.expectedVersion ?? null,
    origin_device: opts.originDevice ?? 'web',
    kind,
    created_at: new Date().toISOString(),
    payload: opts.payload ?? {},
  }
}

/**
 * Whether a held projection is behind the server's.
 *
 * Used to decide whether to prefill from the cached projection or wait for a
 * refresh — prefilling from a stale one shows the athlete a weight that has
 * already moved.
 */
export function isProjectionStale(
  held: WorkoutProjection | null | undefined,
  serverVersion: number | null | undefined,
): boolean {
  if (!held || serverVersion === null || serverVersion === undefined) return false
  return held.version < serverVersion
}

/** Remaining rest, from the server's start time. Display only. */
export function restRemainingSeconds(
  rest: WorkoutProjection['rest'],
  now: number = Date.now(),
): number | null {
  if (!rest.active || !rest.started_at || rest.duration_seconds === null) return null
  const started = Date.parse(rest.started_at)
  if (Number.isNaN(started)) return null
  const elapsed = (now - started) / 1000
  return Math.max(0, Math.round(rest.duration_seconds - elapsed))
}
