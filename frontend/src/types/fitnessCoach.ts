/**
 * Fitness Coach API types.
 *
 * FITNESS_COACH_IMPLEMENTATION_PLAN Step 7 / §7. Mirrors
 * `backend/app/schemas/fitness_coach.py`.
 *
 * Two rules the types themselves enforce:
 *
 * 1. **A metric value is `number | null`, and the null carries a reason.**
 *    `Metric.value` being nullable is not defensive typing — it is the
 *    contract. Zero and unknown are different answers and the UI must render
 *    them differently, so there is no `value: number` anywhere here to make
 *    that easy to get wrong.
 * 2. **Frontend arithmetic is display-only.** Nothing here computes a trend,
 *    an average or an adherence figure; the backend owns every number and
 *    states its coverage. A component that wants a derived value asks for it.
 */

// ── Units and shared primitives ───────────────────────────────────────────

export type Unit =
  | 'kg' | 'lb' | 'cm' | 'in' | 'g' | 'kcal'
  | 'h' | 'min' | 's' | 'count' | 'ml' | 'bpm' | 'ms' | '%'
  | 'kg/week' | '%/week' | 'score'
  /** A legacy row whose unit was never recorded. Never a guess. */
  | 'unknown'

/** Why a metric has no value. Never collapsed into zero. */
export type UnavailableReason =
  | 'no_data'
  | 'insufficient_coverage'
  | 'no_target'
  | 'unknown_unit'
  | 'not_comparable'
  | 'dependency_failed'
  | 'not_applicable'

export type QualityFlag =
  | 'stale' | 'sparse' | 'outlier_present' | 'source_conflict'
  | 'backfilled' | 'estimate' | 'partial_day' | 'unresolved_identity'

/** Half-open athlete-local interval `[start, end)`. */
export interface Period {
  start: string  // YYYY-MM-DD
  end: string    // YYYY-MM-DD, exclusive
}

export interface Metric {
  key: string
  value: number | null
  unit: Unit
  period?: Period | null
  observed_days?: number | null
  expected_days?: number | null
  observed_at?: string | null
  source_count: number
  unavailable_reason?: UnavailableReason | null
  quality_flags: QualityFlag[]
  formula?: string | null
  analytics_version: number
  note?: string | null
}

// ── Athlete profile ───────────────────────────────────────────────────────

export type CalculationSex = 'male' | 'female' | 'unknown' | 'prefer_not_to_say'
export type TrainingLevel = 'unknown' | 'novice' | 'intermediate' | 'advanced'
export type CoachingStyle = 'unset' | 'direct' | 'supportive' | 'analytical'

export interface AthleteProfile {
  user_id: string
  height_cm: number | null
  date_of_birth: string | null
  calculation_sex: CalculationSex
  training_experience_years: number | null
  training_level: TrainingLevel
  timezone: string
  weight_unit: Unit
  length_unit: Unit
  available_days: string[]
  preferred_duration_minutes: number | null
  equipment: string[]
  preferred_exercise_ids: string[]
  excluded_exercise_ids: string[]
  dietary_restrictions: string[]
  dietary_preferences: string[]
  supplements: string[]
  coaching_style: CoachingStyle
  monitoring_consent: boolean
  row_version: number
  created_at: string | null
  updated_at: string | null
  /** Resolved from observations, never stored on the profile. */
  current_weight: Metric | null
}

/**
 * A PATCH body.
 *
 * An omitted key means "leave it alone"; an explicit `null` means "clear
 * it". That distinction is why this is a separate type from `AthleteProfile`
 * and why callers must build it by including only what changed — sending the
 * whole profile back would turn every untouched field into an assertion.
 */
export interface AthleteProfilePatch {
  height_cm?: number | null
  date_of_birth?: string | null
  calculation_sex?: CalculationSex
  training_experience_years?: number | null
  training_level?: TrainingLevel
  timezone?: string
  weight_unit?: Unit
  length_unit?: Unit
  available_days?: string[]
  preferred_duration_minutes?: number | null
  equipment?: string[]
  preferred_exercise_ids?: string[]
  excluded_exercise_ids?: string[]
  dietary_restrictions?: string[]
  dietary_preferences?: string[]
  supplements?: string[]
  coaching_style?: CoachingStyle
  monitoring_consent?: boolean
  /** Optimistic concurrency. A mismatch is a 409 carrying the current one. */
  expected_version?: number
}

// ── Goals ─────────────────────────────────────────────────────────────────

export type GoalKind =
  | 'hypertrophy' | 'strength' | 'powerbuilding'
  | 'gain' | 'cut' | 'recomp' | 'maintenance'

/** Which rate field the athlete actually chose. Not inferable afterwards. */
export type RateBasis = 'absolute' | 'percent' | 'none'

export interface AthleteGoalInput {
  kind: GoalKind
  is_primary: boolean
  priority: number
  rationale?: string | null
  target_weight_kg?: number | null
  rate_basis: RateBasis
  target_rate_kg_week?: number | null
  target_rate_percent_week?: number | null
  strength_targets: Record<string, number>
  valid_from: string
  valid_until?: string | null
  source?: string
}

export interface AthleteGoal extends AthleteGoalInput {
  id: string
  user_id: string
  recorded_at: string
  supersedes_id: string | null
  approved_at: string | null
}

// ── Limitations ───────────────────────────────────────────────────────────

export type LimitationStatus = 'active' | 'resolved' | 'superseded'
export type SeverityFlag = 'mild' | 'moderate' | 'severe'

export interface AthleteLimitationInput {
  area: string
  description?: string | null
  excluded_exercise_ids: string[]
  modified_exercise_ids: string[]
  severity_flag?: SeverityFlag | null
  effective_from: string
  effective_until?: string | null
  notes?: string | null
}

/** Deliberately has no diagnosis field: this is a report, not a finding. */
export interface AthleteLimitation extends AthleteLimitationInput {
  id: string
  user_id: string
  status: LimitationStatus
  created_at: string
}

// ── Targets ───────────────────────────────────────────────────────────────

export type TargetScope = 'phase' | 'default'
export type DayType = 'training' | 'rest' | 'unknown'

/** Where a resolved target actually came from. Always shown. */
export type TargetProvenance =
  | 'approved_revision'
  | 'legacy_phase'
  | 'legacy_default'
  | 'unknown'

export interface TargetValues {
  calories: number | null
  protein_g: number | null
  carbs_g: number | null
  fat_g: number | null
  sleep_hours: number | null
  water_ml: number | null
  steps: number | null
  calorie_tolerance_pct: number
  protein_tolerance_pct: number
}

export interface ResolvedTargets {
  user_id: string
  on_date: string
  day_type: DayType
  values: TargetValues
  provenance: TargetProvenance
  scope: TargetScope | null
  phase_id: string | null
  phase_name: string | null
  revision_id: string | null
  revision_version: number | null
  effective_from: string | null
  effective_until: string | null
  /**
   * True when this date precedes recorded target history. The current
   * values are NOT asserted to have applied then — showing them as if they
   * did would invent adherence data.
   */
  history_unknown: boolean
}

export interface TargetRevisionInput {
  scope: TargetScope
  phase_id?: string | null
  valid_from: string
  valid_until?: string | null
  training: Partial<TargetValues>
  rest?: Partial<TargetValues> | null
  source?: string
  review_recommendation_id?: string | null
  /** Refuses the write if the current revision has moved since. */
  expected_revision?: string | null
}

export interface TargetRevision {
  id: string
  user_id: string
  scope: TargetScope
  phase_id: string | null
  version: number
  valid_from: string
  valid_until: string | null
  training: TargetValues
  rest: TargetValues | null
  source: string
  review_recommendation_id: string | null
  approved_at: string | null
  approved_by: string | null
  created_at: string
}

// ── Errors ────────────────────────────────────────────────────────────────

export type FitnessErrorKind =
  | 'unauthenticated'   // 401
  | 'not_found'         // 404 — includes foreign ids, which never 403
  | 'conflict'          // 409
  | 'validation'        // 422
  | 'server'            // 5xx
  | 'network'

export interface FitnessApiError {
  kind: FitnessErrorKind
  /** Human wording, safe to render. Never a raw stack or SQL fragment. */
  message: string
  status?: number
  /** Present on a profile version conflict, so a client can reconcile. */
  currentVersion?: number
  /** Present on a target conflict, for the same reason. */
  currentRevisionId?: string
  /** Field-level messages from a 422, keyed by field path. */
  fieldErrors?: Record<string, string>
}
