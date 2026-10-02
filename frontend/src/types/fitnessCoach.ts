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

// ── Check-ins ─────────────────────────────────────────────────────────────

export type NutritionStatus = 'unknown' | 'partial' | 'complete'

/**
 * How much of the readiness formula's input was actually present.
 *
 * `recovery_score.compute_readiness({})` returns 100/"Excellent". That is
 * correct arithmetic on no information, so an `unknown` coverage means the
 * score is absent entirely rather than optimistic.
 */
export type ReadinessCoverage = 'unknown' | 'partial' | 'full'

export interface ComputedReadiness {
  score: number
  label: string
  status: string
  color: string
  factors: string[]
  inputs_used: string[]
  inputs_missing: string[]
  coverage: ReadinessCoverage
}

export interface CheckIn {
  user_id: string
  log_date: string
  bedtime_at: string | null
  wake_at: string | null
  sleep_quality: number | null
  energy: number | null
  fatigue: number | null
  soreness_level: number | null
  stress: number | null
  motivation: number | null
  subjective_readiness: number | null
  notes: string | null
  nutrition_status: NutritionStatus
  nutrition_completed_at: string | null
  row_version: number
  /** {field: 'manual' | 'apple_health' | 'correction' | ...} */
  field_sources: Record<string, string>
  /** Resolved from health_metric, not stored on the daily row. */
  weight: Metric | null
  sleep_duration: Metric | null
  steps: Metric | null
  water: Metric | null
  hrv: Metric | null
  resting_heart_rate: Metric | null
  /** Absent — not zero, not 100 — when nothing eligible was recorded. */
  computed_readiness: ComputedReadiness | null
  readiness_coverage: ReadinessCoverage
}

/**
 * A partial daily update.
 *
 * An omitted key is left alone; an explicit `null` clears it. The
 * physiological four (`hrv`, `heart_rate`, `sleep_hours`, `body_weight`) are
 * accepted but are *not* check-in columns — the backend reroutes them to the
 * canonical observation store, so there is one answer to "what did I weigh".
 * Clearing one is refused: removing an observation is a correction.
 */
export interface CheckInPatch {
  hrv?: number
  heart_rate?: number
  sleep_hours?: number
  body_weight?: number
  bedtime_at?: string | null
  wake_at?: string | null
  sleep_quality?: number | null
  energy?: number | null
  fatigue?: number | null
  soreness_level?: number | null
  stress?: number | null
  motivation?: number | null
  subjective_readiness?: number | null
  notes?: string | null
  nutrition_status?: NutritionStatus
  expected_version?: number
}

// ── Measurements ──────────────────────────────────────────────────────────

export type Quantity = 'mass' | 'length' | 'time' | 'count' | 'volume' | 'rate' | 'score'
export type Side = 'left' | 'right' | 'none'

export interface MeasurementType {
  id: string
  code: string
  label: string
  quantity: Quantity
  canonical_unit: Unit
  allows_side: boolean
  allowed_sites: string[]
  /** What makes two readings comparable. Shown next to the input. */
  protocol_guidance: string | null
  /** null = a global seed; otherwise this athlete's private definition. */
  owner_user_id: string | null
  is_active: boolean
}

export interface MeasurementTypeInput {
  code: string
  label: string
  quantity: Quantity
  canonical_unit: Unit
  allows_side?: boolean
  allowed_sites?: string[]
  protocol_guidance?: string | null
}

export interface MeasurementPeriod {
  id: string
  user_id: string
  measured_on: string
  measured_at: string | null
  protocol: string | null
  notes: string | null
  photo_period_label: string | null
  created_at: string
}

export interface MeasurementPeriodInput {
  measured_on: string
  measured_at?: string | null
  protocol?: string | null
  notes?: string | null
  photo_period_label?: string | null
}

export interface Measurement {
  id: string
  user_id: string
  type_code: string
  label: string
  value: number
  unit: Unit
  canonical_value: number | null
  canonical_unit: Unit
  measured_at: string
  logical_date: string
  site: string | null
  side: Side
  period_id: string | null
  protocol: string | null
  source: string
  superseded_by_id: string | null
}

export interface MeasurementInput {
  type_code: string
  value: number
  unit: Unit
  measured_at: string
  site?: string | null
  side?: Side
  period_id?: string | null
  protocol?: string | null
  idempotency_key?: string | null
  corrects_observation_id?: string | null
}

// ── Fitness state (Step 17/18) ────────────────────────────────────────────

export type StateSection =
  | 'profile' | 'targets' | 'weight' | 'nutrition' | 'sleep' | 'recovery'
  | 'training' | 'performance' | 'measurements' | 'pain' | 'photos'
  | 'changes' | 'quality'

/**
 * `degraded` means a dependency failed — it is NOT a smaller state.
 *
 * The distinction is the whole point: fewer metrics because a query broke is
 * indistinguishable from the athlete having less data, and a reader would
 * then draw a conclusion from an absence nobody caused. A component showing
 * a degraded state has to say so rather than render empty charts.
 */
export type Freshness = 'fresh' | 'stale' | 'degraded'

export interface MetricGroup {
  section: StateSection
  metrics: Record<string, Metric>
  items: Array<Record<string, unknown>>
  limitations: string[]
}

export interface DataQuality {
  observed_weight_days: number | null
  expected_weight_days: number | null
  sleep_nights: number | null
  nutrition_complete_days: number
  nutrition_partial_days: number
  nutrition_unknown_days: number
  missing_fields: string[]
  unresolved_units: number
  unresolved_exercise_identities: number
  source_conflicts: number
  incomplete_workouts: number
  overdue_cadences: string[]
  stale_profile: boolean
  no_effective_target: boolean
  insufficient_comparable_exposures: string[]
  notes: string[]
}

export interface FitnessState {
  schema_version: number
  analytics_version: number
  user_id: string
  as_of: string
  athlete_local_date: string
  timezone: string
  period: Period | null
  freshness: Freshness
  data_revision: string | null
  profile: AthleteProfile | null
  goals: AthleteGoal[]
  limitations: AthleteLimitation[]
  targets: ResolvedTargets | null
  program: {
    program?: {
      id?: string | null
      name?: string | null
      goal?: string | null
      start_date?: string | null
      end_date?: string | null
    }
    phase?: {
      id?: string | null
      name?: string | null
      goal?: string | null
      start_date?: string | null
      /**
       * Reported as stored, which is INCLUSIVE. The backend's resolver
       * converts to half-open exactly once; exposing the converted value
       * here would make two surfaces show different block end dates.
       */
      end_date_inclusive?: string | null
      deload_week?: number | null
    }
    day_type?: string
  }
  sections: Partial<Record<StateSection, MetricGroup>>
  quality: DataQuality
  recent_changes: Array<Record<string, unknown>>
  evidence_refs: string[]
  degraded_dependencies: string[]
}

export interface PainItem {
  exercise: string
  exercise_library_id: string | null
  sessions_with_pain: number
  /** The denominator. A pattern from 2 of 20 sessions is not 2 of 2. */
  sessions_with_report: number
  sessions_total: number
  reporting_coverage: number | null
  max_severity: number | null
  locations: string[]
  sides: string[]
}

// ── Coach reviews and recommendations (Step 19-22) ────────────────────────

export type ReviewKind =
  | 'weekly' | 'biweekly' | 'monthly' | 'on_demand'
  | 'phase_transition' | 'photo_comparison'

export type ReviewStatus =
  | 'pending' | 'running' | 'complete' | 'failed' | 'insufficient_data'

/**
 * Why a review produced nothing. A CATEGORY, never a prompt — the backend
 * deliberately does not store the prompt or the transcript.
 */
export type ReviewFailureCategory =
  | 'model_unavailable' | 'model_timeout' | 'invalid_output'
  | 'schema_violation' | 'ungrounded_claim' | 'safety_refused'
  | 'state_unavailable' | 'insufficient_data' | 'internal_error'

export type RequestedBy = 'schedule' | 'user' | 'system'

export type RecommendationCategory =
  | 'maintain' | 'progress' | 'reduce' | 'exercise_change'
  | 'volume_change' | 'nutrition_change' | 'prioritize_recovery'
  | 'request_data' | 'flag_concern'

export type ConfidenceCategory = 'low' | 'moderate' | 'high'

export type ProposedChangeKind =
  | 'none' | 'target_revision' | 'data_request' | 'program_change'

/**
 * `proposed` is the initial state. `accepted` is constrained in the database
 * to require an action receipt or the target revision it produced, so a row
 * cannot claim an effect it did not have.
 */
export type DecisionStatus =
  | 'proposed' | 'accepted' | 'rejected' | 'expired' | 'superseded'

export interface ProposedChange {
  kind: ProposedChangeKind
  scope?: TargetScope | null
  effective_date?: string | null
  target_values?: TargetValues | null
  requested_metric?: string | null
  description?: string | null
}

export interface ReviewObservation {
  text: string
  metric_paths: string[]
}

export interface ReviewRecommendationOutput {
  category: RecommendationCategory
  headline: string
  rationale: string
  metric_paths: string[]
  evidence_refs: string[]
  confidence: ConfidenceCategory
  confidence_basis: string
  proposed_change: ProposedChange
}

export interface CoachReviewOutput {
  output_version: number
  summary: string
  coaching_priority: string
  observations: ReviewObservation[]
  limitations: string[]
  confidence: ConfidenceCategory
  confidence_basis: string
  recommendations: ReviewRecommendationOutput[]
}

export interface CoachReview {
  id: string
  user_id: string
  kind: ReviewKind
  period: Period
  status: ReviewStatus
  input_hash: string
  state_schema_version: number
  analytics_version: number
  data_revision: string | null
  collected_at: string
  source_cutoff: string | null
  model_requested: string | null
  /** The model that ACTUALLY answered, which may not be the one requested. */
  model_actual: string | null
  provider: string | null
  prompt_version: string
  prompt_hash: string | null
  output_schema_version: number | null
  summary: string | null
  evidence_refs: string[]
  error_category: ReviewFailureCategory | null
  error_detail: string | null
  run_id: string | null
  attempt: number
  revision: number
  supersedes_id: string | null
  superseded_by_id: string | null
  requested_by: RequestedBy
  evaluated_at: string | null
  created_at: string
}

export interface CoachRecommendation {
  id: string
  review_id: string
  user_id: string
  category: RecommendationCategory
  action: ProposedChangeKind
  title: string
  rationale: string
  confidence: ConfidenceCategory
  confidence_basis: string | null
  limitations: string | null
  metric_paths: string[]
  evidence_refs: string[]
  proposed_change: ProposedChange
  current_target_revision_id: string | null
  current_phase_id: string | null
  expires_at: string | null
  decision_status: DecisionStatus
  decided_at: string | null
  decided_by: string | null
  decision_note: string | null
  /** The proof an execution happened. Present on every accepted row. */
  action_receipt_id: string | null
  applied_revision_id: string | null
  priority: number
  created_at: string
}

export interface CoachReviewDetail extends CoachReview {
  input_state: FitnessState | null
  output: CoachReviewOutput | null
  recommendations: CoachRecommendation[]
}

export interface ReviewRequestInput {
  kind?: ReviewKind
  period_start?: string
  /** Exclusive, athlete-local. */
  period_end?: string
  /** Produce a linked revision when the data has changed since. */
  force?: boolean
}

export interface RecommendationFieldChange {
  field: string
  current: number | null
  proposed: number | null
  delta: number | null
  unit: string
  is_change: boolean
}

export interface RecommendationPreview {
  recommendation: CoachRecommendation
  /** Whether this path can perform the change at all. */
  applicable: boolean
  acceptable: boolean
  changes: RecommendationFieldChange[]
  scope: string | null
  effective_date: string | null
  proposed_against_revision_id: string | null
  latest_revision_id: string | null
  stale: boolean
  expired: boolean
  /** Shown BEFORE the Accept button, not discovered by pressing it. */
  blockers: string[]
  coverage: {
    observed_weight_days?: number | null
    expected_weight_days?: number | null
    nutrition_complete_days?: number | null
    sleep_nights?: number | null
    period_start?: string
    period_end?: string
  }
  limitations: string[]
}

export interface AcceptanceResult {
  recommendation: CoachRecommendation
  action_receipt_id: string
  applied_revision_id: string | null
  /** Rendered from the committed rows, not from the intent. */
  message: string
  duplicate: boolean
}

// ── Coaching cadence (Step 24) ────────────────────────────────────────────

export type CadenceKind =
  | 'daily_checkin' | 'weekly_review' | 'biweekly_review'
  | 'monthly_review' | 'tape_measurement' | 'progress_photo'

export interface CoachingCadence {
  kind: CadenceKind
  /** Is this cadence switched on. */
  enabled: boolean
  /**
   * May we contact you about it. Deliberately separate from `enabled`: a
   * cadence that computes and stores without delivering is a legitimate
   * state, and one switch would make a weigh-in nudge and a weekly model
   * call the same decision.
   */
  consented: boolean
  consented_at: string | null
  /** Athlete-local wall clock, "HH:MM". */
  local_time: string
  timezone: string
  /** ISO weekdays, 1 = Monday. */
  weekdays: number[]
  /** For 14/28-day cadences: an anchor plus a count, never a cron. */
  cadence_days: number | null
  anchor_date: string | null
  next_due_at: string | null
  /**
   * When the sweep last LOOKED. Separate from `last_completed_at` because a
   * green scheduled row proves a dispatch and nothing about the work.
   */
  last_evaluated_at: string | null
  last_completed_at: string | null
  snoozed_until: string | null
  version: number
}

export interface CadencePatchInput {
  enabled?: boolean
  consented?: boolean
  local_time?: string
  timezone?: string
  weekdays?: number[]
  cadence_days?: number
  anchor_date?: string
  expected_version?: number
}

export interface CoachingRun {
  id: string
  kind: CadenceKind
  occurrence_at: string
  status: 'claimed' | 'enqueued' | 'running' | 'completed' | 'failed' | 'noop'
  attempts: number
  review_id: string | null
  error_category: string | null
  /** Why nothing was delivered. A suppression is recorded, never silent. */
  noop_reason: string | null
  completed_at: string | null
}

// ── Progress photos (Step 26) ─────────────────────────────────────────────

export type PhotoView = 'front' | 'side' | 'back' | 'other'

export type PhotoCleanupState = 'pending_cleanup' | 'cleaned' | 'orphaned'

export interface ProgressPhoto {
  id: string
  original_filename: string | null
  mime_type: string | null
  file_size: number | null
  width: number | null
  height: number | null
  taken_at: string | null
  notes: string | null
  /**
   * Display context only. `bodyweight_observation_id` is the reference a
   * reader should trust — the backend never ingests this float as a body
   * measurement.
   */
  bodyweight: number | null
  bodyweight_unit: string | null
  critique: string | null
  critique_model: string | null
  critiqued_at: string | null
  has_critique: boolean
  created_at: string | null
  view: PhotoView | null
  period_id: string | null
  capture_protocol: string | null
  lighting: string | null
  distance_cm: number | null
  bodyweight_observation_id: string | null
  /** Explicit, and separate from having uploaded the photo. */
  consent_analysis: boolean
  analysis_status: string | null
}

export interface PhotoUploadInput {
  file: File
  view?: PhotoView
  periodId?: string
  notes?: string
  takenAt?: string
  capture_protocol?: string
  lighting?: string
  distanceCm?: number
}

export interface PhotoDeleteResult {
  id: string
  /** False when the stored bytes could not be removed yet. */
  deleted: boolean
  cleanup_state: PhotoCleanupState | null
  message: string
}

export interface PhotoComparability {
  comparable: boolean
  /** Why not — lighting, distance, or a mismatched view. */
  reason: string | null
  photos: string[]
}
