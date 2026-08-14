/**
 * Sara cross-device workout wire contract — TypeScript mirror (plan §5).
 *
 * The same contract exists three times, once per runtime that has to speak it:
 * here, in `targets/watch/WorkoutWireModels.swift` (duplicated into
 * `modules/sara-workout-native/ios/`), and in
 * `backend/app/services/workout_command_service.py`. They cannot share code —
 * different languages, different processes, different devices — so
 * `__tests__/workoutWireParity.test.ts` reads all three and fails when the
 * field names drift.
 *
 * Nothing in here talks to the network or mutates state. It is types plus the
 * two pure helpers (envelope construction, staleness) that all three callers
 * would otherwise reimplement slightly differently.
 */

export const WORKOUT_SCHEMA_VERSION = 1;

export type OriginDevice = 'phone' | 'watch' | 'web' | 'server';

// ── Projection (§5.1) ─────────────────────────────────────────────────────

export interface LastSessionSummary {
  weights?: number[];
  reps?: number[];
  avg_rpe?: number;
}

export interface ProjectionExercise {
  name: string | null;
  variant: string | null;
  /**
   * Working sets this workout is actually asking for. Moves when David adds
   * or removes a set; `prescribed_sets` never does. Showing both is what makes
   * "4 sets (3 prescribed)" honest rather than a silent plan rewrite (§6.2).
   */
  target_sets: number | null;
  prescribed_sets?: number | null;
  /** Drop segments logged under this exercise. Volume, not completion (§4.4). */
  completed_drop_segments?: number | null;
  /** Free text like "8-10" — the backend owns rep ranges, not the client. */
  target_reps: string | null;
  target_rpe: number | null;
  /** What David has agreed to lift. This is what the UI prefills. */
  approved_weight: number | null;
  /** What Sara currently recommends. Never a target until approved (§6.8). */
  calculated_suggestion: number | null;
  completed_sets: number;
  last_session: LastSessionSummary | null;
  progression_note: string | null;
  notes?: string | null;
  metric_type?: string | null;
  is_per_side?: boolean | null;
  superset_group?: string | null;
  set_technique?: string | null;
  rest_seconds?: number | null;
}

export interface WorkoutProposal {
  proposal_id: string;
  session_id: string | null;
  kind: string;
  scope: Record<string, unknown> | null;
  current_value: Record<string, number | string | null> | null;
  proposed_value: Record<string, number | string | null> | null;
  reason: string | null;
  evidence?: Record<string, unknown> | null;
  status: 'pending' | 'approved' | 'rejected' | 'expired' | 'superseded';
  expires_at: string | null;
}

/**
 * One row of what actually happened, as opposed to what was planned.
 *
 * `set_kind` is the whole point: a template's `set_technique` says what Sara
 * asked for, this says what David did. Conflating them is why drop sets used
 * to read as regressions (§6.1).
 */
export interface PerformedSet {
  id: string;
  exercise: string;
  set_index: number;
  weight: number | null;
  reps: number | null;
  rpe: number | null;
  notes: string | null;
  is_pr: boolean;
  set_kind: 'working' | 'warmup' | 'drop';
  parent_set_id: string | null;
  /** Shared by a working set and every drop segment hanging off it. */
  set_group_id: string | null;
  /** 0 for the working set, 1..n for its drops, in performed order. */
  group_sequence: number;
  counts_toward_target: boolean;
  voided: boolean;
  void_reason: string | null;
  revised_from_set_id: string | null;
  logged_at: string | null;
}

export interface WorkoutProjection {
  schema_version: number;
  session_id: string;
  version: number;
  status: 'active' | 'paused' | 'completed' | 'abandoned';
  started_at: string | null;
  origin_device: OriginDevice | null;
  template: { id: string | null; name: string; is_deload: boolean };
  cursor: { exercise_index: number; set_index: number };
  progress: { completed_sets: number; total_sets: number; total_volume: number };
  current_exercise: ProjectionExercise | null;
  /**
   * Sets actually logged. The compact (Watch) form carries only the current
   * exercise's, which is all Undo and the "last set" line need.
   */
  performed_sets: PerformedSet[];
  /** Absent in the compact form sent to the Watch. */
  exercises?: ProjectionExercise[];
  rest: { active: boolean; started_at: string | null; duration_seconds: number | null };
  healthkit?: {
    state: string | null;
    workout_uuid: string | null;
    activity_type: string | null;
    started_at: string | null;
    ended_at: string | null;
  } | null;
  pending_proposal: WorkoutProposal | null;
  updated_at: string | null;
}

// ── Commands (§5.2) ───────────────────────────────────────────────────────

export type WorkoutCommandKind =
  | 'log_set'
  // Flexible sets (§6.3). A direct David tap applies immediately, and an
  // approved Sara proposal runs these exact same handlers, so there is no
  // second path where a recommendation could do more than it showed.
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
  | 'set_policy';

export interface WorkoutCommand {
  schema_version: number;
  /**
   * Minted before the first send and reused on every retry. This single field
   * is what makes a double-tapped Log Set over bad connectivity safe: the
   * backend replays the original result instead of logging a second set.
   */
  command_id: string;
  session_id: string | null;
  /** Stale-UI detector. A mismatch is a conflict, not an overwrite. */
  expected_version: number | null;
  origin_device: OriginDevice;
  kind: WorkoutCommandKind;
  created_at: string;
  payload: Record<string, unknown>;
}

export type CommandStatus = 'accepted' | 'replayed' | 'conflict' | 'rejected';

export interface CommandResult {
  status: CommandStatus;
  command_id?: string;
  projection?: WorkoutProjection | null;
  proposal?: WorkoutProposal | null;
  pr?: { is_pr: boolean; estimated_1rm?: number; previous_best?: number | null } | null;
  rest_seconds?: number;
  exercise_complete?: boolean;
  workout_complete?: boolean;
  logged?: {
    id: string;
    exercise: string;
    exercise_index: number;
    set_number: number;
    weight: number;
    reps: number;
    rpe: number | null;
  };
  [key: string]: unknown;
}

export type WorkoutConflictCode =
  | 'active_workout_conflict'
  | 'version_conflict'
  | 'session_mismatch'
  | 'no_active_session'
  | 'proposal_stale'
  /** The set an edit/undo named is gone — reconcile, don't retry. */
  | 'set_not_found'
  /** Nothing left to give back: every remaining target set is already logged. */
  | 'target_floor'
  /** A drop segment was sent with no working set to hang off. */
  | 'no_parent_set'
  /** Reclassifying into a drop needs an undo + re-log, not an edit. */
  | 'set_kind_change'
  | 'unsupported_schema_version';

export interface WorkoutConflictDetail {
  code: WorkoutConflictCode;
  message: string;
  projection?: WorkoutProjection | null;
}

// ── Coaching (§5.4) ───────────────────────────────────────────────────────

export interface CoachingEvent {
  event_id: string;
  session_id: string;
  after_version: number | null;
  kind: string;
  text: string;
  speak: boolean;
  priority: 'low' | 'normal' | 'high' | 'critical';
  expires_at: string | null;
  proposal_id: string | null;
}

export interface LiveMetrics {
  heart_rate: number | null;
  active_energy_kcal: number | null;
  elapsed_seconds: number | null;
  captured_at: string;
}

// ── Wire envelope (§5.3) ──────────────────────────────────────────────────

export const WATCH_TO_PHONE_KINDS = [
  'start_requested',
  'command_requested',
  'live_metrics',
  'healthkit_started',
  'healthkit_paused',
  'healthkit_resumed',
  'healthkit_finished',
  'watch_recovered_session',
  /**
   * Ask for the uncompacted projection. Per-set messages drop the exercise
   * list to keep the radio quiet; the Watch asks explicitly when it opens the
   * jump screen.
   */
  'projection_requested',
] as const;

export const PHONE_TO_WATCH_KINDS = [
  'start_accepted',
  'start_conflict',
  'command_accepted',
  'command_rejected',
  'projection_updated',
  'coaching_event',
  'proposal_created',
  'proposal_resolved',
  /** Durable terminal directive for a workout ended from the iPhone. */
  'workout_ended',
  'finish_confirmed',
  'catalog_updated',
] as const;

export type WireMessageKind =
  | (typeof WATCH_TO_PHONE_KINDS)[number]
  | (typeof PHONE_TO_WATCH_KINDS)[number];

export interface WireEnvelope {
  schema_version: number;
  message_id: string;
  session_id: string | null;
  kind: WireMessageKind | string;
  sent_at: string;
  payload: Record<string, any>;
}

// ── Standing policy (§6.9) ────────────────────────────────────────────────

export interface WorkoutPolicy {
  adaptive_rest_enabled: boolean;
  rest_range_seconds: [number, number];
  auto_start_rest_after_set: boolean;
  speak_routine_coaching: boolean;
  speak_prs: boolean;
  speak_proposals: boolean;
}

// ── Watch catalog (§7.5) ──────────────────────────────────────────────────

export interface WatchCatalog {
  schema_version: number;
  generated_at: string;
  generated_for_date: string;
  today_template_id: string | null;
  templates: Array<{
    id: string;
    name: string;
    exercise_count: number;
    exercises: Array<{ name: string; sets: number; reps: string }>;
  }>;
  active_projection: WorkoutProjection | null;
  policy: WorkoutPolicy;
}

// ── Helpers ───────────────────────────────────────────────────────────────

/**
 * `crypto.randomUUID` is not in the Hermes runtime, and pulling in a uuid
 * package for one call is not worth the bundle. These ids only need to be
 * unique per device, not cryptographically random — collisions across David's
 * two devices would have to hit the same millisecond AND the same random
 * suffix, and even then the backend's per-user command table catches it.
 */
export function newCommandId(): string {
  const rand = () => Math.random().toString(36).slice(2, 10);
  return `${Date.now().toString(36)}-${rand()}-${rand()}`;
}

export function buildCommand(
  kind: WorkoutCommandKind,
  opts: {
    sessionId?: string | null;
    expectedVersion?: number | null;
    originDevice?: OriginDevice;
    payload?: Record<string, unknown>;
    commandId?: string;
  } = {}
): WorkoutCommand {
  return {
    schema_version: WORKOUT_SCHEMA_VERSION,
    command_id: opts.commandId ?? newCommandId(),
    session_id: opts.sessionId ?? null,
    expected_version: opts.expectedVersion ?? null,
    origin_device: opts.originDevice ?? 'phone',
    kind,
    created_at: new Date().toISOString(),
    payload: opts.payload ?? {},
  };
}

export function buildEnvelope(
  kind: WireMessageKind,
  sessionId: string | null,
  payload: Record<string, unknown> = {}
): WireEnvelope {
  return {
    schema_version: WORKOUT_SCHEMA_VERSION,
    message_id: newCommandId(),
    session_id: sessionId,
    kind,
    sent_at: new Date().toISOString(),
    payload,
  };
}

/** Coaching about a set two sets ago is worse than silence (§10.4). */
export function isExpired(event: { expires_at: string | null }, now = Date.now()): boolean {
  if (!event.expires_at) return false;
  const at = Date.parse(event.expires_at);
  return Number.isFinite(at) && at < now;
}

/**
 * Whether an incoming projection should replace the one already held.
 *
 * Mirrored delivery is not ordered, so a v13 payload can land after v14. Taking
 * it would roll the exercise, the set count and the rest timer backwards
 * mid-workout.
 */
export function isNewerProjection(
  incoming: WorkoutProjection,
  current: WorkoutProjection | null
): boolean {
  if (!current) return true;
  if (incoming.session_id !== current.session_id) return true;
  return incoming.version >= current.version;
}

/**
 * The one line an approval screen shows.
 *
 * Every proposal has to be answerable from this sentence alone — on a wrist,
 * between sets. A proposal that renders as null is one David would be asked to
 * approve blind, so each kind gets an explicit phrasing rather than a fallback.
 */
export function describeProposal(proposal: WorkoutProposal): string | null {
  const current = proposal.current_value ?? {};
  const proposed = proposal.proposed_value ?? {};

  if (proposal.kind === 'add_working_set' || proposal.kind === 'reduce_current_target_sets') {
    const from = current.target_sets;
    const to = proposed.target_sets;
    if (typeof from === 'number' && typeof to === 'number') {
      return `${from} → ${to} sets`;
    }
    return proposal.kind === 'add_working_set' ? 'One more set' : 'One set fewer';
  }

  if (proposal.kind === 'template_set_count') {
    const from = current.sets;
    const to = proposed.sets;
    if (typeof from === 'number' && typeof to === 'number') {
      return `${from} → ${to} sets, every week`;
    }
    return 'Change the plan';
  }

  if (proposal.kind === 'perform_drop_set') {
    const weight = proposed.weight;
    return typeof weight === 'number' ? `Drop to ${weight} lb` : 'Add a drop set';
  }

  const from = current.weight;
  const to = proposed.weight;
  if (typeof from !== 'number' || typeof to !== 'number') return null;
  return `${from} → ${to} lb`;
}
